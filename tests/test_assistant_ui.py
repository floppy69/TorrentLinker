"""Owner flows through desktop widgets and the browser."""

import os
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.shell_support import shell_close_navigation, shell_navigate
from tests.test_assistant import login
from torrentlinker.web.app import create_app


def provider(request):
    if request.method == "GET":
        return httpx.Response(
            200, json={"models": [{"name": "test:latest", "context_length": 262144}]}
        )
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Ready to prepare a Plan. No torrents were changed.",
                    }
                }
            ]
        },
    )


def test_desktop_discussion_keeps_the_composer_available(qtbot, tmp_path, monkeypatch):
    from torrentlinker.gui.assistant import AssistantTab

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local test", "kind": "ollama", "model": "test"},
        ).json()
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.resize(1000, 700)
        widget.show()
        widget.activate()
        assert widget.send.isEnabled()
        widget.prompt.setPlainText("Help me build a Plan.")
        widget.send.click()
        qtbot.waitUntil(lambda: "Ready to prepare" in widget.transcript.toPlainText(), timeout=5000)
        chats = browser.get("/api/assistant/conversations").json()
        assert len(chats) == 1
        assert chats[0]["name"] == "Help me build a Plan."
        assert chats[0]["policy"]["mode"] == "propose"
        assert chats[0]["policy"]["reserve_bytes"] == 0
        assert widget.send.isEnabled()
        assert widget.prompt.height() <= 115
        from PySide6.QtWidgets import QFrame, QToolButton

        assert len(widget.transcript.findChildren(QFrame, "chatMessage")) == 2
        activity = widget.transcript.findChild(QToolButton)
        assert not activity.isChecked()
        activity.click()
        assert activity.isChecked()

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        widget.new_chat.click()
        assert QApplication.activeModalWidget() is None
        assert widget.prompt.hasFocus()
        assert widget.send.isEnabled()
        assert len(browser.get("/api/assistant/conversations").json()) == 1
        widget.prompt.setPlainText("Another task")
        qtbot.keyClick(widget.prompt, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        assert "\n" in widget.prompt.toPlainText()
        assert len(browser.get("/api/assistant/conversations").json()) == 1
        qtbot.keyClick(widget.prompt, Qt.Key.Key_Return)
        qtbot.waitUntil(lambda: "Ready to prepare" in widget.transcript.toPlainText(), timeout=5000)
        assert len(browser.get("/api/assistant/conversations").json()) == 2
        widget.conversations.setCurrentItem(widget.conversations.topLevelItem(0).child(1))
        assert "Help me build a Plan." in widget.transcript.toPlainText()
        qtbot.wait(250)
        widget.grab().save(str(tmp_path / "assistant-desktop.png"))
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
        widget.delete_chat.trigger()
        assert len(browser.get("/api/assistant/conversations").json()) == 1
        assert not widget.conversation_id
        assert "Help me build a Plan." not in widget.transcript.toPlainText()


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_can_configure_model_chat_and_schedule_on_small_screen(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1000, "height": 740}, locale="en-US")

            panel = page.frame_locator("#assistant-frame")

            def new_discussion():
                expect(panel.locator(".assistant-dialog")).to_have_count(0)
                previous = panel.locator("#assistant-prompt").element_handle()
                panel.get_by_role("button", name="New discussion", exact=True).click()
                # The old controls remain visible until the asynchronous reload replaces them.
                previous.wait_for_element_state("hidden")
                expect(panel.locator("#assistant-prompt")).to_be_visible()

            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("#navigation-toggle").click()
            shell_navigate(page, "assistant")
            shell_close_navigation(page)
            # Without a model the composer is replaced by one way to connect one, in Settings.
            expect(panel.locator(".assistant-composer")).to_be_hidden()
            panel.get_by_role("button", name="Connect a model", exact=True).click()
            settings = page.frame_locator("#settings-frame")
            expect(settings.locator("#assistant-connections-body")).to_be_visible()
            settings.get_by_role("button", name="Add connection", exact=True).click()
            dialog = settings.locator(".assistant-dialog")
            dialog.get_by_label("Name", exact=True).fill("Local test")
            dialog.get_by_label("Model ID", exact=True).fill("test")
            expect(dialog.get_by_label("Use server sampling defaults", exact=True)).to_be_checked()
            dialog.get_by_label("Use server sampling defaults", exact=True).uncheck()
            dialog.get_by_label("Temperature (0 = least variation)", exact=True).fill("0")
            expect(dialog.get_by_label("Detect context automatically")).to_be_checked()
            dialog.get_by_role("button", name="Check context", exact=True).click()
            expect(dialog).to_contain_text("262,144 tokens")
            dialog.get_by_label("Detect context automatically").uncheck()
            dialog.get_by_label("Context window (tokens)", exact=True).fill("65536")
            dialog.get_by_role("button", name="Check context", exact=True).click()
            expect(dialog).to_contain_text("Manual context: 65,536 tokens")
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(settings.get_by_role("heading", name="Local test")).to_be_visible()
            assert app.state.assistant.setup()["providers"][0]["temperature"] == 0
            settings.locator("#assistant-connections-body").get_by_role(
                "button", name="Edit", exact=True
            ).click()
            dialog = settings.locator(".assistant-dialog")
            expect(
                dialog.get_by_label("Use server sampling defaults", exact=True)
            ).not_to_be_checked()
            expect(
                dialog.get_by_label("Temperature (0 = least variation)", exact=True)
            ).to_have_value("0")
            page.screenshot(path=str(tmp_path / "sampling-editor-web.png"))
            dialog.get_by_label("Provider", exact=True).select_option("openai")
            expect(dialog.get_by_label("Use server sampling defaults", exact=True)).to_be_checked()
            expect(
                dialog.get_by_label("Temperature (0 = least variation)", exact=True)
            ).to_be_disabled()
            dialog.get_by_role("button", name="Cancel", exact=True).click()
            page.locator("#navigation-toggle").click()
            shell_navigate(page, "assistant")
            shell_close_navigation(page)
            panel.get_by_role("tab", name="Discussion", exact=True).click()
            panel.get_by_role("button", name="Discussions", exact=True).click()
            # An example prompt fills the composer without sending it.
            panel.locator(".assistant-example").first.click()
            expect(panel.locator("#assistant-prompt")).to_have_value(
                "Find ten films I don't seed yet and show them before any action."
            )
            new_discussion()
            expect(panel.locator(".assistant-dialog")).to_have_count(0)
            panel.locator("#assistant-prompt").fill("Help me build a Plan.")
            panel.locator("#assistant-prompt").press("Enter")
            expect(panel.locator("#assistant-transcript")).to_contain_text(
                "Ready to prepare", timeout=10000
            )
            expect(panel.locator(".assistant-message.user")).to_have_count(1)
            activity = panel.locator(".assistant-activity")
            expect(activity.locator("summary")).to_contain_text("No tools called · Reply only")
            expect(panel.locator(".assistant-execution-notice")).to_have_text(
                "No application action was performed in this reply."
            )
            expect(activity).not_to_have_attribute("open", "")
            activity.locator("summary").first.click()
            expect(activity).to_have_attribute("open", "")
            expect(activity).to_contain_text("Model calls: 1 · Tool calls: 0")
            panel.locator("#assistant-prompt").fill("Keep this unfinished message")
            panel.locator("#assistant-more").click()
            panel.get_by_role("menuitem", name="Discussion settings", exact=True).click()
            dialog = panel.locator(".assistant-dialog")
            save_reload_dialog_visible = []

            def observe_save_reload(route):
                # Keep the modal until the refreshed controls are ready, so a
                # new discussion cannot race this pending settings reload.
                save_reload_dialog_visible.append(dialog.is_visible())
                route.continue_()

            page.route("**/api/setup/assistant", observe_save_reload, times=1)
            dialog.get_by_label("Name", exact=True).fill("My films")
            dialog.get_by_label("Allow public Web research", exact=True).check()
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(dialog).to_have_count(0)
            assert save_reload_dialog_visible == [True]
            expect(panel.locator("#assistant-prompt")).to_have_value("Keep this unfinished message")
            expect(panel.locator("#assistant-transcript")).to_contain_text("Ready to prepare")
            new_discussion()
            expect(panel.locator(".assistant-dialog")).to_have_count(0)
            panel.locator("#assistant-more").click()
            panel.get_by_role("menuitem", name="Discussion settings", exact=True).click()
            dialog = panel.locator(".assistant-dialog")
            expect(dialog.get_by_label("Allow public Web research", exact=True)).not_to_be_checked()
            dialog.get_by_label("Allow public Web research", exact=True).check()
            dialog.get_by_role("button", name="Save", exact=True).click()
            new_discussion()
            panel.locator("#assistant-more").click()
            panel.get_by_role("menuitem", name="Discussion settings", exact=True).click()
            dialog = panel.locator(".assistant-dialog")
            expect(dialog.get_by_label("Allow public Web research", exact=True)).to_be_checked()
            dialog.get_by_role("button", name="Cancel", exact=True).click()
            panel.get_by_role("button", name="My films", exact=True).click()
            expect(panel.locator("#assistant-prompt")).to_have_value("Keep this unfinished message")
            page.screenshot(path=str(tmp_path / "assistant-web.png"))
            page.once("dialog", lambda dialog: dialog.accept())
            panel.locator("#assistant-more").click()
            panel.get_by_role("menuitem", name="Delete discussion", exact=True).click()
            expect(panel.get_by_role("button", name="My films", exact=True)).to_have_count(0)
            expect(panel.locator(".assistant-message.user")).to_have_count(0)

            panel.get_by_role("tab", name="Automations", exact=True).click()
            panel.get_by_role("button", name="Create task", exact=True).click()
            dialog = panel.locator(".assistant-dialog")
            dialog.get_by_label("Name", exact=True).fill("Daily report")
            dialog.get_by_label("Instructions", exact=True).fill("Review my Plan.")
            dialog.locator("summary", has_text="Permissions and limits").click()
            model_calls = dialog.get_by_label("Maximum model calls per run", exact=True)
            model_calls.fill("41")
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(dialog).to_be_visible()
            assert not model_calls.evaluate("input => input.checkValidity()")
            assert app.state.assistant.schedules() == []
            model_calls.fill("4")
            dialog.get_by_label("Maximum duration, seconds", exact=True).fill("30")
            dialog.get_by_label("Downloads per day, GiB", exact=True).fill(
                str(1_500_000_000 / 1024**3)
            )
            dialog.get_by_label("Torrents per day", exact=True).fill("3")
            dialog.get_by_label("Keep free, GiB (0 = off)", exact=True).fill("1")
            dialog.get_by_label("Frequency", exact=True).select_option("weekly")
            dialog.get_by_label("Mon", exact=True).uncheck()
            dialog.get_by_label("Sat", exact=True).check()
            dialog.get_by_label("Time", exact=True).fill("10:15")
            dialog.get_by_label("Timezone", exact=True).fill("Europe/Paris")
            dialog.get_by_role("button", name="Preview next run").click()
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(panel.get_by_role("heading", name="Daily report")).to_be_visible()
            saved = app.state.assistant.schedules()[0]
            assert saved["max_calls"] == 4 and saved["max_seconds"] == 30
            assert saved["policy"]["daily_bytes"] == 1_500_000_000
            assert saved["policy"]["daily_torrents"] == 3
            assert saved["policy"]["reserve_bytes"] == 1024**3
            assert saved["weekdays"] == [5] and saved["at"] == "10:15"
            assert saved["timezone"] == "Europe/Paris"
            panel.locator(".assistant-task").get_by_role("button", name="More").click()
            panel.get_by_role("menuitem", name="Edit", exact=True).click()
            dialog.get_by_label("Name", exact=True).fill("Weekly report")
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(panel.get_by_role("heading", name="Weekly report")).to_be_visible()
            assert app.state.assistant.schedules()[0]["policy"]["daily_bytes"] == 1_500_000_000
            output = os.getenv("TL_AUTOMATION_WEB_SCREENSHOTS")
            page.set_viewport_size({"width": 1280, "height": 720})
            for lang in ("fr", "en"):
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    lang, force=True
                )
                for theme in ("light", "dark"):
                    page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                        theme, force=True
                    )
                    expect(panel.locator("html")).to_have_attribute("lang", lang)
                    expect(panel.locator("html")).to_have_attribute("data-theme", theme)
                    expect(
                        panel.get_by_role(
                            "button",
                            name="Créer une tâche" if lang == "fr" else "Create task",
                            exact=True,
                        )
                    ).to_be_visible()
                    expect(panel.locator(".assistant-task")).to_be_visible()
                    expect(panel.locator(".assistant-task")).to_have_count(1)
                    if output:
                        from pathlib import Path

                        Path(output).mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(Path(output) / f"{lang}-{theme}.png"))
            # A new task starts paused: its card offers Enable, then Run now.
            panel.get_by_role("button", name="Enable", exact=True).click()
            panel.get_by_role("button", name="Run now", exact=True).click()
            expect(panel.locator("#view-assistant")).to_contain_text("Runs and tool receipts")
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()


