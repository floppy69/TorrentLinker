"""Read-only audit against simulated clients and isolated HTTP responses."""

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from torrentlinker.domain import Torrent
from torrentlinker.indexer import KeyRefused, RateLimited
from torrentlinker.torrent_audit import TorrentAudit


class Indexer:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.active = False

    @contextmanager
    def background(self):
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def torrent_json(self, key, *, retry, stop):
        assert self.active and retry is False
        self.calls.append((key, time.monotonic()))
        response = self.responses[key].pop(0)
        if isinstance(response, Exception):
            raise response
        if response != 200:
            httpx.Response(
                response, request=httpx.Request("GET", "https://c411.org/private-key")
            ).raise_for_status()
        return {}


def torrent(number, *, tracker="https://tk.c411.tw/private-passkey/announce", tags=frozenset()):
    return Torrent(f"{number:040x}", f"Torrent {number}", Path("/data"), tracker=tracker, tags=tags)


def finish(service, identifier):
    for _ in range(300):
        report = service.read(identifier)
        if report["status"] != "running":
            return report
        time.sleep(0.01)
    raise AssertionError("audit did not finish")


def test_deduplicated_hashes_tracker_selection_confirmation_and_persistence(tmp_path):
    wanted = torrent(1, tags=frozenset({"mine"}))
    deleted = torrent(2, tags=frozenset({"mine"}))
    tag_only = torrent(
        3, tracker="https://other.invalid/announce", tags=frozenset({"mine", "torrentlinker"})
    )
    full_list = Torrent(
        "4" * 40,
        "Backup only",
        Path("/data"),
        tracker="https://other.invalid/private-passkey",
        trackers=("https://tk.c411.tw/private-passkey/announce",),
        tags=frozenset({"mine"}),
    )
    rows = {"a": [wanted, deleted, tag_only, torrent(5), full_list], "b": [wanted, deleted]}
    indexer = Indexer({wanted.hash: [200], deleted.hash: [404, 404], full_list.hash: [200]})
    service = TorrentAudit(
        tmp_path, lambda key: (key, rows[key]), lambda: indexer, confirm_after=0.05
    )
    result = finish(service, service.start(["a", "b"], "mine")["id"])
    assert result["counts"] == {"present": 3, "deleted": 2, "unknown": 0, "suspect": 0}
    assert result["checked_hashes"] == 3
    calls = [at for key, at in indexer.calls if key == deleted.hash]
    assert len(calls) == 2 and calls[1] - calls[0] >= 0.05
    assert len(indexer.calls) == 4
    assert "private-passkey" not in json.dumps(result)
    restored = TorrentAudit(tmp_path, None, None)
    assert restored.read(result["id"])["counts"] == result["counts"]
    assert len(restored.history()) == 1
    assert len(json.loads(restored.export(result["id"])["content"])["rows"]) == 5
    assert "private-passkey" not in restored.export(result["id"], "csv")["content"]
    assert rows["a"][0] == wanted


@pytest.mark.parametrize(
    "response,reason",
    [
        (429, "rate_limited"),
        (401, "key_refused"),
        (403, "key_refused"),
        (500, "server_error"),
        (RateLimited(999), "rate_limited"),
        (KeyRefused(403), "key_refused"),
        (httpx.ReadTimeout("secret URL"), "timeout"),
        (httpx.ConnectError("secret URL"), "network_error"),
    ],
)
def test_errors_are_unknown_and_never_disclose_exception_details(tmp_path, response, reason):
    item = torrent(1)
    indexer = Indexer({item.hash: [response]})
    service = TorrentAudit(tmp_path, lambda _: ("Client", [item]), lambda: indexer)
    report = finish(service, service.start(["a"])["id"])
    assert report["rows"][0]["classification"] == "unknown"
    assert report["rows"][0]["reason"] == reason
    assert "secret" not in json.dumps(report)


def test_stop_keeps_single_404_suspect_and_no_second_lookup(tmp_path):
    item = torrent(1)
    indexer = Indexer({item.hash: [404, 404]})
    service = TorrentAudit(tmp_path, lambda _: ("Client", [item]), lambda: indexer)
    identifier = service.start(["a"])["id"]
    for _ in range(100):
        if indexer.calls:
            break
        time.sleep(0.01)
    service.stop(identifier)
    result = finish(service, identifier)
    assert result["counts"]["suspect"] == 1
    assert result["status"] == "stopped"
    assert len(indexer.calls) == 1


