"""Explicit SFTP access for transfers, independent of Torrent Client credentials."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path, PurePath, PurePosixPath
from typing import Literal

import asyncssh
from pydantic import BaseModel, Field

from torrentlinker.web.security import atomic_private


class AccessConfig(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=256)
    auth: Literal["password", "key"] = "password"
    client_root: str = Field(min_length=1, max_length=4096)
    file_root: str = Field(min_length=1, max_length=4096)


def absolute(value):
    value = value.as_posix() if isinstance(value, PurePath) else value
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or "\\" in value or "\x00" in value:
        raise ValueError("Use an absolute path without parent traversal")
    return path


class RemoteAccess:
    def __init__(self, directory, secrets):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secrets = secrets
        self.path = self.directory / "access.json"
        self.profiles = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.lock = threading.RLock()
        self.loop = None
        self.thread = None
        self.connections = {}
        self.connect_locks = {}
        self.checked = set()
        self.closed = False

    def call(self, coroutine):
        with self.lock:
            if self.closed:
                coroutine.close()
                raise OSError("SFTP access is closed")
            if self.loop is None:
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
                self.thread.start()
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=45)
        except TimeoutError:
            future.cancel()
            raise OSError("SFTP operation timed out") from None

    def discover(self, values):
        config = AccessConfig.model_validate(values)
        absolute(config.client_root)
        absolute(config.file_root)
        key = self.call(asyncssh.get_server_host_key(config.host, config.port, config=None))
        if key is None:
            raise ValueError("Server identity is unavailable")
        return {
            "host_key": key.export_public_key().decode().strip(),
            "fingerprint": key.get_fingerprint(),
        }

    def save(self, identifier, values, credential, host_key):
        config = AccessConfig.model_validate(values).model_dump()
        absolute(config["client_root"])
        absolute(config["file_root"])
        if not host_key:
            raise ValueError("Confirm the server identity before saving access")
        key = asyncssh.import_public_key(host_key)
        if not credential and not self.secrets.get(self.secret_name(identifier)):
            raise ValueError("Enter file-access credentials")
        with self.lock:
            self.call(self.disconnect(identifier))
            self.checked.discard(identifier)
            if credential:
                self.secrets.update({self.secret_name(identifier): credential})
            self.profiles[identifier] = {
                **config,
                "host_key": key.export_public_key().decode().strip(),
            }
            atomic_private(self.path, json.dumps(self.profiles).encode())
        return self.snapshot(identifier)

    @staticmethod
    def secret_name(identifier):
        return "transfer-sftp-" + hashlib.sha256(identifier.encode()).hexdigest()

    def remove(self, identifier):
        """Forget access without changing any remote files or Torrent Client settings."""
        with self.lock:
            self.call(self.disconnect(identifier))
            self.checked.discard(identifier)
            previous = dict(self.profiles)
            updated = {key: value for key, value in previous.items() if key != identifier}
            atomic_private(self.path, json.dumps(updated).encode())
            try:
                self.secrets.update({self.secret_name(identifier): ""})
            except Exception:
                atomic_private(self.path, json.dumps(previous).encode())
                raise
            self.profiles = updated
        return self.snapshot(identifier)

    def snapshot(self, identifier):
        profile = self.profiles.get(identifier)
        if profile is None:
            return {"configured": False, "checked": False}
        key = asyncssh.import_public_key(profile["host_key"])
        return {
            **profile,
            "configured": True,
            "checked": identifier in self.checked,
            "fingerprint": key.get_fingerprint(),
            "has_credential": bool(self.secrets.get(self.secret_name(identifier))),
        }

    def fingerprint(self, identifier):
        if identifier not in self.profiles:
            return ""  # Preserve existing mounted-storage recovery fingerprints.
        return hashlib.sha256(
            json.dumps(self.profiles.get(identifier), sort_keys=True).encode()
            + self.secrets.get(self.secret_name(identifier)).encode()
        ).hexdigest()

    async def disconnect(self, identifier):
        pair = self.connections.pop(identifier, None)
        if pair:
            pair[0].close()
            await pair[0].wait_closed()

    async def connect(self, identifier):
        lock = self.connect_locks.setdefault(identifier, asyncio.Lock())
        async with lock:
            return await self._connect(identifier)

    async def _connect(self, identifier):
        pair = self.connections.get(identifier)
        if pair and not pair[0].is_closed():
            return pair[1]
        p = self.profiles[identifier]
        credential = self.secrets.get(self.secret_name(identifier))
        options = dict(
            host=p["host"],
            port=p["port"],
            username=p["username"],
            config=None,
            known_hosts=([asyncssh.import_public_key(p["host_key"])], [], []),
            agent_path=None,
            client_keys=[],
            password=None,
            connect_timeout=15,
            keepalive_interval=10,
            keepalive_count_max=2,
        )
        if p["auth"] == "key":
            options["client_keys"] = [asyncssh.import_private_key(credential)]
        else:
            options["password"] = credential
        conn = await asyncssh.connect(**options)
        try:
            sftp = await conn.start_sftp_client()
        except Exception:
            conn.close()
            raise
        self.connections[identifier] = (conn, sftp)
        return sftp

    def mapped(self, identifier, path):
        p = self.profiles[identifier]
        relative = absolute(path).relative_to(absolute(p["client_root"]))
        return str(absolute(p["file_root"]) / relative)

    async def check_path(self, identifier, path):
        sftp = await self.connect(identifier)
        mapped = self.mapped(identifier, path)
        for parent in reversed([PurePosixPath(mapped), *PurePosixPath(mapped).parents]):
            if await sftp.islink(str(parent)):
                raise ValueError("SFTP symlink paths are not supported")
        return sftp, mapped

    def check(self, identifier):
        async def run():
            p = self.profiles[identifier]
            sftp, path = await self.check_path(identifier, p["client_root"])
            if not await sftp.isdir(path):
                raise ValueError("The mapped folder does not exist")
            try:
                vfs = await sftp.statvfs(path)
            except asyncssh.SFTPOpUnsupported:
                raise ValueError("The server does not report available space") from None
            return vfs.bavail * vfs.frsize

        self.checked.discard(identifier)
        free = self.call(run())
        self.checked.add(identifier)
        return {**self.snapshot(identifier), "free_bytes": free}

    def browse(self, identifier, path):
        p = self.profiles[identifier]
        path = str(absolute(path or p["client_root"]))

        async def run():
            sftp, mapped = await self.check_path(identifier, path)
            folders = []
            for item in await sftp.listdir(mapped):
                if item in {".", ".."}:
                    continue
                remote = str(PurePosixPath(mapped) / item)
                if await sftp.isdir(remote) and not await sftp.islink(remote):
                    folders.append(str(PurePosixPath(path) / item))
            return sorted(folders)

        return {
            "path": path,
            "parent": str(PurePosixPath(path).parent) if path != p["client_root"] else path,
            "folders": self.call(run()),
        }

    def path_for(self, identifier, path):
        from torrentlinker.transfer_storage import RemotePath

        return (
            RemotePath(self, identifier, str(absolute(path)))
            if identifier in self.profiles
            else Path(path)
        )

    def close(self):
        if self.closed:
            return
        for identifier in list(self.connections):
            self.call(self.disconnect(identifier))
        self.closed = True
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=5)
