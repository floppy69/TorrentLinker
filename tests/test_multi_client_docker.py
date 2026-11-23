"""Real, isolated multi-client tests. Run with TL_MULTI_DOCKER=1 pytest -s -q this_file.

Uses cached pinned images, an internal Docker network, unpublished Web UIs and
generated files. Containers and the network are removed even if a test fails.
No personal settings, keyring entries, torrents or trackers are used.
"""

import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import torf
from fastapi.testclient import TestClient

from tests.test_qbit_integration import check_uploads_seed_from_the_local_files, digest, settle
from tests.test_web_jobs import login
from tests.torrents import make_torrent
from torrentlinker.client_profiles import Connections
from torrentlinker.config import Settings
from torrentlinker.domain import LibraryFolder, PathMapping, TorrentClient
from torrentlinker.download_queue import enqueue, entries, run_queue
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.matching import match
from torrentlinker.multi_plan import distributed_plan
from torrentlinker.plan import restore_plan, saved_items
from torrentlinker.reseed import start_reseed
from torrentlinker.scan import scan
from torrentlinker.send import send_plan
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.torrent_management import status
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.upload import bencode
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_MULTI_DOCKER") != "1", reason="set TL_MULTI_DOCKER=1")

IMAGES = {
    "qbit-a": (TorrentClient.QBITTORRENT, "qbittorrentofficial/qbittorrent-nox:5.2.4-1", 8080),
    "qbit-b": (TorrentClient.QBITTORRENT, "qbittorrentofficial/qbittorrent-nox:5.2.4-1", 8080),
    "deluge": (TorrentClient.DELUGE, "lscr.io/linuxserver/deluge:2.2.0", 8112),
    "transmission": (TorrentClient.TRANSMISSION, "lscr.io/linuxserver/transmission:4.1.3", 9091),
}


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.STDOUT).strip()


