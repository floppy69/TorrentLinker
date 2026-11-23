"""Achievement progress is durable, actor-owned and based on qualified evidence."""

from torrentlinker.achievements import Ledger


def test_full_reseeds_require_a_later_seeding_observation_and_survive_restart(tmp_path):
    path = tmp_path / "achievements.sqlite"
    ledger = Ledger(path)
    key = "a" * 40
    assert not ledger.reseed(
        "owner", key, verified_at=10, observed_at=11, state="queuedUP", progress=1, full=True
    )
    assert not ledger.reseed(
        "owner", key, verified_at=10, observed_at=11, state="uploading", progress=1, full=False
    )
    assert not ledger.reseed(
        "owner", key, verified_at=10, observed_at=9, state="uploading", progress=1, full=True
    )
    assert ledger.reseed(
        "owner", key, verified_at=10, observed_at=11, state="stalledUP", progress=1, full=True
    )
    assert not ledger.reseed(
        "owner",
        key.upper(),
        verified_at=12,
        observed_at=13,
        state="uploading",
        progress=1,
        full=True,
    )
    ledger.close()
    restored = Ledger(path)
    assert restored.state("owner")["reseeds"] == 1
    assert [a["code"] for a in restored.state("owner")["achievements"]] == ["reseed-1"]
    assert restored.state("member")["achievements"] == []
    assert restored.pending("owner") == []
    restored.close()


