"""Owner RSS operations used by both bundled panel hosts."""

from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field

from torrentlinker.feeds import Subscription, candidate, evaluate


class SaveFeed(BaseModel):
    subscription: Subscription
    approve_automatic: bool = False


class JudgeFeed(BaseModel):
    subscription: Subscription
    rows: list[dict] = Field(max_length=1000)


class FeedSelection(BaseModel):
    hashes: list[str] = Field(max_length=1000)
    name: str = Field(default="RSS selection", max_length=100)


class FeedMark(BaseModel):
    hashes: list[str] = Field(max_length=1000)
    feed_id: str = ""
    action: Literal["read", "unread", "save", "unsave", "dismiss", "restore"] = "read"


class FeedComparison(BaseModel):
    client_ids: list[str] | None = Field(default=None, max_length=32)


class FeedEnqueue(BaseModel):
    client_id: str
    folder: str


class FeedWorkspace:
    def __init__(self, control):
        self.control = control

    def request(self, path: str, body=None, method: str = "GET"):
        control = self.control
        feeds, service = control.feeds, control.service
        url = urlsplit(path)
        parts = url.path.split("/")
        query = parse_qs(url.query)
        body = body or {}
        if parts[0] == "community-items" and len(parts) == 2:
            from torrentlinker.community_site import community_site

            return community_site(service.setup).request("items-" + parts[1], body)
        if path == "feed-options" and method == "GET":
            return {
                "categories": {
                    str(k): {"name": v.name, "parent": v.parent}
                    for k, v in service.setup.settings.indexer_categories.items()
                },
                "clients": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "folders": sorted(service.for_client(p.id).download_destinations()),
                    }
                    for p in service.setup.settings.client_profiles
                    if p.enabled
                ],
            }
        if parts == ["feeds"]:
            if method == "GET":
                return feeds.subscriptions()
            if method == "POST":
                saved = SaveFeed.model_validate(body)
                return control.save(saved.subscription, approved=saved.approve_automatic)
        if parts == ["feeds", "preview"] and method == "POST":
            return feeds.preview(Subscription.model_validate(body))
        if parts == ["feeds", "judge"] and method == "POST":
            judged = JudgeFeed.model_validate(body)
            return {
                "evaluations": {
                    r["infohash"]: evaluate(candidate(r), judged.subscription.preferences)
                    for r in judged.rows
                    if r.get("infohash")
                }
            }
        if len(parts) >= 2 and parts[0] == "feeds":
            identifier = parts[1]
            if len(parts) == 2 and method == "DELETE":
                control.delete(identifier)
                return {"deleted": identifier}
            if len(parts) == 3:
                action = parts[2]
                if action == "decisions" and method == "GET":
                    return control.decisions(identifier)
                if action == "pause" and method == "POST":
                    paused = query.get("paused", ["false"])[0] == "true"
                    control.set_paused(identifier, paused)
                    return {"paused": paused}
                if action == "refresh" and method == "POST":
                    return feeds.refresh(identifier)
                if action == "process" and method == "POST":
                    return control.process(identifier)
        if parts == ["feed-inbox"] and method == "GET":
            return control.inbox(
                feed_id=query.get("feed_id", [""])[0],
                unread=query.get("unread", ["false"])[0] == "true",
                saved=query.get("saved", ["false"])[0] == "true",
            )
        if parts == ["feed-inbox", "mark"] and method == "POST":
            marked = FeedMark.model_validate(body)
            feeds.mark(**marked.model_dump())
            return {"updated": len(marked.hashes)}
        if parts == ["feed-inbox", "compare"] and method == "POST":
            return control.inventory(
                refresh=True, client_ids=FeedComparison.model_validate(body).client_ids
            )
        if parts == ["feed-selections"]:
            if method == "GET":
                return feeds.selections()
            if method == "POST":
                selection = FeedSelection.model_validate(body)
                return feeds.select(selection.hashes, selection.name)
        if len(parts) == 2 and parts[0] == "feed-selections" and method == "GET":
            return feeds.selection(parts[1])
        if (
            len(parts) == 3
            and parts[0] == "feed-selections"
            and parts[2] == "enqueue"
            and method == "POST"
        ):
            enqueue = FeedEnqueue.model_validate(body)
            target = service.for_client(enqueue.client_id)
            target.setup.path_under_root(enqueue.folder)
            if enqueue.folder not in target.download_destinations():
                raise ValueError("Choose a configured Download Folder.")
            return feeds.enqueue_selection(
                parts[1], service.setup.store, enqueue.client_id, enqueue.folder
            )
        raise ValueError("Unknown RSS operation.")
