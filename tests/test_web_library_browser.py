"""Real browser workflow with isolated folders and a fake Torrent Client."""

import hashlib
import os
import socket
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_folder_explorer_and_candidate_review(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_web_library_review import EmptyClient
    from tests.torrents import make_torrent
    from torrentlinker.domain import ContentKind, LibraryFolder
    from torrentlinker.indexer import Candidate
    from torrentlinker.review import remember_candidates
    from torrentlinker.web.app import create_app
    from torrentlinker.web.security import ServerSecrets
    from torrentlinker.web.setup import Setup

    config, root = tmp_path / "config", tmp_path / "Library"
    config.mkdir()
    root.mkdir()
    books, films = root / "Books", root / "Films"
    books.mkdir()
    films.mkdir()
    local = books / "The Time Machine.epub"
    local.write_bytes(b"book" * 100)
    setup = Setup(config, (root,), ServerSecrets(config), lambda *args: EmptyClient())
    setup.configured = True
    setup.settings.library_folders = [LibraryFolder(books, 1, ContentKind.EBOOK)]
    setup.secrets.update({"indexer-api-key": "test-key"})
    setup.save()
    indexer = setup.indexer()
    found = Candidate(
        "The.Time.Machine.1895.EN.EPUB",
        400,
        "https://c411.org/download/example",
        seeders=12,
        infohash="a" * 40,
    )
    remember_candidates(setup.store, indexer, local, [found])
    key = hashlib.sha1(indexer.redact(found.download_url).encode()).hexdigest()
    setup.store.cache_torrent(key, make_torrent(local))
    app = create_app(config, password="test-password-long", service_override=setup)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(
                viewport={"width": 1600, "height": 1000}, locale="en-US", color_scheme="dark"
            )
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            assert not errors, errors
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("[data-view=library]").first.click()
            frame = page.frame_locator("#reseed-frame")
            frame.get_by_role("button", name="Folders", exact=True).click()
            frame.get_by_role("button", name="+ Add a folder", exact=True).click()
            frame.locator("[name=local]").fill(str(films))
            frame.locator("[name=kind]").select_option("movie")
            frame.locator("[name=scan]").uncheck()
            frame.locator("#folder-form .primary").click()
            expect(frame.locator(".folder-entry")).to_have_count(2)
            page.evaluate("location.hash='#/library/items'")
            page.locator("#scan").click()
            expect(page.locator("#library-table")).to_contain_text(
                "The Time Machine.epub", timeout=15000
            )
            page.locator("#library-table").get_by_role(
                "button", name="The Time Machine.epub", exact=True
            ).click()
            expect(page.locator("#candidate-table")).to_contain_text("Full Match", timeout=15000)
            page.locator("[data-candidate-tab=files]").click()
            expect(page.locator("#candidate-files")).to_contain_text("matched")
            destination = os.getenv("TL_WEB_SCREENSHOTS")
            if destination:
                Path(destination).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(destination) / "library-web.png"), full_page=True)
            page.locator("[data-candidate-tab=evidence]").click()
            page.locator("#inspect-evidence").click()
            expect(page.locator("#evidence-report")).to_contain_text(
                "No inconsistencies", timeout=15000
            )
            page.locator("#import-provenance").set_input_files(
                {
                    "name": "original.torrent",
                    "mimeType": "application/x-bittorrent",
                    "buffer": make_torrent(local),
                }
            )
            expect(page.locator("#evidence-report")).to_contain_text("Hash verified", timeout=15000)
            if destination:
                page.screenshot(
                    path=str(Path(destination) / "library-features-web.png"), full_page=True
                )
                page.locator("#language").select_option("fr")
                page.locator("#inspect-evidence").click()
                expect(page.locator("#evidence-report")).to_contain_text(
                    "Hashes vérifiés", timeout=15000
                )
                page.screenshot(
                    path=str(Path(destination) / "library-features-web-fr.png"), full_page=True
                )
                page.locator("#language").select_option("en")
            page.locator("[data-candidate-tab=files]").click()
            page.locator("#candidate-expand").click()
            expect(page.locator("#library-results")).to_be_hidden()
            expect(page.locator("#candidate-files")).to_contain_text("The Time Machine.epub")
            page.locator("#candidate-expand").click()
            expect(page.locator("#library-results")).to_be_visible()
            page.locator("#candidate-actions").get_by_role(
                "button", name="Reject Candidate", exact=True
            ).click()
            expect(page.locator("#candidate-table")).to_contain_text("No Candidates", timeout=15000)
            page.locator("#library-manage-folders").click()
            if destination:
                page.screenshot(
                    path=str(Path(destination) / "library-web-folders.png"), full_page=True
                )
            page.set_viewport_size({"width": 650, "height": 950})
            frame.get_by_role("button", name="+ Add a folder", exact=True).click()
            expect(frame.locator("#folder-form")).to_be_visible()
            page.locator("#language").select_option("fr")
            expect(frame.get_by_role("heading", name="Ajouter à la bibliothèque")).to_be_visible()
            expect(frame.locator("[name=local]")).to_be_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
