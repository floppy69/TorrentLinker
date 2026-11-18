import unicodedata
from pathlib import Path

import pytest

from tests.fake_qbit import FakeQbit
from tests.torrents import make_torrent
from torrentlinker.domain import LocalItem
from torrentlinker.matching import match
from torrentlinker.reseed import (
    PARTIAL,
    TAG,
    VERIFYING,
    Outcome,
    ReseedAborted,
    check_verifications,
    start_reseed,
)
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent


def ebook(tmp_path: Path) -> tuple[LocalItem, bytes]:
    lib = tmp_path / "E-Book"
    lib.mkdir()
    f = lib / "Le joueur d'echecs - Stefan Zweig.epub"
    f.write_bytes(b"z" * 67163)
    return LocalItem(f, {f.name: 67163}), make_torrent(f)


def test_reseed_adds_the_torrent_stopped_at_the_item_location_and_forces_a_check(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    t = qbit.torrent(h)
    assert t is not None
    assert t.save_path == item.save_path
    assert {TAG, VERIFYING} <= t.tags
    assert qbit.rechecked == [h]
    assert qbit.started == []


def test_torrent_is_started_once_verification_reaches_100_percent(tmp_path: Path) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    assert check_verifications(qbit, store) == []  # still checking

    qbit.finish_check(h, 1.0)
    outcomes = check_verifications(qbit, store)

    assert outcomes == [Outcome(item.path, h, verified=True, progress=1.0, started=True)]
    assert qbit.started == [h]
    assert VERIFYING not in qbit.by_hash[h].tags


def test_failed_verification_removes_the_torrent_keeps_data_and_records_a_rejection(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    qbit.finish_check(h, 0.973)

    outcomes = check_verifications(qbit, store, now=lambda: 1e12)

    assert outcomes == [Outcome(item.path, h, verified=False, progress=0.973, started=False)]
    assert qbit.removed == [(h, False)]
    assert item.path.read_bytes() == b"z" * 67163
    assert store.rejections(item.path) == {meta.infohash: "Verification failed at 97.3%"}


def test_a_stopped_torrent_right_after_the_recheck_request_is_not_judged_yet(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    qbit.finish_check(h, 0.0)  # e.g. qBittorrent has not picked the recheck up yet

    assert check_verifications(qbit, store) == []
    assert h in qbit.by_hash


def test_reseeding_a_torrent_already_in_qbittorrent_is_refused(tmp_path: Path) -> None:
    import pytest

    from torrentlinker.reseed import AlreadyInClient

    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    with pytest.raises(AlreadyInClient):
        start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]


def test_torrent_files_are_renamed_to_the_local_names_before_verification(
    tmp_path: Path,
) -> None:
    item, _ = ebook(tmp_path)
    scene = tmp_path / "scene" / "Le.Joueur.D'echecs.Stefan.Zweig.2013.FR.[EPUB]-NOTAG.epub"
    scene.parent.mkdir()
    scene.write_bytes(b"z" * 67163)
    meta = read_torrent(make_torrent(scene))
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    assert qbit.by_hash[h].files == {item.path.name: 67163}
    assert qbit.calls == [f"rename {scene.name} -> {item.path.name}", "recheck"]


def test_root_folder_and_layout_differences_are_renamed_file_by_file(tmp_path: Path) -> None:
    src = tmp_path / "scene" / "Show.S01"
    (src / "Subs").mkdir(parents=True)
    (src / "Show.S01E01.mkv").write_bytes(b"a" * 1000)
    (src / "Subs" / "Show.S01E01.srt").write_bytes(b"b" * 10)
    meta = read_torrent(make_torrent(src))
    show = tmp_path / "lib" / "My Show"
    show.mkdir(parents=True)
    (show / "E01.mkv").write_bytes(b"a" * 1000)
    (show / "E01.srt").write_bytes(b"b" * 10)
    item = LocalItem(show, {"My Show/E01.mkv": 1000, "My Show/E01.srt": 10})
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    assert qbit.by_hash[h].files == {"My Show/E01.mkv": 1000, "My Show/E01.srt": 10}


def test_swapped_names_are_renamed_without_collisions(tmp_path: Path) -> None:
    from torrentlinker.matching import Match
    from torrentlinker.reseed import rename_plan

    m = Match({"S/a.mkv": "S/b.mkv", "S/b.mkv": "S/a.mkv"})
    files = {"S/a.mkv": 1, "S/b.mkv": 2}
    for old, new in rename_plan(m, set(files)):
        assert new not in files, f"{new} would overwrite another file"
        files[new] = files.pop(old)

    assert files == {"S/b.mkv": 1, "S/a.mkv": 2}


def test_reseed_refuses_occupied_rename_sources_before_changing_the_client(tmp_path: Path) -> None:
    source, local = tmp_path / "source" / "Show", tmp_path / "library" / "Show"
    source.mkdir(parents=True)
    local.mkdir(parents=True)
    (source / "a.mkv").write_bytes(b"a" * 40)
    (source / "b.mkv").write_bytes(b"b" * 50)
    (local / "a.mkv").write_bytes(b"b" * 50)
    (local / "b.mkv").write_bytes(b"a" * 40)
    meta, item = read_torrent(make_torrent(source)), scan_item(local)
    found = match(item, meta.files)
    assert found is not None
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    with pytest.raises(ReseedAborted, match="would move an existing local path"):
        start_reseed(qbit, store, item, meta, found, meta.infohash)

    assert qbit.torrents() == [] and qbit.removed == [] and qbit.calls == []
    assert store.verification_hashes() == []
    assert (local / "a.mkv").read_bytes() == b"b" * 50
    assert (local / "b.mkv").read_bytes() == b"a" * 40
    assert sorted(p.name for p in local.iterdir()) == ["a.mkv", "b.mkv"]


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("torrent_form,local_form", [("NFC", "NFD"), ("NFD", "NFC")])
def test_reseed_does_not_rename_unicode_aliases_on_a_normalizing_filesystem(
    tmp_path: Path, monkeypatch, nested, torrent_form, local_form
) -> None:
    library = tmp_path / "library"
    relative = "Série/Héros.mkv" if nested else "Héros.mkv"
    local = library / relative
    local.parent.mkdir(parents=True)
    local.write_bytes(b"movie" * 4000)
    source = tmp_path / "source" / unicodedata.normalize(torrent_form, relative)
    source.parent.mkdir(parents=True)
    source.write_bytes(local.read_bytes())
    meta = read_torrent(make_torrent(source.parent if nested else source))
    spelling = unicodedata.normalize(local_form, relative)
    item_path = library / (spelling.split("/")[0] if nested else spelling)
    item = LocalItem(item_path, {spelling: local.stat().st_size})
    # Model macOS lookup semantics while retaining the different directory-entry
    # and torrent spellings. Both names resolve to this one real file.
    original_stat, original_lstat = Path.stat, Path.lstat

    def lookup(path):
        if path.is_relative_to(library):
            return library / unicodedata.normalize("NFC", path.relative_to(library).as_posix())
        return path

    monkeypatch.setattr(Path, "stat", lambda path, **kw: original_stat(lookup(path), **kw))
    monkeypatch.setattr(Path, "lstat", lambda path: original_lstat(lookup(path)))
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    found = match(item, meta.files)
    assert found is not None

    h = start_reseed(qbit, store, item, meta, found, meta.infohash, sleep=lambda _: None)

    assert qbit.calls == ["recheck"]
    assert qbit.files(h) == meta.files
    qbit.finish_check(h, 1.0)
    assert check_verifications(qbit, store)[0].started
    assert local.read_bytes() == b"movie" * 4000
    assert [p.name for p in local.parent.iterdir()] == [local.name]


@pytest.mark.parametrize("source_kind", ["different-file", "symlink", "dangling-symlink"])
def test_unicode_equivalence_never_bypasses_an_occupied_source(tmp_path, source_kind):
    local = tmp_path / "library" / "He\u0301ros.mkv"
    local.parent.mkdir()
    local.write_bytes(b"movie" * 4000)
    old = local.with_name("Héros.mkv")
    if old.exists():
        pytest.skip("requires a filesystem with distinct composed and decomposed names")
    if source_kind == "different-file":
        old.write_bytes(b"other" * 4000)
    else:
        old.symlink_to(local if source_kind == "symlink" else tmp_path / "missing")
    source = tmp_path / "source" / old.name
    source.parent.mkdir()
    source.write_bytes(local.read_bytes())
    meta, item = read_torrent(make_torrent(source)), scan_item(local)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    found = match(item, meta.files)
    assert found is not None

    with pytest.raises(ReseedAborted, match="would move an existing local path"):
        start_reseed(qbit, store, item, meta, found, meta.infohash, sleep=lambda _: None)

    assert qbit.torrents() == [] and qbit.calls == []
    assert store.verification_hashes() == []
    assert local.read_bytes() == b"movie" * 4000


def test_unicode_names_on_a_normalization_sensitive_filesystem_are_still_renamed(tmp_path):
    local = tmp_path / "library" / "He\u0301ros.mkv"
    local.parent.mkdir()
    local.write_bytes(b"movie" * 4000)
    if local.with_name("Héros.mkv").exists():
        pytest.skip("requires a normalization-sensitive filesystem")
    source = tmp_path / "source" / "Héros.mkv"
    source.parent.mkdir()
    source.write_bytes(local.read_bytes())
    meta, item = read_torrent(make_torrent(source)), scan_item(local)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    found = match(item, meta.files)
    assert found is not None

    start_reseed(qbit, store, item, meta, found, meta.infohash, sleep=lambda _: None)

    assert qbit.calls == [f"rename {source.name} -> {local.name}", "recheck"]
    assert local.read_bytes() == b"movie" * 4000


def test_native_filesystem_unicode_alias_can_reseed_without_a_rename(tmp_path):
    local = tmp_path / "library" / "Héros.mkv"
    local.parent.mkdir()
    local.write_bytes(b"movie" * 4000)
    alias = local.with_name(unicodedata.normalize("NFD", local.name))
    if not alias.exists() or not alias.samefile(local):
        pytest.skip("requires a normalizing filesystem, such as macOS APFS")
    meta = read_torrent(make_torrent(local))
    item = scan_item(alias)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    found = match(item, meta.files)
    assert found is not None

    h = start_reseed(qbit, store, item, meta, found, meta.infohash, sleep=lambda _: None)

    assert qbit.calls == ["recheck"]
    qbit.finish_check(h, 1.0)
    assert check_verifications(qbit, store)[0].started
    assert local.read_bytes() == b"movie" * 4000


def partial_pack(tmp_path: Path) -> tuple[LocalItem, bytes]:
    # torf uses 16 KiB pieces here: episode 2 starts inside piece 1.
    src = tmp_path / "scene" / "Show"
    src.mkdir(parents=True)
    (src / "e1.mkv").write_bytes(b"a" * 20000)
    (src / "e2.mkv").write_bytes(b"b" * 20000)
    data = make_torrent(src)
    local = tmp_path / "lib" / "Show" / "e1.mkv"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"a" * 20000)
    item = LocalItem(local.parent, {"Show/e1.mkv": 20000})
    return item, data


def test_partial_match_files_missing_locally_are_never_downloaded(tmp_path: Path) -> None:
    item, data = partial_pack(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    assert qbit.priorities[h] == {1: 0}
    assert qbit.calls.index("priority [1] = 0") < qbit.calls.index("recheck")


def test_partial_match_is_verified_on_the_pieces_inside_local_files_and_seeds_wanting_nothing(
    tmp_path: Path,
) -> None:
    item, data = partial_pack(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    # Piece 0 lies inside e1 only; piece 1 is shared with the absent e2 and cannot verify.
    qbit.finish_check(h, 0.5, pieces=[2, 0, 0])
    [outcome] = check_verifications(qbit, store, now=lambda: 1e12)

    assert outcome.verified and outcome.started
    # Every file skipped, the present one too, before starting: piece 1 is never fetched.
    assert qbit.priorities[h] == {0: 0, 1: 0}
    assert qbit.started == [h]
    assert PARTIAL in qbit.by_hash[h].tags and VERIFYING not in qbit.by_hash[h].tags


def test_partial_match_stays_stopped_when_the_client_does_not_confirm_skipping_its_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import torrentlinker.reseed as reseed

    monkeypatch.setattr(reseed, "SKIP_TIMEOUT", 0.4)
    item, data = partial_pack(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    qbit.priorities_stick = False

    qbit.finish_check(h, 0.5, pieces=[2, 0, 0])
    [outcome] = check_verifications(qbit, store, now=lambda: 1e12)

    assert outcome.verified and not outcome.started
    assert qbit.started == []  # starting would fetch boundary pieces into the library
    assert PARTIAL in qbit.by_hash[h].tags and VERIFYING not in qbit.by_hash[h].tags


def test_partial_match_with_a_bad_piece_inside_local_files_fails(tmp_path: Path) -> None:
    item, data = partial_pack(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    qbit.finish_check(h, 0.0, pieces=[0, 0, 0])
    [outcome] = check_verifications(qbit, store, now=lambda: 1e12)

    assert not outcome.verified
    assert qbit.removed == [(h, False)]


def test_verification_started_before_a_restart_is_settled_after_it(tmp_path: Path) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit = FakeQbit()
    h = start_reseed(
        qbit, Store(tmp_path / "s.db"), item, meta, match(item, meta.files), meta.infohash
    )  # type: ignore[arg-type]
    qbit.finish_check(h, 1.0)

    [outcome] = check_verifications(qbit, Store(tmp_path / "s.db"))  # app relaunched

    assert outcome.verified
    assert qbit.started == [h]


def test_reseed_interrupted_before_its_check_is_undone_without_a_rejection(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    qbit = FakeQbit()
    h = qbit.add(data, str(item.save_path), [TAG, VERIFYING])  # crashed right after the add
    store = Store(tmp_path / "s.db")

    assert check_verifications(qbit, store) == []
    assert qbit.removed == [(h, False)]
    assert item.path.exists()
    assert store.rejections(item.path) == {}


def test_a_reseed_recorded_but_never_rechecked_is_undone_on_the_next_check(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = qbit.add(data, str(item.save_path), [TAG, VERIFYING])
    store.start_verification(h, item.path, meta.infohash)  # crashed before the recheck

    assert check_verifications(qbit, store) == []
    assert qbit.removed == [(h, False)]
    assert store.rejections(item.path) == {}


def test_polling_while_a_reseed_is_being_set_up_leaves_it_alone(tmp_path: Path) -> None:
    import threading

    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    store = Store(tmp_path / "s.db")
    polled: list[object] = []

    class SlowQbit(FakeQbit):
        def rename_file(self, hash: str, old: str, new: str) -> None:  # mid-Reseed
            t = threading.Thread(target=lambda: polled.append(check_verifications(self, store)))
            t.start()
            t.join(timeout=0.3)
            super().rename_file(hash, old, new)

    qbit = SlowQbit()
    scene = tmp_path / "x" / "Scene.Name.epub"
    scene.parent.mkdir()
    scene.write_bytes(b"z" * 67163)
    meta = read_torrent(make_torrent(scene))
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]

    assert h in qbit.by_hash and qbit.removed == []


def test_a_reseed_never_moves_the_local_files_even_when_qbittorrent_lags(
    tmp_path: Path,
) -> None:
    from tests.fake_qbit import RacyQbit

    src = tmp_path / "scene" / "Zweig.Pack"
    src.mkdir(parents=True)
    (src / "a.epub").write_bytes(b"a" * 20000)
    (src / "b.epub").write_bytes(b"b" * 20000)
    meta = read_torrent(make_torrent(src))
    local = tmp_path / "lib" / "Zweig" / "a.epub"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"a" * 20000)
    item = LocalItem(local.parent, {"Zweig/a.epub": 20000})
    m = match(item, meta.files)
    assert m is not None

    start_reseed(
        RacyQbit(), Store(tmp_path / "s.db"), item, meta, m, meta.infohash, sleep=lambda s: None
    )

    assert local.read_bytes() == b"a" * 20000
    assert not (tmp_path / "lib" / "Zweig.Pack").exists()


def test_a_verification_is_not_accepted_if_a_local_file_was_moved_meanwhile(
    tmp_path: Path,
) -> None:
    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    moved = item.path.with_name("elsewhere.epub")
    item.path.rename(moved)  # whoever did it, the torrent must not seed from a wrong place
    qbit.finish_check(h, 1.0)

    [outcome] = check_verifications(qbit, store, now=lambda: 1e12)

    assert not outcome.verified and outcome.problem
    assert qbit.started == [] and qbit.removed == [(h, False)]
    assert moved.exists()
    assert store.rejections(item.path) == {}


@pytest.mark.parametrize("phase", ["settle", "rename"])
@pytest.mark.parametrize("removal_fails", [False, True])
def test_setup_timeout_cleans_up_only_after_successful_removal(
    tmp_path: Path, phase: str, removal_fails: bool
):
    item, _ = ebook(tmp_path)
    scene = tmp_path / "scene.epub"
    scene.write_bytes(item.path.read_bytes())
    meta = read_torrent(make_torrent(scene))
    found = match(item, meta.files)
    assert found is not None

    class StuckClient(FakeQbit):
        def add(self, *args):
            h = super().add(*args)
            if phase == "settle":
                self._set(h, state="checkingResumeData")
            return h

        def rename_file(self, *args):
            pass  # accepted asynchronously, but never reflected in the client's paths

        def remove(self, *args, **kwargs):
            if removal_fails:
                raise ConnectionError("removal unavailable")
            return super().remove(*args, **kwargs)

    client, store = StuckClient(), Store(tmp_path / "s.db")
    error, message = (
        (ConnectionError, "removal unavailable") if removal_fails else (ReseedAborted, "Timed out")
    )
    with pytest.raises(error, match=message):
        start_reseed(client, store, item, meta, found, meta.infohash, sleep=lambda _: None)

    if removal_fails:
        assert client.torrent(meta.infohash) is not None
        assert store.verification_hashes() == [meta.infohash]
        removal_fails = False
        assert check_verifications(client, store) == []
    assert client.torrent(meta.infohash) is None
    assert client.removed == [(meta.infohash, False)]
    assert store.verification_hashes() == []
    assert check_verifications(client, store) == []
    assert store.rejections(item.path) == {}
    assert item.path.read_bytes() == scene.read_bytes()


def test_a_client_naming_the_folder_differently_does_not_cancel_the_reseed(
    tmp_path: Path,
) -> None:
    """#53: every Full Match was cancelled as "no longer in place" when the client
    reported the save folder another way (a share path, a Path Mapping round trip)."""
    from dataclasses import replace

    item, data = ebook(tmp_path)
    meta = read_torrent(data)

    class ShareClient(FakeQbit):
        def torrent(self, hash, with_files=True):  # type: ignore[no-untyped-def]
            found = super().torrent(hash, with_files)
            return found and replace(found, save_path=Path("//nas/share/Library"))

        def torrents(self, tag=None, with_files=True):  # type: ignore[no-untyped-def]
            return [
                replace(t, save_path=Path("//nas/share/Library"))
                for t in super().torrents(tag, with_files)
            ]

    qbit, store = ShareClient(), Store(tmp_path / "s.db")
    h = start_reseed(qbit, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    qbit.finish_check(h, 1.0)

    [outcome] = check_verifications(qbit, store, now=lambda: 1e12)

    assert outcome.verified and not outcome.problem
    assert qbit.started == [h]
