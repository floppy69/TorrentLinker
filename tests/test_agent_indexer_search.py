import httpx

from tests import test_catalogue_selection
from tests.test_agent_access import call
from tests.test_agent_queue_capabilities import approve
from tests.test_agent_torrent_lists import tool
from tests.test_torrent_search import FACETS, TREE, fake_indexer, listing
from tests.test_web_jobs import finished

catalogue_app = test_catalogue_selection.catalogue_app


def native(catalogue_app, handler=None):
    app, browser, token = catalogue_app
    requests = []

    def route(request):
        requests.append(request)
        if handler:
            reply = handler(request)
            if reply is not None:
                return reply
        if request.url.path == "/api/categories":
            return httpx.Response(200, json=TREE)
        if request.url.path.endswith("filter-options"):
            return httpx.Response(200, json=FACETS)
        if request.url.path == "/api/torrents":
            return httpx.Response(200, json=listing(page=int(request.url.params["page"])))
        return httpx.Response(404)

    app.state.agent_service.setup._indexer = fake_indexer(route)
    return app, browser, token, requests


def test_shared_search_discovers_native_filters_and_preserves_live_page_for_durable_lists(
    catalogue_app,
):
    app, browser, token, requests = native(catalogue_app)
    options = tool(browser, token, "search_indexer_options", client_id="default", category=-6)
    assert options["categories"]["1"]["name"] == "Films & Vidéos"
    assert options["categories"]["-1"]["parent"] == 1
    assert options["facets"][0]["choices"][0] == ["Action", "39"]
    assert not any(f["slug"] == "saison" for f in options["facets"])
    assert "2160p" in options["video_filters"]["resolution"]
    assert options["global_filters"]["year"]["maximum"] == 2100
    searched = tool(
        browser,
        token,
        "search_indexer",
        request_id="native",
        client_id="default",
        query="Space",
        category=-6,
        filters={
            "year": 2024,
            "options": "39",
            "resolution": "1080p",
            "lang": "VFF",
            "profile": "pure",
            "sortBy": "seeders",
            "sortOrder": "asc",
        },
        page=2,
    )
    result = finished(browser, searched["job_id"])
    assert result["status"] == "completed", result
    page = result["result"]
    assert searched["selection_id"] == searched["job_id"]
    assert page["total"] == 41789 and page["per_page"] == 10 and page["window_limited"]
    assert page["has_more"] and page["page"] == 2
    query = next(r.url.params for r in requests if r.url.path == "/api/torrents")
    assert {
        k: query[k] for k in ("category", "subcat", "year", "options", "resolution", "name", "page")
    } == {
        "category": "1",
        "subcat": "6",
        "year": "2024",
        "options": "39",
        "resolution": "1080p",
        "name": "Space",
        "page": "2",
    }
    assert query["viewMode"] == "flat"
    saved = tool(
        browser,
        token,
        "create_torrent_list",
        request_id="save-live",
        client_id="default",
        name="Live discoveries",
        selection_id=searched["selection_id"],
    )
    assert saved["count"] == 1 and saved["total_size_bytes"] == 1000000000
    rows = tool(browser, token, "get_torrent_list", list_id=saved["id"], revision=1)["rows"]
    assert rows[0]["title"] == "Example"
    assert rows[0]["provenance"]["source"] == "catalogue"
    assert rows[0]["provenance"]["discovery"] == "live-search"
    assert rows[0]["provenance"]["search"]["query"] == "Space"
    assert rows[0]["provenance"]["page"] == 2
    assert browser.get("/api/queue").json() == []
    proposed = tool(
        browser,
        token,
        "enqueue_selection",
        request_id="queue-live-page",
        selection_id=searched["selection_id"],
    )
    assert proposed["requires_owner_approval"]
    queued = approve(browser, proposed)
    assert queued["queued"] == 1
    assert {row["hash"] for row in browser.get("/api/queue").json()} == {"a" * 40}


def test_invalid_native_filters_never_fall_back_to_cached_catalogue(catalogue_app):
    _, browser, token, requests = native(catalogue_app)
    for number, filters in enumerate(
        [{"year_min": 2020}, {"year": "2020-2024"}, {"resolution": "4K"}]
    ):
        response = call(
            browser,
            token,
            "search_indexer",
            {
                "request_id": f"invalid-{number}",
                "client_id": "default",
                "category": -6,
                "query": "Space",
                "filters": filters,
            },
        )
        assert response.get("isError") or "error" in response.get("structuredContent", {})
    assert not any(r.url.path == "/api/torrents" for r in requests)


def test_native_filter_context_and_scoped_failures_never_search_or_queue(catalogue_app):
    _, browser, token, requests = native(catalogue_app)
    for number, (category, filters) in enumerate(
        [
            (2030, {}),
            (-6, {"options": "118"}),
            (2, {"resolution": "1080p"}),
            (1, {"subcat": "11"}),
            (None, {"options": "39"}),
            (-6, {"subcat": "6"}),
        ]
    ):
        proposed = tool(
            browser,
            token,
            "search_indexer",
            request_id=f"bad-context-{number}",
            client_id="default",
            category=category,
            filters=filters,
        )
        assert finished(browser, proposed["job_id"])["status"] == "failed"
    denied = call(browser, token, "search_indexer_options", {"client_id": "other"})[
        "structuredContent"
    ]
    assert "error" in denied
    assert not any(r.url.path == "/api/torrents" for r in requests)
    assert browser.get("/api/queue").json() == []


