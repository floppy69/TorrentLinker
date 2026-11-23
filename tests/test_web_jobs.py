import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_upload_completeness import complete_description
from torrentlinker.domain import Torrent
from torrentlinker.web.app import create_app


def login(browser):
    browser.headers["X-TorrentLinker"] = "1"
    assert browser.post("/api/login", json={"password": "test-password-long"}).status_code == 200


def finished(browser, identifier, *, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = browser.get(f"/api/jobs/{identifier}").json()
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job {identifier} did not finish within {timeout}s: {job}")


class Client:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.paused = []

    def check(self):
        return "fake"

    def folder_settings(self):
        return []

    def torrents(self, **kwargs):
        return [Torrent("a" * 40, "Book", Path("/remote"), size=1024)]

    def torrent(self, hash, **kwargs):
        return self.torrents()[0]

    def pause(self, hash):
        self.started.set()
        self.release.wait(5)
        self.paused.append(hash)


def test_job_survives_browser_logout_and_is_visible_after_server_restart(tmp_path: Path):
    client = Client()
    app = create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    with TestClient(app) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        created = browser.post(
            "/api/jobs", json={"kind": "manage", "action": "pause", "hashes": ["a" * 40]}
        )
        assert created.status_code == 202, created.text
        identifier = created.json()["id"]
        assert client.started.wait(2)
        changed = browser.post(
            "/api/setup/client", json={"client": "deluge", "host": "https://other.example"}
        )
        assert changed.status_code == 409
        browser.post("/api/logout")
        client.release.set()
        login(browser)
        job = finished(browser, identifier)
        assert job["status"] == "completed", job
        assert job["result"][0]["outcome"] == "sent"
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        login(browser)
        assert browser.get(f"/api/jobs/{identifier}").json()["status"] == "completed"
    assert client.paused == ["a" * 40]


def _leave_interrupted_job(directory, pipe):
    """Abrupt process exit during a client call; deliberately no graceful shutdown."""
    import os

    client = Client()
    with TestClient(
        create_app(directory, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        created = browser.post(
            "/api/jobs", json={"kind": "manage", "action": "pause", "hashes": ["a" * 40]}
        )
        assert client.started.wait(2)
        pipe.send(created.json()["id"])
        pipe.close()
        os._exit(0)


def test_abrupt_restart_records_interruption_without_replaying_mutation(tmp_path):
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_leave_interrupted_job, args=(tmp_path, sender))
    process.start()
    try:
        assert receiver.poll(10)
        identifier = receiver.recv()
        process.join(10)
        assert process.exitcode == 0
        client = Client()
        client.release.set()
        with TestClient(
            create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
        ) as browser:
            login(browser)
            recovered = browser.get(f"/api/jobs/{identifier}").json()
            assert recovered["status"] == "interrupted"
            assert "no action was replayed" in recovered["error"]
        assert client.paused == []
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        receiver.close()
        sender.close()


def test_browser_sessions_share_pending_refresh(tmp_path):
    client = Client()
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        blocking = browser.post("/api/jobs", json={"kind": "manage", "hashes": ["a" * 40]}).json()
        try:
            assert client.started.wait(2)
            first = browser.post("/api/jobs", json={"kind": "refresh"}).json()
            login(browser)
            second = browser.post("/api/jobs", json={"kind": "refresh"}).json()
            assert first["id"] == second["id"]
        finally:
            client.release.set()
        assert finished(browser, blocking["id"])["status"] == "completed"


def test_browser_reuses_running_and_queued_requests_with_the_same_parameters(tmp_path):
    from torrentlinker.web.operations import Operations

    entered, release = threading.Event(), threading.Event()
    calls = []

    class BlockingOperations(Operations):
        def run(self, request, stop, progress):
            if request.kind in {"scan", "check"}:
                calls.append((request.kind, request.path))
                if request.kind == "scan":
                    entered.set()
                assert release.wait(5)
                return {"path": request.path}
            return super().run(request, stop, progress)

    root = tmp_path / "library"
    root.mkdir()
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: Client(),
            operation_factory=BlockingOperations,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        assert browser.post(
            "/api/setup/client", json={"client": "deluge", "host": "https://box.example"}
        ).is_success
        assert browser.post(
            "/api/setup/folder", json={"local": str(root), "client_path": str(root)}
        ).is_success

        def submit(body):
            response = browser.post("/api/jobs", json=body)
            assert response.status_code == 202, response.text
            return response.json()["id"]

        try:
            scan = submit({"kind": "scan"})
            assert entered.wait(2)
            assert submit({"kind": "scan", "client_id": "default", "cached_only": False}) == scan
            first = submit({"kind": "check", "path": str(root / "a")})
            assert submit({"path": str(root / "a"), "kind": "check"}) == first
            second = submit({"kind": "check", "path": str(root / "b")})
            assert len({scan, first, second}) == 3
        finally:
            release.set()
        for identifier in (scan, first, second):
            assert finished(browser, identifier)["status"] == "completed"
        again = submit({"kind": "scan"})
        assert again != scan
        assert finished(browser, again)["status"] == "completed"
        assert calls == [
            ("scan", ""),
            ("check", str(root / "a")),
            ("check", str(root / "b")),
            ("scan", ""),
        ]


def test_pending_confirmed_delete_is_reused_without_replaying_confirmation(tmp_path):
    class DeletingClient(Client):
        def remove(self, infohash, *, delete_files=False):
            self.started.set()
            assert self.release.wait(5)
            self.paused.append((infohash, delete_files))

    client = DeletingClient()
    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            connector=lambda *args: client,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        body = {"kind": "manage", "action": "delete", "hashes": ["a" * 40]}
        body["confirmation"] = browser.post("/api/confirm", json=body).json()["token"]
        first = browser.post("/api/jobs", json=body)
        assert first.status_code == 202
        try:
            assert client.started.wait(2)
            repeated = browser.post("/api/jobs", json=body)
            assert repeated.status_code == 202
            assert repeated.json()["id"] == first.json()["id"]
            # A matching target without the token is still unauthorized.
            assert browser.post("/api/jobs", json={**body, "confirmation": ""}).status_code == 409
        finally:
            client.release.set()
        assert finished(browser, first.json()["id"])["status"] == "completed"
        assert client.paused == [("a" * 40, True)]
        assert browser.post("/api/jobs", json=body).status_code == 409


def test_delete_requires_a_single_use_confirmation_bound_to_selected_torrents(tmp_path: Path):
    class DeletingClient(Client):
        def remove(self, hash, *, delete_files=False):
            self.paused.append((hash, delete_files))

    client = DeletingClient()
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        body = {"kind": "manage", "action": "delete", "hashes": ["a" * 40]}
        assert browser.post("/api/jobs", json=body).status_code == 409
        preview = browser.post("/api/confirm", json=body).json()
        assert preview["torrents"][0]["name"] == "Book"
        assert "Torrent Client" in preview["warning"]
        body["confirmation"] = preview["token"]
        job = browser.post("/api/jobs", json=body)
        assert job.status_code == 202, job.text
        assert finished(browser, job.json()["id"])["status"] == "completed"
        assert client.paused == [("a" * 40, True)]
        assert browser.post("/api/jobs", json=body).status_code == 409


def test_torrents_are_paged_sorted_and_never_expose_announce_keys(tmp_path: Path):
    class ListingClient(Client):
        def torrents(self, **kwargs):
            return [
                Torrent(
                    "a" * 40,
                    "Alpha",
                    Path("/remote"),
                    size=1024,
                    state="uploading",
                    tracker="https://c411.org/announce/private-passkey",
                    connected_seeds=4,
                    connected_peers=2,
                ),
                Torrent("b" * 40, "Beta", Path("/remote"), size=4096),
            ]

    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: ListingClient())
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        response = browser.post("/api/jobs", json={"kind": "refresh"})
        assert response.status_code == 202, response.text
        job = finished(browser, response.json()["id"])
        assert job["status"] == "completed", job
        result = browser.get(
            "/api/torrents", params={"sort": "size", "descending": True, "limit": 1}
        )
        assert result.json()["total"] == 2
        assert result.json()["rows"][0]["name"] == "Beta"
        result = browser.get("/api/torrents", params={"q": "Alpha"})
        assert result.json()["rows"][0]["peers"] == 2
        assert result.json()["rows"][0]["zen"] is not None
        assert "private-passkey" not in result.text
        counts = result.json()["counts"]
        assert counts["all"] == 2
        assert sum(counts["status"].values()) == 2
        assert result.json()["rows"][0]["eta"] == -1
        assert browser.get("/api/torrents", params={"tag": "absent"}).json()["total"] == 0


def test_search_can_queue_a_selected_result_but_remote_unmounted_sends_are_refused(
    tmp_path: Path, monkeypatch
):
    import httpx

    from torrentlinker import net

    def response(request):
        if request.url.params.get("t") == "caps":
            return httpx.Response(
                200, text='<caps><categories><category id="7000" name="Ebook"/></categories></caps>'
            )
        return httpx.Response(
            200,
            text=(
                '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channe'
                "l><item><title>Selected book</title><size>1024</size><link>https:"
                "//tracker.example/download?apikey=private-key</link><torznab:attr"
                ' name="infohash" '
                'value="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/><torznab:attr '
                'name="seeders" value="4"/></item></channel></rss>'
            ),
        )

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response))
    )
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        assert (
            browser.post(
                "/api/setup/indexer",
                json={"url": "https://tracker.example/api", "api_key": "private-key"},
            ).status_code
            == 200
        )
        created = browser.post("/api/jobs", json={"kind": "search", "query": "book"})
        assert created.status_code == 202, created.text
        job = finished(browser, created.json()["id"])
        assert job["status"] == "completed", job
        assert job["result"]["rows"][0]["title"] == "Selected book"
        assert "private-key" not in str(job)
        queued = browser.post("/api/jobs", json={"kind": "enqueue", "hashes": ["a" * 40]})
        assert queued.status_code == 400, queued.text
        assert "folder" in queued.text.lower()


