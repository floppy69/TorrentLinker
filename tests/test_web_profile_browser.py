"""The account workspace renders profile data and updates without a manual refresh."""

import os
import socket
import threading
import time

import pytest

from tests.test_web_profile import ORIGIN, prepared, snapshot

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_profile_first_pair_snapshot_disconnect_browser(tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app, setup = prepared(tmp_path, monkeypatch)
    setup.profile_workspace().refresh(setup.settings.indexer.url, "fake-key")
    from tests.test_community import observation

    setup.profile_workspace().community.observe("42", observation(today=3))
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
            page = browser.new_page(viewport={"width": 1500, "height": 1100}, locale="en-US")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("[data-view=zen]").first.click()
            expect(page.locator("#zen-profile-tab")).to_have_attribute("aria-selected", "true")
            expect(
                page.frame_locator("#profile-frame").locator("#profile-username")
            ).to_contain_text("Demo account")
            expect(page.frame_locator("#profile-frame").locator("#profile-tiles")).to_contain_text(
                "124"
            )
            expect(
                page.frame_locator("#profile-frame").locator("#profile-sync .pf-cal i")
            ).to_have_count(182)
            panel = page.frame_locator("#profile-frame")
            expect(panel.locator("#profile-contribution")).to_contain_text(
                "Daily community contribution"
            )
            expect(panel.locator("#profile-contribution")).to_contain_text("3 / 5")
            page.set_viewport_size({"width": 2100, "height": 1100})
            assert panel.locator(".pf-grid2 > div").evaluate_all(
                "cards => cards.slice(-2).map(c => c.id)"
            ) == ["profile-contribution", "profile-sync"]
            assert (
                panel.locator(".pf-grid2").evaluate(
                    "e => getComputedStyle(e).gridTemplateColumns.split(' ').length"
                )
                == 3
            )
            assert panel.locator("#profile-transfers").evaluate(
                "e => e.getBoundingClientRect().top === "
                "document.querySelector('#profile-progression').getBoundingClientRect().top"
            )
            assert (
                panel.locator("#zen-profile-panel").evaluate(
                    "e => document.documentElement.clientWidth - e.getBoundingClientRect().right"
                )
                < 40
            )
            panel.locator('[data-days="7"]').click()
            expect(panel.locator('[data-days="7"]')).to_have_attribute("aria-pressed", "true")
            assert page.evaluate("localStorage.getItem('profile-period')") == "7"
            page.locator("#language").select_option("fr")
            expect(panel.locator("#profile-refresh")).to_have_text("Actualiser")
            expect(panel.locator('[data-days="0"]')).to_have_text("Tout")
            expect(panel.locator("#profile-contribution")).to_contain_text(
                "Contribution communautaire du jour"
            )
            page.locator("#theme").select_option("light")
            expect(panel.locator("html")).to_have_attribute("data-theme", "light")
            assert (
                page.locator("html").evaluate(
                    "e => getComputedStyle(e).getPropertyValue('--bg').trim()"
                )
                == "#f3f6fa"
            )
            assert (
                page.locator("html").evaluate(
                    "e => getComputedStyle(e).getPropertyValue('--text').trim()"
                )
                == "#203047"
            )
            page.emulate_media(color_scheme="dark")
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            page.locator("#theme").select_option("auto")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            expect(panel.locator("html")).to_have_attribute("data-theme", "dark")
            page.emulate_media(color_scheme="light")
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            expect(panel.locator("html")).to_have_attribute("data-theme", "light")
            page.set_viewport_size({"width": 600, "height": 900})
            assert (
                panel.locator("#profile-tiles").evaluate(
                    "e => getComputedStyle(e).gridTemplateColumns.split(' ').length"
                )
                == 2
            )
            assert panel.locator("html").evaluate("e => e.scrollWidth <= e.clientWidth")
            page.set_viewport_size({"width": 1500, "height": 1100})
            page.locator("#language").select_option("en")
            page.locator("#theme").select_option("dark")
            expect(panel.locator("html")).to_have_attribute("data-theme", "dark")
            page.set_viewport_size({"width": 1500, "height": 700})
            panel.locator("html").evaluate("() => window.scrollTo(0, 200)")
            scroll = panel.locator("html").evaluate("() => window.scrollY")
            assert scroll > 100
            setup.profile_workspace().community.observe("42", observation(today=4))
            expect(panel.locator("#profile-contribution")).to_contain_text("4 / 5", timeout=10000)
            assert abs(panel.locator("html").evaluate("() => window.scrollY") - scroll) <= 1
            page.set_viewport_size({"width": 1500, "height": 1100})
            # A profile invalidated by a settings change refreshes without a click.
            import httpx

            from tests.test_profile import PROFILE

            monkeypatch.setattr(
                "torrentlinker.profile.net.client",
                lambda **kw: httpx.Client(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(
                            200, json={**PROFILE, "username": "Refreshed account"}
                        )
                    )
                ),
            )
            setup.secrets.update({"indexer-api-key": "rotated-fake-key"})
            expect(
                page.frame_locator("#profile-frame").locator("#profile-username")
            ).to_contain_text("Refreshed account", timeout=10000)
            code = page.request.post(
                f"http://127.0.0.1:{port}/api/zen/profile/pairing",
                headers={"X-TorrentLinker": "1"},
            ).json()["code"]
            ext = {"Origin": ORIGIN}
            response = page.request.post(
                f"http://127.0.0.1:{port}/api/companion/pair",
                headers=ext,
                data={"code": code, "accountId": "42"},
            )
            assert response.ok
            ext["Authorization"] = "Bearer " + response.json()["token"]
            assert page.request.post(
                f"http://127.0.0.1:{port}/api/companion/snapshot", headers=ext, data=snapshot()
            ).ok
            expect(
                page.frame_locator("#profile-frame").locator("#profile-seeding")
            ).to_contain_text("42", timeout=10000)
            if output := os.getenv("TL_PROFILE_SCREENSHOTS"):
                from pathlib import Path

                target = Path(output)
                target.mkdir(parents=True, exist_ok=True)
                page.locator("#theme").select_option("dark")
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(target / "web-profile.png"), full_page=True)
            page.locator("[data-view=setup]").first.click()
            page.locator("[data-settings-section=companion]").click()
            page.locator("#profile-disconnect").click()
            page.locator("[data-view=zen]").first.click()
            expect(
                page.frame_locator("#profile-frame").locator("#profile-seeding")
            ).not_to_contain_text("42")
            page.locator("#zen-profile-tab").focus()
            page.keyboard.press("ArrowRight")
            expect(page.locator("#zen-seeding-tab")).to_have_attribute("aria-selected", "true")
            assert not errors

            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
