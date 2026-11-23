"""Owner Settings groups shared by the desktop and Web hosts."""

import json

import pytest

from tests.test_web_plan_execution import prepared
from torrentlinker.settings_workspace import SettingsWorkspace


def test_connections_keep_unchanged_secrets_and_validate_the_whole_group(tmp_path, monkeypatch):
    from torrentlinker import net

    monkeypatch.setattr(net, "_internet", None)
    monkeypatch.setattr(net, "_torrent_client", None)
    _, setup, _, _ = prepared(tmp_path)
    setup.secrets.update(
        {"qbit-password": "private-client-password", "tmdb-api-key": "private-tmdb-key"}
    )
    workspace = SettingsWorkspace(setup)
    snapshot = workspace.snapshot()
    assert "private-client-password" not in json.dumps(snapshot)
    assert "private-tmdb-key" not in json.dumps(snapshot)
    assert snapshot["connections"]["secrets"]["tmdb_api_key"] is True
    body = {
        "client": {
            "client": "qbittorrent",
            "host": setup.settings.qbit.host,
            "username": "admin",
            "name": "Studio",
        },
        "indexer": {"url": setup.settings.indexer.url},
        "proxy": {"address": "http://proxy.invalid:1080", "username": "owner"},
        "tmdb_api_key": "replacement-tmdb-key",
        "announce_hosts": ["NEXT.C411.ORG", "tk.c411.tw", "tk.c411.tw"],
    }
    with pytest.raises(ValueError):
        workspace.save("connections", {**body, "proxy": {"address": "invalid"}})
    assert setup.settings.profile().name != "Studio"
    assert setup.secrets.get("tmdb-api-key") == "private-tmdb-key"
    workspace.save("connections", body)
    assert setup.settings.profile().name == "Studio"
    assert setup.secrets.get("qbit-password") == "private-client-password"
    assert setup.secrets.get("indexer-api-key") == "test-key"
    assert setup.secrets.get("tmdb-api-key") == "replacement-tmdb-key"
    assert setup.settings.proxy.username == "owner"
    from torrentlinker.config import Settings

    assert setup.settings.announce_hosts == ["next.c411.org", "tk.c411.tw"]
    assert Settings.load(setup.path).announce_hosts == setup.settings.announce_hosts


def test_client_management_keeps_one_client_and_refuses_pending_work(tmp_path):
    from torrentlinker.catalogue import candidate
    from torrentlinker.download_queue import enqueue

    _, setup, _, rows = prepared(tmp_path)
    workspace = SettingsWorkspace(setup)
    result = workspace.clients("add", {"name": "Seedbox"})
    second = next(client for client in result["clients"] if client["name"] == "Seedbox")
    workspace.clients("default", {"client_id": second["id"]})
    assert workspace.snapshot()["default_client_id"] == second["id"]
    enqueue(
        setup.store, setup.indexer(), candidate(setup.indexer(), rows[0]), tmp_path / "downloads"
    )
    with pytest.raises(ValueError, match="pending work"):
        workspace.clients("remove", {"client_id": "default", "confirmed": True})
    with pytest.raises(ValueError, match="Confirm"):
        workspace.clients("remove", {"client_id": second["id"]})
    result = workspace.clients("remove", {"client_id": second["id"], "confirmed": True})
    assert len(result["clients"]) == 1
    assert result["default_client_id"] == "default"
    with pytest.raises(ValueError, match="at least one"):
        workspace.clients("remove", {"client_id": "default", "confirmed": True})


