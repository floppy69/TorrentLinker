"""Requests and Wishes, the Member's side: ask for a tracker film, wish for one, follow them.

A Member never downloads: "Demander" makes a Request an Approver answers (#134). The caps
are checked at sending; a reached cap refuses with its reason and the next reset (409).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from torrentlinker.accounts import Actor, Permission
from torrentlinker.member_requests import CapReached, Release, Requests
from torrentlinker.request_approval import RequestApproval
from torrentlinker.web.permissions import Audience, needs

NOT_FOUND = "This Request no longer exists."


class TrackerRequest(BaseModel):
    infohash: str = Field(pattern="^[0-9a-fA-F]{40}$")


class Wish(BaseModel):
    title: str = Field(max_length=200)
    year: str = Field(default="", max_length=4)
    note: str = Field(default="", max_length=500)


class Answer(BaseModel):
    infohash: str = Field(default="", pattern="^([0-9a-fA-F]{40})?$")
    note: str = Field(default="", max_length=500)


def request_routes(app: FastAPI, requests: Requests, media) -> None:
    approval = RequestApproval(media)
    app.state.request_approval = approval

    def actor(request: Request) -> Actor:
        return request.state.actor

    def refused(error: CapReached) -> JSONResponse:
        return JSONResponse(
            {"detail": str(error), "cap": error.cap, "reset": error.reset}, status_code=409
        )

    def mine(account: str) -> dict:
        approval.refresh(requests)
        rows = requests.mine(account)
        return {
            "requests": rows,
            "quota": requests.quota(account),
            "unread": sum(1 for r in rows if r["unread"]),
        }

    @app.get("/api/requests")
    @needs(Audience.ACCOUNT_HOLDER)
    def listing(request: Request) -> dict:
        return mine(actor(request).account)

    @app.post("/api/requests/seen")
    @needs(Audience.ACCOUNT_HOLDER)
    def seen(request: Request) -> dict:
        requests.seen(actor(request).account)
        return mine(actor(request).account)

    @app.post("/api/requests")
    @needs(Permission.REQUEST)
    def ask(body: TrackerRequest, request: Request):
        """A Request for a tracker film the Member sees; the server reads its release."""
        found = actor(request)
        if not media.sees_tracker(found):
            raise HTTPException(404, "This tracker release is no longer suggested.")
        client = media.agent.setup.settings.default_client_id
        try:
            entry = media.tracker_entry(client, body.infohash.lower())
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        facts, best = entry.get("facts") or {}, entry["release"]
        release = Release(
            best["hash"],
            best["name"],
            int(best["size"]),
            facts.get("title") or entry.get("title") or best["name"],
            str(facts.get("year") or entry.get("year") or ""),
        )
        try:
            return requests.ask(found.account, release)
        except CapReached as error:
            return refused(error)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/wishes")
    @needs(Permission.WISH)
    def wish(body: Wish, request: Request):
        try:
            return requests.wish(actor(request).account, body.title, body.year, body.note)
        except CapReached as error:
            return refused(error)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/requests/{identifier}/cancel")
    @needs(Permission.REQUEST, Permission.WISH)
    def cancel(identifier: str, request: Request) -> dict:
        try:
            return requests.cancel(actor(request).account, identifier)
        except KeyError:
            raise HTTPException(404, NOT_FOUND) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/requests/review")
    @needs(Permission.APPROVE)
    def review() -> dict:
        approval.refresh(requests)
        rows = requests.review()
        for row in rows:
            row["score"] = None
            if row["infohash"]:
                try:
                    entry = media.tracker_entry(approval.client_id, row["infohash"])
                    row["score"] = media._score(
                        media.agent.setup.settings.release_score,
                        row["release"],
                        row["size"],
                        entry.get("facts") or {},
                    ).get("score")
                except ValueError:
                    pass
        return {
            "requests": rows,
            "margin": approval.margin(sum(r["size"] or 0 for r in rows if r["state"] == "pending")),
        }

    @app.get("/api/requests/releases")
    @needs(Permission.APPROVE)
    def releases(q: str = "") -> dict:
        return {"releases": approval.choices(q[:200])}

    def answer(identifier: str, body: Answer, request: Request, action: str) -> dict:
        try:
            release = approval.release(body.infohash.lower()) if body.infohash else None
            row = requests.answer(
                identifier,
                actor(request).account,
                release=release,
                note=body.note,
                retry=action == "retry",
                refuse=action == "refuse",
            )
        except KeyError:
            raise HTTPException(404, NOT_FOUND) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if action != "refuse":
            try:
                approval.send(row["infohash"])
            except Exception:
                # Provider errors can contain URLs, credentials or local paths. Keep those
                # out of the Request seen by a Member, including the shared timeline.
                requests.move(
                    identifier, "send_failed", "", "Sending failed. Check the client and retry."
                )
            else:
                requests.move(identifier, "sent", "")
        return requests.get(identifier)

    @app.post("/api/requests/{identifier}/accept")
    @needs(Permission.APPROVE)
    def accept(identifier: str, body: Answer, request: Request) -> dict:
        return answer(identifier, body, request, "accept")

    @app.post("/api/requests/{identifier}/resolve")
    @needs(Permission.APPROVE)
    def resolve(identifier: str, body: Answer, request: Request) -> dict:
        return answer(identifier, body, request, "accept")

    @app.post("/api/requests/{identifier}/retry")
    @needs(Permission.APPROVE)
    def retry(identifier: str, body: Answer, request: Request) -> dict:
        return answer(identifier, body, request, "retry")

    @app.post("/api/requests/{identifier}/refuse")
    @needs(Permission.APPROVE)
    def refuse(identifier: str, body: Answer, request: Request) -> dict:
        return answer(identifier, body, request, "refuse")

    @app.get("/api/requests/artwork/{infohash}")
    @needs(Permission.APPROVE)
    def artwork(infohash: str) -> FileResponse:
        if len(infohash) != 40 or any(c not in "0123456789abcdef" for c in infohash):
            raise HTTPException(404, "Artwork unavailable.")
        try:
            path = media.tracker_artwork(approval.client_id, infohash)
        except (ValueError, OSError):
            path = None
        if path is None or not path.is_file():
            raise HTTPException(404, "Artwork unavailable.")
        return FileResponse(path)
