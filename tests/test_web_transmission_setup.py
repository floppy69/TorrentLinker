"""Adding a Transmission client on the web explains a refused .part option and can fix it."""

import json
import os
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.shell_support import shell_navigate
from torrentlinker.transmission import TransmissionApi
from torrentlinker.web.app import create_app


def fake_transmission():
    """A Transmission RPC with "Append .part to incomplete files' names" on, as by default."""
    state = {"rename-partial-files": True, "calls": []}

    def rpc(request):
        body = json.loads(request.content)
        if request.headers.get("X-Transmission-Session-Id") != "session":
            return httpx.Response(409, headers={"X-Transmission-Session-Id": "session"})
        state["calls"].append(body["method"])
        arguments = body["arguments"]
        if body["method"] == "session-set":
            state["rename-partial-files"] = arguments["rename-partial-files"]
            return httpx.Response(200, json={"result": "success", "arguments": {}})
        values = {
            "version": "4.0.6",
            "rename-partial-files": state["rename-partial-files"],
            "download-dir": "/downloads",
            "incomplete-dir": "",
            "incomplete-dir-enabled": False,
        }
        found = {name: values[name] for name in arguments.get("fields", [])}
        return httpx.Response(200, json={"result": "success", "arguments": found})

    def connector(kind, host, username, password, key):
        return TransmissionApi(
            host, username, password, http=httpx.Client(transport=httpx.MockTransport(rpc))
        )

    return state, connector


def test_refused_partial_names_are_explained_then_turned_off_on_request(tmp_path):
    state, connector = fake_transmission()
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        connector=connector,
        monitor_verifications=False,
    )
    connection = {
        "client": "transmission",
        "host": "http://192.0.2.10:9091",
        "username": "transmission",
        "password": "transmission",
        "name": "Transmission",
    }
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        assert browser.post("/api/login", json={"password": "test-password-long"}).is_success
        refused = browser.post("/api/setup/test-client", json=connection)
        # Reachable, so never "Cannot connect": the real reason and the offered fix.
        assert refused.status_code == 409
        assert ".part" in refused.json()["detail"]
        assert refused.json()["action"] == "turn_off_partial_names"
        assert state["rename-partial-files"] is True
        saved = browser.post(
            "/api/setup/client", json={**connection, "turn_off_partial_names": True}
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == "4.0.6"
        assert state["rename-partial-files"] is False
        assert "session-set" in state["calls"]


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_setup_form_offers_to_turn_off_partial_names(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    state, connector = fake_transmission()
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        connector=connector,
        monitor_verifications=False,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(locale="en-US")
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "setup")
            panel = page.frame_locator("#settings-frame")
            panel.get_by_label("Client type", exact=True).select_option("transmission")
            panel.get_by_label("Address", exact=True).fill("http://192.0.2.10:9091")
            test = panel.get_by_role("button", name="Test connection", exact=True)
            test.click()
            refused = panel.locator(".tl-toast.bad").filter(has_text=".part")
            expect(refused).to_be_visible()
            assert state["rename-partial-files"] is True
            panel.get_by_label("Turn off Transmission’s .part filenames when testing").check()
            test.click()
            expect(panel.locator(".tl-toast.ok").filter(has_text="4.0.6")).to_be_visible()
            assert state["rename-partial-files"] is False
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
