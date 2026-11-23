"""Opt-in browser coverage: known server errors reach the panels in the user's language."""

import os
import socket
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def serve(tmp_path):
    import uvicorn

    from torrentlinker.web.app import create_app

    app = create_app(
        tmp_path / "config", password="test-password-long", monitor_verifications=False
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
    return server, thread, f"http://127.0.0.1:{port}"


@pytest.mark.parametrize(
    ("locale", "torrents", "search"),
    [
        ("fr-FR", "Connectez d’abord votre client torrent", "Ajoutez d’abord votre clé API c411"),
        ("en-US", "Connect your Torrent Client in Settings first.", "Add your c411 API key"),
    ],
)
def test_unconfigured_errors_are_alerts_in_the_users_language(tmp_path, locale, torrents, search):
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate

    server, thread, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(locale=locale)
            page.goto(base + "/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "torrents")
            panel = page.frame_locator("#torrents-frame")
            alert = panel.locator(".tl-toast.bad[role=alert]").filter(has_text=torrents)
            expect(alert).to_be_visible()
            expect(panel.locator("#notice")).to_have_count(0)
            shell_navigate(page, "search")
            panel = page.frame_locator("#search-frame")
            panel.locator("#search-query").fill("film")
            panel.locator("#search-form .primary").click()
            expect(
                panel.locator(".tl-toast.bad[role=alert]").filter(has_text=search)
            ).to_be_visible()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)


def test_buttons_are_busy_while_they_run_and_errors_stay_until_closed(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate

    server, thread, base = serve(tmp_path)
    held = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(locale="fr-FR")
            page.goto(base + "/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "search")
            panel = page.frame_locator("#search-frame")
            holding = [True]
            page.route(
                "**/api/search/workspace/**",
                lambda route: held.append(route) if holding[0] else route.continue_(),
            )
            panel.locator("#search-query").fill("film")
            button = panel.locator("#search-form .primary")
            button.click()
            expect(button).to_be_disabled()
            expect(button).to_have_attribute("aria-busy", "true")
            expect(button).to_have_text("En cours…")
            holding[0] = False
            for route in held:
                route.continue_()
            expect(button).to_be_enabled()
            toast = panel.locator(".tl-toast.bad")
            expect(toast).to_be_visible()
            page.wait_for_timeout(4500)
            expect(toast).to_be_visible()  # an error stays until it is closed
            toast.get_by_role("button", name="Fermer").click()
            expect(toast).to_have_count(0)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
