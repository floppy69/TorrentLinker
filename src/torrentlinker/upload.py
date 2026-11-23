"""Upload: turn an Orphan into a new torrent, its NFO and a c411 Draft (ADR-0011).

The torrent's paths follow c411's naming rules while the data stays where it is: the
torrent is then added to the Torrent Client with its paths renamed onto the local
files, as a Reseed does, so no file of the user's is ever renamed or written.
Rules are summed up in docs/research/upload-rules.md; 3D models come first.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Protocol

from torrentlinker.audio_tags import TagCache
from torrentlinker.catalogue_sync import ROOTS
from torrentlinker.disk_rename import RenameApproval
from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.matching import IgnoreList, Match
from torrentlinker.options import Chosen, OptionType
from torrentlinker.qbit import Qbit
from torrentlinker.queries import name_query
from torrentlinker.reseed import start_reseed
from torrentlinker.store import SavedUpload, Store
from torrentlinker.torrent_meta import TorrentMeta, read_torrent

MiB = 1 << 20
GB = 1_000_000_000
NOTAG = "NOTAG"
IMAGE_PLACEHOLDER = "…"  # in [img][/img] until the image is uploaded on c411
CATEGORY_3D = 10
CATEGORY_VIDEO = 1
CATEGORY_EBOOK = 2
CATEGORY_AUDIO = 3
CATEGORY_APPS = 4
CATEGORY_GAMES = 5
CATEGORY_EMULATION = 6
CATEGORY_GPS = 7
AUDIOBOOK_KBPS = 64  # an audiobook's minimum bitrate

# c411's categories (GET /api/categories); Nulled and Adult get no profile.
CATEGORIES = {
    1: "Films & Vidéos",
    2: "Ebook",
    3: "Audio",
    4: "Applications",
    5: "Jeux Vidéo",
    6: "Emulation",
    7: "GPS",
    9: "Nulled",
    10: "Imprimante 3D",
}
# The category a Content Kind proposes; `other` proposes none, the user picks.
DEFAULT_CATEGORIES = {
    ContentKind.MOVIE: 1,
    ContentKind.SERIES: 1,
    ContentKind.EBOOK: 2,
    ContentKind.MUSIC: 3,
    ContentKind.GAME: 5,
    ContentKind.MODEL_3D: CATEGORY_3D,
}

# c411's 3D formats, in the order a release name lists them.
FORMATS_3D = ("stl", "3mf", "obj", "step", "stp", "gcode", "blend", "f3d", "f3z", "sldprt", "fcstd")
ARCHIVES = ("rar", "zip", "7z")
# c411's eBook formats, in the order a release name lists them (and a single choice takes
# the first found): documents, comics, page images, audiobooks.
FORMATS_EBOOK = (
    "epub",
    "pdf",
    "mobi",
    "djvu",
    "cbz",
    "cbr",
    "jpg",
    "png",
    "mp3",
    "m4b",
    "m4a",
    "flac",
)
DOCUMENT_FORMATS = ("epub", "pdf", "mobi", "djvu")
COMIC_FORMATS = ("cbz", "cbr")
IMAGE_FORMATS = ("jpg", "png")
AUDIO_FORMATS = ("mp3", "m4a", "m4b", "flac")
FORMAT_ALIASES = {"jpeg": "jpg"}  # extensions c411 spells another way
BOOK_LANGUAGE = "FRENCH"
READ_CHUNK = 4 * MiB


class Subcategory3D(IntEnum):
    OBJECTS = 51
    CHARACTERS = 52
    PACK = 53


class SubcategoryEbook(IntEnum):
    AUDIO = 11
    BD = 12
    COMICS = 13
    BOOKS = 14
    MANGA = 15
    PRESS = 16
    SHEET_MUSIC = 59
    MANUALS = 60


class SubcategoryVideo(IntEnum):
    ANIMATION = 1
    ANIMATION_SERIES = 2
    CONCERT = 3
    DOCUMENTARY = 4
    DOCUMENTARY_SERIES = 57
    TV_SHOW = 5
    MOVIE = 6
    SERIES = 7
    SHOW = 8
    SPORT = 9
    CLIPS = 10
    COLLECTION = 54


class SubcategoryAudio(IntEnum):
    KARAOKE = 17
    MUSIC = 18
    PODCAST = 19
    SAMPLES = 20


class SubcategoryApps(IntEnum):
    OTHER = 21
    TRAINING = 22
    LINUX = 23
    MACOS = 24
    SMARTPHONE = 25
    TABLET = 26
    WINDOWS = 27


class SubcategoryGames(IntEnum):
    OTHER = 28
    LINUX = 29
    MACOS = 30
    MICROSOFT = 31
    NINTENDO = 32
    SMARTPHONE = 33
    SONY = 34
    TABLET = 35
    WINDOWS = 36
    VR = 55


class SubcategoryGps(IntEnum):
    APPLICATIONS = 39
    MAPS = 40
    MISC = 41


class SubcategoryEmulation(IntEnum):
    EMULATORS = 37
    ROMS = 38


class UploadStopped(Exception):
    """The user stopped the Upload while its torrent was being made."""


@dataclass(frozen=True)
class UploadFile:
    torrent_path: str  # as the torrent names it, the release name first
    local_path: str  # as the Local Item lists it, relative to its save path
    size: int


class Problem(StrEnum):
    """Why c411 would refuse a Local Item; the GUI words each one."""

    NO_FILE = "no-file"
    ARCHIVE = "archive"  # detail: the archive formats found
    NO_3D_FILE = "no-3d-file"
    NO_EBOOK_FORMAT = "no-ebook-format"
    OPTION_MISSING = "option-missing"  # detail: the option's name
    NO_AUDIO_FILE = "no-audio-file"
    AUDIO_FORMAT = "audio-format"  # detail: the formats found that c411 refuses
    LOW_BITRATE = "low-bitrate"  # detail: what is too low, and the minimum
    NEEDS_CUE = "needs-cue"  # one audio file without a .cue
    MIXED_AUDIO = "mixed-audio"  # detail: the formats or bitrates found
    NO_MEDIAINFO = "no-mediainfo"  # libmediainfo is not installed
    NO_VIDEO_FILE = "no-video-file"
    BAD_CONTAINER = "bad-container"  # detail: the containers found that c411 refuses
    GPU_ENCODER = "gpu-encoder"  # detail: NVENC, QSV or AMF
    LOW_VIDEO_BITRATE = "low-video-bitrate"  # detail: what is too low, and the minimum
    BANNED_TEAM = "banned-team"  # detail: the tag
    NO_FRENCH = "no-french"  # no French audio and no full French subtitles; detail: file
    MIXED_PACK = "mixed-pack"  # detail: what differs
    DOWNLOADER = "downloader"  # detail: the downloader executables found
    BIN_NO_CUE = "bin-no-cue"  # a .bin without a .cue next to it
    CLONECD_INCOMPLETE = "clonecd-incomplete"  # detail: the CloneCD files missing
    PASSWORD_ARCHIVE = "password-archive"  # detail: the protected archives
    CONSOLE_CONTAINER = "console-container"  # detail: the extensions the console does not take
    FORBIDDEN_TOOL = "forbidden-tool"  # detail: trainers, hack tools or hypervisor cracks found
    ISO_NOT_ALLOWED = "iso-not-allowed"  # a PC game .iso that is not a crack, repack or scene


@dataclass(frozen=True)
class Refusal:
    """A mechanical rule a program can check: the Draft cannot be saved."""

    problem: Problem
    detail: str = ""


class Judgement(StrEnum):
    """A c411 rule only the uploader can judge; the GUI words each one."""

    METADATA_CONSISTENCY = "metadata-consistency"
    PAID_CREATORS = "paid-creators"
    PACK_THEME = "pack-theme"
    FRENCH_ONLY = "french-only"
    NO_DUPLICATE = "no-duplicate"
    FEW_FORMATS = "few-formats"
    WHOLE_VOLUMES = "whole-volumes"
    EVERY_VOLUME = "every-volume"
    NO_TRANSCODE = "no-transcode"
    SHORT_SINGLE = "short-single"
    DISCOGRAPHY = "discography"
    CD_RIP_MISSING = "cd-rip-missing"  # detail: what a CD-Rip lacks
    CD_RIP_LINKS = "cd-rip-links"
    FRENCH_TITLE = "french-title"  # detail: the French title when TMDb gave it
    FORBIDDEN_SOURCE = "forbidden-source"
    INCOMPLETE_SEASON = "incomplete-season"  # detail: the episodes missing
    WEB_PLATFORM = "web-platform"
    MICKEY_TAG = "mickey-tag"
    SLOTS = "slots"
    VERSION_ACTIVATION = "version-activation"
    NO_ALPHA = "no-alpha"
    RETRO_ONLY = "retro-only"
    NO_MIXED_MACHINES = "no-mixed-machines"  # detail: the machines found
    RELEASE_TYPE = "release-type"  # detail: the type decided from the files
    INSTALL_NOTE = "install-note"
    NO_IPTV = "no-iptv"
    OLDER_VERSION = "older-version"
    ONE_PER_RELEASE = "one-per-release"  # detail: the release type
    OFFICIAL_TRAINING = "official-training"
    PLUGIN_HOST = "plugin-host"
    ORIGINAL_CRACK = "original-crack"
    UPDATE_ONLY = "update-only"
    ONE_GOG = "one-gog"
    ONE_PER_CONSOLE = "one-per-console"
    REGION = "region"  # detail: the region found, empty when none


@dataclass(frozen=True)
class UploadWarning:
    """A judgement rule: shown beside the Refusals, but the Draft can still be saved."""

    judgement: Judgement
    detail: str = ""


@dataclass(frozen=True)
class Subcategory:
    id: int
    label: str  # English, translated by the GUI


@dataclass(frozen=True)
class ExistingQuery:
    """How to ask c411 what it already has of an item: its title words, or the ids a
    category can look up (the video profile's TMDb id, say)."""

    text: str
    ids: dict[str, str] = field(default_factory=dict)


class UploadProfile(Protocol):
    """What one c411 category needs to become an Upload: its rules, the release name, the
    NFO and a description template. One per category, 3D models first."""

    category: int
    subcategories: tuple[Subcategory, ...]
    renders_models: bool  # the Upload tab shows its models and captures the description's image
    media_extensions: tuple[str, ...]  # a lone file of these in a folder is named the release
    dotted_names: bool  # words are dotted, no spaces or accents; games and applications are exempt

    # `inspect` reads what the files say about themselves (tags, MediaInfo): slow, so the
    # GUI runs it off its thread before it asks the other methods, which never touch the
    # disk. Until it ran, a rule that needs the answers has nothing to say.

    def inspect(self, item: LocalItem, ignore: IgnoreList) -> None: ...
    def refusals(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int | None = None
    ) -> list[Refusal]: ...
    def warnings(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int
    ) -> list[UploadWarning]: ...
    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int: ...
    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str: ...
    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen: ...
    def nfo(self, title: str, files: list[UploadFile]) -> str: ...
    def description(
        self, title: str, files: list[UploadFile], source: str, image_url: str
    ) -> str: ...
    def existing_query(self, item: LocalItem, ignore: IgnoreList) -> ExistingQuery: ...
    def draft_fields(
        self, item: LocalItem, ignore: IgnoreList, files: list[UploadFile]
    ) -> dict[str, Any]: ...
    def image_is_sheet(self, subcategory: int) -> bool: ...


class Model3DProfile:
    """c411's Imprimante 3D category (docs/research/upload-rules.md)."""

    category: int = CATEGORY_3D
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(Subcategory3D.OBJECTS, "Objects"),
        Subcategory(Subcategory3D.CHARACTERS, "Characters"),
        Subcategory(Subcategory3D.PACK, "Pack"),
    )
    renders_models = True
    media_extensions: tuple[str, ...] = ()
    dotted_names = True

    def draft_fields(
        self, item: LocalItem, ignore: IgnoreList, files: list[UploadFile]
    ) -> dict[str, Any]:
        return {}

    def inspect(self, item: LocalItem, ignore: IgnoreList) -> None:
        """Nothing to read: a model's rules go by its file names."""

    def refusals(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int | None = None
    ) -> list[Refusal]:
        files = _content(item, ignore)
        if not files:
            return [Refusal(Problem.NO_FILE)]
        found = []
        archives = sorted({e for p in files if (e := _ext(p)) in ARCHIVES})
        if archives:
            found.append(Refusal(Problem.ARCHIVE, ", ".join(archives)))
        if not any(_ext(p) in FORMATS_3D for p in files):
            found.append(Refusal(Problem.NO_3D_FILE))
        return found

    def warnings(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int
    ) -> list[UploadWarning]:
        found = [UploadWarning(Judgement.PAID_CREATORS)]
        if subcategory == Subcategory3D.PACK:
            found.append(UploadWarning(Judgement.PACK_THEME))
        return found

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        models = [p for p in _content(item, ignore) if _ext(p) in FORMATS_3D]
        return Subcategory3D.PACK if len(models) > 1 else Subcategory3D.OBJECTS

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """`Nom.Source.FORMATS`, or `Nom.Source.[PACK].FORMATS`; NOTAG for an unknown
        source."""
        stem = item.path.stem if item.path.is_file() else item.path.name
        parts = [_words(stem), _words(source) or NOTAG]
        if subcategory == Subcategory3D.PACK:
            parts.append("[PACK]")
        if found := _formats_3d(_content(item, ignore)):
            parts.append("-".join(found))
        return ".".join(p for p in parts if p)

    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen:
        return {}  # c411 lists no options for 3D models

    def image_is_sheet(self, subcategory: int) -> bool:
        """A Pack's image is a contact sheet of its models; any other is one model."""
        return subcategory == Subcategory3D.PACK

    def nfo(self, title: str, files: list[UploadFile]) -> str:
        return nfo_3d(title, files)

    def description(self, title: str, files: list[UploadFile], source: str, image_url: str) -> str:
        return description_3d(title, files, source, image_url)

    def existing_query(self, item: LocalItem, ignore: IgnoreList) -> ExistingQuery:
        return ExistingQuery(name_query(item))


