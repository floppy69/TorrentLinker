"""Media's tracker rows: c411's latest films, and better versions of library films."""

import contextlib
import json
import threading
from types import SimpleNamespace

import pytest

from torrentlinker.indexer import Candidate, RateLimited
from torrentlinker.store import CatalogueRow
from torrentlinker.torrent_search import ListingRow

GB = 1024**3


class FakeIndexer:
    is_c411 = True

    def background(self, stop=None):
        return contextlib.nullcontext()

    def unredact(self, value):
        return value


class FakeStore:
    """The Catalogue: every release's name and size, no runtime."""

    def __init__(self, rows=()):
        self.rows = [
            CatalogueRow(f"{n:040x}", name, size, 30, 2030, "", "", 0.0, "indexer", 1)
            for n, (name, size) in enumerate(rows)
        ]

    def catalogue_titled(self, words, limit=200):
        return [r for r in self.rows if all(w in r.title.lower() for w in words)][:limit]


def latest_page(*films, page=1, more=False):
    """A c411 listing page: each film's releases, with the facts ReleaseScore needs."""
    rows, details = [], {}
    for n, (title, year, releases) in enumerate(films):
        for m, (name, size) in enumerate(releases):
            h = f"{page:02d}{n:02d}{m:02d}".ljust(40, "a")
            rows.append(
                Candidate(name, size, "", 50 - m, h, "", (2030,), published_at=1.7e9 + n * 3600)
            )
            details[h] = ListingRow(
                title=title,
                year=year,
                kind="movie",
                runtime=120,
                genres=("Drame",),
                overview="Un film.",
                poster_url="https://image.tmdb.org/t/p/w500/poster.jpg",
            )
    return SimpleNamespace(rows=rows, details=details, has_more=more)


