from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_multi_client_web import Client
from tests.test_web_jobs import finished, login
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.seeding import seeding
from torrentlinker.store import CatalogueRow
from torrentlinker.web.app import create_app
from torrentlinker.web.seeding import seeding_page
from torrentlinker.zen import ZenClass, ZenProfile


def torrent(number, name="Book", **changes):
    return replace(
        Torrent(
            f"{number:040x}",
            name,
            Path("/data"),
            tracker="https://tracker.c411.org/announce/private",
            size=1024**3,
            state="uploading",
            swarm_seeders=12,
            seeding_time=10 * 86400,
        ),
        **changes,
    )


def test_group_hierarchy_unknowns_and_filter_do_not_change_account_totals():
    profile = ZenProfile(ZenClass.SWARM_KEEPER)
    torrents = [
        torrent(1),
        torrent(2, "Paused", state="pausedUP"),
        torrent(3, "Unknown", swarm_seeders=-1),
        torrent(4, "Other tracker", tracker="https://other.test/announce"),
    ]
    cached = {
        t.hash: CatalogueRow(t.hash, t.name, t.size, 11, 7010, "", "", 0, "zen-lab")
        for t in torrents[:2]
    }
    categories = {7000: IndexerCategory("Ebook"), 7010: IndexerCategory("Livres", 7000)}
    view = seeding(profile, torrents, "https://c411.org", catalogue=cached, categories=categories)
    page = seeding_page(view, profile, 0, group="7000/7010")
    assert page["summary"]["count"] == 2
    assert page["summary"]["total"] == 3
    assert {g["id"] for g in page["groups"]} == {"7000", "7000/7010", "unknown"}
    assert next(g for g in page["groups"] if g["id"] == "7000")["count"] == 2
    assert next(r for r in page["rows"] if r["name"] == "Paused")["zen"] is None
    assert page["rows"][0]["provisional_category"] is True
    assert "private" not in str(page)
    filtered = seeding_page(view, profile, 0, query="LIVRES", group="7000/7010")
    assert filtered["matched"] == 2
    assert filtered["summary"] == page["summary"]
    assert filtered["classes"] == page["classes"]
    unknown = seeding_page(view, profile, 0, group="unknown")["rows"][0]
    assert unknown["seeders"] is None
    assert unknown["seed_days"] == 10
    assert seeding_page(view, profile, 0, query="missing")["groups"] == []


def test_large_category_is_paged_with_stable_numeric_sort_and_full_totals():
    profile = ZenProfile(ZenClass.REUPLOADER)
    view = seeding(
        profile, [torrent(i, size=i + 1) for i in range(1100)], "https://c411.org", uploads=5
    )
    first = seeding_page(view, profile, 5, group="unknown", sort="size", limit=100)
    second = seeding_page(view, profile, 5, group="unknown", sort="size", offset=100, limit=100)
    assert len(first["rows"]) == len(second["rows"]) == 100
    assert not {r["hash"] for r in first["rows"]} & {r["hash"] for r in second["rows"]}
    assert first["rows"][0]["size"] == 1100
    assert first["total"] == 1100
    assert first["groups"][0]["note"] is None
    assert first["summary"]["daily"] == pytest.approx(view.day.total)
    assert first["summary"] == second["summary"]
    assert first["classes"][-1]["current"] is True


def test_ten_thousand_torrents_have_global_pages_and_search_across_category_descendants():
    profile = ZenProfile(ZenClass.SWARM_KEEPER)
    torrents = [torrent(i, f"Release {i:05d}", size=i + 1) for i in range(10001)]
    cached = {
        row.hash: CatalogueRow(row.hash, row.name, row.size, 12, 7010 if i % 2 else 7020, "", "", 0)
        for i, row in enumerate(torrents)
    }
    view = seeding(
        profile,
        torrents,
        "https://c411.org",
        catalogue=cached,
        categories={
            7000: IndexerCategory("Books"),
            7010: IndexerCategory("Comics", 7000),
            7020: IndexerCategory("Fiction", 7000),
        },
    )
    page = seeding_page(
        view, profile, 0, group="all", sort="size", descending=False, offset=9900, limit=100
    )
    assert page["total"] == 10001
    assert len(page["rows"]) == 100
    assert page["rows"][0]["name"] == "Release 09900"
    assert page["rows"][-1]["name"] == "Release 09999"
    assert page["rows"][0]["category"] == "Books / Fiction"
    parent = seeding_page(view, profile, 0, group="7000", descendants=True, query="10000")
    assert parent["total"] == 1
    assert parent["rows"][0]["name"] == "Release 10000"
    assert parent["summary"] == page["summary"]
    assert seeding_page(view, profile, 0, group="all", query="Comics")["total"] == 5000


