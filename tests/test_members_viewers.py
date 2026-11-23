"""Members 8 (#135): Viewers, PINs and Shared Screens, and "Mon compte"."""

import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import PASSWORD, member
from tests.test_web_jobs import login
from torrentlinker.accounts import PICKING, SCREEN_IDLE, Accounts, Permission
from torrentlinker.web.app import create_app

FAMILY = {Permission.FILMS, Permission.SERIES, Permission.ANIME, Permission.REQUEST}


@pytest.fixture
def accounts(tmp_path):
    return Accounts(tmp_path)


def test_a_viewer_is_never_broader_than_its_account(accounts):
    lea = accounts.create("Léa", "lea", FAMILY)
    accounts.set_media_limits(lea, "16", None)
    with pytest.raises(ValueError, match="Media Permissions"):
        accounts.add_viewer(lea, "Hugo", {Permission.MUSIC}, 1)
    with pytest.raises(ValueError, match="Media Permissions"):
        accounts.add_viewer(lea, "Hugo", {Permission.REQUEST}, 1)
    with pytest.raises(ValueError, match="higher Age Rating"):
        accounts.add_viewer(lea, "Mamie", {Permission.FILMS}, None)
    # A narrower profile needs the holder's PIN first.
    with pytest.raises(ValueError, match="PIN for Léa"):
        accounts.add_viewer(lea, "Hugo", {Permission.FILMS}, 1)
    accounts.set_pin(lea, "", "1234")
    hugo = accounts.add_viewer(lea, "Hugo", {Permission.FILMS, Permission.ANIME}, 1)
    actor = accounts.viewer_actor(lea, hugo)
    assert actor is not None and actor.viewer == hugo and not actor.owner
    assert actor.permissions == {Permission.FILMS, Permission.ANIME} and actor.age_limit == 1
    # The account narrows its Viewers at once.
    accounts.grant(lea, {Permission.FILMS})
    assert accounts.viewer_actor(lea, hugo).permissions == {Permission.FILMS}  # type: ignore[union-attr]
    # The holder's PIN cannot go while a narrower profile exists.
    with pytest.raises(ValueError, match="PIN for Léa"):
        accounts.set_pin(lea, "", "")


def test_pins_have_4_to_8_digits_are_hashed_and_only_stepping_up_asks(accounts):
    lea = accounts.create("Léa", "lea", FAMILY)
    with pytest.raises(ValueError, match="4 to 8 digits"):
        accounts.set_pin(lea, "", "12a4")
    with pytest.raises(ValueError, match="4 to 8 digits"):
        accounts.set_pin(lea, "", "123456789")
    accounts.set_pin(lea, "", "12345678")
    stored = accounts.db.execute("SELECT pin FROM holder_pins").fetchone()[0]
    assert stored.startswith("scrypt$") and "12345678" not in stored
    assert accounts.check_pin(lea, "", "12345678") and not accounts.check_pin(lea, "", "0000")
    hugo = accounts.add_viewer(lea, "Hugo", {Permission.FILMS, Permission.ANIME}, 1)
    # Neither narrower than the other: no PIN needed between them.
    mamie = accounts.add_viewer(lea, "Mamie", {Permission.FILMS, Permission.SERIES}, None)
    with pytest.raises(ValueError, match="PIN for Hugo"):
        accounts.add_viewer(lea, "Bébé", {Permission.FILMS}, 0)
    profiles = {p["name"]: p for p in accounts.profiles(lea)}
    assert profiles["Léa"]["needs_pin"] and not profiles["Hugo"]["needs_pin"]
    # From the picker, a profile with a PIN asks for it; going down never does.
    assert accounts.needs_pin(lea, "", None)
    assert not accounts.needs_pin(lea, hugo, None)
    assert not accounts.needs_pin(lea, hugo, "")
    assert accounts.needs_pin(lea, "", hugo)
    assert not accounts.needs_pin(lea, mamie, hugo)  # broader, but she has no PIN


