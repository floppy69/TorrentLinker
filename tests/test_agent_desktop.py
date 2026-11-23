"""Desktop UI and MCP transport acceptance tests use an isolated workspace."""

import json
import os
import socket
import subprocess
import sys
import threading
import time

import httpx
import uvicorn

from torrentlinker.agent.desktop import DesktopSetup
from torrentlinker.config import Settings
from torrentlinker.store import Store
from torrentlinker.web.app import create_app


def test_packaged_smoke_releases_rss_database_before_cleanup(monkeypatch):
    import sqlite3

    import pytest

    from torrentlinker.app import agent_smoke_checks
    from torrentlinker.feeds import FeedService

    connections = []
    original = FeedService.__init__

    def track(self, *args, **kwargs):
        original(self, *args, **kwargs)
        connections.append(self.db)

    monkeypatch.setattr(FeedService, "__init__", track)
    agent_smoke_checks()
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_desktop_mcp_works_without_console_streams(tmp_path, monkeypatch):
    from tests.test_agent_access import rpc
    from torrentlinker.agent.access import Grant
    from torrentlinker.agent.desktop import DesktopServer

    runtime = DesktopServer(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"), port=0
    )
    with monkeypatch.context() as console:
        console.setattr(sys, "stdout", None)
        console.setattr(sys, "stderr", None)
        try:
            runtime.start()
            with httpx.Client(
                base_url=runtime.url.removesuffix("/mcp/"), trust_env=False
            ) as client:
                for _ in range(100):
                    try:
                        if client.get("/healthz", timeout=0.2).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.02)
                else:
                    raise AssertionError("Desktop MCP did not become ready")
                grant = runtime.service.access.create(
                    Grant(name="Windowed app", clients=["default"])
                )
                runtime.service.access.enable(True)
                assert rpc(client, "invalid-token", "tools/list").status_code == 401
                response = rpc(client, grant["token"], "tools/list")
                assert response.status_code == 200
                assert "overview" in {t["name"] for t in response.json()["result"]["tools"]}
        finally:
            runtime.close()


