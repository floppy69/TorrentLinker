"""Keyboard access and 200% reflow of the shared Settings sections (#48)."""

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.test_community_interfaces import js, wait_js
from tests.test_web_plan_execution import prepared

SECTIONS = (
    "connections",
    "clients",
    "companion",
    "community_site",
    "agents",
    "assistant",
    "general",
    "library",
    "downloads",
    "paths",
    "matching",
    "release_score",
    "indexers",
    "zen",
)


def capture_path(host, language, zoom, section):
    folder = os.getenv("TL_POLISH_SCREENSHOTS")
    if not folder:
        return None
    path = Path(folder) / f"settings-{host}-{language}-{zoom}-{section}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@pytest.mark.parametrize("language,theme,zoom", [("en", "dark", 1), ("fr", "light", 2)])
def test_settings_native_keyboard_and_zoom(qtbot, tmp_path, language, theme, zoom, request):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    from PySide6.QtCore import Qt

    from torrentlinker.gui.settings_view import SettingsView
    from torrentlinker.settings_workspace import SettingsWorkspace
    from torrentlinker.web.app import create_app

    config, setup, _, _ = prepared(tmp_path)
    setup.settings.language, setup.settings.theme = language, theme
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    view = SettingsView(
        SettingsWorkspace(setup),
        assistant_service=lambda: app.state.assistant,
        agent_service=lambda: app.state.agent_service,
        companion_action=lambda body: {"paired": False, "downloads": {}},
    )
    qtbot.addWidget(view)
    view.resize(1100, 800)
    view.show()
    view.web.setZoomFactor(zoom)
    wait_js(qtbot, view, "document.querySelectorAll('#settings-navigation button').length===14")
    for index, section in enumerate(SECTIONS):
        js(
            qtbot,
            view,
            f"document.querySelectorAll('#settings-navigation button')[{index}].focus()",
        )
        qtbot.keyClick(view.web.focusProxy(), Qt.Key.Key_Return)
        wait_js(qtbot, view, f"section==={json.dumps(section)}")
        wait_js(qtbot, view, "document.querySelector('.settings-form')!==null")
        wait_js(qtbot, view, "document.documentElement.scrollWidth<=innerWidth+1")
        assert js(qtbot, view, "document.querySelector('#settings-error').textContent") == ""
        # Focus must leave the active navigation button, remain visible and have an outline.
        js(qtbot, view, "document.querySelector('#settings-navigation [aria-current]').focus()")
        qtbot.keyClick(view.web.focusProxy(), Qt.Key.Key_Tab)
        assert js(qtbot, view, "document.activeElement!==document.body")
        assert js(
            qtbot,
            view,
            """(() => {
            const el=document.activeElement,r=el.getBoundingClientRect();
            return r.bottom>0 && r.top<innerHeight &&
                getComputedStyle(el).outlineStyle!=='none';
        })()""",
        )
        if section in {"connections", "matching", "zen"}:
            if path := capture_path("desktop", language, zoom, section):
                js(qtbot, view, "scrollTo(0,0)")
                qtbot.wait(250)
                assert view.grab().save(path)
    view.close()


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
@pytest.mark.parametrize("language,theme,zoom", [("en", "dark", 1), ("fr", "light", 2)])
def test_settings_web_keyboard_and_zoom(tmp_path, language, theme, zoom):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate, shell_open_navigation
    from torrentlinker.web.app import create_app

    config, setup, _, _ = prepared(tmp_path)
    setup.settings.language, setup.settings.theme = language, theme
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
                page = browser.new_page(
                    viewport={"width": 1100 // zoom, "height": 800 // zoom},
                    device_scale_factor=zoom,
                )
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.locator("#login-password").fill("test-password-long")
                page.locator("#login-form button").click()
                shell_navigate(page, "setup")
                shell_open_navigation(page)  # a phone's drawer closes after each page choice
                nav = page.frame_locator("#shell-navigation-frame")
                nav.locator("#language").select_option(language)
                nav.locator("#theme").select_option(theme)
                panel = page.frame_locator("#settings-frame")
                expect(panel.locator("#settings-navigation button")).to_have_count(len(SECTIONS))
                # Match browser zoom: fewer CSS pixels with the same physical screenshot size.
                for index, section in enumerate(SECTIONS):
                    button = panel.locator("#settings-navigation button").nth(index)
                    button.focus()
                    button.press("Enter")
                    expect(button).to_have_attribute("aria-current", "page")
                    expect(panel.locator(".settings-form")).to_be_visible()
                    assert panel.locator("html").evaluate("el=>el.scrollWidth<=innerWidth+1")
                    expect(panel.locator("#settings-error")).to_be_empty()
                    button.focus()
                    button.press("Tab")
                    assert panel.locator("body").evaluate("""() => {
                        const el=document.activeElement,r=el.getBoundingClientRect();
                        return el!==document.body && r.bottom>0 && r.top<innerHeight &&
                            getComputedStyle(el).outlineStyle!=='none';
                    }""")
                    if section in {"connections", "matching", "zen"}:
                        if path := capture_path("web", language, zoom, section):
                            panel.locator("body").evaluate("()=>scrollTo(0,0)")
                            page.locator("#settings-frame").screenshot(path=path)
                browser.close()
        finally:
            server.should_exit = True
            worker.join(5)