class EbookProfile:
    """c411's Ebook category (docs/research/upload-rules.md). An audiobook's bitrate (64
    kbps or more) is read from its tags by `inspect`."""

    category: int = CATEGORY_EBOOK
    renders_models = False  # no model to render; the image is made by hand
    media_extensions: tuple[str, ...] = ()
    dotted_names = True
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(SubcategoryEbook.AUDIO, "Audiobooks"),
        Subcategory(SubcategoryEbook.BD, "Comic strips (BD)"),
        Subcategory(SubcategoryEbook.COMICS, "Comics"),
        Subcategory(SubcategoryEbook.BOOKS, "Books"),
        Subcategory(SubcategoryEbook.MANGA, "Manga"),
        Subcategory(SubcategoryEbook.PRESS, "Press"),
        Subcategory(SubcategoryEbook.SHEET_MUSIC, "Sheet music & tablature"),
        Subcategory(SubcategoryEbook.MANUALS, "Journals & technical manuals"),
    )

    def __init__(self, tags: TagCache | None = None) -> None:
        self.tags = tags or TagCache()

    def image_is_sheet(self, subcategory: int) -> bool:
        return False

    def draft_fields(
        self, item: LocalItem, ignore: IgnoreList, files: list[UploadFile]
    ) -> dict[str, Any]:
        return {}

    def inspect(self, item: LocalItem, ignore: IgnoreList) -> None:
        """Read the tags of the audiobook files."""
        self.tags.inspect(item, [p for p in _content(item, ignore) if _ext(p) in AUDIO_FORMATS])

    def refusals(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int | None = None
    ) -> list[Refusal]:
        files = _content(item, ignore)
        if not files:
            return [Refusal(Problem.NO_FILE)]
        found = []
        archives = sorted({e for p in files if (e := _ext(p)) in ARCHIVES})
        if archives:
            found.append(Refusal(Problem.ARCHIVE, ", ".join(archives)))
        if not _formats_ebook(files):
            found.append(Refusal(Problem.NO_EBOOK_FORMAT))
        slow = sorted(
            {
                f"{t.codec} {t.bitrate} kbps"
                for _, t in self.tags.of(
                    {p: s for p, s in files.items() if _ext(p) in AUDIO_FORMATS}
                )
                if not t.lossless and t.constant and t.bitrate < AUDIOBOOK_KBPS
            }
        )
        if slow:
            found.append(
                Refusal(Problem.LOW_BITRATE, f"{', '.join(slow)} (minimum {AUDIOBOOK_KBPS})")
            )
        return found

    def warnings(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int
    ) -> list[UploadWarning]:
        files = _content(item, ignore)
        found = [UploadWarning(Judgement.FRENCH_ONLY), UploadWarning(Judgement.NO_DUPLICATE)]
        if len(_formats_ebook(files)) > 2:
            found.append(UploadWarning(Judgement.FEW_FORMATS))
        volumes = (SubcategoryEbook.BD, SubcategoryEbook.COMICS, SubcategoryEbook.MANGA)
        if len(files) > 1 and not item.path.is_file() and subcategory in volumes:
            found.append(UploadWarning(Judgement.WHOLE_VOLUMES))
            if subcategory == SubcategoryEbook.BD:
                found.append(UploadWarning(Judgement.EVERY_VOLUME))
        return found

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        found = set(_formats_ebook(_content(item, ignore)))
        pages_only = found & set(IMAGE_FORMATS) and not found & set(DOCUMENT_FORMATS)
        if found & set(COMIC_FORMATS) or pages_only:
            return SubcategoryEbook.BD
        if found & set(AUDIO_FORMATS):
            return SubcategoryEbook.AUDIO
        return SubcategoryEbook.BOOKS

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """`Titre.Auteur.FRENCH.EPUB-Team`, a pack adding `[T01.a.T07]` after the title;
        press is `Titre.Date.FRENCH.PDF-Team`. `source` is the team tag, NOTAG when empty."""
        files = _content(item, ignore)
        press = subcategory == SubcategoryEbook.PRESS
        title, author, date = _guess_book(_first_segment(item), press)
        parts = [_words(title)]
        if not item.path.is_file() and (volumes := _volume_range(files)):
            parts.append(volumes)
        parts.append(_words(date) if press else _words(author))
        parts += [BOOK_LANGUAGE, "-".join(f.upper() for f in _formats_ebook(files))]
        tag = re.sub(r"[^A-Za-z0-9]+", "", _ascii(source)) or NOTAG
        return ".".join(p for p in parts if p) + f"-{tag}"

    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen:
        """The format found (the first by priority for a single choice) and French."""
        found = _formats_ebook(_content(item, ignore))
        chosen: Chosen = {}
        for t in types:
            name = t.name.casefold()
            if name.startswith("format"):
                ids = [v.id for f in found for v in t.values if v.label.casefold() == f]
                if ids:
                    chosen[t.id] = ids if t.multiple else ids[:1]
            elif name.startswith("langue"):
                ids = [v.id for v in t.values if v.label.casefold().startswith("français")]
                if ids:
                    chosen[t.id] = ids[:1]
        return chosen

    def nfo(self, title: str, files: list[UploadFile]) -> str:
        return nfo_ebook(title, files)

    def description(self, title: str, files: list[UploadFile], source: str, image_url: str) -> str:
        return description_ebook(title, files, source, image_url)

    def existing_query(self, item: LocalItem, ignore: IgnoreList) -> ExistingQuery:
        return ExistingQuery(name_query(item))


