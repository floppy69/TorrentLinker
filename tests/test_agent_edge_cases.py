"""Boundary cases through the shared MCP tools and owner approval endpoints."""

from dataclasses import replace
from threading import Event

import pytest

from tests import test_catalogue_selection
from tests.test_agent_access import call
from tests.test_catalogue_selection import selection
from tests.test_web_jobs import finished
from torrentlinker.download_queue import entries

catalogue_app = test_catalogue_selection.catalogue_app


def propose(browser, token, tool, identifier, request_id):
    result = call(browser, token, tool, {"request_id": request_id, "selection_id": identifier})[
        "structuredContent"
    ]
    assert "id" in result, result
    return result


def approve(browser, proposal):
    response = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert response.is_success, response.text
    return finished(browser, response.json()["job_id"])


@pytest.mark.parametrize(
    "criteria", [{"categories": [999999]}, {"query": "no such film"}, {"offset": 1000}]
)
def test_empty_selection_never_falls_back_to_all_torrents(catalogue_app, criteria):
    _, browser, token = catalogue_app
    identifier = selection(browser, token, **criteria)
    result = call(browser, token, "job_status", {"job_id": identifier})["structuredContent"][
        "result"
    ]
    assert result["selected_count"] == result["total_size_bytes"] == 0
    assert result["min_size_bytes"] is result["max_size_bytes"] is None
    for tool in ("enqueue_selection", "send_selection"):
        result = call(browser, token, tool, {"request_id": tool, "selection_id": identifier})[
            "structuredContent"
        ]
        assert "empty" in result["error"]
    assert browser.get("/api/queue").json() == []


