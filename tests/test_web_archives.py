"""Archive extraction through authenticated Library jobs and real archive files."""

import hashlib
from contextlib import contextmanager

from fastapi.testclient import TestClient

from tests.fake_qbit import FakeQbit
from tests.test_archives import release, zipped
from tests.test_web_jobs import finished, login
from tests.torrents import make_torrent
from torrentlinker.indexer import Candidate
from torrentlinker.review import remember_candidates
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.web.app import create_app
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup


@contextmanager
def archive_app(tmp_path, *, suffix=".zip", client=None):
    source = release(tmp_path / "source" / "Kaneda")
    root, config = tmp_path / "Library", tmp_path / "config"
    root.mkdir()
    config.mkdir()
    archive = zipped(source, root / ("Kaneda" + suffix))
    client = client or FakeQbit()
    setup = Setup(config, (root,), ServerSecrets(config), lambda *args: client)
    setup.secrets.update({"indexer-api-key": "test-key"})
    setup.configured = True
    data = make_torrent(source)
    meta = read_torrent(data)
    candidate = Candidate(
        "Kaneda",
        sum(meta.files.values()),
        "https://c411.org/download/model",
        infohash=meta.infohash,
    )
    indexer = setup.indexer()
    remember_candidates(setup.store, indexer, archive, [candidate])
    setup.store.cache_torrent(
        hashlib.sha1(indexer.redact(candidate.download_url).encode()).hexdigest(), data
    )
    app = create_app(config, password="test-password-long", service_override=setup)
    with TestClient(app) as browser:
        login(browser)
        assert (
            browser.post(
                "/api/setup/folder", json={"local": str(root), "kind": "3d-model"}
            ).status_code
            == 200
        )
        run_job(browser, {"kind": "scan"})
        yield browser, archive, source, candidate, client, setup


def run_job(browser, body, status="completed"):
    response = browser.post("/api/jobs", json=body)
    assert response.status_code == 202, response.text
    result = finished(browser, response.json()["id"])
    assert result["status"] == status, result
    return result


def test_review_then_unpack_reseeds_verified_files_and_keeps_archive(tmp_path):
    with archive_app(tmp_path) as (browser, archive, source, candidate, client, _):
        request = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **request})["result"]
        assert preview["destination"] == str(archive.parent / "Kaneda")
        assert preview["size"] == 155800
        assert preview["files"] == 3
        assert preview["free"] >= preview["size"]
        assert preview["match"] == "full"
        assert not (archive.parent / "Kaneda").exists()
        assert not client.by_hash
        result = run_job(
            browser, {"kind": "unpack-reseed", **request, "confirmation": preview["token"]}
        )
        assert result["result"]["status"] == "verifying"
        assert result["progress"]["done"] == 155800
        assert (archive.parent / "Kaneda" / "STL" / "head.stl").read_bytes() == (
            source / "STL" / "head.stl"
        ).read_bytes()
        assert archive.is_file()
        assert client.rechecked == [candidate.infohash]
        assert client.started == []
        assert client.downloads == []


