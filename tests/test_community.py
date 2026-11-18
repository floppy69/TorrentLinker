from copy import deepcopy

import pytest

from torrentlinker.community import DEFAULTS, CommunityActions, message_library, normalized

H = "a" * 40


@pytest.fixture
def queue(tmp_path):
    now = [1000000.0]
    q = CommunityActions(tmp_path, lambda: now[0])
    q.settings("42", {**deepcopy(DEFAULTS), "enabled": True})
    q.observe("42", observation())
    return q, now


def observation(today=0):
    return {
        "rules": {
            k: {"today": today, "limit": 5, "cooldown": 30, "locked": False}
            for k in ("comment", "vote", "chat")
        },
        "page": 1,
        "channels": [
            {"id": 1, "name": "Général", "kind": "general"},
            {"id": 135, "name": "Classe", "kind": "class"},
        ],
        "candidates": [{"hash": H, "title": "Sample"}],
    }


def draft(q, kind="comment", subject=H, content="Merci pour ce partage très utile", **extra):
    identifier = q.save(
        "42", {"kind": kind, "subject": subject, "content": content, "vote": "approve", **extra}
    )
    item = next(i for i in q.state("42")["items"] if i["id"] == identifier)
    q.control("42", identifier, "queue", item["revision"])
    return identifier


def receipt(q, command, outcome="posted", **extra):
    q.receipt("42", {**command, "outcome": outcome, "remoteId": "99", **extra})


def test_draft_timer_and_edit_requires_queue_again(queue):
    q, now = queue
    identifier = draft(q, due=now[0] + 60)
    assert q.claim("42") is None
    now[0] += 60
    item = q.state("42")["items"][0]
    q.save("42", {**item, "content": "Un commentaire corrigé"})
    assert q.claim("42") is None
    item = q.state("42")["items"][0]
    q.control("42", identifier, "queue", item["revision"])
    command = q.claim("42")
    assert command["content"] == "Un commentaire corrigé"
    with pytest.raises(ValueError):
        q.save("42", item)


def test_atomic_claim_and_receipt_replay_survive_restart(queue, tmp_path):
    q, now = queue
    draft(q)
    command = q.claim("42")
    other = CommunityActions(tmp_path, lambda: now[0])
    assert other.claim("42") is None
    receipt(other, command)
    receipt(other, command)
    assert len(other.state("42")["items"]) == 1
    item = other.state("42")["items"][0]
    assert item["state"] == "posted" and item["reward"] == "pending_24h"
    assert item["reward_due"] == now[0] + 86400
    with pytest.raises(ValueError):
        draft(other)


def test_uncertain_send_never_automatically_repeats(queue, tmp_path):
    q, now = queue
    draft(q)
    command = q.claim("42")
    now[0] += 181
    other = CommunityActions(tmp_path, lambda: now[0])
    other.observe("42", observation())
    assert other.claim("42") is None
    item = other.state("42")["items"][0]
    assert item["state"] == "uncertain"
    with pytest.raises(ValueError):
        other.control("42", item["id"], "queue", item["revision"])
    receipt(other, command)
    assert other.state("42")["items"][0]["state"] == "posted"


def test_daily_caps_and_action_buckets(queue):
    q, now = queue
    for i in range(6):
        draft(q, subject=f"{i:040x}")
    for _ in range(5):
        q.observe("42", observation())
        command = q.claim("42")
        assert command
        receipt(q, command)
        now[0] += 60
    q.observe("42", observation())
    assert q.claim("42") is None
    draft(q, kind="vote")
    assert q.claim("42")["kind"] == "vote"
    assert q.state("42")["quotas"]["comment"]["local_used"] == 5


def test_external_site_quota_and_freshness(queue):
    q, now = queue
    draft(q)
    q.observe("42", observation(5))
    assert q.claim("42") is None
    q.observe("42", observation())
    now[0] += 91
    assert q.claim("42") is None
    q.observe("42", observation())
    assert q.claim("42")


