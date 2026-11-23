"""Paramètres → Utilisateurs: the Owner, or a Member allowed to manage Members, edits Members.

A manager never touches the Owner's account, never changes a Permission they do not hold
themselves, never edits their own Permissions or caps, and never changes how someone holding
more than they do signs in (ADR-0022).

Invitation and password links are one-time, valid 24 h, 3 or 7 days; the token travels in the
URL's fragment (`join#…`), so it never reaches a server log.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from torrentlinker import age_ratings
from torrentlinker.accounts import OWNER, Accounts, Actor, Caps, Permission
from torrentlinker.member_requests import Requests
from torrentlinker.web.permissions import Audience, needs


class MemberCaps(BaseModel):
    assistant_per_day: int = Field(default=20, ge=0, le=10_000)
    requests_per_week: int | None = Field(default=None, ge=0, le=10_000)
    bytes_per_week: int | None = Field(default=None, ge=0, le=10**15)
    pending: int | None = Field(default=None, ge=0, le=10_000)


AgeLimit = Literal["TP", "10", "12", "16", "18"] | None


class MediaLimits(BaseModel):
    """What Médias shows: an Age Rating limit and the visible Library Folders (None: all)."""

    age_limit: AgeLimit = None
    folders: list[str] | None = Field(default=None, max_length=500)


class Member(MediaLimits):
    name: str = Field(max_length=100)
    login: str = Field(max_length=100)
    proxy_user: str = Field(default="", max_length=200)
    password: str = Field(default="", max_length=1024)
    permissions: list[Permission] = Field(default_factory=list, max_length=len(Permission))
    caps: MemberCaps = Field(default_factory=MemberCaps)


class ProxyUser(BaseModel):
    proxy_user: str = Field(default="", max_length=200)


class NewLink(BaseModel):
    days: int = 3
    base: str = Field(max_length=500)  # the address the Web UI is opened at, for the link


class Invitation(NewLink, MediaLimits):
    name: str = Field(max_length=100)
    note: str = Field(default="", max_length=500)
    permissions: list[Permission] = Field(default_factory=list, max_length=len(Permission))
    caps: MemberCaps = Field(default_factory=MemberCaps)


class EmailLink(BaseModel):
    email: str = Field(max_length=254)


class LinkToken(BaseModel):
    token: str = Field(max_length=100)


class LinkUse(LinkToken):
    password: str = Field(max_length=1024)
    name: str = Field(default="", max_length=100)
    login: str = Field(default="", max_length=100)


def shared_link(base: str, token: str, details: dict) -> dict:
    """The link to send, with its QR code as rows of modules the page draws."""
    import segno

    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, "Open TorrentLinker at its usual address to create a link.")
    url = base.split("#")[0].rstrip("/") + "/join#" + token
    rows = segno.make(url, error="m", micro=False).matrix
    return {"url": url, "qr": ["".join("1" if m else "0" for m in row) for row in rows], **details}


def member_routes(
    app: FastAPI,
    accounts: Accounts,
    media,
    *,
    proxy: bool,
    signed_in: Callable[[str], JSONResponse],
    requests: Requests,
) -> None:
    def actor(request: Request) -> Actor:
        return request.state.actor

    def answer(work):
        try:
            return work()
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def current(account: str) -> dict:
        found = next((m for m in accounts.members() if m["id"] == account), None)
        if found is None:
            raise HTTPException(404, "This Member no longer exists.")
        return found

    def may_edit(editor: Actor, account: str, before: set[str], after: set[str]) -> None:
        if editor.owner:
            return
        if account == editor.account and before != after:
            raise PermissionError("Ask another manager to change your own Permissions.")
        lacking = {p for p in before ^ after if not editor.holds(Permission(p))}
        if lacking:
            raise PermissionError("You cannot grant or remove a Permission you do not hold.")

    def library_folders() -> list[dict]:
        return [
            {"path": str(f.path.absolute()), "name": f.path.name or str(f.path), "kind": f.kind}
            for f in media.agent.setup.settings.library_folders
        ]

    def rank(age_limit: str | None) -> int | None:
        return None if age_limit is None else age_ratings.rank(age_limit)

    def may_limit(editor: Actor, account: str, before: dict, body: MediaLimits) -> None:
        """A manager never widens what Médias shows past their own limits, nor their own."""
        folders = None if body.folders is None else sorted(set(body.folders))
        if editor.owner or (before.get("age_limit"), before.get("folders")) == (
            body.age_limit,
            folders,
        ):
            return
        if account == editor.account:
            raise PermissionError("Ask another manager to change your own Permissions.")
        limit, wanted = editor.age_limit, rank(body.age_limit)
        if limit is not None and (wanted is None or wanted > limit):
            raise PermissionError("You cannot allow a higher Age Rating than your own.")
        if editor.folders is not None and (
            body.folders is None or not set(body.folders) <= editor.folders
        ):
            raise PermissionError("You cannot show a Library Folder you do not see.")

    def caps(body: Member, account: str) -> Caps:
        kept = body.caps.assistant_per_day
        if Permission.REQUEST not in body.permissions:
            return Caps(assistant_per_day=kept)  # caps need the Request Permission
        return Caps(**body.caps.model_dump())

    @app.get("/api/members")
    @needs(Permission.MANAGE_MEMBERS)
    def members(request: Request) -> dict:
        editor = actor(request)
        return {
            "members": accounts.members(),
            "proxy": proxy,
            "you": editor.account,
            "grantable": sorted(p.value for p in Permission if editor.holds(p)),
            "library_folders": library_folders(),
            **({"owner_proxy_user": accounts.owner_proxy_user()} if editor.owner else {}),
        }

    @app.post("/api/members/owner/proxy-user")
    def owner_proxy_user(body: ProxyUser) -> dict:
        # Undeclared: only the Owner names how the proxy sends them.
        answer(lambda: accounts.set_proxy_user(OWNER, body.proxy_user))
        return {"proxy_user": accounts.owner_proxy_user()}

    def no_links() -> None:
        if proxy:
            raise HTTPException(400, "The reverse proxy signs users in: links are not used.")

    @app.post("/api/members/invite")
    @needs(Permission.MANAGE_MEMBERS)
    def invite(body: Invitation, request: Request) -> dict:
        editor = actor(request)
        no_links()

        def work() -> tuple[str, str]:
            may_edit(editor, "", set(), {p.value for p in body.permissions})
            may_limit(editor, "", {}, body)
            caps = (
                Caps(**body.caps.model_dump())
                if Permission.REQUEST in body.permissions
                else Caps(assistant_per_day=body.caps.assistant_per_day)
            )
            account, token = accounts.invite(
                body.name,
                body.permissions,
                caps,
                days=body.days,
                inviter=editor.account,
                note=body.note,
            )
            accounts.set_media_limits(account, body.age_limit, body.folders)
            return account, token

        account, token = answer(work)
        found = current(account)
        return {"member": found, "link": shared_link(body.base, token, found["link"])}

    def linkable(editor: Actor, account: str) -> dict:
        if account == OWNER:
            raise HTTPException(403, "The Owner's account cannot be edited here.")
        found = current(account)
        stronger = any(not editor.holds(Permission(p)) for p in found["permissions"])
        if stronger and not editor.owner:
            raise HTTPException(
                403, "Only the Owner can change how a Member with more Permissions signs in."
            )
        return found

    @app.post("/api/members/{account}/link")
    @needs(Permission.MANAGE_MEMBERS)
    def new_link(account: str, body: NewLink, request: Request) -> dict:
        """A new password link, or a new invitation for someone who has not joined yet."""
        editor = actor(request)
        no_links()
        linkable(editor, account)
        token = answer(
            lambda: accounts.password_link(account, days=body.days, inviter=editor.account)
        )
        found = current(account)
        return {"member": found, "link": shared_link(body.base, token, found["link"])}

    @app.post("/api/members/{account}/show-link")
    @needs(Permission.MANAGE_MEMBERS)
    def show_link(account: str, body: NewLink, request: Request) -> dict:
        linkable(actor(request), account)
        opened = accounts.open_link(account)
        if opened is None:
            raise HTTPException(404, "This link has expired or was used. Create a new one.")
        return {"link": shared_link(body.base, *opened)}

    @app.post("/api/members/{account}/email-link")
    @needs(Permission.MANAGE_MEMBERS)
    def email_link(account: str, body: EmailLink, request: Request) -> dict:
        from torrentlinker.member_notifications import address

        no_links()
        linkable(actor(request), account)
        opened = accounts.open_link(account)
        if opened is None:
            raise HTTPException(404, "This link has expired or was used.")
        notices = app.state.notifications
        recipient = answer(lambda: address(body.email))
        try:
            notices.send_email(
                recipient,
                "TorrentLinker",
                opened[1]["kind"],
                notices.settings().app_url + "/join#" + opened[0],
            )
        except Exception:
            raise HTTPException(
                502, "Email delivery failed. Check Notifications settings."
            ) from None
        return {"ok": True}

    @app.post("/api/members/{account}/cancel-link")
    @needs(Permission.MANAGE_MEMBERS)
    def cancel_link(account: str, request: Request) -> dict:
        linkable(actor(request), account)
        removed = answer(lambda: accounts.cancel_link(account))
        if removed:
            media.forget_account(account)
        return {"removed": removed}

    @app.post("/api/links/inspect")
    @needs(Audience.PUBLIC)
    def inspect_link(body: LinkToken) -> dict:
        no_links()
        found = accounts.link(body.token)
        if found is None:
            raise HTTPException(404, "This link is not valid.")
        return found

    @app.post("/api/links/redeem")
    @needs(Audience.PUBLIC)
    def redeem_link(body: LinkUse) -> JSONResponse:
        no_links()
        invitation = accounts.link(body.token)
        account = answer(
            lambda: accounts.redeem(body.token, body.password, name=body.name, login=body.login)
        )
        if invitation and invitation["kind"] == "invite":
            app.state.notifications.owner(
                "invitation", accounts.display_name(account), "Invitation accepted"
            )
        return signed_in(account)

    @app.post("/api/members")
    @needs(Permission.MANAGE_MEMBERS)
    def create(body: Member, request: Request) -> dict:
        editor = actor(request)
        if proxy and not body.proxy_user.strip():
            raise HTTPException(400, "Give the name your reverse proxy sends for this Member.")
        if not proxy and not body.password:
            raise HTTPException(400, "Choose a password for this Member.")

        def work() -> str:
            may_edit(editor, "", set(), {p.value for p in body.permissions})
            may_limit(editor, "", {}, body)
            account = accounts.create(
                body.name,
                body.login,
                body.permissions,
                password=body.password,
                proxy_user=body.proxy_user,
            )
            accounts.set_caps(account, caps(body, account))
            accounts.set_media_limits(account, body.age_limit, body.folders)
            return account

        return current(answer(work))

    @app.post("/api/members/{account}")
    @needs(Permission.MANAGE_MEMBERS)
    def update(account: str, body: Member, request: Request) -> dict:
        editor = actor(request)
        if account == OWNER:
            raise HTTPException(403, "The Owner's account cannot be edited here.")
        before = current(account)

        def work() -> None:
            granted = {p.value for p in body.permissions}
            may_edit(editor, account, set(before["permissions"]), granted)
            may_limit(editor, account, before, body)
            new_caps = caps(body, account)
            if account == editor.account and not editor.owner and vars(new_caps) != before["caps"]:
                raise PermissionError("Ask another manager to change your own caps.")
            signs_in = body.password or body.proxy_user.strip() != before["proxy_user"]
            stronger = any(not editor.holds(Permission(p)) for p in before["permissions"])
            if signs_in and stronger:
                # Otherwise a manager could sign in as someone holding more than they do.
                raise PermissionError(
                    "Only the Owner can change how a Member with more Permissions signs in."
                )
            accounts.update(account, body.name, body.login, body.proxy_user)
            accounts.set_media_limits(account, body.age_limit, body.folders)
            accounts.grant(account, body.permissions)
            accounts.set_caps(account, new_caps)
            if body.password:
                accounts.set_password(account, body.password)

        answer(work)
        return current(account)

    @app.post("/api/members/{account}/{action}")
    @needs(Permission.MANAGE_MEMBERS, action={"disable", "enable", "delete"})
    def manage(account: str, action: str, request: Request) -> dict:
        editor = actor(request)
        if account == OWNER:
            raise HTTPException(403, "The Owner's account cannot be disabled or deleted.")
        if account == editor.account and not editor.owner:
            raise HTTPException(403, "Ask another manager to disable or delete your account.")
        current(account)
        if action == "delete":
            if not current(account)["disabled"]:
                raise HTTPException(400, "Disable the Member before deleting them.")
            # Their Requests stay in the history as "ancien membre"; pending ones end first.
            requests.cancel_pending(account)
            answer(lambda: accounts.delete(account))
            media.forget_account(account)
            return {"ok": True}
        answer(lambda: accounts.disable(account, action == "disable"))
        return current(account)
