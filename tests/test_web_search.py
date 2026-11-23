from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from tests.test_torrent_search import FACETS, TREE
from tests.test_web_jobs import Client, finished, login
from torrentlinker import net
from torrentlinker.indexer_search import IndexerFilters
from torrentlinker.web.app import create_app

HASHES = [f"{n:040x}" for n in (1, 2)]
POSTER = "https://image.tmdb.org/t/p/w500/p1.jpg"


def c411_listing(request):
    rows = [
        {
            "infoHash": h,
            "name": f"Release.{n}.2020.MULTI.VFF.1080p.WEB.x264-GRP",
            "size": 4_000_000_000 + n,
            "seeders": n,
            "leechers": 3 * n,
            "completions": 7 * n,
            "comments": 0,
            "uploader": f"up{n}",
            "isExclusive": n == 2,
            "isFreeleech": False,
            "createdAt": "2026-10-27T10:00:00Z",
            "category": {"id": 1, "name": "Films & Vidéos"},
            "subcategory": {"id": 6, "name": "Film"},
            "posterUrl": POSTER if n == 1 else None,
            "media": {
                "kind": "movie",
                "title": f"Title {n}",
                "year": 2020,
                "rating": 7.2,
                "runtime": 119,
                "genres": ["Aventure", "Comédie"],
                "overview": "A synopsis.",
                "cast": ["Dwayne Johnson", "Kevin Hart"],
                "directors": ["Jake Kasdan"],
                "originalTitle": "Welcome",
                "backdropUrl": "https://image.tmdb.org/t/p/w1280/b.jpg",
            },
            "language": "Multi (Français inclus)",
            "quality": "WEB-DL 1080",
            "tech": {"resolution": "1080p", "source": "WEB-DL", "languages": ["MULTI", "VFF"]},
            "palliativeSince": None,
        }
        for n, h in enumerate(HASHES, 1)
    ]
    meta = {
        "total": 137565,
        "page": int(request.url.params.get("page", 1)),
        "perPage": 10,
        "totalPages": 400,
        "totalSize": 1757108743727203,
        "palliativeCount": 693,
        "categories": [{"id": 1, "count": 138013}, {"id": 2, "count": 39239}],
    }
    return {"data": rows, "meta": meta}


DETAIL = {
    "name": "Release.1.2020.MULTI.VFF.1080p.WEB.x264-GRP",
    "description": "<p>Synopsis</p>",
    "uploader": "up1",
    "team": {"id": 9, "name": "BOUBA", "slug": "bouba"},
    "createdAt": "2026-10-27T10:00:00Z",
    "seeders": 0,
    "leechers": 3,
    "completions": 5,
    "files": [{"path": ["a.mkv"], "length": 1024}],
    "metadata": {
        "hasNfo": True,
        "nfoContent": "General\nFormat : Matroska",
        "isExclusive": True,
        "category": {"id": 1, "name": "Films & Vidéos"},
        "subcategory": {"id": 6, "name": "Film"},
        "options": [{"name": "Langue", "values": [{"id": 1, "value": "Multi"}]}],
        "tmdbData": {
            "id": 74342,
            "type": "movie",
            "title": "Title 1",
            "year": 2020,
            "rating": 7.2,
            "ratingCount": 12,
            "posterUrl": POSTER,
            "cast": [{"name": "Ann"}],
        },
    },
    "externalIds": [{"kind": "imdb", "value": "tt1234567"}],
    "trust": {"status": "untested", "isTested": False, "minVotesRequired": 3},
}


def png():
    """A valid 1x1 PNG, so a browser accepts it as an image."""
    import struct
    import zlib

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixel = zlib.compress(b"\x00\x33\x66\x99\xff")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")
    )


def fake_net(monkeypatch, seen, caps="<caps><categories/></caps>"):
    def handler(request):
        seen.append(request)
        path = request.url.path
        if request.url.host == "image.tmdb.org":
            return httpx.Response(200, content=png(), headers={"content-type": "image/png"})
        if path == "/api/categories":
            return httpx.Response(
                200, json={"data": [{**r, "color": "#3B82F6"} for r in TREE["data"]]}
            )
        if path.endswith("filter-options"):
            return httpx.Response(200, json=FACETS)
        if path == "/api/torrents":
            return httpx.Response(200, json=c411_listing(request))
        if path.startswith("/api/torrents/"):
            return httpx.Response(200, json=DETAIL)
        return httpx.Response(200, text=caps)

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler))
    )


def signed_in(tmp_path: Path):
    app = create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    browser = TestClient(app)
    browser.__enter__()
    login(browser)
    browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
    saved = browser.post(
        "/api/setup/indexer", json={"url": "https://c411.org/api", "api_key": "private-key"}
    )
    assert saved.status_code == 200, saved.text
    return browser


def search(browser, **body):
    created = browser.post("/api/jobs", json={"kind": "search", "query": "film", **body})
    assert created.status_code == 202, created.text
    job = finished(browser, created.json()["id"])
    assert job["status"] == "completed", job
    return job["result"]


