"""Real SFTP on disposable internal Docker networks. No user credentials or files."""

import json
import os
import subprocess
import time
import uuid
from contextlib import contextmanager

import pytest

from tests.shell_support import shell_navigate
from tests.test_multi_client_docker import docker
from torrentlinker.remote_access import RemoteAccess
from torrentlinker.web.security import ServerSecrets

pytest_plugins = ["tests.test_multi_client_docker", "tests.test_enqueue_destinations"]

pytestmark = pytest.mark.skipif(
    os.getenv("TL_SEEDBOX_DOCKER") != "1", reason="set TL_SEEDBOX_DOCKER=1"
)


@contextmanager
def sftp_endpoint(data, client_root="/data", sftp_options="", authorized_key=""):
    from pathlib import Path

    network = "tl-seedbox-" + uuid.uuid4().hex[:10]
    data.mkdir(mode=0o777, exist_ok=True)
    data.chmod(0o777)
    (data / "films").mkdir(mode=0o777, exist_ok=True)
    (data / "films").chmod(0o777)
    sshdir = data.parent / (network + "-ssh")
    sshdir.mkdir(mode=0o755)
    (sshdir / "authorized_keys").write_text(authorized_key)
    (sshdir / "authorized_keys").chmod(0o644)
    sshconfig = data.parent / (network + ".conf")
    sshconfig.write_text(
        Path("tests/docker/seedbox/sshd_config")
        .read_text()
        .replace("internal-sftp", "internal-sftp " + sftp_options)
    )
    docker("network", "create", "--internal", network)
    try:
        docker(
            "run",
            "-d",
            "--name",
            network,
            "--network",
            network,
            "-v",
            f"{sshdir}:/home/seed/.ssh:ro",
            "-v",
            f"{sshconfig}:/etc/ssh/sshd_config:ro",
            "-v",
            f"{data}:/files",
            "torrentlinker-sftp-test:118",
        )
        address = json.loads(
            docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", network)
        )[network]["IPAddress"]
        import socket

        for _attempt in range(50):
            try:
                with socket.create_connection((address, 2222), timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        yield (
            {
                "host": address,
                "port": 2222,
                "username": "seed",
                "auth": "password",
                "client_root": client_root,
                "file_root": "/files",
            },
            data,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", network], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


def open_seedbox_browser(page, url, errors):
    """Docker network creation can cancel Chromium's initial asset requests."""
    network_changes = []

    def failed(request):
        if request.failure == "net::ERR_NETWORK_CHANGED":
            network_changes.append(request.url)

    page.on("requestfailed", failed)
    try:
        for _ in range(3):
            network_changes.clear()
            errors.clear()
            page.goto(url)
            if not network_changes:
                return
        pytest.fail("Docker network changes repeatedly interrupted browser startup")
    finally:
        page.remove_listener("requestfailed", failed)


@pytest.fixture
def seedbox(tmp_path, request):
    cluster = request.getfixturevalue("cluster") if "cluster" in request.fixturenames else None
    data = cluster.folder("qbit-b") if cluster else tmp_path / "files"
    with sftp_endpoint(data, "/data" if cluster else "/downloads") as endpoint:
        yield endpoint


def test_remote_access_requires_identity_confirmation_and_keeps_credentials_private(
    seedbox, tmp_path
):
    config, data = seedbox
    service = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
    for _attempt in range(30):
        try:
            identity = service.discover(config)
            break
        except OSError:
            time.sleep(0.2)
    else:
        pytest.fail("Disposable SSH server did not start")
    assert identity["fingerprint"].startswith("SHA256:")
    with pytest.raises(ValueError, match="identity"):
        service.save("seedbox", config, "disposable-test-password", "")
    service.save("seedbox", config, "disposable-test-password", identity["host_key"])
    checked = service.check("seedbox")
    assert checked["checked"] is True
    assert checked["free_bytes"] > 0
    assert "/downloads/films" in service.browse("seedbox", "/downloads")["folders"]
    from pathlib import PureWindowsPath

    # Client adapters use pathlib on Windows; SFTP keeps the server's POSIX namespace.
    assert service.path_for("seedbox", PureWindowsPath("/downloads/films")).is_dir()
    assert "disposable-test-password" not in json.dumps(service.snapshot("seedbox"))
    reopened = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
    assert reopened.check("seedbox")["checked"] is True
    service.close()
    reopened.close()


def test_transfer_copies_to_seedbox_verifies_and_recovers(cluster, seedbox, tmp_path):
    from tests.test_multi_client_docker import until
    from tests.torrents import make_torrent
    from torrentlinker.torrent_meta import read_torrent
    from torrentlinker.transfers import Transfers

    config, data_folder = seedbox
    access = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
    key = access.discover(config)["host_key"]
    access.save("qbit-b", config, "disposable-test-password", key)
    access.check("qbit-b")
    source = cluster.folder("qbit-a") / "remote-transfer.bin"
    source.write_bytes(os.urandom(2_500_000))
    data = make_torrent(source)
    infohash = read_torrent(data).infohash
    cluster.clients["qbit-a"].add(data, str(source.parent), [])
    cluster.clients["qbit-a"].recheck(infohash)
    until(lambda: cluster.clients["qbit-a"].torrent(infohash).progress == 1)
    clients = {**cluster.clients, "qbit-b": cluster.clients["qbit-b"]._inner}
    transfers = Transfers(tmp_path / "plans", clients.get, storage=access.path_for)
    plan = transfers.prepare(
        [{"client_id": "qbit-a", "hash": infohash, "folder": "/data/films"}], "qbit-b"
    )
    assert plan["can_start"], plan
    transfers.stop(plan["id"])
    assert transfers.run(plan["id"])["rows"][0]["status"] == "interrupted"
    reopened = Transfers(tmp_path / "plans", clients.get, storage=access.path_for)
    result = reopened.run(plan["id"])
    assert result["rows"][0]["status"] == "confirmed", result
    assert (data_folder / "films" / source.name).read_bytes() == source.read_bytes()
    assert source.exists()
    # Download from the seedbox, then explicitly remove only the source files.
    returning = Transfers(
        tmp_path / "return", clients.get, metadata=lambda cid, key: data, storage=access.path_for
    )
    target = cluster.folder("deluge") / "returned"
    target.mkdir()
    back = returning.prepare(
        [{"client_id": "qbit-b", "hash": infohash, "folder": str(target)}],
        "deluge",
        remove_files=True,
    )
    assert back["can_start"], back
    result = returning.run(back["id"])
    assert result["rows"][0]["status"] == "confirmed", result
    remote_source = data_folder / "films" / source.name
    before = remote_source.stat()
    remote_source.write_bytes(b"x" * before.st_size)
    os.utime(remote_source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match="Source content"):
        returning.review_cleanup(back["id"], 0)
    remote_source.write_bytes(source.read_bytes())
    os.utime(remote_source, ns=(before.st_atime_ns, before.st_mtime_ns))
    review = returning.review_cleanup(back["id"], 0)
    returning.cleanup(back["id"], 0, review["token"])
    assert not (data_folder / "films" / source.name).exists()
    assert (target / source.name).read_bytes() == source.read_bytes()
    assert clients["qbit-b"].torrent(infohash) is not None
    access.close()


def test_changed_identity_and_unsafe_paths_block_access(seedbox, tmp_path):
    import asyncssh

    config, data = seedbox
    access = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
    identity = access.discover(config)
    wrong = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
    access.save("remote", config, "disposable-test-password", wrong)
    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        access.check("remote")
    assert access.snapshot("remote")["checked"] is False
    access.save("remote", config, "disposable-test-password", identity["host_key"])
    (data / "escape").symlink_to("/etc", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        access.browse("remote", "/downloads/escape")
    with pytest.raises(ValueError):
        access.browse("remote", "/downloads/../etc")
    access.close()


def test_shared_workspace_configures_remote_access_and_browses_client_paths(seedbox, operations):
    from tests.test_torrents_workspace import workspace

    config, _ = seedbox
    service = workspace(operations)
    identity = service.request(
        "transfer-access-discover", {"client_id": "default", "config": config}
    )
    service.request(
        "transfer-access-save",
        {
            "client_id": "default",
            "config": config,
            "credential": "disposable-test-password",
            "host_key": identity["host_key"],
        },
    )
    checked = service.request("transfer-access-check", {"client_id": "default"})
    assert checked["checked"]
    result = service.request(
        "transfer-remote-browse", {"client_id": "default", "path": "/downloads"}
    )
    assert "/downloads/films" in result["folders"]
    options = service.request("transfer-options", {"items": []})
    assert options["clients"][0]["access"]["checked"]


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="set TL_WEB_BROWSER=1")
def test_seedbox_dialog_access_mapping_and_progress(cluster, seedbox, tmp_path):
    import socket
    import threading

    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_multi_client_docker import until
    from tests.torrents import make_torrent
    from torrentlinker.torrent_meta import read_torrent
    from torrentlinker.web.app import create_app

    config, _ = seedbox
    source = cluster.folder("qbit-a") / "sftp-ui.bin"
    source.write_bytes(os.urandom(100_000))
    data = make_torrent(source)
    infohash = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), [])
    client.recheck(infohash)
    until(lambda: client.torrent(infohash).progress == 1)
    directory = tmp_path / "web"
    directory.mkdir()
    cluster.settings.save(directory / "settings.json")
    (directory / "client.ready").touch()
    ServerSecrets(directory).update(cluster.secrets)
    app = create_app(directory, password="test-password-long", roots=(cluster.root,))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    until(lambda: server.started)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            open_seedbox_browser(page, f"http://127.0.0.1:{port}", errors)
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "torrents")
            panel = page.frame_locator("#torrents-frame")
            panel.locator("#query").fill("sftp-ui")
            expect(panel.locator("tbody tr")).to_have_count(1)
            panel.locator("tbody input").first.check()
            panel.locator("#transfer-selection").click()
            panel.locator("#transfer-destination").select_option(cluster.ids["qbit-b"])
            panel.locator(f'[data-remote-edit="{cluster.ids["qbit-b"]}"]').click()
            panel.locator("#remote-host").fill(config["host"])
            panel.locator("#remote-port").fill(str(config["port"]))
            panel.locator("#remote-user").fill("seed")
            panel.locator("#remote-auth").select_option("password")
            panel.locator("#remote-credential").fill("disposable-test-password")
            panel.locator("#remote-client-root").fill("/data")
            panel.locator("#remote-file-root").fill("/files")
            panel.locator("#remote-test").click()
            expect(panel.locator("#remote-trust")).to_be_visible()
            panel.locator("#remote-trust").check()
            panel.locator("#remote-test").click()
            expect(panel.locator("#remote-result")).to_contain_text(
                "Access verified", timeout=20000
            )
            panel.locator("#remote-done").click()
            expect(panel.locator("#transfer-destination")).to_be_visible()
            panel.locator("[data-transfer-folder]").first.fill("/data/films")
            panel.locator("[data-transfer-folder]").first.press("Tab")
            panel.locator("#transfer-check").click()
            expect(panel.locator("#transfer-start")).to_be_enabled(timeout=20000)
            panel.locator("#transfer-start").click()
            expect(panel.locator(".transfer-item")).to_contain_text(
                "Seeding at destination", timeout=60000
            )
            assert source.exists()
            page.screenshot(
                path=os.getenv("TL_SEEDBOX_SCREENSHOT", str(tmp_path / "seedbox-web.png"))
            )
            panel.locator("#transfer-close").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("light")
            panel.locator("#transfer-history").click()
            panel.locator("[data-transfer-id]").first.click()
            expect(panel.locator(".transfer-heading")).to_contain_text(
                "Transférer vers un autre client"
            )
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(15)


