import json

import pytest

from tests import test_catalogue_selection
from tests.test_agent_access import call
from tests.test_catalogue_selection import selection
from tests.test_web_jobs import finished

catalogue_app = test_catalogue_selection.catalogue_app


@pytest.mark.parametrize("case", ["default", "explicit-reserve", "pending-space", "space-changed"])
def test_direct_download_reserve_is_opt_in_but_pending_space_is_required(
    catalogue_app, tmp_path, monkeypatch, case
):
    from collections import namedtuple
    from pathlib import Path
    from types import SimpleNamespace

    import torf

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.store import CatalogueRow
    from torrentlinker.torrent_meta import read_torrent

    app, browser, _ = catalogue_app
    setup = app.state.agent_service.setup
    # This margin belongs to Plan generation, not a direct, explicitly selected send.
    setup.settings.free_space_margin = 0.2
    source = tmp_path / "Selected-film.mkv"
    source.write_bytes(b"film" * 1024)
    torrent = torf.Torrent(path=source, trackers=["https://test.invalid/announce"])
    torrent.generate()
    data = bytes(torrent.dump())
    meta = read_torrent(data)
    client = FakeQbit()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "book", Path("/downloads/books"), files={"book.epub": 4}
    )
    client.by_hash["c" * 40] = Torrent(
        "c" * 40, "Pending", Path("/downloads/books"), size=1000, progress=0
    )
    setup._client = client
    free = 5000 if case == "pending-space" else 6000
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "torrentlinker.agent.budgets.shutil.disk_usage",
        lambda _: usage(1000000, 1000000 - free, free),
    )

    def fetch(*args, **kwargs):
        nonlocal free
        if case == "space-changed":
            free = 5000
        return data

    setup.store.save_catalogue(
        [
            CatalogueRow(
                meta.infohash, "Selected film", 4096, 5, 2030, "https://test.invalid/file", "", 1
            )
        ]
    )
    setup._indexer = SimpleNamespace(
        url="https://test.invalid", redact=lambda v: v, unredact=lambda v: v, fetch_torrent=fetch
    )
    policy = {"name": "Direct downloads", "clients": ["default"]}
    if case == "explicit-reserve":
        policy["reserve_bytes"] = 2000
    created = browser.post("/api/agents", json=policy).json()
    token = created["token"]
    original = selection(browser, token, query="Selected film")
    approve(
        browser,
        tool(browser, token, "enqueue_selection", request_id="queue", selection_id=original),
    )
    selected = queue_selection(browser, token)
    preview = tool(browser, token, "preview_download", selection_id=selected)
    disk = preview["destinations"][0]
    assert disk["reserve_bytes"] == (2000 if case == "explicit-reserve" else 0)
    assert disk["pending_bytes"] == 1000
    fits = case not in {"explicit-reserve", "pending-space"}
    assert preview["fit_count"] == int(fits)
    if not fits:
        assert preview["rows"][0]["blockers"] == [
            "space_reserve" if case == "explicit-reserve" else "insufficient_space"
        ]
    proposal = tool(browser, token, "send_selection", request_id="send", selection_id=selected)
    assert proposal["requires_owner_approval"]
    assert client.downloads == []
    response = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    if not fits:
        assert response.status_code == 400
        assert (
            "reserve" if case == "explicit-reserve" else "Insufficient disk space"
        ) in response.text
    else:
        assert response.is_success, response.text
        result = finished(browser, response.json()["job_id"])
        assert result["status"] == "completed", result
        if case == "space-changed":
            queue = browser.get("/api/queue").json()
            assert queue[0]["status"] == "refused"
            assert "Insufficient disk space" in str(result)
    assert client.downloads == ([meta.infohash] if case == "default" else [])


def tool(browser, token, name, **arguments):
    result = call(browser, token, name, arguments)
    assert not result.get("isError"), result
    content = result["structuredContent"]
    assert not content.get("error"), content
    return content


def queue_films(browser, token):
    selected = selection(browser, token, count=2)
    proposal = tool(
        browser, token, "enqueue_selection", request_id="enqueue", selection_id=selected
    )
    approved = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert approved.is_success, approved.text
    assert finished(browser, approved.json()["job_id"])["status"] == "completed"


def test_queue_selection_filters_and_exact_totals_without_catalogue(catalogue_app):
    app, browser, token = catalogue_app
    queue_films(browser, token)
    app.state.agent_service.setup.store.save_catalogue([])
    selected = tool(
        browser,
        token,
        "select_queue",
        request_id="queue-selection",
        client_id="default",
        criteria={"categories": [2000], "count": 1, "sort_by": "size", "descending": True},
    )
    result = finished(browser, selected["job_id"])["result"]
    assert result["selected_count"] == 1
    assert result["eligible_count"] == 2
    assert result["total_size_bytes"] == 8
    assert result["rows"][0]["hash"] == "b" * 40


