"""Deluge adapter for the torrent-client port, over Deluge's Web UI JSON-RPC (2.x).

Deluge has no tags: they become the one label each torrent carries, which needs Deluge's
Label plugin; of tags like `torrentlinker:partial`, only the last one added stays. Its
states are translated into the qBittorrent names the rest of the app uses. Deluge
resumes a stopped torrent while it rechecks it and stops it again after, so a torrent
added stopped keeps its download speed at about 1 byte/s until it is started or its
Verification ends: nothing can be fetched into the user's files meanwhile (ADR-0009).
"""

from __future__ import annotations

import base64
import itertools
import re
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from torrentlinker import net
from torrentlinker.client_folders import ClientFolder
from torrentlinker.domain import Torrent, TorrentFile
from torrentlinker.login_guard import LoginGuard
from torrentlinker.qbit import AlreadyInClient

GUARD_SPEED = 0.001  # KiB/s, Deluge's unit: 1 byte/s; -1 is unlimited
NOT_AUTHENTICATED = 1  # Deluge Web UI error code
UNKNOWN_METHOD = 2  # also what a core.* call gets when no daemon is connected
KEYS = [
    "name",
    "download_location",
    "save_path",  # Deluge before 2.0
    "label",
    "progress",
    "state",
    "paused",
    "tracker",
    "trackers",
    "total_seeds",
    "total_peers",
    "seeding_time",
    "total_size",
    "download_payload_rate",
    "upload_payload_rate",
    "ratio",
    "eta",
    "num_seeds",
    "num_peers",
]
SKIP, NORMAL = 0, 4  # Deluge file priorities


class DelugeError(RuntimeError):
    pass


class LabelPluginOff(DelugeError):
    def __init__(self) -> None:
        super().__init__(
            "Deluge's Label plugin is off. Enable it in Deluge: Preferences → Plugins → Label. "
            "TorrentLinker labels the torrents it adds to follow their Verification."
        )


def label_for(tags: Iterable[str]) -> str:
    """The one label standing for these tags: the most specific, `a:b` written `a-b`."""
    chosen = max(tags, key=lambda t: (t.count(":"), t), default="")
    return re.sub(r"[^a-z0-9_.-]", "-", chosen.lower().replace(":", "-"))


def tags_of(label: str) -> frozenset[str]:
    """The tags a label stands for: `a-b` is `a:b` and `a`."""
    if not label:
        return frozenset()
    if "-" not in label:
        return frozenset({label})
    base, rest = label.split("-", 1)
    return frozenset({base, f"{base}:{rest}"})


def _state(state: str, paused: bool, progress: float) -> str:
    """Deluge's state in qBittorrent's names, which the Reseed flow and Seeding view read."""
    end = "UP" if progress >= 100 else "DL"
    if state == "Paused":
        # Deluge resumes a stopped torrent to recheck it and stops it again once checked.
        return f"stopped{end}" if paused else f"checking{end}"
    return {
        "Seeding": "uploading",
        "Downloading": "downloading",
        "Checking": f"checking{end}",
        "Queued": f"queued{end}",
        "Allocating": "checkingResumeData",
        "Moving": "moving",
        "Error": "error",
    }.get(state, state.lower())


