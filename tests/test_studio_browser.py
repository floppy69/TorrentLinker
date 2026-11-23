"""The shared Studio works through real Web routing, without external requests."""

import os
import socket
import threading
import time

import pytest

from tests.shell_support import shell_navigate
from tests.test_web_plan_execution import prepared
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_multitrack_studio_autosave_curve_and_render(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
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
                page = browser.new_page(viewport={"width": 1500, "height": 1100}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "media")
                panel = page.frame_locator("#media-frame")
                panel.get_by_role("button", name="Pre-rolls", exact=True).click()
                panel.get_by_role("button", name="Studio", exact=True).click()
                panel.get_by_role("button", name="New project", exact=True).click()
                expect(panel.locator("#studio-preview")).to_have_attribute(
                    "src", __import__("re").compile(r"data:image/jpeg;base64,")
                )
                panel.get_by_label("Project name", exact=True).fill("Browser Studio")
                panel.get_by_label("Project name", exact=True).press("Tab")
                expect(panel.locator("#studio-save-state")).to_contain_text("Saved locally")
                panel.get_by_role("button", name="Welcome", exact=True).click()
                expect(panel.get_by_label("Font size", exact=True)).to_be_visible()
                panel.get_by_label("Property", exact=True).select_option("scale")
                panel.get_by_label("Interpolation", exact=True).first.select_option("bezier")
                expect(
                    panel.get_by_label("Bezier curve editor; numeric handles below")
                ).to_be_visible()
                panel.get_by_role("button", name="Add track", exact=True).click()
                expect(panel.locator(".studio-track")).to_have_count(2)
                panel.get_by_role("button", name="Undo", exact=True).click()
                expect(panel.locator(".studio-track")).to_have_count(1)
                expect(panel.locator("#studio-preview")).to_have_js_property("naturalWidth", 640)
                page.screenshot(path="/tmp/tl-studio-editor.png", full_page=True)
                panel.get_by_role("button", name="Close", exact=True).click()
                page.evaluate(
                    "window.introsDone=false; void playPrerolls({steps:["
                    "{kind:'pause',seconds:60,title:'First'},"
                    "{kind:'pause',seconds:60,title:'Second'}]}).then(()=>window.introsDone=true)"
                )
                page.get_by_role("button", name="Skip clip", exact=True).click()
                expect(page.locator(".preroll-playback")).to_contain_text("2 / 2")
                page.get_by_role("button", name="Skip all · start film", exact=True).click()
                expect(page.locator(".preroll-playback")).to_have_count(0)
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=10)
