"""Member model calls never reach Owner tools, history or provider settings."""

from types import SimpleNamespace

import pytest

from tests.test_members_requests import server as requests_server
from tests.test_members_signin import PASSWORD, member
from torrentlinker.accounts import Caps, Permission
from torrentlinker.member_requests import Release


@pytest.fixture
def server(tmp_path):
    yield from requests_server.__wrapped__(tmp_path)


def configured(app, monkeypatch, turn=None):
    assistant = app.state.assistant
    monkeypatch.setattr(
        assistant,
        "chat_defaults",
        lambda: SimpleNamespace(provider_id="hidden", max_output_tokens=2048),
    )
    monkeypatch.setattr(assistant, "provider", lambda _: SimpleNamespace(kind="openai"))
    monkeypatch.setattr(assistant, "secrets", SimpleNamespace(get=lambda _: "secret-api-key"))
    monkeypatch.setattr(
        assistant.models, "turn", turn or (lambda *args, **kwargs: ("Hello Member", [], 10))
    )
    return assistant


def signin(browser, name):
    browser.cookies.clear()
    return browser.post("/api/login", json={"login": name, "password": PASSWORD})


def test_conversations_and_provider_settings_are_private_and_daily_cap_applies(server, monkeypatch):
    app, browser = server
    lea = member(app, "lea", Permission.ASSISTANT)
    member(app, "other", Permission.ASSISTANT)
    configured(app, monkeypatch)
    app.state.accounts.set_caps(lea, Caps(assistant_per_day=1))
    signin(browser, "lea")
    first = browser.post("/api/member-assistant", json={"message": "private question"})
    assert first.status_code == 200, first.text
    result = first.json()
    identifier = result["conversation"]["id"]
    assert result["usage"]["remaining"] == 0
    assert "secret-api-key" not in first.text and "hidden" not in first.text
    assert browser.post("/api/member-assistant", json={"message": "again"}).status_code == 429
    assert browser.get("/api/setup/assistant").status_code == 403
    assert browser.get("/api/assistant/conversations").status_code == 403
    signin(browser, "other")
    assert browser.get(f"/api/member-assistant/{identifier}").status_code == 404
    assert browser.delete(f"/api/member-assistant/{identifier}").status_code == 404
    assert browser.get("/api/member-assistant").json()["conversations"] == []
    assert (
        browser.post(
            "/api/member-assistant", json={"conversation_id": identifier, "message": "steal"}
        ).status_code
        == 404
    )
    app.state.accounts.disable(lea)
    app.state.accounts.delete(lea)
    assert (
        app.state.accounts.db.execute(
            "SELECT COUNT(*) FROM member_chats WHERE account=?", (lea,)
        ).fetchone()[0]
        == 0
    )


def test_tools_recheck_permissions_and_downloads_become_requests(server, monkeypatch):
    app, _browser = server
    lea = member(
        app, "lea", Permission.FILMS, Permission.SEARCH, Permission.REQUEST, Permission.ASSISTANT
    )
    service = app.state.member_assistant
    monkeypatch.setattr(
        app.state.request_approval,
        "release",
        lambda _: Release("a" * 40, "Film.2025", 100, "Film", "2025"),
    )
    result = service.tool(lea, "request_film", {"infohash": "a" * 40})
    assert result["state"] == "pending"
    assert len(app.state.requests.mine(lea)) == 1
    for tool in ("execute", "download", "read_file", "list_accounts", "setup", "schedule"):
        with pytest.raises(PermissionError):
            service.tool(lea, tool, {})
    app.state.accounts.grant(lea, {Permission.ASSISTANT})
    with pytest.raises(PermissionError):
        service.tool(lea, "request_film", {"infohash": "b" * 40})
    app.state.accounts.disable(lea)
    with pytest.raises(PermissionError):
        service.chats(lea)


def test_midnight_usage_reset_and_provider_errors_are_sanitized(server, monkeypatch):
    app, browser = server
    lea = member(app, "lea", Permission.ASSISTANT)
    service = app.state.member_assistant
    app.state.accounts.db.execute(
        "INSERT INTO member_assistant_usage VALUES (?,?,?)", (lea, "2000-01-01", 100)
    )
    assert service.usage(lea)["remaining"] == 20

    def fail(*args, **kwargs):
        raise RuntimeError("https://secret-api-key@private-provider")

    configured(app, monkeypatch, fail)
    signin(browser, "lea")
    result = browser.post("/api/member-assistant", json={"message": "Hello"})
    assert result.status_code == 502
    assert "secret-api-key" not in result.text and "private-provider" not in result.text
    assert service.usage(lea)["used"] == 1
    assert not service.busy


def test_daily_cap_reservation_is_atomic_and_media_results_are_filtered(server, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from torrentlinker.member_assistant import DailyCap

    app, _browser = server
    lea = member(app, "lea", Permission.ASSISTANT, Permission.FILMS)
    configured(app, monkeypatch)
    app.state.accounts.set_caps(lea, Caps(assistant_per_day=1))
    service = app.state.member_assistant

    def send(_):
        try:
            return service.send(lea, "hello")
        except DailyCap:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(send, range(2)))
    assert sum(result is not None for result in results) == 1
    assert service.usage(lea)["used"] == 1

    def listing(client, **options):
        assert options["actor"].account == lea
        return {
            "rows": [
                {
                    "id": "one",
                    "title": "Film",
                    "year": "2025",
                    "kind": "video",
                    "path": "/private",
                    "token": "secret",
                }
            ]
        }

    monkeypatch.setattr(app.state.agent_service.media, "listing", listing)
    assert service.tool(lea, "find_media", {"query": "Film"}) == {
        "rows": [{"id": "one", "title": "Film", "year": "2025", "kind": "video"}]
    }
