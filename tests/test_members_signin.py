"""Members 2 (#129): Member sign-in, sessions, the proxy's user header and Utilisateurs."""

import time

import pytest
from fastapi.testclient import TestClient

from tests.test_members_accounts import media_library
from tests.test_web_jobs import Client, login
from torrentlinker.accounts import OWNER, SESSION_IDLE, Accounts, Permission
from torrentlinker.web.app import create_app
from torrentlinker.web.security import Throttle

PASSWORD = "lea-password-long"
PROXY = ("10.0.0.0/8",)


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path,
        members_enabled=True,
        password="test-password-long",
        connector=lambda *args: Client(),
    )
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser


def member(app, login="lea", *permissions, password=PASSWORD):
    return app.state.accounts.create(login.title(), login, set(permissions), password=password)


def sign_in(browser, name, password=PASSWORD):
    browser.cookies.clear()
    return browser.post("/api/login", json={"login": name, "password": password})


def test_passwords_are_scrypt_hashes_and_sessions_are_stored_hashed(tmp_path):
    accounts = Accounts(tmp_path)
    lea = accounts.create("Léa", "lea", password=PASSWORD)
    stored = accounts.db.execute("SELECT password FROM accounts WHERE id=?", (lea,)).fetchone()[0]
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert accounts.verify("LEA", PASSWORD) == lea
    assert accounts.verify("lea", "wrong-password-long") is None
    assert accounts.verify("nobody", PASSWORD) is None
    with pytest.raises(ValueError, match="12 characters"):
        accounts.set_password(lea, "short")

    token = accounts.open_session(lea)
    assert accounts.session(token) == (lea, False)
    digests = [r[0] for r in accounts.db.execute("SELECT digest FROM sessions")]
    assert token not in digests and len(digests) == 1

    # 30 days of disuse end it; using it within them starts the 30 days again.
    accounts.db.execute("UPDATE sessions SET used=?", (time.time() - 7200,))
    assert accounts.session(token) == (lea, True)
    accounts.db.execute("UPDATE sessions SET used=?", (time.time() - SESSION_IDLE - 1,))
    assert accounts.session(token) is None

    # A password change, disabling or deleting ends every session.
    first, second = accounts.open_session(lea), accounts.open_session(lea)
    accounts.set_password(lea, "another-password")
    assert accounts.session(first) is None and accounts.session(second) is None
    assert accounts.verify("lea", "another-password") == lea
    token = accounts.open_session(lea)
    accounts.disable(lea)
    assert accounts.session(token) is None and accounts.verify("lea", "another-password") is None
    accounts.disable(lea, False)
    assert accounts.verify("lea", "another-password") == lea
    with pytest.raises(ValueError, match="Disable"):
        accounts.delete(lea)
    accounts.disable(lea)
    accounts.delete(lea)
    assert accounts.members() == [] and accounts.actor(lea) is None
    with pytest.raises(PermissionError):
        accounts.disable(OWNER)


def test_a_member_signs_in_with_name_and_password_and_the_owner_with_the_startup_one(server):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS)
    wrong = sign_in(browser, "lea", "wrong-password-long")
    unknown = sign_in(browser, "nobody")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Incorrect sign-in name or password."}

    signed = sign_in(browser, "Lea")
    assert signed.status_code == 200
    cookie = signed.headers["set-cookie"]
    assert (
        "HttpOnly" in cookie and "SameSite=strict" in cookie and f"Max-Age={SESSION_IDLE}" in cookie
    )
    assert browser.get("/api/shell").status_code == 200
    assert browser.get("/api/settings").status_code == 403
    assert app.state.accounts.session(browser.cookies["tl_session"])[0] == lea

    assert browser.post("/api/logout", json={}).status_code == 200
    assert browser.get("/api/shell").status_code == 401

    browser.cookies.clear()
    login(browser)  # an empty sign-in name is the Owner's startup password
    assert browser.get("/api/members").status_code == 200


