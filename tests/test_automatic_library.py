"""Automatic Library Folders: Local Items detected without a scan depth."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_upload_queue import UploadClient
from tests.test_web_jobs import finished, login
from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, LocalItem, Torrent
from torrentlinker.gui.library_model import LibraryModel
from torrentlinker.library import LibraryEntry, auto_searchable, build_library, pack_episodes
from torrentlinker.scan import scan
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.web.app import create_app


def tree(root: Path, *files: str) -> Path:
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 10)
    return root


def series(tmp_path: Path) -> Path:
    return tree(
        tmp_path / "Séries",
        "Show/Saison 01/Show.S01E01.mkv",
        "Show/Saison 01/Show.S01E02.mkv",
        "Film.2020.1080p-GRP/Film.mkv",
    )


def test_an_automatic_folder_scans_packs_and_their_episodes(tmp_path: Path) -> None:
    root = series(tmp_path)

    items = scan(LibraryFolder(root, None, ContentKind.SERIES))

    season = root / "Show/Saison 01"
    assert {(item.path, item.within) for item in items} == {
        (season, None),
        (season / "Show.S01E01.mkv", season),
        (season / "Show.S01E02.mkv", season),
        (root / "Film.2020.1080p-GRP", None),
    }
    episode = next(item for item in items if item.path.name == "Show.S01E01.mkv")
    assert episode.files == {"Show.S01E01.mkv": 10}  # relative to its own parent, as before
    assert not items.errors


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX permissions")
def test_an_unreadable_folder_is_reported_not_skipped(tmp_path: Path) -> None:
    root = tree(tmp_path / "Films", "Locked/Film.2020.1080p-GRP/Film.mkv")
    (root / "Locked").chmod(0)
    try:
        items = scan(LibraryFolder(root, None, ContentKind.MOVIE))
    finally:
        (root / "Locked").chmod(0o755)

    assert [error.path for error in items.errors] == [root / "Locked"]


def test_seeded_torrents_and_catalogue_sizes_reach_detection(tmp_path: Path) -> None:
    root = tree(tmp_path / "Divers", "Pack/A/a.mkv", "Pack/B/b.mkv", "Logiciel/setup.rar")
    store = Store(tmp_path / "state.db")
    store.save_catalogue(
        [CatalogueRow("f" * 40, "Logiciel", 10, 1, None, "https://x/1", "https://x/d", 0)]
    )
    seeded = Torrent("a" * 40, "Pack", root, {"Pack/A/a.mkv": 10, "Pack/B/b.mkv": 10})

    entries = build_library([LibraryFolder(root, None, ContentKind.OTHER)], [seeded], cache=store)

    assert {(e.item.path.name, e.state) for e in entries} == {
        ("Pack", ItemState.SEEDED),
        ("Logiciel", ItemState.ORPHAN),
    }


def test_automatic_folders_survive_a_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    folders = [LibraryFolder(tmp_path, None, ContentKind.SERIES), LibraryFolder(tmp_path / "b", 2)]
    Settings(library_folders=folders).save(path)

    assert Settings.load(path).library_folders == folders


def entry(path: Path, within: Path | None = None, state=ItemState.ORPHAN) -> LibraryEntry:
    folder = LibraryFolder((within or path).parent, None)  # a pack and its episodes share it
    return LibraryEntry(folder, LocalItem(path, within=within), state)


def test_a_batch_searches_a_pack_once_not_each_episode(tmp_path: Path) -> None:
    pack = entry(tmp_path / "Saison 01")
    episodes = [entry(tmp_path / f"Saison 01/E0{i}.mkv", tmp_path / "Saison 01") for i in (1, 2)]
    seeded_pack = entry(tmp_path / "Saison 02", state=ItemState.SEEDED)
    orphan_episode = entry(tmp_path / "Saison 02/E01.mkv", tmp_path / "Saison 02")

    assert auto_searchable([pack, *episodes, seeded_pack, orphan_episode]) == [pack]
    # Selected without their pack, episodes are searched, even those of a seeded pack.
    assert auto_searchable([*episodes, orphan_episode]) == [*episodes, orphan_episode]


def test_a_batch_still_checks_a_packs_episodes_without_searching(tmp_path: Path) -> None:
    pack = entry(tmp_path / "Saison 01")
    episodes = [entry(tmp_path / f"Saison 01/E0{i}.mkv", tmp_path / "Saison 01") for i in (1, 2)]
    seeded_pack = entry(tmp_path / "Saison 02", state=ItemState.SEEDED)
    orphan_episode = entry(tmp_path / "Saison 02/E01.mkv", tmp_path / "Saison 02")
    seeded_episode = entry(tmp_path / "Saison 02/E02.mkv", tmp_path / "Saison 02", ItemState.SEEDED)

    found = pack_episodes([pack, *episodes, seeded_pack, orphan_episode, seeded_episode])

    assert found == [*episodes, orphan_episode]
    assert pack_episodes([*episodes, orphan_episode]) == []  # searched themselves instead


def test_the_library_shows_episodes_as_children_of_their_pack(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    model = LibraryModel()
    pack = entry(tmp_path / "Saison 01", state=ItemState.SEEDED)
    episodes = [entry(tmp_path / f"Saison 01/E0{i}.mkv", tmp_path / "Saison 01") for i in (1, 2)]
    film = entry(tmp_path / "Film.2020.mkv")
    model.set_entries([episodes[0], pack, film, episodes[1]])  # any order

    assert [model.index(r, 0).data() for r in range(model.rowCount())] == [
        "Saison 01",
        "Film.2020.mkv",
    ]
    top = model.index(0, 0)
    assert model.rowCount(top) == 2
    child = model.index(1, 0, top)
    assert child.data() == "E02.mkv"
    assert child.parent() == top
    assert child.siblingAtColumn(1).data() == "Orphan · in seeded pack"
    assert "Also inside the pack" in child.data(3)  # ToolTipRole
    model.set_status(episodes[1].item.path, "Verifying…")
    assert child.siblingAtColumn(1).data() == "Verifying…"


def test_an_episode_is_seeded_only_by_a_torrent_of_its_own(tmp_path: Path) -> None:
    root = tree(
        tmp_path / "Séries",
        "Show.S01.1080p-GRP/Show.S01E01.mkv",
        "Show.S01.1080p-GRP/Show.S01E02.mkv",
    )
    pack = root / "Show.S01.1080p-GRP"
    whole = Torrent(
        "a" * 40,
        pack.name,
        root,
        {f"{pack.name}/Show.S01E01.mkv": 10, f"{pack.name}/Show.S01E02.mkv": 10},
    )
    single = Torrent("b" * 40, "Show.S01E02.mkv", pack, {"Show.S01E02.mkv": 10})

    entries = build_library([LibraryFolder(root, None, ContentKind.SERIES)], [whole, single])

    assert {e.item.path.name: e.state for e in entries} == {
        pack.name: ItemState.SEEDED,
        "Show.S01E01.mkv": ItemState.ORPHAN,  # inside the seeded pack, not seeded alone
        "Show.S01E02.mkv": ItemState.SEEDED,  # its own torrent
    }


def test_folder_preview_finds_packs_and_episodes_without_saving(tmp_path: Path) -> None:
    root = series(tmp_path)
    with TestClient(
        create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        response = browser.post(
            "/api/setup/preview-folder", json={"local": str(root), "kind": "series", "depth": None}
        )
        assert response.status_code == 200, response.text
        assert response.json()["count"] == 2
        assert response.json()["episodes"] == 2
        assert browser.get("/api/setup").json()["folders"] == []


def test_the_web_saves_an_automatic_folder_and_lists_episodes(tmp_path: Path) -> None:
    root = series(tmp_path)
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: UploadClient(),
        )
    ) as browser:
        login(browser)
        browser.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://box.example"}
        )
        saved = browser.post(
            "/api/setup/folder",
            json={"local": str(root), "kind": "series", "depth": None, "purpose": "library"},
        )
        assert saved.is_success, saved.text
        folder = next(f for f in browser.get("/api/setup").json()["folders"])
        assert folder["depth"] is None
        scan_job = browser.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(browser, scan_job["id"])["status"] == "completed"
        rows = browser.get("/api/library").json()

    rows = rows["rows"]
    within = {Path(row["path"]).name: row["within"] for row in rows}
    assert within["Show.S01E01.mkv"] == str(root / "Show/Saison 01")
    assert within["Saison 01"] == ""
