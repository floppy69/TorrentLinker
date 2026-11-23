"""Film details come from c411 release descriptions and never fail a library refresh."""

import json
import threading
import types

from torrentlinker.indexer import RateLimited
from torrentlinker.media import MediaLibrary
from torrentlinker.store import CatalogueRow

DEBORAH = "9cd37233a21399a4bac244d146010dbfd4de4c01"
SPECTRAL = "a" * 40


class Catalogue:
    rows = [
        CatalogueRow(
            DEBORAH, "The.Taking.of.Deborah.Logan.2014.MULTI.1080p.BluRay", 1, 9, 2030, "", "", 0.0
        ),
        CatalogueRow(SPECTRAL, "Spectral.2016.MULTI.1080p.WEB", 1, 3, 2030, "", "", 0.0),
    ]

    def catalogue_titled(self, words, limit=200):
        return [r for r in self.rows if all(w.lower() in r.title.lower() for w in words)][:limit]


class C411:
    is_c411 = True

    def __init__(self, limited=()):
        self.calls = []
        self.limited = set(limited)

    def torrent_json(self, infohash):
        self.calls.append(infohash)
        if infohash in self.limited:
            raise RateLimited(600)
        return {
            "metadata": {
                "tmdbData": {
                    "id": 297608,
                    "title": "L'Étrange Cas Deborah Logan",
                    "originalTitle": "The Taking of Deborah Logan",
                    "overview": "Pour sa thèse consacrée à Alzheimer, Mia filme Deborah.",
                    "posterUrl": "https://image.tmdb.org/t/p/w500/poster.jpg",
                    "genres": ["Horreur", "Mystère"],
                    "directors": ["Adam Robitel"],
                    "rating": 6.8,
                    "year": 2014,
                }
            }
        }


def library(tmp_path, titles):
    agent = types.SimpleNamespace(setup=types.SimpleNamespace(path=tmp_path / "settings.json"))
    media = MediaLibrary(agent)
    with media.db:
        for number, (title, year) in enumerate(titles):
            body = {
                "kind": "video",
                "title": title,
                "year": year,
                "series": "",
                "description": "",
                "identity_source": "filename",
                "content_id": str(number),
                "artwork": "",
            }
            media.db.execute(
                "INSERT INTO media_items VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(number),
                    "default",
                    f"/films/{number}.mkv",
                    "/films",
                    1,
                    1,
                    0,
                    json.dumps(body),
                ),
            )
    return media


def setup(indexer):
    return types.SimpleNamespace(
        indexer=lambda: indexer, store=Catalogue(), settings=types.SimpleNamespace(path_mappings=[])
    )


def body(media, identifier):
    row = media.db.execute("SELECT body FROM media_items WHERE id=?", (identifier,)).fetchone()
    return json.loads(row[0])


def test_catalogue_release_gives_french_title_synopsis_and_poster(tmp_path):
    media = library(tmp_path, [("The Taking of Deborah Logan", "2014"), ("Unknown Film", "")])
    indexer = C411()
    status = media.enrich("default", setup(indexer), threading.Event(), lambda _p: None)
    assert status == "complete"
    film = body(media, "0")
    assert film["title"] == "L'Étrange Cas Deborah Logan"
    assert film["original_title"] == "The Taking of Deborah Logan"
    assert film["description"].startswith("Pour sa thèse")
    assert film["remote_artwork"].endswith("poster.jpg")
    assert film["genre"] == "Horreur, Mystère"
    assert film["identity_source"] == "c411 release description"
    assert body(media, "1")["title"] == "Unknown Film"
    # Answers are cached: a second refresh asks c411 nothing.
    media.enrich("default", setup(indexer), threading.Event(), lambda _p: None)
    assert indexer.calls == [DEBORAH]


def test_rate_limit_stops_quietly_and_a_later_refresh_finishes(tmp_path):
    media = library(tmp_path, [("Spectral", "2016"), ("The Taking of Deborah Logan", "2014")])
    status = media.enrich("default", setup(C411(limited={SPECTRAL})), threading.Event(), print)
    assert status == "limit"
    assert body(media, "0")["title"] == "Spectral"
    later = C411()
    assert media.enrich("default", setup(later), threading.Event(), print) == "complete"
    assert body(media, "0").get("release_details") == SPECTRAL
    assert body(media, "1").get("release_details") == DEBORAH


