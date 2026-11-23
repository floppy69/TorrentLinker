import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from tests.test_indexer import FakeClock
from torrentlinker.catalogue import candidate
from torrentlinker.catalogue_sync import (
    SNAPSHOT_NAME,
    SNAPSHOT_URL,
    bootstrap_snapshot,
    snapshot_rows,
    sync_catalogue,
)
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.indexer import Indexer
from torrentlinker.store import FeedState, Store
from torrentlinker.zen import GB


@pytest.mark.parametrize("full", [False, True])
def test_images_catalogue_uses_torznab_when_json_omits_the_category(tmp_path, full):
    from tests.fake_torznab import FakeTorznab
    from torrentlinker.plan import PlanOptions, catalogue_candidates, make_plan
    from torrentlinker.store import CrawlState
    from torrentlinker.zen import ZenClass, ZenProfile

    fake = FakeTorznab(window=200)
    fake.add(6060, 300)
    json_calls = []

    def handler(request):
        if request.url.path == "/api/torrents":
            json_calls.append(request)
            return httpx.Response(
                200,
                json={
                    "data": [],
                    "meta": {"page": 1, "perPage": 100, "total": 0, "totalPages": 0},
                },
            )
        return fake.handler(request)

    store = Store(tmp_path / "s.db")
    # The old JSON crawl falsely certified this category as empty and complete.
    store.save_crawl_state(CrawlState(6060, complete=True))
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    ix = native_indexer(handler)
    sync_catalogue(ix, store, [6060], full=full)
    categories = {6000: IndexerCategory("XXX"), 6060: IndexerCategory("Images", 6000)}
    candidates = catalogue_candidates(
        store.catalogue(),
        DownloadFolders({6060: str(tmp_path)}),
        categories,
        set(),
        lambda _: "disk",
        {6060},
        adult=True,  # XXX: planned only once the user enables adult content
    )
    plan = make_plan(
        ZenProfile(ZenClass.SWARM_KEEPER),
        candidates,
        {"disk": 10 * GB},
        options=PlanOptions(max_download_bytes=10 * GB),
    )
    assert plan.items
    assert not json_calls
    assert all(item.candidate.category == 6060 for item in plan.items)
    assert store.catalogue_size() == 200
    assert store.crawl_state(6060).limited
    assert not store.crawl_state(6060).complete


def test_torznab_only_category_keeps_its_resume_cursor_after_backend_migration(tmp_path):
    from tests.fake_torznab import FakeTorznab
    from torrentlinker.store import CrawlState

    fake = FakeTorznab()
    fake.add(6060, 250)
    store = Store(tmp_path / "s.db")
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    store.save_crawl_state(CrawlState(6060, next_offset=1))  # old JSON pause marker
    ix = native_indexer(fake.handler)
    sync_catalogue(ix, store, [6060], full=True, max_pages=1)
    assert store.crawl_state(6060).next_offset == 100
    fake.requests.clear()
    sync_catalogue(ix, store, [6060], full=True)
    assert fake.requests[0].url.params["offset"] == "100"
    assert store.catalogue_size() == 250
    assert store.crawl_state(6060).complete


def snapshot(count=3):  # type: ignore[no-untyped-def]
    return {
        "stored": count,
        "hash": [f"{i:040x}" for i in range(count)],
        "title": [f"Book {i}" for i in range(count)],
        "sizeBytes": [GB] * count,
        "seeders": [10] * count,
        "category": [7000] * count,
    }


def live_item(i: int, seeds: int = 77):  # type: ignore[no-untyped-def]
    return {
        "infoHash": f"{i:040x}",
        "name": f"Book {i}",
        "size": GB,
        "seeders": seeds,
        "category": {"id": 2},
        "subcategory": {"id": 14},
    }


def native_indexer(handler):  # type: ignore[no-untyped-def]
    clock = FakeClock()
    return Indexer(
        "https://c411.org/api/torznab",
        "SECRET",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
    )


