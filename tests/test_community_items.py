"""Transfer review is local, immutable and bound to verified bytes; network is mocked."""

import hashlib
import json
import time
from uuid import uuid4

import httpx
import pytest

from tests.test_web_plan_execution import prepared
from torrentlinker.community_site import LINK_SECRET, community_site
from torrentlinker.feeds import Preferences
from torrentlinker.release_score.preferences import Profile


@pytest.fixture
def transfer(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    setup.secrets.update(
        {
            LINK_SECRET: json.dumps(
                {"token": "t" * 43, "identity": "member", "expires": time.time() + 3600}
            )
        }
    )
    site = community_site(setup)
    calls = []
    replies = []

    def respond(request):
        calls.append(request)
        return replies.pop(0)

    site.transport = httpx.MockTransport(respond)
    return site, setup, calls, replies


def metadata():
    return {
        "title": "Shared preset",
        "description": "Reusable community configuration",
        "category": "presets",
        "license": "CC-BY-4.0",
    }


def test_publish_requires_review_and_uses_exact_preview(transfer):
    site, setup, calls, replies = transfer
    body = {
        "kind": "prompt",
        "metadata": metadata(),
        "data": {
            "prompt": (
                "Find a film. token test-key /home/private/file "
                "https://example.com/private user@example.com"
            )
        },
    }
    preview = site.request("items-prepare", body)
    content = json.dumps(preview)
    assert (
        "test-key" not in content
        and "/home/private" not in content
        and "https://example" not in content
        and "user@example" not in content
    )
    assert not calls
    body["data"]["prompt"] = "This change must never be uploaded"
    with pytest.raises(ValueError, match="confirm"):
        site.request("items-publish", {"review": preview["review"]})
    replies.append(
        httpx.Response(201, json={"id": str(uuid4()), "version": 1, "status": "pending"})
    )
    site.request("items-publish", {"review": preview["review"], "confirmed": True})
    assert len(calls) == 1 and b"This change" not in calls[0].content
    assert b"Find a film" in calls[0].content
    with pytest.raises(ValueError, match="expired"):
        site.request("items-publish", {"review": preview["review"], "confirmed": True})


def test_verified_import_and_tamper_rejection(transfer):
    site, setup, calls, replies = transfer
    item, version = str(uuid4()), str(uuid4())
    raw = json.dumps(
        {
            "format": "torrentlinker-community",
            "schemaVersion": 1,
            "kind": "release-score",
            "data": Profile().model_dump(),
        }
    ).encode()
    detail = {
        "id": item,
        "kind": "release-score",
        "title": "Cinema",
        "license": "CC0-1.0",
        "versions": [
            {
                "id": version,
                "version": 2,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "status": "published",
            }
        ],
    }
    replies.extend([httpx.Response(200, json=detail), httpx.Response(200, content=raw)])
    before = dict(setup.settings.release_score)
    review = site.request("items-download", {"id": item})
    assert setup.settings.release_score == before
    result = site.request("items-apply", {"review": review["review"], "confirmed": True})
    assert result["data"] == Profile().model_dump()
    assert setup.settings.release_score == before  # matching panel still reviews/saves its draft
    assert site.request("items-history")["items"][0]["version"] == 2
    from torrentlinker.achievements import Ledger

    ledger = Ledger(setup.path.parent / "achievements.sqlite")
    assert [a["code"] for a in ledger.state("owner")["achievements"]] == ["community-import-first"]
    ledger.close()
    replies.extend([httpx.Response(200, json=detail), httpx.Response(200, content=b"modified")])
    with pytest.raises(ValueError, match="mismatch"):
        site.request("items-download", {"id": item})
    assert not list((setup.path.parent / "community-imports").glob("*.download"))


def test_rss_preferences_survive_without_private_routing(transfer):
    site, setup, calls, replies = transfer
    prefs = Preferences(
        required={"quality": ["1080p"]}, preferred={"codec": ["HEVC"]}, min_seeders=3
    )
    preview = site.request(
        "items-prepare",
        {
            "kind": "rss",
            "metadata": metadata(),
            "data": {
                "rules": [
                    {
                        "name": "Reusable rule",
                        "query": "Film",
                        "categories": [2030],
                        "preferences": prefs.model_dump(),
                        "folder": "/private/downloads",
                        "feed_url": "https://private/feed?passkey=secret",
                    }
                ]
            },
        },
    )
    data = preview["content"]["data"]["rules"][0]
    assert data["preferences"] == prefs.model_dump()
    assert "folder" not in data and "feed_url" not in data
    assert not calls


def test_updates_offer_new_versions_without_overwriting_local_settings(transfer):
    site, setup, calls, replies = transfer
    item, version = str(uuid4()), str(uuid4())
    site.request("items-history")
    path = setup.path.parent / "community-imports" / "imports.json"
    path.write_text(json.dumps([{"id": item, "kind": "release-score", "version": 1}]))
    before = dict(setup.settings.release_score)
    replies.append(
        httpx.Response(
            200,
            json={
                "id": item,
                "kind": "release-score",
                "title": "Cinema",
                "versions": [
                    {
                        "id": version,
                        "version": 2,
                        "status": "published",
                        "bytes": 100,
                        "sha256": "a" * 64,
                    }
                ],
            },
        )
    )
    updates = site.request("items-updates", {"kind": "release-score"})
    assert updates["items"][0]["version_id"] == version
    assert updates["items"][0]["installed_version"] == 1
    assert setup.settings.release_score == before
