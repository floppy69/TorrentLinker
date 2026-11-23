"""Owner model-connection operations shared by both Settings hosts."""

from torrentlinker.assistant.models import Conversation
from torrentlinker.assistant.providers import Provider
from torrentlinker.assistant.research import SearchSettings


class AssistantSettingsService:
    def __init__(self, service):
        self.service = service

    def request(self, path: str, body=None, method: str = "GET"):
        parts = path.split("/")
        if parts[:2] != ["setup", "assistant"]:
            raise ValueError("Unknown Assistant Settings operation.")
        route = parts[2:]
        service = self.service
        if not route and method == "GET":
            return service.setup()
        if route == ["acknowledge-execute"] and method == "POST":
            return service.acknowledge_execute()
        if route == ["chat"]:
            if method == "GET":
                return service.chat_defaults()
            if method == "PUT":
                return service.save_chat_defaults(Conversation.model_validate(body))
        if route == ["research"]:
            if method == "GET":
                return service.research_settings()
            if method == "PUT":
                return service.save_research(SearchSettings.model_validate(body))
        if route == ["providers"] and method == "POST":
            return service.save_provider(Provider.model_validate(body))
        if route == ["models"] and method == "POST":
            provider = Provider.model_validate(body)
            return service.models.models(provider, provider.api_key or "")
        if route == ["context"] and method == "POST":
            return service.context_preview(Provider.model_validate(body))
        if len(route) >= 2 and route[0] == "providers":
            identifier = route[1]
            if len(route) == 2 and method == "PUT":
                return service.save_provider(Provider.model_validate(body), identifier)
            if len(route) == 3:
                if route[2] == "test" and method == "POST":
                    return service.test_provider(identifier)
                if route[2] == "models" and method == "GET":
                    return service.models.models(
                        service.provider(identifier), service.secrets.get("assistant:" + identifier)
                    )
                if route[2] == "context" and method in {"GET", "POST"}:
                    provider = (
                        service.provider(identifier)
                        if method == "GET"
                        else Provider.model_validate(body)
                    )
                    return service.context_preview(provider, identifier)
        raise ValueError("Unknown Assistant Settings operation.")
