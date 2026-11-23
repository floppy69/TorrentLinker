"""Evidence is exposed through the public Library workflow without changing media."""

import threading
from dataclasses import replace

import pytest

from tests.test_upload_video import recorded
from torrentlinker.domain import LibraryFolder
from torrentlinker.library import build_library
from torrentlinker.matching import IgnoreList
from torrentlinker.web.library import Library
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup


def library_at(tmp_path):
    root, config = tmp_path / "media", tmp_path / "config"
    root.mkdir()
    config.mkdir()
    setup = Setup(config, (root,), ServerSecrets(config))
    setup.settings.library_folders = [LibraryFolder(root)]
    library = Library(setup)
    return library, root


def scan(library):
    library.entries = build_library(
        library.setup.settings.library_folders, [], IgnoreList.default()
    )


def test_library_reports_claim_and_observation_without_changing_file(tmp_path):
    library, root = library_at(tmp_path)
    video = root / "Film.1080p.WEB-DL.DDP5.1.H264-TEAM.mkv"
    video.write_bytes(b"unchanged")
    scan(library)
    facts = replace(recorded("film_x264_1080p_fr"), width=1280, height=720)
    result = library.evidence(str(video), threading.Event(), reader=lambda path: facts)
    conflict = next(row for row in result["observations"] if row["field"] == "resolution")
    assert (conflict["claim"], conflict["observed"], conflict["source"]) == (
        "1080p",
        "720p",
        "filename",
    )
    assert video.read_bytes() == b"unchanged"


def test_embedded_title_is_a_claim_and_handbrake_is_only_a_hint(tmp_path):
    library, root = library_at(tmp_path)
    video = root / "renamed.mkv"
    video.write_bytes(b"media")
    scan(library)
    facts = replace(
        recorded("film_x264_1080p_fr"),
        width=1280,
        height=720,
        title="Film.1080p.WEB-DL",
        writing_application="HandBrake 1.8",
    )
    rows = library.evidence(str(video), threading.Event(), reader=lambda path: facts)[
        "observations"
    ]
    assert {(r["field"], r["source"], r["confidence"]) for r in rows} == {
        ("resolution", "embedded-title", "measured"),
        ("processing", "writing-application", "hint"),
    }


def test_cropped_video_and_an_available_audio_track_do_not_conflict(tmp_path):
    library, root = library_at(tmp_path)
    video = root / "Film.1080p.WEB-DL.x264.AC3.mkv"
    video.write_bytes(b"media")
    scan(library)
    facts = replace(recorded("film_x264_1080p_fr"), width=1920, height=800)
    assert (
        library.evidence(str(video), threading.Event(), reader=lambda path: facts)["observations"]
        == []
    )


def test_old_torrent_import_is_offline_and_hash_verified_against_renamed_file(tmp_path):
    from tests.torrents import make_torrent

    library, root = library_at(tmp_path)
    old = root / "Original.1080p-TEAM.mkv"
    old.write_bytes(b"video" * 10000)
    data = make_torrent(old)
    renamed = old.rename(root / "renamed.mkv")
    scan(library)
    result = library.import_provenance(str(renamed), data, threading.Event())
    assert result["status"] == "verified"
    assert result["files"][0]["original"] == "Original.1080p-TEAM.mkv"
    assert result["files"][0]["local"] == "renamed.mkv"
    assert renamed.read_bytes() == b"video" * 10000
    assert library.provenance(str(renamed))[0]["status"] == "verified"


def test_same_size_wrong_bytes_never_become_verified_provenance(tmp_path):
    from tests.torrents import make_torrent

    library, root = library_at(tmp_path)
    video = root / "original.mkv"
    video.write_bytes(b"A" * 40000)
    data = make_torrent(video)
    video.write_bytes(b"B" * 40000)
    scan(library)
    row = library.import_provenance(str(video), data, threading.Event())
    assert row["status"] == "unverified"
    assert row["missing_bytes"] == 40000


def test_changed_file_invalidates_saved_provenance(tmp_path):
    from tests.torrents import make_torrent

    library, root = library_at(tmp_path)
    video = root / "original.mkv"
    video.write_bytes(b"A" * 40000)
    data = make_torrent(video)
    scan(library)
    library.import_provenance(str(video), data, threading.Event())
    video.write_bytes(b"B" * 40000)
    assert library.provenance(str(video))[0]["status"] == "stale"


def test_equal_size_ambiguous_files_require_a_decision(tmp_path):
    from tests.torrents import make_torrent

    library, root = library_at(tmp_path)
    pack = root / "pack"
    pack.mkdir()
    first = pack / "original.mkv"
    first.write_bytes(b"A" * 40000)
    data = make_torrent(first)
    first.rename(pack / "one.mkv")
    (pack / "two.mkv").write_bytes(b"A" * 40000)
    scan(library)
    assert library.import_provenance(str(pack), data, threading.Event())["status"] == "ambiguous"


