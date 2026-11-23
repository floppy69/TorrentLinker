from dataclasses import replace
from pathlib import Path

import pytest

from torrentlinker.domain import LocalItem
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.plan import (
    DiskSpace,
    Plan,
    PlanCandidate,
    PlanGoal,
    PlanItem,
    PlanOptions,
    catalogue_candidates,
    disk_budgets,
    disk_space,
    make_plan,
)
from torrentlinker.store import CatalogueRow
from torrentlinker.zen import GB, ZenClass, ZenProfile, ZenTorrent, estimate

KEEPER = ZenProfile(ZenClass.SWARM_KEEPER)


def cand(
    name: str, gb: float, seeders: int = 5, disk: str = "A", reseed: bool = False
) -> PlanCandidate:
    return PlanCandidate(name, name, int(gb * GB), seeders, 2000, Path("/dl"), disk, reseed)


def names(plan) -> list[str]:  # type: ignore[no-untyped-def]
    return sorted(i.candidate.title for i in plan.items)


def test_plan_stays_within_each_disk_budget() -> None:
    candidates = [cand("a", 8), cand("b", 8), cand("c", 8, disk="B"), cand("d", 8, disk="B")]

    plan = make_plan(KEEPER, candidates, {"A": int(10 * GB), "B": int(17 * GB)})

    assert names(plan) == ["a", "c", "d"] or names(plan) == ["b", "c", "d"]
    assert plan.download_size == int(24 * GB)


def test_plan_respects_the_torrent_cap() -> None:
    candidates = [cand(str(i), 1) for i in range(10)]

    plan = make_plan(KEEPER, candidates, {"A": 100 * GB}, slots=3)

    assert len(plan.items) == 3


def test_greedy_keeps_the_best_of_several_orderings() -> None:
    # Per GB the small torrent wins, then the big one no longer fits; alone, the big
    # rare torrent pays more.
    candidates = [cand("big", 60, seeders=3), cand("small", 6, 3)]

    plan = make_plan(KEEPER, candidates, {"A": int(60 * GB)}, options=PlanOptions(PlanGoal.ZEN))

    assert names(plan) == ["big"]


@pytest.mark.parametrize("reseed", [False, True])
def test_note_and_zen_goals_can_select_different_torrents(reseed: bool) -> None:
    candidates = [
        cand("high note", 4, seeders=3, reseed=reseed),
        cand("high zen", 60, seeders=60, reseed=reseed),
    ]

    zen = make_plan(KEEPER, candidates, {"A": 60 * GB}, slots=1, options=PlanOptions(PlanGoal.ZEN))
    contribution = make_plan(
        KEEPER, candidates, {"A": 60 * GB}, slots=1, options=PlanOptions(PlanGoal.NOTE)
    )

    assert names(zen) == ["high zen"]
    assert names(contribution) == ["high note"]
    assert contribution.average_note > zen.average_note
    assert zen.zen_added > contribution.zen_added


def test_plan_average_note_and_zen_use_the_new_size_weights() -> None:
    candidates = [cand("small", 1, seeders=200), cand("reference", 4, seeders=5)]

    plan = make_plan(KEEPER, candidates, {"A": 5 * GB})

    assert names(plan) == ["reference", "small"]
    # Notes 1.0 and 1.35, weighted by 0.25 and 1.0 respectively.
    assert plan.average_note == pytest.approx(1.28)
    assert plan.zen_added == pytest.approx(1.6 / 7)


@pytest.mark.parametrize("reverse", [False, True])
def test_note_prefers_smaller_downloads_when_initial_notes_tie(reverse: bool) -> None:
    candidates = [cand("large", 4), cand("small-a", 1), cand("small-b", 1)]
    if reverse:
        candidates.reverse()

    plan = make_plan(KEEPER, candidates, {"A": 4 * GB}, slots=2, options=PlanOptions(PlanGoal.NOTE))

    assert [i.candidate.title for i in plan.items] == ["small-a", "small-b"]
    assert [i.note for i in plan.items] == pytest.approx([1.35, 1.35])


