import pytest

from torrentlinker.zen import (
    GB,
    ZenClass,
    ZenProfile,
    ZenTorrent,
    class_bonus,
    compare_classes,
    duration_bonus,
    estimate,
    is_indexer_torrent,
    note,
    rarity_bonus,
    weight,
)

TANKER = ZenProfile(ZenClass.TANKER)
KEEPER = ZenProfile(ZenClass.SWARM_KEEPER)


def film(seeders: int = 100, days: float = 90, size: float = 4 * GB) -> ZenTorrent:
    return ZenTorrent(size=int(size), seeders=seeders, seed_days=days)


def test_guide_worked_example_tanker_fifteen_films_of_4_gb_earns_about_4_a_day() -> None:
    day = estimate(TANKER, [film() for _ in range(15)])

    assert day.notes[0] == pytest.approx(1.7)
    assert day.total == pytest.approx(1.7 * 15 * 1.05 / 7)
    assert day.paid == 4


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (50_000_000, 0.013),
        (100_000_000, 0.025),
        (500_000_000, 0.13),
        (1 * GB, 0.25),
        (1024**3, 0.27),  # shown as 1,00 Go
        (4 * GB, 1.0),
        (4 * 1024**3, 1.01),  # shown as 4,00 Go
        (25 * GB, 1.26),
        (60 * GB, 1.40),
    ],
)
def test_size_weight_matches_the_guide(size: float, expected: float) -> None:
    assert weight(int(size)) == pytest.approx(expected, abs=0.006)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, 0.0001),
        (1_000, 0.0001),
        (399_999, 0.0001),
        (400_000, 0.0001),
        (400_001, 0.00010000025),
        (1_000_000, 0.00025),
        (100_000_000, 0.025),
        (1 * GB, 0.25),
        (4 * GB - 1, 0.99999999975),
        (4 * GB, 1.0),
    ],
)
def test_size_weight_is_linear_with_a_minimum_below_4_gb(size: int, expected: float) -> None:
    assert weight(size) == pytest.approx(expected, rel=1e-12)


def test_size_weight_is_continuous_at_4_gb() -> None:
    assert weight(4 * GB - 1) < weight(4 * GB) < weight(4 * GB + 1)
    assert weight(4 * GB + 1) == pytest.approx(1.0, abs=1e-9)


def test_weight_keeps_rising_slowly_beyond_25_gb() -> None:
    assert weight(95 * GB) > weight(60 * GB) > weight(25 * GB)


def test_new_weights_apply_to_payout_and_added_torrent_estimates() -> None:
    from torrentlinker.zen import added_values

    # Both have note 1.0: no age or rarity bonus. A 100 MB torrent counts for
    # 0.025 and a 4 GB torrent for 1, then each is prorated to half a day.
    torrents = [ZenTorrent(100_000_000, 200), ZenTorrent(4 * GB, 200)]
    profile = ZenProfile(ZenClass.SWARM_KEEPER, seed_hours=12)
    expected = [0.025 / 14, 1 / 14]

    day = estimate(profile, torrents)

    assert day.notes == [1.0, 1.0]
    assert day.per_torrent == pytest.approx(expected)
    assert day.total == pytest.approx(1.025 / 14)
    assert added_values(profile, torrents) == pytest.approx(expected)


def test_seed_age_bonus_grows_by_steps() -> None:
    assert [duration_bonus(d) for d in (0, 6.9, 7, 30, 90, 180)] == [0, 0, 0.1, 0.25, 0.35, 0.5]


def test_rarity_depends_on_class_size_and_seeders() -> None:
    assert rarity_bonus(ZenClass.TANKER, 4 * GB, 40) == 0  # too few seeders for a Tanker
    assert rarity_bonus(ZenClass.TANKER, 4 * GB, 100) == 0.35
    assert rarity_bonus(ZenClass.TANKER, 60 * GB, 100) == 0.5
    assert rarity_bonus(ZenClass.TANKER, 60 * GB, 220) == 0.35
    assert rarity_bonus(ZenClass.TANKER, 4 * GB, 300) == 0
    assert rarity_bonus(ZenClass.SWARM_KEEPER, 4 * GB, 5) == 0.35
    assert rarity_bonus(ZenClass.SWARM_KEEPER, 0.5 * GB, 30) == 0
    assert rarity_bonus(ZenClass.SWARM_KEEPER, 20 * GB, 8) == 0.5


@pytest.mark.parametrize("category", [6000, 6010, 6050, 6070])
def test_keeper_xxx_category_base_is_added_before_age_and_rarity(category: int) -> None:
    torrent = ZenTorrent(4 * GB, 5, 180, category)

    assert note(ZenClass.SWARM_KEEPER, torrent) == pytest.approx(0.5 + 0.5 + 0.35)


def test_keeper_category_base_does_not_scale_the_age_and_rarity_bonuses() -> None:
    normal = ZenTorrent(4 * GB, 5, 180, 7000)
    adult = ZenTorrent(4 * GB, 5, 180, 6010)

    assert note(ZenClass.SWARM_KEEPER, normal) == pytest.approx(1 + 0.5 + 0.35)
    assert estimate(KEEPER, [adult]).total / estimate(KEEPER, [normal]).total == pytest.approx(
        1.35 / 1.85
    )


def test_class_bonus_grows_with_the_number_of_torrents() -> None:
    assert class_bonus(ZenClass.TANKER, 14) == 0
    assert class_bonus(ZenClass.TANKER, 15) == 0.05
    assert class_bonus(ZenClass.TANKER, 750) == pytest.approx(0.35)
    assert class_bonus(ZenClass.TANKER, 5000) == pytest.approx(0.35)
    assert class_bonus(ZenClass.SWARM_KEEPER, 10) == 0.2


