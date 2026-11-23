"""Age Ratings of the Media items: read from the NFO, then TMDb, else set by a person (#127).

They live in `media_ratings` beside `media_items`, one row per item with its place on the
scale (`rank`), so a Member's age limit filters with one indexed join:
`LEFT JOIN media_ratings r ON r.client=i.client AND r.item=i.id ... AND r.rank <= ?`;
an unrated item has no rank and is hidden under any limit. A series is rated as a whole:
every episode carries the series' rating. A person's rating is never replaced by a scan.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from torrentlinker import age_ratings
from torrentlinker.age_ratings import Found

TMDB_RETRY = 7 * 86400  # a title TMDb did not rate is asked again a week later


def default_tmdb(key: str) -> Any:
    from torrentlinker.tmdb import Tmdb

    return Tmdb(key)


class AgeRatings:
    db: Any
    lock: threading.RLock
    # Tests replace it, so that no test reaches the real TMDb.
    tmdb_client: Callable[[str], Any] = staticmethod(default_tmdb)

    def create_ratings(self) -> None:
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS media_ratings
                    (client TEXT, item TEXT, rating TEXT, rank INTEGER, source TEXT,
                    setter TEXT NOT NULL DEFAULT '', setter_name TEXT NOT NULL DEFAULT '',
                    suggestion TEXT, updated REAL, PRIMARY KEY(client, item));
                CREATE INDEX IF NOT EXISTS media_ratings_rank ON media_ratings(client, rank);
            """)

    @staticmethod
    def rating_group(item: str, body: dict) -> str | None:
        """Items rated together: a film alone, a series' episodes as one. None: not rated."""
        if body.get("kind") != "video":
            return None
        series = str(body.get("series") or "").strip().casefold()
        return "series:" + series if series else "film:" + item

    def age_rating(self, client_id: str, item: str) -> dict:
        """The item's rating, its source and who set it, and any suggestion waiting."""
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM media_ratings WHERE client=? AND item=?", (client_id, item)
            ).fetchone()
        return self._public_rating(row)

    @staticmethod
    def _public_rating(row) -> dict:
        if row is None:
            return {"rating": None, "source": "", "by": "", "suggestion": None}
        return {
            "rating": row["rating"],
            "source": row["source"] or "",
            "by": row["setter_name"],
            "suggestion": json.loads(row["suggestion"]) if row["suggestion"] else None,
        }

    def _group_items(self, client_id: str, item: str) -> list[str]:
        rows = self.db.execute(
            "SELECT id, body FROM media_items WHERE client=?", (client_id,)
        ).fetchall()
        bodies = {r["id"]: json.loads(r["body"]) for r in rows}
        if item not in bodies:
            raise KeyError(item)
        group = self.rating_group(item, bodies[item])
        if group is None:
            raise ValueError("Only videos have an Age Rating.")
        return [i for i, body in bodies.items() if self.rating_group(i, body) == group]

    def rate(self, client_id: str, item: str, rating: str, *, setter: str, name: str) -> dict:
        """A person rates a film, or a whole series; it stays until a person changes it."""
        if age_ratings.rank(rating) is None:
            raise ValueError("Choose Tous publics, −10, −12, −16 or −18.")
        now = time.time()
        with self.lock, self.db:
            items = self._group_items(client_id, item)
            self.db.executemany(
                "INSERT OR REPLACE INTO media_ratings VALUES (?,?,?,?,'person',?,?,NULL,?)",
                [
                    (client_id, i, rating, age_ratings.rank(rating), setter, name, now)
                    for i in items
                ],
            )
        return self.age_rating(client_id, item)

    def unrated(self, client_id: str) -> list[dict]:
        """Every unrated film and series once, with the suggestion waiting, if any."""
        with self.lock:
            rows = self.db.execute(
                "SELECT i.id, i.body, i.added, r.suggestion FROM media_items i "
                "LEFT JOIN media_ratings r ON r.client=i.client AND r.item=i.id "
                "WHERE i.client=? AND r.rank IS NULL ORDER BY i.added DESC",
                (client_id,),
            ).fetchall()
        found: dict[str, dict] = {}
        for row in rows:
            body = json.loads(row["body"])
            group = self.rating_group(row["id"], body)
            if group is None or group in found:
                continue
            found[group] = {
                "id": row["id"],
                "title": body.get("series") or body.get("title") or "",
                "series": bool(body.get("series")),
                "year": body.get("year") or "",
                "genre": body.get("genre") or "",
                "artwork_url": (
                    f"api/media/items/{row['id']}/artwork?client_id={client_id}"
                    if body.get("artwork") or body.get("remote_artwork")
                    else ""
                ),
                "suggestion": json.loads(row["suggestion"]) if row["suggestion"] else None,
            }
        return list(found.values())

    def confirm_suggestions(self, client_id: str, *, setter: str, name: str) -> int:
        """ "Confirmer les n suggestions": every waiting suggestion becomes the rating."""
        confirmed = 0
        for row in self.unrated(client_id):
            if row["suggestion"]:
                self.rate(
                    client_id, row["id"], row["suggestion"]["rating"], setter=setter, name=name
                )
                confirmed += 1
        return confirmed

    def apply_age_ratings(self, client_id: str, setup, stop: threading.Event) -> None:
        """Rate what no person rated: a French NFO or TMDb rating applies, a foreign one waits
        as a suggestion. TMDb is asked only with a key, once per title and week."""
        with self.lock:
            rows = self.db.execute(
                "SELECT id, body FROM media_items WHERE client=?", (client_id,)
            ).fetchall()
            existing = {
                r["item"]: r
                for r in self.db.execute(
                    "SELECT * FROM media_ratings WHERE client=?", (client_id,)
                ).fetchall()
            }
        groups: dict[str, list[tuple[str, dict]]] = {}
        for row in rows:
            body = json.loads(row["body"])
            if group := self.rating_group(row["id"], body):
                groups.setdefault(group, []).append((row["id"], body))
        secrets = getattr(setup, "secrets", None)
        key = secrets.get("tmdb-api-key") if secrets is not None else ""
        tmdb = self.tmdb_client(key) if key else None
        failures = 0
        now = time.time()
        writes = []
        for items in groups.values():
            if stop.is_set():
                break
            person = next(
                (
                    existing[i]
                    for i, _ in items
                    if i in existing and existing[i]["source"] == "person"
                ),
                None,
            )
            if person is not None:
                # A new episode of a series a person rated takes the series' rating.
                writes += [
                    (
                        client_id,
                        i,
                        person["rating"],
                        person["rank"],
                        "person",
                        person["setter"],
                        person["setter_name"],
                        None,
                        now,
                    )
                    for i, _ in items
                    if i not in existing or existing[i]["source"] != "person"
                ]
                continue
            found, source = None, ""
            certification = next(
                (b["certification"] for _, b in items if b.get("certification")), ""
            )
            if certification:
                found, source = age_ratings.parse(certification), "nfo"
            if (found is None or not found.french) and tmdb is not None and failures < 3:
                try:
                    from_tmdb = self._tmdb_rating(tmdb, items)
                except Exception:
                    failures += 1
                    from_tmdb = None
                if from_tmdb and (found is None or from_tmdb.french):
                    found, source = from_tmdb, "tmdb"
            if found is None:
                continue
            for item, _ in items:
                before = existing.get(item)
                if found.french:
                    row = (
                        client_id,
                        item,
                        found.rating,
                        age_ratings.rank(found.rating),
                        source,
                        "",
                        "",
                        None,
                        now,
                    )
                elif before is not None and before["rank"] is not None:
                    continue  # rated already; a foreign suggestion does not replace it
                else:
                    row = (
                        client_id,
                        item,
                        None,
                        None,
                        source,
                        "",
                        "",
                        json.dumps(found.suggestion(source)),
                        now,
                    )
                if before is None or tuple(before)[2:8] != row[2:8]:
                    writes.append(row)
        with self.lock, self.db:
            # Items gone from the library take their rating with them.
            self.db.execute(
                "DELETE FROM media_ratings WHERE client=? AND item NOT IN "
                "(SELECT id FROM media_items WHERE client=?)",
                (client_id, client_id),
            )
            if writes:
                self.db.executemany(
                    "INSERT OR REPLACE INTO media_ratings VALUES (?,?,?,?,?,?,?,?,?)", writes
                )

    def _tmdb_rating(self, tmdb, items: list[tuple[str, dict]]) -> Found | None:
        body = items[0][1]
        series = bool(body.get("series"))
        media_type = "tv" if series else "movie"
        tmdb_id = next(
            (str(b["tmdb_id"]) for _, b in items if str(b.get("tmdb_id", "")).isdigit()), ""
        )
        title = str(body.get("series") if series else body.get("title") or "").strip()
        year = "" if series else str(body.get("year") or "")[:4]
        if not tmdb_id and not title:
            return None
        cache = "tmdb-age:" + (
            f"{media_type}:{tmdb_id}"
            if tmdb_id
            else json.dumps([media_type, title.casefold(), year])
        )
        with self.lock:
            saved = self.db.execute(
                "SELECT body FROM media_options WHERE key=?", (cache,)
            ).fetchone()
        answer = json.loads(saved[0]) if saved else None
        if answer is None or (
            not answer.get("certifications") and time.time() - answer.get("at", 0) > TMDB_RETRY
        ):
            if not tmdb_id:
                from torrentlinker.domain import ContentKind

                kind = ContentKind.SERIES if series else ContentKind.MOVIE
                tmdb_id = tmdb.lookup(title, int(year) if year.isdigit() else None, kind) or ""
            certifications = tmdb.certifications(tmdb_id, media_type) if tmdb_id else []
            answer = {"certifications": certifications, "at": time.time()}
            with self.lock, self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO media_options VALUES (?,?)", (cache, json.dumps(answer))
                )
        return age_ratings.from_tmdb([tuple(c) for c in answer["certifications"]])
