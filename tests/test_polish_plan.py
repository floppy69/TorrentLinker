"""Plan keyboard input, state recovery and zoom in the actual Qt renderer."""

import os
from pathlib import Path

import pytest

from tests.test_community_interfaces import js, wait_js


@pytest.mark.parametrize("language,zoom", [("en", 1), ("fr", 2)])
def test_plan_keyboard_zoom_and_recovery(qtbot, tmp_path, request, language, zoom):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    from PySide6.QtCore import Qt

    from torrentlinker.gui.plan_view import PlanView
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem

    view = PlanView()
    qtbot.addWidget(view)
    view.language = language
    view.resize(1100, 800)
    view.show()
    view.web.setZoomFactor(zoom)
    wait_js(qtbot, view, "typeof initialized!=='undefined' && initialized")

    def capture(state):
        if folder := os.getenv("TL_POLISH_SCREENSHOTS"):
            target = Path(folder) / f"plan-desktop-{language}-{zoom}-{state}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            qtbot.wait(200)
            assert view.grab().save(str(target))

    assert js(qtbot, view, "document.querySelector('#plan-send').disabled")
    capture("empty")
    js(qtbot, view, "document.querySelector('#plan-min-count').focus()")
    qtbot.keyClick(view.web.focusProxy(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClicks(view.web.focusProxy(), "20")
    qtbot.keyClick(view.web.focusProxy(), Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: view.options.min_torrents == 20)
    assert js(qtbot, view, "document.activeElement.id") == "plan-min-seeders"
    qtbot.keyClicks(view.web.focusProxy(), "3")
    qtbot.keyClick(view.web.focusProxy(), Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: view.options.min_seeders == 3)
    view.refresh()
    assert js(qtbot, view, "document.querySelector('#plan-min-count').value") == "20"
    js(qtbot, view, "document.querySelector('#plan-options > summary').focus()")
    qtbot.keyClick(view.web.focusProxy(), Qt.Key.Key_Return)
    assert not js(qtbot, view, "document.querySelector('#plan-options').open")
    qtbot.keyClick(view.web.focusProxy(), Qt.Key.Key_Return)
    assert js(qtbot, view, "document.querySelector('#plan-options').open")
    assert js(qtbot, view, "document.documentElement.scrollWidth<=innerWidth+1")
    view.begin()
    wait_js(qtbot, view, "document.querySelector('#plan-min-count').disabled")
    capture("loading")
    view.failed(OSError("Fixture storage unavailable"))
    wait_js(qtbot, view, "document.body.textContent.includes('Fixture storage unavailable')")
    capture("failure")
    view.show_plan(
        Plan(
            [
                PlanItem(
                    PlanCandidate(
                        "a" * 40, "A long release name " * 20, 1024, 3, 7000, tmp_path, "disk"
                    ),
                    1,
                )
            ],
            1,
        )
    )
    wait_js(qtbot, view, "document.querySelectorAll('#plan-result tbody tr').length===1")
    assert js(qtbot, view, "!document.body.textContent.includes('Fixture storage unavailable')")
    assert js(qtbot, view, "document.documentElement.scrollWidth<=innerWidth+1")
    js(qtbot, view, "document.querySelector('#plan-options').open=false;scrollTo(0,0)")
    capture("recovered")
