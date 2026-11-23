"""Owner Media browsing operations shared by the desktop panel and Web routes."""

import base64
from urllib.parse import parse_qs, unquote, urlsplit


def tracker_hash(value: str) -> str:
    value = value.lower()
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("Unknown tracker release")
    return value


class MediaBrowserService:
    def __init__(self, agent):
        self.agent = agent

    def request(self, path, body=None, method="GET"):
        parsed = urlsplit(path)
        parts = [unquote(part) for part in parsed.path.split("/")]
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        body = body or {}
        client = (
            query.pop("client_id", None)
            or body.get("client_id")
            or self.agent.setup.settings.default_client_id
        )
        media = self.agent.media
        if parts[0] == "prerolls":
            from torrentlinker.preroll_workspace import PrerollWorkspace

            action = "state" if len(parts) == 1 and method == "GET" else parts[-1]
            return PrerollWorkspace(self.agent.setup, media=media).request(action, body)
        if parts == ["media"] and method == "GET":
            allowed = {
                "kind",
                "q",
                "view",
                "genre",
                "year",
                "language",
                "availability",
                "album_id",
                "artist",
                "offset",
                "limit",
                "adult",
                "anime",
                "oav",
            }
            if query.keys() - allowed:
                raise ValueError("Unknown Media filter")
            for key in ("offset", "limit"):
                if key in query:
                    query[key] = int(query[key])
            for key in ("adult", "anime", "oav"):
                if key in query:
                    if query[key] not in {"true", "false"}:
                        raise ValueError("Invalid Media filter")
                    query[key] = query[key] == "true"
            return media.listing(client, **query)
        if parts == ["media", "home"] and method == "GET":
            return media.home_rows(
                client,
                kind="video",
                scope=query.get("scope", "home"),
                limit=int(query.get("limit", 20)),
            )
        if parts[:2] == ["media", "items"] and len(parts) >= 3:
            identifier = parts[2]
            if len(parts) == 3 and method == "GET":
                return media.detail(
                    client,
                    identifier,
                    **{
                        key: int(query[key])
                        for key in ("episodes_offset", "releases_offset", "limit")
                        if key in query
                    },
                )
            if len(parts) == 4 and parts[3] == "artwork" and method == "GET":
                path = media.artwork(client, identifier)
                if path is None:
                    raise ValueError("Artwork unavailable")
                with path.open("rb") as source:
                    data = source.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError("Artwork too large")
                mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
                return {"data_url": f"data:{mime};base64," + base64.b64encode(data).decode()}
            if len(parts) == 4 and parts[3] == "forget-progress" and method == "POST":
                media.forget_progress(client, identifier)
                return {"ok": True}
            if len(parts) == 4 and parts[3] == "watched" and method == "POST":
                return media.watched(client, identifier, bool(body["watched"]))
        if (
            len(parts) == 4
            and parts[:2] == ["media", "tracker"]
            and parts[3] == "download"
            and method == "POST"
        ):
            return media.tracker_download(client, media.setup(client), tracker_hash(parts[2]))
        if parts == ["media", "playlists"] and method == "GET":
            return media.playlists(client)
        if parts == ["media", "playlists"] and method == "POST":
            return media.save_playlist(
                client, str(body["name"]), list(body["media_ids"]), str(body.get("id", ""))
            )
        if len(parts) == 3 and parts[:2] == ["media", "playlists"] and method == "DELETE":
            return media.delete_playlist(client, parts[2])
        if parts == ["media", "scan"] and method == "POST":
            media.setup(client)
            return {
                "id": self.agent.jobs.submit(
                    "media-scan",
                    lambda stop, progress: media.scan(client, stop, progress),
                    client_id=client,
                )
            }
        if parts[:1] == ["jobs"] and len(parts) in {2, 3}:
            job = self.agent.jobs.get(parts[1])
            if job["kind"] != "media-scan" or job["client_id"] != client:
                raise ValueError("This is not a Media scan for the selected client")
            if len(parts) == 2 and method == "GET":
                return job
            if len(parts) == 3 and parts[2] == "cancel" and method == "POST":
                self.agent.jobs.cancel(parts[1])
                return {"ok": True}
        raise ValueError("Unknown Media browsing operation")