def test_desktop_owner_can_revoke_and_default_to_proposals(qtbot, tmp_path):
    from tests.settings_support import service_view
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.agent.access import Grant

    setup = DesktopSetup(
        Settings(language="en"), tmp_path / "settings.json", Store(tmp_path / "state.db")
    )
    app = create_app(
        tmp_path, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    service = app.state.agent_service
    grant = service.access.create(Grant(name="Owner test", clients=["default"]))
    view = service_view(qtbot, setup, agents=service, section="agents")
    try:
        wait_js(qtbot, view, "Boolean(document.querySelector('#agent-mode'))")
        wait_js(
            qtbot,
            view,
            "document.querySelector('#agent-connections').textContent.includes('Owner test')",
        )
        assert js(qtbot, view, "document.querySelector('#agent-mode').value") == "propose"
        assert js(qtbot, view, "document.querySelector('#agents-enabled').checked") is False
        assert js(qtbot, view, "document.querySelector('#agent-permissions').disabled")
        js(
            qtbot,
            view,
            "{const mode=document.querySelector('#agent-mode');mode.val"
            "ue='execute';mode.dispatchEvent(new Event('change'));}",
        )
        assert js(qtbot, view, "document.querySelector('#agent-permissions').disabled") is False
        js(
            qtbot,
            view,
            "[...document.querySelectorAll('#agent-connections button')"
            "].find(b=>b.textContent==='Revoke connection').click()",
        )
        qtbot.waitUntil(lambda: service.access.snapshot()["connections"][0]["revoked"])
        assert grant["token"] not in js(qtbot, view, "document.body.textContent")
        qtbot.waitUntil(lambda: view.pending == 0)
    finally:
        view.close()
        service.jobs.close()


def test_stdio_bridge_uses_running_server_and_only_outputs_protocol(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", headers={"X-TorrentLinker": "1"}
        ) as owner:
            assert (
                owner.post("/api/login", json={"password": "test-password-long"}).status_code == 200
            )
            token = owner.post(
                "/api/agents", json={"name": "stdio", "clients": ["default"]}
            ).json()["token"]
            owner.put("/api/agents", json={"enabled": True})
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "overview", "arguments": {}},
            },
        ]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "torrentlinker.agent.stdio",
                "--url",
                f"http://127.0.0.1:{port}/mcp/",
            ],
            input="\n".join(json.dumps(m) for m in messages) + "\n",
            env={**os.environ, "TL_MCP_TOKEN": token},
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        output = [json.loads(line) for line in result.stdout.splitlines()]
        assert [m["id"] for m in output] == [1, 2, 3]
        assert output[0]["result"]["serverInfo"]["name"] == "TorrentLinker"
        assert "propose_action" in {t["name"] for t in output[1]["result"]["tools"]}
        assert output[2]["result"]["structuredContent"]["mode"] == "propose"
        assert token not in result.stdout + result.stderr
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_desktop_client_switch_resets_agent_connections_and_blocks_settings_races(tmp_path):
    from fastapi.testclient import TestClient

    from tests.test_agent_access import call
    from tests.test_web_jobs import Client, finished, login
    from torrentlinker.agent.desktop import DesktopServer
    from torrentlinker.domain import TorrentClient

    settings = Settings()
    settings.ensure_profiles()
    settings.qbit.host = "http://first.example"
    settings.capture_client()
    second = settings.add_client("Second box", TorrentClient.QBITTORRENT)
    second.host = "http://second.example"
    first_client, second_client = Client(), Client()
    first_client.release.set()
    second_client.release.set()
    runtime = DesktopServer(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    runtime.setup.connector = lambda kind, host, *args: (
        second_client if host == "http://second.example" else first_client
    )
    runtime.app = create_app(
        tmp_path,
        password="test-password-long",
        service_override=runtime.setup,
        monitor_verifications=False,
    )
    with TestClient(runtime.app) as browser:
        login(browser)
        grant = browser.post(
            "/api/agents",
            json={
                "name": "Switch test",
                "clients": ["default", second.id],
                "mode": "execute",
                "permissions": ["controls"],
            },
        ).json()
        browser.put("/api/agents", json={"enabled": True})

        def pause(identifier, key):
            return call(
                browser,
                grant["token"],
                "propose_action",
                {
                    "request_id": key,
                    "operation": {
                        "kind": "manage",
                        "action": "pause",
                        "hashes": ["a" * 40],
                        "client_id": identifier,
                    },
                },
            )["structuredContent"]

        job = pause("default", "first")
        assert finished(browser, job["job_id"])["status"] == "completed"
        with runtime.editing_settings():
            assert "error" in pause(second.id, "while-editing")
            runtime.reset(settings.for_client(second.id))
        job = pause(second.id, "second")
        assert finished(browser, job["job_id"])["status"] == "completed"
        assert first_client.paused == ["a" * 40]
        assert second_client.paused == ["a" * 40]
        # Ordinary desktop mutations cannot change an in-flight agent's settings snapshot.
        settings.qbit.host = "http://changed.example"
        assert runtime.setup.settings.qbit.host == "http://second.example"


def test_failed_server_start_does_not_block_ordinary_settings(qtbot, tmp_path):
    from types import SimpleNamespace

    import pytest

    from torrentlinker.agent.desktop import DesktopServer, agent_settings_change

    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        runtime = DesktopServer(
            Settings(),
            tmp_path / "settings.json",
            Store(tmp_path / "state.db"),
            port=occupied.getsockname()[1],
        )
        with pytest.raises(OSError):
            runtime.start()
    calls = []

    @agent_settings_change
    def edit(window):
        calls.append("settings opened")

    edit(SimpleNamespace(agent_runtime=runtime))
    assert calls == ["settings opened"]
    try:
        runtime.start()  # the occupied port is now available; the same runtime can retry
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get(runtime.url.replace("/mcp/", "/healthz"), timeout=0.2).is_success:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.02)
            else:
                raise AssertionError("Desktop MCP did not recover after the port was released")
    finally:
        runtime.close()


