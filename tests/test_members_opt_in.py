"""Existing servers stay single-user unless the owner enables Members (#127)."""

from ipaddress import ip_network

import pytest
from fastapi.testclient import TestClient

from tests.test_web_jobs import Client, login
from torrentlinker.accounts import OWNER, Accounts, Permission
from torrentlinker.web.app import create_app
from torrentlinker.web.server import argument_parser


def test_members_environment_is_explicit(monkeypatch):
    monkeypatch.delenv("TL_WEB_MEMBERS", raising=False)
    assert argument_parser().parse_args([]).members == "off"
    monkeypatch.setenv("TL_WEB_MEMBERS", "on")
    assert argument_parser().parse_args([]).members == "on"
    assert argument_parser().parse_args(["--members", "off"]).members == "off"


@pytest.mark.parametrize("header", [None, "unknown-sso-owner", "lea"])
def test_default_proxy_ignores_identity_header(tmp_path, header):
    accounts = Accounts(tmp_path)
    account = accounts.create("Lea", "lea", {Permission.FILMS})
    accounts.set_proxy_user(account, "lea")
    accounts.close()
    app = create_app(
        tmp_path,
        password=None,
        trusted_proxies=(ip_network("10.0.0.0/8"),),
        monitor_verifications=False,
        connector=lambda *args: Client(),
    )
    with TestClient(app, client=("10.1.2.3", 5000)) as browser:
        if header:
            browser.headers["Remote-User"] = header
        assert browser.get("/api/shell").json()["actor"]["owner"] is True
        assert browser.get("/api/members").status_code == 404


def test_default_hides_routes_and_rejects_member_login(tmp_path):
    app = create_app(
        tmp_path,
        password="test-password-long",
        monitor_verifications=False,
        connector=lambda *args: Client(),
    )
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        for authenticated in (False, True):
            if authenticated:
                login(browser)
            for path in (
                "/api/members",
                "/api/account",
                "/api/screen",
                "/api/links/inspect",
                "/api/requests",
                "/api/wishes",
                "/api/member-workspace/search",
                "/api/member-assistant",
                "/api/notifications",
                "/notifications-worker.js",
                "/join",
            ):
                assert browser.get(path).status_code == 404, path
                assert browser.post(path, json={}).status_code == 404, path
        assert browser.get("/api/setup").json()["members_enabled"] is False
        assert 'data-members="false"' in browser.get("/").text
        assert (
            browser.post(
                "/api/login", json={"login": "lea", "password": "long-password"}
            ).status_code
            == 404
        )
        assert (
            browser.post(
                "/api/login", json={"screen": "TV", "password": "test-password-long"}
            ).status_code
            == 404
        )
        assert browser.get("/api/shell").json()["actor"]["owner"] is True


def test_disabling_revokes_access_without_deleting_accounts(tmp_path):
    accounts = Accounts(tmp_path)
    account = accounts.create("Lea", "lea", {Permission.FILMS}, password="long-password")
    session = accounts.open_session(account)
    screen = accounts.open_screen(account, "TV")
    link = accounts.password_link(account, days=3, inviter=OWNER)
    accounts.close()
    app = create_app(
        tmp_path,
        password="test-password-long",
        monitor_verifications=False,
        connector=lambda *args: Client(),
    )
    with TestClient(app) as browser:
        browser.cookies.set("tl_session", session)
        assert browser.get("/api/shell").status_code == 401
        accounts = app.state.accounts
        assert accounts.session(session) is None
        assert accounts.screen(screen) is None
        assert accounts.link(link) is None
        assert accounts.verify("lea", "long-password") == account
