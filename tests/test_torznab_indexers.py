import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from tests.torznab_fixtures import CAPS_XML, SEARCH_XML
from torrentlinker import net
from torrentlinker.config import Settings
from torrentlinker.indexer import RateLimited, SearchQuery
from torrentlinker.torznab import IndexerKeyRefused, TorznabIndexer, retry_after
from torrentlinker.web.app import create_app


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def indexer(handler, clock: Clock) -> TorznabIndexer:  # type: ignore[no-untyped-def]
    return TorznabIndexer(
        "https://other.example/api",
        "SECRET",
        "Other",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
    )


def test_a_429_rests_the_pacer_for_retry_after_then_retries() -> None:
    clock, calls = Clock(), []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, text=SEARCH_XML)

    found = indexer(handler, clock)
    with found.background():
        assert found.search(SearchQuery(q="x"))
    assert len(calls) == 2 and calls[1].url.params["apikey"] == "SECRET"
    assert sum(clock.sleeps) >= 7


def test_a_foreground_search_refuses_a_long_wait_and_no_pace_of_ours() -> None:
    clock = Clock()
    found = indexer(lambda r: httpx.Response(429, headers={"Retry-After": "600"}), clock)
    try:
        found.search(SearchQuery(q="x"))
    except RateLimited as error:
        assert error.retry_after == 600
    assert found.next_request_in() > 590

    fast = indexer(lambda r: httpx.Response(200, text=SEARCH_XML), clock)
    for _ in range(5):
        fast.search(SearchQuery(q="x"))
    assert clock.sleeps == []  # nothing waited: no cap of our own


def test_retry_after_as_seconds_or_date_and_refused_key_hides_secret() -> None:
    assert retry_after(httpx.Response(429, headers={"Retry-After": "12"})) == 12
    assert retry_after(httpx.Response(429, headers={"Retry-After": "soon"})) == 30
    clock = Clock()
    found = indexer(lambda r: httpx.Response(401), clock)
    try:
        found.search(SearchQuery(q="x"))
    except IndexerKeyRefused as error:
        assert "SECRET" not in str(error)


def test_old_settings_migrate_to_a_list_with_c411_first(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"indexer": {"url": "https://c411.example/api"}}))
    settings = Settings.load(path)
    assert [i.id for i in settings.indexers] == ["c411"]
    assert settings.indexer.url == "https://c411.example/api"
    settings.save(path)
    assert Settings.load(path).indexer.url == "https://c411.example/api"


def test_owner_adds_tests_disables_and_removes_an_indexer(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("apikey") != "good":
            return httpx.Response(401)
        return httpx.Response(200, text=CAPS_XML)

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler))
    )
    with TestClient(create_app(tmp_path, password="test-password-long")) as web:
        web.headers["X-TorrentLinker"] = "1"
        assert web.post("/api/login", json={"password": "test-password-long"}).status_code == 200
        bad = web.post(
            "/api/indexers", json={"name": "O", "url": "https://o.example/api", "api_key": "bad"}
        )
        assert bad.status_code == 400
        added = web.post(
            "/api/indexers",
            json={"name": "Other", "url": "https://o.example/api", "api_key": "good"},
        )
        assert added.status_code == 200, added.text
        assert "imdbid" in added.json()["searchable_ids"]
        listed = web.get("/api/indexers").json()["indexers"]
        assert [r["name"] for r in listed] == ["c411", "Other"]
        assert "good" not in json.dumps(listed) and listed[1]["has_key"]
        identifier = added.json()["id"]
        assert web.post(f"/api/indexers/{identifier}", json={"enabled": False}).status_code == 200
        assert web.post(f"/api/indexers/{identifier}/test").json()["ok"]
        assert not web.get("/api/indexers").json()["indexers"][1]["enabled"]
        assert web.post("/api/indexers/c411/remove").status_code == 400
        assert web.post(f"/api/indexers/{identifier}/remove").status_code == 200
        assert len(web.get("/api/indexers").json()["indexers"]) == 1
        assert "good" not in (tmp_path / "settings.json").read_text()


def hub_handler(listing: list[dict], seen: list[httpx.Request] | None = None):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/api/v1/indexer":
            if request.headers.get("X-Api-Key") != "hubkey":
                return httpx.Response(401)
            return httpx.Response(200, json=listing)
        if request.url.params.get("apikey") == "hubkey":
            return httpx.Response(200, text=CAPS_XML)
        return httpx.Response(401)

    return handler


