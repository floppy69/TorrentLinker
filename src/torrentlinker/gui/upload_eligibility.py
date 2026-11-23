"""Library-to-Upload eligibility without constructing a second Upload interface."""

from contextlib import nullcontext

from PySide6.QtCore import QCoreApplication, QObject

from torrentlinker.upload import PROFILES, default_category


class UploadEligibility(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.entries = []
        self.searched = {}
        self.entry = None

    def set_entries(self, entries):
        self.entries = list(entries)

    def remember(self, entry, checked):
        self.searched[entry.item.path] = checked

    def why_not(self, entry):
        if default_category(entry.folder.kind) not in PROFILES:
            return QCoreApplication.translate("UploadTab", "Choose a category")
        checked = self.searched.get(entry.item.path)
        if checked is None:
            return QCoreApplication.translate(
                "UploadTab", "Search it first: c411 may already have it"
            )
        if any(value.match for value in checked):
            return QCoreApplication.translate(
                "UploadTab", "c411 already has it: Reseed it from the Library"
            )
        return None

    def select(self, path):
        self.entry = next((e for e in self.entries if e.item.path == path), None)
        self.owner.upload_workspace.focus_source(str(path))

    def defer_refresh(self):
        return nullcontext()

    def throttle_refresh(self, on):
        pass  # This controller never renders rows.

    def refresh_drafts(self):
        self.owner.upload_workspace.refresh()
