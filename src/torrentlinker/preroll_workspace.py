"""Owner management shared by the desktop and Web Media panels."""

from torrentlinker.age_ratings import from_tmdb
from torrentlinker.prerolls import Clip, prerolls
from torrentlinker.tmdb import Tmdb


class PrerollWorkspace:
    def __init__(self, setup, media=None):
        self.setup = setup
        self.media = media
        self.library = prerolls(setup)

    def trailers(self, values):
        key = self.setup.secrets.get("tmdb-api-key")
        if not key:
            raise ValueError("Set the TMDb key in Settings first.")
        identifier, kind = str(values.get("tmdb_id", "")), values.get("media_type", "movie")
        if not identifier.isdigit() or kind not in {"movie", "tv"}:
            raise ValueError("Choose a TMDb film or series ID.")
        service = Tmdb(key)
        try:
            videos = service.videos(identifier, kind)
            found = from_tmdb(service.certifications(identifier, kind))
            rating = found.rating if found and found.french else None
            return {"videos": videos, "rating": rating}
        finally:
            service._http.close()

    def request(self, action, body=None):
        body = body or {}
        library = self.library
        if action.startswith("community-"):
            from torrentlinker.community_site import community_site

            return community_site(self.setup).request(
                "items-" + action.removeprefix("community-"), body
            )
        if action == "studio-artwork":
            from torrentlinker.studio import studio

            if self.media is None:
                raise ValueError("Library artwork is unavailable.")
            path = self.media.artwork(
                body.get("client_id") or self.setup.settings.default_client_id, body["media_id"]
            )
            if path is None:
                raise ValueError("This library item has no artwork.")
            return studio(self.setup).add_asset(path, "Library artwork")
        if action.startswith("studio-"):
            from torrentlinker.studio import studio

            return studio(self.setup).request(action.removeprefix("studio-"), body)
        if action == "state":
            return library.snapshot()
        if action == "configure":
            return library.configure(body["configuration"])
        if action == "import-file":
            return library.import_file(body["path"], body.get("title", ""), body.get("rating"))
        if action == "import-folder":
            return library.import_folder(body["path"])
        if action == "update":
            return library.update(body["id"], body["value"])
        if action == "delete":
            return library.delete(body["id"])
        if action == "trailer-search":
            key = self.setup.secrets.get("tmdb-api-key")
            if not key:
                raise ValueError("Set the TMDb key in Settings first.")
            kind, query = body.get("media_type", "movie"), str(body.get("query", "")).strip()
            if kind not in {"movie", "tv"} or not 1 <= len(query) <= 200:
                raise ValueError("Choose a title and media type.")
            service = Tmdb(key)
            try:
                rows = service._get(
                    "/search/" + kind,
                    {"query": query, "language": "fr-FR", "include_adult": "false"},
                ).get("results", [])
                return {
                    "results": [
                        {
                            "id": str(r["id"]),
                            "title": r.get("title", r.get("name", "")),
                            "year": str(r.get("release_date", r.get("first_air_date", "")))[:4],
                        }
                        for r in rows[:20]
                    ]
                }
            finally:
                service._http.close()
        if action == "trailers":
            return self.trailers(body)
        if action == "add-trailer":
            found = self.trailers(body)
            selected = next((v for v in found["videos"] if v["key"] == body.get("key")), None)
            if selected is None:
                raise ValueError("Choose a trailer returned by TMDb.")
            with library.lock:
                duplicate = next(
                    (c for c in library.data["clips"] if c.get("youtube") == selected["key"]), None
                )
                if duplicate:
                    return duplicate
                clip = Clip(
                    title=selected["name"],
                    category="trailer",
                    source="youtube",
                    youtube=selected["key"],
                    rating=found["rating"],
                    duration=120,
                )
                library.data["clips"].append(clip.model_dump())
                library._save()
                return clip.model_dump()
        raise ValueError("Unknown pre-roll operation.")
