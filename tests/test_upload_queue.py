"""Local Upload review at owner job and MCP connection boundaries."""

import httpx
from fastapi.testclient import TestClient

from tests.fake_qbit import FakeQbit
from tests.test_agent_access import call
from tests.test_upload_completeness import complete_description
from tests.test_web_jobs import finished, login
from torrentlinker.web.app import create_app


class UploadClient(FakeQbit):
    def check(self):
        return "fake"

    def folder_settings(self):
        return []


def test_local_draft_survives_restart_and_only_explicit_send_contacts_site(tmp_path, monkeypatch):
    posts = []

    def response(request):
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(200, json={"data": {"id": 123}})
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
    )
    root = tmp_path / "media"
    root.mkdir()
    path = root / "Object.stl"
    path.write_text("solid model\nendsolid model\n")
    directory = tmp_path / "config"

    def app():
        return create_app(
            directory,
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: UploadClient(),
        )

    def job(browser, **body):
        response = browser.post("/api/jobs", json=body)
        assert response.status_code == 202, response.text
        result = finished(browser, response.json()["id"])
        assert result["status"] == "completed", result
        return result["result"]

    with TestClient(app()) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/models", "kind": "3d-model"},
        )
        job(browser, kind="scan")
        saved = job(
            browser,
            kind="upload-queue",
            path=str(path),
            upload={
                "description": "Unreviewed description",
                "title": "Object.NOTAG.STL",
                "image": "https://images.example/old.png",
            },
        )
        assert saved["status"] == "queued"
        assert not posts
        assert not list(directory.rglob("*.torrent"))
    with TestClient(app()) as browser:
        login(browser)
        rows = browser.get("/api/upload/queue").json()
        assert len(rows) == 1
        assert "Unreviewed description" in rows[0]["form"]["description"]
        assert rows[0]["id"] == saved["id"]
        edited = job(
            browser,
            kind="upload-queue",
            draft_id=saved["id"],
            revision=saved["revision"],
            path=str(path),
            upload={
                **rows[0]["form"],
                "description": complete_description().replace(
                    "https://example.org/cover.jpg", "https://images.example/old.png"
                ),
                "image": "https://images.example/object.png",
            },
        )
        assert "old.png" not in edited["form"]["description"]
        assert "https://images.example/object.png" in edited["form"]["description"]
        assert edited["revision"] == saved["revision"] + 1
        assert not posts
        stale = browser.post(
            "/api/jobs",
            json={"kind": "upload-send", "draft_id": saved["id"], "revision": saved["revision"]},
        )
        assert stale.status_code == 400
        other = browser.post(
            "/api/clients",
            json={"name": "Other", "client": "qbittorrent", "host": "https://other.example"},
        ).json()["client_id"]
        assert browser.get("/api/upload/queue", params={"client_id": other}).json() == []
        denied = browser.post(
            "/api/jobs",
            json={
                "kind": "upload-send",
                "client_id": other,
                "draft_id": edited["id"],
                "revision": edited["revision"],
            },
        )
        assert denied.status_code == 400
        browser.post(
            "/api/setup/indexer",
            json={"url": "https://c411.org/api/torznab", "api_key": "fake-key"},
        )
        browser.post("/api/setup/announce", json={"value": "https://c411.org/announce/fake"})
        path.write_text("solid changed model\nendsolid model\n")
        changed = browser.post(
            "/api/jobs",
            json={"kind": "upload-send", "draft_id": edited["id"], "revision": edited["revision"]},
        ).json()
        assert finished(browser, changed["id"])["status"] == "failed"
        assert not posts
        edited = job(
            browser,
            kind="upload-queue",
            path=str(path),
            draft_id=edited["id"],
            revision=edited["revision"],
            upload=edited["form"],
        )
        sent = job(browser, kind="upload-send", draft_id=edited["id"], revision=edited["revision"])
        assert sent["draft_id"] == 123
        assert len(posts) == 1
        assert "Reviewed description" in posts[0].content.decode()
        again = job(browser, kind="upload-send", draft_id=edited["id"], revision=edited["revision"])
        assert again["draft_id"] == 123
        assert len(posts) == 1
        assert browser.get("/api/upload/queue").json()[0]["status"] == "sent"

    # The shared editor can resume seeding from the durable sent Draft after restart.
    with TestClient(app()) as browser:
        login(browser)
        submitted = browser.post(
            "/api/upload/workspace/tool-start",
            json={
                "tool": "seed-upload",
                "path": str(path),
                "id": edited["id"],
                "revision": edited["revision"],
            },
        )
        assert submitted.is_success, submitted.text
        seeded = finished(browser, submitted.json()["id"])
        assert seeded["status"] == "completed", seeded
        assert seeded["result"]["hash"] == sent["hash"]
        assert seeded["result"]["status"] == "verifying"
        assert seeded["progress"]["cancellable"] is False


