from fastapi.testclient import TestClient

from tests.test_web_jobs import Client, login
from torrentlinker.web.app import create_app


def test_agent_access_is_disabled_and_new_connections_only_propose(tmp_path):
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    ) as browser:
        assert browser.get("/api/agents").status_code == 401
        login(browser)
        state = browser.get("/api/agents")
        assert state.status_code == 200
        assert state.json()["enabled"] is False
        created = browser.post("/api/agents", json={"name": "My assistant", "clients": ["default"]})
        assert created.status_code == 200, created.text
        grant = created.json()
        assert grant["mode"] == "propose"
        assert grant["permissions"] == []
        assert len(grant["token"]) >= 32
        assert grant["token"] not in browser.get("/api/agents").text
        assert browser.post(f"/api/agents/{grant['id']}/revoke").status_code == 200
        assert browser.get("/api/agents").json()["connections"][0]["revoked"] is True


def rpc(browser, token, name, arguments=None):
    return browser.post(
        "/mcp/",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": name, "params": arguments or {}},
    )


def call(browser, token, name, arguments=None):
    response = rpc(browser, token, "tools/call", {"name": name, "arguments": arguments or {}})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_mcp_requires_its_own_token_and_proposes_changes_without_executing(tmp_path):
    client = Client()
    client.release.set()
    with TestClient(
        create_app(
            tmp_path, password="test-password-long", connector=lambda *args, client=client: client
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        grant = browser.post("/api/agents", json={"name": "Helper", "clients": ["default"]}).json()
        token = grant["token"]
        assert rpc(browser, token, "tools/list").status_code == 401
        browser.put("/api/agents", json={"enabled": True})
        assert rpc(browser, "", "tools/list").status_code == 401  # browser cookie is insufficient
        tools = rpc(browser, token, "tools/list").json()["result"]["tools"]
        assert "propose_action" in {t["name"] for t in tools}
        result = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "pause-book",
                "operation": {
                    "kind": "manage",
                    "client_id": "default",
                    "action": "pause",
                    "hashes": ["a" * 40],
                },
            },
        )
        assert not result.get("isError"), result
        proposal = result["structuredContent"]
        assert proposal["status"] == "pending"
        assert client.paused == []
        pending = browser.get("/api/agents").json()["proposals"][0]
        assert pending["id"] == proposal["id"]
        assert "id" in proposal, proposal
        approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
        assert approved.status_code == 200, approved.text
        from tests.test_web_jobs import finished

        assert finished(browser, approved.json()["job_id"])["status"] == "completed"
        assert client.paused == ["a" * 40]
        repeated = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "pause-book",
                "operation": {
                    "kind": "manage",
                    "client_id": "default",
                    "action": "pause",
                    "hashes": ["a" * 40],
                },
            },
        )
        assert repeated["structuredContent"]["job_id"] == approved.json()["job_id"]
        browser.post(f"/api/agents/{grant['id']}/revoke")
        assert rpc(browser, token, "tools/list").status_code == 401


def test_agent_cannot_escalate_scope_or_approve_its_own_deletion(tmp_path):
    client = Client()
    client.release.set()
    with TestClient(
        create_app(
            tmp_path, password="test-password-long", connector=lambda *args, client=client: client
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        grant = browser.post(
            "/api/agents",
            json={
                "name": "Helper",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["controls"],
            },
        ).json()
        browser.put("/api/agents", json={"enabled": True})
        token = grant["token"]
        wrong = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "wrong-client",
                "operation": {
                    "kind": "manage",
                    "client_id": "another",
                    "action": "pause",
                    "hashes": ["a" * 40],
                },
            },
        )["structuredContent"]
        assert "error" in wrong
        deletion = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "delete-book",
                "operation": {
                    "kind": "manage",
                    "client_id": "default",
                    "action": "delete",
                    "hashes": ["a" * 40],
                },
            },
        )["structuredContent"]
        assert deletion["requires_owner_approval"] is True
        assert client.paused == []
        # Revocation also invalidates outstanding owner approvals.
        browser.post(f"/api/agents/{grant['id']}/revoke")
        result = browser.post(f"/api/agents/proposals/{deletion['id']}/approve")
        assert result.status_code in {400, 403}, result.text