def queue_selection(browser, token, request_id="queue-selection", **criteria):
    selected = tool(
        browser,
        token,
        "select_queue",
        request_id=request_id,
        client_id="default",
        criteria=criteria,
    )
    done = finished(browser, selected["job_id"])
    assert done["status"] == "completed", done
    return selected["job_id"]


def test_preview_is_read_only_and_batch_caps_bind_an_exact_subset(catalogue_app):
    app, browser, token = catalogue_app
    queue_films(browser, token)
    identifier = queue_selection(browser, token)
    preview = tool(browser, token, "preview_download", selection_id=identifier)
    assert preview["selected_count"] == 2
    assert preview["remaining_daily_bytes"] == 10 * 1024**3
    assert preview["total_size_bytes"] == 12
    assert preview["observed_at"] > 0
    assert (
        app.state.agent_service.access.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        == 0
    )
    batch = tool(
        browser,
        token,
        "prepare_download_batch",
        request_id="batch",
        selection_id=identifier,
        maximum_bytes=8,
        maximum_torrents=1,
    )
    result = finished(browser, batch["job_id"])["result"]
    assert result["selected_count"] == 1
    assert result["total_size_bytes"] == 8
    assert result["rows"][0]["hash"] == "b" * 40
    assert len(browser.get("/api/queue").json()) == 2
    send = tool(browser, token, "send_selection", request_id="send", selection_id=batch["job_id"])
    review = browser.get(f"/api/agents/proposals/{send['id']}/review").json()
    assert review["selection"]["total_size_bytes"] == 8
    assert review["operation"]["hashes"] == ["b" * 40]
    assert (
        tool(browser, token, "send_selection", request_id="send", selection_id=batch["job_id"])[
            "id"
        ]
        == send["id"]
    )
    queue = browser.get("/api/queue").json()
    app.state.agent_service.setup.store.download_outcome(queue[1]["key"], "sent")
    rejected = browser.post(f"/api/agents/proposals/{send['id']}/approve")
    assert rejected.status_code == 400


