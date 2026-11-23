"""Use the same inline folder recovery from desktop widgets and a real browser."""

import os
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.shell_support import shell_close_navigation, shell_navigate
from tests.test_agent_download_folders import MountedClient
from tests.test_assistant import generation_transport, login, wait_run
from tests.test_assistant_download_folders import (
    HASH,
    mounted,
    prepare,
    provider,
    restore_indexer,
    start_download,
)
from torrentlinker.web.app import create_app


def test_desktop_new_local_folder_approval_syncs_live_settings_and_resumes(qtbot, tmp_path):
    from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

    from torrentlinker.agent.desktop import DesktopOperations, DesktopServer
    from torrentlinker.config import Settings
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.gui.assistant import AssistantTab
    from torrentlinker.store import CatalogueRow, Store
    from torrentlinker.web.security import ServerSecrets

    folder = tmp_path / "new-books"
    folder.mkdir()
    settings = Settings()
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    settings.free_space_margin = 0.0
    settings.ensure_profiles()
    settings.add_client("Other client")
    store = Store(tmp_path / "state.sqlite")
    runtime = DesktopServer(settings, tmp_path / "settings.json", store)
    runtime.setup.secrets = ServerSecrets(tmp_path)
    runtime.setup.connector = lambda *args: MountedClient()
    app = create_app(
        tmp_path,
        password="test-password-long",
        service_override=runtime.setup,
        operation_factory=DesktopOperations,
        monitor_verifications=False,
        assistant_transport=generation_transport(provider),
    )
    runtime.app = app
    with TestClient(app) as browser:
        login(browser)
        restore_indexer(app)
        store.save_catalogue(
            [
                CatalogueRow(HASH, "New book", 4, 1, 7000, "https://indexer.test/download", "", 1),
            ]
        )
        identifier = start_download(browser)
        run = wait_run(browser, identifier)
        assert run["status"] == "awaiting_user", run
        widget = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.conversation_id = run["conversation_id"]
        widget.resize(900, 700)
        widget.show()
        widget.activate()
        qtbot.waitUntil(lambda: bool(widget.transcript.findChildren(QLineEdit)), timeout=5000)
        widget.transcript.findChild(QLineEdit).setText(str(folder))
        next(
            b for b in widget.transcript.findChildren(QPushButton) if b.text() == "Submit answer"
        ).click()
        qtbot.waitUntil(
            lambda: any(
                b.text() == "Approve once" for b in widget.transcript.findChildren(QPushButton)
            ),
            timeout=5000,
        )
        assert settings.download_folders.by_category == {}
        assert runtime.setup.settings.download_folders.by_category == {}
        assert browser.get("/api/queue").json() == []
        assert any(str(folder) in label.text() for label in widget.transcript.findChildren(QLabel))
        next(
            b for b in widget.transcript.findChildren(QPushButton) if b.text() == "Approve once"
        ).click()
        qtbot.waitUntil(
            lambda: app.state.assistant.run(identifier)["status"] == "completed", timeout=5000
        )
        # A subsequent GUI timer sync must pull the approved setting before comparing
        # snapshots, otherwise its old snapshot erases the approved destination.
        settings.qbit.username = "unrelated-owner-edit"
        runtime.service.suspended = True  # legacy stale flag must repair itself
        runtime.sync(settings)
        assert settings.download_folders.by_category == {7000: str(folder)}
        assert runtime.setup.settings.download_folders.by_category == {7000: str(folder)}
        assert runtime.setup.settings.qbit.username == "unrelated-owner-edit"
        assert (
            settings.for_client(settings.client_profiles[1].id).download_folders.by_category == {}
        )
        assert not runtime.service.suspended
        runtime.sync(settings)
        assert len(browser.get("/api/queue").json()) == 1
        assert browser.get("/api/queue").json()[0]["folder"] == str(folder)
        assert Settings.load(tmp_path / "settings.json").download_folders.by_category == {
            7000: str(folder)
        }


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_missing_folder_custom_answer_approval_and_resume(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    root, books = mounted(tmp_path)
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: MountedClient(),
        assistant_transport=generation_transport(provider),
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
            prepare(app, owner, root)
            identifier = start_download(owner)
            assert wait_run(owner, identifier)["status"] == "awaiting_user"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 700, "height": 850}, locale="en-US")
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("#navigation-toggle").click()
            shell_navigate(page, "assistant")
            shell_close_navigation(page)
            panel = page.frame_locator("#assistant-frame")
            # The first chat was created through the same public owner endpoints.
            panel.get_by_role("button", name="Discussions", exact=True).click()
            panel.locator(".assistant-conversations button").last.click()
            panel.get_by_role("button", name="Discussions", exact=True).click()
            question = panel.locator(".assistant-question")
            expect(question).to_be_visible(timeout=10000)
            expect(question).to_contain_text("Ebook")
            question.get_by_role("textbox").fill(str(books))
            question.get_by_role("button", name="Submit answer", exact=True).click()
            decision = panel.locator(".assistant-decision")
            expect(decision).to_be_visible(timeout=10000)
            expect(decision).to_contain_text(str(books))
            expect(decision).to_contain_text("Ebook")
            assert app.state.agent_service.setup.settings.download_folders.by_category == {}
            decision.get_by_role("button", name="Approve once", exact=True).click()
            expect(
                panel.locator(".assistant-markdown").filter(has_text="Finished reviewing")
            ).to_be_visible(timeout=10000)
            from torrentlinker.download_queue import entries

            queue = entries(app.state.agent_service.setup.store)
            assert len(queue) == 1
            assert queue[0].folder == books
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_desktop_remote_folder_uses_existing_mapping_and_seeded_sample(tmp_path):
    from torrentlinker.agent.desktop import DesktopSetup
    from torrentlinker.config import Settings
    from torrentlinker.domain import PathMapping
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.store import Store

    root, books = mounted(tmp_path)
    settings = Settings()
    settings.qbit.host = "https://seedbox.test"
    settings.path_mappings = [PathMapping(str(root), "/downloads")]
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    setup = DesktopSetup(settings, tmp_path / "settings.json", Store(tmp_path / "state.sqlite"))
    setup.connector = lambda *args: MountedClient()
    with pytest.raises(ValueError, match="Path Mapping"):
        setup.configure_download_folder(str(books), 7000, "/invented")
    empty = root / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="seeded sample"):
        setup.configure_download_folder(str(empty), 7000, probe=False)
    assert setup.settings.download_folders.by_category == {}
    checked = setup.configure_download_folder(str(books), 7000, save=True)
    assert checked["client"] == "/downloads/books"
    assert setup.settings.download_folders.by_category == {7000: str(books)}
    assert setup.settings.path_mappings == [PathMapping(str(root), "/downloads")]
