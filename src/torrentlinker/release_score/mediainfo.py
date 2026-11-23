"""Read English/French MediaInfo text already fetched with torrent details.

This parser never reads paths or URLs from the NFO. Incomplete video sections
fall back to the separately labelled listing estimate.
"""

from __future__ import annotations

import re
from functools import lru_cache

from torrentlinker.release_score.estimate import codec_of, hdr_of


def number(text):
    found = re.search(r"\d+(?:[.,]\d+)?", re.sub(r"\s", "", str(text or "")))
    return float(found[0].replace(",", ".")) if found else 0.0


def duration(text):
    text = str(text or "").lower()
    clock = re.search(r"(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if clock:
        return int(clock[1]) * 60 + int(clock[2]) + float(clock[3]) / 60
    total = 0.0
    for pattern, multiplier in (
        (r"(\d+(?:[.,]\d+)?)\s*h", 60),
        (r"(\d+(?:[.,]\d+)?)\s*(?:min|mn)", 1),
        (r"(\d+(?:[.,]\d+)?)\s*s", 1 / 60),
    ):
        found = re.search(pattern, text)
        if found:
            total += float(found[1].replace(",", ".")) * multiplier
    return total


def size(text):
    found = re.search(r"([KMGT])(i?)[Bo]", str(text or ""), re.I)
    return (
        number(text) * ((1024 if found[2] else 1000) ** ("KMGT".index(found[1].upper()) + 1))
        if found
        else number(text)
    )


def bitrate(text):
    if not text:
        return 0.0
    n = number(text)
    return n * (
        1000
        if re.search(r"Mb|Mbit", text, re.I)
        else 1
        if re.search(r"kb|kbit", text, re.I)
        else 0.001
    )


def get(fields, *keys):
    return next((fields[k.casefold()] for k in keys if fields.get(k.casefold())), "")


@lru_cache(maxsize=16)
def parse(text: str) -> dict | None:
    files: list[list[tuple[str, dict]]] = [[]]
    current: dict[str, str] | None = None
    for line in text[:2_000_000].splitlines():
        line = line.strip(" \t║│┃|┆")
        header = re.fullmatch(
            r"(General|Général|Video|Vidéo|Audio|Text|Texte|Menu)(?:\s*#?\s*\d+)?", line, re.I
        )
        if header:
            name = {"général": "general", "vidéo": "video", "texte": "text"}.get(
                header[1].casefold(), header[1].casefold()
            )
            if name == "general" and files[-1]:
                files.append([])
            current = {}
            files[-1].append((name, current))
        elif current is not None:
            match = re.match(r"([^:]+?)\s*:\s*>?\s*(.*)", line)
            if match:
                for key in match[1].split("|"):
                    current.setdefault(key.strip().casefold(), match[2].strip())
    parsed = [result for sections in files if (result := parse_file(sections))]
    if not parsed:
        return None
    result = max(parsed, key=lambda f: f["duree"])
    result["nf"] = len(parsed)
    result["dtot"] = sum(f["duree"] for f in parsed)
    if result["dtot"]:
        result["vmoy"] = sum(f["video"] * f["duree"] for f in parsed) / result["dtot"]
    return result


def parse_file(sections):
    gen = next((f for k, f in sections if k == "general"), {})
    video = next((f for k, f in sections if k == "video"), {})
    w, h = number(get(video, "Width", "Largeur")), number(get(video, "Height", "Hauteur"))
    minutes = duration(get(video, "Duration", "Durée")) or duration(get(gen, "Duration", "Durée"))
    if not w or not h:
        return None
    rate = (
        bitrate(get(video, "Bit rate", "Bitrate", "Débit", "Nominal bit rate", "Débit nominal"))
        / 1000
    )
    stream_size = size(get(video, "Stream size", "Taille du flux", "Taille des données"))
    measured = stream_size * 8 / (minutes * 60) / 1e6 if minutes else 0
    if measured and (not rate or rate / 3 < measured < rate * 3):
        rate = measured
    tracks = []
    subtitles = []
    for kind, fields in sections:
        if kind not in ("audio", "text"):
            continue
        lang = get(fields, "Language", "Langue").lower()
        title = get(fields, "Title", "Titre").lower()
        french = bool(
            re.match(r"fr|fre|fra|french|fran", lang)
            or not lang
            and re.search(r"\b(vf|vff|vfq|vfb|french|français)\b", title)
        )
        if kind == "text":
            subtitles.append(
                dict(
                    langue="fr" if french else lang or "?",
                    force=bool(
                        re.match("yes|oui|1|true", get(fields, "Forced", "Forcé", "Forcée"), re.I)
                        or "forc" in title
                    ),
                )
            )
            continue
        language = "?" if not lang and not title else "vo"
        if french:
            language = (
                "vfq"
                if re.search(r"vfq|qu[eé]b|canad|fr-ca", lang + title)
                else "vfb"
                if re.search(r"vfb|belg|fr-be", lang + title)
                else "vff"
            )
        role_text = title + " " + get(fields, "Service kind", "Genre de service", "Type de service")
        role = (
            "commentaire"
            if re.search("comment", role_text, re.I)
            else "AD"
            if re.search(r"audio.?desc|\bad\b|visually impaired|malvoyant", role_text, re.I)
            else ""
        )
        tracks.append(
            dict(
                format=get(
                    fields, "Commercial name", "Nom commercial", "Format, Nom commercial IfAny"
                ),
                brut=get(fields, "Format"),
                canaux=number(get(fields, "Channel(s)", "Canal(aux)", "Canaux")) or 2,
                debit=bitrate(get(fields, "Bit rate", "Bitrate", "Débit")) or None,
                langue=language,
                role=role,
            )
        )
    # If only the overall bitrate exists, derive video without pretending it was measured.
    derived = False
    if not rate:
        overall = bitrate(get(gen, "Overall bit rate", "Débit global", "Débit total")) / 1000
        if not overall and minutes:
            overall = size(get(gen, "File size", "Taille du fichier")) * 8 / (minutes * 60) / 1e6
        if overall:
            rate = max(overall * 0.5, overall - sum((p["debit"] or 640) / 1000 for p in tracks))
            derived = True
    if not rate:
        return None
    library = get(video, "Writing library", "Bibliothèque utilisée")
    settings = get(video, "Encoding settings", "Paramètres d'encodage")
    enc = {}
    for key in ("subme", "ref", "bframes", "me", "trellis", "rd", "rc-lookahead", "rc_lookahead"):
        match = re.search(r"(?:^|[ /])" + re.escape(key) + r"=(\d+)", settings)
        if match:
            enc["rcla" if key.startswith("rc") else key] = int(match[1])
    me = re.search(r"(?:^|[ /])me=(dia|hex|umh|esa|tesa)", settings)
    if me:
        enc["me"] = ["dia", "hex", "umh", "esa", "tesa"].index(me[1])
    result = dict(
        w=w,
        h=h,
        duree=minutes,
        taille=size(get(gen, "File size", "Taille du fichier")),
        video=rate,
        bits=number(get(video, "Bit depth", "Profondeur binaire", "Profondeur de bits")) or None,
        codec=codec_of(get(video, "Format")),
        hdr=hdr_of(
            get(video, "HDR format", "Format HDR")
            + " "
            + get(video, "Transfer characteristics", "Caractéristiques du transfert")
        ),
        pistes=tracks,
        st=subtitles,
        lib=library,
        enc=enc or None,
        estime=False,
        video_derived=derived,
        avi=get(gen, "Format").upper() == "AVI",
    )
    aspect = get(
        video, "Display aspect ratio", "Format d'affichage", "Rapport largeur/hauteur à l'affichage"
    )
    if aspect:
        a = aspect.split(":")
        dar = number(a[0]) / number(a[1]) if len(a) == 2 and number(a[1]) else number(aspect)
        par = dar / (w / h)
        if 0.5 < par < 2.5 and abs(par - 1) > 0.03:
            result["par"] = par
    return result
