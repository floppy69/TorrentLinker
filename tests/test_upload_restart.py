"""Abrupt Upload termination must preserve review and prevent duplicate sends."""

import json
import multiprocessing
import os
import socket
import threading
import time

import httpx
import keyring
import pytest
from fastapi.testclient import TestClient

from tests.conftest import MemoryKeyring
from tests.shell_support import shell_navigate
from tests.test_agent_access import call
from tests.test_upload_completeness import complete_description
from tests.test_upload_queue import UploadClient
from tests.test_web_jobs import finished, login
from torrentlinker.web.app import create_app


def application(directory):
    return create_app(
        directory / "config",
        password="test-password-long",
        roots=(directory / "models",),
        connector=lambda *args: UploadClient(),
    )


def job(browser, **body):
    submitted = browser.post("/api/jobs", json=body)
    assert submitted.status_code == 202, submitted.text
    return finished(browser, submitted.json()["id"])


def _exit_during_upload(directory):
    keyring.set_keyring(MemoryKeyring())
    submitted = threading.Event()

    def response(request):
        if request.method == "POST":
            # Stand in for the site accepting a POST before its response arrives.
            # Wait until the parent can recover the persisted job identifier.
            assert submitted.wait(10)
            (directory / "accepted.json").write_text(json.dumps({"url": str(request.url)}))
            os._exit(0)
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(200, json={"data": []})

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "torrentlinker.net.client",
            lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
        )
        with TestClient(application(directory)) as browser:
            login(browser)
            for endpoint, body in (
                ("client", {"client": "qbittorrent", "host": "https://box.example"}),
                (
                    "folder",
                    {
                        "local": str(directory / "models"),
                        "client_path": "/models",
                        "kind": "3d-model",
                    },
                ),
                ("indexer", {"url": "https://c411.org/api/torznab", "api_key": "fake-key"}),
                ("announce", {"value": "https://c411.org/announce/fake"}),
            ):
                result = browser.post(f"/api/setup/{endpoint}", json=body)
                assert result.is_success, result.text
            assert job(browser, kind="scan")["status"] == "completed"
            queued = job(
                browser,
                kind="upload-queue",
                path=str(directory / "models" / "Object.stl"),
                upload={
                    "image": "https://images.example/object.png",
                    "description": complete_description(text="Keep this reviewed synopsis"),
                },
            )
            assert queued["status"] == "completed", queued
            record = queued["result"]
            sending = browser.post(
                "/api/jobs",
                json={
                    "kind": "upload-send",
                    "draft_id": record["id"],
                    "revision": record["revision"],
                },
            )
            assert sending.status_code == 202, sending.text
            (directory / "before.json").write_text(
                json.dumps({"draft": record, "job_id": sending.json()["id"]})
            )
            submitted.set()
            finished(browser, sending.json()["id"])
            raise AssertionError("The mocked Upload POST did not terminate the process")


def test_upload_process_exit_requires_reconciliation_and_fresh_approval(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    source = root / "Object.stl"
    original = b"solid model\nendsolid model\n"
    source.write_bytes(original)
    child = multiprocessing.get_context("spawn").Process(
        target=_exit_during_upload, args=(tmp_path,)
    )
    child.start()
    try:
        child.join(20)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.kill()
            child.join()
    assert json.loads((tmp_path / "accepted.json").read_text())["url"].startswith(
        "https://c411.org/"
    )
    before = json.loads((tmp_path / "before.json").read_text())
    record = before["draft"]
    posts = []

    def response(request):
        if request.method == "POST":
            posts.append(request)
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
    )
    with TestClient(application(tmp_path)) as browser:
        login(browser)
        interrupted = browser.get(f"/api/jobs/{before['job_id']}").json()
        assert interrupted["status"] == "interrupted", interrupted
        recovered = browser.get("/api/upload/queue").json()[0]
        assert recovered["id"] == record["id"]
        assert recovered["revision"] == record["revision"]
        assert recovered["status"] == "sending"
        assert recovered["form"] == record["form"]
        refused = job(
            browser, kind="upload-send", draft_id=record["id"], revision=record["revision"]
        )
        assert refused["status"] == "failed", refused

        grant = browser.post(
            "/api/agents",
            json={
                "name": "Recovery",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["uploads"],
            },
        ).json()
        browser.put("/api/agents", json={"enabled": True})

        def propose(request_id, kind, revision):
            return call(
                browser,
                grant["token"],
                "propose_action",
                {
                    "request_id": request_id,
                    "operation": {
                        "client_id": "default",
                        "kind": kind,
                        "draft_id": record["id"],
                        "revision": revision,
                    },
                },
            )["structuredContent"]

        reset = propose("reconcile", "upload-reset", record["revision"])
        assert reset["requires_owner_approval"] is True
        assert browser.get("/api/upload/queue").json()[0] == recovered
        stale = propose("old-send", "upload-send", record["revision"])
        assert stale["requires_owner_approval"] is True
        approved = browser.post(f"/api/agents/proposals/{reset['id']}/approve")
        assert approved.is_success, approved.text
        result = finished(browser, approved.json()["job_id"])
        assert result["status"] == "completed", result
        revised = result["result"]
        assert revised["status"] == "queued"
        assert revised["revision"] == record["revision"] + 1
        assert revised["form"] == recovered["form"]
        assert browser.post(f"/api/agents/proposals/{stale['id']}/approve").status_code == 400
        fresh = propose("fresh-send", "upload-send", revised["revision"])
        assert fresh["requires_owner_approval"] is True
        assert not posts
        assert source.read_bytes() == original


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_reconciles_interrupted_upload_only_after_confirmation(tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    root = tmp_path / "models"
    root.mkdir()
    source = root / "Object.stl"
    original = b"solid model\nendsolid model\n"
    source.write_bytes(original)
    child = multiprocessing.get_context("spawn").Process(
        target=_exit_during_upload, args=(tmp_path,)
    )
    child.start()
    try:
        child.join(20)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.kill()
            child.join()
    before = json.loads((tmp_path / "before.json").read_text())["draft"]
    posts = []

    def response(request):
        if request.method == "POST":
            posts.append(request)
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
    )
    app = application(tmp_path)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            shell_navigate(page, "upload")
            frame = page.frame_locator("#upload-frame")
            frame.locator("[data-tab=tracking]").click()
            expect(frame.locator(".track")).to_contain_text("Envoi lancé · vérifier sur c411")
            store = app.state.agent_service.setup.store
            recovered = store.local_draft(before["id"])
            frame.get_by_role("button", name="Voir le détail →").click()
            expect(frame.locator("#dialog")).to_contain_text("Vérifiez les brouillons sur c411")
            # Dismissing the reconciliation dialog must preserve the uncertain send.
            frame.get_by_role("button", name="Fermer", exact=True).click()
            assert store.local_draft(before["id"]) == recovered
            frame.get_by_role("button", name="Voir le détail →").click()
            frame.get_by_role(
                "button", name="J’ai vérifié c411, autoriser un nouvel essai", exact=True
            ).click()
            expect(frame.locator(".editor")).to_be_visible()
            revised = store.local_draft(before["id"])
            assert revised["revision"] == before["revision"] + 1
            assert revised["status"] == "queued"
            assert revised["form"] == recovered["form"]
            expect(frame.locator("#reviewed")).not_to_be_checked()
            frame.locator('[data-step="5"]').click()
            expect(frame.get_by_role("button", name="Créer le brouillon c411…")).to_be_disabled()
            expect(frame.locator('[data-action="reset-send"]')).not_to_be_visible()
            assert not posts
            assert source.read_bytes() == original
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()
