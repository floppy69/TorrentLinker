"""Members 1 (#128): the accounts store, actors and route Permissions."""

import re
import sqlite3
import types

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.test_web_jobs import Client, login
from torrentlinker.accounts import OWNER, OWNER_ACTOR, Accounts, Actor, Caps, Permission
from torrentlinker.media import MediaLibrary
from torrentlinker.web.app import create_app
from torrentlinker.web.permissions import Audience, Need, needs

# `.schema` of a real media.sqlite written before Members, rows invented.
REAL_MEDIA_SCHEMA = """
CREATE TABLE media_items
                    (id TEXT, client TEXT, path TEXT, folder TEXT, size INTEGER,
                    modified INTEGER, added REAL, body TEXT, PRIMARY KEY(client,id));
CREATE TABLE media_progress
                    (client TEXT, item TEXT, position REAL, duration REAL, watched INTEGER,
                    PRIMARY KEY(client,item));
CREATE TABLE media_options (key TEXT PRIMARY KEY, body TEXT);
CREATE TABLE media_sessions
                    (id TEXT PRIMARY KEY, token TEXT, client TEXT, platform TEXT,
                    updated REAL, body TEXT, commands TEXT, actor TEXT DEFAULT '',
                    conversation TEXT DEFAULT '');
CREATE TABLE media_playlists
                    (id TEXT PRIMARY KEY, client TEXT, name TEXT, items TEXT);
CREATE TABLE media_selections
                    (id TEXT PRIMARY KEY, actor TEXT, client TEXT, items TEXT);
INSERT INTO media_progress VALUES ('default', 'film', 120, 6000, 0);
INSERT INTO media_progress VALUES ('default', 'song', 200, 200, 1);
INSERT INTO media_playlists VALUES ('p1', 'default', 'Soirée', '["song"]');
INSERT INTO media_sessions VALUES ('s1', 'digest', 'default', 'web', 1.0, '{}', '[]', 'g1', 'c1');
"""


def media_library(directory):
    agent = types.SimpleNamespace(setup=types.SimpleNamespace(path=directory / "settings.json"))
    return MediaLibrary(agent)


def test_accounts_keep_the_owner_fixed_and_members_to_their_permissions(tmp_path):
    accounts = Accounts(tmp_path)
    assert accounts.actor(OWNER) is OWNER_ACTOR and OWNER_ACTOR.owner
    member = accounts.create("Léa", "lea", {Permission.FILMS, Permission.REQUEST})
    actor = accounts.actor(member)
    assert actor is not None and not actor.owner
    assert actor.holds(Permission.FILMS) and not actor.holds(Permission.SEARCH)
    assert accounts.caps(member) == Caps()
    accounts.set_caps(member, Caps(requests_per_week=3, pending=2))
    accounts.grant(member, {Permission.MUSIC})
    accounts.close()

    reopened = Accounts(tmp_path)
    assert reopened.actor(member) == Actor(member, frozenset({Permission.MUSIC}))
    assert reopened.caps(member).requests_per_week == 3
    with pytest.raises(PermissionError):
        reopened.grant(OWNER, set())
    with pytest.raises(ValueError, match="already used"):
        reopened.create("Other", "LEA")
    reopened.db.execute("UPDATE accounts SET disabled=1 WHERE id=?", (member,))
    assert reopened.actor(member) is None
    assert reopened.actor("unknown") is None


def test_a_viewer_is_never_the_owner_nor_an_account_holder():
    viewer = Actor(OWNER, frozenset({Permission.FILMS}), viewer="kid")
    assert not viewer.owner and not viewer.holds(Permission.SEARCH)
    assert not Need(frozenset({Audience.ACCOUNT_HOLDER})).admits(viewer, {})
    assert Need(frozenset({Audience.SIGNED_IN})).admits(viewer, {})
    search = Need(frozenset({Permission.SEARCH}), (("action", frozenset({"state"})),))
    member = Actor("m", frozenset({Permission.SEARCH}))
    assert search.admits(member, {"action": "state"})
    assert not search.admits(member, {"action": "enqueue"})
    assert search.admits(OWNER_ACTOR, {"action": "enqueue"})


