"""Offline parity with the pinned MIT upstream engine, not a second Python formula."""

import json
from pathlib import Path

import pytest

from torrentlinker.release_score import PROFILES, judge

REFERENCE = json.loads((Path(__file__).parent / "fixtures/release_score/rapide.json").read_text())


@pytest.mark.parametrize("case", REFERENCE["cases"])
def test_rapide_matches_upstream(case):
    result = judge(case["facts"], PROFILES[case["profile"]], case["equipment"])
    assert result is not None
    for key, value in case["expected"].items():
        actual = result["video"]["note"] if key == "video" else result[key]
        assert actual == pytest.approx(value, abs=1e-10), key


def test_estimates_unknown_runtime_and_pack_counts():
    from torrentlinker.release_score.estimate import estimate
    from torrentlinker.release_score.service import score

    title = "Film.MULTI.VFF.1080p.x265.EAC3.5.1"
    listing = {"runtime": 120, "kind": "movie"}
    facts = estimate(title, 4_000_000_000, listing)
    assert facts and facts["estime"]
    assert facts["video"] == pytest.approx(4e9 * 8 / 7200 / 1e6 - 1.28)
    assert len(facts["pistes"]) == 2
    assert score(facts, {})["estimated"]
    assert estimate(title, 4_000_000_000, {}) is None
    assert estimate("Series.S01.10episodes.1080p", 4_000_000_000, {**listing, "kind": "tv"}) is None
    assert score(None, {})["score"] is None


NFO = """General
Format : Matroska
Duration : 2 h 0 min
File size : 4.0 GB
Video
Format : HEVC
Width : 1 920 pixels
Height : 1 080 pixels
Bit rate : 4 000 kb/s
Bit depth : 10 bits
Audio
Format : E-AC-3
Channel(s) : 6 channels
Bit rate : 640 kb/s
Language : French
"""


def test_measured_details_and_profile_fit_are_separate_from_score():
    from torrentlinker.release_score.mediainfo import parse
    from torrentlinker.release_score.preferences import Preferences
    from torrentlinker.release_score.service import details_score, mark_best, score

    measured = parse(NFO)
    assert measured and measured["video"] == 4 and measured["w"] == 1920
    assert measured["duree"] == 120 and not measured["estime"]
    result = details_score({"nfo": NFO}, {})
    assert result["score"] is not None and result["estimated"] is False
    assert result["color"] == "green"
    prefs = Preferences().model_dump(by_alias=True)
    prefs["profiles"][prefs["active"]]["plafond"] = 1
    prefs["profiles"][prefs["active"]]["cible"] = 1
    assert score(measured, prefs)["color"] == "red"
    rows = [{"release_score": result}, {"release_score": score(None, {})}]
    mark_best(rows)
    assert rows[0]["release_score"]["best"] and not rows[1]["release_score"]["best"]
    assert details_score(
        {"nfo": "unreadable"},
        {},
        title="Film.1080p.x265",
        size=4e9,
        listing={"runtime": 120, "kind": "movie"},
    )["estimated"]


def test_french_mediainfo_and_incomplete_facts():
    from torrentlinker.release_score.mediainfo import parse

    french = (
        NFO.replace("General", "Général")
        .replace("Video", "Vidéo")
        .replace("Duration", "Durée")
        .replace("Width", "Largeur")
        .replace("Height", "Hauteur")
        .replace("Bit rate", "Débit")
        .replace("Language : French", "Langue : Français")
    )
    assert parse(french)["pistes"][0]["langue"] == "vff"
    assert parse("Video\nFormat : HEVC") is None
    assert parse(NFO.replace("Bit rate : 4 000 kb/s", "Stream size : 3.6 GB"))["video"] == 4


def test_equipment_recommendation_and_validation():
    from pydantic import ValidationError

    from torrentlinker.release_score.preferences import Equipment, Preferences

    e = Equipment.model_validate({"def": "4k", "hdr": "oui", "son": "atmos", "priorite": "qualite"})
    assert e.recommendation()["res"] == "2160"
    assert e.recommendation()["audio"] == "sansperte"
    with pytest.raises(ValidationError):
        Equipment(taille=float("nan"))
    with pytest.raises(ValidationError):
        Preferences(profiles={})


def test_identical_nfo_does_not_share_document_size_or_duration():
    from torrentlinker.release_score.service import details_score

    first = details_score({"nfo": NFO}, {}, size=20_000_000_000)
    second = details_score({"nfo": NFO}, {})
    assert first["color"] == "red"
    assert second["gb_per_hour"] == 2
    assert second["color"] == "green"


def test_single_episodes_and_lossless_secondary_tracks():
    from torrentlinker.release_score import note_track
    from torrentlinker.release_score.estimate import estimate

    listing = {"runtime": 45, "kind": "tv"}
    assert estimate("Show.S01E01.1080p.x265", 2_000_000_000, listing) is not None
    assert estimate("Show.S01.1080p.x265", 2_000_000_000, listing) is None
    assert estimate("Show.S01E01-E02.1080p.x265", 2_000_000_000, listing) is None
    assert estimate("Show.S01E01E02.1080p.x265", 2_000_000_000, listing) is None
    facts = estimate(
        "Film.MULTI.VF2.1080p.x265.TrueHD.Atmos.7.1",
        10_000_000_000,
        {"runtime": 120, "kind": "movie"},
    )
    assert facts is not None
    first, second, third = facts["pistes"]
    assert first["format"] == "TrueHD Atmos"
    assert second["format"] == third["format"] == "E-AC-3"
    assert second["debit"] == third["debit"] == 768
    assert note_track(first) > note_track({**first, "format": "TrueHD"})