def test_scan_runs_off_request_and_rejects_files_outside_storage(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "Book.epub").write_bytes(b"book")

    class FilesClient(Client):
        def files(self, hash):
            return {"Book.epub": 4}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: FilesClient(),
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/remote", "kind": "ebook"},
        )
        response = browser.post("/api/jobs", json={"kind": "scan"})
        assert response.status_code == 202, response.text
        job = finished(browser, response.json()["id"])
        assert job["status"] == "completed", job
        rows = browser.get("/api/library").json()["rows"]
        assert rows[0]["name"] == "Book.epub"
        outside = tmp_path / "private.txt"
        outside.write_text("private")
        (root / "escape.txt").symlink_to(outside)
        response = browser.post("/api/jobs", json={"kind": "scan"})
        job = finished(browser, response.json()["id"])
        assert job["status"] == "failed"
        # A failed refresh preserves the previous successful library.
        assert browser.get("/api/library").json()["rows"] == rows


def test_planning_without_mounted_storage_is_explicitly_unavailable(tmp_path: Path):
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        response = browser.post("/api/jobs", json={"kind": "plan"})
        assert response.status_code == 400
        assert "folder" in response.text.lower()


def test_missing_download_mount_is_not_treated_as_empty_storage(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "Book.epub").write_bytes(b"book")

    class FilesClient(Client):
        def files(self, hash):
            return {"Book.epub": 4}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: FilesClient(),
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        assert (
            browser.post(
                "/api/setup/folder",
                json={"local": str(root), "client_path": "/remote", "purpose": "download"},
            ).status_code
            == 200
        )
        (root / "Book.epub").unlink()
        root.rmdir()
        response = browser.post("/api/jobs", json={"kind": "send-queue"})
        assert response.status_code == 400, response.text
        assert "storage" in response.text.lower() or "folder" in response.text.lower()
        # A disconnected mount can leave its empty mountpoint behind.
        root.mkdir()
        response = browser.post("/api/jobs", json={"kind": "send-queue"})
        assert response.status_code == 202, response.text
        job = finished(browser, response.json()["id"])
        assert job["status"] == "failed"
        assert "mapping" in job["error"].lower()