def test_desktop_context_detection_and_manual_override(qtbot, tmp_path):
    from tests.settings_support import edit_field, service_view
    from tests.test_community_interfaces import js, wait_js

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        saved = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local test", "kind": "ollama", "model": "test"},
        ).json()
        view = service_view(
            qtbot, app.state.agent_service.setup, assistant=app.state.assistant, section="assistant"
        )
        wait_js(
            qtbot, view, "[...document.querySelectorAll('button')].some(b=>b.textContent==='Edit')"
        )
        js(
            qtbot,
            view,
            "[...document.querySelectorAll('button')].find(b=>b.textContent==='Edit').click()",
        )
        assert js(
            qtbot,
            view,
            "document.querySelector('[aria-label=\"Detect context automatically\"]').checked",
        )
        js(
            qtbot,
            view,
            "[...document.querySelectorAll('dialog button')].find(b=>b."
            "textContent==='Check context').click()",
        )
        wait_js(
            qtbot,
            view,
            "document.querySelector('dialog').textContent.replaceAll(',"
            "','').includes('262144 tokens')",
        )
        js(
            qtbot,
            view,
            "document.querySelector('[aria-label=\"Detect context automa"
            "tically\"]').click();document.querySelector('[aria-label=\"U"
            "se server sampling defaults\"]').click()",
        )
        edit_field(qtbot, view, "Context window (tokens)", 65536)
        edit_field(qtbot, view, "Temperature (0 = least variation)", 0)
        js(qtbot, view, "document.querySelector('dialog .primary').click()")
        wait_js(qtbot, view, "!document.querySelector('dialog')")
        result = browser.get(f"/api/setup/assistant/providers/{saved['id']}/context").json()
        assert result["context_window"] == 65536 and result["source"] == "manual"
        assert app.state.assistant.setup()["providers"][0]["temperature"] == 0
        js(
            qtbot,
            view,
            "[...document.querySelectorAll('button')].find(b=>b.textContent==='Edit').click()",
        )
        assert (
            js(
                qtbot,
                view,
                "document.querySelector('[aria-label=\"Use server sampling defaults\"]').checked",
            )
            is False
        )
        js(
            qtbot,
            view,
            "document.querySelector('[aria-label=\"Use server sampling defaults\"]').click()",
        )
        assert js(
            qtbot,
            view,
            "document.querySelector('[aria-label=\"Temperature (0 = least variation)\"]').disabled",
        )
        js(qtbot, view, "document.querySelector('dialog .primary').click()")
        wait_js(qtbot, view, "!document.querySelector('dialog')")
        assert app.state.assistant.setup()["providers"][0]["temperature"] is None
        qtbot.waitUntil(lambda: view.pending == 0)
        view.close()