def test_future_consent_excludes_old_awards_and_opt_out_discards_retries(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.complete("owner", "playlist", "playlist-one")
    ledger.bind("owner", "site-account-a")
    ledger.sharing("owner", True, "consent-one")
    assert ledger.pending("owner") == []
    ledger.complete("owner", "studio", "render-one")
    assert ledger.pending("owner") == [{"code": "studio-first", "definitionVersion": 1}]
    ledger.share_existing("owner")
    assert {x["code"] for x in ledger.pending("owner")} == {"playlist-first", "studio-first"}
    ledger.sharing("owner", False)
    assert ledger.pending("owner") == []
    ledger.sharing("owner", True, "consent-two")
    assert ledger.pending("owner") == []
    ledger.complete("owner", "rss", "rss-one")
    ledger.bind("owner", "site-account-b")
    assert ledger.pending("owner") == []
    assert ledger.state("owner")["sharing"] is False
    ledger.close()


def test_account_changes_isolate_history_and_relink_restores_the_original_partition(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.complete("owner", "playlist", "local-playlist")
    ledger.bind("owner", "alice")
    assert len(ledger.state("owner")["achievements"]) == 1
    ledger.bind("owner", "")
    ledger.bind("owner", "bob")
    assert ledger.state("owner")["achievements"] == []
    ledger.complete("owner", "studio", "bob-render")
    ledger.bind("owner", "alice")
    assert [a["code"] for a in ledger.state("owner")["achievements"]] == ["playlist-first"]
    assert ledger.state("owner")["sharing"] is False
    ledger.close()


def test_pair_merge_unions_identities_without_inflating_thresholds_or_sharing_history(tmp_path):
    import copy

    import pytest

    first = Ledger(tmp_path / "first.sqlite")
    second = Ledger(tmp_path / "second.sqlite")
    first.bind("owner", "same-account")
    second.bind("member-id", "same-account")
    for number in range(1, 99):
        first.reseed(
            "owner",
            f"{number:040x}",
            verified_at=1,
            observed_at=2,
            state="uploading",
            progress=1,
            full=True,
        )
    for number in (98, 99, 100):
        second.reseed(
            "member-id",
            f"{number:040x}",
            verified_at=1,
            observed_at=2,
            state="uploading",
            progress=1,
            full=True,
        )
    payload = second.export("member-id")
    first.merge("owner", "same-account", payload)
    first.merge("owner", "same-account", payload)
    assert first.state("owner")["reseeds"] == 100
    assert {a["code"] for a in first.state("owner")["achievements"]} == {
        "reseed-1",
        "reseed-10",
        "reseed-100",
    }
    assert first.pending("owner") == []
    with pytest.raises(ValueError):
        first.merge("owner", "different-account", payload)
    bad = copy.deepcopy(payload)
    bad["events"][0]["version"] = 999
    with pytest.raises(ValueError):
        first.merge("owner", "same-account", bad)
    assert first.state("owner")["reseeds"] == 100
    assert set(payload) == {"schemaVersion", "accountId", "events"}
    first.close()
    second.close()


def test_merging_old_history_does_not_turn_it_into_future_shared_achievements(tmp_path):
    now = [100.0]
    local = Ledger(tmp_path / "local.sqlite", clock=lambda: now[0])
    remote = Ledger(tmp_path / "remote.sqlite", clock=lambda: now[0])
    local.bind("owner", "alice")
    remote.bind("owner", "alice")
    remote.complete("owner", "playlist", "old-playlist")
    now[0] = 200
    local.sharing("owner", True, "epoch")
    local.merge("owner", "alice", remote.export("owner"))
    assert local.pending("owner") == []
    now[0] = 300
    remote.complete("owner", "studio", "new-render")
    local.merge("owner", "alice", remote.export("owner"))
    assert local.pending("owner") == [{"code": "studio-first", "definitionVersion": 1}]
    local.close()
    remote.close()


def test_real_reseed_flow_records_only_after_a_subsequent_confirmed_state(tmp_path):
    from tests.fake_qbit import FakeQbit
    from tests.test_reseed import ebook
    from torrentlinker.matching import match
    from torrentlinker.reseed import check_verifications, start_reseed
    from torrentlinker.store import Store
    from torrentlinker.torrent_meta import read_torrent

    item, data = ebook(tmp_path)
    meta = read_torrent(data)
    client, store = FakeQbit(), Store(tmp_path / "catalogue.sqlite")
    key = start_reseed(client, store, item, meta, match(item, meta.files), meta.infohash)
    client.finish_check(key, 1)
    assert check_verifications(client, store)[0].started
    ledger = Ledger(tmp_path / "achievements.sqlite")
    assert ledger.state("owner")["reseeds"] == 0
    client._set(key, state="queuedUP")
    check_verifications(client, store)
    assert ledger.state("owner")["reseeds"] == 0
    client._set(key, state="stalledUP")
    check_verifications(client, store)
    assert ledger.state("owner")["reseeds"] == 1
    check_verifications(client, store)
    assert ledger.state("owner")["reseeds"] == 1
    ledger.close()


def test_playlist_api_credits_only_a_saved_nonempty_playlist_to_its_actor(tmp_path):
    from fastapi.testclient import TestClient

    from tests.fake_qbit import FakeQbit
    from tests.test_media_api import login, media_app, scan

    app, _ = media_app(tmp_path)
    app.state.agent_service.setup._client = FakeQbit()
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default&kind=music").json()["rows"][0]
        ledger = Ledger(tmp_path / "config/achievements.sqlite")
        empty = browser.post(
            "/api/media/playlists", json={"client_id": "default", "name": "Empty", "media_ids": []}
        )
        assert empty.is_success
        assert ledger.state("owner")["achievements"] == []
        saved = browser.post(
            "/api/media/playlists",
            json={"client_id": "default", "name": "Music", "media_ids": [item["id"]]},
        )
        assert saved.is_success
        assert [a["code"] for a in ledger.state("owner")["achievements"]] == ["playlist-first"]
        assert ledger.state("someone-else")["achievements"] == []
        ledger.close()


def test_rss_credit_requires_live_preview_of_the_exact_saved_configuration(tmp_path):
    from tests.test_feeds import Source
    from torrentlinker.feeds import Subscription
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    control = app.state.agent_service.feed_control
    source = Source()
    control.feeds.indexer = lambda: source
    definition = control.feeds.save(Subscription(name="Saved before tracking"))
    control.feeds.preview(definition)
    changed = definition.model_copy(update={"name": "Changed after test"})
    control.save(changed)
    ledger = Ledger(tmp_path / "achievements.sqlite")
    assert ledger.state("owner")["achievements"] == []
    control.feeds.preview(changed)
    control.save(changed)
    assert [a["code"] for a in ledger.state("owner")["achievements"]] == ["rss-first"]
    ledger.close()


def test_board_full_recheck_uses_the_same_later_observation_rule(tmp_path):
    from tests.test_reseed_workspace import run, workspace

    board, client, original, links, _ = workspace(tmp_path)
    assert run(board, original, links)["seeded"] == 1
    ledger = Ledger(board.setup.path.parent / "achievements.sqlite")
    assert ledger.state("owner")["reseeds"] == 0
    ledger.observe(board.setup.store.client_id, client)
    assert ledger.state("owner")["reseeds"] == 1
    ledger.close()


def test_recovered_milestones_never_auto_share_even_if_scan_occurs_after_consent(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.bind("owner", "account-a")
    ledger.sharing("owner", True, "epoch")
    ledger.complete("owner", "playlist", "retained-history", recovered=True)
    assert ledger.pending("owner") == []
    second = Ledger(tmp_path / "second.sqlite")
    second.bind("owner", "account-a")
    second.sharing("owner", True, "epoch")
    second.merge("owner", "account-a", ledger.export("owner"))
    assert second.pending("owner") == []
    second.share_existing("owner")
    assert second.pending("owner") == [{"code": "playlist-first", "definitionVersion": 1}]
    ledger.close()
    second.close()


def test_account_switch_during_observation_cannot_credit_new_account(tmp_path):
    from types import SimpleNamespace

    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.bind("owner", "alice")
    ledger.await_seeding("owner", "client", "a" * 40)

    def torrent(*args, **kwargs):
        another = Ledger(tmp_path / "ledger.sqlite")
        another.bind("owner", "bob")
        another.close()
        return SimpleNamespace(state="uploading", progress=1)

    ledger.observe("client", SimpleNamespace(torrent=torrent))
    assert ledger.state("owner")["account"] == "bob"
    assert ledger.state("owner")["reseeds"] == 0
    ledger.bind("owner", "alice")
    assert ledger.state("owner")["reseeds"] == 0
    ledger.close()


def test_unlink_detaches_old_partition_and_quarantines_gap_completions(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.bind("owner", "alice")
    ledger.complete("owner", "playlist", "alice-playlist")
    ledger.bind("owner", "")
    assert ledger.state("owner")["achievements"] == []
    ledger.complete("owner", "studio", "unattributed-render")
    ledger.bind("owner", "bob")
    assert ledger.state("owner")["achievements"] == []
    ledger.bind("owner", "alice")
    assert [a["code"] for a in ledger.state("owner")["achievements"]] == ["playlist-first"]
    assert not ledger.history_recovery_allowed("owner")
    ledger.close()


def test_conflicting_evidence_converges_and_cancels_only_implicit_future_queue(tmp_path):
    now = [100.0]
    a = Ledger(tmp_path / "a.sqlite", clock=lambda: now[0])
    b = Ledger(tmp_path / "b.sqlite", clock=lambda: now[0])
    for ledger in (a, b):
        ledger.bind("owner", "account")
    a.complete("owner", "playlist", "same", recovered=True)
    now[0] = 150
    b.sharing("owner", True, "epoch")
    now[0] = 200
    b.complete("owner", "playlist", "same")
    assert b.pending("owner")
    a.merge("owner", "account", b.export("owner"))
    b.merge("owner", "account", a.export("owner"))
    assert a.export("owner") == b.export("owner")
    assert a.state("owner")["achievements"] == b.state("owner")["achievements"]
    assert b.pending("owner") == []
    b.share_existing("owner")
    b.merge("owner", "account", a.export("owner"))
    assert b.pending("owner") == [{"code": "playlist-first", "definitionVersion": 1}]
    a.close()
    b.close()


def test_observation_batches_rotate_past_paused_reseeds(tmp_path):
    from types import SimpleNamespace

    ledger = Ledger(tmp_path / "ledger.sqlite")
    for i in range(33):
        ledger.await_seeding("owner", "client", f"{i:040x}")

    def torrent(infohash, **kwargs):
        return SimpleNamespace(
            state="uploading" if int(infohash, 16) == 32 else "pausedUP", progress=1
        )

    client = SimpleNamespace(torrent=torrent)
    ledger.observe("client", client)
    ledger.observe("client", client)
    assert ledger.state("owner")["reseeds"] == 1
    ledger.close()
