import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.torrents import make_torrent
from torrentlinker.login_guard import LoginRefused
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.transmission import (
    PartialNamesOn,
    RenameUnsupported,
    TransmissionApi,
    _state,
)


class FakeRpc:
    """Transmission's RPC: a session id handshake, then methods on its torrents."""

    def __init__(self, partial_names: bool = False, password: str = "") -> None:
        self.session = "s1"
        self.password = password
        self.settings = {
            "version": "4.1.3",
            "download-dir": "/downloads",
            "rename-partial-files": partial_names,
        }
        self.torrents: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if (
            self.password
            and request.headers.get("authorization")
            != "Basic " + base64.b64encode(f"me:{self.password}".encode()).decode()
        ):
            return httpx.Response(401)
        if request.headers.get("X-Transmission-Session-Id") != self.session:
            return httpx.Response(409, headers={"X-Transmission-Session-Id": self.session})
        body = json.loads(request.content)
        self.calls.append(body["method"])
        result = getattr(self, body["method"].replace("-", "_"))(**body.get("arguments", {}))
        return httpx.Response(200, json={"result": "success", "arguments": result or {}})

    def session_get(self, fields: list[str]) -> dict[str, Any]:
        return {f: self.settings[f] for f in fields}

    def session_set(self, **settings: Any) -> None:
        self.settings.update(settings)

    def torrent_add(
        self, metainfo: str, paused: bool, labels: list[str], **kw: Any
    ) -> dict[str, Any]:
        meta = read_torrent(base64.b64decode(metainfo))
        if meta.infohash in self.torrents:
            return {"torrent-duplicate": {"hashString": meta.infohash}}
        self.torrents[meta.infohash] = {
            "hashString": meta.infohash.upper(),
            "name": meta.name,
            "downloadDir": kw["download-dir"],
            "labels": labels,
            "percentDone": 0.0,
            "status": 0 if paused else 4,
            "error": 0,
            "files": [{"name": n, "length": s} for n, s in meta.files.items()],
            "trackers": [{"announce": "https://tracker.c411.org/a"}],
            "trackerStats": [{"seederCount": 4}, {"seederCount": -1}],
            "secondsSeeding": 0,
            "totalSize": sum(meta.files.values()),
            "pieces": "",
            "pieceCount": 0,
        }
        return {"torrent-added": {"hashString": meta.infohash}}

    def torrent_get(self, fields: list[str], ids: list[str] | None = None) -> dict[str, Any]:
        chosen = [
            t for h, t in self.torrents.items() if ids is None or h in [i.lower() for i in ids]
        ]
        return {"torrents": [{f: t[f] for f in fields if f in t} for t in chosen]}

    def torrent_set(self, ids: list[str], **changes: Any) -> None:
        self.torrents[ids[0]].update(changes)

    def torrent_rename_path(self, ids: list[str], path: str, name: str) -> dict[str, Any]:
        t = self.torrents[ids[0]]
        renamed = "/".join([*path.split("/")[:-1], name])
        for f in t["files"]:
            if f["name"] == path or f["name"].startswith(path + "/"):
                f["name"] = renamed + f["name"][len(path) :]
        return {}


def api_for(rpc: FakeRpc, user: str = "", password: str = "") -> TransmissionApi:
    http = httpx.Client(transport=httpx.MockTransport(rpc.handler))
    return TransmissionApi("nas:9091", user, password, http=http)


@pytest.mark.parametrize("child", ["", "ebooks"])
def test_download_from_resolved_windows_share_uses_docker_path(tmp_path, monkeypatch, child):
    from pathlib import PureWindowsPath

    from torrentlinker.domain import PathMapping
    from torrentlinker.paths import MappedQbit, PathMapper

    drive = "Y:/mnt/disque2/DL2/TRANSMI/complete"
    share = PureWindowsPath(r"\\nas\root\mnt\disque2\DL2\TRANSMI\complete")
    original = Path.resolve

    def mapped_drive(path, *args, **kwargs):
        if str(path).replace("\\", "/") == drive:
            return share
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", mapped_drive)
    rpc = FakeRpc()

    def linux_transmission(request):
        body = json.loads(request.content)
        if body["method"] == "torrent-add":
            destination = body["arguments"]["download-dir"]
            if not destination.startswith("/"):
                return httpx.Response(
                    200, json={"result": "download directory path is not absolute", "arguments": {}}
                )
        return rpc.handler(request)

    api = TransmissionApi(
        "nas:9091", http=httpx.Client(transport=httpx.MockTransport(linux_transmission))
    )
    client = MappedQbit(api, PathMapper([PathMapping(drive, "/downloads/complete")]))
    source = tmp_path / "Book.epub"
    source.write_bytes(b"book")
    queued_folder = str(share / child)
    identity = client.download(make_torrent(source), queued_folder, ["torrentlinker:search"])
    expected = "/downloads/complete" + ("/" + child if child else "")
    assert rpc.torrents[identity]["downloadDir"] == expected
    assert rpc.torrents[identity]["status"] == 4
    assert len(rpc.torrents) == 1


