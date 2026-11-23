"""Guided setup: connection tests, folder discovery and explicit storage access."""

from __future__ import annotations

import copy
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from torrentlinker import indexer_hub, net
from torrentlinker.clients import connect
from torrentlinker.config import C411_ID, HUB_SECRET, IndexerSettings, ProxySettings, Settings
from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping, TorrentClient
from torrentlinker.indexer import Caps, Indexer
from torrentlinker.library import known_files
from torrentlinker.login_guard import LoginRefused
from torrentlinker.paths import PathMapper
from torrentlinker.profile_history import ProfileHistory
from torrentlinker.profile_workspace import ProfileWorkspace
from torrentlinker.qbit import ClientApi
from torrentlinker.store import Store
from torrentlinker.torznab import TorznabIndexer
from torrentlinker.web.security import ServerSecrets

Connector = Callable[..., ClientApi]


class StorageUnavailableError(ValueError):
    """A configured storage path could not be read, rather than rejected for safety."""


CLIENT_SETTINGS = {
    "qbittorrent": "qbit",
    "deluge": "deluge",
    "transmission": "transmission",
    "utorrent": "utorrent",
    "bittorrent": "utorrent",
    "rtorrent": "rtorrent",
}


CLIENT_ADDRESS = (
    "Client address: enter for example http://192.168.0.50:8080, "
    "without user name, password, query or fragment."
)
CLIENT_PORT = "Client address: the port must be between 1 and 65535."
INDEXER_ADDRESS = (
    "Indexer address: enter a full address such as https://c411.org/api/torznab, "
    "without user name, password, query or fragment."
)
SCGI_ADDRESS = (
    "Client address: enter rTorrent's SCGI address as scgi://host:port, "
    "for example scgi://192.168.0.50:5000."
)
SCGI_ONLY_RTORRENT = "Client address: scgi:// is only for rTorrent; use http://host:port."


def http_url(value: str) -> str:
    return _url(value, {"http", "https"}, INDEXER_ADDRESS)


def with_scheme(value: str) -> str:
    """A client address typed as host, host:port or [ipv6]:port is an http:// one."""
    value = value.strip()
    if value and "://" not in value:
        return "http://" + value
    return value