def test_note_ranks_individual_initial_scores_without_weight_or_seed_age() -> None:
    candidates = [
        cand("small lower note", 1, seeders=100),
        cand("large high note", 10, seeders=1),
        cand("huge lower note", 200, seeders=100),
    ]
    # Existing torrents' age and future age bonuses must not enter new scores.
    seeding = [ZenTorrent(4 * GB, 5, seed_days=180)]

    plan = make_plan(
        KEEPER,
        candidates,
        {"A": 300 * GB},
        seeding,
        slots=1,
        options=PlanOptions(PlanGoal.NOTE),
    )

    assert names(plan) == ["large high note"]
    assert plan.items[0].note == 1.5


@pytest.mark.parametrize("goal", [PlanGoal.ZEN, PlanGoal.NOTE])
@pytest.mark.parametrize("reseed", [False, True])
def test_low_seeder_constraint_uses_the_current_swarm_and_includes_the_boundary(
    goal: PlanGoal, reseed: bool
) -> None:
    candidates = [
        cand("rare", 4, seeders=3, reseed=reseed),
        cand("over limit", 4, seeders=4, reseed=reseed),
        cand("popular", 60, seeders=60, reseed=reseed),
    ]
    options = PlanOptions(goal, max_download_bytes=4 * GB, max_torrents=1, max_seeders=3)
    plan = make_plan(KEEPER, candidates, {"A": 100 * GB}, options=options)

    assert names(plan) == ["rare"]
    assert plan.download_size <= options.max_download_bytes
    assert not make_plan(
        KEEPER,
        candidates[1:],
        {"A": 100 * GB},
        options=options,
    ).items


@pytest.mark.parametrize("goal", [PlanGoal.ZEN, PlanGoal.NOTE])
@pytest.mark.parametrize("reseed", [False, True])
@pytest.mark.parametrize(
    "low,high,expected",
    [
        (0, 0, ["huge", "medium", "small"]),
        (2, 0, ["huge", "medium"]),
        (0, 4, ["medium", "small"]),
        (4, 4, ["medium"]),
        (5, 9, []),
    ],
)
def test_torrent_size_range_includes_its_bounds_and_zero_means_unbounded(
    goal: PlanGoal, reseed: bool, low: int, high: int, expected: list[str]
) -> None:
    candidates = [
        cand("small", 1, reseed=reseed),
        cand("medium", 4, reseed=reseed),
        cand("huge", 40, reseed=reseed),
    ]
    options = PlanOptions(goal, min_size=low * GB, max_size=high * GB)

    plan = make_plan(KEEPER, candidates, {"A": 100 * GB}, options=options)

    assert sorted(names(plan)) == expected


@pytest.mark.parametrize("goal", [PlanGoal.ZEN, PlanGoal.NOTE])
def test_reseed_alternatives_are_filtered_before_choosing_the_best_match(
    tmp_path: Path, goal: PlanGoal
) -> None:
    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import Match
    from torrentlinker.plan import reseed_candidates
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.torrent_meta import TorrentMeta

    path = tmp_path / "book.epub"
    files = {path.name: 4 * GB}
    entry = LibraryEntry(LibraryFolder(tmp_path), LocalItem(path, files), ItemState.ORPHAN)
    full = Match({path.name: path.name}, [], [], 1.0)
    alternatives = []
    for title, seeds, h in [("popular", 5, "a" * 40), ("rare", 1, "b" * 40)]:
        c = Candidate(title, 4 * GB, "u", seeds, h, categories=(7000,))
        alternatives.append(CheckedCandidate(c, TorrentMeta(title, h, files, b""), full, full))
    found = [(entry, alternatives)]

    assert reseed_candidates(KEEPER, found, set(), options=PlanOptions(goal))[0].title == "popular"
    rows = reseed_candidates(KEEPER, found, set(), options=PlanOptions(goal, max_seeders=1))
    assert [r.title for r in rows] == ["rare"]


