"""Members 3 (#130): invitation and password links."""

import time

import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import PASSWORD, member, server, sign_in  # noqa: F401
from tests.test_web_jobs import login
from torrentlinker.accounts import OWNER, Accounts, Caps, Permission
from torrentlinker.web.app import create_app

BASE = "https://tl.example/"


def token_of(link):
    return link["url"].split("#", 1)[1]


def test_an_invitation_is_one_time_hashed_and_can_be_shown_again(tmp_path):
    accounts = Accounts(tmp_path)
    karim, token = accounts.invite(
        "Karim", {Permission.FILMS}, Caps(), days=3, inviter=OWNER, note="Salut"
    )
    stored = [r[0] for r in accounts.db.execute("SELECT digest FROM links")]
    assert token not in stored and len(stored) == 1
    assert accounts.open_link(karim)[0] == token  # "Voir le lien" gives the same link
    assert (tmp_path / "accounts.key").stat().st_mode & 0o777 == 0o600
    # The same key gives the same link after a restart; another key, none.
    assert Accounts(tmp_path).open_link(karim)[0] == token

    listed = accounts.members()[0]
    assert listed["invited"] and listed["login"] == "" and listed["link"]["kind"] == "invite"
    assert accounts.verify("", "") is None
    found = accounts.link(token)
    assert found["state"] == "valid" and found["note"] == "Salut" and found["inviter"] == ""
    assert found["permissions"] == ["films"]

    with pytest.raises(ValueError, match="sign-in name"):
        accounts.redeem(token, PASSWORD)
    with pytest.raises(ValueError, match="12 characters"):
        accounts.redeem(token, "short", login="karim")
    assert accounts.redeem(token, PASSWORD, name="Karim B.", login="karim") == karim
    assert accounts.verify("karim", PASSWORD) == karim
    assert accounts.link(token) == {"kind": "invite", "state": "used"}
    with pytest.raises(PermissionError):
        accounts.redeem(token, PASSWORD, login="karim2")
    joined = accounts.members()[0]
    assert joined["name"] == "Karim B." and not joined["invited"] and joined["link"] is None
    assert accounts.link("unknown") is None


def test_links_expire_and_a_new_one_replaces_the_old(tmp_path):
    accounts = Accounts(tmp_path)
    with pytest.raises(ValueError, match="24 hours"):
        accounts.invite("Karim", (), Caps(), days=2, inviter=OWNER)
    karim, first = accounts.invite("Karim", (), Caps(), days=1, inviter=OWNER)
    second = accounts.password_link(karim, days=7, inviter=OWNER)
    assert first != second and accounts.link(first) is None
    assert accounts.link(second)["kind"] == "invite"  # still not joined: a new invitation
    accounts.db.execute("UPDATE links SET expires=?", (time.time() - 1,))
    assert accounts.link(second)["state"] == "expired" and accounts.open_link(karim) is None
    assert accounts.members()[0]["link"]["expired"]
    with pytest.raises(PermissionError):
        accounts.redeem(second, PASSWORD, login="karim")
    # Cancelling an invitation removes the account that never joined.
    assert accounts.cancel_link(karim) is True and accounts.members() == []


def test_a_password_link_sets_a_new_password_and_ends_every_session(tmp_path):
    accounts = Accounts(tmp_path)
    lea = accounts.create("Léa", "lea", password=PASSWORD)
    session = accounts.open_session(lea)
    token = accounts.password_link(lea, days=3, inviter=OWNER)
    assert accounts.link(token)["kind"] == "password"
    assert accounts.link(token)["login"] == "lea"
    assert accounts.verify("lea", PASSWORD) == lea  # the old one works until the link is used
    accounts.redeem(token, "a-brand-new-password", login="ignored")
    assert accounts.session(session) is None
    assert accounts.verify("lea", "a-brand-new-password") == lea
    assert accounts.members()[0]["login"] == "lea"
    # Cancelling a password link keeps the Member.
    accounts.password_link(lea, days=3, inviter=OWNER)
    assert accounts.cancel_link(lea) is False and accounts.members()[0]["link"] is None
    with pytest.raises(PermissionError):
        accounts.password_link(OWNER, days=3, inviter=OWNER)


