"""ReleaseScore 0.3.0 Rapide, ported from Pila33's MIT-licensed engine.

Reference commit cb65746203871d29a04acdf5447c3f662ba072cb. No network IO.
Profile fit and numeric quality are separate: red means over the size cap.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

PROFILES = json.loads(Path(__file__).with_name("profiles.json").read_text(encoding="utf-8"))
MAXIMUM = {2160: 95, 1080: 85, 720: 45, 576: 32}
EFFORT = {
    "fast": 0.92,
    "medium": 1,
    "slow": 1.06,
    "slow+": 1.08,
    "slower": 1.1,
    "veryslow": 1.12,
    "placebo": 1.13,
}


def js_round(n: float) -> int:
    return math.floor(n + 0.5)


def effort(v: dict) -> str | None:
    e = v.get("enc") or {}
    if not any(
        e.get(k) is not None for k in ("subme", "ref", "bframes", "me", "trellis", "rd", "rcla")
    ):
        return None

    def ge(k, n):
        return e.get(k) is not None and e[k] >= n

    if re.search("x264", v.get("lib") or "", re.I) or e.get("trellis") is not None:
        if ge("subme", 11):
            return "placebo"
        if ge("subme", 10) and ge("me", 2):
            return "veryslow"
        if ge("subme", 9):
            return "slower"
        if ge("subme", 8):
            return "slow"
        if ge("subme", 7):
            return "medium"
        return "fast"
    if ge("subme", 5) or ge("me", 4):
        return "placebo"
    if ge("rd", 6) and ge("subme", 4):
        return "veryslow"
    if ge("subme", 4):
        return "slower"
    if ge("rd", 4) and ge("me", 3):
        return "slow+" if ge("ref", 5) or ge("bframes", 8) or ge("rcla", 40) else "slow"
    return "medium" if ge("rd", 3) and ge("subme", 2) else "fast"


def pixels(w, h, aspect=16 / 9, par=1):
    return min(w, js_round((h or w) * aspect / par)) * min(h or w, js_round(w * par / aspect))


def note_video(v: dict, *, aspect: float = 16 / 9, anim: bool = False) -> dict | None:
    if not v.get("video", 0) > 0 or not v.get("w", 0) > 0:
        return None
    w, h, par = v["w"], v.get("h") or v["w"] * 9 / 16, v.get("par") or 1
    width = max(js_round(w * par), js_round(h * 16 / 9))
    cls = 2160 if width >= 3000 else 1080 if width >= 1700 else 720 if width >= 1200 else 576
    useful = w * h if v.get("pleinCadre") else pixels(w, v.get("h"), aspect, par)
    maximum = MAXIMUM[cls]
    lower = {2160: 1080, 1080: 720}.get(cls)
    if lower:
        frames = {2160: (3840, 2160), 1080: (1920, 1080), 720: (1280, 720)}

        def frame(c):
            a, b = frames[c]
            return a * b if v.get("pleinCadre") else pixels(a, b, aspect)

        high, low = frame(cls) * 0.97, frame(lower)
        if useful < high:
            maximum = MAXIMUM[lower] + (MAXIMUM[cls] - MAXIMUM[lower]) * max(0, useful - low) / (
                high - low
            )
    fc = {"H.264": 1, "H.265": 1.6, "AV1": 2, "XviD": 0.7}.get(str(v.get("codec")), 1)
    fb = 1.05 if (v.get("bits") or 0) >= 10 else 1
    ef = effort(v)
    fe = EFFORT[ef] if ef else 1
    fm = (
        0.7
        if re.search(r"nvenc|qsv|quick ?sync|amf|vce|videotoolbox", v.get("lib") or "", re.I)
        else 1
    )
    fa = 0.5 if anim else 1
    ratio = useful / (1920 * 1080)
    k = 4 * ratio ** (0.75 if ratio <= 1 else 0.5) * fa
    effective = v["video"] * fc * fb * fe * fm
    return dict(
        note=maximum * (1 - math.exp(-effective / k)),
        cls=cls,
        maxi=maximum,
        pix=useful,
        fC=fc,
        fB=fb,
        fE=fe,
        ef=ef,
        fM=fm,
        fA=fa,
        eff=effective,
        k=k,
    )


def note_track(p: dict) -> float:
    fmt = (str(p.get("format") or "") + " " + str(p.get("brut") or "")).lower()
    channels = p.get("canaux") or 2
    factor = 1.03 if channels >= 8 else 1 if channels >= 6 else 0.75 if channels >= 2 else 0.6
    if re.search(r"truehd|mlp|dts-hd master|xll|flac|pcm", fmt):
        n = 92.0 + (4 if re.search(r"atmos|mlp fba|dts:x|xll x", fmt) else 0)
    else:
        choices = [
            (r"plus|e-ac-3|eac3", 84, 45, 640),
            (r"dolby digital|ac-3|ac3", 76, 55, 448),
            (r"dts", 84, 110, 1509),
            (r"he-aac|sbr", 72, 22, 128),
            (r"aac", 82, 40, 192),
            (r"opus", 84, 30, 192),
        ]
        entry = next((c for c in choices if re.search(c[0], fmt)), ("", 70, 60, 384))
        pattern, maximum, scale, default = entry
        rate = (p.get("debit") or default) if (p.get("debit") or 0) > 0 else default
        n = maximum * (1 - math.exp(-(rate / channels) / scale))
        if re.search(r"joc|atmos", fmt) or (pattern == choices[0][0] and rate >= 768):
            n += 3
    return min(100, n * factor)


IDEAL_AUDIO = {
    "correct": ({"format": "Dolby Digital", "brut": "AC-3", "canaux": 6, "debit": 448}, 0.9),
    "bon": (
        {
            "format": "Dolby Digital Plus with Dolby Atmos",
            "brut": "E-AC-3 JOC",
            "canaux": 6,
            "debit": 768,
        },
        1.5,
    ),
    "sansperte": (
        {"format": "Dolby TrueHD with Dolby Atmos", "brut": "MLP FBA", "canaux": 8, "debit": 3690},
        4.5,
    ),
}


def judge(
    v: dict, r: dict, equipment: dict | None = None, *, aspect=16 / 9, anim=False, vo=""
) -> dict | None:
    """Return Rapide components with stable criterion keys for translated UI explanations."""
    nv = note_video(v, aspect=aspect, anim=anim)
    if nv is None:
        return None
    equipment = equipment or {}
    ideal_track, audio_rate = IDEAL_AUDIO[r["audio"]]
    ia = note_track(ideal_track)
    iv = MAXIMUM[int(r["res"])] * 0.99
    if r["cible"] > 0:
        w, h = (3840, 2160) if r["res"] == "2160" else (1920, 1080)
        ideal = note_video(
            dict(
                w=w,
                h=h,
                bits=10,
                codec="H.265",
                video=max(0.3, r["cible"] * 8000 / 3600 - audio_rate),
            ),
            aspect=aspect,
            anim=anim,
        )
        assert ideal is not None
        iv = ideal["note"]
    tracks = [p for p in v.get("pistes", []) if not p.get("role")]

    def wanted(p):
        lang = p.get("langue")
        return lang == "?" or (
            lang == "vff"
            if r["langue"] == "vff"
            else lang in ("vff", "vfq")
            if r["langue"] == "vf"
            else lang == "vo" or (vo == "fr" and lang in ("vff", "vfq", "vfb"))
            if r["langue"] == "vo"
            else True
        )

    candidates = [p for p in tracks if wanted(p)]

    def readable(items):
        return [
            p
            for p in items
            if not (
                equipment.get("dts") == "non"
                and re.search(
                    "dts|xll", str(p.get("format", "")) + " " + str(p.get("brut", "")), re.I
                )
            )
        ]

    pool = (
        readable(candidates)
        or readable([p for p in tracks if p.get("langue") in ("vff", "vfq", "vfb")])
        or readable(tracks)
    )
    na = max(map(note_track, pool), default=0)
    criteria: list[dict[str, Any]] = []

    def add(key, ok, factor, detail="", unknown=False):
        criteria.append(
            dict(key=key, ok=bool(ok), factor=1 if ok else factor, detail=detail, unknown=unknown)
        )

    if r["basse"] == "penal":
        add("resolution", nv["cls"] >= int(r["res"]), 0.6, str(nv["cls"]))
    hdr = bool(v.get("hdr") and v["hdr"] != "SDR")
    for setting, ok, factor in (
        ("sdr-req", not hdr, 0.6),
        ("sdr-pref", not hdr, 0.9),
        ("requis", hdr, 0.6),
        ("pref", hdr, 0.9),
    ):
        if r["hdr"] == setting:
            add("hdr", ok, factor, v.get("hdr") or "SDR")
    for key, ok, penalty in (("dv", v.get("hdr") != "DV seul", 0.5), ("avi", not v.get("avi"), 0)):
        setting = r[key]
        if setting == "auto":
            setting = {"oui": "ok", "non": "refuse"}.get(str(equipment.get(key)), "deconseille")
        if setting != "ok":
            add(key, ok, penalty if setting == "refuse" else 0.9)
    if equipment.get("av1") == "non":
        add("av1", v.get("codec") != "AV1", 0.5)
    if r["codec"] != "indiff":
        add(
            "codec",
            v.get("codec") not in ("H.264", "XviD"),
            0.6 if r["codec"] == "requis" else 0.9,
            v.get("codec") or "?",
        )
    if r["langue"] != "indiff":
        add("language", bool(candidates), 0.7, r["langue"])
    if r["st"] in ("pref", "requis"):
        subtitles = v.get("st")
        add(
            "subtitles",
            subtitles is None
            or any(s.get("langue") == "fr" and not s.get("force") for s in subtitles),
            0.7 if r["st"] == "requis" else 0.9,
            unknown=subtitles is None,
        )
    hours = (v.get("duree") or 0) / 60
    goh = v.get("taille", 0) / 1e9 / hours if hours > 0 and v.get("taille", 0) > 0 else None
    fp = 1.0
    if r["cible"] > 0 and goh:
        cap = max(r["plafond"] or r["cible"], r["cible"])
        if goh > cap:
            fp = 0.85 * cap / goh
            add("size", False, 1, str(cap))
        elif goh > r["cible"]:
            fp = 1 - 0.15 * (goh - r["cible"]) / max(0.01, cap - r["cible"])
    wa = r["poidsAudio"] / 100
    pv, pa = min(1, nv["note"] / iv), min(1, na / ia) if ia > 0 else 1
    fc = math.prod(c["factor"] for c in criteria)
    value = 100 * ((1 - wa) * pv + wa * pa) * fp * fc
    missing = [c for c in criteria if not c["ok"]]
    color = (
        "red"
        if any(c["key"] == "size" for c in missing)
        else "grey"
        if len(missing) >= 2
        else "yellow"
        if missing
        else "green"
    )
    return dict(
        score=js_round(value),
        value=value,
        color=color,
        estimated=bool(v.get("estime")),
        video=nv,
        audio=na,
        gb_per_hour=goh,
        criteria=criteria,
        size_factor=fp,
        criteria_factor=fc,
        video_share=pv,
        audio_share=pa,
    )
