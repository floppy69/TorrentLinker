import pytest

from tests.test_deluge_unit import FakeWebUi, torrent
from tests.test_deluge_unit import api_for as deluge_api
from tests.test_qbit_unit import Synced, entry
from tests.test_transmission_unit import FakeRpc, pack
from tests.test_transmission_unit import api_for as transmission_api
from tests.test_utorrent_unit import WebUI
from tests.test_utorrent_unit import api_for as utorrent_api
from torrentlinker.qbit import QbitApi
from torrentlinker.torrent_management import peer_count_text


def test_qbit_swarm_counts_survive_partial_sync_updates():
    api = QbitApi("http://127.0.0.1:1", "", "")
    sync = Synced()
    sync.answers = [
        {
            "rid": 1,
            "full_update": True,
            "torrents": {
                "a": entry("A", num_complete=42, num_incomplete=13, num_seeds=2, num_leechs=3)
            },
        },
        {"rid": 2, "torrents": {"a": {"num_incomplete": 0}}},
        {"rid": 3, "torrents": {"a": {"num_complete": -1, "num_incomplete": -1}}},
    ]
    api._client = sync
    first = api.torrents(with_files=False)[0]
    assert (
        first.connected_seeds,
        first.swarm_seeders,
        first.connected_peers,
        first.swarm_peers,
    ) == (2, 42, 3, 13)
    second = api.torrents(with_files=False)[0]
    assert (second.swarm_seeders, second.swarm_peers) == (42, 0)
    third = api.torrents(with_files=False)[0]
    assert (third.swarm_seeders, third.swarm_peers) == (-1, -1)


def test_deluge_requests_swarm_peer_totals(tmp_path):
    web = FakeWebUi()
    api = deluge_api(web)
    h = api.download(torrent(tmp_path), "/downloads", [])
    web.torrents[h].update(num_seeds=2, total_seeds=42, num_peers=3, total_peers=13)
    result = api.torrents(with_files=False)[0]
    assert (
        result.connected_seeds,
        result.swarm_seeders,
        result.connected_peers,
        result.swarm_peers,
    ) == (2, 42, 3, 13)


def test_transmission_counts_idle_connected_peers_and_does_not_sum_mirrors(tmp_path):
    rpc = FakeRpc()
    api = transmission_api(rpc)
    h = api.download(pack(tmp_path, "book.epub"), "/downloads", [])
    rpc.torrents[h].update(
        peers=[{"progress": 1}, {"progress": 0.2}, {"progress": 0.5}],
        peersSendingToUs=0,
        peersGettingFromUs=0,
        trackerStats=[
            {"seederCount": 42, "leecherCount": 13},
            {"seederCount": 42, "leecherCount": 13},
        ],
    )
    result = api.torrents(with_files=False)[0]
    assert (
        result.connected_seeds,
        result.swarm_seeders,
        result.connected_peers,
        result.swarm_peers,
    ) == (1, 42, 2, 13)
    rpc.torrents[h].update(peers=[], trackerStats=[{"seederCount": -1, "leecherCount": -1}])
    result = api.torrents(with_files=False)[0]
    assert (
        result.connected_seeds,
        result.swarm_seeders,
        result.connected_peers,
        result.swarm_peers,
    ) == (0, -1, 0, -1)


def test_utorrent_reads_both_swarm_columns():
    result = utorrent_api(WebUI()).torrents(with_files=False)[0]
    assert (
        result.connected_seeds,
        result.swarm_seeders,
        result.connected_peers,
        result.swarm_peers,
    ) == (3, 4, 1, 2)


@pytest.mark.parametrize(
    "connected,total,text", [(0, 0, "0 (0)"), (0, -1, "0 (?)"), (-1, 42, "? (42)")]
)
def test_unknown_counts_are_not_zero(connected, total, text):
    assert peer_count_text(connected, total) == text
