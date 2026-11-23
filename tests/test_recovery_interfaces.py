"""Archive and repair dialogs use real services; only the external client is simulated."""

import hashlib
import os
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from tests.fake_qbit import FakeQbit
from tests.test_library_evidence import library_at, scan
from tests.torrents import make_torrent
from torrentlinker.indexer import Candidate
from torrentlinker.review import remember_candidates
from torrentlinker.torrent_meta import read_torrent


def repair_fixture(tmp_path):
    library, root = library_at(tmp_path)
    video = root / "Film.mkv"
    video.write_bytes(b"A" * 1024 * 1024)
    data = make_torrent(video)
    meta = read_torrent(data)
    video.write_bytes(b"B" * 128 + b"A" * (1024 * 1024 - 128))
    scan(library)
    client = FakeQbit()
    library.setup.connector = lambda *args: client
    library.setup.configured = True
    library.setup.secrets.update({"indexer-api-key": "test-key"})
    indexer = library.setup.indexer()
    candidate = Candidate(
        "Film",
        video.stat().st_size,
        "https://c411.org/download/film",
        seeders=2,
        infohash=meta.infohash,
    )
    remember_candidates(library.setup.store, indexer, video, [candidate])
    library.setup.store.cache_torrent(
        hashlib.sha1(indexer.redact(candidate.download_url).encode()).hexdigest(), data
    )
    copies = root / "copies"
    copies.mkdir()
    return library, client, video, copies, meta


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
@pytest.mark.parametrize("language", ["fr", "en"])
def test_shared_repair_opt_in_separate_confirmation_and_history(tmp_path, language):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.web.app import create_app
    from torrentlinker.web.operations import Operations

    library, client, video, copies, meta = repair_fixture(tmp_path)
    original = video.read_bytes(), video.stat().st_ino

    def operations(setup):
        result = Operations(setup)
        result.library.entries = library.entries
        return result

    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        service_override=library.setup,
        operation_factory=operations,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)

    def label(fr, en):
        return fr if language == "fr" else en

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/#/library/reseed")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                language
            )
            frame = page.frame_locator("#reseed-frame")
            frame.locator(".torrent").filter(has_text="Film.mkv").first.click()
            frame.get_by_role(
                "button",
                name=label("Diagnostiquer une réparation…", "Diagnose repair…"),
                exact=True,
            ).click()
            dialog = frame.locator("#recovery-dialog")
            prepare = dialog.get_by_role(
                "button",
                name=label("Préparer une copie indépendante", "Prepare an independent copy"),
                exact=True,
            )
            expect(prepare).to_be_disabled()
            dialog.locator("#repair-path").fill(str(copies))
            dialog.locator("#repair-opt").check()
            expect(prepare).to_be_enabled()
            prepare.click()
            refresh = dialog.get_by_role(
                "button",
                name=label("Actualiser la vérification", "Refresh verification"),
                exact=True,
            )
            expect(refresh).to_be_visible(timeout=15000)
            assert not client.started
            client.by_hash[meta.infohash] = replace(
                client.by_hash[meta.infohash], state="stoppedDL"
            )
            client.pieces[meta.infohash] = [0] + [2] * (
                video.stat().st_size // meta.piece_length - 1
            )
            refresh.click()
            confirm = dialog.get_by_role(
                "button",
                name=label("Confirmer le téléchargement…", "Confirm download…"),
                exact=True,
            )
            expect(confirm).to_be_visible()
            confirm.click()
            confirmation = frame.locator("#recovery-confirm")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                "en" if language == "fr" else "fr"
            )
            expect(confirmation).to_contain_text(
                "Download into this copy?" if language == "fr" else "Télécharger dans cette copie ?"
            )
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                language
            )

            confirmation.get_by_role("button", name=label("Annuler", "Cancel"), exact=True).click()
            assert not client.started
            page.reload()
            frame.locator(".torrent").filter(has_text="Film.mkv").first.click()
            frame.get_by_role(
                "button", name=label("Historique des réparations…", "Repair history…"), exact=True
            ).click()
            frame.locator(".recovery-history button").filter(has_text="Film.mkv").click()
            expect(confirm).to_be_visible()
            assert not client.started
            if output := os.getenv("TL_WEB_SCREENSHOTS"):
                Path(output).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(output) / f"repair-web-{language}.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            confirm.click()
            confirmation.get_by_role(
                "button", name=label("Confirmer le téléchargement", "Confirm download"), exact=True
            ).click()
            expect(dialog).to_contain_text(
                label("Téléchargement dans la copie", "Downloading into copy")
            )
            assert client.started == [meta.infohash]
            assert (video.read_bytes(), video.stat().st_ino) == original
            rows = library.repairs().rows()
            assert Path(rows[0]["copy"]).stat().st_ino != video.stat().st_ino
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)


