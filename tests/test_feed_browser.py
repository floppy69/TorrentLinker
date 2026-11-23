"""Opt-in browser coverage of RSS discovery and preview, against a fake source."""

import os
import re
import socket
import threading
import time

import pytest

from tests.shell_support import shell_navigate

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_rss_preview_sidebar_unread_and_saved_selection(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    source = Source()
    source.rows = [release(title="Baseline film")]
    app.state.agent_service.feed_control.feeds.indexer = lambda: source
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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1250, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "feeds")
            page.frame_locator("#feeds-frame").locator("#feeds-empty").get_by_role(
                "button", name="New subscription"
            ).click()
            editor = page.frame_locator("#feeds-frame").locator("#dialog-content")
            editor.get_by_label("Name", exact=True).fill("Films")
            editor.get_by_label("Title contains", exact=True).fill("film")
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 1 of 1")
            editor.get_by_role("button", name="Save", exact=True).click()
            films = (
                page.frame_locator("#feeds-frame")
                .locator("#feeds-sidebar")
                .get_by_role("button", name=re.compile("^Films"))
            )
            films.click()
            page.frame_locator("#feeds-frame").locator("#feeds-header").get_by_role(
                "button", name="Refresh now"
            ).click()
            expect(page.frame_locator("#feeds-frame").locator("#feeds-results")).to_contain_text(
                "Baseline film"
            )
            source.rows = [release("b", title="New film"), release(title="Baseline film")]
            page.frame_locator("#feeds-frame").locator("#feeds-header").get_by_role(
                "button", name="Refresh now"
            ).click()
            expect(page.frame_locator("#feeds-frame").locator("#feeds-sidebar")).to_contain_text(
                "Films"
            )
            expect(
                page.frame_locator("#feeds-frame").locator("#feeds-sidebar .feed-row-badge").nth(1)
            ).to_have_text("1")
            expect(page.frame_locator("#feeds-frame").locator("#feeds-actions")).to_be_hidden()
            row = (
                page.frame_locator("#feeds-frame")
                .locator("#feeds-results tbody tr")
                .filter(has_text="New film")
            )
            row.locator("input[type=checkbox]").check()
            expect(page.frame_locator("#feeds-frame").locator("#feeds-actions")).to_contain_text(
                "1 selected"
            )
            page.frame_locator("#feeds-frame").locator("#feeds-actions").get_by_role(
                "button", name="Save selection", exact=True
            ).click()
            expect(page.frame_locator("#feeds-frame").locator("#dialog-content")).to_contain_text(
                "New film"
            )
            page.frame_locator("#feeds-frame").locator("#dialog .close").click()
            page.frame_locator("#feeds-frame").locator("#feeds-header").get_by_label(
                "More", exact=True
            ).click()
            page.frame_locator("#feeds-frame").get_by_role(
                "menuitem", name="Saved selections", exact=True
            ).click()
            page.frame_locator("#feeds-frame").locator("#dialog-content").get_by_role(
                "button"
            ).first.click()
            expect(page.frame_locator("#feeds-frame").locator("#dialog-content")).to_contain_text(
                "New film"
            )
            expect(
                page.frame_locator("#feeds-frame")
                .locator("#dialog-content")
                .get_by_role("button", name="Queue selected", exact=True)
            ).to_be_visible()
            page.frame_locator("#feeds-frame").locator("#dialog .close").click()
            # An inbox-only release keeps RSS's destination-selection flow.
            page.frame_locator("#feeds-frame").locator("#feeds-results tbody tr").filter(
                has_text="New film"
            ).get_by_role("button").first.click()
            panel = page.frame_locator("#search-frame")
            expect(panel.locator(".dt-title")).to_contain_text("New film")
            expect(panel.get_by_role("button", name="Download now", exact=True)).to_have_count(0)
            panel.get_by_role("button", name="Add to queue", exact=True).click()
            expect(page.frame_locator("#feeds-frame").locator("#dialog-content")).to_contain_text(
                "Queue selected releases"
            )
            page.frame_locator("#feeds-frame").locator("#dialog .close").click()
            shell_navigate(page, "search")
            panel = page.frame_locator("#search-frame")
            panel.locator("#detail-tabs [role=tab]").first.click()
            panel.locator("#search-query").fill("A new title")
            panel.locator("#subscribe-search").click()
            expect(
                page.frame_locator("#feeds-frame")
                .locator("#dialog-content")
                .get_by_label("Title contains", exact=True)
            ).to_have_value("A new title")
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_rss_editor_chips_judge_fetched_releases(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    from torrentlinker.downloads import IndexerCategory

    source = Source()
    source.rows = [
        release("a", title="Good.1080p", metadata={"quality": "1080p"}),
        release("b", title="Other.720p", metadata={"quality": "720p"}),
    ]
    app.state.agent_service.feed_control.feeds.indexer = lambda: source
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
    app.state.agent_service.feed_control.service.setup.settings.indexer_categories = {
        2030: IndexerCategory("Films"),
        7020: IndexerCategory("Books"),
        1000: IndexerCategory("Games"),
        3010: IndexerCategory("Music"),
        4050: IndexerCategory("Applications"),
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1250, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "feeds")
            page.frame_locator("#feeds-frame").locator("#feeds-empty").get_by_role(
                "button", name="New subscription"
            ).click()
            editor = page.frame_locator("#feeds-frame").locator("#dialog-content")
            page.wait_for_timeout(1500)  # Includes the source debounce interval.
            expect(editor.locator(".feed-strip")).to_have_text("")
            expect(editor.locator(".feed-chip").filter(has_text="720p")).to_have_count(0)
            editor.get_by_role("button", name="Books", exact=True).click()
            expect(editor.locator(".feed-chip").filter(has_text="720p")).to_have_count(0)
            editor.get_by_role("button", name="Books", exact=True).click()
            for category, expected in (
                ("Games", ["Platform"]),
                ("Music", ["Format", "Bitrate"]),
                ("Applications", ["Platform", "License"]),
            ):
                editor.get_by_role("button", name=category, exact=True).click()
                labels = editor.locator(".feed-chip-label").all_text_contents()
                assert len(labels) == len(expected)
                assert all(any(label.startswith(name) for label in labels) for name in expected)
                expect(editor.locator(".feed-chip").filter(has_text="720p")).to_have_count(0)
                editor.get_by_role("button", name=category, exact=True).click()
            editor.get_by_role("button", name="Films", exact=True).click()
            editor.get_by_role("button", name="Check again", exact=True).click()
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 2 of 2")
            chip = editor.locator(".feed-chip").filter(has_text="720p")
            chip.click()
            expect(editor.locator(".feed-chip.prefer")).to_have_text("♡ 1. 720p")
            expect(editor.locator(".feed-chip.prefer")).to_be_focused()
            editor.locator(".feed-chip.prefer").click()
            expect(editor.locator(".feed-chip.must")).to_have_text("✓ 720p")
            expect(editor.locator(".feed-strip")).to_contain_text("Would match now: 1 of 2")
            expect(editor.locator(".feed-strip-titles")).to_have_text("Other.720p")
            editor.locator("summary", has_text="Advanced").click()
            expect(editor.locator("pre")).to_contain_text('"required"')
            editor.get_by_role("button", name="Films", exact=True).click()
            editor.get_by_role("button", name="Books", exact=True).click()
            expect(editor.locator(".feed-chip").filter(has_text="720p")).to_have_count(0)
            editor.locator("summary", has_text="Saved rules outside").click()
            expect(editor.locator(".feed-preserved-rule")).to_contain_text("720p")
            expect(editor.locator(".feed-preserved-rule input")).to_have_count(0)
            editor.get_by_role("button", name="Remove this rule", exact=True).click()
            expect(editor.locator(".feed-preserved-rule")).to_have_count(0)
            expect(editor.locator("pre")).not_to_contain_text('"quality": [')
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_rss_category_legend_and_rich_editor_roundtrip(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    source = Source()
    source.rows = [
        release("a", title="Good.1080p", metadata={"quality": "1080p"}),
        release("b", title="Other.720p", metadata={"quality": "720p"}),
    ]
    app.state.agent_service.feed_control.feeds.indexer = lambda: source
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
    from tests.test_feed_editor import RICH
    from torrentlinker.downloads import IndexerCategory

    control = app.state.agent_service.feed_control
    control.service.setup.settings.indexer_categories = {
        2030: IndexerCategory("Films"),
        7020: IndexerCategory("Books"),
        3010: IndexerCategory("Music"),
        4050: IndexerCategory("Applications"),
    }
    rich = control.feeds.save(RICH)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "feeds")
            panel = page.frame_locator("#feeds-frame")
            panel.locator("#feeds-sidebar").get_by_role("button", name=re.compile("^Rich")).click()
            panel.locator("#feeds-header").get_by_label("More", exact=True).click()
            panel.get_by_role("menuitem", name="Edit…", exact=True).click()
            editor = panel.locator("#dialog-content")
            editor.get_by_role("button", name="Selection legend", exact=True).click()
            expect(editor.locator("#criteria-legend")).to_be_visible()
            expect(editor.locator("#criteria-legend")).to_contain_text("Require")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(panel.locator("#dialog")).not_to_be_visible()
            saved = control.feeds.get(rich.id)
            assert saved.model_dump(exclude={"id"}) == RICH.model_dump(exclude={"id"})
            panel.locator("#feeds-side-head").get_by_role("button").click()
            editor = panel.locator("#dialog-content")
            editor.locator(".feed-cats summary").click()
            editor.get_by_label("Books", exact=True).check()
            editor.get_by_label("Music", exact=True).check()
            format_row = editor.locator(".feed-chip-row").filter(has_text=re.compile("^Format"))
            expect(format_row.locator(".category-tags")).to_contain_text("Books")
            expect(format_row.locator(".category-tags")).to_contain_text("Music")
            format_row.locator("input").fill("EPUB")
            format_row.locator("input").press("Enter")
            expect(format_row.locator(".prefer")).to_contain_text("EPUB")
            editor.get_by_label("Name", exact=True).fill("Mixed categories")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(editor.get_by_label("Nom", exact=True)).to_have_value("Mixed categories")
            expect(editor.get_by_role("button", name="Légende de sélection")).to_be_visible()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(editor.get_by_label("Name", exact=True)).to_have_value("Mixed categories")
            if folder := os.getenv("TL_RSS_SCREENSHOTS"):
                from pathlib import Path

                Path(folder).mkdir(parents=True, exist_ok=True)
                for lang in ("en", "fr"):
                    page.frame_locator("#shell-navigation-frame").locator(
                        "#language"
                    ).select_option(lang)
                    for theme in ("dark", "light"):
                        page.frame_locator("#shell-navigation-frame").locator(
                            "#theme"
                        ).select_option(theme)
                        editor.locator(".criterion-help").scroll_into_view_if_needed()
                        page.screenshot(path=str(Path(folder) / f"rss-web-{lang}-{theme}.png"))
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            page.set_viewport_size({"width": 390, "height": 844})
            assert panel.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
            editor.get_by_label("Name", exact=True).focus()
            reached_save = False
            for _ in range(150):
                page.keyboard.press("Tab")
                focused = panel.locator(":focus")
                expect(focused).to_be_in_viewport()
                if editor.get_by_role("button", name="Save", exact=True).evaluate(
                    "el => el === document.activeElement"
                ):
                    reached_save = True
                    break
            assert reached_save, "The RSS save action must be reachable by Tab"
            if folder:
                page.screenshot(path=str(Path(folder) / "rss-web-narrow.png"))
            page.set_viewport_size({"width": 1280, "height": 900})

            editor.get_by_role("radio", name=re.compile("Download automatically")).check()
            expect(editor.locator(".feed-limits")).to_be_visible()
            editor.get_by_role("radio", name=re.compile("Notify me")).check()
            expect(editor.locator(".feed-limits")).to_be_hidden()
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(panel.locator("#dialog")).not_to_be_visible()
            rule = next(x for x in control.feeds.subscriptions() if x["id"] != rich.id)
            assert rule["preferences"]["category_scopes"]["format"] == [7020, 3010]
            panel.locator("#feeds-sidebar").get_by_role(
                "button", name=re.compile("^Mixed categories")
            ).click()
            panel.locator("#feeds-header").get_by_label("More", exact=True).click()
            panel.get_by_role("menuitem", name="Edit…", exact=True).click()
            format_row = panel.locator(".feed-chip-row").filter(has_text=re.compile("^Format"))
            for _ in range(3):
                format_row.get_by_role("button", name=re.compile("^EPUB,")).click()
            panel.locator(".feed-cats summary").click()
            panel.get_by_label("Books", exact=True).uncheck()
            panel.get_by_label("Music", exact=True).uncheck()
            expect(format_row).to_have_count(0)
            panel.get_by_label("Music", exact=True).check()
            format_row.locator("input").fill("FLAC")
            format_row.locator("input").press("Enter")
            expect(format_row.locator(".category-tags")).to_have_text("Music")
            panel.get_by_role("button", name="Save", exact=True).click()
            expect(panel.locator("#dialog")).not_to_be_visible()
            assert control.feeds.get(rule["id"]).preferences.category_scopes["format"] == [3010]

            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_cancel_pending_preview_never_saves_and_repeated_save_is_locked(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_feeds import Source, release
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    source = Source()
    source.rows = [
        release("a", title="Good.1080p", metadata={"quality": "1080p"}),
        release("b", title="Other.720p", metadata={"quality": "720p"}),
    ]
    app.state.agent_service.feed_control.feeds.indexer = lambda: source
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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "feeds")
            panel = page.frame_locator("#feeds-frame")
            panel.locator("#feeds-empty").get_by_role("button").click()
            expect(panel.locator(".feed-strip")).to_have_text("")
            pending = []

            def hold_preview(route):
                if route.request.post_data_json.get("path") == "feeds/preview":
                    pending.append(route)
                else:
                    route.continue_()

            page.route("**/api/feeds/workspace", hold_preview)
            editor = panel.locator("#dialog-content")
            editor.get_by_label("Title contains", exact=True).fill("changed")
            save = editor.get_by_role("button", name=re.compile(r"^Sav(e|ing)"))
            save.click()
            expect(save).to_be_disabled()
            editor.get_by_role("button", name="Cancel", exact=True).click()
            page.wait_for_timeout(100)
            assert pending
            for route in pending:
                route.fulfill(json={"rows": [], "evaluations": {}})
            page.wait_for_timeout(100)
            assert app.state.agent_service.feed_control.feeds.subscriptions() == []
            page.unroute("**/api/feeds/workspace", hold_preview)
            panel.locator("#feeds-empty").get_by_role("button").click()
            expect(panel.locator(".feed-strip")).to_have_text("")
            panel.get_by_role("button", name="Save", exact=True).dblclick()
            expect(panel.locator("#dialog")).not_to_be_visible()
            assert len(app.state.agent_service.feed_control.feeds.subscriptions()) == 1
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