def test_repeated_enqueue_and_changed_request_id_do_not_duplicate(catalogue_app):
    app, browser, token = catalogue_app
    identifier = selection(browser, token)
    first = propose(browser, token, "enqueue_selection", identifier, "queue")
    assert approve(browser, first)["result"]["queued"] == 1
    retry = propose(browser, token, "enqueue_selection", identifier, "queue")
    assert retry["id"] == first["id"]
    duplicate = propose(browser, token, "enqueue_selection", identifier, "queue-again")
    assert approve(browser, duplicate)["result"]["queued"] == 0
    assert len(entries(app.state.agent_service.setup.store)) == 1
    collision = call(
        browser, token, "send_selection", {"request_id": "queue", "selection_id": identifier}
    )["structuredContent"]
    assert "different operation" in collision["error"]
    assert (
        app.state.agent_service.access.db.execute("SELECT count(*) FROM reservations").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "changed", ["missing", "sent", "sending", "refused", "failed", "size", "title", "category"]
)
def test_send_rejects_changed_or_unavailable_queue_entry(catalogue_app, changed):
    app, browser, token = catalogue_app
    identifier = selection(browser, token)
    assert (
        approve(browser, propose(browser, token, "enqueue_selection", identifier, "queue"))[
            "status"
        ]
        == "completed"
    )
    # Create approval first, then change the queue as a concurrent owner action would.
    pending = propose(browser, token, "send_selection", identifier, "send")
    store = app.state.agent_service.setup.store
    row = entries(store)[0]
    if changed == "missing":
        store.remove_downloads([row.key])
    elif changed in {"sent", "sending", "refused", "failed"}:
        store.download_outcome(row.key, changed)
    else:
        import json

        with store._lock, store._db:
            payload = json.loads(
                store._db.execute(
                    "SELECT payload FROM download_queue WHERE id=?", (row.key,)
                ).fetchone()[0]
            )
            payload["candidate"][{"category": "categories"}.get(changed, changed)] = {
                "size": 999,
                "title": "Other film",
                "category": [7000],
            }[changed]
            store._db.execute(
                "UPDATE download_queue SET payload=? WHERE id=?", (json.dumps(payload), row.key)
            )
    denied = browser.post(f"/api/agents/proposals/{pending['id']}/approve")
    assert denied.status_code == 400
    assert "Queued entries do not match" in denied.text
    assert (
        app.state.agent_service.access.db.execute("SELECT count(*) FROM reservations").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("state", ["full", "closed"])
def test_job_submission_rejection_does_not_spend_budget_or_strand_proposal(catalogue_app, state):
    app, browser, token = catalogue_app
    identifier = selection(browser, token)
    assert (
        approve(browser, propose(browser, token, "enqueue_selection", identifier, "queue"))[
            "status"
        ]
        == "completed"
    )
    pending = propose(browser, token, "send_selection", identifier, "send")
    service = app.state.agent_service
    release = Event()
    started = Event()

    def block(stop, progress):
        started.set()
        release.wait(15)

    try:
        if state == "full":
            service.jobs.submit("test-blocker", block)
            assert started.wait(2)
            for _ in range(19):
                service.jobs.submit("test-blocker", lambda stop, progress: None, deduplicate=False)
        else:
            service.jobs.closed = True
        denied = browser.post(f"/api/agents/proposals/{pending['id']}/approve")
        assert denied.status_code == 400, denied.text
        assert service.proposal(pending["id"])["status"] == "pending"
        assert service.access.db.execute("SELECT count(*) FROM reservations").fetchone()[0] == 0
        assert entries(service.setup.store)[0].status == "queued"
    finally:
        service.jobs.closed = False
        release.set()


def test_invalid_later_candidate_does_not_partially_enqueue_batch(catalogue_app):
    app, browser, token = catalogue_app
    store = app.state.agent_service.setup.store
    row = store.catalogue(["b" * 40])[0]
    store.save_catalogue([replace(row, download_url="")])
    identifier = selection(browser, token, count=2)
    pending = propose(browser, token, "enqueue_selection", identifier, "queue")
    result = approve(browser, pending)
    assert result["status"] == "failed"
    assert "download link" in result["error"]
    assert entries(store) == []


@pytest.mark.parametrize("change", ["space", "size", "identity", "revoked", "cancelled"])
def test_last_moment_download_checks_prevent_client_add(
    catalogue_app, tmp_path, monkeypatch, change
):
    from collections import namedtuple
    from types import SimpleNamespace

    import torf

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.store import CatalogueRow
    from torrentlinker.torrent_meta import read_torrent

    app, browser, token = catalogue_app
    service = app.state.agent_service
    setup = service.setup
    source = tmp_path / "Guard-film.mkv"
    source.write_bytes(b"film" * 1024)
    torrent = torf.Torrent(path=source, trackers=["https://test.invalid/announce"])
    torrent.generate()
    data = bytes(torrent.dump())
    meta = read_torrent(data)
    known_size = source.stat().st_size - 1 if change == "size" else source.stat().st_size
    selected_hash = "e" * 40 if change == "identity" else meta.infohash
    setup.store.save_catalogue(
        [
            CatalogueRow(
                selected_hash, "Guard film", known_size, 5, 2030, "https://test.invalid/file", "", 1
            )
        ]
    )
    client = FakeQbit()
    from pathlib import Path

    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "book", Path("/downloads/books"), files={"book.epub": 4}, progress=1
    )
    setup._client = client
    identifier = selection(browser, token, query="Guard film")
    assert (
        approve(browser, propose(browser, token, "enqueue_selection", identifier, "queue"))[
            "status"
        ]
        == "completed"
    )
    pending = propose(browser, token, "send_selection", identifier, "send")

    def fetch(candidate, retry=False):
        # This runs after reservation, immediately before the real send path.
        if change == "space":
            usage = namedtuple("usage", "total used free")(100000, 100000, 0)
            monkeypatch.setattr("torrentlinker.agent.budgets.shutil.disk_usage", lambda _: usage)
        elif change == "revoked":
            with service.access.lock, service.access.db:
                service.access.db.execute("UPDATE grants SET revoked=1")
        elif change == "cancelled":
            for stop in service.jobs.stops.values():
                stop.set()
        return data

    setup._indexer = SimpleNamespace(
        url="https://test.invalid", redact=lambda v: v, unredact=lambda v: v, fetch_torrent=fetch
    )
    result = approve(browser, pending)
    assert result["status"] in {"completed", "cancelled"}, result
    assert client.downloads == []
    row = entries(setup.store)[0]
    if change == "cancelled":
        assert row.status == "queued"
    else:
        assert row.status in {"failed", "refused"}
        reason = {
            "space": "insufficient disk space",
            "size": "size or identity",
            "identity": "does not match",
            "revoked": "revoked",
        }[change]
        assert reason in row.reason.lower(), row.reason


def test_size_display_keeps_decimal_and_binary_units_distinct():
    from torrentlinker.catalogue_selection import CatalogueCriteria, select_catalogue_rows
    from torrentlinker.store import CatalogueRow

    result = select_catalogue_rows(
        [CatalogueRow("a" * 40, "Film", 500 * 1024**3, 5, 2030, "https://test.invalid/a", "", 1)],
        {},
        CatalogueCriteria(),
    )
    assert result["total_size_bytes"] == 536870912000
    assert result["total_size_display"] == "500.00 GiB / 536.87 GB"
