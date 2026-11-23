"""Real owner Web Catalogue controls using a simulated indexer."""

import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest

from tests.shell_support import shell_navigate
from tests.test_catalogue_sync import native_indexer
from tests.test_web_plan_execution import prepared, second_client
from torrentlinker.catalogue_sync import LISTED_ROOTS
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


@pytest.mark.parametrize("switch_client", [False, True, "load"])
def test_category_fetch_pause_resume_all_language_and_failure(tmp_path, switch_client):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, client, _ = prepared(tmp_path)
    other, _ = second_client(tmp_path, setup, client)
    entered, release = threading.Event(), threading.Event()
    roots = []

    def listing(request):
        if "category" in request.url.params:
            roots.append(int(request.url.params["category"]))
            entered.set()
            assert release.wait(15)
        return httpx.Response(
            200,
            json={
                "data": [],
                "meta": {"page": 1, "perPage": 100, "total": 0, "totalPages": 1, "categories": []},
            },
        )

    setup._indexer = native_indexer(listing)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
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
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "zen")
            page.locator("#zen-catalogue-tab").click()
            panel = page.frame_locator("#catalogue-frame")
            expect(panel.locator(".category")).to_have_count(len(LISTED_ROOTS))
            expect(panel.locator('[data-root="2"] .number')).to_have_text("3")
            delayed = []

            def delay_poll(route):
                if route.request.method == "GET" and not delayed:
                    delayed.append((route, page.request.get(route.request.url)))
                else:
                    route.continue_()

            page.route("**/api/jobs", delay_poll)
            # Hold one idle poll until a later fetch has started.
            for _ in range(150):
                if delayed:
                    break
                page.wait_for_timeout(20)
            assert delayed
            panel.get_by_role("button", name="Fetch only Audio", exact=True).click()
            expect(panel.locator("#catalogue-pause")).to_be_visible()
            assert entered.wait(5)
            expect(panel.locator("#catalogue-pause")).to_be_enabled()
            delayed[0][0].fulfill(response=delayed[0][1])
            page.unroute("**/api/jobs")
            page.wait_for_timeout(200)
            assert panel.locator("#catalogue-fetch").is_disabled()
            assert panel.locator("#catalogue-pause").is_visible()
            page.reload()
            shell_navigate(page, "zen")
            page.locator("#zen-catalogue-tab").click()
            expect(panel.locator("#catalogue-pause")).to_be_visible()
            panel.locator("#catalogue-pause").click()
            expect(panel.locator("#catalogue-status")).to_contain_text("Pausing")
            release.set()
            expect(panel.locator("#catalogue-fetch")).to_be_enabled(timeout=15000)
            assert set(roots) == {3}
            panel.locator("#catalogue-fetch").click()
            expect(panel.locator("#catalogue-fetch")).to_be_enabled(timeout=15000)
            expect(panel.locator('[data-root="1"] .chip')).to_have_text("Up to date", timeout=15000)
            expect(panel.locator('[data-root="3"] .chip')).to_have_text("Up to date", timeout=15000)
            assert set(roots) == set(LISTED_ROOTS)
            page.route(
                "**/api/jobs",
                lambda route: (
                    route.fulfill(status=503, json={"detail": "Fixture unavailable"})
                    if route.request.method == "POST"
                    else route.continue_()
                ),
            )
            panel.get_by_role("button", name="Fetch only Audio", exact=True).click()
            expect(panel.locator(".tl-toast.bad")).to_contain_text("Fixture unavailable")
            page.unroute("**/api/jobs")
            panel.get_by_role("button", name="Retry", exact=True).click()
            expect(panel.locator("#catalogue-fetch")).to_be_enabled(timeout=15000)
            expect(panel.locator("#catalogue-error")).to_be_hidden()
            # Plan now retains the client at the gesture while cancellation waits.
            release.clear()
            entered.clear()
            panel.get_by_role("button", name="Fetch only Audio", exact=True).click()
            expect(panel.locator("#catalogue-pause")).to_be_enabled()
            assert entered.wait(5)
            cancellations = []
            page.route(
                "**/cancel",
                lambda route: cancellations.append(
                    (route, None if switch_client is True else route.fetch())
                ),
            )
            delayed_plan = []
            if switch_client == "load":
                page.route(
                    "**/api/zen/plan?*", lambda route: delayed_plan.append((route, route.fetch()))
                )
            panel.locator("#catalogue-plan-now").click()
            for _ in range(100):
                if cancellations:
                    break
                page.wait_for_timeout(20)
            assert len(cancellations) == 1
            if switch_client is True:
                page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                    other.id
                )
                cancellations[0][0].continue_()
            else:
                release.set()
                expect(panel.locator("#catalogue-progress")).to_be_hidden(timeout=15000)
                cancellations[0][0].fulfill(response=cancellations[0][1])
            page.unroute("**/cancel")
            if switch_client == "load":
                for _ in range(100):
                    if delayed_plan:
                        break
                    page.wait_for_timeout(20)
                assert delayed_plan
                page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                    other.id
                )
                # Release only the old client's pending snapshot after ownership changed.
                for route, response in list(delayed_plan):
                    route.fulfill(response=response)
                page.unroute("**/api/zen/plan?*")
            release.set()
            expect(panel.locator("#catalogue-fetch")).to_be_enabled(timeout=15000)
            page.wait_for_timeout(200)
            jobs = page.request.get(page.url.split("#")[0] + "api/jobs").json()
            assert any(job["kind"] == "plan" for job in jobs) is not bool(switch_client)
            page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                "default"
            )
            page.locator("#zen-catalogue-tab").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("light")
            expect(panel.locator("html")).to_have_attribute("data-theme", "light")
            expect(panel.get_by_role("button", name="Récupérer seulement Audio")).to_be_visible()
            expect(page.locator("#page-jobs")).not_to_contain_text(" · fetching")
            expect(page.locator("#page-jobs")).not_to_contain_text(" · planning")
            if output := os.getenv("TL_CATALOGUE_SCREENSHOTS"):
                Path(output).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(output) / "web-desktop-fr-light.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            assert panel.locator("html").evaluate("e=>e.scrollWidth<=innerWidth")
            if output:
                page.screenshot(path=str(Path(output) / "web-mobile-fr-light.png"))
            assert not errors, errors
            browser.close()
    finally:
        release.set()
        server.should_exit = True
        worker.join(10)
        listener.close()
