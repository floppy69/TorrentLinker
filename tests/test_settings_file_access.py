"""Settings and Transfers share saved file access without exposing its credentials."""

import json

import asyncssh
import pytest
from fastapi.testclient import TestClient

from tests.test_web_jobs import login
from tests.test_web_plan_execution import prepared
from torrentlinker.remote_access import RemoteAccess
from torrentlinker.settings_workspace import SettingsWorkspace
from torrentlinker.web.app import create_app


def access_body():
    return {
        "config": {
            "host": "seedbox.invalid",
            "port": 2222,
            "username": "seed",
            "auth": "password",
            "client_root": "/downloads",
            "file_root": "/files",
        },
        "credential": "private-sftp-password",
        "host_key": asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode(),
    }


def test_settings_access_reuses_transfer_service_and_removal_is_explicit(tmp_path):
    config, setup, _, _ = prepared(tmp_path)
    setup.secrets.update({"qbit-password": "private-api-password"})
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with TestClient(app) as browser:
        url = "/api/settings/file-access/"
        assert browser.post(url + "snapshot", json={}).status_code == 403
        browser.headers["X-TorrentLinker"] = "1"
        assert browser.post(url + "snapshot", json={}).status_code == 401
        login(browser)

        def post(action, value=None):
            return browser.post(url + action, json={"client_id": "default", "value": value or {}})

        assert post("snapshot").json()["configured"] is False
        body = access_body()
        response = post("save", body)
        assert response.status_code == 200, response.text
        assert response.json()["has_credential"]
        assert body["credential"] not in response.text
        workspace = app.state.agent_service.torrents_workspace
        options = workspace.request("transfer-options", {"items": []})
        assert options["clients"][0]["access"]["host"] == "seedbox.invalid"
        assert setup.secrets.get("qbit-password") == "private-api-password"
        assert "private-sftp-password" not in json.dumps(SettingsWorkspace(setup).snapshot())
        assert post("remove").status_code == 400
        workspace.transfers.running.add("fixture-running-transfer")
        try:
            assert post("remove", {"confirmed": True}).status_code == 400
            assert post("save", body).status_code == 400
            assert post("snapshot").json()["busy"]
        finally:
            workspace.transfers.running.clear()
        setup.settings.profile().enabled = False
        assert not post("snapshot").json()["enabled"]
        assert post("check").status_code == 400
        assert post("remove", {"confirmed": True}).status_code == 200
        assert not post("snapshot").json()["configured"]
        assert not setup.secrets.get(RemoteAccess.secret_name("default"))
        assert setup.secrets.get("qbit-password") == "private-api-password"
        assert post("unknown").status_code == 400
        assert browser.post(url + "snapshot", json={"client_id": "missing"}).status_code == 400
        assert browser.post(url + "save", json={"value": []}).status_code == 400


def test_removing_client_requires_removing_its_file_access_first(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    settings = SettingsWorkspace(setup)
    result = settings.clients("add", {"name": "Seedbox"})
    identifier = next(c["id"] for c in result["clients"] if c["name"] == "Seedbox")
    access = RemoteAccess(setup.path.parent / "transfer-access", setup.secrets)
    body = access_body()
    try:
        access.save(identifier, body["config"], body["credential"], body["host_key"])
        with pytest.raises(ValueError, match="remote file access"):
            settings.clients("remove", {"client_id": identifier, "confirmed": True})
        access.remove(identifier)
        settings.clients("remove", {"client_id": identifier, "confirmed": True})
    finally:
        access.close()


def test_remove_failure_restores_saved_access_and_invalidates_checks(tmp_path, monkeypatch):
    _, setup, _, _ = prepared(tmp_path)
    access = RemoteAccess(setup.path.parent / "transfer-access", setup.secrets)
    body = access_body()
    try:
        access.save("default", body["config"], body["credential"], body["host_key"])
        access.checked.add("default")
        previous = access.path.read_bytes()

        def reject(_):
            raise OSError("Secret store unavailable")

        monkeypatch.setattr(setup.secrets, "update", reject)
        with pytest.raises(OSError, match="Secret store"):
            access.remove("default")
        assert access.path.read_bytes() == previous
        assert access.snapshot("default")["configured"]
        assert not access.snapshot("default")["checked"]
    finally:
        access.close()


def test_client_removal_cannot_race_file_access_save(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    config, setup, _, _ = prepared(tmp_path)
    settings = SettingsWorkspace(setup)
    result = settings.clients("add", {"name": "Seedbox"})
    identifier = next(c["id"] for c in result["clients"] if c["name"] == "Seedbox")
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    workspace = app.state.agent_service.torrents_workspace
    started, release, removing = threading.Event(), threading.Event(), threading.Event()
    save = workspace.remote.save

    def paused_save(*args):
        started.set()
        assert release.wait(5)
        return save(*args)

    monkeypatch.setattr(workspace.remote, "save", paused_save)

    def remove():
        removing.set()
        return settings.clients("remove", {"client_id": identifier, "confirmed": True})

    try:
        with ThreadPoolExecutor(2) as pool:
            saving = pool.submit(
                workspace.request,
                "transfer-access-save",
                {"client_id": identifier, **access_body()},
            )
            assert started.wait(5)
            removal = pool.submit(remove)
            assert removing.wait(5)
            try:
                assert not removal.done()
            finally:
                release.set()
            assert saving.result(5)["configured"]
            with pytest.raises(ValueError, match="remote file access"):
                removal.result(5)
        assert setup.settings.profile(identifier).id == identifier
    finally:
        release.set()
        workspace.remote.close()
