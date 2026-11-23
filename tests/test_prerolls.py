"""Pre-roll selection fails closed on ratings and keeps random choices without repeats."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.test_members_media import server as media_server
from tests.test_members_signin import member, sign_in
from torrentlinker.accounts import OWNER_ACTOR, Actor, Permission
from torrentlinker.prerolls import (
    Clip,
    Configuration,
    Prerolls,
    Rules,
    Schedule,
    Sequence,
    Step,
    prerolls,
)


@pytest.fixture
def library(tmp_path):
    return Prerolls(SimpleNamespace(path=tmp_path / "settings.json"))


@pytest.fixture
def server(tmp_path):
    yield from media_server.__wrapped__(tmp_path)


def clip(library, title="Clip", rating="TP", **values):
    result = Clip(title=title, rating=rating, duration=10, **values)
    library.data["clips"].append(result.model_dump())
    (library.root / (result.id + ".mp4")).write_bytes(b"fake fixture clip")
    return result


def enable(library, steps, **values):
    sequence = Sequence(name="Cinema", steps=steps, **values)
    library.configure(
        Configuration(enabled=True, default_sequence=sequence.id, sequences=[sequence]).model_dump()
    )
    return sequence


def feature(rating="18", **values):
    return {"kind": "video", "age_rating": {"rating": rating}, **values}


def test_random_without_repeats_survives_restart_and_fallback(library):
    clips = [clip(library, title=str(i)) for i in range(3)]
    enable(library, [Step(kind="random")])
    first = library.plan(feature())["steps"][0]["clip"]
    reopened = Prerolls(library.setup)
    second = reopened.plan(feature())["steps"][0]["clip"]
    third = reopened.plan(feature())["steps"][0]["clip"]
    assert {first, second, third} == {c.id for c in clips}
    enable(reopened, [Step(clip="missing", fallback=first), Step(kind="pause", seconds=2)])
    planned = reopened.plan(feature())["steps"]
    assert planned[0]["clip"] == first and planned[1]["kind"] == "pause"


def test_ratings_never_exceed_feature_or_viewer_and_unknowns_are_restricted(library):
    general, adult, unknown = clip(library), clip(library, rating="18"), clip(library, rating=None)
    enable(library, [Step(clip=c.id) for c in [general, adult, unknown]])
    child = Actor("member", frozenset({Permission.FILMS}), age_limit=1, viewer="child")
    assert [s["clip"] for s in library.plan(feature(), child)["steps"]] == [general.id]
    assert [s["clip"] for s in library.plan(feature("TP"))["steps"]] == [general.id]
    assert [s["clip"] for s in library.plan(feature(None))["steps"]] == [general.id]
    assert [s["clip"] for s in library.plan(feature())["steps"]] == [general.id, adult.id]


def test_calendar_priority_annual_holiday_and_default_fill(library):
    ordinary, special = clip(library), clip(library, "Holiday")
    base = Sequence(name="Default", steps=[Step(clip=ordinary.id)])
    holiday = Sequence(name="Holiday", steps=[Step(clip=special.id)])
    event = Schedule(
        name="Christmas",
        sequence=holiday.id,
        priority=20,
        date_from="2026-12-24",
        date_to="2026-12-26",
        yearly=True,
    )
    library.configure(
        Configuration(
            enabled=True, default_sequence=base.id, sequences=[base, holiday], schedules=[event]
        ).model_dump()
    )
    assert (
        library.plan(feature(), now=datetime(2027, 12, 25, tzinfo=ZoneInfo("Europe/Paris")))[
            "sequence"
        ]
        == "Holiday"
    )
    assert (
        library.plan(feature(), now=datetime(2027, 12, 27, tzinfo=ZoneInfo("Europe/Paris")))[
            "sequence"
        ]
        == "Default"
    )
    overnight = Schedule(name="Night", sequence=base.id, start="22:00", end="02:00", weekdays=[4])
    assert overnight.active(datetime(2026, 11, 20, 23, tzinfo=ZoneInfo("Europe/Paris")))
    assert overnight.active(datetime(2026, 11, 21, 1, tzinfo=ZoneInfo("Europe/Paris")))
    assert not overnight.active(datetime(2026, 11, 22, 1, tzinfo=ZoneInfo("Europe/Paris")))
    assert not overnight.active(datetime(2026, 11, 20, 12, tzinfo=ZoneInfo("Europe/Paris")))


def test_rules_match_genre_kind_audio_person_and_hours(library):
    rules = Rules(
        kind="episode",
        genres=["Adventure"],
        audio=["AAC"],
        accounts=["lea"],
        viewers=["kid"],
        start="18:00",
        end="22:00",
    )
    actor = Actor("lea", frozenset({Permission.FILMS}), viewer="kid")
    now = datetime(2026, 11, 21, 20, tzinfo=ZoneInfo("Europe/Paris"))
    episode = feature(series="Series", genres=["Adventure"], audio="AAC stereo")
    assert library.matches(rules, episode, actor, now)
    assert not library.matches(rules, episode, OWNER_ACTOR, now)
    assert not library.matches(rules, {**episode, "series": ""}, actor, now)
    assert not library.matches(rules, {**episode, "audio": "DTS"}, actor, now)
    assert not library.matches(rules, episode, actor, now.replace(hour=8))


def test_member_stream_checks_feature_visibility_and_rating_again(server):
    app, browser, ids, _folders = server
    library = prerolls(app.state.agent_service.setup)
    general, adult = clip(library), clip(library, rating="18")
    enable(library, [Step(clip=general.id), Step(clip=adult.id)])
    lea = member(app, "lea", Permission.FILMS)
    app.state.accounts.set_media_limits(lea, "16", None)
    sign_in(browser, "lea")
    identifier = ids["The Revenant"]
    response = browser.get(f"/api/media/items/{identifier}/prerolls")
    assert response.status_code == 200, response.text
    assert [s["clip"] for s in response.json()["steps"]] == [general.id]
    assert browser.get("/" + response.json()["steps"][0]["url"]).status_code == 200
    assert (
        browser.get(f"/api/media/items/{identifier}/prerolls/{adult.id}/stream").status_code == 404
    )
    app.state.accounts.set_media_limits(lea, "12", None)
    assert (
        browser.get(f"/api/media/items/{identifier}/prerolls/{general.id}/stream").status_code
        == 404
    )
    assert browser.get("/api/prerolls").status_code == 403
    assert browser.post("/api/prerolls/configure", json={}).status_code == 403


def test_tmdb_only_returns_youtube_trailer_links():
    import httpx

    from torrentlinker.tmdb import Tmdb

    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"site": "YouTube", "type": "Trailer", "key": "abcdefghijk", "name": "Trailer"},
                    {"site": "YouTube", "type": "Clip", "key": "abcdefghijk"},
                    {"site": "YouTube", "type": "Trailer", "key": "https://private.test"},
                    {"site": "Other", "type": "Trailer", "key": "abcdefghijk"},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        result = Tmdb("test-key", http).videos("123", "movie")
    assert len(result) == 1 and result[0]["key"] == "abcdefghijk"
    assert requests[0].url.path == "/3/movie/123/videos"
