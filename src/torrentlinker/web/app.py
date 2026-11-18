"""Authenticated HTTP adapter for the headless application."""

from __future__ import annotations

import threading
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import asdict
from functools import partial
from html import escape
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from torrentlinker import documentation
from torrentlinker.clients import connect
from torrentlinker.diagnostics import build_report, report_json
from torrentlinker.domain import Torrent
from torrentlinker.torrent_management import peer_count_order, tracker_group
from torrentlinker.updates import installed_version
from torrentlinker.web.confirmations import Confirmations
from torrentlinker.web.documentation import render
from torrentlinker.web.jobs import Jobs
from torrentlinker.web.operations import DownloadFolderRequired, JobRequest, Operations
from torrentlinker.web.security import ServerSecrets, Sessions, TrustedProxies
from torrentlinker.web.setup import (
    Connection,
    Connector,
    FolderRemoval,
    FolderSetup,
    IndexerConnection,
    PartialNamesRefused,
    ProxySetup,
    Setup,
)
from torrentlinker.web.zen_preferences import ZenPreferences


class ClientSelection(BaseModel):
    client_id: str = ""


class ReseedFolder(ClientSelection):
    path: str = Field(default="", max_length=4096)


class Announce(BaseModel):
    value: str = Field(max_length=4096)


class SequentialVideo(BaseModel):
    enabled: bool


class Login(BaseModel):
    password: str = Field(max_length=1024)