@pytest.fixture
def library(tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    root = tmp_path / "videos"
    root.mkdir()
    (root / "The Revenant 2015 VOSTFR 720 WEB.mkv").write_bytes(b"\0" * 64)
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
    with media.lock, media.db:
        # The scan read no real video: give the film the duration a real file reports.
        row = media.db.execute("SELECT id, body FROM media_items").fetchone()
        body = json.loads(row["body"]) | {"duration": 156 * 60}
        media.db.execute(
            "UPDATE media_items SET body=?, size=? WHERE id=?",
            (json.dumps(body), int(1.2 * GB), row["id"]),
        )
        # The scan's own refresh found nothing to ask; let the tests refresh now.
        media.db.execute("DELETE FROM media_options WHERE key LIKE 'tracker%'")
    return media


def setup_with(store=None, threshold=0, folder=None, profile="HDLight 1080p", key="key"):
    from torrentlinker.config import Settings

    settings = Settings()
    settings.release_score = {"threshold": threshold, "active": profile}
    return SimpleNamespace(
        settings=settings,
        store=store or FakeStore(),
        indexer=FakeIndexer,
        secrets=SimpleNamespace(get=lambda name: key),
        download_folder=lambda category: folder,
        verified_download_folder=lambda category: folder,
    )


OPPENHEIMER = (
    "Oppenheimer",
    2023,
    [
        ("Oppenheimer.2023.MULTi.2160p.BluRay.x265-TEAM", 40 * GB),
        ("Oppenheimer.2023.MULTi.1080p.WEB.x264-TEAM", 4 * GB),
    ],
)
REVENANT_RELEASES = [
    ("The.Revenant.2015.MULTi.1080p.WEB.x264-TEAM", 4 * GB),
    ("The.Revenant.2015.MULTi.2160p.BluRay.x265-TEAM", 40 * GB),
]


def test_latest_films_fill_once_then_cost_a_page_and_upgrades_cost_none(library, monkeypatch):
    pages = []

    def search(indexer, params, page=1):
        pages.append((params, page))
        latest = [OPPENHEIMER, ("The Revenant", 2015, [REVENANT_RELEASES[0]])]
        return latest_page(*latest, page=page, more=True)

    monkeypatch.setattr("torrentlinker.torrent_search.native_search", search)
    setup = setup_with(FakeStore(REVENANT_RELEASES))
    assert library.tracker_refresh("default", setup, threading.Event()) == "complete"
    # The first fill reads twenty pages of the latest films; library films cost nothing.
    assert [page for _, page in pages] == list(range(1, 21))
    assert pages[0][0]["sortBy"] == "createdAt" and pages[0][0]["category"] == "1"
    rows = library.tracker_rows("default", setup)
    # A film the library holds is never "available"; it can only be a better version.
    assert [item["title"] for item in rows["tracker"]["rows"]] == ["Oppenheimer"]
    assert rows["tracker"]["rows"][0]["tracker"]["published_at"]
    upgrade = rows["upgrades"]["rows"][0]
    assert upgrade["title"] == "The Revenant"
    assert upgrade["tracker"]["score"] >= upgrade["tracker"]["own_score"] + 5
    # A refresh within ten minutes asks nothing.
    assert library.tracker_refresh("default", setup, threading.Event()) == "waiting"
    assert len(pages) == 20
    # Later, the first page already holds known releases: one request is enough.
    monkeypatch.setattr("torrentlinker.media_tracker.RUN_INTERVAL", 0)
    assert library.tracker_refresh("default", setup, threading.Event()) == "complete"
    assert len(pages) == 21


def test_pages_read_before_c411_asks_to_wait_are_kept(library, monkeypatch):
    def search(indexer, params, page=1):
        if page == 3:
            raise RateLimited(60)
        return latest_page((f"Film {page}", 2020, [OPPENHEIMER[2][1]]), page=page, more=True)

    monkeypatch.setattr("torrentlinker.torrent_search.native_search", search)
    assert library.tracker_refresh("default", setup_with(), threading.Event()) == "limit"
    rows = library.tracker_rows("default", setup_with())
    assert sorted(item["title"] for item in rows["tracker"]["rows"]) == ["Film 1", "Film 2"]


def test_changing_the_profile_or_threshold_changes_the_suggestions_at_once(library, monkeypatch):
    monkeypatch.setattr(
        "torrentlinker.torrent_search.native_search",
        lambda indexer, params, page=1: latest_page(OPPENHEIMER),
    )
    library.tracker_refresh("default", setup_with(), threading.Event())

    def best(**options):
        rows = library.tracker_rows("default", setup_with(**options))
        return rows["tracker"]["rows"][0]["tracker"]["name"] if rows["tracker"]["rows"] else None

    assert best(profile="HDLight 1080p") == "Oppenheimer.2023.MULTi.1080p.WEB.x264-TEAM"
    assert best(profile="Qualité maximale") == "Oppenheimer.2023.MULTi.2160p.BluRay.x265-TEAM"
    assert best(threshold=100) is None
    # Answers exist but none reaches the threshold: the row says so.
    assert library.tracker_rows("default", setup_with(threshold=100))["tracker"]["state"] == "empty"


def test_better_versions_are_found_when_c411_asks_to_wait(library, monkeypatch):
    def limited(indexer, params, page=1):
        raise RateLimited(60)

    monkeypatch.setattr("torrentlinker.torrent_search.native_search", limited)
    setup = setup_with(FakeStore(REVENANT_RELEASES))
    assert library.tracker_refresh("default", setup, threading.Event()) == "limit"
    rows = library.tracker_rows("default", setup)
    # The latest releases are still to come; the row says c411 asked to wait.
    assert rows["tracker"]["state"] == "unavailable" and not rows["tracker"]["rows"]
    assert rows["tracker"]["reason"] == "limit"
    assert rows["upgrades"]["rows"][0]["title"] == "The Revenant"


def test_a_row_without_a_key_or_an_answer_says_why_instead_of_loading(library, monkeypatch):
    rows = library.tracker_rows("default", setup_with(key=""))
    assert [rows[k]["state"] for k in ("tracker", "upgrades")] == ["unavailable"] * 2
    assert rows["tracker"]["reason"] == rows["upgrades"]["reason"] == "key"
    # With a key and no refresh yet, the row really is loading.
    assert library.tracker_rows("default", setup_with())["tracker"]["state"] == "loading"

    def down(indexer, params, page=1):
        raise OSError("unreachable")

    monkeypatch.setattr("torrentlinker.torrent_search.native_search", down)
    assert library.tracker_refresh("default", setup_with(), threading.Event()) == "unreachable"
    row = library.tracker_rows("default", setup_with())["tracker"]
    assert row["state"] == "unavailable" and row["reason"] == "unreachable"


def test_queueing_a_tracker_film_needs_its_download_folder(library, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "torrentlinker.torrent_search.native_search",
        lambda indexer, params, page=1: latest_page(OPPENHEIMER),
    )
    library.tracker_refresh("default", setup_with(), threading.Event())
    item = library.tracker_rows("default", setup_with())["tracker"]["rows"][0]
    infohash = item["tracker"]["hash"]
    with pytest.raises(ValueError, match="Download Folder"):
        library.tracker_enqueue("default", setup_with(), infohash)
    queued = []
    monkeypatch.setattr(
        "torrentlinker.download_queue.enqueue",
        lambda store, indexer, candidate, folder: queued.append((candidate, folder)) or True,
    )
    result = library.tracker_enqueue("default", setup_with(folder=tmp_path), infohash)
    assert result["queued"] and queued[0][0].infohash == infohash and queued[0][1] == tmp_path
    assert queued[0][0].title == item["tracker"]["name"]
    with pytest.raises(ValueError, match="no longer suggested"):
        library.tracker_enqueue("default", setup_with(folder=tmp_path), "0" * 40)


def test_desktop_media_service_downloads_a_tracker_release_by_its_hash():
    from torrentlinker.media_browser import MediaBrowserService

    calls = []
    media = SimpleNamespace(
        setup=lambda client: "setup",
        tracker_download=lambda client, setup, h: calls.append((client, setup, h)) or {"ok": 1},
    )
    agent = SimpleNamespace(
        media=media, setup=SimpleNamespace(settings=SimpleNamespace(default_client_id="default"))
    )
    service = MediaBrowserService(agent)
    assert service.request(f"media/tracker/{'A' * 40}/download", {}, "POST") == {"ok": 1}
    assert calls == [("default", "setup", "a" * 40)]
    with pytest.raises(ValueError, match="Unknown tracker release"):
        service.request("media/tracker/../download", {}, "POST")


def test_a_cancelled_refresh_is_retried_at_the_next_scan(library, monkeypatch):
    monkeypatch.setattr(
        "torrentlinker.torrent_search.native_search",
        lambda indexer, params, page=1: latest_page(OPPENHEIMER),
    )
    setup = setup_with(FakeStore(REVENANT_RELEASES))
    stopped = threading.Event()
    stopped.set()
    assert library.tracker_refresh("default", setup, stopped) == "cancelled"
    # Nothing finished, so nothing to wait for: the next scan refreshes.
    assert library.tracker_refresh("default", setup, threading.Event()) == "complete"
    assert set(library.tracker_rows("default", setup)) == {"tracker", "upgrades"}


def test_new_suggestions_make_a_quiet_scan_redraw_the_rows(library, monkeypatch):
    monkeypatch.setattr(
        "torrentlinker.torrent_search.native_search",
        lambda indexer, params, page=1: latest_page(OPPENHEIMER),
    )
    real = library.setup("default")

    class Setup:
        """The library's own setup, answering through the fake c411."""

        def __getattr__(self, name):
            return FakeIndexer if name == "indexer" else getattr(real, name)

    monkeypatch.setattr(library, "setup", lambda client: Setup())
    first = library.scan("default", threading.Event(), lambda _p: None)
    assert first["changed"]  # the first suggestions arrived
    with library.lock, library.db:
        library.db.execute("DELETE FROM media_options WHERE key LIKE 'tracker-run%'")
    monkeypatch.setattr(
        "torrentlinker.torrent_search.native_search",
        lambda indexer, params, page=1: (_ for _ in ()).throw(RateLimited(60)),
    )
    assert not library.scan("default", threading.Event(), lambda _p: None)["changed"]


def test_download_queues_the_release_and_sends_it_like_search_start(library, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "torrentlinker.torrent_search.native_search",
        lambda indexer, params, page=1: latest_page(OPPENHEIMER),
    )
    library.tracker_refresh("default", setup_with(), threading.Event())
    infohash = library.tracker_rows("default", setup_with())["tracker"]["rows"][0]["tracker"][
        "hash"
    ]
    monkeypatch.setattr("torrentlinker.download_queue.enqueue", lambda *args: True)
    sent = []

    class Operations:
        def run(self, request, stop, progress):
            sent.append((request.kind, request.hashes))

    def submit(kind, work, *, client_id, parameters):
        work(threading.Event(), lambda _p: None)
        return f"{kind}:{client_id}"

    monkeypatch.setattr(library.agent, "for_client", lambda client: Operations())
    monkeypatch.setattr(library.agent.jobs, "submit", submit)
    result = library.tracker_download("default", setup_with(folder=tmp_path), infohash)
    assert result["queued"] and result["job"] == "search-send-queue:default"
    assert sent == [("send-queue", [infohash])]
