"""Experimental µTorrent / BitTorrent Classic WebUI adapter.

Live-tested with µTorrent build 47390 and BitTorrent build 47391.

Management, downloads and full Reseeds with unchanged paths use the WebUI's
token-authenticated HTTP API. The Reseed service can rename files on disk after
explicit approval; partial Reseeds are refused before adding a job. This adapter
never changes global client preferences.
"""

from __future__ import annotations

import hashlib
import ntpath
import posixpath
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from torrentlinker import net
from torrentlinker.client_folders import ClientFolder
from torrentlinker.domain import Torrent, TorrentFile
from torrentlinker.login_guard import LoginGuard
from torrentlinker.matching import Match
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.torrent_meta import TorrentMeta, read_torrent


class UtorrentError(RuntimeError):
    pass


class _TokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inside = False
        self.token = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div" and dict(attrs).get("id") == "token":
            self.inside = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            self.inside = False

    def handle_data(self, data: str) -> None:
        if self.inside:
            self.token += data.strip()


def _enabled(value: Any) -> bool:
    return str(value).lower() in {"1", "true"}


def _state(flags: int, progress: float) -> str:
    end = "UP" if progress >= 1 else "DL"
    if flags & 2:
        return f"checking{end}"
    if flags & 16:
        return "error"
    if flags & 32 or not flags & 1:
        return f"stopped{end}"
    return "uploading" if progress >= 1 else "downloading"


def _path_module(path: str) -> Any:
    return ntpath if ntpath.splitdrive(path)[0] or "\\" in path else posixpath


def _same_path(first: str, second: str) -> bool:
    module = _path_module(first)
    return bool(first and second) and module.normcase(module.normpath(first)) == module.normcase(
        module.normpath(second)
    )


