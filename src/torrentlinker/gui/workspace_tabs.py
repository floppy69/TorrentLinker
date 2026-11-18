"""Do not propagate hidden native pages' minimum sizes into bundled workspaces."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QTabWidget


class WorkspaceTabs(QTabWidget):
    def minimumSizeHint(self):
        if self.currentWidget() and self.currentWidget().property("ownsScrolling"):
            return QSize(0, 0)
        return super().minimumSizeHint()