@pytest.mark.parametrize("goal", [PlanGoal.ZEN, PlanGoal.NOTE])
@pytest.mark.parametrize(
    "size,count,zen_size,note_size",
    [(5, None, 5, 5), (5, 1, 3, 2), (0, 1, 9, 2), (0, None, 14, 14)],
)
def test_download_and_optional_torrent_limits_apply_together(
    goal: PlanGoal, size: int, count: int | None, zen_size: int, note_size: int
) -> None:
    candidates = [cand("large", 9), cand("medium", 3, disk="B"), cand("small", 2)]

    plan = make_plan(
        KEEPER,
        candidates,
        {"A": 100 * GB, "B": 100 * GB},
        options=PlanOptions(goal, size * GB, count),
    )

    assert plan.download_size == (zen_size if goal is PlanGoal.ZEN else note_size) * GB
    assert count is None or len(plan.items) <= count


def test_the_overall_torrent_cap_still_applies_with_a_larger_plan_limit() -> None:
    plan = make_plan(
        KEEPER,
        [cand(str(i), 1) for i in range(10)],
        {"A": 100 * GB},
        slots=2,
        options=PlanOptions(max_torrents=5),
    )
    assert len(plan.items) == 2


def test_reseeds_use_a_torrent_slot_but_no_download_or_disk_budget() -> None:
    candidates = [cand("reseed", 100, reseed=True), cand("download", 4), cand("extra", 1)]
    spaces = [DiskSpace("A", Path("/dl"), free=10 * GB, reserved=2 * GB)]

    plan = make_plan(
        KEEPER,
        candidates,
        {"A": 8 * GB},
        options=PlanOptions(PlanGoal.ZEN, max_download_bytes=4 * GB, max_torrents=2),
        disk_spaces=spaces,
    )

    assert names(plan) == ["download", "reseed"]
    assert plan.download_size == 4 * GB
    assert plan.disk_spaces[0].download == 4 * GB
    assert plan.disk_spaces[0].after_plan == 6 * GB


def test_disk_report_counts_shared_disks_once_and_shows_free_space_for_empty_plans() -> None:
    a, b, c = Path("/dl/a"), Path("/dl/b"), Path("/other")
    spaces = disk_space(
        [a, b, c],
        margin=0.1,
        disk=lambda p: "A" if p in [a, b] else "B",
        usage=lambda p: (1000, 400, 600),
    )
    plan = make_plan(KEEPER, [], {s.disk: s.available for s in spaces}, disk_spaces=spaces)

    assert len(plan.disk_spaces) == 2
    assert all(s.available == 500 and s.after_plan == 600 for s in plan.disk_spaces)


def test_plan_adds_the_zen_of_its_torrents_to_current_seeding() -> None:
    seeding = [ZenTorrent(4 * GB, 3, 100) for _ in range(4)]
    candidates = [cand("a", 4, 2)]

    plan = make_plan(KEEPER, candidates, {"A": 10 * GB}, seeding)

    after = estimate(KEEPER, [*seeding, ZenTorrent(4 * GB, 3, 0, 2000)]).total
    assert plan.zen_added == pytest.approx(after - estimate(KEEPER, seeding).total)
    assert plan.payback_days == pytest.approx(4 / plan.zen_added)


def test_crossing_a_class_threshold_counts_the_bonus_on_existing_seeding() -> None:
    profile = ZenProfile(ZenClass.TANKER, tree_bonus=0.03)
    seeding = [ZenTorrent(4 * GB, 100, 90) for _ in range(14)]
    plan = make_plan(profile, [cand("fifteenth", 4, seeders=99)], {"A": 4 * GB}, seeding)

    # Count 14 -> 15 adds +5% Class bonus, alongside the existing +3% tree bonus.
    before = 14 * 1.7 * 1.03 / 7
    after = (14 * 1.7 + 1.35) * 1.08 / 7
    assert names(plan) == ["fifteenth"]
    assert plan.zen_added == pytest.approx(after - before)
    assert plan.zen_added > plan.items[0].zen  # the existing torrents also earn more


@pytest.mark.parametrize(
    "cls,chosen", [(ZenClass.TANKER, "popular"), (ZenClass.SWARM_KEEPER, "rare")]
)
def test_the_selected_class_changes_which_torrent_the_plan_prefers(
    cls: ZenClass, chosen: str
) -> None:
    candidates = [cand("popular", 4, seeders=99), cand("rare", 4, seeders=3)]
    plan = make_plan(ZenProfile(cls), candidates, {"A": 4 * GB}, slots=1)

    assert names(plan) == [chosen]