def test_queue_only_permission_edits_priority_but_removal_requires_owner_review(catalogue_app):
    app, browser, token = catalogue_app
    queue_films(browser, token)
    created = browser.post(
        "/api/agents",
        json={
            "name": "Queue helper",
            "clients": ["default"],
            "mode": "execute",
            "permissions": ["queue"],
            "daily_bytes": 0,
            "daily_torrents": 0,
            "reserve_bytes": 0,
        },
    )
    assert created.is_success, created.text
    token = created.json()["token"]
    identifier = queue_selection(browser, token, count=1, descending=True, sort_by="size")
    edited = tool(
        browser,
        token,
        "edit_queue_selection",
        request_id="priority",
        selection_id=identifier,
        action="priority",
        priority=7,
    )
    assert finished(browser, edited["job_id"])["status"] == "completed"
    fresh = queue_selection(
        browser, token, "prioritized", sort_by="priority", descending=True, count=1
    )
    result = tool(browser, token, "job_status", job_id=fresh)["result"]
    assert result["rows"][0]["hash"] == "b" * 40
    assert result["rows"][0]["priority"] == 7
    send = tool(browser, token, "send_selection", request_id="send-prioritized", selection_id=fresh)
    assert send["requires_owner_approval"]
    removed = tool(
        browser,
        token,
        "edit_queue_selection",
        request_id="remove",
        selection_id=fresh,
        action="remove",
    )
    assert removed["requires_owner_approval"]
    assert len(browser.get("/api/queue").json()) == 2
    with pytest.raises(ValueError, match="Owner approval"):
        app.state.agent_service.execute(removed["id"], approved=False)
    approved = browser.post(f"/api/agents/proposals/{removed['id']}/approve")
    assert approved.is_success, approved.text
    assert finished(browser, approved.json()["job_id"])["result"]["removed"] == 1
    assert [r["hash"] for r in browser.get("/api/queue").json()] == ["a" * 40]
    assert (
        app.state.agent_service.access.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("generic", [False, True])
def test_overbroad_queue_removal_can_be_rejected_without_changing_entries(catalogue_app, generic):
    app, browser, token = catalogue_app
    queue_films(browser, token)
    token = browser.post(
        "/api/agents",
        json={
            "name": "Queue helper",
            "clients": ["default"],
            "mode": "execute",
            "permissions": ["queue"],
        },
    ).json()["token"]
    identifier = queue_selection(browser, token)
    before = browser.get("/api/queue").json()
    removal = tool(
        browser,
        token,
        "edit_queue_selection",
        request_id="remove-all",
        selection_id=identifier,
        action="remove",
    )
    assert removal["requires_owner_approval"]
    if generic:
        review = browser.get(f"/api/agents/proposals/{removal['id']}/review").json()
        removal = tool(
            browser,
            token,
            "propose_action",
            request_id="generic-removal",
            operation=review["operation"],
        )
        assert removal["requires_owner_approval"]
    with pytest.raises(ValueError, match="Owner approval"):
        app.state.agent_service.execute(removal["id"], approved=False)
    assert browser.get("/api/queue").json() == before
    assert browser.post(f"/api/agents/proposals/{removal['id']}/reject").is_success
    assert browser.get("/api/queue").json() == before
    assert app.state.agent_service.proposal(removal["id"])["status"] == "rejected"


def test_assistant_wrong_selection_waits_for_owner_and_rejection_preserves_queue(catalogue_app):
    import json

    from tests.test_assistant import generation_transport, wait_run
    from tests.test_assistant_waits import response, terminal
    from tests.test_assistant_waits import tool as model_tool

    app, browser, token = catalogue_app
    queue_films(browser, token)
    before = browser.get("/api/queue").json()
    calls = []

    def provider(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            return response(
                [
                    model_tool(
                        "select_queue",
                        {
                            "request_id": "whole-queue",
                            "client_id": "default",
                            "criteria": {"count": 10},
                        },
                    )
                ]
            )
        if len(calls) == 2:
            result = json.loads(
                next(m["content"] for m in reversed(payload["messages"]) if m["role"] == "tool")
            )
            return response(
                [
                    model_tool(
                        "edit_queue_selection",
                        {
                            "request_id": "wrong-removal",
                            "selection_id": result["job_id"],
                            "action": "remove",
                        },
                    )
                ]
            )
        return response(text="The owner rejected the removal; the queue is unchanged.")

    app.state.assistant.models.transport = generation_transport(provider)
    configured = browser.post(
        "/api/setup/assistant/providers",
        json={
            "name": "Controlled",
            "kind": "compatible",
            "url": "http://model.invalid/v1",
            "model": "test",
            # This provider reads raw receipts; context recovery is tested separately.
            "context_window": 131072,
        },
    ).json()
    chat = browser.post(
        "/api/assistant/conversations",
        json={
            "provider_id": configured["id"],
            "policy": {
                "name": "Queue only",
                "clients": ["default"],
                "mode": "execute",
                "permissions": ["queue"],
            },
        },
    ).json()
    run = browser.post(
        "/api/assistant/jobs",
        json={
            "conversation_id": chat["id"],
            "message": "Remove only Film A from the queue. Keep Film B.",
        },
    ).json()
    waiting = wait_run(browser, run["id"])
    assert waiting["status"] == "awaiting_approval", waiting
    assert len(calls) == 2
    assert browser.get("/api/queue").json() == before
    index = len(waiting["events"]) - 1
    proposal = waiting["events"][index]["result"]["id"]
    review = browser.get(f"/api/agents/proposals/{proposal}/review").json()
    assert review["selection"]["selected_count"] == 2
    assert {r["title"] for r in review["operation"]["selection_rows"]} == {"Film A", "Film B"}
    assert browser.post(
        f"/api/assistant/jobs/{run['id']}/decisions/{index}", json={"approve": False}
    ).is_success
    assert terminal(browser, run["id"])["status"] == "completed"
    assert browser.get("/api/queue").json() == before


def test_refinement_and_comparison_save_new_exact_snapshots(catalogue_app):
    _, browser, token = catalogue_app
    original = selection(browser, token, categories=[], count=3)
    refined = tool(
        browser,
        token,
        "refine_selection",
        request_id="refine",
        selection_id=original,
        exclude_queued=True,
        exclude_seeded=True,
    )
    result = finished(browser, refined["job_id"])["result"]
    assert [r["hash"] for r in result["rows"]] == ["c" * 40, "b" * 40]
    assert result["total_size_bytes"] == 10
    assert result["statistics"]["by_category"]["7000"] == {"count": 1, "total_size_bytes": 2}
    comparison = tool(
        browser,
        token,
        "compare_selections",
        left_selection_id=original,
        right_selection_id=refined["job_id"],
    )
    assert comparison["intersection"]["count"] == 2
    assert comparison["left_only"]["total_size_bytes"] == 4
    assert comparison["right_only"]["count"] == 0
    queued = tool(
        browser,
        token,
        "enqueue_selection",
        request_id="enqueue-refined",
        selection_id=refined["job_id"],
    )
    approved = browser.post(f"/api/agents/proposals/{queued['id']}/approve")
    assert approved.is_success, approved.text
    assert finished(browser, approved.json()["job_id"])["result"]["queued"] == 2
    assert tool(browser, token, "job_status", job_id=original)["result"]["selected_count"] == 3


def test_refinement_keeps_the_releases_the_user_picked_by_title_or_hash(catalogue_app):
    _, browser, token = catalogue_app
    original = selection(browser, token, categories=[], count=3)
    rows = tool(browser, token, "job_status", job_id=original)["result"]["rows"]
    picked = tool(
        browser,
        token,
        "refine_selection",
        request_id="pick",
        selection_id=original,
        keep=[rows[1]["title"].upper(), rows[2]["hash"]],
    )
    result = finished(browser, picked["job_id"])["result"]
    assert [r["hash"] for r in result["rows"]] == [rows[1]["hash"], rows[2]["hash"]]
    invented = call(
        browser,
        token,
        "refine_selection",
        {"request_id": "invented", "selection_id": original, "keep": ["Film.2024-ROMKENT"]},
    )
    failure = json.dumps(invented)
    if "job_id" in failure and not invented.get("isError"):
        failure = json.dumps(finished(browser, invented["structuredContent"]["job_id"]))
    assert "Not in this selection: Film.2024-ROMKENT" in failure


def test_download_only_grant_cannot_edit_queue_automatically_and_retries_are_idempotent(
    catalogue_app,
):
    _, browser, token = catalogue_app
    queue_films(browser, token)
    download = browser.post(
        "/api/agents",
        json={
            "name": "Download helper",
            "clients": ["default"],
            "mode": "execute",
            "permissions": ["downloads"],
        },
    ).json()["token"]
    identifier = queue_selection(browser, download, count=1)
    pending = tool(
        browser,
        download,
        "edit_queue_selection",
        request_id="remove",
        selection_id=identifier,
        action="remove",
    )
    assert pending["requires_owner_approval"]
    approved = browser.post(f"/api/agents/proposals/{pending['id']}/approve")
    assert approved.is_success, approved.text
    assert finished(browser, approved.json()["job_id"])["result"]["removed"] == 1
    repeated = tool(
        browser,
        download,
        "edit_queue_selection",
        request_id="remove",
        selection_id=identifier,
        action="remove",
    )
    assert repeated["id"] == pending["id"]
    changed = call(
        browser,
        download,
        "edit_queue_selection",
        {"request_id": "remove", "selection_id": identifier, "action": "retry"},
    )
    assert "error" in changed["structuredContent"]


def test_zero_budget_and_zero_caps_produce_empty_batch(catalogue_app):
    app, browser, token = catalogue_app
    queue_films(browser, token)
    token = browser.post(
        "/api/agents",
        json={
            "name": "Zero",
            "clients": ["default"],
            "daily_bytes": 0,
            "daily_torrents": 0,
            "reserve_bytes": 0,
        },
    ).json()["token"]
    identifier = queue_selection(browser, token)
    preview = tool(browser, token, "preview_download", selection_id=identifier)
    assert preview["remaining_daily_bytes"] == 0
    assert preview["remaining_daily_torrents"] == 0
    assert preview["fit_count"] == 0
    batch = tool(
        browser,
        token,
        "prepare_download_batch",
        request_id="zero",
        selection_id=identifier,
        maximum_bytes=0,
        maximum_torrents=0,
    )
    result = finished(browser, batch["job_id"])["result"]
    assert result["selected_count"] == 0
    assert result["total_size_bytes"] == 0
    rejected = call(
        browser,
        token,
        "send_selection",
        {"request_id": "empty-send", "selection_id": batch["job_id"]},
    )["structuredContent"]
    assert "empty" in rejected["error"]
    assert len(browser.get("/api/queue").json()) == 2
    assert (
        app.state.agent_service.access.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        == 0
    )


def test_unknown_remote_space_stays_unknown_and_preview_does_not_change_ledger(
    catalogue_app, monkeypatch
):
    app, browser, token = catalogue_app
    queue_films(browser, token)
    identifier = queue_selection(browser, token)
    client = app.state.agent_service.setup.client()

    def unavailable(**kwargs):
        raise OSError("Remote client unavailable")

    monkeypatch.setattr(client, "torrents", unavailable)
    before = app.state.agent_service.access.db.total_changes
    preview = tool(browser, token, "preview_download", selection_id=identifier)
    assert preview["fit_count"] == 0
    assert preview["destinations"][0]["capacity_bytes"] is None
    assert preview["destinations"][0]["free_bytes"] is None
    assert preview["destinations"][0]["pending_bytes"] is None
    assert all("client_unavailable" in row["blockers"] for row in preview["rows"])
    assert app.state.agent_service.access.db.total_changes == before


def test_stale_queue_cannot_be_previewed_prepared_or_edited(catalogue_app):
    app, browser, token = catalogue_app
    queue_films(browser, token)
    identifier = queue_selection(browser, token)
    app.state.agent_service.setup.store.download_outcome(
        browser.get("/api/queue").json()[0]["key"], "sending"
    )
    preview = call(browser, token, "preview_download", {"selection_id": identifier})[
        "structuredContent"
    ]
    assert "changed" in preview["error"]
    batch = tool(
        browser,
        token,
        "prepare_download_batch",
        request_id="stale",
        selection_id=identifier,
        maximum_bytes=100,
        maximum_torrents=2,
    )
    assert finished(browser, batch["job_id"])["status"] == "failed"
    rejected = call(
        browser,
        token,
        "edit_queue_selection",
        {"request_id": "stale-edit", "selection_id": identifier, "action": "remove"},
    )["structuredContent"]
    assert "changed" in rejected["error"]


def test_queue_snapshot_ownership_and_unconfirmed_manual_rows_are_rejected(catalogue_app):
    _, browser, token = catalogue_app
    queue_films(browser, token)
    identifier = queue_selection(browser, token)
    other = browser.post("/api/agents", json={"name": "Other", "clients": ["default"]}).json()[
        "token"
    ]
    for name, arguments in [
        ("preview_download", {"selection_id": identifier}),
        ("compare_selections", {"left_selection_id": identifier, "right_selection_id": identifier}),
        (
            "edit_queue_selection",
            {"request_id": "edit", "selection_id": identifier, "action": "remove"},
        ),
    ]:
        assert "error" in call(browser, other, name, arguments)["structuredContent"]
    result = call(
        browser,
        token,
        "propose_action",
        {
            "request_id": "manual-edit",
            "operation": {
                "kind": "edit-queue-selection",
                "client_id": "default",
                "queue_action": "remove",
            },
        },
    )["structuredContent"]
    assert "saved queue selection" in result["error"]


def test_catalogue_exclusions_apply_before_offset_and_count(catalogue_app):
    _, browser, token = catalogue_app
    identifier = selection(browser, token, categories=[], count=2, exclude_seeded=True)
    result = tool(browser, token, "job_status", job_id=identifier)["result"]
    assert [r["hash"] for r in result["rows"]] == ["c" * 40, "b" * 40]
    assert result["shortfall"] == 0


def approve(browser, proposal):
    response = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    assert response.is_success, response.text
    result = finished(browser, response.json()["job_id"])
    assert result["status"] == "completed", result
    return result["result"]


def test_definitive_fetch_failure_can_retry_after_destination_validation(catalogue_app):
    from types import SimpleNamespace

    app, browser, token = catalogue_app
    queue_films(browser, token)
    setup = app.state.agent_service.setup
    selected = queue_selection(browser, token, count=1, sort_by="size", descending=True)

    def fail_fetch(*args, **kwargs):
        raise OSError("Definitive pre-send failure")

    setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        redact=lambda v: v,
        unredact=lambda v: v,
        fetch_torrent=fail_fetch,
    )
    approve(
        browser,
        tool(browser, token, "send_selection", request_id="fail-fetch", selection_id=selected),
    )
    failed = queue_selection(browser, token, "failed", statuses=["failed"])
    result = tool(browser, token, "job_status", job_id=failed)["result"]
    assert result["rows"][0]["retry_safe"] is True
    approve(
        browser,
        tool(
            browser,
            token,
            "edit_queue_selection",
            request_id="retry",
            selection_id=failed,
            action="retry",
        ),
    )
    assert all(r["status"] == "queued" for r in browser.get("/api/queue").json())


@pytest.mark.parametrize("failure", ["timeout", "post-add-bookkeeping"])
def test_accepted_send_errors_are_uncertain_and_cannot_be_retried_or_removed(
    catalogue_app, tmp_path, monkeypatch, failure
):
    from pathlib import Path
    from types import SimpleNamespace

    import torf

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.store import CatalogueRow
    from torrentlinker.torrent_meta import read_torrent

    app, browser, token = catalogue_app
    setup = app.state.agent_service.setup
    source = tmp_path / "Uncertain-film.mkv"
    source.write_bytes(b"film" * 1024)
    torrent = torf.Torrent(path=source, trackers=["https://test.invalid/announce"])
    torrent.generate()
    data = bytes(torrent.dump())
    meta = read_torrent(data)

    class AcceptedThenTimeout(FakeQbit):
        def download(self, data, save_path, tags, *, sequential=False):
            result = super().download(data, save_path, tags, sequential=sequential)
            if failure == "timeout":
                raise TimeoutError("Client accepted the request but its response was lost")
            return result

    client = AcceptedThenTimeout()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "book", Path("/downloads/books"), files={"book.epub": 4}
    )
    setup._client = client
    setup.store.save_catalogue(
        [
            CatalogueRow(
                meta.infohash, "Uncertain film", 4096, 5, 2030, "https://test.invalid/file", "", 1
            )
        ]
    )
    setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        redact=lambda v: v,
        unredact=lambda v: v,
        fetch_torrent=lambda *args, **kwargs: data,
    )
    original = selection(browser, token, query="Uncertain film")
    approve(
        browser,
        tool(
            browser, token, "enqueue_selection", request_id="queue-uncertain", selection_id=original
        ),
    )
    selected = queue_selection(browser, token)
    if failure == "post-add-bookkeeping":

        def fail_bookkeeping(*args, **kwargs):
            raise OSError("Cannot save Catalogue after accepted add")

        monkeypatch.setattr(setup.store, "save_catalogue", fail_bookkeeping)
    approve(
        browser,
        tool(browser, token, "send_selection", request_id="uncertain-send", selection_id=selected),
    )
    assert client.downloads == [meta.infohash]
    assert browser.get("/api/queue").json()[0]["status"] == "uncertain"
    for action in ["remove", "retry"]:
        uncertain = queue_selection(browser, token, "uncertain-" + action, statuses=["uncertain"])
        proposed = tool(
            browser,
            token,
            "edit_queue_selection",
            request_id=action,
            selection_id=uncertain,
            action=action,
        )
        response = browser.post(f"/api/agents/proposals/{proposed['id']}/approve")
        assert response.is_success, response.text
        result = finished(browser, response.json()["job_id"])
        assert result["status"] == "failed"
        assert "uncertain" in result["error"]
    assert client.downloads == [meta.infohash]
    assert len(browser.get("/api/queue").json()) == 1