def test_seedbox_relay_resumes_partial_copy_and_rejects_collision(cluster, seedbox, tmp_path):
    from tests.test_multi_client_docker import until
    from tests.torrents import make_torrent
    from torrentlinker.torrent_meta import read_torrent
    from torrentlinker.transfers import Transfers

    config, source_folder = seedbox
    with sftp_endpoint(cluster.folder("deluge")) as (destination_config, target_folder):
        access = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
        for identifier, cfg in [("qbit-b", config), ("deluge", destination_config)]:
            key = access.discover(cfg)["host_key"]
            access.save(identifier, cfg, "disposable-test-password", key)
            access.check(identifier)
        source = source_folder / "relay.bin"
        source.write_bytes(os.urandom(16 * 1024 * 1024))
        data = make_torrent(source)
        infohash = read_torrent(data).infohash
        cluster.clients["qbit-b"].add(data, str(source_folder), [])
        cluster.clients["qbit-b"].recheck(infohash)
        until(lambda: cluster.clients["qbit-b"].torrent(infohash).progress == 1)
        clients = {name: value._inner for name, value in cluster.clients.items()}
        service = Transfers(
            tmp_path / "plans", clients.get, metadata=lambda cid, key: data, storage=access.path_for
        )
        target = target_folder / "films" / source.name
        target.write_bytes(b"already exists")
        blocked = service.prepare(
            [{"client_id": "qbit-b", "hash": infohash, "folder": "/data/films"}], "deluge"
        )
        assert not blocked["can_start"]
        target.unlink()
        plan = service.prepare(
            [{"client_id": "qbit-b", "hash": infohash, "folder": "/data/films"}], "deluge"
        )
        assert plan["can_start"], plan
        service.start(plan["id"])
        until(lambda: service.get(plan["id"])["rows"][0]["bytes"] > 0)
        service.stop(plan["id"])
        until(lambda: service.get(plan["id"])["status"] != "running")
        assert service.get(plan["id"])["rows"][0]["status"] == "interrupted"
        resumed = Transfers(
            tmp_path / "plans", clients.get, metadata=lambda cid, key: data, storage=access.path_for
        )
        result = resumed.run(plan["id"])
        assert result["rows"][0]["status"] == "confirmed", result
        assert source.read_bytes() == target.read_bytes()
        access.close()


