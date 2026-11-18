import io
import json
import zipfile

import httpx

from tests.test_web_profile import ORIGIN, prepared, snapshot
from torrentlinker.companion import CompanionReceiver, extension_zip


def test_real_loopback_receiver_pairs_and_receives_without_owner_http_controls(
    tmp_path, monkeypatch
):
    _, setup = prepared(tmp_path, monkeypatch)
    workspace = setup.profile_workspace()
    workspace.refresh(setup.settings.indexer.url, "fake-key")
    code = workspace.pairing()["code"]
    receiver = CompanionReceiver(
        workspace, lambda: (setup.settings.indexer.url, "fake-key"), port=0
    )
    try:
        with httpx.Client(base_url=receiver.address, trust_env=False) as extension:
            assert extension.post("/api/zen/profile/pairing", json={}).status_code == 403
            assert extension.options("/api/companion/pair").status_code == 403
            ext = {"Origin": ORIGIN}
            assert extension.options("/api/companion/pair", headers=ext).status_code == 204
            pair = extension.post(
                "/api/companion/pair", headers=ext, json={"code": code, "accountId": "42"}
            )
            assert pair.status_code == 200
            ext["Authorization"] = "Bearer " + pair.json()["token"]
            assert (
                extension.post("/api/companion/snapshot", headers=ext, json=snapshot()).status_code
                == 200
            )
            assert workspace.state()["companion"]["activeSeeds"]["total"] == 42
            assert (
                extension.post(
                    "/api/companion/snapshot", headers={**ext, "Host": "evil.test"}, json=snapshot()
                ).status_code
                == 403
            )
            assert (
                extension.post("/api/companion/disconnect", headers=ext, json={}).status_code == 200
            )
            assert workspace.state()["companion"] is None
    finally:
        receiver.stop()


def test_extension_bundle_is_installable_and_contains_only_packaged_assets():
    with zipfile.ZipFile(io.BytesIO(extension_zip())) as bundle:
        manifest = json.loads(bundle.read("torrentlinker-companion/manifest.json"))
        assert manifest["manifest_version"] == 3
        assert set(manifest["permissions"]) == {"scripting", "storage", "alarms"}
        assert "https://*/*" not in manifest["host_permissions"]
        assert "https://*/*" not in manifest["externally_connectable"]["matches"]
        assert set(bundle.namelist()) == {
            f"torrentlinker-companion/{name}"
            for name in (
                "manifest.json",
                "background.js",
                "collect.js",
                "descriptor.js",
                "community.js",
                "companion.js",
                "companion.html",
                "style.css",
                "receiver.json",
            )
        }
    with zipfile.ZipFile(io.BytesIO(extension_zip("https://nas.example/torrentlinker/"))) as bundle:
        manifest = json.loads(bundle.read("torrentlinker-companion/manifest.json"))
        assert "https://nas.example/*" in manifest["host_permissions"]
        assert manifest["externally_connectable"]["matches"][-1] == "https://nas.example/*"
        assert json.loads(bundle.read("torrentlinker-companion/receiver.json")) == {
            "webTarget": "https://nas.example/torrentlinker"
        }