@pytest.mark.parametrize("ordering", ["priority", "title"])
def test_priority_and_explicit_snapshot_order_control_actual_sends(
    catalogue_app, tmp_path, ordering
):
    from pathlib import Path
    from types import SimpleNamespace

    import torf

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.store import CatalogueRow
    from torrentlinker.torrent_meta import read_torrent

    app, browser, token = catalogue_app
    setup = app.state.agent_service.setup
    client = FakeQbit()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "book", Path("/downloads/books"), files={"book.epub": 4}
    )
    setup._client = client
    data_by_hash = {}
    rows = []
    for name in ["First order film", "Second order film"]:
        source = tmp_path / (name + ".mkv")
        source.write_bytes(name.encode() * 1024)
        torrent = torf.Torrent(path=source, trackers=["https://test.invalid/announce"])
        torrent.generate()
        data = bytes(torrent.dump())
        meta = read_torrent(data)
        data_by_hash[meta.infohash] = data
        rows.append(
            CatalogueRow(
                meta.infohash,
                name,
                source.stat().st_size,
                5,
                2030,
                "https://test.invalid/" + meta.infohash,
                "",
                1,
            )
        )
    setup.store.save_catalogue(rows)
    setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        redact=lambda v: v,
        unredact=lambda v: v,
        fetch_torrent=lambda candidate, **kwargs: data_by_hash[candidate.infohash],
    )
    original = selection(browser, token, query="order film", count=2, sort_by="title")
    approve(
        browser,
        tool(browser, token, "enqueue_selection", request_id="queue-order", selection_id=original),
    )
    second = queue_selection(browser, token, query="Second")
    approve(
        browser,
        tool(
            browser,
            token,
            "edit_queue_selection",
            request_id="priority-order",
            selection_id=second,
            action="priority",
            priority=4,
        ),
    )
    ordered = queue_selection(
        browser, token, "ordered", sort_by=ordering, descending=ordering == "priority"
    )
    approve(
        browser,
        tool(browser, token, "send_selection", request_id="send-order", selection_id=ordered),
    )
    assert client.downloads == (
        [rows[1].infohash, rows[0].infohash]
        if ordering == "priority"
        else [rows[0].infohash, rows[1].infohash]
    )


