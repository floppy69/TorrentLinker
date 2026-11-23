import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.torrents import make_torrent
from torrentlinker.deluge import (
    GUARD_SPEED,
    DelugeApi,
    LabelPluginOff,
    _state,
    label_for,
    tags_of,
)
from torrentlinker.login_guard import LoginRefused
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.torrent_meta import read_torrent


class FakeWebUi:
    """Deluge's Web UI JSON-RPC: a password, a daemon to connect to, and calls."""

    def __init__(self, labels: bool = True) -> None:
        self.plugins = ["Label"] if labels else []
        self.sessions: set[str] = set()
        self.connected = False
        self.logins = 0
        self.labels: list[str] = []
        self.torrents: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, list[Any]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        self.calls.append((method, params))
        cookie = request.headers.get("cookie", "")
        headers = {}
        if method == "auth.login":
            ok = params == ["secret"]
            if ok:
                self.logins += 1
                session = f"s{self.logins}"
                self.sessions.add(session)
                headers["set-cookie"] = f"_session_id={session}; Path=/"
            return self._reply(body, ok, headers=headers)
        if not any(f"_session_id={s}" in cookie for s in self.sessions):
            return self._reply(body, None, {"message": "Not authenticated", "code": 1})
        if method.startswith("web."):
            result = {
                "web.connected": self.connected,
                "web.get_hosts": [["h1", "127.0.0.1", 58846, "localclient"]],
                "web.connect": None,
            }[method]
            if method == "web.connect":
                self.connected = True
            return self._reply(body, result)
        if not self.connected:
            return self._reply(body, None, {"message": "Unknown method", "code": 2})
        try:
            return self._reply(body, getattr(self, method.replace(".", "_"))(*params))
        except Exception as e:  # noqa: BLE001 - Deluge wraps it as an error
            return self._reply(body, None, {"message": str(e), "code": 4})

    @staticmethod
    def _reply(
        body: dict[str, Any],
        result: Any,
        error: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        payload = {"result": result, "error": error, "id": body["id"]}
        return httpx.Response(200, json=payload, headers=headers)

    # Daemon ------------------------------------------------------------------

    def daemon_get_version(self) -> str:
        return "2.2.0"

    def core_get_enabled_plugins(self) -> list[str]:
        return self.plugins

    def core_get_config_value(self, key: str) -> str:
        return {"download_location": "/downloads"}[key]

    def core_add_torrent_file(self, name: str, dump: str, options: dict[str, Any]) -> str:
        import base64

        h = read_torrent(base64.b64decode(dump)).infohash
        if h in self.torrents:
            raise RuntimeError(f"AddTorrentError: Torrent already in session ({h}).")
        self.torrents[h] = {
            "name": "book",
            "download_location": options["download_location"],
            "files": [{"index": 0, "path": "book.epub", "size": 1000, "offset": 0}],
            "file_priorities": [4],
            "label": "",
            "progress": 0.0,
            "state": "Paused" if options.get("add_paused") else "Downloading",
            "paused": bool(options.get("add_paused")),
            "max_download_speed": options.get("max_download_speed", -1),
            "options": options,
            "pieces": [0, 0],
            "num_pieces": 2,
        }
        return h

    def core_get_torrent_status(self, h: str, keys: list[str]) -> dict[str, Any]:
        t = self.torrents.get(h)
        return {k: t[k] for k in keys if k in t} if t else {}

    def core_get_torrents_status(
        self, where: dict[str, Any], keys: list[str]
    ) -> dict[str, dict[str, Any]]:
        labels = where.get("label")
        return {
            h: self.core_get_torrent_status(h, keys)
            for h, t in self.torrents.items()
            if labels is None or t["label"] in labels
        }

    def core_set_torrent_options(self, hashes: list[str], options: dict[str, Any]) -> None:
        for h in hashes:
            self.torrents[h].update(options)

    def core_rename_files(self, h: str, renames: list[list[Any]]) -> None:
        for index, new in renames:
            self.torrents[h]["files"][index]["path"] = new

    def core_resume_torrent(self, h: str) -> None:
        self.torrents[h].update(state="Seeding", paused=False, progress=100.0)

    def core_remove_torrent(self, h: str, remove_data: bool) -> bool:
        assert remove_data is False
        del self.torrents[h]
        return True

    def label_get_labels(self) -> list[str]:
        if "Label" not in self.plugins:
            raise RuntimeError("Unknown method")
        return self.labels

    def label_add(self, label: str) -> None:
        if label in self.labels:
            raise RuntimeError("Label already exists")
        self.labels.append(label)

    def label_set_torrent(self, h: str, label: str) -> None:
        assert not label or label in self.labels
        self.torrents[h]["label"] = label


@pytest.fixture
def web() -> FakeWebUi:
    return FakeWebUi()


def api_for(web: FakeWebUi, password: str = "secret") -> DelugeApi:
    http = httpx.Client(transport=httpx.MockTransport(web.handler))
    return DelugeApi("localhost:8112", password, http=http)


def torrent(tmp_path: Path) -> bytes:
    (tmp_path / "book.epub").write_bytes(b"x" * 1000)
    return make_torrent(tmp_path / "book.epub")


def test_check_logs_in_connects_the_daemon_and_returns_its_version(web: FakeWebUi) -> None:
    api = api_for(web)
    assert api.check() == "2.2.0"
    assert web.connected
    assert api.default_save_path() == "/downloads"


def test_a_wrong_password_is_reported(web: FakeWebUi) -> None:
    with pytest.raises(LoginRefused, match="refused the login"):
        api_for(web, "wrong").check()


def test_check_refuses_when_the_label_plugin_is_off() -> None:
    with pytest.raises(LabelPluginOff, match="Preferences → Plugins → Label"):
        api_for(FakeWebUi(labels=False)).check()


def test_an_expired_session_logs_in_again(web: FakeWebUi) -> None:
    api = api_for(web)
    api.check()
    web.sessions.clear()  # the Web UI restarted, or its session timed out

    assert api.torrents() == []
    assert web.logins == 2


def test_a_reseed_is_added_stopped_out_of_the_queue_with_its_speed_guarded(
    web: FakeWebUi, tmp_path: Path
) -> None:
    api = api_for(web)
    h = api.add(torrent(tmp_path), "/lib", ["torrentlinker", "torrentlinker:verifying"])

    options = web.torrents[h]["options"]
    assert options["add_paused"] and not options["auto_managed"]
    assert options["move_completed"] is False
    assert options["max_download_speed"] == GUARD_SPEED
    t = api.torrent(h)
    assert t is not None
    assert t.state == "stoppedDL" and t.save_path == Path("/lib")
    assert t.tags == {"torrentlinker", "torrentlinker:verifying"}
    assert [x.hash for x in api.torrents(tag="torrentlinker:verifying")] == [h]
    assert [x.hash for x in api.torrents(tag="torrentlinker")] == [h]
    assert api.torrents(tag="torrentlinker:partial") == []

    api.start(h)
    assert web.torrents[h]["max_download_speed"] == -1
    assert api.torrent(h).is_seeding  # type: ignore[union-attr]


def test_a_partial_reseed_keeps_its_last_tag_and_loses_the_guard(
    web: FakeWebUi, tmp_path: Path
) -> None:
    api = api_for(web)
    h = api.add(torrent(tmp_path), "/lib", ["torrentlinker", "torrentlinker:verifying"])

    api.add_tags(h, ["torrentlinker:partial"])
    api.remove_tags(h, ["torrentlinker:verifying"])

    assert api.torrent(h).tags == {"torrentlinker", "torrentlinker:partial"}  # type: ignore[union-attr]
    assert web.torrents[h]["label"] == "torrentlinker-partial"
    assert web.torrents[h]["max_download_speed"] == -1


def test_adding_a_torrent_already_there_says_so(web: FakeWebUi, tmp_path: Path) -> None:
    api = api_for(web)
    data = torrent(tmp_path)
    api.download(data, "/dl", ["torrentlinker:zen"])

    with pytest.raises(AlreadyInClient):
        api.download(data, "/dl", ["torrentlinker:zen"])


def test_tagged_adds_are_refused_before_adding_when_the_label_plugin_is_off(
    tmp_path: Path,
) -> None:
    web = FakeWebUi(labels=False)
    api = api_for(web)

    with pytest.raises(LabelPluginOff):
        api.add(torrent(tmp_path), "/lib", ["torrentlinker"])

    assert web.torrents == {}
    assert api.torrents(tag="torrentlinker") == []


def test_renames_and_priorities_go_by_file_index(web: FakeWebUi, tmp_path: Path) -> None:
    api = api_for(web)
    h = api.add(torrent(tmp_path), "/lib", [])

    api.rename_file(h, "book.epub", "Mine/book.epub")
    api.set_file_priority(h, [0], 0)

    assert api.torrent(h).files == {"Mine/book.epub": 1000}  # type: ignore[union-attr]
    assert web.torrents[h]["file_priorities"] == [0]


def test_piece_states_use_qbittorrent_numbers(web: FakeWebUi, tmp_path: Path) -> None:
    api = api_for(web)
    h = api.add(torrent(tmp_path), "/lib", [])
    web.torrents[h]["pieces"] = [3, 2, 1, 0]
    assert api.piece_states(h) == [2, 1, 0, 0]
    web.torrents[h]["pieces"] = None  # Deluge sends none when every piece is there
    assert api.piece_states(h) == [2, 2]


@pytest.mark.parametrize(
    "state,paused,progress,expected",
    [
        ("Paused", True, 100, "stoppedUP"),
        ("Paused", True, 40, "stoppedDL"),
        ("Paused", False, 40, "checkingDL"),  # Deluge's recheck of a stopped torrent
        ("Checking", False, 100, "checkingUP"),
        ("Seeding", False, 100, "uploading"),
        ("Downloading", False, 10, "downloading"),
        ("Queued", False, 100, "queuedUP"),
        ("Allocating", False, 0, "checkingResumeData"),
        ("Moving", False, 100, "moving"),
        ("Error", True, 0, "error"),
    ],
)
def test_deluge_states_read_as_qbittorrent_states(
    state: str, paused: bool, progress: float, expected: str
) -> None:
    assert _state(state, paused, progress) == expected


def test_tags_and_labels_round_trip() -> None:
    assert label_for(["torrentlinker", "torrentlinker:zen"]) == "torrentlinker-zen"
    assert tags_of("torrentlinker-zen") == {"torrentlinker", "torrentlinker:zen"}
    assert label_for(["torrentlinker"]) == "torrentlinker"
    assert label_for([]) == "" and tags_of("") == frozenset()
