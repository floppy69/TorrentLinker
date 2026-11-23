"""Device linking never calls the real site and never exposes tracker or token secrets."""

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import member, sign_in
from tests.test_web_jobs import login
from tests.test_web_plan_execution import prepared
from torrentlinker.community_site import (
    LINK_SECRET,
    CommunitySite,
    community_site,
    membership_fingerprint,
)
from torrentlinker.web.app import create_app


@pytest.fixture
def linked():
    vault = {"indexer-api-key": "private-indexer-key"}
    now = [1000.0]
    calls = []
    replies = []
    refreshes = []

    def refresh(url, key):
        refreshes.append((url, key))
        return SimpleNamespace(username=" PrivatePerson ")

    setup = SimpleNamespace(
        secrets=SimpleNamespace(get=lambda key: vault.get(key, ""), update=vault.update),
        settings=SimpleNamespace(indexer=SimpleNamespace(url="https://tracker.example")),
        profile_workspace=lambda: SimpleNamespace(refresh=refresh),
    )

    def respond(request):
        calls.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    site = CommunitySite(setup, transport=httpx.MockTransport(respond), clock=lambda: now[0])
    return site, vault, now, calls, replies, refreshes


def admission(**changes):
    return {
        "deviceCode": "d" * 43,
        "userCode": "A1B2C3D4E5",
        "verificationUri": "https://torrentlinker.fr/fr/link",
        "expiresIn": 900,
        "interval": 5,
        **changes,
    }


def token():
    return {"accessToken": "t" * 43, "tokenType": "Bearer", "expiresIn": 7776000}


def test_device_admission_polling_and_secret_storage(linked):
    site, vault, now, calls, replies, refreshes = linked
    replies.append((200, admission()))
    pending = site.start()
    assert refreshes == [("https://tracker.example", "private-indexer-key")]
    body = json.loads(calls[0].content)
    assert body == {
        "identityHash": hashlib.sha256(b"privateperson").hexdigest(),
        "signedIn": True,
        "name": "TorrentLinker",
    }
    assert "PrivatePerson" not in calls[0].content.decode()
    assert "private-indexer-key" not in calls[0].content.decode()
    assert "deviceCode" not in json.dumps(pending)
    assert LINK_SECRET not in vault
    assert site.poll() == pending and len(calls) == 1
    assert site.start() == pending and len(calls) == 1
    now[0] += 5
    replies.append((428, {"error": "pending"}))
    assert site.poll()["pending"]
    now[0] += 5
    replies.append((200, token()))
    state = site.poll()
    assert state["linked"] and not state["pending"]
    assert json.loads(vault[LINK_SECRET])["token"] == "t" * 43
    assert "t" * 43 not in json.dumps(state)
    replies.append(
        (200, {"name": "Public name", "forumAccess": False, "email": "private@example.test"})
    )
    assert site.check()["account"] == {"name": "Public name", "forumAccess": False}
    assert calls[-1].headers["Authorization"] == "Bearer " + "t" * 43
    replies.append((200, {"ok": True}))
    assert not site.disconnect()["linked"]
    assert calls[-1].url.path == "/api/device/revoke" and vault[LINK_SECRET] == ""


def test_fingerprint_canonicalization():
    assert membership_fingerprint(" Ａlice ") == membership_fingerprint("alice")
    assert membership_fingerprint("Straße") == membership_fingerprint("STRASSE")
    with pytest.raises(ValueError):
        membership_fingerprint(" ")


def test_no_attestation_when_profile_authentication_fails(linked):
    site, _vault, _now, calls, _replies, _refreshes = linked

    def fail(*args):
        raise ValueError("private tracker URL and credential")

    site.setup.profile_workspace = lambda: SimpleNamespace(refresh=fail)
    with pytest.raises(ValueError, match="signed-in profile") as failure:
        site.start()
    assert "credential" not in str(failure.value) and not calls


@pytest.mark.parametrize(
    "uri",
    [
        "https://evil.test/fr/link",
        "http://torrentlinker.fr/fr/link",
        "https://torrentlinker.fr/fr/link?secret=1",
    ],
)
def test_only_the_real_site_approval_page_is_returned(linked, uri):
    site, _vault, _now, _calls, replies, _refreshes = linked
    replies.append((200, admission(verificationUri=uri)))
    with pytest.raises(ValueError, match="invalid link"):
        site.start()
    assert not site.state()["pending"]


def test_expiration_backoff_and_revoked_access(linked):
    site, vault, now, calls, replies, _refreshes = linked
    replies.append((200, admission()))
    site.start()
    now[0] += 5
    replies.append((429, {}))
    assert site.poll()["poll_after"] == 60
    now[0] += 6
    site.poll()
    assert len(calls) == 2
    now[0] += 900
    assert not site.poll()["pending"] and len(calls) == 2
    vault[LINK_SECRET] = json.dumps({"token": "t" * 43, "expires": now[0] + 100})
    replies.append((403, {"error": "private response"}))
    with pytest.raises(ValueError, match="unavailable"):
        site.check()
    assert vault[LINK_SECRET] == ""


def test_only_owner_can_access_the_site_link(tmp_path):
    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    with TestClient(app) as browser:
        assert browser.get("/api/community-site").status_code == 401
        login(browser)
        assert browser.get("/api/community-site").json()["linked"] is False
        member(app, "lea")
        sign_in(browser, "lea")
        for path in [
            "/api/community-site",
            "/api/community-site/start",
            "/api/community-site/poll",
            "/api/community-site/check",
            "/api/community-site/disconnect",
        ]:
            response = (
                browser.get(path) if path == "/api/community-site" else browser.post(path, json={})
            )
            assert response.status_code == 403
    assert community_site(setup) is community_site(
        setup.for_client(setup.settings.active_client_id)
    )
