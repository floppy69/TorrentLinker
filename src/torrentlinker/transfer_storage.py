"""File operations for the transfer service, using local or verified SFTP storage."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
from pathlib import PurePosixPath
from types import SimpleNamespace

import asyncssh
import torf


def identity(path):
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Not a regular file")
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def file_path(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or any(p in {"..", "/"} or "\\" in p or ":" in p for p in parts):
        raise ValueError("Unsafe torrent file path")
    path = root.joinpath(*parts)
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError("Symlink storage requires its protected Reseed workflow")
    return path


def free_space(path):
    return path.free_space() if isinstance(path, RemotePath) else shutil.disk_usage(path).free


def writable(path):
    if isinstance(path, RemotePath):
        # The exclusive probe is owned by this operation and is removed immediately.
        import secrets

        probe = path.joinpath(".torrentlinker-probe-" + secrets.token_hex(16))
        with probe.open("xb") as stream:
            stream.write(b"")
        probe.unlink()
        return True
    return os.access(path, os.W_OK | os.X_OK)


def same_file(left, right):
    if isinstance(left, RemotePath) != isinstance(right, RemotePath):
        return False
    return left.samefile(right)


def verify(root, meta, checkpoint=lambda: None, progress=lambda done, total: None):
    torrent = torf.Torrent.read_stream(io.BytesIO(meta.data), validate=False)
    hashes = torrent.metainfo["info"]["pieces"]
    length = meta.piece_length
    if length <= 0 or not hashes or len(hashes) % 20:
        raise ValueError("The torrent has no valid piece hashes")
    digest, filled, index, done = hashlib.sha1(), 0, 0, 0
    total = sum(meta.files.values())
    for name, size in meta.files.items():
        path = file_path(root, name)
        before = identity(path)
        if before[2] != size:
            raise ValueError("File size differs from the torrent")
        with path.open("rb") as stream:
            while chunk := stream.read(min(length - filled, 1024 * 1024)):
                checkpoint()
                digest.update(chunk)
                done += len(chunk)
                filled += len(chunk)
                progress(done, total)
                if filled == length:
                    if digest.digest() != hashes[index * 20 : (index + 1) * 20]:
                        raise ValueError("File contents do not match the torrent")
                    digest, filled, index = hashlib.sha1(), 0, index + 1
        if identity(path) != before:
            raise ValueError("File changed during verification")
    if filled:
        if digest.digest() != hashes[index * 20 : (index + 1) * 20]:
            raise ValueError("File contents do not match the torrent")
        index += 1
    if index * 20 != len(hashes):
        raise ValueError("Torrent piece count does not match the files")


class RemoteStream:
    def __init__(self, path, mode):
        self.path = path

        async def open_file():
            sftp, mapped = await path.access.check_path(path.identifier, str(path))
            return await sftp.open(mapped, mode, encoding=None)

        self.stream = path.access.call(open_file())

    def read(self, size):
        return self.path.access.call(self.stream.read(size))

    def write(self, data):
        return self.path.access.call(self.stream.write(data))

    def seek(self, offset):
        return self.path.access.call(self.stream.seek(offset))

    def flush(self):
        # Writes are acknowledged by the SFTP server before journaling.
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.path.access.call(self.stream.close())


class RemotePath:
    def __init__(self, access, identifier, path):
        self.access, self.identifier, self.path = access, identifier, PurePosixPath(path)
        access.mapped(identifier, str(self.path))

    def __str__(self):
        return str(self.path)

    def joinpath(self, *parts):
        return RemotePath(self.access, self.identifier, str(self.path.joinpath(*parts)))

    @property
    def parent(self):
        root = PurePosixPath(self.access.profiles[self.identifier]["client_root"])
        return RemotePath(
            self.access, self.identifier, str(self.path.parent if self.path != root else root)
        )

    @property
    def parents(self):
        root = PurePosixPath(self.access.profiles[self.identifier]["client_root"])
        return [
            RemotePath(self.access, self.identifier, str(p))
            for p in self.path.parents
            if p.is_relative_to(root)
        ]

    def stat(self):
        async def run():
            sftp, mapped = await self.access.check_path(self.identifier, str(self))
            attrs = await sftp.stat(mapped)
            canonical = await sftp.realpath(mapped)
            vfs = await sftp.statvfs(mapped)
            profile = self.access.profiles[self.identifier]
            return SimpleNamespace(
                st_dev=profile["host_key"] + ":" + str(vfs.fsid),
                st_ino=canonical,
                st_size=attrs.size,
                st_mtime_ns=attrs.mtime * 1_000_000_000 + (attrs.mtime_ns or 0),
                st_mode=attrs.permissions,
            )

        return self.access.call(run())

    def exists(self):
        try:
            self.stat()
            return True
        except (asyncssh.SFTPNoSuchFile, asyncssh.SFTPNoSuchPath):
            return False

    def is_dir(self):
        return stat.S_ISDIR(self.stat().st_mode)

    def is_symlink(self):
        async def run():
            sftp = await self.access.connect(self.identifier)
            return await sftp.islink(self.access.mapped(self.identifier, str(self)))

        return self.access.call(run())

    def resolve(self):
        # Include storage identity to distinguish the same path on different servers.
        profile = self.access.profiles[self.identifier]
        return profile["host_key"] + ":" + self.access.mapped(self.identifier, str(self))

    def samefile(self, other):
        if not isinstance(other, RemotePath):
            return False
        a, b = self.stat(), other.stat()
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)

    def free_space(self):
        async def run():
            sftp, mapped = await self.access.check_path(self.identifier, str(self))
            try:
                vfs = await sftp.statvfs(mapped)
            except asyncssh.SFTPOpUnsupported:
                raise ValueError("The server does not report available space") from None
            return vfs.bavail * vfs.frsize

        return self.access.call(run())

    def mkdir(self, parents=False, exist_ok=False):
        async def run():
            sftp, mapped = await self.access.check_path(self.identifier, str(self))
            await sftp.makedirs(mapped, exist_ok=exist_ok)
            await self.access.check_path(self.identifier, str(self))

        self.access.call(run())

    def open(self, mode):
        return RemoteStream(self, mode)

    def unlink(self):
        async def run():
            sftp, mapped = await self.access.check_path(self.identifier, str(self))
            await sftp.remove(mapped)

        self.access.call(run())


def compare_content(source, target):
    """Check source bytes against the verified destination before unlinking a source."""
    before = identity(source)
    with source.open("rb") as left, target.open("rb") as right:
        while chunk := left.read(1024 * 1024):
            if right.read(len(chunk)) != chunk:
                raise ValueError("Source content changed; cleanup refused")
        if right.read(1):
            raise ValueError("Source content changed; cleanup refused")
    if identity(source) != before:
        raise ValueError("Source content changed during cleanup review")
