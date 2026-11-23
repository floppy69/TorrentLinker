"""Community linking is Owner-only; the default route guard enforces this."""

from fastapi import FastAPI, HTTPException

from torrentlinker.community_site import community_site


def community_site_routes(app: FastAPI, setup) -> None:
    @app.get("/api/community-site")
    def state():
        return community_site(setup).state()

    @app.post("/api/community-site/{action}")
    def operation(action: str, body: dict):
        try:
            return community_site(setup).request(action, body)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
