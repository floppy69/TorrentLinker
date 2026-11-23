"""Members 5 (#132): Age Ratings in the Media panel of an actual browser."""

import os
import socket
import threading
import time

import pytest

from tests.shell_support import media_option, shell_navigate
from tests.test_web_media_browser import media_locator

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_the_owner_rates_unrated_films_from_the_media_menu(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    root = tmp_path / "media"
    root.mkdir()
    for name, rating in (("Oppenheimer", "FR:12"), ("Saw X", "US:R"), ("The Machine", "")):
        folder = root / name
        folder.mkdir()
        (folder / f"{name}.2023.mp4").write_bytes(b"not a real video")
        tag = f"<mpaa>{rating}</mpaa>" if rating else ""
        (folder / "movie.nfo").write_text(f"<movie><title>{name}</title>{tag}</movie>")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(language="en")
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
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.get_by_label("Server password").fill("test-password-long")
            page.locator("#login-form button.primary").click()
            shell_navigate(page, "media")
            media_option(page, "#media-refresh").click()
            media_locator(page, "#media-library-options > summary").click()
            entry = media_locator(page, "#media-ratings-entry")
            expect(entry).to_have_text("Unrated (2)", timeout=15000)
            media_option(page, "#media-ratings-entry").click()
            ratings = media_locator(page, "#media-ratings")
            expect(ratings.get_by_role("heading", name="Unrated")).to_be_visible()
            expect(ratings.get_by_text("NFO : R (United States) → −16 ?")).to_be_visible()
            expect(ratings.get_by_text("No rating found.")).to_be_visible()
            ratings.get_by_role("button", name="Confirm the 1 suggestions").click()
            expect(ratings.locator(".media-unrated")).to_have_count(1)
            machine = ratings.get_by_role("group", name="Rating of The Machine")
            machine.get_by_role("button", name="−10").click()
            expect(ratings.get_by_text("Every film has a rating.")).to_be_visible()
            expect(entry).to_have_text("Unrated")

            # Home: the title panel shows the rating before the year, and its source.
            media_locator(page, '[data-media-view="recent"]').click()
            expect(media_locator(page, "#media-ratings")).to_be_hidden()
            choice = media_locator(page, '.media-focus-choice[aria-label="Oppenheimer"]')
            choice.evaluate("node => node.click()")
            feature = media_locator(page, "#media-feature")
            expect(feature.locator(".media-feature-meta .media-age-rating")).to_have_text("−12")
            feature.get_by_label("About this selection", exact=True).click()
            expect(feature.get_by_text("Rating −12 · NFO file")).to_be_visible()
            feature.get_by_role("button", name="Edit").click()
            feature.get_by_role("button", name="−16").click()
            expect(feature.get_by_text("Rating −16 · the owner")).to_be_visible()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