class UtorrentApi:
    supports_category_tags = False  # one label must not be replaced by category tags
    requires_disk_renames = True
    supports_partial_reseeds = False  # the WebUI does not report verified pieces

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        http: httpx.Client | None = None,
        *,
        client_name: str = "µTorrent Classic",
    ) -> None:
        self.client_name = client_name
        base = host.strip().rstrip("/")
        if "://" not in base:
            base = "http://" + base
        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise self._error("Enter the µTorrent Classic WebUI address")
        path = parsed.path.rstrip("/")
        if not path.endswith("/gui"):
            path += "/gui"
        self._url = urlunsplit((parsed.scheme, parsed.netloc, path + "/", "", ""))
        self.reseed_client_id = hashlib.sha256((self._url + "\0" + username).encode()).hexdigest()
        self._auth = httpx.BasicAuth(username, password)
        self._guard = LoginGuard("utorrent", self._url, username, password)
        self._http = http or net.client(torrent_client=True, timeout=httpx.Timeout(30, connect=5))
        self._lock = threading.RLock()
        self._token = ""
        self._props: dict[str, tuple[float, dict[str, Any]]] = {}

    def _error(self, message: str) -> UtorrentError:
        return UtorrentError(
            message.replace("µTorrent Classic", self.client_name).replace(
                "µTorrent", self.client_name.removesuffix(" Classic")
            )
        )

    def _authenticate(self) -> None:
        self._guard.check()  # refused credentials are not sent again until they change
        reply = self._http.get(self._url + "token.html", auth=self._auth)
        if reply.status_code in (401, 403):
            raise self._guard.refuse()
        reply.raise_for_status()
        parser = _TokenParser()
        parser.feed(reply.text)
        if not parser.token:
            raise self._error("No WebUI token returned. Use µTorrent Classic with WebUI enabled.")
        self._token = parser.token

    def _call(self, params: list[tuple[str, str]], data: bytes | None = None) -> dict[str, Any]:
        # Serialize cookie/token refresh with requests so concurrent workers cannot
        # invalidate each other's sessions. Never replay an upload after a timeout.
        with self._lock:
            self._guard.check()
            if not self._token:
                self._authenticate()
            for attempt in range(2):
                query = httpx.QueryParams([("token", self._token), *params])
                if data is None:
                    reply = self._http.get(self._url, params=query, auth=self._auth)
                else:
                    reply = self._http.post(
                        self._url,
                        params=query,
                        auth=self._auth,
                        files={
                            "torrent_file": ("torrent.torrent", data, "application/x-bittorrent")
                        },
                    )
                if reply.status_code in (400, 401, 403) and attempt == 0:
                    self._token = ""
                    self._authenticate()
                    continue
                reply.raise_for_status()
                result = reply.json()
                if not isinstance(result, dict) or "build" not in result:
                    raise self._error("Invalid µTorrent Classic WebUI response")
                if result.get("error"):
                    raise self._error(str(result["error"]))
                return result
        raise self._error("µTorrent WebUI authentication failed")

    def _action(self, action: str, hash: str) -> dict[str, Any]:
        return self._call([("action", action), ("hash", hash)])

    def _settings(self) -> dict[str, Any]:
        return {row[0]: row[2] for row in self._call([("action", "getsettings")])["settings"]}

    def check(self) -> str:
        self._guard.rearm()  # the user pressed Test
        result = self._call([("list", "1")])
        return f"build {result['build']} (experimental)"

    def default_save_path(self) -> str:
        settings = self._settings()
        if not _enabled(settings.get("dir_active_download_flag")) or not settings.get(
            "dir_active_download"
        ):
            raise self._error("Set a default download folder in µTorrent Preferences → Directories")
        return str(settings["dir_active_download"])

    def folder_settings(self) -> list[ClientFolder]:
        settings = self._settings()
        rows = []
        for flag, key, kind in [
            ("dir_active_download_flag", "dir_active_download", "default"),
            ("dir_completed_download_flag", "dir_completed_download", "completed"),
        ]:
            if _enabled(settings.get(flag)) and settings.get(key):
                rows.append(ClientFolder("", str(settings[key]), kind))  # type: ignore[arg-type]
        return rows

    def _list(self) -> list[list[Any]]:
        result = self._call([("list", "1")])
        if not isinstance(result.get("torrents"), list):
            raise self._error("µTorrent did not return its torrent list")
        return list(result["torrents"])

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        with self._lock:
            rows = self._list()
            alive = {str(row[0]).lower() for row in rows}
            self._props = {h: value for h, value in self._props.items() if h in alive}
            if tag is not None:
                rows = [r for r in rows if tag in self._tags(str(r[11]))]
            stale = [
                str(r[0])
                for r in rows
                if (
                    time.monotonic() - self._props.get(str(r[0]).lower(), (-float("inf"), {}))[0]
                    > 60
                )
            ]
            for offset in range(0, len(stale), 100):
                result = self._call(
                    [("action", "getprops"), *[("hash", h) for h in stale[offset : offset + 100]]]
                )
                for props in result.get("props", []):
                    self._props[str(props["hash"]).lower()] = (time.monotonic(), props)
            return [self._torrent(row, with_files) for row in rows]

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None:
        with self._lock:
            row = next((r for r in self._list() if str(r[0]).lower() == hash.lower()), None)
            if row is None:
                return None
            result = self._action("getprops", hash)
            for props in result.get("props", []):
                self._props[str(props["hash"]).lower()] = (time.monotonic(), props)
            return self._torrent(row, with_files)

    def _torrent(self, row: list[Any], with_files: bool) -> Torrent:
        if len(row) <= 26 or not row[26]:
            raise self._error("This µTorrent build does not report torrent save paths")
        hash = str(row[0]).lower()
        progress = float(row[4]) / 1000
        props = self._props.get(hash, (0, {}))[1]
        trackers = tuple(
            u.strip() for u in str(props.get("trackers", "")).splitlines() if u.strip()
        )
        label = str(row[11])
        return Torrent(
            hash=hash,
            name=str(row[2]),
            save_path=Path(str(row[26])),
            files=self.files(hash) if with_files else {},
            tags=self._tags(label),
            progress=progress,
            state=_state(int(row[1]), progress),
            tracker=trackers[0] if trackers else "",
            trackers=trackers,
            swarm_seeders=int(row[15]),
            swarm_peers=max(int(row[13]), -1),
            size=int(row[3]),
            category=label,
            download_rate=int(row[9]),
            upload_rate=int(row[8]),
            ratio=float(row[7]) / 1000,
            eta=int(row[10]),
            connected_seeds=int(row[14]),
            connected_peers=int(row[12]),
        )

    def file_listing(self, hash: str) -> list[TorrentFile]:
        result = self._action("getfiles", hash).get("files", [])
        if len(result) != 2 or str(result[0]).lower() != hash.lower():
            raise self._error("µTorrent did not return the requested file list")
        return [
            TorrentFile(i, str(row[0]).replace("\\", "/"), int(row[1]), int(row[3]) != 0)
            for i, row in enumerate(result[1])
        ]

    def files(self, hash: str) -> dict[str, int]:
        return {f.name: f.size for f in self.file_listing(hash)}

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        return self._add_stopped(data, save_path, tags, reseed=True)

    def reseed_layout(self, meta: TorrentMeta, match: Match) -> Match:
        """Preflight without I/O, and express paths relative to the native content root.

        µTorrent reports multifile paths without the torrent root folder. Persist
        these relative local paths in the Verification, so recovery also works with
        a fresh adapter after an application restart.
        """
        if match.unwanted or set(match.pairs) != set(meta.files):
            raise self._error(
                "µTorrent Classic cannot verify Partial Matches through its WebUI. "
                "All torrent files must be present, including ignored files. "
                "Use qBittorrent, Transmission or Deluge for Partial Matches."
            )
        if match.renames:
            raise self._error(
                "µTorrent Classic cannot rename files inside a torrent through its WebUI. "
                "Disk renaming must be explicitly confirmed before seeding this torrent."
            )
        if self._multifile(meta):
            prefix = meta.name + "/"
            if not all(path.startswith(prefix) for path in meta.files):
                raise self._error("Unexpected µTorrent multifile layout")
            return Match({path[len(prefix) :]: path[len(prefix) :] for path in meta.files})
        return match

    @staticmethod
    def _multifile(meta: TorrentMeta) -> bool:
        return len(meta.files) != 1 or next(iter(meta.files), "") != meta.name

    def _check_reseed_settings(self, settings: dict[str, Any]) -> None:
        for key, option in [
            ("append_incomplete", "Append .!ut to incomplete files"),
            ("dir_completed_download_flag", "Move completed downloads to"),
            ("dir_add_label", "Append the torrent's label"),
        ]:
            if key not in settings or _enabled(settings[key]):
                raise self._error(
                    f"Disable ‘{option}’ in µTorrent before Reseeds or Upload seeding, "
                    "so it cannot rename or move your existing files."
                )
        if settings.get("finish_cmd") or settings.get("state_cmd"):
            raise self._error(
                "Disable µTorrent's Run Program commands before Reseeds or Upload seeding."
            )

    def rename_file(self, hash: str, old: str, new: str) -> None:
        raise self._error("In-torrent file renaming is not yet supported with µTorrent Classic")

    def piece_states(self, hash: str) -> list[int]:
        raise self._error("Piece verification is not yet supported with µTorrent Classic")

    def download(
        self, data: bytes, save_path: str, tags: list[str], *, sequential: bool = False
    ) -> str:
        # µTorrent's Web UI cannot set sequential download: it is left off.
        with self._lock:
            hash = self._add_stopped(data, save_path, tags, reseed=False)
            try:
                self.start(hash)
            except Exception:
                self.remove(hash)
                raise
            return hash

    def _add_stopped(self, data: bytes, save_path: str, tags: list[str], *, reseed: bool) -> str:
        meta = read_torrent(data)
        with self._lock:
            if any(str(row[0]).lower() == meta.infohash.lower() for row in self._list()):
                raise AlreadyInClient()
            settings = self._settings()
            if reseed:
                self._check_reseed_settings(settings)
            if not _enabled(settings.get("torrents_start_stopped")):
                raise self._error(
                    "Enable ‘Don't start the download automatically’ in µTorrent "
                    "before sending torrents"
                )
            base = str(settings.get("dir_active_download", ""))
            if not base or not _enabled(settings.get("dir_active_download_flag")):
                raise self._error(
                    "Set a default download folder in µTorrent Preferences → Directories"
                )
            module = _path_module(base)
            base, save_path = module.normpath(base), module.normpath(save_path)
            try:
                inside = _same_path(module.commonpath([base, save_path]), base)
            except ValueError:
                inside = False
            if not inside:
                raise self._error(
                    "µTorrent torrents must use its default download folder or a subfolder"
                )
            relative = module.relpath(save_path, base)
            relative = "" if relative == "." else relative
            multi = self._multifile(meta)
            expected = module.join(save_path, meta.name) if multi else save_path
            self._call([("action", "add-file"), ("download_dir", "0"), ("path", relative)], data)
            # New jobs are stopped by the user's preference. Check the actual folder
            # before starting; an unsupported path parameter must never silently fall back.
            try:
                for _ in range(25):
                    row = next(
                        (r for r in self._list() if str(r[0]).lower() == meta.infohash.lower()),
                        None,
                    )
                    if row is not None:
                        break
                    time.sleep(0.1)
                else:
                    raise self._error(
                        "µTorrent did not confirm the added torrent; "
                        "inspect its WebUI before retrying"
                    )
                if len(row) <= 26 or not _same_path(str(row[26]), expected) or int(row[1]) & 1:
                    raise self._error(
                        "µTorrent did not keep the torrent stopped in the requested folder"
                    )
                self.add_tags(meta.infohash, tags)
            except Exception:
                # Only the new job is removed, with the API action that retains all data.
                self.remove(meta.infohash)
                raise
            return meta.infohash

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        if not indexes:
            return
        known = {f.index for f in self.file_listing(hash)}
        if any(i not in known for i in indexes):
            raise self._error("A selected file no longer exists in µTorrent")
        self._call(
            [
                ("action", "setprio"),
                ("hash", hash),
                ("p", "0" if priority == 0 else "2"),
                *[("f", str(i)) for i in indexes],
            ]
        )

    def recheck(self, hash: str) -> None:
        self._action("recheck", hash)

    def pause(self, hash: str) -> None:
        self._action("stop", hash)

    def resume(self, hash: str) -> None:
        with self._lock:
            row = next((r for r in self._list() if str(r[0]).lower() == hash.lower()), None)
            if row is None:
                raise self._error("Torrent no longer exists in µTorrent")
            if "torrentlinker:verifying" in self._tags(str(row[11])):
                self._check_reseed_settings(self._settings())
                # The list's progress is rounded. Check exact completed byte counts
                # too, and refuse skipped files even if selected-file progress is 100%.
                result = self._action("getfiles", hash).get("files", [])
                complete = (
                    len(result) == 2
                    and str(result[0]).lower() == hash.lower()
                    and bool(result[1])
                    and all(int(f[1]) == int(f[2]) and int(f[3]) != 0 for f in result[1])
                )
                if int(row[1]) & (2 | 16) or int(row[4]) != 1000 or int(row[18]) or not complete:
                    raise self._error(
                        "µTorrent has not verified every file. The torrent stays stopped."
                    )
            self._action("start", hash)

    def start(self, hash: str) -> None:
        self.resume(hash)

    def remove(self, hash: str, *, delete_files: bool = False) -> None:
        self._action("removedata" if delete_files else "remove", hash)
        self._props.pop(hash.lower(), None)

    @staticmethod
    def _tags(label: str) -> frozenset[str]:
        if label.startswith("torrentlinker:"):
            return frozenset({"torrentlinker", label})
        return frozenset({label}) if label else frozenset()

    def add_tags(self, hash: str, tags: list[str]) -> None:
        with self._lock:
            row = next((r for r in self._list() if str(r[0]).lower() == hash.lower()), None)
            if row is None:
                raise self._error("Torrent no longer exists in µTorrent")
            old = str(row[11])
            if old and old != "torrentlinker" and not old.startswith("torrentlinker:"):
                raise self._error("µTorrent's existing personal label cannot be replaced")
            wanted = set(tags) | self._tags(old)
            label = max(wanted, key=lambda t: (t.count(":"), t), default="")
            self._call([("action", "setprops"), ("hash", hash), ("s", "label"), ("v", label)])

    def add_tags_many(self, hashes: list[str], tags: list[str]) -> None:
        for hash in hashes:
            self.add_tags(hash, tags)

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        with self._lock:
            row = next((r for r in self._list() if str(r[0]).lower() == hash.lower()), None)
            if row is None:
                raise self._error("Torrent no longer exists in µTorrent")
            old = str(row[11])
            if old != "torrentlinker" and not old.startswith("torrentlinker:"):
                return  # never replace a personal label
            wanted = self._tags(old) - set(tags)
            label = max(wanted, key=lambda t: (t.count(":"), t), default="")
            if label != old:
                self._call([("action", "setprops"), ("hash", hash), ("s", "label"), ("v", label)])
