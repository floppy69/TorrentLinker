"""Search panel behavior through its shared public service."""

from torrentlinker.search_workspace import SearchWorkspace
from torrentlinker.web.jobs import Jobs

pytest_plugins = ["tests.test_enqueue_destinations"]


def test_missing_category_is_saved_and_reused_for_a_mixed_selection(operations, tmp_path):
    del operations.setup.settings.download_folders.by_category[4050]
    jobs = Jobs(tmp_path)
    service = SearchWorkspace(operations, jobs)
    try:
        hashes = ["a" * 40, "b" * 40]
        state = service.request("folders", {"hashes": hashes})
        assert [row["category"] for row in state["missing"]] == [4050]
        assert state["folders"][0]["path"] == str(tmp_path / "films")
        service.request(
            "configure-folder",
            {"hashes": hashes, "category": 4050, "path": str(tmp_path / "games")},
        )
        assert service.request("folders", {"hashes": hashes})["missing"] == []
        assert operations.setup.settings.download_folders.default == ""
        assert operations.setup.settings.download_folders.by_category[4050] == str(
            tmp_path / "games"
        )
    finally:
        jobs.close()


def test_queue_actions_preserve_unsafe_outcomes_and_persist(operations, tmp_path):
    import time

    from torrentlinker.download_queue import entries

    jobs = Jobs(tmp_path)
    service = SearchWorkspace(operations, jobs)
    try:
        identifier = service.request("job", {"kind": "enqueue", "hashes": ["a" * 40, "b" * 40]})[
            "job"
        ]
        for _ in range(100):
            result = service.request("job-status", {"job": identifier})
            if result["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        assert result["status"] == "completed", result
        rows = service.request("state", {})["rows"]
        assert len(rows) == 2
        first, second = entries(operations.setup.store)
        operations.setup.store.download_outcome(first.key, "failed", retry_safe=True)
        operations.setup.store.download_outcome(second.key, "uncertain")
        service.request("retry", {"keys": [first.key, second.key]})
        state = service.request("state", {})
        assert [row["status"] for row in state["rows"]] == ["queued", "uncertain"]
        service.request("remove", {"keys": [first.key]})
    finally:
        jobs.close()
    reopened = Jobs(tmp_path)
    try:
        state = SearchWorkspace(operations, reopened).request("state", {})
        assert [row["status"] for row in state["rows"]] == ["uncertain"]
        assert state["active"] is None
    finally:
        reopened.close()


def test_empty_selected_send_cannot_start_the_whole_queue(operations, tmp_path):
    import pytest

    jobs = Jobs(tmp_path)
    try:
        service = SearchWorkspace(operations, jobs)
        with pytest.raises(ValueError, match="Select.*queued"):
            service.request("start", {"keys": []})
        assert jobs.list() == []
    finally:
        jobs.close()


def wait_job(service, identifier):
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = service.request("job-status", {"job": identifier})
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.01)
    raise AssertionError(result)


def test_start_selected_and_pause_leave_other_torrents_waiting(operations, tmp_path):
    import threading

    import httpx

    from tests.fake_qbit import FakeQbit
    from tests.test_send import release
    from torrentlinker.indexer import Indexer
    from torrentlinker.store import CatalogueRow
    from torrentlinker.torrent_meta import read_torrent

    entered, finish = threading.Event(), threading.Event()

    class SlowClient(FakeQbit):
        def download(self, data, save_path, tags, **kwargs):
            entered.set()
            assert finish.wait(5)
            return super().download(data, save_path, tags, **kwargs)

    data = {str(n): release(tmp_path, f"Film{n}") for n in range(2)}
    hashes = [read_torrent(value).infohash for value in data.values()]
    operations.setup.store.save_catalogue(
        [
            CatalogueRow(h, f"Film{n}", 5001, 2, 2030, f"https://indexer.test/{n}", "", 1)
            for n, h in enumerate(hashes)
        ]
    )
    operations.setup._indexer = Indexer(
        "https://indexer.test",
        "key",
        http=httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, content=data[req.url.path[1:]])
            )
        ),
    )
    client = SlowClient()
    operations.setup._client = client
    jobs = Jobs(tmp_path)
    service = SearchWorkspace(operations, jobs)
    try:
        assert (
            wait_job(service, service.request("job", {"kind": "enqueue", "hashes": hashes})["job"])[
                "status"
            ]
            == "completed"
        )
        rows = service.request("state", {})["rows"]
        started = service.request("start", {"keys": [rows[0]["key"]]})["job"]
        assert entered.wait(3)
        assert service.request("state", {})["active"]["id"] == started
        service.request("pause", {})
        finish.set()
        assert wait_job(service, started)["status"] == "cancelled"
        assert client.downloads == [hashes[0]]
        assert [(r["hash"], r["status"]) for r in service.request("state", {})["rows"]] == [
            (hashes[1], "queued")
        ]
    finally:
        finish.set()
        jobs.close()


