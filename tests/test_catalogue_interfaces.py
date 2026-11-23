"""Catalogue controls through the owner API and the desktop bundled view."""

import threading

import httpx
from fastapi.testclient import TestClient

from tests.test_catalogue_sync import native_indexer
from tests.test_web_jobs import finished, login
from tests.test_web_plan_execution import prepared, second_client
from torrentlinker.web.app import create_app


def test_full_fetch_progress_keeps_native_roots_with_shared_torznab_ids(tmp_path):
    from torrentlinker.catalogue_sync import LISTED_ROOTS
    from torrentlinker.web.planning import catalogue

    _, setup, _, _ = prepared(tmp_path)
    setup._indexer = native_indexer(
        lambda request: httpx.Response(
            200,
            json={
                "data": [],
                "meta": {"page": 1, "perPage": 100, "total": 0, "totalPages": 1, "categories": []},
            },
        )
    )
    progress = []
    catalogue(setup, threading.Event(), progress.append)
    assert {p["catalogue_root"] for p in progress} == set(LISTED_ROOTS)
    assert all(p["catalogue_root"] == LISTED_ROOTS[p["position"]["done"] - 1] for p in progress)


def test_shared_catalogue_rejects_competing_fetches_from_other_sessions(tmp_path):
    config, setup, client, _ = prepared(tmp_path)
    other, _ = second_client(tmp_path, setup, client)
    entered, release = threading.Event(), threading.Event()

    def listing(request):
        entered.set()
        assert release.wait(10)
        return httpx.Response(
            200,
            json={
                "data": [],
                "meta": {"page": 1, "perPage": 100, "total": 0, "totalPages": 1, "categories": []},
            },
        )

    setup._indexer = native_indexer(listing)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with TestClient(app) as browser:
        login(browser)
        request = {"kind": "catalogue", "catalogue_root": 3}
        first = browser.post("/api/jobs", json=request)
        assert first.status_code == 202
        try:
            assert entered.wait(5)
            assert browser.post("/api/jobs", json=request).json() == first.json()
            for client_id in ("default", other.id):
                competing = browser.post(
                    "/api/jobs", json={**request, "catalogue_root": 2, "client_id": client_id}
                )
                assert competing.status_code == 400, competing.text
        finally:
            browser.post(f"/api/jobs/{first.json()['id']}/cancel")
            release.set()


def test_desktop_fetch_only_limits_non_c411_indexers(qtbot, tmp_path):
    from tests.fake_torznab import FakeTorznab
    from tests.test_indexer import FakeClock
    from torrentlinker.catalogue_sync import root_categories
    from torrentlinker.config import Settings
    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.gui.settings_common import INDEXER_API_KEY
    from torrentlinker.indexer import Indexer
    from torrentlinker.store import Store

    fake, clock = FakeTorznab(), FakeClock()
    fake.add(2000, 1)
    fake.add(7000, 1)
    settings = Settings()
    settings.indexer.url = "https://indexer.test/api"
    settings.indexer_categories = {2000: IndexerCategory("Films"), 7000: IndexerCategory("Ebook")}
    set_secret(INDEXER_API_KEY, "fixture-key")
    store = Store(tmp_path / "store.sqlite")
    window = MainWindow(settings, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window._indexer = Indexer(
        settings.indexer.url, "fixture-key", http=fake.client(), clock=clock.time, sleep=clock.sleep
    )
    window.zen_tab.catalogue.category_requested.emit(2)
    qtbot.waitUntil(lambda: window.catalogue_runner is None, timeout=10000)
    assert {r.category for r in store.catalogue()} == {7000}
    asked = {int(c) for r in fake.requests for c in r.url.params.get("cat", "").split(",") if c}
    assert asked <= set(root_categories(2))


def test_category_fetch_only_updates_selected_root_and_exposes_cards(tmp_path):
    config, setup, _, _ = prepared(tmp_path)
    roots = []

    def listing(request):
        query = dict(request.url.params)
        if "category" in query:
            roots.append(int(query["category"]))
        return httpx.Response(
            200,
            json={
                "data": [],
                "meta": {"page": 1, "perPage": 100, "total": 0, "totalPages": 1, "categories": []},
            },
        )

    setup._indexer = native_indexer(listing)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with TestClient(app) as browser:
        login(browser)
        cards = browser.get("/api/zen/catalogue").json()["cards"]
        assert next(c for c in cards if c["root"] == 2)["ours"] == 3
        assert not any(c["root"] == 8 for c in cards)
        submitted = browser.post("/api/jobs", json={"kind": "catalogue", "catalogue_root": 3})
        assert submitted.status_code == 202
        result = finished(browser, submitted.json()["id"])
        assert result["status"] == "completed", result
        assert roots and set(roots) == {3}
        cards = result["result"]["cards"]
        assert next(c for c in cards if c["root"] == 3)["state"] == "done"
        for root in (8, 999):
            invalid = browser.post("/api/jobs", json={"kind": "catalogue", "catalogue_root": root})
            assert invalid.status_code in (400, 422)


def test_desktop_cards_fetch_pause_language_and_resize(qtbot):
    # Other GUI tests select a process-wide Qt Quick renderer. Isolate Chromium's
    # resize check so its compositor can initialize normally.
    import os
    import subprocess
    import sys

    if not os.getenv("TL_PLAN_CATALOGUE_RESIZE_CHILD"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"{__file__}::test_desktop_cards_fetch_pause_language_and_resize",
            ],
            env={**os.environ, "TL_PLAN_CATALOGUE_RESIZE_CHILD": "1"},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.gui.zen_view import CatalogueBox, CategoryCard

    view = CatalogueBox()
    qtbot.addWidget(view)
    view.language = "en"
    view.resize(1100, 720)
    view.set_cards([CategoryCard(1, "Films & Vidéos", 3, 10, "paused")])
    view.set_state(False, True)
    view.show()
    wait_js(qtbot, view, "document.querySelector('[data-root=\"1\"]')!==null")
    assert js(qtbot, view, "document.body.textContent.includes('7 missing')")
    with qtbot.waitSignal(view.category_requested) as received:
        js(qtbot, view, "document.querySelector('[data-root=\"1\"] button').click()")
    assert received.args == [1]
    with qtbot.waitSignal(view.start_requested):
        js(qtbot, view, "document.querySelector('#catalogue-fetch').click()")
    view.set_state(True, False)
    wait_js(qtbot, view, "document.querySelector('[data-root=\"1\"] button').disabled")
    with qtbot.waitSignal(view.pause_requested):
        js(qtbot, view, "document.querySelector('#catalogue-pause').click()")
    view.language = "fr"
    view.refresh()
    view.resize(390, 700)
    wait_js(qtbot, view, "document.documentElement.lang==='fr'")
    wait_js(qtbot, view, "innerWidth<=390 && document.documentElement.scrollWidth<=innerWidth")
    assert js(qtbot, view, "document.body.textContent.includes('manquants')")
