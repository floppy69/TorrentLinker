from pathlib import Path

import pytest

from tests.torrents import make_torrent
from torrentlinker.qbit import AlreadyInClient, QbitApi
from torrentlinker.torrent_meta import read_torrent


class Client:
    """qBittorrent's API refusing an add, with the torrent already listed or not."""

    def __init__(self, listed: bool) -> None:
        self.listed = listed

    def torrents_add(self, **kwargs: object) -> str:
        return "Fails."

    def torrents_info(self, torrent_hashes: str) -> list[object]:
        return [object()] if self.listed else []


def torrent(tmp_path: Path) -> bytes:
    (tmp_path / "book.epub").write_bytes(b"x" * 1000)
    return make_torrent(tmp_path / "book.epub")


@pytest.mark.parametrize("listed,error", [(True, AlreadyInClient), (False, RuntimeError)])
def test_a_refused_add_says_when_the_torrent_is_already_there(
    tmp_path: Path, listed: bool, error: type[Exception]
) -> None:
    api = QbitApi("http://127.0.0.1:1", "", "")
    api._client = Client(listed)
    data = torrent(tmp_path)
    assert read_torrent(data).infohash

    with pytest.raises(error) as raised:
        api.download(data, str(tmp_path), [])

    assert ("already in the Torrent Client" in str(raised.value)) == listed


class Recording:
    """qBittorrent's API accepting an add and keeping its arguments."""

    def __init__(self) -> None:
        self.added: dict[str, object] = {}

    def torrents_add(self, **kwargs: object) -> str:
        self.added = kwargs
        return "Ok."

    def torrents_info(self, torrent_hashes: str) -> list[object]:
        return [object()]


def test_a_reseed_is_checked_in_its_save_path_not_the_incomplete_folder(tmp_path: Path) -> None:
    # With "Keep incomplete torrents in" on, qBittorrent would check a renamed Reseed in
    # that folder, where its files are not, unless the add turns it off.
    api = QbitApi("http://127.0.0.1:1", "", "")
    api._client = client = Recording()

    api.add(torrent(tmp_path), str(tmp_path), [])

    assert client.added["use_download_path"] is False


def test_a_download_keeps_the_clients_incomplete_folder(tmp_path: Path) -> None:
    api = QbitApi("http://127.0.0.1:1", "", "")
    api._client = client = Recording()

    api.download(torrent(tmp_path), str(tmp_path), [])

    assert client.added.get("use_download_path") is None


class Synced:
    """qBittorrent's sync API: the whole list first, then only what changed."""

    def __init__(self) -> None:
        self.answers: list[dict[str, object]] = []
        self.rids: list[int] = []
        self.timeouts: list[object] = []
        self.busy = 0
        self.overlapped = False

    def sync_maindata(self, rid: int, requests_args: dict[str, object]) -> dict[str, object]:
        import time

        self.busy += 1
        self.overlapped |= self.busy > 1
        time.sleep(0.01)
        self.busy -= 1
        self.rids.append(rid)
        self.timeouts.append(requests_args["timeout"])
        return self.answers.pop(0) if self.answers else {"rid": rid + 1}


def entry(name: str, **changes: object) -> dict[str, object]:
    return {
        "name": name,
        "save_path": "/data",
        "tags": "",
        "progress": 1.0,
        "state": "stoppedUP",
        **changes,
    }


def test_listings_read_everything_once_then_only_what_changed() -> None:
    api = QbitApi("http://127.0.0.1:1", "", "")
    sync = Synced()
    sync.answers = [
        {"rid": 1, "full_update": True, "torrents": {"a": entry("A"), "b": entry("B")}},
        {"rid": 2, "torrents": {"a": {"state": "uploading", "num_complete": 7}}},
        {"rid": 3, "torrents_removed": ["b"]},
        {"rid": 9, "full_update": True, "torrents": {"c": entry("C")}},  # rid too old
    ]
    api._client = sync

    first = api.torrents(with_files=False)
    assert sorted(t.name for t in first) == ["A", "B"]
    [a, _] = sorted(api.torrents(with_files=False), key=lambda t: t.name)
    assert (a.hash, a.state, a.swarm_seeders, a.name) == ("a", "uploading", 7, "A")
    assert [t.name for t in api.torrents(with_files=False)] == ["A"]
    assert [t.name for t in api.torrents(with_files=False)] == ["C"]
    assert sync.rids == [0, 1, 2, 3]
    assert sync.timeouts[0] == (5, 300)  # a first listing of 15k torrents is slow


def test_listings_from_several_tasks_never_overlap() -> None:
    import threading

    api = QbitApi("http://127.0.0.1:1", "", "")
    sync = Synced()
    sync.answers = [{"rid": 1, "full_update": True, "torrents": {"a": entry("A")}}]
    api._client = sync
    threads = [threading.Thread(target=lambda: api.torrents(with_files=False)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not sync.overlapped
    assert len(sync.rids) == 6