def test_origin_is_rejected_even_with_an_agent_token(tmp_path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        login(browser)
        grant = browser.post("/api/agents", json={"name": "Helper", "clients": ["default"]}).json()
        browser.put("/api/agents", json={"enabled": True})
        browser.headers["Origin"] = "https://evil.example"
        assert rpc(browser, grant["token"], "tools/list").status_code == 403


def test_zero_download_budget_cannot_be_bypassed_by_owner_approval(tmp_path, monkeypatch):
    import httpx

    from torrentlinker import net

    def response(request):
        return httpx.Response(
            200,
            text=(
                '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel><item>'
                "<title>Book</title><size>1024</size>"
                '<enclosure url="https://tracker.example/file" length="1024" '
                'type="application/x-bittorrent"/>'
                '<torznab:attr name="infohash" value="' + "a" * 40 + '"/>'
                "</item></channel></rss>"
            ),
        )

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response))
    )
    root = tmp_path / "media"
    root.mkdir()
    (root / "Book").write_bytes(b"x" * 1024)

    class FilesClient(Client):
        def files(self, hash):
            return {"Book": 1024}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: FilesClient(),
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        browser.post(
            "/api/setup/indexer", json={"url": "https://tracker.example/api", "api_key": "test"}
        )
        browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/remote", "purpose": "download"},
        )
        grant = browser.post(
            "/api/agents", json={"name": "Helper", "clients": ["default"], "daily_bytes": 0}
        ).json()
        browser.put("/api/agents", json={"enabled": True})
        token = grant["token"]
        search = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "find",
                "operation": {"kind": "search", "client_id": "default", "query": "Book"},
            },
        )["structuredContent"]
        from tests.test_web_jobs import finished

        assert finished(browser, search["job_id"])["status"] == "completed"
        proposal = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "queue",
                "operation": {"kind": "enqueue", "client_id": "default", "hashes": ["a" * 40]},
            },
        )["structuredContent"]
        assert "id" in proposal, proposal
        approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
        assert approved.is_success, approved.text
        queued = finished(browser, approved.json()["job_id"])
        assert queued["status"] == "completed", queued
        assert len(browser.get("/api/queue").json()) == 1
        send = call(
            browser,
            token,
            "propose_action",
            {
                "request_id": "send",
                "operation": {"kind": "send-queue", "client_id": "default", "hashes": ["a" * 40]},
            },
        )["structuredContent"]
        denied = browser.post(f"/api/agents/proposals/{send['id']}/approve")
        assert denied.status_code == 400
        assert "budget" in denied.text.lower()