def test_other_client_queue_is_never_retried_removed_or_sent(operations, tmp_path):
    import pytest

    from torrentlinker.download_queue import enqueue
    from torrentlinker.indexer import Candidate, Indexer

    settings = operations.setup.settings
    other = settings.add_client("Other")
    foreign = operations.setup.store.for_client(other.id)
    enqueue(
        foreign,
        Indexer("https://elsewhere.test", "key"),
        Candidate("Other torrent", 1, "https://elsewhere.test/file", infohash="c" * 40),
        tmp_path / "films",
    )
    key = foreign.queued_downloads()[0][0]
    foreign.download_outcome(key, "failed", retry_safe=True)
    jobs = Jobs(tmp_path)
    try:
        service = SearchWorkspace(operations, jobs)
        assert service.request("state", {})["rows"] == []
        service.request("retry", {"keys": [key]})
        service.request("remove", {"keys": [key]})
        assert foreign.queued_downloads()[0][2] == "failed"
        with pytest.raises(ValueError, match="Select"):
            service.request("start", {"keys": [key]})
        with pytest.raises(ValueError, match="Invalid Search job"):
            service.request("job", {"kind": "enqueue", "hashes": ["a" * 40], "category": 4050})
    finally:
        jobs.close()


def test_queue_estimates_keep_saved_tracker_origin(operations, tmp_path):
    from torrentlinker.zen import ZenClass, ZenProfile

    operations.setup.settings.zen = ZenProfile(zen_class=ZenClass.SWARM_KEEPER)
    from torrentlinker.download_queue import enqueue
    from torrentlinker.indexer import Candidate, Indexer

    enqueue(
        operations.setup.store,
        Indexer("https://c411.org/api", "key"),
        Candidate("C411", 4_000_000_000, "https://c411.org/file", 2, "c" * 40, categories=(2030,)),
        tmp_path / "films",
    )
    enqueue(
        operations.setup.store,
        Indexer("https://other.test/api", "key"),
        Candidate(
            "Other", 4_000_000_000, "https://other.test/file", 2, "d" * 40, categories=(2030,)
        ),
        tmp_path / "films",
    )
    jobs = Jobs(tmp_path)
    try:
        rows = SearchWorkspace(operations, jobs).request("state", {})["rows"]
        assert rows[0]["note"] == 1.35
        assert rows[0]["zen"] > 0
        assert rows[1]["note"] is None and rows[1]["zen"] is None
    finally:
        jobs.close()


def test_failed_send_remains_visible_after_job_finishes(operations, tmp_path):
    jobs = Jobs(tmp_path, error_message=str)
    service = SearchWorkspace(operations, jobs)
    try:
        wait_job(service, service.request("job", {"kind": "enqueue", "hashes": ["a" * 40]})["job"])
        operations.setup.settings.download_folders.by_category.clear()
        started = service.request("start", {})["job"]
        assert wait_job(service, started)["status"] == "failed"
        state = service.request("state", {})
        assert state["active"] is None
        assert state["last"]["status"] == "failed"
        assert state["last"]["error"]
        assert state["rows"][0]["status"] == "queued"
    finally:
        jobs.close()


def test_queue_edits_leave_another_senders_claim_intact(operations, tmp_path):
    from torrentlinker.store import Store

    jobs = Jobs(tmp_path)
    service = SearchWorkspace(operations, jobs)
    try:
        wait_job(service, service.request("job", {"kind": "enqueue", "hashes": ["a" * 40]})["job"])
        key = service.request("state", {})["rows"][0]["key"]
        external = Store(tmp_path / "state.db")
        assert external.claim_download(key)
        service.request("remove", {"keys": [key]})
        service.request("retry", {"keys": [key]})
        service.request("clear-sent", {})
        assert service.request("state", {})["rows"][0]["status"] == "sending"
    finally:
        jobs.close()
