"""Read-only local media inventory and instance-bound playback coordination."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from guessit import guessit

from torrentlinker import media_tracks
from torrentlinker.domain import ContentKind

VIDEO = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".mpeg", ".mpg", ".ts", ".wmv"}
AUDIO = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".wma", ".wv"}
PARTIAL = (".part", ".partial", ".!qb", ".!ut", ".crdownload", ".tmp")


# A file is an episode only when its name says so (S01E02, S3.EP 27, 1x02, Saison 2) or its
# folder is a season. "Episode 4", "1080" or a year alone made films look like series.
EPISODE_MARK = re.compile(
    r"(?i)(?<![a-z0-9])"
    r"(?:S\d{1,2}[ ._-]?EP?[ ._-]?\d{1,3}|\d{1,2}x\d{2}|(?:season|saison)[ ._-]?\d{1,2})"
    r"(?![a-z0-9])"
)
SEASON_FOLDER = re.compile(
    r"(?i)(?<![a-z0-9])(?:S\d{1,2}|(?:season|saison)[ ._-]?\d{1,2})(?![a-z0-9])"
)


# Anime releases number episodes their own way: "Session 01", "e01m", "OAV 2". An OAV is
# kept apart from the series' episodes.
ANIME_MARK = re.compile(
    r"(?i)(?<![a-z0-9])(?:(?P<oav>oav|ova|oad)[ ._-]?|session[ ._-]?|ep?[ ._-]?(?=\d{2}))"
    r"(?P<number>\d{1,3})m?(?![a-z0-9])"
)
ANIME_FOLDERS = {"anime", "animes", "animé", "animés", "japanimation", "manga", "mangas"}


def anime_episode(path: Path) -> tuple[int, bool] | None:
    """The episode number of an anime-style file name, and whether it is an OAV."""
    found = ANIME_MARK.search(path.stem)
    return (int(found["number"]), bool(found["oav"])) if found else None


def is_episode(path: Path) -> bool:
    return bool(
        EPISODE_MARK.search(path.name)
        or SEASON_FOLDER.search(path.parent.name)
        or anime_episode(path)
    )


def is_anime_details(details) -> bool:
    """Japanese animation, as c411's TMDb details describe it."""
    genres = details.get("genres") or []
    keywords = details.get("keywords") or []
    countries = details.get("countries") or []
    return "anime" in keywords or "Animation" in genres and "Japan" in countries


def is_anime(body, path) -> bool:
    """c411's details decide; without them, a folder named Anime (or Manga) does."""
    if body.get("anime") is not None:
        return bool(body["anime"])
    if body.get("kind") != "video":
        return False
    return any(part.casefold() in ANIME_FOLDERS for part in Path(path).parent.parts)


def film_title(guessed, path: Path) -> str:
    """`Star Wars Episode 4 – A New Hope` for a film the guesser split into parts."""
    title = str(guessed.get("title") or "")
    number, subtitle = guessed.get("episode"), guessed.get("alternative_title")
    if title and isinstance(number, int):
        title += f" Episode {number}"
    if title and subtitle:
        title += f" – {subtitle}"
    return title or (f"Episode {number}" if isinstance(number, int) else path.stem)


def genres_of(value) -> list[str]:
    """`Horreur, Mystère` -> each genre; release details list several in one field."""
    return [genre.strip() for genre in str(value or "").split(",") if genre.strip()]


def rating_of(row) -> float:
    try:
        return float(row.get("rating") or 0)
    except (TypeError, ValueError):
        return 0.0


HIGHLY_RATED = 7.0  # the "Highly rated" home row and view


