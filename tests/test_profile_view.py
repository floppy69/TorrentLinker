import pytest
from PySide6.QtCore import Qt

from tests.test_community_interfaces import js, wait_js
from tests.test_web_profile import ORIGIN, prepared, snapshot
from torrentlinker.gui.companion_panel import CompanionPanel
from torrentlinker.gui.zen_view import ZenTab
from torrentlinker.zen import ZenProfile


def isolated_profile_test(nodeid):
    # Qt Quick/WebEngine and the application theme are process-global. Keep these
    # rendering tests from changing the renderer or timers of later GUI tests.
    import os
    import subprocess
    import sys

    if os.getenv("TL_PROFILE_NATIVE_CHILD"):
        return False
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", nodeid],
        env={**os.environ, "TL_PROFILE_NATIVE_CHILD": "1"},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return True


def test_profile_is_first_desktop_tab_and_shows_api_and_companion(
    qtbot, tmp_path, monkeypatch, request
):
    if isolated_profile_test(request.node.nodeid):
        return
    _, setup = prepared(tmp_path, monkeypatch)
    workspace = setup.profile_workspace()
    workspace.refresh(setup.settings.indexer.url, "fake-key")
    tab = ZenTab(lambda: lambda: None, ZenProfile)
    qtbot.addWidget(tab)
    tab.resize(1200, 850)
    tab.show()
    assert tab.pages.tabText(0) == "Profile"
    view = tab.profile_view
    view.show_state(workspace.state())
    wait_js(
        qtbot,
        view,
        "document.querySelector('#profile-username').textContent.includes('Demo account')",
    )
    assert "124" in js(qtbot, view, "document.querySelector('#profile-zen').textContent")
    wait_js(
        qtbot, view, "document.querySelector('#profile-seeding').textContent.includes('Connect')"
    )
    panel = CompanionPanel()
    qtbot.addWidget(panel)
    panel.show_state(workspace.state())
    assert not panel.session_downloads.isEnabled()
    with qtbot.waitSignal(panel.pair_requested):
        qtbot.mouseClick(panel.pair_button, Qt.MouseButton.LeftButton)
    code = workspace.pairing()["code"]
    token = workspace.receive("/api/companion/pair", ORIGIN, "", {"code": code, "accountId": "42"})[
        "token"
    ]
    workspace.receive("/api/companion/snapshot", ORIGIN, "Bearer " + token, snapshot())
    view.show_state(workspace.state())
    wait_js(qtbot, view, "document.querySelector('#profile-seeding').textContent.includes('42')")
    panel.show_state(workspace.state())
    assert panel.disconnect_button.isEnabled()
    assert panel.session_downloads.isEnabled() and not panel.session_downloads.isChecked()
    with qtbot.waitSignal(panel.session_downloads_toggled) as toggled:
        panel.session_downloads.setChecked(True)
    assert toggled.args == [True]
    workspace.set_session_downloads(True)
    panel.show_state(workspace.state())
    assert panel.session_downloads.isChecked()
    import os
    from pathlib import Path

    if output := os.getenv("TL_PROFILE_SCREENSHOTS"):
        from PySide6.QtWidgets import QApplication

        from torrentlinker.gui.theme import apply_theme

        apply_theme(QApplication.instance(), "dark")
        tab.resize(1400, 1000)
        qtbot.wait(100)
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        assert tab.grab().save(str(target / "desktop-profile.png"))
    workspace.disconnect()
    view.show_state(workspace.state())
    wait_js(
        qtbot, view, "document.querySelector('#profile-seeding').textContent.includes('Connect')"
    )