def test_mcp_automations_queue_locally_and_sending_needs_current_revision_approval(
    tmp_path, monkeypatch
):
    posts = []

    def response(request):
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(200, json={"data": {"id": 456}})
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
    )
    root = tmp_path / "media"
    root.mkdir()
    path = root / "Object.stl"
    path.write_text("solid model\nendsolid model\n")
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: UploadClient(),
        )
    ) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/models", "kind": "3d-model"},
        )
        scan = browser.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(browser, scan["id"])["status"] == "completed"
        grant = browser.post(
            "/api/agents",
            json={
                "name": "Automatic uploads",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["uploads"],
            },
        ).json()
        browser.put("/api/agents", json={"enabled": True})
        token = grant["token"]

        def propose(request_id, **operation):
            return call(
                browser,
                token,
                "propose_action",
                {"request_id": request_id, "operation": {"client_id": "default", **operation}},
            )["structuredContent"]

        queued = propose(
            "legacy-task",
            kind="upload-draft",
            path=str(path),
            upload={
                "title": "Object.NOTAG.STL",
                "description": "Needs review",
                "image": "https://images.example/object.png",
                "reviewed": True,
            },
        )
        assert queued["requires_owner_approval"] is False
        result = finished(browser, queued["job_id"])
        assert result["status"] == "completed", result
        draft = result["result"]
        assert draft["status"] == "queued"
        assert posts == []
        listing = call(
            browser, token, "list_items", {"client_id": "default", "collection": "upload-queue"}
        )["structuredContent"]
        assert listing["total"] == 1
        assert listing["rows"][0]["form"]["image"] == "https://images.example/object.png"
        send = propose(
            "send-old", kind="upload-send", draft_id=draft["id"], revision=draft["revision"]
        )
        assert send["requires_owner_approval"] is True
        preview = browser.get(f"/api/agents/proposals/{send['id']}/review").json()
        assert preview["local_draft"]["revision"] == draft["revision"]
        assert "Needs review" in preview["local_draft"]["form"]["description"]
        changed = propose(
            "edit",
            kind="upload-queue",
            path=str(path),
            draft_id=draft["id"],
            revision=draft["revision"],
            upload={**draft["form"], "description": complete_description(text="Corrected")},
        )
        edited = finished(browser, changed["job_id"])["result"]
        stale = browser.post(f"/api/agents/proposals/{send['id']}/approve")
        assert stale.status_code == 400
        assert posts == []
        browser.post(
            "/api/setup/indexer",
            json={"url": "https://c411.org/api/torznab", "api_key": "fake-key"},
        )
        browser.post("/api/setup/announce", json={"value": "https://c411.org/announce/fake"})
        send = propose(
            "send-reviewed", kind="upload-send", draft_id=edited["id"], revision=edited["revision"]
        )
        assert send["requires_owner_approval"] is True
        approved = browser.post(f"/api/agents/proposals/{send['id']}/approve").json()
        sent = finished(browser, approved["job_id"])
        assert sent["status"] == "completed", sent
        assert len(posts) == 1
        removed = propose(
            "remove-local", kind="upload-remove", draft_id=edited["id"], revision=edited["revision"]
        )
        assert finished(browser, removed["job_id"])["status"] == "completed"
        assert browser.get("/api/upload/queue").json() == []
        assert len(posts) == 1


def test_uncertain_send_is_kept_and_does_not_retry_automatically(tmp_path, monkeypatch):
    posts = []

    def response(request):
        if request.method == "POST":
            posts.append(request)
            raise httpx.ReadTimeout("connection lost after POST")
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
    )
    root = tmp_path / "models"
    root.mkdir()
    item = root / "Object.stl"
    item.write_text("solid model\nendsolid model\n")
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: UploadClient(),
        )
    ) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/models", "kind": "3d-model"},
        )
        browser.post(
            "/api/setup/indexer",
            json={"url": "https://c411.org/api/torznab", "api_key": "fake-key"},
        )
        browser.post("/api/setup/announce", json={"value": "https://c411.org/announce/fake"})

        def job(**body):
            submitted = browser.post("/api/jobs", json=body)
            assert submitted.status_code == 202, submitted.text
            return finished(browser, submitted.json()["id"])

        assert job(kind="scan")["status"] == "completed"
        record = job(
            kind="upload-queue",
            path=str(item),
            upload={
                "image": "https://images.example/object.png",
                "description": complete_description(text="Review me"),
            },
        )["result"]
        first = job(kind="upload-send", draft_id=record["id"], revision=record["revision"])
        assert first["status"] == "failed"
        assert len(posts) == 1
        kept = browser.get("/api/upload/queue").json()[0]
        assert kept["status"] == "uncertain"
        assert "Review me" in kept["form"]["description"]
        second = job(kind="upload-send", draft_id=record["id"], revision=record["revision"])
        assert second["status"] == "failed"
        assert len(posts) == 1
        reset = job(kind="upload-reset", draft_id=record["id"], revision=record["revision"])
        assert reset["status"] == "completed"
        assert reset["result"]["revision"] == record["revision"] + 1
        assert reset["result"]["status"] == "queued"
        assert len(posts) == 1
