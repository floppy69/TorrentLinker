"""Authenticated owner controls; companion writes use a separate, narrow capability."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from torrentlinker.community import message_library
from torrentlinker.companion_downloads import MAX_RESULT
from torrentlinker.domain import Torrent
from torrentlinker.profile import ProfileError
from torrentlinker.profile_history import active_seeds
from torrentlinker.profile_overview import PERIODS, overview, torrent_clients_overview
from torrentlinker.profile_workspace import extension_origin
from torrentlinker.web.setup import Setup


async def companion_request(request: Request, route: str, setup: Setup) -> Response:
    origin = request.headers.get("origin", "")
    if not extension_origin(origin):
        return JSONResponse({"detail": "Use the paired browser extension."}, status_code=403)
    headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin", "Cache-Control": "no-store"}
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                **headers,
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "content-type, authorization",
            },
        )
    if request.method != "POST":
        return JSONResponse({"detail": "POST required."}, status_code=405, headers=headers)
    try:
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > (MAX_RESULT if route == "/api/companion/result" else 65536):
                raise ValueError("Request too large.")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("Invalid JSON object.")
        workspace = setup.profile_workspace()
        result = workspace.receive(route, origin, request.headers.get("authorization", ""), body)
        return JSONResponse(result, headers=headers)
    except PermissionError as error:
        return JSONResponse({"detail": str(error)}, status_code=403, headers=headers)
    except (ValueError, UnicodeError):
        return JSONResponse(
            {"detail": "Invalid or expired snapshot. Read a new preview."},
            status_code=400,
            headers=headers,
        )


class DownloadTest(BaseModel):
    infohash: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")


class SessionDownloads(BaseModel):
    enabled: bool


TorrentClients = Callable[[], list[tuple[str, Callable[[], list[Torrent]]]]]
Period = Query(30, description="Days of Profile history: 7, 30, 90 or 0 for all.")


def profile_routes(app: FastAPI, setup: Setup, torrent_clients: TorrentClients) -> None:
    def with_overview(days: int) -> dict[str, Any]:
        """The workspace state plus the Profile overview for a period of history."""
        if days not in PERIODS:
            raise HTTPException(400, "Choose 7, 30, 90 or 0 days.")
        workspace = setup.profile_workspace()
        state = workspace.state()
        return {**state, "overview": overview(state, workspace.history_days(), days, date.today())}

    @app.get("/api/community")
    def community_state():
        try:
            return setup.profile_workspace().community_state()
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/community/messages")
    def community_messages():
        return {"entries": message_library()}

    @app.post("/api/community/{operation}")
    def community_update(operation: str, body: dict[str, Any]):
        try:
            return setup.profile_workspace().community_update(operation, body)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/zen/profile/session-downloads")
    def session_downloads(body: SessionDownloads, days: int = Period):
        workspace = setup.profile_workspace()
        try:
            workspace.set_session_downloads(body.enabled)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return with_overview(days)

    @app.get("/api/zen/profile/avatar")
    def avatar() -> Response:
        """The account's cached avatar, so the page never contacts the image host."""
        image = setup.profile_workspace().avatar()
        if image is None:
            raise HTTPException(404, "No avatar.")
        return Response(
            image[0],
            media_type=image[1],
            headers={"Cache-Control": "private, max-age=86400", "Content-Disposition": "inline"},
        )

    @app.get("/api/zen/profile/torrent-clients")
    def profile_torrent_clients() -> dict[str, Any]:
        """Seeding per Torrent Client against c411, and today's Zen Estimate."""
        settings = setup.settings
        return torrent_clients_overview(
            settings.zen,
            torrent_clients(),
            settings.indexer.url,
            active_seeds(setup.profile_workspace().state().get("companion")),
            settings.uploads,
        )

    @app.post("/api/zen/profile/download-tests")
    def test_download(body: DownloadTest):
        try:
            return setup.profile_workspace().test_download(body.infohash, body.request_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/zen/profile/download-tests/{identifier}")
    def download_test(identifier: str):
        try:
            return setup.profile_workspace().download_test(identifier)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/api/zen/profile")
    def state(days: int = Period):  # type: ignore[no-untyped-def]
        return with_overview(days)

    @app.post("/api/zen/profile/refresh")
    def refresh(days: int = Period):  # type: ignore[no-untyped-def]
        workspace = setup.profile_workspace()
        try:
            profile = workspace.refresh(
                setup.settings.indexer.url, setup.secrets.get("indexer-api-key")
            )
            setup.settings.zen = profile.apply(setup.settings.zen)
            setup.save()
        except ProfileError:
            pass  # Typed error is shown next to the last successful API data.
        return with_overview(days)

    @app.post("/api/zen/profile/pairing")
    def pairing():  # type: ignore[no-untyped-def]
        try:
            return setup.profile_workspace().pairing()
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/zen/profile/disconnect")
    def disconnect(days: int = Period):  # type: ignore[no-untyped-def]
        setup.profile_workspace().disconnect()
        return with_overview(days)

    @app.get("/api/zen/profile/extension")
    def extension(request: Request) -> Response:
        from torrentlinker.companion import extension_zip

        return Response(
            extension_zip(str(request.base_url)),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="torrentlinker-companion.zip"'},
        )

    @app.get("/companion/connect")
    @app.get("/companion/connect.js")
    @app.get("/companion/connect.css")
    def connect_page(request: Request) -> Response:
        from torrentlinker.companion import connection_asset

        path = "/companion/" + request.url.path.rsplit("/", 1)[-1]
        asset = connection_asset(path)
        assert asset is not None
        raw, kind = asset
        return Response(
            raw,
            media_type=kind,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
