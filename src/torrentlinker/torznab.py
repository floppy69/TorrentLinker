"""A Torznab Indexer other than c411: its own key, caps and pacer (ADR-0024).

c411 keeps `indexer.Indexer`, with its hourly budget and key slots. These Indexers have
no budget of ours; each obeys its own rate limit and `Retry-After`.
"""

from __future__ import annotations

import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import httpx

from torrentlinker import net
from torrentlinker.indexer import (
    FOREGROUND_PATIENCE,
    MAX_RETRIES,
    Candidate,
    Caps,
    KeyRefused,
    RateLimited,
    SearchMode,
    SearchQuery,
    _parse_items,
    parse_caps,
)
from torrentlinker.ratelimit import Pacer, cancellable_sleep

DEFAULT_RETRY_AFTER = 30.0


class IndexerKeyRefused(KeyRefused):
    """An Indexer other than c411 refused its API key."""

    def __init__(self, name: str, status: int) -> None:
        Exception.__init__(
            self,
            f"{name or 'The Indexer'} refused the API key (HTTP {status}): check it in Settings",
        )
        self.status = status
        self.key_number = 1
        self.scope = ""


def retry_after(response: httpx.Response) -> float:
    """Seconds a 429 asks to wait: `Retry-After` as a number or an HTTP date."""
    value = response.headers.get("Retry-After", "").strip()
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
        return max((when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp() - time.time(), 0)
    except (TypeError, ValueError, IndexError):
        return DEFAULT_RETRY_AFTER


class TorznabIndexer:
    def __init__(
        self,
        url: str,
        api_key: str,
        name: str = "",
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.url, self.api_key, self.name = url, api_key, name
        self._http = http or net.client(timeout=30, follow_redirects=True)
        self._sleep = sleep
        self.pacer = Pacer(clock, sleep)
        self._caps_lock = threading.Lock()
        self._modes: dict[SearchMode, set[str]] | None = None
        self._thread = threading.local()

    def background(self, stop: threading.Event | None = None):
        """Searches of a job may wait out a rate limit; cancellation interrupts the wait."""
        return _Context(self._thread, True, stop)

    def caps(self) -> Caps:
        return parse_caps(self._get({"t": "caps"}))

    def supported_modes(self) -> dict[SearchMode, set[str]] | None:
        with self._caps_lock:
            if self._modes is None:
                try:
                    self._modes = self.caps().modes
                except (httpx.HTTPError, KeyRefused, ET.ParseError, RateLimited):
                    return None
            return self._modes

    def search(self, query: SearchQuery) -> list[Candidate]:
        return _parse_items(self._get(query.params()))

    def fetch_torrent(self, candidate: Candidate, *, retry: bool = True) -> bytes:
        """The Candidate's .torrent, through the same pacer as its searches."""
        url = candidate.download_url
        if "apikey=" not in url:
            url += ("&" if "?" in url else "?") + urlencode({"apikey": self.api_key})
        data = self._send(url, None).content
        if not data.startswith(b"d"):
            raise ValueError(f"{self.name or 'The Indexer'} did not return a .torrent file")
        return data

    def cached_torrent(self, candidate: Candidate) -> bytes | None:
        return None

    def keep_torrent(self, candidate: Candidate, data: bytes) -> None:
        pass

    def next_request_in(self) -> float:
        return self.pacer.next_in()

    def redact(self, text: str) -> str:
        return text.replace(self.api_key, "[secret]") if self.api_key else text

    def unredact(self, text: str) -> str:
        return text.replace("[secret]", self.api_key) if self.api_key else text

    @property
    def is_c411(self) -> bool:
        return False

    def _get(self, params: dict[str, str]) -> str:
        return self._send(self.url, params).text

    def _send(self, url: str, params: dict[str, str] | None) -> httpx.Response:
        background = getattr(self._thread, "background", False)
        stop = getattr(self._thread, "stop", None)
        waits = 0
        while True:
            wait = self.pacer.next_in()
            if not background and wait > FOREGROUND_PATIENCE:
                raise RateLimited(wait)
            with self.pacer.turn(background, stop):
                response = self._http.get(
                    url, params={**params, "apikey": self.api_key} if params is not None else None
                )
                self.pacer.observe(response.headers)
            if response.status_code == 429:
                wait = retry_after(response)
                self.pacer.rest(wait)
                self.pacer.adopt_refusal(response.headers)
                if not background and wait > FOREGROUND_PATIENCE or waits >= MAX_RETRIES:
                    raise RateLimited(wait)
                waits += 1
                cancellable_sleep(wait, stop, self._sleep)
                continue
            if response.status_code in (401, 403):
                raise IndexerKeyRefused(self.name, response.status_code)
            try:
                return response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise httpx.HTTPStatusError(
                    self.redact(str(e)), request=e.request, response=e.response
                ) from None


class _Context:
    def __init__(self, local: threading.local, background: bool, stop: threading.Event | None):
        self.local, self.background, self.stop = local, background, stop

    def __enter__(self) -> None:
        self.before = (getattr(self.local, "background", False), getattr(self.local, "stop", None))
        self.local.background, self.local.stop = self.background, self.stop

    def __exit__(self, *exc: object) -> None:
        self.local.background, self.local.stop = self.before
