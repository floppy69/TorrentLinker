"""Durable in-app notices and opt-in mail/Web Push delivery for server Members."""

from __future__ import annotations

import base64
import json
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, Field, field_validator

from torrentlinker.accounts import OWNER, Permission

EVENTS = (
    "new-request",
    "new-wish",
    "cancelled",
    "accepted",
    "refused",
    "available",
    "wish-resolved",
    "margin",
    "invitation",
    "screen",
    "locked",
    "cross-added",
    "cross-failed",
    "cross-review",
    "cross-orphan",
)
OWNER_EVENTS = {
    "margin",
    "invitation",
    "screen",
    "locked",
    "cross-added",
    "cross-failed",
    "cross-review",
    "cross-orphan",
}
APPROVER_EVENTS = {"new-request", "new-wish", "cancelled"}


def address(value: str) -> str:
    value = value.strip()
    if value and (
        len(value) > 254
        or value.count("@") != 1
        or any(c.isspace() or c in "<>\r\n" for c in value)
    ):
        raise ValueError("Enter an email address.")
    return value


class Channels(BaseModel):
    browser: bool = False
    email: bool = False


class NoticeSettings(BaseModel):
    email_enabled: bool = False
    browser_enabled: bool = False
    host: str = Field(default="", max_length=253)
    port: int = Field(default=465, ge=1, le=65535)
    security: str = "ssl"
    username: str = Field(default="", max_length=254)
    sender: str = ""
    app_url: str = Field(default="", max_length=500)
    margin_gb: float = Field(default=0, ge=0, le=1_000_000, allow_inf_nan=False)
    defaults: dict[str, Channels] = Field(default_factory=dict)

    @field_validator("sender")
    @classmethod
    def sender_address(cls, value):
        return address(value)

    @field_validator("security")
    @classmethod
    def tls(cls, value):
        if value not in {"ssl", "starttls"}:
            raise ValueError("Choose SSL/TLS or STARTTLS.")
        return value

    @field_validator("app_url")
    @classmethod
    def application_url(cls, value):
        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.query
            ):
                raise ValueError("Use the app's HTTP(S) address without credentials.")
        return value.rstrip("/")

    @field_validator("defaults")
    @classmethod
    def events(cls, value):
        if set(value) - set(EVENTS):
            raise ValueError("Unknown notification event.")
        return value


class Preferences(BaseModel):
    email: str = ""
    events: dict[str, Channels] = Field(default_factory=dict)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        return address(value)

    @field_validator("events")
    @classmethod
    def known_events(cls, value):
        if set(value) - set(EVENTS):
            raise ValueError("Unknown notification event.")
        return value