def test_main_window_settings_stay_available_after_mcp_port_failure(qtbot, tmp_path, monkeypatch):
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.agent.desktop import DesktopServer
    from torrentlinker.gui import main_window

    window = main_window.MainWindow(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db")
    )
    qtbot.addWidget(window)
    opened = []

    def inspect(dialog):
        dialog.window().show()
        if dialog.view.section == "agents":
            wait_js(
                qtbot, dialog.view, "Boolean(document.querySelector('#settings-error').textContent)"
            )
            opened.append(
                js(qtbot, dialog.view, "document.querySelector('#settings-error').textContent")
            )
        else:
            wait_js(
                qtbot,
                dialog.view,
                "Boolean(document.querySelector('[aria-label=\"Client name\"]'))",
            )
            opened.append("connections")

    # Settings is a page: inspect it once opened, then leave it, which applies it.
    original_open = main_window.MainWindow.open_settings

    def open_then_inspect(self, **kwargs):
        original_open(self, **kwargs)
        if self._settings_page is not None:
            inspect(self._settings_page)
            self.close_settings()

    monkeypatch.setattr(main_window.MainWindow, "open_settings", open_then_inspect)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        window.agent_runtime = DesktopServer(
            window.settings, window.settings_path, window.store, port=occupied.getsockname()[1]
        )
        window.open_agent_access()
    assert "already in use" in opened[0] and "TorrentLinker instance" in opened[0]
    assert window.agent_runtime.app is None
    window.open_settings()
    assert opened[1] == "connections"


def test_saved_agent_startup_reuses_runtime_started_for_rss(qtbot, tmp_path, monkeypatch):
    from torrentlinker.agent import desktop
    from torrentlinker.gui.main_window import MainWindow

    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    server_class = desktop.DesktopServer
    monkeypatch.setattr(
        desktop,
        "DesktopServer",
        lambda settings, path, store, **kw: server_class(settings, path, store, port=port, **kw),
    )
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    # RSS startup uses this same accessor before the delayed saved-agent startup.
    service = window.assistant_service()
    runtime = window.agent_runtime
    try:
        window.start_saved_agent_access()
        window.assistant_tab.activate()
        assert "Address already in use" not in window.assistant_tab.startup_error
        assert window.assistant_tab.service is service
        assert window.agent_runtime is runtime
    finally:
        runtime.close()
        if window.agent_runtime is not None and window.agent_runtime is not runtime:
            window.agent_runtime.close()


def test_assistant_port_conflict_explains_recovery_and_can_retry(qtbot, tmp_path):
    from torrentlinker.agent.desktop import DesktopServer
    from torrentlinker.gui.main_window import MainWindow

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        runtime = DesktopServer(window.settings, window.settings_path, window.store, port=port)
        window.agent_runtime = runtime
        window.assistant_tab.activate()
        notice = window.assistant_tab.startup_error
        assert str(port) in notice and "reopen the Assistant tab to retry" in notice
        assert "Errno" not in notice
        assert window.assistant_tab.service is None
    try:
        window.assistant_tab.activate()
        assert window.assistant_tab.service is runtime.app.state.assistant
        assert "already in use" not in window.assistant_tab.startup_error
    finally:
        runtime.close()