def test_shared_screens_last_90_days_and_end_with_the_password(accounts, monkeypatch):
    lea = accounts.create("Léa", "lea", FAMILY, password=PASSWORD)
    token = accounts.open_screen(lea, "Télé du salon")
    found = accounts.screen(token)
    assert found is not None
    actor, _ = found
    assert actor.viewer == PICKING and not actor.permissions and actor.screen
    accounts.choose(actor.screen, "")
    assert accounts.screen(token)[0].permissions == accounts.actor(lea).permissions  # type: ignore[index,union-attr]
    [listed] = accounts.screens(lea)
    assert listed["name"] == "Télé du salon"
    stored = accounts.db.execute("SELECT digest FROM screens").fetchone()[0]
    assert token not in stored
    import time

    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + SCREEN_IDLE + 10)
    assert accounts.screen(token) is None
    monkeypatch.setattr(time, "time", lambda: now)
    token = accounts.open_screen(lea, "Tablette")
    accounts.set_password(lea, "another-password-long")
    assert accounts.screen(token) is None


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path, members_enabled=True, password="test-password-long", monitor_verifications=False
    )
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser


def screen_sign_in(browser, name="lea", screen="Télé du salon"):
    browser.cookies.clear()
    return browser.post("/api/login", json={"login": name, "password": PASSWORD, "screen": screen})


def test_who_watches_on_a_shared_screen_with_the_pin_rule(server):
    app, browser = server
    lea = member(app, "lea", *FAMILY)
    app.state.accounts.set_pin(lea, "", "2468")
    hugo = app.state.accounts.add_viewer(lea, "Hugo", {Permission.FILMS}, 1)
    assert screen_sign_in(browser).status_code == 200
    shell = browser.get("/api/shell").json()
    assert shell["actor"]["screen"] == {"name": "Télé du salon", "picking": True}
    assert shell["pages"] == []
    # Nothing but the picker until someone is chosen.
    assert browser.get("/api/media").status_code == 403
    assert browser.get("/api/account").status_code == 403
    picker = browser.get("/api/screen").json()
    assert [(p["name"], p["locked"]) for p in picker["profiles"]] == [
        ("Lea", True),
        ("Hugo", False),
    ]
    assert browser.post("/api/screen/choose", json={"viewer": hugo}).status_code == 200
    shell = browser.get("/api/shell").json()
    assert shell["actor"]["name"] == "Hugo" and shell["pages"] == ["media", "documentation"]
    assert shell["sections"] == []
    # A Viewer: Media only, never Requests nor "Mon compte".
    assert browser.get("/api/media").status_code == 200
    assert browser.get("/api/requests").status_code == 403
    assert browser.get("/api/account").status_code == 403
    # Stepping up takes the PIN, throttled.
    assert browser.post("/api/screen/choose", json={"viewer": ""}).status_code == 403
    for _ in range(4):
        browser.post("/api/screen/choose", json={"viewer": "", "pin": "0000"})
    assert browser.post("/api/screen/choose", json={"viewer": "", "pin": "2468"}).status_code == 429


def test_the_holder_manages_viewers_pins_and_screens_in_mon_compte(server):
    app, browser = server
    lea = member(app, "lea", *FAMILY)
    screen_sign_in(browser, screen="Télé")
    browser.post("/api/screen/choose", json={"viewer": ""})
    account = browser.get("/api/account").json()
    assert account["name"] == "Lea" and [s["name"] for s in account["screens"]] == ["Télé"]
    shell = browser.get("/api/shell").json()
    assert "setup" in shell["pages"] and shell["sections"] == ["account", "notifications"]
    refused = browser.post(
        "/api/account/viewers/new",
        json={"name": "Hugo", "permissions": ["films"], "age_limit": "10"},
    )
    assert refused.status_code == 400 and "PIN" in refused.json()["detail"]
    wrong = browser.post("/api/account/pin", json={"pin": "1234", "password": "wrong-password-x"})
    assert wrong.status_code == 403
    assert (
        browser.post("/api/account/pin", json={"pin": "1234", "password": PASSWORD}).status_code
        == 200
    )
    added = browser.post(
        "/api/account/viewers/new",
        json={"name": "Hugo", "permissions": ["films"], "age_limit": "10"},
    )
    assert added.status_code == 200, added.text
    hugo = added.json()["profiles"][1]
    assert hugo["age_limit"] == "10" and hugo["permissions"] == ["films"]
    # Forgetting the screen signs this browser out at once.
    [screen] = account["screens"]
    browser.post(f"/api/account/screens/{screen['id']}/forget")
    assert browser.get("/api/shell").status_code == 401
    # Changing one's password keeps this browser signed in.
    browser.cookies.clear()
    browser.post("/api/login", json={"login": "lea", "password": PASSWORD})
    changed = browser.post(
        "/api/account/password", json={"current": PASSWORD, "password": "a-new-password-long"}
    )
    assert changed.status_code == 200
    assert browser.get("/api/account").status_code == 200
    assert app.state.accounts.check_password(lea, "a-new-password-long")


