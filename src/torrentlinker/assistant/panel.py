"""Owner-only operations used by the bundled Assistant panel on desktop."""

from urllib.parse import parse_qs, unquote, urlsplit

from torrentlinker.assistant.models import (
    Conversation,
    Decision,
    FolderMove,
    Message,
    Schedule,
    UserAnswer,
)


class AssistantPanelService:
    def __init__(self, assistant):
        self.assistant = assistant

    def request(self, path, body=None, method="GET"):
        parsed = urlsplit(path)
        parts = [unquote(p) for p in parsed.path.split("/")]
        query = parse_qs(parsed.query)
        service = self.assistant
        body = body or {}
        if parts[0] == "community-site" and len(parts) == 2:
            from torrentlinker.community_site import community_site

            return community_site(service.agent.setup).request(parts[1], body)
        if parts == ["assistant", "image"] and method == "GET":
            import base64

            from torrentlinker.assistant.images import fetch_image

            data, kind = fetch_image(query.get("url", [""])[0])
            return {"data_url": "data:" + kind + ";base64," + base64.b64encode(data).decode()}
        if parts == ["setup"] and method == "GET":
            settings = service.agent.setup.settings
            return {
                "client_id": settings.active_client_id,
                "clients": [
                    {"id": p.id, "name": p.name, "enabled": p.enabled}
                    for p in settings.client_profiles
                ],
            }
        if parts == ["setup", "assistant"] and method == "GET":
            return service.setup()
        if parts == ["setup", "assistant", "acknowledge-execute"] and method == "POST":
            return service.acknowledge_execute()
        if parts == ["setup", "assistant", "chat"]:
            if method == "GET":
                return service.chat_defaults()
            if method == "PUT":
                return service.save_chat_defaults(Conversation.model_validate(body))
        if parts[:2] == ["assistant", "conversations"]:
            if len(parts) == 2:
                if method == "GET":
                    return service.conversations()
                if method == "POST":
                    return service.create_conversation(Conversation.model_validate(body))
            if len(parts) == 3:
                if method == "PUT":
                    return service.update_conversation(parts[2], Conversation.model_validate(body))
                if method == "DELETE":
                    return service.delete_conversation(parts[2])
            if len(parts) == 4 and parts[3] == "folder" and method == "PUT":
                move = FolderMove.model_validate(body)
                return service.move_conversation(parts[2], move.folder, automatic=move.automatic)
        if parts[:2] == ["assistant", "jobs"]:
            if len(parts) == 2:
                if method == "GET":
                    return service.history(query.get("conversation_id", [""])[0], rendered=True)
                if method == "POST":
                    message = Message.model_validate(body)
                    return service.start(message.conversation_id, message.message)
            if len(parts) == 3 and method == "GET":
                return service.run(parts[2], rendered=True)
            if len(parts) == 4 and parts[3] == "cancel" and method == "POST":
                return service.cancel(parts[2])
            if len(parts) == 5 and method == "POST":
                if parts[3] == "questions":
                    return service.answer(
                        parts[2], int(parts[4]), UserAnswer.model_validate(body).answer
                    )
                if parts[3] == "decisions":
                    return service.decide(
                        parts[2], int(parts[4]), Decision.model_validate(body).approve
                    )
        if parts[:2] == ["assistant", "presentations"] and method == "GET":
            if len(parts) == 3:
                offset = max(0, int(query.get("offset", [0])[0]))
                limit = max(1, min(20, int(query.get("limit", [12])[0])))
                return service.presentation_page(parts[2], offset, limit)
            if len(parts) == 5 and parts[3] == "items":
                return service.presentation_item(parts[2], parts[4])
        if parts[:2] == ["assistant", "schedules"]:
            if len(parts) == 2:
                if method == "GET":
                    return service.schedules()
                if method == "POST":
                    return service.save_schedule(Schedule.model_validate(body))
            if len(parts) == 3 and method == "PUT":
                return service.save_schedule(Schedule.model_validate(body), parts[2])
            if len(parts) == 3 and parts[2] == "preview" and method == "POST":
                import time

                schedule = Schedule.model_validate(body)
                return {
                    "next_at": schedule.next_at(time.time()),
                    "policy": schedule.policy.model_dump(),
                }
            if len(parts) == 4 and parts[3] == "run" and method == "POST":
                return service.run_schedule(parts[2])
        if parts[:2] == ["agents", "proposals"] and len(parts) == 4:
            if parts[3] == "review" and method == "GET":
                return service.agent.review(parts[2])
            if parts[3] == "approve" and method == "POST":
                return service.agent.execute(parts[2], approved=True)
            if parts[3] == "reject" and method == "POST":
                return service.agent.reject(parts[2])
        if len(parts) == 2 and parts[0] == "jobs" and method == "GET":
            return service.agent.jobs.get(parts[1])
        raise ValueError("Unknown Assistant panel operation")