def test_chat_follows_messages_after_layout_settles(qtbot, tmp_path):
    from torrentlinker.gui.assistant import AssistantTab

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        )
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.resize(800, 600)
        widget.show()
        widget.activate()
        for i in range(4):
            widget.prompt.setPlainText(f"Message {i} with many lines.\n\n" * 20)
            widget.send.click()
            qtbot.waitUntil(lambda: widget.send.isEnabled(), timeout=5000)
            qtbot.wait(150)
            bar = widget.transcript.verticalScrollBar()
            assert bar.maximum() - bar.value() <= 10


def test_desktop_question_approval_and_markdown_table(qtbot, tmp_path):
    from PySide6.QtGui import QTextTable
    from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton

    from tests.test_assistant_waits import response, tool
    from tests.test_multi_client_web import Client
    from torrentlinker.gui.assistant import AssistantTab
    from torrentlinker.gui.chat_transcript import MessageText

    client = Client("Test")
    turns = []

    def model(request):
        if request.method == "GET":
            return httpx.Response(404)
        turns.append(request)
        if len(turns) == 1:
            return response(
                [tool("ask_user", {"question": "Which action?", "options": ["Pause", "Skip"]})]
            )
        if len(turns) == 2:
            return response(
                [
                    tool(
                        "propose_action",
                        {
                            "request_id": "pause",
                            "operation": {
                                "kind": "manage",
                                "client_id": "default",
                                "action": "pause",
                                "hashes": ["a" * 40],
                            },
                        },
                    )
                ]
            )
        return response(text="| Action | Result |\n| --- | --- |\n| Pause | Complete |")

    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda *args: client,
        assistant_transport=httpx.MockTransport(model),
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
        )
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        )
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.resize(900, 700)
        widget.show()
        widget.activate()
        widget.prompt.setPlainText("Help choose an action.")
        widget.send.click()
        qtbot.waitUntil(
            lambda: (
                bool(widget.transcript.findChildren(QPushButton))
                and any(
                    b.text() == "Submit answer" for b in widget.transcript.findChildren(QPushButton)
                )
            ),
            timeout=5000,
        )
        widget.pages.setCurrentWidget(widget.history)
        widget.refresh_run()
        assert any(b.text() == "Submit answer" for b in widget.history.findChildren(QPushButton))
        widget.pages.setCurrentIndex(0)
        submit = next(
            b for b in widget.transcript.findChildren(QPushButton) if b.text() == "Submit answer"
        )
        assert not submit.isEnabled()
        options = widget.transcript.findChild(QComboBox)
        options.setCurrentIndex(1)
        assert submit.isEnabled()
        assert len(turns) == 1  # Selecting an option never submits it.
        widget.transcript.findChild(QLineEdit).setText("Please pause this torrent")
        submit.click()
        qtbot.waitUntil(
            lambda: any(
                b.text() == "Approve once" for b in widget.transcript.findChildren(QPushButton)
            ),
            timeout=5000,
        )
        assert client.paused == []  # The answer did not authorize the action.
        # While a run waits on approval, the button stops it instead of sending.
        assert widget.composer.running and not widget.composer.can_send
        next(
            b for b in widget.transcript.findChildren(QPushButton) if b.text() == "Approve once"
        ).click()
        qtbot.waitUntil(lambda: "Complete" in widget.transcript.toPlainText(), timeout=5000)
        assert client.paused == ["a" * 40]
        assert any(
            isinstance(frame, QTextTable)
            for text in widget.transcript.findChildren(MessageText)
            for frame in text.document().rootFrame().childFrames()
        )
        widget.grab().save(str(tmp_path / "assistant-inline-desktop.png"))


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_inline_question_approval_and_safe_table(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_assistant_waits import response, tool
    from tests.test_multi_client_web import Client

    client = Client("Test")
    turns = []

    def model(request):
        if request.method == "GET":
            return httpx.Response(404)
        turns.append(request)
        if len(turns) == 1:
            return response(
                [tool("ask_user", {"question": "Which action?", "options": ["Pause", "Skip"]})]
            )
        if len(turns) == 2:
            return response(
                [
                    tool(
                        "propose_action",
                        {
                            "request_id": "pause",
                            "operation": {
                                "kind": "manage",
                                "client_id": "default",
                                "action": "pause",
                                "hashes": ["a" * 40],
                            },
                        },
                    )
                ]
            )
        return response(
            text="| Action | Result |\n| --- | --- |\n| Pause | Complete |\n\n<script>alert(1)</script>\n\n![bad](https://resource.test/image.png)\n\n[bad](javascript:alert(1))"
        )

    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda *args: client,
        assistant_transport=httpx.MockTransport(model),
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as owner:
            login(owner)
            owner.post(
                "/api/setup/client", json={"client": "qbittorrent", "host": "https://one.test"}
            )
            owner.post(
                "/api/setup/assistant/providers",
                json={"name": "Local", "kind": "ollama", "model": "test"},
            )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 560, "height": 760}, locale="en-US")
            errors, remote = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    remote.append(request.url)
                    if request.url.startswith("https://resource.test/")
                    else None
                ),
            )
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("#navigation-toggle").click()
            shell_navigate(page, "assistant")
            shell_close_navigation(page)
            panel = page.frame_locator("#assistant-frame")
            panel.locator("#assistant-prompt").fill("Help choose an action.")
            panel.locator("#assistant-prompt").press("Enter")
            question = panel.locator(".assistant-question")
            expect(question).to_be_visible(timeout=10000)
            submit = question.get_by_role("button", name="Submit answer", exact=True)
            expect(submit).to_be_disabled()
            question.get_by_role("combobox").select_option("Pause")
            expect(submit).to_be_enabled()
            assert len(turns) == 1
            question.get_by_role("textbox").fill("Please pause this torrent")
            submit.click()
            decision = panel.locator(".assistant-decision")
            expect(decision).to_be_visible(timeout=10000)
            expect(decision).to_contain_text("pause")
            assert client.paused == []
            # While the run waits for approval, the composer button stops it instead of sending.
            expect(panel.locator("#assistant-send")).to_have_attribute("aria-label", "Stop")
            assert panel.locator(".assistant-dialog").count() == 0
            decision.get_by_role("button", name="Approve once", exact=True).click()
            expect(
                panel.locator(".assistant-markdown table td").filter(has_text="Complete")
            ).to_be_visible(timeout=10000)
            assert client.paused == ["a" * 40]
            assert (
                panel.locator(
                    ".assistant-markdown script, .assistant-markdown a[href^='javascript:']"
                ).count()
                == 0
            )
            assert not remote
            assert (
                panel.locator(
                    ".assistant-markdown a[href='https://resource.test/image.png']"
                ).count()
                == 1
            )
            assert not errors
            page.screenshot(path=str(tmp_path / "assistant-inline-web.png"))
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_chat_composer_switches_between_send_and_stop(qtbot):
    from torrentlinker.gui.chat_composer import ChatComposer

    composer = ChatComposer()
    qtbot.addWidget(composer)
    sent, stopped = [], []
    composer.sendRequested.connect(lambda: sent.append(1))
    composer.stopRequested.connect(lambda: stopped.append(1))
    assert not composer.send.isEnabled()  # No model yet: nothing to send to.
    composer.set_state(running=False, can_send=True)
    composer.send.click()
    assert sent == [1] and composer.send.accessibleName() == "Send"
    composer.set_state(running=True, can_send=False)
    assert composer.send.isEnabled() and not composer.model.isEnabled()
    assert composer.send.accessibleName() == "Stop"
    composer.send.click()
    assert stopped == [1] and sent == [1]