def test_stop_before_lookup_and_report_pagination(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def collect(_):
        entered.set()
        release.wait(3)
        return "Client", [torrent(i) for i in range(250)]

    service = TorrentAudit(tmp_path, collect, lambda: Indexer({}))
    identifier = service.start(["a"])["id"]
    assert entered.wait(3)
    service.stop(identifier)
    release.set()
    result = finish(service, identifier)
    assert result["counts"]["unknown"] == 250
    assert result["rows"][0]["reason"] == "stopped_before_checking"
    assert len(service.read(identifier, 200)["rows"]) == 50
    assert len(json.loads(service.export(identifier)["content"])["rows"]) == 250
    with pytest.raises(ValueError):
        service.read("../elsewhere")


@pytest.mark.parametrize("second,state", [(200, "present"), (429, "unknown"), (500, "unknown")])
def test_second_lookup_can_disprove_or_leave_deletion_unknown(tmp_path, second, state):
    item = torrent(1)
    indexer = Indexer({item.hash: [404, second]})
    service = TorrentAudit(tmp_path, lambda _: ("Client", [item]), lambda: indexer, confirm_after=0)
    report = finish(service, service.start(["a"])["id"])
    assert report["rows"][0]["classification"] == state
    assert report["counts"]["deleted"] == 0


def test_large_audit_persists_in_batches_and_csv_escapes_formula_names(tmp_path, monkeypatch):
    from dataclasses import replace

    rows = [torrent(i) for i in range(10000)]
    rows[0] = replace(rows[0], name="=HYPERLINK(secret)")
    indexer = Indexer({row.hash: [200] for row in rows})
    writes = []
    original = Path.write_text

    def write(path, *args, **kwargs):
        writes.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    service = TorrentAudit(tmp_path, lambda _: ("Client", rows), lambda: indexer)
    report = finish(service, service.start(["a"])["id"])
    assert report["total"] == 10000 and len(indexer.calls) == 10000
    assert len(writes) <= 3
    assert "'=HYPERLINK(secret)" in service.export(report["id"], "csv")["content"]


def test_web_and_mcp_read_the_same_persistent_report_without_permissions(tmp_path):
    from fastapi.testclient import TestClient

    from tests.test_agent_media import invoke
    from tests.test_web_jobs import login
    from tests.test_web_plan_execution import prepared
    from torrentlinker.web.app import create_app

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    service = app.state.agent_service.torrents_workspace
    item = torrent(1)
    service.audit.collect = lambda _: ("Client", [item])
    service.audit.indexer = lambda: Indexer({item.hash: [200]})
    with TestClient(app) as browser:
        url = "/api/torrents/workspace"
        assert browser.post(url, json={"action": "audit-list"}).status_code == 403
        browser.headers["X-TorrentLinker"] = "1"
        assert browser.post(url, json={"action": "audit-list"}).status_code == 401
        login(browser)
        result = invoke(
            app, "read-only-test", "audit_torrents", action="start", client_ids=["default"]
        )
        report = finish(service.audit, result["id"])
        web = browser.post(
            url, json={"action": "audit-report", "body": {"id": report["id"]}}
        ).json()
        mcp = invoke(
            app, "read-only-test", "audit_torrents", action="report", report_id=report["id"]
        )
        assert web == mcp == service.request("audit-report", {"id": report["id"]})
        assert "private-passkey" not in json.dumps(mcp)
        assert (
            browser.post(
                url, json={"action": "audit-start", "body": {"client_ids": ["missing"]}}
            ).status_code
            == 400
        )


def test_stop_interrupts_real_indexer_hourly_budget_wait_without_request(tmp_path):
    from torrentlinker.indexer import Indexer as RealIndexer

    requests = []
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: requests.append(r) or httpx.Response(200, json={}))
    )
    indexer = RealIndexer("https://c411.org", "secret", http=http)
    indexer.api.budget = 1
    indexer.api.wait_turn()
    item = torrent(1)
    entered = threading.Event()

    def collect(_):
        entered.set()
        return "Client", [item]

    service = TorrentAudit(tmp_path, collect, lambda: indexer)
    identifier = service.start(["a"])["id"]
    assert entered.wait(1)
    time.sleep(0.05)
    started = time.monotonic()
    service.stop(identifier)
    report = finish(service, identifier)
    assert time.monotonic() - started < 1
    assert not requests
    assert report["status"] == "stopped"
    assert report["rows"][0]["reason"] == "stopped_before_checking"
    http.close()


