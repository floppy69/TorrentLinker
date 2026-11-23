"""Folder explorer shared by Library navigation and its inline folder editor."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.gui.library_folder_dialog import grouping, grouping_box
from torrentlinker.gui.settings_common import choose_directory, kind_label, offered_kinds
from torrentlinker.gui.workspace_tabs import WorkspaceTabs
from torrentlinker.scan import ScanError


class FolderEditor(QWidget):
    """Edit registered Library Folders without altering downloads or Path Mappings."""

    def __init__(
        self, folders: list[LibraryFolder], parent: QWidget | None = None, *, adult: bool = False
    ):
        super().__init__(parent)
        self.adult = adult
        layout = QVBoxLayout(self)
        note = QLabel(
            self.tr(
                "Register the folders TorrentLinker can read. Add as many as you need. "
                "Download destinations and Torrent Client Path Mappings are configured separately."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.scan_errors: list[ScanError] = []
        self.scanned = False
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Library Folder"),
                self.tr("Content Kind"),
                self.tr("Scan grouping"),
                self.tr("File access"),
            ]
        )
        self.table.setColumnWidth(0, 430)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 250)
        layout.addWidget(self.table, 1)
        self.path = QLineEdit()
        self.path.setPlaceholderText(self.tr("Type a folder path"))
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        browse = QPushButton(self.tr("Browse…"))
        browse.clicked.connect(self.browse)
        add = QPushButton(self.tr("Add folder"))
        add.clicked.connect(self.add_typed)
        self.path.returnPressed.connect(self.add_typed)
        remove = QPushButton(self.tr("Remove selected"))
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        for button in (browse, add, remove):
            row.addWidget(button)
        layout.addLayout(row)
        hint = QLabel(
            self.tr(
                "Automatic finds releases, season packs and their episodes at any depth. "
                "Choose a depth only when a folder needs it: depth 1 makes each direct child "
                "one Local Item. Removing a folder here keeps all files on disk."
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.set_folders(folders)

    def set_folders(self, folders: list[LibraryFolder]) -> None:
        self.table.setRowCount(0)
        for folder in folders:
            self.add_folder(folder)
        self.set_scan_errors(self.scan_errors, self.scanned)

    def add_folder(self, folder: LibraryFolder) -> None:
        if any(str(f.path) == str(folder.path) for f in self.folders()):
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        cell = QTableWidgetItem(str(folder.path))
        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, cell)
        kind = QComboBox()
        for value in offered_kinds(self.adult, folder.kind):
            kind.addItem(kind_label(value), value)
        kind.setCurrentIndex(kind.findData(folder.kind))
        self.table.setCellWidget(row, 1, kind)
        self.table.setCellWidget(row, 2, grouping_box(folder.depth))
        self.set_scan_errors(self.scan_errors, self.scanned)

    def set_scan_errors(self, errors: list[ScanError], scanned: bool = True) -> None:
        self.scan_errors, self.scanned = list(errors), scanned
        for row in range(self.table.rowCount()):
            path = self.table.item(row, 0)
            if path is None:
                continue
            folder = Path(path.text())
            failures = [
                e
                for e in errors
                if e.path == folder or folder in e.path.parents or e.path in folder.parents
            ]
            text = (
                self.tr("Scan incomplete · previous items kept")
                if failures
                else (self.tr("Last scan readable") if scanned else self.tr("Not scanned"))
            )
            cell = QTableWidgetItem(text)
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cell.setToolTip("\n".join(f"{e.path}: {e.message}" for e in failures))
            self.table.setItem(row, 3, cell)

    def folders(self) -> list[LibraryFolder]:
        result = []
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            kind, depth = self.table.cellWidget(row, 1), self.table.cellWidget(row, 2)
            assert cell and isinstance(kind, QComboBox) and isinstance(depth, QSpinBox)
            result.append(
                LibraryFolder(Path(cell.text()), grouping(depth), ContentKind(kind.currentData()))
            )
        return result

    def browse(self) -> None:
        if path := choose_directory(self, self.tr("Library Folder"), self.path.text()):
            self.path.setText(path)
            self.add_typed()

    def add_typed(self) -> None:
        value = self.path.text().strip()
        if not value:
            return
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            QMessageBox.warning(self, self.tr("Library Folder"), self.tr("Folder is unavailable."))
            return
        self.add_folder(LibraryFolder(path, None))  # Automatic until the user picks a depth
        self.path.clear()


class LibraryWorkspace(QWidget):
    def __init__(self, window, toolbar, matches):
        super().__init__()
        self.owner = window
        self.scan_errors: list[ScanError] = []
        self.scanned = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setProperty("ownsScrolling", True)
        self.sections = WorkspaceTabs()
        self.sections.setObjectName("librarySections")
        self.sections.setDocumentMode(True)
        layout.addWidget(self.sections)
        from torrentlinker.gui.reseed_workspace import ReseedBoard

        self.reseed = ReseedBoard(window)
        self.sections.addTab(self.reseed, self.tr("Reseed"))
        self.sections.currentChanged.connect(
            lambda _index: (
                self.reseed.refresh() if self.sections.currentWidget() is self.reseed else None
            )
        )
        # The guided view owns navigation. Keep the advanced comparison tools in
        # a dialog, rather than a second Library landing page.
        self.sections.tabBar().hide()
        self.sections.setCurrentWidget(self.reseed)
        self.toolbar, self.matches = toolbar, matches
        self.review_dialog = None
        window.review.setParent(self)
        window.review.hide()
        window.review.expand_button.hide()
        window.statusBar().messageChanged.connect(self.record_activity)

    def open_folders(self):
        if self.review_dialog:
            self.review_dialog.accept()
        self.reseed.requested_tab = "folders"
        self.reseed.refresh()

    def refresh(self):
        self.reseed.refresh_rows()

    def record_activity(self, message: str) -> None:
        if message:
            import time

            self.reseed.activity.append({"at": time.time(), "name": "", "message": message})
            self.reseed.activity[:] = self.reseed.activity[-300:]

    def set_scan_errors(self, errors: list[ScanError]) -> None:
        self.scan_errors = list(errors)
        self.scanned = True
        self.reseed.scan_errors = [str(e.path) for e in errors]
        self.refresh()