def test_cancelling_extraction_stops_the_tool_and_removes_only_its_partial_folder(
    tmp_path, monkeypatch
):
    import os
    import signal
    import sys
    import time

    import pytest

    tools = tmp_path / "tools"
    tools.mkdir()
    executable = tools / "7z"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time, zipfile\n"
        "from pathlib import Path\n"
        "archive=Path(sys.argv[-1])\n"
        "with zipfile.ZipFile(archive) as z:\n"
        " if sys.argv[1]=='l':\n"
        "  for i in z.infolist(): print(f'Path = {i.filename}\\nSize = {i.file_size}\\n')\n"
        " else:\n"
        "  into=Path(next(a[2:] for a in sys.argv if a.startswith('-o')))\n"
        "  archive.with_suffix('.pid').write_text(str(os.getpid()))\n"
        "  z.extract(z.namelist()[0], into)\n"
        "  time.sleep(20)\n"
        "  z.extractall(into)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    with archive_app(tmp_path, suffix=".7z") as (browser, archive, _, candidate, client, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        untouched = archive.parent / "keep.txt"
        untouched.write_text("keep")
        response = browser.post(
            "/api/jobs", json={"kind": "unpack-reseed", **body, "confirmation": preview["token"]}
        )
        identifier = response.json()["id"]
        pid = None
        try:
            for _ in range(200):
                current = browser.get(f"/api/jobs/{identifier}").json()
                if (current.get("progress") or {}).get("done", 0):
                    break
                time.sleep(0.01)
            assert current["progress"]["done"] > 0
            pid = int(archive.with_suffix(".pid").read_text())
            assert browser.post(f"/api/jobs/{identifier}/cancel").status_code == 200
            result = finished(browser, identifier)
            assert result["status"] == "cancelled", result
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            assert not (archive.parent / "Kaneda").exists()
            assert archive.is_file()
            assert untouched.read_text() == "keep"
            assert not client.by_hash
        finally:
            if pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_confirmation_is_required_and_cannot_be_reused_or_transferred(tmp_path):
    with archive_app(tmp_path) as (browser, archive, _, candidate, client, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        run_job(browser, {"kind": "unpack-reseed", **body}, "failed")
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        run_job(
            browser,
            {
                "kind": "unpack-reseed",
                **body,
                "candidate_key": "b" * 40,
                "confirmation": preview["token"],
            },
            "failed",
        )
        run_job(
            browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]}, "failed"
        )
        assert not (archive.parent / "Kaneda").exists()
        assert not client.by_hash


def test_changed_archive_needs_a_fresh_confirmation(tmp_path):
    import zipfile

    with archive_app(tmp_path) as (browser, archive, _, candidate, client, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr("Kaneda/extra.txt", "new content")
        result = run_job(
            browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]}, "failed"
        )
        assert "changed" in result["error"]
        assert not (archive.parent / "Kaneda").exists()
        assert not client.by_hash


def test_destination_created_after_review_is_preserved(tmp_path):
    with archive_app(tmp_path) as (browser, archive, _, candidate, client, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        target = archive.parent / "Kaneda"
        target.mkdir()
        existing = target / "keep.txt"
        existing.write_text("original")
        result = run_job(
            browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]}, "failed"
        )
        assert "already exists" in result["error"]
        assert existing.read_text() == "original"
        assert list(target.iterdir()) == [existing]
        assert not client.by_hash


def test_free_space_is_rechecked_after_confirmation(tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace

    with archive_app(tmp_path) as (browser, archive, _, candidate, client, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=100))
        result = run_job(
            browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]}, "failed"
        )
        assert "Not enough free space" in result["error"]
        assert not (archive.parent / "Kaneda").exists()
        assert not client.by_hash


def test_rejecting_candidate_invalidates_archive_confirmation(tmp_path):
    with archive_app(tmp_path) as (browser, archive, _, candidate, client, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        run_job(browser, {"kind": "library-reject", **body})
        run_job(
            browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]}, "failed"
        )
        assert not (archive.parent / "Kaneda").exists()
        assert not client.by_hash


def test_partial_archive_reseed_does_not_download_missing_files(tmp_path):
    import zipfile

    with archive_app(tmp_path) as (browser, archive, source, candidate, client, _):
        with zipfile.ZipFile(archive, "w") as z:
            for name in ("head.stl", "body.stl"):
                z.write(source / "STL" / name, f"Kaneda/STL/{name}")
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        assert preview["match"] == "partial"
        assert preview["missing"] == 1
        run_job(browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]})
        assert len(client.priorities[candidate.infohash]) == 1
        assert set(client.priorities[candidate.infohash].values()) == {0}
        assert not client.started
        assert not client.downloads
        assert archive.is_file()


def test_an_archive_replaced_by_an_outside_root_link_cannot_be_extracted(tmp_path):
    with archive_app(tmp_path) as (browser, archive, _, candidate, client, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        outside = tmp_path / "outside.zip"
        archive.rename(outside)
        archive.symlink_to(outside)
        result = run_job(
            browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]}, "failed"
        )
        assert "outside" in result["error"]
        assert not (archive.parent / "Kaneda").exists()
        assert not client.by_hash


