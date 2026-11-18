"""Guided upload sources use mounted storage and persistent Local Drafts."""

import threading

import pytest
from fastapi.testclient import TestClient

from tests.test_web_jobs import login
from torrentlinker.web.app import create_app
from torrentlinker.web.uploads import UploadForm


def test_manual_source_can_be_saved_and_reopened_without_registering_library(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "Sculpture.stl"
    source.write_text("solid sculpture\nendsolid sculpture\n")
    app = create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    with TestClient(app) as browser:
        login(browser)
        uploads = app.state.agent_service.for_client("").uploads
        draft = uploads.queue(
            str(source), UploadForm(manual_source=True, category=10), threading.Event()
        )
        assert draft["path"] == str(source)
        assert draft["status"] == "queued"
        reopened = uploads.queue(
            str(source),
            UploadForm(manual_source=True, category=10, title="Sculpture", workflow_step=3),
            threading.Event(),
            draft["id"],
            draft["revision"],
        )
        assert reopened["revision"] == 2
        assert uploads.setup.store.local_draft(reopened["id"])["form"]["workflow_step"] == 3
        assert [e["revision"] for e in reopened["history"]] == [1, 2]
        assert not uploads.setup.settings.library_folders
        outside = tmp_path / "private.stl"
        outside.write_text("solid private\nendsolid private\n")
        with pytest.raises(ValueError):
            uploads.queue(
                str(outside), UploadForm(manual_source=True, category=10), threading.Event()
            )


def test_guided_workspace_lists_saved_manual_sources_and_reads_only_mounted_files(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "Sculpture.stl"
    source.write_text("solid sculpture\nendsolid sculpture\n")
    app = create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    with TestClient(app) as browser:
        login(browser)
        saved = browser.post(
            "/api/upload/workspace/save",
            json={
                "path": str(source),
                "form": {"manual_source": True, "category": 10},
            },
        )
        assert saved.is_success, saved.text
        state = browser.post("/api/upload/workspace/state", json={}).json()
        assert state["drafts"][0]["path"] == str(source)
        listing = browser.post("/api/upload/workspace/browse", json={"path": str(root)}).json()
        assert listing["files"] == [str(source)]
        blocked = browser.post("/api/upload/workspace/browse", json={"path": str(tmp_path)})
        assert blocked.status_code == 400


def test_source_suggestions_distinguish_incompatible_candidates_from_compatible(tmp_path):
    from torrentlinker.domain import ContentKind, ItemState, LibraryFolder
    from torrentlinker.library import LibraryEntry
    from torrentlinker.scan import scan_item
    from torrentlinker.upload_workspace import UploadWorkspace

    root = tmp_path / "media"
    root.mkdir()
    app = create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    with TestClient(app) as browser:
        login(browser)
        uploads = app.state.agent_service.for_client("").uploads
        for name, matches in [("wrong", ["none"]), ("same", ["full"]), ("pending", ["unchecked"])]:
            source = root / (name + ".stl")
            source.write_text("solid sculpture\nendsolid sculpture\n")
            uploads.library.entries.append(
                LibraryEntry(
                    LibraryFolder(root, 1, ContentKind.MODEL_3D),
                    scan_item(source),
                    ItemState.ORPHAN,
                )
            )
            uploads.setup.store.save_reseed_record(
                str(source),
                {
                    "stage": "candidates",
                    "candidates": [{"match": m} for m in matches],
                },
            )
        rows = UploadWorkspace(uploads).state()["sources"]
        assert {r["name"]: r["reason"] for r in rows} == {
            "wrong.stl": "rejected",
            "pending.stl": "unchecked",
        }


def test_native_specialised_editor_reopens_manual_source_and_preserves_workflow(qtbot, tmp_path):
    from tests.fake_qbit import FakeQbit
    from tests.test_upload_view import StubIndexer
    from torrentlinker.gui.upload_view import UploadTab
    from torrentlinker.matching import IgnoreList

    root = tmp_path / "media"
    root.mkdir()
    source = root / "Sculpture.stl"
    source.write_text("solid sculpture\nendsolid sculpture\n")
    app = create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    with TestClient(app) as browser:
        login(browser)
        uploads = app.state.agent_service.for_client("").uploads
        record = uploads.queue(
            str(source),
            UploadForm(
                manual_source=True,
                category=10,
                workflow_step=3,
                existing_reviewed=True,
            ),
            threading.Event(),
        )
        indexer = StubIndexer()
        view = UploadTab(
            uploads.setup.store,
            lambda: indexer,
            lambda: FakeQbit(),
            IgnoreList.default,
            lambda: "",
            tmp_path / "uploads",
        )
        qtbot.addWidget(view)
        view.edit_saved_details(record)
        qtbot.waitUntil(lambda: bool(view.files))
        assert view.entry.item.path == source
        view.description.setPlainText("Présentation corrigée dans les outils avancés.")
        view.queue_draft()
        qtbot.waitUntil(lambda: uploads.setup.store.local_draft(record["id"])["revision"] == 2)
        form = uploads.setup.store.local_draft(record["id"])["form"]
        assert form["manual_source"]
        assert form["workflow_step"] == 3
        assert form["existing_reviewed"]
