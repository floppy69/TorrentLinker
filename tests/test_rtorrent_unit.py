"""rTorrent's adapter against a fake XML-RPC endpoint over HTTP."""

import xmlrpc.client
from pathlib import Path

import httpx
import pytest
from PySide6.QtWidgets import QLabel

from tests.torrents import make_torrent
from torrentlinker.clients import connect
from torrentlinker.config import Settings
from torrentlinker.domain import TorrentClient
from torrentlinker.login_guard import LoginRefused
from torrentlinker.matching import Match
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.rtorrent import TAGS_KEY, RtorrentApi, RtorrentError, _state
from torrentlinker.torrent_meta import read_torrent


class FakeRtorrent:
    """Just enough of rTorrent's XML-RPC: torrents as dicts of their d.* values."""

    def __init__(self) -> None:
        self.torrents: dict[str, dict[str, object]] = {}
        self.files: dict[str, list[list[object]]] = {}
        self.calls: list[tuple[str, tuple]] = []
        self.auth: str | None = None
        self.paths: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.headers.get("authorization") != self.auth:
            return httpx.Response(401)
        params, method = xmlrpc.client.loads(request.content, use_builtin_types=True)
        try:
            result = self.call(method, *params)
            body = xmlrpc.client.dumps((result,), methodresponse=True, allow_none=False)
        except xmlrpc.client.Fault as fault:
            body = xmlrpc.client.dumps(fault, methodresponse=True)
        return httpx.Response(200, content=body.encode(), headers={"Content-Type": "text/xml"})

    def call(self, method: str, *params):  # type: ignore[no-untyped-def]
        self.calls.append((method, params))
        if method == "system.multicall":
            return [[self.call(c["methodName"], *c["params"])] for c in params[0]]
        if method == "system.client_version":
            return "0.15.2"
        if method == "directory.default":
            return "/downloads"
        if method == "download_list":
            return list(self.torrents)
        if method == "execute.throw":
            return 0
        if method in {"load.raw", "load.raw_start"}:
            return self.load(params[1], params[2:], method == "load.raw_start")
        if method == "d.multicall2":
            return [[self.field(h, f) for f in params[2:]] for h in self.torrents]
        if method == "f.multicall":
            return self.files[params[0]]
        if method == "t.multicall":
            return [["https://tracker.example/announce", 4, 2]]
        if method == "d.custom.set":
            self.torrents[params[0]]["custom:" + params[1]] = params[2]
            return 0
        if method in {"d.start", "d.stop", "d.open", "d.close", "d.erase", "d.check_hash"}:
            if params[0] not in self.torrents:
                raise xmlrpc.client.Fault(-501, "Could not find info-hash.")
            if method == "d.erase":
                del self.torrents[params[0]]
            elif method == "d.start":
                self.torrents[params[0]].update({"d.state": 1, "d.is_active": 1})
            return 0
        if method.startswith(("d.", "f.")):
            if method == "f.priority.set" or method == "d.update_priorities":
                return 0
            field = method + "=" + (params[1] if len(params) > 1 else "")
            return self.field(params[0], field)
        raise xmlrpc.client.Fault(-506, f"Method '{method}' not defined")

    def field(self, hash: str, field: str) -> object:
        name, _, key = field.partition("=")
        t = self.torrents[hash]
        return t["custom:" + key] if name == "d.custom" else t[name]

    def load(self, data: bytes, commands: tuple, started: bool) -> int:
        meta = read_torrent(data)
        h = meta.infohash.upper()
        multi = len(meta.files) != 1 or next(iter(meta.files)) != meta.name
        directory = ""
        tags = ""
        for command in commands:
            name, _, value = command.partition("=")
            if name == "d.directory.set":
                directory = value.strip('"')
            elif name == "d.custom.set":
                tags = value.split(",", 1)[1].strip('"')
        self.torrents[h] = {
            "d.hash": h,
            "d.name": meta.name,
            "d.directory": f"{directory}/{meta.name}" if multi else directory,
            "d.is_multi_file": int(multi),
            "d.state": int(started),
            "d.is_active": int(started),
            "d.hashing": 0,
            "d.hashing_failed": 0,
            "d.complete": 0,
            "d.completed_bytes": 0,
            "d.size_bytes": sum(meta.files.values()),
            f"custom:{TAGS_KEY}": tags,
            "d.custom1": "",
            "d.up.rate": 0,
            "d.down.rate": 0,
            "d.ratio": 0,
            "d.peers_complete": 0,
            "d.peers_accounted": 0,
            "d.left_bytes": sum(meta.files.values()),
            "d.timestamp.finished": 0,
        }
        prefix = meta.name + "/" if multi else ""
        self.files[h] = [[path.removeprefix(prefix), size, 1] for path, size in meta.files.items()]
        return 0


def api_for(fake: FakeRtorrent, host: str = "https://seedbox.example/RPC2", **kw) -> RtorrentApi:
    return RtorrentApi(host, http=httpx.Client(transport=httpx.MockTransport(fake.handle)), **kw)