def test_agent_access_reports_non_port_startup_failure(qtbot, tmp_path, monkeypatch):
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.agent.desktop import DesktopServer
    from torrentlinker.gui import main_window

    window = main_window.MainWindow(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db")
    )
    qtbot.addWidget(window)
    window.agent_runtime = DesktopServer(
        window.settings, window.settings_path, window.store, port=0
    )
    (tmp_path / "agents.sqlite").write_bytes(b"not a SQLite database" * 100)
    messages = []

    def inspect(dialog):
        dialog.window().show()
        wait_js(
            qtbot, dialog.view, "Boolean(document.querySelector('#settings-error').textContent)"
        )
        messages.append(
            js(qtbot, dialog.view, "document.querySelector('#settings-error').textContent")
        )

    # Settings is a page: inspect it once opened, then leave it, which applies it.
    original_open = main_window.MainWindow.open_settings

    def open_then_inspect(self, **kwargs):
        original_open(self, **kwargs)
        if self._settings_page is not None:
            inspect(self._settings_page)
            self.close_settings()

    monkeypatch.setattr(main_window.MainWindow, "open_settings", open_then_inspect)
    window.open_agent_access()
    assert window.agent_runtime.app is None
    assert "file is not a database" in messages[0]
    assert "another TorrentLinker instance" not in messages[0]