def test_snapshot_is_anonymous_and_live_rows_override_its_counts_and_category(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "s.db")
    anonymous: list[httpx.Request] = []
    direct: list[httpx.Request] = []

    def public(request: httpx.Request) -> httpx.Response:
        anonymous.append(request)
        return httpx.Response(200, json=snapshot())

    def live(request: httpx.Request) -> httpx.Response:
        direct.append(request)
        return httpx.Response(
            200,
            json={
                "data": [live_item(0), live_item(3)],
                "meta": {"page": 1, "perPage": 100, "total": 2, "totalPages": 1},
            },
        )

    ix = native_indexer(live)
    public_http = httpx.Client(transport=httpx.MockTransport(public))
    sync_catalogue(ix, store, [7000], full=True, snapshot_http=public_http)
    rows = {r.infohash: r for r in store.catalogue()}

    assert len(rows) == 4
    assert rows[f"{0:040x}"].seeders == 77
    assert rows[f"{0:040x}"].category == 7020
    assert rows[f"{0:040x}"].source == "indexer"
    assert rows[f"{1:040x}"].source == SNAPSHOT_NAME
    assert store.crawl_state(7000).complete
    assert str(anonymous[0].url) == SNAPSHOT_URL
    assert "authorization" not in anonymous[0].headers and "cookie" not in anonymous[0].headers
    assert direct[0].headers["Authorization"] == "Bearer SECRET"
    assert direct[0].url.host == "c411.org" and "apikey" not in direct[0].url.params
    download = candidate(ix, rows[f"{1:040x}"])
    url = httpx.URL(download.download_url)
    assert url.host == "c411.org" and url.params["apikey"] == "SECRET"
    assert url.params["id"] == f"{1:040x}" and url.params["t"] == "get"

    # Reimporting an older snapshot cannot undo a live category/seeder correction.
    bootstrap_snapshot(store, http=public_http, clock=lambda: time.time() + 86401)
    assert next(r for r in store.catalogue() if r.infohash == f"{0:040x}").seeders == 77
    requests = len(anonymous)
    bootstrap_snapshot(store, http=public_http, clock=lambda: time.time() + 86402)
    assert len(anonymous) == requests  # cached across restarts, too
    assert Store(tmp_path / "s.db").feed_state(SNAPSHOT_NAME).count == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("stored", 100),
        ("hash", ["bad"] * 3),
        ("sizeBytes", [-1, 1, 1]),
        ("category", [True, 7000, 7000]),
        ("seeders", [1.5, 1, 1]),
        ("hash", ["a" * 40, "a" * 40, "b" * 40]),
    ],
)
def test_invalid_snapshots_are_rejected_before_any_rows_are_written(
    tmp_path: Path, field: str, value: object
) -> None:
    store = Store(tmp_path / "s.db")
    data = {**snapshot(), field: value}
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data)))

    with pytest.raises(ValueError):
        bootstrap_snapshot(store, http=http)

    assert store.catalogue_size() == 0
    assert store.feed_state(SNAPSHOT_NAME).updated_at is None


def test_cancelled_snapshot_import_is_retryable_without_duplicates(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=snapshot(2000)))
    )
    progress = []
    bootstrap_snapshot(
        store,
        http=http,
        progress=progress.append,
        stop=lambda: bool(progress and progress[-1].offset >= 1000),
    )

    assert store.catalogue_size() == 1000
    assert store.feed_state(SNAPSHOT_NAME).updated_at is None

    bootstrap_snapshot(Store(tmp_path / "s.db"), http=http)
    assert store.catalogue_size() == 2000
    assert store.feed_state(SNAPSHOT_NAME).count == 2000


