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


def test_preparation_tools_inspect_manual_models_and_refuse_other_paths(tmp_path):
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
        ).json()
        result = browser.post(
            "/api/upload/workspace/model-inspect",
            json={
                "path": str(source),
                "id": saved["id"],
            },
        )
        assert result.is_success, result.text
        assert result.json()["models"][0]["file"] == "Sculpture.stl"
        denied = browser.post(
            "/api/upload/workspace/model-inspect",
            json={
                "path": str(tmp_path / "other.stl"),
                "id": saved["id"],
            },
        )
        assert denied.status_code == 400


def test_upload_archive_tools_require_review_and_keep_source(tmp_path):
    import zipfile

    root = tmp_path / "media"
    root.mkdir()
    archive = root / "Sculpture.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("model.stl", "solid sculpture\nendsolid sculpture\n")
    app = create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    with TestClient(app) as browser:
        login(browser)
        saved = browser.post(
            "/api/upload/workspace/save",
            json={
                "path": str(archive),
                "form": {"manual_source": True, "category": 10},
            },
        ).json()
        body = {"path": str(archive), "id": saved["id"]}
        preview = browser.post("/api/upload/workspace/archive-preview", json=body)
        assert preview.is_success, preview.text
        denied = browser.post("/api/upload/workspace/archive-extract", json=body)
        assert denied.status_code == 400
        extracted = browser.post(
            "/api/upload/workspace/archive-extract",
            json={
                **body,
                **preview.json(),
            },
        )
        assert extracted.is_success, extracted.text
        assert archive.exists()
        assert (root / "Sculpture" / "model.stl").is_file()
        assert extracted.json()["draft"]["form"]["manual_source"]
        assert extracted.json()["draft"]["id"] != saved["id"]


def test_model_render_job_uses_selected_piece_and_returns_local_artwork(tmp_path):
    import time

    root = tmp_path / "media"
    root.mkdir()
    source = root / "Sculpture.obj"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n")
    app = create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    with TestClient(app) as browser:
        login(browser)
        saved = browser.post(
            "/api/upload/workspace/save",
            json={
                "path": str(source),
                "form": {"manual_source": True, "category": 10},
            },
        ).json()
        body = {"path": str(source), "id": saved["id"]}
        geometry = browser.post(
            "/api/upload/workspace/model-geometry",
            json={
                **body,
                "file": "Sculpture.obj",
            },
        )
        assert geometry.is_success, geometry.text
        assert len(geometry.json()["triangles"]) == 4
        job = browser.post(
            "/api/upload/workspace/tool-start",
            json={
                **body,
                "tool": "model-render",
                "files": ["Sculpture.obj"],
                "cameras": {"Sculpture.obj": {"yaw": 90, "pitch": 45}},
            },
        )
        assert job.is_success, job.text
        for _ in range(200):
            status = browser.post(
                "/api/upload/workspace/tool-status", json={"job": job.json()["id"]}
            ).json()
            if status["status"] not in {"queued", "running"}:
                break
            time.sleep(0.05)
        assert status["status"] == "completed", status
        assert status["result"]["covered"] == ["Sculpture.obj"]
        assert status["result"]["artifacts"][0]["asset_id"]
        assert status["result"]["content"][0]["mimeType"] == "image/png"
