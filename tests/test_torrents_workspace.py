"""Owner torrent workspace, tested with real services and simulated clients."""

from pathlib import Path

from tests.fake_qbit import FakeQbit
from torrentlinker.domain import Torrent
from torrentlinker.torrents_workspace import TorrentWorkspace

pytest_plugins = ["tests.test_enqueue_destinations"]


def workspace(operations):
    operations.setup.settings.indexer.url = "https://c411.org"
    operations.setup._client = FakeQbit(
        by_hash={
            "c" * 40: Torrent(
                "c" * 40,
                "Small",
                Path("/data"),
                size=1_000_000_000,
                state="uploading",
                tracker="https://c411.org/secret",
                swarm_seeders=10,
                seeding_time=172800,
            ),
            "d" * 40: Torrent(
                "d" * 40,
                "Large",
                Path("/data"),
                size=12_000_000_000,
                state="uploading",
                tracker="https://c411.org/secret",
                swarm_seeders=4,
            ),
            "e" * 40: Torrent(
                "e" * 40,
                "Other",
                Path("/data"),
                size=2_000_000_000,
                state="uploading",
                tracker="https://other.test/secret",
            ),
        }
    )
    return TorrentWorkspace(operations.setup, lambda _: operations)


def test_numeric_sort_and_combined_metrics_before_pagination(operations):
    service = workspace(operations)
    result = service.request("list", {"sort": "size", "descending": True, "limit": 1})
    assert result["rows"][0]["name"] == "Large"
    assert result["total"] == 3
    observed = result["rows"][0]["observed_at"]
    assert observed > 0
    assert service.request("list")["observed_at"] == observed
    result = service.request(
        "list", {"scope": "c411", "size_min": 1_000_000_000, "seed_max": 10, "days_min": 1}
    )
    assert [r["name"] for r in result["rows"]] == ["Small"]
    assert result["rows"][0]["weight"] == 0.25
    assert result["rows"][0]["seedtime"] == 2
    for descending in (False, True):
        rows = service.request("list", {"sort": "note", "descending": descending})["rows"]
        assert rows[-1]["name"] == "Other"
        assert rows[-1]["zen"] is None


def test_review_binds_action_and_source_and_protects_link_files(operations):
    from dataclasses import replace

    import pytest

    service = workspace(operations)
    selected = [{"client_id": "default", "hash": "c" * 40}]
    with pytest.raises(ValueError, match="Review"):
        service.request("apply", {"action": "delete", "items": selected})
    review = service.request("review", {"action": "remove", "items": selected})
    with pytest.raises(ValueError, match="Review"):
        service.request("apply", {"action": "delete", "items": selected, "token": review["token"]})
    review = service.request("review", {"action": "remove", "items": selected})
    service.request("apply", {"action": "remove", "items": selected, "token": review["token"]})
    assert operations.setup.client().removed == [("c" * 40, False)]
    fake = operations.setup.client()
    fake.by_hash["d" * 40] = replace(
        fake.by_hash["d" * 40], tags=frozenset({"torrentlinker:links"})
    )
    items = [{"client_id": "default", "hash": "d" * 40}]
    review = service.request("review", {"action": "delete", "items": items})
    result = service.request(
        "apply", {"action": "delete", "items": items, "token": review["token"]}
    )
    assert result["rows"][0]["outcome"] == "failed"
    assert "d" * 40 in fake.by_hash


def test_same_hash_routes_to_selected_client_and_file_priority(operations):
    from dataclasses import replace

    from torrentlinker.web.operations import Operations

    service = workspace(operations)
    settings = operations.setup.settings
    settings.client_profiles.append(replace(settings.profile(), id="nas", name="NAS"))
    second = Operations(operations.setup.for_client("nas"))
    second.setup._client = FakeQbit(by_hash=dict(operations.setup.client().by_hash))
    service = TorrentWorkspace(operations.setup, lambda cid: second if cid == "nas" else operations)
    items = [{"client_id": "nas", "hash": "c" * 40}]
    review = service.request("review", {"action": "pause", "items": items})
    service.request("apply", {"action": "pause", "items": items, "token": review["token"]})
    assert second.setup.client().torrent("c" * 40).state == "stoppedUP"
    assert operations.setup.client().torrent("c" * 40).state == "uploading"
    fake = second.setup.client()
    fake.by_hash["c" * 40] = replace(
        fake.by_hash["c" * 40], files={"main.bin": 100, "note.nfo": 10}
    )
    files = service.request("files", items[0])["files"]
    assert [f["name"] for f in files] == ["main.bin", "note.nfo"]
    payload = {"action": "skip_files", "items": items, "file_indexes": [1]}
    review = service.request("review", payload)
    service.request("apply", {**payload, "token": review["token"]})
    assert service.request("files", items[0])["files"][1]["wanted"] is False