def test_selected_download_uses_verified_client_path_and_survives_queue_reload(
    tmp_path, monkeypatch
):
    import httpx

    from tests.fake_qbit import FakeQbit
    from tests.test_send import release
    from torrentlinker import net
    from torrentlinker.torrent_meta import read_torrent

    data = release(tmp_path)
    meta = read_torrent(data)
    root = tmp_path / "media"
    root.mkdir()
    (root / "existing.epub").write_bytes(b"book")

    class DownloadingClient(FakeQbit):
        def check(self):
            return "fake"

        def folder_settings(self):
            return []

    client = DownloadingClient()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "Existing", Path("/downloads"), files={"existing.epub": 4}
    )

    def response(request):
        if request.url.path == "/file":
            return httpx.Response(200, content=data)
        if request.url.params.get("t") == "caps":
            return httpx.Response(
                200, text='<caps><categories><category id="7000" name="Ebook"/></categories></caps>'
            )
        return httpx.Response(
            200,
            text=(
                '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel><item>'
                "<title>Film.2020</title><size>5001</size>"
                "<link>https://tracker.example/file?apikey=private-key</link>"
                '<enclosure url="https://tracker.example/file?apikey=private-key"/>'
                f'<torznab:attr name="infohash" value="{meta.infohash}"/>'
                '<torznab:attr name="category" value="7000"/>'
                '<torznab:attr name="seeders" value="4"/></item></channel></rss>'
            ),
        )

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response))
    )

    def app():
        return create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: client,
        )

    with TestClient(app()) as browser:
        login(browser)
        assert (
            browser.post(
                "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
            ).status_code
            == 200
        )
        assert (
            browser.post(
                "/api/setup/indexer",
                json={"url": "https://tracker.example/api", "api_key": "private-key"},
            ).status_code
            == 200
        )
        assert (
            browser.post(
                "/api/setup/folder",
                json={"local": str(root), "client_path": "/downloads", "purpose": "download"},
            ).status_code
            == 200
        )
        job = browser.post("/api/jobs", json={"kind": "plan"}).json()
        planned = finished(browser, job["id"])
        assert planned["status"] == "completed", planned
        assert planned["result"]["provisional"] is True
        assert planned["result"]["rows"][0]["hash"] == meta.infohash
        assert planned["result"]["catalogue"]["count"] == 1
        job = browser.post("/api/jobs", json={"kind": "search", "query": "Film"}).json()
        assert finished(browser, job["id"])["status"] == "completed"
        job = browser.post("/api/jobs", json={"kind": "enqueue", "hashes": [meta.infohash]}).json()
        receipt = finished(browser, job["id"])["result"]
        assert receipt["queued"] == 1
        assert receipt["location"] == "TorrentLinker Search > Download queue"
        assert receipt["sent_to_client"] is False
        assert receipt["downloads_started"] is False
        assert client.downloads == []
    with TestClient(app()) as browser:
        login(browser)
        assert browser.get("/api/queue").json()[0]["status"] == "queued"
        job = browser.post("/api/jobs", json={"kind": "send-queue"}).json()
        result = finished(browser, job["id"])
        assert result["status"] == "completed", result
        assert result["result"]["added"] == 1, result
        assert browser.get("/api/queue").json() == []
        assert result["result"]["rows"][0]["outcome"] == "sent"
        assert client.by_hash[meta.infohash].save_path == Path("/downloads")
        job = browser.post("/api/jobs", json={"kind": "send-queue"}).json()
        assert finished(browser, job["id"])["result"]["added"] == 0
    assert client.downloads == [meta.infohash]


