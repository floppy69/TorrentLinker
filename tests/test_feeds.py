import pytest

from torrentlinker.feeds import FeedService, Subscription
from torrentlinker.indexer import Candidate


class Source:
    url = "https://c411.org/api"
    rows = []

    def search(self, query, *, cached):
        assert cached is False
        return self.rows

    def redact(self, value):
        return value.replace("secret", "<API_KEY>")


def release(hash="a", title="Release", **kwargs):
    return Candidate(
        title, 1000, "https://c411.org/api?apikey=secret", infohash=hash * 40, **kwargs
    )


def test_activation_baselines_existing_rows_and_restart_preserves_unread(tmp_path):
    source = Source()
    source.rows = [release()]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(Subscription(name="Films", categories=[2030]))
    service.refresh(feed.id, now=100)
    assert service.inbox()[0]["unread"] is False
    source.rows = [release("b"), release()]
    service.refresh(feed.id, now=200)
    assert [row["infohash"] for row in service.inbox(unread=True)] == ["b" * 40]
    restarted = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    assert restarted.subscriptions()[0]["unread_count"] == 1
    assert restarted.inbox()[0]["discovered_at"] == 200


def test_pending_replacement_cannot_race_a_claim_from_another_store(tmp_path):
    import sqlite3

    from torrentlinker.store import Store

    path = tmp_path / "queue.sqlite"
    replacing = Store(path)
    sending = Store(path)
    sending._db.execute("PRAGMA busy_timeout=1")
    replacing.enqueue_download("old", {})
    claims = []

    def claim_between_status_check_and_insert(statement):
        if statement.startswith("INSERT OR IGNORE INTO download_queue"):
            try:
                claims.append(sending.claim_download("old"))
            except sqlite3.OperationalError as error:
                assert "locked" in str(error)
                claims.append(False)

    replacing._db.set_trace_callback(claim_between_status_check_and_insert)
    try:
        replaced = replacing.replace_pending_download("old", "new", {})
    finally:
        replacing._db.set_trace_callback(None)

    assert claims == [False], "Replacement must lock before checking queued status"
    assert replaced
    assert not sending.claim_download("old")
    assert sending.claim_download("new")


@pytest.mark.parametrize(
    "historical_status,expected",
    [("queued", "queued"), ("sent", "duplicate_work"), ("uncertain", "duplicate_work")],
)
def test_deleted_subscription_only_retains_completed_or_uncertain_work_claims(
    tmp_path, historical_status, expected
):
    from torrentlinker.download_queue import entries
    from torrentlinker.store import Store

    source = Source()
    source.rows = [release(metadata={"kind": "movie", "tmdbid": "123"})]
    store = Store(tmp_path / "queue.sqlite")
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    original = service.save(
        Subscription(name="A", mode="app_queue", folder=str(tmp_path), include_current=True)
    )
    service.refresh(original.id, now=100)
    service.process(original.id, store, present_hashes=set(), now=101)
    [entry] = entries(store)
    with service.db:
        service.db.execute(
            "UPDATE decisions SET status=? WHERE feed=?", (historical_status, original.id)
        )
    store.remove_downloads([entry.key])
    service.delete(original.id)

    source.rows = [release("b", metadata={"kind": "movie", "tmdbid": "123"})]
    later = service.save(
        Subscription(name="B", mode="app_queue", folder=str(tmp_path), include_current=True)
    )
    service.refresh(later.id, now=200)
    result = service.process(later.id, store, present_hashes=set(), now=201)

    assert result[0]["status"] == expected
    assert len(entries(store)) == int(expected == "queued")


def test_seeder_preference_is_ranked_at_the_users_chosen_priority():
    from torrentlinker.feeds import Preferences, evaluate

    codec_first = Preferences(
        preferred={"codec": ["HEVC", "H264"]},
        priorities=["codec", "seeders"],
    )
    seeds_first = codec_first.model_copy(update={"priorities": ["seeders", "codec"]})
    efficient = release(seeders=2, metadata={"codec": "HEVC"})
    available = release("b", seeders=20, metadata={"codec": "H264"})
    assert evaluate(efficient, codec_first)["rank"] < evaluate(available, codec_first)["rank"]
    assert evaluate(available, seeds_first)["rank"] < evaluate(efficient, seeds_first)["rank"]
    unknown = release("c", seeders=-1, metadata={"codec": "H264"})
    assert evaluate(available, seeds_first)["rank"] < evaluate(unknown, seeds_first)["rank"]
    assert "seeders" in evaluate(unknown, seeds_first)["unknown_preferences"]


