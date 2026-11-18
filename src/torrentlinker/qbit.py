"""Torrent Client port, named after qBittorrent, and qBittorrent's WebUI adapter.

Deluge's adapter is in deluge.py; it speaks qBittorrent's state names and tags too.
Paths crossing this boundary are in the client's view; translation to the app's view
happens in the caller through Path Mappings.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import qbittorrentapi

from torrentlinker import net
from torrentlinker.client_folders import ClientFolder, qbit_folders
from torrentlinker.domain import Torrent, TorrentFile
from torrentlinker.torrent_meta import read_torrent


class Qbit(Protocol):
    @property
    def supports_category_tags(self) -> bool: ...

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        """Torrents, optionally without their file lists (much faster)."""
        ...

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None: ...
    def files(self, hash: str) -> dict[str, int]:
        """The torrent's file paths, relative to its save path, and sizes."""
        ...

    def file_listing(self, hash: str) -> list[TorrentFile]: ...

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        """Add stopped, with automatic management off and the original layout; return hash.

        The data already sits in save_path: the client must check it there.
        """
        ...

    def rename_file(self, hash: str, old: str, new: str) -> None:
        """Rename a file inside the torrent (paths relative to the save path)."""
        ...

    def download(
        self, data: bytes, save_path: str, tags: list[str], *, sequential: bool = False
    ) -> str:
        """Add started, to download into `save_path` with the original layout and
        automatic management off; return hash. `sequential` downloads pieces in order,
        first and last first, so a video plays while it downloads."""
        ...

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None: ...
    def recheck(self, hash: str) -> None: ...
    def piece_states(self, hash: str) -> list[int]:
        """Per piece: 0 missing, 1 downloading, 2 verified."""
        ...

    def pause(self, hash: str) -> None: ...
    def resume(self, hash: str) -> None: ...
    def start(self, hash: str) -> None: ...
    def remove(self, hash: str, *, delete_files: bool = False) -> None:
        """Remove a torrent, keeping its files unless deletion is explicitly requested."""
        ...

    def add_tags(self, hash: str, tags: list[str]) -> None: ...
    def add_tags_many(self, hashes: list[str], tags: list[str]) -> None: ...
    def remove_tags(self, hash: str, tags: list[str]) -> None: ...


class ClientApi(Qbit, Protocol):
    """A Torrent Client as the app connects to it: QbitApi or DelugeApi."""

    def folder_settings(self) -> list[ClientFolder]: ...

    def check(self) -> str:
        """Log in and return the client's version."""
        ...

    def default_save_path(self) -> str:
        """The client's own download folder, as the client sees it."""
        ...


class AlreadyInClient(RuntimeError):
    """The Torrent Client already has this hash; it must not be replaced or retargeted."""

    def __init__(self, torrent: Torrent | None = None) -> None:
        self.torrent = torrent
        message = "This torrent is already in the Torrent Client."
        if torrent is not None:
            message += (
                " It is already seeding."
                if torrent.is_seeding
                else " Check its state and save path in your torrent client."
            )
            message += (
                f"\nName: {torrent.name}\nHash: {torrent.hash}\nState: {torrent.state}"
                f"\nSave path: {torrent.save_path}"
            )
        super().__init__(message)


API_KEY_PATTERN = re.compile(r"^qbt_[A-Za-z0-9]{28}$")


def is_api_key(text: str) -> bool:
    """Whether `text` looks like a qBittorrent WebUI API key (qBittorrent 5.2+)."""
    return bool(API_KEY_PATTERN.match(text))


class _SharedLogin:
    """qbittorrent-api calls that share one login, safe when several threads start at once.

    Left alone, every thread that finds no session logs in by itself, the logins replace
    each other's session cookie and requests in between are refused with 403.
    """

    def __init__(self, client: qbittorrentapi.Client) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._logged_in = False

    def log_in(self) -> None:
        with self._lock:
            self._client.auth_log_in()
            self._logged_in = True

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._client, name)
        if not callable(attribute) or name.startswith("auth_"):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            if not self._logged_in:
                with self._lock:
                    if not self._logged_in:
                        self._client.auth_log_in()
                        self._logged_in = True
            try:
                return attribute(*args, **kwargs)
            except qbittorrentapi.Forbidden403Error:
                self.log_in()  # the session expired or was replaced: once more
                return attribute(*args, **kwargs)

        return call


LIST_TIMEOUT = 300  # seconds to read the first full listing: 15k torrents take 15 s on a NAS