def test_expired_archive_confirmation_requires_review_again(tmp_path, monkeypatch):
    import time

    with archive_app(tmp_path) as (browser, archive, _, candidate, client, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        clock = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: clock() + 301)
        run_job(
            browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]}, "failed"
        )
        assert not (archive.parent / "Kaneda").exists()
        assert not client.by_hash


def test_real_7z_extraction_uses_the_same_verified_reseed(tmp_path):
    import shutil
    import subprocess

    import pytest

    tool = shutil.which("7z")
    if not tool:
        pytest.skip("7-Zip is not installed")
    with archive_app(tmp_path, suffix=".7z") as (browser, archive, source, candidate, client, _):
        archive.unlink()
        subprocess.run(
            [tool, "a", "-t7z", str(archive), source.name],
            cwd=source.parent,
            check=True,
            capture_output=True,
        )
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        run_job(browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]})
        assert (archive.parent / "Kaneda" / "STL" / "body.stl").read_bytes() == (
            source / "STL" / "body.stl"
        ).read_bytes()
        assert client.rechecked == [candidate.infohash]
        assert archive.is_file()


def test_archive_with_symbolic_links_cannot_be_approved(tmp_path):
    import shutil
    import subprocess

    import pytest

    tool = shutil.which("7z")
    if not tool:
        pytest.skip("7-Zip is not installed")
    with archive_app(tmp_path, suffix=".7z") as (browser, archive, source, candidate, client, _):
        outside = tmp_path / "private.txt"
        outside.write_text("must stay outside the Library")
        (source / "link.txt").symlink_to(outside)
        archive.unlink()
        subprocess.run(
            [tool, "a", "-snl", str(archive), source.name],
            cwd=source.parent,
            check=True,
            capture_output=True,
        )
        run_job(
            browser,
            {"kind": "preview-unpack", "path": str(archive), "candidate_key": candidate.infohash},
            "failed",
        )
        assert not (archive.parent / "Kaneda").exists()
        assert outside.read_text() == "must stay outside the Library"
        assert not client.by_hash


def test_client_submission_cannot_be_reported_as_cancelled(tmp_path):
    import threading

    class SlowClient(FakeQbit):
        def __init__(self):
            super().__init__()
            self.adding = threading.Event()
            self.release = threading.Event()

        def add(self, data, save_path, tags):
            self.adding.set()
            assert self.release.wait(10)
            return super().add(data, save_path, tags)

    client = SlowClient()
    with archive_app(tmp_path, client=client) as (browser, archive, _, candidate, _, _):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        response = browser.post(
            "/api/jobs", json={"kind": "unpack-reseed", **body, "confirmation": preview["token"]}
        )
        identifier = response.json()["id"]
        try:
            assert client.adding.wait(5)
            cancelled = browser.post(f"/api/jobs/{identifier}/cancel")
            assert cancelled.status_code == 400
            assert "cannot be cancelled" in cancelled.json()["detail"]
        finally:
            client.release.set()
        result = finished(browser, identifier)
        assert result["status"] == "completed", result
        assert result["result"]["status"] == "verifying"
        assert client.rechecked == [candidate.infohash]


def test_archive_status_follows_real_verification_without_starting_it(tmp_path):
    from dataclasses import replace

    from torrentlinker.reseed import check_verifications

    with archive_app(tmp_path) as (browser, archive, _, candidate, client, setup):
        body = {"path": str(archive), "candidate_key": candidate.infohash}
        preview = run_job(browser, {"kind": "preview-unpack", **body})["result"]
        run_job(browser, {"kind": "unpack-reseed", **body, "confirmation": preview["token"]})
        status = {"kind": "refresh-unpack", "hashes": [candidate.infohash]}
        assert run_job(browser, status)["result"]["status"] == "verifying"
        assert not client.started
        client.by_hash[candidate.infohash] = replace(
            client.by_hash[candidate.infohash], state="stoppedUP", progress=1
        )
        check_verifications(client, setup.store)
        assert run_job(browser, status)["result"]["status"] == "seeding"
        assert client.started == [candidate.infohash]
