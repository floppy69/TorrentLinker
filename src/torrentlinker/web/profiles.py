"""Viewers, PINs and Shared Screens (ADR-0022, #135), and "Mon compte".

Every account holder, the Owner or a Member but never a Viewer, manages their own password,
Viewers, PINs and Shared Screens under `/api/account`. A manager reaches another Member's
under `/api/members/{account}/…`, never the Owner's. A Viewer has only Media Permissions,
never broader than the account's. Once a profile is more restricted than another, the
broader one needs a PIN; stepping up to it asks for that PIN, going down never does. A PIN
is reset with the account's password.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from torrentlinker import age_ratings
from torrentlinker.accounts import (
    MEDIA,
    OWNER,
    PICKING,
    Accounts,
    Actor,
    Permission,
    narrowest,
)
from torrentlinker.web.members import NewLink, shared_link
from torrentlinker.web.permissions import Audience, needs
from torrentlinker.web.security import Throttle


class Viewer(BaseModel):
    name: str = Field(max_length=100)
    permissions: list[Permission] = Field(default_factory=list, max_length=len(MEDIA))
    age_limit: Literal["TP", "10", "12", "16", "18"] | None = None


class Pin(BaseModel):
    viewer: str = Field(default="", max_length=64)  # empty: the account holder
    pin: str = Field(default="", max_length=8)  # empty: no PIN
    password: str = Field(default="", max_length=1024)  # the account's, to set or reset one


class Choice(BaseModel):
    viewer: str = Field(default="", max_length=64)
    pin: str = Field(default="", max_length=8)


class NewPassword(BaseModel):
    current: str = Field(max_length=1024)
    password: str = Field(max_length=1024)


def household_routes(
    app: FastAPI,
    accounts: Accounts,
    media,
    *,
    proxy: bool,
    owner_password: Callable[[str], bool],
    signed_in: Callable[[str], JSONResponse],
) -> None:
    pins = Throttle()

    def actor(request: Request) -> Actor:
        return request.state.actor

    def answer(work):
        try:
            return work()
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def rank(age_limit: str | None) -> int | None:
        return None if age_limit is None else age_ratings.rank(age_limit)

    def public(profile: dict) -> dict:
        age = profile["age_limit"]
        return {
            **profile,
            "age_limit": None if age is None else age_ratings.SCALE[age],
        }

    def household(account: str) -> dict:
        return {
            "profiles": [public(p) for p in accounts.profiles(account)],
            "screens": accounts.screens(account),
        }

    def password_ok(account: str, password: str) -> bool:
        if proxy:
            return True  # the proxy signs people in: there is no password to ask
        if account == OWNER:
            return owner_password(password)
        return accounts.check_password(account, password)

    # A Shared Screen: "Qui regarde ?", then the chosen profile. "Changer de profil" shows
    # the picker again while the current profile keeps watching, so going down asks no PIN.

    def on_screen(request: Request) -> Actor:
        found = actor(request)
        if not found.screen:
            raise HTTPException(404, "This browser is not a Shared Screen.")
        return found

    def current(found: Actor) -> str | None:
        return None if found.viewer == PICKING else found.viewer

    @app.get("/api/screen")
    @needs(Audience.SIGNED_IN)
    def screen(request: Request) -> dict:
        found = on_screen(request)
        return {
            "name": accounts.screen_name(found.screen),
            "holder": accounts.display_name(found.account),
            "current": current(found),
            "profiles": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "holder": p["holder"],
                    "locked": accounts.needs_pin(found.account, p["id"], current(found)),
                }
                for p in accounts.profiles(found.account)
            ],
        }

    @app.post("/api/screen/choose")
    @needs(Audience.SIGNED_IN)
    def choose(body: Choice, request: Request) -> dict:
        found = on_screen(request)
        try:
            accounts.viewer(found.account, body.viewer)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        if accounts.needs_pin(found.account, body.viewer, current(found)):
            keys = (
                f"pin:{found.account}:{body.viewer}",
                f"address:{request.client.host if request.client else ''}",
            )
            if wait := pins.wait(*keys):
                minutes = max(1, round(wait / 60))
                raise HTTPException(429, f"Too many attempts. Try again in {minutes} min.")
            if not accounts.check_pin(found.account, body.viewer, body.pin):
                pins.failed(*keys)
                raise HTTPException(403, "Incorrect PIN.")
            pins.succeeded(*keys)
        accounts.choose(found.screen, body.viewer)
        return {"ok": True}

    # Mon compte: the account holder's own password, Viewers, PINs and Shared Screens.

    @app.get("/api/account")
    @needs(Audience.ACCOUNT_HOLDER)
    def account(request: Request) -> dict:
        found = actor(request)
        details = next((m for m in accounts.members() if m["id"] == found.account), None)
        return {
            "id": found.account,
            "owner": found.owner,
            # Inviting a profile as a Member is managing Members, through a link.
            "promote": found.holds(Permission.MANAGE_MEMBERS) and not proxy,
            "name": accounts.display_name(found.account),
            "login": details["login"] if details else "",
            "proxy": proxy,
            "screen": found.screen,
            **household(found.account),
        }

    @app.post("/api/account/password")
    @needs(Audience.ACCOUNT_HOLDER)
    def change_password(body: NewPassword, request: Request) -> JSONResponse:
        found = actor(request)
        if found.owner or proxy:
            raise HTTPException(400, "This password is set where the server starts.")
        if not accounts.check_password(found.account, body.current):
            raise HTTPException(403, "Incorrect current password.")
        answer(lambda: accounts.set_password(found.account, body.password))
        # Every session and Shared Screen ended; this browser stays signed in.
        return signed_in(found.account)

    def may_view(
        editor: Actor, holder: str, before: dict | None, body: Viewer, *, own: bool
    ) -> None:
        """A manager never gives a Viewer more than they see themselves: no Permission they
        lack, no Age Rating above their limit, no Library Folder they do not see."""
        if own or editor.owner:
            return
        was = set(before["permissions"]) if before else set()
        if any(not editor.holds(Permission(p)) for p in set(body.permissions) - was):
            raise PermissionError("You cannot grant or remove a Permission you do not hold.")
        base, folders = accounts.media_limits(holder)
        wanted = narrowest(base, rank(body.age_limit))
        widened_age = before is None or (
            before["age_limit"] is not None and (wanted is None or wanted > before["age_limit"])
        )
        if (
            editor.age_limit is not None
            and widened_age
            and (wanted is None or wanted > editor.age_limit)
        ):
            raise PermissionError("You cannot allow a higher Age Rating than your own.")
        if (
            (widened_age or bool(set(body.permissions) - was))
            and editor.folders is not None
            and (folders is None or not set(folders) <= editor.folders)
        ):
            raise PermissionError("You cannot show a Library Folder you do not see.")

    def viewer_routes(prefix: str, holder: Callable[[Request, str], str]) -> None:
        """The same Viewer routes for one's own account and, for a manager, another's."""

        @app.post(prefix + "/viewers/new")
        @needs(Audience.ACCOUNT_HOLDER if prefix == "/api/account" else Permission.MANAGE_MEMBERS)
        def add(body: Viewer, request: Request, account: str = "") -> dict:
            owner_of = holder(request, account)
            answer(
                lambda: may_view(actor(request), owner_of, None, body, own=prefix == "/api/account")
            )
            answer(
                lambda: accounts.add_viewer(
                    owner_of, body.name, body.permissions, rank(body.age_limit)
                )
            )
            return household(owner_of)

        @app.post(prefix + "/viewers/{viewer}")
        @needs(Audience.ACCOUNT_HOLDER if prefix == "/api/account" else Permission.MANAGE_MEMBERS)
        def edit(viewer: str, body: Viewer, request: Request, account: str = "") -> dict:
            owner_of = holder(request, account)
            answer(
                lambda: may_view(
                    actor(request),
                    owner_of,
                    answer(lambda: accounts.viewer(owner_of, viewer)),
                    body,
                    own=prefix == "/api/account",
                )
            )
            answer(
                lambda: accounts.update_viewer(
                    owner_of, viewer, body.name, body.permissions, rank(body.age_limit)
                )
            )
            return household(owner_of)

        @app.post(prefix + "/viewers/{viewer}/delete")
        @needs(Audience.ACCOUNT_HOLDER if prefix == "/api/account" else Permission.MANAGE_MEMBERS)
        def remove(viewer: str, request: Request, account: str = "") -> dict:
            owner_of = holder(request, account)
            accounts.remove_viewer(owner_of, viewer)
            media.forget_viewer(owner_of, viewer)
            return household(owner_of)

        @app.post(prefix + "/screens/{screen}/forget")
        @needs(Audience.ACCOUNT_HOLDER if prefix == "/api/account" else Permission.MANAGE_MEMBERS)
        def forget(screen: str, request: Request, account: str = "") -> dict:
            owner_of = holder(request, account)
            accounts.forget_screen(owner_of, screen)
            return household(owner_of)

    def own(request: Request, _account: str) -> str:
        return actor(request).account

    viewer_routes("/api/account", own)

    @app.post("/api/account/pin")
    @needs(Audience.ACCOUNT_HOLDER)
    def set_pin(body: Pin, request: Request) -> dict:
        """Set, change or remove a profile's PIN; a forgotten one is reset this way too."""
        found = actor(request)
        if not password_ok(found.account, body.password):
            raise HTTPException(403, "Incorrect password.")
        answer(lambda: accounts.set_pin(found.account, body.viewer, body.pin))
        return household(found.account)

    # Another Member's household, for the Owner or a manager. Never the Owner's account.

    def managed(request: Request, account: str) -> str:
        editor = actor(request)
        if account == OWNER:
            raise HTTPException(403, "The Owner's account cannot be edited here.")
        found = next((m for m in accounts.members() if m["id"] == account), None)
        if found is None:
            raise HTTPException(404, "This Member no longer exists.")
        if not editor.owner and any(not editor.holds(Permission(p)) for p in found["permissions"]):
            raise HTTPException(
                403, "Only the Owner can change the profiles of a Member with more Permissions."
            )
        return account

    @app.get("/api/members/{account}/profiles")
    @needs(Permission.MANAGE_MEMBERS)
    def profiles(account: str, request: Request) -> dict:
        return household(managed(request, account))

    viewer_routes("/api/members/{account}", managed)

    @app.post("/api/members/{account}/viewers/{viewer}/promote")
    @needs(Permission.MANAGE_MEMBERS)
    def promote(account: str, viewer: str, body: NewLink, request: Request) -> dict:
        """Invite a Viewer as a Member; their progress and playlists follow them. The Owner
        may promote their own Viewers too."""
        editor = actor(request)
        holder = account if account == OWNER and editor.owner else managed(request, account)
        if proxy:
            raise HTTPException(400, "The reverse proxy signs users in: links are not used.")
        found = answer(lambda: accounts.viewer(holder, viewer))
        if not editor.owner and any(not editor.holds(Permission(p)) for p in found["permissions"]):
            raise HTTPException(403, "You cannot grant or remove a Permission you do not hold.")
        member, token = answer(
            lambda: accounts.promote(holder, viewer, days=body.days, inviter=editor.account)
        )
        media.move_viewer(holder, viewer, member)
        details = next(m for m in accounts.members() if m["id"] == member)
        return {
            "member": details,
            "link": shared_link(body.base, token, details["link"]),
            **household(holder),
        }
