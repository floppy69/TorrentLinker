"""Account-bound API cache and explicitly paired browser snapshots.

One-time codes live only in memory. Connection hashes and cached account data are
private on disk; changing the indexer or its key clears them. Browser snapshots
never change planning inputs.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from torrentlinker import net
from torrentlinker.community import CommunityActions
from torrentlinker.companion_downloads import CompanionDownloads, SessionFetchError
from torrentlinker.profile import ProfileClient, ProfileError, ProfileProblem, UserProfile
from torrentlinker.profile_history import ProfileDay, ProfileHistory

COMPANION_ROUTES = {
    f"/api/companion/{name}"
    for name in (
        "pair",
        "snapshot",
        "disconnect",
        "commands",
        "result",
        "actions-demand",
        "actions-observe",
        "actions-claim",
        "actions-receipt",
    )
}
DETAILS = {
    "actualDownloaded",
    "actualUploaded",
    "creditedDownloaded",
    "creditedUploaded",
    "totalSeedingTimeSec",
    "validatedUploadsCount",
}
LEDGER_LIMIT = 500  # Zen ledger entries per snapshot: about three months of payouts


AVATAR_MAX_BYTES = 2_000_000
AVATAR_RETRY = 3600.0  # seconds before a failed avatar is tried again
# Raster images by their first bytes, never by the server's word: no SVG, which can script.
AVATAR_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def image_type(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return next((kind for magic, kind in AVATAR_TYPES if data.startswith(magic)), None)


def avatar_url(source: str, url: str | None) -> str | None:
    """The avatar's absolute https URL, or None when it is missing or unsafe to fetch."""
    if not url:
        return None
    absolute = urljoin(source + "/", url)
    try:
        parts = urlsplit(absolute)
        parts.port  # noqa: B018 - raises on a malformed port
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return None if parts.hostname == "localhost" else absolute
    return None if not address.is_global else absolute


def fetch_avatar(url: str) -> bytes | None:
    """At most AVATAR_MAX_BYTES of a raster image; no key, cookie or credential is sent."""
    try:
        with (
            net.client(timeout=15, follow_redirects=True, max_redirects=3) as client,
            client.stream("GET", url) as response,
        ):
            if response.status_code != 200 or response.url.scheme != "https":
                return None
            data = b""
            for chunk in response.iter_bytes():
                data += chunk
                if len(data) > AVATAR_MAX_BYTES:
                    return None
    except (httpx.HTTPError, OSError):
        return None
    return data if image_type(data) else None


def extension_origin(origin: str) -> bool:
    return re.fullmatch(r"chrome-extension://[a-p]{32}", origin) is not None