def pack(tmp_path: Path) -> bytes:
    folder = tmp_path / "Show"
    folder.mkdir()
    (folder / "e1.mkv").write_bytes(b"a" * 3000)
    (folder / "e2.mkv").write_bytes(b"b" * 2000)
    return make_torrent(folder)


@pytest.mark.parametrize(
    ("host", "path"),
    [
        ("https://seedbox.example", "/RPC2"),
        ("seedbox.example/", "/RPC2"),
        ("https://seedbox.example/rutorrent/RPC2", "/rutorrent/RPC2"),
    ],
)
def test_an_address_without_a_path_gets_rpc2(host: str, path: str) -> None:
    fake = FakeRtorrent()
    assert api_for(fake, host).check() == "0.15.2"
    assert fake.paths == [path]


@pytest.mark.parametrize("host", ["scgi://", "ftp://seedbox.example", "scgi://seedbox.example"])
def test_an_address_rtorrent_cannot_answer_on_is_refused(host: str) -> None:
    with pytest.raises(RtorrentError):
        RtorrentApi(host)


def test_the_web_servers_login_and_rtorrent_faults_are_clear() -> None:
    fake = FakeRtorrent()
    fake.auth = httpx.BasicAuth("me", "secret")._auth_header
    with pytest.raises(LoginRefused, match="refused the login"):
        api_for(fake).check()
    api = api_for(fake, username="me", password="secret")
    assert api.check() == "0.15.2"
    with pytest.raises(RtorrentError, match="info-hash"):
        api.start("0" * 40)


@pytest.mark.parametrize(
    ("started", "active", "hashing", "failed", "done", "state"),
    [
        (0, 0, 0, 0, 0.5, "stoppedDL"),
        (1, 0, 0, 0, 1.0, "stoppedUP"),  # paused
        (1, 1, 0, 0, 0.5, "downloading"),
        (1, 1, 0, 0, 1.0, "uploading"),
        (0, 0, 1, 0, 0.0, "checkingDL"),
        (0, 0, 0, 1, 0.0, "error"),
    ],
)
def test_state_translation(started, active, hashing, failed, done, state) -> None:  # type: ignore[no-untyped-def]
    assert _state(started, active, hashing, failed, done) == state


def test_a_folder_torrent_lists_from_its_parent_with_tags_beside_the_users_label(
    tmp_path: Path,
) -> None:
    fake = FakeRtorrent()
    api = api_for(fake)
    h = api.add(pack(tmp_path), "/data/tv", ["torrentlinker", "torrentlinker:verifying"])
    fake.torrents[h.upper()]["d.custom1"] = "My label"

    [t] = api.torrents()
    assert t.save_path == Path("/data/tv")
    assert t.files == {"Show/e1.mkv": 3000, "Show/e2.mkv": 2000}
    assert t.tags == {"torrentlinker", "torrentlinker:verifying"}
    assert t.category == "My label"
    assert t.state == "stoppedDL"
    assert t.trackers == ("https://tracker.example/announce",) and t.swarm_seeders == 4
    assert api.torrents(tag="zen") == []

    api.remove_tags(h, ["torrentlinker:verifying"])
    api.add_tags(h, ["zen"])
    t2 = api.torrent(h, with_files=False)
    assert t2 is not None and t2.tags == {"torrentlinker", "zen"} and t2.category == "My label"
    assert api.torrent("f" * 40) is None


def test_adding_twice_is_refused_and_downloads_make_their_folder_first(tmp_path: Path) -> None:
    fake = FakeRtorrent()
    api = api_for(fake)
    data = pack(tmp_path)
    h = api.download(data, "/data/new folder", ["zen"], sequential=True)
    methods = [m for m, _ in fake.calls]
    assert methods.index("execute.throw") < methods.index("load.raw_start")
    assert ("execute.throw", ("", "mkdir", "-p", "--", "/data/new folder")) in fake.calls
    assert api.torrent(h, with_files=False).state == "downloading"  # type: ignore[union-attr]
    with pytest.raises(AlreadyInClient):
        api.add(data, "/data", [])


def test_a_partial_match_is_refused_and_files_are_never_deleted(tmp_path: Path) -> None:
    meta = read_torrent(pack(tmp_path))
    api = api_for(FakeRtorrent())
    [first, second] = meta.files
    with pytest.raises(RtorrentError, match="Partial"):
        api.reseed_layout(meta, Match({first: first}, absent=(second,), coverage=0.6))
    full = Match({p: p for p in meta.files})
    assert api.reseed_layout(meta, full) == full
    with pytest.raises(RtorrentError):
        api.remove(meta.infohash, delete_files=True)


def test_pieces_come_from_the_hex_bitfield(tmp_path: Path) -> None:
    fake = FakeRtorrent()
    api = api_for(fake)
    h = api.add(pack(tmp_path), "/data", []).upper()
    fake.torrents[h].update({"d.bitfield": "A0", "d.size_chunks": 3})
    assert api.piece_states(h) == [2, 0, 2]


def test_settings_and_connection_choose_rtorrent(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.client = TorrentClient.RTORRENT
    settings.rtorrent.host = "scgi://seedbox.example:5000"
    settings.save(path)
    loaded = Settings.load(path)
    assert loaded.client is TorrentClient.RTORRENT
    assert loaded.rtorrent.host == "scgi://seedbox.example:5000"
    assert isinstance(connect(TorrentClient.RTORRENT, loaded.rtorrent.host, "", ""), RtorrentApi)


def test_the_web_form_takes_an_scgi_address_for_rtorrent_only() -> None:
    from pydantic import ValidationError

    from torrentlinker.web.setup import Connection

    ok = Connection(client=TorrentClient.RTORRENT, host="scgi://seedbox.example:5000")
    assert ok.host == "scgi://seedbox.example:5000"
    for client, host in [
        (TorrentClient.QBITTORRENT, "scgi://seedbox.example:5000"),
        (TorrentClient.RTORRENT, "scgi://seedbox.example"),
        (TorrentClient.RTORRENT, "scgi:///run/rtorrent.sock"),
    ]:
        with pytest.raises(ValidationError):
            Connection(client=client, host=host)


def test_deleting_files_is_refused_before_anything_is_sent(tmp_path: Path) -> None:
    from torrentlinker.paths import MappedQbit, PathMapper
    from torrentlinker.torrent_management import manage

    fake = FakeRtorrent()
    api = api_for(fake)
    h = api.add(pack(tmp_path), "/data", [])
    client = MappedQbit(api, PathMapper([]))
    assert not client.can_delete_files and not client.supports_partial_reseeds
    assert client.client_name == "rTorrent"
    seen = []

    [result] = manage(client, [h], "delete", seen.append)

    assert result.outcome == "failed" and seen == [result]
    assert result.detail.startswith("rTorrent cannot delete a torrent's files. Remove the torrent")
    assert not any(m == "d.erase" for m, _ in fake.calls)
    assert manage(client, [h], "remove")[0].outcome == "sent"


def test_an_unreachable_or_wrong_address_says_so() -> None:
    with pytest.raises(RtorrentError, match=r"does not answer at scgi://127\.0\.0\.1:9"):
        RtorrentApi("scgi://127.0.0.1:9").check()
    api = RtorrentApi(
        "https://seedbox.example/rutorrent",
        http=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404))),
    )
    with pytest.raises(RtorrentError, match=r"HTTP 404.*/RPC2"):
        api.check()


def test_the_rename_dialog_names_the_client(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.disk_rename import DiskRenamePlan
    from torrentlinker.gui.reseed_consent import DiskRenameDialog

    dialog = DiskRenameDialog(DiskRenamePlan("0" * 40, "Film", ()), None, "rTorrent")
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "rTorrent: rename files on disk?"
    assert "µTorrent" not in dialog.findChild(QLabel).text()  # type: ignore[union-attr]


def test_the_review_refuses_a_partial_match_and_names_the_client(
    qtbot, tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    from torrentlinker.domain import ItemState, LibraryFolder
    from torrentlinker.gui.review_panel import ReviewPanel
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import MatchRules
    from torrentlinker.paths import MappedQbit, PathMapper
    from torrentlinker.review import check_candidate
    from torrentlinker.scan import scan_item
    from torrentlinker.store import Store

    (tmp_path / "scene").mkdir()
    data = pack(tmp_path / "scene")
    lib = tmp_path / "lib" / "Show"
    lib.mkdir(parents=True)
    (lib / "e1.mkv").write_bytes(b"a" * 3000)
    item = scan_item(lib)
    indexer = SimpleNamespace(fetch_torrent=lambda c: data)
    checked = check_candidate(
        indexer, item, Candidate("Show", 5000, "u"), MatchRules(min_partial_coverage=0.1)
    )
    assert checked.match is not None and not checked.match.is_full
    fake = FakeRtorrent()
    client = MappedQbit(api_for(fake), PathMapper([]))
    panel = ReviewPanel(
        Store(tmp_path / "s.db"), lambda: indexer, lambda: client, MatchRules, lambda: None, str
    )
    qtbot.addWidget(panel)
    entry = LibraryEntry(LibraryFolder(tmp_path / "lib"), item, ItemState.ORPHAN)
    panel.remember(entry, [checked])
    panel.set_entry(entry)
    panel.candidates.selectRow(0)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _, title, text: shown.append(text))

    panel.reseed_button.click()

    assert shown and shown[0].startswith("rTorrent cannot reseed a Partial Match")
    assert not any(m.startswith("load.") for m, _ in fake.calls)


def test_the_web_refuses_deleting_files_before_asking_to_confirm(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from tests.test_media_api import login
    from torrentlinker.web.app import create_app

    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.client = TorrentClient.RTORRENT
    settings.rtorrent.host = "scgi://127.0.0.1:9"  # never reached: the refusal comes first
    settings.save(config / "settings.json")
    (config / "client.ready").touch()  # connected once, as after the setup
    app = create_app(config, password="test-password-long", monitor_verifications=False)
    with TestClient(app) as browser:
        login(browser)
        response = browser.post(
            "/api/confirm", json={"kind": "manage", "action": "delete", "hashes": ["a" * 40]}
        )
    assert response.status_code == 400, response.text
    assert "rTorrent cannot delete a torrent's files" in response.text