def test_large_batch_observes_client_once_per_destination_not_per_item(catalogue_app, monkeypatch):
    from pathlib import Path

    from torrentlinker.download_queue import enqueue
    from torrentlinker.indexer import Candidate

    app, browser, token = catalogue_app
    setup = app.state.agent_service.setup
    for number in range(1, 501):
        enqueue(
            setup.store,
            setup.indexer(),
            Candidate(
                "Batch " + str(number),
                1,
                "https://test.invalid/file",
                5,
                f"{number:040x}",
                categories=(2030,),
            ),
            Path(setup.settings.download_folders.by_category[2030]),
        )
    token = browser.post(
        "/api/agents",
        json={
            "name": "Large batch",
            "clients": ["default"],
            "daily_torrents": 1000,
            "reserve_bytes": 0,
        },
    ).json()["token"]
    selected = queue_selection(browser, token, count=500)
    client = setup.client()
    original = client.torrents
    observed = []

    def count_calls(**kwargs):
        observed.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(client, "torrents", count_calls)
    result = tool(
        browser,
        token,
        "prepare_download_batch",
        request_id="large",
        selection_id=selected,
        maximum_bytes=500,
        maximum_torrents=500,
    )
    done = finished(browser, result["job_id"])
    assert done["result"]["selected_count"] == 500
    assert len(observed) <= 5


