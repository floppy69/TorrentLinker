from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from torrentlinker.config import Settings
from torrentlinker.gui import main_window
from torrentlinker.gui.library_workspace import FolderEditor
from torrentlinker.gui.upload_view import UploadTab
from torrentlinker.gui.zen_view import SeedingView
from torrentlinker.store import Store


def test_existing_settings_without_key_do_not_start_network_work(qtbot, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(main_window, "get_secret", lambda name: "")
    for method in ("check_verifications", "refresh_profile", "refresh_categories", "scan"):
        monkeypatch.setattr(
            main_window.MainWindow, method, lambda self, *args, **kw: calls.append("network")
        )
    monkeypatch.setattr(UploadTab, "refresh_drafts", lambda self: calls.append("drafts"))
    monkeypatch.setattr(SeedingView, "refresh", lambda self, **kw: calls.append("seeding"))
    settings = Settings()
    settings_path = tmp_path / "settings.json"
    settings.save(settings_path)
    window = main_window.MainWindow(settings, settings_path, Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    qtbot.wait(20)
    assert not calls
    assert not window.seeding_timer.isActive()


def test_profile_reads_no_torrent_client_before_setup(qtbot, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(main_window, "get_secret", lambda name: "")
    monkeypatch.setattr(main_window.MainWindow, "refresh_profile", lambda self: None)
    window = main_window.MainWindow(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    monkeypatch.setattr(window._connections, "client", lambda *a, **kw: calls.append(a))
    window.show()
    assert window.zen_tab.profile_view.isVisible()

    window._poll_account_profile()
    window.zen_tab.profile_view.refresh_requested.emit()

    assert not calls


def test_media_layout_shortcut_is_restored_when_the_app_reopens(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QComboBox

    window, calls, _ = setup_window(qtbot, tmp_path, monkeypatch)
    selector = window.media_tab.findChild(QComboBox, "media-layout")
    assert selector.currentData() == "cinematic"
    selector.setCurrentIndex(selector.findData("focus"))
    saved = Settings.load(window.settings_path)
    assert saved.media_layout == "focus"

    reopened = main_window.MainWindow(saved, window.settings_path, window.store)
    qtbot.addWidget(reopened)
    restored = reopened.media_tab.findChild(QComboBox, "media-layout")
    assert restored.currentData() == "focus"
    restored.setCurrentIndex(restored.findData("collection"))
    assert Settings.load(window.settings_path).media_layout == "collection"
    assert not calls


def test_media_center_hides_app_chrome_and_restores_window(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    window, _, _ = setup_window(qtbot, tmp_path, monkeypatch)
    window.show()
    window.tabs.setCurrentWidget(window.media_tab)
    player = window.media_tab.player
    qtbot.mouseClick(window.media_tab.center_button, Qt.LeftButton)
    assert window.isFullScreen()
    assert not window.navigation.isVisible()
    assert not window.page_title.isVisible()
    assert window.media_tab.kind_tabs["video"].isVisible()
    assert window.media_tab.chat.isVisible()
    assert window.media_tab.player is player
    qtbot.mouseClick(window.media_tab.center_button, Qt.LeftButton)
    assert not window.isFullScreen()
    assert window.navigation.isVisible()
    assert window.page_title.isVisible()
    qtbot.mouseClick(window.media_tab.center_button, Qt.LeftButton)
    qtbot.keyClick(window.media_tab.center_button, Qt.Key_Escape)
    qtbot.waitUntil(lambda: not window.isFullScreen())
    assert window.navigation.isVisible()
    window.showMaximized()
    qtbot.mouseClick(window.media_tab.center_button, Qt.LeftButton)
    qtbot.mouseClick(window.media_tab.center_button, Qt.LeftButton)
    assert window.isMaximized()
    qtbot.mouseClick(window.media_tab.center_button, Qt.LeftButton)
    window.tabs.setCurrentIndex(0)
    assert not window.media_center_active
    assert not window.isFullScreen()
    assert window.navigation.isVisible()


def setup_window(qtbot, tmp_path, monkeypatch, *, saved=True, key=""):
    from torrentlinker.domain import LibraryFolder

    secret = {"key": key}
    calls = []
    monkeypatch.setattr(
        main_window,
        "get_secret",
        lambda name: secret["key"] if name == main_window.INDEXER_API_KEY else "",
    )
    for method in ("check_verifications", "refresh_profile", "refresh_categories", "scan"):
        monkeypatch.setattr(
            main_window.MainWindow,
            method,
            lambda self, *args, _name=method, **kw: calls.append(_name),
        )
    monkeypatch.setattr(UploadTab, "refresh_drafts", lambda self: calls.append("drafts"))
    monkeypatch.setattr(SeedingView, "refresh", lambda self, **kw: calls.append("seeding"))
    settings = Settings(library_folders=[LibraryFolder(tmp_path)])
    path = tmp_path / "settings.json"
    if saved:
        settings.save(path)
    window = main_window.MainWindow(settings, path, Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    return window, calls, secret


def test_configured_startup_loads_once_without_welcome(qtbot, tmp_path, monkeypatch):
    window, calls, _ = setup_window(qtbot, tmp_path, monkeypatch, key="test-key")
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))
    window.startup()
    window.startup()
    qtbot.waitUntil(lambda: len(calls) == 6)
    assert set(calls) == {
        "check_verifications",
        "refresh_profile",
        "refresh_categories",
        "scan",
        "drafts",
        "seeding",
    }
    assert not messages
    assert window.seeding_timer.isActive()
    assert window.setup_notice.isHidden()


def test_cancelled_welcome_can_resume_after_saving_key(qtbot, tmp_path, monkeypatch):
    window, calls, secret = setup_window(qtbot, tmp_path, monkeypatch)
    messages, opened = [], []
    save = [False]
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[1]))

    class Dialog(QObject):
        diagnostics_requested = Signal()
        agent_approvals = ()

        def __init__(self, settings, parent):
            super().__init__(parent)
            opened.append(True)
            self.folder_editor = FolderEditor(settings.library_folders, parent)

        def exec(self):
            if save[0]:
                secret["key"] = "test-key"
                return True
            return False

    monkeypatch.setattr(main_window, "SettingsDialog", Dialog)
    window.startup()
    qtbot.wait(20)
    assert messages == ["Welcome to TorrentLinker"]
    assert opened == [True]
    assert not calls
    assert not window.seeding_timer.isActive()
    assert not window.setup_notice.isHidden()
    assert window.tabs.isEnabled()
    assert window.tabs.isTabEnabled(window.tabs.indexOf(window.media_tab))
    assert not window.tabs.isTabEnabled(window.tabs.indexOf(window.search_tab))
    save[0] = True
    window.open_settings()
    qtbot.waitUntil(lambda: len(calls) == 6)
    assert window.tabs.isEnabled()
    assert window.setup_notice.isHidden()
    assert window.seeding_timer.isActive()


def test_first_launch_save_without_key_keeps_loading_paused(qtbot, tmp_path, monkeypatch):
    window, calls, secret = setup_window(qtbot, tmp_path, monkeypatch, saved=False, key="  ")

    class Dialog(QObject):
        diagnostics_requested = Signal()
        agent_approvals = ()

        def __init__(self, settings, parent):
            super().__init__(parent)
            self.folder_editor = FolderEditor(settings.library_folders, parent)

        def exec(self):
            return True

    monkeypatch.setattr(main_window, "SettingsDialog", Dialog)
    window.startup()
    qtbot.wait(20)
    assert window.settings_path.exists()
    assert not calls
    assert not window.seeding_timer.isActive()
    assert not window.setup_notice.isHidden()
    secret["key"] = "test-key"
    window.open_settings()
    qtbot.waitUntil(lambda: len(calls) == 6)
    assert window._startup_complete


def test_restoring_searches_checks_upload_eligibility_once_per_item(qtbot, tmp_path, monkeypatch):
    from torrentlinker.config import Settings
    from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, LocalItem
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.library import LibraryEntry
    from torrentlinker.store import Store

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    folder = LibraryFolder(tmp_path, 1, ContentKind.MOVIE)
    entries = [
        LibraryEntry(
            folder, LocalItem(tmp_path / f"film{i}.mkv", {f"film{i}.mkv": 1}), ItemState.ORPHAN
        )
        for i in range(30)
    ]
    window.library_model.set_entries(entries)
    window.upload_tab.set_entries(entries)
    checked = []
    monkeypatch.setattr(
        window.upload_tab, "why_not", lambda entry: checked.append(entry) or "Not ready"
    )
    window._searches_restored([(entry, []) for entry in entries])
    assert len(checked) == len(entries)
    assert len(window.review.cache) == len(entries)
    assert len(window.upload_tab.searched) == len(entries)


def test_first_web_panel_visit_keeps_the_native_window(qtbot, tmp_path, monkeypatch):
    # Offscreen never recreates windows. Use the session's display in a child process.
    import os
    import subprocess
    import sys

    import pytest

    if not os.getenv("TL_NATIVE_WINDOW_CHILD"):
        platform = (
            "wayland" if os.getenv("WAYLAND_DISPLAY") else "xcb" if os.getenv("DISPLAY") else ""
        )
        if not platform:
            pytest.skip("needs a Wayland or X11 display")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"{__file__}::{sys._getframe().f_code.co_name}"],
            env={
                **os.environ,
                "TL_NATIVE_WINDOW_CHILD": "1",
                "QT_QPA_PLATFORM": platform,
                "LC_ALL": "fr_FR.UTF-8",
                "LANG": "fr_FR.UTF-8",
            },
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QStackedWidget, QTabWidget

    window, _, _ = setup_window(qtbot, tmp_path, monkeypatch)
    window.show()
    qtbot.waitExposed(window)
    native = window.windowHandle()
    destroyed = []

    class Spy(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.PlatformSurface:
                destroyed.append(event.surfaceEventType())
            return False

    spy = Spy()
    native.installEventFilter(spy)
    for panel in (
        window.zen_tab.profile_view,
        window.community_view,
        window.library_workspace.reseed,
        window.upload_workspace,
    ):
        child = panel
        while child is not window:
            parent = child.parentWidget()
            if isinstance(parent, QStackedWidget):
                tabs = parent.parentWidget()
                if isinstance(tabs, QTabWidget):
                    tabs.setCurrentWidget(child)
                else:
                    parent.setCurrentWidget(child)
            child = parent
        qtbot.waitUntil(lambda panel=panel: panel.web is not None and panel.isVisible())
        from tests.test_community_interfaces import js, wait_js

        labels = {
            "profile": ("Refresh", "Actualiser"),
            "community": ("Every contribution counts.", "Chaque contribution compte."),
            "reseed": ("Run all", "Tout enchaîner"),
            "upload": ("A new share starts here.", "Un nouveau partage commence ici."),
        }
        for language, text in [
            ("auto", labels[panel.channel_name][1]),
            *zip(("en", "fr"), labels[panel.channel_name], strict=True),
        ]:
            panel.language = language
            panel.refresh()
            resolved_language = "fr" if language == "auto" else language
            import json

            if panel.channel_name == "community":
                # This startup fixture has no tracker profile. The populated Community
                # workflow is covered separately in test_community_interfaces.
                wait_js(
                    qtbot,
                    panel,
                    f"document.documentElement.lang === {json.dumps(resolved_language)}",
                )
            else:
                wait_js(qtbot, panel, f"document.body.innerText.includes({json.dumps(text)})")
            assert js(qtbot, panel, "document.documentElement.lang") == resolved_language
        # A neighboring file must not become loadable when shared assets are allowed.
        forbidden = tmp_path / "unbundled.js"
        forbidden.write_text("document.title = 'unbundled script executed'")
        js(
            qtbot,
            panel,
            f"""(() => {{
          const script = document.createElement('script');
          script.src = {json.dumps(forbidden.as_uri())};
          script.onerror = () => document.body.dataset.blocked = 'yes';
          document.head.append(script);
        }})()""",
        )
        wait_js(qtbot, panel, "document.body.dataset.blocked === 'yes'")
        assert js(qtbot, panel, "document.title") != "unbundled script executed"
        assert window.windowHandle() is native and not destroyed, panel
