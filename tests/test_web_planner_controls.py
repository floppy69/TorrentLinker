"""Web planner controls reach the domain planner on both execution paths."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.test_web_jobs import finished, login
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.plan import PlanGoal
from torrentlinker.store import CatalogueRow
from torrentlinker.web.app import create_app
from torrentlinker.web.operations import JobRequest, Operations
from torrentlinker.zen import ZenClass, ZenProfile


def test_web_plan_defaults_to_note_and_accepts_explicit_zen() -> None:
    assert JobRequest(kind="plan").planning_options().goal is PlanGoal.NOTE
    assert JobRequest(kind="plan", plan_goal="zen").planning_options().goal is PlanGoal.ZEN


@pytest.mark.parametrize("distributed", [False, True])
def test_web_plan_filters_categories_sizes_seeders_and_optional_count(tmp_path, distributed):
    class Client:
        def check(self):
            return "test"

        def folder_settings(self):
            return []

        def torrents(self, **kwargs):
            return [Torrent("f" * 40, "Existing", storage, size=4)]

        def files(self, infohash):
            return {"existing.epub": 4}

    class PreparedOperations(Operations):
        def __init__(self, setup):
            super().__init__(setup)
            setup.settings.indexer_categories = {
                2000: IndexerCategory("Films"),
                2030: IndexerCategory("Film", 2000),
                7000: IndexerCategory("Ebook"),
            }
            setup.settings.zen = ZenProfile(ZenClass.SWARM_KEEPER)
            # Desktop category state must not silently restrict web "All categories".
            setup.settings.plan_categories = [7000]
            setup.store.save_catalogue(
                [
                    CatalogueRow(f"{i:040x}", title, size, seeds, category, "", "", 0)
                    for i, title, size, seeds, category in [
                        (1, "Small film", 100, 2, 2030),
                        (2, "Film A", 1000, 3, 2030),
                        (3, "Film B", 1100, 4, 2030),
                        (4, "Large film", 10000, 2, 2030),
                        (5, "Popular film", 1000, 50, 2030),
                        (6, "Book", 1000, 3, 7000),
                    ]
                ]
            )

    storage = tmp_path / "downloads"
    storage.mkdir()
    (storage / "existing.epub").write_bytes(b"book")
    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        roots=(storage,),
        connector=lambda *args: Client(),
        operation_factory=PreparedOperations,
        monitor_verifications=False,
    )
    with TestClient(app) as browser:
        assert browser.get("/api/zen/catalogue").status_code == 401
        login(browser)
        assert browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://client.test"}
        ).is_success
        assert browser.post(
            "/api/setup/folder",
            json={"local": str(storage), "client_path": str(storage), "purpose": "download"},
        ).is_success
        assert browser.get("/api/setup").json()["indexer_categories"]["2030"]["parent"] == 2000
        assert browser.get("/api/zen/catalogue").json()["count"] == 6
        request = {
            "kind": "plan",
            "cached_only": True,
            "category": 2000,
            "plan_goal": "note",
            "min_size": 500,
            "max_size": 2000,
            "max_seeders": 4,
            "maximum_torrents": 1,
            "limit_torrents": False,
        }
        if distributed:
            request["client_ids"] = ["default"]
            request["client_budgets"] = {"default": 100_000}

        def run(body):
            submitted = browser.post("/api/jobs", json=body)
            assert submitted.status_code == 202, submitted.text
            result = finished(browser, submitted.json()["id"])
            assert result["status"] == "completed", result
            return result["result"]

        result = run(request)
        assert {row["title"] for row in result["rows"]} == {"Film A", "Film B"}
        assert result["size"] == 2100
        assert result["storage"][0]["download"] == 2100
        assert result["storage"][0]["after_plan"] == result["storage"][0]["free"] - 2100
        assert len(run({**request, "limit_torrents": True})["rows"]) == 1
        assert {row["title"] for row in run({**request, "category": None})["rows"]} == {
            "Film A",
            "Film B",
            "Book",
        }
        assert run({**request, "max_seeders": 0})["rows"] == []
        selected = run({**request, "category": None, "categories": [2030, 7000]})
        assert {row["title"] for row in selected["rows"]} == {"Film A", "Film B", "Book"}
        books = run({**request, "category": None, "categories": [7000]})
        assert [row["title"] for row in books["rows"]] == ["Book"]
        assert books["average_note"] is not None
        assert books["payback_days"] == pytest.approx(1000 / 1e9 / books["zen"])
        assert books["sending_seconds"] == 0
        assert books["rows"][0]["download_size"] == 1000
        assert books["rows"][0]["reseed"] is False
        invalid = browser.post("/api/jobs", json={**request, "min_size": 3000})
        assert invalid.status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"plan_goal": "invalid"},
        {"min_size": -1},
        {"max_seeders": -1},
        {"min_size": 2, "max_size": 1},
    ],
)
def test_plan_rejects_invalid_filters(fields):
    with pytest.raises(ValidationError):
        JobRequest(kind="plan", **fields)


@pytest.mark.parametrize("client_ids", [[], ["default"]])
@pytest.mark.parametrize("disk_rename", [False, True])
def test_plan_includes_checked_reseeds_without_spending_download_budget(
    tmp_path, client_ids, disk_rename
):
    import hashlib

    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.indexer import Candidate
    from torrentlinker.review import remember_candidates
    from torrentlinker.torrent_meta import read_torrent
    from torrentlinker.web.security import ServerSecrets
    from torrentlinker.web.setup import Setup

    root, config = tmp_path / "books", tmp_path / "config"
    root.mkdir()
    config.mkdir()
    book = root / "Example.epub"
    book.write_bytes(b"book" * 100)
    data = make_torrent(book)
    if disk_rename:
        book = book.rename(root / "Renamed.epub")
    infohash = read_torrent(data).infohash
    client = FakeQbit()
    if disk_rename:
        client.requires_disk_renames = True
        client.reseed_layout = lambda meta, match: match
    (root / "existing.epub").write_bytes(b"seed")
    client.by_hash["f" * 40] = Torrent(
        "f" * 40, "Existing", root, files={"existing.epub": 4}, size=4
    )
    links = tmp_path / "links"
    links.mkdir()
    setup = Setup(config, (root, links), ServerSecrets(config), lambda *args: client)
    if disk_rename:
        from torrentlinker.domain import TorrentClient

        setup.settings.client = TorrentClient.UTORRENT
        setup.settings.capture_client()
        setup.settings.profile().reseed_link_root = str(links)
    original = book.read_bytes(), book.stat().st_ino, book.name
    setup.configured = True
    setup.settings.zen = ZenProfile(ZenClass.SWARM_KEEPER)
    setup.settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    setup.settings.download_folders.default = str(root)
    setup.secrets.update({"indexer-api-key": "test-key"})
    indexer = setup.indexer()
    candidate = Candidate(
        "Example EPUB", 400, "https://c411.org/download/example", 3, infohash, categories=(7000,)
    )
    remember_candidates(setup.store, indexer, book, [candidate])
    key = hashlib.sha1(indexer.redact(candidate.download_url).encode()).hexdigest()
    setup.store.cache_torrent(key, data)
    with TestClient(
        create_app(
            config,
            password="test-password-long",
            service_override=setup,
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        assert browser.post("/api/setup/folder", json={"local": str(root)}).is_success

        def run(body):
            response = browser.post("/api/jobs", json=body)
            assert response.status_code == 202, response.text
            result = finished(browser, response.json()["id"])
            assert result["status"] == "completed", result
            return result["result"]

        run({"kind": "scan"})
        run({"kind": "library-review", "path": str(book)})
        request = {
            "kind": "plan",
            "cached_only": True,
            "maximum_bytes": 1,
            "client_ids": client_ids,
            "categories": [7000],
        }
        result = run(request)
        assert len(result["rows"]) == 1
        assert result["rows"][0]["reseed"] is True
        assert result["rows"][0]["path"] == str(book)
        assert result["size"] == 0
        assert result["payback_days"] == 0
        assert client.downloads == client.rechecked == []
        sending = {"kind": "send-plan", "plan_id": result["plan_id"]}
        preview = browser.post("/api/zen/plan/review", json=sending)
        assert preview.is_success, preview.text
        assert preview.json()["renames"] == []
        sent = run({**sending, "confirmation": preview.json()["token"]})
        assert len(sent["reseeded"]) == 1, sent
        assert client.rechecked == [infohash]
        assert client.started == client.downloads == []
        assert (book.read_bytes(), book.stat().st_ino, book.name) == original
        if disk_rename:
            assert not (root / "Example.epub").exists()
            assert (client.torrent(infohash).save_path / "Example.epub").is_symlink()
        assert browser.get("/api/zen/plan").json()["rows"] == []
        # Remove only the fake client state to exercise rejection independently.
        client.by_hash.pop(infohash)
        run({"kind": "library-reject", "path": str(book), "candidate_key": infohash})
        assert run(request)["rows"] == []