def test_missing_mount_never_reports_parent_filesystem_capacity(catalogue_app):
    from pathlib import Path

    app, browser, token = catalogue_app
    queue_films(browser, token)
    selected = queue_selection(browser, token)
    folder = Path(app.state.agent_service.setup.settings.download_folders.by_category[2030])
    folder.rename(folder.with_name("offline-books"))
    result = tool(browser, token, "preview_download", selection_id=selected)
    assert result["destinations"][0]["capacity_bytes"] is None
    assert result["destinations"][0]["free_bytes"] is None
    assert result["fit_count"] == 0


def test_preview_does_not_reconcile_completed_storage_reservations(catalogue_app):
    import json
    from datetime import UTC, datetime

    app, browser, token = catalogue_app
    queue_films(browser, token)
    selected = queue_selection(browser, token)
    access = app.state.agent_service.access
    actor = access.authenticate(token)
    from pathlib import Path

    from torrentlinker.plan import disk_of

    folder = app.state.agent_service.setup.settings.download_folders.by_category[2030]
    with access.lock, access.db:
        access.db.execute(
            "INSERT INTO proposals (id,grant_id,request_id,body,fingerprint,created,status) "
            "VALUES ('completed-send',?,'completed-send',?,'',0,'finished')",
            (actor, json.dumps({"client_id": "default", "hashes": ["a" * 40]})),
        )
        access.db.execute(
            "INSERT INTO reservations (proposal_id,grant_id,day,bytes,torrents,disk) "
            "VALUES ('completed-send',?,?,4,1,?)",
            (actor, datetime.now(UTC).date().isoformat(), str(disk_of(Path(folder)))),
        )
    changes = access.db.total_changes
    result = tool(browser, token, "preview_download", selection_id=selected)
    assert result["used_daily_bytes"] == 4
    assert result["remaining_daily_torrents"] == 19
    assert access.db.total_changes == changes
    assert (
        access.db.execute(
            "SELECT storage_reconciled FROM reservations WHERE proposal_id='completed-send'"
        ).fetchone()[0]
        == 0
    )


