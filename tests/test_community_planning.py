from copy import deepcopy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.test_community import H, observation
from torrentlinker.community import DEFAULTS, CommunityActions


def test_automatic_comments_are_durable_and_disabling_preserves_manual(tmp_path):
    now = datetime(2026, 11, 17, 10, tzinfo=UTC).timestamp()
    q = CommunityActions(tmp_path, lambda: now)
    q.observe("42", observation())
    manual = q.save(
        "42", {"kind": "chat", "subject": "1", "content": "Un message choisi pour le canal général"}
    )
    q.control("42", manual, "queue", 1)
    settings = deepcopy(DEFAULTS)
    settings["enabled"] = True
    settings["templates"]["comment"] = "Merci pour le partage de {titre} !"
    settings["automation"] = {
        "enabled": True,
        "kinds": {"comment": True, "vote": False, "chat": False},
        "start": "09:00",
        "end": "19:00",
        "timezone": "UTC",
        "channels": ["general"],
        "messages": [],
    }
    q.settings("42", settings)
    restored = CommunityActions(tmp_path, lambda: now)
    items = restored.state("42")["items"]
    automatic = next(i for i in items if i["kind"] == "comment")
    assert automatic["content"] == "Merci pour le partage de Sample !"
    assert automatic["source"] == "automatic" and automatic["state"] == "queued"
    assert automatic["due"] >= now
    settings["automation"]["enabled"] = False
    restored.settings("42", settings)
    items = restored.state("42")["items"]
    assert next(i for i in items if i["id"] == manual)["state"] == "queued"
    assert next(i for i in items if i["id"] == automatic["id"])["state"] == "cancelled"


def test_discovery_advances_pages_and_retains_more_than_500_torrents(tmp_path):
    q = CommunityActions(tmp_path, lambda: 1000000.0)
    q.discover("42")
    for page in range(1, 23):
        assert q.demand("42")["page"] == page
        q.observe(
            "42",
            {
                **observation(),
                "page": page,
                "has_more": page < 22,
                "candidates": [
                    {"hash": f"{page * 25 + i:040x}", "title": f"Torrent {page}-{i}"}
                    for i in range(25)
                ],
            },
        )
    assert not q.demand("42")["collect"]
    assert len(q.state("42")["candidates"]) == 550
    q.discover("42")
    assert not q.demand("42")["collect"]


def test_journal_preserves_edits_and_receipts_across_restart(tmp_path):
    q = CommunityActions(tmp_path)
    identifier = q.save(
        "42", {"kind": "comment", "subject": H, "content": "Premier texte de commentaire"}
    )
    q.save(
        "42",
        {
            "id": identifier,
            "revision": 1,
            "kind": "comment",
            "subject": H,
            "content": "Texte corrigé du commentaire",
        },
    )
    q.control("42", identifier, "queue", 2)
    events = CommunityActions(tmp_path).state("42")["items"][0]["events"]
    assert [e["state"] for e in events] == ["draft", "draft", "queued"]
    assert events[0]["content"] == "Premier texte de commentaire"
    assert events[1]["content"] == "Texte corrigé du commentaire"


def test_automatic_votes_use_prepared_choices_and_window_is_enforced(tmp_path):
    clock = [datetime(2026, 11, 17, 8, tzinfo=UTC).timestamp()]
    q = CommunityActions(tmp_path, lambda: clock[0])
    q.observe("42", observation())
    q.save(
        "42",
        {"kind": "vote", "subject": H, "vote": "disapprove", "content": "Le fichier est incomplet"},
    )
    settings = deepcopy(DEFAULTS)
    settings["enabled"] = True
    settings["automation"]["enabled"] = True
    settings["automation"]["kinds"]["vote"] = True
    q.settings("42", settings)
    item = q.state("42")["items"][0]
    assert item["vote"] == "disapprove"
    assert datetime.fromtimestamp(item["due"], UTC).hour == 9
    assert q.claim("42") is None
    clock[0] += 3600
    q.observe("42", observation())
    assert q.claim("42")["vote"] == "disapprove"


def test_calendar_reserves_separate_slots_with_paris_daily_caps(tmp_path):
    from tests.test_community import draft

    q = CommunityActions(tmp_path, lambda: 1000000.0)
    q.observe("42", observation())
    settings = deepcopy(DEFAULTS)
    settings["enabled"] = True
    settings["limits"]["comment"] = 1
    q.settings("42", settings)
    draft(q, subject="b" * 40)
    draft(q, subject="c" * 40)
    items = q.state("42")["items"]
    assert datetime.fromtimestamp(items[1]["next_at"], ZoneInfo("Europe/Paris")).hour == 0
    assert 0 < items[1]["next_at"] - items[0]["next_at"] < 86400


def test_automatic_vote_keeps_owner_scheduled_time(tmp_path):
    now = datetime(2026, 11, 17, 10, tzinfo=UTC).timestamp()
    q = CommunityActions(tmp_path, lambda: now)
    q.observe("42", observation())
    q.save("42", {"kind": "vote", "subject": H, "vote": "approve", "due": now + 86400})
    settings = deepcopy(DEFAULTS)
    settings["automation"]["enabled"] = True
    settings["automation"]["kinds"]["vote"] = True
    q.settings("42", settings)
    assert q.state("42")["items"][0]["due"] >= now + 86400