def test_multiple_native_children_and_every_video_parameter_reach_the_same_listing(catalogue_app):
    _, browser, token, requests = native(catalogue_app)
    searched = tool(
        browser,
        token,
        "search_indexer",
        request_id="all-video",
        client_id="default",
        category=1,
        query="Example",
        filters={
            "subcat": "6,7",
            "options": "39,118",
            "year": 2024,
            "uploader": "ExampleUploader",
            "exclusive": True,
            "crew": True,
            "palliative": "include",
            "palliativeTail": False,
            "resolution": "2160p,1080p",
            "source": "BluRay,Remux",
            "codec": "H.265,AV1",
            "hdr": "HDR10+,DV",
            "audioType": "lossless",
            "channels": "7.1,5.1",
            "profile": "pure,hc_optimized",
            "lang": "VFF,VOSTFR",
            "sortBy": "relevance",
            "sortOrder": "desc",
        },
    )
    assert finished(browser, searched["job_id"])["status"] == "completed"
    params = next(r.url.params for r in requests if r.url.path == "/api/torrents")
    assert params["subcat"] == "6,7" and params["options"] == "39,118"
    for key, value in {
        "uploader": "ExampleUploader",
        "exclusive": "true",
        "crew": "true",
        "palliative": "include",
        "palliativeTail": "false",
        "resolution": "2160p,1080p",
        "source": "BluRay,Remux",
        "codec": "H.265,AV1",
        "hdr": "HDR10+,DV",
        "audioType": "lossless",
        "channels": "7.1,5.1",
        "profile": "pure,hc_optimized",
        "lang": "VFF,VOSTFR",
        "sortBy": "relevance",
        "sortOrder": "desc",
    }.items():
        assert params[key] == value


def test_live_page_seeded_exclusion_is_explicit_and_unavailable_clients_fail_closed(catalogue_app):
    from pathlib import Path
    from types import SimpleNamespace

    from torrentlinker.domain import Torrent

    app, browser, token, requests = native(catalogue_app)
    app.state.agent_service.setup._client = SimpleNamespace(
        torrents=lambda **kwargs: [
            Torrent("a" * 40, "Already completed", Path("/downloads"), progress=1, state="pausedUP")
        ]
    )
    searched = tool(
        browser,
        token,
        "search_indexer",
        request_id="exclude-completed",
        client_id="default",
        category=-6,
        exclude_seeded=True,
    )
    page = finished(browser, searched["job_id"])["result"]
    assert page["selected_count"] == 0 and page["excluded_seeded_count"] == 1
    assert page["total"] == 41789 and page["has_more"]

    def unavailable(**kwargs):
        raise OSError("Client unavailable")

    app.state.agent_service.setup._client = SimpleNamespace(torrents=unavailable)
    calls_before = len(requests)
    proposed = tool(
        browser,
        token,
        "search_indexer",
        request_id="no-observation",
        client_id="default",
        category=-6,
        exclude_seeded=True,
    )
    assert finished(browser, proposed["job_id"])["status"] == "failed"
    assert len(requests) == calls_before
    assert browser.get("/api/queue").json() == []


def test_live_search_errors_do_not_substitute_matching_cached_titles(catalogue_app):
    def fail(request):
        if request.url.path == "/api/torrents":
            return httpx.Response(500, json={"error": "Unavailable"})

    _, browser, token, _ = native(catalogue_app, fail)
    proposed = tool(
        browser,
        token,
        "search_indexer",
        request_id="native-fails",
        client_id="default",
        query="Film",
    )
    result = finished(browser, proposed["job_id"])
    assert result["status"] == "failed" and result["result"] is None
    assert browser.get("/api/queue").json() == []


def test_native_search_reports_explicit_revival_fallback_metadata(catalogue_app):
    def fallback(request):
        if request.url.path == "/api/torrents":
            payload = listing()
            payload["meta"].update(
                palliativeMatches=0, palliativeFallback=True, palliativeCount=764
            )
            return httpx.Response(200, json=payload)

    _, browser, token, _ = native(catalogue_app, fallback)
    searched = tool(
        browser,
        token,
        "search_indexer",
        request_id="revival-fallback",
        client_id="default",
        query="Example",
        category=-6,
        filters={"palliativeTail": True},
    )
    page = finished(browser, searched["job_id"])["result"]
    assert page["palliative_fallback"] is True and page["palliative_matches"] == 0
    assert page["rows"][0]["revival"] is True
    assert page["rows"][0]["native_category_label"] == "Films & Vidéos / Film"


def test_interactive_agent_read_cannot_clear_a_running_download_guard(catalogue_app, monkeypatch):
    import threading

    from torrentlinker.agent.service import AgentRequest

    app, browser, token = catalogue_app
    service = app.state.agent_service
    actor = service.access.authenticate(token)
    target = service.for_client("default")
    entered, release = threading.Event(), threading.Event()

    def guard(data, folder):
        return None

    def sending(stop, progress):
        target.setup.download_guard = guard
        entered.set()
        assert release.wait(5)
        assert target.setup.download_guard is guard
        target.setup.download_guard = None
        return {}

    monkeypatch.setattr(target, "run", lambda *_: {"read": True})
    send_id = service.jobs.submit("send-queue", sending)
    try:
        assert entered.wait(2)
        read = service.request(
            actor,
            "concurrent-read",
            AgentRequest(kind="details", client_id="default", hashes=["a" * 40]),
        )
        assert finished(browser, read["job_id"])["status"] == "completed"
        assert target.setup.download_guard is guard
        assert service.jobs.get(send_id)["status"] == "running"
    finally:
        release.set()
    assert finished(browser, send_id)["status"] == "completed"