def test_upload_preview_uses_local_profile_without_publishing(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "Object.stl").write_text("solid model\nendsolid model\n")

    class FilesClient(Client):
        def files(self, hash):
            return {}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: FilesClient(),
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/remote", "kind": "3d-model"},
        )
        job = browser.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(browser, job["id"])["status"] == "completed"
        created = browser.post(
            "/api/jobs", json={"kind": "upload-preview", "path": str(root / "Object.stl")}
        )
        assert created.status_code == 202, created.text
        preview = finished(browser, created.json()["id"])
        assert preview["status"] == "completed", preview
        assert preview["result"]["title"] == "Object.NOTAG.STL"
        assert preview["result"]["files"][0]["size"] == 27
        assert preview["result"]["warnings"]
        assert preview["result"]["presentation"]["status"] == "incomplete"
        assert any("description.synopsis" in row for row in preview["result"]["refusals"])


def test_prepared_upload_survives_unrelated_folder_changes(tmp_path, monkeypatch):
    import httpx

    from tests.fake_qbit import FakeQbit
    from torrentlinker import net

    class UploadClient(FakeQbit):
        def check(self):
            return "fake"

        def folder_settings(self):
            return []

    def response(request):
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"id": 123}})
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response))
    )
    root = tmp_path / "media"
    models, other = root / "models", root / "other"
    models.mkdir(parents=True)
    other.mkdir()
    item = models / "Object.stl"
    item.write_text("solid model\nendsolid model\n")
    client = UploadClient()
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: client,
        )
    ) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        assert (
            browser.post(
                "/api/setup/indexer",
                json={"url": "https://c411.org/api/torznab", "api_key": "fake-key"},
            ).status_code
            == 200
        )
        browser.post("/api/setup/announce", json={"value": "https://c411.org/announce/fake"})
        browser.post(
            "/api/setup/folder",
            json={"local": str(models), "client_path": "/models", "kind": "3d-model"},
        )
        job = browser.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(browser, job["id"])["status"] == "completed"
        job = browser.post(
            "/api/jobs",
            json={
                "kind": "upload-draft",
                "path": str(item),
                "upload": {
                    "image": "https://images.example/model.png",
                    "reviewed": True,
                    "description": complete_description(),
                },
            },
        ).json()
        draft = finished(browser, job["id"])
        assert draft["status"] == "completed", draft
        assert (
            browser.post(
                "/api/setup/folder", json={"local": str(other), "client_path": "/other"}
            ).status_code
            == 200
        )
        assert (
            browser.post("/api/setup/remove-folder", json={"local": str(other)}).status_code == 200
        )
        job = browser.post(
            "/api/jobs", json={"kind": "upload-seed", "hashes": [draft["result"]["hash"]]}
        ).json()
        seeded = finished(browser, job["id"])
        assert seeded["status"] == "completed", seeded
        assert seeded["result"]["status"] == "verifying"
        assert item.read_text() == "solid model\nendsolid model\n"


