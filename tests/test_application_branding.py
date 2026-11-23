"""The launch path and sidebar expose TorrentLinker's identity."""

import os
import subprocess
import sys

from tests.test_library_folders import window_for


def test_sidebar_displays_the_packaged_logo(qtbot, tmp_path, monkeypatch, request):
    from tests.test_community_interfaces import wait_js
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    window.show()
    wait_js(qtbot, window.navigation, "document.getElementById('brand-logo')?.naturalWidth > 0")
    wait_js(
        qtbot,
        window.navigation,
        "document.getElementById('brand-logo').getBoundingClientRect().width >= 24",
    )


def test_real_entrypoint_sets_desktop_identity_before_creating_its_window(tmp_path):
    code = """
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from torrentlinker import app
app.data_dir = lambda: Path(sys.argv[1])
class InspectWindow:
    def __init__(self, *args):
        instance = QApplication.instance()
        print('Desktop identity:', repr(instance.desktopFileName()), flush=True)
        raise SystemExit(0 if instance.desktopFileName() == 'torrentlinker'
                         and not instance.windowIcon().isNull() else 1)
app.MainWindow = InspectWindow
app.main()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
