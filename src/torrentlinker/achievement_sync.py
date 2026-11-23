"""Owner-only consent and bounded badge synchronization with the Community Site."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime

import httpx

from torrentlinker import net
from torrentlinker.achievements import Ledger
from torrentlinker.community_site import SITE_URL

SECRET = "community-achievement-sync"


class AchievementSync:
    def __init__(self, site):
        self.site = site
        self.setup = site.setup
        self.lock = threading.RLock()
        self.ledger = Ledger(self.setup.path.parent / "achievements.sqlite")
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.capabilities: dict[str, dict] = {}
        self.status = ""
        self.closed = False
        self.agent = None
        self.peer = None
        try:
            self.config = json.loads(self.setup.secrets.get(SECRET) or "{}")
        except (ValueError, TypeError):
            self.config = {}
        if not isinstance(self.config, dict):
            self.config = {}
        self._check_link()

    def _save(self):
        self.setup.secrets.update({SECRET: json.dumps(self.config)})

    def _fingerprint(self):
        token = self.site._link().get("token", "")
        return hashlib.sha256(token.encode()).hexdigest() if token else ""

    def _check_link(self):
        current = self._fingerprint()
        if self.config.get("link", "") != current or (
            not current and self.ledger.state("owner")["account"]
        ):
            self.ledger.bind("owner", "")
            self.capabilities.clear()
            self.config = {"link": current}
            self._save()
            if self.peer:
                self.peer.invalidate()

    def state(self):
        with self.lock:
            self._check_link()
            value = self.ledger.state("owner")
            return {
                **value,
                "pending": len(self.ledger.pending("owner")),
                "status": self.status,
                "pairing": bool(self.config.get("pairing")),
                "peers": self.peer.state() if self.peer else [],
            }

    def identity(self):
        self._check_link()
        data = self.site._json(
            self.site._request("GET", "/api/device/identity", authenticated=True)
        )
        if not all(
            isinstance(data.get(k), str) and 0 < len(data[k]) <= 160
            for k in ("accountId", "installationId")
        ):
            raise ValueError("Invalid Community account identity.")
        previous = self.config.get("accountId")
        if previous and previous != data["accountId"]:
            self.capabilities.clear()
            self.config.pop("pairing", None)
            self.config.pop("peers", None)
            if self.peer:
                self.peer.invalidate()
        self.ledger.bind("owner", data["accountId"])
        self.config.update(accountId=data["accountId"], installationId=data["installationId"])
        self._save()
        return data

    def _consent(self):
        data = self.site._json(
            self.site._request("GET", "/api/app-achievements", authenticated=True)
        )
        if (
            data.get("accountId") != self.ledger.state("owner")["account"]
            or data.get("installationId") != self.config.get("installationId")
            or data.get("definitionVersion") != 1
        ):
            self.disable()
            raise ValueError("Community identity changed. Reconnect before sharing.")
        return data

    def enable(self):
        with self.lock:
            self.identity()
            data = self._consent()
            epoch = data.get("consentEpoch")
            if data.get("sharing") is not True or not isinstance(epoch, str) or not epoch:
                raise ValueError("Enable app badge sharing in your member account first.")
            self._capability("achievements:write")
            self.ledger.sharing("owner", True, epoch)
            self.status = ""
            return self.state()

    def disable(self):
        with self.lock:
            self.ledger.sharing("owner", False)
            self.capabilities.pop("achievements:write", None)
            self.status = ""
            return self.state()

    def share_existing(self):
        with self.lock:
            self._check_link()
            data = self._consent()
            state = self.ledger.state("owner")
            if not data.get("sharing") or data.get("consentEpoch") != state["consentEpoch"]:
                self.disable()
                raise ValueError("Sharing consent changed. Enable sharing again first.")
            self.ledger.share_existing("owner")
            return self.state()

    def _capability(self, permission):
        cached = self.capabilities.get(permission, {})
        if cached.get("until", 0) > time.time() + 60:
            return cached["token"]
        data = self.site._json(
            self.site._request(
                "POST",
                "/api/device/capability",
                authenticated=True,
                json={"permissions": [permission]},
            )
        )
        try:
            expires = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00")).timestamp()
            valid = (
                data["accountId"] == self.config["accountId"]
                and data["installationId"] == self.config["installationId"]
                and data["permissions"] == [permission]
                and data["tokenType"] == "Bearer"
                and isinstance(data["accessToken"], str)
                and 0 < len(data["accessToken"]) <= 256
                and expires > time.time()
            )
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("The Community Site returned an invalid capability.")
        self.capabilities[permission] = {"token": data["accessToken"], "until": expires}
        return data["accessToken"]

    def scoped(self, path, permission, body):
        token = self._capability(permission)
        try:
            with net.client(
                timeout=15, follow_redirects=False, transport=self.site.transport
            ) as client:
                response = client.post(
                    SITE_URL + path,
                    json=body,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                )
        except httpx.HTTPError:
            raise ValueError(
                "Community synchronization is offline; local progress is retained."
            ) from None
        if len(response.content) > 1_000_000:
            raise ValueError("Invalid Community response.")
        if response.status_code in {401, 403}:
            self.capabilities.pop(permission, None)
            raise ValueError("Community permission expired or was revoked.")
        return response

    def proof(self, fingerprint):
        with self.lock:
            self.identity()
            if not self.config.get("pairing"):
                raise ValueError("Enable installation pairing first.")
            return self.site._json(
                self.scoped(
                    "/api/device/pair-proof", "ledger:pair", {"certificateFingerprint": fingerprint}
                )
            )

    def verify(self, proof, fingerprint):
        with self.lock:
            self.identity()
            if not self.config.get("pairing"):
                raise ValueError("Installation pairing is disabled.")
            data = self.site._json(
                self.scoped(
                    "/api/device/verify-pair",
                    "ledger:pair",
                    {"proof": proof, "certificateFingerprint": fingerprint},
                )
            )
            if (
                data.get("accountId") != self.config.get("accountId")
                or data.get("installationId") == self.config.get("installationId")
                or data.get("certificateFingerprint") != fingerprint
            ):
                raise ValueError("The peer account does not match.")
            return data

    def tick(self):
        with self.lock:
            self._check_link()
            state = self.ledger.state("owner")
            if not state["sharing"]:
                return
            data = self._consent()
            if not data.get("sharing") or data.get("consentEpoch") != state["consentEpoch"]:
                self.disable()
                return
            awards = self.ledger.pending("owner")
            if not awards:
                return
            response = self.scoped(
                "/api/app-achievements",
                "achievements:write",
                {"consentEpoch": state["consentEpoch"], "achievements": awards},
            )
            if response.status_code == 409:
                self.disable()
                return
            if self.site._json(response).get("ok") is not True:
                raise ValueError("The Community Site did not acknowledge these badges.")
            self.ledger.acknowledge("owner", state["account"], state["consentEpoch"], awards)
            self.status = ""

    def start(self, agent):
        self.agent = agent
        if self.closed:
            self.ledger = Ledger(self.setup.path.parent / "achievements.sqlite")
            self.closed = False
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        if self.config.get("pairing") and self.config.get("listen"):
            try:
                self.peers().start(*self.config["listen"])
            except (OSError, ValueError):
                self.status = "Pairing address unavailable. Choose the current local interface."
        self.thread = threading.Thread(target=self._run, daemon=True, name="achievement-sync")
        self.thread.start()

    def _run(self):
        retry = 300
        next_sync = 0.0
        while not self.stop.wait(30):
            try:
                if self.agent is not None:
                    with self.ledger.lock:
                        clients = [
                            r[0]
                            for r in self.ledger.db.execute(
                                "SELECT DISTINCT client FROM reseed_pending LIMIT 16"
                            )
                        ]
                    for client in clients:
                        if self.stop.is_set():
                            return
                        try:
                            setup = self.agent.setup.for_client(client)
                            if setup.settings.profile(client).enabled:
                                self.ledger.observe(client, setup.client())
                        except Exception:
                            continue
                if time.monotonic() >= next_sync:
                    self.tick()
                    if self.peer:
                        self.peer.synchronize(force=False)
                    retry = 300
                    next_sync = time.monotonic() + retry
            except Exception:
                self.status = "Synchronization unavailable; local progress is retained."
                next_sync = time.monotonic() + retry
                retry = min(3600, retry * 2)

    def close(self):
        self.stop.set()
        if self.peer:
            self.peer.close()
        if self.thread:
            self.thread.join(timeout=25)
        if not self.thread or not self.thread.is_alive():
            self.ledger.close()
            self.closed = True

    def peers(self):
        if self.peer is None:
            from torrentlinker.achievement_peers import PeerExchange

            self.peer = PeerExchange(self)
        return self.peer

    def backup(self):
        with self.lock:
            self.identity()
            pages, cursor = [], ""
            for _ in range(100):
                page = self.ledger.export("owner", after=cursor)
                pages.append(page)
                if len(page["events"]) < 500:
                    return {"schemaVersion": 1, "accountId": page["accountId"], "pages": pages}
                last = page["events"][-1]
                cursor = last["family"] + ":" + last["identity"]
            raise ValueError(
                "Use a private application-data backup for ledgers above 50,000 events."
            )

    def restore(self, document):
        with self.lock:
            self.identity()
            if (
                not isinstance(document, dict)
                or set(document) != {"schemaVersion", "accountId", "pages"}
                or type(document["schemaVersion"]) is not int
                or document["schemaVersion"] != 1
                or document["accountId"] != self.config["accountId"]
                or not isinstance(document["pages"], list)
                or len(document["pages"]) > 100
                or len(json.dumps(document)) > 20_000_000
            ):
                raise ValueError("Unsupported backup or different Site Account.")
            for page in document["pages"]:
                if (
                    not isinstance(page, dict)
                    or set(page) != {"schemaVersion", "accountId", "events"}
                    or type(page["schemaVersion"]) is not int
                    or page["schemaVersion"] != 1
                    or page["accountId"] != self.config["accountId"]
                    or not isinstance(page["events"], list)
                    or len(page["events"]) > 500
                ):
                    raise ValueError("Invalid ledger backup page.")
                for event in page["events"]:
                    self.ledger._validate_event(event)
            # Restoring evidence never restores transmission consent or peer keys.
            self.disable()
            self.config.pop("pairing", None)
            self.config.pop("peers", None)
            self._save()
            if self.peer:
                self.peer.close()
            for page in document["pages"]:
                self.ledger.merge("owner", self.config["accountId"], page)
            return self.state()

    def request(self, action, values):
        if action == "state":
            with self.lock:
                self._check_link()
                if self._fingerprint() and not self.ledger.state("owner")["account"]:
                    try:
                        self.identity()
                    except ValueError:
                        self.status = (
                            "Account identity unavailable; local evidence stays unattributed."
                        )
                return self.state()
        if action == "enable":
            return self.enable()
        if action == "disable":
            return self.disable()
        if action == "share-existing":
            return self.share_existing()
        if action == "sync":
            self.tick()
            if self.peer:
                self.peer.synchronize()
            return self.state()
        if action == "recover":
            from torrentlinker.achievement_history import recover

            with self.lock:
                return {**self.state(), "recovery": recover(self, self.agent)}
        if action == "backup":
            return self.backup()
        if action == "restore":
            if values.get("confirmed") is not True:
                raise ValueError("Review the backup before merging it.")
            return self.restore(values.get("document"))
        if action == "reset":
            if values.get("confirmed") is not True:
                raise ValueError("Confirm the local reset first.")
            with self.lock:
                self.disable()
                for key in ("pairing", "peers", "certificate", "privateKey", "listen"):
                    self.config.pop(key, None)
                self._save()
                if self.peer:
                    self.peer.close()
                    self.peer = None
                self.ledger.reset("owner")
                return self.state()
        if action == "pair-enable":
            with self.lock:
                self.identity()
                self._capability("ledger:pair")
                self.config["pairing"] = True
                self._save()
                return self.state()
        if action == "pair-disable":
            with self.lock:
                self.config.pop("pairing", None)
                self.config.pop("peers", None)
                self.capabilities.pop("ledger:pair", None)
                self._save()
                if self.peer:
                    self.peer.close()
                return self.state()
        if action == "invitation":
            from torrentlinker.achievement_peers import endpoint

            host, port = endpoint(values.get("endpoint"))
            if not port:
                raise ValueError("Choose a port between 1 and 65535.")
            invitation = self.peers().invitation(values["endpoint"])
            self.peers().close()
            self.peers().start(host, port)
            self.config["listen"] = [host, port]
            self._save()
            return invitation
        if action == "pair-inspect":
            with self.lock:
                self.identity()
                invitation = values.get("invitation")
                fp = self.peers().inspect(invitation)
                return {
                    "fingerprint": fp,
                    "installationId": invitation["installationId"],
                    "endpoint": invitation["endpoint"],
                }
        if action == "pair-add":
            if values.get("confirmed") is not True:
                raise ValueError("Confirm the peer fingerprint first.")
            self.peers().add(values.get("invitation"))
            return self.state()
        if action == "pair-remove":
            self.peers().remove(values.get("fingerprint"))
            return self.state()
        raise ValueError("Unknown achievement operation.")


def achievement_sync(site):
    with site.lock:
        if not hasattr(site, "achievements") or site.achievements.closed:
            site.achievements = AchievementSync(site)
        return site.achievements