def test_sign_in_locks_after_five_failures_per_account_and_per_address(server):
    app, browser = server
    member(app, "lea")
    for _ in range(4):
        assert sign_in(browser, "lea", "wrong-password-long").status_code == 401
    assert sign_in(browser, "lea").status_code == 200  # a success starts over
    for _ in range(5):
        assert sign_in(browser, "lea", "wrong-password-long").status_code == 401
    locked = sign_in(browser, "lea")
    assert locked.status_code == 429 and "1 min" in locked.json()["detail"]
    # The address is locked too, so another name or the Owner cannot be tried from it.
    assert browser.post("/api/login", json={"password": "test-password-long"}).status_code == 429


def test_the_lock_doubles_on_repeat_up_to_fifteen_minutes(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    throttle = Throttle()
    waits = []
    for _ in range(6):
        for attempt in range(5):
            locked = throttle.failed("account:lea")
            assert locked == (attempt == 4)
        waits.append(throttle.wait("account:lea", "address:x"))
        now[0] += waits[-1]
    assert waits == [60, 120, 240, 480, 900, 900]
    throttle.succeeded("account:lea")
    for _ in range(5):
        throttle.failed("account:lea")
    assert throttle.wait("account:lea") == 60


def test_disabling_or_deleting_a_member_ends_their_session_at_once(server):
    app, browser = server
    lea = member(app, "lea", Permission.FILMS)
    sign_in(browser, "lea")
    owner = TestClient(app)
    owner.headers["X-TorrentLinker"] = "1"
    login(owner)

    disabled = owner.post(f"/api/members/{lea}/disable")
    assert disabled.json()["disabled"] is True
    assert browser.get("/api/shell").status_code == 401
    assert sign_in(browser, "lea").status_code == 401
    assert owner.post(f"/api/members/{lea}/enable").json()["disabled"] is False
    assert sign_in(browser, "lea").status_code == 200

    assert owner.post(f"/api/members/{lea}/delete").status_code == 400
    owner.post(f"/api/members/{lea}/disable")
    assert owner.post(f"/api/members/{lea}/delete").json() == {"ok": True}
    assert owner.get("/api/members").json()["members"] == []
    assert owner.post(f"/api/members/{OWNER}/disable").status_code == 403


def test_the_owner_creates_and_edits_a_member_with_caps(server):
    app, browser = server
    login(browser)
    body = {
        "name": "Léa",
        "login": "lea",
        "password": PASSWORD,
        "permissions": ["films", "request"],
        "caps": {"requests_per_week": 5, "bytes_per_week": 100 * 10**9, "pending": 3},
    }
    created = browser.post("/api/members", json=body).json()
    assert created["permissions"] == ["films", "request"] and created["has_password"]
    assert created["caps"]["requests_per_week"] == 5 and created["caps"]["assistant_per_day"] == 20
    assert "password" not in created
    assert browser.post("/api/members", json=body).status_code == 400  # name already used
    assert browser.post("/api/members", json={**body, "login": "x", "password": ""}).json() == {
        "detail": "Choose a password for this Member."
    }

    # Without the Request Permission, the caps go.
    edited = browser.post(
        f"/api/members/{created['id']}", json={**body, "password": "", "permissions": ["films"]}
    ).json()
    assert edited["permissions"] == ["films"] and edited["caps"]["requests_per_week"] is None
    assert browser.post(f"/api/members/{OWNER}", json=body).status_code == 403


def test_a_manager_never_reaches_the_owner_nor_grants_what_they_lack(server):
    app, browser = server
    manager = member(app, "maman", Permission.MANAGE_MEMBERS, Permission.FILMS)
    stronger = member(app, "papa", Permission.FILMS, Permission.APPROVE)
    lea = member(app, "lea", Permission.FILMS)
    sign_in(browser, "maman")
    listing = browser.get("/api/members").json()
    assert listing["grantable"] == ["films", "manage-members"] and "owner_proxy_user" not in listing
    assert (
        browser.post("/api/members/owner/proxy-user", json={"proxy_user": "x"}).status_code == 403
    )

    def edit(account, login, permissions, **extra):
        return browser.post(
            f"/api/members/{account}",
            json={"name": login.title(), "login": login, "permissions": permissions, **extra},
        )

    assert edit(lea, "lea", ["films", "search"]).status_code == 403
    assert edit(lea, "lea", []).status_code == 200
    assert edit(stronger, "papa", ["films"]).status_code == 403  # cannot remove Approve either
    assert (
        edit(stronger, "papa", ["films", "approve"], password="taken-over-pass").status_code == 403
    )
    assert edit(manager, "maman", ["films"]).status_code == 403  # not their own Permissions
    assert browser.post(f"/api/members/{manager}/disable").status_code == 403
    assert browser.post(f"/api/members/{OWNER}/disable").status_code == 403
    created = browser.post(
        "/api/members",
        json={"name": "Hugo", "login": "hugo", "password": PASSWORD, "permissions": ["approve"]},
    )
    assert created.status_code == 403
    assert browser.post(f"/api/members/{lea}/disable").json()["disabled"] is True

    sign_in(browser, "papa")
    assert browser.get("/api/members").status_code == 403


def test_the_proxy_user_header_names_a_member_only_from_a_trusted_proxy(tmp_path):
    from ipaddress import ip_network

    networks = tuple(ip_network(n) for n in PROXY)
    app = create_app(tmp_path, members_enabled=True, password=None, trusted_proxies=networks)
    proxy = TestClient(app, client=("10.0.0.2", 1))
    outsider = TestClient(app, client=("192.168.1.5", 1))
    with proxy:
        accounts = app.state.accounts
        lea = accounts.create("Léa", "lea", {Permission.FILMS})
        # Until an account has a proxy name, the header is ignored: the Owner, as before.
        assert proxy.get("/api/settings", headers={"Remote-User": "vincent"}).status_code != 403
        accounts.set_proxy_user(lea, "lea@famille")

        as_lea = {"Remote-User": "LEA@famille"}
        assert proxy.get("/api/shell", headers=as_lea).status_code == 200
        assert proxy.get("/api/settings", headers=as_lea).status_code == 403
        unknown = proxy.get("/api/shell", headers={"Remote-User": "vincent"})
        assert unknown.status_code == 403 and "not a Member" in unknown.json()["detail"]
        assert proxy.get("/api/settings").status_code != 403  # no header: the Owner

        accounts.set_proxy_user(OWNER, "vincent")
        assert proxy.get("/api/settings", headers={"Remote-User": "vincent"}).status_code != 403
        assert outsider.get("/api/shell", headers=as_lea).status_code == 403
        accounts.disable(lea)
        assert proxy.get("/api/shell", headers=as_lea).status_code == 403

        created = proxy.post(
            "/api/members",
            headers={"X-TorrentLinker": "1"},
            json={"name": "Hugo", "login": "hugo", "permissions": ["films"]},
        )
        assert created.json() == {
            "detail": "Give the name your reverse proxy sends for this Member."
        }


def test_deleting_a_member_erases_their_progress_and_playlists(tmp_path):
    media = media_library(tmp_path)
    with media.db:
        media.save_progress("default", "film", 5, 60, False, account="lea", viewer="")
        media.save_progress("default", "film", 9, 60, False, account="lea", viewer="hugo")
        media.save_progress("default", "film", 7, 60, False, account=OWNER, viewer="")
        media.db.execute(
            "INSERT INTO media_playlists (id, client, name, items, account) "
            "VALUES ('p', 'default', 'Soirée', '[]', 'lea')"
        )
    media.forget_account("lea")
    assert [r[0] for r in media.db.execute("SELECT account FROM media_progress")] == [OWNER]
    assert media.db.execute("SELECT COUNT(*) FROM media_playlists").fetchone()[0] == 0
    media.db.close()


def test_the_owner_stays_signed_in_across_a_restart_until_the_password_changes(tmp_path):
    from torrentlinker.web.security import Sessions

    path = tmp_path / "owner-sessions.json"
    token = Sessions("first-password-long", path).login("first-password-long")
    # Only digests are written down; the cookie's token never reaches the disk.
    assert token not in path.read_text()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    restarted = Sessions("first-password-long", path)
    assert restarted.account(token) == OWNER
    restarted.logout(token)
    assert Sessions("first-password-long", path).account(token) is None
    kept = Sessions("first-password-long", path).login("first-password-long")
    assert Sessions("new-password-long", path).account(kept) is None
    assert Sessions("first-password-long", path).account(kept) is None
