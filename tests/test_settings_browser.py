"""Shared owner Settings drafts and secret handling in an actual browser."""

import os
import socket
import threading
import time
from dataclasses import replace

import pytest

from tests.shell_support import shell_navigate
from tests.test_web_plan_execution import prepared
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


@pytest.mark.parametrize("configured", [True, False])
def test_connection_drafts_survive_section_changes_and_failed_save(
    tmp_path, configured, monkeypatch
):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, client, _ = prepared(tmp_path)
    monkeypatch.setattr(client, "check", lambda: "fixture-client", raising=False)
    setup.configured = configured
    if not configured:
        setup.marker.unlink(missing_ok=True)
    setup.secrets.update({"tmdb-api-key": "private-existing-key"})
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
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
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                assert not errors
                page.locator("#login-password").fill("test-password-long")
                page.locator("#login-form button").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                name = panel.get_by_label("Client name", exact=True)
                expect(name).to_be_visible(timeout=5000)
                # Navigate within Settings while the host refresh is still in flight.
                pending_setup = []
                page.evaluate("""() => {
                    const refresh = refreshSetup;
                    window.fixtureSetupDone = false;
                    refreshSetup = async () => {
                        await refresh(); window.fixtureSetupDone = true;
                    };
                }""")
                page.route(
                    "**/api/setup?*", lambda route: pending_setup.append((route, route.fetch()))
                )
                shell_navigate(page, "setup")
                for _ in range(100):
                    if pending_setup:
                        break
                    page.wait_for_timeout(20)
                assert pending_setup
                panel.get_by_role("button", name="Clients", exact=True).click()
                page.wait_for_function("() => state.settingsSection === 'clients'")
                pending_setup[0][0].fulfill(response=pending_setup[0][1])
                page.wait_for_function("() => window.fixtureSetupDone")
                assert page.evaluate("state.settingsSection") == "clients"
                page.unroute("**/api/setup?*")
                panel.get_by_role("button", name="Connections", exact=True).click()
                name.fill("Studio draft")
                panel.get_by_role("button", name="Clients", exact=True).click()
                panel.get_by_role("button", name="Connections", exact=True).click()
                expect(name).to_have_value("Studio draft")
                secret = panel.get_by_label("TMDb API key", exact=True)
                expect(secret).to_have_value("••••••••")
                secret.fill("replacement-key")
                page.route(
                    "**/api/settings/connections",
                    lambda route: route.fulfill(
                        status=409,
                        content_type="application/json",
                        body='{"detail":"Wait for active jobs before changing settings."}',
                    ),
                )
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-error")).to_contain_text("Wait for active jobs")
                expect(name).to_have_value("Studio draft")
                expect(secret).to_have_value("replacement-key")
                page.unroute("**/api/settings/connections")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                expect(secret).to_have_value("••••••••")
                assert setup.configured
                if not configured:
                    assert setup.marker.read_text() == "connected"
                page.reload()
                shell_navigate(page, "setup")
                expect(name).to_have_value("Studio draft")
                assert "private-existing-key" not in panel.locator("body").inner_text()
                panel.get_by_role("button", name="Clients", exact=True).click()
                panel.get_by_label("New client name", exact=True).fill("Seedbox")
                panel.get_by_role("button", name="Add client", exact=True).click()
                card = panel.locator(".client-card").filter(has_text="Seedbox")
                expect(card).to_be_visible()
                card.get_by_role("button", name="Make default", exact=True).click()
                expect(card).to_contain_text("Default")
                if configured:
                    second = next(
                        p.id for p in setup.settings.client_profiles if p.name == "Seedbox"
                    )
                    panel.get_by_role("button", name="Connections", exact=True).click()
                    stale_save = panel.get_by_role(
                        "button", name="Save", exact=True
                    ).element_handle()
                    pending = []

                    def delay_client(route):
                        pending.append((route, route.fetch()))

                    pattern = f"**/api/settings?client_id={second}"
                    page.route(pattern, delay_client)
                    page.frame_locator("#shell-header-frame").locator(
                        "#target-client"
                    ).select_option(second)
                    expect(panel.locator("#settings-body")).to_have_text("Loading Settings…")
                    for _ in range(100):
                        if pending:
                            break
                        page.wait_for_timeout(20)
                    assert pending
                    stale_save.evaluate("button => button.click()")
                    expect(panel.locator("#settings-error")).to_contain_text(
                        "Wait for the selected client"
                    )
                    assert setup.settings.profile(second).name == "Seedbox"
                    pending[0][0].fulfill(response=pending[0][1])
                    expect(panel.get_by_label("Client name", exact=True)).to_have_value("Seedbox")
                    page.unroute(pattern, delay_client)
                    page.frame_locator("#shell-header-frame").locator(
                        "#target-client"
                    ).select_option("default")
                    expect(panel.get_by_label("Client name", exact=True)).to_have_value(
                        "Studio draft"
                    )
                    panel.get_by_role("button", name="Clients", exact=True).click()
                page.once("dialog", lambda dialog: dialog.accept())
                card.get_by_role("button", name="Remove client", exact=True).click()
                expect(panel.locator(".client-card")).to_have_count(1)
                panel.get_by_role("button", name="General", exact=True).click()
                panel.get_by_label("Theme", exact=True).select_option("light")
                panel.get_by_label("Media interface", exact=True).select_option("focus")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                expect(panel.locator("html")).to_have_attribute("data-theme", "light")
                panel.get_by_role("button", name="Search & Matching", exact=True).click()
                panel.get_by_label("Ignored Files", exact=True).fill("*.nfo\n*.txt")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                panel.get_by_role("button", name="Zen", exact=True).click()
                panel.get_by_label("Seed hours per day", exact=True).fill("12")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                page.reload()
                shell_navigate(page, "setup")
                panel.get_by_role("button", name="Zen", exact=True).click()
                expect(panel.get_by_label("Seed hours per day", exact=True)).to_have_value("12")
                # Changes made elsewhere refresh clean sections; edited drafts survive reopening.
                shell_navigate(page, "torrents")
                setup.settings.zen = replace(setup.settings.zen, seed_hours=13)
                setup.save()
                shell_navigate(page, "setup")
                panel.get_by_role("button", name="Zen", exact=True).click()
                expect(panel.get_by_label("Seed hours per day", exact=True)).to_have_value("13")
                panel.get_by_label("Seed hours per day", exact=True).fill("9")
                shell_navigate(page, "torrents")
                setup.settings.zen = replace(setup.settings.zen, seed_hours=18)
                setup.save()
                shell_navigate(page, "setup")
                panel.get_by_role("button", name="Zen", exact=True).click()
                expect(panel.get_by_label("Seed hours per day", exact=True)).to_have_value("9")
                for section in ("Library Folders", "Download Folders", "Client Paths"):
                    panel.locator("#settings-navigation").get_by_role(
                        "button", name=section, exact=True
                    ).click()
                    expect(panel.get_by_role("button", name="Browse…", exact=True)).to_be_visible()
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="Assistant", exact=True
                ).click()
                expect(
                    panel.get_by_role("button", name="Add connection", exact=True)
                ).to_be_visible()
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="Companion", exact=True
                ).click()
                expect(
                    panel.get_by_role("button", name="Save extension…", exact=True)
                ).to_be_visible()
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="Agent access", exact=True
                ).click()
                expect(panel.locator("#agents-endpoint")).to_contain_text("mcp/")
                panel.get_by_role("button", name="New connection", exact=True).click()
                panel.locator("#agent-name").fill("Fixture agent")
                panel.get_by_role("button", name="Create connection", exact=True).click()
                expect(panel.locator("#agent-token")).not_to_have_value("")
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="General", exact=True
                ).click()
                panel.locator("#settings-navigation").get_by_role(
                    "button", name="Agent access", exact=True
                ).click()
                expect(panel.locator("#agent-token-box")).to_be_hidden()
                expect(panel.locator("#agent-connections")).to_contain_text("Fixture agent")
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(10)