def test_failed_report_save_does_not_leave_a_phantom_running_audit(tmp_path, monkeypatch):
    service = TorrentAudit(tmp_path, lambda _: ("Client", []), lambda: Indexer({}))
    original = Path.write_text

    def fail(*args, **kwargs):
        raise OSError("private storage details")

    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(ValueError, match="could not be saved"):
        service.start(["a"])
    assert not service.running
    monkeypatch.setattr(Path, "write_text", original)
    assert finish(service, service.start(["a"])["id"])["status"] == "complete"


def test_interrupted_report_has_the_same_reasons_in_exports(tmp_path):
    identifier = "a" * 32
    payload = {
        "id": identifier,
        "status": "running",
        "created_at": 1,
        "rows": [
            {
                "client_id": "a",
                "client_name": "A",
                "name": "File",
                "hash": "b" * 40,
                "tags": [],
                "hosts": ["c411.org"],
                "checked_at": None,
                "classification": "unknown",
                "reason": "not_checked",
            }
        ],
    }
    (tmp_path / (identifier + ".json")).write_text(json.dumps(payload))
    service = TorrentAudit(tmp_path, None, None)
    report = service.read(identifier)
    exported = json.loads(service.export(identifier)["content"])
    assert exported["rows"] == report["rows"]
    assert "interrupted" in service.export(identifier, "csv")["content"]


def test_desktop_export_uses_the_same_report_and_owner_chosen_file(tmp_path, qtbot, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QFileDialog

    from torrentlinker.gui.torrents_view import TorrentBridge

    item = torrent(1)
    audit = TorrentAudit(
        tmp_path / "reports", lambda _: ("Client", [item]), lambda: Indexer({item.hash: [200]})
    )
    report = finish(audit, audit.start(["a"])["id"])
    board = SimpleNamespace(target_client="default", service=lambda: SimpleNamespace(audit=audit))
    bridge = TorrentBridge(board)
    responses = []
    bridge.response.connect(lambda _, payload: responses.append(json.loads(payload)))
    chosen = tmp_path / "export.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(chosen), ""))
    payload = json.dumps({"_client": "default", "id": report["id"], "format": "json"})
    bridge.requestAsync(1, "audit-save-export", payload)
    assert responses[-1] == {"data": {"saved": True}}
    assert json.loads(chosen.read_text())["rows"] == report["rows"]
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    bridge.requestAsync(2, "audit-save-export", payload)
    assert responses[-1] == {"data": {"saved": False}}


def test_final_save_failure_keeps_a_readable_failure_and_releases_running_state(
    tmp_path, monkeypatch
):
    entered, release = threading.Event(), threading.Event()

    def collect(_):
        entered.set()
        release.wait(3)
        return "Client", []

    service = TorrentAudit(tmp_path, collect, lambda: Indexer({}))
    identifier = service.start(["a"])["id"]
    assert entered.wait(1)

    def fail(*args, **kwargs):
        raise OSError("private details")

    monkeypatch.setattr(Path, "write_text", fail)
    release.set()
    report = finish(service, identifier)
    assert report["status"] == "failed"
    assert {"reason": "report_not_saved"} in report["errors"]
    assert not service.running
    assert "private details" not in json.dumps(report)


def test_cancelled_confirmation_keeps_the_first_404_suspect(tmp_path):
    from torrentlinker.indexer import Indexer as RealIndexer

    requests = []
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: requests.append(r) or httpx.Response(404))
    )
    indexer = RealIndexer("https://c411.org", "secret", http=http)
    indexer.api.budget = 1
    item = torrent(1)
    service = TorrentAudit(tmp_path, lambda _: ("Client", [item]), lambda: indexer, confirm_after=0)
    identifier = service.start(["a"])["id"]
    for _ in range(100):
        if requests:
            break
        time.sleep(0.01)
    time.sleep(0.05)
    service.stop(identifier)
    report = finish(service, identifier)
    assert len(requests) == 1
    assert report["rows"][0]["classification"] == "suspect"
    assert report["rows"][0]["reason"] == "single_404"
    http.close()