def test_without_c411_nothing_is_fetched(tmp_path):
    media = library(tmp_path, [("Spectral", "2016")])

    def missing():
        raise ValueError("Add your c411 API key in Settings first.")

    plain = types.SimpleNamespace(
        indexer=missing, store=Catalogue(), settings=types.SimpleNamespace(path_mappings=[])
    )
    assert media.enrich("default", plain, threading.Event(), print) == "off"
    assert "release_details" not in body(media, "0")


def test_downloaded_release_is_described_by_its_own_hash(tmp_path):
    from pathlib import Path

    from torrentlinker.domain import Torrent

    exact = "b" * 40
    media = library(tmp_path, [("deborah logan rip", "")])
    indexer = C411()
    downloaded = Torrent(exact, "rip", Path("/films"), {"0.mkv": 1}, progress=1.0)
    media.enrich("default", setup(indexer), threading.Event(), print, [downloaded])
    assert indexer.calls == [exact]
    assert body(media, "0")["release_details"] == exact


def test_home_rows_group_films_by_genre_rating_and_watch_state(tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    root = tmp_path / "films"
    root.mkdir()
    facts = [
        ("Horreur, Mystère", "7.4"),
        ("Horreur", "5.1"),
        ("Horreur, Drame", "8.0"),
        ("Drame", "6.0"),
        ("Comédie", ""),
    ]
    for number in range(len(facts)):
        (root / f"Film {number} (2020).mkv").write_bytes(b"\0" * 64)
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    media = app.state.assistant.agent.media
    media.scan("default", threading.Event(), lambda _p: None)
    ids = {}
    with media.db:
        for row in media.db.execute("SELECT id, body FROM media_items").fetchall():
            film = json.loads(row["body"])
            number = int(film["title"].split()[-1])
            ids[number] = row["id"]
            film.update(genre=facts[number][0], rating=facts[number][1])
            media.db.execute(
                "UPDATE media_items SET body=? WHERE id=?", (json.dumps(film), row["id"])
            )
        media.db.execute(
            "INSERT INTO media_progress (client,item,position,duration,watched) "
            "VALUES ('default',?,30,100,0)",
            (ids[4],),
        )
    rows = {(r["key"], r["title"]): r for r in media.home_rows("default", limit=10)["rows"]}
    horror = rows[("genre", "Horreur")]
    assert horror["total"] == 3 and horror["filters"] == {"view": "films", "genre": "Horreur"}
    assert ("genre", "Drame") not in rows  # fewer than three films
    assert [r["id"] for r in rows[("rated", "")]["rows"]] == [ids[2], ids[0]]
    assert ids[4] not in {r["id"] for r in rows[("unwatched", "")]["rows"]}
    assert [r["id"] for r in rows[("continue", "")]["rows"]] == [ids[4]]
    assert "Horreur" in media.listing("default", kind="video")["filters"]["genre"]


def test_series_view_shows_one_card_per_series_and_films_stay_films(tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    root = tmp_path / "videos"
    (root / "Show Saison 2").mkdir(parents=True)
    names = [
        "Show.S01E01.mkv",
        "Show.S01E02.mkv",
        "Show Saison 2/Show.201.mkv",
        "Star.Wars.Episode.4.A.New.Hope.1080p.mkv",
        "The Revenant 2015 VOSTFR 1080 Bluray.mkv",
    ]
    for name in names:
        (root / name).write_bytes(b"\0" * 64)
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    media = app.state.assistant.agent.media
    media.scan("default", threading.Event(), lambda _p: None)
    series = media.listing("default", kind="video", view="series")["rows"]
    assert [(s["title"], s["episode_count"], s["seasons"]) for s in series] == [("Show", 3, [1, 2])]
    films = {f["title"] for f in media.listing("default", kind="video", view="films")["rows"]}
    assert films == {"Star Wars Episode 4 – A New Hope", "The Revenant"}
    episodes = media.detail("default", series[0]["id"])["episodes"]
    assert [(e["season"], e["episode"]) for e in episodes] == [(1, 1), (1, 2), (2, 1)]
    rows = media.home_rows("default", scope="series")["rows"]
    assert [r["key"] for r in rows] == ["recent"] and rows[0]["filters"] == {
        "view": "series",
        "anime": False,
    }
