"""A refused login stops every automatic login; nothing here reaches a real client."""

import os
import socket
import threading
import time

import httpx
import pytest
import qbittorrentapi

from torrentlinker import qbit
from torrentlinker.deluge import DelugeApi
from torrentlinker.login_guard import LoginRefused
from torrentlinker.qbit import QbitApi
from torrentlinker.transmission import TransmissionApi
from torrentlinker.utorrent import UtorrentApi

HOST = "http://192.0.2.50:8080"
BANNED = "Your IP address has been banned after too many failed authentication attempts."


class FakeClient:
    """qbittorrentapi.Client with a scripted login; counts what the server would see."""

    mode = "ok"  # ok | wrong | banned
    logins = 0
    expired = 0  # the next calls answer 403 as if the session had ended
    calls = 0

    def __init__(self, **kwargs):
        self.api_key = kwargs.get("api_key")
        self._lock = threading.Lock()
        self.session = False

    def auth_log_in(self):
        with self._lock:
            type(self).logins += 1
        if self.mode == "wrong":
            raise qbittorrentapi.LoginFailed()
        if self.mode == "banned":
            raise qbittorrentapi.Forbidden403Error(BANNED)
        self.session = True

    def app_version(self):
        return "v5.2.0"

    def app_default_save_path(self):
        with self._lock:
            type(self).calls += 1
            if type(self).expired:
                type(self).expired -= 1
                self.session = False
        if not self.api_key and not self.session:
            raise qbittorrentapi.Forbidden403Error("Forbidden")
        return "/downloads"


@pytest.fixture(autouse=True)
def fake_qbittorrent(monkeypatch):
    FakeClient.mode, FakeClient.logins, FakeClient.expired, FakeClient.calls = "ok", 0, 0, 0
    monkeypatch.setattr(qbit.qbittorrentapi, "Client", FakeClient)