def test_live_json_crawl_resumes_and_does_not_call_a_capped_feed_complete(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    requested: list[int] = []

    def live(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested.append(page)
        return httpx.Response(
            200,
            json={
                "data": [
                    {**live_item(i), "category": {"id": 1}, "subcategory": {"id": 6}}
                    for i in range((page - 1) * 100, page * 100)
                ],
                "meta": {"page": page, "perPage": 100, "total": 300, "totalPages": 2},
            },
        )

    ix = native_indexer(live)
    sync_catalogue(ix, store, [2030], full=True, stop=lambda: bool(requested))
    assert requested == [1] and store.crawl_paused()
    assert not store.limited_categories()

    sync_catalogue(ix, Store(tmp_path / "s.db"), [2030], full=True)
    assert requested == [1, 2]
    assert not store.crawl_state(2030).complete
    assert store.limited_categories() == {2030}
    assert store.catalogue_size() == 200


def test_capped_categories_are_split_using_the_native_subcategory_ids(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    requests: list[tuple[str, int]] = []
    new = 0

    def live(request: httpx.Request) -> httpx.Response:
        p = request.url.params
        sub, page = p.get("subcat", ""), int(p["page"])
        requests.append((sub, page))
        start, count = (150, 150) if sub == "16" else (0, 150 if sub else 300)
        ids = list(range(start, start + count))
        if not sub:
            ids = [*range(300, 300 + new), *ids]
        count = len(ids)
        items = [live_item(i) for i in ids[(page - 1) * 100 : page * 100]]
        for item in items:
            item["subcategory"] = {"id": 16 if sub == "16" else 14}
        return httpx.Response(
            200,
            json={
                "data": items,
                "meta": {
                    "page": page,
                    "perPage": 100,
                    "total": count,
                    "totalPages": 2,
                    "subcategories": [{"id": 14, "count": 150}, {"id": 16, "count": 150}],
                },
            },
        )

    sync_catalogue(native_indexer(live), store, [7000], full=True)

    assert requests == [("", 1), ("14", 1), ("14", 2), ("16", 1), ("16", 2)]
    assert store.catalogue_size() == 300
    assert store.crawl_state(7000).complete
    assert {r.category for r in store.catalogue()} == {7010, 7020}

    # Once the history is fetched, a capped parent needs only its newest page.
    requests.clear()
    sync_catalogue(native_indexer(live), Store(tmp_path / "s.db"), [7000], full=True)
    assert requests == [("", 1)]
    assert store.crawl_state(7000).complete

    new = 150
    requests.clear()
    sync_catalogue(native_indexer(live), Store(tmp_path / "s.db"), [7000], full=True)
    assert requests == [("", 1), ("", 2)]
    assert store.catalogue_size() == 450
    assert store.crawl_state(7000).complete


def test_incremental_sync_reaches_its_checkpoint_even_when_new_rows_are_in_the_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "s.db"
    store = Store(path)
    # A later sync must not download the whole public snapshot again, even after a day.
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time() - 2 * 86400))
    total = 150
    requested: list[int] = []

    def live(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested.append(page)
        ids = list(range(total - 1, -1, -1))[(page - 1) * 100 : page * 100]
        return httpx.Response(
            200,
            json={
                "data": [live_item(i, seeds=total) for i in ids],
                "meta": {
                    "page": page,
                    "perPage": 100,
                    "total": total,
                    "totalPages": (total + 99) // 100,
                },
            },
        )

    def public(request: httpx.Request) -> httpx.Response:
        pytest.fail("A completed bootstrap should not be downloaded again")

    ix = native_indexer(live)
    public_http = httpx.Client(transport=httpx.MockTransport(public))
    sync_catalogue(ix, store, [7000], full=True, snapshot_http=public_http)
    assert requested == [1, 2]

    # Snapshot-known rows are not a checkpoint for this filter's live sync.
    store.save_catalogue(snapshot_rows(snapshot(370), time.time()))
    total = 370
    requested.clear()
    sync_catalogue(ix, Store(path), [7000], full=True, snapshot_http=public_http)

    assert requested == [1, 2, 3]
    rows = {r.infohash: r for r in store.catalogue()}
    assert all(rows[f"{i:040x}"].seeders == 370 for i in range(150, 370))
    assert rows[f"{0:040x}"].seeders == 150  # older history was not fetched again

    requested.clear()
    sync_catalogue(ix, Store(path), [7000], full=True, snapshot_http=public_http)
    assert requested == [1]


@pytest.mark.parametrize("failure", [False, True])
def test_interrupted_incremental_sync_keeps_the_last_successful_checkpoint(
    tmp_path: Path, failure: bool
) -> None:
    path = tmp_path / "s.db"
    store = Store(path)
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    total = 150
    interrupt = False
    requested: list[int] = []

    def live(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested.append(page)
        if failure and interrupt and page == 2:
            raise httpx.ConnectError("Disconnected", request=request)
        ids = list(range(total - 1, -1, -1))[(page - 1) * 100 : page * 100]
        return httpx.Response(
            200,
            json={
                "data": [live_item(i) for i in ids],
                "meta": {
                    "page": page,
                    "perPage": 100,
                    "total": total,
                    "totalPages": (total + 99) // 100,
                },
            },
        )

    ix = native_indexer(live)
    sync_catalogue(ix, store, [7000], full=True)
    old_state = _ebook_feed_state(store)
    total = 370
    interrupt = True
    requested.clear()
    if failure:
        with pytest.raises(httpx.ConnectError):
            sync_catalogue(ix, store, [7000], full=True)
    else:
        sync_catalogue(ix, store, [7000], full=True, stop=lambda: bool(requested))
    state = store.feed_state(old_state.name)
    assert state.updated_at == old_state.updated_at
    assert state.head_hashes == old_state.head_hashes

    total = 371  # another arrival while the app is paused or closed
    interrupt = False
    requested.clear()
    sync_catalogue(ix, Store(path), [7000], full=True)

    assert requested == [1, 2, 3]
    assert store.catalogue_size() == total
    assert store.feed_state(old_state.name).head_hashes[0] == f"{370:040x}"


def _ebook_feed_state(store: Store) -> FeedState:
    from urllib.parse import urlencode

    params = {
        "category": "2",
        "viewMode": "flat",
        "perPage": "100",
        "sortBy": "createdAt",
        "sortOrder": "desc",
        "palliative": "include",
    }
    return store.feed_state("c411-json:" + urlencode(params))


def test_ebook_selection_with_real_caps_only_fetches_native_ebook_categories(
    tmp_path: Path,
) -> None:
    from torrentlinker.catalogue import plan_categories

    xml = (Path(__file__).parent / "fixtures/c411_caps.xml").read_text()
    caps = Indexer(
        "https://c411.example/api/torznab",
        "K",
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=xml))),
    ).caps()
    categories = {
        cid: IndexerCategory(name, caps.parents.get(cid)) for cid, name in caps.categories.items()
    }
    folders = DownloadFolders({7000: "/ebooks", 3000: "/music", 2030: "/films"})
    targets = plan_categories({7000}, folders, categories)
    store = Store(tmp_path / "s.db")
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    requests: list[httpx.Request] = []

    def live(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page, sub = int(request.url.params["page"]), request.url.params.get("subcat")
        count = 300 if sub is None else 150
        start = 150 if sub == "14" else 0
        items = [
            live_item(i)
            for i in range(start + (page - 1) * 100, min(start + page * 100, start + count))
        ]
        for item in items:
            item["subcategory"] = {"id": int(sub) if sub else 11}
        return httpx.Response(
            200,
            json={
                "data": items,
                "meta": {
                    "page": page,
                    "perPage": 100,
                    "total": count,
                    "totalPages": 2,
                    "subcategories": [{"id": 11, "count": 150}, {"id": 14, "count": 150}],
                },
            },
        )

    progress = []
    sync_catalogue(
        native_indexer(live),
        store,
        targets,
        full=True,
        categories=categories,
        progress=progress.append,
    )

    assert requests and all(r.url.params["category"] == "2" for r in requests)
    assert {r.url.params.get("subcat") for r in requests} == {None, "11", "14"}
    assert {p.category for p in progress} == {7000, 3030, 7020}
    assert 3000 not in {p.category for p in progress}  # the separate Audio/music category


def test_zen_outage_still_allows_live_c411_to_refresh(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    public = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    ix = native_indexer(
        lambda r: httpx.Response(
            200,
            json={
                "data": [live_item(9)],
                "meta": {"page": 1, "perPage": 100, "total": 1, "totalPages": 1},
            },
        )
    )

    with pytest.raises(ValueError, match="available c411 pages were refreshed"):
        sync_catalogue(ix, store, [7000], full=True, snapshot_http=public)

    assert store.catalogue_size() == 1


def test_gui_plan_uses_cached_categories_without_individual_metadata_checks(
    qtbot, tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker import catalogue_sync
    from torrentlinker.config import Settings
    from torrentlinker.credentials import set_secret
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.gui.settings_common import INDEXER_API_KEY
    from torrentlinker.paths import MappedQbit, PathMapper

    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=snapshot()))
    )
    bootstrap = catalogue_sync.bootstrap_snapshot
    monkeypatch.setattr(
        catalogue_sync,
        "bootstrap_snapshot",
        lambda store, **kw: bootstrap(store, **{**kw, "http": http}),
    )
    checked: list[str] = []

    def live(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/torrents":
            return httpx.Response(
                200,
                json={
                    "data": [live_item(0), live_item(9)],
                    "meta": {"page": 1, "perPage": 100, "total": 2, "totalPages": 1},
                },
            )
        h = request.url.path.rsplit("/", 1)[-1]
        checked.append(h)
        return httpx.Response(200, json=live_item(int(h, 16), seeds=5))

    settings = Settings()
    settings.indexer_categories = {
        7000: IndexerCategory("Ebook"),
        7020: IndexerCategory("Livres", 7000),
    }
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    settings.plan_categories = [7020]  # broad snapshot entries stay out of a narrow selection
    store = Store(tmp_path / "s.db")
    window = MainWindow(settings, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "SECRET")
    window._indexer = native_indexer(live)
    window.qbit = lambda: MappedQbit(FakeQbit(), PathMapper([]))  # type: ignore[method-assign]

    window.make_plan()
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.plan is not None, timeout=10_000)

    plan = window.zen_tab.plan_view.plan
    assert len(plan.items) == 2
    assert checked == []
    assert all(item.candidate.source.source == "indexer" for item in plan.items)
    assert all(item.candidate.category == 7020 for item in plan.items)
    assert not window.zen_tab.plan_view.state()["busy"]
    assert not window.zen_tab.plan_view.state()["fetching"]


