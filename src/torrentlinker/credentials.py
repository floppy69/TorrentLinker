"""Secrets live in the OS keyring (Secret Service, Windows Credential Manager)."""

from __future__ import annotations

import keyring
import keyring.errors

SERVICE = "torrentlinker"
TMDB_API_KEY = "tmdb-api-key"  # the video profile identifies releases with it

# A locked keyring shows an unlock prompt on every read, and timers read secrets often:
# once the user dismisses the prompt, reads return nothing until they save a secret.
_declined_unlock = False


def get_secret(name: str) -> str:
    global _declined_unlock
    if _declined_unlock:
        return ""
    try:
        return keyring.get_password(SERVICE, name) or ""
    except keyring.errors.KeyringLocked:
        _declined_unlock = True
        return ""
    except keyring.errors.KeyringError:
        return ""


def set_secret(name: str, value: str) -> None:
    global _declined_unlock
    _declined_unlock = False
    if value:
        keyring.set_password(SERVICE, name, value)
    else:
        try:
            keyring.delete_password(SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass
