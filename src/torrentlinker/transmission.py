"""Transmission adapter for the torrent-client port, over its RPC (4.x, and 3.0 for labels).

Transmission renames a file it finds incomplete to `name.part`, on disk, when its
"Append .part to incomplete files" setting is on: during a Reseed's check that would
rename the user's own files. Adding a Reseed is refused while it is on; the refusal can
turn it off when the user agrees. Transmission renames only the last part of a path, a
file or a folder name, so a Reseed needing other folders is refused (ADR-0010).
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from torrentlinker import net
from torrentlinker.client_folders import ClientFolder
from torrentlinker.domain import Torrent, TorrentFile
from torrentlinker.login_guard import LoginGuard
from torrentlinker.qbit import AlreadyInClient

SESSION_HEADER = "X-Transmission-Session-Id"
FIELDS = [
    "hashString",
    "name",
    "downloadDir",
    "labels",
    "percentDone",
    "status",
    "error",
    "trackers",
    "trackerStats",
    "secondsSeeding",
    "totalSize",
    "rateDownload",
    "rateUpload",
    "uploadRatio",
    "eta",
    "peers",
]
LOCAL_ERROR = 3  # Transmission's error kind for a problem with the data, not the tracker


class TransmissionError(RuntimeError):
    pass


class PartialNamesOn(TransmissionError):
    """Transmission would rename the user's files to .part; `turn_off` changes that."""

    def __init__(self, turn_off: Callable[[], None]) -> None:
        super().__init__(
            "Transmission appends .part to the names of incomplete files, which would rename "
            "your own files during a Reseed. Untick “Append .part to incomplete files' names” "
            "in Transmission's preferences (Downloading), or let TorrentLinker turn it off."
        )
        self.turn_off = turn_off


class RenameUnsupported(TransmissionError):
    pass


def _state(status: int, done: float, error: int) -> str:
    """Transmission's status in qBittorrent's names, which the rest of the app reads."""
    end = "UP" if done >= 1 else "DL"
    if error == LOCAL_ERROR:
        return "error"
    return {
        0: f"stopped{end}",
        1: f"checking{end}",  # waiting to check
        2: f"checking{end}",
        3: "queuedDL",
        4: "downloading",
        5: "queuedUP",
        6: "uploading",
    }.get(status, f"stopped{end}")