def test_general_matching_and_zen_are_shared_without_overwriting_client_paths(tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.domain import ContentKind

    _, setup, _, _ = prepared(tmp_path)
    workspace = SettingsWorkspace(setup)
    folder = setup.settings.download_folders.default
    workspace.save(
        "general",
        {
            "language": "fr",
            "theme": "light",
            "media_layout": "focus",
            "media_horizon": "showcase",
            "ui_scale": 1.25,
            "adult_content": True,
        },
    )
    workspace.save(
        "matching",
        {
            "kind_categories": {"ebook": [7000, 7010]},
            "size_tolerance": 0.03,
            "min_partial_coverage": 0.9,
            "ignore_patterns": ["*.nfo"],
            "plan_exclusions": ["sample"],
        },
    )
    workspace.save(
        "zen",
        {
            "zen_class": "swarm-keeper",
            "tree_bonus": 0.05,
            "badge_bonus": 0.15,
            "seed_hours": 12,
            "torrent_cap": 100,
            "free_space_margin": 0.2,
        },
    )
    with pytest.raises(ValueError):
        workspace.save("general", {"language": "fr", "theme": "unknown"})
    saved = Settings.load(setup.path)
    assert (saved.language, saved.theme, saved.media_layout) == ("fr", "light", "focus")
    assert saved.media_horizon == "showcase"
    assert saved.kind_categories[ContentKind.EBOOK] == [7000, 7010]
    assert saved.matching.ignore_patterns == ["*.nfo"]
    assert saved.zen.seed_hours == 12
    assert saved.zen.badge_bonus == 0.15
    assert saved.free_space_margin == 0.2
    assert saved.download_folders.default == folder


def test_storage_edits_retain_root_and_removal_guards(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    workspace = SettingsWorkspace(setup)
    folder = setup.roots[0] / "library"
    folder.mkdir()
    result = workspace.storage("save", {"local": str(folder), "kind": "ebook", "depth": 0})
    assert any(row["local"] == str(folder) for row in result["storage"]["folders"])
    with pytest.raises(ValueError, match="Confirm"):
        workspace.storage("remove", {"local": str(folder)})
    outside = tmp_path.parent / "outside-settings-root"
    outside.mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="outside"):
        workspace.storage("save", {"local": str(outside)})
    result = workspace.storage("remove", {"local": str(folder), "confirmed": True})
    assert not any(row["local"] == str(folder) for row in result["storage"]["folders"])
    assert folder.is_dir()


def test_connection_write_failure_restores_keys_and_settings(tmp_path, monkeypatch):
    _, setup, _, _ = prepared(tmp_path)
    workspace = SettingsWorkspace(setup)
    setup.secrets.update({"tmdb-api-key": "original-key"})
    original = setup.settings
    body = workspace.snapshot()["connections"]
    body.pop("secrets")
    body.pop("managed_secrets")
    body["tmdb_api_key"] = "replacement-key"
    body["client"]["name"] = "Unsaved name"

    def fail():
        raise OSError("disk is full")

    monkeypatch.setattr(setup, "save", fail)
    with pytest.raises(OSError, match="disk is full"):
        workspace.save("connections", body)
    assert setup.settings is original
    assert setup.secrets.get("tmdb-api-key") == "original-key"


def test_desktop_extra_keys_keep_existing_keyring_names():
    from torrentlinker.agent.desktop import KeyringSecrets
    from torrentlinker.credentials import get_secret, set_secret

    set_secret("indexer-api-key-2", "existing-extra")
    secrets = KeyringSecrets()
    assert secrets.get("indexer-extra-key-1") == "existing-extra"
    secrets.update({"indexer-extra-key-1": "replacement-extra"})
    assert get_secret("indexer-api-key-2") == "replacement-extra"
    assert "replacement-extra" not in secrets.redact("key replacement-extra")


def test_proxy_test_uses_draft_without_saving_credentials(tmp_path, monkeypatch):
    from torrentlinker import net

    _, setup, _, _ = prepared(tmp_path)
    setup.secrets.update({"proxy-password": "saved-password"})
    seen = []
    monkeypatch.setattr(net, "address_seen", lambda proxy: seen.append(proxy) or "192.0.2.4")
    result = SettingsWorkspace(setup).test_connection(
        "proxy",
        {"address": "http://proxy.example:8080", "username": "owner", "password": "draft-password"},
    )
    assert result["ip"] == "192.0.2.4"
    assert "draft-password" in seen[0]
    assert "draft-password" not in json.dumps(result)
    assert setup.secrets.get("proxy-password") == "saved-password"


def test_mapping_edit_replaces_both_paths_and_rolls_back_failed_persistence(tmp_path, monkeypatch):
    from torrentlinker.domain import PathMapping

    _, setup, _, _ = prepared(tmp_path)
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    setup.roots = (tmp_path,)
    setup.settings.path_mappings = [PathMapping(str(old), "/old")]
    monkeypatch.setattr(setup, "folder", lambda *args, **kwargs: {"verification": "existing-file"})
    workspace = SettingsWorkspace(setup)
    body = {
        "local": str(new),
        "client_path": "/new",
        "original_local": str(old),
        "original_client_path": "/old",
    }
    save = setup.save
    monkeypatch.setattr(setup, "save", lambda: (_ for _ in ()).throw(OSError("Disk full")))
    with pytest.raises(OSError, match="Disk full"):
        workspace.storage("mapping", body)
    assert setup.settings.path_mappings == [PathMapping(str(old), "/old")]
    monkeypatch.setattr(setup, "save", save)
    workspace.storage("mapping", body)
    assert setup.settings.path_mappings == [PathMapping(str(new), "/new")]


@pytest.mark.parametrize("failed", [False, True])
def test_first_run_validates_through_draft_proxy_and_restores_it_on_failure(
    tmp_path, monkeypatch, failed
):
    from torrentlinker import net

    _, setup, _, _ = prepared(tmp_path)
    setup.configured = False
    monkeypatch.setattr(net, "_internet", None)
    monkeypatch.setattr(net, "_torrent_client", None)
    proxy = "http://owner:secret@proxy.test:1080"

    def check(value):
        assert net.current() == (proxy, proxy)
        if failed:
            raise ValueError("Cannot connect")
        return {"version": "fixture"}

    monkeypatch.setattr(setup, "test_client", check)
    workspace = SettingsWorkspace(setup)
    body = workspace.snapshot()["connections"]
    del body["secrets"]
    del body["managed_secrets"]
    body["proxy"] = {
        "address": "http://proxy.test:1080",
        "username": "owner",
        "password": "secret",
        "torrent_client": True,
    }
    if failed:
        with pytest.raises(ValueError, match="Cannot connect"):
            workspace.save("connections", body)
        assert net.current() == (None, None)
        assert not setup.configured
        assert setup.secrets.get("proxy-password") == ""
    else:
        workspace.save("connections", body)
        assert setup.configured
        assert net.current() == (proxy, proxy)


def test_reseed_layout_is_saved_per_client_and_forced_for_disk_rename_clients(tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.reseed_layout import effective_layout

    _, setup, _, _ = prepared(tmp_path)
    workspace = SettingsWorkspace(setup)
    added = workspace.clients("add", {"name": "Second"})
    second = next(client["id"] for client in added["clients"] if client["name"] == "Second")
    body = workspace.snapshot()["connections"]
    body.pop("secrets")
    body.pop("managed_secrets")
    body["reseed_layout"] = "links"
    body["reseed_link_root"] = str(setup.roots[0])
    workspace.save("connections", body)
    restored = Settings.load(setup.path)
    assert restored.profile().reseed_layout == "links"
    assert restored.profile(second).reseed_layout == "auto"
    body["reseed_layout"] = "client"
    body["client"]["client"] = "rtorrent"
    body["client"]["host"] = "http://127.0.0.1:8080/RPC2"
    workspace.save("connections", body)
    assert effective_layout(setup.settings.profile()) == "links"


def test_release_score_profiles_persist_validate_and_reset(tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.release_score import PROFILES

    _, setup, _, _ = prepared(tmp_path)
    workspace = SettingsWorkspace(setup)
    data = workspace.snapshot()["release_score"]
    data["profiles"]["Cinema"] = {**data["profiles"]["4KLight"], "poidsAudio": 30}
    data["active"] = "Cinema"
    data["equipment"]["dv"] = "oui"
    workspace.save("release_score", data)
    assert Settings.load(setup.path).release_score == data
    data["profiles"]["Cinema"]["poidsAudio"] = 500
    with pytest.raises(ValueError):
        workspace.save("release_score", data)
    assert setup.settings.release_score["profiles"]["Cinema"]["poidsAudio"] == 30
    data = workspace.snapshot()["release_score"]
    data["profiles"]["HDLight 1080p"] = PROFILES["HDLight 1080p"]
    del data["profiles"]["Cinema"]
    data["active"] = "HDLight 1080p"
    workspace.save("release_score", data)
    assert "Cinema" not in Settings.load(setup.path).release_score["profiles"]
