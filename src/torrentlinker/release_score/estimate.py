"""Author-specified listing estimates. Never fetch missing facts or guess pack durations."""

from __future__ import annotations

import re


def codec_of(text: str) -> str:
    for pattern, codec in (
        (r"AV1", "AV1"),
        (r"HEVC|[HX][ ._-]?265", "H.265"),
        (r"AVC|[HX][ ._-]?264", "H.264"),
        (r"XVID|DIVX|MPEG-4 VISUAL", "XviD"),
    ):
        if re.search(pattern, text, re.I):
            return codec
    return "?"


def hdr_of(text: str) -> str:
    dv = bool(re.search(r"\bDV\b|DOVI|DOLBY.?VISION", text, re.I))
    hdr = (
        "HDR10+"
        if re.search(r"HDR10\+|HDR10PLUS|2094", text, re.I)
        else "HDR10"
        if re.search(r"HDR|2086|PQ", text, re.I)
        else "HLG"
        if "HLG" in text.upper()
        else "SDR"
    )
    return ("DV seul" if hdr == "SDR" else "DV + " + hdr) if dv else hdr


def estimate(title: str, size: int, listing: dict) -> dict | None:
    runtime = listing.get("runtime")
    if not isinstance(runtime, (int, float)) or runtime <= 0 or size <= 0:
        return None
    # TV runtime is per episode. An explicit single episode is usable; a pack is not.
    single_episode = re.search(r"\b(?:S\d{1,2}E\d{1,3}|\d{1,2}x\d{1,3})\b", title, re.I)
    pack = re.search(
        r"\bS\d{1,2}\b|\b(?:SEASON|SAISON|COMPLETE|INTEGRALE)\b|"
        r"E\d{1,3}[- ._]*(?:E\d|[-–]\d)|\d{1,2}x\d{1,3}[-–]\d",
        title,
        re.I,
    )
    if pack or (listing.get("kind") == "tv" and not single_episode):
        return None
    if listing.get("kind") not in ("movie", "tv", ""):
        return None
    tags = dict(listing.get("tags") or [])
    text = (title + " " + " ".join(str(v) for v in tags.values())).upper()
    resolution = tags.get("resolution", "") or title
    width = next(
        (
            w
            for pattern, w in (
                (r"2160|4K|UHD", 3840),
                (r"1080", 1920),
                (r"720", 1280),
                (r"576|480", 720),
            )
            if re.search(pattern, resolution, re.I)
        ),
        0,
    )
    if not width:
        return None
    audio = (tags.get("audio") or title).upper()
    stereo = bool(re.search(r"2[ .]0|STEREO", audio))
    channels = 2 if stereo else 8 if "7.1" in audio else 6
    eac3 = 0.224 if stereo else 0.768 if "7.1" in audio or "ATMOS" in audio else 0.64
    formats = [
        (r"E-?AC-?3|DDP|DD\+|DIGITAL PLUS", "E-AC-3", eac3),
        (r"AC-?3|DOLBY DIGITAL", "AC-3", 0.192 if stereo else 0.448),
        (r"HE.?AAC", "HE-AAC", 0.08 if stereo else 0.224),
        (r"AAC|OPUS", "Opus" if "OPUS" in audio else "AAC", 0.16 if stereo else 0.32),
    ]
    lossy = next(((fmt, rate) for pattern, fmt, rate in formats if re.search(pattern, audio)), None)
    lossless = next(
        (
            (fmt, rate)
            for pattern, fmt, rate in (
                (r"TRUEHD|MLP", "TrueHD Atmos" if "ATMOS" in audio else "TrueHD", 3.3),
                (r"DTS[: -]?X", "DTS XLL X", 3.5),
                (r"DTS.?HD.?MA|DTS.?HD MASTER|XLL", "DTS XLL", 3),
                (r"L?PCM", "PCM", 1.5 if stereo else 4.6),
            )
            if re.search(pattern, audio)
        ),
        None,
    )
    if not lossless and "ATMOS" in audio and not lossy:
        lossless = ("TrueHD Atmos", 3.3)
    if lossy is None:
        lossy = ("DTS", 1.5) if "DTS" in audio and not lossless else ("?", 0.45)
    count = 1 + int("MULTI" in text) + int("VF2" in text)
    total_audio = (
        lossless[1] + (count - 1) * (eac3 if lossy[1] == 0.45 else lossy[1])
        if lossless
        else lossy[1] * count
    )
    global_rate = size * 8 / (runtime * 60) / 1e6
    cap = 0.7 if lossless or "DTS" in audio else 0.6 if count >= 3 else 0.4
    langs = []
    if re.search(r"VFF|TRUEFRENCH|FRENCH|\bFR\b|VF2|MULTI", text):
        langs.append("vff")
    if re.search(r"VFQ|VF2", text):
        langs.append("vfq")
    if re.search(r"MULTI|VOSTFR|\bVO\b|ENGLISH|\bEN\b", text):
        langs.append("vo")
    langs = (langs or ["?"])[:count]
    langs += ["?"] * (count - len(langs))
    secondary = ("E-AC-3", eac3) if lossless and lossy[1] == 0.45 else lossy
    tracks = []
    for i, lang in enumerate(langs):
        fmt, rate = lossless if i == 0 and lossless else secondary
        tracks.append(dict(format=fmt, canaux=channels, debit=rate * 1000, langue=lang))
    result = dict(
        w=width,
        h=width * 9 / 16,
        bits=10 if re.search(r"10[ .-]?BITS?", text) else None,
        codec=codec_of(tags.get("codec", "") or title),
        hdr=hdr_of(tags.get("hdr", "") or title),
        video=global_rate - min(total_audio, cap * global_rate),
        pistes=tracks,
        taille=size,
        duree=runtime,
        estime=True,
        avi=bool(re.search(r"\.AVI\b|\bXVID\b", title, re.I)),
    )
    result["anim"] = any(str(g).lower() == "animation" for g in listing.get("genres", []))
    if "VOSTFR" in text:
        result["st"] = [dict(langue="fr", force=False)]
    return result