def test_ssh_key_authentication_and_unreported_capacity(tmp_path):
    import asyncssh

    key = asyncssh.generate_private_key("ssh-ed25519")
    with sftp_endpoint(
        tmp_path / "files",
        sftp_options="-P statvfs,fstatvfs",
        authorized_key=key.export_public_key().decode(),
    ) as (config, _):
        access = RemoteAccess(tmp_path / "access", ServerSecrets(tmp_path))
        config["auth"] = "key"
        identity = access.discover(config)
        access.save("remote", config, key.export_private_key().decode(), identity["host_key"])
        assert "/data/films" in access.browse("remote", "/data")["folders"]
        with pytest.raises(ValueError, match="available space"):
            access.check("remote")
        assert not access.snapshot("remote")["checked"]
        access.close()


def test_settings_saved_access_reuses_sftp_and_reports_connection_failures(seedbox, tmp_path):
    import asyncssh
    from fastapi.testclient import TestClient

    from tests.test_web_jobs import login
    from tests.test_web_plan_execution import prepared
    from torrentlinker.web.app import create_app

    values, data = seedbox
    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with TestClient(app) as browser:
        login(browser)

        def call(action, value=None):
            return browser.post(
                "/api/settings/file-access/" + action,
                json={"client_id": "default", "value": value or {}},
            )

        identity = call("discover", {"config": values}).json()
        body = {
            "config": values,
            "credential": "disposable-test-password",
            "host_key": identity["host_key"],
        }
        assert call("save", body).status_code == 200
        assert call("check").json()["checked"]
        assert "/downloads/films" in call("browse").json()["folders"]
        workspace = app.state.agent_service.torrents_workspace
        assert workspace.request("transfer-options", {"items": []})["clients"][0]["access"][
            "checked"
        ]
        # Permission failures belong to the operation; a directory-space check
        # does not claim arbitrary read or write permission.
        denied = data / "denied"
        denied.mkdir(mode=0)
        try:
            response = call("browse", {"path": "/downloads/denied"})
            assert response.status_code == 400
            assert "denied" in response.text.lower()
        finally:
            denied.chmod(0o700)
        wrong = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
        assert call("save", {**body, "host_key": wrong}).status_code == 200
        assert call("check").status_code == 400
        assert not call("snapshot").json()["checked"]
        assert call("save", {**body, "config": {**values, "port": 1}}).status_code == 200
        assert call("check").status_code == 400
        assert not call("snapshot").json()["checked"]
        assert call("remove", {"confirmed": True}).status_code == 200
        assert (data / "films").is_dir()
        assert not call("snapshot").json()["configured"]


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="set TL_WEB_BROWSER=1")
def test_settings_file_access_editor_and_transfer_reuse_in_browser(seedbox, tmp_path):
    import socket
    import threading
    from pathlib import Path

    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_web_plan_execution import prepared
    from torrentlinker.web.app import create_app

    values, _ = seedbox
    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1300, "height": 950}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(error.stack))
                open_seedbox_browser(page, f"http://127.0.0.1:{listener.getsockname()[1]}", errors)
                page.locator("#login-password").fill("test-password-long")
                page.locator("#login-form button").click()
                assert not errors
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "dark"
                )
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                name = panel.get_by_label("Client name", exact=True)
                name.fill("Unsaved API draft")
                card = panel.locator("#file-access-card")
                card.get_by_role("button", name="Configure file access…").click()
                for selector, value in [
                    ("host", values["host"]),
                    ("port", str(values["port"])),
                    ("user", "seed"),
                    ("client-root", "/downloads"),
                    ("file-root", "/files"),
                ]:
                    panel.locator("#remote-" + selector).fill(value)
                panel.locator("#remote-auth").select_option("password")
                panel.locator("#remote-credential").fill("disposable-test-password")
                panel.locator("#remote-test").click()
                expect(panel.locator("#remote-trust")).to_be_visible()
                assert not app.state.agent_service.torrents_workspace.remote.snapshot("default")[
                    "configured"
                ]
                panel.locator("#remote-trust").check()
                panel.locator("#remote-test").click()
                expect(panel.locator("#remote-result")).to_contain_text(
                    "Access verified", timeout=20000
                )
                expect(panel.locator("#remote-credential")).to_have_value("")
                panel.locator("#remote-browse").click()
                expect(panel.get_by_role("heading", name="Browse SFTP folders")).to_be_visible()
                panel.locator("#root-cancel").click()
                panel.locator("#remote-done").click()
                expect(card).to_contain_text("Checked · SFTP")
                expect(card).to_contain_text("SFTP alone is not supported")
                expect(name).to_have_value("Unsaved API draft")
                output = Path(os.getenv("TL_FILE_ACCESS_SCREENSHOTS", str(tmp_path / "shots")))
                output.mkdir(parents=True, exist_ok=True)
                card.scroll_into_view_if_needed()
                page.screenshot(path=str(output / "settings-en-dark.png"))
                # Same shared editor retains unsaved credentials when translated,
                # and discards them when dismissed.
                card.get_by_role("button", name="Configure file access…").click()
                panel.locator("#remote-credential").fill("unsaved-credential")
                pending_discovery = []
                page.route(
                    "**/api/settings/file-access/discover",
                    lambda route: pending_discovery.append(route),
                )
                panel.locator("#remote-test").click()
                expect(panel.locator("#remote-credential")).to_be_disabled()
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "fr"
                )
                expect(panel.locator("#remote-credential")).to_be_disabled()
                expect(panel.locator("#remote-test")).to_be_disabled()
                for _ in range(100):
                    if pending_discovery:
                        break
                    page.wait_for_timeout(20)
                assert len(pending_discovery) == 1
                pending_discovery[0].fulfill(
                    status=400,
                    content_type="application/json",
                    body='{"detail":"Fixture discovery failure"}',
                )
                expect(panel.locator("#remote-test")).to_be_enabled()
                page.unroute("**/api/settings/file-access/discover")
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "light"
                )
                expect(panel.locator("#remote-test")).to_contain_text("accès")
                expect(panel.locator("#remote-credential")).to_have_value("unsaved-credential")
                page.screenshot(path=str(output / "editor-fr-light.png"))
                page.set_viewport_size({"width": 390, "height": 844})
                assert panel.locator("#file-access-editor").evaluate(
                    "e => e.scrollWidth <= e.clientWidth + 1"
                )
                page.screenshot(path=str(output / "editor-fr-mobile.png"))
                panel.locator("#remote-done").click()
                card.get_by_role("button", name="Configurer l’accès aux fichiers…").click()
                expect(panel.locator("#remote-credential")).to_have_value("")
                pending_saved_check = []
                page.route(
                    "**/api/settings/file-access/check",
                    lambda route: pending_saved_check.append(route),
                )
                panel.locator("#remote-credential").fill("disposable-test-password")
                panel.locator("#remote-test").click()
                for _ in range(100):
                    if pending_saved_check:
                        break
                    page.wait_for_timeout(20)
                assert len(pending_saved_check) == 1
                expect(panel.locator("#remote-credential")).to_have_value("")
                page.set_viewport_size({"width": 1300, "height": 950})
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "en"
                )
                expect(panel.locator("#remote-credential")).to_be_disabled()
                expect(panel.locator("#remote-credential")).to_have_value("")
                pending_saved_check[0].fulfill(
                    status=400,
                    content_type="application/json",
                    body='{"detail":"Fixture connection failure"}',
                )
                expect(panel.locator("#remote-result")).to_contain_text(
                    "Fixture connection failure"
                )
                expect(panel.locator("#remote-credential")).to_have_value("")
                panel.locator("#file-access-editor").press("Escape")
                expect(card).to_contain_text("Recheck required · SFTP")
                page.unroute("**/api/settings/file-access/check")
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "fr"
                )
                # A completed check response from a previous visit must not
                # overwrite the fresh snapshot after returning to Settings.
                page.set_viewport_size({"width": 1300, "height": 950})
                pending_check = []
                page.route(
                    "**/api/settings/file-access/check",
                    lambda route: pending_check.append((route, route.fetch())),
                )
                card.get_by_role("button", name="Tester l’accès", exact=True).click()
                for _ in range(100):
                    if pending_check:
                        break
                    page.wait_for_timeout(20)
                assert len(pending_check) == 1
                shell_navigate(page, "library")
                shell_navigate(page, "setup")
                expect(card).to_contain_text("Vérifié · SFTP")
                pending_check[0][0].fulfill(response=pending_check[0][1])
                page.unroute("**/api/settings/file-access/check")
                panel.get_by_role("button", name="Clients", exact=True).click()
                panel.get_by_role("button", name="Connexions", exact=True).click()
                expect(card).to_contain_text("Vérifié · SFTP")
                expect(card).not_to_contain_text("Le client cible a changé")
                card.get_by_role("button", name="Supprimer l’accès…").click()
                panel.locator("dialog").get_by_role("button", name="Annuler").click()
                assert app.state.agent_service.torrents_workspace.remote.snapshot("default")[
                    "configured"
                ]
                card.get_by_role("button", name="Supprimer l’accès…").click()
                panel.locator("dialog").get_by_role(
                    "button", name="Supprimer l’accès", exact=True
                ).click()
                expect(card).to_contain_text("Non configuré")
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(15)