PROFILES: dict[int, UploadProfile] = {}  # filled at the end of this module, by category id


def category_name(category: int) -> str:
    """c411's name for a category, as the site spells it."""
    return CATEGORIES.get(category, str(category))


def default_category(kind: ContentKind) -> int | None:
    """The category a Content Kind proposes; None when the user must pick."""
    return DEFAULT_CATEGORIES.get(kind)


def profile_for(kind: ContentKind) -> UploadProfile | None:
    """How a Content Kind becomes an Upload by default; None when its category has no
    profile yet or the kind proposes none."""
    category = default_category(kind)
    return PROFILES.get(category) if category is not None else None


def find_existing(
    search: Callable[[SearchQuery], list[Candidate]],
    query: ExistingQuery,
    category: int,
    by_ids: Callable[[dict[str, str]], list[Candidate]] | None = None,
) -> list[Candidate]:
    """The releases c411 already has for `query`, most seeded first; information only,
    the app never decides a duplicate. Ids go to `by_ids` when the category has such a
    lookup, else the title words are searched in the category."""
    if query.ids and by_ids is not None:
        found = by_ids(query.ids)
    else:
        root = ROOTS.get(category)
        found = search(SearchQuery(q=query.text, categories=(root,) if root else ()))
    return sorted(found, key=lambda c: -c.seeders)