def create_app(
    directory: Path,
    *,
    password: str | None,
    trusted_proxies: tuple[IPv4Network | IPv6Network, ...] = (),
    roots: tuple[Path, ...] = (),
    connector: Connector = connect,
    secret_files: dict[str, Path] | None = None,
    secure_cookie: bool = False,
    service_override: Setup | None = None,
    operation_factory=Operations,
    monitor_verifications: bool = True,
    assistant_transport=None,
) -> FastAPI:
    app_version = escape(installed_version())
    directory.mkdir(parents=True, exist_ok=True)
    # Exactly one owner check: the Web UI password, or the reverse proxy's networks.
    if (password is None) == (not trusted_proxies):
        raise ValueError("Set a Web UI password or trusted proxies, not both.")
    sessions = Sessions(password) if password is not None else None
    if sessions is None:
        proxies = TrustedProxies(trusted_proxies)

        def signed_in(request: Request) -> bool:
            return proxies.allows(request.client.host if request.client else None)

    else:

        def signed_in(request: Request) -> bool:
            return sessions.valid(request.cookies.get("tl_session", ""))

    def sign_in_required() -> JSONResponse:
        if sessions is None:
            return JSONResponse(
                {"detail": "Open TorrentLinker through its reverse proxy."}, status_code=403
            )
        return JSONResponse({"detail": "Sign in to TorrentLinker."}, status_code=401)

    service = service_override or Setup(
        directory, roots, ServerSecrets(directory, secret_files), connector
    )

    def error_message(error: Exception) -> str:
        if isinstance(error, ValueError):
            return service.secrets.redact(str(error))
        kind = type(error).__name__.lower()
        if "timeout" in kind or "connection" in kind or "connect" in kind:
            return (
                "Cannot reach the service from this server. Check its address, "
                "port, network and proxy settings."
            )
        if any(word in kind for word in ("login", "forbidden", "unauthorized", "keyrefused")):
            return (
                "The service refused authentication. Check the username, password "
                "or API key permissions."
            )
        return (
            "Operation failed. Check the connection, folder permissions and "
            "available space before retrying."
        )

    jobs = Jobs(directory, error_message)
    operations = operation_factory(service)
    confirmations = Confirmations(service)
    client_operations: dict[str, Operations] = {}
    client_confirmations: dict[str, Confirmations] = {}

    def for_client(identifier: str = "") -> Operations:
        identifier = identifier or service.settings.default_client_id
        service.settings.profile(identifier)
        if identifier == service.settings.active_client_id:
            return operations
        if identifier not in client_operations:
            client_operations[identifier] = operation_factory(service.for_client(identifier))
        target = client_operations[identifier]
        target.setup.settings = service.settings.for_client(identifier)
        return target

    def consent(identifier: str) -> Confirmations:
        target = for_client(identifier)
        if target is operations:
            return confirmations
        if identifier not in client_confirmations:
            client_confirmations[identifier] = Confirmations(target.setup)
        return client_confirmations[identifier]

    def reset_clients() -> None:
        nonlocal operations, confirmations
        operations = operation_factory(service)
        confirmations = Confirmations(service)
        client_operations.clear()
        client_confirmations.clear()

    shutdown = threading.Event()
    verification_cursor = 0

    def verify_loop() -> None:
        nonlocal verification_cursor
        while not shutdown.wait(10):
            with jobs.lock:
                if service.configured and not jobs.active():
                    profiles = service.settings.client_profiles
                    start = verification_cursor % len(profiles)
                    for offset in range(len(profiles)):
                        position = (start + offset) % len(profiles)
                        profile = profiles[position]
                        if (
                            profile.enabled
                            and service.store.for_client(profile.id).verification_hashes()
                        ):
                            target = for_client(profile.id)
                            jobs.submit(
                                "verify",
                                lambda stop, progress, target=target: target.run(  # type: ignore[misc]
                                    JobRequest(
                                        kind="verify",
                                        client_id=target.setup.settings.active_client_id,
                                    ),
                                    stop,
                                    progress,
                                ),
                                client_id=profile.id,
                            )
                            verification_cursor = position + 1
                            break

    def history_loop() -> None:
        """Refresh the profile hourly so Profile history has a row on days nobody opens it."""
        from torrentlinker.profile import ProfileError

        while not shutdown.wait(60):
            key = service.secrets.get("indexer-api-key")
            if not service.configured or not key:
                continue
            workspace = service.profile_workspace()
            if time.time() >= workspace.state()["refresh_after"] + 3480:  # an hour since
                try:
                    workspace.refresh(service.settings.indexer.url, key)
                except ProfileError:
                    pass  # recorded in the history as the day's failure

    def catalogue_loop() -> None:
        """Every few hours, the newest torrents of every category, as on the desktop."""
        from torrentlinker.catalogue_sync import refresh_catalogue, refresh_due

        while not shutdown.wait(600):
            if not service.configured or not service.secrets.get("indexer-api-key"):
                continue
            with jobs.lock:
                if jobs.active() or not refresh_due(service.store):
                    continue
                jobs.submit(
                    "catalogue",
                    lambda stop, progress: refresh_catalogue(
                        service.indexer(),
                        service.store,
                        service.settings.indexer_categories,
                        stop=stop.is_set,
                        progress=lambda p: progress({"phase": "fetching", **asdict(p)}),
                    ),
                    # This refresh only fetches new releases; a manual Catalogue
                    # job also fetches history and must remain separate.
                    parameters={"refresh_newest": True},
                )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        monitor = threading.Thread(target=verify_loop, daemon=True, name="verification-monitor")
        if monitor_verifications:
            monitor.start()
        threading.Thread(target=history_loop, daemon=True, name="profile-history").start()
        if monitor_verifications:
            threading.Thread(target=catalogue_loop, daemon=True, name="catalogue-refresh").start()
        assistant.start_scheduler()
        agent_service.feed_control.start()
        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            shutdown.set()
            if monitor_verifications:
                monitor.join(timeout=2)
            agent_service.feed_control.close()
            assistant.close()
            jobs.close()
            agent_service.media.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    from torrentlinker.agent.access import Access
    from torrentlinker.agent.routes import owner_routes

    agent_access = Access(directory)
    from torrentlinker.agent.server import make_server
    from torrentlinker.agent.service import AgentService

    agent_service = AgentService(agent_access, service, jobs, for_client)
    mcp_server, mcp_app = make_server(agent_service)
    app.mount("/mcp", mcp_app)
    owner_routes(app, agent_access, service, agent_service)
    from torrentlinker.assistant.routes import routes as assistant_routes
    from torrentlinker.assistant.service import Assistant

    assistant = Assistant(directory, agent_service, mcp_server, assistant_transport)
    assistant_routes(app, assistant)
    app.state.assistant = assistant
    app.state.agent_service = agent_service
    from torrentlinker.web.feeds import feed_routes

    feed_routes(app, agent_service)
    from torrentlinker.web.media import media_routes

    media_routes(app, agent_service, assistant)
    app.state.reset_clients = reset_clients
    from torrentlinker.profile_workspace import COMPANION_ROUTES
    from torrentlinker.web.profile import companion_request, profile_routes

    def client_torrents(identifier: str) -> list[Torrent]:
        return for_client(identifier).setup.client().torrents(with_files=False)

    profile_routes(
        app,
        service,
        lambda: [
            (p.name, partial(client_torrents, p.id))
            for p in service.settings.client_profiles
            if p.enabled
        ],
    )

    def idle() -> None:
        if jobs.active():
            raise HTTPException(409, "Wait for active jobs before changing settings.")

    @app.middleware("http")
    async def protect(request: Request, call_next):  # type: ignore[no-untyped-def]
        # ASGI root_path may prefix the URL behind a reverse proxy.
        route = request.scope.get("path", request.url.path)
        prefix = request.scope.get("root_path", "")
        if prefix and route.startswith(prefix + "/"):
            route = route[len(prefix) :]
        if route in COMPANION_ROUTES:
            return await companion_request(request, route, service)
        if route.startswith("/documentation/") and not signed_in(request):
            return sign_in_required()
        if route.startswith("/api/"):
            length = request.headers.get("content-length", "0")
            limit = 12_000_000 if route in {"/api/jobs", "/api/zen/plan/review"} else 256_000
            if not length.isdigit() or int(length) > limit:
                return JSONResponse({"detail": "Request too large."}, status_code=413)
            if request.method != "GET" and request.headers.get("X-TorrentLinker") != "1":
                return JSONResponse({"detail": "Browser request header required."}, status_code=403)
            if route != "/api/login" and not signed_in(request):
                return sign_in_required()
        try:
            response = await call_next(request)
        except Exception as error:
            # Do not let ASGI log a raw HTTP exception containing private URLs.
            response = JSONResponse({"detail": error_message(error)}, status_code=502)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if route in {
            "/static/community/view.html",
            "/static/reseed/view.html",
            "/static/upload/view.html",
            "/static/profile/view.html",
        }:
            # This bundled component may be embedded only by our own Web UI.
            # Other pages remain unframeable; the component has no network access.
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                + (
                    "img-src data:; "
                    if route == "/static/profile/view.html"
                    else "img-src 'self'; "
                )
                + "frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        # Pydantic's default response echoes inputs, including passwords.
        return JSONResponse(
            {"detail": "Invalid input. Check the required fields and their values."},
            status_code=422,
        )

    @app.post("/api/login")
    def login(body: Login) -> JSONResponse:
        if sessions is None:
            return JSONResponse({"detail": "The reverse proxy signs users in."}, status_code=404)
        try:
            token = sessions.login(body.password)
        except PermissionError as error:
            return JSONResponse({"detail": str(error)}, status_code=401)
        except ValueError as error:
            return JSONResponse({"detail": str(error)}, status_code=429)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            "tl_session",
            token,
            httponly=True,
            samesite="strict",
            max_age=43200,
            secure=secure_cookie,
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request) -> JSONResponse:
        if sessions is not None:
            sessions.logout(request.cookies.get("tl_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("tl_session")
        return response

    @app.get("/api/documentation")
    def documentation_index(language: str = "en") -> list[dict[str, str]]:
        return documentation.guides(language)

    @app.get("/documentation/{name:path}", response_class=HTMLResponse)
    def documentation_reference(name: str, request: Request) -> HTMLResponse:
        if name not in {
            g["path"] for language in ("en", "fr") for g in documentation.guides(language)
        }:
            raise HTTPException(404, "Guide unavailable.")
        try:
            html = render(name, standalone=True, root_path=request.scope.get("root_path", ""))
        except (ValueError, OSError) as error:
            raise HTTPException(404, "Guide unavailable.") from error
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width">'
            f"<title>TorrentLinker {app_version} documentation</title><main>" + html + "</main>"
        )

    @app.get("/api/documentation/page/{name:path}")
    def documentation_page(name: str) -> dict[str, str]:
        try:
            return {"html": render(name)}
        except (ValueError, OSError) as error:
            raise HTTPException(404, "Guide unavailable.") from error

    @app.get("/api/documentation/file/{name:path}")
    def documentation_file(name: str) -> FileResponse:
        try:
            path = documentation.document_path(name)
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                raise ValueError("Not an image.")
            return FileResponse(path)
        except (ValueError, OSError) as error:
            raise HTTPException(404, "Image unavailable.") from error

    @app.get("/api/setup")
    def setup(client_id: str = "") -> dict:
        snapshot = for_client(client_id).setup.snapshot()
        return {**snapshot, "web_auth": "password" if sessions is not None else "proxy"}

    @app.get("/api/diagnostics")
    def diagnostics() -> Response:
        with service.lock:
            report = build_report(service.settings, service.store, jobs)
        return Response(
            report_json(report),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="torrentlinker-diagnostics.json"',
            },
        )

    @app.exception_handler(PartialNamesRefused)
    async def partial_names(request: Request, error: PartialNamesRefused) -> JSONResponse:
        # The form offers to turn the option off and try again.
        return JSONResponse({"detail": str(error), "action": error.action}, status_code=409)

    @app.exception_handler(ValueError)
    async def bad_input(request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse({"detail": error_message(error)}, status_code=400)

    @app.exception_handler(DownloadFolderRequired)
    async def plan_folder_required(request: Request, error: DownloadFolderRequired) -> JSONResponse:
        return JSONResponse(
            {
                "detail": str(error),
                "action": {
                    "kind": "plan-folder",
                    "client_id": error.client_id,
                    "category": error.category,
                },
            },
            status_code=400,
        )

    @app.exception_handler(Exception)
    async def failed(request: Request, error: Exception) -> JSONResponse:
        # Adapter exceptions can contain private URLs and passwords.
        return JSONResponse(
            {
                "detail": error_message(error),
                "kind": type(error).__name__,
            },
            status_code=502,
        )

    @app.post("/api/setup/test-client")
    def test_client(body: Connection) -> dict:
        return for_client(body.client_id).setup.test_client(body)

    @app.post("/api/setup/client")
    def save_client(body: Connection) -> dict:
        nonlocal operations
        with jobs.lock:
            idle()
            target = for_client(body.client_id)
            old = target.setup.snapshot()
            saved = target.setup.test_client(body, save=True)
            if old["client"] != body.client or old["host"] != body.host:
                target.rows.clear()
                target.library.entries.clear()
            return saved

    @app.post("/api/clients")
    def add_client(body: Connection) -> dict:
        with jobs.lock:
            idle()
            if not body.name.strip():
                raise ValueError("Enter a name for this Torrent Client.")
            profile = service.settings.add_client(body.name, body.client)
            try:
                target = service.for_client(profile.id)
                result = target.test_client(body, save=True)
                service.configured = True
            except Exception:
                service.settings.client_profiles.remove(profile)
                raise
            return {**result, "client_id": profile.id}

    @app.post("/api/clients/default")
    def default_client(body: ClientSelection) -> dict:
        with jobs.lock:
            idle()
            service.settings.profile(body.client_id)
            service.settings.default_client_id = body.client_id
            service.save()
        return {"ok": True}

    @app.post("/api/clients/remove")
    def remove_client(body: ClientSelection) -> dict:
        from torrentlinker.client_profiles import pending_work

        with jobs.lock:
            idle()
            profile = service.settings.profile(body.client_id)
            if len(service.settings.client_profiles) == 1 or pending_work(
                service.settings, service.store, profile.id
            ):
                raise ValueError("This client has pending work or is the only configured client.")
            remaining = [p for p in service.settings.client_profiles if p.id != profile.id]
            if service.settings.active_client_id == profile.id:
                service.settings.select_client(remaining[0].id)
                service.store = service.store.for_client(remaining[0].id)
                service._client = None
            service.settings.client_profiles = remaining
            if service.settings.default_client_id == profile.id:
                service.settings.default_client_id = remaining[0].id
            service.save()
            reset_clients()
        return {"ok": True}

    @app.post("/api/setup/test-indexer")
    def test_indexer(body: IndexerConnection) -> dict:
        return service.test_indexer(body)

    @app.post("/api/setup/indexer")
    def save_indexer(body: IndexerConnection) -> dict:
        with jobs.lock:
            idle()
            result = service.test_indexer(body, save=True)
            reset_clients()
            return result

    @app.get("/api/folders")
    def folders(path: str = "") -> dict:
        return service.browse(path)

    @app.post("/api/setup/reseed-folder")
    def save_reseed_folder(body: ReseedFolder) -> dict:
        with jobs.lock:
            idle()
            setup = for_client(body.client_id).setup
            value = body.path.strip()
            path = str(setup.path_under_root(value)) if value else ""
            setup.settings.profile().reseed_link_root = path
            setup.save()
            return {"reseed_link_root": path}

    @app.post("/api/setup/preview-folder")
    def preview_folder(body: FolderSetup) -> dict:
        return for_client(body.client_id).setup.preview_folder(body)

    @app.post("/api/setup/test-folder")
    def test_folder(body: FolderSetup) -> dict:
        return for_client(body.client_id).setup.folder(body, probe=True)

    @app.post("/api/setup/folder")
    def save_folder(body: FolderSetup) -> dict:
        with jobs.lock:
            idle()
            target = for_client(body.client_id)
            result = target.setup.folder(body, save=True)
            # Adding a folder keeps the successful scans of all other folders.
            for operation in [operations, *client_operations.values()]:
                valid = {f.path for f in service.settings.library_folders}
                operation.library.entries[:] = [
                    e for e in operation.library.entries if e.folder.path in valid
                ]
            return result

    @app.post("/api/setup/remove-folder")
    def remove_folder(body: FolderRemoval) -> dict:
        with jobs.lock:
            idle()
            target = for_client(body.client_id)
            if target.setup.store.verification_hashes():
                raise HTTPException(
                    409, "Finish pending Reseed Verifications before removing folders."
                )
            target.setup.remove_folder(body)
            if body.purpose == "library":
                for operation in [operations, *client_operations.values()]:
                    operation.library.entries[:] = [
                        e for e in operation.library.entries if str(e.folder.path) != body.local
                    ]
        return {"ok": True}

    @app.post("/api/setup/suggest-mappings")
    def suggest_mappings(body: ClientSelection) -> dict:
        with jobs.lock:
            idle()
            return for_client(body.client_id).setup.suggest_mappings()

    @app.post("/api/setup/proxy")
    def save_proxy(body: ProxySetup) -> dict:
        with jobs.lock:
            idle()
            result = service.proxy(body)
            reset_clients()
            return result

    @app.post("/api/setup/sequential-video")
    def save_sequential_video(body: SequentialVideo) -> dict:
        with jobs.lock:
            service.set_sequential_video(body.enabled)
            return {"ok": True}

    @app.post("/api/setup/adult-content")
    def save_adult_content(body: SequentialVideo) -> dict:
        with jobs.lock:
            service.set_adult_content(body.enabled)
            return {"ok": True}

    @app.post("/api/setup/announce")
    def save_announce(body: Announce) -> dict:
        parsed = urlsplit(body.value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise HTTPException(400, "Use the private Announce URL supplied by c411.")
        with jobs.lock:
            idle()
            service.secrets.update({"announce-url": body.value})
        return {"ok": True}

    @app.post("/api/upload/workspace/{action}")
    def upload_workspace(action: str, body: dict, client_id: str = "") -> dict | list:
        from torrentlinker.upload_workspace import UploadWorkspace

        try:
            return UploadWorkspace(for_client(client_id).uploads).request(action, body)
        except (ValueError, KeyError) as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/upload/categories")
    def upload_categories() -> list:
        from torrentlinker.upload import PROFILES, category_name

        return [{"id": cid, "name": category_name(cid)} for cid in PROFILES]

    @app.get("/api/upload/drafts")
    def upload_drafts(client_id: str = "") -> list:
        return for_client(client_id).setup.indexer().drafts()

    @app.get("/api/upload/queue")
    def upload_queue(client_id: str = "") -> list:
        return for_client(client_id).setup.store.local_drafts()

    @app.get("/api/upload/queue/{identifier}/preview")
    def upload_queue_preview(
        identifier: str, revision: int = Query(ge=1), client_id: str = ""
    ) -> dict:
        from torrentlinker.agent.upload_presentations import draft_item

        store = for_client(client_id).setup.store
        try:
            draft = store.local_draft(identifier)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        if draft["revision"] != revision:
            raise HTTPException(409, "Draft changed. Refresh the queue and preview it again.")
        return draft_item(draft, "0", store)

    @app.get("/api/library")
    def library(
        client_id: str = "",
        q: str = "",
        folder: str = "",
        state: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
    ) -> dict:
        rows = [
            r
            for r in for_client(client_id).library.rows()
            if q.casefold() in r["name"].casefold()
            and (not folder or r["folder"] == folder)
            and (not state or r["state"] == state)
        ]
        from collections import Counter

        library = for_client(client_id).library
        counts = Counter(str(entry.folder.path) for entry in library.entries)
        return {
            "rows": rows[offset : offset + limit],
            "total": len(rows),
            "folder_counts": counts,
            "folder_errors": [str(error.path) for error in library.folder_errors],
        }

    @app.get("/api/reseed-workspace")
    def reseed_workspace(client_id: str = "") -> dict:
        target = for_client(client_id)
        return {
            "rows": target.reseed_workspace.rows(),
            "folder_errors": [str(e.path) for e in target.library.folder_errors],
            "link_root": target.setup.settings.profile().reseed_link_root,
            "paused_paths": sorted(target.reseed_workspace.paused_paths()),
        }

    @app.post("/api/reseed-workspace/control")
    def control_reseed(body: dict, client_id: str = "") -> dict:
        target = for_client(client_id).reseed_workspace
        paths = body.get("paths", [])
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ValueError("Select Local Items first.")
        if body.get("action") == "enqueue":
            target.enqueue(paths, body.get("key", ""))
        elif body.get("action") == "scan":
            target.request_scan(body.get("folders"))
        elif body.get("action") == "pause-item":
            target.control(paths, paused=bool(body.get("paused")))
        else:
            raise ValueError("Unknown reseed operation.")
        return {"paused_paths": sorted(target.paused_paths())}

    from torrentlinker.poster_cache import PosterCache, valid_poster_url

    posters = PosterCache(directory / "posters")

    @app.get("/api/poster")
    def poster(url: str = Query("", max_length=300)) -> Response:
        # The browser may not load TMDB images itself (the page's CSP, and TMDB would see the
        # visitor's address). The server fetches only TMDB poster URLs, bounded and cached.
        if not valid_poster_url(url):
            raise HTTPException(404, "No poster.")
        data = posters.fetch(url)
        if data is None:
            raise HTTPException(404, "No poster.")
        kind = (
            "image/png"
            if data[:4] == b"\x89PNG"
            else "image/webp"
            if data[8:12] == b"WEBP"
            else "image/jpeg"
        )
        return Response(data, media_type=kind)

    @app.get("/api/queue")
    def queue(client_id: str = "") -> list:
        if client_id == "all":
            return [
                row for p in service.settings.client_profiles for row in for_client(p.id).queue()
            ]
        return for_client(client_id).queue()

    @app.post("/api/queue/retry")
    def retry_queue(keys: list[str]) -> dict:
        from torrentlinker.download_queue import entries

        with jobs.lock:
            idle()
            selected = set(keys[:1000])
            for entry in entries(service.store, all_clients=True):
                if entry.key in selected and (
                    entry.status == "refused" or (entry.status == "failed" and entry.retry_safe)
                ):
                    service.store.download_outcome(entry.key, "queued")
        return {"ok": True}

    @app.post("/api/queue/remove")
    def remove_queue(keys: list[str]) -> dict:
        with jobs.lock:
            idle()
            service.store.remove_downloads(keys[:1000])
        return {"ok": True}

    @app.get("/api/zen/catalogue")
    def zen_catalogue() -> dict:
        from torrentlinker.web.planning import catalogue_status

        return catalogue_status(service)

    @app.get("/api/zen/plan")
    def zen_plan(client_id: str = "") -> dict:
        with jobs.lock:
            return for_client(client_id).planner.read()

    @app.get("/api/zen/preferences")
    def zen_preferences() -> dict:
        from torrentlinker.web.zen_preferences import snapshot

        return snapshot(service.settings)

    @app.post("/api/zen/plan/review")
    def review_zen_plan(body: JobRequest) -> dict:
        with jobs.lock:
            idle()
            return for_client(body.client_id).planner.review(
                body.plan_id,
                body.plan_selection or body.hashes,
            )

    @app.post("/api/zen/preferences")
    def save_zen_preferences(body: ZenPreferences) -> dict:
        with jobs.lock:
            idle()
            body.apply(service.settings)
            service.save()
            if body.model_fields_set - {"uploads", "download_speed"}:
                for profile in service.settings.client_profiles:
                    for_client(profile.id).planner.clear()
            return zen_preferences()

    @app.get("/api/zen/seeding")
    def zen_seeding(
        client_id: str = "",
        q: str = "",
        group: str = "",
        sort: Literal["name", "size", "seeders", "seed_days", "zen", "note"] = "zen",
        descending: bool = True,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
    ) -> dict:
        from torrentlinker.seeding import combined_seeding
        from torrentlinker.web.seeding import seeding_page

        targets = (
            [for_client(p.id) for p in service.settings.client_profiles if p.enabled]
            if client_id == "all"
            else [for_client(client_id)]
        )
        observed = [t for target in targets for t in target.observed]
        settings = service.settings
        view = combined_seeding(
            settings.zen,
            observed,
            settings.indexer.url,
            settings.uploads,
            catalogue={
                r.infohash: r for r in service.store.catalogue([t.hash.lower() for t in observed])
            },
            categories=settings.indexer_categories,
        )
        result = seeding_page(
            view,
            settings.zen,
            settings.uploads,
            query=q,
            group=group,
            sort=sort,
            descending=descending,
            offset=offset,
            limit=limit,
        )
        result["client_errors"] = [
            {"name": target.setup.settings.profile().name, "message": target.connection_error}
            for target in targets
            if target.connection_error
        ]
        return result

    @app.get("/api/torrents")
    def torrents(
        client_id: str = "",
        q: str = "",
        sort: str = "name",
        descending: bool = False,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
        tracker: str = "",
        state: str = "",
        category: str = "",
        tag: str = "",
    ) -> dict:
        targets = (
            [for_client(p.id) for p in service.settings.client_profiles if p.enabled]
            if client_id == "all"
            else [for_client(client_id)]
        )
        from torrentlinker.seeding import combined_seeding

        observed = [t for target in targets for t in target.observed]
        combined = combined_seeding(
            service.settings.zen,
            observed,
            service.settings.indexer.url,
            catalogue={
                r.infohash: r for r in service.store.catalogue([t.hash.lower() for t in observed])
            },
        )
        combined_zen = {
            "count": combined.count,
            "daily": combined.day.total,
            "paid": combined.day.paid,
        }
        all_rows = [r for target in targets for r in target.rows]
        rows = [
            r
            for r in all_rows
            if q.casefold() in r["name"].casefold()
            and (
                not tracker
                or any(tracker_group(tracker) == tracker_group(host) for host in r["trackers"])
            )
            and (not state or r["status"] == state)
            and (not category or any(category == " / ".join(c) for c in r["categories"]))
            and (not tag or tag in r["tags"])
        ]
        if sort not in {
            "name",
            "client_name",
            "status",
            "size",
            "progress",
            "download",
            "upload",
            "ratio",
            "seeds",
            "peers",
            "zen",
            "note",
        }:
            raise HTTPException(400, "Unknown sort column.")

        def sort_value(row):
            if sort in {"seeds", "peers"}:
                return peer_count_order(row[sort], row.get("total_" + sort, -1))
            return row[sort]

        rows.sort(
            key=lambda r: (
                sort_value(r) is None,
                sort_value(r).casefold() if isinstance(sort_value(r), str) else sort_value(r) or 0,
            ),
            reverse=descending,
        )
        return {
            "rows": rows[offset : offset + limit],
            "total": len(rows),
            "zen": combined_zen,
            "client_errors": [
                {"name": t.setup.settings.profile().name, "message": t.connection_error}
                for t in targets
                if t.connection_error
            ],
            "trackers": sorted({tracker_group(h) for r in all_rows for h in r["trackers"] if h}),
            "categories": sorted({" / ".join(c) for r in all_rows for c in r["categories"] if c}),
            "tags": sorted({t for r in all_rows for t in r["tags"]}),
            "counts": {
                "status": dict(Counter(r["status"] for r in all_rows)),
                "tags": dict(Counter(t for r in all_rows for t in r["tags"])),
                "trackers": dict(
                    Counter(
                        g for r in all_rows for g in {tracker_group(h) for h in r["trackers"] if h}
                    )
                ),
                "categories": dict(
                    Counter(" / ".join(c) for r in all_rows for c in r["categories"] if c)
                ),
                "all": len(all_rows),
            },
        }

    @app.get("/api/torrents/{infohash}/files")
    def torrent_files(infohash: str, client_id: str = "") -> list:
        """The file list of one torrent, for the Files tab under the Torrents table."""
        if len(infohash) != 40 or any(c not in "0123456789abcdefABCDEF" for c in infohash):
            raise HTTPException(400, "Invalid torrent hash.")
        found = for_client(client_id).setup.client().file_listing(infohash.lower())
        return [
            {"index": f.index, "name": f.name, "size": f.size, "wanted": f.wanted} for f in found
        ]

    @app.post("/api/jobs", status_code=202)
    def start_job(body: JobRequest) -> dict:
        with jobs.lock:
            if body.client_id == "all":
                if body.kind != "refresh":
                    raise ValueError("Choose a target client before making changes.")
                targets = [for_client(p.id) for p in service.settings.client_profiles if p.enabled]

                def refresh_all(stop, progress):
                    results = []
                    for target in targets:
                        try:
                            result = target.run(body, stop, progress)
                        except Exception as error:
                            target.connection_error = error_message(error)
                            result = {"error": target.connection_error}
                        results.append(
                            {"client_id": target.setup.settings.active_client_id, **result}
                        )
                    return results

                return {"id": jobs.submit("refresh", refresh_all, client_id="all")}
            body = body.model_copy(
                update={"client_id": body.client_id or service.settings.default_client_id}
            )
            target = for_client(body.client_id)
            parameters = body.model_dump(
                mode="json", exclude_defaults=True, exclude={"kind", "client_id"}
            )
            existing = jobs.check_capacity(body.kind, body.client_id, parameters=parameters)
            if existing is not None:
                return {"id": existing}
            target.validate(body)
            if (
                body.kind == "manage"
                and body.action in {"delete", "remove"}
                and not consent(body.client_id).consume(body)
            ):
                raise HTTPException(409, "Review and confirm the selected torrents first.")

            def execute(stop, progress):
                try:
                    return target.run(body, stop, progress)
                except Exception as error:
                    if body.kind == "refresh":
                        target.connection_error = error_message(error)
                    raise

            identifier = jobs.submit(
                body.kind,
                execute,
                client_id=body.client_id,
                parameters=parameters,
            )
        return {"id": identifier}

    @app.post("/api/confirm")
    def confirm(body: JobRequest) -> dict:
        with jobs.lock:
            body = body.model_copy(
                update={"client_id": body.client_id or service.settings.default_client_id}
            )
            return consent(body.client_id).preview(body)

    @app.get("/api/jobs")
    def list_jobs() -> list:
        return jobs.list()

    @app.get("/api/jobs/{identifier}")
    def read_job(identifier: str) -> dict:
        try:
            return jobs.get(identifier)
        except KeyError:
            raise HTTPException(404, "Job not found.") from None

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel_job(identifier: str) -> dict:
        try:
            jobs.cancel(identifier)
        except KeyError:
            raise HTTPException(404, "Job not found.") from None
        return {"ok": True}

    @app.post("/api/jobs/{identifier}/plan-now")
    def plan_from_cache(identifier: str) -> dict:
        try:
            jobs.plan_now(identifier)
        except KeyError:
            raise HTTPException(404, "Job not found.") from None
        return {"ok": True}

    @app.post("/api/jobs/{identifier}/pause-reseed")
    def pause_reseed(identifier: str, paused: bool = True) -> dict:
        try:
            jobs.pause_reseed(identifier, paused)
        except KeyError:
            raise HTTPException(404, "Job not found.") from None
        return {"ok": True}

    assets = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=assets), name="static")

    @app.get("/healthz")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/")
    def shell() -> HTMLResponse:
        html = (assets / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("{{ app_version }}", app_version))

    return app
