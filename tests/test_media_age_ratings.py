"""Members 5 (#132): Age Ratings, their sources and the "Sans classification" page.

TMDb is always a fake here: no test reaches the real service."""

import json
import threading
import types

import pytest
from fastapi.testclient import TestClient

from tests.test_members_accounts import media_library
from tests.test_members_signin import member, sign_in
from tests.test_web_jobs import Client, login
from torrentlinker import age_ratings
from torrentlinker.accounts import Permission
from torrentlinker.web.app import create_app


class FakeTmdb:
    def __init__(self, answers):
        self.answers = answers  # title -> (id, [(country, certification)])
        self.calls = []

    def lookup(self, title, year, kind):
        self.calls.append(("lookup", title, year, kind.value))
        return self.answers.get(title, (None, []))[0]

    def certifications(self, tmdb_id, media_type):
        self.calls.append(("certifications", tmdb_id, media_type))
        return next((c for i, c in self.answers.values() if i == tmdb_id), [])


def add(library, identifier, client="default", **body):
    body = {"kind": "video", "title": identifier, "series": "", "year": "2023", **body}
    with library.db:
        library.db.execute(
            "INSERT INTO media_items VALUES (?,?,?,?,?,?,?,?)",
            (identifier, client, f"/m/{identifier}.mkv", "/m", 1, 1, 1.0, json.dumps(body)),
        )


def apply(library, key=""):
    library.apply_age_ratings(
        "default", types.SimpleNamespace(secrets={"tmdb-api-key": key}), threading.Event()
    )


def test_ratings_map_to_the_french_scale_and_only_french_ones_apply():
    french = age_ratings.parse("FR:12")
    assert (french.rating, french.french) == ("12", True)
    assert age_ratings.parse("France:-16").rating == "16"
    assert age_ratings.parse("Tous publics").french
    assert age_ratings.parse("-12").french
    rated_r = age_ratings.parse("Rated R")
    assert (rated_r.rating, rated_r.country, rated_r.french) == ("16", "US", False)
    assert age_ratings.parse("FSK 16").country == "DE"
    assert age_ratings.parse("US:PG-13 / FR:10").rating == "10"  # the French one wins
    assert age_ratings.parse("GB:15").rating == "16"
    assert age_ratings.parse("Unknown") is None
    assert age_ratings.from_tmdb([("US", "R"), ("FR", "")]).country == "US"
    assert age_ratings.from_tmdb([("US", "R"), ("FR", "12")]).rating == "12"
    assert age_ratings.rank("TP") == 0 and age_ratings.rank("18") == 4
    assert age_ratings.rank(None) is None


def test_nfo_then_tmdb_then_a_person(tmp_path):
    library = media_library(tmp_path)
    add(library, "vice-versa", certification="FR:Tous publics")
    add(library, "monde", title="Le Monde après nous", certification="Rated R")
    add(library, "oppenheimer", title="Oppenheimer", tmdb_id="872585")
    add(library, "saw", title="Saw X")
    add(library, "machine", title="The Machine")
    add(library, "e1", series="Arcane", title="Arcane")
    add(library, "e2", series="arcane", title="Arcane")
    add(library, "song", kind="music")
    tmdb = FakeTmdb(
        {
            "Oppenheimer": ("872585", [("FR", "12"), ("US", "R")]),
            "Saw X": ("951491", [("US", "R")]),
            "Arcane": ("94605", [("FR", "12")]),
        }
    )
    library.tmdb_client = lambda key: tmdb

    apply(library)  # no key: only the NFO
    assert library.age_rating("default", "vice-versa")["rating"] == "TP"
    assert library.age_rating("default", "vice-versa")["source"] == "nfo"
    monde = library.age_rating("default", "monde")
    assert monde["rating"] is None and monde["suggestion"]["country"] == "US" and not tmdb.calls

    apply(library, "KEY")
    oppenheimer = library.age_rating("default", "oppenheimer")
    assert (oppenheimer["rating"], oppenheimer["source"]) == ("12", "tmdb")
    assert ("lookup", "Oppenheimer", 2023, "movie") not in tmdb.calls  # its id was known
    saw = library.age_rating("default", "saw")
    assert saw["rating"] is None and saw["suggestion"] == {
        "rating": "16",
        "country": "US",
        "original": "R",
        "source": "tmdb",
    }
    assert library.age_rating("default", "e1")["rating"] == "12"  # a series as a whole
    assert library.age_rating("default", "e2")["rating"] == "12"
    assert library.age_rating("default", "song")["rating"] is None
    asked = len(tmdb.calls)
    apply(library, "KEY")
    assert len(tmdb.calls) == asked  # answers are kept; nothing asked again within a week

    # The page lists each unrated title once; a person's rating stays through scans.
    unrated = library.unrated("default")
    assert {r["id"] for r in unrated} == {"machine", "saw", "monde"}
    assert library.confirm_suggestions("default", setter="owner", name="") == 2
    assert [r["id"] for r in library.unrated("default")] == ["machine"]
    library.rate("default", "vice-versa", "10", setter="lea-id", name="Léa")
    apply(library, "KEY")
    person = library.age_rating("default", "vice-versa")
    assert person == {"rating": "10", "source": "person", "by": "Léa", "suggestion": None}
    with pytest.raises(ValueError):
        library.rate("default", "machine", "14", setter="owner", name="")
    with pytest.raises(KeyError):
        library.rate("default", "nothing", "12", setter="owner", name="")
    # A new episode of a series a person rated takes its rating.
    library.rate("default", "e1", "16", setter="owner", name="")
    add(library, "e3", series="Arcane", title="Arcane")
    apply(library, "KEY")
    assert library.age_rating("default", "e3")["rating"] == "16"