class DelugeApi:
    """Adapter over Deluge's Web UI (2.x): its address and the Web UI password.

    The Web UI forwards calls to its daemon; when it is not connected to one, the first
    daemon of its host list is connected. One session is shared by every thread.
    """

    # A torrent has only one Label; category tags must not replace its existing label.
    supports_category_tags = False

    def __init__(self, host: str, password: str, http: httpx.Client | None = None) -> None:
        base = host.strip().rstrip("/")
        if "//" not in base:
            base = "http://" + base
        self._url = base + "/json"
        self._password = password
        self._guard = LoginGuard("deluge", base, "", password)
        self._http = http or net.client(
            torrent_client=True, timeout=httpx.Timeout(30, connect=5), verify=False
        )
        self._lock = threading.Lock()
        self._ready = False
        self._labels: bool | None = None
        self._ids = itertools.count(1)

    # Session ---------------------------------------------------------------

    def _post(self, method: str, params: list[Any]) -> dict[str, Any]:
        request = {"method": method, "params": params, "id": next(self._ids)}
        response = self._http.post(self._url, json=request)
        response.raise_for_status()
        return dict(response.json())

    def _open(self) -> None:
        self._guard.check()  # a refused password is not sent again until it changes
        if not self._post("auth.login", [self._password]).get("result"):
            raise self._guard.refuse()
        if self._post("web.connected", []).get("result"):
            return
        hosts = self._post("web.get_hosts", []).get("result") or []
        if not hosts:
            raise DelugeError("Deluge's Web UI knows no daemon: add one in its Connection Manager")
        self._post("web.connect", [hosts[0][0]])
        for _ in range(25):
            if self._post("web.connected", []).get("result"):
                return
            time.sleep(0.2)
        raise DelugeError("Deluge's Web UI could not connect to its daemon")

    def _call(self, method: str, *params: Any) -> Any:
        self._guard.check()
        if not self._ready:
            with self._lock:
                if not self._ready:
                    self._open()
                    self._ready = True
        reply = self._post(method, list(params))
        error = reply.get("error")
        if error and error.get("code") in (NOT_AUTHENTICATED, UNKNOWN_METHOD):
            with self._lock:  # the session expired, or the daemon was disconnected: once more
                self._open()
            reply = self._post(method, list(params))
            error = reply.get("error")
        if error:
            raise DelugeError(str(error.get("message", error)))
        return reply.get("result")

    def announce_entries(self, hash: str):
        from torrentlinker.tracker_updates import Announce

        row = self._call("core.get_torrent_status", hash, ["trackers"])
        return [Announce(str(r["url"]), int(r["tier"])) for r in row["trackers"]]

    def apply_announces(self, hash: str, before, after) -> None:
        self._call(
            "core.set_torrent_trackers",
            hash,
            [{"url": entry.url, "tier": entry.tier} for entry in after],
        )

    def reannounce(self, hash: str) -> None:
        self._call("core.force_reannounce", [hash])

    def check(self) -> str:
        """Log in, connect to the daemon and return Deluge's version.

        Refused when the Label plugin is off: Reseeds need it.
        """
        self._guard.rearm()  # the user pressed Test
        with self._lock:
            self._open()
            self._ready = True
        version = str(self._call("daemon.get_version"))
        self._labels = None
        self._require_labels()
        return version

    def default_save_path(self) -> str:
        """Deluge's own download folder, as Deluge sees it."""
        return str(self._call("core.get_config_value", "download_location"))

    def folder_settings(self) -> list[ClientFolder]:
        config = self._call(
            "core.get_config_values",
            [
                "download_location",
                "move_completed",
                "move_completed_path",
            ],
        )
        rows = []
        if config.get("download_location"):
            rows.append(ClientFolder("", str(config["download_location"]), "default"))
        if config.get("move_completed") and config.get("move_completed_path"):
            rows.append(ClientFolder("", str(config["move_completed_path"]), "completed"))
        if "Label" in (self._call("core.get_enabled_plugins") or []):
            for label in sorted(self._call("label.get_labels") or []):
                options = self._call("label.get_options", label)
                if (
                    options.get("apply_move_completed")
                    and options.get("move_completed")
                    and options.get("move_completed_path")
                ):
                    rows.append(
                        ClientFolder(label, str(options["move_completed_path"]), "completed")
                    )
        return rows

    def _require_labels(self) -> None:
        if not self._labels:
            self._labels = "Label" in (self._call("core.get_enabled_plugins") or [])
        if not self._labels:
            raise LabelPluginOff()

    # Port ------------------------------------------------------------------

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        """Torrents, optionally without their file lists (much faster)."""
        where: dict[str, Any] = {}
        if tag is not None:
            try:
                self._require_labels()
            except LabelPluginOff:
                return []  # no torrent can carry a tag
            labels = [x for x in self._call("label.get_labels") or [] if tag in tags_of(x)]
            if not labels:
                return []
            where["label"] = labels
        keys = [*KEYS, "files"] if with_files else KEYS
        found = self._call("core.get_torrents_status", where, keys) or {}
        return [self._torrent(h, s) for h, s in found.items()]

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None:
        s = self._call("core.get_torrent_status", hash, [*KEYS, "files"] if with_files else KEYS)
        return self._torrent(hash, s) if s else None

    def files(self, hash: str) -> dict[str, int]:
        found = self._call("core.get_torrent_status", hash, ["files"]).get("files") or []
        return {str(f["path"]): int(f["size"]) for f in found}

    def file_listing(self, hash: str) -> list[TorrentFile]:
        data = self._call("core.get_torrent_status", hash, ["files", "file_priorities"])
        priorities = data.get("file_priorities") or []
        result = []
        for i, f in enumerate(data.get("files") or []):
            index = int(f.get("index", i))
            wanted = priorities[index] > 0 if index < len(priorities) else True
            result.append(TorrentFile(index, str(f["path"]), int(f["size"]), wanted))
        return result

    @staticmethod
    def _torrent(hash: str, s: dict[str, Any]) -> Torrent:
        progress = float(s.get("progress") or 0)
        trackers = s.get("trackers") or []
        return Torrent(
            hash=hash,
            name=str(s.get("name", "")),
            save_path=Path(str(s.get("download_location") or s.get("save_path") or "")),
            files={str(f["path"]): int(f["size"]) for f in s.get("files") or []},
            tags=tags_of(str(s.get("label") or "")),
            progress=progress / 100,
            state=_state(str(s.get("state", "")), bool(s.get("paused")), progress),
            # The current tracker is only known once announced; a stopped torrent has none.
            tracker=str(s.get("tracker") or (trackers[0].get("url", "") if trackers else "")),
            swarm_seeders=max(int(s.get("total_seeds", -1)), -1),
            swarm_peers=max(int(s.get("total_peers", -1)), -1),
            seeding_time=float(s.get("seeding_time") or 0),
            size=int(s.get("total_size") or 0),
            trackers=tuple(str(t["url"]) for t in trackers if t.get("url")),
            category=str(s.get("label") or ""),
            download_rate=int(s.get("download_payload_rate") or 0),
            upload_rate=int(s.get("upload_payload_rate") or 0),
            ratio=float(s.get("ratio") or 0),
            eta=int(s.get("eta") or -1),
            connected_seeds=int(s.get("num_seeds") or 0),
            connected_peers=int(s.get("num_peers") or 0),
        )

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        """Add stopped, out of Deluge's queue and with its download speed at 1 byte/s."""
        return self._add(
            data,
            save_path,
            tags,
            {"add_paused": True, "auto_managed": False, "max_download_speed": GUARD_SPEED},
        )

    def download(
        self, data: bytes, save_path: str, tags: list[str], *, sequential: bool = False
    ) -> str:
        options: dict[str, Any] = {"add_paused": False}
        if sequential:
            options.update(sequential_download=True, prioritize_first_last_pieces=True)
        return self._add(data, save_path, tags, options)

    def _add(self, data: bytes, save_path: str, tags: list[str], options: dict[str, Any]) -> str:
        if tags:
            self._require_labels()  # before adding: a Reseed must carry its tags
        options = {
            "download_location": save_path,
            "move_completed": False,  # stay where the files are, whatever Deluge's default
            **options,
        }
        try:
            h = self._call(
                "core.add_torrent_file", "torrent", base64.b64encode(data).decode(), options
            )
        except DelugeError as e:
            if "already in session" in str(e):
                raise AlreadyInClient() from e
            raise
        if not h:
            raise RuntimeError("Deluge refused the torrent")
        if tags:
            self._label(h, frozenset(tags))
        return str(h)

    def rename_file(self, hash: str, old: str, new: str) -> None:
        files = self._call("core.get_torrent_status", hash, ["files"]).get("files") or []
        index = next(f["index"] for f in files if f["path"] == old)
        self._call("core.rename_files", hash, [[index, new]])

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        """qBittorrent's priority 0 skips a file, as in Deluge; any other is Deluge's normal."""
        status = self._call("core.get_torrent_status", hash, ["file_priorities"])
        priorities = list(status.get("file_priorities") or [])
        for i in indexes:
            priorities[i] = SKIP if priority == 0 else NORMAL
        self._call("core.set_torrent_options", [hash], {"file_priorities": priorities})

    def recheck(self, hash: str) -> None:
        self._call("core.force_recheck", [hash])

    def piece_states(self, hash: str) -> list[int]:
        """Per piece: 0 missing, 1 downloading, 2 verified (Deluge says 3, or nothing when
        it has every piece)."""
        s = self._call("core.get_torrent_status", hash, ["pieces", "num_pieces"])
        if s.get("pieces") is None:
            return [2] * int(s.get("num_pieces") or 0)
        return [2 if p == 3 else 1 if p == 2 else 0 for p in s["pieces"]]

    def pause(self, hash: str) -> None:
        self._call("core.pause_torrent", [hash])

    def resume(self, hash: str) -> None:
        # Managing an existing torrent must preserve its personal speed limits.
        self._call("core.resume_torrent", hash)

    def start(self, hash: str) -> None:
        self._lift_guard(hash)
        self._call("core.resume_torrent", hash)

    def remove(self, hash: str, *, delete_files: bool = False) -> None:
        """Remove a torrent; data deletion requires an explicit request."""
        self._call("core.remove_torrent", hash, delete_files)

    def add_tags(self, hash: str, tags: list[str]) -> None:
        """One label holds one `a:b` tag: an added one replaces the torrent's own."""
        specific = any(":" in t for t in tags)
        self._label(hash, frozenset(tags) if specific else self._tags(hash) | set(tags))

    def add_tags_many(self, hashes: list[str], tags: list[str]) -> None:
        for hash in hashes:
            self.add_tags(hash, tags)

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        # The Reseed flow removes a tag when Verification ends: a torrent left stopped
        # then starts at full speed if the user starts it in Deluge.
        self._lift_guard(hash)
        self._label(hash, self._tags(hash) - set(tags))

    def _tags(self, hash: str) -> frozenset[str]:
        return tags_of(str(self._call("core.get_torrent_status", hash, ["label"]).get("label")))

    def _label(self, hash: str, tags: frozenset[str]) -> None:
        label = label_for(tags)
        if label and label not in (self._call("label.get_labels") or []):
            try:
                self._call("label.add", label)
            except DelugeError as e:
                if "already exists" not in str(e):  # another task made it meanwhile
                    raise
        self._call("label.set_torrent", hash, label)

    def _lift_guard(self, hash: str) -> None:
        speed = self._call("core.get_torrent_status", hash, ["max_download_speed"])
        if 0 < float(speed.get("max_download_speed", -1)) <= GUARD_SPEED * 2:
            self._call("core.set_torrent_options", [hash], {"max_download_speed": -1})
