"""Members 6 (#133): Requests and Wishes, the Member's side."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import member, sign_in
from tests.test_web_jobs import login
from torrentlinker.accounts import Accounts, Caps, Permission
from torrentlinker.member_requests import EXPIRY, CapReached, Release, Requests, week
from torrentlinker.web.app import create_app

GB = 10**9
DUNE = "d" * 40


def release(infohash: str, size: int = 7 * GB, title: str = "Dune") -> Release:
    return Release(infohash, f"{title}.2024.1080p", size, title, "2024")


@pytest.fixture
def store(tmp_path):
    accounts = Accounts(tmp_path)
    lea = accounts.create("Léa", "lea", {Permission.REQUEST, Permission.WISH})
    return accounts, Requests(accounts), lea


def test_the_week_runs_monday_to_sunday_server_time():
    wednesday = datetime(2026, 11, 18, 15, 30).timestamp()
    start, reset = week(wednesday)
    assert datetime.fromtimestamp(start) == datetime(2026, 11, 16)
    assert datetime.fromtimestamp(reset) == datetime(2026, 11, 23)
    sunday_night = datetime(2026, 11, 22, 23, 59).timestamp()
    assert week(sunday_night) == (start, reset)


def test_caps_count_accepted_this_week_and_pending(store):
    accounts, requests, lea = store
    accounts.set_caps(lea, Caps(requests_per_week=3, bytes_per_week=20 * GB, pending=2))
    first = requests.ask(lea, release("1" * 40))
    requests.ask(lea, release("2" * 40))
    # Two pending: the pending cap refuses a third, with no reset.
    with pytest.raises(CapReached) as refused:
        requests.wish(lea, "Le dernier Miyazaki")
    assert refused.value.cap == "pending" and refused.value.reset is None
    # Accepted this week still counts toward the week, not toward pending.
    requests.move(first["id"], "accepted", "owner")
    quota = requests.quota(lea)
    assert quota["requests_left"] == 1 and quota["pending_left"] == 1
    assert quota["bytes_left"] == 6 * GB
    with pytest.raises(CapReached) as refused:
        requests.ask(lea, release("3" * 40, size=8 * GB))
    assert refused.value.cap == "size" and refused.value.reset == week(quota["reset"] - 1)[1]
    requests.ask(lea, release("3" * 40, size=6 * GB))
    with pytest.raises(CapReached) as refused:
        requests.wish(lea, "Ponyo")
    assert refused.value.cap in {"count", "pending"}


def test_refused_cancelled_and_expired_requests_give_their_slot_back(store):
    accounts, requests, lea = store
    accounts.set_caps(lea, Caps(requests_per_week=1))
    asked = requests.ask(lea, release(DUNE))
    with pytest.raises(CapReached):
        requests.ask(lea, release("e" * 40))
    requests.cancel(lea, asked["id"])
    asked = requests.ask(lea, release("e" * 40))
    requests.move(asked["id"], "refused", "owner", "Pas cette semaine")
    assert requests.quota(lea)["requests_left"] == 1
    # Accepted last week does not count this week.
    last_week = week(requests.quota(lea)["reset"])[0] - 8 * 86400
    old = requests.ask(lea, release("f" * 40))
    requests.move(old["id"], "accepted", "owner", now=last_week)
    assert requests.quota(lea)["requests_left"] == 1


def test_a_pending_request_expires_after_14_days_and_is_new_to_the_member(store):
    _, requests, lea = store
    asked = requests.ask(lea, release(DUNE))
    assert not requests.get(asked["id"])["unread"]
    requests.expire(asked["created"] + EXPIRY + 1)
    found = requests.get(asked["id"])
    assert found["state"] == "expired" and found["unread"]
    requests.seen(lea)
    assert not requests.get(asked["id"])["unread"]
    # Only a pending one can be cancelled.
    with pytest.raises(ValueError):
        requests.cancel(lea, asked["id"])


def test_an_answer_is_unread_with_the_approvers_note(store):
    accounts, requests, lea = store
    approver = accounts.create("Hugo", "hugo", {Permission.APPROVE})
    asked = requests.ask(lea, release(DUNE))
    requests.move(asked["id"], "refused", approver, "On l'a déjà en 4K")
    [found] = requests.mine(lea)
    assert found["unread"] and found["answered_by"] == "Hugo"
    assert found["answer"] == "On l'a déjà en 4K"
    # Refused: the same release may be asked again, but not twice while open.
    requests.ask(lea, release(DUNE))
    with pytest.raises(ValueError, match="already asked"):
        requests.ask(lea, release(DUNE))


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path, members_enabled=True, password="test-password-long", monitor_verifications=False
    )
    library = app.state.agent_service.media

    def entry(client_id, infohash):
        if infohash != DUNE:
            raise ValueError("This tracker release is no longer suggested.")
        best = {"hash": DUNE, "name": "Dune.Part.Two.2024.1080p", "size": 7 * GB}
        return {"facts": {"title": "Dune : Deuxième partie", "year": 2024}, "release": best}

    library.tracker_entry = entry
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser


def test_a_member_asks_for_a_tracker_film_and_cancels_it(server):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS, Permission.REQUEST)
    sign_in(browser, "lea")
    assert browser.post(f"/api/media/tracker/{DUNE}/download", json={}).status_code == 403
    asked = browser.post("/api/requests", json={"infohash": DUNE, "client_id": "x"})
    assert asked.status_code == 200, asked.text
    assert asked.json()["title"] == "Dune : Deuxième partie" and asked.json()["size"] == 7 * GB
    assert browser.post("/api/requests", json={"infohash": DUNE}).status_code == 409
    assert browser.post("/api/requests", json={"infohash": "b" * 40}).status_code == 404
    mine = browser.get("/api/requests").json()
    assert [r["state"] for r in mine["requests"]] == ["pending"]
    assert mine["quota"]["requests_left"] is None
    identifier = asked.json()["id"]
    assert browser.post(f"/api/requests/{identifier}/cancel").json()["state"] == "cancelled"
    # Wishes need their own Permission.
    assert browser.post("/api/wishes", json={"title": "Ponyo"}).status_code == 403
    app.state.accounts.grant(lea, {Permission.FILMS, Permission.WISH})
    wished = browser.post("/api/wishes", json={"title": "Ponyo", "year": "2008", "note": "VF"})
    assert wished.status_code == 200 and wished.json()["kind"] == "wish"
    assert browser.post("/api/wishes", json={"title": " "}).status_code == 400


def test_a_reached_cap_says_why_and_when_it_resets(server):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS, Permission.REQUEST)
    app.state.accounts.set_caps(lea, Caps(requests_per_week=0))
    sign_in(browser, "lea")
    refused = browser.post("/api/requests", json={"infohash": DUNE})
    assert refused.status_code == 409
    assert refused.json()["cap"] == "count" and refused.json()["reset"] > 0


def test_a_member_cannot_reach_another_members_request_and_tracker_needs_no_limit(server):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS, Permission.REQUEST)
    member(app, "hugo", Permission.FILMS, Permission.REQUEST)
    sign_in(browser, "lea")
    identifier = browser.post("/api/requests", json={"infohash": DUNE}).json()["id"]
    sign_in(browser, "hugo")
    assert browser.get("/api/requests").json()["requests"] == []
    assert browser.post(f"/api/requests/{identifier}/cancel").status_code == 404
    # Under an age limit tracker films are hidden, so they cannot be asked for either.
    app.state.accounts.set_media_limits(lea, "12", None)
    sign_in(browser, "lea")
    assert browser.post("/api/requests", json={"infohash": DUNE}).status_code == 404


def test_seen_clears_the_unread_answers(server):
    app, browser = server
    member(app, "lea", Permission.FILMS, Permission.REQUEST)
    sign_in(browser, "lea")
    identifier = browser.post("/api/requests", json={"infohash": DUNE}).json()["id"]
    app.state.requests.move(identifier, "refused", "owner", "Pas cette semaine")
    assert browser.get("/api/requests").json()["unread"] == 1
    assert browser.post("/api/requests/seen").json()["unread"] == 0


def test_deleting_a_member_cancels_pending_requests_and_keeps_them(server):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS, Permission.REQUEST)
    sign_in(browser, "lea")
    identifier = browser.post("/api/requests", json={"infohash": DUNE}).json()["id"]
    browser.cookies.clear()
    login(browser)
    assert browser.post(f"/api/members/{lea}/disable").status_code == 200
    assert browser.post(f"/api/members/{lea}/delete").status_code == 200
    assert app.state.requests.get(identifier)["state"] == "cancelled"
