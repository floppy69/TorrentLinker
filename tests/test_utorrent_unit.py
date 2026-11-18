import httpx
import pytest

from tests.torrents import make_torrent
from torrentlinker.client_folders import ClientFolder
from torrentlinker.domain import LocalItem, PathMapping
from torrentlinker.matching import Match
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.reseed import TAG, VERIFYING, check_verifications, start_reseed
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.utorrent import UtorrentApi, UtorrentError, _state

H = "a" * 40


def row(hash=H, name="book.epub", save_path="C:\\Downloads", label="personal"):
    result = [
        hash.upper(),
        137,
        name,
        100,
        1000,
        100,
        200,
        2000,
        11,
        12,
        -1,
        label,
        1,
        2,
        3,
        4,
        0,
        1,
        0,
        "",
        "",
        "Seeding",
        "1",
        1,
        0,
        "",
        save_path,
        0,
        "",
    ]
    return result


class WebUI:
    def __init__(self):
        self.token = "token1"
        self.auths = 0
        self.calls = []
        self.jobs = {H: row()}
        self.file_rows = {H: [["book.epub", 100, 100, 2]]}
        self.settings = {
            "dir_active_download_flag": "true",
            "dir_active_download": "C:\\Downloads",
            "dir_completed_download_flag": "false",
            "dir_completed_download": "C:\\Done",
            "torrents_start_stopped": "true",
            "append_incomplete": "false",
            "dir_add_label": "false",
        }
        self.ignore_path = False
        self.expire = False
        self.bad_password = False

    def handle(self, request):
        assert request.headers["authorization"].startswith("Basic ")
        if self.bad_password:
            return httpx.Response(401)
        if request.url.path.endswith("token.html"):
            self.auths += 1
            self.token = f"token{self.auths}"
            return httpx.Response(
                200,
                text=f"<div id='token' style='display:none'>{self.token}</div>",
                headers={"Set-Cookie": f"GUID=session{self.auths}; Path=/"},
            )
        params = request.url.params
        assert f"GUID=session{self.auths}" in request.headers["cookie"]
        if self.expire:
            self.expire = False
            return httpx.Response(400)
        assert params["token"] == self.token
        self.calls.append(dict(params))
        action = params.get("action")
        hash = params.get("hash", "").lower()
        reply = {"build": 47390}
        if params.get("list"):
            reply["torrents"] = list(self.jobs.values())
        elif action == "getsettings":
            reply["settings"] = [[k, 2, v] for k, v in self.settings.items()]
        elif action == "getprops":
            reply["props"] = [
                {"hash": h.upper(), "trackers": "https://tracker.example/announce\r\n"}
                for h in params.get_list("hash")
                if h.lower() in self.jobs
            ]
        elif action == "getfiles":
            reply["files"] = [hash.upper(), self.file_rows[hash]]
        elif action == "add-file":
            assert request.method == "POST"
            body = request.read().split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            meta = read_torrent(body)
            destination = self.settings["dir_active_download"]
            if params["path"] and not self.ignore_path:
                destination += "\\" + params["path"]
            multi = UtorrentApi._multifile(meta)
            if multi:
                destination += "\\" + meta.name
            self.jobs[meta.infohash] = row(meta.infohash, meta.name, destination, "")
            self.jobs[meta.infohash][1] = 136
            self.jobs[meta.infohash][4] = 0
            self.file_rows[meta.infohash] = [
                [name[len(meta.name) + 1 :] if multi else name, size, 0, 2]
                for name, size in meta.files.items()
            ]
        elif action == "setprops":
            self.jobs[hash][11] = params["v"]
        elif action == "setprio":
            for i in params.get_list("f"):
                self.file_rows[hash][int(i)][3] = int(params["p"])
        elif action == "remove":
            self.jobs.pop(hash, None)
        elif action in {"start", "stop", "recheck"}:
            pass
        else:
            raise AssertionError(action)
        return httpx.Response(200, json=reply)


