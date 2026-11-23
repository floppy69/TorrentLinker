"""Transfers use real disposable clients on the internal multi-client Docker network."""

import os

import pytest

from tests.shell_support import shell_navigate
from tests.test_multi_client_docker import until
from tests.torrents import make_torrent
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.transfers import Transfers

pytest_plugins = ["tests.test_multi_client_docker"]

pytestmark = pytest.mark.skipif(os.getenv("TL_MULTI_DOCKER") != "1", reason="set TL_MULTI_DOCKER=1")


@pytest.mark.parametrize("destination_client", ["transmission", "deluge"])
def test_copy_between_clients_preserves_source_until_explicit_cleanup(cluster, destination_client):
    source = cluster.folder("qbit-a") / f"transfer-{destination_client}-source.bin"
    source.write_bytes(os.urandom(512_000))
    data = make_torrent(source)
    key = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), [])
    client.recheck(key)
    until(lambda: client.torrent(key).progress == 1)
    destination = cluster.folder(destination_client) / "transfer-target"
    destination.mkdir()
    service = Transfers(
        cluster.root / "transfer-state",
        lambda identifier: cluster.clients[identifier],
    )
    plan = service.prepare(
        [{"client_id": "qbit-a", "hash": key, "folder": str(destination)}],
        destination_client,
        remove_torrent=True,
        remove_files=True,
    )
    assert plan["can_start"], plan
    result = service.run(plan["id"])
    assert result["rows"][0]["status"] == "confirmed", result
    assert source.exists()
    assert (destination / source.name).read_bytes() == source.read_bytes()
    assert cluster.clients[destination_client].torrent(key).progress == 1
    # Reopen the public service to prove that completion survives restart.
    reopened = Transfers(cluster.root / "transfer-state", lambda i: cluster.clients[i])
    review = reopened.review_cleanup(plan["id"], 0)
    reopened.cleanup(plan["id"], 0, review["token"])
    assert not source.exists()
    assert client.torrent(key) is None
    assert (destination / source.name).exists()
    # Non-qBittorrent sources use retained original metainfo rather than reconstructing it.
    returning = Transfers(
        cluster.root / (destination_client + "-return"),
        lambda i: cluster.clients[i],
        metadata=lambda cid, key: data,
    )
    back = returning.prepare(
        [{"client_id": destination_client, "hash": key, "folder": str(source.parent)}], "qbit-a"
    )
    assert back["can_start"], back
    result = returning.run(back["id"])
    assert result["rows"][0]["status"] == "confirmed", result
    assert source.read_bytes() == (destination / source.name).read_bytes()


def test_entire_batch_blocks_and_source_client_is_excluded(cluster):
    source = cluster.folder("qbit-a") / "blocked-source.bin"
    source.write_bytes(os.urandom(32_000))
    data = make_torrent(source)
    key = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), [])
    client.recheck(key)
    until(lambda: client.torrent(key).progress == 1)
    service = Transfers(cluster.root / "blocked-state", lambda i: cluster.clients[i])
    plan = service.prepare(
        [
            {"client_id": "qbit-a", "hash": key, "folder": str(cluster.folder("qbit-b"))},
            {"client_id": "qbit-a", "hash": key, "folder": ""},
        ],
        "qbit-b",
    )
    assert not plan["can_start"]
    with pytest.raises(ValueError, match="every blocker"):
        service.run(plan["id"])
    assert cluster.clients["qbit-b"].torrent(key) is None
    same = service.prepare(
        [{"client_id": "qbit-a", "hash": key, "folder": str(source.parent)}], "qbit-a"
    )
    assert not same["can_start"]


