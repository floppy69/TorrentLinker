"""Members never receive another person's queue, paths, tracker URLs or client actions."""

from types import SimpleNamespace

import pytest

from tests.test_members_requests import server as requests_server
from tests.test_members_signin import PASSWORD, member
from torrentlinker.accounts import OWNER, Permission
from torrentlinker.member_requests import Release


@pytest.fixture
def server(tmp_path):
    yield from requests_server.__wrapped__(tmp_path)


def test_member_reads_only_their_accepted_downloads(server, monkeypatch):
    app, browser = server
    lea = member(app, "lea", Permission.QUEUE, Permission.TORRENTS)
    other = member(app, "other", Permission.QUEUE)
    requests = app.state.requests
    own = requests.ask(lea, Release("a" * 40, "Own release", 10, "Own"))
    hidden = requests.ask(other, Release("b" * 40, "Secret release", 20, "Secret"))
    requests.ask(lea, Release("c" * 40, "Pending release", 30, "Pending"))
    requests.answer(own["id"], OWNER)
    requests.answer(hidden["id"], OWNER)
    client = SimpleNamespace(
        torrents=lambda **kwargs: [
            SimpleNamespace(
                hash="a" * 40,
                size=10,
                progress=0.4,
                save_path="/private",
                tracker="https://secret/passkey",
            ),
            SimpleNamespace(
                hash="b" * 40,
                size=20,
                progress=0.8,
                save_path="/other",
                tracker="https://secret/other",
            ),
        ]
    )
    monkeypatch.setattr(
        app.state.agent_service.media, "setup", lambda _: SimpleNamespace(client=lambda: client)
    )
    browser.post("/api/login", json={"login": "lea", "password": PASSWORD})
    queue = browser.get("/api/member-workspace/queue").json()["rows"]
    assert [row["id"] for row in queue] == [own["id"]]
    response = browser.get("/api/member-workspace/torrents?client_id=other")
    assert response.json()["rows"] == [
        {"id": own["id"], "title": "Own", "size": 10, "progress": 0.4, "state": "downloading"}
    ]
    assert (
        "/private" not in response.text
        and "secret" not in response.text
        and "tracker" not in response.text
    )
    for path in ("/api/torrents", "/api/queue", "/api/settings"):
        assert browser.get(path).status_code == 403
    assert browser.post("/api/search/workspace/start", json={}).status_code == 403
    assert browser.post("/api/torrents/workspace", json={"action": "delete"}).status_code == 403
    assert browser.get("/api/member-workspace/search?q=test").status_code == 403
    assert {"member-queue", "member-torrents"} <= set(browser.get("/api/shell").json()["pages"])


def test_search_respects_media_visibility_and_uses_requests(server, monkeypatch):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS, Permission.SEARCH, Permission.REQUEST)
    calls = []

    def choices(q):
        calls.append(q)
        return [{"hash": "a" * 40, "name": "Film", "size": 10, "score": 80}]

    monkeypatch.setattr(app.state.request_approval, "choices", choices)
    browser.post("/api/login", json={"login": "lea", "password": PASSWORD})
    result = browser.get("/api/member-workspace/search?q=Film")
    assert result.json()["rows"][0]["name"] == "Film"
    assert calls == ["Film"]
    app.state.accounts.set_media_limits(lea, "12", None)
    assert browser.get("/api/member-workspace/search?q=Film").json() == {"rows": []}
    assert calls == ["Film"]
    assert browser.get("/api/member-workspace/queue").status_code == 403
