import sys
from ipaddress import ip_network

import pytest
from fastapi.testclient import TestClient

from torrentlinker.web import server
from torrentlinker.web.app import create_app

PROXY = (ip_network("172.18.0.0/16"),)


def proxied(tmp_path, host="172.18.0.2"):
    return TestClient(create_app(tmp_path, password=None, trusted_proxies=PROXY), client=(host, 1))


def test_the_reverse_proxy_stands_for_the_owner_without_a_web_ui_password(tmp_path):
    with proxied(tmp_path) as browser:
        setup = browser.get("/api/setup")
        assert setup.status_code == 200
        assert setup.json()["web_auth"] == "proxy"
        page = browser.get("/api/documentation/page/guide/en/getting-started.md")
        assert page.status_code == 200
        headers = {"X-TorrentLinker": "1"}
        assert (
            browser.post("/api/login", json={"password": "x"}, headers=headers).status_code == 404
        )
        assert browser.post("/api/logout", json={}, headers=headers).status_code == 200


@pytest.mark.parametrize("host", ["10.0.0.5", "172.19.0.2", "::ffff:10.0.0.5", "testclient", "::1"])
def test_requests_that_bypass_the_reverse_proxy_are_refused(tmp_path, host):
    with proxied(tmp_path, host) as browser:
        # 403 rather than 401: this is not an expired Web UI session.
        assert browser.get("/api/setup").status_code == 403
        assert browser.get("/api/agents").status_code == 403
        assert browser.get("/documentation/guide/en/getting-started.md").status_code == 403


def test_an_ipv4_mapped_proxy_address_is_trusted(tmp_path):
    with proxied(tmp_path, "::ffff:172.18.0.2") as browser:
        assert browser.get("/api/setup").status_code == 200


def test_mutations_still_require_the_browser_header_behind_the_proxy(tmp_path):
    with proxied(tmp_path) as browser:
        response = browser.post("/api/logout", json={})
        assert response.status_code == 403
        assert response.json()["detail"] == "Browser request header required."


def test_agents_keep_their_own_token_whatever_their_address(tmp_path):
    with proxied(tmp_path, "10.0.0.5") as browser:
        response = browser.post("/mcp/", json={})
        assert response.status_code == 401
        assert response.json() == {"error": "Agent token required."}


def test_the_password_mode_is_reported_and_unchanged(tmp_path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        assert browser.get("/api/setup").status_code == 401
        browser.post(
            "/api/login", json={"password": "test-password-long"}, headers={"X-TorrentLinker": "1"}
        )
        assert browser.get("/api/setup").json()["web_auth"] == "password"


@pytest.mark.parametrize(
    "options",
    [
        {"password": None},
        {"password": "test-password-long", "trusted_proxies": PROXY},
    ],
)
def test_exactly_one_owner_check_is_configured(tmp_path, options):
    with pytest.raises(ValueError, match="password or trusted proxies"):
        create_app(tmp_path, **options)


def test_trusted_proxies_come_from_the_command_line_before_the_environment():
    environ = {"TL_TRUSTED_PROXIES": "10.0.0.0/8, fd00::/8"}
    assert server.trusted_networks([], environ) == (
        ip_network("10.0.0.0/8"),
        ip_network("fd00::/8"),
    )
    assert server.trusted_networks(["172.18.0.1"], environ) == (ip_network("172.18.0.1/32"),)
    assert server.trusted_networks([], {}) == ()
    with pytest.raises(ValueError):
        server.trusted_networks(["reverse-proxy"], {})


def start(monkeypatch, tmp_path, *arguments, **environ):
    started = {}
    monkeypatch.setattr(sys, "argv", ["torrentlinker-web", "--config", str(tmp_path), *arguments])
    for name in ("TL_WEB_AUTH", "TL_TRUSTED_PROXIES", "TL_WEB_PASSWORD", "TL_WEB_PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("torrentlinker.web.app.create_app", lambda d, **o: started.update(o))
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    server.main()
    return started


def test_proxy_mode_starts_without_a_password(monkeypatch, tmp_path):
    started = start(monkeypatch, tmp_path, TL_WEB_AUTH="proxy", TL_TRUSTED_PROXIES="172.18.0.0/16")
    assert started["password"] is None
    assert started["trusted_proxies"] == PROXY


@pytest.mark.parametrize("proxies", ["", "reverse-proxy"])
def test_proxy_mode_refuses_to_start_without_valid_trusted_proxies(monkeypatch, tmp_path, proxies):
    with pytest.raises(SystemExit):
        start(monkeypatch, tmp_path, TL_WEB_AUTH="proxy", TL_TRUSTED_PROXIES=proxies)


def test_password_mode_still_requires_a_password(monkeypatch, tmp_path):
    with pytest.raises(SystemExit):
        start(monkeypatch, tmp_path, "--trusted-proxy", "172.18.0.0/16")


def test_server_never_logs_request_urls_that_carry_api_keys(monkeypatch, tmp_path):
    import logging

    monkeypatch.setattr(logging.getLogger("httpx"), "level", logging.INFO)
    start(monkeypatch, tmp_path, TL_WEB_PASSWORD="correct horse battery")
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_a_single_proxy_address_trusts_no_neighbour(tmp_path):
    only = (ip_network("172.30.0.2/32"),)
    for host, status in (("172.30.0.2", 200), ("172.30.0.3", 403)):
        app = create_app(tmp_path / host, password=None, trusted_proxies=only)
        with TestClient(app, client=(host, 1)) as browser:
            assert browser.get("/api/setup").status_code == status


def test_a_proxy_address_does_not_sign_in_the_password_mode(tmp_path):
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app, client=("172.18.0.2", 1)) as browser:
        assert browser.get("/api/setup").status_code == 401


def test_an_unknown_web_auth_mode_refuses_to_start(monkeypatch, tmp_path):
    # With a password set, a mistyped mode must not quietly start in password mode.
    with pytest.raises(SystemExit):
        start(
            monkeypatch,
            tmp_path,
            TL_WEB_AUTH="proxi",
            TL_TRUSTED_PROXIES="172.18.0.0/16",
            TL_WEB_PASSWORD="test-password-long",
        )
