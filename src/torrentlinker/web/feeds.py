"""Owner-authenticated RSS endpoints. Authentication is supplied by the app middleware."""

from __future__ import annotations

from fastapi import FastAPI

from torrentlinker.feed_workspace import (
    FeedComparison,
    FeedEnqueue,
    FeedMark,
    FeedSelection,
    FeedWorkspace,
    JudgeFeed,
    SaveFeed,
)
from torrentlinker.feeds import Subscription, candidate, evaluate


def feed_routes(app: FastAPI, service):
    control = service.feed_control
    feeds = control.feeds

    @app.post("/api/feeds/workspace")
    def workspace(body: dict):
        return FeedWorkspace(control).request(
            body["path"], body.get("body"), body.get("method", "GET")
        )

    @app.get("/api/feed-options")
    def options():
        return {
            "clients": [
                {
                    "id": p.id,
                    "name": p.name,
                    "folders": sorted(service.for_client(p.id).download_destinations()),
                }
                for p in service.setup.settings.client_profiles
                if p.enabled
            ]
        }

    @app.get("/api/feeds")
    def subscriptions():
        return feeds.subscriptions()

    @app.post("/api/feeds/preview")
    def preview(body: Subscription):
        return feeds.preview(body)

    @app.post("/api/feeds/judge")
    def judge(body: JudgeFeed):
        """Judge rows from an earlier preview against edited criteria; no source request."""
        return {
            "evaluations": {
                row["infohash"]: evaluate(candidate(row), body.subscription.preferences)
                for row in body.rows
                if row.get("infohash")
            }
        }

    @app.post("/api/feeds")
    def save(body: SaveFeed):
        return control.save(body.subscription, approved=body.approve_automatic)

    @app.delete("/api/feeds/{identifier}")
    def delete(identifier: str):
        control.delete(identifier)
        return {"deleted": identifier}

    @app.post("/api/feeds/{identifier}/pause")
    def pause(identifier: str, paused: bool):
        control.set_paused(identifier, paused)
        return {"paused": paused}

    @app.post("/api/feeds/{identifier}/refresh")
    def refresh(identifier: str):
        return feeds.refresh(identifier)

    @app.post("/api/feeds/{identifier}/process")
    def process(identifier: str):
        return control.process(identifier)

    @app.get("/api/feed-inbox")
    def inbox(
        feed_id: str = "", unread: bool = False, saved: bool = False, dismissed: bool = False
    ):
        return control.inbox(feed_id=feed_id, unread=unread, saved=saved, dismissed=dismissed)

    @app.post("/api/feed-inbox/{infohash}/enrich")
    def enrich(infohash: str):
        return feeds.enrich(infohash)

    @app.post("/api/feed-inbox/mark")
    def mark(body: FeedMark):
        feeds.mark(**body.model_dump())
        return {"updated": len(body.hashes)}

    @app.post("/api/feed-inbox/compare")
    def compare(body: FeedComparison):
        return control.inventory(refresh=True, client_ids=body.client_ids)

    @app.get("/api/feeds/{identifier}/decisions")
    def decisions(identifier: str):
        return control.decisions(identifier)

    @app.get("/api/feed-selections")
    def selections():
        return feeds.selections()

    @app.post("/api/feed-selections")
    def select(body: FeedSelection):
        return feeds.select(body.hashes, body.name)

    @app.get("/api/feed-selections/{identifier}")
    def selection(identifier: str):
        return feeds.selection(identifier)

    @app.post("/api/feed-selections/{identifier}/enqueue")
    def enqueue(identifier: str, body: FeedEnqueue):
        target = service.for_client(body.client_id)
        target.setup.path_under_root(body.folder)
        if body.folder not in target.download_destinations():
            raise ValueError("Choose a configured Download Folder.")
        return feeds.enqueue_selection(identifier, service.setup.store, body.client_id, body.folder)