def test_invalid_date_filters_are_rejected_and_empty_queue_is_safe(catalogue_app):
    _, browser, token = catalogue_app
    for value in ["NaN", "Infinity", "-Infinity", -1]:
        result = call(
            browser,
            token,
            "select_queue",
            {
                "request_id": "invalid-date",
                "client_id": "default",
                "criteria": {"added_after": value},
            },
        )
        assert result.get("isError") or "error" in result.get("structuredContent", {}), result
    selected = queue_selection(browser, token)
    result = tool(browser, token, "preview_download", selection_id=selected)
    assert result["selected_count"] == 0
    assert result["fit_count"] == 0
    assert result["total_size_bytes"] == 0


def test_legacy_download_grants_migrate_once_without_granting_new_download_only_queue_rights(
    tmp_path,
):
    import json
    import sqlite3

    from fastapi.testclient import TestClient

    from tests.test_web_jobs import login
    from torrentlinker.web.app import create_app

    directory = tmp_path / "migration"
    with TestClient(create_app(directory, password="test-password-long")) as browser:
        login(browser)
        old = browser.post(
            "/api/agents",
            json={"name": "Legacy", "clients": ["default"], "permissions": ["downloads"]},
        ).json()
    with sqlite3.connect(directory / "agents.sqlite") as db:
        db.execute("DELETE FROM config WHERE key='queue_permission_v1'")
    with TestClient(create_app(directory, password="test-password-long")) as browser:
        login(browser)
        migrated = next(
            r for r in browser.get("/api/agents").json()["connections"] if r["id"] == old["id"]
        )
        assert set(migrated["permissions"]) == {"downloads", "queue"}
        new = browser.post(
            "/api/agents",
            json={"name": "Download only", "clients": ["default"], "permissions": ["downloads"]},
        ).json()
        assert new["permissions"] == ["downloads"]
    with sqlite3.connect(directory / "agents.sqlite") as db:
        bodies = {
            identifier: json.loads(body)
            for identifier, body in db.execute("SELECT id,body FROM grants")
        }
        assert bodies[new["id"]]["permissions"] == ["downloads"]
    with TestClient(create_app(directory, password="test-password-long")) as browser:
        login(browser)
        reread = next(
            r for r in browser.get("/api/agents").json()["connections"] if r["id"] == new["id"]
        )
        assert reread["permissions"] == ["downloads"]


