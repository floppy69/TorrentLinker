"""Members 4 (#131): Médias as a Member, visibility and per-person progress."""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import member, sign_in
from tests.test_web_jobs import login
from torrentlinker.accounts import Accounts, Permission
from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.web.app import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def film(folder: Path, name: str) -> None:
    (folder / f"{name}.mkv").write_bytes(b"\0" * 64)
    (folder / f"{name}.png").write_bytes(PNG)


@pytest.fixture
def server(tmp_path):
    films, cartoons, adult = tmp_path / "films", tmp_path / "cartoons", tmp_path / "xxx"
    for folder in (films, cartoons, adult):
        folder.mkdir()
    film(films, "The Revenant 2015 1080p")
    film(films, "Saw X 2023 1080p")
    film(films, "Unrated Film 2020 1080p")
    film(cartoons, "Vice Versa 2015 1080p")
    film(adult, "Private Scene 2019 1080p")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(adult_content=True)
    settings.library_folders = [
        LibraryFolder(films, None, ContentKind.MOVIE),
        LibraryFolder(cartoons, None, ContentKind.MOVIE),
        LibraryFolder(adult, None, ContentKind.ADULT),
    ]
    settings.save(config / "settings.json")
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        roots=(films, cartoons, adult),
        monitor_verifications=False,
    )
    library = app.state.agent_service.media
    library.scan("default", threading.Event(), lambda _p: None)
    ids = {
        r["title"]: r["id"]
        for r in library.listing("default", kind="video")["rows"]
        + library.listing("default", kind="video", adult=True)["rows"]
    }
    for title, rating in (("The Revenant", "16"), ("Saw X", "18"), ("Vice Versa", "TP")):
        library.rate("default", ids[title], rating, setter="owner", name="")
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser, ids, {"films": str(films), "cartoons": str(cartoons)}


def titles(browser, **params):
    page = browser.get("/api/media", params={"kind": "video", **params})
    assert page.status_code == 200, page.text
    return sorted(r["title"] for r in page.json()["rows"])


def test_media_limits_are_stored_and_adult_content_needs_no_limit_or_18(tmp_path):
    accounts = Accounts(tmp_path)
    lea = accounts.create("Léa", "lea", {Permission.FILMS, Permission.ADULT})
    accounts.set_media_limits(lea, "18", ["/b", "/a"])
    actor = accounts.actor(lea)
    assert actor is not None and actor.age_limit == 4 and actor.folders == {"/a", "/b"}
    assert actor.holds(Permission.ADULT)
    accounts.set_media_limits(lea, "12", None)
    actor = accounts.actor(lea)
    assert actor is not None and actor.age_limit == 2 and actor.folders is None
    assert not actor.holds(Permission.ADULT)
    accounts.grant(lea, {Permission.FILMS, Permission.ADULT})  # still refused under −12
    assert not accounts.actor(lea).holds(Permission.ADULT)  # type: ignore[union-attr]
    [found] = accounts.members()
    assert found["age_limit"] == "12" and found["folders"] is None
    with pytest.raises(ValueError):
        accounts.set_media_limits(lea, "14", None)


def test_a_member_sees_only_what_is_visible_to_them(server):
    app, browser, ids, folders = server
    lea = member(app, "lea", Permission.FILMS)
    login(browser)
    assert titles(browser) == ["Saw X", "The Revenant", "Unrated Film", "Vice Versa"]

    sign_in(browser, "lea")
    # No limit: every film; XXX needs its Permission.
    assert titles(browser) == ["Saw X", "The Revenant", "Unrated Film", "Vice Versa"]
    assert titles(browser, adult="true") == []
    # Under −16, what is rated above it and what is unrated are hidden, in search too.
    app.state.accounts.set_media_limits(lea, "16", None)
    assert titles(browser) == ["The Revenant", "Vice Versa"]
    assert titles(browser, q="saw") == []
    # Library Folders.
    app.state.accounts.set_media_limits(lea, None, [folders["cartoons"]])
    assert titles(browser) == ["Vice Versa"]
    home = browser.get("/api/media/home").json()["rows"]
    assert {r["title"] for row in home for r in row["rows"]} == {"Vice Versa"}
    # A Content Kind the Member lacks.
    app.state.accounts.grant(lea, {Permission.SERIES})
    assert titles(browser) == []
    app.state.accounts.grant(lea, {Permission.FILMS, Permission.ADULT})
    app.state.accounts.set_media_limits(lea, None, None)
    assert titles(browser, adult="true") == ["Private Scene"]


