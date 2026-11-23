"""The native picker and shared Upload view use the actual desktop bridge."""

import json
import os
import subprocess
import sys

from tests.test_community_interfaces import js, ready, wait_js
from tests.test_library_folders import window_for


def test_desktop_manual_source_and_shared_rendering(qtbot, tmp_path, monkeypatch):
    if not os.getenv("TL_UPLOAD_NATIVE_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", __file__],
            env={
                **os.environ,
                "TL_UPLOAD_NATIVE_CHILD": "1",
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

    from torrentlinker.gui.theme import apply_theme

    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    apply_theme(QApplication.instance(), "dark")
    source = tmp_path / "Sculpture.stl"
    source.write_text("solid sculpture\nendsolid sculpture\n")
    view = window.upload_workspace
    window.tabs.setCurrentWidget(view)
    window.resize(1560, 1050)
    window.show()
    wait_js(qtbot, view, "document.querySelectorAll('.step').length===6")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(source), ""))
    js(qtbot, view, "document.querySelector('[data-action=file]').click()")
    js(qtbot, view, "document.querySelector('[data-picker=file]').click()")
    wait_js(
        qtbot, view, f"document.querySelector('#manual-path').value==={json.dumps(str(source))}"
    )
    js(
        qtbot,
        view,
        "document.querySelector('#manual-kind').value='10';document.querySelector('#manual-form').requestSubmit()",
    )
    wait_js(qtbot, view, "!!document.querySelector('#confirm-existing')")
    assert window.store.local_drafts()[0]["path"] == str(source)
    assert js(qtbot, view, "getComputedStyle(document.body).backgroundColor") == "rgb(22, 29, 35)"
    assert window.palette().window().color().name() == "#161d23"
    js(qtbot, view, "document.querySelector('[data-step=\"2\"]').click()")
    wait_js(qtbot, view, "!!document.querySelector('[data-action=advanced]')")
    js(qtbot, view, "document.querySelector('[data-action=advanced]').click()")
    wait_js(
        qtbot,
        view,
        "document.querySelector('#preparation').open && "
        "!document.querySelector('[data-prep=save]').disabled",
    )
    js(
        qtbot,
        view,
        "document.querySelector('#prep-source').value='Desktop source';"
        "document.querySelector('#prep-source').dispatchEvent(new Event('input',{bubbles:true}));"
        "document.querySelector('[data-prep=save]').click()",
    )
    wait_js(
        qtbot,
        view,
        "document.querySelector('#prep-status').textContent==='Saved' || "
        "document.querySelector('#prep-status').textContent==='Enregistré'",
    )
    assert window.store.local_drafts()[0]["form"]["source"] == "Desktop source"
    qtbot.wait(250)
    window.grab().save("/tmp/upload-preparation-desktop.png")
    js(qtbot, view, "document.querySelector('[data-prep=close]').click()")
    js(qtbot, view, "document.querySelector('[data-action=draft-list]').click()")
    qtbot.wait(300)
    assert window.workspace_scroll.verticalScrollBar().maximum() == 0
    window.grab().save("/tmp/upload-guided-desktop.png")
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "offscreen":
        qtbot.waitUntil(
            lambda: (
                len(
                    {
                        view.grab().toImage().pixelColor(x, y).rgb()
                        for x in range(20, view.width(), 40)
                        for y in range(20, view.height(), 40)
                    }
                )
                > 10
            ),
            timeout=5000,
        )
    from tests.test_community import observation

    (tmp_path / "community").mkdir()
    _, _, profile = ready(tmp_path / "community", monkeypatch)
    observed = observation()
    observed["candidates"] = [
        {"hash": f"{index:040x}", "title": f"Community sample {index}"} for index in range(30)
    ]
    profile.community.observe("42", observed)
    window.community_view.bridge.workspace = profile
    window.community_view.workspace = profile
    for workspace, panel in (
        (window.zen_tab, window.community_view),
        (window.library_workspace, window.library_workspace.reseed),
        (window.upload_workspace, window.upload_workspace),
    ):
        window.tabs.setCurrentWidget(workspace)
        if workspace is window.zen_tab:
            window.zen_tab.pages.setCurrentWidget(panel)
        for width, height in ((1560, 1050), (800, 560)):
            window.resize(width, height)
            wait_js(qtbot, panel, "document.readyState==='complete'")
            if panel is window.community_view:
                wait_js(qtbot, panel, "document.querySelectorAll('.torrent').length >= 20")
            qtbot.wait(200)
            assert (
                js(qtbot, panel, "parseFloat(getComputedStyle(document.body).paddingRight)") >= 16
            )
            assert window.workspace_scroll.verticalScrollBar().maximum() == 0
            assert window.workspace_scroll.horizontalScrollBar().maximum() == 0
            window.grab().save(f"/tmp/panel-scroll-{panel.channel_name}-{width}.png")
    view.close()