@pytest.mark.parametrize("layout", ["auto", "links"])
@pytest.mark.parametrize("workflow", ["board", "local"])
def test_reseed_layout_choice_on_disposable_client(cluster, tmp_path, layout, workflow):
    from pathlib import Path

    from tests.test_reseed_workspace import run, workspace
    from torrentlinker.domain import PathMapping

    shared = cluster.folder("qbit-a")
    root = shared / ("reseed-layout-" + layout + "-" + workflow)
    root.mkdir()
    client = cluster.clients["qbit-a"]._inner
    board, _, original, links, meta = workspace(root, client)
    board.setup.settings.path_mappings = [PathMapping(str(shared), "/data")]
    board.setup.settings.profile().reseed_layout = layout
    before = original.read_bytes(), original.stat().st_ino, original.name
    try:
        if workflow == "board":
            result = run(board, original, links if layout == "links" else "")
            assert not result["errors"], result
            destination = result["rows"][0]["destination"]
        else:
            from tests.test_multi_client_docker import until
            from torrentlinker.reseed import check_verifications
            from torrentlinker.web.jobs import JobStop

            board.setup.settings.profile().reseed_link_root = str(links)
            board.library.reseed(str(original), meta.infohash, JobStop())
            outcomes = []

            def verified():
                outcomes.extend(check_verifications(board.library.client(), board.setup.store))
                return bool(outcomes)

            until(verified)
            assert outcomes[0].started, outcomes
            destination = (
                board.setup.store.reseed_link_layout(meta.infohash)["destination"]
                if layout == "links"
                else str(original.parent)
            )
        torrent = client.torrent(meta.infohash)
        assert torrent.progress == 1
        assert torrent.files == {
            "Release.mkv" if layout == "links" else original.name: original.stat().st_size
        }
        assert torrent.save_path == Path("/data") / Path(destination).relative_to(shared)
        if layout == "auto":
            assert not list(links.iterdir())
        assert (original.read_bytes(), original.stat().st_ino, original.name) == before
    finally:
        client.remove(meta.infohash)
        from tests.test_multi_client_docker import until

        until(lambda: client.torrent(meta.infohash) is None)
