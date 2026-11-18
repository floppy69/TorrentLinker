import os
import subprocess

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QProcess, Qt

from torrentlinker.config import Settings
from torrentlinker.gui import theme


@pytest.fixture
def desktop(qapp, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setattr(theme.sys, "platform", "linux")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "'prefer-dark'\n")
    )
    # Keep the real desktop monitor out of deterministic unit tests.
    monkeypatch.setattr(QProcess, "start", lambda *a, **kw: None)
    theme._update_theme(qapp, Qt.ColorScheme.Light)
    theme.apply_theme(qapp)
    follower = qapp.findChild(theme.ThemeFollower)
    yield follower
    follower.stop()
    follower.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    theme._update_theme(qapp, Qt.ColorScheme.Light)


def test_explicit_gnome_dark_preference_overrides_light_qt_hint(qapp, desktop):
    assert qapp.palette().window().color().lightness() < 128


def test_manual_theme_overrides_desktop_and_auto_resumes_following(qapp, desktop):
    theme.set_theme("light")
    assert qapp.palette().window().color().lightness() > 128
    desktop.set_preference("color-scheme: 'prefer-dark'")
    assert qapp.palette().window().color().lightness() > 128
    theme.set_theme("auto")
    assert qapp.palette().window().color().lightness() < 128
    desktop.set_preference("color-scheme: 'prefer-light'")
    assert qapp.palette().window().color().lightness() > 128
    theme.set_theme("dark")
    assert qapp.palette().window().color().lightness() < 128


@pytest.mark.parametrize("original", [None, "", "/host/vendor-libraries"])
def test_frozen_theme_probe_and_monitor_use_host_libraries(qapp, monkeypatch, original):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setattr(theme.sys, "platform", "linux")
    monkeypatch.setattr(theme.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/frozen/_internal")
    if original is None:
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    else:
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", original)
    probes, monitors = [], []

    def probe(args, **kwargs):
        probes.append(kwargs.get("env", os.environ).get("LD_LIBRARY_PATH"))
        # The reproduced broken GIO backend returns a default despite prefer-dark.
        value = "default" if probes[-1] == "/frozen/_internal" else "prefer-dark"
        return subprocess.CompletedProcess(args, 0, f"'{value}'\n")

    def monitor(process, *args):
        env = process.processEnvironment()
        monitors.append(env.value("LD_LIBRARY_PATH") if env.contains("LD_LIBRARY_PATH") else None)

    monkeypatch.setattr(subprocess, "run", probe)
    monkeypatch.setattr(QProcess, "start", monitor)
    theme._update_theme(qapp, Qt.ColorScheme.Light)
    follower = theme.ThemeFollower(qapp)
    try:
        assert qapp.palette().window().color().lightness() < 128
        assert probes == [original]
        assert monitors == [original]
        assert os.environ["LD_LIBRARY_PATH"] == "/frozen/_internal"
    finally:
        follower.stop()
        follower.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        theme._update_theme(qapp, Qt.ColorScheme.Light)


def test_theme_setting_is_saved_and_old_settings_default_to_auto(tmp_path, qtbot):
    from torrentlinker.gui.settings_dialog import SettingsDialog

    path = tmp_path / "settings.json"
    path.write_text("{}")
    settings = Settings.load(path)
    assert settings.theme == "auto"
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog._save()
    assert settings.theme == "dark"
    settings.save(path)
    assert Settings.load(path).theme == "dark"


def test_media_interface_choice_survives_settings_reopen_and_cancel(tmp_path, qtbot):
    from PySide6.QtWidgets import QDialogButtonBox

    from torrentlinker.gui.settings_dialog import SettingsDialog

    path = tmp_path / "settings.json"
    path.write_text("{}")
    settings = Settings.load(path)
    assert settings.media_layout == "cinematic"
    for choice in ("focus", "collection", "cinematic"):
        dialog = SettingsDialog(settings)
        qtbot.addWidget(dialog)
        dialog.media_layout.setCurrentIndex(dialog.media_layout.findData(choice))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        settings.save(path)
        settings = Settings.load(path)
        reopened = SettingsDialog(settings)
        qtbot.addWidget(reopened)
        assert reopened.media_layout.currentData() == choice
        reopened.media_layout.setCurrentIndex((reopened.media_layout.currentIndex() + 1) % 3)
        reopened.reject()
        assert settings.media_layout == choice

    path.write_text('{"media_layout": "removed-experimental-layout"}')
    assert Settings.load(path).media_layout == "cinematic"


@pytest.mark.parametrize(
    "mode, expected",
    [
        (
            "dark",
            [
                "#161d23",
                "#202932",
                "#26323c",
                "#e2e9ed",
                "#98aab7",
                "#33404b",
                "#263e43",
                "#64c9c0",
            ],
        ),
        (
            "light",
            [
                "#f3f6fa",
                "#ffffff",
                "#f7f9fc",
                "#203047",
                "#5c6c80",
                "#d5dfe9",
                "#d8eeeb",
                "#087f76",
            ],
        ),
    ],
)
def test_native_palette_uses_approved_shared_colors(qapp, desktop, mode, expected):
    from PySide6.QtGui import QPalette

    theme.set_theme(mode)
    roles = [
        QPalette.ColorRole.Window,
        QPalette.ColorRole.Base,
        QPalette.ColorRole.AlternateBase,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.PlaceholderText,
        QPalette.ColorRole.Mid,
        QPalette.ColorRole.Highlight,
        QPalette.ColorRole.Link,
    ]
    assert [qapp.palette().color(role).name() for role in roles] == expected