def test_overlapping_feeds_deduplicate_globally_and_report_repeated_pages(tmp_path):
    source = Source()
    # A full repeated page never establishes complete history.
    source.rows = [Candidate(str(i), 1, "url", infohash=f"{i:040x}") for i in range(100)]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    a = service.save(Subscription(name="A"))
    b = service.save(Subscription(name="B"))
    result = service.refresh(a.id)
    service.refresh(b.id)
    assert "repeated page" in result["coverage"]
    assert len(service.inbox()) == 100
    assert len(service.inbox()[0]["feeds"]) == 2


def test_app_queue_persists_without_downloading_and_rules_are_idempotent(tmp_path):
    from torrentlinker.download_queue import entries
    from torrentlinker.store import Store

    source = Source()
    source.rows = []
    store = Store(tmp_path / "catalogue.sqlite")
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(Subscription(name="Films", mode="app_queue", folder=str(tmp_path)))
    service.refresh(feed.id, now=100)
    source.rows = [release(metadata={"kind": "movie", "tmdbid": "123"})]
    service.refresh(feed.id, now=200)
    result = service.process(feed.id, store, present_hashes=set(), now=201)
    assert result[0]["status"] == "queued"
    assert len(entries(store)) == 1
    restarted = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    restarted.process(feed.id, store, present_hashes=set(), now=202)
    assert len(entries(store)) == 1


def test_unknown_hard_metadata_blocks_rule_and_ranking_explains_alternatives(tmp_path):
    from torrentlinker.feeds import Preferences, evaluate

    prefs = Preferences(required={"audio": ["fr"]}, preferred={"codec": ["HEVC", "H264"]})
    unknown = evaluate(release(), prefs)
    assert unknown["eligible"] is False
    assert unknown["unknown"] == ["audio"]
    good = evaluate(release(metadata={"audio": ["fr"], "codec": "HEVC"}), prefs)
    fallback = evaluate(release(metadata={"audio": ["fr"], "codec": "H264"}), prefs)
    assert good["rank"] < fallback["rank"]


def test_better_match_replaces_only_pending_queue_entries(tmp_path):
    from torrentlinker.download_queue import entries
    from torrentlinker.feeds import Preferences
    from torrentlinker.store import Store

    source = Source()
    source.rows = []
    store = Store(tmp_path / "catalogue.sqlite")
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(
        Subscription(
            name="Films",
            mode="app_queue",
            folder=str(tmp_path),
            replace_pending=True,
            preferences=Preferences(preferred={"codec": ["HEVC", "H264"]}),
        )
    )
    service.refresh(feed.id, now=100)
    source.rows = [release(metadata={"kind": "movie", "tmdbid": "123", "codec": "H264"})]
    service.refresh(feed.id, now=200)
    service.process(feed.id, store, present_hashes=set(), now=201)
    source.rows.append(release("b", metadata={"kind": "movie", "tmdbid": "123", "codec": "HEVC"}))
    service.refresh(feed.id, now=250)
    service.process(feed.id, store, present_hashes=set(), now=251)
    assert [e.candidate.infohash for e in entries(store)] == ["b" * 40]
    assert any(d["status"] == "replaced" for d in service.decisions())


def test_unknown_identity_and_in_client_work_never_queue_automatically(tmp_path):
    from torrentlinker.download_queue import entries
    from torrentlinker.store import Store

    source = Source()
    source.rows = [release(), release("b", metadata={"kind": "movie", "tmdbid": "123"})]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(
        Subscription(name="Films", mode="app_queue", folder=str(tmp_path), include_current=True)
    )
    service.refresh(feed.id)
    store = Store(tmp_path / "catalogue.sqlite")
    results = service.process(
        feed.id, store, present_hashes={"c" * 40}, present_works={"movie:tmdb:123"}
    )
    assert {r["status"] for r in results} == {"blocked", "duplicate_work"}
    assert entries(store) == []