def test_large_cached_plan_makes_no_per_torrent_metadata_requests(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.config import Settings
    from torrentlinker.credentials import set_secret
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.gui.settings_common import INDEXER_API_KEY
    from torrentlinker.paths import MappedQbit, PathMapper

    store = Store(tmp_path / "s.db")
    data = snapshot(14_000)
    data["sizeBytes"] = [1000] * data["stored"]
    store.save_catalogue(snapshot_rows(data, 0))
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time(), count=14_000))
    requested: list[str] = []

    def live(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        assert request.url.path == "/api/torrents", "Planning must not verify individual torrents"
        return httpx.Response(
            200,
            json={
                "data": [],
                "meta": {"page": 1, "perPage": 100, "total": 0, "totalPages": 0},
            },
        )

    settings = Settings()
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    settings.plan_categories = [7000]
    window = MainWindow(settings, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "SECRET")
    window._indexer = native_indexer(live)
    window.qbit = lambda: MappedQbit(FakeQbit(), PathMapper([]))  # type: ignore[method-assign]

    window.make_plan()
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.plan is not None, timeout=5000)

    assert len(window.zen_tab.plan_view.plan.items) == 14_000
    assert requested == ["/api/torrents"]
    assert "Provisional estimates" in window.zen_tab.plan_view.notice