def captured_at(data: dict[str, Any]) -> float:
    stamp = datetime.fromisoformat(data["capturedAt"].replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Capture time requires a timezone.")
    return stamp.timestamp()


def ledger_entries(ledger: Any) -> list[tuple[float, float]] | None:
    """(time, delta) from the companion's Zen ledger read, None when malformed."""
    if not isinstance(ledger, list) or len(ledger) > LEDGER_LIMIT:
        return None
    entries = []
    for entry in ledger:
        if not isinstance(entry, dict) or set(entry) != {"createdAt", "delta"}:
            return None
        delta = entry["delta"]
        if type(delta) not in (int, float) or not math.isfinite(delta) or abs(delta) > 1e12:
            return None
        try:
            entries.append((captured_at({"capturedAt": entry["createdAt"]}), float(delta)))
        except (ValueError, TypeError, AttributeError, OverflowError):
            return None
    return entries


def valid_snapshot(data: Any, now: float) -> bool:
    def text(value: Any) -> bool:
        return isinstance(value, str) and 0 < len(value) <= 160

    def number(value: Any) -> bool:
        return value is None or (
            type(value) in (int, float) and 0 <= value <= 1e30 and math.isfinite(value)
        )

    if not isinstance(data, dict) or set(data) - {"zenLedger"} != {
        "schema",
        "source",
        "capturedAt",
        "account",
        "profile",
        "details",
        "activeSeeds",
    }:
        return False
    if "zenLedger" in data and ledger_entries(data["zenLedger"]) is None:
        return False
    if (
        type(data["schema"]) is not int
        or data["schema"] != 1
        or data["source"] != "https://c411.org"
    ):
        return False
    account, profile, details, seeds = (
        data[k] for k in ("account", "profile", "details", "activeSeeds")
    )
    if (
        not isinstance(account, dict)
        or set(account) != {"id", "username"}
        or not all(text(v) for v in account.values())
    ):
        return False
    if not isinstance(profile, dict) or set(profile) != {"balance", "classSlug", "level"}:
        return False
    if (
        not number(profile["balance"])
        or not number(profile["level"])
        or not (profile["classSlug"] is None or text(profile["classSlug"]))
    ):
        return False
    if details is not None and (
        not isinstance(details, dict)
        or set(details) != DETAILS
        or not all(number(v) for v in details.values())
    ):
        return False
    if seeds is not None and (
        not isinstance(seeds, dict)
        or set(seeds) != {"total"}
        or type(seeds["total"]) is not int
        or not 0 <= seeds["total"] <= 1e12
    ):
        return False
    try:
        return -30 <= now - captured_at(data) <= 300
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False


class ProfileWorkspace:
    def __init__(
        self,
        directory: Path,
        clock: Callable[[], float] = time.time,
        history: ProfileHistory | None = None,
    ):
        self.path = directory / "profile-cache.json"
        self.avatar_path = directory / "profile-avatar.img"
        self.clock = clock
        self.history = history
        self.downloads = CompanionDownloads(lambda: self.clock())
        self.community = CommunityActions(directory, lambda: self.clock())
        self.lock = threading.RLock()
        self.data: dict[str, Any] = {}
        try:
            saved = json.loads(self.path.read_text())
            if isinstance(saved, dict):
                self.data = saved
        except (OSError, ValueError):
            pass
        self._code = ""
        self._code_until = 0.0
        self._pair: tuple[str, str] | None = None
        saved_pair = self.data.get("connection")
        if (
            isinstance(saved_pair, list)
            and len(saved_pair) == 2
            and all(isinstance(value, str) for value in saved_pair)
            and re.fullmatch(r"[a-f0-9]{64}", saved_pair[0])
            and extension_origin(saved_pair[1])
        ):
            self._pair = (saved_pair[0], saved_pair[1])
        self._client: tuple[tuple[object, ...], ProfileClient] | None = None
        self._last_attempt = 0.0
        self.error: str | None = None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(temp, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(self.data, output, allow_nan=False)
        os.replace(temp, self.path)

    def remember_receiver(self, port: int) -> None:
        with self.lock:
            self.data["receiver_port"] = port
            self._save()

    def receiver_port(self) -> int:
        port = self.data.get("receiver_port", 8767)
        return port if type(port) is int and 0 < port < 65536 else 8767

    def bind(self, url: str, key: str) -> str:
        parts = urlsplit(url)
        source = f"{parts.scheme}://{parts.netloc}"
        binding = hashlib.sha256((source + "\0" + key).encode()).hexdigest()
        with self.lock:
            if self.data.get("binding") != binding:
                self.data = {"binding": binding, "source": source}
                self.avatar_path.unlink(missing_ok=True)
                self._code, self._pair, self._client = "", None, None
                self.downloads.clear()
                self.error = None
                self._last_attempt = 0.0
                self._save()
        return binding

    def refresh(self, url: str, key: str) -> UserProfile:
        binding = self.bind(url, key)
        client_key = (binding, net.current())
        with self.lock:
            self._last_attempt = self.clock()
            if self._client is None or self._client[0] != client_key:
                self._client = (client_key, ProfileClient(url, key))
            client = self._client[1]
        try:
            profile = client.fetch()
        except ProfileError as error:
            with self.lock:
                if self.data.get("binding") == binding:
                    self.error = error.problem.value
                    if self.history and error.problem is not ProfileProblem.NO_KEY:
                        self.history.record_failure(binding)
            raise
        with self.lock:
            if self.data.get("binding") != binding:
                raise ProfileError(
                    ProfileProblem.FAILED, "Account settings changed; refresh again."
                )
            old_id = (self.data.get("api") or {}).get("account_id")
            if old_id and old_id != profile.account_id:
                self.disconnect()
            api = asdict(profile)
            api.pop("zen_class")
            self.data.update(api=api, api_updated_at=self.clock())
            self.error = None
            self._save()
            if self.history:
                self.history.record_api(binding, profile)
        self._update_avatar(binding, profile)
        return profile

    def _update_avatar(self, binding: str, profile: UserProfile) -> None:
        """Keep the account's avatar on disk; a failure only leaves the initial shown."""
        with self.lock:
            url = avatar_url(str(self.data.get("source") or ""), profile.avatar_url)
            known = self.data.get("avatar") or {}
            if url is None:
                if known:
                    self.data.pop("avatar", None)
                    self.avatar_path.unlink(missing_ok=True)
                    self._save()
                return
            if known.get("url") == url and (
                known.get("ok") or self.clock() - known.get("at", 0) < AVATAR_RETRY
            ):
                return
        data = fetch_avatar(url)  # outside the lock: it can take seconds
        with self.lock:
            if self.data.get("binding") != binding:
                return
            if data is not None:
                temp = self.avatar_path.with_name(self.avatar_path.name + ".tmp")
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                os.chmod(temp, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write(data)
                os.replace(temp, self.avatar_path)
            else:
                self.avatar_path.unlink(missing_ok=True)
            self.data["avatar"] = {"url": url, "ok": data is not None, "at": self.clock()}
            self._save()

    def avatar(self) -> tuple[bytes, str] | None:
        """The cached avatar and its image type, checked again on every read."""
        with self.lock:
            if not (self.data.get("avatar") or {}).get("ok"):
                return None
            try:
                data = self.avatar_path.read_bytes()
            except OSError:
                return None
        kind = image_type(data)
        return (data, kind) if kind else None

    def avatar_token(self) -> str | None:
        """Changes with the avatar, so pages can cache it by URL."""
        avatar = self.data.get("avatar") or {}
        if not avatar.get("ok") or not self.avatar_path.exists():
            return None
        return hashlib.sha256(str(avatar["url"]).encode()).hexdigest()[:12]

    def history_days(self) -> list[ProfileDay]:
        """The bound account's Profile history, oldest first; never another account's."""
        with self.lock:
            binding = self.data.get("binding")
            if not self.history or not binding:
                return []
            return self.history.days(binding)

    def state(self) -> dict[str, Any]:
        with self.lock:
            companion = self.data.get("companion")
            try:
                contribution = self.community.daily_contribution(self.community_account())
            except ValueError:
                contribution = None
            return {
                "community_contribution": contribution,
                "api": self.data.get("api"),
                "source": self.data.get("source"),
                "api_updated_at": self.data.get("api_updated_at"),
                "refresh_after": max(self.data.get("api_updated_at", 0), self._last_attempt) + 120,
                "error": self.error,
                "api_stale": bool(
                    self.data.get("api_updated_at")
                    and self.clock() - self.data["api_updated_at"] > 300
                ),
                "companion": companion,
                "received_at": self.data.get("received_at"),
                "paired": bool(self._pair),
                "stale": bool(companion and self.clock() - captured_at(companion) > 300),
                "downloads": {**self.downloads.state(), "enabled": self.session_downloads},
                "avatar": self.avatar_token(),
            }

    def pairing(self) -> dict[str, Any]:
        with self.lock:
            if not (self.data.get("api") or {}).get("account_id") or self.error:
                raise ValueError("Refresh the API profile successfully before pairing.")
            if self.data.get("source") != "https://c411.org":
                raise ValueError("The companion supports https://c411.org accounts.")
            self._code = secrets.token_urlsafe(32)
            self._code_until = self.clock() + 600
            return {"code": self._code, "expiresIn": 600}

    def disconnect(self) -> None:
        with self.lock:
            self._code, self._pair = "", None
            self.downloads.clear()
            self.data.pop("connection", None)
            self.data.pop("companion", None)
            self.data.pop("received_at", None)
            self.data.pop("session_downloads", None)
            self._save()

    def receive(
        self, route: str, origin: str, authorization: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        with self.lock:
            if not extension_origin(origin):
                raise PermissionError("Use the paired browser extension.")
            account = (self.data.get("api") or {}).get("account_id")
            if route == "/api/companion/pair":
                code = body.get("code")
                if (
                    not isinstance(code, str)
                    or not self._code
                    or self.clock() >= self._code_until
                    or not hmac.compare_digest(code.encode(), self._code.encode())
                ):
                    raise PermissionError("Pairing code invalid or expired.")
                if body.get("accountId") != account:
                    raise PermissionError("Different c411 account. Use the API profile account.")
                token = secrets.token_urlsafe(32)
                self._pair = (
                    hashlib.sha256(("Bearer " + token).encode()).hexdigest(),
                    origin,
                )
                self.data["connection"] = self._pair
                self.downloads.clear()
                self._save()
                self._code = ""
                return {"token": token}
            digest = hashlib.sha256(authorization.encode()).hexdigest()
            if (
                not self._pair
                or origin != self._pair[1]
                or not hmac.compare_digest(digest, self._pair[0])
            ):
                raise PermissionError("Pair again from the Profile tab.")
            if route == "/api/companion/disconnect":
                self.disconnect()
                return {"disconnected": True}
            if route.startswith("/api/companion/actions-"):
                if (
                    body.get("accountId") != account
                    or self.data.get("source") != "https://c411.org"
                ):
                    raise PermissionError("Different c411 account.")
                identity = str(account)
                if route.endswith("actions-demand"):
                    return self.community.demand(identity)
                if route.endswith("actions-observe"):
                    self.community.observe(identity, body.get("snapshot", {}))
                elif route.endswith("actions-claim"):
                    return {"command": self.community.claim(identity)}
                elif route.endswith("actions-receipt"):
                    self.community.receipt(identity, body)
                else:
                    raise ValueError("Unknown action route.")
                return {"accepted": True}
            if route == "/api/companion/commands":
                limit = body.get("limit", 1)
                if not self.session_downloads:
                    self.downloads.last_poll = self.clock()  # the tab is still there
                    return {"command": None, "commands": [], "concurrency": 1}
                return self.downloads.poll(str(account), limit if type(limit) is int else 1)
            if route == "/api/companion/result":
                if body.get("accountId") != account:
                    raise PermissionError("Different c411 account.")
                return self.downloads.receive(body)
            if route != "/api/companion/snapshot" or not valid_snapshot(body, self.clock()):
                raise ValueError("Snapshot fields or capture time invalid; read a new preview.")
            if body["account"]["id"] != account:
                raise PermissionError("Different c411 account. Use the API profile account.")
            previous = self.data.get("companion")
            if previous and captured_at(body) <= captured_at(previous):
                raise ValueError("Snapshot already received or older than current data.")
            body = dict(body)
            ledger = ledger_entries(body.pop("zenLedger", []))
            self.data.update(companion=body, received_at=self.clock())
            self._save()
            if self.history:
                self.history.record_companion(self.data["binding"], body)
                balance = body["profile"]["balance"]
                if ledger and balance is not None:
                    self.history.record_ledger(self.data["binding"], balance, ledger)
            return {"accepted": True}

    def community_account(self) -> str:
        with self.lock:
            account = (self.data.get("api") or {}).get("account_id")
            if self.data.get("source") != "https://c411.org" or not account:
                raise ValueError("Refresh the c411 profile first.")
            return str(account)

    def community_state(self) -> dict[str, Any]:
        with self.lock:
            account = self.community_account()
            self.community.discover(account)
            return {**self.community.state(account), "paired": bool(self._pair)}

    def community_update(self, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            account = self.community_account()
            if operation == "settings":
                self.community.settings(account, body)
            elif operation == "refresh":
                self.community.refresh(account, body.get("page", 1))
            elif operation == "save":
                self.community.save(account, body)
            elif operation == "control":
                self.community.control(
                    account, body.get("id", ""), body.get("action", ""), body.get("revision", 0)
                )
            else:
                raise ValueError("Unknown community operation.")
            return self.community_state()

    def test_download(self, infohash: str, request_id: str, actor: str = "owner") -> dict[str, Any]:
        with self.lock:
            if not self._pair:
                raise ValueError("Connect the companion first.")
            if not self.session_downloads:
                raise ValueError("Turn on session downloads in Settings → Companion first.")
            return self.downloads.submit(infohash, request_id, actor)

    @property
    def session_downloads(self) -> bool:
        """Owner opt-in; a session download never replaces an API one on its own."""
        with self.lock:
            return bool(self._pair) and self.data.get("session_downloads") is True

    def set_session_downloads(self, enabled: bool) -> bool:
        with self.lock:
            if enabled and not self._pair:
                raise ValueError("Connect the companion first.")
            if type(enabled) is not bool:
                raise ValueError("Use true or false.")
            self.data["session_downloads"] = enabled
            if not enabled:
                self.downloads.clear()
            self._save()
            return enabled

    def fetch_descriptor(self, infohash: str, timeout: float = 150.0) -> bytes:
        """One .torrent through the browser session; blocks. Never uses the API key."""
        with self.lock:
            if not self.session_downloads:
                raise SessionFetchError("Session downloads are off.")
            try:
                job = self.downloads.submit(
                    infohash, "app-" + secrets.token_hex(8), "app", keep=True
                )
            except ValueError as error:
                raise SessionFetchError(str(error)) from error
        deadline = time.monotonic() + timeout
        try:
            while True:
                with self.lock:
                    job = self.downloads.get(job["id"], "app")
                    if job["status"] == "complete":
                        raw = self.downloads.take(job["id"])
                        if raw is not None:
                            return raw
                        raise SessionFetchError("The descriptor was not kept.")
                    if job["status"] == "failed":
                        status = int(job.get("http_status") or 0)
                        raise SessionFetchError(
                            job.get("error") or "Session download failed.",
                            status,
                            int(job.get("retry_after") or 0),
                            fatal=job.get("reason") != "timeout",
                        )
                if time.monotonic() > deadline:
                    raise SessionFetchError("The browser did not answer in time.")
                time.sleep(0.1)
        except ValueError as error:  # the job expired
            raise SessionFetchError(str(error)) from error
        finally:
            with self.lock:
                self.downloads.take(job["id"])

    def set_download_concurrency(self, value: int) -> int:
        with self.lock:
            return self.downloads.set_concurrency(value)

    def download_test(self, identifier: str, actor: str = "owner") -> dict[str, Any]:
        with self.lock:
            return self.downloads.get(identifier, actor)