def test_saved_goal_uses_estimates_without_changing_the_actual_class(tmp_path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        login(browser)
        grant = browser.post("/api/agents", json={"name": "Helper", "clients": ["default"]}).json()
        browser.put("/api/agents", json={"enabled": True})
        token = grant["token"]
        before = call(browser, token, "overview")["structuredContent"]["zen_profile"]
        goal = call(
            browser,
            token,
            "save_goal",
            {
                "goal_id": "steady-seed",
                "revision": 0,
                "goal": {
                    "name": "Steady seeding",
                    "client_ids": ["default"],
                    "target_daily_zen": 200,
                    "desired_class": "swarm-keeper",
                },
            },
        )["structuredContent"]
        assert goal["revision"] == 1
        stale = call(
            browser,
            token,
            "save_goal",
            {
                "goal_id": "steady-seed",
                "revision": 0,
                "goal": {
                    "name": "Wrong revision",
                    "client_ids": ["default"],
                    "target_daily_zen": 10,
                },
            },
        )
        assert stale.get("isError") or "error" in stale["structuredContent"]
        progress = call(browser, token, "goal_status", {"goal_id": "steady-seed"})[
            "structuredContent"
        ]
        assert progress["target_daily_zen"] == 200
        assert progress["daily_zen"] is None  # no refreshed clients, not a false zero
        after = call(browser, token, "overview")["structuredContent"]["zen_profile"]
        assert before == after


def test_successful_mcp_jobs_keep_empty_errors_on_desktop_and_web(tmp_path):
    from tests.test_web_jobs import finished
    from torrentlinker.agent.desktop import DesktopSetup
    from torrentlinker.config import Settings
    from torrentlinker.store import Store

    for desktop in (False, True):
        directory = tmp_path / ("desktop" if desktop else "web")
        directory.mkdir()
        client = Client()
        client.release.set()
        setup = None
        if desktop:
            setup = DesktopSetup(
                Settings(), directory / "settings.json", Store(directory / "state.db")
            )
            setup.connector = lambda *args, client=client: client
        app = create_app(
            directory,
            password="test-password-long",
            connector=lambda *args, client=client: client,
            service_override=setup,
            monitor_verifications=False,
        )
        with TestClient(app) as browser:
            login(browser)
            if not desktop:
                browser.post(
                    "/api/setup/client", json={"client": "deluge", "host": "https://box.example"}
                )
            grant = browser.post(
                "/api/agents", json={"name": "Job status", "clients": ["default"]}
            ).json()
            browser.put("/api/agents", json={"enabled": True})
            result = call(
                browser,
                grant["token"],
                "propose_action",
                {"request_id": "refresh", "operation": {"kind": "refresh", "client_id": "default"}},
            )["structuredContent"]
            assert finished(browser, result["job_id"])["status"] == "completed"
            status = call(browser, grant["token"], "job_status", {"job_id": result["job_id"]})[
                "structuredContent"
            ]
            assert status["status"] == "completed"
            assert status["error"] == ""
            proposal = call(
                browser,
                grant["token"],
                "propose_action",
                {
                    "request_id": "review-removal",
                    "operation": {
                        "kind": "manage",
                        "action": "delete",
                        "hashes": ["a" * 40],
                        "client_id": "default",
                    },
                },
            )["structuredContent"]
            reviewed = browser.get(f"/api/agents/proposals/{proposal['id']}/review")
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["torrents"][0]["name"] == "Book"
            assert reviewed.json()["torrents"][0]["folder"] == "/remote"


def test_download_budget_accounts_for_incomplete_client_data(tmp_path, monkeypatch):
    from collections import namedtuple
    from pathlib import Path

    from torrentlinker.agent.desktop import DesktopSetup
    from torrentlinker.config import Settings
    from torrentlinker.domain import Torrent
    from torrentlinker.store import CatalogueRow, Store

    root = tmp_path / "media"
    root.mkdir()
    settings = Settings()
    settings.ensure_profiles()
    settings.download_folders.default = str(root)
    settings.free_space_margin = 0
    settings.capture_client()
    store = Store(tmp_path / "state.db")
    store.save_catalogue(
        [CatalogueRow("b" * 40, "Next book", 1000, 5, 7000, "https://example/file", "", 0)]
    )
    from types import SimpleNamespace

    from torrentlinker.download_queue import enqueue
    from torrentlinker.indexer import Candidate

    enqueue(
        store,
        SimpleNamespace(url="https://example", redact=lambda value: value),
        Candidate("Next book", 1000, "https://example/file", 5, infohash="b" * 40),
        root,
    )
    setup = DesktopSetup(settings, tmp_path / "settings.json", store)
    pending = Torrent(
        "a" * 40, "Downloading book", Path(root), size=1000, progress=0, state="downloading"
    )
    client = Client()
    client.torrents = lambda **kwargs: [pending]
    setup.connector = lambda *args, client=client: client
    usage = namedtuple("usage", "total used free")(10000, 7500, 2500)
    monkeypatch.setattr("torrentlinker.agent.budgets.shutil.disk_usage", lambda _: usage)
    with TestClient(
        create_app(
            tmp_path,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        grant = browser.post(
            "/api/agents",
            json={"name": "Storage check", "clients": ["default"], "reserve_bytes": 1000},
        ).json()
        browser.put("/api/agents", json={"enabled": True})
        proposal = call(
            browser,
            grant["token"],
            "propose_action",
            {
                "request_id": "queue-next",
                "operation": {"kind": "send-queue", "client_id": "default", "hashes": ["b" * 40]},
            },
        )["structuredContent"]
        result = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
        assert result.status_code == 400
        assert "reserve" in result.text.lower()


def test_disabling_agent_access_cancels_jobs_beyond_the_display_page(tmp_path):
    import threading

    from tests.test_web_jobs import finished

    entered = threading.Event()
    stopped = threading.Event()
    app = create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    with TestClient(app) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        grant = browser.post("/api/agents", json={"name": "Helper", "clients": ["default"]}).json()
        browser.put("/api/agents", json={"enabled": True})
        service = app.state.agent_service

        def blocked(request, stop, progress):
            entered.set()
            assert stop.wait(60), "Disabling MCP must cancel this job"
            stopped.set()
            return {}

        target = service.for_client("default")
        target.run = blocked
        pending = call(
            browser,
            grant["token"],
            "propose_action",
            {"request_id": "running", "operation": {"kind": "refresh", "client_id": "default"}},
        )["structuredContent"]
        assert entered.wait(2)
        for i in range(101):
            result = call(
                browser,
                grant["token"],
                "propose_action",
                {
                    "request_id": f"later-{i}",
                    "operation": {
                        "kind": "manage",
                        "client_id": "default",
                        "action": "pause",
                        "hashes": ["a" * 40],
                    },
                },
            )
            assert not result.get("isError"), result
        assert browser.put("/api/agents", json={"enabled": False}).status_code == 200
        assert stopped.wait(2)
        assert finished(browser, pending["job_id"])["status"] == "cancelled"