def test_seeded_pack_can_find_and_check_a_smaller_episode(tmp_path, monkeypatch):
    from tests.torrents import make_torrent
    from torrentlinker.domain import ContentKind, ItemState
    from torrentlinker.indexer import Candidate, SearchMode
    from torrentlinker.torrent_meta import read_torrent

    library, root = library_at(tmp_path)
    pack = root / "Example.Show"
    pack.mkdir()
    episode = pack / "Example.Show.S01E01.mkv"
    episode.write_bytes(b"A" * 40000)
    (pack / "Example.Show.S01E02.mkv").write_bytes(b"B" * 80000)
    data = make_torrent(episode)
    meta = read_torrent(data)
    hit = Candidate("Example.Show.S01E01", 40000, "https://example/dl", infohash=meta.infohash)
    library.setup.settings.library_folders = [LibraryFolder(root, kind=ContentKind.SERIES)]
    scan(library)
    library.entries = [replace(library.entries[0], state=ItemState.SEEDED)]

    class Indexer:
        def supported_modes(self):
            return {SearchMode.TV: {"q", "season", "ep"}}

        def search(self, query):
            return [hit] if query.ep == 1 else []

        def fetch_torrent(self, candidate):
            return data

        def redact(self, value):
            return value

        def website_url(self, candidate):
            return ""

        url = "https://example/api"
        is_c411 = False

    monkeypatch.setattr(library.setup, "indexer", lambda: Indexer())
    rows = library.compatible(str(pack), threading.Event(), lambda value: None)
    assert len(rows) == 1
    assert rows[0]["match"] == "full"
    assert rows[0]["files"][0]["local"] == "Example.Show/Example.Show.S01E01.mkv"


def test_near_match_diagnostic_counts_valid_bytes_without_modifying_original(tmp_path):
    import random

    from tests.torrents import make_torrent
    from torrentlinker.indexer import Candidate
    from torrentlinker.torrent_meta import read_torrent

    library, root = library_at(tmp_path)
    video = root / "Film.mkv"
    original = random.Random(43).randbytes(1024 * 1024)
    video.write_bytes(original)
    data = make_torrent(video)
    meta = read_torrent(data)
    video.write_bytes(b"X" * 128 + original[128:])
    scan(library)
    candidate = Candidate(
        "Film", len(original), "https://example/dl", seeders=2, infohash=meta.infohash
    )
    result = library.diagnose(str(video), candidate, data, threading.Event())
    assert result["verified_bytes"] == len(original) - meta.piece_length
    assert result["size_difference"] == 0
    assert result["eligible"] is True
    assert result["status"] == "awaiting-confirmation"
    assert video.read_bytes() == b"X" * 128 + original[128:]


