from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from torrentlinker.config import Settings
from torrentlinker.gui.settings_dialog import SettingsDialog
from torrentlinker.gui.zen_view import PlanView


def test_editing_plan_size_keeps_focus_and_scroll(qtbot):
    view = PlanView()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(view)
    scroll.resize(620, 450)
    qtbot.addWidget(scroll)
    view.options_changed.connect(lambda _: view.invalidate())
    scroll.show()
    view.min_size.setValue(1)
    view.min_size.setFocus()
    qtbot.wait(20)
    before = (scroll.horizontalScrollBar().value(), scroll.verticalScrollBar().value())
    edit = view.min_size.lineEdit()
    edit.setSelection(0, 1)
    qtbot.keyClicks(edit, "4")
    qtbot.wait(20)
    assert view.min_size.hasFocus()
    assert (scroll.horizontalScrollBar().value(), scroll.verticalScrollBar().value()) == before
    assert view.min_size.value() == 4


def test_scrolling_over_focused_plan_size_does_not_change_value(qtbot):
    view = PlanView()
    qtbot.addWidget(view)
    view.show()
    box = view.min_size
    box.setValue(4)
    box.setFocus()
    wheel = QWheelEvent(
        QPointF(5, 5),
        QPointF(box.mapToGlobal(QPoint(5, 5))),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(box, wheel)
    assert box.value() == 4


def test_settings_save_fits_available_screen(qtbot):
    dialog = SettingsDialog(Settings(), secret_values={})
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)
    available = dialog.screen().availableGeometry()
    assert available.contains(dialog.frameGeometry())
    buttons = dialog.findChild(QDialogButtonBox)
    save = buttons.button(QDialogButtonBox.StandardButton.Save)
    assert available.contains(save.mapToGlobal(save.rect().bottomRight()))


def test_settings_uses_short_work_area_above_taskbar(qtbot, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QRect

    area = QRect(0, 0, 1366, 640)
    monkeypatch.setattr(
        SettingsDialog, "screen", lambda self: SimpleNamespace(availableGeometry=lambda: area)
    )
    dialog = SettingsDialog(Settings(), secret_values={})
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)
    assert dialog.height() <= area.height() - 60
    buttons = dialog.findChild(QDialogButtonBox)
    save = buttons.button(QDialogButtonBox.StandardButton.Save)
    assert dialog.rect().contains(save.mapTo(dialog, save.rect().bottomRight()))
