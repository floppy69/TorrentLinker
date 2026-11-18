"""Browser acceptance of the real workflow; only the Torrent Client is simulated."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.test_reseed_workspace import CheckingClient, workspace
from torrentlinker.web.app import create_app
from torrentlinker.web.operations import Operations


def reseed_app(root, client=None):
    board, client, original, links, meta = workspace(root, client)
    board.setup.save()

    def operations(setup):
        result = Operations(setup)
        result.library.entries = board.library.entries
        return result

    app = create_app(
        root / "config",
        password="test-password-long",
        service_override=board.setup,
        operation_factory=operations,
    )
    return app, board, client, original, links, meta


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_reseed_board_runs_pauses_and_preserves_original_on_small_screen(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    class SlowCheck(CheckingClient):
        release = threading.Event()

        def torrent(self, hash, **kwargs):
            if not self.release.is_set():
                return self.by_hash.get(hash)
            return super().torrent(hash, **kwargs)

    client = SlowCheck()
    app, board, _, original, links, meta = reseed_app(tmp_path, client)
    before = original.read_bytes(), original.stat().st_ino
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
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("localStorage.setItem('tl-theme','dark')")
            page.goto(f"http://127.0.0.1:{port}/#/library/reseed")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            frame = page.frame_locator("#reseed-frame")
            expect(frame.locator(".torrent")).to_contain_text(original.name)
            expect(frame.locator("body")).to_have_css("padding-right", "16px")
            assert page.locator("#reseed-frame").evaluate(
                "el => el.getBoundingClientRect().bottom <= innerHeight - 16"
            )

            page.locator("#language").select_option("en")
            expect(frame.get_by_role("button", name="Run all", exact=True)).to_be_visible()
            expect(frame.locator("html")).to_have_attribute("lang", "en")
            frame.get_by_role("button", name="Folders", exact=True).click()
            frame.get_by_role("button", name="Edit", exact=True).first.click()
            expect(frame.get_by_role("heading", name="Edit folder")).to_be_visible()
            expect(frame.locator("#folder-live")).to_contain_text(original.name)
            frame.get_by_label("Item grouping", exact=True).select_option("1")
            frame.get_by_label("Scan after saving", exact=True).uncheck()
            frame.get_by_role("button", name="Save", exact=True).click()
            expect(frame.locator("#dialog")).not_to_be_visible()
            expect(frame.locator(".folder-entry").first).to_contain_text("Depth 1")
            frame.get_by_role("button", name="Activity", exact=True).click()
            expect(frame.get_by_text("Upcoming transitions will appear here.")).to_be_visible()
            frame.get_by_role("button", name="Reseed", exact=True).click()
            frame.locator(".guided button").nth(1).click()
            expect(frame.get_by_role("heading", name="Browse my folders")).to_be_visible()
            frame.get_by_role("button", name="Close", exact=True).click()
            page.locator("#language").select_option("fr")
            expect(frame.get_by_role("button", name="Tout enchaîner", exact=True)).to_be_visible()
            frame.locator(".guided button").first.click()
            frame.get_by_role("button", name="Parcourir…").click()
            frame.get_by_role("button", name=str(links), exact=True).click()
            frame.get_by_role("button", name="Choisir ce dossier", exact=True).click()
            expect(frame.locator("#root-form [name=path]")).to_have_value(str(links))
            frame.get_by_role("button", name="Enregistrer", exact=True).click()
            expect(frame.locator("#dialog")).not_to_be_visible()
            page.reload()
            expect(frame.locator(".guided button").first).to_contain_text(
                "Dossier de liens configuré"
            )
            page.on("dialog", lambda dialog: dialog.accept())
            frame.get_by_role("button", name="Tout enchaîner", exact=True).click()
            expect(frame.locator(".torrent .badge")).to_contain_text("Vérifier", timeout=20000)
            frame.get_by_role("button", name="Suspendre le parcours", exact=True).click()
            expect(frame.get_by_role("button", name="Reprendre le parcours")).to_be_visible(
                timeout=10000
            )
            client.release.set()
            assert not client.started
            page.reload()
            expect(frame.get_by_role("button", name="Reprendre le parcours")).to_be_visible(
                timeout=10000
            )
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            frame.get_by_role("button", name="Reprendre le parcours", exact=True).click()
            expect(frame.locator(".torrent .badge")).to_have_text("En partage", timeout=20000)
            assert client.started == [meta.infohash]
            frame.locator(".torrent").click()
            expect(frame.locator(".inspector")).to_contain_text("Release.mkv")
            expect(frame.locator(".inspector")).to_contain_text(str(original))
            frame.locator(".inspector").get_by_role("button", name="Fermer", exact=True).click()
            page.locator("#theme").select_option("light")
            expect(frame.locator("html")).to_have_attribute("data-theme", "light")
            page.locator("#theme").select_option("dark")
            expect(frame.locator("html")).to_have_attribute("data-theme", "dark")
            destination = os.getenv("TL_WEB_SCREENSHOTS")
            if destination:
                Path(destination).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(destination) / "reseed-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1560, "height": 1000})
                frame.locator("body").evaluate("() => window.scrollTo(0,0)")
                page.screenshot(path=str(Path(destination) / "reseed-web.png"), full_page=True)
            assert not errors
            assert (original.read_bytes(), original.stat().st_ino) == before
            browser.close()
    finally:
        client.release.set()
        server.should_exit = True
        thread.join(15)