def test_desktop_agent_timer_does_not_wait_for_busy_job_lock(tmp_path):
    from torrentlinker.agent.desktop import DesktopServer

    settings = Settings()
    runtime = DesktopServer(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    runtime.app = create_app(
        tmp_path,
        password="test-password-long",
        service_override=runtime.setup,
        monitor_verifications=False,
    )
    locked, release = threading.Event(), threading.Event()

    def worker():
        with runtime.service.jobs.lock:
            locked.set()
            release.wait(3)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert locked.wait(1)
        settings.uploads += 1
        before = time.monotonic()
        runtime.sync(settings)
        assert runtime.busy()
        assert time.monotonic() - before < 0.25
        assert runtime.setup.settings.uploads != settings.uploads
    finally:
        release.set()
        thread.join(3)
    runtime.sync(settings)
    assert runtime.setup.settings.uploads == settings.uploads
    runtime.service.jobs.close()


def test_settings_sync_recovers_stale_suspension_without_unlocking_editor(tmp_path):
    from torrentlinker.agent.desktop import DesktopServer

    settings = Settings()
    runtime = DesktopServer(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    runtime.app = create_app(
        tmp_path,
        password="test-password-long",
        service_override=runtime.setup,
        monitor_verifications=False,
    )
    try:
        runtime.service.suspended = True
        runtime.sync(settings)
        assert not runtime.service.suspended
        with runtime.editing_settings():
            runtime.sync(settings)
            assert runtime.service.suspended
            with runtime.editing_settings():
                assert runtime.settings_edit_depth == 2
            assert runtime.service.suspended
        assert not runtime.service.suspended
    finally:
        runtime.service.jobs.close()


def test_agent_connections_are_embedded_without_discarding_settings(qtbot, tmp_path, monkeypatch):
    from tests.settings_support import edit_field, service_view
    from tests.test_community_interfaces import js, wait_js

    setup = DesktopSetup(
        Settings(language="en"), tmp_path / "settings.json", Store(tmp_path / "state.db")
    )
    app = create_app(
        tmp_path, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    service = app.state.agent_service
    view = service_view(qtbot, setup, agents=service)
    try:
        edit_field(qtbot, view, "Client name", "Unsaved client name")
        js(
            qtbot,
            view,
            "[...document.querySelectorAll('#settings-navigation button"
            "')].find(b=>b.textContent==='Agent access').click()",
        )
        wait_js(qtbot, view, "Boolean(document.querySelector('#agent-clients input'))")
        js(
            qtbot,
            view,
            "document.querySelector('[data-agent-tab=new]').click();doc"
            "ument.querySelector('#agent-name').value='Codex local draf"
            "ts';document.querySelector('#agent-clients input').checked"
            "=true;document.querySelector('#agent-form').requestSubmit("
            ")",
        )
        wait_js(qtbot, view, "Boolean(document.querySelector('#agent-token').value)")
        token = js(qtbot, view, "document.querySelector('#agent-token').value")
        assert len(service.access.snapshot()["connections"]) == 1
        assert token not in js(
            qtbot, view, "document.querySelector('#agent-connections').textContent"
        )
        js(
            qtbot,
            view,
            "[...document.querySelectorAll('#settings-navigation button"
            "')].find(b=>b.textContent==='Connections').click()",
        )
        assert (
            js(qtbot, view, "document.querySelector('[aria-label=\"Client name\"]').value")
            == "Unsaved client name"
        )
        assert setup.settings.profile().name != "Unsaved client name"
        js(
            qtbot,
            view,
            "[...document.querySelectorAll('#settings-navigation button"
            "')].find(b=>b.textContent==='Agent access').click()",
        )
        wait_js(qtbot, view, "Boolean(document.querySelector('#agent-token'))")
        assert js(qtbot, view, "document.querySelector('#agent-token').value") == ""
        qtbot.waitUntil(lambda: view.pending == 0)
    finally:
        view.close()
        service.jobs.close()


def test_embedded_approval_waits_until_settings_transaction_finishes(qtbot, tmp_path, monkeypatch):
    from tests.settings_support import service_view
    from torrentlinker.agent.settings_panel import AgentSettingsService

    setup = DesktopSetup(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    app = create_app(
        tmp_path, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    service = app.state.agent_service
    view = service_view(qtbot, setup, agents=service)
    calls = []
    monkeypatch.setattr(service, "execute", lambda *a, **k: calls.append(a))
    service.suspended = True
    try:
        endpoint = AgentSettingsService(service, view.queue_approval)
        assert endpoint.request("agents/proposals/review-one/approve", {}, "POST") == {
            "queued": True
        }
        endpoint.request("agents/proposals/review-one/approve", {}, "POST")
        assert view.agent_approvals == ["review-one"]
        assert calls == []
    finally:
        view.close()
        service.jobs.close()


def test_agent_runtime_started_in_settings_stays_suspended(qtbot, tmp_path, monkeypatch):
    from torrentlinker.agent import desktop
    from torrentlinker.gui import main_window

    server_class = desktop.DesktopServer
    monkeypatch.setattr(
        desktop,
        "DesktopServer",
        lambda settings, path, store, **kw: server_class(settings, path, store, port=0, **kw),
    )
    window = main_window.MainWindow(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db")
    )
    qtbot.addWidget(window)

    def inspect(dialog):
        from tests.test_community_interfaces import wait_js

        dialog.window().show()
        wait_js(qtbot, dialog.view, "Boolean(document.querySelector('#agent-clients input'))")
        assert window.agent_runtime.service.suspended
        assert window.agent_runtime.settings_edit_depth == 1

    # Settings is a page: inspect it once opened, then leave it, which applies it.
    original_open = main_window.MainWindow.open_settings

    def open_then_inspect(self, **kwargs):
        original_open(self, **kwargs)
        if self._settings_page is not None:
            inspect(self._settings_page)
            self.close_settings()

    monkeypatch.setattr(main_window.MainWindow, "open_settings", open_then_inspect)
    try:
        window.open_settings(agents=True)
        assert not window.agent_runtime.service.suspended
        assert window.agent_runtime.settings_edit_depth == 0
    finally:
        if window.agent_runtime:
            window.agent_runtime.close()


def test_agent_token_can_be_saved_privately(qtbot, tmp_path, monkeypatch):
    import json
    import os
    import stat

    from PySide6.QtWidgets import QFileDialog

    from tests.settings_support import settings_page

    dialog = settings_page(qtbot, tmp_path)
    destination = tmp_path / "token.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    dialog.view.bridge.requestAsync(
        999,
        "save-token",
        json.dumps(
            {"_client": dialog.setup.settings.active_client_id, "token": "example-token-for-test"}
        ),
    )
    assert destination.read_text() == "example-token-for-test\n"
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