def test_files_endpoint_lists_one_torrents_files_for_the_files_tab(tmp_path: Path):
    from torrentlinker.domain import TorrentFile

    class Files(Client):
        def file_listing(self, hash):
            return [TorrentFile(0, "a.mkv", 2048, True), TorrentFile(1, "b.nfo", 10, False)]

    client = Files()
    app = create_app(tmp_path, password="test-password-long", connector=lambda *args: client)
    with TestClient(app) as browser:
        assert browser.get("/api/torrents/" + "a" * 40 + "/files").status_code == 401
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        found = browser.get("/api/torrents/" + "a" * 40 + "/files")
        assert found.status_code == 200
        assert found.json() == [
            {"index": 0, "name": "a.mkv", "size": 2048, "wanted": True},
            {"index": 1, "name": "b.nfo", "size": 10, "wanted": False},
        ]
        assert browser.get("/api/torrents/not-a-hash/files").status_code == 400


def test_send_queue_probes_each_download_folder_once(tmp_path: Path, monkeypatch):
    import threading

    from torrentlinker.web import operations
    from torrentlinker.web.operations import JobRequest

    app = create_app(tmp_path / "config", password="test-password-long")
    with TestClient(app):
        target = app.state.agent_service.for_client("default")
        folders = [tmp_path / "films", tmp_path / "books"]
        for i in range(6):
            target.setup.store.enqueue_download(
                str(i),
                {
                    "client_id": "default",
                    "folder": str(folders[i % 2]),
                    "indexer_url": "https://tracker.example/api",
                    "candidate": {"title": f"Release {i}", "size": 1, "download_url": "u"},
                },
            )
        probes: list[str] = []
        monkeypatch.setattr(target.setup, "path_under_root", Path)
        monkeypatch.setattr(target.setup, "configure_download_folder", probes.append)
        monkeypatch.setattr(target, "download_destinations", lambda: {str(f) for f in folders})

        class Probed(Exception):
            pass

        def stop_before_sending(*args, **kwargs):
            raise Probed

        monkeypatch.setattr(operations, "DownloadClient", lambda setup: None)
        monkeypatch.setattr(target.setup, "indexer", lambda: None)
        monkeypatch.setattr(operations, "run_queue", stop_before_sending)
        with pytest.raises(Probed):
            target.run(JobRequest(kind="send-queue"), threading.Event(), lambda _: None)

    assert sorted(probes) == sorted(str(f) for f in folders)
