"""Exercise historical upgrades and offline backup/restore with disposable fixtures.

Run from the checkout with its development environment. Historical refs must exist
locally. No application directory, keyring, client or tracker is used. Each fixture
producer runs the actual source from its tag in a separate Python process.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def fingerprints(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def assert_preserved(actual, expected, path="settings"):
    """Allow new default fields while requiring every old value and list entry."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), ("Settings type changed", path)
        for key, value in expected.items():
            assert key in actual, ("Setting removed", path + "." + key)
            assert_preserved(actual[key], value, path + "." + key)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), (
            "Settings list changed",
            path,
        )
        for index, (new, old) in enumerate(zip(actual, expected, strict=True)):
            assert_preserved(new, old, f"{path}[{index}]")
    else:
        assert actual == expected, ("Setting changed", path)


CONNECTION_ATTEMPTS: list[str] = []


def no_connection(*args, **kwargs):
    CONNECTION_ATTEMPTS.append("blocked")
    raise AssertionError("Upgrade/restore must not contact a client, tracker or provider")


def worker(mode: str, directory: Path, manifest: Path) -> None:
    # Guard even accidental network calls in old source code. In-memory ASGI and
    # SQLite do not need sockets; fixtures never start schedulers or HTTP servers.
    socket.socket.connect = no_connection
    socket.socket.connect_ex = no_connection
    socket.create_connection = no_connection

    import keyring

    keyring.get_password = no_connection
    keyring.set_password = no_connection
    keyring.delete_password = no_connection

    from torrentlinker.agent.access import Grant
    from torrentlinker.assistant.models import Conversation
    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder, PathMapping, TorrentClient
    from torrentlinker.store import Store
    from torrentlinker.web.app import create_app

    media = manifest.parent / "media"
    source = media / "Object.stl"
    if mode == "seed":
        media.mkdir()
        source.write_bytes(b"solid upgrade_fixture\nendsolid upgrade_fixture\n")
        directory.mkdir()
        settings = Settings(language="fr", theme="dark")
        settings.qbit.host = "https://fixture.invalid"
        settings.library_folders = [LibraryFolder(media)]
        settings.path_mappings = [PathMapping(str(media), "/downloads")]
        settings.download_folders.default = str(media)
        settings.ensure_profiles()
        second = settings.add_client("Fixture NAS", TorrentClient.TRANSMISSION)
        second.host = "https://fixture-nas.invalid"
        second.path_mappings = [PathMapping(str(media), "/storage")]
        settings.save(directory / "settings.json")
    else:
        expected = json.loads(manifest.read_text())

    app = create_app(
        directory,
        password="fixture-password-long",
        connector=no_connection,
        monitor_verifications=False,
    )
    agent = app.state.agent_service
    assistant = app.state.assistant
    desktop_store = Store(directory / "state.db")
    stores = {"desktop": desktop_store, "web": agent.setup.store}
    try:
        if mode == "seed":
            draft_payload = {
                "path": str(source),
                "form": {
                    "title": "Object.NOTAG.STL",
                    "description": "Keep this draft text",
                    "image": "https://fixture.invalid/image.png",
                    "reviewed": False,
                    "category": 10,
                    "subcategory": 51,
                    "options": {},
                    "nfo": "Fixture NFO",
                },
                "files": [
                    {
                        "path": source.name,
                        "size": source.stat().st_size,
                        "mtime": source.stat().st_mtime_ns,
                    }
                ],
                "extra": {},
                "review": {"warnings": ["Fixture review finding"]},
            }
            drafts = {}
            secondary_drafts = {}
            queues = {}
            for name, store in stores.items():
                drafts[name] = store.save_local_draft(draft_payload)
                for key, status in (("queued-fixture", "queued"), ("sending-fixture", "sending")):
                    store.enqueue_download(
                        key,
                        {
                            "folder": str(media),
                            "indexer_url": "https://fixture.invalid/api",
                            "client_id": "default",
                            "candidate": {
                                "title": "Fixture book",
                                "size": 1024,
                                "seeders": 2,
                                "download_url": "https://fixture.invalid/torrent",
                                "categories": [7000],
                            },
                        },
                    )
                    store.download_outcome(key, status)
                scoped = store.for_client(second.id)
                secondary_drafts[name] = scoped.save_local_draft(
                    {**draft_payload, "form": {**draft_payload["form"], "title": "NAS draft"}}
                )
                queues[name] = store.queued_downloads()
            conversation = assistant.create_conversation(
                Conversation(
                    name="Keep this conversation",
                    folder="Fixture folder",
                    policy=Grant(
                        name="Fixture", clients=["default"], permissions=["queue", "downloads"]
                    ),
                ),
                require_provider=False,
            )
            messages = [
                {"role": "user", "content": "Keep this question"},
                {"role": "assistant", "content": "Keep this answer"},
            ]
            with assistant.db:
                assistant.db.execute(
                    "INSERT INTO runs (id,conversation_id,schedule_id,status,created,messages,"
                    "events,tokens,calls,error) VALUES (?,?,?,'completed',1,?,'[]',5,0,'')",
                    ("fixture-run", conversation["id"], "", json.dumps(messages)),
                )
            with agent.jobs.db:
                agent.jobs.db.execute(
                    "INSERT INTO jobs (id,kind,status,created,progress,result,error,client_id) "
                    "VALUES ('fixture-job','scan','running',1,'null','null','','default')"
                )
            agent.setup.secrets.update({"indexer-api-key": "fixture-secret-preserved"})
            upload = directory / "uploads" / "fixture"
            upload.mkdir(parents=True)
            (upload / "draft.nfo").write_text("Preserved upload attachment", encoding="utf-8")
            expected = {
                "settings": json.loads((directory / "settings.json").read_text()),
                "drafts": drafts,
                "secondary_drafts": secondary_drafts,
                "queues": queues,
                "second_client": second.id,
                "conversation": conversation["id"],
                "conversation_body": {k: v for k, v in conversation.items() if k != "id"},
                "messages": messages,
                "media": fingerprints(media),
                "uploads": fingerprints(directory / "uploads"),
            }
            manifest.write_text(json.dumps(expected, indent=2), encoding="utf-8")
        else:
            settings = Settings.load(directory / "settings.json")
            settings.save(directory / "roundtrip-settings.json")
            roundtrip = json.loads((directory / "roundtrip-settings.json").read_text())
            assert_preserved(roundtrip, expected["settings"])
            assert settings.language == "fr" and settings.theme == "dark"
            assert settings.qbit.host == "https://fixture.invalid"
            assert settings.library_folders == [LibraryFolder(media)]
            assert settings.path_mappings == [PathMapping(str(media), "/downloads")]
            assert settings.download_folders.default == str(media)
            assert len(settings.client_profiles) == 2
            second = settings.profile(expected["second_client"])
            assert second.name == "Fixture NAS" and second.client == TorrentClient.TRANSMISSION
            assert second.host == "https://fixture-nas.invalid"
            assert second.path_mappings == [PathMapping(str(media), "/storage")]
            for name, store in stores.items():
                before = expected["drafts"][name]
                after = store.local_draft(before["id"])
                assert after == before, (name, "Local Draft changed")
                assert store.for_client(second.id).local_drafts() == [
                    expected["secondary_drafts"][name]
                ]
                rows = {
                    key: (payload, status) for key, payload, status, _ in store.queued_downloads()
                }
                assert set(rows) == {"queued-fixture", "sending-fixture"}
                for key, payload, _, _ in expected["queues"][name]:
                    assert rows[key][0] == payload, (name, "Queue payload changed")
                assert rows["queued-fixture"][1] == "queued"
                assert rows["sending-fixture"][1] == "uncertain"
                assert rows["queued-fixture"][0]["folder"] == str(media)
                assert rows["queued-fixture"][0]["candidate"]["title"] == "Fixture book"
                assert not rows["sending-fixture"][0]["retry_safe"]
            conversation, _ = assistant.conversation(expected["conversation"])
            current_body = conversation.model_dump()
            for key, value in expected["conversation_body"].items():
                assert current_body[key] == value, ("Conversation settings changed", key)
            assert conversation.name == "Keep this conversation"
            assert conversation.folder == "Fixture folder"
            assert "downloads" in conversation.policy.permissions
            assert "queue" in conversation.policy.permissions
            assert (
                assistant.history(expected["conversation"])[0]["messages"] == expected["messages"]
            )
            assert agent.jobs.get("fixture-job")["status"] == "interrupted"
            assert agent.setup.secrets.get("indexer-api-key") == "fixture-secret-preserved"
            assert fingerprints(media) == expected["media"]
            assert fingerprints(directory / "uploads") == expected["uploads"]
            for db in (desktop_store._db, agent.setup.store._db, agent.jobs.db, assistant.db):
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        assistant.close()
        agent.jobs.close()
        if hasattr(agent, "media"):
            agent.media.close()
        agent.access.db.close()
        agent.setup.store._db.close()
        desktop_store._db.close()
        assert not CONNECTION_ATTEMPTS, "A background connection was attempted"