def test_interrupted_transfer_recovers_from_saved_plan_and_files_only_cleanup(cluster):
    source = cluster.folder("qbit-a") / "recover-source.bin"
    source.write_bytes(os.urandom(120_000))
    data = make_torrent(source)
    key = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), [])
    client.recheck(key)
    until(lambda: client.torrent(key).progress == 1)
    service = Transfers(cluster.root / "recover-state", lambda i: cluster.clients[i])
    plan = service.prepare(
        [{"client_id": "qbit-a", "hash": key, "folder": str(cluster.folder("qbit-b"))}],
        "qbit-b",
        remove_files=True,
    )
    service.stop(plan["id"])
    assert service.run(plan["id"])["rows"][0]["status"] == "interrupted"
    reopened = Transfers(cluster.root / "recover-state", lambda i: cluster.clients[i])
    result = reopened.run(plan["id"])
    assert result["rows"][0]["status"] == "confirmed", result
    review = reopened.review_cleanup(plan["id"], 0)
    reopened.cleanup(plan["id"], 0, review["token"])
    assert not source.exists()
    assert client.torrent(key) is not None
    assert cluster.clients["qbit-b"].torrent(key).progress == 1


def test_web_transfer_options_defaults_overrides_and_rendering(cluster, tmp_path):
    import socket
    import threading

    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.web.app import create_app
    from torrentlinker.web.security import ServerSecrets

    source = cluster.folder("qbit-a") / "browser-source.bin"
    source.write_bytes(os.urandom(32_000))
    data = make_torrent(source)
    key = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), ["torrentlinker:category:Films"])
    client.recheck(key)
    until(lambda: client.torrent(key).progress == 1)
    category_folder = cluster.folder("qbit-b") / "films"
    category_folder.mkdir()
    cluster.settings.indexer_categories[42] = IndexerCategory("Films")
    cluster.settings.profile(cluster.ids["qbit-b"]).download_folders.by_category[42] = str(
        category_folder
    )
    config = tmp_path / "config"
    config.mkdir()
    cluster.settings.save(config / "settings.json")
    (config / "client.ready").touch()
    ServerSecrets(config).update(cluster.secrets)
    app = create_app(config, password="test-password-long", roots=(cluster.root,))
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
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "torrents")
            panel = page.frame_locator("#torrents-frame")
            panel.locator("#query").fill("browser-source")
            expect(panel.locator("tbody tr")).to_have_count(1)
            panel.locator("tbody input").first.check()
            panel.locator("#transfer-selection").click()
            expect(panel.locator("#transfer-destination")).to_be_visible()
            assert (
                panel.locator(
                    f'#transfer-destination option[value="{cluster.ids["qbit-a"]}"]'
                ).get_attribute("disabled")
                is not None
            )
            panel.locator("#transfer-destination").select_option(cluster.ids["qbit-b"])
            panel.locator("#cleanup-torrent").check()
            field = panel.locator("[data-transfer-folder]").first
            expect(field).to_have_value(str(category_folder))
            field.fill("")
            field.press("Tab")
            panel.locator("#transfer-check").click()
            expect(panel.locator("#transfer-start")).to_be_disabled()
            expect(panel.locator(".transfer-blocked")).to_be_visible()
            panel.locator("[data-fix]").click()
            field = panel.locator("[data-transfer-folder]").first
            field.fill(str(cluster.folder("qbit-b")))
            field.press("Tab")
            panel.locator("#transfer-check").click()
            assert panel.locator("#transfer-start").is_enabled(), panel.locator(
                "#transfer-content"
            ).inner_text()
            panel.locator("#transfer-start").click()
            expect(panel.locator(".transfer-item")).to_contain_text(
                "Seeding at destination", timeout=60000
            )
            page.screenshot(path=str(tmp_path / "transfer-web.png"))
            panel.locator("[data-cleanup]").click()
            panel.locator("#cleanup-confirm").click()
            expect(panel.locator(".transfer-item")).to_contain_text("Confirmed cleanup completed")
            panel.locator("#transfer-close").click()
            panel.locator("#transfer-history").click()
            panel.locator("[data-transfer-id]").filter(has_text="Complete").click()
            expect(panel.locator(".transfer-item")).to_contain_text("Confirmed cleanup completed")
            panel.locator("#transfer-close").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("dark")
            expect(panel.locator("html")).to_have_attribute("data-theme", "dark")
            panel.locator("#transfer-history").click()
            panel.locator("[data-transfer-id]").filter(has_text="Terminé").click()
            expect(panel.locator(".transfer-heading")).to_contain_text(
                "Transférer vers un autre client"
            )
            page.screenshot(path=str(tmp_path / "transfer-web-fr-dark.png"))
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(15)


