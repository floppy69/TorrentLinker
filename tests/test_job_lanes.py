"""Interactive reads do not wait behind batches; mutations remain serialized."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from torrentlinker.domain import ContentKind, ItemState, LibraryFolder
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.job_lanes import job_lane
from torrentlinker.library import LibraryEntry
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.web.jobs import Jobs
from torrentlinker.web.operations import JobRequest, Operations


def finished(jobs, identifier):
    for _ in range(500):
        result = jobs.get(identifier)
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.01)
    raise AssertionError(result)


def test_one_item_check_finishes_during_batch_and_uses_foreground(tmp_path):
    from tests.test_reseed_workspace import workspace

    board, _, original, _, _ = workspace(tmp_path)
    operations = Operations(board.setup)
    operations.library = board.library
    indexer = board.setup.indexer()
    batch_started, release = threading.Event(), threading.Event()
    lanes = []

    def batch(stop, report):
        lanes.append(("batch", getattr(indexer._thread, "background", False)))
        batch_started.set()
        assert release.wait(5)
        return {}

    def check(path, stop, progress):
        lanes.append(("interactive", getattr(indexer._thread, "background", False)))
        return {"path": path}

    operations.library.check_all = batch
    operations.library.check = check
    jobs = Jobs(tmp_path)
    try:
        batch_id = jobs.submit(
            "check-all",
            lambda stop, report: operations.run(JobRequest(kind="check-all"), stop, report),
        )
        assert batch_started.wait(2)
        one = jobs.submit(
            "check",
            lambda stop, report: operations.run(
                JobRequest(kind="check", path=str(original)), stop, report
            ),
        )
        assert finished(jobs, one)["status"] == "completed"
        assert jobs.get(batch_id)["status"] == "running"
        assert lanes == [("batch", True), ("interactive", False)]
        assert jobs.get(one)["lane"] == "interactive"
    finally:
        release.set()
        jobs.close()


def test_mutations_never_overlap_while_read_lane_remains_available(tmp_path):
    jobs = Jobs(tmp_path)
    started, release, second_started = (threading.Event() for _ in range(3))

    def first(stop, report):
        started.set()
        assert release.wait(5)
        return 1

    def second(stop, report):
        second_started.set()
        return 2

    try:
        first_id = jobs.submit("reseed", first)
        assert started.wait(2)
        second_id = jobs.submit("manage", second)
        read = jobs.submit("details", lambda *_: "read")
        assert finished(jobs, read)["result"] == "read"
        assert not second_started.is_set()
        assert jobs.get(second_id)["status"] == "queued"
        release.set()
        assert finished(jobs, first_id)["status"] == "completed"
        assert finished(jobs, second_id)["result"] == 2
        assert all(
            job_lane(kind) == "batch"
            for kind in (
                "reseed",
                "manage",
                "prepare-repair",
                "unpack-reseed",
                "enqueue",
                "send-queue",
                "unknown",
            )
        )
        assert job_lane("candidate-inspector", {"inspector_action": "import"}) == "batch"
        assert job_lane("candidate-inspector", {"inspector_action": "check"}) == "interactive"
    finally:
        release.set()
        jobs.close()


def test_scan_publishes_whole_library_and_read_snapshot_remains_stable(tmp_path):
    from tests.test_reseed_workspace import workspace

    board, _, original, _, _ = workspace(tmp_path)
    library = board.library
    second = original.parent / "Second.mkv"
    second.write_bytes(b"movie")
    another = tmp_path / "Other"
    another.mkdir()
    (another / "Third.mkv").write_bytes(b"movie")
    folder = LibraryFolder(another, 1, ContentKind.MOVIE)
    board.setup.roots += (another,)
    board.setup.settings.library_folders.append(folder)
    library.entries = [
        LibraryEntry(library.entries[0].folder, scan_item(original), ItemState.ORPHAN)
    ]
    pinned = library.snapshot()
    published_first, release = threading.Event(), threading.Event()

    def progress(value):
        if value.get("folder") == str(original.parent):
            published_first.set()
            assert release.wait(5)

    with ThreadPoolExecutor(1) as pool:
        result = pool.submit(library.scan, threading.Event(), progress)
        try:
            assert published_first.wait(2)
            assert [entry.item.path for entry in library.entries] == [original]
            assert [entry.item.path for entry in library.snapshot().entries] == [original]
        finally:
            release.set()
        assert result.result()["count"] == 3
    assert len(library.entries) == 3
    assert [entry.item.path for entry in pinned.entries] == [original]


def test_concurrent_checks_download_a_torrent_once(tmp_path):
    entered, release = threading.Event(), threading.Event()
    requests = []

    def respond(request):
        requests.append(request)
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, content=b"complete torrent")

    http = httpx.Client(transport=httpx.MockTransport(respond))
    indexer = Indexer("https://c411.org", "secret", http=http, cache=Store(tmp_path / "state.db"))
    candidate = Candidate("Film", 100, "https://c411.org/download/1", infohash="a" * 40)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(indexer.fetch_torrent, candidate)
        assert entered.wait(2)
        second = pool.submit(indexer.fetch_torrent, candidate)
        release.set()
        assert first.result() == second.result() == b"complete torrent"
    assert len(requests) == 1
    http.close()


def test_cache_read_never_observes_a_partial_replacement(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.cache_torrent("a", b"old complete")
    original = Path.write_bytes
    entered, release = threading.Event(), threading.Event()

    def slow(path, data):
        if path.suffix == ".tmp":
            original(path, data[:2])
            entered.set()
            assert release.wait(5)
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", slow)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(store.cache_torrent, "a", b"new complete")
        try:
            assert entered.wait(2)
            assert store.cached_torrent("a") == b"old complete"
        finally:
            release.set()
        future.result()
    assert store.cached_torrent("a") == b"new complete"


def test_shared_client_session_calls_are_serialized_without_serializing_jobs():
    from torrentlinker.client_access import SerializedClient

    first, release, second = (threading.Event() for _ in range(3))

    class Client:
        def torrents(self):
            first.set()
            assert release.wait(5)
            return []

        def check(self):
            second.set()
            return "ok"

    client = SerializedClient(Client())
    with ThreadPoolExecutor(2) as pool:
        listing = pool.submit(client.torrents)
        assert first.wait(2)
        checking = pool.submit(client.check)
        assert not second.wait(0.05)
        release.set()
        assert listing.result() == []
        assert checking.result() == "ok"


def test_background_rate_limit_wait_is_cancelled_without_delaying_shutdown(tmp_path):
    entered = threading.Event()

    def respond(_):
        entered.set()
        return httpx.Response(429, headers={"Retry-After": "3600"})

    http = httpx.Client(transport=httpx.MockTransport(respond))
    indexer = Indexer("https://c411.org", "secret", http=http)
    jobs = Jobs(tmp_path)

    def work(stop, progress):
        with indexer.background(stop):
            indexer.torrent_json("a" * 40)

    try:
        identifier = jobs.submit("catalogue", work)
        assert entered.wait(2)
        started = time.monotonic()
        jobs.cancel(identifier)
        assert finished(jobs, identifier)["status"] == "cancelled"
        assert time.monotonic() - started < 1
    finally:
        jobs.close()
        http.close()


def test_foreground_same_hash_does_not_wait_through_batch_backoff(tmp_path):
    import pytest

    from torrentlinker.indexer import RateLimited

    entered, stop = threading.Event(), threading.Event()

    def respond(_):
        entered.set()
        return httpx.Response(429, headers={"Retry-After": "3600"})

    http = httpx.Client(transport=httpx.MockTransport(respond))
    indexer = Indexer("https://c411.org", "secret", http=http, cache=Store(tmp_path / "state.db"))
    candidate = Candidate("Film", 100, "https://c411.org/download/1", infohash="a" * 40)

    def background():
        with indexer.background(stop):
            indexer.fetch_torrent(candidate)

    with ThreadPoolExecutor(1) as pool:
        batch = pool.submit(background)
        assert entered.wait(2)
        started = time.monotonic()
        try:
            with pytest.raises(RateLimited):
                indexer.fetch_torrent(candidate)
            assert time.monotonic() - started < 1
        finally:
            stop.set()
        with pytest.raises(InterruptedError):
            batch.result(timeout=2)
    assert indexer._fetch_locks == {}
    http.close()


def test_shared_search_names_use_interactive_lane_but_enqueue_does_not():
    assert job_lane("search-search") == "interactive"
    assert job_lane("search-search-options") == "interactive"
    assert job_lane("search-enqueue") == "batch"
    assert job_lane("search-send-queue") == "batch"


def test_reseed_scan_pipelines_discoveries_without_publishing_partial_library(tmp_path):
    from tests.test_reseed_workspace import workspace
    from torrentlinker.web.jobs import JobStop

    board, _, original, links, _ = workspace(tmp_path)
    discovered = original.with_name("New discovery.mkv")
    checked = threading.Event()
    scan = board.library.scan

    def scan_with_barrier(stop, progress, folders=None, on_discovered=None):
        def admit(entries):
            on_discovered(entries)
            assert checked.wait(5), "New item must run before the scan publishes"
            assert str(discovered) not in {row["path"] for row in board.library.rows()}

        return scan(stop, progress, folders, admit)

    def check(path, stop, progress):
        if path == str(discovered):
            checked.set()
        return []

    def progress(value):
        if value["phase"] == "find" and value["path"] == str(original):
            discovered.write_bytes(original.read_bytes())
            board.request_scan()

    board.library.scan = scan_with_barrier
    board.library.check = check
    result = board.run([str(original)], "find", str(links), JobStop(), progress)
    assert checked.is_set()
    assert result["done"] == 2
    assert str(discovered) in {row["path"] for row in board.library.rows()}
    assert not any("Scan the Library" in error["message"] for error in result["errors"])
