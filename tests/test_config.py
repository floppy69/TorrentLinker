from pathlib import Path

import pytest

from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping


def test_settings_survive_a_save_and_load(tmp_path: Path) -> None:
    s = Settings()
    s.library_folders = [LibraryFolder(Path("/lib/films"), 2, ContentKind.MOVIE)]
    s.path_mappings = [PathMapping("/mnt/nas", "/data")]
    s.kind_categories = {ContentKind.MOVIE: [2000, 2030]}
    s.matching.ignore_patterns = ["*.nfo"]
    s.save(tmp_path / "settings.json")

    loaded = Settings.load(tmp_path / "settings.json")

    assert loaded.library_folders == s.library_folders
    assert loaded.path_mappings == s.path_mappings
    assert loaded.categories(ContentKind.MOVIE) == (2000, 2030)
    assert loaded.matching.ignore_patterns == ["*.nfo"]


def test_zen_profile_survives_a_save_and_load(tmp_path: Path) -> None:
    from torrentlinker.zen import ZenClass, ZenProfile

    s = Settings()
    s.zen = ZenProfile(ZenClass.SWARM_KEEPER, tree_bonus=0.03, seed_hours=18, torrent_cap=400)
    s.save(tmp_path / "settings.json")

    assert Settings.load(tmp_path / "settings.json").zen == s.zen


def test_download_folders_and_indexer_categories_survive_a_save_and_load(tmp_path: Path) -> None:
    from torrentlinker.downloads import DownloadFolders, IndexerCategory

    s = Settings()
    s.indexer_categories = {2000: IndexerCategory("Films"), 2030: IndexerCategory("VO", 2000)}
    s.download_folders = DownloadFolders({2030: "/dl/vo"}, "/dl")
    s.save(tmp_path / "settings.json")

    loaded = Settings.load(tmp_path / "settings.json")

    assert loaded.indexer_categories == s.indexer_categories
    assert loaded.download_folders == s.download_folders


def test_qbittorrent_api_keys_are_recognised() -> None:
    from torrentlinker.qbit import is_api_key

    assert is_api_key("qbt_" + "aB3" * 9 + "x")
    assert not is_api_key("qbt_short")
    assert not is_api_key("password")


def test_the_categories_chosen_for_plans_survive_a_save_and_load(tmp_path: Path) -> None:
    s = Settings()
    assert s.plan_categories is None  # every category by default
    s.plan_categories = [2000, 7000]
    s.save(tmp_path / "settings.json")

    assert Settings.load(tmp_path / "settings.json").plan_categories == [2000, 7000]


@pytest.mark.parametrize("goal", ["zen", "note"])
def test_plan_goal_and_both_limits_survive_a_save_and_load(tmp_path: Path, goal: str) -> None:
    from torrentlinker.plan import PlanGoal, PlanOptions
    from torrentlinker.zen import GB

    settings = Settings()
    settings.plan_options = PlanOptions(
        PlanGoal(goal),
        25 * GB,
        100,
        max_seeders=10,
        min_size=GB // 2,
        max_size=8 * GB,
        min_torrents=20,
        min_seeders=3,
    )
    settings.save(tmp_path / "settings.json")

    assert Settings.load(tmp_path / "settings.json").plan_options == settings.plan_options


def test_old_settings_default_to_zen_and_unlimited_plan_limits(tmp_path: Path) -> None:
    from torrentlinker.plan import PlanGoal, PlanOptions

    path = tmp_path / "settings.json"
    path.write_text("{}")

    assert Settings.load(path).plan_options == PlanOptions(PlanGoal.ZEN)


def test_new_settings_default_to_note(tmp_path: Path) -> None:
    from torrentlinker.plan import PlanGoal

    assert Settings().plan_options.goal is PlanGoal.NOTE
    assert Settings.load(tmp_path / "new.json").plan_options.goal is PlanGoal.NOTE


def test_the_excluded_plan_titles_survive_a_save_and_load(tmp_path: Path) -> None:
    settings = Settings()
    settings.plan_exclusions = ["mein", "kampf"]
    settings.save(tmp_path / "settings.json")

    assert Settings.load(tmp_path / "settings.json").plan_exclusions == ["mein", "kampf"]


def test_the_tested_download_speed_survives_a_save_and_load(tmp_path: Path) -> None:
    s = Settings()
    s.download_speed, s.download_speed_tested = 20_000_000.0, "2026-10-22T04:30"
    s.save(tmp_path / "s.json")

    loaded = Settings.load(tmp_path / "s.json")

    assert loaded.download_speed == 20_000_000.0
    assert loaded.download_speed_tested == "2026-10-22T04:30"


def test_mappings_of_library_folders_from_0_2_move_to_the_shared_list(tmp_path: Path) -> None:
    import json

    old = {
        "library_folders": [
            {
                "path": "/mnt/nas/films",
                "depth": 1,
                "kind": "movie",
                "mapping": {"local": "/mnt/nas/films", "qbit": "/data/films"},
            },
            {
                "path": "/mnt/nas/books",
                "depth": 1,
                "kind": "ebook",
                "mapping": {"local": "/mnt/nas/books", "qbit": "/data/books"},
            },
            {"path": "/home/me/stl", "depth": 1, "kind": "3d-model", "mapping": None},
        ]
    }
    (tmp_path / "settings.json").write_text(json.dumps(old))

    loaded = Settings.load(tmp_path / "settings.json")

    assert loaded.path_mappings == [
        PathMapping("/mnt/nas/films", "/data/films"),
        PathMapping("/mnt/nas/books", "/data/books"),
    ]
    assert [f.path for f in loaded.library_folders] == [
        Path("/mnt/nas/films"),
        Path("/mnt/nas/books"),
        Path("/home/me/stl"),
    ]


def test_the_torrent_client_choice_survives_and_old_settings_mean_qbittorrent(
    tmp_path: Path,
) -> None:
    from torrentlinker.domain import TorrentClient

    path = tmp_path / "settings.json"
    path.write_text('{"qbit": {"host": "http://nas:8080", "username": "me"}}')
    assert Settings.load(path).client is TorrentClient.QBITTORRENT

    s = Settings()
    s.client = TorrentClient.DELUGE
    s.deluge.host = "http://nas:8112"
    s.save(path)

    loaded = Settings.load(path)
    assert loaded.client is TorrentClient.DELUGE
    assert loaded.deluge.host == "http://nas:8112"
