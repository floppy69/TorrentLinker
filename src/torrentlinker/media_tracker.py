"""Media's tracker rows: films on c411 whose release scores well, films only.

"Available on the tracker" is c411's latest film releases the library does not have: one
listing request returns a hundred releases with the runtime and tags ReleaseScore needs.
"Better versions on the tracker" costs no request: a library film knows its own duration,
and the Catalogue knows every release's name and size, so each film is scored locally
against its file. Both are cached; the rows are drawn from the cache.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict
from typing import Any

from guessit import guessit

LATEST_PAGES = 20  # at most this many listing pages per refresh; known releases end it sooner
RUN_INTERVAL = 600  # seconds between two refreshes of the same client
LATEST_KEEP = 30 * 86400  # a latest release stays suggested for a month
UPGRADES_RECHECK = 86400  # a library film is scored against the Catalogue daily
UPGRADE_MARGIN = 5  # an upgrade scores at least this much more than the file on disk
ROW_LIMIT = 60


def plain(value: Any) -> str:
    """A title compared without case, accents or punctuation."""
    import unicodedata

    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def film_key(title: str, year: str) -> str:
    return json.dumps([plain(title), str(year or "")])


class TrackerRows:
    """Mixed into MediaLibrary, which provides db, lock, agent, artwork and cache_artwork."""

    db: Any
    lock: Any

    # -- Cache ------------------------------------------------------------------------------

    def _tracker_cache(self, client_id, kind: str) -> dict[str, dict[str, Any]]:
        prefix = f"{kind}:{client_id}:"
        with self.lock:
            rows = self.db.execute(
                "SELECT key, body FROM media_options WHERE key LIKE ?", (prefix + "%",)
            ).fetchall()
        return {row[0][len(prefix) :]: json.loads(row[1]) for row in rows}

    def tracker_saves(self) -> int:
        """Grows with every saved suggestion, so a quiet scan knows to redraw the rows."""
        return getattr(self, "_tracker_saved", 0)

    def _tracker_save(self, client_id, kind: str, key: str, entry: dict[str, Any]) -> None:
        self._tracker_saved = self.tracker_saves() + 1
        entry["cache_key"] = f"{kind}:{client_id}:{key}"
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                (entry["cache_key"], json.dumps(entry)),
            )

    # -- What the library holds -------------------------------------------------------------

    def _library_films(self, client_id) -> dict[str, dict[str, Any]]:
        """Library films by title and year, with their files and durations."""
        with self.lock:
            rows = self.db.execute(
                "SELECT id, path, size, body FROM media_items WHERE client=?", (client_id,)
            ).fetchall()
        films: dict[str, dict[str, Any]] = {}
        for row in rows:
            body = json.loads(row["body"])
            if body.get("kind") != "video" or body.get("series") or body.get("anime"):
                continue
            title, year = (body.get("title") or "").strip(), str(body.get("year") or "")
            if not title:
                continue
            film = films.setdefault(film_key(title, year), {"title": title, "year": year})
            film.setdefault("files", []).append(
                {
                    "id": row["id"],
                    "name": row["path"].replace("\\", "/").rsplit("/", 1)[-1],
                    "size": row["size"],
                    "minutes": round((body.get("duration") or 0) / 60),
                }
            )
            for name in ("genre", "rating", "description"):
                film.setdefault(name, body.get(name))
        return films

    # -- Scoring ----------------------------------------------------------------------------

    @staticmethod
    def _score(preferences, name: str, size: int, facts: dict[str, Any]) -> dict[str, Any]:
        from torrentlinker.release_score.estimate import estimate
        from torrentlinker.release_score.service import score

        return score(estimate(name, size, facts), preferences)

    def _latest(
        self, setup, indexer, known: set[str], stop: threading.Event
    ) -> tuple[dict[str, dict[str, Any]], str]:
        """Each film's readable releases on c411's latest listing pages, newest first.

        The first refresh reads up to LATEST_PAGES pages; later ones stop at the first page
        holding a release already known, since everything after it was read before. What was
        read is kept when c411 asks to wait part-way.
        """
        from torrentlinker.indexer import KeyRefused, RateLimited
        from torrentlinker.release_score.estimate import estimate
        from torrentlinker.torrent_search import native_search

        found: dict[str, dict[str, Any]] = {}
        params = {"category": "1", "sortBy": "createdAt", "sortOrder": "desc"}
        for page_number in range(1, LATEST_PAGES + 1):
            if stop.is_set():
                return found, "cancelled"
            try:
                page = native_search(indexer, params, page_number)
            except (RateLimited, KeyRefused):
                return found, "limit"
            for candidate in page.rows:
                listing = page.details.get(candidate.infohash or "")
                if listing is None or listing.kind != "movie" or not listing.title:
                    continue
                facts = asdict(listing)
                if estimate(candidate.title, candidate.size, facts) is None:
                    continue  # ReleaseScore cannot read this release at all
                key = film_key(listing.title, str(listing.year or ""))
                entry = found.setdefault(
                    key,
                    {
                        "at": time.time(),
                        "title": listing.title,
                        "year": str(listing.year or ""),
                        "facts": facts,
                        "releases": [],
                    },
                )
                entry["releases"].append(
                    {
                        "hash": candidate.infohash,
                        "name": candidate.title,
                        "size": candidate.size,
                        "seeders": candidate.seeders,
                        "category": candidate.categories[0] if candidate.categories else None,
                        "published_at": candidate.published_at,
                    }
                )
            if not page.has_more or any(c.infohash in known for c in page.rows):
                break
        return found, "complete"

    def _upgrade(self, setup, film: dict[str, Any]) -> dict[str, Any]:
        """The film's best Catalogue release, scored with the film's own duration."""
        minutes = max((f["minutes"] for f in film["files"]), default=0)
        entry: dict[str, Any] = {"at": time.time(), "title": film["title"], "year": film["year"]}
        if minutes <= 0:
            return entry
        wanted = plain(film["title"])
        words = [w for w in wanted.split() if len(w) > 1][:6]
        releases = []
        for row in setup.store.catalogue_titled(words, limit=60):
            if not 2000 <= (row.category or 0) <= 2999:
                continue
            if film["year"] and film["year"] not in row.title:
                continue  # cheap before guessing the name
            guessed = guessit(row.title, {"type": "movie"})
            if plain(guessed.get("title") or "") != wanted:
                continue
            releases.append(
                {
                    "hash": row.infohash.lower(),
                    "name": row.title,
                    "size": row.size,
                    "seeders": row.seeders,
                    "category": row.category,
                }
            )
        entry.update(
            releases=releases,
            files=[{"name": f["name"], "size": f["size"]} for f in film["files"]],
            library_id=film["files"][0]["id"],
            facts={
                "title": film["title"],
                "year": film["year"],
                "runtime": minutes,
                "kind": "movie",
                "tags": [],
                "genres": [g.strip() for g in str(film.get("genre") or "").split(",") if g],
                "rating": film.get("rating"),
                "overview": film.get("description") or "",
            },
        )
        return entry

    def tracker_refresh(self, client_id, setup, stop: threading.Event) -> str:
        """Read c411's latest releases, then score library films against the Catalogue.

        The refresh waits ten minutes only after one has finished: a cancelled scan leaves
        nothing to wait for, and the local pass resumes with the films it had not reached.
        """
        gate = "tracker-run:" + client_id
        with self.lock:
            saved = self.db.execute(
                "SELECT body FROM media_options WHERE key=?", (gate,)
            ).fetchone()
        if saved and time.time() - json.loads(saved[0]) < RUN_INTERVAL:
            return "waiting"
        status = self._refresh_latest(client_id, setup, stop)
        self._tracker_status_save(client_id, status)
        if stop.is_set():
            return "cancelled"
        # Upgrades: local only, every film whose answer is a day old or missing.
        library = self._library_films(client_id)
        upgrades = self._tracker_cache(client_id, "tracker-upgrade")
        for key, film in library.items():
            if stop.is_set():
                return "cancelled"
            if time.time() - upgrades.get(key, {}).get("at", 0) > UPGRADES_RECHECK:
                self._tracker_save(client_id, "tracker-upgrade", key, self._upgrade(setup, film))
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_options VALUES (?,?)", (gate, json.dumps(time.time()))
            )
        return status

    def _tracker_status_save(self, client_id, status: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                ("tracker-status:" + client_id, json.dumps(status)),
            )

    def _tracker_status(self, client_id) -> str:
        """How the last read of c411's listing ended; "" before the first one."""
        with self.lock:
            saved = self.db.execute(
                "SELECT body FROM media_options WHERE key=?", ("tracker-status:" + client_id,)
            ).fetchone()
        return json.loads(saved[0]) if saved else ""

    def _refresh_latest(self, client_id, setup, stop: threading.Event) -> str:
        """Available: c411's latest film releases, newest first."""
        try:
            indexer = setup.indexer()
        except Exception:
            return "off"
        if not indexer.is_c411:
            return "off"
        known = self._tracker_cache(client_id, "tracker-new")
        hashes = {r["hash"] for entry in known.values() for r in entry.get("releases") or []}
        try:
            with indexer.background(stop):
                latest, status = self._latest(setup, indexer, hashes, stop)
        except Exception:
            return "unreachable"
        for key, entry in latest.items():
            fresh = {release["hash"] for release in entry["releases"]}
            entry["releases"] += [
                release
                for release in known.get(key, {}).get("releases", [])
                if release["hash"] not in fresh
            ]
            self._tracker_save(client_id, "tracker-new", key, entry)
        with self.lock, self.db:
            for key, entry in known.items():
                if time.time() - entry.get("at", 0) > LATEST_KEEP and key not in latest:
                    self.db.execute("DELETE FROM media_options WHERE key=?", (entry["cache_key"],))
        return status

    # -- Rows -------------------------------------------------------------------------------

    def _best(self, preferences, entry: dict[str, Any]) -> dict[str, Any] | None:
        """The entry's best release under the current profile, so a new profile applies at once."""
        best = None
        for release in entry.get("releases") or []:
            result = self._score(preferences, release["name"], release["size"], entry["facts"])
            if result.get("score") is None:
                continue
            scored = {**release, "score": result["score"], "color": result.get("color", "")}
            if best is None or (scored["score"], scored["seeders"]) > (
                best["score"],
                best["seeders"],
            ):
                best = scored
        return best

    def tracker_rows(self, client_id, setup) -> dict[str, dict[str, Any]]:
        """The two rows by key, drawn from the cache and scored with the current profile.

        With c411 as Indexer both rows always show: "loading" until a refresh has filled
        the cache, "empty" when no release reaches the threshold.
        """
        from urllib.parse import urlsplit

        from torrentlinker.release_score.preferences import Preferences

        if urlsplit(setup.settings.indexer.url).hostname != "c411.org":
            return {}
        preferences = setup.settings.release_score
        threshold = Preferences.model_validate(preferences).threshold
        library = self._library_films(client_id)
        latest = self._tracker_cache(client_id, "tracker-new")
        known = self._tracker_cache(client_id, "tracker-upgrade")
        available = []
        for key, entry in latest.items():
            best = None if key in library else self._best(preferences, entry)
            if best and best["score"] >= threshold:
                available.append(self._tracker_item(entry, best))
        # The newest first, as in a "recently added" row.
        available.sort(key=lambda item: -(item["tracker"]["published_at"] or 0))
        upgrades = []
        for key, entry in known.items():
            best = self._best(preferences, entry) if key in library else None
            if not best or best["score"] < threshold:
                continue
            own = max(
                (
                    self._score(preferences, f["name"], f["size"], entry["facts"]).get("score") or 0
                    for f in entry.get("files") or []
                ),
                default=0,
            )
            if best["score"] >= own + UPGRADE_MARGIN:
                item = self._tracker_item(entry, best)
                item["tracker"].update(own_score=own)
                upgrades.append(item)
        upgrades.sort(key=lambda item: -item["tracker"]["score"])
        status = self._tracker_status(client_id)
        # Why a row has nothing yet: no key, c411 asking to wait, or c411 not answering.
        reason = (
            "key"
            if not setup.secrets.get("indexer-api-key")
            else {"limit": "limit", "unreachable": "unreachable"}.get(status, "")
        )
        rows = {}
        for key, items, cached in (("tracker", available, latest), ("upgrades", upgrades, known)):
            state = "ready" if items else "empty" if cached else "loading"
            if state == "loading" and reason:
                state = "unavailable"
            elif state == "loading" and status in {"complete", "waiting"}:
                state = "empty"
            rows[key] = {
                "key": key,
                "title": "",
                "filters": {"tracker": key},
                "total": min(len(items), ROW_LIMIT),
                "rows": items[:ROW_LIMIT],
                "state": state,
                "reason": reason if state == "unavailable" else "",
                "threshold": threshold,
            }
        return rows

    @staticmethod
    def _tracker_item(entry: dict[str, Any], best: dict[str, Any]) -> dict[str, Any]:
        facts = entry.get("facts") or {}
        return {
            "id": "tracker-" + best["hash"],
            "kind": "video",
            "title": facts.get("title") or entry.get("title") or best["name"],
            "year": str(facts.get("year") or entry.get("year") or ""),
            "rating": facts.get("rating"),
            "genre": ", ".join(facts.get("genres") or []),
            "description": facts.get("overview") or "",
            "duration": (facts.get("runtime") or 0) * 60,
            "artwork_url": "tracker" if facts.get("poster_url") or entry.get("library_id") else "",
            "available": True,
            "tracker": {
                "hash": best["hash"],
                "name": best["name"],
                "size": best["size"],
                "seeders": best["seeders"],
                "score": best["score"],
                "color": best.get("color", ""),
                "published_at": best.get("published_at"),
            },
        }

    def tracker_entry(self, client_id, infohash: str) -> dict[str, Any]:
        for kind in ("tracker-new", "tracker-upgrade"):
            for entry in self._tracker_cache(client_id, kind).values():
                for release in entry.get("releases") or []:
                    if release["hash"] == infohash:
                        return {**entry, "release": release}
        raise ValueError("This tracker release is no longer suggested.")

    def tracker_artwork(self, client_id, infohash: str):
        """An upgrade shows the library film's poster; a new film its c411 poster, once."""
        entry = self.tracker_entry(client_id, infohash)
        if entry.get("library_id"):
            return self.artwork(client_id, entry["library_id"])  # type: ignore[attr-defined]
        poster = (entry.get("facts") or {}).get("poster_url") or ""
        if not poster.startswith("https://image.tmdb.org/"):
            return None
        if not entry.get("artwork"):
            from torrentlinker.assistant.images import fetch_image

            data, _ = fetch_image(poster)
            entry["artwork"] = self.cache_artwork(data)  # type: ignore[attr-defined]
            entry.pop("release", None)
            with self.lock, self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO media_options VALUES (?,?)",
                    (entry["cache_key"], json.dumps(entry)),
                )
        image = entry["artwork"]
        if not re.fullmatch(r"asset:[a-f0-9]{64}\.png", image):
            return None
        return self.agent.setup.path.parent / "media-artwork" / image[6:]  # type: ignore[attr-defined]

    def tracker_enqueue(self, client_id, setup, infohash: str) -> dict[str, Any]:
        """Queue the suggested release, as Search does; nothing starts until the queue is sent."""
        from torrentlinker.catalogue_sync import download_url
        from torrentlinker.download_queue import enqueue
        from torrentlinker.indexer import Candidate

        best = self.tracker_entry(client_id, infohash)["release"]
        category = best.get("category")
        if setup.download_folder(category) is None:
            raise ValueError(
                "Choose a Download Folder for this category in Settings before queueing."
            )
        indexer = setup.indexer()
        candidate = Candidate(
            best["name"],
            best["size"],
            indexer.unredact(download_url(infohash)),
            best["seeders"],
            infohash,
            f"https://c411.org/torrents/{infohash}",
            categories=(category,) if category is not None else (),
        )
        added = enqueue(setup.store, indexer, candidate, setup.verified_download_folder(category))
        return {"queued": bool(added), "title": best["name"]}

    def tracker_download(self, client_id, setup, infohash: str) -> dict[str, Any]:
        """Download now: queue the release, then send it to the client as Search's "Start" does."""
        from torrentlinker.web.operations import JobRequest

        result = self.tracker_enqueue(client_id, setup, infohash)
        operations = self.agent.for_client(client_id)  # type: ignore[attr-defined]
        request = JobRequest(kind="send-queue", hashes=[infohash])
        job = self.agent.jobs.submit(  # type: ignore[attr-defined]
            "search-send-queue",
            lambda stop, progress: operations.run(request, stop, progress),
            client_id=client_id,
            parameters=request.model_dump(),
        )
        return {**result, "job": job}