def test_desktop_connect_opens_handoff_and_receiver_returns_after_restart(
    qtbot, tmp_path, monkeypatch, request
):
    if isolated_profile_test(request.node.nodeid):
        return
    import json
    import socket
    from urllib.parse import unquote, urlsplit

    import httpx

    from torrentlinker.config import Settings
    from torrentlinker.credentials import set_secret
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.store import Store

    prepared(tmp_path, monkeypatch)
    set_secret("indexer-api-key", "fake-key")
    opened = []
    monkeypatch.setattr(
        "PySide6.QtGui.QDesktopServices.openUrl", lambda url: opened.append(url.toString()) or True
    )
    settings = Settings()
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "desktop.db"))
    qtbot.addWidget(window)
    window.show()
    wait_js(
        qtbot,
        window.zen_tab.profile_view,
        "document.querySelector('#profile-username').textContent.includes('Demo account')",
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        window.account_workspace.remember_receiver(listener.getsockname()[1])
    qtbot.mouseClick(window.companion_panel_widget().pair_button, Qt.MouseButton.LeftButton)
    assert len(opened) == 1
    payload = json.loads(unquote(urlsplit(opened[0]).fragment))
    address = payload["target"]
    with httpx.Client(base_url=address, trust_env=False) as browser:
        assert browser.get("/companion/connect").status_code == 200
        assert browser.get("/companion/connect.js").status_code == 200
        token = browser.post(
            "/api/companion/pair", headers={"Origin": ORIGIN}, json=payload
        ).json()["token"]
    window.close()
    restarted = MainWindow(
        settings, tmp_path / "settings.json", Store(tmp_path / "desktop-restarted.db")
    )
    qtbot.addWidget(restarted)
    restarted.show()
    qtbot.waitUntil(lambda: restarted.companion_receiver is not None)
    with httpx.Client(base_url=address, trust_env=False) as browser:
        assert (
            browser.post(
                "/api/companion/snapshot",
                headers={"Origin": ORIGIN, "Authorization": "Bearer " + token},
                json=snapshot(),
            ).status_code
            == 200
        )
    wait_js(
        qtbot,
        restarted.zen_tab.profile_view,
        "document.querySelector('#profile-seeding').textContent.includes('42')",
    )
    assert len(opened) == 1  # No new handoff or consent on restart.
    restarted.close()


@pytest.mark.parametrize("failed", [False, True])
def test_profile_completion_after_window_destruction_is_ignored(
    qtbot, tmp_path, monkeypatch, failed, request
):
    if isolated_profile_test(request.node.nodeid):
        return
    import threading

    from shiboken6 import delete, isValid

    from torrentlinker.config import Settings
    from torrentlinker.gui import tasks
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.store import Store

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    window.profile_timer.stop()
    started, release = threading.Event(), threading.Event()

    def read_profile(*args):
        started.set()
        assert release.wait(5)
        if failed:
            raise ValueError("controlled profile failure")
        from torrentlinker.profile import UserProfile

        return UserProfile("Fixture", None, None, 0, 0, True, None)

    monkeypatch.setattr(window.account_workspace, "refresh", read_profile)
    window.refresh_profile()
    assert started.wait(1)
    try:
        window.close()
        delete(window)
        assert not isValid(window)
    finally:
        release.set()
    qtbot.waitUntil(lambda: not tasks._alive, timeout=5000)


def test_profile_view_draws_history_period_clients_and_wraps_tiles(
    qtbot, tmp_path, monkeypatch, request
):
    if isolated_profile_test(request.node.nodeid):
        return
    from datetime import date, timedelta

    from PySide6.QtCore import QSettings

    from torrentlinker.gui.profile_view import ProfileView
    from torrentlinker.profile_history import ProfileDay

    _, setup = prepared(tmp_path, monkeypatch)
    workspace = setup.profile_workspace()
    workspace.refresh(setup.settings.indexer.url, "fake-key")
    today = date.today()
    history = [
        ProfileDay(
            (today - timedelta(days=back)).isoformat(),
            {"uploaded_actual": 1000 - back, "downloaded_actual": 100, "balance": 50 - back},
            api=True,
        )
        for back in range(40, -1, -1)
    ]
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    view = ProfileView(settings)
    qtbot.addWidget(view)
    view.resize(1400, 1200)
    view.show()
    view.show_state(workspace.state(), [])
    wait_js(
        qtbot,
        view,
        "document.querySelector('#profile-volumes').textContent"
        ".includes('History is being collected')",
    )
    assert (
        js(
            qtbot,
            view,
            "document.documentElement.clientWidth - "
            "document.querySelector('#zen-profile-panel').getBoundingClientRect().right",
        )
        < 40
    )
    from tests.test_community import observation

    workspace.community.observe("42", observation(today=3))
    view.show_state(workspace.state(), history)
    wait_js(
        qtbot, view, "document.querySelector('#profile-contribution').textContent.includes('3 / 5')"
    )
    wait_js(qtbot, view, "document.querySelectorAll('#profile-volumes svg').length === 1")
    text_size_is_stable = (
        "Array.from(document.querySelectorAll('.pf-chart text')).every(t => "
        "Math.abs(parseFloat(getComputedStyle(t).fontSize) * t.getScreenCTM().a - 10) < 0.2)"
    )
    wait_js(qtbot, view, text_size_is_stable)
    assert (
        js(qtbot, view, "document.querySelector('.pf-chart').getBoundingClientRect().height") == 220
    )
    assert "+30 B" in js(qtbot, view, "document.querySelector('#profile-tiles').textContent")
    js(qtbot, view, "document.querySelectorAll('#profile-period button')[0].click()")
    wait_js(
        qtbot,
        view,
        "document.querySelectorAll('#profile-period button')[0]"
        ".getAttribute('aria-pressed') === 'true'",
    )
    assert "+7 B" in js(qtbot, view, "document.querySelector('#profile-tiles').textContent")
    import os
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from torrentlinker.gui.theme import apply_theme

    for theme in ("dark", "light"):
        apply_theme(QApplication.instance(), theme)
        wait_js(qtbot, view, f"document.documentElement.dataset.theme === '{theme}'")
        if output := os.getenv("TL_PROFILE_SCREENSHOTS"):
            target = Path(output)
            target.mkdir(parents=True, exist_ok=True)
            qtbot.wait(100)
            assert view.grab().save(str(target / f"desktop-history-{theme}.png"))
    assert settings.value("profile/period") in (7, "7")
    restored = ProfileView(settings)
    qtbot.addWidget(restored)
    assert restored.period == 7

    view.show_torrent_clients(
        {
            "clients": [
                {"name": "seedbox", "count": 3, "size": 30, "error": None},
                {"name": "NAS", "count": None, "size": None, "error": "refused"},
            ],
            "unique": 3,
            "gap": None,
            "zen": None,
        }
    )
    wait_js(
        qtbot, view, "document.querySelector('#profile-seeding').textContent.includes('seedbox')"
    )
    text = js(qtbot, view, "document.querySelector('#profile-seeding').textContent")
    assert "NAS" in text and "Unavailable" in text
    columns = (
        "getComputedStyle(document.querySelector('#profile-tiles'))"
        ".gridTemplateColumns.split(' ').length"
    )
    assert js(qtbot, view, columns) == 6
    assert (
        js(
            qtbot,
            view,
            "getComputedStyle(document.querySelector('#profile-sync')).gridColumnEnd",
        )
        == "auto"
    )
    view.resize(1800, 1000)
    wait_js(
        qtbot,
        view,
        "getComputedStyle(document.querySelector('.pf-grid2'))"
        ".gridTemplateColumns.split(' ').length === 3",
    )
    assert (
        js(
            qtbot,
            view,
            "Array.from(document.querySelector('.pf-grid2').children).slice(-2).map(e=>e.id).join(',')",
        )
        == "profile-contribution,profile-sync"
    )
    if output := os.getenv("TL_PROFILE_SCREENSHOTS"):
        qtbot.wait(100)
        assert view.grab().save(str(Path(output) / "desktop-contribution-wide.png"))
    view.resize(900, 1200)
    wait_js(qtbot, view, columns + " === 3")
    view.resize(600, 1200)
    wait_js(qtbot, view, columns + " === 2")
    wait_js(qtbot, view, text_size_is_stable)
    for width in (1800, 1400, 600):
        view.resize(width, 650)
        qtbot.wait(100)
        for offset in (200, 450, 700):
            js(qtbot, view, f"window.scrollTo(0, {offset})")
            position = js(qtbot, view, "window.scrollY")
            assert position > 100
            for _ in range(3):
                view.show_state(workspace.state(), history)
                qtbot.wait(100)
                assert abs(js(qtbot, view, "window.scrollY") - position) <= 1
    with qtbot.waitSignal(view.refresh_requested):
        js(qtbot, view, "document.querySelector('#profile-refresh').click()")
    view.language = "fr"
    view.refresh()
    wait_js(qtbot, view, "document.querySelector('#profile-refresh').textContent === 'Actualiser'")
    view.set_busy(True)
    wait_js(qtbot, view, "document.querySelector('#profile-refresh').disabled")
    view.close()
