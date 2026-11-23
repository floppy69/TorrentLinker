"""Real Qt WebEngine rendering of the same bundled Torrents panel."""

import os
import subprocess
import sys
from types import SimpleNamespace

pytest_plugins = ["tests.test_enqueue_destinations"]


def test_desktop_torrent_sort_filter_and_preferences(
    qtbot, operations, tmp_path, monkeypatch, request
):
    if not os.getenv("TL_TORRENTS_NATIVE_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={
                **os.environ,
                "TL_TORRENTS_NATIVE_CHILD": "1",
                "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
                "QT_QUICK_BACKEND": "software",
            },
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PySide6.QtCore import QSettings

    from tests.test_community_interfaces import js, wait_js
    from tests.test_torrents_workspace import workspace
    from torrentlinker.gui.torrents_view import TorrentsTab

    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("torrentlinker.gui.torrents_view.QSettings", lambda: prefs)
    from torrentlinker.agent.desktop import DesktopOperations

    operations = DesktopOperations(operations.setup)
    service = workspace(operations)
    from dataclasses import replace

    fake = operations.setup.client()
    fake.by_hash["c" * 40] = replace(
        fake.by_hash["c" * 40], files={"main.bin": 1000, "notes.nfo": 20}
    )
    operations.setup.settings.language = "en"
    tab = TorrentsTab(SimpleNamespace(settings=operations.setup.settings), lambda: service)
    qtbot.addWidget(tab)
    tab.resize(1400, 900)
    tab.show()
    wait_js(qtbot, tab, "document.querySelectorAll('tbody tr').length===3")
    js(qtbot, tab, "document.querySelector('[data-sort=size]').click()")
    wait_js(qtbot, tab, "document.querySelector('tbody tr').textContent.includes('Small')")
    js(qtbot, tab, "document.querySelector('[data-sort=size]').click()")
    wait_js(qtbot, tab, "document.querySelector('tbody tr').textContent.includes('Large')")
    js(
        qtbot,
        tab,
        "document.querySelector('#columns').click();document.querySelector('[data-col=weight]').click();document.querySelector('#done').click()",
    )
    wait_js(qtbot, tab, "document.querySelector('[data-sort=weight]')!==null")
    qtbot.waitUntil(lambda: '"weight": true' in prefs.value("torrents/shared-columns", ""))
    operations.setup.settings.language = "fr"
    tab.refresh()
    wait_js(qtbot, tab, "document.querySelector('#columns').textContent==='Colonnes'")
    tab.focus_torrent("c" * 40)
    wait_js(
        qtbot,
        tab,
        "document.querySelectorAll('tbody tr').length===1 && "
        "document.querySelector('#inspector').textContent.includes('Small')",
    )
    js(qtbot, tab, "document.querySelector('[data-tab=files]').click()")
    wait_js(qtbot, tab, "document.querySelector('[data-file=\"1\"]') !== null")
    js(
        qtbot,
        tab,
        "const choice=document.querySelector('[data-file=\"1\"]');"
        "choice.value='skip_files';choice.dispatchEvent(new Event('change'))",
    )
    wait_js(qtbot, tab, "document.querySelector('dialog').open")
    assert js(qtbot, tab, "document.querySelector('dialog li').textContent").startswith("notes.nfo")
    js(qtbot, tab, "document.querySelector('#cancel').click()")
    assert js(qtbot, tab, "document.querySelector('[data-file=\"1\"]').value") == "want_files"
    js(
        qtbot,
        tab,
        "document.querySelector('[data-file=\"1\"]').value='skip_files';"
        "document.querySelector('[data-file=\"1\"]').dispatchEvent(new Event('change'))",
    )
    wait_js(qtbot, tab, "document.querySelector('dialog').open")
    js(qtbot, tab, "document.querySelector('#confirm').click()")
    wait_js(qtbot, tab, "document.querySelector('[data-file=\"1\"]')?.value==='skip_files'")
    assert js(qtbot, tab, "document.querySelector('[data-file=\"0\"]').value") == "want_files"
    js(qtbot, tab, "document.querySelector('[data-tab=summary]').click()")
    tab.focus_torrent("d" * 40)
    wait_js(
        qtbot,
        tab,
        "document.querySelectorAll('tbody tr').length===1 && "
        "document.querySelector('#inspector').textContent.includes('Large')",
    )
    js(qtbot, tab, "document.querySelector('.metric-filters').open=true")
    js(qtbot, tab, "document.querySelector('[data-unit=sizeMin]').click()")
    wait_js(qtbot, tab, "document.querySelector('[data-unit=sizeMin]').textContent==='MiB'")
    assert js(qtbot, tab, "document.querySelector('[data-unit=sizeMax]').textContent") == "GiB"
    if folder := os.getenv("TL_TORRENTS_SCREENSHOTS"):
        from pathlib import Path

        Path(folder).mkdir(parents=True, exist_ok=True)
        tab.grab().save(str(Path(folder) / "torrents-desktop.png"))
    js(qtbot, tab, "document.querySelector('tbody input').click()")
    js(qtbot, tab, "document.querySelector('#transfer-selection').click()")
    wait_js(qtbot, tab, "document.querySelector('#transfer-destination') !== null")
    assert js(qtbot, tab, "document.querySelector('#transfer-check').disabled")
    assert js(qtbot, tab, "document.querySelector('#transfer-method') !== null")
    assert "Transférer vers un autre client" in js(
        qtbot, tab, "document.querySelector('dialog').textContent"
    )
    if folder := os.getenv("TL_TORRENTS_SCREENSHOTS"):
        tab.grab().save(str(Path(folder) / "transfer-desktop.png"))
    js(qtbot, tab, "document.querySelector('[data-remote-edit]').click()")
    wait_js(qtbot, tab, "document.querySelector('#remote-host') !== null")
    assert "Correspondance des dossiers" in js(
        qtbot, tab, "document.querySelector('dialog').textContent"
    )
    assert js(qtbot, tab, "document.querySelector('#remote-browse').disabled")
    if folder := os.getenv("TL_TORRENTS_SCREENSHOTS"):
        tab.grab().save(str(Path(folder) / "seedbox-desktop.png"))
    js(qtbot, tab, "document.querySelector('#remote-done').click()")
    wait_js(qtbot, tab, "document.querySelector('#transfer-close') !== null")
    js(qtbot, tab, "document.querySelector('#transfer-close').click()")
    tab.close()