class QbitApi:
    """Adapter over qBittorrent's WebUI API (4.5+ and 5.x).

    With an API key (qBittorrent 5.2+) every request carries `Authorization: Bearer`
    and there is no login; otherwise the username and password open one session that
    every thread shares.

    Every torrent is listed through one copy kept in step with qBittorrent's sync API,
    as its own Web UI does: the first listing reads them all, later ones only what
    changed. qBittorrent answers one request at a time, and with 15,000 torrents a full
    listing is 22 MB that a NAS takes 15 s to send, so listings that overlap at start-up
    timed out or were dropped. Listings wait for each other instead.
    """

    supports_category_tags = True

    def __init__(self, host: str, username: str, password: str, api_key: str = "") -> None:
        client = qbittorrentapi.Client(
            host=host,
            username=None if api_key else username,
            password=None if api_key else password,
            api_key=api_key or None,
            VERIFY_WEBUI_CERTIFICATE=False,
            REQUESTS_ARGS={"timeout": (5, 30), "proxies": net.requests_proxies()},
        )
        self._client: Any = client if api_key else _SharedLogin(client)
        self._sync = threading.Lock()
        self._trackers: dict[str, list[str]] = {}
        self._rid = 0
        self._known: dict[str, dict[str, Any]] = {}

    def check(self) -> str:
        """Log in (or validate the API key) and return the qBittorrent version."""
        self._client.auth_log_in()
        return str(self._client.app_version())

    def default_save_path(self) -> str:
        """qBittorrent's own download folder, as qBittorrent sees it."""
        return str(self._client.app_default_save_path())

    def folder_settings(self) -> list[ClientFolder]:
        preferences = self._client.app_preferences()
        default = str(preferences.get("save_path") or self.default_save_path())
        rows = qbit_folders(
            default,
            self._client.torrents_categories(),
            bool(preferences.get("subcategories_enabled", True)),
        )
        if preferences.get("temp_path_enabled") and preferences.get("temp_path"):
            rows.append(ClientFolder("", str(preferences["temp_path"]), "incomplete"))
        return rows

    def rotate_api_key(self) -> str:
        """Ask qBittorrent (5.2+) for a new API key, replacing any previous one."""
        return str(self._client.app_rotate_api_key()["apiKey"])

    def delete_api_key(self) -> None:
        self._client.app_delete_api_key()

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        # A tag is filtered by qBittorrent itself: a short answer, sent at once.
        found = self._client.torrents_info(tag=tag) if tag is not None else self._synced()
        return [self._torrent(t, with_files) for t in found]

    def _synced(self) -> list[dict[str, Any]]:
        """Every torrent, from the copy kept in step with qBittorrent's sync API."""
        with self._sync:
            data = self._client.sync_maindata(
                rid=self._rid, requests_args={"timeout": (5, LIST_TIMEOUT)}
            )
            if data.get("full_update"):
                self._known = {}
                self._trackers = {}
            for h, changed in (data.get("torrents") or {}).items():
                self._known.setdefault(h, {"hash": h}).update(changed)
            for h in data.get("torrents_removed") or []:
                self._known.pop(h, None)
            self._trackers.update(data.get("trackers") or {})
            for url in data.get("trackers_removed") or []:
                self._trackers.pop(url, None)
            by_hash: dict[str, list[str]] = {}
            for url, hashes in self._trackers.items():
                for h in hashes:
                    by_hash.setdefault(h, []).append(url)
            for h, t in self._known.items():
                t["tracker_urls"] = by_hash.get(h, [])
            self._rid = int(data.get("rid", 0))
            return [dict(t) for t in self._known.values()]

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None:
        found = self._client.torrents_info(torrent_hashes=hash)
        if not found:
            return None
        info = dict(found[0])
        if "tracker_urls" not in info:
            # The plain info call names only the current tracker; one torrent can afford the list.
            info["tracker_urls"] = [
                str(x["url"])
                for x in self._client.torrents_trackers(hash)
                if str(x.get("url", "")).startswith(("http", "udp"))
            ]
        return self._torrent(info, with_files)

    def files(self, hash: str) -> dict[str, int]:
        return {f.name: int(f.size) for f in self._client.torrents_files(hash)}

    def file_listing(self, hash: str) -> list[TorrentFile]:
        return [
            TorrentFile(
                int(f.get("index", i)),
                str(f["name"]),
                int(f["size"]),
                int(f.get("priority", 1)) > 0,
            )
            for i, f in enumerate(self._client.torrents_files(hash))
        ]

    def _torrent(self, t: Mapping[str, Any], with_files: bool = True) -> Torrent:
        files = self.files(t["hash"]) if with_files else {}
        return Torrent(
            hash=t["hash"],
            name=t["name"],
            save_path=Path(t["save_path"]),
            files=files,
            tags=frozenset(x.strip() for x in str(t.get("tags", "")).split(",") if x.strip()),
            progress=float(t["progress"]),
            state=str(t["state"]),
            tracker=str(t.get("tracker", "")),
            trackers=tuple(t.get("tracker_urls", ())),
            category=str(t.get("category", "")),
            download_rate=int(t.get("dlspeed", 0)),
            upload_rate=int(t.get("upspeed", 0)),
            ratio=float(t.get("ratio", 0)),
            eta=int(t.get("eta", -1)),
            connected_seeds=int(t.get("num_seeds", 0)),
            connected_peers=int(t.get("num_leechs", 0)),
            swarm_seeders=max(int(str(t.get("num_complete", -1))), -1),
            swarm_peers=max(int(str(t.get("num_incomplete", -1))), -1),
            seeding_time=float(str(t.get("seeding_time", 0))),
            size=int(str(t.get("total_size", 0) or t.get("size", 0))),
        )

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        # The files are already in save_path: never in the folder qBittorrent may keep
        # incomplete torrents in, where the check would find nothing after a rename.
        return self._add(data, save_path, tags, stopped=True, use_download_path=False)

    def download(
        self, data: bytes, save_path: str, tags: list[str], *, sequential: bool = False
    ) -> str:
        return self._add(data, save_path, tags, stopped=False, sequential=sequential)

    def _add(
        self,
        data: bytes,
        save_path: str,
        tags: list[str],
        stopped: bool,
        sequential=False,
        use_download_path: bool | None = None,
    ) -> str:
        h = read_torrent(data).infohash
        order = {"is_sequential_download": True, "is_first_last_piece_priority": True}
        try:
            result = self._client.torrents_add(
                torrent_files=data,
                save_path=save_path,
                is_stopped=stopped,
                use_auto_torrent_management=False,
                content_layout="Original",
                tags=tags,
                use_download_path=use_download_path,
                **(order if sequential else {}),
            )
        except qbittorrentapi.Conflict409Error:
            result = "Fails."
        if str(result).strip().lower().startswith("fail"):
            # Another task may have added it a moment ago (a Plan and a Reseed at once).
            if self._client.torrents_info(torrent_hashes=h):
                raise AlreadyInClient()
            raise RuntimeError("qBittorrent refused the torrent")
        for _ in range(50):  # the add is asynchronous inside qBittorrent
            if self._client.torrents_info(torrent_hashes=h):
                return h
            time.sleep(0.2)
        raise RuntimeError("Torrent did not appear in qBittorrent")

    def rename_file(self, hash: str, old: str, new: str) -> None:
        self._client.torrents_rename_file(torrent_hash=hash, old_path=old, new_path=new)

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        self._client.torrents_file_priority(torrent_hash=hash, file_ids=indexes, priority=priority)

    def recheck(self, hash: str) -> None:
        self._client.torrents_recheck(torrent_hashes=hash)

    def media_preview_state(self, hash: str) -> dict[str, Any]:
        """Read live sequential mode and verified pieces. Never changes download priorities."""
        found = self._client.torrents_info(torrent_hashes=hash)
        if not found:
            raise ValueError("Torrent is no longer present in qBittorrent.")
        info = found[0]
        properties = self._client.torrents_properties(torrent_hash=hash)
        files = self._client.torrents_files(torrent_hash=hash)
        return {
            "sequential": info.get("seq_dl") is True,
            "state": str(info.get("state") or ""),
            "piece_size": int(properties.get("piece_size") or 0),
            "files": [
                {
                    "name": str(f["name"]),
                    "size": int(f["size"]),
                    "piece_range": list(f.get("piece_range") or []),
                }
                for f in files
            ],
            "piece_states": self.piece_states(hash),
        }

    def piece_states(self, hash: str) -> list[int]:
        return [int(s) for s in self._client.torrents_piece_states(torrent_hash=hash)]

    def pause(self, hash: str) -> None:
        self._client.torrents_stop(torrent_hashes=hash)

    def resume(self, hash: str) -> None:
        self.start(hash)

    def start(self, hash: str) -> None:
        self._client.torrents_start(torrent_hashes=hash)

    def remove(self, hash: str, *, delete_files: bool = False) -> None:
        self._client.torrents_delete(delete_files=delete_files, torrent_hashes=hash)

    def add_tags(self, hash: str, tags: list[str]) -> None:
        self._client.torrents_add_tags(tags=tags, torrent_hashes=hash)

    def add_tags_many(self, hashes: list[str], tags: list[str]) -> None:
        self._client.torrents_add_tags(tags=tags, torrent_hashes=hashes)

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        self._client.torrents_remove_tags(tags=tags, torrent_hashes=hash)