def missing_options(types: list[OptionType], chosen: Chosen) -> list[Refusal]:
    """A Refusal for each required option the user left empty."""
    return [
        Refusal(Problem.OPTION_MISSING, t.name)
        for t in types
        if t.required and not chosen.get(t.id)
    ]


def _formats_3d(paths: Iterable[str]) -> list[str]:
    present = {_ext(p) for p in paths}
    return [f.upper() for f in FORMATS_3D if f in present]


def _formats_ebook(paths: Iterable[str]) -> list[str]:
    """The accepted formats present, in release-name order; `jpeg` counts as `jpg`."""
    present = {FORMAT_ALIASES.get(e, e) for p in paths if (e := _ext(p))}
    return [f for f in FORMATS_EBOOK if f in present]


def upload_files(
    item: LocalItem, title: str, ignore: IgnoreList, media: tuple[str, ...] = ()
) -> list[UploadFile]:
    """Each content file under its compliant torrent path, in torrent order.

    A single file is named the release title plus its extension, as c411 names media
    files; a folder becomes the release title, and the names below it lose accents and
    spaces. Ignored Files are left out. When a folder holds a single file with one of the
    `media` extensions, that file is named the release title too (c411's detag engine
    compares a media file's name with the title); a pack of such files keeps its names.
    """
    content = _content(item, ignore)
    if item.path.is_file():
        ((local, size),) = content.items()
        return [UploadFile(f"{title}.{_ext(local)}", local, size)]
    result: dict[str, UploadFile] = {}
    medias = [p for p in content if _ext(p) in media]
    for local, size in content.items():
        below = local.split("/")[1:]
        path = "/".join([title, *(_clean_segment(s) for s in below)])
        if len(medias) == 1 and local == medias[0]:
            path = f"{title}/{title}.{_ext(local)}"
        if path.casefold() in {p.casefold() for p in result}:
            raise ValueError(f"Two files would share the name {path}")
        result[path] = UploadFile(path, local, size)
    return [result[p] for p in sorted(result)]