def test_the_tree_bonus_is_never_inferred_from_the_torrents_seeded() -> None:
    # c411 grants it for challenges completed over time: 5,682 torrents alone give none.
    many = [film(100, 200) for _ in range(5682)]

    day = estimate(ZenProfile(ZenClass.SWARM_KEEPER), many)

    assert day.multiplier == pytest.approx(1.25)  # the grid's maximum, as c411 shows


def test_the_tree_bonus_is_capped_at_5_percent() -> None:
    profile = ZenProfile(ZenClass.SWARM_KEEPER, tree_bonus=0.08)

    assert estimate(profile, [film()]).multiplier == pytest.approx(1.05)  # 1 torrent: no grid


def test_shop_badges_add_on_top_of_the_class_maximum() -> None:
    many = [film(100, 200) for _ in range(500)]
    profile = ZenProfile(ZenClass.SWARM_KEEPER, tree_bonus=0.05, badge_bonus=0.04)

    # Grid at its +25 % maximum, tree +5 %, badges +4 %: c411's 30 % maximum is passed.
    assert estimate(profile, many).multiplier == pytest.approx(1.34)


def test_tree_bonus_already_unlocked_on_c411_is_kept() -> None:
    unlocked = ZenProfile(ZenClass.TANKER, tree_bonus=0.03)

    assert estimate(unlocked, [film()]).multiplier == pytest.approx(1.03)


def test_seed_time_is_prorated_and_under_30_minutes_counts_nothing() -> None:
    full = estimate(TANKER, [film()]).total

    assert estimate(ZenProfile(ZenClass.TANKER, seed_hours=12), [film()]).total == pytest.approx(
        full / 2
    )
    assert estimate(ZenProfile(ZenClass.TANKER, seed_hours=0.4), [film()]).total == 0


def test_each_torrent_estimate_adds_up_to_the_total() -> None:
    day = estimate(KEEPER, [film(3), film(30, 10), film(200, 400, 40 * GB)])

    assert sum(day.per_torrent) == pytest.approx(day.total)


def test_the_day_is_rounded_once_on_the_total() -> None:
    # c411's example: 18.7 before bonus, +25 %, 23 paid.
    day = estimate(KEEPER, [film(100, 90) for _ in range(4)])

    assert day.paid == round(day.total)


@pytest.mark.parametrize(
    ("hours", "expected", "paid"),
    [(0.49, 0.0, 0), (0.5, 0.0796875, 0), (12, 1.9125, 2), (24, 3.825, 4)],
)
def test_official_tanker_example_through_the_estimator(hours, expected, paid) -> None:
    # c411 /guide/tokens: fifteen 4 GB films, ninety seed days, note 1.7,
    # +5% class bonus, approximately four Zen for a full day.
    torrents = [ZenTorrent(4 * GB, 100, seed_days=90) for _ in range(15)]
    day = estimate(ZenProfile(ZenClass.TANKER, seed_hours=hours), torrents)
    assert day.notes == pytest.approx([1.7] * 15)
    assert day.multiplier == pytest.approx(1.05)
    assert day.total == pytest.approx(expected)
    assert day.paid == paid


def test_a_reuploader_earns_nothing_from_seeding_and_a_rough_amount_per_upload() -> None:
    reup = ZenProfile(ZenClass.REUPLOADER)

    assert estimate(reup, [film()]).total == 0
    assert estimate(reup, [], uploads=10).total == pytest.approx(4.3)


def test_c411_torrents_are_recognised_by_their_tracker_host() -> None:
    url = "https://c411.org/api/torznab"
    assert is_indexer_torrent("https://tracker.c411.org/announce/abc", url)
    assert is_indexer_torrent("c411.org", url)
    assert not is_indexer_torrent("udp://tracker.opentrackr.org:1337/announce", url)
    assert not is_indexer_torrent("", url)


def test_class_comparison_estimates_the_same_seeding_in_every_class() -> None:
    torrents = [film(5, 200, 8 * GB) for _ in range(20)]  # few seeders: Swarm Keeper land
    profile = ZenProfile(ZenClass.TANKER, tree_bonus=0.05)

    days = compare_classes(profile, torrents, uploads=3)

    assert days[ZenClass.TANKER].total == estimate(profile, torrents).total
    assert days[ZenClass.SWARM_KEEPER].total > days[ZenClass.TANKER].total
    assert days[ZenClass.SWARM_KEEPER].multiplier == 1 + class_bonus(ZenClass.SWARM_KEEPER, 20)
    assert days[ZenClass.REUPLOADER].total == pytest.approx(3 * 0.43)


def test_added_values_match_the_estimate_of_one_more_torrent() -> None:
    from torrentlinker.zen import added_values, torrent_zen

    seeding = [film(100, 90) for _ in range(14)]
    new = [film(60, 0), film(5, 0, 30 * GB)]

    values = added_values(TANKER, new, seeding)

    assert values == pytest.approx([torrent_zen(TANKER, t, seeding) for t in new])


def test_alternate_c411_tracker_is_only_trusted_for_c411():
    assert is_indexer_torrent("https://tk.c411.tw/announce/key", "https://c411.org/api/torznab")
    assert not is_indexer_torrent(
        "https://tk.c411.tw.attacker.test/announce", "https://c411.org/api"
    )
    assert not is_indexer_torrent("https://tk.c411.tw/announce", "https://another.test/api")