def test_seeding_endpoint_scopes_clients_deduplicates_and_reports_offline(tmp_path):
    class SeedClient(Client):
        def __init__(self, rows):
            super().__init__("test")
            self.rows = rows
            self.offline = False
            self.reads = 0

        def torrents(self, **kwargs):
            self.reads += 1
            if self.offline:
                raise TimeoutError("offline")
            return self.rows

    clients = {
        "https://one.test": SeedClient([torrent(1)]),
        "https://two.test": SeedClient([torrent(1), torrent(2)]),
    }
    app = create_app(
        tmp_path,
        password="test-password-long",
        connector=lambda kind, host, *args: clients[host],
        monitor_verifications=False,
    )
    with TestClient(app) as browser:
        assert browser.get("/api/zen/seeding").status_code == 401
        login(browser)
        assert browser.post(
            "/api/setup/client",
            json={"client": "qbittorrent", "host": "https://one.test", "name": "Home"},
        ).is_success
        remote = browser.post(
            "/api/clients",
            json={"client": "qbittorrent", "host": "https://two.test", "name": "Seedbox"},
        ).json()["client_id"]
        job = browser.post("/api/jobs", json={"kind": "refresh", "client_id": "all"}).json()
        assert finished(browser, job["id"])["status"] == "completed"
        before = sum(c.reads for c in clients.values())
        assert browser.get("/api/zen/seeding?client_id=default").json()["summary"]["count"] == 1
        assert (
            browser.get("/api/zen/seeding", params={"client_id": remote}).json()["summary"]["count"]
            == 2
        )
        combined = browser.get("/api/zen/seeding?client_id=all&group=unknown").json()
        assert combined["summary"]["count"] == 2
        assert combined["total"] == 2
        assert (
            sum(c.reads for c in clients.values()) == before
        )  # GET never refreshes or contacts c411.
        assert browser.get("/api/zen/seeding?limit=201").status_code == 422
        assert browser.get("/api/zen/seeding?sort=tracker").status_code == 422
        clients["https://two.test"].offline = True
        job = browser.post("/api/jobs", json={"kind": "refresh", "client_id": "all"}).json()
        assert finished(browser, job["id"])["status"] == "completed"
        stale = browser.get("/api/zen/seeding?client_id=all").json()
        assert stale["client_errors"][0]["name"] == "Seedbox"
        assert stale["summary"]["count"] == 2  # Last observations retained, explicitly flagged.
        clients["https://one.test"].offline = True
        job = browser.post("/api/jobs", json={"kind": "refresh", "client_id": "default"}).json()
        assert finished(browser, job["id"])["status"] == "failed"
        stale_single = browser.get("/api/zen/seeding?client_id=default").json()
        assert stale_single["client_errors"][0]["name"] == "Home"
        assert stale_single["summary"]["count"] == 1


def test_seeding_combines_approved_filters_before_paging_and_keeps_options():
    from torrentlinker.web.seeding import SeedingFilters

    profile = ZenProfile(ZenClass.SWARM_KEEPER)
    torrents = [
        torrent(1, "Small", size=1024**2, tags=("archive",), swarm_seeders=2),
        torrent(2, "Large", size=2 * 1024**3, tags=("archive",), swarm_seeders=3),
        torrent(3, "Paused", size=3 * 1024**3, state="pausedUP", tags=("favourite",)),
        torrent(4, "Unknown seeds", size=4 * 1024**3, swarm_seeders=-1),
    ]
    view = seeding(profile, torrents, "https://c411.org")
    unfiltered = seeding_page(view, profile, 0, group="all")
    filtered = seeding_page(
        view,
        profile,
        0,
        group="all",
        filters=SeedingFilters(state="seeding", tag="archive", size_min=1024**3, seed_max=3),
    )
    assert [row["name"] for row in filtered["rows"]] == ["Large"]
    assert filtered["summary"] == unfiltered["summary"]
    assert filtered["filter_options"] == unfiltered["filter_options"]
    assert "private" not in str(filtered)
    assert (
        seeding_page(view, profile, 0, group="all", filters=SeedingFilters(zen_min=0))["total"] == 3
    )
    assert (
        seeding_page(view, profile, 0, group="all", filters=SeedingFilters(seed_max=99))["total"]
        == 3
    )
    assert (
        seeding_page(view, profile, 0, group="all", filters=SeedingFilters(days_min=11))["total"]
        == 0
    )
    with pytest.raises(ValueError):
        SeedingFilters(size_min=float("nan"))