def test_search_can_return_the_listing_details_counts_and_known_marks(tmp_path, monkeypatch):
    fake_net(monkeypatch, [])
    browser = signed_in(tmp_path)
    plain = search(browser)
    assert "listing" not in plain and "root_counts" not in plain
    result = search(browser, search_listing=True)
    assert [r["hash"] for r in result["rows"]] == HASHES
    first = result["listing"][HASHES[0]]
    assert (first["leechers"], first["completions"], first["uploader"]) == (3, 7, "up1")
    assert first["poster_url"] == POSTER and first["year"] == 2020 and first["rating"] == 7.2
    assert first["genres"] == ["Aventure", "Comédie"] and first["runtime"] == 119
    assert first["cast"] == ["Dwayne Johnson", "Kevin Hart"] and first["overview"] == "A synopsis."
    assert first["backdrop_url"].endswith("/w1280/b.jpg") and first["directors"] == ["Jake Kasdan"]
    assert [t for _, t in first["tags"]] == ["MULTI.VFF", "1080p", "WEB-DL"]
    assert result["listing"][HASHES[1]]["exclusive"] is True
    assert result["root_counts"] == {"1": 138013, "2": 39239}
    assert result["total_size"] == 1757108743727203 and result["palliative_count"] == 693
    assert result["pages"] == 400 and result["known"] == {}
    # The rows themselves are unchanged, so saved selections and agents see the same shape.
    assert set(result["rows"][0]) == set(plain["rows"][0])


def test_search_marks_results_the_queue_already_holds(tmp_path, monkeypatch):
    from torrentlinker.download_queue import enqueue
    from torrentlinker.indexer import Candidate, Indexer

    fake_net(monkeypatch, [])
    browser = signed_in(tmp_path)
    service = browser.app.state.agent_service.setup
    candidate = Candidate("Queued", 1, "https://c411.org/x", 1, HASHES[1])
    enqueue(service.store, Indexer("https://c411.org/api", "k"), candidate, tmp_path)
    assert search(browser, search_listing=True)["known"] == {HASHES[1]: "queued"}


def test_native_filters_including_team_and_sort_reach_the_listing(tmp_path, monkeypatch):
    seen: list = []
    fake_net(monkeypatch, seen)
    browser = signed_in(tmp_path)
    search(
        browser,
        category=1,
        filters={"team": "bouba", "sortBy": "seeders", "sortOrder": "asc", "exclusive": "true"},
        search_listing=True,
    )
    params = [r.url.params for r in seen if r.url.path == "/api/torrents"][-1]
    assert (params["team"], params["sortBy"], params["sortOrder"]) == ("bouba", "seeders", "asc")
    assert params["exclusive"] == "true" and params["category"] == "1"
    assert IndexerFilters(team="bouba").params()["team"] == "bouba"


def test_search_options_carry_the_root_colors(tmp_path, monkeypatch):
    fake_net(monkeypatch, [])
    browser = signed_in(tmp_path)
    created = browser.post("/api/jobs", json={"kind": "search-options"})
    options = finished(browser, created.json()["id"])["result"]
    assert options["root_colors"] == {"1": "#3B82F6", "2": "#3B82F6"}
    assert "team" in options["global_filters"]


def test_posters_are_served_from_tmdb_through_the_server_only(tmp_path, monkeypatch):
    seen: list = []
    fake_net(monkeypatch, seen)
    app = create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    with TestClient(app) as browser:
        assert browser.get("/api/poster", params={"url": POSTER}).status_code == 401
        login(browser)
        ok = browser.get("/api/poster", params={"url": POSTER})
        assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
        assert ok.content == png()
        again = browser.get("/api/poster", params={"url": POSTER})
        assert again.content == png()
        assert len([r for r in seen if r.url.host == "image.tmdb.org"]) == 1  # kept on disk
        for bad in (
            "https://evil.example/t/p/w500/p1.jpg",
            "http://image.tmdb.org/t/p/w500/p1.jpg",
            "",
        ):
            assert browser.get("/api/poster", params={"url": bad}).status_code == 404
        assert not any(r.url.host == "evil.example" for r in seen)


def test_torznab_search_has_no_listing_but_still_marks_queued(tmp_path, monkeypatch):
    def response(request):
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(
            200,
            text=(
                '<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel><item>'
                "<title>Book</title><size>1024</size><link>https://tracker.example/d</link>"
                f'<torznab:attr name="infohash" value="{"a" * 40}"/>'
                '<torznab:attr name="seeders" value="4"/></item></channel></rss>'
            ),
        )

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response))
    )
    app = create_app(tmp_path, password="test-password-long", connector=lambda *args: Client())
    with TestClient(app) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        browser.post(
            "/api/setup/indexer", json={"url": "https://tracker.example/api", "api_key": "k"}
        )
        result = search(browser, search_listing=True)
        assert result["listing"] == {} and result["root_counts"] == {}
        assert result["rows"][0]["title"] == "Book"


def test_details_return_the_page_facts_apart_from_the_description(tmp_path, monkeypatch):
    fake_net(monkeypatch, [])
    browser = signed_in(tmp_path)
    created = browser.post("/api/jobs", json={"kind": "details", "hashes": [HASHES[0]]})
    result = finished(browser, created.json()["id"])["result"]
    info = result["info"]
    assert "description" not in info and "nfo" not in info and "files" not in info
    assert (info["uploader"], info["team"], info["exclusive"]) == ("up1", "BOUBA", True)
    assert (info["seeders"], info["leechers"], info["completions"]) == (0, 3, 5)
    assert info["subcategory"] == "Film" and info["facts"] == [["Langue", ["Multi"]]]
    assert info["trust"]["status"] == "untested" and info["trust"]["required"] == 3
    assert info["media"]["title"] == "Title 1" and info["media"]["imdb_id"] == "tt1234567"
    assert info["poster"] == POSTER and result["nfo"].startswith("General")
