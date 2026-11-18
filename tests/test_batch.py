from pathlib import Path

from torrentlinker.batch import run_batch
from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
from torrentlinker.library import LibraryEntry

FOLDER = LibraryFolder(Path("/lib"))


def entry(name: str, state: ItemState = ItemState.ORPHAN) -> LibraryEntry:
    return LibraryEntry(FOLDER, LocalItem(Path("/lib") / name), state)


def test_batch_searches_each_orphan_and_reports_progress() -> None:
    entries = [entry("a"), entry("b", ItemState.PARTIALLY_SEEDED), entry("c")]
    progress: list[tuple[int, int, str]] = []

    done = run_batch(
        entries,
        search=lambda e: [e.item.path.name.upper()],
        on_searched=lambda i, n, e, r: progress.append((i, n, r[0])),
        cancelled=lambda: False,
    )

    assert done == 2
    assert progress == [(1, 2, "A"), (2, 2, "C")]


def test_cancelling_stops_before_the_next_item() -> None:
    searched: list[str] = []
    entries = [entry("a"), entry("b"), entry("c")]

    done = run_batch(
        entries,
        search=lambda e: searched.append(e.item.path.name) or [],
        on_searched=lambda *_: None,
        cancelled=lambda: len(searched) >= 1,
    )

    assert searched == ["a"]
    assert done == 1


def test_a_failing_item_is_reported_and_the_batch_goes_on() -> None:
    errors: list[str] = []

    def search(e: LibraryEntry) -> list[str]:
        if e.item.path.name == "a":
            raise RuntimeError("boom")
        return ["ok"]

    done = run_batch(
        [entry("a"), entry("b")],
        search=search,
        on_searched=lambda *_: None,
        cancelled=lambda: False,
        on_error=lambda e, err: errors.append(f"{e.item.path.name}: {err}"),
    )

    assert done == 2
    assert errors == ["a: boom"]


def test_a_rate_limit_pauses_the_batch_and_retries_the_same_item() -> None:
    from torrentlinker.indexer import RateLimited

    calls: list[str] = []
    waits: list[tuple[str, float]] = []
    paused: list[float] = []

    def search(e: LibraryEntry) -> list[str]:
        calls.append(e.item.path.name)
        if calls.count("b") == 1 and e.item.path.name == "b":
            raise RateLimited(120)
        return ["ok"]

    errors: list[str] = []
    done = run_batch(
        [entry("a"), entry("b"), entry("c")],
        search=search,
        on_searched=lambda *_: None,
        cancelled=lambda: False,
        on_error=lambda e, err: errors.append(e.item.path.name),
        on_wait=lambda e, seconds: waits.append((e.item.path.name, seconds)),
        wait=lambda seconds, cancelled: paused.append(seconds) or True,
    )

    assert calls == ["a", "b", "b", "c"]
    assert waits == [("b", 120)] and paused == [120]
    assert errors == [] and done == 3


def test_cancelling_during_a_rate_limit_wait_stops_the_batch() -> None:
    from torrentlinker.indexer import RateLimited

    def search(e: LibraryEntry) -> list[str]:
        raise RateLimited(600)

    done = run_batch(
        [entry("a"), entry("b")],
        search=search,
        on_searched=lambda *_: None,
        cancelled=lambda: False,
        wait=lambda seconds, cancelled: False,  # the user cancelled while waiting
    )

    assert done == 0


def test_a_persistent_rate_limit_ends_as_an_error_for_that_item() -> None:
    from torrentlinker.batch import MAX_WAITS
    from torrentlinker.indexer import RateLimited

    calls: list[str] = []
    errors: list[str] = []

    def search(e: LibraryEntry) -> list[str]:
        calls.append(e.item.path.name)
        if e.item.path.name == "a":
            raise RateLimited(30)
        return ["ok"]

    done = run_batch(
        [entry("a"), entry("b")],
        search=search,
        on_searched=lambda *_: None,
        cancelled=lambda: False,
        on_error=lambda e, err: errors.append(e.item.path.name),
        wait=lambda seconds, cancelled: True,
    )

    assert calls.count("a") == MAX_WAITS + 1 and calls[-1] == "b"
    assert errors == ["a"] and done == 2


def test_pause_waits_and_stops_early_when_cancelled() -> None:
    from torrentlinker.batch import pause

    assert pause(0.05, lambda: False) is True
    assert pause(600, lambda: True) is False  # returns at once, without waiting


def test_each_item_is_announced_before_its_search_even_when_it_fails() -> None:
    started: list[tuple[int, int, str]] = []
    failed: list[str] = []

    def search(e: LibraryEntry) -> list[str]:
        if e.item.path.name == "a":
            raise RuntimeError("down")
        return []

    run_batch(
        [entry("a"), entry("b")],
        search=search,
        on_searched=lambda i, n, e, r: None,
        cancelled=lambda: False,
        on_error=lambda e, err: failed.append(e.item.path.name),
        on_start=lambda i, n, e: started.append((i, n, e.item.path.name)),
    )

    assert started == [(1, 2, "a"), (2, 2, "b")] and failed == ["a"]
