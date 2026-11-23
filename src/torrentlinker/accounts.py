"""Accounts that share a server: the Owner and Members, their Permissions and caps (ADR-0022)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from torrentlinker import age_ratings

OWNER = "owner"  # the fixed account of the Owner; never restricted, edited or deleted
SESSION_IDLE = 30 * 86400  # a Member's session ends after 30 days of disuse
SCREEN_IDLE = 90 * 86400  # a Shared Screen's after 90 days of disuse
PICKING = "?"  # the Viewer of a Shared Screen until someone chooses who watches
LINK_DAYS = (1, 3, 7)  # an invitation or password link is valid 24 h, 3 or 7 days


class Permission(StrEnum):
    """One thing a Member may see or do. What acts on the Owner's c411 account is never one."""

    FILMS = "films"
    SERIES = "series"
    ANIME = "anime"
    MUSIC = "music"
    MEDIA_CENTER = "media-center"
    ADULT = "adult"
    REQUEST = "request"
    WISH = "wish"
    SEARCH = "search"
    ASSISTANT = "assistant"
    QUEUE = "queue"
    TORRENTS = "torrents"
    APPROVE = "approve"
    MANAGE_MEMBERS = "manage-members"
    EDIT_RATINGS = "edit-ratings"


WATCH = (Permission.FILMS, Permission.SERIES, Permission.ANIME, Permission.MUSIC)
# A Viewer holds only these, never more than its account.
MEDIA = frozenset({*WATCH, Permission.MEDIA_CENTER, Permission.ADULT})


@dataclass(frozen=True)
class Actor:
    """Who makes a request: an account holder, or a Viewer watching under one."""

    account: str
    permissions: frozenset[Permission]
    viewer: str = ""
    # What Médias shows them (#131): an Age Rating rank at most (None: no limit), and the
    # Library Folders by path (None: every folder, those added later included).
    age_limit: int | None = None
    folders: frozenset[str] | None = None
    screen: str = ""  # the Shared Screen this actor watches on, if any

    @property
    def owner(self) -> bool:
        return self.account == OWNER and not self.viewer

    def holds(self, permission: Permission) -> bool:
        return self.owner or permission in self.permissions


OWNER_ACTOR = Actor(OWNER, frozenset(Permission))


@dataclass(frozen=True)
class Caps:
    """A Member's optional limits; None means no limit."""

    requests_per_week: int | None = None
    bytes_per_week: int | None = None
    pending: int | None = None
    assistant_per_day: int = 20