def test_clear_secrets_before_agent_settings_script_loads():
    """Host navigation can arrive between the deferred Settings scripts."""
    from pathlib import Path

    from playwright.sync_api import expect, sync_playwright

    static = Path(__file__).parents[1] / "src/torrentlinker/web/static/settings"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content(
            '<div id="agent-token-box"><input id="agent-token" value="temporary"></div>'
        )
        page.add_script_tag(path=str(static / "view.js"))
        page.evaluate("""window.dispatchEvent(new MessageEvent('message', {
            source: window, origin: location.origin, data: {type: 'settings-clear-secrets'}
        }))""")
        assert not errors, errors
        expect(page.locator("#agent-token")).to_have_value("")
        expect(page.locator("#agent-token-box")).to_be_hidden()
        page.add_script_tag(path=str(static / "agents.js"))
        assert page.evaluate("agentTokenGeneration") == 1
        browser.close()


def test_saved_secrets_show_a_mask_and_the_eye_reveals_them_and_extra_keys_edit_one_by_one(
    tmp_path,
):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
    setup.secrets.update(
        {
            "tmdb-api-key": "private-existing-key",
            "indexer-extra-key-1": "extra-one",
            "indexer-extra-key-2": "extra-two",
        }
    )
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
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
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.locator("#login-password").fill("test-password-long")
                page.locator("#login-form button").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                tmdb = panel.get_by_label("TMDb API key", exact=True)
                expect(tmdb).to_have_value("••••••••")
                expect(tmdb).to_have_attribute("type", "password")
                assert "private-existing-key" not in panel.locator("body").inner_text()
                panel.get_by_role("button", name="Show TMDb API key", exact=True).click()
                expect(tmdb).to_have_value("private-existing-key")
                expect(tmdb).to_have_attribute("type", "text")
                panel.get_by_role("button", name="Hide TMDb API key", exact=True).click()
                expect(tmdb).to_have_value("••••••••")
                # Typing replaces the mask; emptying the field keeps the saved key.
                tmdb.click()
                page.keyboard.type("typed")
                expect(tmdb).to_have_value("typed")
                tmdb.fill("")
                tmdb.blur()
                expect(tmdb).to_have_value("••••••••")
                # Each saved additional key is its own field.
                first = panel.get_by_label("Additional API key 1", exact=True)
                second = panel.get_by_label("Additional API key 2", exact=True)
                expect(first).to_have_value("••••••••")
                expect(second).to_have_value("••••••••")
                panel.get_by_role("button", name="Show additional API key 2", exact=False).click()
                expect(second).to_have_value("extra-two")
                panel.get_by_role("button", name="Remove additional API key 1").click()
                expect(panel.get_by_label("Additional API key 2", exact=True)).to_have_count(0)
                panel.get_by_role("button", name="Add an API key", exact=True).click()
                panel.get_by_label("Additional API key 2", exact=True).fill("extra-new")
                panel.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator("#settings-status")).to_contain_text("Settings saved")
                assert setup.extra_indexer_keys() == ["extra-two", "extra-new"]
                assert setup.secrets.get("tmdb-api-key") == "private-existing-key"
                # Every result is a toast, never reaching the real Indexer.
                answers = iter(
                    [
                        {"body": '{"ok":true,"categories":38,"keys":5}', "status": 200},
                        {"body": '{"detail":"Indexer test failed."}', "status": 400},
                    ]
                )
                page.route(
                    "**/api/settings/test/indexer",
                    lambda route: route.fulfill(content_type="application/json", **next(answers)),
                )
                test = panel.get_by_role("button", name="Test Indexer", exact=True)
                test.scroll_into_view_if_needed()
                test.click()
                done = panel.locator(".tl-toast.ok").filter(has_text="c411 answers")
                expect(done).to_have_text("c411 answers · 38 categories · 5 keys")
                expect(done).to_be_in_viewport()
                expect(test).to_be_enabled()
                test.click()
                failed = panel.locator(".tl-toast.bad").filter(has_text="Indexer test failed.")
                expect(failed).to_be_in_viewport()
                expect(failed).to_have_attribute("role", "alert")
                expect(failed.get_by_role("button", name="Close")).to_be_visible()
                failed.get_by_role("button", name="Close").click()
                expect(failed).to_have_count(0)
                # Save: busy label, then a toast in view whatever the scroll; a failure keeps edits.
                name = panel.get_by_label("Client name", exact=True)
                name.fill("Scrolled")
                save = panel.get_by_role("button", name="Save", exact=True)
                page.route(
                    "**/api/settings/connections",
                    lambda route: route.fulfill(
                        status=409,
                        content_type="application/json",
                        body='{"detail":"Wait for active jobs."}',
                    ),
                )
                save.click()
                failure = panel.locator(".tl-toast.bad").filter(has_text="Wait for active jobs.")
                expect(failure).to_be_in_viewport()
                expect(name).to_have_value("Scrolled")
                expect(save).to_be_enabled()
                expect(save).to_have_text("Save")
                page.unroute("**/api/settings/connections")
                save.click()
                saved = panel.locator(".tl-toast.ok").filter(has_text="Settings saved")
                expect(saved.first).to_be_in_viewport()
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)