def poll(api, times=40, threads=8):
    """Many refreshes at once, as the seed state, Zen, Library and Torrents all poll."""
    errors = []

    def run():
        for _ in range(times // threads):
            try:
                api.default_save_path()
            except Exception as error:  # noqa: BLE001
                errors.append(error)

    workers = [threading.Thread(target=run) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return errors


def test_a_wrong_password_is_tried_once_across_many_polls_and_threads():
    FakeClient.mode = "wrong"
    errors = poll(QbitApi(HOST, "admin", "wrong"))
    assert len(errors) == 40
    assert all(isinstance(error, LoginRefused) and not error.banned for error in errors)
    assert FakeClient.logins == 1
    assert "Settings" in str(errors[0])


def test_changing_any_setting_arms_the_login_again():
    FakeClient.mode = "wrong"
    poll(QbitApi(HOST, "admin", "wrong"))
    assert FakeClient.logins == 1
    FakeClient.mode = "ok"
    # The same credentials stay refused, even on a new adapter (a rebuilt profile)...
    assert all(isinstance(e, LoginRefused) for e in poll(QbitApi(HOST, "admin", "wrong")))
    assert FakeClient.logins == 1
    # ...a changed password, username or address is a new chance.
    for index, api in enumerate(
        [
            QbitApi(HOST, "admin", "right"),
            QbitApi(HOST, "owner", "wrong"),
            QbitApi("http://192.0.2.51:8080", "admin", "wrong"),
        ],
        start=2,
    ):
        assert poll(api) == []
        assert FakeClient.logins == index


def test_pressing_test_tries_again_and_a_good_answer_frees_every_caller():
    FakeClient.mode = "wrong"
    api = QbitApi(HOST, "admin", "secret")
    poll(api)
    with pytest.raises(LoginRefused):
        api.check()
    assert FakeClient.logins == 2  # the explicit Test is one more attempt, then silence
    poll(api)
    assert FakeClient.logins == 2
    FakeClient.mode = "ok"  # the user fixed qBittorrent's side, same credentials
    assert api.check() == "v5.2.0"
    assert poll(api) == []


def test_a_ban_stops_everything_and_says_so_in_both_languages():
    FakeClient.mode = "banned"
    errors = poll(QbitApi(HOST, "admin", "secret"))
    assert FakeClient.logins == 1
    assert all(isinstance(error, LoginRefused) and error.banned for error in errors)
    english, french = errors[0].text("en"), errors[0].text("fr")
    assert "banned" in english and "Restart qBittorrent" in english
    assert "banni" in french and "Redémarrez qBittorrent" in french


def test_an_api_key_never_logs_in():
    api = QbitApi(HOST, "", "", "tlk_" + "a" * 32)
    assert api.check() == "v5.2.0"
    assert poll(api) == []
    assert FakeClient.logins == 0


def test_an_expired_session_logs_in_once_for_all_threads_and_never_loops():
    api = QbitApi(HOST, "admin", "secret")
    assert api.default_save_path() == "/downloads"
    FakeClient.expired = 1
    assert poll(api, 16, 8) == []
    assert FakeClient.logins == 2  # the first login, one more for the lost session
    FakeClient.logins = 0
    FakeClient.expired = 10**6  # the server keeps refusing: one relogin per call, no loop
    with pytest.raises(qbittorrentapi.Forbidden403Error):
        api.default_save_path()
    assert FakeClient.logins == 1


def test_a_ban_answered_to_an_ordinary_call_stops_logins_too(monkeypatch):
    api = QbitApi(HOST, "admin", "secret")
    api.default_save_path()
    monkeypatch.setattr(
        FakeClient,
        "app_default_save_path",
        lambda self: (_ for _ in ()).throw(qbittorrentapi.Forbidden403Error(BANNED)),
    )
    errors = poll(api, 8, 4)
    assert all(isinstance(e, LoginRefused) and e.banned for e in errors)
    assert FakeClient.logins == 1


def http_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_deluge_asks_a_refused_password_once():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": 1, "result": False, "error": None})

    api = DelugeApi("http://192.0.2.60:8112", "wrong", http=http_client(handler))
    assert all(isinstance(e, LoginRefused) for e in poll(api))
    assert len(seen) == 1
    DelugeApi("http://192.0.2.60:8112", "other", http=http_client(handler))
    assert len(seen) == 1


def test_utorrent_asks_refused_credentials_once():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(401)

    api = UtorrentApi("http://192.0.2.61:8080", "admin", "wrong", http=http_client(handler))
    assert all(isinstance(e, LoginRefused) for e in poll(api))
    assert len(seen) == 1


def test_transmission_sends_refused_credentials_once():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(401)

    api = TransmissionApi("http://192.0.2.62:9091", "u", "wrong", http=http_client(handler))
    assert all(isinstance(e, LoginRefused) for e in poll(api))
    assert len(seen) == 1


@pytest.mark.parametrize("language,expected", [("en", "banned"), ("fr", "banni")])
def test_settings_show_the_ban_not_a_generic_failure(tmp_path, language, expected):
    from tests.test_web_plan_execution import prepared
    from torrentlinker.settings_workspace import SettingsWorkspace

    _, setup, _, _ = prepared(tmp_path)
    setup.settings.language = language
    FakeClient.mode = "banned"
    setup.connector = lambda kind, host, username, password, key: QbitApi(
        host, username, password, key
    )
    with pytest.raises(ValueError) as refused:
        SettingsWorkspace(setup).test_connection(
            "client", {"client": "qbittorrent", "host": "192.0.2.70:8080", "password": "x"}
        )
    assert expected in str(refused.value)
    assert "Authentication failed" not in str(refused.value)


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_settings_toast_the_wrong_address_and_a_refused_login_in_french(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.shell_support import shell_navigate
    from torrentlinker.login_guard import LoginRefused
    from torrentlinker.web.app import create_app

    def refusing(kind, host, username, password, key):
        class Refused:
            def check(self):
                raise LoginRefused(banned=True)

        return Refused()

    app = create_app(
        tmp_path / "config",
        password="test-password-long",
        connector=refusing,
        monitor_verifications=False,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(locale="fr-FR")
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "setup")
            panel = page.frame_locator("#settings-frame")
            address = panel.get_by_label("Adresse", exact=True)
            test = panel.get_by_role("button", name="Tester la connexion", exact=True)
            address.fill("nas:99999")
            test.click()
            wrong = panel.locator(".tl-toast.bad").filter(has_text="Adresse du client : le port")
            expect(wrong).to_be_visible()
            address.fill("192.168.0.50:8080")
            test.click()
            banned = panel.locator(".tl-toast.bad").filter(has_text="qBittorrent a banni")
            expect(banned).to_be_visible()
            test.click()
            expect(banned).to_have_count(1)  # the same refusal never stacks up
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
