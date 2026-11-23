"""Site consent and requests use a fake HTTP transport, never real credentials."""

import json
from types import SimpleNamespace

import httpx
import pytest

from torrentlinker.achievement_sync import AchievementSync
from torrentlinker.community_site import LINK_SECRET, CommunitySite


def linked(tmp_path):
    vault = {LINK_SECRET: json.dumps({"token": "original-token", "expires": 9999999999})}
    calls = []
    remote = {
        "sharing": True,
        "consentEpoch": "one",
        "accountId": "account-a",
        "installationId": "install-a",
        "definitionVersion": 1,
    }

    def respond(request):
        calls.append(request)
        if request.url.path == "/api/device/capability":
            return httpx.Response(
                200,
                json={
                    **remote,
                    "accessToken": "scoped-token",
                    "tokenType": "Bearer",
                    "permissions": json.loads(request.content)["permissions"],
                    "expiresAt": "2090-01-01T00:00:00Z",
                },
            )
        if request.method == "POST" and request.url.path == "/api/app-achievements":
            body = json.loads(request.content)
            return httpx.Response(
                200 if body["consentEpoch"] == remote["consentEpoch"] else 409, json={"ok": True}
            )
        return httpx.Response(200, json=remote)

    setup = SimpleNamespace(
        path=tmp_path / "settings.json",
        secrets=SimpleNamespace(get=lambda k: vault.get(k, ""), update=vault.update),
    )
    site = CommunitySite(setup, transport=httpx.MockTransport(respond))
    return AchievementSync(site), remote, calls, vault


def test_future_existing_and_disabled_consent(tmp_path):
    sync, remote, calls, _ = linked(tmp_path)
    sync.ledger.complete("owner", "playlist", "private-playlist")
    sync.tick()
    assert calls == []
    sync.enable()
    assert not sync.ledger.pending("owner")
    sync.ledger.complete("owner", "studio", "private-render")
    sync.tick()
    posts = [r for r in calls if r.method == "POST" and r.url.path == "/api/app-achievements"]
    assert len(posts) == 1
    assert json.loads(posts[0].content) == {
        "consentEpoch": "one",
        "achievements": [{"code": "studio-first", "definitionVersion": 1}],
    }
    assert posts[0].headers["Authorization"] == "Bearer scoped-token"
    assert "private-" not in posts[0].content.decode()
    sync.share_existing()
    assert {a["code"] for a in sync.ledger.pending("owner")} == {"playlist-first", "studio-first"}
    sync.disable()
    before = len(calls)
    sync.tick()
    assert len(calls) == before
    assert sync.ledger.pending("owner") == []
    sync.close()


def test_remote_epoch_change_and_account_change_discard_queue(tmp_path):
    sync, remote, calls, vault = linked(tmp_path)
    sync.enable()
    sync.ledger.complete("owner", "playlist", "one")
    remote["consentEpoch"] = "two"
    sync.tick()
    assert not sync.state()["sharing"] and not sync.ledger.pending("owner")
    assert not any(r.url.path == "/api/app-achievements" and r.method == "POST" for r in calls)
    sync.enable()
    sync.ledger.complete("owner", "rss", "one")
    vault[LINK_SECRET] = json.dumps({"token": "different-account-token", "expires": 9999999999})
    before = len(calls)
    sync.tick()
    assert len(calls) == before
    assert not sync.state()["sharing"]
    remote["accountId"] = "account-b"
    sync.enable()
    assert sync.state()["achievements"] == []
    sync.close()


def test_site_denial_and_expired_token_do_not_create_consent(tmp_path):
    sync, remote, calls, vault = linked(tmp_path)
    remote["sharing"] = False
    with pytest.raises(ValueError):
        sync.enable()
    assert not sync.state()["sharing"]
    vault[LINK_SECRET] = ""
    with pytest.raises(ValueError):
        sync.enable()
    sync.close()


def test_backup_merge_never_restores_consent_and_rejects_unknown_pages_atomically(tmp_path):
    import copy

    sync, _, _, _ = linked(tmp_path)
    sync.enable()
    sync.ledger.complete("owner", "playlist", "private-playlist")
    document = sync.backup()
    assert set(document) == {"schemaVersion", "accountId", "pages"}
    assert not any(
        word in json.dumps(document)
        for word in ("private-playlist", "scoped-token", "privateKey", "consentEpoch")
    )
    sync.ledger.reset("owner")
    invalid = copy.deepcopy(document)
    invalid["pages"].append({"schemaVersion": 2, "accountId": "account-a", "events": []})
    with pytest.raises(ValueError):
        sync.restore(invalid)
    assert sync.state()["achievements"] == []
    sync.restore(document)
    sync.restore(document)
    assert len(sync.state()["achievements"]) == 1
    assert not sync.state()["sharing"] and sync.state()["pending"] == 0
    sync.close()


def test_shared_http_routes_reject_unauthenticated_and_member_claims(tmp_path):
    from fastapi.testclient import TestClient

    from tests.test_members_signin import member, sign_in
    from tests.test_web_jobs import login
    from tests.test_web_plan_execution import prepared
    from torrentlinker.web.app import create_app

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        assert browser.post("/api/community-site/achievements-state", json={}).status_code == 401
        login(browser)
        assert browser.post("/api/community-site/achievements-state", json={}).status_code == 200
        assert (
            browser.post(
                "/api/community-site/achievements-claim", json={"code": "reseed-100"}
            ).status_code
            == 400
        )
        member(app, "lea")
        sign_in(browser, "lea")
        for action in ("state", "enable", "restore", "pair-add", "backup", "reset"):
            assert (
                browser.post("/api/community-site/achievements-" + action, json={}).status_code
                == 403
            )


def test_new_account_cannot_scan_previous_accounts_legacy_history(tmp_path):
    from torrentlinker.achievement_history import recover

    sync, remote, _, vault = linked(tmp_path)
    sync.identity()
    sync.ledger.complete("owner", "playlist", "alice")
    vault[LINK_SECRET] = json.dumps({"token": "bob-token", "expires": 9999999999})
    remote["accountId"] = "account-b"
    assert sync.state()["achievements"] == []
    sync.request("state", {})
    assert sync.state()["account"] == "account-b"
    client = SimpleNamespace(
        torrents=lambda **kw: [SimpleNamespace(hash="a" * 40, state="uploading", progress=1)]
    )
    agent = SimpleNamespace(
        setup=SimpleNamespace(
            settings=SimpleNamespace(client_profiles=[SimpleNamespace(id="default", enabled=True)]),
            for_client=lambda _: SimpleNamespace(client=lambda: client),
        )
    )
    result = recover(sync, agent)
    assert result["historicalPlaylistsSkipped"] is True
    assert result["playlistsRecovered"] == 0 and result["seedingObserved"] == 1
    assert [a["code"] for a in sync.state()["achievements"]] == ["already-seeding"]
    sync.close()