@pytest.mark.parametrize("paused_history", [False, True])
def test_gui_plan_does_not_start_or_resume_historical_scans(
    qtbot, tmp_path: Path, paused_history: bool
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.config import Settings
    from torrentlinker.credentials import set_secret
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.gui.settings_common import INDEXER_API_KEY
    from torrentlinker.paths import MappedQbit, PathMapper
    from torrentlinker.plan import PlanOptions

    settings = Settings()
    settings.indexer_categories = {
        7000: IndexerCategory("Ebook"),
        7030: IndexerCategory("Autres", 7000),
    }
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    settings.plan_categories = [7000]
    settings.plan_options = PlanOptions(max_torrents=1)
    store = Store(tmp_path / "s.db")
    store.save_catalogue(snapshot_rows(snapshot(100), time.time()))
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time(), count=100))
    child = replace(
        _ebook_feed_state(store),
        name=_ebook_feed_state(store).name + "&subcat=15",
        next_page=28,
        head_hashes=tuple(f"{i:040x}" for i in range(100)),
    )
    if paused_history:
        store.save_feed_state(child)
    requested: list[tuple[str | None, int]] = []

    def live(request: httpx.Request) -> httpx.Response:
        sub, page = request.url.params.get("subcat"), int(request.url.params["page"])
        requested.append((sub, page))
        return httpx.Response(
            200,
            json={
                "data": [{**live_item(i), "subcategory": {"id": 15}} for i in range(100)],
                "meta": {
                    "page": page,
                    "perPage": 100,
                    "total": 2800 if sub else 20000,
                    "totalPages": 28 if sub else 100,
                    "subcategories": [{"id": 15, "count": 20000}],
                },
            },
        )

    window = MainWindow(settings, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "SECRET")
    window._indexer = native_indexer(live)
    window.qbit = lambda: MappedQbit(FakeQbit(), PathMapper([]))  # type: ignore[method-assign]

    window.make_plan()
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.plan is not None, timeout=5000)

    assert requested == [(None, 1)]
    if paused_history:
        assert store.feed_state(child.name) == child  # the full-fetch cursor remains available
        requested.clear()
        sync_catalogue(window._indexer, store, [7000], full=True)
        assert requested == [(None, 1), ("15", 28)]