def test_a_hidden_item_is_missing_to_a_member_even_with_a_guessed_id(server):
    app, browser, ids, _ = server
    lea = member(app, "lea", Permission.FILMS)
    app.state.accounts.set_media_limits(lea, "12", None)
    sign_in(browser, "lea")
    hidden, shown = ids["Saw X"], ids["Vice Versa"]
    item = f"/api/media/items/{hidden}"
    for response in (
        browser.get(f"{item}/stream", headers={"Range": "bytes=0-3"}),
        browser.get(f"{item}/artwork"),
        browser.get(item),
        browser.get(f"{item}/subtitles/any"),
        browser.get(f"{item}/playback"),
        browser.get(f"{item}/playback/stream?playback_id=test-player"),
        browser.post(f"{item}/watched", json={"watched": True}),
        browser.post(f"{item}/forget-progress", json={}),
        browser.post(f"{item}/preview", json={}),
        browser.get("/api/media/items/no-such-item/stream"),
    ):
        assert response.status_code == 404, response.text
        assert "Saw" not in response.text
    # What is visible plays, and the Member's client_id is ignored.
    stream = browser.get(
        f"/api/media/items/{shown}/stream?client_id=elsewhere", headers={"Range": "bytes=0-3"}
    )
    assert stream.status_code == 206
    assert browser.get(f"/api/media/items/{shown}/artwork?client_id=x").content == PNG
    assert browser.get(f"/api/media/items/{shown}").json()["title"] == "Vice Versa"
    # A playlist or a player queue cannot carry a hidden item either.
    playlist = {"name": "Mine", "media_ids": [hidden]}
    assert browser.post("/api/media/playlists", json=playlist).status_code == 404
    session = browser.post("/api/media/sessions", json={}).json()
    queued = {"token": session["token"], "action": "play", "media_ids": [hidden]}
    assert browser.post(f"/api/media/sessions/{session['id']}", json=queued).status_code == 404
    # The Owner's tools stay the Owner's.
    assert browser.post("/api/media/scan", json={}).status_code == 403
    assert browser.post(f"/api/media/tracker/{'a' * 40}/download", json={}).status_code == 403
    assert browser.get(f"/api/media/items/tracker-{'a' * 40}/artwork").status_code == 404


def test_progress_and_playlists_belong_to_whoever_watches(server):
    app, browser, ids, _ = server
    member(app, "lea", Permission.FILMS)
    film_id = ids["Vice Versa"]
    sign_in(browser, "lea")
    assert browser.post(f"/api/media/items/{film_id}/watched", json={"watched": True}).json()[
        "watched"
    ]
    session = browser.post("/api/media/sessions", json={}).json()
    report = {"current_id": film_id, "queue": [film_id], "position": 30, "duration": 100}
    browser.post(
        f"/api/media/sessions/{session['id']}", json={"token": session["token"], "report": report}
    )
    rows = browser.get("/api/media", params={"kind": "video", "q": "vice"}).json()["rows"]
    assert rows[0]["watched"]

    login(browser)
    rows = browser.get("/api/media", params={"kind": "video", "q": "vice"}).json()["rows"]
    assert not rows[0]["watched"] and rows[0]["position"] == 0
    assert browser.get("/api/media/playlists").json() == []
    owner_session = browser.post("/api/media/sessions", json={}).json()
    sign_in(browser, "lea")
    # Another person's player is not theirs to drive.
    foreign = {"token": owner_session["token"], "action": "play", "media_ids": [film_id]}
    assert browser.post(f"/api/media/sessions/{owner_session['id']}", json=foreign).is_client_error


def test_the_shell_is_trimmed_to_the_member(server):
    app, browser, _, _ = server
    member(app, "lea", Permission.FILMS)
    member(app, "tom", Permission.SEARCH)
    sign_in(browser, "lea")
    shell = browser.get("/api/shell").json()
    # Settings hold "Mon compte" for every account holder (#135).
    assert shell["pages"] == ["media", "documentation", "notifications", "setup"]
    assert not shell["actor"]["owner"] and shell["release"] is None
    assert shell["setup"]["adult_content"] is False and shell["setup"]["clients"] == []
    assert browser.get("/api/setup").status_code == 403
    sign_in(browser, "tom")
    assert browser.get("/api/shell").json()["pages"] == [
        "documentation",
        "notifications",
        "member-search",
        "setup",
    ]
    assert browser.get("/api/media").status_code == 403
    login(browser)
    assert browser.get("/api/shell").json()["actor"]["owner"]


def test_utilisateurs_sets_the_age_limit_and_folders_within_the_managers_own(server):
    app, browser, _, folders = server
    login(browser)
    listing = browser.get("/api/members").json()
    assert {f["path"] for f in listing["library_folders"]} >= set(folders.values())
    body = {
        "name": "Hugo",
        "login": "hugo",
        "password": "hugo-password-long",
        "permissions": ["films", "adult"],
        "age_limit": "10",
        "folders": [folders["cartoons"]],
    }
    hugo = browser.post("/api/members", json=body).json()
    assert hugo["age_limit"] == "10" and hugo["folders"] == [folders["cartoons"]]
    assert "adult" not in hugo["permissions"]

    # A manager limited to −12 cannot lift Hugo's limit past their own, nor show more folders.
    manager = member(app, "max", Permission.FILMS, Permission.MANAGE_MEMBERS)
    app.state.accounts.set_media_limits(manager, "12", [folders["cartoons"]])
    sign_in(browser, "max")
    lifted = {**body, "permissions": ["films"], "age_limit": None}
    assert browser.post(f"/api/members/{hugo['id']}", json=lifted).status_code == 403
    wider = {**body, "permissions": ["films"], "folders": None}
    assert browser.post(f"/api/members/{hugo['id']}", json=wider).status_code == 403
    within = {**body, "permissions": ["films"], "age_limit": "12"}
    assert browser.post(f"/api/members/{hugo['id']}", json=within).json()["age_limit"] == "12"
    own = {"name": "Max", "login": "max", "permissions": ["films", "manage-members"]}
    assert browser.post(f"/api/members/{manager}", json=own).status_code == 403