def test_keeper_selection_uses_the_category_component_of_the_note() -> None:
    adult = replace(cand("adult", 4, seeders=5), category=6010)
    ebook = replace(cand("ebook", 4, seeders=5), category=7000)

    plan = make_plan(KEEPER, [adult, ebook], {"A": 4 * GB}, slots=1)

    assert names(plan) == ["ebook"]


def test_reseeds_come_first_and_cost_no_download() -> None:
    candidates = [cand("dl", 4, 3), cand("reseed", 30, 3, disk=None, reseed=True)]  # type: ignore[arg-type]

    plan = make_plan(KEEPER, candidates, {"A": 5 * GB}, slots=1)

    assert names(plan) == ["reseed"]
    assert plan.download_size == 0
    assert plan.zen_added > 0


def test_catalogue_torrents_in_qbittorrent_or_without_download_folder_are_skipped() -> None:
    categories = {2000: IndexerCategory("Films"), 7000: IndexerCategory("Ebook")}
    rows = [
        CatalogueRow("aa" * 20, "in client", GB, 5, 2000, "u", "d", 0),
        CatalogueRow("bb" * 20, "no folder", GB, 5, 7000, "u", "d", 0),
        CatalogueRow("cc" * 20, "dead", GB, 0, 2000, "u", "d", 0),
        CatalogueRow("dd" * 20, "ok", GB, 5, 2000, "u", "d", 0),
    ]
    folders = DownloadFolders({2000: "/dl/films"})

    found = catalogue_candidates(rows, folders, categories, {"aa" * 20}, lambda p: "disk")

    assert [c.title for c in found] == ["ok"]
    assert found[0].folder == Path("/dl/films") and found[0].disk == "disk"


def test_a_plan_can_be_limited_to_chosen_categories_parents_including_their_subcategories() -> None:
    categories = {
        2000: IndexerCategory("Films"),
        2030: IndexerCategory("Films étrangers", parent=2000),
        5000: IndexerCategory("Séries"),
        7000: IndexerCategory("Ebook"),
    }
    rows = [
        CatalogueRow("aa" * 20, "film", GB, 5, 2000, "u", "d", 0),
        CatalogueRow("bb" * 20, "foreign film", GB, 5, 2030, "u", "d", 0),
        CatalogueRow("cc" * 20, "series", GB, 5, 5000, "u", "d", 0),
        CatalogueRow("dd" * 20, "ebook", GB, 5, 7000, "u", "d", 0),
    ]
    folders = DownloadFolders(default="/dl")

    def titles(only: set[int] | None) -> list[str]:
        found = catalogue_candidates(rows, folders, categories, set(), lambda p: "d", only)
        return [c.title for c in found]

    assert titles(None) == ["film", "foreign film", "series", "ebook"]
    assert titles({2000, 7000}) == ["film", "foreign film", "ebook"]
    assert titles({2030}) == ["foreign film"]


def test_the_plan_respects_the_excluded_titles() -> None:
    categories = {
        7000: IndexerCategory("Ebook"),
        7020: IndexerCategory("Livres", parent=7000),
    }
    rows = [
        CatalogueRow(
            "aa" * 20,
            "Adolf.Hitler.Mon.Combat.Mein.Kampf.2017.FR.[ePub]-NOTAG",
            GB,
            119,
            7020,
            "u",
            "d",
            0,
        ),
        CatalogueRow("bb" * 20, "Mein Kampf (traduction) FR [EPUB]", GB, 50, 7020, "u", "d", 0),
        CatalogueRow("cc" * 20, "ok", GB, 5, 7020, "u", "d", 0),
    ]
    folders = DownloadFolders({7020: "/books"})

    found = catalogue_candidates(
        rows, folders, categories, set(), lambda p: "d", {7000}, ["mein", "kampf"]
    )

    assert [c.title for c in found] == ["ok"]