def api_for(web, host="http://client:8081/gui/"):
    return UtorrentApi(
        host, "user", "secret", http=httpx.Client(transport=httpx.MockTransport(web.handle))
    )


@pytest.mark.parametrize(
    "host", ["http://client:8081", "client:8081/gui/", "https://client/prefix/gui"]
)
def test_authentication_token_cookie_and_expiration(host):
    web = WebUI()
    api = api_for(web, host)
    assert api.check() == "build 47390 (experimental)"
    web.expire = True
    api.check()
    assert web.auths == 2
    assert api._url.endswith("/gui/")


def test_bad_credentials_and_wrong_edition_are_clear():
    web = WebUI()
    web.bad_password = True
    with pytest.raises(UtorrentError, match="credentials"):
        api_for(web).check()
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>Web</html>"))
    )
    with pytest.raises(UtorrentError, match="Classic"):
        UtorrentApi("http://client", "", "", http).check()


def test_lists_paths_trackers_personal_label_and_statistics_without_file_requests():
    web = WebUI()
    api = api_for(web)
    item = api.torrents(with_files=False)[0]
    assert item.hash == H
    assert str(item.save_path) == "C:\\Downloads"
    assert item.category == "personal" and item.tags == frozenset({"personal"})
    assert item.progress == 1 and item.state == "uploading"
    assert item.ratio == 2 and item.download_rate == 12 and item.upload_rate == 11
    assert item.trackers == ("https://tracker.example/announce",)
    assert not any(c.get("action") == "getfiles" for c in web.calls)
    api.torrents(with_files=False)
    assert sum(c.get("action") == "getprops" for c in web.calls) == 1
    assert api.torrents(tag="absent") == []
    assert api.torrent("b" * 40) is None
    assert api.torrent(H).files == {"book.epub": 100}


def test_multifile_paths_remain_relative_to_reported_content_root():
    web = WebUI()
    web.jobs[H][26] = "D:\\Books\\Bundle"
    web.file_rows[H] = [["one.epub", 100, 100, 2], ["Sub\\two.epub", 200, 0, 0]]
    item = api_for(web).torrent(H)
    assert str(item.save_path) == "D:\\Books\\Bundle"
    assert item.files == {"one.epub": 100, "Sub/two.epub": 200}


@pytest.mark.parametrize(
    "flags,progress,state",
    [
        (137, 1, "uploading"),
        (137, 0.5, "downloading"),
        (136, 1, "stoppedUP"),
        (169, 0.5, "stoppedDL"),
        (138, 0.5, "checkingDL"),
        (152, 0, "error"),
    ],
)
def test_state_translation(flags, progress, state):
    assert _state(flags, progress) == state


def test_folder_import_respects_enabled_flags_and_has_no_global_writes():
    web = WebUI()
    api = api_for(web)
    assert api.folder_settings() == [ClientFolder("", "C:\\Downloads", "default")]
    web.settings["dir_completed_download_flag"] = "true"
    assert api.folder_settings()[-1] == ClientFolder("", "C:\\Done", "completed")
    web.settings["dir_active_download_flag"] = "false"
    with pytest.raises(UtorrentError, match="default download folder"):
        api.default_save_path()
    assert all(c.get("action") == "getsettings" for c in web.calls)


def test_download_checks_stopped_state_and_destination_before_starting(tmp_path):
    f = tmp_path / "new.txt"
    f.write_bytes(b"disposable" * 100)
    data = make_torrent(f)
    web = WebUI()
    api = api_for(web)
    h = api.download(data, "C:\\Downloads\\Books", ["torrentlinker:zen"])
    assert web.jobs[h][26] == "C:\\Downloads\\Books"
    assert web.jobs[h][11] == "torrentlinker:zen"
    actions = [c.get("action") for c in web.calls]
    assert actions.index("add-file") < actions.index("setprops") < actions.index("start")
    assert not any(a == "setsetting" for a in actions)
    with pytest.raises(AlreadyInClient):
        api.download(data, "C:\\Downloads", [])


