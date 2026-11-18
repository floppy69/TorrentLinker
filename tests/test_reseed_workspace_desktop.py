from PySide6.QtWidgets import QMessageBox

from tests.test_library_folders import window_for
from tests.test_reseed_workspace import workspace


def test_native_board_runs_the_shared_workflow(qtbot, tmp_path, monkeypatch):
    root = tmp_path / "fixture"
    root.mkdir()
    service, client, original, links, meta = workspace(root)
    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    board = window.library_workspace.reseed
    monkeypatch.setattr(board, "service", lambda: service)
    monkeypatch.setattr(window, "indexer", service.setup.indexer)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.tabs.setCurrentIndex(1)
    window.library_workspace.sections.setCurrentWidget(board)
    window.settings.profile().reseed_link_root = str(links)
    window._fill_folder_filter()
    board.refresh_rows()
    window.resize(1400, 1000)
    window.show()
    from PySide6.QtWidgets import QLineEdit

    assert board.findChild(QLineEdit, "reseedLinkRoot") is None
    assert board.link_root == str(links)
    assert len(board.rows) == 1 and board.rows[0]["stage"] == "find"
    before = original.read_bytes(), original.stat().st_ino
    board.request("run", {"paths": [str(original)]})
    qtbot.waitUntil(lambda: not board.running, timeout=10000)
    assert board.rows[0]["stage"] == "seeding", board.error
    assert client.started == [meta.infohash]
    assert (original.read_bytes(), original.stat().st_ino) == before
    assert board.request("state", {})["running"] is False
    import os
    from pathlib import Path

    if output := os.getenv("TL_WEB_SCREENSHOTS"):
        Path(output).mkdir(parents=True, exist_ok=True)
        window.grab().save(str(Path(output) / "reseed-desktop.png"))


def test_link_folder_is_edited_in_client_settings_without_leaking_between_clients(
    qtbot, monkeypatch
):
    from torrentlinker.config import Settings
    from torrentlinker.gui.settings_dialog import SettingsDialog

    settings = Settings()
    original = settings.active_client_id
    other = settings.add_client("NAS")
    settings.select_client(other.id)
    monkeypatch.setattr(SettingsDialog, "_save_secrets", lambda self: None)
    dialog = SettingsDialog(settings, secret_values={})
    qtbot.addWidget(dialog)
    dialog.reseed_link_root.setText("/media/nas-links")
    dialog._save()
    assert settings.profile().reseed_link_root == "/media/nas-links"
    settings.select_client(original)
    assert settings.profile().reseed_link_root == ""
    cancelled = SettingsDialog(settings, secret_values={})
    qtbot.addWidget(cancelled)
    cancelled.reseed_link_root.setText("/do-not-save")
    cancelled.reject()
    assert settings.profile().reseed_link_root == ""


def test_shared_native_view_renders_and_browses_folders(qtbot, tmp_path, monkeypatch):
    import json
    import os
    import subprocess
    import sys

    if not os.getenv("TL_RESEED_NATIVE_CHILD"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"{__file__}::test_shared_native_view_renders_and_browses_folders",
            ],
            env={
                **os.environ,
                "TL_RESEED_NATIVE_CHILD": "1",
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

    window, scans = window_for(qtbot, tmp_path, monkeypatch)
    from torrentlinker.gui.theme import apply_theme

    apply_theme(QApplication.instance(), "dark")
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    service, _, _, _, _ = workspace(fixture)
    view = window.library_workspace.reseed
    view.language = "fr"
    monkeypatch.setattr(view, "service", lambda: service)
    view.refresh_rows()
    view.setParent(None)
    qtbot.addWidget(view)
    view.resize(1300, 900)
    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('.guided button').length===2")
    assert (
        js(qtbot, view, "document.querySelector('h2').textContent")
        == "Chaque fichier avance à son rythme."
    )
    assert js(qtbot, view, "document.querySelectorAll('.stage').length") == 7
    folder = service.setup.roots[0] / "Films"
    folder.mkdir()
    (folder / "Example.mkv").write_bytes(b"example")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(folder))
    js(qtbot, view, "document.querySelector('[data-command=disk]').click()")
    js(qtbot, view, "document.querySelector('[data-command=add-folder]').click()")
    js(qtbot, view, "document.querySelector('[data-command=browse-folder]').click()")
    wait_js(
        qtbot, view, f"document.querySelector('[name=local]').value==={json.dumps(str(folder))}"
    )
    wait_js(
        qtbot, view, "document.querySelector('#folder-live').textContent.includes('Example.mkv')"
    )
    if output := os.getenv("TL_WEB_SCREENSHOTS"):
        from pathlib import Path

        Path(output).mkdir(parents=True, exist_ok=True)
        view.grab().save(str(Path(output) / "folder-dialog-desktop.png"))
    js(
        qtbot,
        view,
        "document.querySelector('[name=depth]').value='2'; "
        "document.querySelector('[name=scan]').checked=false",
    )
    js(qtbot, view, "document.querySelector('#folder-form').requestSubmit()")
    qtbot.waitUntil(lambda: any(f.path == folder for f in window.settings.library_folders))
    assert next(f for f in window.settings.library_folders if f.path == folder).depth == 2
    qtbot.waitUntil(lambda: not view.scanning)
    wait_js(qtbot, view, "!document.querySelector('dialog').open")

    def painted():
        image = view.grab().toImage()
        return (
            len(
                {
                    image.pixelColor(x, y).rgb()
                    for x in range(20, image.width(), 30)
                    for y in range(20, image.height(), 30)
                }
            )
            > 10
        )

    from PySide6.QtGui import QGuiApplication

    # Offscreen cannot composite WebEngine after Qt Quick creates its renderer.
    # Real Wayland/X11/Windows runs must prove pixels, in addition to DOM checks.
    if QGuiApplication.platformName() != "offscreen":
        qtbot.waitUntil(painted, timeout=5000)
    qtbot.wait(300)
    if output := os.getenv("TL_WEB_SCREENSHOTS"):
        from pathlib import Path

        Path(output).mkdir(parents=True, exist_ok=True)
        view.grab().save(str(Path(output) / "reseed-desktop.png"))
    view.close()


def test_guided_client_setup_saves_and_selects_tested_profile(qtbot, tmp_path, monkeypatch):
    from tests.fake_qbit import FakeQbit
    from torrentlinker.config import Settings

    class ConnectionClient(FakeQbit):
        def check(self):
            return "fixture"

        def folder_settings(self):
            return []

    root = tmp_path / "fixture"
    root.mkdir()
    service, _, _, _, _ = workspace(root, ConnectionClient())
    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    board = window.library_workspace.reseed
    monkeypatch.setattr(board, "service", lambda: service)
    selected = []
    monkeypatch.setattr(window, "_replace_workspace", selected.append)
    done, errors = [], []
    board.add_client(
        {
            "name": "My NAS",
            "client": "qbittorrent",
            "host": "http://fixture:8080",
            "username": "owner",
            "password": "fixture-secret",
        },
        done.append,
        errors.append,
    )
    qtbot.waitUntil(lambda: bool(done or errors))
    assert not errors
    qtbot.waitUntil(lambda: bool(selected))
    profile = Settings.load(window.settings_path).profile(done[0]["client_id"])
    assert profile.name == "My NAS"
    assert profile.host == "http://fixture:8080"
    assert selected[0].active_client_id == profile.id
    assert "fixture-secret" not in window.settings_path.read_text()
