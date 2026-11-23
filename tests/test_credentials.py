"""A dismissed keyring unlock prompt is not shown again on every secret read."""

from collections.abc import Iterator

import keyring
import keyring.errors
import pytest
from keyring.backend import KeyringBackend

from torrentlinker import credentials


class LockedKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.prompts = 0
        self.secrets: dict[str, str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        self.prompts += 1
        raise keyring.errors.KeyringLocked("Failed to unlock the collection!")

    def set_password(self, service: str, username: str, password: str) -> None:
        self.secrets[username] = password

    def delete_password(self, service: str, username: str) -> None:
        self.secrets.pop(username, None)


@pytest.fixture
def locked() -> Iterator[LockedKeyring]:
    previous = keyring.get_keyring()
    credentials._declined_unlock = False  # an earlier test may have met a locked keyring
    backend = LockedKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)
    credentials._declined_unlock = False


def test_dismissed_unlock_prompt_is_not_repeated(locked: LockedKeyring) -> None:
    assert credentials.get_secret("indexer-api-key") == ""
    assert credentials.get_secret("indexer-api-key") == ""
    assert credentials.get_secret("tmdb-api-key") == ""
    assert locked.prompts == 1


def test_saving_a_secret_asks_again(locked: LockedKeyring) -> None:
    credentials.get_secret("indexer-api-key")
    credentials.set_secret("indexer-api-key", "key")
    credentials.get_secret("indexer-api-key")
    assert locked.prompts == 2