def test_the_plan_exclusion_is_case_insensitive() -> None:
    categories = {
        7000: IndexerCategory("Ebook"),
        7020: IndexerCategory("Livres", parent=7000),
    }
    rows = [
        # Uppercase "KAMPF" must still match the lowercase exclusion "kampf".
        CatalogueRow("aa" * 20, "Mon.Combat.KAMPF [EPUB]", GB, 9, 7020, "u", "d", 0),
        # Contains "Kampf" too, so it survives only because of the case-insensitive match.
        CatalogueRow("bb" * 20, "ok", GB, 5, 7020, "u", "d", 0),
    ]
    folders = DownloadFolders({7020: "/books"})

    found = catalogue_candidates(rows, folders, categories, set(), lambda p: "d", {7000}, ["kampf"])

    assert [c.title for c in found] == ["ok"]


def test_disk_budget_is_free_space_minus_a_margin_of_the_disk_shared_by_its_folders(
    tmp_path: Path,
) -> None:
    a, b, c = tmp_path / "a", tmp_path / "b" / "not-yet", tmp_path / "c"
    a.mkdir()
    c.mkdir()
    disks = {a: 1, b: 1, c: 2}

    budgets = disk_budgets(
        [a, b, c],
        0.10,
        usage=lambda p: (1000, 400, 600),
        disk=lambda p: disks[p],
    )

    assert budgets == {1: 500, 2: 500}


def test_a_full_disk_gives_no_budget(tmp_path: Path) -> None:
    assert disk_budgets([tmp_path], 0.10, usage=lambda p: (1000, 950, 50)) != {}
    assert set(disk_budgets([tmp_path], 0.10, usage=lambda p: (1000, 950, 50)).values()) == {0}


def test_broad_snapshot_entries_do_not_guess_a_child_category_or_download_folder() -> None:
    cats = {
        2000: IndexerCategory("Video"),
        2030: IndexerCategory("Film", 2000),
        2060: IndexerCategory("Animation", 2000),
    }
    row = CatalogueRow("a" * 40, "Old video", GB, 10, 2000, "u", "d", 0, "zen-lab")
    assert not catalogue_candidates(
        [row], DownloadFolders({2030: "/films"}), cats, set(), lambda p: "d"
    )
    assert not catalogue_candidates(
        [row], DownloadFolders({2000: "/video"}), cats, set(), lambda p: "d", {2030}
    )
    rows = catalogue_candidates(
        [row], DownloadFolders({2000: "/video"}), cats, set(), lambda p: "d", {2000}
    )
    assert rows[0].category == 2000 and rows[0].folder == Path("/video")


def test_orphans_with_a_full_match_become_reseed_rows_listed_first(tmp_path: Path) -> None:
    from tests.torrents import make_torrent
    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import Match
    from torrentlinker.plan import reseed_candidates
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.torrent_meta import read_torrent

    f = tmp_path / "book.epub"
    f.write_bytes(b"b" * 3000)
    meta = read_torrent(make_torrent(f))
    folder = LibraryFolder(tmp_path)
    full = Match({"book.epub": "book.epub"}, [], [], 1.0)
    partial = Match({"book.epub": "book.epub"}, ["x"], [], 0.6)
    orphan = LibraryEntry(folder, LocalItem(f, {f.name: 3000}), ItemState.ORPHAN)
    other = LibraryEntry(folder, LocalItem(tmp_path / "o"), ItemState.ORPHAN)
    seeded = LibraryEntry(folder, LocalItem(tmp_path / "s"), ItemState.SEEDED)
    checked = CheckedCandidate(Candidate("Book", 3000, "u", 4, meta.infohash), meta, full, full)
    found = [
        (orphan, [checked]),
        (other, [CheckedCandidate(Candidate("P", 3000, "u", 4), meta, partial, partial)]),
        (seeded, [checked]),
    ]

    rows = reseed_candidates(KEEPER, found, in_client=set())
    downloads = [
        cand("dl", 4, 3),
        PlanCandidate(meta.infohash, "Book in catalogue", 3000, 4, 7000, Path("/dl"), "A"),
    ]
    plan = make_plan(KEEPER, rows + downloads, {"A": 10 * GB})

    assert [r.title for r in rows] == ["Book"]
    assert plan.items[0].candidate.reseed
    assert plan.items[0].zen > 0
    assert [i.candidate.title for i in plan.items] == ["Book", "dl"]  # not downloaded twice
    assert plan.download_size == 4 * GB
    assert reseed_candidates(KEEPER, found, in_client={meta.infohash}) == []