def test_an_age_limit_filters_with_one_indexed_join(tmp_path):
    """What #131 filters on: the rank, beside the item; unrated has none."""
    library = media_library(tmp_path)
    for name, rating in (("a", "TP"), ("b", "12"), ("c", "18"), ("d", None)):
        add(library, name)
        if rating:
            library.rate("default", name, rating, setter="owner", name="")
    visible = library.db.execute(
        "SELECT i.id FROM media_items i JOIN media_ratings r ON r.client=i.client AND r.item=i.id "
        "WHERE i.client=? AND r.rank<=? ORDER BY i.id",
        ("default", age_ratings.rank("12")),
    ).fetchall()
    assert [r[0] for r in visible] == ["a", "b"]
    plan = " ".join(
        str(r[-1])
        for r in library.db.execute(
            "EXPLAIN QUERY PLAN SELECT item FROM media_ratings WHERE client=? AND rank<=?",
            ("default", 2),
        )
    )
    assert "media_ratings_rank" in plan


def test_the_nfo_rating_is_read_from_the_sidecar(tmp_path):
    library = media_library(tmp_path)
    film = tmp_path / "Film.mkv"
    film.write_bytes(b"")
    (tmp_path / "Film.nfo").write_text(
        "<movie><title>Film</title><mpaa>US:R</mpaa><certification>FR:16</certification>"
        '<uniqueid type="tmdb">42</uniqueid></movie>'
    )
    library.sidecar = lambda client_id, path, folder, maximum=262144: path.read_bytes()
    assert library.nfo_age_rating("default", film, tmp_path) == {
        "certification": "FR:16 / US:R",
        "tmdb_id": "42",
    }


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
        library = app.state.agent_service.media
        add(library, "monde", title="Le Monde après nous", certification="Rated R")
        add(library, "machine", title="The Machine")
        apply(library)
        yield app, browser


def test_editors_rate_confirm_and_list_unrated_titles(server):
    app, browser = server
    login(browser)
    listing = browser.get("/api/media/ratings?client_id=default").json()
    assert listing["suggestions"] == 1 and len(listing["rows"]) == 2
    rated = browser.post(
        "/api/media/items/machine/rating", json={"client_id": "default", "rating": "TP"}
    )
    assert rated.json() == {"rating": "TP", "source": "person", "by": "", "suggestion": None}
    bad = {"client_id": "default", "rating": "14"}
    assert browser.post("/api/media/items/machine/rating", json=bad).status_code == 422
    missing = {"client_id": "default", "rating": "12"}
    assert browser.post("/api/media/items/nothing/rating", json=missing).status_code == 404
    assert browser.post("/api/media/ratings/confirm", json={"client_id": "default"}).json() == {
        "confirmed": 1
    }
    assert browser.get("/api/media/ratings?client_id=default").json()["rows"] == []

    # A Member allowed to edit ratings sets one, under their name; others cannot.
    member(app, "lea", Permission.FILMS, Permission.EDIT_RATINGS)
    member(app, "tom", Permission.FILMS)
    sign_in(browser, "lea")
    by_lea = browser.post(
        "/api/media/items/monde/rating", json={"client_id": "default", "rating": "18"}
    ).json()
    assert by_lea["by"] == "Lea" and by_lea["source"] == "person"
    assert browser.get("/api/media/ratings?client_id=default").status_code == 200
    sign_in(browser, "tom")
    assert browser.post("/api/media/items/monde/rating", json=missing).status_code == 403
    assert browser.get("/api/media/ratings?client_id=default").status_code == 403