class TransmissionApi:
    """Adapter over Transmission's RPC: its address, and a username and password if set.

    Unlike Deluge, Transmission checks a stopped torrent without starting it, and has
    several labels per torrent, which stand for the port's tags as they are.
    """

    supports_category_tags = True

    def __init__(
        self, host: str, username: str = "", password: str = "", http: httpx.Client | None = None
    ) -> None:
        url = host.strip().rstrip("/")
        if "//" not in url:
            url = "http://" + url
        if not url.endswith("/rpc"):
            url += "/transmission/rpc"
        self._url = url
        auth = httpx.BasicAuth(username, password) if username or password else None
        self._http = http or net.client(
            torrent_client=True, timeout=httpx.Timeout(300, connect=5), verify=False
        )
        self._auth = auth
        # Basic credentials ride on every request: once refused, none is sent again.
        self._guard = LoginGuard("transmission", url, username, password)
        self._session = ""
        self._lock = threading.Lock()

    def _call(self, method: str, **arguments: Any) -> dict[str, Any]:
        self._guard.check()
        for _ in range(3):
            response = self._http.post(
                self._url,
                json={"method": method, "arguments": arguments},
                headers={SESSION_HEADER: self._session},
                auth=self._auth or httpx.USE_CLIENT_DEFAULT,
            )
            if response.status_code == 409:  # a new session: its id comes with the refusal
                with self._lock:
                    self._session = response.headers.get(SESSION_HEADER, "")
                continue
            if response.status_code == 401:
                raise self._guard.refuse()
            response.raise_for_status()
            reply = response.json()
            if reply.get("result") != "success":
                raise TransmissionError(f"Transmission: {reply.get('result')}")
            return dict(reply.get("arguments") or {})
        raise TransmissionError("Transmission did not accept the session")

    def _session_get(self, *fields: str) -> dict[str, Any]:
        return self._call("session-get", fields=list(fields))

    def tracker_updates_supported(self) -> bool:
        return int(self._session_get("rpc-version").get("rpc-version", 0)) >= 17

    def announce_entries(self, hash: str):
        from torrentlinker.tracker_updates import Announce

        rows = self._call("torrent-get", ids=[hash], fields=["trackers"])["torrents"]
        if not rows:
            raise ValueError("Torrent no longer exists.")
        return [Announce(str(r["announce"]), int(r["tier"])) for r in rows[0]["trackers"]]

    def apply_announces(self, hash: str, before, after) -> None:
        # trackerList preserves tiers and unrelated URLs on Transmission 4.x.
        tiers: dict[int, list[str]] = {}
        for entry in after:
            tiers.setdefault(entry.tier, []).append(entry.url)
        self._call(
            "torrent-set",
            ids=[hash],
            trackerList="\n\n".join("\n".join(tiers[tier]) for tier in sorted(tiers)),
        )

    def reannounce(self, hash: str) -> None:
        self._call("torrent-reannounce", ids=[hash])

    def check(self) -> str:
        """Return Transmission's version; refused while it would rename files to .part."""
        self._guard.rearm()  # the user pressed Test
        version = str(self._session_get("version")["version"])
        self._require_whole_names()
        return version

    def default_save_path(self) -> str:
        """Transmission's own download folder, as Transmission sees it."""
        return str(self._session_get("download-dir")["download-dir"])

    def folder_settings(self) -> list[ClientFolder]:
        config = self._session_get("download-dir", "incomplete-dir", "incomplete-dir-enabled")
        rows = []
        if config.get("download-dir"):
            rows.append(ClientFolder("", str(config["download-dir"]), "default"))
        if config.get("incomplete-dir-enabled") and config.get("incomplete-dir"):
            rows.append(ClientFolder("", str(config["incomplete-dir"]), "incomplete"))
        return rows

    def turn_off_partial_names(self) -> None:
        """Untick “Append .part to incomplete files' names”, for every torrent."""
        self._call("session-set", **{"rename-partial-files": False})

    def _require_whole_names(self) -> None:
        if self._session_get("rename-partial-files").get("rename-partial-files"):
            raise PartialNamesOn(self.turn_off_partial_names)

    # Port ------------------------------------------------------------------

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        """Torrents, optionally without their file lists; one request either way."""
        ids: list[str] | None = None
        if tag is not None:  # Transmission does not filter by label: find them first
            found = self._call("torrent-get", fields=["hashString", "labels"])["torrents"]
            ids = [t["hashString"] for t in found if tag in (t.get("labels") or [])]
            if not ids:
                return []
        return self._get(ids, with_files)

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None:
        found = self._get([hash], with_files)
        return found[0] if found else None

    def files(self, hash: str) -> dict[str, int]:
        found = self._call("torrent-get", ids=[hash], fields=["files"])["torrents"]
        return {str(f["name"]): int(f["length"]) for f in found[0]["files"]} if found else {}

    def file_listing(self, hash: str) -> list[TorrentFile]:
        found = self._call("torrent-get", ids=[hash], fields=["files", "wanted"])["torrents"]
        if not found:
            return []
        wanted = found[0].get("wanted") or []
        return [
            TorrentFile(
                i, str(f["name"]), int(f["length"]), bool(wanted[i]) if i < len(wanted) else True
            )
            for i, f in enumerate(found[0].get("files") or [])
        ]

    def _get(self, ids: list[str] | None, with_files: bool) -> list[Torrent]:
        arguments: dict[str, Any] = {"fields": [*FIELDS, "files"] if with_files else FIELDS}
        if ids is not None:
            arguments["ids"] = ids
        return [self._torrent(t) for t in self._call("torrent-get", **arguments)["torrents"]]

    @staticmethod
    def _torrent(t: dict[str, Any]) -> Torrent:
        done = float(t.get("percentDone") or 0)  # of the wanted files, as qBittorrent's
        trackers = t.get("trackers") or []
        seeders = [int(s.get("seederCount", -1)) for s in t.get("trackerStats") or []]
        leechers = [int(s.get("leecherCount", -1)) for s in t.get("trackerStats") or []]
        peers = t.get("peers") or []
        known_peers = isinstance(t.get("peers"), list) and all("progress" in p for p in peers)
        return Torrent(
            hash=str(t["hashString"]).lower(),
            name=str(t.get("name", "")),
            save_path=Path(str(t.get("downloadDir", ""))),
            files={str(f["name"]): int(f["length"]) for f in t.get("files") or []},
            tags=frozenset(str(x) for x in t.get("labels") or []),
            progress=done,
            state=_state(int(t.get("status", 0)), done, int(t.get("error") or 0)),
            tracker=str(trackers[0].get("announce", "")) if trackers else "",
            swarm_seeders=max([*seeders, -1]),
            swarm_peers=max([*leechers, -1]),
            seeding_time=float(t.get("secondsSeeding") or 0),
            size=int(t.get("totalSize") or 0),
            trackers=tuple(str(tr["announce"]) for tr in trackers if tr.get("announce")),
            download_rate=int(t.get("rateDownload") or 0),
            upload_rate=int(t.get("rateUpload") or 0),
            ratio=float(t.get("uploadRatio") or 0),
            eta=int(t.get("eta", -1)),
            connected_seeds=sum(p["progress"] >= 1 for p in peers) if known_peers else -1,
            connected_peers=sum(p["progress"] < 1 for p in peers) if known_peers else -1,
        )

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        """Add stopped, after making sure Transmission will not rename files to .part."""
        self._require_whole_names()
        return self._add(data, save_path, tags, paused=True)

    def download(
        self, data: bytes, save_path: str, tags: list[str], *, sequential: bool = False
    ) -> str:
        return self._add(data, save_path, tags, paused=False, sequential=sequential)

    def _add(
        self, data: bytes, save_path: str, tags: list[str], paused: bool, sequential=False
    ) -> str:
        # Transmission 4.1 reads sequential_download; older versions ignore it.
        reply = self._call(
            "torrent-add",
            metainfo=base64.b64encode(data).decode(),
            paused=paused,
            labels=tags,
            **{"download-dir": save_path},
            **({"sequential_download": True} if sequential else {}),
        )
        if "torrent-duplicate" in reply:
            raise AlreadyInClient()
        return str(reply["torrent-added"]["hashString"]).lower()

    def rename_file(self, hash: str, old: str, new: str) -> None:
        """Rename each part that differs, deepest last: Transmission renames one file or
        folder name at a time, which also renames every file inside that folder."""
        old_parts, new_parts = old.split("/"), new.split("/")
        if len(old_parts) != len(new_parts):
            raise RenameUnsupported(
                f"Transmission can only rename names in place, not move {old} to {new}"
            )
        current = list(old_parts)
        files = set(self.files(hash))
        for i, (was, wanted) in enumerate(zip(old_parts, new_parts, strict=True)):
            if was == wanted:
                continue
            path = "/".join(current[: i + 1])
            if not any(f == path or f.startswith(path + "/") for f in files):
                # An earlier rename of the same folder already took this file along.
                current[i] = wanted
                continue
            renamed = "/".join([*current[:i], wanted])
            if any(f == renamed or f.startswith(renamed + "/") for f in files):
                raise RenameUnsupported(
                    f"Transmission cannot rename {path} to {renamed}: that name is taken"
                )
            self._call("torrent-rename-path", ids=[hash], path=path, name=wanted)
            files = {
                renamed + f[len(path) :] if f == path or f.startswith(path + "/") else f
                for f in files
            }
            current[i] = wanted

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        """Priority 0 leaves the files out, as in qBittorrent; any other wants them."""
        key = "files-unwanted" if priority == 0 else "files-wanted"
        self._call("torrent-set", ids=[hash], **{key: indexes})

    def recheck(self, hash: str) -> None:
        self._call("torrent-verify", ids=[hash])

    def piece_states(self, hash: str) -> list[int]:
        """Per piece: 0 missing, 2 verified (Transmission's bitfield, first piece first)."""
        [t] = self._call("torrent-get", ids=[hash], fields=["pieces", "pieceCount"])["torrents"]
        bits = base64.b64decode(t["pieces"])
        return [2 if bits[i // 8] & (0x80 >> (i % 8)) else 0 for i in range(int(t["pieceCount"]))]

    def pause(self, hash: str) -> None:
        self._call("torrent-stop", ids=[hash])

    def resume(self, hash: str) -> None:
        self.start(hash)

    def start(self, hash: str) -> None:
        self._call("torrent-start", ids=[hash])

    def remove(self, hash: str, *, delete_files: bool = False) -> None:
        """Remove a torrent; data deletion requires an explicit request."""
        self._call("torrent-remove", ids=[hash], **{"delete-local-data": delete_files})

    def add_tags(self, hash: str, tags: list[str]) -> None:
        current = self._labels(hash)
        self._call(
            "torrent-set", ids=[hash], labels=[*current, *(t for t in tags if t not in current)]
        )

    def add_tags_many(self, hashes: list[str], tags: list[str]) -> None:
        for hash in hashes:
            self.add_tags(hash, tags)

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        labels = [t for t in self._labels(hash) if t not in tags]
        self._call("torrent-set", ids=[hash], labels=labels)

    def _labels(self, hash: str) -> list[str]:
        found = self._call("torrent-get", ids=[hash], fields=["labels"])["torrents"]
        return list(found[0].get("labels") or []) if found else []