def test_sending_takes_one_interval_per_download_and_none_for_reseeds(tmp_path: Path) -> None:
    download = PlanCandidate("aa" * 20, "Book", 2_000_000, 3, 7000, tmp_path, 1)
    reseed = replace(download, infohash="bb" * 20, reseed=True)
    plan = Plan([PlanItem(download, 0.1), PlanItem(download, 0.1), PlanItem(reseed, 0.1)])

    assert plan.sending_seconds(1) == pytest.approx(2.05)  # the second one waits its turn
    assert plan.sending_seconds(2) == pytest.approx(0)  # one per key, at once


def test_downloading_takes_the_plan_size_over_the_speed(tmp_path: Path) -> None:
    c = PlanCandidate("aa" * 20, "Film", 8 * GB, 3, 2000, tmp_path, 1)

    assert Plan([PlanItem(c, 0.1)]).download_seconds(100_000_000) == pytest.approx(80)


def test_a_saved_plan_restores_only_what_is_left_to_send(tmp_path: Path) -> None:
    from torrentlinker.plan import restore_plan, saved_items
    from torrentlinker.store import SavedPlan

    def row(h: str) -> CatalogueRow:
        return CatalogueRow(h * 40, f"Book {h}", 1000, 2, 7020, f"https://c411/{h}", "", 0)

    sent, left, gone = (
        PlanCandidate(h * 40, f"Book {h}", 1000, 2, 7020, tmp_path, 1, source=row(h)) for h in "abc"
    )
    reseed = replace(sent, infohash="d" * 40, folder=None, reseed=True)
    plan = Plan([PlanItem(c, 0.1) for c in (reseed, sent, left, gone)], 0.4)

    items = saved_items(plan)
    assert [i.title for i in items] == ["Book a", "Book b", "Book c"]  # no Reseed
    items[0] = replace(items[0], outcome="added")
    restored = restore_plan(SavedPlan(0.0, True, items), {"b" * 40: row("b"), "a" * 40: row("a")})

    [item] = restored.items  # "a" was sent, "c" left the Catalogue
    assert item.candidate.title == "Book b" and item.candidate.folder == tmp_path
    assert item.candidate.source == row("b")
    assert restored.zen_added == pytest.approx(0.1)


def test_a_restored_plan_keeps_its_share_of_the_plan_zen(tmp_path: Path) -> None:
    from torrentlinker.plan import restore_plan
    from torrentlinker.store import SavedPlan, SavedPlanItem

    items = [
        SavedPlanItem(h * 40, h, 1000, 2, 7020, str(tmp_path), zen, None, outcome)
        for h, zen, outcome in (("a", 0.3, "added"), ("b", 0.1, None))
    ]
    rows = {"b" * 40: CatalogueRow("b" * 40, "b", 1000, 2, 7020, "u", "", 0)}

    restored = restore_plan(SavedPlan(0.0, False, items, zen_added=0.8), rows)

    assert restored.zen_added == pytest.approx(0.2)  # a quarter of the Plan's 0.8 is left


def ebook(path: Path, size: int) -> LocalItem:
    return LocalItem(path, {path.name: size})


def download(title: str, size: int, tmp_path: Path, h: str = "a") -> PlanCandidate:
    return PlanCandidate(h * 40, title, size, 3, 7020, tmp_path, 1)


def test_a_book_already_in_the_library_is_found_under_another_name(tmp_path: Path) -> None:
    from torrentlinker.plan import on_disk

    local = ebook(tmp_path / "Un homme dangereux - Alexandre KAUFFMANN.epub", 250_000)
    torrent = "Un.Homme.Dangereux.Alexandre.Kauffmann.2024.FR.[EPUB]-NOTAG"

    # The torrent may also hold a small .nfo or cover the Library lacks.
    [found] = on_disk([download(torrent, 250_000 + 4_000, tmp_path)], [local])

    assert found.title == torrent and found.path == local.path


def test_another_book_of_the_same_author_is_not_taken_for_it(tmp_path: Path) -> None:
    from torrentlinker.plan import on_disk

    local = ebook(tmp_path / "La petite Fadette - George Sand.epub", 250_000)

    assert (
        on_disk([download("Indiana.George.Sand.FR.[EPUB]-NOTAG", 250_000, tmp_path)], [local]) == []
    )


