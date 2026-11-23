"""The same Seeding hierarchy and owner expansion in the Web host."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI

from tests.shell_support import shell_navigate
from tests.test_web_plan_execution import prepared, second_client
from tests.test_web_seeding import torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.store import CatalogueRow
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


@pytest.mark.parametrize("root_path", ["", "/tl"])
def test_ten_thousand_torrents_have_bounded_rows_and_global_search(tmp_path, root_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, client, _ = prepared(tmp_path)
    client.by_hash = {
        row.hash: row for row in (torrent(i, f"Release {i:05d}", size=i + 1) for i in range(10001))
    }
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    if root_path:
        mounted = FastAPI()
        mounted.mount(root_path, app)
        app = mounted
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
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}{root_path}/")
                page.locator("#login-password").fill("test-password-long")
                page.locator("#login-form button").click()
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "dark"
                )
                shell_navigate(page, "zen")
                page.locator("#zen-seeding-tab").click()
                panel = page.frame_locator("#seeding-frame")
                expect(panel.locator("#seeding-result tbody tr")).to_have_count(100)
                expect(panel.locator("#seeding-page")).to_contain_text("10001")
                expect(panel.locator("#seeding-sort")).to_have_count(0)
                expect(panel.locator(".filters [data-filter]")).to_have_count(4)
                panel.locator(".metric-filters > summary").click()
                panel.locator('[data-unit="sizeMin"]').click()
                panel.locator('[data-metric="sizeMin"]').fill("0.009")
                panel.locator('[data-metric="sizeMin"]').press("Tab")
                expect(panel.locator("#seeding-page")).to_contain_text("/ 564")
                panel.locator("#clear-filters").click()
                expect(panel.locator("#seeding-page")).to_contain_text("/ 10001")
                panel.locator('[data-sort="size"]').click()
                expect(panel.locator("tbody tr").first).to_contain_text("Release 00000")
                panel.locator("#seeding-last").click()
                expect(panel.locator("tbody tr")).to_have_count(1)
                expect(panel.locator("tbody")).to_contain_text("Release 10000")
                panel.locator("#seeding-query").fill("Release 09999")
                expect(panel.locator("tbody tr")).to_have_count(1)
                expect(panel.locator("tbody")).to_contain_text("Release 09999")
                panel.locator("#seeding-query").fill("")
                expect(panel.locator("tbody tr")).to_have_count(100)
                assert (
                    panel.locator("body").evaluate("node=>node.querySelectorAll('*').length") < 1600
                )
                if output := os.getenv("TL_SEEDING_SCREENSHOTS"):
                    Path(output).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(output) / "web-10001-en-dark.png"))
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "fr"
                )
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "light"
                )
                page.set_viewport_size({"width": 390, "height": 844})
                expect(panel.locator("html")).to_have_attribute("lang", "fr")
                expect(panel.locator("#seeding-query")).to_have_attribute(
                    "placeholder", "Rechercher un torrent…"
                )
                assert panel.locator("html").evaluate("node=>node.scrollWidth<=innerWidth")
                if output:
                    page.screenshot(path=str(Path(output) / "web-10001-mobile-fr-light.png"))
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(10)


@pytest.mark.parametrize("root_path", ["", "/tl"])
def test_seeding_hierarchy_sort_filter_owner_memory_and_client_switch(
    tmp_path, root_path, monkeypatch
):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, client, _ = prepared(tmp_path)
    profile, second = second_client(tmp_path, setup, client)
    client.by_hash = {
        row.hash: row for row in [torrent(1, "Small", size=1000), torrent(2, "Large", size=1000000)]
    }
    second.by_hash = {row.hash: row for row in [torrent(3, "Remote book")]}
    setup.settings.indexer_categories = {
        7000: IndexerCategory("Books"),
        7010: IndexerCategory("Comics", 7000),
    }
    setup.store.save_catalogue(
        [
            CatalogueRow(row.hash, row.name, row.size, 11, 7010, "", "", 0)
            for row in client.by_hash.values()
        ]
    )
    setup.save()
    refresh_started, release_refresh = threading.Event(), threading.Event()
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    if root_path:
        mounted = FastAPI()
        mounted.mount(root_path, app)
        app = mounted
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
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}{root_path}/")
                page.locator("#login-password").fill("test-password-long")
                page.locator("#login-form button").click()
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "en"
                )
                shell_navigate(page, "zen")
                page.locator("#zen-seeding-tab").click()
                panel = page.frame_locator("#seeding-frame")
                expect(panel.locator(".seeding-category")).to_have_count(2)
                if panel.locator("#seeding-category-totals").get_attribute("open") is None:
                    panel.locator("#seeding-category-totals > summary").click()
                panel.locator("#seeding-expand").click()
                expect(panel.locator("tbody tr")).to_have_count(2)
                panel.locator('[data-sort="size"]').click()
                expect(panel.locator("tbody tr").first).to_contain_text("Small")
                panel.locator("#seeding-query").fill("large")
                expect(panel.locator("tbody tr")).to_have_count(1)
                expect(panel.locator("tbody")).to_contain_text("Large")
                panel.locator("#seeding-query").fill("")
                expect(panel.locator("tbody tr")).to_have_count(2)
                page.reload()
                shell_navigate(page, "zen")
                page.locator("#zen-seeding-tab").click()
                expect(panel.locator(".seeding-category[open]")).to_have_count(2)
                page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                    profile.id
                )
                expect(panel.locator(".seeding-category[open]")).to_have_count(0)
                panel.locator("#seeding-refresh").click()
                expect(panel.locator("#seeding-refresh")).to_be_enabled(timeout=15000)
                if panel.locator("#seeding-category-totals").get_attribute("open") is None:
                    panel.locator("#seeding-category-totals > summary").click()
                panel.locator("#seeding-expand").click()
                expect(panel.locator("tbody")).to_contain_text("Remote book")
                page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                    "default"
                )
                expect(panel.locator(".seeding-category[open]")).to_have_count(2)
                expect(panel.locator("tbody tr")).to_have_count(2)
                original = client.torrents

                def held_refresh(*args, **kwargs):
                    refresh_started.set()
                    assert release_refresh.wait(20)
                    return original(*args, **kwargs)

                monkeypatch.setattr(client, "torrents", held_refresh)
                panel.locator("#seeding-refresh").click()
                assert refresh_started.wait(5)
                page.reload()
                shell_navigate(page, "zen")
                page.locator("#zen-seeding-tab").click()
                expect(panel.locator("#seeding-refresh")).to_be_disabled()
                client.by_hash[torrent(1).hash] = torrent(1, "Updated during refresh", size=1000)
                release_refresh.set()
                expect(panel.locator("#seeding-refresh")).to_be_enabled(timeout=15000)
                if panel.locator("#seeding-category-totals").get_attribute("open") is None:
                    panel.locator("#seeding-category-totals > summary").click()
                panel.locator("#seeding-expand").click()
                expect(panel.locator("#seeding-result")).to_contain_text("Updated during refresh")
                panel.locator("#seeding-collapse").click()
                if panel.locator("#seeding-category-totals").get_attribute("open") is None:
                    panel.locator("#seeding-category-totals > summary").click()
                panel.locator("#seeding-expand").click()
                panel.locator("#seeding-uploads").fill("10")
                panel.locator("#seeding-save-uploads").click()
                expect(panel.locator("#seeding-classes")).to_contain_text("4.3")
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "fr"
                )
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "light"
                )
                expect(panel.locator("html")).to_have_attribute("lang", "fr")
                expect(panel.locator("#seeding-query")).to_have_attribute(
                    "placeholder", "Rechercher un torrent…"
                )
                expect(panel.locator("html")).to_have_attribute("data-theme", "light")
                if output := os.getenv("TL_SEEDING_SCREENSHOTS"):
                    Path(output).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(output) / "web-desktop-fr-light.png"))
                page.set_viewport_size({"width": 390, "height": 844})
                assert panel.locator("html").evaluate("node=>node.scrollWidth<=innerWidth")
                if output:
                    page.screenshot(path=str(Path(output) / "web-mobile-fr-light.png"))
                panel.locator("#seeding-collapse").click()
                expect(panel.locator(".seeding-category[open]")).to_have_count(0)
                assert not errors, errors
                browser.close()
        finally:
            release_refresh.set()
            server.should_exit = True
            worker.join(10)