def test_first_latest_update_does_not_stop_at_its_own_partially_fetched_pages(
    tmp_path: Path,
) -> None:
    path = tmp_path / "s.db"
    store = Store(path)
    store.save_catalogue(snapshot_rows(snapshot(150), time.time()))
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    total = 400
    requested: list[int] = []

    def live(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested.append(page)
        ids = list(range(total - 1, -1, -1))[(page - 1) * 100 : page * 100]
        return httpx.Response(
            200,
            json={
                "data": [live_item(i) for i in ids],
                "meta": {
                    "page": page,
                    "perPage": 100,
                    "total": total,
                    "totalPages": (total + 99) // 100,
                },
            },
        )

    ix = native_indexer(live)
    sync_catalogue(ix, store, [7000], stop=lambda: bool(requested))
    assert requested == [1]
    assert not store.crawl_paused()  # latest updates do not pretend a history crawl was paused

    total = 401
    requested.clear()
    sync_catalogue(ix, Store(path), [7000])
    assert requested == [1, 2, 3, 4]
    assert store.catalogue_size() == 401

    requested.clear()
    sync_catalogue(ix, Store(path), [7000])
    assert requested == [1]


@pytest.mark.parametrize("capped", [False, True])
def test_full_parent_fetch_finishes_old_child_crawl_states(tmp_path: Path, capped: bool) -> None:
    from torrentlinker.store import CrawlState

    store = Store(tmp_path / "s.db")
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    store.save_crawl_state(CrawlState(7020, next_offset=1))

    def live(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [live_item(i) for i in range(100)],
                "meta": {
                    "page": 1,
                    "perPage": 100,
                    "total": 101 if capped else 100,
                    "totalPages": 1,
                },
            },
        )

    sync_catalogue(native_indexer(live), store, [7000], full=True)

    assert not store.crawl_paused()
    child = store.crawl_state(7020)
    assert child.next_offset == 0
    assert child.complete is not capped
    assert child.limited is capped
    assert store.catalogue_size() == 100

    # A previously fetched parent uses its saved checkpoint, but must still
    # repair legacy child markers on the next explicit fetch.
    store.save_crawl_state(CrawlState(7020, next_offset=1))
    sync_catalogue(native_indexer(live), Store(tmp_path / "s.db"), [7000], full=True)
    assert not store.crawl_paused()
    assert store.crawl_state(7020).limited is capped


def test_parent_fetch_preserves_pending_categories_with_other_native_sources(
    tmp_path: Path,
) -> None:
    from torrentlinker.store import CrawlState

    store = Store(tmp_path / "s.db")
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=time.time()))
    pending = CrawlState(4050, next_offset=1)
    store.save_crawl_state(pending)
    ix = native_indexer(
        lambda r: httpx.Response(
            200,
            json={
                "data": [],
                "meta": {"page": 1, "perPage": 100, "total": 0, "totalPages": 0},
            },
        )
    )

    sync_catalogue(ix, store, [1000], full=True)

    # 4050 also includes applications and GPS outside the fetched games categories.
    assert store.crawl_state(4050) == pending
    assert store.crawl_paused()


def test_the_whole_catalogue_refresh_reads_each_category_to_what_is_known(
    tmp_path: Path,
) -> None:
    from torrentlinker.catalogue_sync import REFRESH_FEED, refresh_catalogue, refresh_due

    store = Store(tmp_path / "s.db")
    store.save_feed_state(FeedState(SNAPSHOT_NAME, updated_at=1.0))  # no Zen Lab here
    asked: list[str] = []

    def listing(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.params["category"])
        return httpx.Response(
            200,
            json={
                "data": [live_item(int(request.url.params["category"]))],
                "meta": {"page": 1, "perPage": 100, "total": 1, "totalPages": 1},
            },
        )

    categories = {
        2000: IndexerCategory("Films", None),
        2010: IndexerCategory("Films/HD", 2000),
        7000: IndexerCategory("Livres", None),
    }
    assert refresh_due(store, now=1000.0)

    refresh_catalogue(native_indexer(listing), store, categories, clock=lambda: 1000.0)

    assert sorted(asked) == ["1", "2"]  # each top category once, its children with it
    assert store.catalogue_size() == 2
    assert store.feed_state(REFRESH_FEED).updated_at == 1000.0
    assert not refresh_due(store, now=1000.0 + 3 * 3600)
    assert refresh_due(store, now=1000.0 + 4 * 3600)