def test_wait_window_and_concurrent_subscriptions_choose_one_release_per_work(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from torrentlinker.download_queue import entries
    from torrentlinker.store import Store

    source = Source()
    source.rows = [release(metadata={"kind": "movie", "tmdbid": "123"})]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feeds = [
        service.save(
            Subscription(
                name=name,
                mode="app_queue",
                folder=str(tmp_path),
                include_current=True,
                wait_minutes=1,
            )
        )
        for name in ("A", "B")
    ]
    for feed in feeds:
        service.refresh(feed.id, now=100)
    store = Store(tmp_path / "catalogue.sqlite")
    assert (
        service.process(feeds[0].id, store, present_hashes=set(), now=150)[0]["status"] == "waiting"
    )
    other = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    with ThreadPoolExecutor(2) as executor:
        results = list(
            executor.map(
                lambda pair: pair[0].process(pair[1].id, store, present_hashes=set(), now=161),
                [(service, feeds[0]), (other, feeds[1])],
            )
        )
    assert len(entries(store)) == 1
    assert sum(row["status"] == "queued" for batch in results for row in batch) == 1


def test_saved_selection_survives_dismissal_and_missing_metadata_is_explicit(tmp_path):
    source = Source()
    source.rows = [release()]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(Subscription(name="Films"))
    service.refresh(feed.id)
    selection = service.select(["a" * 40], "Review")
    service.mark(["a" * 40], action="dismiss")
    restarted = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    assert restarted.inbox() == []
    assert restarted.selection(selection["id"])["rows"][0]["infohash"] == "a" * 40


def test_started_queue_entry_cannot_be_replaced_or_claimed_twice(tmp_path):
    from torrentlinker.store import Store

    store = Store(tmp_path / "catalogue.sqlite")
    store.enqueue_download("old", {})
    assert store.claim_download("old")
    assert not store.claim_download("old")
    assert not store.replace_pending_download("old", "new", {})


def test_enabling_rules_baselines_existing_inbox_without_include_current(tmp_path):
    from torrentlinker.store import Store

    source = Source()
    source.rows = []
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(Subscription(name="Review first"))
    service.refresh(feed.id)
    source.rows = [release(metadata={"kind": "movie", "tmdbid": "123"})]
    service.refresh(feed.id)
    enabled = service.save(feed.model_copy(update={"mode": "app_queue", "folder": str(tmp_path)}))
    rows = service.process(enabled.id, Store(tmp_path / "catalogue.sqlite"), present_hashes=set())
    assert rows[0]["status"] == "baseline"


def test_manual_queue_preserves_saved_selection_and_feed_origins(tmp_path):
    from torrentlinker.download_queue import entries
    from torrentlinker.store import Store

    source = Source()
    source.rows = [release()]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(Subscription(name="Films"))
    service.refresh(feed.id)
    saved = service.select(["a" * 40])
    store = Store(tmp_path / "catalogue.sqlite")
    service.enqueue_selection(saved["id"], store, "default", str(tmp_path))
    assert entries(store)[0].origin == {
        "source": "rss",
        "selection_id": saved["id"],
        "subscriptions": [feed.id],
    }


def test_shared_verified_ids_join_releases_without_title_similarity(tmp_path):
    from torrentlinker.download_queue import entries
    from torrentlinker.store import Store

    source = Source()
    source.rows = [
        release(
            "a", title="Title A", metadata={"kind": "movie", "tmdbid": "123", "imdbid": "tt456"}
        ),
        release(
            "b", title="Completely different title", metadata={"kind": "movie", "tmdbid": "123"}
        ),
    ]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(
        Subscription(name="Films", mode="app_queue", folder=str(tmp_path), include_current=True)
    )
    service.refresh(feed.id)
    store = Store(tmp_path / "catalogue.sqlite")
    service.process(feed.id, store, present_hashes=set())
    assert len(entries(store)) == 1


def test_unknown_client_work_coverage_blocks_automatic_choices(tmp_path):
    from torrentlinker.store import Store

    source = Source()
    source.rows = [release(metadata={"kind": "movie", "tmdbid": "123"})]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(
        Subscription(name="Films", mode="app_queue", folder=str(tmp_path), include_current=True)
    )
    service.refresh(feed.id)
    result = service.process(
        feed.id,
        Store(tmp_path / "catalogue.sqlite"),
        present_hashes={"e" * 40},
        unknown_client_works={"e" * 40},
    )
    assert result[0]["status"] == "blocked"
    assert "identities unknown" in result[0]["reason"]


def test_unknown_existing_app_queue_work_blocks_automatic_choices(tmp_path):
    from torrentlinker.download_queue import enqueue
    from torrentlinker.store import Store

    source = Source()
    source.rows = [release(metadata={"kind": "movie", "tmdbid": "123"})]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(
        Subscription(name="Films", mode="app_queue", folder=str(tmp_path), include_current=True)
    )
    service.refresh(feed.id)
    store = Store(tmp_path / "catalogue.sqlite")
    enqueue(store, source, release("e"), tmp_path)
    result = service.process(feed.id, store, present_hashes=set())
    assert result[0]["status"] == "blocked"
    assert "app queue torrent identities unknown" in result[0]["reason"]


def test_prefer_small_ranks_unknown_size_after_known_sizes():
    from torrentlinker.feeds import Preferences, evaluate

    preferences = Preferences(prefer_small=True)
    known = evaluate(Candidate("Known", 1000, "url"), preferences)
    unknown = evaluate(Candidate("Unknown", 0, "url"), preferences)
    assert known["rank"] < unknown["rank"]
    assert "size" in unknown["unknown_preferences"]


def test_saved_feed_selection_freezes_reviewed_rows_and_indexer(tmp_path):
    import pytest

    from torrentlinker.store import Store

    source = Source()
    source.rows = [release(title="Reviewed")]
    service = FeedService(tmp_path / "feeds.sqlite", lambda: source)
    feed = service.save(Subscription(name="Films"))
    service.refresh(feed.id)
    saved = service.select(["a" * 40])
    source.rows = [Candidate("Changed", 9999, "url", infohash="a" * 40)]
    service.refresh(feed.id)
    assert service.selection(saved["id"])["rows"][0]["title"] == "Reviewed"
    source.url = "https://other.test/api"
    with pytest.raises(ValueError, match="Indexer changed"):
        service.enqueue_selection(
            saved["id"], Store(tmp_path / "catalogue.sqlite"), "default", str(tmp_path)
        )


def test_preferred_format_and_small_size_are_ranked_without_explicit_priorities():
    from torrentlinker.feeds import Preferences, evaluate

    prefs = Preferences(preferred={"format": ["EPUB", "PDF"]}, prefer_small=True, priorities=[])
    epub = release("a", metadata={"format": "EPUB"})
    pdf = release("b", metadata={"format": "PDF"})
    assert evaluate(epub, prefs)["rank"] < evaluate(pdf, prefs)["rank"]
    from dataclasses import replace

    assert evaluate(epub, prefs)["rank"] < evaluate(replace(epub, size=2000), prefs)["rank"]
    assert prefs.priorities == ["format", "size"]


def test_a_client_inventory_is_observed_in_one_transaction_without_rewriting_known_rows(
    tmp_path,
):
    service = FeedService(tmp_path / "feeds.sqlite", lambda: Source())
    service.observe_client_release(release("a", "Known first"))
    statements = []
    service.db.set_trace_callback(statements.append)

    service.observe_client_releases(
        [release("a", "Renamed in the client"), release("b"), release("c")]
        + [Candidate("Not a hash", 1, "", infohash="xyz")]
    )

    assert sum(s.startswith("INSERT") for s in statements) == 2  # b and c, not the known a
    assert statements.count("COMMIT") == 1
    payloads = {row["infohash"]: row["title"] for row in service.releases()}
    assert payloads == {"a" * 40: "Known first", "b" * 40: "Release", "c" * 40: "Release"}


def test_category_scoped_rules_preserve_legacy_and_do_not_reject_other_categories(tmp_path):
    from torrentlinker.feeds import Preferences, evaluate

    prefs = Preferences(
        required={"quality": ["1080p"], "format": ["EPUB"]},
        category_scopes={"quality": [2030], "format": [7020]},
    )
    book = release(categories=(7020,), metadata={"format": "EPUB"})
    film = release(categories=(2030,), metadata={"quality": "1080p"})
    assert evaluate(book, prefs)["eligible"]
    assert evaluate(film, prefs)["eligible"]
    assert not evaluate(release(categories=(7020,)), prefs)["eligible"]
    assert not evaluate(release(), prefs)["eligible"]
    assert not evaluate(book, Preferences(required={"quality": ["1080p"]}))["eligible"]
    source = Source()
    service = FeedService(tmp_path / "scoped.sqlite", lambda: source)
    saved = service.save(Subscription(name="Mixed", preferences=prefs))
    assert (
        FeedService(tmp_path / "scoped.sqlite", lambda: source).get(saved.id).preferences == prefs
    )
