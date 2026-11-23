"""The proxy: every connection goes through it, the Torrent Client only when asked."""

import base64
import socket
import socketserver
import struct
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from torrentlinker import net


class _Target(BaseHTTPRequestHandler):
    """The site, behind the proxy."""

    def do_GET(self) -> None:  # noqa: N802
        body = b"hello from the target"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class _HttpProxy(BaseHTTPRequestHandler):
    """A plain HTTP proxy that wants user:secret."""

    seen: list[tuple[str, str]] = []

    def do_GET(self) -> None:  # noqa: N802
        auth = self.headers.get("Proxy-Authorization", "")
        _HttpProxy.seen.append((self.path, auth))
        if auth != "Basic " + base64.b64encode(b"user:s3cr:et").decode():
            self.send_response(407)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"through the http proxy"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class _Socks5(socketserver.BaseRequestHandler):
    """A SOCKS5 proxy with username/password, relaying to the requested host."""

    used: list[tuple[str, str]] = []

    def handle(self) -> None:
        c = self.request
        _ver, n = c.recv(2)
        methods = c.recv(n)
        assert 2 in methods
        c.sendall(b"\x05\x02")
        _v, ulen = c.recv(2)
        user = c.recv(ulen).decode()
        (plen,) = c.recv(1)
        password = c.recv(plen).decode()
        _Socks5.used.append((user, password))
        c.sendall(b"\x01\x00" if (user, password) == ("user", "pw") else b"\x01\x01")
        _v, _cmd, _rsv, atyp = c.recv(4)
        if atyp == 1:
            host = socket.inet_ntoa(c.recv(4))
        else:
            (hlen,) = c.recv(1)
            host = c.recv(hlen).decode()
        (port,) = struct.unpack("!H", c.recv(2))
        upstream = socket.create_connection(("127.0.0.1" if host == "target.test" else host, port))
        c.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", port))
        for a, b in ((c, upstream), (upstream, c)):
            threading.Thread(target=_pipe, args=(a, b), daemon=True).start()
        threading.Event().wait(1)


def _pipe(a: socket.socket, b: socket.socket) -> None:
    try:
        while data := a.recv(65536):
            b.sendall(data)
    except OSError:
        pass


@pytest.fixture
def target() -> Iterator[int]:
    server = HTTPServer(("127.0.0.1", 0), _Target)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port
    server.shutdown()


@pytest.fixture
def http_proxy() -> Iterator[int]:
    _HttpProxy.seen = []
    server = HTTPServer(("127.0.0.1", 0), _HttpProxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port
    server.shutdown()


@pytest.fixture
def socks_proxy() -> Iterator[int]:
    _Socks5.used = []
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Socks5)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def test_a_proxy_address_takes_its_credentials_and_hides_its_password() -> None:
    url = net.proxy_url("socks5h://proxy.lan:1080", "me@home", "p:w/d")
    assert url == "socks5h://me%40home:p%3Aw%2Fd@proxy.lan:1080"
    assert net.redacted(url) == "socks5h://me%40home@proxy.lan:1080"
    assert net.proxy_url("proxy.lan:3128") == "http://proxy.lan:3128"
    assert net.proxy_url("  ") is None
    for wrong in ("ftp://proxy:21", "socks5://proxy", "http://:8080"):
        with pytest.raises(ValueError):
            net.proxy_url(wrong)


def test_internet_connections_go_through_an_http_proxy_with_its_login(
    target: int, http_proxy: int
) -> None:
    net.configure(net.proxy_url(f"http://127.0.0.1:{http_proxy}", "user", "s3cr:et"))

    r = net.client().get(f"http://site.test:{target}/api")

    assert r.text == "through the http proxy"
    assert _HttpProxy.seen[-1][0] == f"http://site.test:{target}/api"


def test_the_torrent_client_goes_direct_unless_asked(target: int, http_proxy: int) -> None:
    proxy = net.proxy_url(f"http://127.0.0.1:{http_proxy}", "user", "s3cr:et")
    net.configure(proxy)
    assert net.client(torrent_client=True).get(f"http://127.0.0.1:{target}/").text == (
        "hello from the target"
    )
    assert net.requests_proxies() == {}

    net.configure(proxy, for_torrent_client=True)
    assert net.client(torrent_client=True).get(f"http://127.0.0.1:{target}/").text == (
        "through the http proxy"
    )
    assert net.requests_proxies() == {"http": proxy, "https": proxy}


def test_socks5_with_a_login_carries_httpx_and_requests(target: int, socks_proxy: int) -> None:
    proxy = net.proxy_url(f"socks5h://127.0.0.1:{socks_proxy}", "user", "pw")
    net.configure(proxy, for_torrent_client=True)

    assert net.client().get(f"http://target.test:{target}/").text == "hello from the target"
    # qBittorrent's adapter speaks through requests
    r = requests.get(f"http://target.test:{target}/", proxies=net.requests_proxies(), timeout=10)
    assert r.text == "hello from the target"
    assert _Socks5.used == [("user", "pw"), ("user", "pw")]


def test_no_proxy_means_a_direct_connection(target: int) -> None:
    net.configure(None)
    assert net.client().get(f"http://127.0.0.1:{target}/").text == "hello from the target"


def test_settings_keep_the_proxy_and_its_password_in_the_keyring(qtbot, tmp_path):
    from tests.settings_support import edit_field, save_group, settings_page
    from tests.test_community_interfaces import js
    from torrentlinker.config import Settings
    from torrentlinker.credentials import get_secret
    from torrentlinker.gui.settings_common import PROXY_PASSWORD

    dialog = settings_page(qtbot, tmp_path)
    edit_field(qtbot, dialog.view, "Proxy address", "socks5h://proxy.lan:1080")
    edit_field(qtbot, dialog.view, "Proxy username", "me")
    edit_field(qtbot, dialog.view, "Proxy password", "pw")
    js(
        qtbot,
        dialog.view,
        "document.querySelector('[aria-label=\"Also for the Torrent Client\"]').click()",
    )
    save_group(qtbot, dialog)
    loaded = Settings.load(tmp_path / "settings.json")
    assert (loaded.proxy.address, loaded.proxy.username, loaded.proxy.torrent_client) == (
        "socks5h://proxy.lan:1080",
        "me",
        True,
    )
    assert get_secret(PROXY_PASSWORD) == "pw"
    assert '"pw"' not in (tmp_path / "settings.json").read_text()


def test_an_unusable_proxy_address_is_not_saved(qtbot, tmp_path):
    from tests.settings_support import edit_field, settings_page
    from tests.test_community_interfaces import js, wait_js

    dialog = settings_page(qtbot, tmp_path)
    edit_field(qtbot, dialog.view, "Proxy address", "ftp://proxy:21")
    js(
        qtbot,
        dialog.view,
        "document.querySelector('.settings-form > .settings-actions .primary').click()",
    )
    wait_js(qtbot, dialog.view, "Boolean(document.querySelector('#settings-error').textContent)")
    assert dialog.setup.settings.proxy.address == ""
    assert not dialog.setup.path.exists()
    assert dialog.isVisible()


def test_a_new_proxy_makes_the_kept_connections_again(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.config import Settings
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.store import Store

    settings = Settings()
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    indexer = window.indexer()
    window.qbit()
    client = window.qbit()._inner
    assert window.indexer() is indexer  # kept while nothing changes

    settings.proxy.address = "http://proxy.lan:3128"
    window.apply_proxy()

    assert net.current() == ("http://proxy.lan:3128", None)
    assert window.indexer() is not indexer
    window.qbit()
    assert window.qbit()._inner is not client
