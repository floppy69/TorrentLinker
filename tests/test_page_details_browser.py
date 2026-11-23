"""Opt-in browser coverage: Recherche, Assistant and the download queue when they are empty."""

import os

import pytest

from tests.test_toast_errors_browser import serve

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_empty_pages_offer_nothing_that_cannot_work(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate

    server, thread, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800}, locale="fr-FR")
            page.goto(base + "/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "search")
            search = page.frame_locator("#search-frame")
            # A sort label without a sort control, and actions with nothing to act on, are hidden.
            expect(search.locator(".results-sort")).to_be_hidden()
            expect(search.locator("#subscribe-search")).to_be_disabled()
            expect(search.locator("#search-clear")).to_be_disabled()
            search.locator("#search-query").fill("film")
            expect(search.locator("#subscribe-search")).to_be_enabled()
            shell_navigate(page, "assistant")
            conversations = page.frame_locator("#assistant-frame").locator(
                "#assistant-conversations"
            )
            expect(conversations).to_have_class("assistant-conversations assistant-empty")
            assert conversations.evaluate("el => getComputedStyle(el).resize") == "none"
            shell_navigate(page, "queue")
            panel = page.frame_locator("#search-frame")
            empty = panel.locator("#queue-table .empty")
            expect(empty).to_be_visible()
            assert empty.evaluate("el => parseFloat(getComputedStyle(el).paddingLeft)") >= 12
            expect(panel.locator(".queue-foot")).to_be_hidden()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
