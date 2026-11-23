"""The Settings eye: revealing one saved secret, and editing additional API keys one by one."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_members_signin import member, sign_in
from tests.test_members_viewers import FAMILY, screen_sign_in
from tests.test_web_jobs import Client, login
from tests.test_web_plan_execution import prepared
from torrentlinker.accounts import Permission
from torrentlinker.settings_workspace import SettingsWorkspace
from torrentlinker.web.app import create_app


def connections_body(setup, **indexer):
    return {
        "client": {
            "client": "qbittorrent",
            "host": setup.settings.qbit.host,
            "username": "admin",
            "name": "Studio",
        },
        "indexer": {"url": setup.settings.indexer.url, **indexer},
        "proxy": {"address": "", "username": ""},
    }


def test_reveal_returns_only_the_one_secret_asked_for(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    setup.secrets.update(
        {
            "tmdb-api-key": "tmdb-secret",
            "qbit-password": "client-secret",
            "indexer-extra-key-2": "second-extra",
            "indexer-key-lyra": "lyra-secret",
            "assistant:brave": "brave-secret",
        }
    )
    workspace = SettingsWorkspace(setup)
    assert workspace.reveal("tmdb-api-key") == "tmdb-secret"
    assert workspace.reveal("client-password") == "client-secret"
    assert workspace.reveal("indexer-api-key") == "test-key"
    assert workspace.reveal("extra-key:2") == "second-extra"
    assert workspace.reveal("indexer:lyra") == "lyra-secret"
    assert workspace.reveal("assistant-brave") == "brave-secret"
    assert workspace.reveal("proxy-password") == ""
    for unknown in ("extra-key:5", "indexer:../x", "credentials", "", "assistant:"):
        with pytest.raises(ValueError, match="Unknown secret"):
            workspace.reveal(unknown)
    assert "tmdb-secret" not in json.dumps(workspace.snapshot())


def test_a_managed_secret_is_never_revealed(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    file = tmp_path / "tmdb"
    file.write_text("deployment-secret")
    setup.secrets.files["tmdb-api-key"] = file
    with pytest.raises(ValueError, match="managed by the deployment"):
        SettingsWorkspace(setup).reveal("tmdb-api-key")


@pytest.fixture
def server(tmp_path):
    config, setup, _, _ = prepared(tmp_path)
    setup.secrets.update({"tmdb-api-key": "tmdb-secret"})
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        connector=lambda *args: Client(),
    )
    with TestClient(app) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        yield app, browser, setup


def test_the_reveal_route_is_the_owners_and_never_cached(server):
    _, browser, setup = server
    login(browser)
    shown = browser.post("/api/settings/reveal", json={"secret": "tmdb-api-key"})
    assert shown.status_code == 200 and shown.json() == {"value": "tmdb-secret"}
    assert shown.headers["Cache-Control"] == "no-store"
    assert "tmdb-secret" not in browser.get("/api/settings").text
    assert browser.post("/api/settings/reveal", json={"secret": "nope"}).status_code >= 400
    file = setup.secrets.files
    file["tmdb-api-key"] = setup.path.parent / "managed"
    (setup.path.parent / "managed").write_text("deployment-secret")
    refused = browser.post("/api/settings/reveal", json={"secret": "tmdb-api-key"})
    assert refused.status_code >= 400 and "deployment-secret" not in refused.text
    file.clear()


def test_a_member_and_a_viewer_cannot_reveal(server):
    app, browser, _ = server
    lea = member(app, "lea", *FAMILY)
    assert sign_in(browser, "lea").status_code == 200
    assert browser.post("/api/settings/reveal", json={"secret": "tmdb-api-key"}).status_code == 403
    app.state.accounts.set_pin(lea, "", "2468")
    hugo = app.state.accounts.add_viewer(lea, "Hugo", {Permission.FILMS}, 1)
    assert screen_sign_in(browser).status_code == 200
    assert browser.post("/api/screen/choose", json={"viewer": hugo}).status_code == 200
    assert browser.post("/api/settings/reveal", json={"secret": "tmdb-api-key"}).status_code == 403


def test_editing_one_extra_key_keeps_the_others_and_removing_one_removes_only_it(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    setup.secrets.update({f"indexer-extra-key-{i}": f"extra-{i}" for i in range(1, 5)})
    workspace = SettingsWorkspace(setup)
    assert workspace.snapshot()["connections"]["secrets"]["extra_key_slots"] == [1, 2, 3, 4]
    keep = lambda *slots: [{"keep": slot} for slot in slots]  # noqa: E731
    # Edit the second key only: the page never read the others.
    workspace.save(
        "connections",
        connections_body(setup, extra_keys=[*keep(1), "edited-2", *keep(3, 4)]),
    )
    assert setup.extra_indexer_keys() == ["extra-1", "edited-2", "extra-3", "extra-4"]
    # Remove the first: the rest move up and the last slot empties.
    workspace.save("connections", connections_body(setup, extra_keys=keep(2, 3, 4)))
    assert setup.extra_indexer_keys() == ["edited-2", "extra-3", "extra-4"]
    assert setup.secrets.get("indexer-extra-key-4") == ""
    # Add one beside the saved ones.
    workspace.save("connections", connections_body(setup, extra_keys=[*keep(1, 2, 3), "added"]))
    assert setup.extra_indexer_keys() == ["edited-2", "extra-3", "extra-4", "added"]
    # A save that does not mention the keys leaves them all.
    workspace.save("connections", connections_body(setup))
    assert len(setup.extra_indexer_keys()) == 4
    # Removing them all is explicit: an empty list.
    workspace.save("connections", connections_body(setup, extra_keys=[]))
    assert setup.extra_indexer_keys() == []
    assert setup.secrets.get("indexer-api-key") == "test-key"


def test_desktop_extra_keys_keep_their_keyring_slots_when_edited_one_by_one(monkeypatch):
    from torrentlinker.agent import desktop

    store = {"indexer-api-key-2": "one", "indexer-api-key-3": "two"}
    monkeypatch.setattr(desktop, "get_secret", lambda name: store.get(name, ""))
    monkeypatch.setattr(desktop, "set_secret", lambda name, value: store.__setitem__(name, value))
    secrets = desktop.KeyringSecrets()
    assert secrets.get("indexer-extra-key-2") == "two"
    secrets.update({"indexer-extra-key-1": "one", "indexer-extra-key-2": ""})
    assert store["indexer-api-key-2"] == "one" and store["indexer-api-key-3"] == ""