@pytest.fixture
def server(tmp_path):
    app = create_app(
        tmp_path,
        members_enabled=True,
        password="test-password-long",
        connector=lambda *args: Client(),
    )

    @app.get("/api/test/declared")
    @needs(Permission.SEARCH)
    def declared():
        return {"ok": True}

    @app.get("/api/test/undeclared")
    def undeclared():
        return {"ok": True}

    with TestClient(app) as browser:
        yield app, browser


def as_member(app, browser, *permissions):
    member = app.state.accounts.create(
        f"Léa {len(permissions)}", f"lea{len(permissions)}", set(permissions)
    )
    browser.cookies.clear()
    browser.cookies.set("tl_session", app.state.accounts.open_session(member))


def test_an_undeclared_route_refuses_a_member_and_a_declared_one_checks_the_permission(server):
    app, browser = server
    login(browser)
    assert browser.get("/api/test/undeclared").json() == {"ok": True}
    assert browser.get("/api/test/declared").json() == {"ok": True}
    as_member(app, browser)
    refused = browser.get("/api/test/undeclared")
    assert refused.status_code == 403 and "Permission" in refused.json()["detail"]
    assert browser.get("/api/test/declared").status_code == 403
    assert browser.get("/api/shell").status_code == 200

    as_member(app, browser, Permission.SEARCH)
    assert browser.get("/api/test/declared").json() == {"ok": True}
    assert browser.get("/api/test/undeclared").status_code == 403


def test_every_existing_route_without_a_declaration_is_the_owners(server):
    app, browser = server
    as_member(app, browser, *Permission)
    reached = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path.startswith("/api/test/"):
            continue
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        if not path.startswith(("/api/", "/documentation/")) or path.startswith("/api/companion/"):
            continue
        if getattr(route.endpoint, "need", None) is not None:
            reached.append(route.path)
            continue
        method = sorted(route.methods)[0]
        response = browser.request(method, path, headers={"X-TorrentLinker": "1"})
        assert response.status_code == 403, (method, route.path)
    assert set(reached) == {
        "/api/login",
        "/api/logout",
        "/api/shell",
        "/api/documentation",
        "/api/documentation/page/{name:path}",
        "/api/documentation/file/{name:path}",
        "/documentation/{name:path}",
        "/api/members",
        "/api/members/{account}",
        "/api/members/{account}/{action}",
        "/api/members/invite",
        "/api/members/{account}/link",
        "/api/members/{account}/show-link",
        "/api/members/{account}/cancel-link",
        "/api/links/inspect",
        "/api/links/redeem",
        "/api/media/items/{identifier}/rating",
        "/api/media/ratings",
        "/api/media/ratings/confirm",
        # Médias with visibility (#131).
        "/api/media",
        "/api/media/home",
        "/api/media/items/{identifier}",
        "/api/media/items/{identifier}/stream",
        "/api/media/items/{identifier}/playback",
        "/api/media/items/{identifier}/playback/stream",
        "/api/media/items/{identifier}/playback/{playback_id}",
        "/api/media/items/{identifier}/prerolls",
        "/api/media/items/{identifier}/prerolls/{clip_id}/stream",
        "/api/media/items/{identifier}/artwork",
        "/api/media/items/{identifier}/subtitles/{subtitle_id}",
        "/api/media/items/{identifier}/watched",
        "/api/media/items/{identifier}/forget-progress",
        "/api/media/items/{identifier}/preview",
        "/api/media/previews/{preview_id}",
        "/api/media/previews/{preview_id}/stream",
        "/api/media/playlists",
        "/api/media/playlists/{identifier}",
        "/api/media/sessions",
        "/api/media/sessions/{identifier}",
        # Requests and Wishes, the Member's side (#133).
        "/api/requests",
        "/api/requests/seen",
        "/api/requests/{identifier}/cancel",
        "/api/wishes",
        # Approvals, scoped workspaces, private Assistant and notifications.
        "/api/requests/review",
        "/api/requests/releases",
        "/api/requests/{identifier}/accept",
        "/api/requests/{identifier}/resolve",
        "/api/requests/{identifier}/retry",
        "/api/requests/{identifier}/refuse",
        "/api/requests/artwork/{infohash}",
        "/api/member-workspace/search",
        "/api/member-workspace/queue",
        "/api/member-workspace/torrents",
        "/api/member-assistant",
        "/api/member-assistant/{identifier}",
        "/api/notifications",
        "/api/notifications/seen",
        "/api/notifications/preferences",
        "/api/notifications/push-key",
        "/api/notifications/subscription",
        "/api/members/{account}/email-link",
        # Viewers, PINs and Shared Screens, and Mon compte (#135).
        "/api/screen",
        "/api/screen/choose",
        "/api/account",
        "/api/account/password",
        "/api/account/pin",
        "/api/account/viewers/new",
        "/api/account/viewers/{viewer}",
        "/api/account/viewers/{viewer}/delete",
        "/api/account/screens/{screen}/forget",
        "/api/members/{account}/profiles",
        "/api/members/{account}/viewers/new",
        "/api/members/{account}/viewers/{viewer}",
        "/api/members/{account}/viewers/{viewer}/delete",
        "/api/members/{account}/screens/{screen}/forget",
        "/api/members/{account}/viewers/{viewer}/promote",
    }