def test_queue_key_binding_does_not_widen_to_same_hash_on_another_indexer(catalogue_app):
    from types import SimpleNamespace

    from torrentlinker.download_queue import enqueue, entries

    app, browser, token = catalogue_app
    queue_films(browser, token)
    setup = app.state.agent_service.setup
    from pathlib import Path

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent

    client = FakeQbit()
    client.by_hash["a" * 40] = Torrent(
        "a" * 40, "book", Path("/downloads/books"), files={"book.epub": 4}
    )
    setup._client = client
    existing = next(e for e in entries(setup.store) if e.candidate.infohash == "b" * 40)
    other = SimpleNamespace(url="https://other.invalid", redact=lambda v: v)
    enqueue(setup.store, other, existing.candidate, existing.folder)
    chosen = queue_selection(browser, token, query="Film B", count=1)
    fetched = []

    def fail_fetch(candidate, **kwargs):
        fetched.append(candidate.infohash)
        raise OSError("Fetch failed before sending")

    setup._indexer = SimpleNamespace(
        url="https://test.invalid",
        redact=lambda v: v,
        unredact=lambda v: v,
        fetch_torrent=fail_fetch,
    )
    approve(
        browser, tool(browser, token, "send_selection", request_id="one-key", selection_id=chosen)
    )
    assert fetched == ["b" * 40]
    duplicate = next(e for e in entries(setup.store) if e.indexer_url == other.url)
    assert duplicate.status == "queued"


def test_unknown_queue_identity_and_size_are_blocked_but_can_be_removed(catalogue_app):
    from pathlib import Path

    from torrentlinker.download_queue import enqueue
    from torrentlinker.indexer import Candidate

    app, browser, token = catalogue_app
    setup = app.state.agent_service.setup
    enqueue(
        setup.store,
        setup.indexer(),
        Candidate("Unknown identity", 0, "https://test.invalid/unknown"),
        Path(setup.settings.download_folders.by_category[2030]),
    )
    selected = queue_selection(browser, token)
    preview = tool(browser, token, "preview_download", selection_id=selected)
    assert {"unknown_identity", "unknown_size"} <= set(preview["rows"][0]["blockers"])
    assert preview["fit_count"] == 0
    assert preview["total_size_bytes"] is None
    comparison = call(
        browser,
        token,
        "compare_selections",
        {"left_selection_id": selected, "right_selection_id": selected},
    )["structuredContent"]
    assert "unknown torrent identities" in comparison["error"]
    edit = tool(
        browser,
        token,
        "edit_queue_selection",
        request_id="remove-unknown",
        selection_id=selected,
        action="remove",
    )
    assert approve(browser, edit)["removed"] == 1
    assert browser.get("/api/queue").json() == []


def test_catalogue_admission_exclusion_does_not_invalidate_its_queued_send(catalogue_app):
    app, browser, token = catalogue_app
    identifier = selection(browser, token, query="Film B", exclude_queued=True)
    approve(
        browser,
        tool(browser, token, "enqueue_selection", request_id="admit", selection_id=identifier),
    )
    send = tool(
        browser, token, "send_selection", request_id="send-admitted", selection_id=identifier
    )
    result = approve(browser, send)
    assert result["selected_count"] == 1
    assert result["rows"][0]["hash"] == "b" * 40


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("prepare_download_batch", {"maximum_bytes": 100, "maximum_torrents": 2}),
        ("refine_selection", {"exclude_seeded": False}),
        ("edit_queue_selection", {"action": "priority", "priority": 2}),
    ],
)
def test_completed_selection_operations_remain_idempotent_after_source_expires(
    catalogue_app, monkeypatch, name, arguments
):
    app, browser, token = catalogue_app
    queue_films(browser, token)
    selected = queue_selection(browser, token)
    operation = tool(browser, token, name, request_id="stable", selection_id=selected, **arguments)
    if operation["requires_owner_approval"]:
        approve(browser, operation)
    else:
        assert finished(browser, operation["job_id"])["status"] == "completed"
    import time

    now = time.time()
    monkeypatch.setattr("torrentlinker.agent.service.time.time", lambda: now + 901)
    retried = tool(browser, token, name, request_id="stable", selection_id=selected, **arguments)
    assert retried["id"] == operation["id"]
    assert retried["job_id"]


def test_send_approval_rejects_changed_queued_destination(catalogue_app):
    import json

    app, browser, token = catalogue_app
    queue_films(browser, token)
    selected = tool(
        browser,
        token,
        "select_catalogue",
        request_id="bound-selection",
        client_id="default",
        criteria={"query": "Film B", "count": 1},
    )["job_id"]
    assert finished(browser, selected)["status"] == "completed"
    proposal = tool(
        browser, token, "send_selection", request_id="bound-folder", selection_id=selected
    )
    store = app.state.agent_service.setup.store
    key, payload, _, _ = next(
        row for row in store.queued_downloads() if row[1]["candidate"]["infohash"] == "b" * 40
    )
    payload["folder"] = "/changed-destination"
    with store._lock, store._db:
        store._db.execute(
            "UPDATE download_queue SET payload=? WHERE id=?", (json.dumps(payload), key)
        )
    response = browser.post(f"/api/agents/proposals/{proposal['id']}/approve")
    if response.is_success:
        result = finished(browser, response.json()["job_id"])
        assert result["status"] == "failed", result
    else:
        assert response.status_code == 400, response.text
