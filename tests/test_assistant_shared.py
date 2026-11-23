"""Assistant shared-panel behavior through owner service and host interfaces."""

from fastapi.testclient import TestClient

from tests.shell_support import shell_navigate
from tests.test_assistant import login
from torrentlinker.web.app import create_app


def test_execute_acknowledgement_is_shared_and_survives_restart(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app) as browser:
        login(browser)
        assert browser.get("/api/setup/assistant").json()["execute_acknowledged"] is False
        # The desktop invokes this same public service, not a host-local preference.
        app.state.assistant.acknowledge_execute()
        assert browser.get("/api/setup/assistant").json()["execute_acknowledged"] is True
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        login(browser)
        assert browser.get("/api/setup/assistant").json()["execute_acknowledged"] is True
        assert browser.post("/api/setup/assistant/acknowledge-execute", json={}).status_code == 200


def test_web_shared_discussion_and_history(tmp_path):
    import os
    import socket
    import threading
    import time

    import httpx
    import pytest
    import uvicorn

    if os.getenv("TL_WEB_BROWSER") != "1":
        pytest.skip("set TL_WEB_BROWSER=1")
    from playwright.sync_api import expect, sync_playwright

    from tests.test_assistant_ui import provider

    release = threading.Event()

    def slow_provider(request):
        if request.method == "POST" and b"Wait for cancellation" in request.content:
            release.wait(20)
        return provider(request)

    app = create_app(
        tmp_path,
        password="test-password-long",
        assistant_transport=httpx.MockTransport(slow_provider),
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
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            page.request.post(
                f"http://127.0.0.1:{port}/api/setup/assistant/providers",
                data={"name": "Test", "kind": "ollama", "model": "test"},
                headers={"X-TorrentLinker": "1"},
            )
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "assistant")
            panel = page.frame_locator("#assistant-frame")
            try:
                panel.locator("#assistant-prompt").fill("Help me build a Plan.")
            except Exception:
                print("PAGE ERRORS", errors)
                print("FRAMES", [(f.url, f.locator("body").inner_text()) for f in page.frames])
                raise
            panel.locator("#assistant-prompt").press("Shift+Enter")
            expect(panel.locator("#assistant-prompt")).to_have_value("Help me build a Plan.\n")
            panel.locator("#assistant-prompt").press("Enter")
            expect(panel.locator("#assistant-transcript")).to_contain_text(
                "Ready to prepare a Plan", timeout=15000
            )
            panel.get_by_role("tab", name="History", exact=True).click()
            expect(panel.locator(".assistant-history")).to_contain_text("Help me build a Plan.")
            panel.get_by_role("tab", name="Discussion", exact=True).click()
            panel.locator("#assistant-prompt").fill("Wait for cancellation")
            panel.locator("#assistant-prompt").press("Enter")
            expect(panel.locator("#assistant-send")).to_have_attribute(
                "aria-label", "Stop", timeout=10000
            )
            with page.expect_response(lambda r: "/cancel" in r.url and r.request.method == "POST"):
                panel.locator("#assistant-send").click()
            release.set()
            expect(panel.locator("#assistant-send")).to_have_attribute(
                "aria-label", "Send", timeout=10000
            )
            # Resize the actual sidebar grip, then revisit the host page.
            page.set_viewport_size({"width": 1600, "height": 900})
            panel.get_by_role("button", name="Discussions", exact=True).click()
            side = panel.locator("#assistant-conversations")
            box = side.bounding_box()
            assert box is not None
            page.mouse.move(box["x"] + box["width"] - 3, box["y"] + box["height"] - 3)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] + 45, box["y"] + box["height"] - 3, steps=8)
            page.mouse.up()
            page.wait_for_timeout(350)
            width = side.bounding_box()["width"]
            assert width > box["width"] + 20
            page.reload()
            panel = page.frame_locator("#assistant-frame")
            expect(panel.locator("#assistant-conversations")).to_be_visible()
            assert (
                abs(panel.locator("#assistant-conversations").bounding_box()["width"] - width) < 2
            )
            panel.locator("#assistant-folders button").first.click()
            if directory := os.getenv("TL_ASSISTANT_WEB_SCREENSHOTS"):
                from pathlib import Path

                Path(directory).mkdir(parents=True, exist_ok=True)
                page.set_viewport_size({"width": 1280, "height": 720})
                panel.get_by_role("button", name="Discussions", exact=True).click()
                for lang in ("en", "fr"):
                    page.frame_locator("#shell-navigation-frame").locator(
                        "#language"
                    ).select_option(lang)
                    for theme in ("dark", "light"):
                        page.evaluate(
                            "theme => document.documentElement.dataset.theme=theme", theme
                        )
                        page.wait_for_timeout(300)
                        page.screenshot(path=f"{directory}/{lang}-{theme}.png")
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "en"
                )
            panel.locator("#assistant-more").click()
            panel.get_by_role("menuitem", name="Discussion settings", exact=True).click()
            panel.get_by_label("Action policy", exact=True).select_option("execute")
            confirmations = []

            def acknowledge(dialog):
                confirmations.append(dialog.message)
                dialog.accept()

            page.on("dialog", acknowledge)
            panel.get_by_role("button", name="Save", exact=True).click()
            expect(panel.locator("dialog")).to_have_count(0)
            assert len(confirmations) == 1
            panel.locator("#assistant-mode").click()
            panel.locator("#assistant-mode").click()
            expect(panel.locator("#assistant-mode")).to_have_text("Execute within limits")
            assert len(confirmations) == 1
            panel.locator("#assistant-prompt").fill("Keep this unsent draft")
            shell_navigate(page, "media")
            page.frame_locator("#media-frame").locator("#media-toolbar-chat").click()
            compact_prompt = page.frame_locator("#media-assistant-frame").locator(
                "#assistant-prompt"
            )
            expect(compact_prompt).to_be_visible()
            box = compact_prompt.bounding_box()
            assert box is not None and box["y"] + box["height"] <= page.viewport_size["height"]
            shell_navigate(page, "assistant")
            expect(panel.locator("#assistant-prompt")).to_have_value("Keep this unsent draft")
            # Context actions work directly on a sidebar discussion.
            toggle = panel.get_by_role("button", name="Discussions", exact=True)
            if toggle.get_attribute("aria-expanded") != "true":
                toggle.click()
            panel.locator("#assistant-folders button").first.click(button="right")
            panel.get_by_role("menuitem", name="Move to folder…", exact=True).click()
            expect(panel.get_by_role("dialog")).to_be_visible()
            panel.get_by_role("button", name="Cancel", exact=True).click()
            toggle.click()
            # The model chip also offers the approved Settings shortcut.
            panel.locator("#assistant-model").select_option("__connections__")
            expect(page.locator("#view-setup")).to_be_visible()
            assert not errors
            browser.close()
    finally:
        release.set()
        server.should_exit = True
        thread.join(timeout=10)