def test_the_owner_has_mon_compte_and_promotes_a_viewer_keeping_history(server):
    app, browser = server
    login(browser)
    assert browser.get("/api/account").json()["owner"] is True
    browser.post("/api/account/pin", json={"pin": "1357", "password": "test-password-long"})
    added = browser.post(
        "/api/account/viewers/new",
        json={"name": "Hugo", "permissions": ["films"], "age_limit": "10"},
    ).json()
    hugo = added["profiles"][1]["id"]
    library = app.state.agent_service.media
    library.db.execute(
        "INSERT INTO media_progress VALUES ('default','x',10,100,0,'owner',?)", (hugo,)
    )
    library.db.commit()
    promoted = browser.post(
        f"/api/members/owner/viewers/{hugo}/promote", json={"days": 3, "base": "http://tv.local/"}
    )
    assert promoted.status_code == 200, promoted.text
    member_id = promoted.json()["member"]["id"]
    assert promoted.json()["member"]["permissions"] == ["films"]
    assert promoted.json()["member"]["age_limit"] == "10"
    assert promoted.json()["link"]["url"].startswith("http://tv.local/join#")
    moved = library.db.execute("SELECT account, viewer FROM media_progress").fetchall()
    assert [tuple(r) for r in moved] == [(member_id, "")]
    assert len(browser.get("/api/account").json()["profiles"]) == 1


def test_a_manager_reaches_members_but_not_the_owners_profiles(server):
    app, browser = server
    member(app, "maman", Permission.MANAGE_MEMBERS, *FAMILY)
    lea = member(app, "lea", *FAMILY)
    browser.cookies.clear()
    browser.post("/api/login", json={"login": "maman", "password": PASSWORD})
    shell = browser.get("/api/shell").json()
    assert shell["sections"] == ["account", "notifications", "users"]
    assert browser.get(f"/api/members/{lea}/profiles").status_code == 200
    assert browser.get("/api/members/owner/profiles").status_code == 403
    assert (
        browser.post(
            "/api/members/owner/viewers/x/promote", json={"days": 3, "base": "http://a/"}
        ).status_code
        == 403
    )


def test_a_manager_cannot_widen_a_viewer_past_their_own_limits(server):
    app, browser = server
    accounts = app.state.accounts
    manager = member(app, "manager", Permission.MANAGE_MEMBERS, *FAMILY)
    lea = member(app, "lea", *FAMILY)
    accounts.set_media_limits(manager, "12", ["/films"])
    accounts.set_media_limits(lea, None, ["/films"])
    accounts.set_pin(lea, "", "1234")
    browser.post("/api/login", json={"login": "manager", "password": PASSWORD})
    prefix = f"/api/members/{lea}/viewers"
    body = {"name": "Child", "permissions": ["films"], "age_limit": "16"}
    assert browser.post(prefix + "/new", json=body).status_code == 403
    body["age_limit"] = "12"
    assert browser.post(prefix + "/new", json=body).status_code == 200
    viewer = next(p for p in accounts.profiles(lea) if not p["holder"])["id"]
    body["age_limit"] = None
    assert browser.post(prefix + f"/{viewer}", json=body).status_code == 403
    body["age_limit"] = "12"
    body["permissions"] = ["films", "music"]
    assert browser.post(prefix + f"/{viewer}", json=body).status_code == 403
    # A different folder scope must also prevent widening an existing Viewer.
    accounts.set_media_limits(lea, None, ["/private"])
    body["permissions"] = ["films", "series"]
    assert browser.post(prefix + f"/{viewer}", json=body).status_code == 403
    body["permissions"] = ["films"]
    body["age_limit"] = "10"
    assert browser.post(prefix + f"/{viewer}", json=body).status_code == 200
    assert browser.post(prefix + "/new", json=body).status_code == 403
