"""Owner-controlled device linking to the Community Site, separate from tracker activity."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import unicodedata
from typing import Any
from urllib.parse import urlsplit

import httpx

from torrentlinker import net

SITE_URL = "https://torrentlinker.fr"
LINK_SECRET = "community-site-link"


def membership_fingerprint(username: str) -> str:
    canonical = unicodedata.normalize("NFKC", username).strip().casefold()
    if not canonical:
        raise ValueError("Refresh your signed-in profile before joining the community.")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CommunitySite:
    def __init__(self, setup, *, transport=None, clock=time.time):
        self.setup = setup
        self.transport, self.clock = transport, clock
        self.lock = threading.RLock()
        self.pending: dict[str, Any] = {}

    def _link(self) -> dict:
        try:
            value = json.loads(self.setup.secrets.get(LINK_SECRET) or "{}")
        except (ValueError, TypeError):
            return {}
        if not isinstance(value, dict) or value.get("expires", 0) <= self.clock():
            return {}
        return value

    def _request(self, method: str, path: str, *, authenticated=False, **kwargs):
        headers = {"Accept": "application/json"}
        if authenticated:
            token = self._link().get("token")
            if not token:
                raise ValueError("Link this app to the community first.")
            headers["Authorization"] = "Bearer " + token
        try:
            with net.client(timeout=20, follow_redirects=False, transport=self.transport) as client:
                response = client.request(method, SITE_URL + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise ValueError("The Community Site could not be reached. Try again later.") from None
        if response.status_code in {401, 403}:
            if authenticated and (response.status_code == 401 or path == "/api/device/status"):
                self.setup.secrets.update({LINK_SECRET: ""})
            raise ValueError("Community access is unavailable. Sign in on the site and link again.")
        if len(response.content) > 1_000_000:
            raise ValueError("The Community Site returned an invalid response.")
        return response

    @staticmethod
    def _json(response) -> dict:
        if not response.is_success:
            if response.status_code == 429:
                raise ValueError("Too many requests. Wait a minute before trying again.")
            raise ValueError("The Community Site refused this operation. Try again later.")
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise ValueError("The Community Site returned an invalid response.") from None

    def state(self) -> dict:
        with self.lock:
            if self.pending.get("expires", 0) <= self.clock():
                self.pending = {}
            linked = self._link()
            return {
                "linked": bool(linked.get("token")),
                "expires": linked.get("expires"),
                "site": SITE_URL,
                "pending": {
                    key: self.pending[key]
                    for key in ("userCode", "verificationUri", "expires")
                    if key in self.pending
                },
                "poll_after": max(0, self.pending.get("next_poll", 0) - self.clock()),
            }

    def start(self, name: str = "TorrentLinker") -> dict:
        with self.lock:
            if self._link():
                raise ValueError("Unlink the existing community account first.")
            if self.state()["pending"]:
                return self.state()
            name = name.strip()
            if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
                raise ValueError("Use an app name between 1 and 80 characters.")
            # Fetch an authenticated profile now; never attest from an old cache alone.
            try:
                profile = self.setup.profile_workspace().refresh(
                    self.setup.settings.indexer.url, self.setup.secrets.get("indexer-api-key")
                )
                fingerprint = membership_fingerprint(profile.username)
            except Exception:
                raise ValueError(
                    "Refresh your signed-in profile before joining the community."
                ) from None
            data = self._json(
                self._request(
                    "POST",
                    "/api/device/request",
                    json={
                        "identityHash": fingerprint,
                        "signedIn": True,
                        "name": name,
                    },
                )
            )
            uri = str(data.get("verificationUri", ""))
            parsed = urlsplit(uri)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "torrentlinker.fr"
                or parsed.path not in {"/fr/link", "/en/link"}
                or parsed.query
                or parsed.fragment
                or not re.fullmatch(r"[A-F0-9]{10}", str(data.get("userCode", "")))
                or not re.fullmatch(r"[A-Za-z0-9_-]{40,60}", str(data.get("deviceCode", "")))
            ):
                raise ValueError("The Community Site returned an invalid link.")
            self.pending = {
                "deviceCode": data["deviceCode"],
                "userCode": data["userCode"],
                "verificationUri": uri,
                "identity": fingerprint,
                "expires": self.clock() + min(900, max(1, int(data.get("expiresIn", 900)))),
                "next_poll": self.clock() + max(5, int(data.get("interval", 5))),
            }
            return self.state()

    def poll(self) -> dict:
        with self.lock:
            state = self.state()
            if not state["pending"] or state["poll_after"] > 0:
                return state
            self.pending["next_poll"] = self.clock() + 5
            response = self._request(
                "POST",
                "/api/device/token",
                json={
                    "deviceCode": self.pending["deviceCode"],
                },
            )
            if response.status_code == 428:
                return self.state()
            if response.status_code == 429:
                self.pending["next_poll"] = self.clock() + 60
                return self.state()
            if response.status_code == 400:
                self.pending = {}
                raise ValueError("This link expired. Start again to get a new code.")
            data = self._json(response)
            token = data.get("accessToken", "")
            if data.get("tokenType") != "Bearer" or not re.fullmatch(
                r"[A-Za-z0-9_-]{40,128}", token
            ):
                raise ValueError("The Community Site returned an invalid token.")
            self.setup.secrets.update(
                {
                    LINK_SECRET: json.dumps(
                        {
                            "token": token,
                            "identity": self.pending["identity"],
                            "expires": self.clock()
                            + min(7776000, max(1, int(data.get("expiresIn", 0)))),
                        }
                    )
                }
            )
            self.pending = {}
            if hasattr(self, "achievements") and not self.achievements.closed:
                with self.achievements.lock:
                    self.achievements._check_link()
                    try:
                        self.achievements.identity()
                    except ValueError:
                        self.achievements.status = (
                            "Account identity unavailable; history stays local."
                        )
            return self.state()

    def check(self) -> dict:
        with self.lock:
            data = self._json(
                self._request("POST", "/api/device/status", authenticated=True, json={})
            )
            return {
                **self.state(),
                "account": {key: data.get(key) for key in ("name", "forumAccess")},
            }

    def disconnect(self) -> dict:
        with self.lock:
            if self._link():
                self._json(self._request("POST", "/api/device/revoke", authenticated=True, json={}))
            self.setup.secrets.update({LINK_SECRET: ""})
            self.pending = {}
            if hasattr(self, "achievements") and not self.achievements.closed:
                with self.achievements.lock:
                    self.achievements._check_link()
            return self.state()

    def request(self, action: str, values: dict | None = None) -> dict:
        values = values or {}
        if action.startswith("achievements-"):
            from torrentlinker.achievement_sync import achievement_sync

            return achievement_sync(self).request(action.removeprefix("achievements-"), values)
        if action.startswith("items-"):
            from torrentlinker.community_items import CommunityItems

            with self.lock:
                if not hasattr(self, "items"):
                    self.items = CommunityItems(self)
                return self.items.request(action.removeprefix("items-"), values)
        if action == "state":
            return self.state()
        if action == "start":
            return self.start(values.get("name", "TorrentLinker"))
        if action == "poll":
            return self.poll()
        if action == "check":
            return self.check()
        if action == "disconnect":
            return self.disconnect()
        raise ValueError("Unknown community operation.")


def community_site(setup) -> CommunitySite:
    root = setup._root or setup
    with root.lock:
        if not hasattr(root, "_community_site"):
            root._community_site = CommunitySite(root)
        return root._community_site