@pytest.mark.parametrize(
    "folder", ["D:\\Other", "C:\\DownloadsOther", "C:\\Downloads\\..\\Other", "relative"]
)
def test_download_refuses_unsupported_destinations_before_adding(tmp_path, folder):
    f = tmp_path / "new.txt"
    f.write_text("disposable")
    web = WebUI()
    with pytest.raises(UtorrentError, match="default download folder"):
        api_for(web).download(make_torrent(f), folder, [])
    assert not any(c.get("action") == "add-file" for c in web.calls)


def test_download_requires_user_to_enable_stopped_adds(tmp_path):
    f = tmp_path / "new.txt"
    f.write_text("disposable")
    web = WebUI()
    web.settings["torrents_start_stopped"] = "false"
    with pytest.raises(UtorrentError, match="automatically"):
        api_for(web).download(make_torrent(f), "C:\\Downloads", [])
    assert not any(c.get("action") in {"add-file", "setsetting"} for c in web.calls)


def test_silent_path_fallback_removes_only_new_job_and_never_starts(tmp_path):
    f = tmp_path / "new.txt"
    f.write_text("disposable")
    web = WebUI()
    web.ignore_path = True
    with pytest.raises(UtorrentError, match="requested folder"):
        api_for(web).download(make_torrent(f), "C:\\Downloads\\Books", [])
    assert list(web.jobs) == [H]
    assert web.calls[-1]["action"] == "remove"
    assert not any(c.get("action") == "start" for c in web.calls)


def test_management_keeps_data_and_personal_labels():
    web = WebUI()
    api = api_for(web)
    api.pause(H)
    api.resume(H)
    api.recheck(H)
    api.set_file_priority(H, [0], 0)
    assert not api.file_listing(H)[0].wanted
    with pytest.raises(UtorrentError, match="no longer exists"):
        api.set_file_priority(H, [2], 1)
    with pytest.raises(UtorrentError, match="personal label"):
        api.add_tags(H, ["torrentlinker"])
    assert web.jobs[H][11] == "personal"
    api.remove(H)
    assert web.calls[-1]["action"] == "remove"
    assert not any(
        c.get("action") in {"removedata", "removedatatorrent", "setsetting"} for c in web.calls
    )


def test_unsupported_reseeds_do_not_contact_client():
    web = WebUI()
    api = api_for(web)
    with pytest.raises(UtorrentError, match="renaming"):
        api.rename_file(H, "a", "b")
    with pytest.raises(UtorrentError, match="Piece"):
        api.piece_states(H)
    assert web.calls == [] and web.auths == 0


def test_reseed_preflight_refuses_missing_files_before_contacting_client(tmp_path):
    f = tmp_path / "book.epub"
    f.write_bytes(b"book" * 10000)
    meta = read_torrent(make_torrent(f))
    match = Match({}, absent=(f.name,))
    web = WebUI()
    client = MappedQbit(api_for(web), PathMapper([]))
    with pytest.raises(UtorrentError, match="Partial Matches"):
        start_reseed(client, Store(tmp_path / "s.db"), LocalItem(f), meta, match, "candidate")
    assert web.calls == [] and web.auths == 0


@pytest.mark.parametrize(
    "setting,value",
    [
        ("append_incomplete", "true"),
        ("dir_completed_download_flag", "true"),
        ("dir_add_label", "true"),
        ("finish_cmd", "some command"),
        ("state_cmd", "some command"),
    ],
)
def test_reseed_refuses_file_changing_preferences_before_add(tmp_path, setting, value):
    f = tmp_path / "book.epub"
    f.write_bytes(b"book" * 10000)
    web = WebUI()
    web.settings[setting] = value
    with pytest.raises(UtorrentError, match="Disable"):
        api_for(web).add(make_torrent(f), "C:\\Downloads", [TAG, VERIFYING])
    assert not any(c.get("action") in {"add-file", "setsetting"} for c in web.calls)