def test_the_owner_invites_and_the_person_joins_signed_in(server):  # noqa: F811
    app, browser = server
    login(browser)
    created = browser.post(
        "/api/members/invite",
        json={
            "name": "Karim",
            "note": "Voici les films",
            "permissions": ["films", "request"],
            "caps": {"requests_per_week": 5},
            "days": 3,
            "base": BASE,
        },
    ).json()
    link, karim = created["link"], created["member"]
    assert link["url"].startswith(BASE + "join#") and link["kind"] == "invite"
    assert len(link["qr"]) == len(link["qr"][0]) and set("".join(link["qr"])) == {"0", "1"}
    assert karim["invited"] and karim["caps"]["requests_per_week"] == 5
    shown = browser.post(f"/api/members/{karim['id']}/show-link", json={"base": BASE})
    assert shown.json()["link"]["url"] == link["url"]
    assert (
        browser.post("/api/members/invite", json={"name": "X", "base": "javascript:"}).status_code
        == 400
    )

    # Editing an invited Member keeps the sign-in name empty until they join.
    edited = browser.post(
        f"/api/members/{karim['id']}",
        json={"name": "Karim", "login": "", "permissions": ["films"]},
    )
    assert edited.status_code == 200 and edited.json()["invited"]

    stranger = TestClient(app)
    stranger.headers["X-TorrentLinker"] = "1"
    assert stranger.get("/join").status_code == 200
    seen = stranger.post("/api/links/inspect", json={"token": token_of(link)}).json()
    assert seen["state"] == "valid" and seen["note"] == "Voici les films"
    assert stranger.post("/api/links/inspect", json={"token": "nope"}).status_code == 404
    taken = member(app, "taken")
    assert taken
    clash = stranger.post(
        "/api/links/redeem",
        json={"token": token_of(link), "login": "taken", "password": PASSWORD},
    )
    assert clash.status_code == 400 and "already used" in clash.json()["detail"]
    joined = stranger.post(
        "/api/links/redeem",
        json={"token": token_of(link), "name": "Karim", "login": "karim", "password": PASSWORD},
    )
    assert joined.status_code == 200 and "HttpOnly" in joined.headers["set-cookie"]
    assert stranger.get("/api/shell").status_code == 200
    again = stranger.post(
        "/api/links/redeem", json={"token": token_of(link), "login": "k2", "password": PASSWORD}
    )
    assert again.status_code == 403
    assert stranger.post("/api/links/inspect", json={"token": token_of(link)}).json() == {
        "kind": "invite",
        "state": "used",
    }


def test_password_links_follow_the_managers_rules(server):  # noqa: F811
    app, browser = server
    member(app, "maman", Permission.MANAGE_MEMBERS, Permission.FILMS)
    papa = member(app, "papa", Permission.FILMS, Permission.APPROVE)
    lea = member(app, "lea", Permission.FILMS)
    sign_in(browser, "maman")
    assert browser.post(f"/api/members/{papa}/link", json={"base": BASE}).status_code == 403
    assert browser.post(f"/api/members/{OWNER}/link", json={"base": BASE}).status_code == 403
    issued = browser.post(f"/api/members/{lea}/link", json={"days": 1, "base": BASE}).json()
    assert issued["link"]["kind"] == "password" and issued["member"]["link"]["kind"] == "password"
    # A manager cannot invite with a Permission they lack.
    refused = browser.post(
        "/api/members/invite", json={"name": "Zoé", "permissions": ["approve"], "base": BASE}
    )
    assert refused.status_code == 403
    assert browser.post(f"/api/members/{lea}/cancel-link").json() == {"removed": False}
    assert browser.post(f"/api/members/{lea}/show-link", json={"base": BASE}).status_code == 404


def test_behind_a_proxy_links_are_not_used(tmp_path):
    from ipaddress import ip_network

    app = create_app(
        tmp_path, members_enabled=True, password=None, trusted_proxies=(ip_network("10.0.0.0/8"),)
    )
    with TestClient(app, client=("10.0.0.2", 1)) as proxy:
        proxy.headers["X-TorrentLinker"] = "1"
        refused = proxy.post("/api/members/invite", json={"name": "K", "base": BASE})
        assert refused.status_code == 400
        assert proxy.post("/api/links/inspect", json={"token": "x"}).status_code == 400