def piece_size(total: int) -> int:
    """c411's table: <1 Go 1 Mo, <2 Go 2 Mo, <3 Go 4 Mo, <8 Go 8 Mo, else 16 Mo."""
    for limit, mib in ((1 * GB, 1), (2 * GB, 2), (3 * GB, 4), (8 * GB, 8)):
        if total < limit:
            return mib * MiB
    return 16 * MiB


def make_torrent(
    item: LocalItem,
    files: list[UploadFile],
    announce: str,
    report: Callable[[int, int], None] = lambda done, total: None,
    stopped: Callable[[], bool] = lambda: False,
    now: Callable[[], float] = time.time,
    *,
    announce_hosts: list[str] | None = None,
) -> bytes:
    """A private v1 torrent of `files`, hashed from the Local Item's own files."""
    total = sum(f.size for f in files)
    length = piece_size(total)
    pieces = bytearray()
    piece = hashlib.sha1()
    filled = done = 0
    for f in files:
        with open(item.save_path / f.local_path, "rb") as stream:
            while chunk := stream.read(READ_CHUNK):
                if stopped():
                    raise UploadStopped()
                done += len(chunk)
                while chunk:
                    take = chunk[: length - filled]
                    piece.update(take)
                    filled += len(take)
                    chunk = chunk[len(take) :]
                    if filled == length:
                        pieces += piece.digest()
                        piece, filled = hashlib.sha1(), 0
                report(done, total)
    if filled:
        pieces += piece.digest()
    name = files[0].torrent_path.split("/")[0]
    info: dict[str, Any] = {"name": name, "piece length": length, "pieces": bytes(pieces)}
    if item.path.is_file():
        info["length"] = files[0].size
    else:
        info["files"] = [{"length": f.size, "path": f.torrent_path.split("/")[1:]} for f in files]
    info["private"] = 1
    # c411 adds this on publication. Include it before seeding so the hash stays valid.
    info["source"] = "C411"
    from torrentlinker.tracker_updates import upload_announces

    urls = upload_announces(announce, announce_hosts or [])
    return bencode(
        {
            "announce": urls[0],
            **({"announce-list": [[url] for url in urls]} if len(urls) > 1 else {}),
            "created by": "TorrentLinker",
            "creation date": int(now()),
            "info": info,
        }
    )