def test_qbit_controls_send_exact_hash_and_limits_to_client():
    from torrentlinker.qbit import QbitApi

    class Endpoint:
        def __init__(self):
            self.received = []

        def torrents_reannounce(self, **kwargs):
            self.received.append(("announce", kwargs))

        def torrents_set_download_limit(self, **kwargs):
            self.received.append(("down", kwargs))

        def torrents_set_upload_limit(self, **kwargs):
            self.received.append(("up", kwargs))

    api = QbitApi("http://test", "", "")
    endpoint = Endpoint()
    api._client = endpoint
    api.manage_control("a" * 40, "limits", {"download_limit": 1024, "upload_limit": 2048})
    api.manage_control("b" * 40, "reannounce", {})
    assert endpoint.received == [
        ("down", {"torrent_hashes": "a" * 40, "limit": 1024}),
        ("up", {"torrent_hashes": "a" * 40, "limit": 2048}),
        ("announce", {"torrent_hashes": "b" * 40}),
    ]


def test_desktop_actions_wait_for_exclusive_jobs(operations):
    import threading

    from torrentlinker.agent.coordination import coordinator

    service = workspace(operations)
    items = [{"client_id": "default", "hash": "c" * 40}]
    review = service.request("review", {"action": "pause", "items": items})
    started, finished = threading.Event(), threading.Event()
    errors = []

    def apply():
        started.set()
        try:
            service.request("apply", {"action": "pause", "items": items, "token": review["token"]})
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()

    with coordinator.agent(threading.Event()):
        thread = threading.Thread(target=apply, daemon=True)
        thread.start()
        assert started.wait(2)
        assert not finished.wait(0.1)
        assert operations.setup.client().torrent("c" * 40).state == "uploading"
    thread.join(5)
    assert finished.is_set()
    assert not errors
    assert operations.setup.client().torrent("c" * 40).state == "stoppedUP"


def test_combined_clients_sort_swarm_totals_numerically(operations):
    from dataclasses import replace

    from torrentlinker.web.operations import Operations

    workspace(operations)
    settings = operations.setup.settings
    settings.client_profiles.append(replace(settings.profile(), id="nas", name="NAS"))
    second = Operations(operations.setup.for_client("nas"))
    book = operations.setup.client().torrent("c" * 40)
    second.setup._client = FakeQbit(
        by_hash={book.hash: replace(book, swarm_seeders=100, swarm_peers=13)}
    )
    service = TorrentWorkspace(operations.setup, lambda cid: second if cid == "nas" else operations)
    rows = service.request("list", {"client_id": "all", "sort": "seeds", "descending": True})[
        "rows"
    ]
    assert rows[0]["client_id"] == "nas"
    assert rows[0]["seeds"] == 0
    assert rows[0]["total_seeds"] == 100
    assert rows[0]["total_peers"] == 13
    assert rows[1]["total_seeds"] == 10


def test_file_review_names_original_indexes_and_rejects_changed_files(operations):

    import pytest

    from torrentlinker.domain import TorrentFile

    service = workspace(operations)

    class IndexedClient(FakeQbit):
        names = ["main.bin", "notes.nfo"]

        def file_listing(self, hash):
            return [
                TorrentFile(index, name, size, self.priorities.get(hash, {}).get(index, 1) > 0)
                for index, name, size in zip((7, 42), self.names, (1000, 20), strict=True)
            ]

    client = IndexedClient(by_hash=dict(operations.setup.client().by_hash))
    operations.setup._client = client
    payload = {
        "action": "skip_files",
        "items": [{"client_id": "default", "hash": "c" * 40}],
        "file_indexes": [42],
    }
    review = service.request("review", payload)
    assert review["rows"][0]["files"] == [
        {"index": 42, "name": "notes.nfo", "size": 20, "wanted": True}
    ]
    client.names = ["main.bin", "different.nfo"]
    with pytest.raises(ValueError, match="Review"):
        service.request("apply", {**payload, "token": review["token"]})
    assert not client.priorities
    review = service.request("review", payload)
    service.request("apply", {**payload, "token": review["token"]})
    files = service.request("files", payload["items"][0])["files"]
    assert files[0]["wanted"] is True
    assert files[1]["wanted"] is False
    with pytest.raises(ValueError, match="file indexes"):
        service.request("review", {**payload, "file_indexes": [99]})
