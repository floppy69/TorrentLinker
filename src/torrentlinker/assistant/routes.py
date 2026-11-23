"""Owner APIs share the application's cookie and CSRF protection."""

from fastapi import HTTPException, Query, Response

from torrentlinker.assistant.images import fetch_image
from torrentlinker.assistant.models import (
    Conversation,
    Decision,
    FolderMove,
    Message,
    Schedule,
    UserAnswer,
)
from torrentlinker.assistant.providers import Provider
from torrentlinker.assistant.research import SearchSettings


def routes(app, assistant):
    @app.get("/api/assistant/presentations/{identifier}")
    def presentation_page(
        identifier: str, offset: int = Query(0, ge=0), limit: int = Query(12, ge=1, le=20)
    ):
        return assistant.presentation_page(identifier, offset, limit)

    @app.get("/api/assistant/presentations/{identifier}/items/{item_id}")
    def presentation_item(identifier: str, item_id: str):
        return assistant.presentation_item(identifier, item_id)

    @app.get("/api/assistant/image")
    def image(url: str):
        try:
            data, kind = fetch_image(url)
        except Exception:
            raise HTTPException(400, "Image unavailable. Open its source link instead.") from None
        return Response(data, media_type=kind, headers={"X-Content-Type-Options": "nosniff"})

    @app.get("/api/setup/assistant")
    def setup():
        return assistant.setup()

    @app.post("/api/setup/assistant/acknowledge-execute")
    def acknowledge_execute():
        return assistant.acknowledge_execute()

    @app.post("/api/setup/assistant/providers")
    def create(body: Provider):
        return assistant.save_provider(body)

    @app.put("/api/setup/assistant/providers/{identifier}")
    def edit(identifier: str, body: Provider):
        return assistant.save_provider(body, identifier)

    @app.post("/api/setup/assistant/providers/{identifier}/test")
    def test(identifier: str):
        return assistant.test_provider(identifier)

    @app.get("/api/setup/assistant/providers/{identifier}/models")
    def models(identifier: str):
        return assistant.models.models(
            assistant.provider(identifier), assistant.secrets.get("assistant:" + identifier)
        )

    @app.get("/api/setup/assistant/providers/{identifier}/context")
    def provider_context(identifier: str):
        return assistant.context_preview(assistant.provider(identifier), identifier)

    @app.post("/api/setup/assistant/providers/{identifier}/context")
    def preview_saved_context(identifier: str, body: Provider):
        return assistant.context_preview(body, identifier)

    @app.post("/api/setup/assistant/context")
    def preview_context(body: Provider):
        return assistant.context_preview(body)

    @app.get("/api/setup/assistant/chat")
    def chat_defaults():
        return assistant.chat_defaults()

    @app.put("/api/setup/assistant/chat")
    def save_chat_defaults(body: Conversation):
        return assistant.save_chat_defaults(body)

    @app.put("/api/assistant/conversations/{identifier}/folder")
    def move_conversation(identifier: str, body: FolderMove):
        return assistant.move_conversation(identifier, body.folder, automatic=body.automatic)

    @app.put("/api/assistant/conversations/{identifier}")
    def edit_conversation(identifier: str, body: Conversation):
        return assistant.update_conversation(identifier, body)

    @app.post("/api/assistant/conversations")
    def conversation(body: Conversation):
        return assistant.create_conversation(body)

    @app.delete("/api/assistant/conversations/{identifier}")
    def delete_conversation(identifier: str):
        return assistant.delete_conversation(identifier)

    @app.get("/api/assistant/conversations")
    def conversations():
        return assistant.conversations()

    @app.post("/api/assistant/jobs", status_code=202)
    def start(body: Message):
        return assistant.start(body.conversation_id, body.message)

    @app.get("/api/assistant/jobs")
    def history(conversation_id: str = ""):
        return assistant.history(conversation_id, rendered=True)

    @app.get("/api/assistant/jobs/{identifier}")
    def run(identifier: str):
        return assistant.run(identifier, rendered=True)

    @app.post("/api/assistant/jobs/{identifier}/cancel")
    def cancel(identifier: str):
        return assistant.cancel(identifier)

    @app.post("/api/assistant/jobs/{identifier}/questions/{event_index}")
    def answer(identifier: str, event_index: int, body: UserAnswer):
        return assistant.answer(identifier, event_index, body.answer)

    @app.post("/api/assistant/jobs/{identifier}/decisions/{event_index}")
    def decide(identifier: str, event_index: int, body: Decision):
        return assistant.decide(identifier, event_index, body.approve)

    @app.post("/api/assistant/schedules/preview")
    def preview(body: Schedule):
        import time

        return {"next_at": body.next_at(time.time()), "policy": body.policy.model_dump()}

    @app.get("/api/assistant/schedules")
    def schedules():
        return assistant.schedules()

    @app.post("/api/assistant/schedules")
    def schedule(body: Schedule):
        return assistant.save_schedule(body)

    @app.put("/api/assistant/schedules/{identifier}")
    def edit_schedule(identifier: str, body: Schedule):
        return assistant.save_schedule(body, identifier)

    @app.post("/api/assistant/schedules/{identifier}/run", status_code=202)
    def run_schedule(identifier: str):
        return assistant.run_schedule(identifier)

    @app.get("/api/setup/assistant/research")
    def research_settings():
        return assistant.research_settings()

    @app.put("/api/setup/assistant/research")
    def research(body: SearchSettings):
        return assistant.save_research(body)

    @app.post("/api/setup/assistant/models")
    def discover_models(body: Provider):
        return assistant.models.models(body, body.api_key or "")