def seed_match(files: list[UploadFile]) -> Match:
    """The Upload's torrent against its Local Item: Full by construction."""
    return Match({f.torrent_path: f.local_path for f in files})


def nfo_3d(title: str, files: list[UploadFile]) -> str:
    """c411's 3D NFO: name, file count, total size, formats, then every file."""
    names = [f.torrent_path.split("/", 1)[-1] for f in files]
    found = _formats_3d(names)
    width = max(len(n) for n in names)
    lines = [
        title,
        "",
        f"Nom ............ : {title}",
        f"Fichiers ....... : {len(files)}",
        f"Taille totale .. : {human_size(sum(f.size for f in files))}",
        f"Format ......... : {', '.join(found) or '-'}",
        "",
        "Contenu :",
        *(
            f"  {n.ljust(width)}  {human_size(f.size):>10}"
            for n, f in zip(names, files, strict=True)
        ),
    ]
    return "\n".join(lines) + "\n"


def description_3d(title: str, files: list[UploadFile], source: str, image_url: str) -> str:
    """c411's description: an image (a placeholder to fill on c411 until there is a URL),
    a presentation the user writes, then the facts of the NFO; a pack lists its files in
    a spoiler."""
    names = [f.torrent_path.split("/", 1)[-1] for f in files]
    lines = [
        f"[center][img]{image_url or IMAGE_PLACEHOLDER}[/img][/center]",
        "",
        f"[center][h2]{title}[/h2][/center]",
        "",
        "[h3]Présentation[/h3]",
        "",
        "",
        "[h3]Informations[/h3]",
        f"[b]Source :[/b] {source or 'Inconnue'}",
        f"[b]Formats :[/b] {', '.join(_formats_3d(names))}",
        f"[b]Fichiers :[/b] {len(files)}",
        f"[b]Taille totale :[/b] {human_size(sum(f.size for f in files))}",
    ]
    if len(files) > 1:
        lines += ["", "[spoiler=Contenu][list]", *(f"[*]{n}" for n in names), "[/list][/spoiler]"]
    return "\n".join(lines) + "\n"


def nfo_ebook(title: str, files: list[UploadFile]) -> str:
    """c411's books NFO: title, author, format, language, file count, total size, then
    every file with its size. Title and author are guessed from the Local Item's name."""
    book, author, _ = _guess_book(files[0].local_path.split("/")[0], press=False)
    names = [f.torrent_path.split("/", 1)[-1] for f in files]
    width = max(len(n) for n in names)
    lines = [
        title,
        "",
        f"Titre .......... : {book}",
        f"Auteur ......... : {author or '-'}",
        f"Format ......... : {', '.join(f.upper() for f in _formats_ebook(names)) or '-'}",
        "Langue ......... : ",
        f"Fichiers ....... : {len(files)}",
        f"Taille totale .. : {human_size(sum(f.size for f in files))}",
        "",
        "Contenu :",
        *(
            f"  {n.ljust(width)}  {human_size(f.size):>10}"
            for n, f in zip(names, files, strict=True)
        ),
    ]
    return "\n".join(lines) + "\n"


