"""Owner settings, native folder picking and queue actions for the shared Plan."""

from pathlib import Path

from PySide6.QtCore import QCoreApplication

from torrentlinker.catalogue import candidate
from torrentlinker.download_queue import enqueue
from torrentlinker.gui.settings_common import choose_directory
from torrentlinker.store import CatalogueRow
from torrentlinker.web.zen_preferences import ZenPreferences, snapshot


class PlanHost:
    def __init__(self, owner):
        self.owner = owner
        self.view = owner.zen_tab.plan_view
        self.view.configuration = self.configuration
        self.view.action = self.request
        self.view.cached_requested.connect(self.cached)

    def configuration(self) -> dict:
        settings = self.owner.settings
        return {
            "client_id": settings.active_client_id,
            "clients": [
                {"id": p.id, "name": p.name, "enabled": p.enabled} for p in settings.client_profiles
            ],
            "preferences": snapshot(settings),
            "destinations": dict(self.owner._plan_destinations),
        }

    def request(self, action: str, body: dict):
        settings = self.owner.settings
        if action == "queue":
            self.queue(body["plan"])
            return {"queued": sum(not item.candidate.reseed for item in body["plan"].items)}
        if action == "preferences":
            preferences = ZenPreferences.model_validate(body)
            preferences.apply(settings)
            settings.save(self.owner.settings_path)
            self.view.set_speed(settings.download_speed, settings.download_speed_tested)
            if preferences.model_fields_set - {"uploads", "download_speed"}:
                self.owner._plan_options_changed(settings.plan_options)
            self.owner.zen_tab.seeding_view.reload()
            return snapshot(settings)
        if action == "destinations":
            clients = body.get("client_ids", [])
            budgets = body.get("client_budgets", {})
            known = {p.id for p in settings.client_profiles if p.enabled}
            if not isinstance(clients, list) or not clients or set(clients) - known:
                raise ValueError("Choose enabled Torrent Clients for this Plan.")
            selected = {}
            for identifier in clients:
                amount = budgets.get(identifier, 0)
                if type(amount) is not int or amount < 0:
                    raise ValueError("Client budgets must be nonnegative byte counts.")
                selected[identifier] = amount
            if selected != self.owner._plan_destinations:
                self.owner._plan_destinations = selected
                self.owner._plan_options_changed(settings.plan_options)
            return None
        if action == "pick":
            return {
                "selected": choose_directory(
                    self.owner, QCoreApplication.translate("MainWindow", "Download Folder")
                )
            }
        client = body.get("client_id", settings.active_client_id)
        current = settings.for_client(client)
        category = body.get("category")
        if category is not None and (
            type(category) is not int or category not in settings.indexer_categories
        ):
            raise ValueError("Choose a known category.")
        if action == "folders":
            path = (
                current.download_folders.resolve(category, current.indexer_categories)
                if category is not None
                else current.download_folders.default
            )
            return {"path": str(path) if path else ""}
        if action == "save-folder":
            path = Path(body.get("path", "")).expanduser().resolve()
            if not body.get("path") or not path.is_dir():
                raise ValueError("Choose an existing Download Folder.")
            settings.capture_client()
            folders = [settings.profile(client).download_folders]
            if client == settings.active_client_id:
                folders.append(settings.download_folders)
            for target in folders:
                if category is None:
                    target.default = str(path)
                else:
                    target.by_category[category] = str(path)
            settings.save(self.owner.settings_path)
            self.owner.offer_plan_categories()
            self.owner._plan_options_changed(settings.plan_options)
            return {"saved": True}
        raise ValueError("Unknown Plan operation.")

    def cached(self) -> None:
        owner = self.owner
        if not owner._ensure_plan_download_folders():
            return
        owner.store.clear_plan()
        self.view.begin()
        owner.band.set_plan(None)
        owner._use_cached_plan = True
        owner._plan_refresh_failed = False
        if owner.catalogue_runner is not None:
            owner._pending_plan = lambda: owner._build_plan()
            owner._planning = True
            owner._stop_plan_fetch()
        else:
            owner._build_plan()

    def queue(self, plan) -> None:
        indexer = self.owner.indexer()
        for item in plan.items:
            row = item.candidate
            if row.reseed:
                continue
            if not isinstance(row.source, CatalogueRow) or row.folder is None:
                raise ValueError("This Plan row has no download destination.")
            client = row.client_id or self.owner.settings.active_client_id
            self.owner.settings.profile(client)
            enqueue(
                self.owner.store.for_client(client),
                indexer,
                candidate(indexer, row.source),
                row.folder,
            )
