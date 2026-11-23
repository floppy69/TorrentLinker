"""Send an approved release through the same checked queue as an Owner's download."""

from __future__ import annotations

import threading

from torrentlinker.download_queue import entries
from torrentlinker.member_requests import Release
from torrentlinker.web.operations import JobRequest


class RequestApproval:
    def __init__(self, media):
        self.media = media

    @property
    def client_id(self):
        return self.media.agent.setup.settings.default_client_id

    def release(self, infohash: str) -> Release:
        entry = self.media.tracker_entry(self.client_id, infohash)
        best, facts = entry["release"], entry.get("facts") or {}
        return Release(
            best["hash"],
            best["name"],
            int(best["size"]),
            facts.get("title") or entry.get("title") or best["name"],
            str(facts.get("year") or entry.get("year") or ""),
        )

    def choices(self, query: str) -> list[dict]:
        """Search tracker films and cache their authoritative release details for approval."""
        import time
        from dataclasses import asdict

        from torrentlinker.media_tracker import film_key
        from torrentlinker.torrent_search import native_search

        searched = set()
        if query.strip():
            setup = self.media.setup(self.client_id)
            page = native_search(setup.indexer(), {"name": query.strip(), "category": "1"})
            grouped = self.media._tracker_cache(self.client_id, "tracker-new")
            changed = set()
            for candidate in page.rows:
                facts = page.details.get(candidate.infohash or "")
                if not facts or facts.kind != "movie" or not facts.title:
                    continue
                key = film_key(facts.title, str(facts.year or ""))
                entry = grouped.setdefault(
                    key,
                    {
                        "title": facts.title,
                        "year": str(facts.year or ""),
                        "facts": asdict(facts),
                        "releases": [],
                    },
                )
                entry["at"] = time.time()
                entry["releases"] = [
                    r for r in entry["releases"] if r["hash"] != candidate.infohash
                ]
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
                changed.add(key)
                searched.add(candidate.infohash)
            for key in changed:
                self.media._tracker_save(self.client_id, "tracker-new", key, grouped[key])
        found = {}
        for kind in ("tracker-new", "tracker-upgrade"):
            for entry in self.media._tracker_cache(self.client_id, kind).values():
                for release in entry.get("releases") or []:
                    if (
                        release["hash"] not in searched
                        and query.casefold()
                        not in (entry.get("title", "") + " " + release["name"]).casefold()
                    ):
                        continue
                    score = self.media._score(
                        self.media.agent.setup.settings.release_score,
                        release["name"],
                        release["size"],
                        entry.get("facts") or {},
                    )
                    found[release["hash"]] = {
                        "hash": release["hash"],
                        "name": release["name"],
                        "size": release["size"],
                        "score": score.get("score"),
                    }
        return list(found.values())[:100]

    def send(self, infohash: str) -> None:
        setup = self.media.setup(self.client_id)
        client = setup.client()
        if any(t.hash.lower() == infohash for t in client.torrents(with_files=False)):
            return  # A lost receipt or retried Request must not add the torrent twice.
        matching = [e for e in entries(setup.store) if e.candidate.infohash == infohash]
        for entry in matching:
            if entry.status == "uncertain" or entry.status == "failed" and not entry.retry_safe:
                raise ValueError("Check the Torrent Client before retrying this uncertain send.")
            if entry.status in {"refused", "failed"}:
                setup.store.download_outcome(entry.key, "queued")
        self.media.tracker_enqueue(self.client_id, setup, infohash)
        result = self.media.agent.for_client(self.client_id).run(
            JobRequest(kind="send-queue", hashes=[infohash]), threading.Event(), lambda _p: None
        )
        if not any(r["hash"] == infohash and r["outcome"] == "sent" for r in result["rows"]):
            raise ValueError(
                "The Torrent Client did not confirm this download. Check the queue before retrying."
            )

    def margin(self, pending: int) -> dict:
        setup = self.media.agent.setup
        state = setup.profile_workspace().state()
        profile = state.get("api") or {}
        up, down = profile.get("uploaded_actual"), profile.get("downloaded_actual")
        capacity = (
            max(0, int(up / 0.8 - down))
            if isinstance(up, (int, float)) and isinstance(down, (int, float))
            else None
        )
        try:
            torrents = self.media.setup(self.client_id).client().torrents(with_files=False)
            ongoing = sum(max(0, int(t.size * (1 - t.progress))) for t in torrents)
        except Exception:
            ongoing = None
        return {
            "capacity": capacity,
            "downloading": ongoing,
            "pending": pending,
            "stale": bool(state.get("api_stale")),
        }

    def refresh(self, requests) -> None:
        from torrentlinker.media_tracker import film_key

        rows = [r for r in requests.review() if r["state"] in {"sent", "downloading"}]
        if not rows:
            return
        try:
            torrents = {
                t.hash.lower(): t
                for t in self.media.setup(self.client_id).client().torrents(with_files=False)
            }
            films = self.media._library_films(self.client_id)
        except Exception:
            return  # A disconnected client is not proof of a failed or missing download.
        for row in rows:
            torrent = torrents.get(row["infohash"])
            if torrent is None:
                continue
            state = (
                "available"
                if torrent.progress >= 1 and film_key(row["title"], row["year"]) in films
                else "downloading"
            )
            if state != row["state"]:
                requests.move(row["id"], state, "")
