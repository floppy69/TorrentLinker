"""Opt-in app/site contract on the disposable LOCAL website, never production."""

import hashlib
import json
import os
import secrets
import subprocess
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TL_ACHIEVEMENT_SITE"), reason="isolated site contract only"
)


def test_actual_site_consent_capabilities_peer_proofs_and_revocation(tmp_path, monkeypatch):
    import torrentlinker.achievement_sync as sync_module
    import torrentlinker.community_site as site_module
    from torrentlinker.achievement_peers import PeerExchange

    base = os.environ["TL_ACHIEVEMENT_SITE"]
    url = urlsplit(base)
    assert url.scheme == "http" and url.hostname == "localhost" and url.port == 3192
    container = "torrentlinker-site-db-1"
    label = subprocess.check_output(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "com.docker.compose.project"}}',
            container,
        ],
        text=True,
    ).strip()
    assert label == "torrentlinker-site"

    def sql(statement):
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-U",
                "site",
                "-d",
                "site",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input=statement,
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise AssertionError("Isolated database fixture operation failed")
        return result.stdout.strip()

    user = "app-achievement-test-" + str(uuid4())
    tokens = [secrets.token_urlsafe(32) for _ in range(2)]
    ids = [str(uuid4()) for _ in tokens]
    monkeypatch.setattr(site_module, "SITE_URL", base)
    monkeypatch.setattr(sync_module, "SITE_URL", base)
    services = []
    try:
        sql(f"""INSERT INTO "user"(id,name,email,"emailVerified","createdAt",
        "updatedAt",role,"forumAccess",banned)
        VALUES('{user}','Disposable app fixture','{user}@example.invalid',
        true,now(),now(),'member',true,false);""")
        for i, token in enumerate(tokens):
            digest = hashlib.sha256(token.encode()).hexdigest()
            sql(
                "INSERT INTO app_tokens(id,user_id,token_hash,name,expires) "
                f"VALUES('{ids[i]}','{user}','{digest}',"
                "'Disposable app fixture',now()+interval '1 hour');"
            )
            vault = {site_module.LINK_SECRET: json.dumps({"token": token, "expires": 9999999999})}
            setup = SimpleNamespace(
                path=tmp_path / str(i) / "settings.json",
                secrets=SimpleNamespace(get=lambda k, v=vault: v.get(k, ""), update=vault.update),
            )
            services.append(sync_module.AchievementSync(site_module.CommunitySite(setup)))
        a, b = services
        with pytest.raises(ValueError, match="Enable app badge sharing"):
            a.enable()
        a.site._json(
            a.site._request(
                "POST",
                "/api/community",
                authenticated=True,
                json={"action": "sharing", "enabled": True, "hideExisting": False},
            )
        )
        a.ledger.complete("owner", "playlist", "old-private-evidence")
        a.enable()
        a.ledger.complete("owner", "studio", "new-private-evidence")
        a.tick()
        assert sql(f"SELECT code FROM app_achievements WHERE user_id='{user}'") == "studio-first"
        a.site._json(
            a.site._request(
                "POST",
                "/api/community",
                authenticated=True,
                json={"action": "pairing", "enabled": True},
            )
        )
        a.request("pair-enable", {})
        b.request("pair-enable", {})
        pa, pb = PeerExchange(a), PeerExchange(b)
        ai = pa.invitation("https://127.0.0.1:0")
        bi = pb.invitation("https://127.0.0.1:0")
        pa.add(bi)
        pb.add(ai)
        pa.start("127.0.0.1", 0)
        pb.start("127.0.0.1", 0)
        a.config["peers"][0]["endpoint"] = f"https://127.0.0.1:{pb.server.server_port}"
        b.config["peers"][0]["endpoint"] = f"https://127.0.0.1:{pa.server.server_port}"
        b.ledger.complete("owner", "rss", "peer-private-evidence")
        pa.synchronize()
        assert pa.state()[0]["status"] == "synced"
        assert {r["code"] for r in a.state()["achievements"]} == {
            "playlist-first",
            "studio-first",
            "rss-first",
        }
        assert {r["code"] for r in b.state()["achievements"]} == {
            "playlist-first",
            "studio-first",
            "rss-first",
        }
        a.site._json(
            a.site._request(
                "POST",
                "/api/community",
                authenticated=True,
                json={"action": "sharing", "enabled": False, "hideExisting": True},
            )
        )
        a.tick()
        assert not a.state()["sharing"] and a.state()["pending"] == 0
        a.site._json(a.site._request("POST", "/api/device/revoke", authenticated=True, json={}))
        pa.synchronize()
        assert pa.state()[0]["status"] == "offline"
        assert a.state()["account"] == ""
        # Revocation quarantines the collection; durable account-owned evidence remains.
        assert a.ledger.db.execute("SELECT count(*) FROM awards").fetchone()[0] == 3
    finally:
        for service in services:
            service.close()
        sql(f"""DELETE FROM "user" WHERE id='{user}';""")
