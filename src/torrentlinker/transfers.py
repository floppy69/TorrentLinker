"""Owner-reviewed transfers between accessible Torrent Client storage locations.

No remote transport is inferred from a client URL. Journal records contain paths,
not tracker credentials; original metainfo is held in private sidecar files.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from torrentlinker.torrent_management import safe_error
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.transfer_storage import (
    RemotePath,
    compare_content,
    file_path,
    free_space,
    identity,
    same_file,
    verify,
    writable,
)


def reconcile_copy(row, name, source_root, target_root):
    target = file_path(target_root, name)
    before = row["owned"].get(name)
    current = identity(target)
    if before is None or current[:2] != before[:2] or current[2] > row["files"][name]:
        raise ValueError("Destination file changed; it will not be overwritten")
    if current != before or isinstance(target, RemotePath):
        # A crash may occur after flushing a chunk but before saving the journal.
        with target.open("rb") as copied, file_path(source_root, name).open("rb") as source:
            while chunk := copied.read(1024 * 1024):
                if source.read(len(chunk)) != chunk:
                    raise ValueError("Destination copy changed outside this transfer")
        row["owned"][name] = current


class Transfers:
    def __init__(
        self,
        directory,
        client,
        metadata=None,
        client_ids=None,
        fingerprint=None,
        accessible=None,
        storage=None,
    ):
        self.storage = storage or (lambda cid, path: Path(path))
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.client = client
        self.client_ids = client_ids
        self.fingerprint = fingerprint or (lambda identifier: identifier)
        self.accessible = accessible or (lambda identifier, path: None)
        self.operation_locks = {}
        self.metadata = metadata or (lambda cid, key: self.client(cid).export_torrent(key))
        self.lock = threading.RLock()
        self.running = set()
        self.stops = {}
        self.tokens = {}
        for plan in self.list():
            if plan["status"] == "running":
                plan["status"] = "attention"
                for row in plan["rows"]:
                    if row["status"] != "confirmed":
                        row.update(
                            status="interrupted", error="Application stopped; resume after review"
                        )
                self._save(plan)

    def _path(self, identifier):
        if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            raise ValueError("Invalid transfer identifier")
        return self.directory / (identifier + ".json")

    def _save(self, plan):
        with self.lock:
            target = self._path(plan["id"])
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(plan))
            temp.chmod(0o600)
            os.replace(temp, target)

    def get(self, identifier):
        with self.lock:
            return json.loads(self._path(identifier).read_text())

    def list(self):
        return [self.get(p.stem) for p in sorted(self.directory.glob("*.json"))]

    def prepare(self, items, destination, *, remove_torrent=False, remove_files=False):
        plan = dict(
            id=secrets.token_hex(16),
            destination=destination,
            rows=[],
            remove_torrent=bool(remove_torrent),
            remove_files=bool(remove_files),
            status="review",
            can_start=False,
            clients={
                identifier: self.fingerprint(identifier)
                for identifier in {destination, *(i["client_id"] for i in items)}
            },
        )
        if not items or len(items) > 100:
            raise ValueError("Select between one and 100 torrents")
        sources = {i["client_id"] for i in items}
        occupied = set()
        for index, item in enumerate(items):
            row = dict(
                item,
                status="ready",
                error="",
                index=index,
                bytes=0,
                speed=0,
                fraction=0,
                history=[],
                owned={},
                cleanup_done=False,
            )
            plan["rows"].append(row)
            try:
                if destination in sources:
                    raise ValueError("The destination cannot be a source client")
                source = self.client(item["client_id"])
                torrent = source.torrent(item["hash"])
                if not torrent or torrent.progress < 1 or "checking" in torrent.state.lower():
                    raise ValueError("Source torrent is incomplete or being checked")
                if any(
                    t.startswith("torrentlinker:link") or t == "torrentlinker:verifying"
                    for t in torrent.tags
                ):
                    raise ValueError("Protected Reseed files cannot be transferred")
                data = self.metadata(item["client_id"], item["hash"])
                meta = read_torrent(data)
                if meta.infohash.lower() != item["hash"].lower():
                    raise ValueError("Torrent metadata does not match source")
                if meta.files != torrent.files:
                    raise ValueError("Renamed torrent files require their original layout")
                if self.client(destination).torrent(item["hash"]) is not None:
                    raise ValueError("Torrent already exists at destination")
                folder = str(item.get("folder", "")).strip()
                target_root = self.storage(destination, folder)
                source_root = self.storage(item["client_id"], torrent.save_path)
                folder_path = (
                    PurePosixPath(folder) if isinstance(target_root, RemotePath) else Path(folder)
                )
                if not folder or not folder_path.is_absolute() or not target_root.is_dir():
                    raise ValueError("Choose an existing accessible destination folder")
                self.accessible(item["client_id"], torrent.save_path)
                self.accessible(destination, folder)
                row.update(
                    name=torrent.name,
                    source=(
                        torrent.save_path.as_posix()
                        if isinstance(source_root, RemotePath)
                        else str(torrent.save_path)
                    ),
                    folder=folder,
                    files=meta.files,
                    total=sum(meta.files.values()),
                    identities={},
                )
                row["method"] = (
                    "shared"
                    if not isinstance(target_root, RemotePath)
                    and not isinstance(source_root, RemotePath)
                    and same_file(target_root, source_root)
                    else "copy"
                )
                if row["method"] == "shared" and remove_files:
                    raise ValueError("Shared source files cannot be deleted")
                for name, size in meta.files.items():
                    origin = file_path(self.storage(row["client_id"], row["source"]), name)
                    row["identities"][name] = identity(origin)
                    if origin.stat().st_size != size:
                        raise ValueError("Source file size changed")
                    target = file_path(target_root, name)
                    key = str(target.resolve())
                    if key in occupied:
                        raise ValueError("Selected torrents have overlapping destination files")
                    occupied.add(key)
                    if row["method"] == "copy" and target.exists():
                        raise ValueError(
                            "Destination file already exists; it will not be overwritten"
                        )
                if row["method"] == "copy" and free_space(target_root) < row["total"]:
                    raise ValueError("Insufficient destination space")
                sidecar = self.directory / f"{plan['id']}-{index}.torrent"
                sidecar.write_bytes(data)
                sidecar.chmod(0o600)
            except Exception as error:
                row.update(status="blocked", error=safe_error(error))
        required = {}
        for row in plan["rows"]:
            if row["status"] != "ready" or row["method"] == "shared":
                continue
            try:
                folder = self.storage(plan["destination"], row["folder"])
                device = folder.stat().st_dev
                required[device] = required.get(device, 0) + row["total"]
                if not writable(folder):
                    raise ValueError("Destination folder is not writable")
            except Exception as error:
                row.update(status="blocked", error=safe_error(error))
        for row in plan["rows"]:
            if row["status"] == "ready" and row["method"] == "copy":
                try:
                    folder = self.storage(plan["destination"], row["folder"])
                    if free_space(folder) < required[folder.stat().st_dev]:
                        raise ValueError("Insufficient destination space for the entire batch")
                except Exception as error:
                    row.update(status="blocked", error=safe_error(error))
        plan["can_start"] = all(r["status"] == "ready" for r in plan["rows"])
        self._save(plan)
        return plan

    def _check_clients(self, plan):
        if any(self.fingerprint(cid) != value for cid, value in plan["clients"].items()):
            raise ValueError("Client settings changed; prepare a new transfer")

    def stop(self, identifier):
        self.stops.setdefault(identifier, threading.Event()).set()
        return self.get(identifier)

    def start(self, identifier):
        with self.lock:
            if identifier in self.running:
                return self.get(identifier)
            plan = self.get(identifier)
            if not plan["can_start"]:
                raise ValueError("Resolve every blocker before starting this batch")
            plan["status"] = "running"
            self._save(plan)
            self.running.add(identifier)
            self.stops[identifier] = threading.Event()

        def work():
            try:
                self.run(identifier)
            except Exception as error:
                plan = self.get(identifier)
                plan["status"] = "attention"
                for row in plan["rows"]:
                    if row["status"] != "confirmed":
                        row.update(status="failed", error=safe_error(error))
                self._save(plan)
            finally:
                with self.lock:
                    self.running.discard(identifier)

        threading.Thread(target=work, daemon=True).start()
        return self.get(identifier)

    def run(self, identifier):
        with self.lock:
            operation = self.operation_locks.setdefault(identifier, threading.RLock())
        with operation:
            return self._run(identifier)

    def _run(self, identifier):
        plan = self.get(identifier)
        if not plan["can_start"]:
            raise ValueError("Resolve every blocker before starting this batch")
        self._check_clients(plan)
        # Validate the entire batch again before any copy or client mutation.
        needed = {}
        for row in plan["rows"]:
            if row["status"] == "confirmed":
                continue
            source = self.client(row["client_id"]).torrent(row["hash"])
            if (
                source is None
                or source.save_path != Path(row["source"])
                or source.files != row["files"]
            ):
                raise ValueError("Source registration changed; prepare a new plan")
            if (
                source.progress < 1
                or "checking" in source.state.lower()
                or any(
                    tag.startswith("torrentlinker:link") or tag == "torrentlinker:verifying"
                    for tag in source.tags
                )
            ):
                raise ValueError("Protected Reseed files cannot be transferred")
            existing = self.client(plan["destination"]).torrent(row["hash"])
            if existing and (
                "torrentlinker:transfer-" + identifier not in existing.tags
                or existing.save_path != Path(row["folder"])
            ):
                raise ValueError("Destination torrent belongs to another operation")
            for name, before in row["identities"].items():
                if (
                    identity(file_path(self.storage(row["client_id"], row["source"]), name))
                    != before
                ):
                    raise ValueError("Source files changed; prepare a new plan")
                target = file_path(self.storage(plan["destination"], row["folder"]), name)
                if row["method"] == "copy" and target.exists():
                    reconcile_copy(
                        row,
                        name,
                        self.storage(row["client_id"], row["source"]),
                        self.storage(plan["destination"], row["folder"]),
                    )
            if row["method"] == "copy":
                folder = self.storage(plan["destination"], row["folder"])
                device = folder.stat().st_dev
                previous = needed.get(device, (folder, 0))[1]
                remaining = row["total"] - sum(i[2] for i in row["owned"].values())
                needed[device] = (folder, previous + remaining)
        if any(free_space(folder) < size for folder, size in needed.values()):
            raise ValueError("Insufficient destination space for the entire batch")
        stop = self.stops.setdefault(identifier, threading.Event())
        plan["status"] = "running"
        self._save(plan)

        def process_row(row):
            if row["status"] == "confirmed":
                return

            def checkpoint():
                if stop.is_set():
                    raise InterruptedError("Transfer interrupted; source retained")

            def update(status, row=row, **values):
                if row["status"] != status:
                    row["history"].append({"status": status, "time": time.time()})
                row.update(status=status, **values)
                self._save(plan)

            try:
                checkpoint()
                for name, before in row["identities"].items():
                    if (
                        identity(file_path(self.storage(row["client_id"], row["source"]), name))
                        != before
                    ):
                        raise ValueError("Source files changed; prepare a new plan")
                source = self.client(row["client_id"])
                if source.torrent(row["hash"]) is None:
                    raise ValueError("Source torrent no longer exists")
                client = self.client(plan["destination"])
                tag = "torrentlinker:transfer-" + identifier
                existing = client.torrent(row["hash"])
                if existing and (
                    tag not in existing.tags or existing.save_path != Path(row["folder"])
                ):
                    raise ValueError("Destination torrent belongs to another operation")
                if existing:
                    client.pause(row["hash"])
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        current = client.torrent(row["hash"], with_files=False)
                        if current and current.state.lower().startswith(("paused", "stopped")):
                            break
                        checkpoint()
                        time.sleep(0.1)
                    else:
                        raise ValueError("Destination pause was not confirmed")
                if row["method"] == "copy":
                    update("copying", error="", speed=0)
                    started, done, sent = time.monotonic(), 0, 0
                    for name in row["files"]:
                        checkpoint()
                        origin, target = (
                            file_path(self.storage(row["client_id"], row["source"]), name),
                            file_path(self.storage(plan["destination"], row["folder"]), name),
                        )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if name in row["owned"]:
                            reconcile_copy(
                                row,
                                name,
                                self.storage(row["client_id"], row["source"]),
                                self.storage(plan["destination"], row["folder"]),
                            )
                        offset = row["owned"].get(name, [0, 0, 0])[2]
                        with (
                            origin.open("rb") as src,
                            target.open("ab" if name in row["owned"] else "xb") as dst,
                        ):
                            src.seek(offset)
                            done += offset
                            row["owned"][name] = identity(target)
                            self._save(plan)
                            while chunk := src.read(1024 * 1024):
                                checkpoint()
                                dst.write(chunk)
                                dst.flush()
                                done += len(chunk)
                                sent += len(chunk)
                                row["owned"][name] = identity(target)
                                update(
                                    "copying",
                                    bytes=done,
                                    fraction=done / max(1, row["total"]),
                                    speed=sent / max(0.01, time.monotonic() - started),
                                )
                        row["owned"][name] = identity(target)
                        self._save(plan)
                meta = read_torrent(
                    (self.directory / f"{identifier}-{row['index']}.torrent").read_bytes()
                )
                update("verifying", fraction=0, speed=0)
                verify(
                    self.storage(plan["destination"], row["folder"]),
                    meta,
                    checkpoint=checkpoint,
                    progress=lambda done, total, update=update: update(
                        "verifying", fraction=done / max(1, total)
                    ),
                )
                self._check_clients(plan)
                if not existing:
                    update("adding")
                    client.add(meta.data, row["folder"], [tag])
                client.recheck(row["hash"])
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    checkpoint()
                    torrent = client.torrent(row["hash"])
                    if (
                        torrent
                        and torrent.progress == 1
                        and "checking" not in torrent.state.lower()
                    ):
                        break
                    time.sleep(0.2)
                else:
                    raise ValueError("Destination verification timed out; source retained")
                update("seeding")
                client.start(row["hash"])
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    checkpoint()
                    torrent = client.torrent(row["hash"])
                    if (
                        torrent
                        and torrent.progress == 1
                        and torrent.state in {"uploading", "stalledUP", "forcedUP", "seeding"}
                    ):
                        break
                    time.sleep(0.2)
                else:
                    raise ValueError("Destination seeding not confirmed; source retained")
                update("confirmed", fraction=1)
            except InterruptedError as error:
                update("interrupted", error=str(error))
            except Exception as error:
                update("interrupted" if stop.is_set() else "failed", error=safe_error(error))

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(process_row, plan["rows"]))
        plan["status"] = (
            "complete" if all(r["status"] == "confirmed" for r in plan["rows"]) else "attention"
        )
        self._save(plan)
        return plan

    def review_cleanup(self, identifier, index):
        plan = self.get(identifier)
        self._check_clients(plan)
        if not isinstance(index, int) or not 0 <= index < len(plan["rows"]):
            raise ValueError("Invalid transfer item")
        if not (plan["remove_torrent"] or plan["remove_files"]):
            raise ValueError("No source cleanup was selected")
        row = plan["rows"][index]
        if row["status"] != "confirmed" or row["cleanup_done"]:
            raise ValueError("Confirm destination seeding first")
        destination = self.client(plan["destination"]).torrent(row["hash"])
        if (
            not destination
            or destination.progress != 1
            or destination.save_path != Path(row["folder"])
        ):
            raise ValueError("Destination changed; source retained")
        if plan["remove_files"] and row["method"] == "shared":
            raise ValueError("Shared files must remain")
        meta = read_torrent((self.directory / f"{identifier}-{index}.torrent").read_bytes())
        try:
            verify(
                self.storage(plan["destination"], row["folder"]),
                meta,
            )
        except ValueError as error:
            raise ValueError("Destination content verification failed; source retained") from error
        source = self.client(row["client_id"])
        torrent = source.torrent(row["hash"])
        if torrent is None and row.get("remove_started"):
            row["cleanup_done"] = True
            self._save(plan)
            raise ValueError("Source cleanup already completed")
        if (
            torrent is None
            or torrent.save_path != Path(row["source"])
            or torrent.files != row["files"]
        ):
            raise ValueError("Source registration changed; cleanup refused")
        if any(
            t.startswith("torrentlinker:link") or t == "torrentlinker:verifying"
            for t in torrent.tags
        ):
            raise ValueError("Protected Reseed files cannot be transferred")
        for name, before in row["identities"].items():
            path = file_path(self.storage(row["client_id"], row["source"]), name)
            if name in row.get("delete_started", []):
                if not path.exists():
                    continue
                if identity(path) != before:
                    raise ValueError("Source file changed; cleanup refused")
            if identity(path) != before:
                raise ValueError("Source file changed; cleanup refused")
            if plan["remove_files"]:
                target = file_path(self.storage(plan["destination"], row["folder"]), name)
                compare_content(path, target)
                if same_file(path, target):
                    raise ValueError("Destination still uses source files")
                identifiers = (
                    self.client_ids()
                    if self.client_ids
                    else {row["client_id"], plan["destination"]}
                )
                for client_id in identifiers:
                    for torrent in self.client(client_id).torrents():
                        if client_id == row["client_id"] and torrent.hash == row["hash"]:
                            continue
                        for other_name in torrent.files:
                            other = file_path(
                                self.storage(client_id, torrent.save_path), other_name
                            )
                            if other.exists() and same_file(other, path):
                                raise ValueError("Another torrent uses these source files")
        token = secrets.token_urlsafe(32)
        self.tokens[token] = (time.monotonic() + 300, identifier, index, plan)
        return {
            "token": token,
            "row": row,
            "remove_torrent": plan["remove_torrent"],
            "remove_files": plan["remove_files"],
        }

    def cleanup(self, identifier, index, token):
        with self.lock:
            operation = self.operation_locks.setdefault(identifier, threading.RLock())
        from torrentlinker.reseed import _LOCK

        with operation, _LOCK:
            return self._cleanup(identifier, index, token)

    def _cleanup(self, identifier, index, token):
        record = self.tokens.pop(token, None)
        if not record or record[1:3] != (identifier, index) or record[0] < time.monotonic():
            raise ValueError("Review this cleanup first")
        plan = self.get(identifier)
        if plan != record[3]:
            raise ValueError("Transfer changed; review cleanup again")
        check = self.review_cleanup(identifier, index)
        self.tokens.pop(check["token"], None)
        row = plan["rows"][index]
        client = self.client(row["client_id"])
        self._check_clients(plan)
        client.pause(row["hash"])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            torrent = client.torrent(row["hash"], with_files=False)
            if torrent and torrent.state.lower().startswith(("paused", "stopped")):
                break
            time.sleep(0.1)
        else:
            raise ValueError("Source pause was not confirmed; no files removed")
        if plan["remove_files"]:
            for name in row["files"]:
                path = file_path(self.storage(row["client_id"], row["source"]), name)
                if name in row.get("delete_started", []) and not path.exists():
                    continue
                if identity(path) != row["identities"][name]:
                    raise ValueError("Source file changed during cleanup")
                compare_content(
                    path, file_path(self.storage(plan["destination"], row["folder"]), name)
                )
                if name not in row.setdefault("delete_started", []):
                    row["delete_started"].append(name)
                self._save(plan)
                path.unlink()
                self._save(plan)
        if plan["remove_torrent"]:
            row["remove_started"] = True
            self._save(plan)
            client.remove(row["hash"])
        row["cleanup_done"] = True
        self._save(plan)
        return plan
