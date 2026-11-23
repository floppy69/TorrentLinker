"""Candidate decisions and offline evidence through the public Library boundary."""

import threading

from tests.test_reseed_workspace import workspace
from tests.torrents import make_torrent


def test_inspector_reviews_rejects_and_imports_provenance_without_client_changes(tmp_path):
    board, client, original, _, _ = workspace(tmp_path)
    library = board.library
    stop = threading.Event()
    rows = library.inspector(str(original), "review", stop)
    assert rows[0]["title"] == "Release.mkv"
    assert rows[0]["match"] == "full"
    assert rows[0]["files"][0]["local"] == original.name
    data = make_torrent(original)
    library.import_provenance(str(original), data, stop)
    assert library.inspector(str(original), "provenance", stop)[0]["status"] == "verified"
    original.write_bytes(b"changed")
    assert library.inspector(str(original), "provenance", stop)[0]["status"] == "stale"
    assert library.inspector(str(original), "reject", stop, key=rows[0]["key"]) == []
    assert library.inspector(str(original), "review", stop) == []
    assert not client.calls