@pytest.mark.parametrize("multi", [False, True])
def test_full_reseed_verification_survives_new_adapter_and_preserves_native_layout(tmp_path, multi):
    local = tmp_path / "Library"
    local.mkdir()
    if multi:
        local = local / "Bundle"
        local.mkdir()
    f = local / "book.epub"
    f.write_bytes(b"book" * 10000)
    meta = read_torrent(make_torrent(local if multi else f))
    item = LocalItem(local if multi else f, meta.files)
    web = WebUI()
    mapper = PathMapper([PathMapping(str(tmp_path / "Library"), "C:\\Downloads")])
    client = MappedQbit(api_for(web), mapper)
    store = Store(tmp_path / "s.db")
    h = start_reseed(client, store, item, meta, Match({p: p for p in meta.files}), "candidate")
    # Recorded where the user keeps them (beside the Local Item), not in µTorrent's
    # layout, whose multifile save path is the content folder itself.
    assert store.verification(h).local_files == ["Bundle/book.epub" if multi else "book.epub"]
    assert client.torrent(h).save_path == local
    assert not any(c.get("action") == "start" for c in web.calls)
    assert check_verifications(client, store) == []
    web.jobs[h][4] = 1000
    for file in web.file_rows[h]:
        file[2] = file[1]
    # Recovery depends only on the persisted Verification and client's label/paths.
    outcomes = check_verifications(MappedQbit(api_for(web), mapper), store)
    assert len(outcomes) == 1 and outcomes[0].started
    assert web.jobs[h][11] == TAG
    assert store.verification(h) is None
    assert any(c.get("action") == "start" for c in web.calls)
    assert f.read_bytes() == b"book" * 10000


@pytest.mark.parametrize("problem", ["missing_byte", "skipped_file", "checking", "move_enabled"])
def test_verified_job_cannot_start_with_incomplete_files_or_changed_preferences(problem):
    web = WebUI()
    web.jobs[H][11] = VERIFYING
    if problem == "missing_byte":
        web.file_rows[H][0][2] = 99
    elif problem == "skipped_file":
        web.file_rows[H][0][3] = 0
    elif problem == "checking":
        web.jobs[H][1] |= 2
    else:
        web.settings["dir_completed_download_flag"] = "true"
    with pytest.raises(UtorrentError):
        api_for(web).start(H)
    assert not any(c.get("action") == "start" for c in web.calls)


def test_removing_verification_label_preserves_personal_label():
    web = WebUI()
    api_for(web).remove_tags(H, [VERIFYING])
    assert web.jobs[H][11] == "personal"
    assert not any(c.get("action") == "setprops" for c in web.calls)


def test_settings_roundtrip_and_app_factory(qtbot, tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.credentials import get_secret
    from torrentlinker.domain import TorrentClient
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.gui.settings_dialog import UTORRENT_PASSWORD, SettingsDialog
    from torrentlinker.store import Store

    settings = Settings()
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.client.setCurrentIndex(dialog.client.findData("utorrent"))
    assert dialog.client_forms.currentWidget().isAncestorOf(dialog.utorrent_host)
    dialog.utorrent_host.setText("http://client:18089/gui/")
    dialog.utorrent_user.setText("tester")
    dialog.utorrent_password.setText("secret")
    assert isinstance(dialog._form_qbit(), UtorrentApi)
    dialog._save()
    settings.save(tmp_path / "settings.json")
    saved = Settings.load(tmp_path / "settings.json")
    assert saved.client is TorrentClient.UTORRENT
    assert saved.utorrent.host == "http://client:18089/gui/" and saved.utorrent.username == "tester"
    assert get_secret(UTORRENT_PASSWORD) == "secret"
    assert "secret" not in (tmp_path / "settings.json").read_text()
    w = MainWindow(saved, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(w)
    w.qbit()
    assert isinstance(w.qbit()._inner, UtorrentApi)
