"""Authenticated HTTP adapter for the headless application."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import asdict
from functools import partial
from html import escape
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from torrentlinker import documentation
from torrentlinker.accounts import (
    OWNER,
    OWNER_ACTOR,
    PICKING,
    SCREEN_IDLE,
    SESSION_IDLE,
    WATCH,
    Accounts,
    Actor,
    Permission,
)
from torrentlinker.clients import connect
from torrentlinker.crossseed import STATES as CROSS_SEED_STATES
from torrentlinker.crossseed import CrossSeed, CrossSeedRunner
from torrentlinker.diagnostics import build_report, report_json
from torrentlinker.domain import Torrent
from torrentlinker.login_guard import LoginRefused
from torrentlinker.member_requests import Requests
from torrentlinker.torrent_management import peer_count_order, tracker_group
from torrentlinker.updates import check_for_update, installed_version
from torrentlinker.web.confirmations import Confirmations
from torrentlinker.web.documentation import render
from torrentlinker.web.jobs import Jobs
from torrentlinker.web.member_requests import request_routes
from torrentlinker.web.members import member_routes
from torrentlinker.web.operations import DownloadFolderRequired, JobRequest, Operations
from torrentlinker.web.permissions import Audience, allowed, needs, public
from torrentlinker.web.profiles import household_routes
from torrentlinker.web.security import (
    PROXY_USER_HEADER,
    ServerSecrets,
    Sessions,
    Throttle,
    TrustedProxies,
)
from torrentlinker.web.setup import (
    Connection,
    Connector,
    CrossSeedRules,
    FolderRemoval,
    FolderSetup,
    IndexerConnection,
    IndexerEntry,
    IndexerHubEntry,
    IndexerHubImport,
    PartialNamesRefused,
    ProxySetup,
    Setup,
)
from torrentlinker.web.zen_preferences import ZenPreferences

logger = logging.getLogger(__name__)


class ClientSelection(BaseModel):
    client_id: str = ""


class ReseedFolder(ClientSelection):
    path: str = Field(default="", max_length=4096)
    layout: Literal["auto", "client", "links"] | None = None


class Announce(BaseModel):
    value: str = Field(max_length=4096)


class SequentialVideo(BaseModel):
    enabled: bool


class Login(BaseModel):
    password: str = Field(max_length=1024)
    login: str = Field(default="", max_length=100)  # empty: the Owner's startup password
    screen: str = Field(default="", max_length=60)  # "Cet écran est partagé": its name


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
    members_enabled: bool = False,
) -> FastAPI:
    app_version = escape(installed_version())
    directory.mkdir(parents=True, exist_ok=True)
    # Exactly one owner check: the Web UI password, or the reverse proxy's networks.
    if (password is None) == (not trusted_proxies):
        raise ValueError("Set a Web UI password or trusted proxies, not both.")
    sessions = None if password is None else Sessions(password, directory / "owner-sessions.json")
    accounts = Accounts(directory)
    if not members_enabled:
        accounts.revoke_member_access()
    throttle = Throttle()
    if sessions is None:
        proxies = TrustedProxies(trusted_proxies)

        def actor_of(request: Request) -> Actor | None:
            # Only the proxy's own address counts. Without a user header, or before any
            # account has a proxy name, it is the Owner; an unknown name is refused (ADR-0022).
            if not proxies.allows(request.client.host if request.client else None):
                return None
            if not members_enabled:
                return OWNER_ACTOR
            name = request.headers.get(PROXY_USER_HEADER, "").strip()
            if not name or not accounts.proxy_users():
                return OWNER_ACTOR
            account = accounts.by_proxy_user(name)
            return accounts.actor(account) if account else None

    else:

        def actor_of(request: Request) -> Actor | None:
            token = request.cookies.get("tl_session", "")
            if account := sessions.account(token):
                return accounts.actor(account)
            if not members_enabled:
                return None
            member = accounts.session(token)
            if member is not None:
                if member[1]:
                    request.state.renew_session = (token, SESSION_IDLE)
                return accounts.actor(member[0])
            # A Shared Screen: whoever was chosen watches, until the picker asks again.
            shared = accounts.screen(token)
            if shared is None:
                return None
            if shared[1]:
                request.state.renew_session = (token, SCREEN_IDLE)
            return shared[0]

    def sign_in_required(request: Request) -> JSONResponse:
        if sessions is None:
            if request.headers.get(PROXY_USER_HEADER, "").strip():
                return JSONResponse(
                    {"detail": "Your reverse proxy's user is not a Member of this server."},
                    status_code=403,
                )
            return JSONResponse(
                {"detail": "Open TorrentLinker through its reverse proxy."}, status_code=403
            )
        return JSONResponse({"detail": "Sign in to TorrentLinker."}, status_code=401)

    def session_cookie(response: JSONResponse, token: str, max_age: int) -> None:
        response.set_cookie(
            "tl_session",
            token,
            httponly=True,
            samesite="strict",
            max_age=max_age,
            secure=secure_cookie,
        )

    service = service_override or Setup(
        directory, roots, ServerSecrets(directory, secret_files), connector
    )

    def error_message(error: Exception) -> str:
        if isinstance(error, ValueError):
            return service.secrets.redact(str(error))
        if isinstance(error, LoginRefused):
            # One clear sentence, never "Operation failed": the client was not even asked.
            return error.text(service.settings.language)
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
    cross_seeds: dict[str, tuple[Any, CrossSeed]] = {}

    def owner_notice(event: str, title: str, state: str, note: str, dedup: str) -> None:
        """A Cross-seed event as the Owner's notice (there are none without Members)."""
        if notices := getattr(app.state, "notifications", None):
            notices.emit(OWNER, event, title, state, note=note, dedup=dedup)

    def cross_seed(identifier: str = "") -> CrossSeed:
        """The Cross-seed engine of a Torrent Client profile, rebuilt with its Operations."""
        target = for_client(identifier)
        key = target.setup.settings.active_client_id
        held = cross_seeds.get(key)
        if held is None or held[0] is not target:
            held = (target, CrossSeed(target.setup, target.library, service, owner_notice))
            cross_seeds[key] = held
        return held[1]

    def cross_seed_engines() -> list[CrossSeed]:
        if not service.configured:
            return []
        return [cross_seed(p.id) for p in service.settings.client_profiles if p.enabled]

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
            CrossSeedRunner(cross_seed_engines, shutdown).start()
        if members_enabled:
            app.state.notifications.start()
        assistant.start_scheduler()
        agent_service.feed_control.start()
        from torrentlinker.achievement_sync import achievement_sync
        from torrentlinker.community_site import community_site

        achievement_worker = achievement_sync(community_site(service))
        achievement_worker.start(agent_service)
        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            shutdown.set()
            if monitor_verifications:
                monitor.join(timeout=2)
            agent_service.feed_control.close()
            achievement_worker.close()
            if members_enabled:
                app.state.notifications.close()
            assistant.close()
            jobs.close()
            app.state.media_conversions.close()
            agent_service.media.close()
            agent_service.torrents_workspace.close()
            accounts.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def crash_response(request: Request, error: Exception) -> dict[str, Any]:
        return {"detail": error_message(error), "kind": type(error).__name__}

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
    app.state.secure_cookie = secure_cookie
    app.state.agent_service = agent_service
    from torrentlinker.web.feeds import feed_routes

    feed_routes(app, agent_service)
    from torrentlinker.web.media import media_routes

    media_routes(app, agent_service, assistant)

    def signed_in(account: str) -> JSONResponse:
        response = JSONResponse({"ok": True})
        session_cookie(response, accounts.open_session(account), SESSION_IDLE)
        return response

    requests = Requests(accounts)
    if members_enabled:
        requests.recover_sends()
        member_routes(
            app,
            accounts,
            agent_service.media,
            proxy=sessions is None,
            signed_in=signed_in,
            requests=requests,
        )
        request_routes(app, requests, agent_service.media)
        from torrentlinker.web.member_workspace import member_workspace_routes

        member_workspace_routes(app, requests, app.state.request_approval, agent_service.media)
        from torrentlinker.web.member_assistant import member_assistant_routes

        member_assistant_routes(app, accounts, assistant, app.state.member_workspace)
        from torrentlinker.web.member_notifications import notification_routes

        notification_routes(app, accounts, service.secrets, requests, app.state.request_approval)
        household_routes(
            app,
            accounts,
            agent_service.media,
            proxy=sessions is None,
            owner_password=lambda password: sessions is not None and sessions.verify(password),
            signed_in=signed_in,
        )
    app.state.requests = requests
    app.state.reset_clients = reset_clients
    app.state.accounts = accounts
    app.state.sessions = sessions
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
        if not members_enabled and (
            route in {"/join", "/notifications-worker.js"}
            or any(
                route == p or route.startswith(p + "/")
                for p in (
                    "/api/members",
                    "/api/account",
                    "/api/screen",
                    "/api/links",
                    "/api/requests",
                    "/api/wishes",
                    "/api/member-workspace",
                    "/api/member-assistant",
                    "/api/notifications",
                )
            )
        ):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        if route in COMPANION_ROUTES:
            return await companion_request(request, route, service)
        if route.startswith(("/api/", "/documentation/")):
            if route.startswith("/api/"):
                length = request.headers.get("content-length", "0")
                limit = (
                    12_000_000
                    if route
                    in {
                        "/api/jobs",
                        "/api/zen/plan/review",
                        "/api/prerolls/studio-save",
                        "/api/prerolls/studio-preview",
                    }
                    else 256_000
                )
                if not length.isdigit() or int(length) > limit:
                    return JSONResponse({"detail": "Request too large."}, status_code=413)
                if request.method != "GET" and request.headers.get("X-TorrentLinker") != "1":
                    return JSONResponse(
                        {"detail": "Browser request header required."}, status_code=403
                    )
            if not public(app.router.routes, request.scope):
                actor = actor_of(request)
                if actor is None:
                    return sign_in_required(request)
                if not allowed(app.router.routes, request.scope, actor):
                    return JSONResponse(
                        {"detail": "Your account does not have the Permission for this."},
                        status_code=403,
                    )
                request.state.actor = actor
        try:
            response = await call_next(request)
        except Exception as error:
            # Do not let ASGI log a raw HTTP exception containing private URLs.
            response = JSONResponse(crash_response(request, error), status_code=502)
        renewed = getattr(request.state, "renew_session", None)
        if renewed and route != "/api/logout":
            # A Member's session lasts 30 days of disuse, a Shared Screen 90: each use
            # restarts the cookie's too.
            session_cookie(response, *renewed)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://www.youtube.com https://s.ytimg.com; "
            "style-src 'self'; frame-src 'self' https://www.youtube-nocookie.com; "
            "media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        if route in {
            "/static/community/view.html",
            "/static/reseed/view.html",
            "/static/upload/view.html",
            "/static/profile/view.html",
            "/static/search/view.html",
            "/static/feeds/view.html",
            "/static/torrents/view.html",
            "/static/assistant/view.html",
            "/static/media/view.html",
            "/static/documentation/view.html",
            "/static/catalogue/view.html",
            "/static/plan/view.html",
            "/static/seeding/view.html",
            "/static/settings/view.html",
            "/static/player/view.html",
            "/static/player-details/view.html",
            "/static/shell/view.html",
        }:
            # This bundled component may be embedded only by our own Web UI.
            # Other pages remain unframeable; the component has no network access.
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                + (
                    "img-src data:; "
                    if route
                    in {
                        "/static/profile/view.html",
                        "/static/upload/view.html",
                        "/static/search/view.html",
                        "/static/assistant/view.html",
                        "/static/media/view.html",
                        "/static/player-details/view.html",
                    }
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
    @needs(Audience.PUBLIC)
    def login(body: Login, request: Request) -> JSONResponse:
        if sessions is None:
            return JSONResponse({"detail": "The reverse proxy signs users in."}, status_code=404)
        if not members_enabled and (body.login.strip() or body.screen.strip()):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        name = body.login.strip()
        keys = (
            f"address:{request.client.host if request.client else ''}",
            f"account:{name.casefold() if name else OWNER}",
        )
        if wait := throttle.wait(*keys):
            minutes = max(1, round(wait / 60))
            return JSONResponse(
                {"detail": f"Too many attempts. Try again in {minutes} min."}, status_code=429
            )
        if name:
            account = accounts.verify(name, body.password) or ""
        else:
            account = OWNER if sessions.verify(body.password) else ""
        if not account:
            if throttle.failed(*keys):
                # The Owner receives a notice when Members are enabled.
                logger.warning("Sign-in locked after repeated failures: %s", " ".join(keys))
                if members_enabled:
                    app.state.notifications.owner("locked", name or "Owner", "Sign-in locked")
            detail = "Incorrect sign-in name or password." if name else "Incorrect password."
            return JSONResponse({"detail": detail}, status_code=401)
        throttle.succeeded(*keys)
        response = JSONResponse({"ok": True})
        if body.screen.strip():
            # "Cet écran est partagé": it asks who watches and lasts 90 days of disuse.
            try:
                token = accounts.open_screen(account, body.screen)
                app.state.notifications.owner("screen", body.screen, "New Shared Screen")
            except ValueError as error:
                return JSONResponse({"detail": str(error)}, status_code=400)
            session_cookie(response, token, SCREEN_IDLE)
        elif name:
            session_cookie(response, accounts.open_session(account), SESSION_IDLE)
        else:
            session_cookie(response, sessions.open(OWNER), 43200)
        return response

    @app.post("/api/logout")
    @needs(Audience.SIGNED_IN)
    def logout(request: Request) -> JSONResponse:
        if sessions is not None:
            sessions.logout(request.cookies.get("tl_session", ""))
            accounts.end_session(request.cookies.get("tl_session", ""))
            accounts.end_screen(request.cookies.get("tl_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("tl_session")
        return response

    @app.get("/api/documentation")
    @needs(Audience.SIGNED_IN)
    def documentation_index(language: str = "en") -> list[dict[str, str]]:
        return documentation.guides(language)

    @app.get("/documentation/{name:path}", response_class=HTMLResponse)
    @needs(Audience.SIGNED_IN)
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
    @needs(Audience.SIGNED_IN)
    def documentation_page(name: str) -> dict[str, str]:
        try:
            return {"html": render(name)}
        except (ValueError, OSError) as error:
            raise HTTPException(404, "Guide unavailable.") from error

    @app.get("/api/documentation/file/{name:path}")
    @needs(Audience.SIGNED_IN)
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
        return {
            **snapshot,
            "web_auth": "password" if sessions is not None else "proxy",
            "members_enabled": members_enabled,
        }

    @app.get("/api/settings")
    def settings_snapshot(client_id: str = "") -> dict:
        from torrentlinker.settings_workspace import SettingsWorkspace

        return SettingsWorkspace(for_client(client_id).setup).snapshot()

    # One saved secret for the Owner's eye button; declared before `{group}`.
    @app.post("/api/settings/reveal")
    def settings_reveal(body: dict, response: Response) -> dict:
        from torrentlinker.settings_workspace import SettingsWorkspace

        response.headers["Cache-Control"] = "no-store"
        target = for_client(body.get("client_id", "")).setup
        return {"value": SettingsWorkspace(target).reveal(body.get("secret", ""))}

    @app.post("/api/settings/{group}")
    def settings_save(group: str, body: dict) -> dict:
        from torrentlinker.settings_workspace import SettingsWorkspace

        with jobs.lock:
            idle()
            target = for_client(body.get("client_id", "")).setup
            result = SettingsWorkspace(target).save(group, body.get("value", {}))
            reset_clients()
            return result

    @app.post("/api/settings/test/{group}")
    def settings_test(group: str, body: dict) -> dict:
        from torrentlinker.settings_workspace import SettingsWorkspace

        return SettingsWorkspace(for_client(body.get("client_id", "")).setup).test_connection(
            group, body.get("value", {})
        )

    @app.post("/api/settings/file-access/{action}")
    def settings_file_access(action: str, body: dict) -> dict:
        if action not in {"snapshot", "discover", "save", "check", "browse", "remove"}:
            raise ValueError("Unknown file-access operation")
        identifier = for_client(body.get("client_id", "")).setup.settings.active_client_id
        if not isinstance(body.get("value", {}), dict):
            raise ValueError("File-access values must be an object")
        operation = "transfer-remote-browse" if action == "browse" else "transfer-access-" + action
        return agent_service.torrents_workspace.request(
            operation, {**body.get("value", {}), "client_id": identifier}
        )

    @app.post("/api/settings/storage/{action}")
    def settings_storage(action: str, body: dict) -> dict:
        from torrentlinker.settings_workspace import SettingsWorkspace

        with jobs.lock:
            idle()
            target = for_client(body.get("client_id", "")).setup
            result = SettingsWorkspace(target).storage(action, body.get("value", {}))
            if action in {"save", "download", "remove"}:
                valid = {f.path for f in service.settings.library_folders}
                for operation in [operations, *client_operations.values()]:
                    operation.library.entries[:] = [
                        e for e in operation.library.entries if e.folder.path in valid
                    ]
            return result

    @app.post("/api/settings/clients/{action}")
    def settings_clients(action: str, body: dict) -> dict:
        from torrentlinker.settings_workspace import SettingsWorkspace

        with jobs.lock:
            idle()
            target = for_client(body.get("owner_client_id", "")).setup
            result = SettingsWorkspace(target).clients(action, body)
            reset_clients()
            return result

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
            crash_response(request, error),
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
        from torrentlinker.client_profiles import pending_work, require_no_file_access

        with jobs.lock, service.lock:
            idle()
            profile = service.settings.profile(body.client_id)
            if len(service.settings.client_profiles) == 1 or pending_work(
                service.settings, service.store, profile.id
            ):
                raise ValueError("This client has pending work or is the only configured client.")
            require_no_file_access(service, profile.id)
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

    # The Indexers Cross-seed searches. No declaration: the Owner's alone (ADR-0022, 0024).
    @app.get("/api/indexers")
    def list_indexers() -> dict:
        return {
            "indexers": service.indexer_rows(),
            "cross_seed": asdict(service.settings.cross_seed),
        }

    # Prowlarr or Jackett as a source of Indexers; declared before `{identifier}` routes.
    @app.get("/api/indexers/hub")
    def indexer_hub_state() -> dict:
        return service.hub_state()

    @app.get("/api/indexers/hub/available")
    def indexer_hub_available() -> dict:
        return service.hub_available()

    @app.post("/api/indexers/hub")
    def connect_indexer_hub(body: IndexerHubEntry) -> dict:
        with jobs.lock:
            idle()
            return service.connect_hub(body)

    @app.post("/api/indexers/hub/import")
    def import_indexer_hub(body: IndexerHubImport) -> dict:
        with jobs.lock:
            idle()
            return service.import_hub(body)

    @app.post("/api/indexers/hub/sync")
    def sync_indexer_hub() -> dict:
        with jobs.lock:
            idle()
            return service.sync_hub()

    @app.post("/api/indexers/hub/disconnect")
    def disconnect_indexer_hub() -> dict:
        with jobs.lock:
            idle()
            service.disconnect_hub()
            return {"ok": True}

    @app.post("/api/indexers/probe")
    def probe_new_indexer(body: IndexerEntry) -> dict:
        return service.probe_indexer(body)

    @app.post("/api/indexers")
    def add_indexer(body: IndexerEntry) -> dict:
        with jobs.lock:
            idle()
            return service.add_indexer(body)

    @app.post("/api/indexers/{identifier}")
    def update_indexer(identifier: str, body: IndexerEntry) -> dict:
        with jobs.lock:
            idle()
            return service.update_indexer(identifier, body)

    @app.post("/api/indexers/{identifier}/probe")
    def probe_indexer(identifier: str, body: IndexerEntry) -> dict:
        return service.probe_indexer(body, identifier)

    @app.post("/api/indexers/{identifier}/test")
    def test_indexer_entry(identifier: str) -> dict:
        return service.test_indexer_entry(identifier)

    @app.post("/api/indexers/{identifier}/remove")
    def remove_indexer(identifier: str) -> dict:
        with jobs.lock:
            idle()
            service.remove_indexer(identifier)
            return {"ok": True}

    # Cross-seed activity, review and rules, for the Reseed board's tab (ADR-0024). The
    # Owner's alone: it acts on the Owner's tracker accounts.
    @app.get("/api/cross-seed")
    def cross_seed_activity(
        client_id: str = "", state: str = "", limit: int = Query(500, ge=1, le=2000)
    ) -> dict:
        if state and state not in CROSS_SEED_STATES:
            raise HTTPException(400, "Unknown Cross-seed state.")
        return cross_seed(client_id).activity(state or None, limit)

    @app.post("/api/cross-seed/settings")
    def cross_seed_settings(body: CrossSeedRules) -> dict:
        with jobs.lock:
            idle()
            return service.set_cross_seed(body)

    @app.post("/api/cross-seed/pause")
    def cross_seed_pause() -> dict:
        return service.set_cross_seed(CrossSeedRules(paused=True))

    @app.post("/api/cross-seed/resume")
    def cross_seed_resume() -> dict:
        return service.set_cross_seed(CrossSeedRules(paused=False))

    @app.post("/api/cross-seed/{identifier}/{action}")
    def cross_seed_act(identifier: str, action: str, client_id: str = "") -> dict:
        engine = cross_seed(client_id)
        if action == "reject":
            engine.reject(identifier)
        elif action in ("accept", "retry", "remove"):
            with jobs.lock:
                idle()
                getattr(engine, action)(identifier)
        else:
            raise HTTPException(404, "Unknown Cross-seed action.")
        return {"ok": True}

    @app.get("/api/folders")
    def folders(path: str = "") -> dict:
        return service.browse(path)

    @app.post("/api/setup/reseed-folder")
    def save_reseed_folder(body: ReseedFolder) -> dict:
        with jobs.lock:
            idle()
            setup = for_client(body.client_id).setup
            profile = setup.settings.profile()
            layout = body.layout if body.layout is not None else profile.reseed_layout
            value = body.path.strip()
            path = str(setup.path_under_root(value)) if value else ""
            profile.reseed_link_root = path
            profile.reseed_layout = layout
            setup.save()
            return {
                "reseed_link_root": path,
                "reseed_layout": setup.settings.profile().reseed_layout,
            }

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

    @app.post("/api/search/workspace/{action}")
    def search_workspace(action: str, body: dict, client_id: str = ""):
        from torrentlinker.search_workspace import SearchWorkspace

        try:
            return SearchWorkspace(for_client(client_id), jobs).request(action, body)
        except (ValueError, KeyError) as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/upload/workspace/{action}")
    def upload_workspace(action: str, body: dict, client_id: str = "") -> dict | list:
        from torrentlinker.upload_workspace import UploadWorkspace

        try:
            workspace = UploadWorkspace(for_client(client_id).uploads)
            if action.startswith("tool-"):
                from torrentlinker.upload_tool_jobs import tool_job

                return tool_job(
                    jobs, workspace, workspace.setup.settings.active_client_id, action, body
                )
            return workspace.request(action, body)
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
            "repair_sources": {r["id"]: r["source"] for r in target.library.repairs().rows()},
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

    from torrentlinker.poster_cache import shared_poster_cache, valid_poster_url

    posters = shared_poster_cache(directory / "posters")

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

    @app.get("/api/shell")
    @needs(Audience.SIGNED_IN)
    def shell_state(request: Request) -> dict:
        actor: Actor = request.state.actor
        # On a Shared Screen, "Qui regarde ?" comes first; then whoever was chosen.
        screen = (
            {"name": accounts.screen_name(actor.screen), "picking": actor.viewer == PICKING}
            if actor.screen
            else None
        )
        if not actor.owner:
            # A Member's or a Viewer's shell: Médias without the Owner's tools, the guides,
            # and for an account holder their settings ("Mon compte", Utilisateurs for a
            # manager). The setup snapshot is the Owner's; the shell reads these values instead.
            holder = not actor.viewer
            pages = [
                *(["media"] if any(actor.holds(p) for p in WATCH) else []),
                "documentation",
                *(["notifications"] if holder else []),
                *(["requests"] if actor.holds(Permission.APPROVE) else []),
                *(["member-assistant"] if actor.holds(Permission.ASSISTANT) else []),
                *(["member-search"] if actor.holds(Permission.SEARCH) else []),
                *(["member-queue"] if actor.holds(Permission.QUEUE) else []),
                *(["member-torrents"] if actor.holds(Permission.TORRENTS) else []),
                *(["setup"] if holder else []),
            ]
            viewer = actor.viewer not in ("", PICKING)
            return {
                "version": app_version,
                "release": None,
                "actor": {
                    "owner": False,
                    "viewer": bool(actor.viewer),
                    "name": accounts.viewer(actor.account, actor.viewer)["name"]
                    if viewer
                    else accounts.display_name(actor.account),
                    "permissions": sorted(actor.permissions),
                    "screen": screen,
                },
                "pages": [] if actor.viewer == PICKING else pages,
                "sections": [
                    "account",
                    "notifications",
                    *(["users"] if actor.holds(Permission.MANAGE_MEMBERS) else []),
                ]
                if holder
                else [],
                "setup": {
                    "configured": True,
                    "members_enabled": members_enabled,
                    "adult_content": service.settings.adult_content
                    and actor.holds(Permission.ADULT),
                    "client_id": service.settings.default_client_id,
                    "default_client_id": service.settings.default_client_id,
                    "web_auth": "password" if sessions is not None else "proxy",
                    "clients": [],
                    "capabilities": {},
                },
            }
        release = check_for_update(directory / "release-check.json", current=app_version)
        return {
            "version": app_version,
            "release": {"tag": release.tag, "url": release.url} if release else None,
            "actor": {
                "owner": True,
                "viewer": False,
                "name": "",
                "permissions": sorted(Permission),
                "screen": screen,
            },
        }

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
        state: str = "",
        tracker: str = "",
        tag: str = "",
        size_min: float | None = Query(None, ge=0, allow_inf_nan=False),
        size_max: float | None = Query(None, ge=0, allow_inf_nan=False),
        note_min: float | None = Query(None, ge=0, allow_inf_nan=False),
        zen_min: float | None = Query(None, ge=0, allow_inf_nan=False),
        weight_min: float | None = Query(None, ge=0, allow_inf_nan=False),
        seed_max: float | None = Query(None, ge=0, allow_inf_nan=False),
        days_min: float | None = Query(None, ge=0, allow_inf_nan=False),
        group: str = "",
        descendants: bool = False,
        sort: Literal[
            "name", "size", "seeders", "seed_days", "zen", "note", "ratio", "weight"
        ] = "zen",
        descending: bool = True,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
    ) -> dict:
        from torrentlinker.seeding import combined_seeding
        from torrentlinker.web.seeding import SeedingFilters, seeding_page

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
            filters=SeedingFilters(
                state=state,
                tracker=tracker,
                tag=tag,
                size_min=size_min,
                size_max=size_max,
                note_min=note_min,
                zen_min=zen_min,
                weight_min=weight_min,
                seed_max=seed_max,
                days_min=days_min,
            ),
            group=group,
            descendants=descendants,
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

    @app.post("/api/torrents/workspace")
    def torrent_workspace(body: dict) -> dict:
        return agent_service.torrents_workspace.request(body["action"], body.get("body"))

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
            if body.kind == "catalogue" and any(
                row["kind"] == "catalogue" and row["status"] in {"queued", "running"}
                for row in jobs.list()
            ):
                raise ValueError(
                    "A Catalogue fetch is already running. Pause it or wait for it to finish."
                )
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

    from torrentlinker.web.community_site import community_site_routes

    community_site_routes(app, service)

    assets = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=assets), name="static")

    @app.get("/notifications-worker.js")
    @needs(Audience.PUBLIC)
    def notifications_worker() -> FileResponse:
        return FileResponse(assets / "notifications-worker.js", media_type="text/javascript")

    @app.get("/healthz")
    @needs(Audience.PUBLIC)
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/join")
    @needs(Audience.PUBLIC)
    def join() -> HTMLResponse:
        # An invitation or password link, outside the app; its token stays in the fragment.
        html = (assets / "join.html").read_text(encoding="utf-8")
        return HTMLResponse(
            html.replace("{{ app_version }}", app_version).replace(
                "{{ members_enabled }}", str(members_enabled).lower()
            )
        )

    @app.get("/")
    @needs(Audience.PUBLIC)
    def shell() -> HTMLResponse:
        html = (assets / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            html.replace("{{ app_version }}", app_version).replace(
                "{{ members_enabled }}", str(members_enabled).lower()
            )
        )

    return app
