from dataclasses import replace
from pathlib import Path

import pytest

from tests.fake_qbit import FakeQbit
from tests.test_qbit_unit import Synced, entry
from torrentlinker.category_tags import category_tag
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.qbit import QbitApi
from torrentlinker.reseed import VERIFYING
from torrentlinker.torrent_management import (
    category_labels,
    manage,
    safe_error,
    status,
    torrent_categories,
    tracker_groups,
    tracker_hosts,
)


def torrent(hash="a", **kwargs):
    return Torrent(hash, f"Torrent {hash}", Path("/seedbox/downloads"), **kwargs)


def test_tracker_identity_does_not_use_personal_tags_or_leak_passkeys():
    t = torrent(
        tags=frozenset({"c411"}), tracker="https://Elsewhere.EXAMPLE/secret/announce?k=pass"
    )
    assert tracker_hosts(t) == ("elsewhere.example",)
    assert tracker_hosts(torrent(tags=frozenset({"c411"}))) == ("",)
    t = replace(
        t,
        trackers=(
            "udp://second.example:6969/announce",
            "https://user:password@elsewhere.example/private",
            "https://[broken",
        ),
    )
    assert tracker_hosts(t) == ("elsewhere.example", "second.example")
    assert "secret" not in safe_error(RuntimeError("failed https://tracker/secret?key=abc"))


def test_category_names_with_slashes_remain_real_taxonomy_nodes():
    categories = {
        7000: IndexerCategory("Ebook"),
        7010: IndexerCategory("Books / Manuals", parent=7000),
    }
    tag = category_tag(7010, categories)
    assert torrent_categories(torrent(tags=frozenset({tag})), category_labels(categories)) == (
        ("Ebook", "Books / Manuals"),
    )
    assert torrent_categories(torrent(category="Media/Books"), {}) == (("Media", "Books"),)
    assert torrent_categories(torrent(tags=frozenset({"my-books"})), {}) == ((),)


def test_mirror_grouping_preserves_announce_hosts_and_unrelated_trackers():
    t = torrent(
        trackers=(
            "https://c411.org/announce/private",
            "https://TK.C411.TW./announce/private",
            "https://tk.c411.tw.attacker.test/announce",
            "https://elsewhere.example/announce",
        )
    )
    assert tracker_groups(t) == ("c411.org", "elsewhere.example", "tk.c411.tw.attacker.test")
    assert "tk.c411.tw" in tracker_hosts(t)
    assert tracker_groups(torrent(tags=frozenset({"c411"}))) == ("",)


def test_qbit_sync_tracks_all_announce_memberships_and_removals():
    api = QbitApi("http://127.0.0.1:1", "", "")
    sync = Synced()
    sync.answers = [
        {
            "rid": 1,
            "full_update": True,
            "torrents": {"a": entry("A")},
            "trackers": {"https://one.example/secret": ["a"], "udp://two.example/announce": ["a"]},
        },
        {"rid": 2, "trackers_removed": ["https://one.example/secret"]},
        {"rid": 3, "trackers": {"udp://two.example/announce": []}},
        {"rid": 4, "full_update": True, "torrents": {"a": entry("A")}},
    ]
    api._client = sync
    assert tracker_hosts(api.torrents(with_files=False)[0]) == ("one.example", "two.example")
    assert tracker_hosts(api.torrents(with_files=False)[0]) == ("two.example",)
    assert tracker_hosts(api.torrents(with_files=False)[0]) == ("",)
    assert tracker_hosts(api.torrents(with_files=False)[0]) == ("",)


def test_actions_deduplicate_protect_verification_and_keep_files():
    client = FakeQbit(by_hash={"a": torrent(), "b": torrent("b", tags=frozenset({VERIFYING}))})
    results = manage(client, ["a", "a", "b", "gone"], "remove")
    assert [r.outcome for r in results] == ["sent", "verifying", "missing"]
    assert client.removed == [("a", False)]
    assert "b" in client.by_hash


