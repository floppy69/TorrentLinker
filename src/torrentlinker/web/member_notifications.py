"""Notification channels are Owner-configured; preferences and notices are account-private."""

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from torrentlinker.member_notifications import NoticeSettings, Notifications, Preferences, address
from torrentlinker.web.permissions import Audience, needs


class Settings(NoticeSettings):
    password: str = Field(default="", max_length=1024)


class Recipient(BaseModel):
    email: str = Field(max_length=254)


class Subscription(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: dict[str, str] = Field(default_factory=dict)


def notification_routes(app: FastAPI, accounts, secrets, requests, approval) -> None:
    notices = Notifications(accounts, secrets, requests, approval)
    app.state.notifications = notices

    def answer(work):
        try:
            return work()
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except Exception:
            raise HTTPException(
                502, "Notification delivery failed. Check the channel configuration."
            ) from None

    @app.get("/api/notifications")
    @needs(Audience.ACCOUNT_HOLDER)
    def listing(request: Request):
        notices.collect()
        return notices.listing(request.state.actor.account)

    @app.post("/api/notifications/seen")
    @needs(Audience.ACCOUNT_HOLDER)
    def seen(request: Request):
        notices.seen(request.state.actor.account)
        return {"ok": True}

    @app.get("/api/notifications/preferences")
    @needs(Audience.ACCOUNT_HOLDER)
    def preferences(request: Request):
        actor = request.state.actor
        config = notices.settings()
        public = (
            config.model_dump()
            if actor.owner
            else {
                key: getattr(config, key)
                for key in ("email_enabled", "browser_enabled", "defaults")
            }
        )
        return {
            "owner": actor.owner,
            "config": public,
            "preferences": notices.preferences(actor.account).model_dump(),
            "events": notices.event_names(actor.account),
        }

    @app.post("/api/notifications/preferences")
    @needs(Audience.ACCOUNT_HOLDER)
    def save_preferences(body: Preferences, request: Request):
        answer(lambda: notices.save_preferences(request.state.actor.account, body))
        return preferences(request)

    @app.post("/api/notifications/settings")
    def settings(body: Settings):
        answer(
            lambda: notices.save_settings(
                NoticeSettings.model_validate(body.model_dump()), body.password
            )
        )
        return {"ok": True}

    @app.post("/api/notifications/test-email")
    def test_email(body: Recipient):
        recipient = answer(lambda: address(body.email))
        answer(
            lambda: notices.send_email(
                recipient, "TorrentLinker", "Test notification", notices.settings().app_url
            )
        )
        return {"ok": True}

    @app.get("/api/notifications/push-key")
    @needs(Audience.ACCOUNT_HOLDER)
    def push_key():
        if not notices.settings().browser_enabled:
            raise HTTPException(400, "Browser notifications are disabled.")
        return {"key": notices.public_key()}

    @app.post("/api/notifications/subscription")
    @needs(Audience.ACCOUNT_HOLDER)
    def subscribe(body: Subscription, request: Request):
        answer(lambda: notices.subscribe(request.state.actor.account, body.model_dump()))
        return {"ok": True}

    @app.delete("/api/notifications/subscription")
    @needs(Audience.ACCOUNT_HOLDER)
    def unsubscribe(body: Subscription, request: Request):
        notices.unsubscribe(request.state.actor.account, body.endpoint)
        return {"ok": True}
