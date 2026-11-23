"""Compact Media discussions through the shared view and owner services."""

import os
import subprocess
import sys
import threading

import httpx
from fastapi.testclient import TestClient

from tests.shell_support import media_option, shell_navigate
from tests.test_assistant import login
from tests.test_assistant_ui import provider
from torrentlinker.config import Settings
from torrentlinker.domain import LibraryFolder
from torrentlinker.web.app import create_app


def test_media_chat_shared_desktop_workflow(qtbot, tmp_path, request):
    if not os.getenv("TL_MEDIA_CHAT_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={**os.environ, "TL_MEDIA_CHAT_CHILD": "1", "XDG_CONFIG_HOME": str(tmp_path / "qt")},
            capture_output=True,
            text=True,
            timeout=100,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PySide6.QtWidgets import QApplication

    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.gui.theme import apply_theme

    root = tmp_path / "films"
    root.mkdir()
    (root / "A Journey.2024.mp4").write_bytes(b"\0" * 64)
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(language="en", library_folders=[LibraryFolder(root)])
    settings.save(config / "settings.json")
    app = create_app(
        config,
        password="test-password-long",
        roots=(root,),
        assistant_transport=httpx.MockTransport(provider),
        monitor_verifications=False,
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Test", "kind": "ollama", "model": "test"},
        )
        app.state.agent_service.media.scan("default", threading.Event(), lambda _: None)
        tab = MediaTab(lambda: app.state.assistant, lambda: "default", lambda: None)
        qtbot.addWidget(tab)
        tab.resize(1280, 720)
        tab.show()
        tab.activate()
        wait_js(qtbot, tab.browser, "!!document.querySelector('#media-feature h2')")
        js(qtbot, tab.browser, "document.querySelector('#media-toolbar-chat').click()")
        qtbot.waitUntil(lambda: tab.assistant is not None)
        chat = tab.assistant
        wait_js(
            qtbot,
            chat,
            "!!document.querySelector('#assistant-prompt') && "
            "!document.querySelector('#view-assistant').inert",
        )
        first = tab.conversation_id
        session = app.state.agent_service.media.session_record(tab.session_id, tab.token)
        assert session["conversation"] == first
        assert tab.browse_selection
        assert js(qtbot, chat, "document.querySelectorAll('.assistant-tabs').length===0")
        js(
            qtbot,
            chat,
            "document.querySelector('#assistant-prompt').value='Help me build a Plan.';d"
            "ocument.querySelector('#assistant-send').click()",
        )
        wait_js(
            qtbot,
            chat,
            "document.querySelector('#assistant-transcript').innerText.includes('Ready t"
            "o prepare')",
        )
        assert js(
            qtbot,
            chat,
            "document.querySelector('#assistant-prompt').getBoundingClientRect().bottom "
            "<= innerHeight",
        )
        # A draft belongs to its discussion across history switches and reopenings.
        js(
            qtbot,
            chat,
            "document.querySelector('#assistant-prompt').value='Keep this draft';documen"
            "t.querySelector('#assistant-prompt').dispatchEvent(new Event('input'));docu"
            "ment.querySelector('#media-chat-history').click()",
        )
        wait_js(qtbot, chat, "!document.querySelector('#media-chat-menu').hidden")
        js(qtbot, chat, "document.querySelector('#media-chat-menu button').click()")
        qtbot.waitUntil(lambda: tab.conversation_id != first)
        wait_js(qtbot, chat, "document.querySelector('#assistant-prompt')?.value===''")
        tab.open_chat(first)
        wait_js(
            qtbot, chat, "document.querySelector('#assistant-prompt')?.value==='Keep this draft'"
        )
        # A narrow desktop uses the whole Media area for chat without losing its width.
        tab.splitter.setSizes([780, 480])
        tab._remember_chat_width()
        saved_width = tab.credentials.value("chat_width")
        tab.resize(700, 720)
        qtbot.waitUntil(lambda: tab.media_column.isHidden())
        assert chat.width() <= tab.width()
        tab.resize(1280, 720)
        qtbot.waitUntil(lambda: not tab.media_column.isHidden())
        assert tab.credentials.value("chat_width") == saved_width
        assert abs(tab.splitter.sizes()[-1] - int(saved_width)) <= 2
        # Escape preserves a draft, then closes when the composer is empty.
        js(
            qtbot,
            chat,
            "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))",
        )
        assert chat.isVisible()
        js(
            qtbot,
            chat,
            "document.querySelector('#assistant-prompt').value='';document.querySelector"
            "('#assistant-prompt').dispatchEvent(new Event('input'));document.dispatchEv"
            "ent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))",
        )
        qtbot.waitUntil(chat.isHidden)
        assert tab.media_column.isVisible()
        tab.open_chat(first)
        wait_js(
            qtbot,
            chat,
            "!!document.querySelector('#media-chat-more') && "
            "!document.querySelector('#view-assistant').inert",
        )
        opened = []
        tab.discussion_requested.connect(opened.append)
        js(qtbot, chat, "document.querySelector('#media-chat-more').click()")
        js(
            qtbot,
            chat,
            "[...document.querySelectorAll('#media-chat-menu button')].find(b=>b.textCon"
            "tent==='Open in Assistant').click()",
        )
        qtbot.waitUntil(lambda: opened == [first])
        for language in ("en", "fr"):
            app.state.agent_service.setup.settings.language = language
            for theme in ("dark", "light"):
                apply_theme(QApplication.instance(), theme)
                tab.refresh()
                chat.activate()
                wait_js(
                    qtbot,
                    chat,
                    f"document.documentElement.lang==='{language}' && "
                    f"document.documentElement.dataset.theme==='{theme}' && "
                    f"!!document.querySelector('#assistant-prompt') && "
                    "!document.querySelector('#view-assistant').inert",
                )
                assert js(qtbot, chat, "document.documentElement.scrollWidth<=innerWidth")
                if output := os.getenv("TL_CHAT_SCREENSHOTS"):
                    from pathlib import Path

                    Path(output).mkdir(parents=True, exist_ok=True)
                    qtbot.wait(200)
                    tab.grab().save(str(Path(output) / f"desktop-{language}-{theme}.png"))
        tab.close_chat()
        tab.stop()


def test_media_chat_shared_browser_workflow(tmp_path):
    import socket
    import time

    import pytest

    if os.getenv("TL_WEB_BROWSER") != "1":
        pytest.skip("opt-in browser test")
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    root = tmp_path / "films"
    root.mkdir()
    (root / "A Journey.2024.mp4").write_bytes(b"\0" * 64)
    (root / "B Arrival.2025.mp4").write_bytes(b"\0" * 64)
    config = tmp_path / "config"
    config.mkdir()
    Settings(language="en", library_folders=[LibraryFolder(root)]).save(config / "settings.json")
    app = create_app(
        config,
        password="test-password-long",
        roots=(root,),
        assistant_transport=httpx.MockTransport(provider),
        monitor_verifications=False,
    )
    setup_release, setup_entered = threading.Event(), threading.Event()
    report_release, report_entered = threading.Event(), threading.Event()
    setup_release.set()
    report_release.set()

    @app.middleware("http")
    async def delayed_responses(request, call_next):
        import asyncio

        if request.url.path == "/api/setup/assistant" and not setup_release.is_set():
            setup_entered.set()
            await asyncio.to_thread(setup_release.wait, 10)
        response = await call_next(request)
        if (
            request.method == "POST"
            and "/api/media/sessions/" in request.url.path
            and not request.url.path.endswith("/chat")
            and not report_release.is_set()
        ):
            report_entered.set()
            await asyncio.to_thread(report_release.wait, 10)
        return response

    owner = TestClient(app)
    login(owner)
    owner.post(
        "/api/setup/assistant/providers",
        json={"name": "Test", "kind": "ollama", "model": "test"},
    )
    owner.close()
    app.state.agent_service.media.scan("default", threading.Event(), lambda _: None)
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
            page = browser.new_page(viewport={"width": 1280, "height": 720}, locale="en-US")
            errors = []
            submissions = []
            reports = []

            def observe(request):
                if request.method != "POST":
                    return
                if request.url.endswith("/api/assistant/jobs"):
                    submissions.append(request.post_data_json)
                elif "/api/media/sessions/" in request.url and not request.url.endswith("/chat"):
                    reports.append(request.post_data_json)

            page.on("request", observe)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "media")
            media = page.frame_locator("#media-frame")
            expect(media.locator("#media-feature")).to_contain_text("A Journey")
            media_option(page, "#media-toolbar-chat").click()
            chat = page.frame_locator("#media-assistant-frame")
            expect(chat.locator("#assistant-prompt")).to_be_visible()
            chat.locator("#assistant-prompt").fill("Help me build a Plan.")
            chat.locator("#assistant-send").click()
            expect(chat.locator("#assistant-transcript")).to_contain_text("Ready to prepare")
            chat.locator("#assistant-prompt").fill("Keep my draft")
            # Hold the new discussion's setup response while the old composer is visible.
            setup_release.clear()
            chat.locator("#media-chat-history").click()
            chat.get_by_role("menuitem", name="New discussion", exact=True).click()
            for _ in range(100):
                if setup_entered.is_set():
                    break
                page.wait_for_timeout(20)
            assert setup_entered.is_set()
            assert chat.locator("#view-assistant").evaluate("e=>e.inert")
            chat.locator("#assistant-prompt").evaluate(
                "e=>{e.dispatchEvent(new Event('input'));e.closest('form').requestSubmit()}"
            )
            assert len(submissions) == 1
            setup_release.set()
            expect(chat.locator("#assistant-prompt")).to_have_value("")
            chat.locator("#media-chat-history").click()
            chat.get_by_role("menuitemradio").last.click()
            expect(chat.locator("#assistant-prompt")).to_have_value("Keep my draft")
            # An explicit send waits for an older heartbeat, then reports the new selection.
            report_release.clear()
            for _ in range(100):
                if report_entered.is_set():
                    break
                page.wait_for_timeout(20)
            assert report_entered.is_set()
            media.locator(".media-home-row").first.get_by_role(
                "button", name="B Arrival", exact=False
            ).click()
            expect(media.locator("#media-feature h2")).to_have_text("B Arrival")
            chat.locator("#assistant-prompt").fill("Use the newly selected film")
            chat.locator("#assistant-send").click()
            page.wait_for_timeout(100)
            assert len(submissions) == 1
            report_release.set()
            for _ in range(100):
                if len(submissions) == 2:
                    break
                page.wait_for_timeout(20)
            assert len(submissions) == 2
            listing = page.request.get(
                f"http://127.0.0.1:{port}/api/media?client_id=default&kind=video"
            ).json()
            selected = next(row["id"] for row in listing["rows"] if row["title"] == "B Arrival")
            assert reports[-1]["context"]["selection"] == selected
            expect(chat.locator("#assistant-prompt")).to_have_value("")
            chat.locator("#assistant-prompt").fill("Keep my draft")
            chat.locator("#media-chat-more").click()
            chat.get_by_role("menuitem", name="Discussion settings", exact=True).click()
            expect(chat.locator("dialog[open]")).to_be_visible()
            chat.get_by_role("button", name="Cancel", exact=True).click()
            for language in ("en", "fr"):
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    language
                )
                for theme in ("dark", "light"):
                    page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                        theme
                    )
                    expect(chat.locator("html")).to_have_attribute("lang", language)
                    expect(chat.locator("html")).to_have_attribute("data-theme", theme)
                    expect(chat.locator("#view-assistant")).not_to_have_attribute("inert", "")
                    expect(chat.locator("#assistant-prompt")).to_have_value("Keep my draft")
                    if output := os.getenv("TL_CHAT_SCREENSHOTS"):
                        from pathlib import Path

                        Path(output).mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(Path(output) / f"web-{language}-{theme}.png"))
            page.set_viewport_size({"width": 390, "height": 720})
            assert page.locator("#media-chat-panel").bounding_box()["width"] == 390
            assert chat.locator("html").evaluate("e=>e.scrollWidth<=innerWidth")
            chat.locator("#assistant-prompt").press("Escape")
            expect(page.locator("#media-chat-panel")).to_be_visible()
            chat.locator("#assistant-prompt").fill("")
            expect(chat.locator("#view-assistant")).not_to_have_attribute("inert", "")
            expect(chat.locator("#assistant-prompt")).to_have_value("")
            chat.locator("#assistant-prompt").press("Escape")
            expect(page.locator("#media-chat-panel")).to_be_hidden()
            media_option(page, "#media-toolbar-chat").click()
            expect(chat.locator("#assistant-prompt")).to_be_visible()
            chat.locator("#media-chat-more").click()
            chat.get_by_role("menuitem", name="Ouvrir dans l’Assistant", exact=True).click()
            full = page.frame_locator("#assistant-frame")
            expect(full.locator("#assistant-transcript")).to_contain_text("Ready to prepare")
            expect(page.locator("#media-chat-panel")).to_be_hidden()
            assert not errors, errors
            browser.close()
    finally:
        setup_release.set()
        report_release.set()
        server.should_exit = True
        thread.join(10)