def test_batch_action_continues_after_one_failure():
    class FailingClient(FakeQbit):
        def pause(self, hash):
            if hash == "a":
                raise RuntimeError("unavailable")
            super().pause(hash)

    client = FailingClient(by_hash={"a": torrent(), "b": torrent("b")})
    assert [r.outcome for r in manage(client, ["a", "b"], "pause")] == ["failed", "sent"]
    assert status(client.by_hash["b"]) == "paused"


def test_empty_file_selection_cannot_mean_all_files():
    client = FakeQbit(by_hash={"a": torrent()})
    assert manage(client, ["a"], "skip_files") == []
    assert client.priorities == {}
    manage(client, ["a"], "skip_files", file_indexes=[2])
    assert client.priorities == {"a": {2: 0}}


def test_qbit_file_listing_keeps_real_file_indexes():
    from unittest.mock import Mock

    api = QbitApi("http://127.0.0.1:1", "", "")
    api._client = Mock()
    api._client.torrents_files.return_value = [
        {"index": 0, "name": "first", "size": 10, "priority": 1},
        {"index": 2, "name": "third", "size": 20, "priority": 0},
    ]
    assert [(f.index, f.wanted) for f in api.file_listing("a")] == [(0, True), (2, False)]
    api.pause("a")
    api._client.torrents_stop.assert_called_once_with(torrent_hashes="a")


def test_deluge_management_resume_keeps_user_limits_and_pause_targets_selection():
    from unittest.mock import Mock

    from torrentlinker.deluge import DelugeApi

    api = DelugeApi("http://127.0.0.1:1", "")
    api._call = Mock()
    api.resume("a")
    api._call.assert_called_once_with("core.resume_torrent", "a")
    api._call.reset_mock()
    api.pause("a")
    api._call.assert_called_once_with("core.pause_torrent", ["a"])


def test_transmission_management_stop_targets_selection():
    from unittest.mock import Mock

    from torrentlinker.transmission import TransmissionApi

    api = TransmissionApi("http://127.0.0.1:1", "", "")
    api._call = Mock()
    api.pause("a")
    api._call.assert_called_once_with("torrent-stop", ids=["a"])


def test_explicit_delete_removes_data_once_and_protects_verifying_torrents():
    client = FakeQbit(by_hash={"a": torrent(), "b": torrent("b", tags=frozenset({VERIFYING}))})
    results = manage(client, ["a", "a", "b", "gone"], "delete")
    assert [r.outcome for r in results] == ["sent", "verifying", "missing"]
    assert client.removed == [("a", True)]
    assert "b" in client.by_hash


@pytest.mark.parametrize("delete_files", [False, True])
def test_all_client_adapters_send_explicit_data_deletion_flag(delete_files):
    from unittest.mock import Mock

    from torrentlinker.deluge import DelugeApi
    from torrentlinker.paths import MappedQbit, PathMapper
    from torrentlinker.transmission import TransmissionApi
    from torrentlinker.utorrent import UtorrentApi

    qbit = QbitApi("http://127.0.0.1:1", "", "")
    qbit._client = Mock()
    qbit.remove("a", delete_files=delete_files)
    qbit._client.torrents_delete.assert_called_once_with(
        delete_files=delete_files, torrent_hashes="a"
    )
    deluge = DelugeApi("http://127.0.0.1:1", "")
    deluge._call = Mock()
    deluge.remove("a", delete_files=delete_files)
    deluge._call.assert_called_once_with("core.remove_torrent", "a", delete_files)
    transmission = TransmissionApi("http://127.0.0.1:1", "", "")
    transmission._call = Mock()
    transmission.remove("a", delete_files=delete_files)
    transmission._call.assert_called_once_with(
        "torrent-remove", ids=["a"], **{"delete-local-data": delete_files}
    )
    utorrent = UtorrentApi("http://127.0.0.1:1", "", "")
    utorrent._action = Mock()
    utorrent.remove("a", delete_files=delete_files)
    utorrent._action.assert_called_once_with("removedata" if delete_files else "remove", "a")
    client = FakeQbit(by_hash={"a": torrent()})
    MappedQbit(client, PathMapper([])).remove("a", delete_files=delete_files)
    assert client.removed == [("a", delete_files)]