def test_changed_batch_and_corrupted_destination_refuse_mutation(cluster):
    source = cluster.folder("qbit-a") / "safety-source.bin"
    original = os.urandom(64_000)
    source.write_bytes(original)
    data = make_torrent(source)
    key = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), [])
    client.recheck(key)
    until(lambda: client.torrent(key).progress == 1)
    target = cluster.folder("qbit-b") / "safety-target"
    target.mkdir()
    service = Transfers(cluster.root / "safety-state", lambda i: cluster.clients[i])
    items = [{"client_id": "qbit-a", "hash": key, "folder": str(target)}]
    plan = service.prepare(items, "qbit-b", remove_files=True)
    source.write_bytes(b"x" * len(original))
    with pytest.raises(ValueError, match="Source files changed"):
        service.run(plan["id"])
    assert not (target / source.name).exists()
    source.write_bytes(original)
    plan = service.prepare(items, "qbit-b", remove_files=True)
    assert service.run(plan["id"])["rows"][0]["status"] == "confirmed"
    cluster.clients["qbit-b"].pause(key)
    (target / source.name).write_bytes(b"x" * len(original))
    with pytest.raises(ValueError):
        service.review_cleanup(plan["id"], 0)
    assert source.read_bytes() == original


def test_changed_client_configuration_and_shared_file_deletion_are_blocked(cluster):
    source = cluster.folder("qbit-a") / "binding-source.bin"
    source.write_bytes(os.urandom(32_000))
    data = make_torrent(source)
    key = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), [])
    client.recheck(key)
    until(lambda: client.torrent(key).progress == 1)
    version = [1]
    service = Transfers(
        cluster.root / "binding-state",
        lambda i: cluster.clients[i],
        fingerprint=lambda i: version[0],
    )
    plan = service.prepare(
        [{"client_id": "qbit-a", "hash": key, "folder": str(cluster.folder("qbit-b"))}], "qbit-b"
    )
    version[0] = 2
    with pytest.raises(ValueError, match="settings changed"):
        service.run(plan["id"])
    assert cluster.clients["qbit-b"].torrent(key) is None
    shared = service.prepare(
        [{"client_id": "qbit-a", "hash": key, "folder": str(source.parent)}],
        "qbit-b",
        remove_files=True,
    )
    assert not shared["can_start"]
    assert "Shared source files" in shared["rows"][0]["error"]


def test_interrupt_during_copy_resumes_verified_bytes(cluster):
    import time

    source = cluster.folder("qbit-a") / "partial-source.bin"
    source.write_bytes(os.urandom(64 * 1024 * 1024))
    data = make_torrent(source)
    key = read_torrent(data).infohash
    client = cluster.clients["qbit-a"]
    client.add(data, str(source.parent), [])
    client.recheck(key)
    until(lambda: client.torrent(key).progress == 1)
    service = Transfers(cluster.root / "partial-state", lambda i: cluster.clients[i])
    plan = service.prepare(
        [{"client_id": "qbit-a", "hash": key, "folder": str(cluster.folder("qbit-b"))}], "qbit-b"
    )
    service.start(plan["id"])
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        current = service.get(plan["id"])
        if current["rows"][0]["bytes"] > 0:
            service.stop(plan["id"])
            break
        time.sleep(0.001)
    until(lambda: service.get(plan["id"])["status"] == "attention")
    partial = service.get(plan["id"])["rows"][0]
    assert 0 < partial["bytes"] < partial["total"]
    reopened = Transfers(cluster.root / "partial-state", lambda i: cluster.clients[i])
    result = reopened.run(plan["id"])
    assert result["rows"][0]["status"] == "confirmed", result
    assert (cluster.folder("qbit-b") / source.name).read_bytes() == source.read_bytes()
