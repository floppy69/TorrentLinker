"""The Library: every Local Item of every Library Folder, with its state."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Literal, TypeVar

import httpx
import requests

from torrentlinker.deluge import DelugeError
from torrentlinker.domain import ItemState, LibraryFolder, LocalItem, Torrent
from torrentlinker.item_detection import seeded_roots
from torrentlinker.matching import IgnoreList
from torrentlinker.qbit import Qbit
from torrentlinker.read_pacing import ReadPacing
from torrentlinker.reconcile import classify
from torrentlinker.scan import ScanError, scan
from torrentlinker.seeding import indexer_torrents
from torrentlinker.store import Store


class LibraryReadTimeout(TimeoutError):
    """A scan timed out, with enough context to distinguish client reads from disk I/O."""

    def __init__(self, operation: Literal["torrents", "files", "folder"], target: str = ""):
        self.operation = operation
        self.target = target
        message = {
            "torrents": (
                "The Torrent Client timed out while reading its torrent list after two attempts."
            ),
            "files": (
                f"The Torrent Client timed out while reading the files of {target} "
                "after two attempts."
            ),
            "folder": f"Reading the Library Folder timed out: {target}",
        }[operation]
        super().__init__(message)


T = TypeVar("T")


def _timed_out(error: BaseException) -> bool:
    # qBittorrent wraps requests timeouts in APIConnectionError; retain the cause.
    seen: set[int] = set()
    while id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, TimeoutError | httpx.TimeoutException | requests.Timeout):
            return True
        # A timeout inside Deluge's daemon can arrive as a JSON-RPC error instead.
        if isinstance(error, DelugeError) and str(error).strip().casefold() == "timed out":
            return True
        nested = error.__cause__ or error.__context__
        if nested is None:
            break
        error = nested
    return False


log = logging.getLogger(__name__)


def _client_read(
    read: Callable[[], T], operation: Literal["torrents", "files"], target: str = ""
) -> T:
    """Retry a timed-out read once. Never retry commands or accept incomplete contents."""
    try:
        return read()
    except Exception as error:
        if not _timed_out(error):
            raise
    try:
        return read()
    except Exception as error:
        if not _timed_out(error):
            raise
        raise LibraryReadTimeout(operation, target) from error


@dataclass(frozen=True)
class LibraryEntry:
    folder: LibraryFolder
    item: LocalItem
    state: ItemState
    torrent_hashes: frozenset[str] = frozenset()


class LibraryResult(list[LibraryEntry]):
    """Current entries and failures, retaining previous unavailable entries."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[ScanError] = []
        self.client_error: Exception | None = None


def build_library(
    folders: Iterable[LibraryFolder],
    torrents: list[Torrent] | None,
    ignore: IgnoreList = IgnoreList(),
    cache: Store | None = None,
    refresh: bool = False,
    previous: Iterable[LibraryEntry] = (),
) -> LibraryResult:
    file_hashes: dict[Path, set[str]] = {}
    for torrent in torrents or []:
        for rel in torrent.files:
            file_hashes.setdefault(torrent.save_path / rel, set()).add(torrent.hash.lower())
    entries = LibraryResult()
    previous = list(previous)
    folders = list(folders)
    automatic = any(folder.depth is None for folder in folders)
    roots = seeded_roots(torrents or []) if automatic else frozenset()
    sizes = cache.catalogue_sizes() if automatic and cache else frozenset()
    for folder in folders:
        items = scan(folder, cache, refresh, seeded_roots=roots, catalogue_sizes=sizes)
        entries.errors.extend(items.errors)
        entries.extend(
            entry
            for entry in previous
            if entry.folder == folder
            and any(
                entry.item.path == error.path
                or error.path in entry.item.path.parents
                or entry.item.path in error.path.parents
                for error in items.errors
            )
        )
        states = (
            classify(items, torrents, ignore)
            if torrents is not None
            else {item.path: ItemState.UNKNOWN for item in items}
        )
        for item in items:
            content = [rel for rel in item.files if not ignore.matches(rel)] or list(item.files)
            hashes = frozenset(
                hash for rel in content for hash in file_hashes.get(item.save_path / rel, ())
            )
            entries.append(LibraryEntry(folder, item, states[item.path], hashes))
    if torrents is None:
        entries[:] = [replace(entry, state=ItemState.UNKNOWN) for entry in entries]
    return entries