class Notifications:
    def __init__(self, accounts, secrets, requests, approval):
        self.accounts, self.secrets = accounts, secrets
        self.requests, self.approval = requests, approval
        self.db, self.lock = accounts.db, accounts.lock
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.margin_at = 0.0
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS notice_options (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS notice_preferences (
                    account TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE, body TEXT
                );
                CREATE TABLE IF NOT EXISTS notices (
                    id INTEGER PRIMARY KEY, account TEXT REFERENCES accounts(id) ON DELETE CASCADE,
                    event TEXT, title TEXT, state TEXT, note TEXT,
                    created REAL, seen INTEGER DEFAULT 0,
                    dedup TEXT, UNIQUE(account,dedup)
                );
                CREATE TABLE IF NOT EXISTS notice_outbox (
                    notice INTEGER REFERENCES notices(id) ON DELETE CASCADE, channel TEXT,
                    attempts INTEGER DEFAULT 0, next_at REAL DEFAULT 0, PRIMARY KEY(notice,channel)
                );
                CREATE TABLE IF NOT EXISTS notice_subscriptions (
                    endpoint TEXT PRIMARY KEY,
                    account TEXT REFERENCES accounts(id) ON DELETE CASCADE,
                    body TEXT NOT NULL
                );
            """)
            if not self.db.execute("SELECT 1 FROM notice_options WHERE key='cursor'").fetchone():
                cursor = self.db.execute(
                    "SELECT COALESCE(MAX(rowid),0) FROM request_events"
                ).fetchone()[0]
                self.db.execute("INSERT INTO notice_options VALUES ('cursor',?)", (str(cursor),))

    def option(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM notice_options WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def settings(self) -> NoticeSettings:
        return NoticeSettings.model_validate(self.option("settings", {}))

    def save_settings(self, settings: NoticeSettings, password: str = "") -> None:
        if settings.email_enabled and (
            not settings.host or not settings.sender or not settings.app_url
        ):
            raise ValueError("Set the SMTP server, sender and app address before enabling email.")
        if settings.browser_enabled and not settings.app_url.startswith("https://"):
            raise ValueError("Browser notifications require the app's HTTPS address.")
        if password:
            self.secrets.update({"notifications:smtp": password})
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO notice_options VALUES ('settings',?)",
                (settings.model_dump_json(),),
            )

    def event_names(self, account: str) -> list[str]:
        actor = self.accounts.actor(account)
        if actor is None:
            return []
        return [
            event
            for event in EVENTS
            if event not in OWNER_EVENTS | APPROVER_EVENTS
            or event in OWNER_EVENTS
            and actor.owner
            or event in APPROVER_EVENTS
            and actor.holds(Permission.APPROVE)
        ]

    def preferences(self, account: str) -> Preferences:
        with self.lock:
            row = self.db.execute(
                "SELECT body FROM notice_preferences WHERE account=?", (account,)
            ).fetchone()
        return Preferences.model_validate_json(row[0]) if row else Preferences()

    def effective(self, account: str, event: str) -> Channels:
        config, prefs = self.settings(), self.preferences(account)
        chosen = prefs.events.get(event, config.defaults.get(event, Channels()))
        allowed = event in self.event_names(account)
        return Channels(
            browser=allowed and config.browser_enabled and chosen.browser,
            email=allowed and config.email_enabled and chosen.email and bool(prefs.email),
        )

    def save_preferences(self, account: str, prefs: Preferences) -> None:
        if set(prefs.events) - set(self.event_names(account)):
            raise ValueError("These events are not available to this account.")
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO notice_preferences VALUES (?,?)",
                (account, prefs.model_dump_json()),
            )

    def emit(self, account: str, event: str, title: str, state: str, *, note="", dedup="") -> None:
        if event not in self.event_names(account):
            return
        dedup = dedup or f"{event}:{time.time_ns()}"
        with self.lock, self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO notices (account,event,title,state,note,created,dedup) "
                "VALUES (?,?,?,?,?,?,?)",
                (account, event, title[:200], state[:100], note[:500], time.time(), dedup),
            )
            if not cursor.rowcount:
                return
            channels = self.effective(account, event)
            for channel in ("email", "browser"):
                if getattr(channels, channel):
                    self.db.execute(
                        "INSERT INTO notice_outbox (notice,channel) VALUES (?,?)",
                        (cursor.lastrowid, channel),
                    )

    def owner(self, event: str, title: str, state: str) -> None:
        self.emit(OWNER, event, title, state)

    def listing(self, account: str) -> dict:
        events = self.event_names(account)
        if not events:
            return {"notices": [], "unread": 0}
        placeholders = ",".join("?" for _ in events)
        with self.lock:
            rows = self.db.execute(
                "SELECT id,event,title,state,note,created,seen FROM notices "
                f"WHERE account=? AND event IN ({placeholders}) ORDER BY id DESC LIMIT 100",
                (account, *events),
            ).fetchall()
            unread = self.db.execute(
                f"SELECT COUNT(*) FROM notices WHERE account=? AND event IN ({placeholders}) "
                "AND seen=0",
                (account, *events),
            ).fetchone()[0]
        return {"notices": [dict(row) for row in rows], "unread": unread}

    def seen(self, account: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE notices SET seen=1 WHERE account=?", (account,))

    def collect(self) -> None:
        with self.lock, self.db:
            cursor = int(self.option("cursor", 0))
            rows = self.db.execute(
                "SELECT e.rowid AS event_id,e.state AS event_state,e.note AS event_note,r.* "
                "FROM request_events e JOIN requests r ON r.id=e.request "
                "WHERE e.rowid>? ORDER BY e.rowid",
                (cursor,),
            ).fetchall()
            for row in rows:
                state = row["event_state"]
                event = (
                    {
                        "pending": "new-wish" if row["origin_kind"] == "wish" else "new-request",
                        "cancelled": "cancelled",
                        "accepted": "wish-resolved" if row["origin_kind"] == "wish" else "accepted",
                        "refused": "refused",
                        "available": "available",
                    }
                ).get(state)
                if event:
                    recipients = [row["account"]]
                    if event in APPROVER_EVENTS:
                        recipients = [
                            r[0]
                            for r in self.db.execute("SELECT id FROM accounts WHERE disabled=0")
                            if (actor := self.accounts.actor(r[0]))
                            and actor.holds(Permission.APPROVE)
                        ]
                    for account in recipients:
                        self.emit(
                            account,
                            event,
                            row["title"],
                            state,
                            note=row["event_note"],
                            dedup=f"request:{row['event_id']}",
                        )
                cursor = row["event_id"]
            self.db.execute(
                "INSERT OR REPLACE INTO notice_options VALUES ('cursor',?)", (json.dumps(cursor),)
            )

    def public_key(self) -> str:
        with self.lock:
            encoded = self.secrets.get("notifications:vapid")
            if not encoded:
                generated = ec.generate_private_key(ec.SECP256R1())
                encoded = base64.b64encode(
                    generated.private_bytes(
                        serialization.Encoding.DER,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                ).decode()
                self.secrets.update({"notifications:vapid": encoded})
            key = serialization.load_der_private_key(base64.b64decode(encoded), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey):
                raise ValueError("Invalid VAPID key.")
            raw = key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def subscribe(self, account: str, subscription: dict) -> None:
        if not self.settings().browser_enabled:
            raise ValueError("Browser notifications are disabled.")
        self.public_key()
        endpoint = subscription.get("endpoint", "")
        parsed = urlsplit(endpoint)
        hosts = {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
        if (
            parsed.scheme != "https"
            or parsed.hostname not in hosts
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or len(endpoint) > 2000
        ):
            raise ValueError("Unsupported browser push endpoint.")
        keys = subscription.get("keys", {})
        if set(keys) != {"p256dh", "auth"} or any(
            not isinstance(v, str) or not 16 <= len(v) <= 150 for v in keys.values()
        ):
            raise ValueError("Invalid push subscription keys.")
        with self.lock, self.db:
            count = self.db.execute(
                "SELECT COUNT(*) FROM notice_subscriptions WHERE account=? AND endpoint<>?",
                (account, endpoint),
            ).fetchone()[0]
            if count >= 8:
                raise ValueError("At most eight browsers can receive notifications per account.")
            self.db.execute(
                "INSERT OR REPLACE INTO notice_subscriptions VALUES (?,?,?)",
                (endpoint, account, json.dumps({"endpoint": endpoint, "keys": keys})),
            )

    def unsubscribe(self, account: str, endpoint: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM notice_subscriptions WHERE account=? AND endpoint=?",
                (account, endpoint),
            )

    def send_email(self, recipient: str, title: str, state: str, url: str) -> None:
        config = self.settings()
        if not config.email_enabled or not address(recipient):
            raise ValueError("Email notifications are unavailable.")
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = (
            config.sender,
            recipient,
            "TorrentLinker notification",
        )
        message.set_content(f"{title}\n{state}\n\n{url}\n")
        context = ssl.create_default_context()
        connection = (
            smtplib.SMTP_SSL(config.host, config.port, timeout=15, context=context)
            if config.security == "ssl"
            else smtplib.SMTP(config.host, config.port, timeout=15)
        )
        with connection as smtp:
            if config.security == "starttls":
                smtp.starttls(context=context)
            if config.username:
                smtp.login(config.username, self.secrets.get("notifications:smtp"))
            smtp.send_message(message)

    def push(self, subscription: dict, payload: dict) -> None:
        from pywebpush import webpush

        config = self.settings()
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=self.secrets.get("notifications:vapid"),
            vapid_claims={"sub": config.app_url},
            timeout=15,
            ttl=3600,
        )

    def deliver(self) -> None:
        with self.lock:
            rows = self.db.execute(
                "SELECT o.channel,o.attempts,n.* FROM notice_outbox o "
                "JOIN notices n ON n.id=o.notice "
                "WHERE o.next_at<=? AND o.attempts<5 ORDER BY n.id LIMIT 10",
                (time.time(),),
            ).fetchall()
        for row in rows:
            if self.stop.is_set():
                return
            allowed = getattr(self.effective(row["account"], row["event"]), row["channel"])
            try:
                if allowed:
                    url = self.settings().app_url + (
                        "/#/requests" if row["event"] in APPROVER_EVENTS else "/#/media/video"
                    )
                    if row["channel"] == "email":
                        self.send_email(
                            self.preferences(row["account"]).email, row["title"], row["state"], url
                        )
                    else:
                        with self.lock:
                            subscriptions = self.db.execute(
                                "SELECT body FROM notice_subscriptions WHERE account=?",
                                (row["account"],),
                            ).fetchall()
                        for subscription in subscriptions:
                            if self.stop.is_set():
                                return
                            self.push(
                                json.loads(subscription[0]),
                                {
                                    "id": row["id"],
                                    "title": row["title"],
                                    "state": row["state"],
                                    "url": url,
                                },
                            )
            except Exception:
                with self.lock, self.db:
                    self.db.execute(
                        "UPDATE notice_outbox SET attempts=attempts+1,next_at=? "
                        "WHERE notice=? AND channel=?",
                        (
                            time.time() + min(3600, 30 * 2 ** row["attempts"]),
                            row["id"],
                            row["channel"],
                        ),
                    )
            else:
                with self.lock, self.db:
                    self.db.execute(
                        "DELETE FROM notice_outbox WHERE notice=? AND channel=?",
                        (row["id"], row["channel"]),
                    )

    def tick(self) -> None:
        self.approval.refresh(self.requests)
        self.collect()
        config = self.settings()
        if config.margin_gb and time.time() - self.margin_at > 60:
            self.margin_at = time.time()
            margin = self.approval.margin(0)
            if margin["capacity"] is not None and margin["downloading"] is not None:
                below = margin["capacity"] - margin["downloading"] < config.margin_gb * 1024**3
                if below and not self.option("margin_below", False):
                    self.owner("margin", "Download margin", "Below the configured threshold")
                with self.lock, self.db:
                    self.db.execute(
                        "INSERT OR REPLACE INTO notice_options VALUES ('margin_below',?)",
                        (json.dumps(below),),
                    )
        self.deliver()

    def start(self) -> None:
        def work():
            while not self.stop.wait(15):
                try:
                    self.tick()
                except Exception:
                    pass  # Retry on the next tick; never log raw SMTP/push credentials.

        self.worker = threading.Thread(target=work, name="member-notifications", daemon=True)
        self.worker.start()

    def close(self) -> None:
        self.stop.set()
        if self.worker:
            self.worker.join()