def test_another_volume_of_a_series_is_not_taken_for_it(tmp_path: Path) -> None:
    from torrentlinker.plan import on_disk

    local = ebook(tmp_path / "Outsphere.T1.Guy.Roger.Duvert.FR.2019.[EPUB].NOTAG.epub", 250_000)
    torrent = "Outsphere.T2.Guy.Roger.Duvert.FR.2019.[EPUB]-NOTAG"

    assert on_disk([download(torrent, 250_000, tmp_path)], [local]) == []


def test_a_different_size_is_not_the_same_book(tmp_path: Path) -> None:
    from torrentlinker.plan import on_disk

    local = ebook(tmp_path / "La confidente - Audrey Lefevre.epub", 250_000)
    torrent = "La.Confidente.Audrey.Lefevre.2026.FR.[EPUB]-G11"

    assert on_disk([download(torrent, 400_000, tmp_path)], [local]) == []
    assert on_disk([download(torrent, 249_000, tmp_path)], [local]) == []  # smaller than mine


def test_a_book_inside_a_library_folder_of_many_books_is_found(tmp_path: Path) -> None:
    from torrentlinker.plan import on_disk

    author = LocalItem(
        tmp_path / "Jules Renard",
        {"Jules Renard/renard_sourires_pinces.epub": 120_000, "Jules Renard/poil.epub": 90_000},
    )

    [found] = on_disk(
        [download("Sourires.Pincés.Jules.Renard.2017.FR.[EPUB]-NOTAG", 120_000, tmp_path)],
        [author],
    )

    assert found.path == tmp_path / "Jules Renard" / "renard_sourires_pinces.epub"


def test_a_match_inside_an_archive_is_never_a_plan_reseed(tmp_path: Path) -> None:
    from torrentlinker.archives import Unpacked
    from torrentlinker.domain import ItemState, LibraryFolder
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import Match
    from torrentlinker.plan import reseed_candidates
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.torrent_meta import TorrentMeta

    archive = tmp_path / "Kaneda.rar"
    item = LocalItem(archive, {archive.name: 2 * GB})
    inside = LocalItem(tmp_path / "Kaneda", {"Kaneda/a.stl": 4 * GB})
    entry = LibraryEntry(LibraryFolder(tmp_path), item, ItemState.ORPHAN)
    full = Match({"Kaneda/a.stl": "Kaneda/a.stl"}, (), (), 1.0)
    c = Candidate("Kaneda[STL]", 4 * GB, "u", 2, "a" * 40, categories=(8010,))
    meta = TorrentMeta("Kaneda", "a" * 40, {"Kaneda/a.stl": 4 * GB}, b"")
    checked = CheckedCandidate(c, meta, full, full, Unpacked(archive, tmp_path, inside))

    # Unpacking writes gigabytes into the Library: only the user decides it.
    assert reseed_candidates(KEEPER, [(entry, [checked])], set()) == []


@pytest.mark.parametrize("goal", [PlanGoal.NOTE, PlanGoal.ZEN])
def test_minimum_torrent_count_tries_a_feasible_smaller_selection(goal):
    candidates = [cand("large", 60, 3), cand("small-a", 2, 1000), cand("small-b", 2, 1000)]
    result = make_plan(
        KEEPER,
        candidates,
        {"A": 60 * GB},
        options=PlanOptions(goal=goal, min_torrents=2, max_torrents=2, min_seeders=3),
    )
    assert names(result) == ["small-a", "small-b"]
    assert not result.issues


def test_minimum_seeders_and_count_report_shortfall_without_relaxing_limits():
    result = make_plan(
        KEEPER,
        [cand("eligible", 2, 10), cand("too few seeders", 1, 2)],
        {"A": 10 * GB},
        options=PlanOptions(min_torrents=2, min_seeders=5),
    )
    assert names(result) == ["eligible"]
    assert any(issue.code == "minimum_torrents" and issue.count == 2 for issue in result.issues)
    with pytest.raises(ValueError):
        PlanOptions(min_torrents=5, max_torrents=3)
    with pytest.raises(ValueError):
        PlanOptions(min_seeders=10, max_seeders=3)
