"""A local preview; opening GitHub is an explicit user action."""

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout

from torrentlinker.crash_reports import exception_draft

_open_dialogs: set[QDialog] = set()


def offer_report(error: BaseException, *, modal: bool = True) -> None:
    draft = exception_draft(error)
    dialog = QDialog()
    dialog.setWindowTitle(QCoreApplication.translate("CrashReport", "Report the problem"))
    dialog.resize(720, 520)
    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            QCoreApplication.translate(
                "CrashReport", "Review the sanitized draft. Nothing is sent automatically."
            )
        )
    )
    preview = QPlainTextEdit(draft["body"])
    preview.setReadOnly(True)
    layout.addWidget(preview)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    opening = buttons.addButton(
        QCoreApplication.translate("CrashReport", "Open GitHub draft"),
        QDialogButtonBox.ButtonRole.ActionRole,
    )
    opening.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(draft["url"])))
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if modal:
        dialog.exec()
    else:
        for previous in tuple(_open_dialogs):
            previous.close()
        _open_dialogs.add(dialog)
        dialog.finished.connect(lambda _: _open_dialogs.discard(dialog))
        dialog.show()
