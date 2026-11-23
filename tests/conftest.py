"""Tests never touch the user's real keyring, except the opt-in live tests."""

import gc
import os

# Test windows and their dialogs never show on the user's screen, as in CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import keyring
import pytest
from keyring.backend import KeyringBackend


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.secrets: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.secrets.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.secrets[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.secrets.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring():  # type: ignore[no-untyped-def]
    if os.environ.get("TL_LIVE"):
        yield None
        return
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def collect_garbage_on_the_gui_thread(request):  # type: ignore[no-untyped-def]
    """Free each test's leftover windows here, on the GUI thread.

    A window caught in a reference cycle is otherwise freed whenever the garbage
    collector next runs, possibly on a later test's worker thread, and destroying Qt
    widgets off the GUI thread crashes Python.
    """
    yield
    if "qtbot" in request.fixturenames:
        gc.collect()


# The app's default client addresses are the user's own clients on this machine: a test
# must never log in to them (a wrong password gets localhost banned by qBittorrent).
USER_CLIENTS = {
    f"{scheme}://{host}:{port}"
    for scheme in ("http", "https")
    for host in ("localhost", "127.0.0.1")
    for port in (8080, 8081, 8112, 9091)
} | {
    f"{scheme}://{host}{port}"
    for scheme, port in (("http", "/RPC2"), ("https", "/RPC2"), ("scgi", ":5000"))
    for host in ("localhost", "127.0.0.1")
}
NOWHERE = "http://127.0.0.1:9"  # discard port: refused at once


@pytest.fixture(autouse=True)
def never_take_the_running_apps_assistant_port(monkeypatch):  # type: ignore[no-untyped-def]
    """The desktop Assistant listens on 8790. A test server there kept the user's own
    running TorrentLinker from opening its Assistant and Media center, so a test gets a
    free port unless it names one."""
    from torrentlinker.agent.desktop import DesktopServer

    original = DesktopServer.__init__

    def guarded(self, *args, port: int = 0, **kwargs):  # type: ignore[no-untyped-def]
        original(self, *args, port=port, **kwargs)

    monkeypatch.setattr(DesktopServer, "__init__", guarded)


@pytest.fixture(autouse=True)
def never_reach_the_users_own_clients(monkeypatch):  # type: ignore[no-untyped-def]
    from torrentlinker.deluge import DelugeApi
    from torrentlinker.qbit import QbitApi
    from torrentlinker.rtorrent import RtorrentApi
    from torrentlinker.transmission import TransmissionApi
    from torrentlinker.utorrent import UtorrentApi

    for cls in (QbitApi, DelugeApi, TransmissionApi, UtorrentApi, RtorrentApi):
        original = cls.__init__

        def guarded(self, host, *args, __original=original, **kwargs):  # type: ignore[no-untyped-def]
            address = host.strip().rstrip("/").removesuffix("/gui")
            if address in USER_CLIENTS:
                host = NOWHERE
            __original(self, host, *args, **kwargs)

        monkeypatch.setattr(cls, "__init__", guarded)


@pytest.fixture(autouse=True)
def forget_refused_logins():  # type: ignore[no-untyped-def]
    """A refused login is remembered for the process; no test inherits another's."""
    from torrentlinker import login_guard

    login_guard._REFUSED.clear()
    yield


@pytest.fixture(autouse=True)
def no_bundled_catalogue(monkeypatch, tmp_path_factory):  # type: ignore[no-untyped-def]
    """A Catalogue bundled into a local checkout would be imported by every sync."""
    from torrentlinker import bundled_catalogue

    monkeypatch.setattr(bundled_catalogue, "BUNDLE", tmp_path_factory.getbasetemp() / "none")


@pytest.fixture(autouse=True)
def dialogs_answer_at_once(monkeypatch):  # type: ignore[no-untyped-def]
    """A message box a test did not expect returns at once, as if dismissed, rather than
    waiting offscreen for a click that never comes. Tests that answer one patch it."""
    from PySide6.QtWidgets import QMessageBox

    def dismissed(*args, **kwargs):  # type: ignore[no-untyped-def]
        return QMessageBox.StandardButton.NoButton

    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, dismissed)


@pytest.fixture(autouse=True)
def no_proxy_left_over():  # type: ignore[no-untyped-def]
    """The proxy is app-wide: one test's never leaks into the next."""
    from torrentlinker import net

    yield
    net.configure(None)