def test_shared_chat_limit_and_cross_channel_duplicate(queue):
    q, now = queue
    draft(q, "chat", "1")
    with pytest.raises(ValueError):
        draft(q, "chat", "135", content="  MERCI pour ce partage très utile  ")
    command = q.claim("42")
    receipt(q, command)
    draft(q, "chat", "135", content="Le soleil revient enfin ce matin")
    now[0] += 60
    q.observe("42", observation())
    assert q.claim("42") is None
    now[0] += 540
    q.observe("42", observation())
    assert q.claim("42")["subject"] == "135"


def test_throttle_and_auth_pause_persist(queue, tmp_path):
    q, now = queue
    draft(q)
    command = q.claim("42")
    receipt(q, command, "deferred", reason="rate", retryAfter=300)
    q = CommunityActions(tmp_path, lambda: now[0])
    assert q.claim("42") is None
    now[0] += 300
    q.observe("42", observation())
    command = q.claim("42")
    receipt(q, command, "refused", reason="auth")
    assert not q.state("42")["settings"]["enabled"]


def test_account_isolation_and_limits_validation(queue):
    q, now = queue
    draft(q)
    assert q.state("other")["items"] == []
    assert q.claim("other") is None
    with pytest.raises(ValueError):
        q.settings("42", {**deepcopy(DEFAULTS), "limits": {"comment": 6, "vote": 5, "chat": 5}})
    with pytest.raises(ValueError):
        q.save("42", {"kind": "upload"})
    with pytest.raises(ValueError):
        draft(q, kind="chat", subject="1", content="Bonjour !")


def test_cancelled_draft_cannot_bypass_duplicate_guard(queue):
    q, _ = queue
    first = draft(q)
    q.control("42", first, "cancel", 2)
    draft(q)
    with pytest.raises(ValueError):
        q.control("42", first, "queue", 3)


def test_library_is_packaged_distinct_and_with_attribution():
    entries = message_library()
    assert len(entries) >= 180
    assert len({e["id"] for e in entries}) == len(entries)
    assert len({normalized(e["text"]) for e in entries}) == len(entries)
    for entry in entries:
        assert 5 <= len(entry["text"].split()) and len(entry["text"]) <= 500
        if entry["kind"] == "quote":
            assert entry["author"] in entry["text"]
            assert entry["source"].startswith("https://")


def test_custom_limit_and_interval_apply_after_settings_edit(queue):
    q, now = queue
    settings = deepcopy(DEFAULTS)
    settings.update(enabled=True)
    settings["limits"]["comment"] = 1
    settings["limits"]["vote"] = 0
    q.settings("42", settings)
    draft(q)
    receipt(q, q.claim("42"))
    draft(q, subject="b" * 40)
    draft(q, kind="vote")
    now[0] += 3600
    q.observe("42", observation())
    assert q.claim("42") is None
    now[0] += 86400
    q.observe("42", observation())
    assert q.claim("42")["kind"] == "comment"


def test_two_scheduler_connections_cannot_claim_same_job(queue, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    q, now = queue
    draft(q)
    other = CommunityActions(tmp_path, lambda: now[0])
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda service: service.claim("42"), [q, other]))
    assert sum(result is not None for result in results) == 1


def test_punctuation_or_accent_change_does_not_repeat_chat(queue):
    q, _ = queue
    draft(q, "chat", "1", "Le café est prêt pour demain.")
    with pytest.raises(ValueError):
        draft(q, "chat", "135", "LE CAFE est prêt pour demain !")


def test_site_quota_reserves_sends_at_the_same_clock_tick_as_snapshot(queue):
    q, now = queue
    settings = deepcopy(DEFAULTS)
    settings["enabled"] = True
    settings["intervals"]["comment"] = 30
    q.settings("42", settings)
    q.observe("42", observation(3))
    for i in range(3):
        draft(q, subject=f"{i:040x}")
    receipt(q, q.claim("42"))
    now[0] += 30
    receipt(q, q.claim("42"))
    now[0] += 30
    # Three external actions plus the two reserved locally exhaust the quota.
    assert q.claim("42") is None


def test_profile_daily_contribution_uses_site_counts_and_resets_at_midnight(queue):
    q, now = queue
    q.observe("42", observation(today=3))
    assert q.daily_contribution("42")["comment"] == {
        "site_used": 3,
        "local_used": 0,
        "limit": 5,
    }
    now[0] += 86400
    assert q.daily_contribution("42")["comment"]["site_used"] == 0