def test_automatic_mode_can_resume_without_repeating_completed_actions(tmp_path):
    now = datetime(2026, 11, 17, 10, tzinfo=UTC).timestamp()
    q = CommunityActions(tmp_path, lambda: now)
    q.observe("42", observation())
    settings = deepcopy(DEFAULTS)
    settings["templates"]["comment"] = "Merci pour le partage de {titre}"
    settings["automation"]["enabled"] = True
    settings["automation"]["kinds"]["comment"] = True
    q.settings("42", settings)
    settings["automation"]["enabled"] = False
    q.settings("42", settings)
    settings["automation"]["enabled"] = True
    q.settings("42", settings)
    assert len([i for i in q.state("42")["items"] if i["state"] == "queued"]) == 1


def test_settings_remove_stale_automatic_chat_and_preserve_manual(tmp_path):
    now = datetime(2026, 11, 17, 10, tzinfo=UTC).timestamp()
    q = CommunityActions(tmp_path, lambda: now)
    q.observe("42", observation())
    settings = deepcopy(DEFAULTS)
    settings["automation"].update(enabled=True, messages=["Un ancien message qui sera retiré"])
    settings["automation"]["kinds"]["chat"] = True
    q.settings("42", settings)
    settings["automation"].update(
        channels=["class"], messages=["Un nouveau message pour notre classe"]
    )
    q.settings("42", settings)
    queued = [i for i in q.state("42")["items"] if i["state"] == "queued"]
    assert len(queued) == 1
    assert queued[0]["subject"] == "135"
    assert queued[0]["content"] == "Un nouveau message pour notre classe"


def test_auto_vote_recovery_keeps_new_manual_choice(tmp_path):
    now = datetime(2026, 11, 17, 10, tzinfo=UTC).timestamp()
    q = CommunityActions(tmp_path, lambda: now)
    q.observe("42", observation())
    q.save("42", {"kind": "vote", "subject": H, "vote": "approve"})
    settings = deepcopy(DEFAULTS)
    settings["automation"]["enabled"] = True
    settings["automation"]["kinds"]["vote"] = True
    q.settings("42", settings)
    settings["automation"]["enabled"] = False
    q.settings("42", settings)
    q.save(
        "42",
        {
            "kind": "vote",
            "subject": H,
            "vote": "disapprove",
            "content": "Fichiers incomplets après vérification",
        },
    )
    settings["automation"]["enabled"] = True
    q.settings("42", settings)
    queued = [i for i in q.state("42")["items"] if i["state"] == "queued"]
    assert len(queued) == 1
    assert queued[0]["vote"] == "disapprove"


def test_limits_only_or_old_scan_cannot_complete_new_discovery(tmp_path):
    clock = [1000000.0]
    q = CommunityActions(tmp_path, lambda: clock[0])
    q.observe("42", observation())
    previous = q.demand("42")
    clock[0] += 10
    q.refresh("42")
    q.observe(
        "42",
        {
            **observation(),
            "candidates": [],
            "seeds": False,
            "scan": previous["scan"],
            "has_more": False,
        },
    )
    assert q.state("42")["refresh_pending"]
    assert len(q.state("42")["candidates"]) == 1
    current = q.demand("42")
    q.observe("42", {**observation(), "seeds": True, "scan": current["scan"], "has_more": False})
    assert not q.state("42")["refresh_pending"]
    assert len(q.state("42")["candidates"]) == 1


def test_explicit_cancel_after_automatic_recovery_stays_cancelled(tmp_path):
    now = datetime(2026, 11, 17, 10, tzinfo=UTC).timestamp()
    q = CommunityActions(tmp_path, lambda: now)
    q.observe("42", observation())
    q.save("42", {"kind": "vote", "subject": H, "vote": "approve"})
    settings = deepcopy(DEFAULTS)
    settings["enabled"] = True
    settings["automation"]["enabled"] = True
    settings["automation"]["kinds"]["vote"] = True
    q.settings("42", settings)
    settings["automation"]["enabled"] = False
    q.settings("42", settings)
    settings["automation"]["enabled"] = True
    q.settings("42", settings)
    item = q.state("42")["items"][0]
    q.control("42", item["id"], "cancel", item["revision"])
    assert q.claim("42") is None
    assert q.state("42")["items"][0]["state"] == "cancelled"


