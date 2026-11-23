"""Tracker edits on disposable clients, using generated private torrents only."""

import os
import time

import torf

from torrentlinker.tracker_updates import Announce, fingerprint, normalized_tiers, plan_change


def check_tracker_updates(client, root):
    source = root / "tracker-check.bin"
    source.write_bytes(os.urandom(18000))
    torrent = torf.Torrent(path=source, private=True)
    torrent.trackers = [
        ["http://c411.org/fixture-old/announce"],
        ["http://unrelated.invalid/announce"],
    ]
    torrent.generate()
    identifier = client.add(bytes(torrent.dump()), str(root), [])
    try:
        deadline = time.monotonic() + 15
        while not client.torrent(identifier):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        for action, extra in [
            ("add-backup", {}),
            ("replace-host", {"source_host": "c411.org", "target_host": "next.c411.org"}),
            ("update-passkey", {"groups": [fingerprint("fixture-old")]}),
        ]:
            before = client.announce_entries(identifier)
            change = plan_change(
                before,
                action,
                configured=["c411.org", "tk.c411.tw"],
                target_host=extra.get("target_host", "tk.c411.tw"),
                source_host=extra.get("source_host", ""),
                groups=extra.get("groups", []),
                settings_announce="http://c411.org/fixture-new/announce",
            )
            assert change.changed
            client.apply_announces(identifier, change.before, change.after)
            observed = client.announce_entries(identifier)
            assert normalized_tiers(observed) == normalized_tiers(change.after)
            assert any(entry.url == "http://unrelated.invalid/announce" for entry in observed)
            client.reannounce(identifier)
            if action == "add-backup":
                assert observed[-1].url == "http://tk.c411.tw/fixture-old/announce"
                assert not plan_change(
                    observed,
                    action,
                    configured=["c411.org", "tk.c411.tw"],
                    target_host="tk.c411.tw",
                ).changed
        assert Announce("http://tk.c411.tw/fixture-new/announce", observed[-1].tier) in observed
    finally:
        client.remove(identifier)
