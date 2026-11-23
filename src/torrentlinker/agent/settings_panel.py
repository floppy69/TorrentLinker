"""Explicit owner operations exposed by the shared Agent access Settings page."""

from torrentlinker.agent.access import Grant


class AgentSettingsService:
    def __init__(self, service, approve=None):
        self.service = service
        self.approve = approve

    def request(self, path: str, body=None, method: str = "GET"):
        service = self.service
        body = body or {}
        parts = path.split("/")
        if parts == ["agents"]:
            if method == "GET":
                return service.access.snapshot()
            if method == "PUT":
                if type(body.get("enabled")) is not bool:
                    raise ValueError("Choose whether agent access is enabled.")
                service.enable(body["enabled"])
                return service.access.snapshot()
            if method == "POST":
                grant = Grant.model_validate(body)
                for identifier in grant.clients:
                    service.setup.settings.profile(identifier)
                return service.access.create(grant)
        if len(parts) == 3 and parts[0] == "agents" and parts[2] == "revoke" and method == "POST":
            service.revoke(parts[1])
            return {"ok": True}
        if len(parts) == 4 and parts[:2] == ["agents", "proposals"]:
            identifier, operation = parts[2:]
            if operation == "review" and method == "GET":
                return service.review(identifier)
            if method == "POST":
                if operation == "approve":
                    if self.approve is not None:
                        return self.approve(identifier)
                    return service.execute(identifier, approved=True)
                if operation == "reject":
                    service.reject(identifier)
                    return {"ok": True}
                if operation == "release-storage":
                    service.release_storage(identifier)
                    return {"ok": True}
        if len(parts) == 2 and parts[0] == "jobs" and method == "GET":
            return service.jobs.get(parts[1])
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel" and method == "POST":
            service.jobs.cancel(parts[1])
            return {"ok": True}
        raise ValueError("Unknown Agent access operation.")
