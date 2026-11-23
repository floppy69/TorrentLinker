"""Search/detail scoring from facts already in memory, with no additional Indexer IO."""

from __future__ import annotations

import copy

from torrentlinker.release_score import judge
from torrentlinker.release_score.estimate import estimate
from torrentlinker.release_score.mediainfo import parse
from torrentlinker.release_score.preferences import Preferences

REASONS = {
    "resolution": ("Lower resolution than requested", "Résolution inférieure à celle demandée"),
    "hdr": ("HDR preference not met", "Préférence HDR non respectée"),
    "dv": ("Dolby Vision without HDR10", "Dolby Vision sans HDR10"),
    "avi": ("AVI not accepted by this profile", "AVI non accepté par ce profil"),
    "av1": ("Equipment cannot decode AV1", "L’appareil ne décode pas l’AV1"),
    "codec": ("H.265 / AV1 preference not met", "Préférence H.265 / AV1 non respectée"),
    "language": ("Requested audio language missing", "Langue audio demandée absente"),
    "subtitles": ("Full French subtitles missing", "Sous-titres français complets absents"),
    "size": ("Above the profile size cap", "Au-dessus du plafond de taille du profil"),
}


def score(facts: dict | None, preferences: dict) -> dict:
    prefs = Preferences.model_validate(preferences)
    result = (
        judge(
            facts,
            prefs.profiles[prefs.active].model_dump(),
            prefs.equipment.model_dump(by_alias=True),
            aspect=facts.get("aspect", 16 / 9),
            anim=facts.get("anim", False),
            vo=facts.get("vo", ""),
        )
        if facts
        else None
    )
    if result is None:
        result = dict(
            score=None,
            color="grey",
            estimated=True,
            criteria=[],
            summary="Not enough facts to calculate ReleaseScore",
            summary_fr="Données insuffisantes pour calculer ReleaseScore",
        )
    else:
        missing = [c for c in result["criteria"] if not c["ok"]]
        for c in result["criteria"]:
            c["label"], c["label_fr"] = REASONS[c["key"]]
        result["summary"] = "; ".join(REASONS[c["key"]][0] for c in missing) or "Fits the profile"
        result["summary_fr"] = (
            "; ".join(REASONS[c["key"]][1] for c in missing) or "Correspond au profil"
        )
        result["video_derived"] = bool((facts or {}).get("video_derived"))
    result.update(profile=prefs.active, version="0.3.0", best=False)
    return result


def mark_best(rows):
    candidates = [
        r["release_score"]
        for r in rows
        if r.get("release_score", {}).get("color") == "green"
        and r["release_score"].get("score") is not None
    ]
    for row in rows:
        if "release_score" in row:
            row["release_score"]["best"] = False
    if candidates:
        max(candidates, key=lambda s: s["value"])["best"] = True


def details_score(document: dict, preferences: dict, *, title="", size=0, listing=None):
    measured = copy.deepcopy(parse(document.get("nfo") or ""))
    info = document.get("info") or {}
    media = info.get("media") or {}
    files = document.get("files") or []
    title = title or document.get("title", "")
    total_size = size or document.get("size") or sum(f[1] for f in files)
    if measured:
        measured["anim"] = any(str(g).lower() == "animation" for g in media.get("genres", []))
        ratio = measured["w"] * measured.get("par", 1) / measured["h"]
        measured["aspect"] = (
            min(ratio, 2.76) if ratio > 16 / 9 + 0.005 else ratio if 1.2 <= ratio < 1.72 else 16 / 9
        )
        if media.get("kind") == "tv":
            videos = [
                f
                for f in files
                if str(f[0]).lower().endswith((".mkv", ".mp4", ".avi", ".m4v", ".ts"))
            ]
            if not videos or len(videos) != measured["nf"] or not measured["dtot"]:
                return score(None, preferences)
            measured["duree"] = measured["dtot"]
            measured["video"] = measured.get("vmoy", measured["video"])
        measured["taille"] = total_size or measured["taille"]
        return score(measured, preferences)
    return score(estimate(title, total_size, listing or media), preferences)
