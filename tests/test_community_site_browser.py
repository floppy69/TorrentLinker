"""The Owner can join and revoke the Community Site through the shared Settings panel."""

import os
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from tests.shell_support import shell_navigate
from tests.test_community_site import admission, token
from tests.test_web_plan_execution import prepared
from torrentlinker.community_site import community_site
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_community_link_settings(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    setup.profile_workspace().refresh = lambda *args: SimpleNamespace(username="PrivatePerson")
    site = community_site(setup)
    replies = [
        (200, admission()),
        (200, token()),
        (200, {"name": "Site member", "forumAccess": False}),
        (200, {"ok": True}),
    ]

    # Keep response selection atomic and never contact an external service.
    def response(request):
        if request.url.path == "/api/device/identity":
            return httpx.Response(
                200, json={"accountId": "fixture-account", "installationId": "fixture-installation"}
            )
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    site.transport = httpx.MockTransport(response)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1400, "height": 1000}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                panel.get_by_role("button", name="Join the community", exact=True).click()
                panel.get_by_role("button", name="Get a link code").click()
                expect(panel.get_by_label("Community link code")).to_have_value("A1B2C3D4E5")
                expect(panel.get_by_role("link", name="Open the approval page")).to_have_attribute(
                    "href", "https://torrentlinker.fr/fr/link"
                )
                page.screenshot(path="/tmp/tl-community-link-settings.png", full_page=True)
                expect(panel.get_by_role("heading", name="App linked", exact=True)).to_be_visible(
                    timeout=15000
                )
                panel.get_by_role("button", name="Check connection").click()
                expect(panel.get_by_text("Site member · Forum approval pending")).to_be_visible()
                panel.get_by_role("button", name="Revoke this app's access").click()
                expect(panel.get_by_role("button", name="Get a link code")).to_be_visible()
                assert not errors and not replies
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)
