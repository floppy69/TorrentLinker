"""rTorrent adapter for the torrent-client port, over its XML-RPC (ADR-0017).

rTorrent answers XML-RPC on an SCGI port or socket, which seedboxes usually publish over
HTTP (`/RPC2` behind ruTorrent's web server). Both are accepted: an http(s) address, or
`scgi://host:port` and `scgi:///path/to/socket` for the SCGI interface itself.

rTorrent cannot rename a file inside a torrent, and its check creates every absent file
on disk, even a skipped one. So a Reseed whose names differ uses confirmed disk renames,
as with µTorrent (ADR-0013), and Partial Matches are refused before anything is added.
The port's tags live in a custom field of their own, so the user's ruTorrent label is
never touched.
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time
import xmlrpc.client
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx

from torrentlinker import net
from torrentlinker.client_folders import ClientFolder
from torrentlinker.domain import Torrent, TorrentFile
from torrentlinker.login_guard import LoginGuard
from torrentlinker.matching import Match
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.torrent_meta import TorrentMeta, read_torrent

TAGS_KEY = "torrentlinker_tags"  # d.custom=…, comma-separated; ruTorrent's label is custom1
FIELDS = [
    "d.hash=",
    "d.name=",
    "d.directory=",
    "d.is_multi_file=",
    "d.state=",
    "d.is_active=",
    "d.hashing=",
    "d.hashing_failed=",
    "d.complete=",
    "d.completed_bytes=",
    "d.size_bytes=",
    f"d.custom={TAGS_KEY}",
    "d.custom1=",
    "d.up.rate=",
    "d.down.rate=",
    "d.ratio=",
    "d.peers_complete=",
    "d.peers_accounted=",
    "d.left_bytes=",
    "d.timestamp.finished=",
]
TRACKER_FIELDS = ["t.url=", "t.scrape_complete=", "t.scrape_incomplete="]
FILE_FIELDS = ["f.path=", "f.size_bytes=", "f.priority="]
TIMEOUT = httpx.Timeout(300, connect=5)


class RtorrentError(RuntimeError):
    pass


def _tags(text: str) -> frozenset[str]:
    return frozenset(t for t in text.split(",") if t)


def _state(started: bool, active: bool, hashing: bool, failed: bool, done: float) -> str:
    """rTorrent's state in qBittorrent's names, which the rest of the app reads."""
    end = "UP" if done >= 1 else "DL"
    if hashing:
        return f"checking{end}"
    if failed:
        return "error"
    if not (started and active):
        return f"stopped{end}"
    return "uploading" if done >= 1 else "downloading"


class RtorrentApi:
    """Adapter over rTorrent's XML-RPC: its address, and a username and password if the
    web server in front of it asks for them."""

    client_name = "rTorrent"
    supports_category_tags = True
    requires_disk_renames = True
    supports_partial_reseeds = False  # its check creates every missing file
    can_delete_files = False  # its XML-RPC only removes the torrent

    def __init__(
        self, host: str, username: str = "", password: str = "", http: httpx.Client | None = None
    ) -> None:
        address = host.strip()
        if "://" not in address:
            address = "http://" + address
        parts = urlsplit(address)
        if parts.scheme == "scgi":
            if not (parts.path if not parts.hostname else parts.port):
                raise RtorrentError("Enter rTorrent's SCGI address as scgi://host:port")
            self._url = ""
            self._scgi: tuple[str, int] | str = (
                (parts.hostname, int(parts.port or 0)) if parts.hostname else parts.path
            )
        elif parts.scheme in {"http", "https"} and parts.hostname:
            self._url = (
                address.rstrip("/") if parts.path.strip("/") else address.rstrip("/") + "/RPC2"
            )
            self._scgi = ""
        else:
            raise RtorrentError("Enter rTorrent's XML-RPC address, for example https://host/RPC2")
        self._auth = httpx.BasicAuth(username, password) if username or password else None
        # Basic credentials ride on every request: once refused, none is sent again.
        self._guard = LoginGuard("rtorrent", address, username, password)
        self._address = self._url or address  # for messages; never holds the password
        self._http = http
        self._lock = threading.Lock()
        self.reseed_client_id = hashlib.sha256((address + "\0" + username).encode()).hexdigest()

    # Transport -------------------------------------------------------------

    def _call(self, method: str, *params: Any) -> Any:
        body = xmlrpc.client.dumps(params, method, allow_none=False).encode()
        try:
            reply = self._post_scgi(body) if self._scgi else self._post_http(body)
        except httpx.HTTPStatusError as e:
            raise RtorrentError(
                f"No rTorrent XML-RPC at {self._address} (HTTP {e.response.status_code}). "
                "Check the address: it often ends in /RPC2."
            ) from e
        except (OSError, httpx.HTTPError) as e:
            raise RtorrentError(f"rTorrent does not answer at {self._address}: {e}") from e
        try:
            return xmlrpc.client.loads(reply, use_builtin_types=True)[0][0]
        except xmlrpc.client.Fault as fault:
            raise RtorrentError(f"rTorrent: {fault.faultString}") from None
        except Exception as e:  # noqa: BLE001 - an HTML login page, a proxy's error page
            raise RtorrentError(f"rTorrent did not answer XML-RPC at this address ({e})") from e

    def _post_http(self, body: bytes) -> bytes:
        self._guard.check()
        if self._http is None:
            self._http = net.client(torrent_client=True, timeout=TIMEOUT, verify=False)
        response = self._http.post(
            self._url,
            content=body,
            headers={"Content-Type": "text/xml"},
            auth=self._auth or httpx.USE_CLIENT_DEFAULT,
        )
        if response.status_code in (401, 403):
            raise self._guard.refuse()
        response.raise_for_status()
        return response.content

    def _post_scgi(self, body: bytes) -> bytes:
        headers = {"CONTENT_LENGTH": str(len(body)), "SCGI": "1", "REQUEST_METHOD": "POST"}
        head = b"".join(k.encode() + b"\0" + v.encode() + b"\0" for k, v in headers.items())
        if isinstance(self._scgi, str):
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(TIMEOUT.read)
            connection.connect(self._scgi)
        else:
            connection = socket.create_connection(self._scgi, timeout=TIMEOUT.connect)
            connection.settimeout(TIMEOUT.read)
        with connection:
            connection.sendall(str(len(head)).encode() + b":" + head + b"," + body)
            reply = b""
            while chunk := connection.recv(65536):
                reply += chunk
        return reply.split(b"\r\n\r\n", 1)[-1]  # rTorrent answers with CGI headers first

    # Connection ------------------------------------------------------------

    def check(self) -> str:
        self._guard.rearm()  # the user pressed Test
        return str(self._call("system.client_version"))

    def default_save_path(self) -> str:
        return str(self._call("directory.default"))

    def folder_settings(self) -> list[ClientFolder]:
        folder = self.default_save_path()
        return [ClientFolder("", folder, "default")] if folder else []

    # Port ------------------------------------------------------------------

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        """Torrents, optionally without their file lists; two requests either way."""
        rows = self._call("d.multicall2", "", "main", *FIELDS)
        found = [self._torrent(row) for row in rows]
        if tag is not None:
            found = [(t, multi) for t, multi in found if tag in t.tags]
        return self._detailed(found, with_files)

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None:
        key = hash.upper()
        if key not in self._hashes():
            return None
        row = self._batch([(f.split("=")[0], key, *_argument(f)) for f in FIELDS])
        return self._detailed([self._torrent(row)], with_files)[0]

    def _detailed(self, found: list[tuple[Torrent, bool]], with_files: bool) -> list[Torrent]:
        """Add trackers, and file lists when asked, for every torrent in one request."""
        if not found:
            return []
        calls: list[tuple[Any, ...]] = []
        for t, _ in found:
            key = t.hash.upper()
            calls.append(("t.multicall", key, "", *TRACKER_FIELDS))
            if with_files:
                calls.append(("f.multicall", key, "", *FILE_FIELDS))
        replies = iter(self._batch(calls))
        detailed = []
        for t, multi in found:
            trackers = next(replies)
            urls = tuple(str(url) for url, *_ in trackers if url)
            files = (
                {f.name: f.size for f in _files(t.name, multi, next(replies))} if with_files else {}
            )
            detailed.append(
                replace(
                    t,
                    files=files,
                    tracker=urls[0] if urls else "",
                    trackers=urls,
                    swarm_seeders=max([*(int(s) for _, s, _ in trackers), -1]),
                    swarm_peers=max([*(int(p) for _, _, p in trackers), -1]),
                )
            )
        return detailed

    def _batch(self, calls: list[tuple[Any, ...]]) -> list[Any]:
        """Several calls in one request, each answer in order."""
        replies = self._call(
            "system.multicall", [{"methodName": c[0], "params": list(c[1:])} for c in calls]
        )
        for reply in replies:
            if isinstance(reply, dict):
                raise RtorrentError(f"rTorrent: {reply.get('faultString')}")
        return [reply[0] for reply in replies]

    def _hashes(self) -> set[str]:
        return {str(h).upper() for h in self._call("download_list")}

    @staticmethod
    def _torrent(row: list[Any]) -> tuple[Torrent, bool]:
        """The torrent, and whether it has a folder of its own."""
        f = dict(zip((name.split("=")[0] for name in FIELDS), row, strict=True))
        size = int(f["d.size_bytes"] or 0)
        done = int(f["d.completed_bytes"] or 0) / size if size else 0.0
        directory = str(f["d.directory"])
        # A multi-file torrent's directory is its own folder; the port wants the parent.
        save_path = str(PurePosixPath(directory).parent) if f["d.is_multi_file"] else directory
        finished = int(f["d.timestamp.finished"] or 0)
        rate, left = int(f["d.down.rate"] or 0), int(f["d.left_bytes"] or 0)
        torrent = Torrent(
            hash=str(f["d.hash"]).lower(),
            name=str(f["d.name"]),
            save_path=Path(save_path),
            files={},
            tags=_tags(str(f["d.custom"])),
            progress=done,
            state=_state(
                bool(f["d.state"]),
                bool(f["d.is_active"]),
                bool(f["d.hashing"]),
                bool(f["d.hashing_failed"]),
                done,
            ),
            size=size,
            category=str(f["d.custom1"]),
            download_rate=int(f["d.down.rate"] or 0),
            upload_rate=int(f["d.up.rate"] or 0),
            ratio=int(f["d.ratio"] or 0) / 1000,
            connected_seeds=int(f["d.peers_complete"] or 0),
            connected_peers=max(
                int(f["d.peers_accounted"] or 0) - int(f["d.peers_complete"] or 0), 0
            ),
            seeding_time=max(time.time() - finished, 0.0) if finished and done >= 1 else 0.0,
            eta=left // rate if rate and left else -1,
        )
        return torrent, bool(f["d.is_multi_file"])

    def file_listing(self, hash: str) -> list[TorrentFile]:
        key = hash.upper()
        name, multi, rows = self._batch(
            [("d.name", key), ("d.is_multi_file", key), ("f.multicall", key, "", *FILE_FIELDS)]
        )
        return _files(str(name), bool(multi), rows)

    def files(self, hash: str) -> dict[str, int]:
        return {f.name: f.size for f in self.file_listing(hash)}

    def reseed_layout(self, meta: TorrentMeta, match: Match) -> Match:
        """Refuse a Partial Match before adding anything: rTorrent's check would create
        each absent file inside the user's folder."""
        if match.unwanted or set(match.pairs) != set(meta.files):
            raise RtorrentError(
                "rTorrent cannot reseed a Partial Match: its check would create the missing "
                "files in your folder. Choose a Full Match, or reseed this one with "
                "qBittorrent, Transmission or Deluge."
            )
        if match.renames:
            raise RtorrentError(
                "rTorrent cannot rename files inside a torrent. Disk renaming must be "
                "explicitly confirmed before seeding this torrent."
            )
        return match

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        return self._add(data, save_path, tags, start=False)

    def download(
        self, data: bytes, save_path: str, tags: list[str], *, sequential: bool = False
    ) -> str:
        # rTorrent has no sequential download: it is left off.
        return self._add(data, save_path, tags, start=True)

    def _add(self, data: bytes, save_path: str, tags: list[str], *, start: bool) -> str:
        meta = read_torrent(data)
        key = meta.infohash.upper()
        with self._lock:
            if key in self._hashes():  # rTorrent ignores a duplicate without saying so
                raise AlreadyInClient(self.torrent(key, with_files=False))
            if start:  # rTorrent leaves a torrent inactive when its folder is missing
                self._make_folder(save_path)
            commands = [f'd.directory.set="{_quoted(save_path)}"']
            if tags:
                commands.append(f'd.custom.set={TAGS_KEY},"{_quoted(",".join(tags))}"')
            method = "load.raw_start" if start else "load.raw"
            self._call(method, "", xmlrpc.client.Binary(data), *commands)
            if key not in self._hashes():
                raise RtorrentError("rTorrent did not take in the torrent")
        return meta.infohash.lower()

    def _make_folder(self, path: str) -> None:
        """Create a download folder where rTorrent runs, which may be another machine."""
        try:
            self._call("execute.throw", "", "mkdir", "-p", "--", path)
        except RtorrentError as e:
            raise RtorrentError(f"rTorrent could not create the folder {path}: {e}") from e

    def rename_file(self, hash: str, old: str, new: str) -> None:
        raise RtorrentError("rTorrent cannot rename files inside a torrent")

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        """Priority 0 leaves the files out, as in qBittorrent; any other is rTorrent's normal."""
        key = hash.upper()
        for i in indexes:
            self._call("f.priority.set", f"{key}:f{i}", 0 if priority == 0 else 1)
        if indexes:
            self._call("d.update_priorities", key)

    def recheck(self, hash: str) -> None:
        self._call("d.check_hash", hash.upper())

    def piece_states(self, hash: str) -> list[int]:
        """Per piece: 0 missing, 2 verified (rTorrent's bitfield in hex, first piece first)."""
        key = hash.upper()
        bits = bytes.fromhex(str(self._call("d.bitfield", key)) or "")
        count = int(self._call("d.size_chunks", key))
        if not bits:
            return [2 if self._call("d.complete", key) else 0] * count
        return [2 if bits[i // 8] & (0x80 >> (i % 8)) else 0 for i in range(count)]

    def pause(self, hash: str) -> None:
        key = hash.upper()
        self._call("d.stop", key)
        self._call("d.close", key)

    def resume(self, hash: str) -> None:
        self.start(hash)

    def start(self, hash: str) -> None:
        key = hash.upper()
        self._call("d.open", key)
        self._call("d.start", key)

    def remove(self, hash: str, *, delete_files: bool = False) -> None:
        """Remove a torrent and keep its files: rTorrent's XML-RPC never deletes data,
        so deleting them is refused rather than silently skipped."""
        if delete_files:
            raise RtorrentError(
                "rTorrent cannot delete a torrent's files. Remove the torrent instead, which "
                "keeps its files, then delete them yourself if you no longer need them."
            )
        self._call("d.erase", hash.upper())

    def add_tags(self, hash: str, tags: list[str]) -> None:
        current = self._own_tags(hash)
        self._set_tags(hash, [*current, *(t for t in tags if t not in current)])

    def add_tags_many(self, hashes: list[str], tags: list[str]) -> None:
        for hash in hashes:
            self.add_tags(hash, tags)

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        self._set_tags(hash, [t for t in self._own_tags(hash) if t not in tags])

    def _own_tags(self, hash: str) -> list[str]:
        return [t for t in str(self._call("d.custom", hash.upper(), TAGS_KEY)).split(",") if t]

    def _set_tags(self, hash: str, tags: list[str]) -> None:
        self._call("d.custom.set", hash.upper(), TAGS_KEY, ",".join(tags))


def _files(name: str, multi: bool, rows: list[list[Any]]) -> list[TorrentFile]:
    """Paths relative to the save path: inside the torrent's folder when it has one."""
    prefix = f"{name}/" if multi else ""
    return [
        TorrentFile(i, prefix + str(path), int(size), int(priority) != 0)
        for i, (path, size, priority) in enumerate(rows)
    ]


def _argument(field: str) -> tuple[str, ...]:
    """The argument a multicall field carries after its `=`, such as a custom key."""
    value = field.split("=", 1)[1]
    return (value,) if value else ()


def _quoted(text: str) -> str:
    """A value inside one of rTorrent's quoted command arguments."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
