"""Approvers claim answers once; failed sends remain retryable without leaking secrets."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.test_members_requests import server as requests_server
from tests.test_members_signin import PASSWORD, member
from tests.test_web_jobs import login
from torrentlinker.accounts import OWNER, Caps, Permission
from torrentlinker.member_requests import Release, Requests


@pytest.fixture
def server(tmp_path):
    yield from requests_server.__wrapped__(tmp_path)


RELEASE = Release("a" * 40, "Example.2025.1080p", 100, "Example", "2025")


def test_first_approver_wins_and_own_answers_are_unread(tmp_path):
    from torrentlinker.accounts import Accounts

    accounts = Accounts(tmp_path)
    requests = Requests(accounts)
    row = requests.ask(OWNER, RELEASE)

    def answer(actor):
        try:
            return requests.answer(row["id"], actor)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(answer, [OWNER, "another"]))
    assert sum(a is not None for a in answers) == 1
    assert requests.get(row["id"])["state"] == "accepted"
    assert requests.get(row["id"])["unread"]
    with pytest.raises(ValueError):
        requests.cancel(OWNER, row["id"])
    accounts.close()


def test_wish_resolution_records_over_quota(tmp_path):
    from torrentlinker.accounts import Accounts

    accounts = Accounts(tmp_path)
    person = accounts.create("Lea", "lea", {Permission.WISH})
    accounts.set_caps(person, Caps(bytes_per_week=10))
    requests = Requests(accounts)
    row = requests.wish(person, "Example")
    result = requests.answer(row["id"], OWNER, release=RELEASE)
    assert result["infohash"] == RELEASE.infohash
    assert "weekly quota" in result["answer"]
    assert requests.review()[0]["events"][-1]["state"] == "accepted"
    accounts.close()


def test_approval_permissions_failure_and_retry(server, monkeypatch):
    app, browser = server
    requests = app.state.requests
    requester = member(app, "lea", Permission.REQUEST)
    row = requests.ask(requester, RELEASE)
    browser.post("/api/login", json={"login": "lea", "password": PASSWORD})
    path = f"/api/requests/{row['id']}"
    assert browser.post(path + "/accept", json={}).status_code == 403
    assert browser.get("/api/requests/review").status_code == 403
    browser.cookies.clear()
    login(browser)
    sent = []

    def fail(infohash):
        sent.append(infohash)
        raise ValueError("https://secret:password@tracker/private")

    monkeypatch.setattr(app.state.request_approval, "send", fail)
    result = browser.post(path + "/accept", json={})
    assert result.status_code == 200
    assert result.json()["state"] == "send_failed"
    assert "secret" not in result.text
    assert browser.post(path + "/accept", json={}).status_code == 409
    monkeypatch.setattr(app.state.request_approval, "send", lambda infohash: sent.append(infohash))
    result = browser.post(path + "/retry", json={})
    assert result.json()["state"] == "sent"
    assert sent == [RELEASE.infohash, RELEASE.infohash]
    assert browser.post(path + "/retry", json={}).status_code == 409


@pytest.mark.parametrize("confirmed", [True, False])
def test_client_handoff_requires_receipt(monkeypatch, confirmed):
    from types import SimpleNamespace

    import torrentlinker.request_approval as module
    from torrentlinker.request_approval import RequestApproval

    sent = []
    client = SimpleNamespace(torrents=lambda **kwargs: [])
    setup = SimpleNamespace(client=lambda: client, store=object())
    operations = SimpleNamespace(
        run=lambda request, stop, progress: {
            "rows": [{"hash": RELEASE.infohash, "outcome": "sent" if confirmed else "failed"}]
        }
    )
    media = SimpleNamespace(
        setup=lambda _client: setup,
        tracker_enqueue=lambda client, setup, infohash: sent.append(infohash),
        agent=SimpleNamespace(
            setup=SimpleNamespace(settings=SimpleNamespace(default_client_id="default")),
            for_client=lambda _client: operations,
        ),
    )
    monkeypatch.setattr(module, "entries", lambda _store: [])
    approval = RequestApproval(media)
    if confirmed:
        approval.send(RELEASE.infohash)
    else:
        with pytest.raises(ValueError, match="did not confirm"):
            approval.send(RELEASE.infohash)
    assert sent == [RELEASE.infohash]
    client.torrents = lambda **kwargs: [SimpleNamespace(hash=RELEASE.infohash)]
    approval.send(RELEASE.infohash)
    assert sent == [RELEASE.infohash]  # Retry detects a previous successful send.


@pytest.mark.parametrize("query", ["Example", "director name"])
def test_wish_search_caches_authoritative_releases(monkeypatch, query):
    from dataclasses import dataclass
    from types import SimpleNamespace

    import torrentlinker.torrent_search as search
    from torrentlinker.request_approval import RequestApproval

    @dataclass
    class Facts:
        title: str = "Example"
        kind: str = "movie"
        year: int = 2025

    candidate = SimpleNamespace(
        infohash=RELEASE.infohash,
        title=RELEASE.name,
        size=100,
        seeders=4,
        categories=(1,),
        published_at=0,
    )
    seen = []

    def find(indexer, params):
        seen.append(params)
        return SimpleNamespace(rows=[candidate], details={RELEASE.infohash: Facts()})

    monkeypatch.setattr(search, "native_search", find)
    cache = {}
    setup = SimpleNamespace(
        indexer=lambda: object(),
        settings=SimpleNamespace(default_client_id="default", release_score={}),
    )
    media = SimpleNamespace(
        setup=lambda client: setup,
        agent=SimpleNamespace(setup=setup),
        _tracker_cache=lambda client, kind: cache if kind == "tracker-new" else {},
        _tracker_save=lambda client, kind, key, entry: cache.update({key: entry}),
        _score=lambda *args: {"score": 87},
    )
    choices = RequestApproval(media).choices(query)
    assert seen == [{"name": query, "category": "1"}]
    assert choices == [{"hash": RELEASE.infohash, "name": RELEASE.name, "size": 100, "score": 87}]
    assert next(iter(cache.values()))["releases"][0]["category"] == 1


def test_restart_requires_retry_and_completed_media_becomes_available(tmp_path):
    from types import SimpleNamespace

    from torrentlinker.accounts import Accounts
    from torrentlinker.media_tracker import film_key
    from torrentlinker.request_approval import RequestApproval

    accounts = Accounts(tmp_path)
    requests = Requests(accounts)
    row = requests.ask(OWNER, RELEASE)
    requests.answer(row["id"], OWNER)
    requests.recover_sends()
    assert requests.get(row["id"])["state"] == "send_failed"
    requests.answer(row["id"], OWNER, retry=True)
    requests.move(row["id"], "sent", "")
    torrent = SimpleNamespace(hash=RELEASE.infohash, progress=0.5)
    setup = SimpleNamespace(
        client=lambda: SimpleNamespace(torrents=lambda **kwargs: [torrent]),
        settings=SimpleNamespace(default_client_id="default"),
    )
    films = {}
    media = SimpleNamespace(
        setup=lambda _client: setup,
        agent=SimpleNamespace(setup=setup),
        _library_films=lambda _client: films,
    )
    approval = RequestApproval(media)
    approval.refresh(requests)
    assert requests.get(row["id"])["state"] == "downloading"
    torrent.progress = 1
    approval.refresh(requests)
    assert requests.get(row["id"])["state"] == "downloading"
    films[film_key(RELEASE.title, RELEASE.year)] = {}
    approval.refresh(requests)
    assert requests.get(row["id"])["state"] == "available"
    accounts.close()