def test_mode_chip_switches_and_confirms_only_the_first_time(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from torrentlinker.gui import assistant as module

    store = QSettings(str(tmp_path / "chat.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(module, "QSettings", lambda: store)
    asked = []

    def question(*args):
        asked.append(args)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local test", "kind": "ollama", "model": "test"},
        )
        widget = module.AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.show()
        widget.activate()
        assert widget.composer.mode.text() == "Proposals only"
        # A new discussion keeps the choice until its first message creates it.
        widget.composer.mode.click()
        assert widget.composer.mode.text() == "Execute within limits" and len(asked) == 1
        widget.prompt.setPlainText("Help me build a Plan.")
        widget.send_message()
        chat = browser.get("/api/assistant/conversations").json()[0]
        assert chat["policy"]["mode"] == "execute"
        qtbot.waitUntil(lambda: widget.composer.can_send, timeout=5000)
        widget.composer.mode.click()
        assert browser.get("/api/assistant/conversations").json()[0]["policy"]["mode"] == (
            "propose"
        )
        widget.composer.mode.click()
        assert browser.get("/api/assistant/conversations").json()[0]["policy"]["mode"] == (
            "execute"
        )
        assert len(asked) == 1  # Confirmed once, remembered after.
        assert store.value("assistant/execute_confirmed", False, bool)


def test_model_connections_open_in_settings(qtbot, tmp_path):
    from tests.settings_support import service_view
    from tests.test_community_interfaces import js, wait_js

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app):
        view = service_view(
            qtbot, app.state.agent_service.setup, assistant=app.state.assistant, section="assistant"
        )
        wait_js(
            qtbot, view, "Boolean(document.querySelector('#assistant-connections-body button'))"
        )
        assert (
            js(qtbot, view, "document.querySelector('.settings-form h2').textContent")
            == "Assistant"
        )
        assert js(qtbot, view, "document.querySelector('#settings-error').textContent") == ""
        qtbot.waitUntil(lambda: view.pending == 0)
        view.close()
