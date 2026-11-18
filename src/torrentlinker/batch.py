"""Batch search: search many Orphans one after the other."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import TypeVar

from torrentlinker.indexer import RateLimited
from torrentlinker.library import LibraryEntry, auto_searchable

R = TypeVar("R")
MAX_WAITS = 6  # c411 waits per item before the item is reported as failed


def pause(
    seconds: float, cancelled: Callable[[], bool], sleep: Callable[[float], None] = time.sleep
) -> bool:
    """Wait in short steps; False as soon as the batch is cancelled."""
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        if cancelled():
            return False
        sleep(min(1.0, left))
    return not cancelled()


def run_batch(
    entries: Iterable[LibraryEntry],
    search: Callable[[LibraryEntry], list[R]],
    on_searched: Callable[[int, int, LibraryEntry, list[R]], None],
    cancelled: Callable[[], bool],
    on_error: Callable[[LibraryEntry, Exception], None] = lambda e, err: None,
    *,
    orphans_only: bool = True,
    on_wait: Callable[[LibraryEntry, float], None] = lambda e, seconds: None,
    wait: Callable[[float, Callable[[], bool]], bool] = pause,
    on_start: Callable[[int, int, LibraryEntry], None] = lambda i, n, e: None,
) -> int:
    """Search every Orphan among `entries`; return how many were processed.

    When c411 asks to wait (RateLimited), the batch waits as long as it asks, then
    searches the same item again, instead of failing every item that follows."""
    queue = auto_searchable(entries) if orphans_only else list(entries)
    done = 0
    for i, entry in enumerate(queue, 1):
        if cancelled():
            break
        on_start(i, len(queue), entry)
        waits = 0
        while True:
            try:
                found = search(entry)
            except RateLimited as err:
                if waits < MAX_WAITS:
                    waits += 1
                    on_wait(entry, err.retry_after)
                    if wait(err.retry_after, cancelled):
                        continue
                    return done  # cancelled while waiting
                on_error(entry, err)
            except Exception as err:  # noqa: BLE001 - one bad item must not stop the batch
                on_error(entry, err)
            else:
                on_searched(i, len(queue), entry, found)
            break
        done += 1
    return done