def known_files(client: Qbit, store: Store, infohash: str) -> dict[str, int]:
    """A torrent's file list, from an earlier read when there was one. For reads that
    only look (probes, scans); never for checking renames, which must ask the client."""
    if (files := store.torrent_files([infohash]).get(infohash.lower())) is not None:
        return files
    files = client.files(infohash)
    store.cache_torrent_files({infohash: files})
    return files


def indexer_contents(
    client: Qbit,
    store: Store,
    indexer_url: str,
    *,
    refresh: bool = False,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    stop: threading.Event | None = None,
    progress: Callable[[int, int, float], None] = lambda done, total, rate: None,
) -> list[Torrent]:
    """The Indexer's torrents in the Torrent Client, with their files.

    Only they make a Local Item Seeded: a file seeded for another tracker stays an Orphan,
    to be searched and cross-seeded. Files are read for these torrents alone, one request
    each, which spares thousands of requests when the client seeds for other trackers.

    File lists read before are reused (`refresh` reads them all again). The client
    file requests are paced from measured response times: at most five per second,
    targeting 20% time spent answering this scan. Slow responses reduce the rate
    immediately; recovery is gradual. This measures API latency, not disk throughput.
    Lists are saved as they come, so an interrupted scan keeps what it read.
    """
    if stop is not None and stop.is_set():
        raise InterruptedError("Client file-list scan cancelled.")
    listed = _client_read(lambda: client.torrents(with_files=False), "torrents")
    known = store.known_hashes([t.hash.lower() for t in listed])
    torrents = indexer_torrents(listed, indexer_url, known)
    cached = {} if refresh else store.torrent_files([t.hash for t in torrents])
    result, fresh = [], {}
    pacing = ReadPacing()
    try:
        for done, t in enumerate(torrents, 1):
            if stop is not None and stop.is_set():
                raise InterruptedError("Client file-list scan cancelled.")
            files = cached.get(t.hash.lower())
            if files is None:
                started = clock()
                files = _client_read(partial(client.files, t.hash), "files", t.name)
                elapsed = max(0.0, clock() - started)
                pause = pacing.observe(elapsed)
                fresh[t.hash] = files
                progress(done, len(torrents), pacing.rate)
                if stop is not None:
                    if stop.wait(pause):
                        raise InterruptedError("Client file-list scan cancelled.")
                else:
                    sleep(pause)
                if len(fresh) >= 200:
                    store.cache_torrent_files(fresh)
                    fresh = {}
            result.append(replace(t, files=files))
    finally:
        store.cache_torrent_files(fresh)
        if pacing.samples:
            log.info(
                "Client file-list scan: %d reads, %.3fs mean response, %.2f requests/s target",
                pacing.samples,
                pacing.total / pacing.samples,
                pacing.rate,
            )
    # Linked reseeds use a persistent layout elsewhere. Classification must still
    # associate verified sharing with the original Local Item, across restarts.
    from torrentlinker.reseed_links import validate_links

    linked = {r.get("hash"): (path, r) for path, r in store.reseed_records().items()}
    for i, torrent in enumerate(result):
        if torrent.hash not in linked:
            continue
        path, record = linked[torrent.hash]
        if (
            "torrentlinker:links" not in torrent.tags
            or record.get("status") not in {"verified", "seeding"}
            or str(torrent.save_path) != record.get("destination")
            or torrent.progress < 1
        ):
            continue
        try:
            validate_links(record)
        except (ValueError, OSError):
            continue
        base = Path(path).parent
        result[i] = replace(
            torrent,
            save_path=base,
            files={
                str(Path(f["source"]).relative_to(base)).replace("\\", "/"): f["identity"][2]
                for f in record["files"]
            },
        )
    return result


def auto_searchable(entries: Iterable[LibraryEntry]) -> list[LibraryEntry]:
    """Entries a batch search may pick up: Orphans only, never (Partially) Seeded Items.

    An episode is skipped when its pack is in the same batch, searched or already
    seeded: one search per pack, not one per episode. Selecting episodes without their
    pack searches them, to cross-seed them as single episodes."""
    entries = list(entries)
    packs = {e.item.path for e in entries}
    return [e for e in entries if e.state is ItemState.ORPHAN and e.item.within not in packs]


def pack_episodes(entries: Iterable[LibraryEntry]) -> list[LibraryEntry]:
    """The Orphan episodes `auto_searchable` leaves to their pack's search. A batch still
    checks them against the Catalogue and cached torrents, which costs no search: a
    torrent of that single episode can be reseeded beside the pack's."""
    entries = list(entries)
    packs = {e.item.path for e in entries}
    return [e for e in entries if e.state is ItemState.ORPHAN and e.item.within in packs]