def description_ebook(title: str, files: list[UploadFile], source: str, image_url: str) -> str:
    """c411's description: an image, a presentation the user writes, then the facts of
    the NFO; several files are listed in a spoiler."""
    book, author, _ = _guess_book(files[0].local_path.split("/")[0], press=False)
    names = [f.torrent_path.split("/", 1)[-1] for f in files]
    lines = []
    if image_url:
        lines += [f"[center][img]{image_url}[/img][/center]", ""]
    lines += [
        f"[center][h2]{book}[/h2][/center]",
        "",
        "[h3]Présentation[/h3]",
        "",
        "",
        "[h3]Informations[/h3]",
        f"[b]Titre :[/b] {book}",
    ]
    if author:
        lines.append(f"[b]Auteur :[/b] {author}")
    lines += [
        f"[b]Format :[/b] {', '.join(f.upper() for f in _formats_ebook(names))}",
        "[b]Langue :[/b] ",
        f"[b]Fichiers :[/b] {len(files)}",
        f"[b]Taille totale :[/b] {human_size(sum(f.size for f in files))}",
    ]
    if len(files) > 1:
        lines += ["", "[spoiler=Contenu][list]", *(f"[*]{n}" for n in names), "[/list][/spoiler]"]
    return "\n".join(lines) + "\n"


def draft_body(
    title: str,
    description: str,
    category: int,
    subcategory: int,
    torrent: bytes,
    nfo: str,
    options: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The JSON c411's upload page sends to save a Draft; `options` is as options_body
    makes it, empty for 3D models; `extra` sets other fields (mediainfo, tmdbData)."""
    return {
        "name": title,
        "title": title,
        "description": description,
        "categoryId": category,
        "subcategoryId": subcategory,
        "options": options or {},
        "tmdbData": None,
        "musicData": None,
        "rawgData": None,
        "bookData": None,
        "mediainfo": None,
        "identifiers": [],
        "templateId": None,
        "uploaderNote": None,
        "ebookMetadata": None,
        "torrentFileName": f"{title}.torrent",
        "torrentFileData": base64.b64encode(torrent).decode(),
        "nfoFileName": f"{title}.nfo",
        "nfoFileData": base64.b64encode(nfo.encode()).decode(),
        **(extra or {}),
    }


def save_upload_files(folder: Path, title: str, torrent: bytes, nfo: str) -> tuple[Path, Path]:
    """Keep the Upload's .torrent and .nfo in the app's own folder, never in the Library."""
    folder.mkdir(parents=True, exist_ok=True)
    torrent_path, nfo_path = folder / f"{title}.torrent", folder / f"{title}.nfo"
    torrent_path.write_bytes(torrent)
    nfo_path.write_text(nfo, encoding="utf-8")
    return torrent_path, nfo_path


@dataclass(frozen=True)
class PreparedUpload:
    """An Upload whose Draft is saved, ready to seed."""

    saved: SavedUpload
    meta: TorrentMeta
    files: list[UploadFile]


@dataclass(frozen=True)
class UploadRequest:
    """An Upload as the user set it up: the files, the name, the texts and the category."""

    item: LocalItem
    title: str
    files: list[UploadFile]
    nfo: str
    description: str
    category: int
    subcategory: int
    options: dict[str, Any] = field(default_factory=dict)  # as options_body makes it
    extra: dict[str, Any] = field(default_factory=dict)  # Draft fields: mediainfo, tmdbData


def create_upload(
    request: UploadRequest,
    announce: str,
    folder: Path,
    save_draft: Callable[[dict[str, Any]], int],
    store: Store,
    report: Callable[[int, int], None] = lambda done, total: None,
    stopped: Callable[[], bool] = lambda: False,
    now: Callable[[], float] = time.time,
    *,
    announce_hosts: list[str] | None = None,
) -> PreparedUpload:
    """Make the torrent, keep it and the NFO in `folder`, then save the c411 Draft."""
    if not announce:
        raise ValueError("No Announce URL: enter yours in Settings → Connections")
    from torrentlinker.upload_presentation import file_evidence, request_form, require_complete

    require_complete(request_form(request), file_evidence(request))
    item, title, files, nfo = request.item, request.title, request.files, request.nfo
    torrent = make_torrent(
        item, files, announce, report, stopped, now, announce_hosts=announce_hosts
    )
    save_upload_files(folder, title, torrent, nfo)
    meta = read_torrent(torrent)
    body = draft_body(
        title,
        request.description,
        request.category,
        request.subcategory,
        torrent,
        nfo,
        request.options,
        request.extra,
    )
    saved = SavedUpload(item.path, title, meta.infohash, save_draft(body), now())
    store.save_upload(saved)
    return PreparedUpload(saved, meta, files)


def seed_upload(
    qbit: Qbit,
    store: Store,
    item: LocalItem,
    prepared: PreparedUpload,
    *,
    approve_disk_renames: RenameApproval | None = None,
) -> str:
    """Add the Upload's torrent to the Torrent Client against the local files and verify
    it, as a Reseed: c411 refuses an upload whose uploader is not seeding."""
    key = f"upload:{prepared.meta.infohash}"
    return start_reseed(
        qbit,
        store,
        item,
        prepared.meta,
        seed_match(prepared.files),
        key,
        approve_disk_renames=approve_disk_renames,
    )


def bencode(value: Any) -> bytes:
    if isinstance(value, bool):
        raise TypeError("bencode has no booleans")
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        keys = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
        return b"d" + b"".join(bencode(k) + bencode(v) for k, v in keys) + b"e"
    raise TypeError(f"cannot bencode {type(value).__name__}")


def human_size(n: float) -> str:
    """Sizes as c411's French NFOs write them."""
    if n < 1024:
        return f"{int(n)} o"
    for unit in ("Ko", "Mo", "Go"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n / 1024:.1f} To"


def _content(item: LocalItem, ignore: IgnoreList) -> dict[str, int]:
    return {p: s for p, s in item.files.items() if not ignore.matches(p)}


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].casefold() if "." in name else ""


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _words(text: str) -> str:
    """Words joined by dots, without accents: `Petit étau de bureau` → `Petit.Etau.De.Bureau`."""
    words = re.split(r"[^A-Za-z0-9]+", _ascii(text))
    return ".".join(w[:1].upper() + w[1:] for w in words if w)