@pytest.mark.parametrize("invalidate", [False, True])
def test_repair_requires_completed_client_check_and_confirmation_and_preserves_original(
    tmp_path, invalidate
):
    import pytest

    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.indexer import Candidate
    from torrentlinker.torrent_meta import read_torrent

    library, root = library_at(tmp_path)
    video = root / "Film.mkv"
    video.write_bytes(b"A" * 1024 * 1024)
    data = make_torrent(video)
    meta = read_torrent(data)
    video.write_bytes(b"B" * 128 + b"A" * (1024 * 1024 - 128))
    original = video.read_bytes()
    scan(library)
    candidate = Candidate(
        "Film", len(original), "https://example/dl", seeders=2, infohash=meta.infohash
    )
    report = library.diagnose(str(video), candidate, data, threading.Event())
    client = FakeQbit()
    copies = root / "copies"
    copies.mkdir()
    with pytest.raises(ValueError, match="experimental"):
        library.prepare_repair(report["id"], str(copies), threading.Event(), client=client)
    assert list(copies.iterdir()) == []
    prepared = library.prepare_repair(
        report["id"], str(copies), threading.Event(), client=client, experimental=True
    )
    assert prepared["status"] == "checking"
    assert client.started == []
    with pytest.raises(ValueError):
        library.start_repair(report["id"], report["id"], client=client)
    client.by_hash[meta.infohash] = replace(client.by_hash[meta.infohash], state="stoppedDL")
    client.pieces[meta.infohash] = [0] + [2] * (len(original) // meta.piece_length - 1)
    assert library.refresh_repair(report["id"], client=client)["status"] == "ready"
    if invalidate:
        client.pieces[meta.infohash] = [0] * (len(original) // meta.piece_length)
        with pytest.raises(ValueError):
            library.start_repair(report["id"], report["id"], client=client)
        assert client.started == []
        assert library.refresh_repair(report["id"], client=client)["status"] == "needs-review"
        return
    with pytest.raises(ValueError):
        library.start_repair(report["id"], "", client=client)
    assert (
        library.start_repair(report["id"], report["id"], client=client)["status"] == "downloading"
    )
    assert client.started == [meta.infohash]
    with pytest.raises(ValueError):
        library.start_repair(report["id"], report["id"], client=client)
    assert video.read_bytes() == original
    assert video.stat().st_ino != __import__("pathlib").Path(prepared["copy"]).stat().st_ino


def test_selected_seasons_share_a_virtual_manifest_without_copying_files(tmp_path):
    library, root = library_at(tmp_path)
    for season in ("S01", "S02"):
        folder = root / season
        folder.mkdir()
        (folder / f"Show.{season}E01.mkv").write_bytes(season.encode() * 100)
    scan(library)
    selected = library.combine([str(root / "S01"), str(root / "S02")], threading.Event())
    entry = library.entry(selected["path"])
    assert entry.item.files == {"S01/Show.S01E01.mkv": 300, "S02/Show.S02E01.mkv": 300}
    assert not entry.item.path.exists()
    assert sorted(p.name for p in root.iterdir()) == ["S01", "S02"]
    rows = library.rows()
    group = next(row for row in rows if row["path"] == selected["path"])
    assert group["members"] == [str(root / "S01"), str(root / "S02")]
    assert group["state"] == "orphan"
    assert group["size"] == 600
    assert {str(root / "S01"), str(root / "S02")} <= {row["path"] for row in rows}


def test_import_refuses_invalid_metadata_and_never_persists_tracker_secrets(tmp_path):
    import io

    import pytest
    import torf

    from tests.torrents import make_torrent

    library, root = library_at(tmp_path)
    video = root / "film.mkv"
    video.write_bytes(b"A" * 40000)
    torrent = torf.Torrent.read_stream(io.BytesIO(make_torrent(video)))
    torrent.trackers = ["https://tracker.invalid/private-passkey/announce"]
    data = torrent.dump()
    scan(library)
    result = library.import_provenance(str(video), data, threading.Event())
    assert result["status"] == "verified"
    assert (
        b"private-passkey"
        not in (library.setup.store.torrent_dir.parent / "library-evidence.sqlite").read_bytes()
    )
    with pytest.raises(ValueError, match="metadata"):
        library.import_provenance(str(video), b"not a torrent", threading.Event())


def test_combining_inconsistent_nas_mappings_is_refused(tmp_path):
    import pytest

    from torrentlinker.domain import PathMapping

    library, root = library_at(tmp_path)
    for name in ("Season1", "Season2"):
        folder = root / name
        folder.mkdir()
        (folder / "episode.mkv").write_bytes(b"data")
    scan(library)
    library.setup.settings.path_mappings = [PathMapping(str(root / "Season1"), "/unrelated")]
    with pytest.raises(ValueError, match="consistent Path Mapping"):
        library.combine([str(root / "Season1"), str(root / "Season2")], threading.Event())


def test_audio_claim_must_match_one_track_and_hdr_formats_stay_distinct(tmp_path):
    library, root = library_at(tmp_path)
    video = root / "Film.DDP5.1.DV.HDR10+.mkv"
    video.write_bytes(b"media")
    scan(library)
    facts = recorded("film_x264_1080p_fr")
    facts = replace(
        facts,
        hdr10=True,
        hdr10plus=False,
        dv_profile=0,
        audio=(
            replace(facts.audio[0], codec="EAC3", channels=2),
            replace(facts.audio[0], codec="AC3", channels=6),
        ),
    )
    rows = library.evidence(str(video), threading.Event(), reader=lambda path: facts)[
        "observations"
    ]
    assert any(r["field"] == "audio-channels" for r in rows)
    assert {r["claim"] for r in rows if r["field"] == "hdr"} == {"Dolby Vision", "HDR10+"}


def test_combined_seasons_discover_by_show_identity(tmp_path, monkeypatch):
    from torrentlinker.domain import ContentKind
    from torrentlinker.indexer import SearchMode

    library, root = library_at(tmp_path)
    library.setup.settings.library_folders = [LibraryFolder(root, kind=ContentKind.SERIES)]
    for season in ("S01", "S02"):
        folder = root / season
        folder.mkdir()
        (folder / f"Example.Show.{season}E01.mkv").write_bytes(b"data")
    scan(library)
    row = library.combine([str(root / "S01"), str(root / "S02")], threading.Event())
    queries = []

    class Indexer:
        def supported_modes(self):
            return {SearchMode.TV: {"q", "season", "ep"}}

        def search(self, query):
            queries.append(query)
            return []

    monkeypatch.setattr(library.setup, "indexer", lambda: Indexer())
    library.compatible(row["path"], threading.Event(), lambda value: None)
    assert queries and {q.q for q in queries} == {"Example Show"}
    assert {(q.season, q.ep) for q in queries} >= {(None, None), (1, 1), (2, 1)}
