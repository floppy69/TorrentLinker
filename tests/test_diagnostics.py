"""Support exports contain bounded metadata, never user content or credentials."""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_web_jobs import login
from torrentlinker.config import ClientProfile, Settings
from torrentlinker.diagnostics import build_report, report_json
from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping, TorrentClient
from torrentlinker.store import Store
from torrentlinker.web.app import create_app
from torrentlinker.web.jobs import Jobs

PRIVATE = "PRIVATE-SUPPORT-SENTINEL"


def test_report_excludes_private_fields_and_preserves_running_state(tmp_path, monkeypatch):
    settings = Settings(client=TorrentClient.TRANSMISSION)
    settings.transmission.host = f"https://{PRIVATE}:{PRIVATE}@{PRIVATE}.invalid/rpc?key={PRIVATE}"
    settings.transmission.username = PRIVATE
    settings.indexer.url = f"https://{PRIVATE}.invalid/{PRIVATE}"
    settings.proxy.address = f"socks5://{PRIVATE}:{PRIVATE}@{PRIVATE}.invalid"
    settings.proxy.username = PRIVATE
    settings.library_folders = [LibraryFolder(Path(f"/{PRIVATE}"), kind=ContentKind.MOVIE)]
    settings.path_mappings = [PathMapping(f"Y:/{PRIVATE}", f"/downloads/{PRIVATE}")]
    settings.download_folders.default = f"Y:/{PRIVATE}"
    settings.download_folders.by_category = {2030: f"Y:/{PRIVATE}"}
    settings.ensure_profiles()
    settings.client_profiles[0].name = PRIVATE
    settings.client_profiles.append(ClientProfile(PRIVATE, PRIVATE, enabled=False))
    original = copy.deepcopy(settings)
    store = Store(tmp_path / "state.sqlite")
    jobs = Jobs(tmp_path)
    try:
        with store._db:
            store._db.executemany(
                "INSERT INTO download_queue (id,payload,status,reason,added_at) VALUES (?,?,?,?,?)",
                [("a", PRIVATE, "sending", PRIVATE, 0), ("b", PRIVATE, PRIVATE, PRIVATE, 0)],
            )
        with jobs.db:
            jobs.db.executemany(
                "INSERT INTO jobs (id,kind,status,created,progress,result,error,client_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        str(i),
                        "scan" if i else PRIVATE,
                        "running" if i else PRIVATE,
                        i,
                        PRIVATE,
                        PRIVATE,
                        PRIVATE,
                        PRIVATE,
                    )
                    for i in range(25)
                ],
            )
        # Export must not look up credentials or contact either service.
        monkeypatch.setattr("keyring.get_password", lambda *a: pytest.fail("secret lookup"))
        report = build_report(settings, store, jobs)
        encoded = report_json(report)
        assert PRIVATE not in encoded
        assert report["schema_version"] == 1
        assert report["clients"][0]["type"] == "transmission"
        assert report["clients"][0]["connection"] == {"scheme": "https", "scope": "remote"}
        assert report["clients"][0]["path_mappings"] == {"windows-absolute -> posix-absolute": 1}
        assert report["clients"][0]["download_folders"] == {
            "default": "windows-absolute",
            "category_overrides": 1,
        }
        assert report["library_folders"] == {"movie": 1}
        assert report["state"]["download_queue"] == {"sending": 1, "other": 1}
        assert len(report["recent_jobs"]) == 20
        assert report["recent_jobs"][0] == {
            "kind": "scan",
            "status": "running",
            "client": "client-2",
        }
        assert settings == original
        assert (
            jobs.db.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0] == 24
        )
        assert (
            store._db.execute("SELECT status FROM download_queue WHERE id='a'").fetchone()[0]
            == "sending"
        )
        # Unknown values are folded into a fixed label, never copied out.
        with jobs.db:
            jobs.db.execute("DELETE FROM jobs WHERE kind='scan'")
        assert build_report(settings, store, jobs)["recent_jobs"] == [
            {"kind": "other", "status": "other", "client": "client-2"}
        ]
    finally:
        jobs.close()
        store._db.close()


def test_report_works_without_job_server_and_does_not_create_profiles(tmp_path):
    settings = Settings()
    store = Store(tmp_path / "state.sqlite")
    try:
        report = build_report(settings, store)
        assert report["recent_jobs"] is None
        assert settings.client_profiles == []
        assert report["clients"][0]["connection"]["scope"] == "local"
    finally:
        store._db.close()


def test_authenticated_report_download_under_mount_prefix(tmp_path):
    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    with TestClient(app, root_path="/tl") as browser:
        assert browser.get("/tl/api/diagnostics").status_code == 401
        login(browser)
        before = app.state.agent_service.jobs.list()
        response = browser.get("/tl/api/diagnostics")
        assert response.status_code == 200
        assert response.headers["content-disposition"] == (
            'attachment; filename="torrentlinker-diagnostics.json"'
        )
        assert "no-store" in response.headers["cache-control"]
        assert json.loads(response.content)["schema_version"] == 1
        assert app.state.agent_service.jobs.list() == before


@pytest.mark.parametrize("action", ["cancel", "save", "unwritable"])
def test_desktop_export_respects_file_choice(qtbot, tmp_path, monkeypatch, action):
    from PySide6.QtWidgets import QWidget

    from torrentlinker.gui.diagnostics import export_report

    parent = QWidget()
    qtbot.addWidget(parent)
    chosen = tmp_path / "report.json"
    if action == "unwritable":
        chosen = tmp_path / "missing" / "report.json"
    monkeypatch.setattr(
        "torrentlinker.gui.diagnostics.QFileDialog.getSaveFileName",
        lambda *a: ("" if action == "cancel" else str(chosen), ""),
    )
    warnings = []
    monkeypatch.setattr(
        "torrentlinker.gui.diagnostics.QMessageBox.warning", lambda *a: warnings.append(a)
    )
    calls = []

    def report():
        calls.append(True)
        return {"schema_version": 1}

    export_report(parent, report)
    assert bool(calls) == (action != "cancel")
    assert bool(warnings) == (action == "unwritable")
    if action == "save":
        assert json.loads(chosen.read_text()) == {"schema_version": 1}
    else:
        assert not chosen.exists()


def test_settings_export_button_is_translated_and_emits_request(qtbot, tmp_path):
    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js

    dialog = settings_page(qtbot, tmp_path, Settings(language="fr"), section="general")
    with qtbot.waitSignal(dialog.view.diagnostics_requested):
        js(
            qtbot,
            dialog.view,
            "[...document.querySelectorAll('button')].find(b=>b.textCon"
            "tent==='Exporter le diagnostic…').click()",
        )
    assert dialog.parent().exports == [dialog]
