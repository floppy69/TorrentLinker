"""Member Assistant APIs expose only account-private conversation content and usage."""

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from torrentlinker.accounts import Permission
from torrentlinker.member_assistant import DailyCap, MemberAssistant
from torrentlinker.web.permissions import needs


class Message(BaseModel):
    conversation_id: str = Field(default="", max_length=64)
    message: str = Field(min_length=1, max_length=16000)


def member_assistant_routes(app: FastAPI, accounts, assistant, workspace) -> None:
    service = MemberAssistant(accounts, assistant, workspace)
    app.state.member_assistant = service

    def answer(work):
        try:
            return work()
        except DailyCap as error:
            raise HTTPException(429, str(error)) from error
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except KeyError:
            raise HTTPException(404, "This discussion no longer exists.") from None
        except ValueError:
            raise HTTPException(
                409,
                "The Assistant could not complete this message. Check your usage "
                "or ask the Owner to check its configuration.",
            ) from None
        except Exception:
            raise HTTPException(
                502, "Assistant provider unavailable. Ask the Owner to check its configuration."
            ) from None

    @app.get("/api/member-assistant")
    @needs(Permission.ASSISTANT)
    def listing(request: Request):
        return answer(lambda: service.chats(request.state.actor.account))

    @app.get("/api/member-assistant/{identifier}")
    @needs(Permission.ASSISTANT)
    def conversation(identifier: str, request: Request):
        return answer(lambda: service.conversation(request.state.actor.account, identifier))

    @app.post("/api/member-assistant")
    @needs(Permission.ASSISTANT)
    def message(body: Message, request: Request):
        return answer(
            lambda: service.send(request.state.actor.account, body.message, body.conversation_id)
        )

    @app.delete("/api/member-assistant/{identifier}")
    @needs(Permission.ASSISTANT)
    def delete(identifier: str, request: Request):
        answer(lambda: service.delete(request.state.actor.account, identifier))
        return {"ok": True}
