"""Poster thumbnails for the Search results: fetched from TMDB only, bounded, kept on disk."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

import httpx

from torrentlinker import net

ALLOWED_HOSTS = frozenset({"image.tmdb.org"})
MAX_BYTES = 600_000  # a w500 poster is far smaller; this only stops a runaway response
MAX_FILES = 600
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


def valid_poster_url(url: str) -> bool:
    """Only plain https TMDB image URLs. Search rows carry untrusted text, so nothing else
    (other hosts, ports, credentials, redirects) is ever requested."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname in ALLOWED_HOSTS
        and port is None
        and not parts.username
        and parts.path.startswith("/t/p/")
        and ".." not in parts.path
    )


class PosterCache:
    """No Indexer key, cookie or other header is sent with a poster request."""

    def __init__(
        self,
        folder: Path,
        http: Callable[[], httpx.Client] | None = None,
        max_files: int = MAX_FILES,
    ) -> None:
        self.folder = folder
        self.max_files = max_files
        self._http = http or (lambda: net.client(timeout=10, follow_redirects=False))
        self._lock = threading.Lock()

    def path(self, url: str) -> Path:
        return self.folder / (hashlib.sha256(url.encode()).hexdigest()[:40] + ".img")

    def cached(self, url: str) -> bytes | None:
        try:
            return self.path(url).read_bytes() if valid_poster_url(url) else None
        except OSError:
            return None

    def fetch(self, url: str) -> bytes | None:
        """The image bytes from disk or the network; None when there is no usable poster."""
        if not valid_poster_url(url):
            return None
        if (data := self.cached(url)) is not None:
            return data
        try:
            with self._http() as client, client.stream("GET", url) as response:
                kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if response.status_code != 200 or kind not in IMAGE_TYPES:
                    return None
                data = b""
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) > MAX_BYTES:
                        return None
        except (httpx.HTTPError, OSError):
            return None
        self._store(url, data)
        return data

    def _store(self, url: str, data: bytes) -> None:
        with self._lock:
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                target = self.path(url)
                temp = target.with_suffix(".part")
                temp.write_bytes(data)
                temp.replace(target)
                files = sorted(self.folder.glob("*.img"), key=lambda p: p.stat().st_mtime)
                for old in files[: max(0, len(files) - self.max_files)]:
                    old.unlink(missing_ok=True)
            except OSError:
                pass  # a full or read-only disk only costs the cache


_cache_lock = threading.Lock()
_cache_owners: WeakValueDictionary[Path, PosterCache] = WeakValueDictionary()


def shared_poster_cache(folder: Path) -> PosterCache:
    """One writer per cache directory across Search, details and client profiles."""
    folder = folder.resolve()
    with _cache_lock:
        cache = _cache_owners.get(folder)
        if cache is None:
            cache = PosterCache(folder)
            _cache_owners[folder] = cache
        return cache