def test_owner_imports_and_resyncs_prowlarr_indexers(tmp_path: Path, monkeypatch) -> None:
    listing = [
        {"id": 1, "name": "Nebula", "protocol": "torrent", "enable": True},
        {"id": 2, "name": "Orion", "protocol": "torrent", "enable": True},
        {"id": 3, "name": "Usenet", "protocol": "usenet", "enable": True},
    ]
    seen: list[httpx.Request] = []
    monkeypatch.setattr(
        net,
        "client",
        lambda **kwargs: httpx.Client(transport=httpx.MockTransport(hub_handler(listing, seen))),
    )
    with TestClient(create_app(tmp_path, password="test-password-long")) as web:
        web.headers["X-TorrentLinker"] = "1"
        assert web.post("/api/login", json={"password": "test-password-long"}).status_code == 200
        entry = {"service": "prowlarr", "url": "http://prowlarr.example:9696/", "api_key": "bad"}
        assert web.post("/api/indexers/hub", json=entry).status_code == 400
        connected = web.post("/api/indexers/hub", json={**entry, "api_key": "hubkey"})
        assert connected.status_code == 200, connected.text
        assert [a["name"] for a in connected.json()["available"]] == ["Nebula", "Orion"]
        assert web.get("/api/indexers/hub").json()["has_key"]

        done = web.post("/api/indexers/hub/import", json={"ids": ["1"]})
        assert done.json()["added"] == ["Nebula"]
        again = web.post("/api/indexers/hub/import", json={"ids": ["1"]})
        assert again.json()["added"] == []
        rows = web.get("/api/indexers").json()["indexers"]
        assert [(r["name"], r["source"]) for r in rows] == [("c411", ""), ("Nebula", "prowlarr")]
        assert rows[1]["url"] == "http://prowlarr.example:9696/1/api" and rows[1]["has_key"]
        assert "hubkey" not in json.dumps(rows) + (tmp_path / "settings.json").read_text()

        listing[:] = [{"id": 2, "name": "Orion", "protocol": "torrent"}] + [
            {"id": 1, "name": "Nebula 2", "protocol": "torrent"}
        ][:0]
        synced = web.post("/api/indexers/hub/sync").json()
        assert synced["removed"] == ["Nebula"] and synced["new"] == ["Orion"]
        assert web.get("/api/indexers").json()["indexers"][1]["missing"]
        listing.append({"id": 1, "name": "Nebula 2", "protocol": "torrent"})
        synced = web.post("/api/indexers/hub/sync").json()
        assert synced["renamed"] == ["Nebula 2"] and synced["removed"] == []
        row = web.get("/api/indexers").json()["indexers"][1]
        assert row["name"] == "Nebula 2" and not row["missing"]
        assert web.post("/api/indexers/hub/disconnect").status_code == 200
        assert web.get("/api/indexers").json()["indexers"][1]["source"] == ""


def test_owner_imports_jackett_indexers(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2.0/indexers":
            assert request.url.params["configured"] == "true"
            return httpx.Response(200, json=[{"id": "lyra", "name": "Lyra", "configured": True}])
        return httpx.Response(200, text=CAPS_XML)

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler))
    )
    with TestClient(create_app(tmp_path, password="test-password-long")) as web:
        web.headers["X-TorrentLinker"] = "1"
        assert web.post("/api/login", json={"password": "test-password-long"}).status_code == 200
        entry = {"service": "jackett", "url": "http://jackett.example:9117", "api_key": "k"}
        assert web.post("/api/indexers/hub", json=entry).status_code == 200
        assert web.post("/api/indexers/hub/import", json={"ids": ["lyra"]}).json()["added"] == [
            "Lyra"
        ]
        row = web.get("/api/indexers").json()["indexers"][1]
        assert row["source"] == "jackett"
        assert row["url"] == "http://jackett.example:9117/api/v2.0/indexers/lyra/results/torznab/"


def test_probe_reads_caps_without_saving_and_the_panel_runs_the_same_operations(
    tmp_path: Path, monkeypatch
) -> None:
    from torrentlinker.agent.desktop import DesktopSetup
    from torrentlinker.indexers_panel import IndexersPanel
    from torrentlinker.store import Store
    from torrentlinker.web.security import ServerSecrets

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("apikey") != "good":
            return httpx.Response(401)
        return httpx.Response(200, text=CAPS_XML)

    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler))
    )
    with TestClient(create_app(tmp_path, password="test-password-long")) as web:
        web.headers["X-TorrentLinker"] = "1"
        web.post("/api/login", json={"password": "test-password-long"})
        probe = web.post(
            "/api/indexers/probe", json={"url": "https://o.example/api", "api_key": "good"}
        )
        assert probe.status_code == 200 and "imdbid" in probe.json()["searchable_ids"]
        refused = web.post(
            "/api/indexers/probe", json={"url": "https://o.example/api", "api_key": "bad"}
        )
        assert refused.status_code == 400
        assert len(web.get("/api/indexers").json()["indexers"]) == 1  # nothing saved
        assert web.get("/api/indexers").json()["cross_seed"]["threshold"] == 0.95

    setup = DesktopSetup(Settings(), tmp_path / "settings.json", Store(tmp_path / "t.db"))
    setup.secrets = ServerSecrets(tmp_path)
    panel = IndexersPanel(setup)
    added = panel.request(
        "indexers", {"name": "Other", "url": "https://o.example/api", "api_key": "good"}, "POST"
    )
    assert panel.request(f"indexers/{added['id']}/probe", {})["ok"]
    assert [r["name"] for r in panel.request("indexers")["indexers"]] == ["c411", "Other"]
    assert panel.request("cross-seed/pause")["paused"] is True
    assert panel.request("cross-seed/settings", {"threshold": 0.9})["threshold"] == 0.9
    panel.request(f"indexers/{added['id']}/remove", {}, "POST")
    assert len(panel.request("indexers")["indexers"]) == 1