def test_a_disabled_member_has_no_actor(tmp_path):
    app = create_app(
        tmp_path,
        members_enabled=True,
        password="test-password-long",
        connector=lambda *args: Client(),
    )
    with TestClient(app) as browser:
        as_member(app, browser)
        assert browser.get("/api/shell").status_code == 200
        app.state.accounts.db.execute("UPDATE accounts SET disabled=1")
        app.state.accounts.db.commit()
        assert browser.get("/api/shell").status_code == 401


def test_the_migration_gives_existing_rows_to_the_owner_once(tmp_path):
    with sqlite3.connect(tmp_path / "media.sqlite") as old:
        old.executescript(REAL_MEDIA_SCHEMA)
    media = media_library(tmp_path)
    progress = media.db.execute(
        "SELECT client, item, position, watched, account, viewer FROM media_progress ORDER BY item"
    ).fetchall()
    assert [tuple(r) for r in progress] == [
        ("default", "film", 120, 0, OWNER, ""),
        ("default", "song", 200, 1, OWNER, ""),
    ]
    playlist = media.db.execute("SELECT * FROM media_playlists").fetchone()
    assert (playlist["name"], playlist["account"], playlist["viewer"]) == ("Soirée", OWNER, "")
    session = media.db.execute("SELECT * FROM media_sessions").fetchone()
    assert (session["actor"], session["account"], session["viewer"]) == ("g1", OWNER, "")
    # Two people may now each hold progress on the same item.
    media.save_progress("default", "film", 5, 6000, False, account="m1", viewer="")
    media.db.commit()
    media.db.close()

    again = media_library(tmp_path)
    assert again.db.execute("SELECT COUNT(*) FROM media_progress").fetchone()[0] == 3
    assert {r[0] for r in again.db.execute("SELECT account FROM media_progress")} == {OWNER, "m1"}
    again.db.close()


def test_a_failed_migration_leaves_the_old_tables(tmp_path):
    with sqlite3.connect(tmp_path / "media.sqlite") as old:
        old.executescript(REAL_MEDIA_SCHEMA)
        # A duplicate column fails the last step, after progress was rebuilt.
        old.execute("ALTER TABLE media_sessions ADD COLUMN viewer TEXT")
    with pytest.raises(sqlite3.OperationalError):
        media_library(tmp_path)
    with sqlite3.connect(tmp_path / "media.sqlite") as kept:
        columns = {r[1] for r in kept.execute("PRAGMA table_info(media_progress)")}
        assert "account" not in columns
        assert kept.execute("SELECT COUNT(*) FROM media_progress").fetchone()[0] == 2
