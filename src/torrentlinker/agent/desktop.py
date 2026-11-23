"""Loopback MCP server owned by the desktop process, sharing its settings and Store."""

from __future__ import annotations

import copy
import secrets
import socket
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from torrentlinker.agent.coordination import coordinator
from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret, set_secret
from torrentlinker.profile_workspace import ProfileWorkspace
from torrentlinker.store import Store
from torrentlinker.torrent_management import safe_error
from torrentlinker.web.operations import Operations
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup


class KeyringSecrets(ServerSecrets):
    def __init__(self):
        self.lock = threading.Lock()
        self.files: dict[str, Path] = {}
        self.seen: set[str] = set()

    @staticmethod
    def _key(name: str) -> str:
        # Desktop credentials predate the Web deployment secret names.
        if name.startswith("indexer-extra-key-"):
            suffix = name.removeprefix("indexer-extra-key-")
            if suffix in {"1", "2", "3", "4"}:
                return f"indexer-api-key-{int(suffix) + 1}"
        return name

    def get(self, name: str) -> str:
        value = get_secret(self._key(name))
        if value:
            with self.lock:
                self.seen.add(value)
        return value

    def update(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            set_secret(self._key(key), value)
            if value:
                with self.lock:
                    self.seen.add(value)

    def redact(self, text: str, *, public_urls: bool = False) -> str:
        if not text:
            return text
        with self.lock:
            for value in self.seen:
                text = text.replace(value, "[secret]")
        if public_urls:
            from torrentlinker.assistant.privacy import safe_content

            return safe_content(text)
        return safe_error(ValueError(text))


class DesktopSetup(Setup):
    def __init__(self, settings: Settings, path: Path, store: Store):
        from torrentlinker.clients import connect

        self.path, self.settings, self.store = path, copy.deepcopy(settings), store
        self._root = None
        self.marker = path.parent / "desktop.ready"
        self.configured = True  # ordinary client errors surface through the job
        self.secrets = KeyringSecrets()
        self.connector = connect
        self.lock = threading.RLock()
        self._folder_proofs = {}
        self._profile_workspace = ProfileWorkspace(path.parent)
        self._client = None
        self._indexer = None
        self._torznab = {}
        self.download_guard = None
        self.roots = ()
        self.download_folder_changes: list[tuple[str, int | None, str, str]] = []
        self._folder_candidate: Path | None = None

    def _refresh_roots(self) -> None:
        roots = [f.path for f in self.settings.library_folders]
        for profile in self.settings.client_profiles:
            folders = profile.download_folders
            roots.extend(Path(p) for p in [folders.default, *folders.by_category.values()] if p)
        roots.extend(Path(m.local) for m in self.settings.path_mappings)
        if candidate := getattr(self, "_folder_candidate", None):
            roots.append(candidate)
        self.roots = tuple(p.resolve() for p in roots)

    def snapshot(self) -> dict[str, Any]:
        self._refresh_roots()
        return super().snapshot()

    def suggest_mappings(self) -> dict[str, Any]:
        from dataclasses import asdict

        from torrentlinker.paths import detect_mappings

        self._refresh_roots()
        client = self.client()
        found = detect_mappings(
            client.torrents(with_files=False),
            self.roots,
            files=lambda torrent: client.files(torrent.hash),
        )
        # Desktop owners may choose local folders outside existing storage roots.
        # This only proposes paths; saving still verifies the selected mapping.
        return {
            "suggestions": [asdict(suggestion) for suggestion in found.suggestions],
            "same_paths": found.same_paths,
            "not_found": found.not_found,
        }

    def path_under_root(self, value: str, *, directory: bool = True) -> Path:
        self._refresh_roots()
        return super().path_under_root(value, directory=directory)

    def local_client(self) -> bool:
        from urllib.parse import urlsplit

        from torrentlinker.config import CLIENT_FIELDS

        host = urlsplit(getattr(self.settings, CLIENT_FIELDS[self.settings.client]).host).hostname
        return host in {"localhost", "127.0.0.1", "::1"} and not self.settings.path_mappings

    def configure_download_folder(
        self,
        local: str,
        category: int | None = None,
        client_path: str = "",
        *,
        save: bool = False,
        probe: bool = True,
    ) -> dict[str, Any]:
        import os

        with self.lock:
            if category is not None and category not in self.settings.indexer_categories:
                raise ValueError("Choose a known Indexer category or subcategory.")
            # The owner may select a new desktop directory. This temporary candidate
            # authorizes validation only; it does not register a root or mapping.
            self._folder_candidate = Path(local)
            try:
                path = self.path_under_root(local)
                checked: dict[str, Any]
                if self.local_client():
                    if client_path and client_path != str(path):
                        raise ValueError(
                            "Use this computer's exact path for a local Torrent Client."
                        )
                    with os.scandir(path) as children:
                        next(children, None)
                    if not os.access(path, os.W_OK):
                        raise ValueError("The Download Folder is not writable. Check permissions.")
                    checked = {
                        "local": str(path),
                        "client": str(path),
                        "sample": None,
                        "readable": True,
                        "warning": "",
                        "category": category,
                    }
                else:
                    checked = super().configure_download_folder(
                        local, category, client_path, save=False, probe=probe
                    )
            finally:
                self._folder_candidate = None
            if save:
                folders = self.settings.download_folders
                old = folders.default if category is None else folders.by_category.get(category, "")
                if category is None:
                    folders.default = checked["local"]
                else:
                    folders.by_category[category] = checked["local"]
                self.save()
                root = self._root or self
                assert isinstance(root, DesktopSetup)
                root.download_folder_changes.append(
                    (self.settings.active_client_id, category, old, checked["local"])
                )
            return {**checked, "saved": save}

    def verified_download_folder(self, category: int | None = None) -> Path:
        folder = self.download_folder(category)
        if self.local_client():
            return self.path_under_root(str(folder) if folder else "")
        return super().verified_download_folder(category)

    def apply_download_folder_changes(self, settings: Settings) -> None:
        """Merge only approved folder edits back into the GUI's live settings."""
        with self.lock:
            settings.capture_client()
            while self.download_folder_changes:
                identifier, category, old, value = self.download_folder_changes.pop(0)
                try:
                    profile = settings.profile(identifier)
                except ValueError:
                    continue
                targets = [profile.download_folders]
                if identifier == settings.active_client_id:
                    targets.append(settings.download_folders)
                for folders in targets:
                    current = (
                        folders.default
                        if category is None
                        else folders.by_category.get(category, "")
                    )
                    if current not in {old, value}:
                        continue  # A later explicit owner edit takes precedence.
                    if category is None:
                        folders.default = value
                    else:
                        folders.by_category[category] = value


class DesktopOperations(Operations):
    def run(self, request, stop, progress):
        progress({"message": "Waiting for desktop operations to finish."})
        with coordinator.agent(stop):
            return super().run(request, stop, progress)


class DesktopServer:
    def __init__(
        self,
        settings: Settings,
        path: Path,
        store: Store,
        *,
        port: int = 8790,
        workspace: ProfileWorkspace | None = None,
    ):
        self.setup = DesktopSetup(settings, path, store)
        if workspace is not None:
            self.setup._profile_workspace = workspace

        def creation(action, values):
            from torrentlinker.community_site import community_site

            return community_site(self.setup).request(action, values)

        self.setup._profile_workspace.creation_handler = creation
        self.directory = path.parent
        self.server: Any = None
        self.thread: threading.Thread | None = None
        self.app: Any = None
        self.pending_settings = False
        self.settings_edit_depth = 0
        self.port = port
        self.url = f"http://127.0.0.1:{port}/mcp/"

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        import uvicorn

        from torrentlinker.web.app import create_app

        listener = socket.socket()
        try:
            listener.bind(("127.0.0.1", self.port))
            listener.listen(128)
            self.url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp/"
            self.app = create_app(
                self.directory,
                password=secrets.token_urlsafe(32),
                service_override=self.setup,
                operation_factory=DesktopOperations,
                monitor_verifications=False,
            )
            # The Windows GUI executable has no stdout/stderr. Keep the desktop's
            # file logging instead of Uvicorn's console formatter and handlers.
            self.server = uvicorn.Server(
                uvicorn.Config(self.app, access_log=False, log_level="warning", log_config=None)
            )
        except Exception:
            listener.close()
            if self.app is not None:
                self.app.state.assistant.close()
                self.service.jobs.close()
                self.service.media.close()
                self.service.access.db.close()
                self.app = None
            raise
        server = self.server

        def run():
            try:
                server.run(sockets=[listener])
            finally:
                listener.close()

        self.thread = threading.Thread(target=run, daemon=True, name="desktop-mcp")
        self.thread.start()

    def reset(self, settings: Settings) -> None:
        self.setup._folder_proofs.clear()
        if self.app is None:
            self.setup.settings = copy.deepcopy(settings)
            self.setup.store = self.setup.store.for_client(settings.active_client_id)
            return
        with self.service.jobs.lock:
            if self.service.jobs.active():
                raise ValueError("Wait for agent jobs before changing clients.")
            self.setup.settings = copy.deepcopy(settings)
            self.setup.store = self.setup.store.for_client(settings.active_client_id)
            self.setup._client = None
            self.setup._indexer = None
            self.app.state.reset_clients()

    def busy(self) -> bool:
        if self.app is None:
            return False
        if not self.service.jobs.lock.acquire(blocking=False):
            return True
        try:
            return self.service.jobs.active()
        finally:
            self.service.jobs.lock.release()

    @contextmanager
    def editing_settings(self):
        if not self.service.jobs.lock.acquire(blocking=False):
            raise ValueError("Wait for agent jobs before changing settings.")
        try:
            if self.service.jobs.active():
                raise ValueError("Wait for agent jobs before changing settings.")
            self.settings_edit_depth += 1
            self.service.suspended = True
        finally:
            self.service.jobs.lock.release()
        try:
            yield
        finally:
            self.settings_edit_depth -= 1
            self.service.suspended = bool(self.settings_edit_depth or self.pending_settings)

    def sync(self, settings: Settings) -> None:
        """GUI-thread refresh after profile, folder or Plan preferences change."""
        if self.app is None:
            return
        self.setup.apply_download_folder_changes(settings)
        # These are the only owners of suspension. Repair a stale legacy flag
        # without unlocking an active editor or a deferred settings update.
        self.service.suspended = bool(self.settings_edit_depth or self.pending_settings)
        if self.setup.settings == settings and not self.pending_settings:
            return
        if not self.service.jobs.lock.acquire(blocking=False):
            return
        try:
            if self.settings_edit_depth:
                return
            if self.service.jobs.active():
                self.service.suspended = True
                self.pending_settings = True
                return
            self.reset(settings)
            if self.pending_settings:
                self.service.suspended = False
                self.pending_settings = False
        finally:
            self.service.jobs.lock.release()

    @property
    def service(self):
        if self.app is None:
            raise ValueError("Start Agent access first.")
        return self.app.state.agent_service

    def close(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.app is not None:
            assistant = self.app.state.assistant
            assistant.shutdown.set()
            for stop in list(assistant.stops.values()):
                stop.set()
            for job in self.service.jobs.list():
                if job["status"] in {"queued", "running"}:
                    self.service.jobs.cancel(job["id"])
        if self.thread is not None:
            self.thread.join(timeout=3)


def agent_settings_change(fn):
    """Make the whole desktop settings transaction unavailable to agent submissions."""

    @wraps(fn)
    def guarded(window, *args, **kwargs):
        runtime = window.agent_runtime
        if runtime is None or runtime.app is None:
            return fn(window, *args, **kwargs)
        try:
            runtime.sync(window.settings)
            with runtime.editing_settings():
                return fn(window, *args, **kwargs)
        except ValueError as error:
            window.shell_host.refresh()
            window.statusBar().showMessage(window.tr(str(error)))

    return guarded