def until(check, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    pytest.fail("Client did not reach the expected state")


@dataclass
class Cluster:
    root: Path
    settings: Settings
    ids: dict
    secrets: dict = field(repr=False)
    clients: dict
    containers: dict
    gateway: str

    def folder(self, name):
        return self.root / name / "data"


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    root = tmp_path_factory.mktemp("multi-docker")
    network = "tl-multi-" + uuid.uuid4().hex[:10]
    settings, secrets, ids, containers = Settings(), {}, {}, {}
    for _, image, _ in IMAGES.values():
        docker("image", "inspect", image)
    docker("network", "create", "--internal", "--label", "torrentlinker.test=multi-client", network)
    try:
        for name, (kind, image, port) in IMAGES.items():
            base = root / name
            config, data = base / "config", base / "data"
            config.mkdir(parents=True)
            data.mkdir()
            default_downloads = base / "default-downloads"
            default_downloads.mkdir()
            if kind is TorrentClient.QBITTORRENT:
                subprocess.run(
                    [sys.executable, "scripts/qbit_sandbox.py", str(config), "--docker", "--auth"],
                    check=True,
                    capture_output=True,
                )
                path = config / "qBittorrent/config/qBittorrent.conf"
                path.write_text(
                    path.read_text().replace(
                        "AuthSubnetWhitelistEnabled=true", "AuthSubnetWhitelistEnabled=false"
                    )
                )
                password = (config / "password").read_text()
                username = "sandbox"
            else:
                password = "deluge" if kind is TorrentClient.DELUGE else ""
                username = ""
            container = network + "-" + name
            containers[name] = container
            docker(
                "run",
                "-d",
                "--pull=never",
                "--name",
                container,
                "--network",
                network,
                "--label",
                "torrentlinker.test=multi-client",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "-e",
                f"PUID={os.getuid()}",
                "-e",
                f"PGID={os.getgid()}",
                "-e",
                "QBT_LEGAL_NOTICE=confirm",
                "-v",
                f"{config}:/config",
                "-v",
                f"{data}:/data",
                "-v",
                f"{default_downloads}:/downloads",
                image,
            )
            networks = json.loads(
                docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", container)
            )
            host = f"http://{networks[network]['IPAddress']}:{port}"
            profile = settings.profile() if name == "qbit-a" else settings.add_client(name, kind)
            profile.name, profile.client, profile.host, profile.username = (
                name,
                kind,
                host,
                username,
            )
            if name == "qbit-a":
                settings.qbit.host, settings.qbit.username = host, username
            profile.path_mappings = [PathMapping(str(data), "/data")]
            profile.download_folders.default = str(data / "downloads")
            (data / "downloads").mkdir()
            if name == "qbit-a":
                settings.path_mappings = profile.path_mappings.copy()
                settings.download_folders = profile.download_folders
            ids[name] = profile.id
            field = "qbit" if kind is TorrentClient.QBITTORRENT else kind.value
            secrets[profile.secret_name(field + "-password")] = password
            if kind in {TorrentClient.DELUGE, TorrentClient.TRANSMISSION}:
                subprocess.run(
                    [sys.executable, f"scripts/{kind.value}_sandbox.py", host],
                    check=True,
                    timeout=90,
                )
        pool = Connections(lambda key: secrets.get(key, ""))
        clients = {name: pool.client(settings, identifier) for name, identifier in ids.items()}
        for name, client in clients.items():
            if name == "transmission":
                client._inner.turn_off_partial_names()
                client._inner._call("session-set", **{"download-queue-enabled": False})
            elif name == "deluge":
                # Earlier routing tests deliberately leave downloads without peers.
                # Their slots must not queue the later real transfer test.
                client._inner._call(
                    "core.set_config",
                    {
                        "max_active_limit": -1,
                        "max_active_downloading": -1,
                        "max_active_seeding": -1,
                    },
                )

            def ready(client=client):
                try:
                    return client._inner.check()
                except Exception:
                    return False

            version = until(ready)
            print(f"{name}: {version}")
        gateway = json.loads(docker("network", "inspect", network))[0]["IPAM"]["Config"][0][
            "Gateway"
        ]
        yield Cluster(root, settings, ids, secrets, clients, containers, gateway)
    finally:
        for container in containers.values():
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


@pytest.fixture
def local_tracker(cluster):
    peers = {}
    lock = threading.Lock()

    class Tracker(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query, encoding="latin1")
            if urlsplit(self.path).path == "/scrape":
                self.reply(
                    bencode(
                        {
                            "files": {
                                h.encode("latin1"): {
                                    "complete": 1,
                                    "incomplete": 1,
                                    "downloaded": 0,
                                }
                                for h in query.get("info_hash", [])
                            }
                        }
                    )
                )
                return
            identifier = query["info_hash"][0]
            peer = (self.client_address[0], int(query["port"][0]))
            with lock:
                swarm = peers.setdefault(identifier, set())
                swarm.add(peer)
                compact = b"".join(
                    socket.inet_aton(ip) + struct.pack("!H", port)
                    for ip, port in swarm
                    if (ip, port) != peer
                )
            body = bencode(
                {"interval": 1, "min interval": 1, "complete": 1, "incomplete": 1, "peers": compact}
            )
            self.reply(body)

        def reply(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((cluster.gateway, 0), Tracker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{cluster.gateway}:{server.server_port}/announce", peers
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("name", IMAGES)
def test_reseed_renamed_local_file_on_each_client(cluster, name, tmp_path):
    source = tmp_path / "Scene.epub"
    source.write_bytes(os.urandom(70001))
    meta = read_torrent(make_torrent(source))
    local = cluster.folder(name) / "library" / "My book.epub"
    local.parent.mkdir()
    local.write_bytes(source.read_bytes())
    [item] = scan(LibraryFolder(local.parent))
    before = digest(local)
    store = Store(tmp_path / "state.db").for_client(cluster.ids[name])
    client = cluster.clients[name]
    start_reseed(client, store, item, meta, match(item, meta.files), meta.infohash)
    [outcome] = settle(client, store)
    assert outcome.verified and outcome.started
    assert digest(local) == before
    assert client.torrent(meta.infohash).save_path == local.parent
    assert str(client._inner.torrent(meta.infohash).save_path) == "/data/library"
    assert not store.verification_hashes()


@pytest.mark.parametrize("name", IMAGES)
def test_upload_seeding_keeps_local_names_and_bytes(cluster, name):
    root = cluster.folder(name) / "uploads"
    root.mkdir()
    check_uploads_seed_from_the_local_files(cluster.clients[name], root)


@pytest.mark.parametrize("name", IMAGES)
def test_queue_only_sends_to_its_named_client(cluster, name, tmp_path):
    source = tmp_path / "Queue.bin"
    source.write_bytes(os.urandom(60001))
    data = make_torrent(source)
    meta = read_torrent(data)
    store = Store(tmp_path / "state.db")
    indexer = Indexer("http://tracker.example/api", "", cache=store)
    indexer.fetch_torrent = lambda *args, **kwargs: data
    candidate = Candidate(
        meta.name, source.stat().st_size, "http://tracker.example/get", infohash=meta.infohash
    )
    for label, identifier in cluster.ids.items():
        enqueue(
            store.for_client(identifier), indexer, candidate, cluster.folder(label) / "downloads"
        )
    scoped = store.for_client(cluster.ids[name])
    report = run_queue(
        scoped, indexer, cluster.clients[name], {}, threading.Event(), lambda _: None
    )
    assert report.added == [meta.name], report
    until(lambda: cluster.clients[name].torrent(meta.infohash))
    for label, client in cluster.clients.items():
        assert (client.torrent(meta.infohash) is not None) == (label == name)
        assert [e.status for e in entries(store.for_client(cluster.ids[label]))] == (
            [] if label == name else ["queued"]
        )
    assert str(cluster.clients[name]._inner.torrent(meta.infohash).save_path) == "/data/downloads"


def test_distributed_plan_saved_and_sent_to_real_destinations(cluster, tmp_path):
    store = Store(tmp_path / "state.db")
    payloads = {}
    for i in range(8):
        source = tmp_path / f"Plan-{i}.bin"
        source.write_bytes(os.urandom(70000))
        data = make_torrent(source)
        meta = read_torrent(data)
        payloads[meta.infohash] = data
        store.save_catalogue(
            [
                CatalogueRow(
                    meta.infohash,
                    meta.name,
                    70000,
                    1,
                    7000,
                    "http://tracker.example/get",
                    "",
                    time.time(),
                )
            ]
        )
    clients = {cluster.ids[name]: client for name, client in cluster.clients.items()}
    proposed = distributed_plan(
        cluster.settings, store, clients, {identifier: 140000 for identifier in clients}
    )
    assert len(proposed.items) == 8
    assert {item.candidate.client_id for item in proposed.items} == set(clients)
    store.save_plan(saved_items(proposed))
    restored = restore_plan(
        Store(tmp_path / "state.db").saved_plan(), {r.infohash: r for r in store.catalogue()}
    )
    report = send_plan(
        restored,
        cluster.clients["qbit-a"],
        lambda c: payloads[c.infohash],
        client_for=clients.__getitem__,
    )
    assert len(report.added) == 8, report
    for item in restored.items:
        c = item.candidate
        until(lambda c=c: clients[c.client_id].torrent(c.infohash))
        assert sum(client.torrent(c.infohash) is not None for client in clients.values()) == 1
        assert clients[c.client_id].torrent(c.infohash).save_path == c.folder


def completed(browser, request):
    response = browser.post("/api/jobs", json=request)
    assert response.status_code == 202, response.text

    def result():
        value = browser.get("/api/jobs/" + response.json()["id"]).json()
        return value if value["status"] not in {"running", "queued"} else None

    value = until(result, timeout=60)
    assert value["status"] == "completed", value
    return value


@pytest.mark.parametrize("name", ["qbit-b", "deluge", "transmission"])
def test_generated_file_downloads_over_the_internal_network(cluster, name, tmp_path, local_tracker):
    tracker_url, announced = local_tracker
    seed = cluster.folder("qbit-a") / ("transfer-" + name)
    seed.mkdir()
    source = seed / "Transfer.bin"
    source.write_bytes(os.urandom(2_000_001))
    torrent = torf.Torrent(path=source, trackers=[tracker_url], private=True)
    torrent.generate()
    meta = read_torrent(bytes(torrent.dump()))
    [item] = scan(LibraryFolder(seed))
    store = Store(tmp_path / "state.db")
    seeder = cluster.clients["qbit-a"]
    start_reseed(seeder, store, item, meta, match(item, meta.files), meta.infohash)
    [outcome] = settle(seeder, store)
    assert outcome.verified and outcome.started
    # Private torrents cannot discover peers through DHT/PeX. Make the first
    # download announce see its seed instead of relying on a client's retry timer.
    until(lambda: announced.get(bytes.fromhex(meta.infohash).decode("latin1")))
    target = cluster.clients[name]
    folder = cluster.folder(name) / "transfer"
    folder.mkdir()
    target.download(meta.data, str(folder), [])
    until(lambda: target.torrent(meta.infohash))
    until(lambda: target.torrent(meta.infohash).progress == 1, timeout=60)
    # Transmission can report completed bytes before moving out of its incomplete directory.
    until(lambda: (folder / source.name).is_file())
    assert digest(folder / source.name) == digest(source)


def test_web_combined_overview_and_same_hash_actions_are_isolated(cluster, tmp_path):
    source = tmp_path / "Shared.bin"
    source.write_bytes(os.urandom(80001))
    data = make_torrent(source)
    hash = read_torrent(data).infohash
    for name, client in cluster.clients.items():
        directory = cluster.folder(name) / "same-hash"
        directory.mkdir()
        (directory / source.name).write_bytes(source.read_bytes())
        meta = read_torrent(data)
        [item] = scan(LibraryFolder(directory))
        store = Store(tmp_path / (name + ".db")).for_client(cluster.ids[name])
        start_reseed(client, store, item, meta, match(item, meta.files), hash)
        [outcome] = settle(client, store)
        assert outcome.verified and outcome.started
        until(lambda client=client: status(client.torrent(hash)) == "seeding")
    config = tmp_path / "web"
    cluster.settings.save(config / "settings.json")
    (config / "client.ready").touch()
    from torrentlinker.web.security import ServerSecrets

    ServerSecrets(config).update(cluster.secrets)
    app = create_app(config, password="test-password-long", roots=(cluster.root,))
    with TestClient(app) as browser:
        login(browser)
        for name, identifier in cluster.ids.items():
            snapshot = browser.get("/api/setup", params={"client_id": identifier}).json()
            assert snapshot["name"] == name
            checked = browser.post(
                "/api/setup/test-client",
                json={
                    "client_id": identifier,
                    "client": snapshot["client"],
                    "host": snapshot["host"],
                    "username": snapshot["username"],
                },
            )
            assert checked.status_code == 200, checked.text
        completed(browser, {"kind": "refresh", "client_id": "all"})
        rows = browser.get("/api/torrents?client_id=all&limit=200").json()["rows"]
        assert {r["client_name"] for r in rows if r["hash"] == hash} == set(IMAGES)
        assert (
            browser.post(
                "/api/clients/default", json={"client_id": cluster.ids["qbit-b"]}
            ).status_code
            == 200
        )
        for name in IMAGES:
            identifier = cluster.ids[name]
            completed(
                browser,
                {"kind": "manage", "action": "pause", "hashes": [hash], "client_id": identifier},
            )
            until(lambda name=name: status(cluster.clients[name].torrent(hash)) == "paused")
            completed(browser, {"kind": "refresh", "client_id": "all"})
            overview = browser.get("/api/torrents?client_id=all&limit=200").json()
            expected_seeds = {row["hash"] for row in overview["rows"] if row["zen"] is not None}
            assert overview["zen"]["count"] == len(expected_seeds)
            for other, client in cluster.clients.items():
                if other != name:
                    assert status(client.torrent(hash)) == "seeding"
            completed(
                browser,
                {"kind": "manage", "action": "resume", "hashes": [hash], "client_id": identifier},
            )
            until(lambda name=name: status(cluster.clients[name].torrent(hash)) == "seeding")
        # Remove on one qBittorrent, delete on the other; identical hashes elsewhere survive.
        for name, action in [("qbit-a", "remove"), ("qbit-b", "delete")]:
            request = {
                "kind": "manage",
                "action": action,
                "hashes": [hash],
                "client_id": cluster.ids[name],
            }
            preview = browser.post("/api/confirm", json=request)
            assert preview.status_code == 200, preview.text
            completed(browser, {**request, "confirmation": preview.json()["token"]})
            until(lambda name=name: cluster.clients[name].torrent(hash) is None)
        assert (cluster.folder("qbit-a") / "same-hash" / source.name).is_file()
        until(lambda: not (cluster.folder("qbit-b") / "same-hash" / source.name).exists())
        assert all(cluster.clients[name].torrent(hash) for name in ("deluge", "transmission"))
        # A stopped container must not block refreshed rows from the surviving clients.
        docker("stop", "-t", "3", cluster.containers["qbit-a"])
        completed(browser, {"kind": "refresh", "client_id": "all"})
        overview = browser.get("/api/torrents?client_id=all&limit=200").json()
        assert overview["client_errors"]
        assert {r["client_name"] for r in overview["rows"]} >= {"qbit-b", "deluge", "transmission"}


@pytest.mark.parametrize("name", IMAGES)
def test_tracker_updates_keep_tiers_and_private_keys(cluster, name):
    from tests.tracker_support import check_tracker_updates

    check_tracker_updates(cluster.clients[name], cluster.folder(name))