def test_desktop_repair_dialog_uses_shared_flow_and_native_picker(qtbot, tmp_path, monkeypatch):
    import subprocess
    import sys

    if not os.getenv("TL_RECOVERY_NATIVE_CHILD"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"{__file__}::test_desktop_repair_dialog_uses_shared_flow_and_native_picker",
            ],
            env={
                **os.environ,
                "TL_RECOVERY_NATIVE_CHILD": "1",
                "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
                "QT_QUICK_BACKEND": "software",
            },
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PySide6.QtWidgets import QApplication, QFileDialog

    from tests.test_community_interfaces import js, wait_js
    from torrentlinker import clients
    from torrentlinker.credentials import set_secret
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.gui.theme import apply_theme

    root = tmp_path / "fixture"
    root.mkdir()
    library, client, video, copies, meta = repair_fixture(root)
    monkeypatch.setattr(clients, "connect", lambda *args: client)
    set_secret("indexer-api-key", "test-key")
    window = MainWindow(
        library.setup.settings, root / "config" / "settings.json", library.setup.store
    )
    qtbot.addWidget(window)
    window.library_model.set_entries(library.entries)
    view = window.library_workspace.reseed
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(copies))
    apply_theme(QApplication.instance(), "dark")
    view.language = "fr"
    view.refresh_rows()
    view.setParent(None)
    qtbot.addWidget(view)
    view.resize(1400, 1000)
    view.show()
    try:
        wait_js(qtbot, view, "document.querySelector('.torrent')!==null")
        js(qtbot, view, "document.querySelector('.torrent').click()")
        wait_js(
            qtbot,
            view,
            "document.querySelector('[data-review-action=repair]') && "
            "!document.querySelector('[data-review-action=repair]').disabled",
        )
        js(qtbot, view, "document.querySelector('[data-review-action=repair]').click()")
        wait_js(qtbot, view, "document.querySelector('#repair-prepare')!==null")
        assert js(qtbot, view, "document.querySelector('#repair-prepare').disabled")
        js(qtbot, view, "document.querySelector('[data-recovery=browse]').click()")
        wait_js(qtbot, view, "document.querySelector('#repair-path').value!==''")
        js(qtbot, view, "document.querySelector('#repair-opt').click()")
        wait_js(qtbot, view, "!document.querySelector('#repair-prepare').disabled")
        if output := os.getenv("TL_WEB_SCREENSHOTS"):
            Path(output).mkdir(parents=True, exist_ok=True)
            view.grab().save(str(Path(output) / "repair-desktop.png"))
        js(qtbot, view, "document.querySelector('#repair-prepare').click()")
        wait_js(qtbot, view, "document.querySelector('[data-recovery=refresh]')!==null")
        assert not client.started
        client.by_hash[meta.infohash] = replace(client.by_hash[meta.infohash], state="stoppedDL")
        client.pieces[meta.infohash] = [0] + [2] * (video.stat().st_size // meta.piece_length - 1)
        js(qtbot, view, "document.querySelector('[data-recovery=refresh]').click()")
        wait_js(qtbot, view, "document.querySelector('[data-recovery=confirm]')!==null")
        js(qtbot, view, "document.querySelector('[data-recovery=confirm]').click()")
        wait_js(qtbot, view, "document.querySelector('#recovery-confirm').open")
        js(qtbot, view, "document.querySelector('[data-recovery=cancel-confirm]').click()")
        assert not client.started
    finally:
        view.close_recovery()


def test_repair_diagnosis_refuses_an_unsupported_client(tmp_path):
    from torrentlinker.domain import TorrentClient
    from torrentlinker.web.operations import JobRequest, Operations

    library, _, video, _, meta = repair_fixture(tmp_path)
    library.setup.settings.client = TorrentClient.TRANSMISSION
    operations = Operations(library.setup)
    operations.library.entries = library.entries
    with pytest.raises(ValueError, match="requires qBittorrent"):
        operations.run(
            JobRequest(kind="diagnose-repair", path=str(video), candidate_key=meta.infohash),
            threading.Event(),
            lambda value: None,
        )
    assert library.repairs().rows() == []


def test_desktop_archive_consent_survives_separate_jobs(qtbot, tmp_path, monkeypatch):
    from tests.test_web_archives import archive_app
    from torrentlinker import clients
    from torrentlinker.credentials import set_secret
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.library import build_library
    from torrentlinker.matching import IgnoreList

    with archive_app(tmp_path) as (_, archive, _, candidate, client, setup):
        monkeypatch.setattr(clients, "connect", lambda *args: client)
        set_secret("indexer-api-key", "test-key")
        window = MainWindow(setup.settings, tmp_path / "config" / "settings.json", setup.store)
        qtbot.addWidget(window)
        window.library_model.set_entries(
            build_library(setup.settings.library_folders, [], IgnoreList.default())
        )
        view = window.library_workspace.reseed

        def job(body):
            identifier = view.request("recovery-start", body)["id"]
            qtbot.waitUntil(
                lambda: (
                    view.request("recovery-job", {"id": identifier})["status"]
                    not in {"queued", "running"}
                ),
                timeout=10000,
            )
            result = view.request("recovery-job", {"id": identifier})
            assert result["status"] == "completed", result
            return result["result"]

        try:
            body = {"path": str(archive), "candidate_key": candidate.infohash}
            preview = job({"kind": "preview-unpack", **body})
            assert not client.by_hash
            result = job({"kind": "unpack-reseed", **body, "confirmation": preview["token"]})
            assert result["status"] == "verifying"
            assert archive.is_file()
            assert Path(result["path"]).is_dir()
            assert any(
                row.get("kind") == "unpack-reseed" and row["status"] == "completed"
                for row in view.request("state", {})["activity"]
            )
            assert not client.started
        finally:
            view.close_recovery()
