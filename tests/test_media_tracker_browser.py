"""Media Home: tracker rows say why they are empty (#158); job cards stay on their page and
Activity speaks plainly (#159)."""

import os
import re
import socket
import threading
import time

import pytest

from tests.shell_support import media_option, shell_navigate
from tests.test_web_media_browser import media_locator

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def serve(tmp_path, language):
    import uvicorn

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    root = tmp_path / "media"
    root.mkdir()
    folder = root / "Oppenheimer"
    folder.mkdir()
    (folder / "Oppenheimer.2023.mp4").write_bytes(b"not a real video")
    (folder / "movie.nfo").write_text("<movie><title>Oppenheimer</title></movie>")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(language=language)
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    return server, thread, f"http://127.0.0.1:{listener.getsockname()[1]}/"


@pytest.mark.parametrize(
    ("locale", "language", "reason", "settings_button"),
    [
        ("en-US", "en", "Add your c411 API key in Settings", "Open Settings"),
        ("fr-FR", "fr", "Ajoutez votre clé API c411", "Ouvrir les paramètres"),
    ],
)
def test_tracker_rows_without_a_c411_key_say_so_and_open_settings(
    tmp_path, locale, language, reason, settings_button
):
    from playwright.sync_api import expect, sync_playwright

    server, thread, base = serve(tmp_path, language)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale=locale)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button.primary").click()
            shell_navigate(page, "media")
            media_option(page, "#media-refresh").click()
            media_locator(page, "#media-library-options > summary").click()
            rows = media_locator(page, "#media-home-rows")
            expect(rows.locator(".media-row-note").first).to_contain_text(reason, timeout=20000)
            expect(rows.locator(".media-row-skeleton")).to_have_count(0)
            expect(rows.get_by_role("button", name=settings_button).first).to_be_visible()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.parametrize(
    ("locale", "language", "title"),
    [("fr-FR", "fr", "Analyse des médias"), ("en-US", "en", "Media scan")],
)
def test_a_media_scan_card_stays_off_torrents_and_activity_has_no_raw_json(
    tmp_path, locale, language, title
):
    from playwright.sync_api import expect, sync_playwright

    server, thread, base = serve(tmp_path, language)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale=locale)
            page.goto(base)
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button.primary").click()
            shell_navigate(page, "media")
            media_option(page, "#media-refresh").click()
            media_locator(page, "#media-library-options > summary").click()
            expect(media_locator(page, "#media-home-rows .media-row-note").first).to_be_visible(
                timeout=20000
            )
            shell_navigate(page, "torrents")
            page.wait_for_timeout(1500)
            assert page.locator("#page-jobs").is_hidden()
            shell_navigate(page, "jobs")
            card = page.locator("#job-list .job").first
            expect(card).to_contain_text(title)
            text = page.locator("#job-list").inner_text()
            assert "{" not in text and "media scan" not in text
            card.get_by_role("button", name=re.compile("Details|Détails")).click()
            dialog = page.locator("#dialog-content")
            expect(dialog.locator("h2")).to_have_text(title)
            assert "{" not in dialog.inner_text()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.parametrize(
    ("locale", "language", "one", "many"),
    [("fr-FR", "fr", "1 élément", "2 éléments"), ("en-US", "en", "1 item", "2 items")],
)
def test_activity_status_line_agrees_the_item_count(tmp_path, locale, language, one, many):
    from playwright.sync_api import sync_playwright

    server, thread, base = serve(tmp_path, language)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(locale=locale)
            page.goto(base)
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button.primary").click()
            page.locator("#workspace").wait_for(state="visible")
            line = "n => jobStatus({status: 'running', progress: {items: n}})"
            assert page.evaluate(line, 1).endswith(f"· {one}")
            assert page.evaluate(line, 2).endswith(f"· {many}")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