def pack(tmp_path: Path, *names: str) -> bytes:
    root = tmp_path / "Pack"
    for n in names:
        (root / n).parent.mkdir(parents=True, exist_ok=True)
        (root / n).write_bytes(n.encode() * 100)
    return make_torrent(root)


def test_the_session_id_handshake_and_version() -> None:
    rpc = FakeRpc()
    api = api_for(rpc)
    assert api.check() == "4.1.3"
    assert api.default_save_path() == "/downloads"
    rpc.session = "s2"  # Transmission restarted
    assert api.check() == "4.1.3"


def test_a_wrong_password_is_reported() -> None:
    with pytest.raises(LoginRefused, match="refused the login"):
        api_for(FakeRpc(password="secret"), "me", "wrong").check()
    assert api_for(FakeRpc(password="secret"), "me", "secret").check() == "4.1.3"


def test_part_names_refuse_a_reseed_before_adding_until_turned_off(tmp_path: Path) -> None:
    rpc = FakeRpc(partial_names=True)
    api = api_for(rpc)

    with pytest.raises(PartialNamesOn) as refused:
        api.add(pack(tmp_path, "a.epub"), "/lib", ["torrentlinker"])
    assert rpc.torrents == {}
    with pytest.raises(PartialNamesOn):
        api.check()

    refused.value.turn_off()
    assert rpc.settings["rename-partial-files"] is False
    assert api.add(pack(tmp_path, "a.epub"), "/lib", ["torrentlinker"])


def test_plan_downloads_do_not_need_whole_names(tmp_path: Path) -> None:
    api = api_for(FakeRpc(partial_names=True))
    h = api.download(pack(tmp_path, "a.epub"), "/dl", ["torrentlinker:zen"])
    t = api.torrent(h)
    assert t is not None and t.state == "downloading" and t.tags == {"torrentlinker:zen"}
    assert t.swarm_seeders == 4 and t.tracker == "https://tracker.c411.org/a"
    with pytest.raises(AlreadyInClient):
        api.download(pack(tmp_path, "a.epub"), "/dl", [])


def test_tags_are_labels_and_filter_the_listing(tmp_path: Path) -> None:
    api = api_for(FakeRpc())
    h = api.add(pack(tmp_path, "a.epub"), "/lib", ["torrentlinker", "torrentlinker:verifying"])

    assert [t.hash for t in api.torrents(tag="torrentlinker:verifying")] == [h]
    api.add_tags(h, ["torrentlinker:partial"])
    api.remove_tags(h, ["torrentlinker:verifying"])
    assert api.torrents(tag="torrentlinker:verifying") == []
    assert api.torrent(h).tags == {"torrentlinker", "torrentlinker:partial"}  # type: ignore[union-attr]


def test_a_folder_rename_takes_its_files_along_and_names_change_in_place(
    tmp_path: Path,
) -> None:
    api = api_for(FakeRpc())
    h = api.add(pack(tmp_path, "a.epub", "b.epub"), "/lib", [])

    api.rename_file(h, "Pack/a.epub", "Mine/Le joueur.epub")
    api.rename_file(h, "Pack/b.epub", "Mine/b.epub")  # its folder is already renamed

    assert set(api.files(h)) == {"Mine/Le joueur.epub", "Mine/b.epub"}


def test_renames_into_other_folders_are_refused(tmp_path: Path) -> None:
    api = api_for(FakeRpc())
    h = api.add(pack(tmp_path, "a.epub", "b.epub"), "/lib", [])

    with pytest.raises(RenameUnsupported):
        api.rename_file(h, "Pack/a.epub", "a.epub")
    with pytest.raises(RenameUnsupported, match="taken"):
        api.rename_file(h, "Pack/a.epub", "Pack/b.epub")


def test_piece_states_read_the_bitfield_first_piece_first(tmp_path: Path) -> None:
    rpc = FakeRpc()
    api = api_for(rpc)
    h = api.add(pack(tmp_path, "a.epub"), "/lib", [])
    rpc.torrents[h].update(
        pieces=base64.b64encode(bytes([0b10100000, 0b10000000])).decode(), pieceCount=9
    )

    assert api.piece_states(h) == [2, 0, 2, 0, 0, 0, 0, 0, 2]


@pytest.mark.parametrize(
    "status,done,error,expected",
    [
        (0, 1.0, 0, "stoppedUP"),
        (0, 0.5, 0, "stoppedDL"),
        (1, 0.0, 0, "checkingDL"),
        (2, 1.0, 0, "checkingUP"),
        (4, 0.5, 0, "downloading"),
        (6, 1.0, 2, "uploading"),  # a tracker error is not the data's
        (0, 0.0, 3, "error"),
    ],
)
def test_transmission_statuses_read_as_qbittorrent_states(
    status: int, done: float, error: int, expected: str
) -> None:
    assert _state(status, done, error) == expected