def identity(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def bounded_number(value, maximum=8640000):
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError("Player value is outside its supported range.")
    return number


class MediaLibrary:
    def __init__(self, agent):
        self.agent = agent
        self.lock = threading.RLock()
        self.db = sqlite3.connect(agent.setup.path.parent / "media.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.scanning: set[str] = set()
        self.previews: dict[str, dict[str, Any]] = {}
        self.observations: dict[str, tuple[object, set[str]]] = {}
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS media_items
                    (id TEXT, client TEXT, path TEXT, folder TEXT, size INTEGER,
                    modified INTEGER, added REAL, body TEXT, PRIMARY KEY(client,id));
                CREATE TABLE IF NOT EXISTS media_progress
                    (client TEXT, item TEXT, position REAL, duration REAL, watched INTEGER,
                    PRIMARY KEY(client,item));
                CREATE TABLE IF NOT EXISTS media_options (key TEXT PRIMARY KEY, body TEXT);
                CREATE TABLE IF NOT EXISTS media_sessions
                    (id TEXT PRIMARY KEY, token TEXT, client TEXT, platform TEXT,
                    updated REAL, body TEXT, commands TEXT, actor TEXT DEFAULT '',
                    conversation TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS media_playlists
                    (id TEXT PRIMARY KEY, client TEXT, name TEXT, items TEXT);
                CREATE TABLE IF NOT EXISTS media_selections
                    (id TEXT PRIMARY KEY, actor TEXT, client TEXT, items TEXT);
            """)

    def setup(self, client_id):
        client_id = client_id or self.agent.setup.settings.default_client_id
        self.agent.setup.settings.profile(client_id)
        return self.agent.for_client(client_id).setup

    def checked_path(self, client_id: str, value: str, folder: str) -> Path:
        setup = self.setup(client_id)
        roots = [f.path.absolute() for f in setup.settings.library_folders]
        base = Path(folder).absolute()
        path = Path(value).absolute()
        if base not in roots or not path.is_relative_to(base):
            raise ValueError("This media folder is no longer registered.")
        # Reject links in every ancestor, including an in-root symlink to another file.
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink():
                raise ValueError("Media paths containing symbolic links are unavailable.")
        checked = setup.path_under_root(str(path), directory=False)
        if not checked.is_relative_to(base.resolve(strict=True)):
            raise ValueError("Media is outside its registered Library Folder.")
        return checked

    def record(self, client_id, identifier):
        self.setup(client_id)
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM media_items WHERE client=? AND id=?", (client_id, identifier)
            ).fetchone()
        if row is None:
            raise ValueError("Media item is unavailable. Refresh the media library.")
        registered = {
            str(folder.path.absolute()) for folder in self.setup(client_id).settings.library_folders
        }
        if row["folder"] not in registered:
            raise ValueError("This media folder is no longer registered.")
        return row

    def resolve(self, client_id, identifier):
        row = self.record(client_id, identifier)
        body = json.loads(row["body"])
        if body.get("incomplete"):
            raise ValueError("This file is still downloading or awaiting Verification.")
        path = self.checked_path(client_id, row["path"], row["folder"])
        if not path.is_file() or path.stat().st_size != row["size"] or row["size"] <= 0:
            raise ValueError("This file is missing or has changed. Refresh the media library.")
        if any(path.is_relative_to(p) for p in self.incomplete_paths(client_id)):
            raise ValueError("This file is still downloading or awaiting Verification.")
        return path

    def incomplete_paths(self, client_id):
        target = self.agent.for_client(client_id)
        observed = target.observed
        cached = self.observations.get(client_id)
        if cached is not None and cached[0] is observed:
            return cached[1]
        from torrentlinker.paths import PathMapper

        mapper = PathMapper(target.setup.settings.path_mappings)
        paths = set()
        for torrent in observed:
            if torrent.progress >= 1 and "checking" not in torrent.state.lower():
                continue
            save_path = Path(mapper.to_local(str(torrent.save_path)))
            if torrent.files:
                paths.update(str((save_path / p).absolute()) for p in torrent.files)
            else:
                # An incomplete torrent without its file list cannot establish safe children.
                paths.add(str(save_path.absolute()))
        self.observations[client_id] = (observed, paths)
        return paths

    def scan(self, client_id, stop, progress):
        setup = self.setup(client_id)
        with self.lock:
            if client_id in self.scanning:
                raise ValueError("A media refresh is already running for this client.")
            self.scanning.add(client_id)
        try:
            before = self.revision(client_id)
            result = self._scan(client_id, setup, stop, progress)
            if not result.get("cancelled"):
                # Lets an automatic refresh reload the screen only when something changed.
                result["changed"] = self.revision(client_id) != before
            return result
        finally:
            with self.lock:
                self.scanning.discard(client_id)

    def revision(self, client_id) -> str:
        """Changes whenever an item of the library, or what is known of it, changes."""
        digest = hashlib.sha256()
        with self.lock:
            for row in self.db.execute(
                "SELECT id, size, modified, body FROM media_items WHERE client=? ORDER BY id",
                (client_id,),
            ):
                digest.update(json.dumps(tuple(row)).encode())
        return digest.hexdigest()

    def cached_metadata(self, client_id, observed):
        """Reuse saved verified release facts only for an exact local torrent file."""
        from torrentlinker.paths import PathMapper
        from torrentlinker.torrent_meta import read_torrent

        access = self.agent.access
        with access.lock:
            cached = access.db.execute(
                "SELECT i.body FROM selection_presentation_items i JOIN "
                "selection_presentations p ON p.id=i.presentation WHERE p.client=? "
                "ORDER BY i.rowid DESC LIMIT 50000",
                (client_id,),
            ).fetchall()
        by_hash = {}
        for saved in cached:
            item = json.loads(saved[0])
            if item.get("metadata_status") != "verified":
                continue
            for source in item.get("provenance", []):
                if source.get("release_hash"):
                    by_hash.setdefault(source["release_hash"].lower(), item)
        setup = self.setup(client_id)
        mapper = PathMapper(setup.settings.path_mappings)
        result = {}
        for torrent in observed:
            item = by_hash.get(torrent.hash.lower())
            if not item:
                continue
            files = torrent.files
            if not files:
                try:
                    data = setup.store.cached_torrent(torrent.hash)
                    files = read_torrent(data).files if data else {}
                except Exception:
                    continue
            videos = [name for name in files if Path(name).suffix.lower() in VIDEO]
            if len(videos) != 1 or item.get("kind") != "movie":
                continue
            path = Path(mapper.to_local(str(torrent.save_path))) / videos[0]
            result[str(path.absolute())] = (files[videos[0]], item)
        return result

    def _scan(self, client_id, setup, stop, progress):
        found, errors = [], []
        incomplete: set[str] = set()
        target = self.agent.for_client(client_id)
        observed = target.observed
        if setup.configured:
            try:
                client = setup.client()
                observed = client.torrents(with_files=False)
                hydrated = []
                for torrent in observed:
                    if stop.is_set():
                        return {"cancelled": True}
                    if torrent.progress < 1 or "checking" in torrent.state.lower():
                        try:
                            torrent = client.torrent(torrent.hash) or torrent
                        except Exception:
                            pass
                    hydrated.append(torrent)
                target.observed = hydrated
            except Exception:
                # Ordinary local files remain usable without a Torrent Client.
                errors.append(
                    {"message": "Torrent Client unavailable; using last known download state."}
                )
        incomplete = self.incomplete_paths(client_id)
        enrichment = self.cached_metadata(client_id, target.observed)
        successful = []
        for folder in setup.settings.library_folders:
            if stop.is_set():
                return {"cancelled": True}
            base = str(folder.path.absolute())
            folder_rows = []
            try:
                self.checked_path(client_id, base, base)

                def failed(error):
                    raise error

                for directory, dirs, files in os.walk(base, followlinks=False, onerror=failed):
                    if stop.is_set():
                        return {"cancelled": True}
                    dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
                    sidecars = []
                    for name in files:
                        entry = Path(directory) / name
                        if entry.suffix.lower() in {".nfo", ".srt", ".vtt", ".jpg", ".png"}:
                            info = entry.lstat()
                            sidecars.append((name, info.st_size, info.st_mtime_ns))
                    sidecar_signature = identity(json.dumps(sorted(sidecars)))
                    for name in sorted(files):
                        if stop.is_set():
                            return {"cancelled": True}
                        path = Path(directory) / name
                        extension = path.suffix.lower()
                        partial_name = extension == ".!qb"
                        if partial_name:
                            extension = Path(path.stem).suffix.lower()
                        if extension not in VIDEO | AUDIO or path.is_symlink():
                            continue
                        self.checked_path(client_id, str(path), base)
                        stat = path.stat()
                        identifier = identity(str(path))
                        with self.lock:
                            previous = self.db.execute(
                                "SELECT * FROM media_items WHERE client=? AND id=?",
                                (client_id, identifier),
                            ).fetchone()
                        if (
                            previous
                            and previous["size"] == stat.st_size
                            and (previous["modified"] == stat.st_mtime_ns)
                            and json.loads(previous["body"]).get("sidecar_signature")
                            == sidecar_signature
                        ):
                            body = json.loads(previous["body"])
                            if (
                                body.get("kind") == "video"
                                and bool(body.get("series")) != is_episode(path)
                                and body.get("series_source") != "tags"
                            ):
                                # Classified as a series by the older filename rule: read again.
                                body = self.inspect(path, extension, client_id, base)
                        else:
                            body = self.inspect(path, extension, client_id, base)
                        known = enrichment.get(str(path))
                        if known and known[0] == stat.st_size:
                            source = known[1]
                            canonical = source.get("content_identity") or {}
                            if canonical.get("provider") in {"tmdb", "imdb"} and canonical.get(
                                "id"
                            ):
                                body["content_id"] = identity(
                                    canonical["provider"] + ":movie:" + str(canonical["id"])
                                )
                                body["identity_source"] = "verified cached release metadata"
                                body["title"] = source.get("content_title") or body["title"]
                                body["description"] = (
                                    source.get("description") or body["description"]
                                )
                                body["remote_artwork"] = source.get("image_url") or ""
                                facts = source.get("facts") or {}
                                body["year"] = str(facts.get("releaseDate") or body["year"])[:4]
                        body["sidecar_signature"] = sidecar_signature
                        body["incomplete"] = partial_name or any(
                            path.is_relative_to(p) for p in incomplete
                        )
                        body["missing"] = False
                        added = previous["added"] if previous else time.time()
                        folder_rows.append(
                            (
                                identifier,
                                client_id,
                                str(path),
                                base,
                                stat.st_size,
                                stat.st_mtime_ns,
                                added,
                                json.dumps(body),
                            )
                        )
                        if len(folder_rows) % 20 == 0:
                            progress({"items": len(found) + len(folder_rows)})
                successful.append(base)
                found.extend(folder_rows)
            except (ValueError, OSError):
                errors.append(
                    {"message": "A Library Folder is unavailable or contains unsafe paths."}
                )
            progress({"items": len(found)})
        if stop.is_set():
            return {"cancelled": True}
        with self.lock, self.db:
            # Replace only successfully scanned folders. Missing folders retain their cards.
            for folder in successful:
                self.db.execute(
                    "DELETE FROM media_items WHERE client=? AND folder=?",
                    (client_id, folder),
                )
            self.db.executemany(
                "INSERT OR REPLACE INTO media_items VALUES (?,?,?,?,?,?,?,?)", found
            )
            self.db.execute(
                "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                ("errors:" + client_id, json.dumps(errors)),
            )
        details = self.enrich(client_id, setup, stop, progress, target.observed)
        if stop.is_set():
            return {"cancelled": True}
        if details in {"limit", "unavailable", "rejected"}:
            # The library is complete; the remaining descriptions come with a later refresh.
            note = {
                "message": "c411 is not answering for now; the remaining film details "
                "will be fetched on the next refresh."
            }
            with self.lock, self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                    ("errors:" + client_id, json.dumps([*errors, note])),
                )
        return {
            "count": len(found),
            "errors": errors,
            "partial": bool(errors),
            "film_details": details,
        }

    def _release_hashes(self, setup, observed):
        """Local path of each video in the client's torrents, with the torrent's hash.

        A torrent holding several videos is kept only for series episodes, since a film
        collection's release description fits none of its films alone.
        """
        from torrentlinker.paths import PathMapper
        from torrentlinker.torrent_meta import read_torrent

        mapper = PathMapper(setup.settings.path_mappings)
        result = {}
        for torrent in observed:
            files = torrent.files
            if not files:
                try:
                    data = setup.store.cached_torrent(torrent.hash)
                    files = read_torrent(data).files if data else {}
                except Exception:
                    continue
            videos = [name for name in files if Path(name).suffix.lower() in VIDEO]
            for name in videos:
                path = Path(mapper.to_local(str(torrent.save_path))) / name
                result[str(path.absolute())] = (torrent.hash.lower(), len(videos) == 1)
        return result

    @staticmethod
    def _plain(value):
        """A title compared without case, accents or punctuation."""
        import re
        import unicodedata

        value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def _catalogue_release(self, setup, title, year, series):
        """The best seeded Catalogue release whose name guesses to the same title and year."""
        import re

        wanted = self._plain(title)
        words = [w for w in re.findall(r"[A-Za-z0-9]+", wanted) if len(w) > 1][:6]
        for row in setup.store.catalogue_titled(words):
            guessed = guessit(row.title)
            if self._plain(guessed.get("title") or "") != wanted:
                continue
            # A complete-series pack ("…INTEGRALE…") has no episode marker, so series accept
            # any release of that title; films still refuse episodes.
            if not series and guessed.get("type") == "episode":
                continue
            if year and str(guessed.get("year") or "") not in {"", year}:
                continue
            return row.infohash.lower()
        return ""

    def enrich(self, client_id, setup, stop, progress, observed=()):
        """Fill film and series facts from c411 release descriptions, in French.

        Never fails the scan: answers are cached per release, so titles left over when
        c411 asks to wait or is unreachable are described by a later refresh.
        """
        from torrentlinker.indexer import KeyRefused, RateLimited

        self._tell_anime_apart(client_id)
        try:
            indexer = setup.indexer()
        except Exception:
            return "off"
        if not indexer.is_c411:
            return "off"
        with self.lock:
            rows = self.db.execute(
                "SELECT id, path, body FROM media_items WHERE client=?", (client_id,)
            ).fetchall()
        downloads = self._release_hashes(setup, observed)
        wanted: dict[tuple[str, str, bool], list[tuple[str, dict, str]]] = {}
        for row in rows:
            body = json.loads(row["body"])
            if body.get("kind") != "video" or body.get("release_details"):
                continue
            if body.get("description") and body.get("identity_source") != "filename":
                continue  # local or verified metadata already describes it
            series = bool(body.get("series"))
            title = (body["series"] if series else body["title"]).strip()
            known = downloads.get(str(Path(row["path"]).absolute()))
            exact = known[0] if known and (known[1] or series) else ""
            if title or exact:
                query = (title, "" if series else str(body.get("year") or ""), series)
                wanted.setdefault(query, []).append((row["id"], body, exact))
        status, failures, done = "complete", 0, 0
        for (title, year, series), items in wanted.items():
            if stop.is_set():
                break
            match_key = "c411-match:" + identity(json.dumps([title.lower(), year, series]))
            with self.lock:
                saved = self.db.execute(
                    "SELECT body FROM media_options WHERE key=?", (match_key,)
                ).fetchone()
            match = json.loads(saved[0]) if saved else None
            if match is None or (
                not match.get("hash") and time.time() - match.get("at", 0) > 7 * 86400
            ):
                match = {"hash": self._catalogue_release(setup, title, year, series)}
                match["at"] = time.time()
                with self.lock, self.db:
                    self.db.execute(
                        "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                        (match_key, json.dumps(match)),
                    )
            for identifier, body, exact in items:
                release = exact or match["hash"]
                if not release:
                    continue
                details_key = "c411-details:" + release
                with self.lock:
                    saved = self.db.execute(
                        "SELECT body FROM media_options WHERE key=?", (details_key,)
                    ).fetchone()
                if saved:
                    details = json.loads(saved[0])
                else:
                    try:
                        payload = indexer.torrent_json(release)
                    except (RateLimited, KeyRefused) as error:
                        status = "limit" if isinstance(error, RateLimited) else "rejected"
                        break
                    except Exception:
                        failures += 1
                        if failures >= 3:
                            status = "unavailable"
                            break
                        continue
                    metadata = payload.get("metadata") if isinstance(payload, dict) else None
                    details = (metadata or {}).get("tmdbData") or {}
                    if not isinstance(details, dict):
                        details = {}
                    with self.lock, self.db:
                        self.db.execute(
                            "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                            (details_key, json.dumps(details)),
                        )
                if not details.get("title"):
                    continue
                self._apply_release_details(body, details, release)
                with self.lock, self.db:
                    self.db.execute(
                        "UPDATE media_items SET body=? WHERE client=? AND id=?",
                        (json.dumps(body), client_id, identifier),
                    )
            if status != "complete":
                break
            done += 1
            if done % 10 == 0:
                progress({"film_details": done, "of": len(wanted)})
        return status

    def _tell_anime_apart(self, client_id):
        """Films and series described before anime was told apart: their cached c411
        details say whether they are anime, with no request."""
        with self.lock:
            rows = self.db.execute(
                "SELECT id, body FROM media_items WHERE client=?", (client_id,)
            ).fetchall()
        for row in rows:
            body = json.loads(row["body"])
            if not body.get("release_details") or "anime" in body:
                continue
            with self.lock:
                saved = self.db.execute(
                    "SELECT body FROM media_options WHERE key=?",
                    ("c411-details:" + body["release_details"],),
                ).fetchone()
            if saved:
                body["anime"] = is_anime_details(json.loads(saved[0]))
                with self.lock, self.db:
                    self.db.execute(
                        "UPDATE media_items SET body=? WHERE client=? AND id=?",
                        (json.dumps(body), client_id, row["id"]),
                    )

    @staticmethod
    def _apply_release_details(body, details, release):
        def text(name, limit=16000):
            value = details.get(name)
            if isinstance(value, list):
                value = ", ".join(
                    str(v.get("name") if isinstance(v, dict) else v) for v in value[:8]
                )
            return str(value or "").strip()[:limit]

        body["release_details"] = release
        body["anime"] = is_anime_details(details)
        if body.get("series"):
            body["series"] = text("title", 500) or body["series"]
        else:
            body["title"] = text("title", 500) or body["title"]
            body["year"] = (text("year") or text("releaseDate"))[:4] or body["year"]
        body["original_title"] = text("originalTitle", 500)
        if not body.get("description") or body.get("identity_source") == "filename":
            body["description"] = text("overview") or body.get("description", "")
        body["genre"] = body.get("genre") or text("genres", 500)
        for field, name in (
            ("director", "directors"),
            ("actors", "cast"),
            ("rating", "rating"),
            ("tagline", "tagline"),
        ):
            if text(name, 1000):
                body[field] = text(name, 1000)
        if not body.get("artwork") and not body.get("remote_artwork"):
            body["remote_artwork"] = text("posterUrl", 2000)
        content = text("id", 40)
        if content and body.get("identity_source") == "filename" and not body.get("series"):
            body["content_id"] = identity("tmdb:movie:" + content)
            body["identity_source"] = "c411 release description"

    def sidecar(self, client_id, path, folder, maximum=262144):
        checked = self.checked_path(client_id, str(path), folder)
        if checked.stat().st_size > maximum:
            raise ValueError("Local metadata file is too large.")
        return checked.read_bytes()

    def inspect(self, path, extension, client_id, folder):
        kind = "video" if extension in VIDEO else "music"
        body: dict[str, Any] = {
            "kind": kind,
            "title": path.stem,
            "release": path.name,
            "year": "",
            "artist": "",
            "album": "",
            "album_id": "",
            "genre": "",
            "language": "",
            "series": "",
            "season": None,
            "episode": None,
            "duration": 0,
            "description": "",
            "identity_source": "filename",
            "content_id": identity(str(path)),
            "subtitles": [],
            "artwork": "",
        }
        if kind == "music":
            from torrentlinker.audio_tags import read_tags

            tags = read_tags(path)
            if tags:
                body.update(
                    title=tags.title or path.stem,
                    artist=tags.artist,
                    album=tags.album,
                    year=tags.year,
                    track=tags.track,
                    duration=tags.duration,
                    codec=tags.codec,
                    identity_source="audio tags",
                )
                if tags.artist and tags.album:
                    body["album_id"] = identity(
                        str(path.parent) + "|" + tags.artist + "|" + tags.album
                    )
            try:
                import mutagen

                audio = mutagen.File(path, easy=True)
                genre = audio.get("genre", []) if audio else []
                body["genre"] = str(genre[0]) if genre else ""
            except Exception:
                pass
            try:
                raw_audio = mutagen.File(path)
                pictures = getattr(raw_audio, "pictures", []) or []
                image = pictures[0].data if pictures else None
                raw_tags = getattr(raw_audio, "tags", None)
                if image is None and raw_tags:
                    for tag in raw_tags.values():
                        if getattr(tag, "FrameID", "") == "APIC":
                            image = tag.data
                            break
                    if image is None and raw_tags.get("covr"):
                        image = bytes(raw_tags["covr"][0])
                if image:
                    body["artwork"] = self.cache_artwork(image)
            except Exception:
                pass
        else:
            anime = None if EPISODE_MARK.search(path.name) else anime_episode(path)
            if anime:
                guessed = guessit(path.name, {"type": "episode"})
                title = str(guessed.get("title") or path.stem)
                # The guesser keeps the mark in the title: "tenjo tenge e01m".
                title = ANIME_MARK.split(title)[0].strip(" ._-")
                title = re.sub(r"(?i)[ ._-]*(?:session|oav|ova|oad)$", "", title) or path.stem
                body.update(
                    title=title,
                    series=title,
                    year=str(guessed.get("year") or ""),
                    season=0 if anime[1] else None,
                    episode=anime[0],
                    oav=anime[1],
                )
            elif is_episode(path):
                guessed = guessit(path.name, {"type": "episode"})
                season, episode = guessed.get("season"), guessed.get("episode")
                body.update(
                    title=str(guessed.get("title") or path.stem),
                    year=str(guessed.get("year") or ""),
                    season=season if isinstance(season, int) and season < 100 else None,
                    episode=episode if isinstance(episode, int) else None,
                )
                body["series"] = body["title"]
                body["episode_title"] = str(guessed.get("episode_title") or "")
            else:
                guessed = guessit(path.name, {"type": "movie"})
                body.update(title=film_title(guessed, path), year=str(guessed.get("year") or ""))
            from torrentlinker.media_info import read_media

            facts = read_media(path)
            tags = dict(facts.tags) if facts else {}
            if not body["series"] and tags.get("show") and tags.get("episode", "").isdigit():
                # Proper TV tags make an episode even when the file name does not say so.
                season = tags.get("season", "")
                body.update(
                    series=tags["show"][:500],
                    title=tags["show"][:500],
                    season=int(season) if season.isdigit() and int(season) < 100 else None,
                    episode=int(tags["episode"]),
                )
            if body["series"] and tags.get("episode_title") and not body.get("episode_title"):
                body["episode_title"] = tags["episode_title"][:500]
            if tags.get("synopsis") and not body["description"]:
                body["description"] = tags["synopsis"]  # c411 details may still replace it
            if facts:
                body.update(
                    duration=facts.duration,
                    codec=facts.video_codec,
                    language=", ".join(sorted({a.language for a in facts.audio if a.language})),
                    embedded_subtitles=[
                        {"label": s.language or "Unknown language", "format": s.format}
                        for s in facts.subtitles
                    ],
                )
            for nfo in (
                path.with_suffix(".nfo"),
                path.parent / "movie.nfo",
                path.parent / "tvshow.nfo",
            ):
                try:
                    metadata = ElementTree.fromstring(self.sidecar(client_id, nfo, folder))
                    if metadata.tag not in {"movie", "tvshow", "episodedetails"}:
                        continue
                    for field, tag in (
                        ("title", "title"),
                        ("description", "plot"),
                        ("year", "year"),
                        ("genre", "genre"),
                    ):
                        if text := metadata.findtext(tag):
                            body[field] = text[:16000]
                    for unique in metadata.findall("uniqueid"):
                        provider = unique.get("type", "")
                        if provider in {"tmdb", "imdb"} and unique.text:
                            episode_key = (
                                f":{body['season']}:{body['episode']}"
                                if body["season"] is not None
                                else ""
                            )
                            body["content_id"] = identity(
                                provider + ":" + unique.text + episode_key
                            )
                            body["identity_source"] = "local " + provider + " metadata"
                            break
                    break
                except (OSError, ValueError, ElementTree.ParseError):
                    continue
            for subtitle in sorted(path.parent.glob(path.stem + "*"))[:100]:
                if subtitle.suffix.lower() in {".srt", ".vtt"} and (
                    subtitle.stem == path.stem or subtitle.stem.startswith(path.stem + ".")
                ):
                    body["subtitles"].append(
                        {
                            "id": identity(subtitle.name),
                            "label": subtitle.stem,
                            "path": str(subtitle),
                        }
                    )
        candidates = [path.with_suffix(".jpg"), path.with_suffix(".png")]
        candidates += [
            path.parent / name
            for name in ("poster.jpg", "poster.png", "cover.jpg", "cover.png", "folder.jpg")
        ]
        for image in candidates:
            try:
                data = self.sidecar(client_id, image, folder, 8 * 1024 * 1024)
                if data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
                    body["artwork"] = str(image)
                    break
            except (ValueError, OSError):
                continue
        return body

    def row(self, record, *, check=True):
        body = json.loads(record["body"])
        public = {
            k: v
            for k, v in body.items()
            if k
            not in {
                "artwork",
                "embedded_artwork",
                "incomplete",
                "missing",
                "sidecar_signature",
                "remote_artwork",
            }
        }
        public["subtitles"] = [
            {"id": s["id"], "label": s["label"]} for s in body.get("subtitles", [])
        ]
        with self.lock:
            saved = self.db.execute(
                "SELECT * FROM media_progress WHERE client=? AND item=?",
                (record["client"], record["id"]),
            ).fetchone()
        public.update(
            id=record["id"],
            added=record["added"],
            anime=is_anime(body, record["path"]),
            oav=bool(body.get("oav")),
            position=saved["position"] if saved else 0,
            watched=bool(saved["watched"]) if saved else False,
            artwork_url=(
                f"api/media/items/{record['id']}/artwork?client_id={record['client']}"
                if body.get("artwork") or body.get("remote_artwork")
                else ""
            ),
        )
        if not check:
            public.update(
                available=not body.get("incomplete") and not body.get("missing"),
                availability="unfinished"
                if body.get("incomplete")
                else "unavailable"
                if body.get("missing")
                else "available",
                reason="File is missing."
                if body.get("missing")
                else "File is unfinished."
                if body.get("incomplete")
                else "",
            )
            return public
        try:
            self.resolve(record["client"], record["id"])
            public.update(available=True, availability="available", reason="")
        except (ValueError, OSError) as error:
            reason = str(error)
            # Do not expose paths, which low-level filesystem exceptions can contain.
            public.update(
                available=False,
                availability="unfinished" if body.get("incomplete") else "unavailable",
                reason=reason
                if isinstance(error, ValueError)
                and not isinstance(error, OSError)
                and "/" not in reason
                else "This file is missing or its storage is unavailable.",
            )
        return public

    def listing(
        self,
        client_id,
        *,
        kind="",
        q="",
        view="all",
        genre="",
        year="",
        language="",
        availability="",
        album_id="",
        artist="",
        offset=0,
        limit=100,
        adult=False,
        anime=None,
        oav=None,
        **unused,
    ):
        self.setup(client_id)
        offset, limit = max(0, int(offset)), min(200, max(1, int(limit)))
        with self.lock:
            records = self.db.execute(
                "SELECT * FROM media_items WHERE client=? ORDER BY added DESC", (client_id,)
            ).fetchall()
            error = self.db.execute(
                "SELECT body FROM media_options WHERE key=?", ("errors:" + client_id,)
            ).fetchone()
        settings = self.setup(client_id).settings
        registered = {str(folder.path.absolute()) for folder in settings.library_folders}
        # XXX lives in its own panel, from folders of that kind, only once enabled.
        adult_folders = {
            str(folder.path.absolute())
            for folder in settings.library_folders
            if folder.kind is ContentKind.ADULT
        }
        adult = bool(adult)
        records = [
            record
            for record in records
            if record["folder"] in registered
            and (record["folder"] in adult_folders) == adult
            and (settings.adult_content or not adult)
        ]
        rows = [self.row(r, check=bool(availability)) for r in records]
        rows = [r for r in rows if (not kind or r["kind"] == kind)]
        filters = {
            name: sorted({str(r.get(name) or "") for r in rows if r.get(name)})
            for name in ("year", "language", "artist", "album")
        }
        filters["genre"] = sorted({genre for r in rows for genre in genres_of(r.get("genre"))})
        rows = [
            r
            for r in rows
            if q.casefold()
            in " ".join(
                str(r.get(k) or "") for k in ("title", "artist", "album", "release", "series")
            ).casefold()
            and (not genre or genre in genres_of(r["genre"]))
            and (not year or r["year"] == year)
            and (not language or language in r["language"].split(", "))
            and (not availability or r["availability"] == availability)
            and (not album_id or (r["album_id"] or r["id"]) == album_id)
            and (not artist or r["artist"] == artist)
            and (anime is None or r["anime"] == bool(anime))
            and (oav is None or r["oav"] == bool(oav))
            and (view != "continue" or r["position"] > 0 and not r["watched"])
            and (view != "films" or not r["series"])
            and (view != "series" or r["series"])
            and (view != "unwatched" or not r["watched"] and not r["position"])
            and (view != "rated" or rating_of(r) >= HIGHLY_RATED)
        ]
        if view == "rated":
            rows.sort(key=rating_of, reverse=True)
        if view == "series":
            rows = self._series_cards(rows)
        releases_by_content = {}
        for row in rows:
            releases_by_content.setdefault(row["content_id"], []).append(row["id"])
        if view not in {"tracks", "artists", "albums"}:
            seen = set()
            grouped = []
            for row in rows:
                key = row["content_id"] if row["kind"] == "video" else row["id"]
                if key not in seen:
                    grouped.append(row)
                    seen.add(key)
                elif row["available"]:
                    for position, selected in enumerate(grouped):
                        if selected["content_id"] == key and not selected["available"]:
                            grouped[position] = row
                            break
            rows = grouped
        if view in {"albums", "artists"}:
            grouped = {}
            for row in rows:
                key = (
                    (row["album_id"] or row["id"])
                    if view == "albums"
                    else (row["artist"] or row["id"])
                )
                if key not in grouped:
                    grouped[key] = {**row, "track_count": 0}
                grouped[key]["track_count"] += 1
            rows = list(grouped.values())
        if view == "tracks":
            rows.sort(key=lambda r: (r["artist"], r["album"], r.get("track", 0), r["title"]))
        total = len(rows)
        by_id = {record["id"]: record for record in records}
        page = []
        for row in rows[offset : offset + limit]:
            checked = self.row(by_id[row["id"]])
            if not checked["available"] and row["kind"] == "video" and not availability:
                for alternative in releases_by_content[row["content_id"]][:200]:
                    candidate = self.row(by_id[alternative])
                    if candidate["available"]:
                        checked = candidate
                        break
            entry = {**row, **checked}
            if row.get("series_card"):
                # A series card keeps its series name, counts and artwork over the episode's.
                for key in ("title", "series_card", "episode_count", "seasons", "content_id"):
                    entry[key] = row[key]
                for key in ("description", "artwork_url"):
                    entry[key] = row.get(key) or checked.get(key) or ""
            page.append(entry)
        return {
            "rows": page,
            "total": total,
            "filters": filters,
            "scanning": client_id in self.scanning,
            "errors": json.loads(error[0]) if error else [],
            "has_more": offset + limit < total,
            "next_offset": offset + limit if offset + limit < total else None,
        }

    @staticmethod
    def _series_cards(rows):
        """One card per series instead of every episode: the first episode stands for the
        series, with how many episodes and seasons it has."""
        cards: dict[tuple[str, bool], dict] = {}
        for row in sorted(rows, key=lambda r: (r["season"] or 0, r["episode"] or 0)):
            # A series' OAVs make a card of their own.
            key = (row["series"], bool(row.get("oav")))
            card = cards.get(key)
            if card is None:
                card = cards[key] = {
                    **row,
                    "title": row["series"] + (" (OAV)" if key[1] else ""),
                    "series_card": True,
                    "episode_count": 0,
                    "seasons": [],
                    "content_id": ("oav:" if key[1] else "series:")
                    + identity(row["series"].casefold()),
                }
            card["episode_count"] += 1
            if row["season"] is not None and row["season"] not in card["seasons"]:
                card["seasons"].append(row["season"])
            if not card.get("artwork_url") and row.get("artwork_url"):
                card["artwork_url"] = row["artwork_url"]
            if not card.get("description") and row.get("description"):
                card["description"] = row["description"]
        order = {(row["series"], bool(row.get("oav"))): i for i, row in enumerate(rows)}
        return sorted(cards.values(), key=lambda card: order[card["series"], card["oav"]])

    def home_rows(self, client_id, *, kind="video", limit=20, genres=8, scope="home"):
        """Video browsing as rows. The home: what to continue, what is new, the main genres,
        series, the best rated and what is not watched yet. The Films and Series views: what
        is new and the main genres of that kind. Each row says how to see all of it."""
        rows = []

        def add(key, title, **filters):
            page = self.listing(client_id, kind=kind, limit=limit, **filters)
            if page["rows"]:
                rows.append(
                    {
                        "key": key,
                        "title": title,
                        "filters": filters,
                        "total": page["total"],
                        "rows": page["rows"],
                    }
                )

        def genre_rows(view, least=3, **extra):
            page = self.listing(client_id, kind=kind, view=view, limit=200, **extra)
            counts: dict[str, int] = {}
            while True:
                for row in page["rows"]:
                    for genre in genres_of(row.get("genre")):
                        counts[genre] = counts.get(genre, 0) + 1
                if page["next_offset"] is None:
                    break
                page = self.listing(
                    client_id,
                    kind=kind,
                    view=view,
                    limit=200,
                    offset=page["next_offset"],
                    **extra,
                )
            top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            for genre, count in top[:genres]:
                if count >= least:
                    add("genre", genre, view=view, genre=genre, **extra)

        if scope == "adult":
            # The XXX panel: what is new, then its main genres, in XXX folders only.
            add("recent", "", view="recent", adult=True)
            genre_rows("all", adult=True)
            add("unwatched", "", view="unwatched", adult=True)
            return {"rows": rows}
        if scope == "anime":
            # The Anime panel: its series, their OAVs and its films, apart from the rest.
            add("recent", "", view="recent", anime=True)
            add("series", "", view="series", anime=True, oav=False)
            add("oav", "", view="series", anime=True, oav=True)
            add("films", "", view="films", anime=True)
            genre_rows("all", least=2, anime=True)
            return {"rows": rows}
        base = scope if scope in {"films", "series"} else "films"
        apart = {} if scope == "home" else {"anime": False}
        if scope == "home":
            add("continue", "", view="continue")
            add("recent", "", view="recent")
        else:
            add("recent", "", view=base, **apart)
        # Libraries hold far fewer series than films.
        genre_rows(base, least=2 if base == "series" else 3, **apart)
        if scope == "home":
            add("series", "", view="series")
            add("rated", "", view="rated")
            add("unwatched", "", view="unwatched")
        return {"rows": rows}

    def detail(self, client_id, identifier, *, episodes_offset=0, releases_offset=0, limit=200):
        item = self.row(self.record(client_id, identifier))
        with self.lock:
            records = self.db.execute(
                "SELECT * FROM media_items WHERE client=?", (client_id,)
            ).fetchall()
        others = [self.row(r, check=False) for r in records]
        releases = [r for r in others if r["content_id"] == item["content_id"]]
        episodes = sorted(
            [
                r
                for r in others
                if item["series"] and r["series"] == item["series"] and r["oav"] == item["oav"]
            ],
            key=lambda r: (r["season"] or 0, r["episode"] or 0),
        )
        limit = min(200, max(1, int(limit)))
        episodes_offset, releases_offset = (
            max(0, int(episodes_offset)),
            max(0, int(releases_offset)),
        )
        item["releases"] = releases[releases_offset : releases_offset + limit]
        item["episodes"] = episodes[episodes_offset : episodes_offset + limit]
        for label, rows, offset in (
            ("episodes", episodes, episodes_offset),
            ("releases", releases, releases_offset),
        ):
            item[label + "_total"] = len(rows)
            item[label + "_has_more"] = offset + limit < len(rows)
            item[label + "_next_offset"] = offset + limit if offset + limit < len(rows) else None
        return item

    def cache_artwork(self, data):
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("Artwork is too large.")
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(data)) as picture:
            if picture.width * picture.height > 32_000_000:
                raise ValueError("Artwork dimensions are too large.")
            picture.load()
            picture.thumbnail((1200, 1200))
            folder = self.agent.setup.path.parent / "media-artwork"
            folder.mkdir(exist_ok=True)
            key = hashlib.sha256(data).hexdigest() + ".png"
            destination = folder / key
            if destination.is_symlink():
                raise ValueError("Artwork cache contains an unsafe path.")
            if not destination.exists():
                picture.convert("RGB").save(destination, format="PNG")
        return "asset:" + key

    def artwork(self, client_id, identifier):
        row = self.record(client_id, identifier)
        image = json.loads(row["body"]).get("artwork")
        if not image:
            remote = json.loads(row["body"]).get("remote_artwork")
            if not remote:
                return None
            self.checked_path(client_id, row["path"], row["folder"])
            from torrentlinker.assistant.images import fetch_image

            data, _ = fetch_image(remote)
            image = self.cache_artwork(data)
            body = json.loads(row["body"])
            body["artwork"] = image  # download each poster once
            with self.lock, self.db:
                self.db.execute(
                    "UPDATE media_items SET body=? WHERE client=? AND id=?",
                    (json.dumps(body), client_id, identifier),
                )
        self.checked_path(client_id, row["path"], row["folder"])
        if image.startswith("asset:"):
            key = image[6:]
            import re

            if not re.fullmatch(r"[a-f0-9]{64}\.png", key):
                raise ValueError("Artwork unavailable.")
            path = self.agent.setup.path.parent / "media-artwork" / key
            if path.is_symlink() or not path.is_file():
                raise ValueError("Artwork unavailable.")
            return path
        data = self.sidecar(client_id, Path(image), row["folder"], 8 * 1024 * 1024)
        if not data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
            raise ValueError("Artwork is unavailable.")
        return self.checked_path(client_id, image, row["folder"])

    def subtitle(self, client_id, identifier, subtitle_id):
        row = self.record(client_id, identifier)
        self.resolve(client_id, identifier)
        found = next(
            (s for s in json.loads(row["body"]).get("subtitles", []) if s["id"] == subtitle_id),
            None,
        )
        if found is None:
            raise ValueError("Subtitle unavailable.")
        data = self.sidecar(client_id, Path(found["path"]), row["folder"], 2 * 1024 * 1024)
        text = data.decode("utf-8-sig", errors="replace")
        if Path(found["path"]).suffix.lower() == ".srt":
            import re

            text = "WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d{3})", r"\1.\2", text)
        return text.encode(), "text/vtt; charset=utf-8"

    def watched(self, client_id, identifier, watched):
        item = self.row(self.record(client_id, identifier))
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_progress VALUES (?,?,?,?,?)",
                (client_id, identifier, item["position"], item["duration"], bool(watched)),
            )
        return self.row(self.record(client_id, identifier))

    def forget_progress(self, client_id, identifier):
        """Reset playback progress so the title leaves Continue watching."""
        self.setup(client_id)
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM media_progress WHERE client=? AND item=?", (client_id, identifier)
            )

    def playlists(self, client_id):
        self.setup(client_id)
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM media_playlists WHERE client=? ORDER BY name", (client_id,)
            ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "media_ids": json.loads(r["items"])} for r in rows
        ]

    def save_playlist(self, client_id, name, media_ids, identifier=""):
        if not name.strip() or len(name) > 100 or len(media_ids) > 1000:
            raise ValueError("Use a playlist name and at most 1,000 tracks.")
        for media_id in media_ids:
            row = self.record(client_id, media_id)
            if json.loads(row["body"])["kind"] != "music":
                raise ValueError("Music playlists accept tracks only.")
        if identifier and not any(p["id"] == identifier for p in self.playlists(client_id)):
            raise ValueError("Playlist unavailable for this client.")
        identifier = identifier or uuid4().hex
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_playlists VALUES (?,?,?,?)",
                (identifier, client_id, name.strip(), json.dumps(media_ids)),
            )
        return {"id": identifier, "name": name.strip(), "media_ids": media_ids}

    def delete_playlist(self, client_id, identifier):
        self.setup(client_id)
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM media_playlists WHERE client=? AND id=?", (client_id, identifier)
            )
        return {"ok": True}

    def open_session(self, client_id, platform="web"):
        self.setup(client_id)
        identifier, token = uuid4().hex, secrets.token_urlsafe(32)
        state = {
            "current_id": "",
            "queue": [],
            "index": 0,
            "position": 0,
            "duration": 0,
            "paused": True,
            "volume": 1,
            "shuffle": False,
            "repeat": "off",
            "context": {},
            "command_ack": 0,
        }
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO media_sessions VALUES (?,?,?,?,?,?,?,'','')",
                (
                    identifier,
                    identity(token),
                    client_id,
                    platform,
                    time.time(),
                    json.dumps(state),
                    "[]",
                ),
            )
        return {"id": identifier, "token": token, "state": state, "commands": []}

    def session_record(self, identifier, token):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM media_sessions WHERE id=?", (identifier,)
            ).fetchone()
        if row is None or not secrets.compare_digest(row["token"], identity(token)):
            raise ValueError("Player session unavailable for this instance.")
        self.setup(row["client"])
        return row

    @staticmethod
    def append_command(state, commands, command):
        if len(commands) >= 100:
            raise ValueError("This player is not consuming commands. Reopen its Media view.")
        command["sequence"] = (
            max(
                [
                    state.get("command_ack", 0),
                    state.get("command_sequence", 0),
                    *[c["sequence"] for c in commands],
                ]
            )
            + 1
        )
        state["command_sequence"] = command["sequence"]
        return [*commands, command]

    def session(
        self,
        identifier,
        token,
        *,
        report=None,
        action="",
        media_ids=None,
        index=None,
        position=None,
        volume=None,
        shuffle=None,
        repeat=None,
        context=None,
        command_ack=None,
        kind=None,
        track_id=None,
        source_token=None,
    ):
        with self.lock, self.db:
            row = self.session_record(identifier, token)
            state, commands = json.loads(row["body"]), json.loads(row["commands"])
            if report is not None:
                if not isinstance(report, dict):
                    raise ValueError("Invalid player report.")
                queue = report.get("queue", state["queue"])
                if not isinstance(queue, list) or len(queue) > 1000:
                    raise ValueError("Playback queues accept at most 1,000 items.")
                for item in queue:
                    self.record(row["client"], item)
                current = report.get("current_id", state["current_id"]) or ""
                if current and current not in queue:
                    raise ValueError("The current media must belong to this player's queue.")
                player_index = report.get("index", state["index"])
                if (
                    not isinstance(player_index, int)
                    or isinstance(player_index, bool)
                    or player_index < 0
                    or player_index >= max(1, len(queue))
                ):
                    raise ValueError("Choose an index inside this player's queue.")
                for key in ("paused", "shuffle"):
                    if key in report and not isinstance(report[key], bool):
                        raise ValueError("Player toggles must be true or false.")
                if current and queue[player_index] != current:
                    raise ValueError("The current item must match the player's queue index.")
                for key in ("index", "paused", "shuffle", "repeat"):
                    if key in report:
                        state[key] = report[key]
                if current != state["current_id"]:
                    state.pop("track_state", None)
                    state.pop("track_result", None)
                state.update(queue=queue, current_id=current)
                if "track_state" in report:
                    tracks = media_tracks.inventory(report["track_state"], current)
                    if tracks["source_token"] != state.get("track_state", {}).get("source_token"):
                        state.pop("track_result", None)
                    state["track_state"] = tracks
                if "track_result" in report:
                    if report["track_result"] is None:
                        state.pop("track_result", None)
                    else:
                        state["track_result"] = media_tracks.result_report(report["track_result"])
                for key in ("position", "duration", "volume"):
                    if key in report:
                        state[key] = bounded_number(report[key], 1 if key == "volume" else 8640000)
                if state["repeat"] not in {"off", "one", "all"}:
                    raise ValueError("Choose a supported repeat mode.")
                ack = int(report.get("command_ack", state.get("command_ack", 0)))
                state["command_ack"] = max(state.get("command_ack", 0), ack)
                if current:
                    previous = self.db.execute(
                        "SELECT watched FROM media_progress WHERE client=? AND item=?",
                        (row["client"], current),
                    ).fetchone()
                    watched = bool(previous[0]) if previous else False
                    browsing = context or state.get("context", {})
                    if (
                        state["duration"] > 0
                        and state["position"] >= state["duration"] * 0.95
                        and not browsing.get("preview_id")
                        and not browsing.get("preview")
                    ):
                        try:
                            self.resolve(row["client"], current)
                            watched = True
                        except (ValueError, OSError):
                            pass
                    self.db.execute(
                        "INSERT OR REPLACE INTO media_progress VALUES (?,?,?,?,?)",
                        (row["client"], current, state["position"], state["duration"], watched),
                    )
            if command_ack is not None:
                state["command_ack"] = max(state.get("command_ack", 0), int(command_ack))
            commands = [c for c in commands if c["sequence"] > state.get("command_ack", 0)]
            if context is not None:
                if not isinstance(context, dict) or len(json.dumps(context)) > 16000:
                    raise ValueError("Player browsing context is too large.")
                state["context"] = context
            if action:
                commands = self.cancel_track_request(state, commands)
                command = (
                    media_tracks.selection(state, kind, track_id, source_token)
                    if action == "select_track"
                    else self.command(
                        row["client"], action, media_ids, index, position, volume, shuffle, repeat
                    )
                )
                commands = self.append_command(state, commands, command)
            allowed = False
            if state.get("track_request"):
                try:
                    grant = self.agent.access.grant(row["actor"])
                    allowed = (
                        grant.mode == "execute"
                        and "media" in grant.permissions
                        and row["client"] in grant.clients
                        and row["actor"] == state["track_request"]["actor"]
                    )
                except PermissionError:
                    pass
                commands = media_tracks.advance(state, commands, self.append_command, allowed)
            self.db.execute(
                "UPDATE media_sessions SET body=?,commands=?,updated=? WHERE id=?",
                (json.dumps(state), json.dumps(commands), time.time(), identifier),
            )
            return {"id": identifier, "state": state, "commands": commands}

    @staticmethod
    def cancel_track_request(state, commands):
        request = state.get("track_request")
        if request and request["status"] in {"failed", "completed"}:
            state.pop("track_request", None)
            return commands
        if request and request["status"] not in {"failed", "completed"}:
            request.update(
                status="failed",
                error="Another player command cancelled automatic track preparation.",
            )
            commands = [c for c in commands if c.get("request_token") != request["source_token"]]
        return commands

    def command(self, client_id, action, media_ids, index, position, volume, shuffle, repeat):
        if action not in {
            "play",
            "pause",
            "seek",
            "volume",
            "queue",
            "next",
            "previous",
            "shuffle",
            "repeat",
        }:
            raise ValueError("Unknown playback action.")
        required = {
            "seek": position,
            "volume": volume,
            "shuffle": shuffle,
            "repeat": repeat,
            "queue": media_ids,
        }
        if action in required and required[action] is None:
            raise ValueError("Supply the value required by this player action.")
        command: dict[str, Any] = {"action": action}
        if media_ids is not None:
            if not isinstance(media_ids, list) or len(media_ids) > 1000:
                raise ValueError("Playback queues accept at most 1,000 items.")
            for item in media_ids:
                self.resolve(client_id, item)
            command["media_ids"] = media_ids
        if index is not None:
            index = int(index)
            if index < 0 or media_ids and index >= len(media_ids):
                raise ValueError("Choose an item in the playback queue.")
            command["index"] = index
        for key, value, maximum in (("position", position, 8640000), ("volume", volume, 1)):
            if value is not None:
                command[key] = bounded_number(value, maximum)
        if shuffle is not None:
            command["shuffle"] = bool(shuffle)
        if repeat is not None:
            if repeat not in {"off", "one", "all"}:
                raise ValueError("Choose a supported repeat mode.")
            command["repeat"] = repeat
        return command

    def actor_session(self, actor):
        grant = self.agent.access.grant(actor)
        with self.lock:
            row = self.db.execute("SELECT * FROM media_sessions WHERE actor=?", (actor,)).fetchone()
        if row is None or row["client"] not in grant.clients:
            raise ValueError("Open Chat from the Media player to attach this discussion.")
        self.agent.target(actor, row["client"])
        if time.time() - row["updated"] > 90:
            raise ValueError("The attached player is offline. Reopen its Media view.")
        return row

    def actor_context(self, actor):
        try:
            session = self.actor_session(actor)
        except (ValueError, PermissionError):
            return None
        state = json.loads(session["body"])
        result = {
            key: state[key]
            for key in ("position", "duration", "paused", "shuffle", "repeat", "context")
        }
        browsing = state.get("context") or {}
        result["context"] = {
            key: browsing[key]
            for key in ("kind", "view", "q", "filters", "genre", "year", "language", "playlist")
            if key in browsing
        }
        selected = browsing.get("selected_ids") or (
            [browsing["selection"]] if browsing.get("selection") else []
        )
        selected = selected[:200] if isinstance(selected, list) else []
        known = []
        for media_id in selected:
            try:
                self.record(session["client"], media_id)
                known.append(media_id)
            except ValueError:
                continue
        if known:
            selection_id = identity(session["id"] + ":browsing-selection")
            with self.lock, self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO media_selections VALUES (?,?,?,?)",
                    (selection_id, actor, session["client"], json.dumps(known)),
                )
            result["context"].update(selection_id=selection_id, selected_count=len(known))
        result["partial_preview"] = bool(browsing.get("preview_id") or browsing.get("preview"))
        if isinstance(browsing.get("preview"), dict):
            result["preview"] = {
                key: browsing["preview"][key]
                for key in ("verified_bytes", "total_bytes")
                if key in browsing["preview"]
            }
        result["client_id"] = session["client"]
        result["queue_count"] = len(state["queue"])
        if state.get("track_request"):
            result["track_request"] = {
                key: state["track_request"][key]
                for key in ("status", "error", "preferences")
                if key in state["track_request"]
            }
        if state["current_id"]:
            try:
                item = self.row(self.record(session["client"], state["current_id"]))
            except ValueError:
                result["current_unavailable"] = True
                return result
            result["current"] = {
                key: item[key]
                for key in (
                    "title",
                    "release",
                    "kind",
                    "artist",
                    "album",
                    "series",
                    "season",
                    "episode",
                    "year",
                    "available",
                )
            }
        return result

    @staticmethod
    def preview_path_matches(expected, actual):
        expected, actual = expected.absolute(), actual.absolute()
        return expected == actual or (
            actual.suffix.lower() == ".!qb" and expected == actual.with_suffix("")
        )

    def preview_window(self, client_id, identifier, torrent_hash):
        path, size, piece_size, pieces = self.preview_pieces(client_id, identifier, torrent_hash)
        count = 0
        for done in pieces:
            if not done:
                break
            count += 1
        verified = min(size, count * piece_size, path.stat().st_size)
        if verified <= 0:
            raise ValueError(
                "The start of this file is not downloaded yet. Wait and refresh preview."
            )
        return path, verified, size

    def preview_map(self, client_id, preview_id):
        """The live piece map of an open preview: which pieces qBittorrent has verified, so
        the player can read the file as it downloads."""
        with self.lock:
            preview = self.previews.get(preview_id)
        if preview is None or preview["client"] != client_id:
            raise ValueError("Preview expired. Select Preview downloaded portion again.")
        _, size, piece_size, pieces = self.preview_pieces(
            client_id, preview["item"], preview["hash"]
        )
        return size, piece_size, pieces

    def preview_pieces(self, client_id, identifier, torrent_hash):
        """The file and its verified pieces, once qBittorrent proves their offsets."""
        setup = self.setup(client_id)
        if setup.settings.client != "qbittorrent":
            raise ValueError(
                "Partial preview requires a confirmed qBittorrent sequential download."
            )
        record = self.record(client_id, identifier)
        path = self.checked_path(client_id, record["path"], record["folder"])
        client = setup.client()
        reader = getattr(client, "media_preview_state", None)
        if reader is None:
            raise ValueError("This Torrent Client cannot prove a safe partial preview.")
        state = reader(torrent_hash)
        if not state.get("sequential") or "checking" in state.get("state", "").lower():
            raise ValueError(
                "Enable sequential download in qBittorrent and finish its hash check first."
            )
        files = state.get("files") or []
        if len(files) != 1:
            raise ValueError(
                "Partial preview currently supports single-file torrents only. "
                "Multi-file offsets are unproven."
            )
        file = files[0]
        size, piece_size = int(file["size"]), int(state.get("piece_size") or 0)
        if size <= 0 or piece_size <= 0 or file.get("piece_range") != [0, (size - 1) // piece_size]:
            raise ValueError("qBittorrent did not prove this file's piece offsets.")
        # Match the live file layout to the exact registered local file before reading bytes.
        torrent = client.torrent(torrent_hash, with_files=False)
        if torrent is None:
            raise ValueError("Torrent is no longer present in qBittorrent.")
        from torrentlinker.paths import PathMapper

        mapper = PathMapper(setup.settings.path_mappings)
        expected = Path(mapper.to_local(str(torrent.save_path))) / str(file["name"])
        if not self.preview_path_matches(expected, path):
            raise ValueError("The torrent's file layout no longer matches this local media.")
        pieces = state.get("piece_states") or []
        if len(pieces) != (size + piece_size - 1) // piece_size:
            raise ValueError("qBittorrent returned an incomplete piece map.")
        return path, size, piece_size, [piece == 2 for piece in pieces]

    def create_preview(self, client_id, identifier):
        from torrentlinker.paths import PathMapper

        setup = self.setup(client_id)
        record = self.record(client_id, identifier)
        path = Path(record["path"]).absolute()
        mapper = PathMapper(setup.settings.path_mappings)
        target = self.agent.for_client(client_id)
        torrent_hash = ""
        for torrent in target.observed:
            root = Path(mapper.to_local(str(torrent.save_path)))
            candidates = torrent.files or {torrent.name: 0}
            if any(self.preview_path_matches(root / name, path) for name in candidates):
                torrent_hash = torrent.hash
                break
        if not torrent_hash:
            raise ValueError("Refresh Media to identify this qBittorrent download first.")
        _, verified, size = self.preview_window(client_id, identifier, torrent_hash)
        preview_id = uuid4().hex
        with self.lock:
            # Each attempt has a fixed prefix. It never grows implicitly.
            self.previews[preview_id] = {
                "client": client_id,
                "item": identifier,
                "hash": torrent_hash,
                "bytes": verified,
                "created": time.time(),
            }
            while len(self.previews) > 100:
                self.previews.pop(next(iter(self.previews)))
        return {
            "preview_id": preview_id,
            "verified_bytes": verified,
            "total_bytes": size,
            "progress": verified / size,
            "label": "Preview of downloaded portion",
            "note": "Fixed verified prefix. Refresh preview as the download progresses. "
            "Formats needing the missing end of the file may not play yet.",
        }

    def preview_source(self, client_id, preview_id):
        with self.lock:
            preview = self.previews.get(preview_id)
        if (
            preview is None
            or preview["client"] != client_id
            or time.time() - preview["created"] > 14400
        ):
            raise ValueError("Preview expired. Select Preview downloaded portion again.")
        path, verified, _ = self.preview_window(client_id, preview["item"], preview["hash"])
        if verified < preview["bytes"]:
            raise ValueError("Downloaded pieces changed. Wait and refresh preview.")
        return path, preview["bytes"]

    def close_preview(self, client_id, preview_id):
        with self.lock:
            preview = self.previews.get(preview_id)
            if preview and preview["client"] == client_id:
                del self.previews[preview_id]
        return {"ok": True}

    def close(self):
        """Release application-owned state after workers and players have stopped."""
        with self.lock:
            if getattr(self, "closed", False):
                return
            self.closed = True
            self.previews.clear()
            self.observations.clear()
            self.db.close()