def _url(value: str, schemes: set[str], hint: str = INDEXER_ADDRESS) -> str:
    port_hint = CLIENT_PORT if hint == CLIENT_ADDRESS else hint
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError:
        raise ValueError(port_hint) from None
    if (
        parsed.scheme not in schemes
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(hint)
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(port_hint)
    return value.rstrip("/")


class Connection(BaseModel):
    client_id: str = ""
    name: str = Field(default="", max_length=100)
    client: TorrentClient
    host: str = Field(max_length=2048)
    username: str = Field(default="", max_length=256)
    password: str | None = Field(default=None, max_length=4096)
    api_key: str | None = Field(default=None, max_length=4096)
    # The user agreed to untick Transmission's "Append .part to incomplete files' names".
    turn_off_partial_names: bool = False

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        # rTorrent's SCGI port is reached over TCP only here, never a socket path.
        value = with_scheme(value)
        hint = SCGI_ADDRESS if value.lower().startswith("scgi:") else CLIENT_ADDRESS
        return _url(value, {"http", "https", "scgi"}, hint)

    @model_validator(mode="after")
    def scgi_for_rtorrent(self) -> Connection:
        if self.host.startswith("scgi:") and self.client is not TorrentClient.RTORRENT:
            raise ValueError(SCGI_ONLY_RTORRENT)
        if self.host.startswith("scgi:") and urlsplit(self.host).port is None:
            raise ValueError(SCGI_ADDRESS)
        return self


class PartialNamesRefused(ValueError):
    """Transmission is reachable but would rename files to .part; the user can let us fix it."""

    action = "turn_off_partial_names"


class KeptKey(BaseModel):
    """An additional API key left as saved: the number of its stored slot, 1 to 4."""

    keep: int = Field(ge=1, le=4)


class IndexerConnection(BaseModel):
    url: str = "https://c411.org/api/torznab"
    api_key: str | None = Field(default=None, max_length=4096)
    # Each entry is a key typed in, or a KeptKey standing for a saved one the page never read.
    extra_keys: list[str | KeptKey] | None = Field(default=None, max_length=4)

    @field_validator("extra_keys")
    @classmethod
    def valid_extra_keys(cls, values: list[str | KeptKey] | None) -> list[str | KeptKey] | None:
        if values is None:
            return None
        if any(isinstance(key, str) and len(key) > 4096 for key in values):
            raise ValueError("API key too long.")
        return [key.strip() if isinstance(key, str) else key for key in values]

    _url = field_validator("url")(http_url)


class IndexerEntry(BaseModel):
    """An Indexer added by hand: a Torznab URL and its API key, kept as a secret."""

    name: str = Field(default="", max_length=100)
    url: str = ""
    api_key: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None

    _url = field_validator("url")(lambda value: http_url(value) if value else value)


class IndexerHubEntry(BaseModel):
    """A Prowlarr or Jackett instance: its address and API key (kept as a secret)."""

    service: Literal["prowlarr", "jackett"]
    url: str
    api_key: str | None = Field(default=None, max_length=4096)

    _url = field_validator("url")(http_url)


class IndexerHubImport(BaseModel):
    ids: list[str] = Field(max_length=1000)


class CrossSeedRules(BaseModel):
    """What Cross-seed adds without a review, and its pause."""

    auto_add: bool | None = None
    threshold: float | None = Field(default=None, ge=0.5, le=1.0)
    paused: bool | None = None


def mode_names(caps: Caps) -> dict[str, list[str]]:
    return {mode.value: sorted(params) for mode, params in caps.modes.items()}


class ProxySetup(BaseModel):
    address: str = Field(default="", max_length=2048)
    username: str = Field(default="", max_length=256)
    password: str | None = Field(default=None, max_length=4096)
    torrent_client: bool = False

    @field_validator("address")
    @classmethod
    def valid_address(cls, value: str) -> str:
        if value:
            parsed = urlsplit(value)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Enter proxy credentials in their separate fields.")
            net.proxy_url(value)
        return value


class FolderRemoval(BaseModel):
    client_id: str = ""
    local: str = Field(max_length=4096)
    purpose: Literal["library", "download"] = "library"
    category: int | None = None


class FolderSetup(FolderRemoval):
    original_local: str = Field(default="", max_length=4096)
    client_path: str = Field(default="", max_length=4096)
    kind: ContentKind = ContentKind.OTHER
    depth: int | None = Field(default=1, ge=0, le=10)  # None: Automatic


class Setup:
    def __init__(
        self,
        directory: Path,
        roots: tuple[Path, ...],
        secrets: ServerSecrets,
        connector: Connector = connect,
    ):
        self.path = directory / "settings.json"
        self.settings = Settings.load(self.path)
        self.settings.ensure_profiles()
        self._root: Setup | None = None
        self.marker = directory / "client.ready"
        self.configured = self.marker.exists()
        self.roots = tuple(p.resolve(strict=True) for p in roots)
        if any(
            not p.is_dir()
            or directory.resolve().is_relative_to(p)
            or p.is_relative_to(directory.resolve())
            for p in self.roots
        ):
            raise ValueError("Storage roots must be directories separate from configuration.")
        self.secrets = secrets
        self.connector = connector
        self.lock = threading.RLock()
        self._folder_proofs: dict[tuple, float] = {}
        self.download_guard: Callable[[bytes, str], None] | None = None
        self._client: ClientApi | None = None
        self._indexer: Indexer | None = None
        self._torznab: dict[str, tuple[tuple[str, str], TorznabIndexer]] = {}
        self.store = Store(directory / "catalogue.sqlite").for_client(
            self.settings.active_client_id
        )
        self._profile_workspace = ProfileWorkspace(directory, history=ProfileHistory(self.store))
        proxy = self.settings.proxy
        net.configure(
            net.proxy_url(proxy.address, proxy.username, self.secrets.get("proxy-password")),
            proxy.torrent_client,
        )

    def profile_workspace(self) -> ProfileWorkspace:
        root = self._root or self
        root._profile_workspace.bind(root.settings.indexer.url, root.secrets.get("indexer-api-key"))

        def creation(action, values):
            from torrentlinker.community_site import community_site

            return community_site(root).request(action, values)

        root._profile_workspace.creation_handler = creation
        return root._profile_workspace

    def for_client(self, identifier: str) -> Setup:
        root = self._root or self
        with root.lock:
            result = copy.copy(root)
            result._root = root
            result.settings = root.settings.for_client(identifier)
            result.store = root.store.for_client(identifier)
            result._client = None
            return result

    def client(self) -> ClientApi:
        with self.lock:
            if not self.configured:
                raise ValueError("Connect your Torrent Client in Settings first.")
            if self._client is None:
                name = CLIENT_SETTINGS[self.settings.client]
                config = getattr(self.settings, name)
                self._client = self.connector(
                    self.settings.client,
                    config.host,
                    getattr(config, "username", ""),
                    self.secrets.get(self.settings.secret_name(name + "-password")),
                    self.secrets.get(self.settings.secret_name("qbit-api-key"))
                    if name == "qbit"
                    else "",
                )
            from torrentlinker.client_access import SerializedClient

            port = getattr(self, "_client_port", None)
            if port is None or port.client is not self._client:
                self._client_port = SerializedClient(self._client)
            return self._client_port

    def indexer(self) -> Indexer:
        with self.lock:
            if self._indexer is None:
                key = self.secrets.get("indexer-api-key")
                if not key:
                    raise ValueError("Add your c411 API key in Settings first.")
                self._indexer = Indexer(
                    self.settings.indexer.url,
                    key,
                    cache=self.store,
                    extra_keys=self.extra_indexer_keys(),
                )
                self._indexer.session = (self._root or self)._profile_workspace
                self._indexer.adult_content = lambda: self.settings.adult_content
            return self._indexer

    def extra_indexer_keys(self) -> list[str]:
        return [key for i in range(1, 5) if (key := self.secrets.get(f"indexer-extra-key-{i}"))]

    def resolve_extra_keys(self, entries: list[str | KeptKey]) -> list[str]:
        """The final additional keys: typed and kept ones, without blanks or repeats."""
        keys = [
            self.secrets.get(f"indexer-extra-key-{key.keep}") if isinstance(key, KeptKey) else key
            for key in entries
        ]
        return list(dict.fromkeys(key for key in keys if key))

    def indexer_key_count(self) -> int:
        return len(
            {
                key
                for key in [self.secrets.get("indexer-api-key"), *self.extra_indexer_keys()]
                if key
            }
        )

    def snapshot(self) -> dict[str, Any]:
        from torrentlinker.reseed_layout import effective_layout

        with self.lock:
            name = CLIENT_SETTINGS[self.settings.client]
            config = getattr(self.settings, name)
            return {
                "client_id": self.settings.active_client_id,
                "name": self.settings.profile().name,
                "reseed_link_root": self.settings.profile().reseed_link_root,
                "reseed_layout": self.settings.profile().reseed_layout,
                "reseed_effective_layout": effective_layout(self.settings.profile()),
                "default_client_id": (self._root or self).settings.default_client_id,
                "clients": [
                    {"id": p.id, "name": p.name, "client": p.client, "enabled": p.enabled}
                    for p in (self._root or self).settings.client_profiles
                ],
                "configured": self.configured,
                "client": self.settings.client,
                "host": config.host,
                "username": getattr(config, "username", ""),
                "has_password": bool(
                    self.secrets.get(self.settings.secret_name(name + "-password"))
                ),
                "has_api_key": bool(self.secrets.get(self.settings.secret_name("qbit-api-key"))),
                "has_proxy_password": bool(self.secrets.get("proxy-password")),
                "has_announce_url": bool(self.secrets.get("announce-url")),
                # Without adult content, XXX is left out of every picker (read-only here).
                "indexer_categories": {
                    str(key): asdict(self.settings.indexer_categories[key])
                    for key in self.settings.visible_categories(self.settings.indexer_categories)
                },
                "adult_content": self.settings.adult_content,
                "indexer_url": self.settings.indexer.url,
                "indexer_configured": bool(self.secrets.get("indexer-api-key")),
                "indexer_key_count": self.indexer_key_count(),
                "storage_roots": [str(p) for p in self.roots],
                "folders": [
                    {"local": str(f.path), "depth": f.depth, "kind": f.kind}
                    for f in self.settings.library_folders
                ],
                "download_folder": self.settings.download_folders.default,
                "download_folders": {
                    "default": self.settings.download_folders.default,
                    "by_category": self.settings.download_folders.by_category,
                    "effective": {
                        str(cid): str(self.download_folder(cid) or "")
                        for cid in self.settings.indexer_categories
                    },
                },
                "sequential_video": self.settings.sequential_video,
                "mappings": [asdict(m) for m in self.settings.path_mappings],
                "capabilities": {
                    "manage": self.configured,
                    "scan": bool(self.settings.library_folders),
                    "download": bool(self.settings.download_folders.default),
                },
                "managed_secrets": list(self.secrets.files),
                "proxy": asdict(self.settings.proxy),
            }

    def test_client(self, body: Connection, *, save: bool = False) -> dict[str, Any]:
        with self.lock:
            name = CLIENT_SETTINGS[body.client]
            password = (
                body.password
                if body.password is not None
                else self.secrets.get(self.settings.secret_name(name + "-password"))
            )
            key = (
                body.api_key
                if body.api_key is not None
                else self.secrets.get(self.settings.secret_name("qbit-api-key"))
                if name == "qbit"
                else ""
            )
            from torrentlinker.transmission import PartialNamesOn

            try:
                client = self.connector(body.client, body.host, body.username, password, key)
                try:
                    version = client.check()
                except PartialNamesOn as refused:
                    # Connected: say why it is refused rather than "cannot connect".
                    if not body.turn_off_partial_names:
                        raise PartialNamesRefused(str(refused)) from None
                    refused.turn_off()
                    version = client.check()
            except PartialNamesRefused:
                raise
            except LoginRefused as refused:
                raise ValueError(refused.text(self.settings.language)) from None
            except Exception as error:
                if any(
                    word in str(error).lower()
                    for word in ("password", "unauthorized", "forbidden", "login", "401", "403")
                ):
                    raise ValueError(
                        "Authentication failed. Check the username, password or client API key."
                    ) from None
                raise ValueError(
                    "Cannot connect from this server. Check the address, port, TLS "
                    "certificate and proxy settings."
                ) from None
            # Folder discovery is helpful, but optional on restricted hosted services.
            try:
                folders = [asdict(f) for f in client.folder_settings()]
                warning = ""
            except Exception:
                folders, warning = (
                    [],
                    (
                        "Connected. This service did not provide folder settings; enter "
                        "the folder manually."
                    ),
                )
            if save:
                values = {}
                if body.password is not None:
                    values[self.settings.secret_name(name + "-password")] = body.password
                if body.api_key is not None and name == "qbit":
                    values[self.settings.secret_name("qbit-api-key")] = body.api_key
                old = getattr(self.settings, CLIENT_SETTINGS[self.settings.client])
                changed = (
                    self.settings.client != body.client
                    or old.host != body.host
                    or getattr(old, "username", "")
                    != ("" if body.client is TorrentClient.DELUGE else body.username)
                )
                from torrentlinker.client_profiles import pending_work

                if changed and pending_work(
                    self.settings, self.store, self.settings.active_client_id
                ):
                    raise ValueError(
                        "Finish pending Reseed Verifications before changing Torrent Clients."
                    )
                self.secrets.update(values)
                (self._root or self)._folder_proofs.clear()
                config = getattr(self.settings, name)
                config.host = body.host
                if hasattr(config, "username"):
                    config.username = body.username
                # Paths from one server must never silently target another server.
                if changed:
                    from torrentlinker.download_queue import entries

                    for entry in entries(self.store):
                        if entry.status in {"queued", "sending"}:
                            self.store.download_outcome(
                                entry.key,
                                "refused",
                                "Torrent Client changed. Queue this selection again.",
                            )
                    self.settings.path_mappings.clear()

                    self.settings.download_folders.default = ""
                    self.settings.download_folders.by_category.clear()
                if body.name.strip():
                    self.settings.profile().name = body.name.strip()
                self.settings.client = body.client
                self.save()
                self.marker.write_text("connected", encoding="utf-8")
                self.configured = True
                self._client = client
            return {"version": version, "folders": folders, "warning": warning}

    def test_indexer(self, body: IndexerConnection, *, save: bool = False) -> dict[str, Any]:
        with self.lock:
            if (
                save
                and self.secrets.get("indexer-api-key")
                and body.url != self.settings.indexer.url
                and self.store.catalogue_size()
            ):
                raise ValueError(
                    "Use a separate configuration directory for a different Indexer "
                    "with an existing catalogue."
                )
            key = body.api_key if body.api_key is not None else self.secrets.get("indexer-api-key")
            if not key:
                raise ValueError("Enter your c411 API key.")
            extras = (
                self.extra_indexer_keys()
                if body.extra_keys is None
                else self.resolve_extra_keys(body.extra_keys)
            )
            indexer = Indexer(body.url, key, cache=self.store, extra_keys=extras)
            try:
                caps = indexer.caps()
            except Exception:
                raise ValueError(
                    "Indexer test failed. Check its address and API key; c411 needs "
                    "torznab:read permission."
                ) from None
            if save:
                credentials = {"indexer-api-key": key} if body.api_key is not None else {}
                if body.extra_keys is not None:
                    credentials.update(
                        {
                            f"indexer-extra-key-{i + 1}": extras[i] if i < len(extras) else ""
                            for i in range(4)
                        }
                    )
                if credentials:
                    self.secrets.update(credentials)
                self.settings.indexer.url = body.url
                self.settings.indexer.modes = mode_names(caps)
                from torrentlinker.downloads import IndexerCategory

                self.settings.indexer_categories = {
                    k: IndexerCategory(v, caps.parents.get(k)) for k, v in caps.categories.items()
                }
                self.save()
                indexer.session = (self._root or self)._profile_workspace
                indexer.adult_content = lambda: self.settings.adult_content
                self._indexer = indexer
            return {
                "ok": True,
                "categories": len(caps.categories),
                "keys": len(dict.fromkeys([key, *extras])),
            }

    def indexer_for(self, identifier: str) -> Indexer | TorznabIndexer:
        """The Indexer to search: c411's own, or an added one with its pacer kept."""
        if identifier == C411_ID:
            return self.indexer()
        with self.lock:
            entry = self.settings.find_indexer(identifier)
            key = self.secrets.get(Settings.indexer_secret(identifier))
            if not key:
                raise ValueError(f"Add the API key of {entry.name} first.")
            held = self._torznab.get(identifier)
            if held is None or held[0] != (entry.url, key):
                held = ((entry.url, key), TorznabIndexer(entry.url, key, entry.name))
                self._torznab[identifier] = held
            return held[1]

    def set_cross_seed(self, body: CrossSeedRules) -> dict[str, Any]:
        with self.lock:
            rules = self.settings.cross_seed
            for name, value in body.model_dump(exclude_none=True).items():
                setattr(rules, name, value)
            self.save()
            return asdict(rules)

    def indexer_rows(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = []
            for entry in self.settings.indexers:
                row = {
                    "id": entry.id,
                    "name": entry.name,
                    "url": entry.url,
                    "enabled": entry.enabled,
                    "has_key": bool(self.secrets.get(Settings.indexer_secret(entry.id))),
                    "modes": entry.modes,
                    "searchable_ids": entry.searchable_ids,
                    "c411": entry.id == C411_ID,
                    "source": entry.source,
                    "missing": entry.missing,
                    "next_request_in": 0.0,
                }
                held = self._torznab.get(entry.id)
                if held is not None:
                    row["next_request_in"] = held[1].next_request_in()
                elif entry.id == C411_ID and self._indexer is not None:
                    row["next_request_in"] = self._indexer.next_request_in()
                rows.append(row)
            return rows

    def _probe(self, url: str, key: str, name: str) -> Caps:
        try:
            return TorznabIndexer(url, key, name).caps()
        except Exception:
            raise ValueError(
                "Indexer test failed. Check its Torznab address and API key."
            ) from None

    def probe_indexer(self, body: IndexerEntry, identifier: str = "") -> dict[str, Any]:
        """Read an Indexer's caps without saving it: what the add dialog's Test shows."""
        with self.lock:
            saved = self.settings.find_indexer(identifier) if identifier else None
            url = body.url or (saved.url if saved else "")
            key = body.api_key or (
                self.secrets.get(Settings.indexer_secret(identifier)) if saved else ""
            )
            if not url or not key:
                raise ValueError("Enter the Indexer's Torznab URL and API key.")
            entry = IndexerSettings(modes=mode_names(self._probe(url, key, body.name or url)))
            return {"ok": True, "modes": entry.modes, "searchable_ids": entry.searchable_ids}

    def add_indexer(self, body: IndexerEntry) -> dict[str, Any]:
        name = body.name.strip()
        if not name or not body.url or not body.api_key:
            raise ValueError("Enter the Indexer's name, Torznab URL and API key.")
        with self.lock:
            if name.casefold() in {i.name.casefold() for i in self.settings.indexers}:
                raise ValueError("An Indexer already has this name.")
            caps = self._probe(body.url, body.api_key, name)
            entry = IndexerSettings(
                url=body.url,
                id=uuid.uuid4().hex[:8],
                name=name,
                enabled=body.enabled is not False,
                modes=mode_names(caps),
            )
            self.secrets.update({Settings.indexer_secret(entry.id): body.api_key})
            self.settings.indexers.append(entry)
            self.save()
            return {"ok": True, "id": entry.id, "searchable_ids": entry.searchable_ids}

    def update_indexer(self, identifier: str, body: IndexerEntry) -> dict[str, Any]:
        with self.lock:
            entry = self.settings.find_indexer(identifier)
            if identifier == C411_ID:
                if body.enabled is not None:
                    entry.enabled = body.enabled
                self.save()  # c411's URL and keys are set by the connection
                return {"ok": True}
            name = body.name.strip() or entry.name
            if name.casefold() in {
                i.name.casefold() for i in self.settings.indexers if i.id != identifier
            }:
                raise ValueError("An Indexer already has this name.")
            url = body.url or entry.url
            key = body.api_key or self.secrets.get(Settings.indexer_secret(identifier))
            if (url, key) != (entry.url, self.secrets.get(Settings.indexer_secret(identifier))):
                entry.modes = mode_names(self._probe(url, key, name))
                if body.api_key:
                    self.secrets.update({Settings.indexer_secret(identifier): body.api_key})
            entry.name, entry.url = name, url
            if body.enabled is not None:
                entry.enabled = body.enabled
            self.save()
            return {"ok": True, "searchable_ids": entry.searchable_ids}

    def test_indexer_entry(self, identifier: str) -> dict[str, Any]:
        """Read the Indexer's caps again and keep which id searches it supports."""
        with self.lock:
            entry = self.settings.find_indexer(identifier)
            key = self.secrets.get(Settings.indexer_secret(identifier))
            if not key:
                raise ValueError(f"Add the API key of {entry.name} first.")
            entry.modes = mode_names(self._probe(entry.url, key, entry.name))
            self.save()
            return {"ok": True, "modes": entry.modes, "searchable_ids": entry.searchable_ids}

    def remove_indexer(self, identifier: str) -> None:
        with self.lock:
            if identifier == C411_ID:
                raise ValueError("c411 cannot be removed.")
            entry = self.settings.find_indexer(identifier)
            self.settings.indexers.remove(entry)
            self.secrets.update({Settings.indexer_secret(identifier): ""})
            self._torznab.pop(identifier, None)
            self.save()

    def hub_state(self) -> dict[str, Any]:
        with self.lock:
            hub = self.settings.indexer_hub
            return {
                "service": hub.service,
                "url": hub.url,
                "has_key": bool(self.secrets.get(HUB_SECRET)),
                "last_sync": hub.last_sync,
                "imported": sum(1 for i in self.settings.indexers if i.source),
            }

    def _hub_listing(self) -> list[indexer_hub.HubIndexer]:
        hub = self.settings.indexer_hub
        key = self.secrets.get(HUB_SECRET)
        if not hub.service or not key:
            raise ValueError("Connect Prowlarr or Jackett first.")
        try:
            return indexer_hub.list_indexers(hub.service, hub.url, key)
        except Exception as error:
            raise ValueError(indexer_hub.refused(error)) from None

    def _hub_rows(self, listing: list[indexer_hub.HubIndexer]) -> list[dict[str, Any]]:
        service = self.settings.indexer_hub.service
        known = {i.source_id for i in self.settings.indexers if i.source == service}
        return [
            {
                "id": h.source_id,
                "name": h.name,
                "enabled": h.enabled,
                "imported": h.source_id in known,
            }
            for h in listing
        ]

    def connect_hub(self, body: IndexerHubEntry) -> dict[str, Any]:
        """Save the instance once it answers, and list its indexers."""
        with self.lock:
            key = body.api_key or self.secrets.get(HUB_SECRET)
            if not key:
                raise ValueError("Enter the API key.")
            try:
                listing = indexer_hub.list_indexers(body.service, body.url, key)
            except Exception as error:
                raise ValueError(indexer_hub.refused(error)) from None
            hub = self.settings.indexer_hub
            if body.service != hub.service:  # another service: its imports are no longer synced
                for entry in self.settings.indexers:
                    entry.source = entry.source_id = ""
                    entry.missing = False
            hub.service, hub.url = body.service, body.url.rstrip("/")
            if body.api_key:
                self.secrets.update({HUB_SECRET: body.api_key})
            self.save()
            return {"ok": True, "available": self._hub_rows(listing)}

    def hub_available(self) -> dict[str, Any]:
        with self.lock:
            return {"available": self._hub_rows(self._hub_listing())}

    def disconnect_hub(self) -> None:
        """Forget the instance; imported Indexers stay, as added by hand."""
        with self.lock:
            for entry in self.settings.indexers:
                entry.source = entry.source_id = ""
                entry.missing = False
            self.settings.indexer_hub = type(self.settings.indexer_hub)()
            self.secrets.update({HUB_SECRET: ""})
            self.save()

    def _hub_name(self, name: str, taken: set[str]) -> str:
        if name.casefold() in taken:
            name = f"{name} ({self.settings.indexer_hub.service.title()})"
        return name

    def import_hub(self, body: IndexerHubImport) -> dict[str, Any]:
        """Import the chosen indexers in one step; each one's caps are read on the way."""
        with self.lock:
            hub = self.settings.indexer_hub
            key = self.secrets.get(HUB_SECRET)
            wanted = {h.source_id: h for h in self._hub_listing() if h.source_id in set(body.ids)}
            known = {i.source_id for i in self.settings.indexers if i.source == hub.service}
            taken = {i.name.casefold() for i in self.settings.indexers}
            added, failed = [], []
            for source_id, found in wanted.items():
                if source_id in known:
                    continue
                name = self._hub_name(found.name, taken)
                try:
                    caps = self._probe(found.url, key, name)
                except ValueError:
                    failed.append(found.name)
                    continue
                entry = IndexerSettings(
                    url=found.url,
                    id=uuid.uuid4().hex[:8],
                    name=name,
                    enabled=found.enabled,
                    modes=mode_names(caps),
                    source=hub.service,
                    source_id=source_id,
                )
                taken.add(name.casefold())
                self.secrets.update({Settings.indexer_secret(entry.id): key})
                self.settings.indexers.append(entry)
                added.append(entry.name)
            self.save()
            return {"ok": True, "added": added, "failed": failed}

    def sync_hub(self) -> dict[str, Any]:
        """Re-sync: renamed ones follow, vanished ones are flagged (kept), new ones listed."""
        with self.lock:
            hub = self.settings.indexer_hub
            key = self.secrets.get(HUB_SECRET)
            listing = {h.source_id: h for h in self._hub_listing()}
            imported = [i for i in self.settings.indexers if i.source == hub.service]
            renamed, removed = [], []
            for entry in imported:
                found = listing.get(entry.source_id)
                entry.missing = found is None
                if found is None:
                    removed.append(entry.name)
                    continue
                others = {i.name.casefold() for i in self.settings.indexers if i is not entry}
                name = self._hub_name(found.name, others)
                if name != entry.name:
                    renamed.append(name)
                    entry.name = name
                if found.url != entry.url:
                    entry.url = found.url
                if self.secrets.get(Settings.indexer_secret(entry.id)) != key:
                    self.secrets.update({Settings.indexer_secret(entry.id): key})
            self._torznab.clear()
            hub.last_sync = time.time()
            self.save()
            known = {i.source_id for i in imported}
            new = [h.name for sid, h in listing.items() if sid not in known]
            return {"ok": True, "renamed": renamed, "removed": removed, "new": new}

    def suggest_mappings(self) -> dict[str, Any]:
        from torrentlinker.paths import detect_mappings

        def is_file(path: Path, size: int) -> bool:
            try:
                resolved = self.path_under_root(str(path), directory=False)
                return resolved.is_file() and resolved.stat().st_size == size
            except (ValueError, OSError):
                return False

        client = self.client()
        selected = []
        paths: dict[str, int] = {}
        for torrent in client.torrents(with_files=False):
            path = str(torrent.save_path)
            if path not in paths and len(paths) >= 32:
                continue
            if paths.get(path, 0) >= 3:
                continue
            paths[path] = paths.get(path, 0) + 1
            selected.append(torrent)
        found = detect_mappings(
            selected, self.roots, files=lambda t: client.files(t.hash), is_file=is_file
        )
        suggestions = []
        for suggestion in found.suggestions:
            try:
                self.path_under_root(suggestion.mapping.local)
                suggestions.append(asdict(suggestion))
            except (ValueError, OSError):
                pass
        return {
            "suggestions": suggestions,
            "same_paths": found.same_paths,
            "not_found": found.not_found,
        }

    def proxy(self, body: ProxySetup) -> dict[str, Any]:
        with self.lock:
            password = (
                body.password if body.password is not None else self.secrets.get("proxy-password")
            )
            url = net.proxy_url(body.address, body.username, password)
            if body.password is not None:
                self.secrets.update({"proxy-password": password})
            self.settings.proxy = ProxySettings(body.address, body.username, body.torrent_client)
            self.save()
            net.configure(url, body.torrent_client)
            self._client = None
            self._indexer = None
            self._torznab.clear()
            return {"ok": True}

    def set_adult_content(self, enabled: bool) -> None:
        root = self._root or self
        with root.lock:
            root.settings.adult_content = enabled
            root.save()
        self.settings.adult_content = enabled

    def set_sequential_video(self, enabled: bool) -> None:
        root = self._root or self
        with root.lock:
            root.settings.sequential_video = enabled
            root.save()
        self.settings.sequential_video = enabled

    def path_under_root(self, value: str, *, directory: bool = True) -> Path:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("Choose an absolute folder visible to this server.")
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise StorageUnavailableError(
                "The folder is unavailable. Check the storage mount and permissions."
                f" {path}: {error}"
            ) from error
        if not any(resolved.is_relative_to(root) for root in self.roots):
            raise ValueError("This path is outside the configured storage roots.")
        if directory and not resolved.is_dir():
            raise ValueError("Choose a directory.")
        return resolved

    def browse(self, value: str) -> dict[str, Any]:
        if not value:
            return {"path": "", "parent": "", "folders": [str(r) for r in self.roots]}
        path = self.path_under_root(value)
        children = []
        for child in path.iterdir():
            try:
                resolved = self.path_under_root(str(child))
            except (ValueError, OSError):
                continue
            children.append(str(resolved))
        parent = str(path.parent) if any(path.parent.is_relative_to(r) for r in self.roots) else ""
        return {"path": str(path), "parent": parent, "folders": sorted(set(children))[:1000]}

    def preview_folder(self, body: FolderSetup) -> dict[str, Any]:
        """Read grouping examples without saving settings or contacting a client."""
        from torrentlinker.item_detection import detect_items

        root = self.path_under_root(body.local)
        errors: list[str] = []
        if body.depth is None:
            found = [
                (item.path, item.within)
                for item in detect_items(
                    root, body.kind, on_error=lambda path, error: errors.append(str(error))
                )
            ]
        else:
            # Fixed grouping needs names only, not recursive size calculation.
            level = [root]
            files: list[Path] = []
            for _ in range(body.depth):
                children: list[Path] = []
                for path in level:
                    self.path_under_root(str(path))
                    try:
                        children.extend(sorted(path.iterdir()))
                    except OSError as error:
                        errors.append(str(error))
                level = []
                for path in children:
                    self.path_under_root(str(path), directory=False)
                    (level if path.is_dir() else files).append(path)
            found = [(path, None) for path in files + level]
        for path, _within in found:
            self.path_under_root(str(path), directory=False)
        return {
            "count": sum(within is None for _, within in found),
            "episodes": sum(within is not None for _, within in found),
            "items": [
                {"name": path.name, "within": str(within) if within else None}
                for path, within in found[:8]
            ],
            "errors": errors,
        }

    def folder(
        self, body: FolderSetup, *, save: bool = False, probe: bool = False
    ) -> dict[str, Any]:
        with self.lock:
            local = self.path_under_root(body.local)
            if (
                body.original_local
                and Path(body.original_local) != local
                and self.store.verification_hashes()
            ):
                raise ValueError(
                    "Finish pending Reseed Verifications before changing folder paths."
                )
            if body.original_local and not any(
                str(f.path) == body.original_local for f in self.settings.library_folders
            ):
                raise ValueError("The Library Folder no longer exists. Reopen the dialog.")
            if body.purpose == "library" and not body.client_path.strip():
                # Register readable storage independently of a Torrent Client connection.
                with os.scandir(local) as entries:
                    next(entries, None)
                if save:
                    self.settings.library_folders = [
                        f
                        for f in self.settings.library_folders
                        if f.path != local and str(f.path) != body.original_local
                    ] + [LibraryFolder(local, body.depth, body.kind)]
                    self.save()
                return {
                    "readable": True,
                    "sample": None,
                    "local": str(local),
                    "client": "",
                    "warning": "",
                }
            if not body.client_path.startswith(("/", "\\\\")) and not (
                len(body.client_path) > 2 and body.client_path[1] == ":"
            ):
                raise ValueError("Enter the absolute folder used by your Torrent Client.")
            # Verify directory enumeration, not just existence.
            with os.scandir(local) as entries:
                next(entries, None)
            mapper = PathMapper([PathMapping(str(local), body.client_path)])
            remote_type = (
                PureWindowsPath
                if "\\" in body.client_path or body.client_path[1:2] == ":"
                else PurePosixPath
            )
            remote_root = remote_type(body.client_path)
            if not remote_root.is_absolute() or ".." in remote_root.parts:
                raise ValueError("Use an absolute client folder without parent traversal.")
            sample = None
            attempts = 0
            for torrent in self.client().torrents(with_files=False):
                try:
                    relative = remote_type(str(torrent.save_path)).relative_to(remote_root)
                except ValueError:
                    continue
                if ".." in relative.parts:
                    continue
                mapped = local.joinpath(*relative.parts)
                if attempts >= 10:
                    break
                attempts += 1
                files = known_files(self.client(), self.store, torrent.hash)
                for rel, size in sorted(files.items(), key=lambda f: f[1], reverse=True)[:3]:
                    try:
                        file = self.path_under_root(str(mapped / rel), directory=False)
                        if (
                            file.is_relative_to(local)
                            and file.is_file()
                            and file.stat().st_size == size
                        ):
                            sample = {
                                "local": str(file),
                                "client": mapper.to_qbit(str(file)),
                                "size": size,
                            }
                            break
                    except (ValueError, OSError):
                        continue
                if sample:
                    break
            verification = "existing-file" if sample else ""
            if sample is None:
                import time

                from torrentlinker.folder_probe import verify_folder

                stat = local.stat()
                config = getattr(self.settings, CLIENT_SETTINGS[self.settings.client])
                key = (
                    self.settings.active_client_id,
                    self.settings.client,
                    config.host,
                    getattr(config, "username", ""),
                    str(local),
                    body.client_path,
                    stat.st_dev,
                    stat.st_ino,
                )
                root = self._root or self
                root._folder_proofs = {
                    k: expiry
                    for k, expiry in root._folder_proofs.items()
                    if expiry > time.monotonic()
                }
                if root._folder_proofs.get(key, 0) > time.monotonic():
                    verification = "temporary-file"
                elif probe or (save and body.purpose == "download"):
                    verify_folder(self.client(), local, body.client_path)
                    root._folder_proofs[key] = time.monotonic() + 300
                    verification = "temporary-file"
            if save:
                if body.purpose == "download" and not verification:
                    raise ValueError(
                        "No existing torrent file confirms this mapping. Verify a seeded "
                        "sample before enabling downloads."
                    )
                self.settings.path_mappings = [
                    m
                    for m in self.settings.path_mappings
                    if m.local != str(local) and m.qbit != body.client_path
                ]
                self.settings.path_mappings.append(PathMapping(str(local), body.client_path))
                if body.purpose == "library":
                    self.settings.library_folders = [
                        f for f in self.settings.library_folders if f.path != local
                    ]
                    self.settings.library_folders.append(
                        LibraryFolder(local, body.depth, body.kind)
                    )
                else:
                    self.settings.download_folders.default = str(local)
                self.save()
            return {
                "readable": True,
                "sample": sample,
                "verification": verification,
                "local": str(local),
                "client": body.client_path,
                "warning": ""
                if verification
                else "Folder readable, but no matching torrent file confirms the mapping yet.",
            }

    def configure_download_folder(
        self,
        local: str,
        category: int | None = None,
        client_path: str = "",
        *,
        save: bool = False,
        probe: bool = True,
    ) -> dict[str, Any]:
        """Validate one destination using existing mappings; never create a mount or mapping."""
        with self.lock:
            if category is not None and category not in self.settings.indexer_categories:
                raise ValueError("Choose a known Indexer category or subcategory.")
            path = self.path_under_root(local)
            mapped = PathMapper(self.settings.path_mappings).to_qbit(str(path))
            if client_path and client_path != mapped:
                raise ValueError(
                    "The client folder differs from the existing Path Mapping. "
                    "Configure and verify the Path Mapping in Settings first."
                )
            checked = self.folder(FolderSetup(local=str(path), client_path=mapped), probe=probe)
            if not checked["verification"]:
                raise ValueError(
                    "No existing torrent file confirms this Download Folder's Path Mapping. "
                    "Choose a mounted folder containing a seeded sample, or verify its "
                    "Path Mapping in Settings first. Browser computer paths are not server mounts."
                )
            if save:
                if category is None:
                    self.settings.download_folders.default = str(path)
                else:
                    self.settings.download_folders.by_category[category] = str(path)
                self.save()
            return {**checked, "category": category, "saved": save}

    def download_folder(self, category: int | None = None) -> Path | None:
        if category is None:
            value = self.settings.download_folders.default
            return Path(value) if value else None
        return self.settings.download_folders.resolve(category, self.settings.indexer_categories)

    def verified_download_folder(self, category: int | None = None) -> Path:
        folder = self.download_folder(category)
        local = self.path_under_root(str(folder) if folder else "")
        client_path = PathMapper(self.settings.path_mappings).to_qbit(str(local))
        checked = self.folder(FolderSetup(local=str(local), client_path=client_path), probe=True)
        if not checked["verification"]:
            raise ValueError(
                "The Download Folder mapping no longer matches a seeded file. "
                "Check the storage mount and test the mapping again in Settings."
            )
        return local

    def remove_folder(self, body: FolderRemoval) -> None:
        # Do not resolve this path: removing a disconnected mount must still work.
        with self.lock:
            if body.purpose == "library":
                self.settings.library_folders = [
                    folder
                    for folder in self.settings.library_folders
                    if str(folder.path) != body.local
                ]
            elif body.category is not None:
                if self.settings.download_folders.by_category.get(body.category) == body.local:
                    self.settings.download_folders.by_category.pop(body.category)
            elif self.settings.download_folders.default == body.local:
                self.settings.download_folders.default = ""
            self.save()

    def save(self) -> None:
        if self._root is not None:
            with self.lock:
                self.settings.capture_client()
                root = self._root
                root.settings.capture_client()
                profile = copy.deepcopy(self.settings.profile())
                root.settings.client_profiles = [
                    profile if p.id == profile.id else p for p in root.settings.client_profiles
                ]
                # Shared account and Library settings belong to the workspace.
                root.settings.library_folders = copy.deepcopy(self.settings.library_folders)
                root.settings.zen = copy.deepcopy(self.settings.zen)
                root.settings.indexer_categories = copy.deepcopy(self.settings.indexer_categories)
                if root.settings.active_client_id == profile.id:
                    root.settings = self.settings.for_client(profile.id)
                root.save()
            return
        temporary = self.path.with_suffix(".new")
        self.settings.save(temporary)
        temporary.replace(self.path)