class Accounts:
    def __init__(self, directory: Path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "accounts.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, login TEXT UNIQUE,
                    proxy_user TEXT UNIQUE, password TEXT NOT NULL DEFAULT '',
                    disabled INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS permissions (
                    account TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    permission TEXT NOT NULL, PRIMARY KEY(account, permission)
                );
                CREATE TABLE IF NOT EXISTS caps (
                    account TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                    requests_per_week INTEGER, bytes_per_week INTEGER, pending INTEGER,
                    assistant_per_day INTEGER NOT NULL DEFAULT 20
                );
                CREATE TABLE IF NOT EXISTS media_limits (
                    account TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                    age_limit INTEGER, folders TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY,
                    account TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    created REAL NOT NULL, used REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS viewers (
                    id TEXT PRIMARY KEY,
                    account TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, permissions TEXT NOT NULL, age_limit INTEGER,
                    pin TEXT NOT NULL DEFAULT '', created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS holder_pins (
                    account TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                    pin TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS screens (
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE,
                    account TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, viewer TEXT, created REAL NOT NULL, used REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS links (
                    digest TEXT PRIMARY KEY,
                    account TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, inviter TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, expires REAL NOT NULL, used REAL
                );
            """)
            self.db.execute(
                "INSERT OR IGNORE INTO accounts (id, name, created) VALUES (?, 'Owner', ?)",
                (OWNER, time.time()),
            )
        self.link_key = private_key(directory / "accounts.key")

    def close(self) -> None:
        self.db.close()

    def actor(self, account: str) -> Actor | None:
        """The actor an account signs in as; None when it is unknown or disabled."""
        if account == OWNER:
            return OWNER_ACTOR
        with self.lock:
            row = self.db.execute("SELECT disabled FROM accounts WHERE id=?", (account,)).fetchone()
            if row is None or row["disabled"]:
                return None
            granted = self.db.execute(
                "SELECT permission FROM permissions WHERE account=?", (account,)
            ).fetchall()
        known = {p.value for p in Permission}
        age_limit, folders = self.media_limits(account)
        return Actor(
            account,
            frozenset(Permission(r["permission"]) for r in granted if r["permission"] in known),
            age_limit=age_limit,
            folders=None if folders is None else frozenset(folders),
        )

    def create(
        self,
        name: str,
        login: str,
        permissions: Iterable[Permission] = (),
        *,
        password: str = "",
        proxy_user: str = "",
    ) -> str:
        """Add a Member with these Permissions, signing in with this password or proxy name."""
        if not login.strip():
            raise ValueError("Give the Member a display name and a sign-in name.")
        identifier = uuid4().hex
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO accounts (id, name, created) VALUES (?,'',?)",
                (identifier, time.time()),
            )
            self._identify(identifier, name, login, proxy_user)
            if password:
                self._password(identifier, password)
            self.db.execute("INSERT INTO caps (account) VALUES (?)", (identifier,))
            self._grant(identifier, permissions)
        return identifier

    def update(self, account: str, name: str, login: str, proxy_user: str = "") -> None:
        """Rename a Member, or change how they sign in."""
        with self.lock, self.db:
            self._member(account)
            self._identify(account, name, login, proxy_user)

    def _identify(self, account: str, name: str, login: str, proxy_user: str) -> None:
        name, login = name.strip(), login.strip()
        if not login and self._invited(account):
            login = ""  # the invited person chooses it with their link
        elif not login:
            raise ValueError("Give the Member a display name and a sign-in name.")
        if not name or len(name) > 100 or len(login) > 100:
            raise ValueError("Give the Member a display name and a sign-in name.")
        if self.db.execute(
            "SELECT 1 FROM accounts WHERE login=? COLLATE NOCASE AND id<>?", (login, account)
        ).fetchone():
            raise ValueError("This sign-in name is already used.")
        self.db.execute(
            "UPDATE accounts SET name=?, login=? WHERE id=?", (name, login or None, account)
        )
        self._proxy_user(account, proxy_user)

    def set_proxy_user(self, account: str, proxy_user: str) -> None:
        """The name the trusted proxy sends for this account; the Owner may have one too."""
        with self.lock, self.db:
            if account != OWNER:
                self._member(account)
            self._proxy_user(account, proxy_user)

    def _proxy_user(self, account: str, proxy_user: str) -> None:
        proxy_user = proxy_user.strip()
        if len(proxy_user) > 200:
            raise ValueError("The proxy's user name is too long.")
        if (
            proxy_user
            and self.db.execute(
                "SELECT 1 FROM accounts WHERE proxy_user=? COLLATE NOCASE AND id<>?",
                (proxy_user, account),
            ).fetchone()
        ):
            raise ValueError("Another account already has this proxy user name.")
        self.db.execute(
            "UPDATE accounts SET proxy_user=? WHERE id=?", (proxy_user or None, account)
        )

    def by_proxy_user(self, proxy_user: str) -> str | None:
        with self.lock:
            row = self.db.execute(
                "SELECT id FROM accounts WHERE proxy_user=? COLLATE NOCASE", (proxy_user,)
            ).fetchone()
        return row["id"] if row else None

    def proxy_users(self) -> bool:
        """Whether any account is named by the proxy; until then its user header is ignored."""
        with self.lock:
            return bool(
                self.db.execute("SELECT 1 FROM accounts WHERE proxy_user IS NOT NULL").fetchone()
            )

    def members(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM accounts WHERE id<>? ORDER BY name COLLATE NOCASE", (OWNER,)
            ).fetchall()
            granted = self.db.execute("SELECT * FROM permissions").fetchall()
            links = {r["account"]: r for r in self._open_links()}
        known = {p.value for p in Permission}
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "login": r["login"] or "",
                "proxy_user": r["proxy_user"] or "",
                "disabled": bool(r["disabled"]),
                "has_password": bool(r["password"]),
                "permissions": sorted(
                    g["permission"]
                    for g in granted
                    if g["account"] == r["id"] and g["permission"] in known
                ),
                "caps": vars(self.caps(r["id"])),
                **self._public_limits(r["id"]),
                "invited": not r["login"] and not r["password"],
                "link": (
                    {
                        "kind": links[r["id"]]["kind"],
                        "expires": links[r["id"]]["expires"],
                        "expired": links[r["id"]]["expires"] < time.time(),
                    }
                    if r["id"] in links
                    else None
                ),
            }
            for r in rows
        ]

    def display_name(self, account: str) -> str:
        """A Member's display name; empty for the Owner, whom the screens call the owner."""
        if account == OWNER:
            return ""
        with self.lock:
            row = self.db.execute("SELECT name FROM accounts WHERE id=?", (account,)).fetchone()
        return row["name"] if row else ""

    def owner_proxy_user(self) -> str:
        with self.lock:
            row = self.db.execute("SELECT proxy_user FROM accounts WHERE id=?", (OWNER,)).fetchone()
        return row["proxy_user"] or ""

    def set_password(self, account: str, password: str) -> None:
        """Change a Member's password; every session of the account ends."""
        with self.lock, self.db:
            self._member(account)
            if self._invited(account):
                raise ValueError("This Member chooses a sign-in name with their invitation first.")
            self._password(account, password)
            self._sign_out(account)

    def _sign_out(self, account: str) -> None:
        """End every session and Shared Screen of the account."""
        self.db.execute("DELETE FROM sessions WHERE account=?", (account,))
        self.db.execute("DELETE FROM screens WHERE account=?", (account,))
        if self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='notice_subscriptions'"
        ).fetchone():
            self.db.execute("DELETE FROM notice_subscriptions WHERE account=?", (account,))

    def _password(self, account: str, password: str) -> None:
        if not 12 <= len(password) <= 1024:
            raise ValueError("Use a password of at least 12 characters.")
        salt = secrets.token_bytes(16)
        stored = f"scrypt${salt.hex()}${scrypt(password, salt).hex()}"
        self.db.execute("UPDATE accounts SET password=? WHERE id=?", (stored, account))

    def check_password(self, account: str, password: str) -> bool:
        """Whether this is the Member's password, to reset a PIN or change the password."""
        with self.lock:
            row = self.db.execute(
                "SELECT login FROM accounts WHERE id=? AND id<>?", (account, OWNER)
            ).fetchone()
        return bool(row and row["login"]) and self.verify(row["login"], password) == account

    def verify(self, login: str, password: str) -> str | None:
        """The enabled Member signing in with this name and password, or None."""
        with self.lock:
            row = self.db.execute(
                "SELECT id, password, disabled FROM accounts "
                "WHERE login=? COLLATE NOCASE AND id<>?",
                (login.strip(), OWNER),
            ).fetchone()
        stored = row["password"] if row else ""
        _, salt, digest = stored.split("$") if stored.count("$") == 2 else ("", "00" * 16, "")
        # Hash even for an unknown name, so the time taken does not tell which field was wrong.
        matches = secrets.compare_digest(scrypt(password, bytes.fromhex(salt)).hex(), digest)
        return row["id"] if row and matches and not row["disabled"] else None

    def revoke_member_access(self) -> None:
        """Disabling Members invalidates links and sessions, including after re-enabling."""
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions")
            self.db.execute("DELETE FROM screens")
            self.db.execute("DELETE FROM links")
            if self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='notice_subscriptions'"
            ).fetchone():
                self.db.execute("DELETE FROM notice_subscriptions")

    def open_session(self, account: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE used<?", (now - SESSION_IDLE,))
            self.db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)", (digest(token), account, now, now)
            )
        return token

    def session(self, token: str) -> tuple[str, bool] | None:
        """The account of a Member's session, and whether its 30 days just started again."""
        if not token:
            return None
        now = time.time()
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT account, used FROM sessions WHERE digest=?", (digest(token),)
            ).fetchone()
            if row is None:
                return None
            if row["used"] < now - SESSION_IDLE:
                self.db.execute("DELETE FROM sessions WHERE digest=?", (digest(token),))
                return None
            renewed = row["used"] < now - 3600  # written at most hourly
            if renewed:
                self.db.execute("UPDATE sessions SET used=? WHERE digest=?", (now, digest(token)))
        return row["account"], renewed

    def end_session(self, token: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE digest=?", (digest(token),))

    def disable(self, account: str, disabled: bool = True) -> None:
        """Désactiver ends every session and keeps everything; Réactiver undoes it."""
        with self.lock, self.db:
            self._member(account)
            self.db.execute("UPDATE accounts SET disabled=? WHERE id=?", (disabled, account))
            self._sign_out(account)

    def delete(self, account: str) -> None:
        """Erase a disabled Member with their Permissions, caps and sessions."""
        with self.lock, self.db:
            self._member(account)
            row = self.db.execute("SELECT disabled FROM accounts WHERE id=?", (account,)).fetchone()
            if not row["disabled"]:
                raise ValueError("Disable the Member before deleting them.")
            self.db.execute("DELETE FROM accounts WHERE id=?", (account,))

    def grant(self, account: str, permissions: Iterable[Permission]) -> None:
        """Replace a Member's Permissions. The Owner holds every Permission and cannot change."""
        with self.lock, self.db:
            self._member(account)
            self.db.execute("DELETE FROM permissions WHERE account=?", (account,))
            self._grant(account, permissions)

    def _grant(self, account: str, permissions: Iterable[Permission]) -> None:
        granted = {Permission(p) for p in permissions}
        limit = self.db.execute(
            "SELECT age_limit FROM media_limits WHERE account=?", (account,)
        ).fetchone()
        if limit is not None and not adult_allowed(limit["age_limit"]):
            granted.discard(Permission.ADULT)
        self.db.executemany(
            "INSERT INTO permissions VALUES (?,?)", [(account, p.value) for p in granted]
        )

    def caps(self, account: str) -> Caps:
        with self.lock:
            self._member(account)
            row = self.db.execute("SELECT * FROM caps WHERE account=?", (account,)).fetchone()
        if row is None:
            return Caps()
        return Caps(
            row["requests_per_week"],
            row["bytes_per_week"],
            row["pending"],
            row["assistant_per_day"],
        )

    def set_caps(self, account: str, caps: Caps) -> None:
        values = (caps.requests_per_week, caps.bytes_per_week, caps.pending)
        if any(v is not None and v < 0 for v in values) or not 0 <= caps.assistant_per_day:
            raise ValueError("Caps cannot be negative.")
        with self.lock, self.db:
            self._member(account)
            self.db.execute(
                "INSERT OR REPLACE INTO caps VALUES (?,?,?,?,?)",
                (account, *values, caps.assistant_per_day),
            )

    def media_limits(self, account: str) -> tuple[int | None, list[str] | None]:
        """The account's Age Rating limit, as a rank, and its visible Library Folders."""
        with self.lock:
            row = self.db.execute(
                "SELECT age_limit, folders FROM media_limits WHERE account=?", (account,)
            ).fetchone()
        if row is None:
            return None, None
        return row["age_limit"], None if row["folders"] is None else json.loads(row["folders"])

    def _public_limits(self, account: str) -> dict:
        age_limit, folders = self.media_limits(account)
        return {
            "age_limit": None if age_limit is None else age_ratings.SCALE[age_limit],
            "folders": folders,
        }

    def set_media_limits(
        self, account: str, age_limit: str | None, folders: Iterable[str] | None
    ) -> None:
        """Limit what Médias shows a Member. Under any limit but −18, adult content goes."""
        rank = None if age_limit is None else age_ratings.rank(age_limit)
        if age_limit is not None and rank is None:
            raise ValueError("Choose Tous publics, −10, −12, −16 or −18.")
        chosen = None if folders is None else sorted({str(f) for f in folders})
        with self.lock, self.db:
            self._member(account)
            self.db.execute(
                "INSERT OR REPLACE INTO media_limits VALUES (?,?,?)",
                (account, rank, None if chosen is None else json.dumps(chosen)),
            )
            if not adult_allowed(rank):
                self.db.execute(
                    "DELETE FROM permissions WHERE account=? AND permission=?",
                    (account, Permission.ADULT.value),
                )

    def invite(
        self,
        name: str,
        permissions: Iterable[Permission],
        caps: Caps,
        *,
        days: int,
        inviter: str,
        note: str = "",
    ) -> tuple[str, str]:
        """Add a Member who chooses their sign-in name and password with a one-time link."""
        identifier = uuid4().hex
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO accounts (id, name, created) VALUES (?,'',?)",
                (identifier, time.time()),
            )
            self._identify(identifier, name, "", "")
            self.db.execute("INSERT INTO caps (account) VALUES (?)", (identifier,))
            self._grant(identifier, permissions)
            token = self._link(identifier, "invite", days, inviter, note)
        self.set_caps(identifier, caps)
        return identifier, token

    def password_link(self, account: str, *, days: int, inviter: str) -> str:
        """A one-time link to choose a new password; an invited Member gets a new invitation."""
        with self.lock, self.db:
            self._member(account)
            kind = "invite" if self._invited(account) else "password"
            note = self.db.execute(
                "SELECT note FROM links WHERE account=? ORDER BY created DESC", (account,)
            ).fetchone()
            return self._link(account, kind, days, inviter, note["note"] if note else "")

    def _link(self, account: str, kind: str, days: int, inviter: str, note: str) -> str:
        if days not in LINK_DAYS:
            raise ValueError("A link is valid 24 hours, 3 or 7 days.")
        if len(note) > 500:
            raise ValueError("Keep the message under 500 characters.")
        # One open link per account: a new one replaces the one before.
        self.db.execute("DELETE FROM links WHERE account=? AND used IS NULL", (account,))
        created = time.time()
        token = self._token(account, kind, created)
        self.db.execute(
            "INSERT INTO links VALUES (?,?,?,?,?,?,?,NULL)",
            (digest(token), account, kind, inviter, note.strip(), created, created + days * 86400),
        )
        return token

    def _token(self, account: str, kind: str, created: float) -> str:
        """Derived from a key kept outside the database, which stores only its hash, so the
        open link can be shown again ("Voir le lien") and a copied database opens none."""
        mac = hmac.new(self.link_key, f"{account}|{kind}|{created!r}".encode(), "sha256")
        return base64.urlsafe_b64encode(mac.digest()).rstrip(b"=").decode()

    def _open_links(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM links WHERE used IS NULL").fetchall()

    def open_link(self, account: str) -> tuple[str, dict] | None:
        """The account's open link again, with its kind and expiry, while it is valid."""
        with self.lock:
            self._member(account)
            row = self.db.execute(
                "SELECT * FROM links WHERE account=? AND used IS NULL AND expires>?",
                (account, time.time()),
            ).fetchone()
        if row is None:
            return None
        return self._token(account, row["kind"], row["created"]), {
            "kind": row["kind"],
            "expires": row["expires"],
        }

    def cancel_link(self, account: str) -> bool:
        """Close the account's open link; an invited Member who never joined goes with it.
        True when the account was removed."""
        with self.lock, self.db:
            self._member(account)
            self.db.execute("DELETE FROM links WHERE account=? AND used IS NULL", (account,))
            if self._invited(account):
                self.db.execute("DELETE FROM accounts WHERE id=?", (account,))
                return True
        return False

    def link(self, token: str) -> dict | None:
        """What a link opens: its kind and state (valid, expired or used), and for a valid one
        the account and what it is shared."""
        with self.lock:
            row = self.db.execute(
                "SELECT links.*, accounts.name, accounts.login, accounts.disabled "
                "FROM links JOIN accounts ON accounts.id=links.account WHERE digest=?",
                (digest(token),),
            ).fetchone()
            if row is None:
                return None
            inviter = self.db.execute(
                "SELECT name FROM accounts WHERE id=? AND id<>?", (row["inviter"], OWNER)
            ).fetchone()
        state = (
            "used"
            if row["used"] is not None
            else "expired"
            if row["expires"] < time.time() or row["disabled"]
            else "valid"
        )
        found: dict = {"kind": row["kind"], "state": state}
        if state == "valid":
            actor = self.actor(row["account"])
            found |= {
                "name": row["name"],
                "login": row["login"] or "",
                "inviter": inviter["name"] if inviter else "",
                "note": row["note"],
                "expires": row["expires"],
                "permissions": sorted(actor.permissions) if actor else [],
                "caps": vars(self.caps(row["account"])),
            }
        return found

    def redeem(self, token: str, password: str, *, name: str = "", login: str = "") -> str:
        """Use a valid link once: an invitation sets the sign-in name and password, a password
        link the password, ending every session. The account, to sign in."""
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT links.account, links.kind FROM links "
                "JOIN accounts ON accounts.id=links.account "
                "WHERE digest=? AND used IS NULL AND expires>? AND disabled=0",
                (digest(token), time.time()),
            ).fetchone()
            if row is None:
                raise PermissionError("This link is no longer valid.")
            account = row["account"]
            if row["kind"] == "invite":
                if not login.strip():
                    raise ValueError("Choose a sign-in name.")
                current = self.db.execute(
                    "SELECT name FROM accounts WHERE id=?", (account,)
                ).fetchone()
                self._identify(account, name.strip() or current["name"], login, "")
            self._password(account, password)
            self._sign_out(account)
            self.db.execute("UPDATE links SET used=? WHERE digest=?", (time.time(), digest(token)))
        return account

    # Viewers (#135): people without credentials who watch under an account holder, with
    # only Media Permissions, never broader than the account's.

    def profiles(self, account: str) -> list[dict]:
        """Who may watch under the account: the holder first, then their Viewers."""
        with self.lock:
            holder = self.db.execute(
                "SELECT accounts.name, holder_pins.pin FROM accounts LEFT JOIN holder_pins "
                "ON holder_pins.account=accounts.id WHERE accounts.id=?",
                (account,),
            ).fetchone()
            rows = self.db.execute(
                "SELECT * FROM viewers WHERE account=? ORDER BY created", (account,)
            ).fetchall()
        if holder is None:
            raise ValueError("This Member no longer exists.")
        base = self.actor(account) or Actor(account, frozenset())
        found = [
            {
                "id": "",
                "name": self.display_name(account),
                "holder": True,
                "permissions": sorted(p.value for p in base.permissions if p in MEDIA),
                "age_limit": base.age_limit,
                "pin": bool(holder["pin"]),
            }
        ]
        for row in rows:
            permissions = {p for p in json.loads(row["permissions"]) if p in MEDIA}
            found.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "holder": False,
                    "permissions": sorted(permissions & {p.value for p in base.permissions}),
                    "age_limit": narrowest(base.age_limit, row["age_limit"]),
                    "pin": bool(row["pin"]),
                }
            )
        for profile in found:
            profile["needs_pin"] = any(narrower(other, profile) for other in found)
        return found

    def viewer(self, account: str, viewer: str) -> dict:
        found = next((p for p in self.profiles(account) if p["id"] == viewer), None)
        if found is None:
            raise ValueError("This profile no longer exists.")
        return found

    def add_viewer(
        self, account: str, name: str, permissions: Iterable[Permission], age_limit: int | None
    ) -> str:
        identifier = uuid4().hex
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO viewers (id, account, name, permissions, created) VALUES (?,?,'',?,?)",
                (identifier, account, "[]", time.time()),
            )
            self._viewer(account, identifier, name, permissions, age_limit)
        return identifier

    def update_viewer(
        self,
        account: str,
        viewer: str,
        name: str,
        permissions: Iterable[Permission],
        age_limit: int | None,
    ) -> None:
        with self.lock, self.db:
            if not self.db.execute(
                "SELECT 1 FROM viewers WHERE id=? AND account=?", (viewer, account)
            ).fetchone():
                raise ValueError("This profile no longer exists.")
            self._viewer(account, viewer, name, permissions, age_limit)

    def _viewer(
        self,
        account: str,
        viewer: str,
        name: str,
        permissions: Iterable[Permission],
        age_limit: int | None,
    ) -> None:
        base = self.actor(account)
        if base is None:
            raise ValueError("This Member no longer exists.")
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("Give the profile a name.")
        if age_limit is not None and not 0 <= age_limit < len(age_ratings.SCALE):
            raise ValueError("Choose Tous publics, −10, −12, −16 or −18.")
        if base.age_limit is not None and (age_limit is None or age_limit > base.age_limit):
            raise ValueError("A profile cannot see a higher Age Rating than its account.")
        granted = {Permission(p) for p in permissions}
        if not granted <= MEDIA or not all(base.holds(p) for p in granted):
            raise ValueError("A profile has only Media Permissions its account holds.")
        if not adult_allowed(age_limit):
            granted.discard(Permission.ADULT)
        self.db.execute(
            "UPDATE viewers SET name=?, permissions=?, age_limit=? WHERE id=?",
            (name, json.dumps(sorted(p.value for p in granted)), age_limit, viewer),
        )
        self._pins_needed(account)

    def _pins_needed(self, account: str) -> None:
        """Once a profile is more restricted than another, the broader one needs a PIN, so a
        child cannot step up to a parent."""
        for profile in self.profiles(account):
            if profile["needs_pin"] and not profile["pin"]:
                raise ValueError(
                    f"Choose a PIN for {profile['name'] or 'the owner'} first: "
                    "a more restricted profile exists."
                )

    def remove_viewer(self, account: str, viewer: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM viewers WHERE id=? AND account=?", (viewer, account))
            self.db.execute(
                "UPDATE screens SET viewer=NULL WHERE account=? AND viewer=?", (account, viewer)
            )

    def set_pin(self, account: str, viewer: str, pin: str) -> None:
        """Set a profile's PIN (4 to 8 digits), or remove it with an empty one."""
        if pin and not (pin.isdigit() and pin.isascii() and 4 <= len(pin) <= 8):
            raise ValueError("A PIN has 4 to 8 digits.")
        stored = ""
        if pin:
            salt = secrets.token_bytes(16)
            stored = f"scrypt${salt.hex()}${scrypt(pin, salt).hex()}"
        with self.lock, self.db:
            self.viewer(account, viewer)
            if viewer:
                self.db.execute(
                    "UPDATE viewers SET pin=? WHERE id=? AND account=?", (stored, viewer, account)
                )
            elif stored:
                self.db.execute(
                    "INSERT OR REPLACE INTO holder_pins VALUES (?,?)", (account, stored)
                )
            else:
                self.db.execute("DELETE FROM holder_pins WHERE account=?", (account,))
            self._pins_needed(account)

    def check_pin(self, account: str, viewer: str, pin: str) -> bool:
        with self.lock:
            row = (
                self.db.execute(
                    "SELECT pin FROM viewers WHERE id=? AND account=?", (viewer, account)
                ).fetchone()
                if viewer
                else self.db.execute(
                    "SELECT pin FROM holder_pins WHERE account=?", (account,)
                ).fetchone()
            )
        stored = row["pin"] if row else ""
        _, salt, expected = stored.split("$") if stored.count("$") == 2 else ("", "00" * 16, "")
        return secrets.compare_digest(scrypt(pin, bytes.fromhex(salt)).hex(), expected)

    def needs_pin(self, account: str, viewer: str, current: str | None) -> bool:
        """Whether opening this profile asks for its PIN: from the picker, whenever it has
        one (one is required once a more restricted profile exists); from another profile,
        only when stepping up. Going down never asks."""
        profiles = {p["id"]: p for p in self.profiles(account)}
        target = profiles[viewer]
        if not target["pin"]:
            return False
        if current is None or current not in profiles:
            return True
        return not narrower(target, profiles[current], strict=False)

    def viewer_actor(self, account: str, viewer: str, screen: str = "") -> Actor | None:
        """The actor of a Viewer: the account's Permissions narrowed by the Viewer's own."""
        base = self.actor(account)
        if base is None:
            return None
        if viewer == "":
            return replace(base, screen=screen)
        if viewer == PICKING:
            return Actor(account, frozenset(), viewer=PICKING, screen=screen)
        try:
            found = self.viewer(account, viewer)
        except ValueError:
            return None
        return Actor(
            account,
            frozenset(Permission(p) for p in found["permissions"]),
            viewer=viewer,
            age_limit=found["age_limit"],
            folders=base.folders,
            screen=screen,
        )

    def promote(self, account: str, viewer: str, *, days: int, inviter: str) -> tuple[str, str]:
        """Invite a Viewer as a Member with the same Permissions; the caller moves their
        history to the new account."""
        found = self.viewer(account, viewer)
        if found["holder"]:
            raise ValueError("Choose a profile, not the account holder.")
        member, token = self.invite(
            found["name"],
            [Permission(p) for p in found["permissions"]],
            Caps(),
            days=days,
            inviter=inviter,
        )
        age_limit = found["age_limit"]
        _, folders = self.media_limits(account)
        self.set_media_limits(
            member, None if age_limit is None else age_ratings.SCALE[age_limit], folders
        )
        self.remove_viewer(account, viewer)
        return member, token

    # Shared Screens: a browser the account holder marks as shared when signing in. It asks
    # who watches, and stays signed in for 90 days of disuse.

    def open_screen(self, account: str, name: str) -> str:
        name = name.strip()
        if not name or len(name) > 60:
            raise ValueError("Name this screen, such as “Living room TV”.")
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock, self.db:
            self.db.execute("DELETE FROM screens WHERE used<?", (now - SCREEN_IDLE,))
            self.db.execute(
                "INSERT INTO screens VALUES (?,?,?,?,NULL,?,?)",
                (uuid4().hex, digest(token), account, name, now, now),
            )
        return token

    def screen(self, token: str) -> tuple[Actor, bool] | None:
        """The actor watching on this Shared Screen, and whether its 90 days just started
        again. Until someone chooses who watches, the actor is the picker."""
        if not token:
            return None
        now = time.time()
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM screens WHERE digest=?", (digest(token),)
            ).fetchone()
            if row is None:
                return None
            if row["used"] < now - SCREEN_IDLE:
                self.db.execute("DELETE FROM screens WHERE id=?", (row["id"],))
                return None
            renewed = row["used"] < now - 3600
            if renewed:
                self.db.execute("UPDATE screens SET used=? WHERE id=?", (now, row["id"]))
        viewer = PICKING if row["viewer"] is None else row["viewer"]
        actor = self.viewer_actor(row["account"], viewer, row["id"])
        return (actor, renewed) if actor else None

    def choose(self, screen: str, viewer: str | None) -> None:
        """Who watches on this screen now; None goes back to the picker."""
        with self.lock, self.db:
            self.db.execute("UPDATE screens SET viewer=? WHERE id=?", (viewer, screen))

    def screens(self, account: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM screens WHERE account=? AND used>=? ORDER BY used DESC",
                (account, time.time() - SCREEN_IDLE),
            ).fetchall()
        return [{"id": r["id"], "name": r["name"], "used": r["used"]} for r in rows]

    def screen_name(self, screen: str) -> str:
        with self.lock:
            row = self.db.execute("SELECT name FROM screens WHERE id=?", (screen,)).fetchone()
        return row["name"] if row else ""

    def forget_screen(self, account: str, screen: str) -> None:
        """Forget a Shared Screen: it is signed out at once."""
        with self.lock, self.db:
            self.db.execute("DELETE FROM screens WHERE id=? AND account=?", (screen, account))

    def end_screen(self, token: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM screens WHERE digest=?", (digest(token),))

    def _invited(self, account: str) -> bool:
        row = self.db.execute(
            "SELECT login, password FROM accounts WHERE id=?", (account,)
        ).fetchone()
        return row is not None and not row["login"] and not row["password"]

    def _member(self, account: str) -> None:
        if account == OWNER:
            raise PermissionError("The Owner's account cannot be restricted.")
        if not self.db.execute("SELECT 1 FROM accounts WHERE id=?", (account,)).fetchone():
            raise ValueError("This Member no longer exists.")


def narrowest(*limits: int | None) -> int | None:
    """The strictest of these Age Rating limits; None is no limit."""
    known = [limit for limit in limits if limit is not None]
    return min(known) if known else None


def narrower(profile: dict, other: dict, *, strict: bool = True) -> bool:
    """Whether a profile sees no more than another (and, strictly, less)."""
    unlimited = len(age_ratings.SCALE)
    age = unlimited if profile["age_limit"] is None else profile["age_limit"]
    others = unlimited if other["age_limit"] is None else other["age_limit"]
    within = set(profile["permissions"]) <= set(other["permissions"]) and age <= others
    return within and not (
        strict and set(profile["permissions"]) == set(other["permissions"]) and age == others
    )


def adult_allowed(age_limit: int | None) -> bool:
    """Adult content is granted only with no age limit or the −18 one."""
    return age_limit is None or age_limit >= len(age_ratings.SCALE) - 1


def scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)


def private_key(path: Path) -> bytes:
    """A random key readable only by the server, created on first use."""
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(secrets.token_bytes(32))
    return path.read_bytes()


def digest(token: str) -> str:
    """Session tokens are random, so a fast hash is enough to keep them unusable at rest."""
    return hashlib.sha256(token.encode()).hexdigest()
