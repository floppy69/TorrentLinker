"""Sessions and encrypted server credentials, independent of desktop keyring."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
import threading
import time
from pathlib import Path

from cryptography.fernet import Fernet

from torrentlinker.accounts import OWNER


def atomic_private(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    path.chmod(0o600)


class ServerSecrets:
    """Encrypt UI-entered secrets at rest; deployment secret files override them.

    Back up both the key and vault. Protect the entire configuration volume: encryption
    cannot protect against someone who can read both files.
    """

    def __init__(self, directory: Path, files: dict[str, Path] | None = None):
        self.directory = directory
        self.files = files or {}
        key = directory / "credentials.key"
        if not key.exists():
            atomic_private(key, Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        self.path = directory / "credentials.enc"
        self.lock = threading.Lock()
        self.values: dict[str, str] = (
            json.loads(self.cipher.decrypt(self.path.read_bytes())) if self.path.exists() else {}
        )

    def get(self, name: str) -> str:
        with self.lock:
            return (
                self.files[name].read_text().strip()
                if name in self.files
                else self.values.get(name, "")
            )

    def redact(self, text: str, *, public_urls: bool = False) -> str:
        from torrentlinker.torrent_management import safe_error

        if not text:
            return text
        with self.lock:
            values = list(self.values.values())
            for path in self.files.values():
                try:
                    values.append(path.read_text().strip())
                except OSError:
                    pass
        for value in values:
            if value:
                text = text.replace(value, "[secret]")
        if public_urls:
            from torrentlinker.assistant.privacy import safe_content

            return safe_content(text)
        return safe_error(ValueError(text))

    def update(self, values: dict[str, str]) -> None:
        with self.lock:
            if any(name in self.files for name in values):
                raise ValueError(
                    "This credential is managed by a secret file. Edit that file instead."
                )
            updated = {**self.values, **values}
            atomic_private(self.path, self.cipher.encrypt(json.dumps(updated).encode()))
            self.values = updated


class Sessions:
    """The Owner's browsers, signed in with the startup password; Members' are in Accounts.

    With a file, sign-ins survive a restart: it keeps only token digests, and a new startup
    password discards them."""

    def __init__(self, password: str, path: Path | None = None):
        if len(password) < 12:
            raise ValueError("Set a Web UI password of at least 12 characters.")
        self.path = path
        self.salt = secrets.token_bytes(16)
        self.tokens: dict[str, tuple[float, str]] = {}
        self.lock = threading.Lock()
        saved = self._read()
        if saved and secrets.compare_digest(
            self._scrypt(password, bytes.fromhex(saved["salt"])), bytes.fromhex(saved["check"])
        ):
            self.salt = bytes.fromhex(saved["salt"])
            now = time.time()
            self.tokens = {
                digest: (float(expiry), str(account))
                for digest, (expiry, account) in saved["tokens"].items()
                if float(expiry) > now
            }
        self.digest = self.hash(password)
        self._save()

    @staticmethod
    def _scrypt(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _read(self) -> dict | None:
        if self.path is None or not self.path.exists():
            return None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            return saved if {"salt", "check", "tokens"} <= set(saved) else None
        except (OSError, ValueError):
            return None

    def _save(self) -> None:
        if self.path is None:
            return
        tokens = {digest: [expiry, account] for digest, (expiry, account) in self.tokens.items()}
        payload = {"salt": self.salt.hex(), "check": self.digest.hex(), "tokens": tokens}
        atomic_private(self.path, json.dumps(payload).encode())

    def hash(self, password: str) -> bytes:
        return self._scrypt(password, self.salt)

    def verify(self, password: str) -> bool:
        return secrets.compare_digest(self.hash(password), self.digest)

    def login(self, password: str) -> str:
        if not self.verify(password):
            raise PermissionError("Incorrect password.")
        return self.open(OWNER)

    def open(self, account: str) -> str:
        with self.lock:
            now = time.time()
            self.tokens = {k: v for k, v in self.tokens.items() if v[0] > now}
            if len(self.tokens) >= 32:
                del self.tokens[next(iter(self.tokens))]
            token = secrets.token_urlsafe(32)
            self.tokens[self._key(token)] = (now + 12 * 3600, account)
            self._save()
            return token

    def account(self, token: str) -> str | None:
        with self.lock:
            expiry, account = self.tokens.get(self._key(token), (0.0, ""))
            return account if expiry > time.time() else None

    def valid(self, token: str) -> bool:
        return self.account(token) is not None

    def logout(self, token: str) -> None:
        with self.lock:
            if self.tokens.pop(self._key(token), None):
                self._save()


class Throttle:
    """Sign-in failures per account and per address: after 5, a lock of one minute that
    doubles on each repeat, up to 15 minutes. A success starts its keys over."""

    def __init__(self, failures: int = 5, first: float = 60, longest: float = 900):
        self.failures, self.first, self.longest = failures, first, longest
        self.state: dict[str, tuple[int, int, float]] = {}  # failures, locks, locked until
        self.lock = threading.Lock()

    def wait(self, *keys: str) -> float:
        """Seconds left before any of these keys may try again."""
        now = time.monotonic()
        with self.lock:
            return max([0.0, *(self.state.get(k, (0, 0, 0.0))[2] - now for k in keys)])

    def failed(self, *keys: str) -> bool:
        """Count a failure; True when it starts a lock."""
        locked = False
        with self.lock:
            if len(self.state) > 10_000:
                now = time.monotonic()
                self.state = {k: v for k, v in self.state.items() if v[2] > now}
            for key in keys:
                failures, locks, until = self.state.get(key, (0, 0, 0.0))
                failures += 1
                if failures >= self.failures:
                    until = time.monotonic() + min(self.first * 2**locks, self.longest)
                    failures, locks, locked = 0, locks + 1, True
                self.state[key] = (failures, locks, until)
        return locked

    def succeeded(self, *keys: str) -> None:
        with self.lock:
            for key in keys:
                self.state.pop(key, None)


# Read only from a trusted proxy's own address; names a Member (ADR-0016, amended by ADR-0022).
PROXY_USER_HEADER = "Remote-User"


class TrustedProxies:
    """Let the reverse proxy that signs users in stand for them, and nobody else."""

    def __init__(self, networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]):
        if not networks:
            raise ValueError("Set the trusted proxy networks for reverse-proxy sign-in.")
        self.networks = networks

    def allows(self, host: str | None) -> bool:
        try:
            address = ipaddress.ip_address(host or "")
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return any(address in network for network in self.networks)
