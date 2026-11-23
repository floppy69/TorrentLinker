"""Desktop navigation and client ownership behind the shared application shell."""

from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QDialog, QVBoxLayout

from torrentlinker import i18n
from torrentlinker.gui.shell_view import WORKSPACES, ShellView
from torrentlinker.gui.theme import set_theme


class ShellHost:
    def __init__(self, owner):
        self.owner = owner
        self.help_dialog = None

    def page(self):
        owner = self.owner
        index = owner.tabs.currentIndex()
        if owner.tabs.currentWidget() is getattr(owner, "_settings_page", None):
            return "setup"
        if 0 <= index < len(WORKSPACES):
            return WORKSPACES[index]
        if (
            owner.documentation_tab is not None
            and owner.tabs.currentWidget() is owner.documentation_tab
        ):
            return "documentation"
        return "reading"

    def snapshot(self):
        owner = self.owner
        return {
            "page": self.page(),
            "pages": [
                *WORKSPACES,
                *(["reading"] if owner._reader_unlocked else []),
                "documentation",
                "setup",
            ],
            "shortcuts": WORKSPACES,
            "language": i18n.pick_language(owner.settings.language),
            "theme_choice": owner.settings.theme,
            "clients": [
                {"id": row.id, "name": row.name}
                for row in owner.settings.client_profiles
                if row.enabled
            ],
            "client_id": "all" if owner.aggregate_clients else owner.settings.active_client_id,
            "allow_all": self.page() == "torrents",
            "setup_needed": owner.setup_needed,
            "profile_notice": owner.band.profile_notice if owner.band.isVisible() else "",
            "compact": owner.width() < 650,
        }

    def refresh(self):
        for name in ("navigation", "app_header"):
            view = getattr(self.owner, name, None)
            if isinstance(view, ShellView):
                view.refresh()

    def command(self, action, values):
        owner = self.owner
        if action == "navigate":
            page = values.get("view")
            if page in WORKSPACES:
                owner.tabs.setCurrentIndex(WORKSPACES.index(page))
            elif page == "documentation":
                owner._open_documentation()
            elif page == "reading" and owner._reader_unlocked:
                owner._open_reading_room()
            elif page == "setup":
                owner.open_settings()
            else:
                raise ValueError("Unknown workspace.")
        elif action == "client":
            identifier = values.get("client_id")
            if identifier == "all":
                if self.page() != "torrents":
                    raise ValueError("All clients is available in Torrents.")
                owner.aggregate_clients = True
                owner.torrents_tab.refresh()
            elif identifier in {row.id for row in owner.settings.client_profiles if row.enabled}:
                if identifier == owner.settings.active_client_id:
                    owner.aggregate_clients = False
                    owner.torrents_tab.refresh()
                else:
                    owner._select_client(identifier)
            else:
                raise ValueError("Unknown target client.")
        elif action == "theme":
            value = values.get("value")
            if value not in {"auto", "light", "dark"}:
                raise ValueError("Unknown theme.")
            owner.settings.theme = value
            owner.settings.save(owner.settings_path)
            set_theme(value)
        elif action == "language":
            language = values.get("value")
            if language not in {"en", "fr"}:
                raise ValueError("Unknown language.")
            if QThreadPool.globalInstance().activeThreadCount() or (
                owner.agent_runtime and owner.agent_runtime.busy()
            ):
                raise ValueError("Wait for the current operation before changing language.")
            owner._change_language(language)
        elif action == "shortcuts":
            dialog = QDialog(owner)
            dialog.setWindowTitle(
                "Raccourcis clavier"
                if i18n.pick_language(owner.settings.language) == "fr"
                else "Keyboard shortcuts"
            )
            dialog.resize(470, 440)
            view = ShellView(
                "help",
                self.snapshot,
                lambda action, values: dialog.close(),
                language=owner.settings.language,
            )
            layout = QVBoxLayout(dialog)
            layout.addWidget(view)
            self.help_dialog = dialog
            dialog.show()
        else:
            raise ValueError("Unknown shell action.")
        self.refresh()
