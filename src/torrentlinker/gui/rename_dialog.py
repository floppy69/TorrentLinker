"""Review torrent-client path changes without growing beyond the screen."""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class RenameDialog(QDialog):
    def __init__(self, renames: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Rename inside the torrent"))
        available = self.screen().availableGeometry()
        self.resize(
            min(900, int(available.width() * 0.9)), min(480, int(available.height() * 0.85))
        )
        layout = QVBoxLayout(self)
        message = QLabel(
            self.tr(
                "These files will be renamed inside your torrent client to match yours "
                "(your files are not touched):"
            )
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        self.files = QTableWidget(len(renames), 2)
        self.files.setHorizontalHeaderLabels([self.tr("Path in torrent"), self.tr("Local path")])
        self.files.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.files.setWordWrap(False)
        for column in range(2):
            self.files.setColumnWidth(column, 400)
        for row, paths in enumerate(sorted(renames.items())):
            for column, path in enumerate(paths):
                cell = QTableWidgetItem(path)
                cell.setToolTip(path)
                self.files.setItem(row, column, cell)
        layout.addWidget(self.files, 1)
        buttons = QDialogButtonBox()
        yes = buttons.addButton(self.tr("&Yes"), QDialogButtonBox.ButtonRole.AcceptRole)
        no = buttons.addButton(self.tr("&No"), QDialogButtonBox.ButtonRole.RejectRole)
        yes.setAutoDefault(False)
        no.setDefault(True)
        no.setFocus()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Native button mnemonics vary by platform. Also support the plain letter
        # shown in the current language, even while the path table has focus.
        for key, action in ((self.tr("Y"), self.accept), (self.tr("N"), self.reject)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(action)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Qt positions modal windows relative to their parent. Fit the decorated
        # frame after that placement, including off-screen parents and taskbars.
        QTimer.singleShot(0, self._fit_position)

    def _fit_position(self) -> None:
        area = self.screen().availableGeometry()
        frame = self.frameGeometry()
        self.move(
            max(area.left(), min(frame.left(), area.right() - frame.width() + 1)),
            max(area.top(), min(frame.top(), area.bottom() - frame.height() + 1)),
        )
