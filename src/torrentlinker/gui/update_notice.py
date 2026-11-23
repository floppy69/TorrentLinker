"""A quiet, dismissible notice linking to a newer release."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from torrentlinker.gui.shell_view import ShellView
from torrentlinker.updates import Release


class UpdateNotice(ShellView):
    def __init__(self, language="en") -> None:
        self.release: Release | None = None
        self._dismissed: str | None = None
        super().__init__("update", self._snapshot, self._command, language=language)
        self.setObjectName("updateNotice")
        self.hide()

    def _snapshot(self):
        return {
            "language": self.language,
            "release": {"tag": self.release.tag} if self.release else None,
        }

    def _command(self, action, values):
        if action == "release" and self.release:
            QDesktopServices.openUrl(QUrl(self.release.url))
        elif action == "dismiss":
            if self.release:
                self._dismissed = self.release.tag
            self.hide()

    def show_release(self, release: Release | None) -> None:
        if release is None or release.tag == self._dismissed:
            return
        self.release = release
        self.refresh()
        self.show()