def archived_source(repo: Path, ref: str, destination: Path) -> None:
    data = subprocess.check_output(["git", "archive", ref, "src"], cwd=repo)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            target = destination / member.name
            assert target.resolve().is_relative_to(destination.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            assert stream is not None
            target.write_bytes(stream.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refs", nargs="+", default=["v0.12.2", "v1.0.0-beta.27"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=["seed", "check"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.directory, args.manifest)
        return
    repo = Path(__file__).resolve().parents[1]
    results = []
    with tempfile.TemporaryDirectory(prefix="tl-upgrade-check-") as temporary:
        root = Path(temporary)
        for index, ref in enumerate(args.refs):
            case = root / str(index)
            case.mkdir()
            old = case / "old-source"
            archived_source(repo, ref, old)
            original, backup, upgraded, restored = [
                case / n for n in ("original", "backup", "upgraded", "restored")
            ]
            manifest = case / "fixture.json"

            def run(
                mode: str, source: Path, directory: Path, *, manifest=manifest, case=case
            ) -> None:
                subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--worker",
                        mode,
                        "--directory",
                        str(directory),
                        "--manifest",
                        str(manifest),
                    ],
                    env={**os.environ, "PYTHONPATH": str(source / "src")},
                    cwd=case,
                    check=True,
                    timeout=60,
                )

            run("seed", old, original)
            pristine = fingerprints(original)
            # The producer has exited and closed its databases before copying.
            shutil.copytree(original, backup)
            shutil.copytree(original, upgraded)
            run("check", repo, upgraded)
            run("check", repo, upgraded)  # migrations/recovery remain stable on a second restart
            shutil.copytree(backup, restored)
            run("check", repo, restored)
            assert fingerprints(backup) == pristine
            assert fingerprints(original) == pristine
            results.append(
                {
                    "from": ref,
                    "source_commit": subprocess.check_output(
                        ["git", "rev-parse", f"{ref}^{{commit}}"], cwd=repo, text=True
                    ).strip(),
                    "upgrade": "passed",
                    "second_restart": "passed",
                    "offline_restore": "passed",
                    "backup_unchanged": True,
                    "network_connections": 0,
                }
            )
            print(f"{ref}: upgrade, restart and offline restore passed", flush=True)
    report = {
        "target_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "python": sys.version.split()[0],
        "results": results,
    }
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
