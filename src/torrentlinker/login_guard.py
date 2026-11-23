"""Remember a Torrent Client's refused login, so nothing keeps knocking with the same credentials.

qBittorrent bans an IP after a few failed logins. Every periodic refresh (seed state, Zen,
Library, Torrents, Cross-seed) used to log in again with the credentials it was started with,
so one wrong password became a ban. A refused login is now remembered per client address and
credentials: every caller gets one clear error without touching the network, until the
settings change (the credentials are part of the key) or the user presses Test.
"""

from __future__ import annotations

import hashlib
import threading

_REFUSED: dict[tuple[str, ...], LoginRefused] = {}
_LOCK = threading.Lock()

REFUSED = {
    "en": (
        "The client refused the login. Check the username and password (or API key) in "
        "Settings, then press Test. No automatic login is tried until then."
    ),
    "fr": (
        "Le client a refusé la connexion. Vérifiez l’identifiant et le mot de passe (ou la "
        "clé API) dans les paramètres, puis appuyez sur Tester. Aucune connexion "
        "automatique n’est tentée d’ici là."
    ),
}
BANNED = {
    "en": (
        "qBittorrent has banned this IP address after too many failed logins. Restart "
        "qBittorrent (or wait for the ban to end), check the username and password in "
        "Settings, then press Test."
    ),
    "fr": (
        "qBittorrent a banni cette adresse IP après trop d’échecs de connexion. Redémarrez "
        "qBittorrent (ou attendez la fin du bannissement), vérifiez l’identifiant et le mot "
        "de passe dans les paramètres, puis appuyez sur Tester."
    ),
}


def language(setting: str = "auto") -> str:
    """French when chosen, otherwise English, which the browser translates by its own."""
    return "fr" if setting == "fr" else "en"


class LoginRefused(RuntimeError):
    """The client refused (or banned) a login; nothing else is tried until settings change."""

    def __init__(self, banned: bool = False) -> None:
        self.banned = banned
        super().__init__(BANNED["en"] if banned else REFUSED["en"])

    def text(self, setting: str = "auto") -> str:
        return (BANNED if self.banned else REFUSED)[language(setting)]


class LoginGuard:
    """The refused-login memory of one client address with one set of credentials."""

    def __init__(self, kind: str, host: str, username: str, *secrets: str) -> None:
        digest = hashlib.sha256("\0".join(secrets).encode()).hexdigest()
        self._key = (kind, host, username, digest)

    def check(self) -> None:
        """Raise the remembered refusal; this is the only thing callers do after one."""
        with _LOCK:
            refused = _REFUSED.get(self._key)
        if refused is not None:
            raise LoginRefused(refused.banned)

    def refuse(self, banned: bool = False) -> LoginRefused:
        refused = LoginRefused(banned)
        with _LOCK:
            _REFUSED[self._key] = refused
        return refused

    def rearm(self) -> None:
        """The user pressed Test: the next login attempt is allowed."""
        with _LOCK:
            _REFUSED.pop(self._key, None)
