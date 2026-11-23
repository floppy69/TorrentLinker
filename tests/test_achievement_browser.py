"""Shared Settings UI drives real consent handlers against an isolated Site transport."""

import json
import os
import socket
import threading
import time

import pytest

from tests.test_achievement_sync import linked
from tests.test_web_plan_execution import prepared
from torrentlinker.community_site import LINK_SECRET, community_site
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_sharing_controls_pending_feedback_and_no_claim_endpoint(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate

    fake, remote, calls, _ = linked(tmp_path / "site-fixture")
    (tmp_path / "app").mkdir()
    config, setup, client, _ = prepared(tmp_path / "app")
    setup.connector = lambda *a, **k: client
    setup.secrets.update(
        {LINK_SECRET: json.dumps({"token": "fixture-original", "expires": time.time() + 7776000})}
    )
    site = community_site(setup)
    site.transport = fake.site.transport
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
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
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                panel.get_by_role("button", name="Join the community", exact=True).click()
                expect(panel.get_by_role("heading", name="App achievements")).to_be_visible()
                account_link = panel.get_by_role("link", name="Open my account on the site")
                expect(account_link).to_have_attribute(
                    "href", "https://torrentlinker.fr/en/space/account"
                )
                assert (
                    account_link.evaluate(
                        "a => a.parentElement.nextElementSibling.getBoundingClientRect().top"
                        " - a.getBoundingClientRect().bottom"
                    )
                    >= 16
                )
                panel.get_by_role("button", name="Share future achievements", exact=True).click()
                expect(
                    panel.get_by_role("button", name="Pause on this installation")
                ).to_be_visible()
                expect(panel.get_by_text("Pending badges : 0")).to_be_visible()
                site.achievements.ledger.complete("owner", "playlist", "browser-playlist")
                panel.get_by_role("button", name="Sync now", exact=True).click()
                expect(panel.get_by_text("✓ First playlist", exact=True)).to_be_visible()
                assert any(
                    r.url.path == "/api/app-achievements" and r.method == "POST" for r in calls
                )
                panel.get_by_role("button", name="Pause on this installation").click()
                expect(
                    panel.get_by_role("button", name="Share future achievements", exact=True)
                ).to_be_visible()
                expect(
                    panel.get_by_text("Paused on this installation.", exact=False)
                ).to_be_visible()
                expect(
                    panel.get_by_role("link", name="Consent and badge visibility")
                ).to_have_attribute("href", "https://torrentlinker.fr/en/space/achievements")
                page.screenshot(path="/tmp/tl-achievements-settings.png", full_page=True)
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)
            fake.close()