def test_manual_today_preserves_five_automatic_comments_tomorrow(tmp_path):
    from zoneinfo import ZoneInfo

    from tests.test_community import draft

    paris = ZoneInfo("Europe/Paris")
    now = datetime(2026, 11, 17, 23, 31, tzinfo=paris).timestamp()
    q = CommunityActions(tmp_path, lambda: now)
    q.observe(
        "42",
        {
            **observation(),
            "candidates": [{"hash": f"{i:040x}", "title": f"Torrent {i}"} for i in range(5)],
        },
    )
    settings = deepcopy(DEFAULTS)
    settings["templates"]["comment"] = "Merci pour le partage de {titre}"
    settings["automation"].update(enabled=True, start="10:00", timezone="Europe/Paris")
    settings["automation"]["kinds"]["comment"] = True
    q.settings("42", settings)
    before = {i["id"]: i["next_at"] for i in q.state("42")["items"]}
    manual = draft(q)
    after = {i["id"]: i for i in q.state("42")["items"]}
    assert {key: after[key]["next_at"] for key in before} == before
    assert all(datetime.fromtimestamp(t, paris).day == 18 for t in before.values())
    assert after[manual]["next_at"] == now


@pytest.mark.parametrize("kind", ["comment", "vote", "chat"])
@pytest.mark.parametrize("day", [(2026, 11, 17), (2026, 3, 29), (2026, 10, 25)])
def test_daily_limit_resets_at_paris_midnight_but_requires_fresh_site_snapshot(tmp_path, day, kind):
    from zoneinfo import ZoneInfo

    from tests.test_community import draft, receipt

    paris = ZoneInfo("Europe/Paris")
    local = datetime(*day, 23, 59, tzinfo=paris)
    clock = [local.timestamp()]
    q = CommunityActions(tmp_path, lambda: clock[0])
    settings = deepcopy(DEFAULTS)
    settings["enabled"] = True
    settings["limits"][kind] = 1
    settings["intervals"][kind] = 60
    q.settings("42", settings)
    q.observe("42", observation())
    draft(q, kind=kind, subject="1" if kind == "chat" else H)
    receipt(q, q.claim("42"))
    second = draft(
        q,
        kind=kind,
        subject="135" if kind == "chat" else "b" * 40,
        content="Un autre message pour la communauté",
    )
    midnight = (local.replace(hour=0, minute=0) + timedelta(days=1)).timestamp()
    item = next(i for i in q.state("42")["items"] if i["id"] == second)
    assert item["next_at"] == midnight
    clock[0] = midnight
    assert q.state("42")["quotas"][kind]["local_used"] == 0
    assert q.claim("42") is None  # yesterday's observation is only 60 seconds old
    q.observe("42", observation())
    assert q.claim("42")["id"] == second


def test_long_paris_day_keeps_early_sends_in_quota(tmp_path):
    from tests.test_community import draft, receipt

    paris = ZoneInfo("Europe/Paris")
    clock = [datetime(2026, 10, 25, 0, 5, tzinfo=paris).timestamp()]
    q = CommunityActions(tmp_path, lambda: clock[0])
    settings = deepcopy(DEFAULTS)
    settings["enabled"] = True
    settings["limits"]["comment"] = 1
    q.settings("42", settings)
    q.observe("42", observation())
    draft(q)
    receipt(q, q.claim("42"))
    second = draft(q, subject="b" * 40)
    clock[0] = datetime(2026, 10, 25, 23, 30, tzinfo=paris).timestamp()
    q.observe("42", observation())
    assert q.claim("42") is None
    state = q.state("42")
    assert state["quotas"]["comment"]["local_used"] == 1
    item = next(i for i in state["items"] if i["id"] == second)
    assert item["next_at"] == datetime(2026, 10, 26, tzinfo=paris).timestamp()


def test_cooldown_crosses_midnight_even_when_daily_quota_resets(tmp_path):
    from tests.test_community import draft, receipt

    paris = ZoneInfo("Europe/Paris")
    clock = [datetime(2026, 11, 17, 23, 59, 50, tzinfo=paris).timestamp()]
    q = CommunityActions(tmp_path, lambda: clock[0])
    q.settings("42", {**deepcopy(DEFAULTS), "enabled": True})
    q.observe("42", observation())
    draft(q)
    receipt(q, q.claim("42"))
    second = draft(q, subject="b" * 40)
    clock[0] += 10
    q.observe("42", observation())
    assert q.claim("42") is None
    item = next(i for i in q.state("42")["items"] if i["id"] == second)
    assert item["next_at"] == clock[0] + 50
    clock[0] += 50
    assert q.claim("42")["id"] == second


def test_turning_on_automatic_mode_runs_scheduled_actions_until_paused(tmp_path):
    now = datetime(2026, 11, 17, 10, tzinfo=UTC).timestamp()
    q = CommunityActions(tmp_path, lambda: now)
    q.observe("42", observation())
    settings = deepcopy(DEFAULTS)
    settings["templates"]["comment"] = "Merci pour le partage de {titre}"
    settings["automation"]["enabled"] = True
    settings["automation"]["kinds"]["comment"] = True
    q.settings("42", settings)
    # Automatic mode must not plan comments that the queue would never send.
    assert q.state("42")["settings"]["enabled"]
    assert q.claim("42")["kind"] == "comment"
    settings = q.state("42")["settings"]
    settings["enabled"] = False
    q.settings("42", settings)
    settings["automation"]["start"] = "08:00"
    q.settings("42", settings)
    assert not q.state("42")["settings"]["enabled"]
