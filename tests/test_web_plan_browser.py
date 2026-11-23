"""Desktop planning capabilities remain usable through the visible WebUI."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.shell_support import shell_navigate
from tests.test_web_plan_execution import prepared, second_client
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def wait_for_route(page, routes):
    for _ in range(100):
        if routes:
            return
        page.wait_for_timeout(20)
    assert routes, "The expected delayed request did not arrive"


def test_review_sort_send_and_resume_plan_in_browser(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, client, rows = prepared(tmp_path)
    profile, second = second_client(tmp_path, setup, client)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
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
            page = browser.new_page(viewport={"width": 1600, "height": 1100}, locale="en-US")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            initial_load = []
            page.route("**/api/zen/plan?*", lambda route: initial_load.append(route))
            shell_navigate(page, "zen")
            page.locator("#zen-plan-tab").click()
            panel = page.frame_locator("#plan-frame")
            expect(panel.locator("#plan-send")).to_be_disabled()
            expect(panel.locator("#plan-limit-count")).to_be_disabled()
            wait_for_route(page, initial_load)
            for route in list(initial_load):
                route.continue_()
            page.unroute("**/api/zen/plan?*")
            expect(panel.locator("#plan-limit-count")).to_be_enabled()
            for control in (
                "plan-category",
                "plan-goal",
                "plan-budget",
                "plan-count",
                "plan-min-count",
                "plan-min-seeders",
                "plan-seeders",
                "plan-min-size",
                "plan-max-size",
                "plan-cached",
            ):
                expect(panel.locator(f"#{control}")).to_be_visible()
            panel.locator("#plan-limit-count").check()
            panel.locator("#plan-cached").check()
            panel.locator("#plan-category").select_option(["7000"])
            panel.locator("#plan-count").fill("2000")
            panel.locator("#plan-min-count").fill("2")
            panel.locator("#plan-min-seeders").fill("1")
            panel.locator("#plan-max-size").fill("1")
            panel.locator("[data-size-unit=max]").click()
            expect(panel.locator("#plan-max-size")).to_have_value("1024")
            expect(panel.locator("[data-size-unit=min]")).to_have_text("GiB")
            panel.locator("#plan-max-size").fill("0")
            panel.locator("#plan-options > summary").click()
            expect(panel.locator("#plan-budget")).not_to_be_visible()
            panel.locator("#plan-options > summary").click()
            expect(panel.locator("#plan-count")).to_have_value("2000")
            missing = []

            def missing_folder(route):
                if (
                    route.request.method == "POST"
                    and route.request.post_data_json.get("kind") == "plan"
                ):
                    missing.append(True)
                    route.fulfill(
                        status=400,
                        json={
                            "detail": "Choose an Ebook folder",
                            "action": {
                                "kind": "plan-folder",
                                "client_id": "default",
                                "category": 7000,
                            },
                        },
                    )
                else:
                    route.continue_()

            page.route("**/api/jobs", missing_folder)
            panel.locator("#plan").click()
            expect(panel.locator("#dialog")).to_be_visible()
            expect(panel.locator('#dialog select[aria-label="Category"]')).to_have_value("7000")
            expect(
                panel.locator('#dialog input[aria-label="Folder on the TorrentLinker host"]')
            ).to_have_value(setup.settings.download_folders.default)
            assert missing == [True]
            page.keyboard.press("Escape")
            page.unroute("**/api/jobs", missing_folder)
            panel.locator("#plan").click()
            expect(panel.locator("#plan-summary")).to_contain_text("paid back", timeout=15000)
            expect(panel.locator("#plan-storage")).to_contain_text("Reserved")
            expect(panel.locator("#plan-result tbody tr")).to_have_count(3)
            assert setup.settings.plan_options.min_torrents == 2
            assert setup.settings.plan_options.min_seeders == 1
            expect(panel.locator("#plan-sort")).to_have_count(0)
            panel.locator("#plan-query").fill("Alpha")
            expect(panel.locator("#plan-result tbody tr")).to_have_count(1)
            panel.locator("#plan-query").fill("")
            expect(panel.locator("#plan-result tbody tr")).to_have_count(3)
            expect(panel.locator("#plan-times")).to_contain_text("Sending")
            panel.locator("[data-sort=title]").click()
            expect(panel.locator("#plan-result tbody tr").first).to_contain_text("Alpha")
            panel.locator("#plan-budget").fill("12")
            expect(panel.locator("#plan-send")).to_be_disabled()
            panel.locator("#plan").click()
            expect(panel.locator("#plan-send")).to_be_enabled(timeout=15000)
            stale_load = []
            page.route("**/api/zen/plan?*", lambda route: stale_load.append((route, route.fetch())))
            shell_navigate(page, "torrents")
            shell_navigate(page, "zen")
            page.locator("#zen-plan-tab").click()
            panel.locator("#plan-result thead input").uncheck()
            panel.locator("#plan-result tbody input").first.check()
            panel.locator("#plan-send").click()
            expect(panel.locator("#dialog")).to_contain_text("1 download")
            assert client.downloads == []
            pending_send = []

            def hold_send(route):
                if (
                    route.request.method == "POST"
                    and route.request.post_data_json.get("kind") == "send-plan"
                ):
                    pending_send.append(route)
                else:
                    route.continue_()

            page.route("**/api/jobs", hold_send)
            panel.locator("#dialog").get_by_role("button", name="Send selected", exact=True).click()
            expect(panel.locator("#plan")).to_be_disabled()
            expect(panel.locator("#queue-plan")).to_be_disabled()
            wait_for_route(page, pending_send)
            assert len(pending_send) == 1
            wait_for_route(page, stale_load)
            assert stale_load
            for route, response in stale_load:
                route.fulfill(response=response)
            page.unroute("**/api/zen/plan?*")
            expect(panel.locator("#plan")).to_be_disabled()
            expect(panel.locator("#plan-stop")).to_be_visible()
            next_client_load = []
            next_client_url = f"**/api/zen/plan?client_id={profile.id}"
            page.route(
                next_client_url, lambda route: next_client_load.append((route, route.fetch()))
            )
            page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                profile.id
            )
            expect(
                page.frame_locator("#shell-header-frame").locator("#target-client")
            ).to_have_value(profile.id)
            wait_for_route(page, next_client_load)
            assert len(next_client_load) == 1
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith("/api/jobs")
                )
            ):
                pending_send[0].continue_()
            next_client_load[0][0].fulfill(response=next_client_load[0][1])
            page.unroute(next_client_url)
            expect(panel.locator(f'input[data-client-id="{profile.id}"]')).to_be_checked()
            page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                "default"
            )
            page.unroute("**/api/jobs", hold_send)
            expect(panel.locator("#plan-result tbody tr")).to_have_count(2, timeout=15000)

            assert len(client.downloads) == 1
            page.reload()
            shell_navigate(page, "zen")
            page.locator("#zen-plan-tab").click()
            panel = page.frame_locator("#plan-frame")
            expect(panel.locator("#plan-result tbody tr")).to_have_count(2)
            for control in (
                "plan-category",
                "plan-goal",
                "plan-budget",
                "plan-count",
                "plan-seeders",
                "plan-min-size",
                "plan-max-size",
                "plan-cached",
            ):
                expect(panel.locator(f"#{control}")).to_be_visible()
            expect(panel.locator("#plan-count")).to_have_value("2000")
            expect(panel.locator("#plan-budget")).to_have_value("12")
            expect(panel.locator("#plan-clients")).to_be_visible()
            panel.locator(f'input[data-budget-id="{profile.id}"]').fill("0.5")
            panel.locator("#plan-folders").click()
            expect(panel.locator("#dialog")).to_contain_text("TorrentLinker host")
            held_folder = []
            second_url = f"**/api/setup?client_id={profile.id}"
            page.route(second_url, lambda route: held_folder.append((route, route.fetch())))
            panel.locator('#dialog select[aria-label="Torrent Client"]').select_option(profile.id)
            expect(
                panel.locator("#dialog").get_by_role("button", name="Save folder", exact=True)
            ).to_be_disabled()
            wait_for_route(page, held_folder)
            assert len(held_folder) == 1
            panel.locator('#dialog select[aria-label="Torrent Client"]').select_option("default")
            expect(
                panel.locator('#dialog input[aria-label="Folder on the TorrentLinker host"]')
            ).to_have_value(setup.settings.download_folders.default)
            held_folder[0][0].fulfill(response=held_folder[0][1])
            page.unroute(second_url)
            expect(
                panel.locator('#dialog input[aria-label="Folder on the TorrentLinker host"]')
            ).to_have_value(setup.settings.download_folders.default)
            panel.locator('#dialog select[aria-label="Torrent Client"]').select_option(profile.id)
            expect(
                panel.locator('#dialog input[aria-label="Folder on the TorrentLinker host"]')
            ).to_have_value(profile.download_folders.default)
            panel.locator("#dialog").get_by_role("button", name="Save folder", exact=True).click()
            expect(panel.locator("#dialog")).to_contain_text(
                "Folder verified and saved", timeout=15000
            )
            page.keyboard.press("Escape")
            expect(panel.locator(f'input[data-budget-id="{profile.id}"]')).to_have_value("0.5")
            expect(panel.locator("#plan-send")).to_be_disabled()
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("dark")
            panel.locator("#plan-cached").check()
            panel.locator("#plan").click()
            expect(panel.locator("#plan-send")).to_be_enabled(timeout=15000)
            send_entered, send_release = threading.Event(), threading.Event()
            original_download = client.download

            def slow_download(*args):
                send_entered.set()
                assert send_release.wait(15)
                return original_download(*args)

            client.download = slow_download
            panel.locator("#plan-send").click()
            panel.locator("#dialog").get_by_role("button", name="Send selected", exact=True).click()
            try:
                assert send_entered.wait(5)
                expect(panel.locator("#plan-stop")).to_be_enabled()
                with page.expect_response(lambda response: response.url.endswith("/cancel")):
                    panel.locator("#plan-stop").click()
            finally:
                send_release.set()
                client.download = original_download
            expect(panel.locator("#plan-outcome")).to_contain_text("Stopped", timeout=15000)
            expect(panel.locator("#plan-outcome")).to_contain_text("1 added")
            expect(panel.locator("#plan-stop")).to_be_hidden()
            if destination := os.getenv("TL_WEB_SCREENSHOTS"):
                Path(destination).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(destination) / "web-plan-parity.png"), full_page=True)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(panel.locator("#plan-summary")).to_contain_text("amorti")
            page.set_viewport_size({"width": 390, "height": 844})
            panel.locator("#plan-min-count").focus()
            panel.locator("#plan-min-count").press("Tab")
            expect(panel.locator("#plan-min-seeders")).to_be_focused()
            expect(panel.locator("#plan-min-seeders")).to_be_in_viewport()
            expect(panel.locator("#plan-min-count")).to_have_value("2")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if destination := os.getenv("TL_WEB_SCREENSHOTS"):
                page.screenshot(
                    path=str(Path(destination) / "web-plan-mobile-fr.png"), full_page=True
                )
            # A Catalogue fetch belongs to the shared cache even after changing clients.
            import httpx

            from torrentlinker.indexer import Indexer

            entered, release = threading.Event(), threading.Event()

            def catalogue_response(request):
                entered.set()
                assert release.wait(10)
                return httpx.Response(200, text="<rss><channel></channel></rss>")

            setup.settings.indexer.url = "https://tracker.example/api"
            setup._indexer = Indexer(
                setup.settings.indexer.url,
                "test-key",
                cache=setup.store,
                http=httpx.Client(transport=httpx.MockTransport(catalogue_response)),
            )
            page.set_viewport_size({"width": 1600, "height": 1100})
            page.locator("#zen-catalogue-tab").click()
            catalogue = page.frame_locator("#catalogue-frame")
            catalogue.locator("#catalogue-fetch").click()
            try:
                assert entered.wait(5)
                page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                    profile.id
                )
                expect(catalogue.locator("#catalogue-fetch")).to_be_disabled()
                catalogue.locator("#catalogue-pause").click()
            finally:
                release.set()
            expect(catalogue.locator("#catalogue-fetch")).to_be_enabled(timeout=15000)
            expect(catalogue.locator("#catalogue-pause")).to_be_hidden()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
