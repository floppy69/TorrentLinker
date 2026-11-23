"""Opt-in browser coverage: the app shell header, setup banner and phone drawer."""

import os

import pytest

from tests.test_toast_errors_browser import serve

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def sign_in(page, base):
    page.goto(base + "/")
    page.locator("#login-password").fill("test-password-long")
    page.locator("#login-form button").click()
    page.locator("#workspace").wait_for(state="visible")


def test_desktop_header_keeps_one_bar_and_no_duplicate_titles(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate

    server, thread, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800}, locale="fr-FR")
            sign_in(page, base)
            # The pill sits in the header, level with the toggle, not floating past the title row.
            header = page.locator("main > header")
            expect(page.locator("#work-status")).to_be_visible()
            pill = page.locator("#work-status").bounding_box()
            toggle = page.locator("#navigation-toggle").bounding_box()
            box = header.bounding_box()
            assert pill and toggle and box
            assert abs(pill["y"] - toggle["y"]) < 12
            assert pill["x"] + pill["width"] <= box["x"] + box["width"] + 1
            # The setup banner offers Settings, except on Settings itself.
            shell_navigate(page, "torrents")
            frame = page.frame_locator("#shell-header-frame")
            expect(frame.locator("#open-settings")).to_be_visible()
            for view, panel in (
                ("setup", "#settings-frame"),
                ("documentation", "#documentation-frame"),
            ):
                shell_navigate(page, view)
                expect(frame.locator("#page-title")).to_be_visible()
                title = page.frame_locator(panel).locator("h1").first
                assert title.evaluate("el => el.getBoundingClientRect().width") <= 1
            shell_navigate(page, "setup")
            expect(frame.locator("#open-settings")).to_be_hidden()
            # The section list scrolls inside the viewport instead of running past it.
            navigation = page.frame_locator("#settings-frame").locator("#settings-navigation")
            assert navigation.evaluate("el => getComputedStyle(el).position") == "sticky"
            assert navigation.evaluate("el => el.getBoundingClientRect().bottom <= innerHeight")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)


def test_phone_navigation_is_one_closed_drawer_with_the_preferences(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    server, thread, base = serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 800}, locale="fr-FR")
            sign_in(page, base)
            expect(page.locator("#app-sidebar")).to_be_hidden()
            assert page.locator("#shell-header-frame").bounding_box()["y"] < 120
            page.locator("#navigation-toggle").click()
            navigation = page.frame_locator("#shell-navigation-frame")
            expect(navigation.locator("#pages")).to_be_visible()
            expect(navigation.locator("#page-select")).to_be_hidden()
            for control in ("#theme", "#language", "#shortcuts"):
                expect(navigation.locator(control)).to_be_visible()
            navigation.locator('[data-view="documentation"]').click()
            expect(page.locator("#view-documentation")).to_be_visible()
            expect(page.locator("#app-sidebar")).to_be_hidden()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
