"""Authenticated media adapters. Playback bytes remain under existing storage roots.

A Member sees only what is visible to them (ADR-0022): every route naming an item answers
404 for a hidden one, as for a missing one, and their `client_id` is ignored: the server
reads the client that holds the item. Progress, playlists and sessions are the actor's.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from torrentlinker.accounts import OWNER_ACTOR, WATCH, Actor, Permission
from torrentlinker.web.permissions import needs

NOT_FOUND = "Media item not found."


class MediaClient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = ""


class SessionOpen(MediaClient):
    platform: Literal["web", "desktop"] = "web"


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=100)
    report: dict[str, Any] | None = None
    action: str = Field(default="", max_length=30)
    media_ids: list[str] | None = Field(default=None, max_length=1000)
    index: int | None = Field(default=None, ge=0, le=1000)
    position: float | None = Field(default=None, ge=0, le=8640000)
    volume: float | None = Field(default=None, ge=0, le=1)
    shuffle: bool | None = None
    repeat: Literal["off", "one", "all"] | None = None
    context: dict[str, Any] | None = None
    command_ack: int | None = Field(default=None, ge=0)
    kind: Literal["audio", "subtitle"] | None = None
    track_id: str | None = Field(default=None, max_length=128)
    source_token: str | None = Field(default=None, max_length=128)


class PlaylistSave(MediaClient):
    id: str = ""
    name: str = Field(min_length=1, max_length=100)
    media_ids: list[str] = Field(max_length=1000)


class Watched(MediaClient):
    watched: bool


class AgeRating(MediaClient):
    rating: Literal["TP", "10", "12", "16", "18"]


class MediaChat(BaseModel):
    token: str = Field(max_length=100)
    conversation_id: str = Field(default="", max_length=64)
    new: bool = False


def media_routes(app, agent, assistant):
    from torrentlinker.media_conversion import Conversions

    media = agent.media
    conversions = app.state.media_conversions = Conversions()

    def client(value):
        return value or agent.setup.settings.default_client_id

    def actor(request: Request) -> Actor:
        return getattr(request.state, "actor", OWNER_ACTOR)

    def who(request: Request) -> dict:
        found = actor(request)
        return {"account": found.account, "viewer": found.viewer}

    def target(request: Request, value: str, identifier: str = "") -> str:
        """The Owner's chosen client; for a Member, the one holding the item, else the
        default one."""
        if actor(request).owner:
            return client(value)
        held = media.holder(identifier) if identifier else None
        return held or agent.setup.settings.default_client_id

    def item(request: Request, value: str, identifier: str) -> str:
        """The client of an item the actor sees. A hidden item is missing to them."""
        found, chosen = actor(request), target(request, value, identifier)
        if not found.owner:
            try:
                media.visible(chosen, identifier, found)
            except KeyError:
                raise HTTPException(404, NOT_FOUND) from None
        return chosen

    def preview(request: Request, value: str, preview_id: str) -> str:
        """The client of a preview: a Member reaches only their own, of an item they see."""
        found = actor(request)
        if found.owner:
            return client(value)
        opened = media.preview_owner(preview_id)
        if opened is None or opened[2] != found.account:
            raise HTTPException(404, "Preview expired. Select Preview downloaded portion again.")
        return item(request, opened[0], opened[1])

    def watchable(request: Request, media_ids) -> None:
        for identifier in media_ids or ():
            item(request, "", str(identifier))

    def edits_ratings(request: Request) -> bool:
        actor = getattr(request.state, "actor", None)
        return actor is not None and actor.holds(Permission.EDIT_RATINGS)

    def setter(request: Request) -> dict:
        actor = request.state.actor
        return {
            "setter": actor.account,
            "name": request.app.state.accounts.display_name(actor.account),
        }

    @app.get("/api/prerolls")
    def preroll_state():
        from torrentlinker.preroll_workspace import PrerollWorkspace

        state = PrerollWorkspace(agent.setup, media=media).request("state")
        accounts = app.state.accounts
        state["accounts"] = [{"id": "owner", "name": "Owner"}] + [
            {"id": row["id"], "name": row["name"]} for row in accounts.members()
        ]
        state["viewers"] = [
            {"id": row["id"], "name": row["name"]}
            for account in state["accounts"]
            for row in accounts.profiles(account["id"])
            if row["id"]
        ]
        return state

    @app.post("/api/prerolls/{operation}")
    def preroll_operation(operation: str, body: dict):
        from torrentlinker.preroll_workspace import PrerollWorkspace

        return PrerollWorkspace(agent.setup, media=media).request(operation, body)

    @app.get("/api/studio/exports/{filename}")
    def studio_export(filename: str):
        from pathlib import Path

        from torrentlinker.studio import studio

        suffix = Path(filename).suffix
        if suffix not in {".mp4", ".tlstudio"}:
            raise HTTPException(404, "Export unavailable.")
        path = studio(agent.setup).path("exports", Path(filename).stem, suffix)
        if not path.is_file():
            raise HTTPException(404, "Export unavailable.")
        return FileResponse(
            path,
            filename=filename,
            media_type="video/mp4" if suffix == ".mp4" else "application/zip",
        )

    @app.get("/api/prerolls/clips/{identifier}")
    def preview_preroll(identifier: str):
        from torrentlinker.prerolls import prerolls

        return FileResponse(prerolls(agent.setup).file(identifier), media_type="video/mp4")

    @app.get("/api/media/items/{identifier}/prerolls")
    @needs(*WATCH)
    def preroll_plan(identifier: str, request: Request, client_id: str = ""):
        from urllib.parse import quote

        from torrentlinker.prerolls import prerolls

        chosen = item(request, client_id, identifier)
        feature = media.detail(chosen, identifier, actor=actor(request))
        plan = prerolls(agent.setup).plan(feature, actor(request))
        for step in plan["steps"]:
            if step["kind"] == "clip":
                step["url"] = (
                    f"api/media/items/{quote(identifier, safe='')}/prerolls/"
                    f"{step['clip']}/stream?client_id={quote(chosen, safe='')}"
                )
        return plan

    @app.get("/api/media/items/{identifier}/prerolls/{clip_id}/stream")
    @needs(*WATCH)
    def preroll_stream(identifier: str, clip_id: str, request: Request, client_id: str = ""):
        from torrentlinker.prerolls import prerolls

        chosen = item(request, client_id, identifier)
        library = prerolls(agent.setup)
        clip = library.clip(clip_id)
        if not library.allowed(
            clip, media.detail(chosen, identifier, actor=actor(request)), actor(request)
        ):
            raise HTTPException(404, "Pre-roll unavailable.")
        return FileResponse(library.file(clip_id), media_type="video/mp4")

    @app.post("/api/media/items/{identifier}/rating")
    @needs(Permission.EDIT_RATINGS)
    def rate(identifier: str, body: AgeRating, request: Request):
        try:
            return media.rate(client(body.client_id), identifier, body.rating, **setter(request))
        except KeyError:
            raise HTTPException(404, "Media item not found.") from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/media/ratings")
    @needs(Permission.EDIT_RATINGS)
    def unrated(client_id: str = ""):
        """The "Sans classification" page: every unrated film and series."""
        rows = media.unrated(client(client_id))
        return {"rows": rows, "suggestions": sum(1 for r in rows if r["suggestion"])}

    @app.post("/api/media/ratings/confirm")
    @needs(Permission.EDIT_RATINGS)
    def confirm_ratings(body: MediaClient, request: Request):
        return {"confirmed": media.confirm_suggestions(client(body.client_id), **setter(request))}

    @app.get("/api/media")
    @needs(*WATCH)
    def listing(
        request: Request,
        client_id: str = "",
        kind: str = "",
        q: str = "",
        view: str = "all",
        genre: str = "",
        year: str = "",
        language: str = "",
        availability: str = "",
        album_id: str = "",
        artist: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
        adult: bool = False,
        anime: bool | None = None,
        oav: bool | None = None,
    ):
        client_id = target(request, client_id)
        result = media.listing(
            client_id,
            kind=kind,
            q=q,
            view=view,
            genre=genre,
            year=year,
            language=language,
            availability=availability,
            offset=offset,
            limit=limit,
            album_id=album_id,
            artist=artist,
            adult=adult,
            anime=anime,
            oav=oav,
            actor=actor(request),
        )
        if edits_ratings(request) and kind != "music" and offset == 0 and view != "continue":
            # The "Sans classification (n)" entry of the Media menu, for editors only.
            result = {
                **result,
                "edit_ratings": True,
                "unrated": len(media.unrated(client(client_id))),
            }
        return result

    @app.get("/api/media/home")
    @needs(*WATCH)
    def home(
        request: Request,
        client_id: str = "",
        limit: int = Query(20, ge=1, le=50),
        scope: str = Query("home", pattern="^(home|films|series|anime|adult)$"),
    ):
        return media.home_rows(
            target(request, client_id),
            kind="video",
            limit=limit,
            scope=scope,
            actor=actor(request),
        )

    @app.post("/api/media/tracker/{infohash}/download")
    def tracker_download(infohash: str, body: MediaClient):
        from torrentlinker.media_browser import tracker_hash

        target = client(body.client_id)
        try:
            return media.tracker_download(target, media.setup(target), tracker_hash(infohash))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/media/scan", status_code=202)
    def scan(body: MediaClient):
        target = client(body.client_id)
        media.setup(target)
        return {
            "id": agent.jobs.submit(
                "media-scan",
                lambda stop, progress: media.scan(target, stop, progress),
                client_id=target,
            )
        }

    @app.get("/api/media/items/{identifier}")
    @needs(*WATCH)
    def detail(
        identifier: str,
        request: Request,
        client_id: str = "",
        episodes_offset: int = Query(0, ge=0),
        releases_offset: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=200),
    ):
        return media.detail(
            item(request, client_id, identifier),
            identifier,
            episodes_offset=episodes_offset,
            releases_offset=releases_offset,
            limit=limit,
            actor=actor(request),
        )

    @app.api_route("/api/media/items/{identifier}/stream", methods=["GET", "HEAD"])
    @needs(*WATCH)
    def stream(identifier: str, request: Request, client_id: str = ""):
        chosen = item(request, client_id, identifier)
        try:
            path = media.resolve(chosen, identifier)
        except (ValueError, OSError) as error:
            raise HTTPException(
                409, "Media is unavailable or unfinished. Refresh its details."
            ) from error
        # Starlette validates Range and serves 206/416 without loading the file into memory.
        import mimetypes

        return FileResponse(
            path,
            media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            headers={"Accept-Ranges": "bytes"},
        )

    @app.get("/api/media/items/{identifier}/playback")
    @needs(*WATCH)
    def playback_info(identifier: str, request: Request, client_id: str = ""):
        from torrentlinker.media_conversion import inspect

        chosen = item(request, client_id, identifier)
        return inspect(media.resolve(chosen, identifier))

    @app.get("/api/media/items/{identifier}/playback/stream")
    @needs(*WATCH)
    async def compatible_stream(
        identifier: str,
        request: Request,
        client_id: str = "",
        quality: Literal["360", "480", "720", "1080"] = "720",
        start: float = Query(0, ge=0, le=86400),
        audio: int = Query(0, ge=0, le=99),
        playback_id: str = Query(..., pattern=r"^[a-zA-Z0-9_-]{8,80}$"),
    ):
        import asyncio

        from torrentlinker.media_conversion import PlaybackChoice, inspect

        chosen = item(request, client_id, identifier)
        path = await asyncio.to_thread(media.resolve, chosen, identifier)
        facts = await asyncio.to_thread(inspect, path)
        found = actor(request)
        key = (found.account, found.viewer, chosen, identifier, playback_id)
        try:
            job = conversions.open(key, path, PlaybackChoice(quality, start, audio), facts)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

        async def content():
            try:
                while data := await asyncio.to_thread(job.read):
                    yield data
            finally:
                job.close()

        return StreamingResponse(
            content(), media_type="video/mp4", headers={"Cache-Control": "no-store"}
        )

    @app.delete("/api/media/items/{identifier}/playback/{playback_id}")
    @needs(*WATCH)
    def cancel_playback(identifier: str, playback_id: str, request: Request, client_id: str = ""):
        found = actor(request)
        chosen = target(request, client_id, identifier)
        conversions.cancel((found.account, found.viewer, chosen, identifier, playback_id))
        return {"ok": True}

    @app.post("/api/media/items/{identifier}/preview")
    @needs(*WATCH)
    def create_preview(identifier: str, body: MediaClient, request: Request):
        return media.create_preview(
            item(request, body.client_id, identifier),
            identifier,
            account=actor(request).account,
        )

    @app.delete("/api/media/previews/{preview_id}")
    @needs(*WATCH)
    def close_preview(preview_id: str, request: Request, client_id: str = ""):
        return media.close_preview(preview(request, client_id, preview_id), preview_id)

    @app.api_route("/api/media/previews/{preview_id}/stream", methods=["GET", "HEAD"])
    @needs(*WATCH)
    def preview_stream(preview_id: str, request: Request, client_id: str = ""):
        import mimetypes
        import re

        chosen = preview(request, client_id, preview_id)
        try:
            path, size = media.preview_source(chosen, preview_id)
        except (ValueError, OSError) as error:
            raise HTTPException(
                409, str(error) if isinstance(error, ValueError) else "Preview source unavailable."
            ) from error
        start, end, status = 0, size - 1, 200
        requested = request.headers.get("range", "")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            if match[1]:
                start = int(match[1])
                end = min(int(match[2]), size - 1) if match[2] else size - 1
            else:
                start = max(0, size - int(match[2]))
            if start > end or start >= size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            status = 206
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "X-Media-Preview": "verified-fixed-prefix",
        }
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        if request.method == "HEAD":
            return Response(
                status_code=status,
                headers=headers,
                media_type=mimetypes.guess_type(
                    path.stem if path.suffix.lower() == ".!qb" else path.name
                )[0]
                or "application/octet-stream",
            )

        def content():
            with path.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    block = source.read(min(65536, remaining))
                    if not block:
                        break
                    remaining -= len(block)
                    yield block

        return StreamingResponse(
            content(),
            status_code=status,
            headers=headers,
            media_type=mimetypes.guess_type(
                path.stem if path.suffix.lower() == ".!qb" else path.name
            )[0]
            or "application/octet-stream",
        )

    @app.get("/api/media/items/{identifier}/artwork")
    @needs(*WATCH)
    def artwork(identifier: str, request: Request, client_id: str = ""):
        if not identifier.startswith("tracker-"):
            client_id = item(request, client_id, identifier)
        elif not media.sees_tracker(actor(request)):
            raise HTTPException(404, "Artwork unavailable.")
        else:
            client_id = target(request, client_id)
        try:
            path = media.artwork(client_id, identifier)
            if path is None:
                raise ValueError("Artwork unavailable.")
            return FileResponse(path)
        except (OSError, ValueError) as error:
            raise HTTPException(404, "Artwork unavailable.") from error

    @app.get("/api/media/items/{identifier}/subtitles/{subtitle_id}")
    @needs(*WATCH)
    def subtitles(identifier: str, subtitle_id: str, request: Request, client_id: str = ""):
        chosen = item(request, client_id, identifier)
        try:
            data, mime = media.subtitle(chosen, identifier, subtitle_id)
            return Response(data, media_type=mime)
        except (OSError, ValueError) as error:
            raise HTTPException(404, "Subtitle unavailable.") from error

    @app.post("/api/media/items/{identifier}/forget-progress")
    @needs(*WATCH)
    def forget_progress(identifier: str, body: MediaClient, request: Request):
        chosen = item(request, body.client_id, identifier)
        media.forget_progress(chosen, identifier, **who(request))
        return {"ok": True}

    @app.post("/api/media/items/{identifier}/watched")
    @needs(*WATCH)
    def watched(identifier: str, body: Watched, request: Request):
        chosen = item(request, body.client_id, identifier)
        return media.watched(chosen, identifier, body.watched, **who(request))

    @app.get("/api/media/playlists")
    @needs(*WATCH)
    def playlists(request: Request, client_id: str = ""):
        chosen, found = target(request, client_id), actor(request)
        rows = media.playlists(chosen, **who(request))
        if found.owner:
            return rows
        # What became hidden since it was added leaves the Member's playlist.
        kept = media.visible_ids(chosen, found)
        return [{**r, "media_ids": [i for i in r["media_ids"] if i in kept]} for r in rows]

    @app.post("/api/media/playlists")
    @needs(*WATCH)
    def save_playlist(body: PlaylistSave, request: Request):
        watchable(request, body.media_ids)
        return media.save_playlist(
            target(request, body.client_id), body.name, body.media_ids, body.id, **who(request)
        )

    @app.delete("/api/media/playlists/{identifier}")
    @needs(*WATCH)
    def delete_playlist(identifier: str, request: Request, client_id: str = ""):
        return media.delete_playlist(target(request, client_id), identifier, **who(request))

    @app.post("/api/media/sessions")
    @needs(*WATCH)
    def open_session(body: SessionOpen, request: Request):
        return media.open_session(target(request, body.client_id), body.platform, **who(request))

    @app.post("/api/media/sessions/{identifier}")
    @needs(*WATCH)
    def session(identifier: str, body: SessionUpdate, request: Request):
        found = actor(request)
        if not found.owner:
            try:
                opened = media.session_record(identifier, body.token)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            if (opened["account"], opened["viewer"]) != (found.account, found.viewer):
                raise HTTPException(400, "Player session unavailable for this instance.")
            report = body.report or {}
            watchable(request, [*(body.media_ids or ()), *(report.get("queue") or ())])
            if report.get("current_id"):
                watchable(request, [report["current_id"]])
        return media.session(identifier, **body.model_dump(exclude_none=True))

    @app.post("/api/media/sessions/{identifier}/chat")
    def chat(identifier: str, body: MediaChat):
        return assistant.media_chat(identifier, body.token, body.conversation_id, new=body.new)
