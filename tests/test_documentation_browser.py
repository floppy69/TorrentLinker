"""The same guide reader on the owner Web UI, including reverse-proxy mounts."""

import os
import socket
import threading
import time

import pytest

from tests.shell_support import shell_navigate

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


@pytest.mark.parametrize("root_path", ["", "/tl"])
def test_guides_filter_history_language_images_and_retry(tmp_path, root_path):
    import uvicorn
    from fastapi import FastAPI
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.web.app import create_app

    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    if root_path:
        mounted = FastAPI()
        mounted.mount(root_path, app)
        app = mounted
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
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}{root_path}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "documentation")
            panel = page.frame_locator("#documentation-frame")
            expect(panel.locator("#guide-content h1")).to_have_text("Install and configure")
            panel.locator('[data-guide-path="guide/en/torrents.md"]').click()
            expect(panel.locator("#guide-content h1")).to_have_text("Manage torrents")
            expect(panel.locator("#guide-content img").first).to_be_visible()
            expect(panel.locator("#guide-content img").first).to_have_js_property("complete", True)
            assert panel.locator("#guide-content img").first.evaluate("i=>i.naturalWidth>0")
            panel.get_by_role("button", name="Back", exact=True).click()
            expect(panel.locator("#guide-content h1")).to_have_text("Install and configure")
            panel.get_by_role("button", name="Forward", exact=True).click()
            expect(panel.locator("#guide-content h1")).to_have_text("Manage torrents")
            # A slow language index must not replace a later guide selection.
            delayed = []
            page.route("**/api/documentation?language=fr", lambda route: delayed.append(route))
            panel.get_by_label("Guide language", exact=True).select_option("fr")
            panel.locator('[data-guide-path="guide/en/media.md"]').click()
            expect(panel.locator("#guide-content h1")).to_contain_text("Media")
            assert len(delayed) == 1
            response = page.request.get(delayed[0].request.url)
            delayed[0].fulfill(response=response)
            page.unroute("**/api/documentation?language=fr")
            page.wait_for_timeout(200)  # Allow the released response to reach the iframe.
            expect(panel.locator("#guide-language")).to_have_value("en")
            expect(panel.locator("#guide-content h1")).to_contain_text("Media")
            panel.locator('[data-guide-path="guide/en/torrents.md"]').click()
            expect(panel.locator("#guide-content h1")).to_have_text("Manage torrents")
            panel.get_by_label("Guide language", exact=True).select_option("fr")
            expect(panel.locator("#guide-content h1")).to_have_text("Gérer les torrents")
            panel.get_by_label("Filter guides", exact=True).fill("assistant")
            expect(panel.locator('[data-guide-path="guide/fr/torrents.md"]')).to_be_hidden()
            expect(panel.locator('[data-guide-path="guide/fr/assistant.md"]')).to_be_visible()
            panel.get_by_label("Filter guides", exact=True).fill("not-a-guide")
            expect(panel.locator("#guide-empty")).to_have_text("No matching guide")
            panel.get_by_label("Filter guides", exact=True).fill("")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("light")
            expect(panel.locator("html")).to_have_attribute("data-theme", "light")
            # Guide language remains an independent choice when the shell changes.
            panel.get_by_label("Langue du guide", exact=True).select_option("en")
            expect(panel.locator("#guide-content h1")).to_have_text("Manage torrents")
            shell_navigate(page, "torrents")
            shell_navigate(page, "documentation")
            expect(panel.locator("#guide-language")).to_have_value("en")
            expect(panel.locator("#guide-content h1")).to_have_text("Manage torrents")
            page.route(
                "**/api/documentation/page/guide/en/media.md",
                lambda route: route.fulfill(status=503, json={"detail": "Fixture unavailable"}),
            )
            panel.locator('[data-guide-path="guide/en/media.md"]').click()
            expect(panel.locator("#guide-status")).to_contain_text("indisponible")
            page.unroute("**/api/documentation/page/guide/en/media.md")
            panel.get_by_role("button", name="Réessayer", exact=True).click()
            expect(panel.locator("#guide-content h1")).to_contain_text("Media")
            page.set_viewport_size({"width": 390, "height": 844})
            assert panel.locator("html").evaluate("e=>e.scrollWidth<=innerWidth")
            if output := os.getenv("TL_DOC_SCREENSHOTS"):
                from pathlib import Path

                Path(output).mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(Path(output) / f"web-mobile{'-mounted' if root_path else ''}.png")
                )
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()