def test_the_whole_catalogue_refresh_leaves_other_indexers_alone(tmp_path: Path) -> None:
    from torrentlinker.catalogue_sync import REFRESH_FEED, refresh_catalogue

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("only c411's listing stops at what is known")

    ix = Indexer(
        "https://tracker.example/api", "K", http=httpx.Client(transport=httpx.MockTransport(never))
    )
    store = Store(tmp_path / "s.db")

    refresh_catalogue(ix, store, {7000: IndexerCategory("Books", None)})

    assert store.feed_state(REFRESH_FEED).updated_at is None


def test_a_capped_subcategory_is_read_oldest_first_then_year_by_year(tmp_path: Path) -> None:
    from torrentlinker.catalogue_sync import fill_capped

    asked: list[dict[str, str]] = []

    def listing(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        asked.append(q)
        meta = {"page": int(q["page"]), "perPage": 100, "total": 0, "totalPages": 1}
        rows = []
        if q["category"] == "1" and "subcat" not in q:
            meta |= {"total": 20000, "totalPages": 100}
            meta["subcategories"] = [{"id": 6, "count": 15000}, {"id": 7, "count": 5000}]
        elif q.get("subcat") == "6" and q.get("sortOrder") == "asc":
            rows = [live_item(1)]
        elif q.get("subcat") == "6" and q.get("year") == "2020":
            rows = [live_item(2), live_item(1)]
        meta["total"] = meta["total"] or len(rows)
        return httpx.Response(200, json={"data": rows, "meta": meta})

    store = Store(tmp_path / "s.db")
    fill_capped(native_indexer(listing), store, this_year=2026)

    assert store.catalogue_size() == 2
    subcat6 = [q for q in asked if q.get("subcat") == "6"]
    assert subcat6[0]["sortOrder"] == "asc"
    assert [q["year"] for q in subcat6[1:]] == [str(y) for y in range(1900, 2028)]
    assert not any(q.get("subcat") == "7" for q in asked)  # small enough to page through

    asked.clear()
    fill_capped(native_indexer(listing), store, this_year=2026)  # every part already read
    assert all("subcat" not in q for q in asked)


def test_fetching_one_category_reaches_parity_with_c411(tmp_path: Path) -> None:
    from torrentlinker.catalogue_sync import ROOT_FEED, fetch_root
    from torrentlinker.store import CatalogueRow

    store = Store(tmp_path / "s.db")
    store.save_feed_state(FeedState("c411-json:category=2&viewMode=flat", updated_at=1.0))

    def row(h: str, category: int, root: int | None = None) -> CatalogueRow:
        return CatalogueRow(h * 40, h, 1, 1, category, "u", "d", 5.0, root=root)

    # a: listed again. b: deleted on c411. c: unlisted but alive. d: XXX. e: another
    # category, never checked by this fetch.
    store.save_catalogue(
        [row("a", 7010), row("b", 7020), row("c", 7030), row("d", 6010), row("e", 2000, 1)]
    )
    asked: list[str] = []

    def c411(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/torrents/"):
            h = request.url.path.rsplit("/", 1)[1]
            asked.append(h[0])
            return httpx.Response(404 if h[0] == "b" else 200, json={})
        q = dict(request.url.params)
        meta = {"page": int(q["page"]), "perPage": 100, "total": 1, "totalPages": 1}
        if "category" not in q:
            meta["categories"] = [{"id": 2, "count": 2}]
            return httpx.Response(200, json={"data": [], "meta": meta})
        item = live_item(int("a" * 40, 16)) | {"infoHash": "a" * 40}
        return httpx.Response(200, json={"data": [item], "meta": meta})

    assert fetch_root(native_indexer(c411), store, 2, clock=lambda: 50.0, this_year=2026)

    assert sorted(asked) == ["b", "c"]  # only this category's unseen torrents, never XXX
    titles = {r.infohash[0] for r in store.catalogue()}
    assert titles == {"a", "c", "d", "e"}
    assert store.catalogue([("a" * 40)])[0].root == 2  # c411's own category, from the listing
    state = store.feed_state(f"{ROOT_FEED}2")
    assert state.updated_at == 50.0 and state.started_at is None and state.count == 2
    assert store.feed_state("c411-json:category=2&viewMode=flat").updated_at is None  # forgot
    store.save_catalogue([row("b", 7020)])
    assert "b" not in {r.infohash[0] for r in store.catalogue()}  # deleted for good
