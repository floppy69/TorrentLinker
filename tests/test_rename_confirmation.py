import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QTableWidget

from torrentlinker import i18n
from torrentlinker.gui.review_panel import ReviewPanel
from torrentlinker.matching import MatchRules
from torrentlinker.store import Store

# conftest dismisses unexpected message boxes. Exercise the real modal UI here.
QUESTION = QMessageBox.question


def panel_for(qtbot, tmp_path):
    panel = ReviewPanel(
        Store(tmp_path / "state.db"),
        lambda: None,
        lambda: None,
        MatchRules,
        lambda: None,
        lambda entry: "",
    )
    qtbot.addWidget(panel)
    panel.show()
    return panel


@pytest.mark.parametrize("parent_offset", [None, (1500, 1000)])
def test_long_rename_confirmation_keeps_buttons_visible_and_every_path_reviewable(
    qtbot, tmp_path, monkeypatch, parent_offset
):
    monkeypatch.setattr(QMessageBox, "question", QUESTION)
    panel = panel_for(qtbot, tmp_path)
    if parent_offset:
        panel.move(*parent_offset)
    renames = {
        f"Horace.and.Pete.2016.S01.VOSTFR.1080p.WEB-DL.AAC2.0.x264-PROPER/"
        f"Horace.and.Pete.2016.S01E{i:02}.VOSTFR.1080p.WEB-DL.AAC2.0.x264-PROPER.mkv": (
            f"Horace.and.Pete.S01.VOSTFR/Horace.and.Pete.S01E{i:02}.VOSTFR.PROPER.1080p.mkv"
        )
        for i in range(1, 51)
    }
    observed = {}

    def inspect():
        dialog = QApplication.activeModalWidget()
        observed["fits"] = dialog.screen().availableGeometry().contains(dialog.frameGeometry())
        observed["geometry"] = (dialog.frameGeometry(), dialog.screen().availableGeometry())
        observed["buttons"] = all(
            dialog.rect().contains(button.mapTo(dialog, button.rect().bottomRight()))
            for button in dialog.findChildren(QPushButton)
        )
        tables = dialog.findChildren(QTableWidget)
        observed["paths"] = [
            (table.item(row, 0).text(), table.item(row, 1).text())
            for table in tables
            for row in range(table.rowCount())
        ]
        dialog.reject()

    QTimer.singleShot(50, inspect)
    assert not panel._confirm_renames(renames)
    assert observed["fits"], observed["geometry"]
    assert observed["buttons"]
    assert observed["paths"] == sorted(renames.items())


@pytest.mark.parametrize("table_focus", [False, True])
@pytest.mark.parametrize(
    "language,key,approved",
    [
        ("en", Qt.Key.Key_Y, True),
        ("fr", Qt.Key.Key_O, True),
        ("en", Qt.Key.Key_N, False),
        ("fr", Qt.Key.Key_N, False),
        ("en", Qt.Key.Key_Return, False),
        ("fr", Qt.Key.Key_Return, False),
        ("en", Qt.Key.Key_Escape, False),
        ("fr", Qt.Key.Key_Escape, False),
    ],
)
def test_rename_confirmation_keyboard(
    qtbot, qapp, tmp_path, monkeypatch, language, key, approved, table_focus
):
    monkeypatch.setattr(QMessageBox, "question", QUESTION)
    previous = qapp.property("language")
    translators = i18n.install(qapp, language)
    try:
        panel = panel_for(qtbot, tmp_path)
        observed = {}

        def press():
            dialog = QApplication.activeModalWidget()
            if table_focus:
                dialog.findChild(QTableWidget).setFocus()
            qtbot.keyClick(dialog.focusWidget() or dialog, key)
            observed["closed"] = not dialog.isVisible()
            # A broken shortcut must fail instead of leaving an unattended modal open.
            if dialog.isVisible():
                dialog.reject()

        QTimer.singleShot(50, press)
        assert panel._confirm_renames({"Héros.mkv": "Mon.Héros.mkv"}) is approved
        assert observed["closed"], "the key must close the dialog without the test's fallback"
    finally:
        for translator in translators:
            qapp.removeTranslator(translator)
        qapp.setProperty("language", previous)
