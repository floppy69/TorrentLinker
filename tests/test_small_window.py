import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from torrentlinker import i18n
from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.gui.theme import ThemeFollower, apply_theme
from torrentlinker.store import Store


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("size", [(1000, 650), (800, 560)])
def test_small_window_keeps_every_workspace_action_reachable(
    qtbot, qapp, tmp_path, monkeypatch, language, size, request
):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    monkeypatch.setattr("keyring.get_password", lambda *args: None)
    palette = qapp.palette()
    stylesheet = qapp.styleSheet()
    style = qapp.style().objectName()
    apply_theme(qapp, "dark")
    translators = i18n.install(qapp, language)
    try:
        window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
        qtbot.addWidget(window)
        window.show()
        controls = [
            window.zen_tab.profile_view,
            window.review.reseed_button,
            window.upload_workspace,
            window.search_tab.board,
        ]
        for index, control in enumerate(controls):
            window.tabs.setCurrentIndex(index)
            window.resize(*size)
            qtbot.wait(10)
            assert window.width() <= size[0] and window.height() <= size[1]
            # Small screens can scroll to actions instead of clipping them off-screen.
            window.workspace_scroll.ensureWidgetVisible(control)
            qtbot.wait(10)
            viewport = window.workspace_scroll.viewport()
            center = control.mapTo(viewport, control.rect().center())
            assert viewport.rect().contains(center), window.tabs.tabText(index)
            if index in {2, 3}:
                assert control.isVisible()
                assert window.workspace_scroll.verticalScrollBar().maximum() == 0
            assert window.navigation.isVisible()
            assert window.centralWidget().rect().contains(window.navigation.geometry())
        window.tabs.setCurrentIndex(0)
        assert window.workspace_scroll.horizontalScrollBar().value() == 0
        assert window.workspace_scroll.verticalScrollBar().value() == 0
    finally:
        for translator in translators:
            qapp.removeTranslator(translator)
        follower = qapp.findChild(ThemeFollower)
        follower.stop()
        follower.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.setStyle(style)
        qapp.setPalette(palette)
        qapp.setStyleSheet(stylesheet)


def test_initial_window_size_fits_available_screen(qtbot, qapp, tmp_path, monkeypatch, request):
    from PySide6.QtCore import QRect

    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return

    class Screen:
        def availableGeometry(self):
            return QRect(0, 0, 1024, 700)

    monkeypatch.setattr("keyring.get_password", lambda *args: None)
    monkeypatch.setattr(MainWindow, "screen", lambda self: Screen())
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(10)
    assert window.width() <= 984
    assert window.height() <= 640