def _clean_segment(name: str) -> str:
    """A file or folder name without accents or spaces; its extension kept."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", ".", _ascii(name)).strip(".")
    return re.sub(r"\.{2,}", ".", cleaned) or "_"


DATE_RE = re.compile(
    r"\b((?:19|20)\d\d)(?:[-._ ](0[1-9]|1[0-2]))?(?:[-._ ](0[1-9]|[12]\d|3[01]))?\b"
)
VOLUME_RE = re.compile(r"(?:\b|_)(?:t|tome|vol|volume)[ ._-]*0*(\d{1,3})\b", re.IGNORECASE)


def _first_segment(item: LocalItem) -> str:
    """The name the release is guessed from: a file's stem, a folder's name."""
    return item.path.stem if item.path.is_file() else item.path.name


def _guess_book(name: str, press: bool) -> tuple[str, str, str]:
    """(title, author, date) from a file or folder name: `Auteur - Titre` is common; press
    has a date instead of an author. Bracketed notes are dropped; any part may be empty."""
    name = name.rsplit(".", 1)[0] if _ext(name) in FORMATS_EBOOK else name
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", name)
    date = ""
    if press and (m := DATE_RE.search(name)):
        date = ".".join(g for g in m.groups() if g)
        name = name[: m.start()] + name[m.end() :]
    name = VOLUME_RE.sub(" ", name)
    parts = [p.strip(" ._-") for p in re.split(r"\s+-\s+", name.strip()) if p.strip(" ._-")]
    if press or len(parts) < 2:
        return " ".join(parts), "", date
    return " ".join(parts[1:]), parts[0], date


def _volume_range(files: dict[str, int]) -> str:
    """`[T01.a.T07]` when the files number several volumes, else nothing."""
    numbers = sorted(
        {int(m.group(1)) for p in files if (m := VOLUME_RE.search(p.rsplit("/", 1)[-1]))}
    )
    if len(numbers) < 2:
        return ""
    return f"[T{numbers[0]:02d}.a.T{numbers[-1]:02d}]"


# Profiles that need this module's types come last (see upload_audio's docstring).
from torrentlinker.upload_audio import AudioProfile  # noqa: E402
from torrentlinker.upload_software import (  # noqa: E402
    ApplicationsProfile,
    EmulationProfile,
    GamesProfile,
    GpsProfile,
)
from torrentlinker.upload_video import VideoProfile  # noqa: E402

PROFILES.update(
    {
        CATEGORY_VIDEO: VideoProfile(),
        CATEGORY_EBOOK: EbookProfile(),
        CATEGORY_AUDIO: AudioProfile(),
        CATEGORY_APPS: ApplicationsProfile(),
        CATEGORY_GAMES: GamesProfile(),
        CATEGORY_EMULATION: EmulationProfile(),
        CATEGORY_GPS: GpsProfile(),
        CATEGORY_3D: Model3DProfile(),
    }
)
