"""XXX in Search: c411's API hides it from the key, so it is read through the signed-in
session, or by Torznab with a note. c411 is mocked entirely."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from tests.test_torrent_search import FACETS, TREE, fake_indexer, listing
from torrentlinker.companion_downloads import CompanionDownloads, SessionFetchError
from torrentlinker.indexer_search import IndexerFilters, search_options
from torrentlinker.torrent_search import native_search, parse_tree

XXX_ROOT = {
    "id": 8,
    "name": "XXX",
    "slug": "xxx",
    "subcategories": [
        {"id": 42, "name": "Ebooks", "slug": "ebooks"},
        {"id": 43, "name": "Films", "slug": "films"},
        {"id": 44, "name": "Hentai", "slug": "hentai"},
        {"id": 45, "name": "Images", "slug": "images"},
        {"id": 46, "name": "Jeux", "slug": "jeux"},
        {"id": 56, "name": "VR", "slug": "vr"},
    ],
}
XXX_FACETS = {
    "data": [{"slug": "langue", "name": "Langue", "values": [{"id": 900, "value": "Français"}]}]
}
TORZNAB = (
    '<?xml version="1.0"?><rss xmlns:torznab="http://torznab.com/schemas/2015/feed">'
    "<channel><item><title>Scene</title><size>10</size>"
    '<enclosure url="https://c411.org/api?t=get&amp;id=' + "b" * 40 + '&amp;apikey=test-key"/>'
    '<torznab:attr name="infohash" value="' + "b" * 40 + '"/>'
    '<torznab:attr name="seeders" value="3"/><torznab:attr name="category" value="6010"/>'
    "</item></channel></rss>"
)


class Session:
    """A paired companion: answers the fixed pages, like the signed-in tab would."""

    def __init__(self, available=True):
        self.can_read = available
        self.asked = []

    def read_json(self, path):
        self.asked.append(path)
        if path == "/api/categories":
            return {"data": [*TREE["data"], XXX_ROOT]}
        if path.endswith("/filter-options"):
            return XXX_FACETS
        listed = listing()
        listed["data"][0].update(
            name="Adult film",
            category={"id": 8, "name": "XXX"},
            subcategory={"id": 43, "name": "Films"},
        )
        return listed


def indexer(session=None, adult=True):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/categories":
            return httpx.Response(200, json=TREE)
        if request.url.path == "/api":
            return httpx.Response(200, content=TORZNAB)
        return httpx.Response(200, json=listing())

    ix = fake_indexer(handler)
    ix.session = session
    ix.adult_content = lambda: adult
    return ix, calls


def test_the_key_tree_has_no_xxx_and_the_session_merges_it_with_its_subcategories():
    session = Session()
    ix, calls = indexer(session)
    tree = parse_tree(ix.search_categories())
    assert {1, 2, 8} <= set(tree.categories)
    assert {-42, -43, -44, -45, -46, -56} <= set(tree.categories)
    assert tree.root(-44) == 8 and not tree.torznab_only
    assert [c.url.path for c in calls] == ["/api/categories"]  # the key never asks for 8
    assert session.asked == ["/api/categories"]
    ix.search_categories()
    assert session.asked == ["/api/categories"]  # the XXX tree is reused


def test_session_filters_and_search_for_xxx_use_the_session_only():
    session = Session()
    ix, calls = indexer(session)
    options = search_options(ix, 8, {})
    assert options["adult_filters"] == ""
    assert [f["slug"] for f in options["facets"]] == ["langue"]
    page = native_search(ix, {"category": "8", "name": "scene", "subcat": "43"})
    assert page.rows[0].title == "Adult film" and page.labels["a" * 40] == "XXX / Films"
    path, query = session.asked[-1].split("?")
    assert path == "/api/torrents"
    assert parse_qs(query)["category"] == ["8"] and parse_qs(query)["name"] == ["scene"]
    assert all(c.url.path == "/api/categories" for c in calls)  # nothing XXX through the key


def test_everything_else_stays_on_the_key():
    session = Session()
    ix, calls = indexer(session)
    native_search(ix, {"category": "1", "name": "film"})
    search_options(ix, 1, {})
    assert session.asked == [] or session.asked == ["/api/categories"]
    assert [c.url.path for c in calls if c.url.path != "/api/categories"] == [
        "/api/torrents",
        "/api/categories/1/filter-options",
    ]


@pytest.mark.parametrize("session", [None, Session(available=False)])
def test_without_a_session_xxx_comes_from_torznab_with_the_note(session):
    ix, calls = indexer(session)
    tree = parse_tree(ix.search_categories())
    assert tree.torznab_only == {8} and -42 in tree.categories
    options = search_options(ix, 8, {})
    assert options["adult_filters"] == "extension" and options["facets"] == []
    page = native_search(ix, {"category": "8", "name": "scene", "subcat": "43,44"})
    assert [c.title for c in page.rows] == ["Scene"]
    params = parse_qs(calls[-1].url.query.decode())
    assert params["t"] == ["search"] and params["q"] == ["scene"]
    assert params["cat"] == ["6010,6070"] and params["offset"] == ["0"]
    assert not any("category=8" in str(c.url) for c in calls)
    with pytest.raises(ValueError, match="extension"):
        IndexerFilters(year=2020).validate_native(ix, 8, "scene")
    assert IndexerFilters().validate_native(ix, 8, "scene")["category"] == "8"


def test_a_refused_session_read_falls_back_to_torznab():
    class Refusing(Session):
        def read_json(self, path):
            raise SessionFetchError("refused", 429, 60)

    ix, calls = indexer(Refusing())
    assert parse_tree(ix.search_categories()).torznab_only == {8}
    assert [c.title for c in native_search(ix, {"category": "8"}).rows] == ["Scene"]


def test_with_adult_content_off_xxx_is_nowhere():
    session = Session()
    ix, calls = indexer(session, adult=False)
    assert 8 not in parse_tree(ix.search_categories()).categories
    assert 8 not in search_options(ix, None, {})["categories"]
    assert ix.search_filter_options(8) == {"data": []}
    with pytest.raises(ValueError, match="Adult"):
        native_search(ix, {"category": "8"})
    with pytest.raises(ValueError, match="Unknown"):
        search_options(ix, 8, {})
    assert session.asked == []
    assert [c.url.path for c in calls] == ["/api/categories"] * 3 or all(
        c.url.path == "/api/categories" for c in calls
    )


def test_a_key_tree_that_one_day_includes_xxx_is_left_alone():
    session = Session()
    ix, _ = indexer(session)
    ix._http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": [*TREE["data"], XXX_ROOT]})
        )
    )
    assert 8 in parse_tree(ix.search_categories()).categories
    assert session.asked == []


def test_search_options_keep_non_xxx_facets_for_the_key():
    ix, _ = indexer(None)
    assert FACETS and search_options(ix, None, {})["adult_filters"] == ""


def test_companion_reads_only_fixed_adult_pages_and_polls_them_without_downloads():
    now = [100.0]
    jobs = CompanionDownloads(lambda: now[0])
    jobs.poll("acct", 1, reads_only=True)  # the tab is there
    for path in (
        "/api/torrents?category=1",
        "/api/user/profile",
        "/api/categories/1/filter-options",
    ):
        with pytest.raises(ValueError, match="cannot be read"):
            jobs.submit_read(path)
    job = jobs.submit_read("/api/torrents?category=8&name=x&page=1")
    batch = jobs.poll("acct", 5, reads_only=True)["commands"]
    assert batch == [{"id": job["id"], "path": job["path"], "accountId": "acct"}]
    assert jobs.receive({"id": job["id"], "status": 200, "data": json.dumps({"data": []})})
    assert jobs.take_json(job["id"]) == {"data": []}
    other = jobs.submit_read("/api/categories")
    jobs.poll("acct", 5, reads_only=True)
    jobs.receive({"id": other["id"], "status": 429, "retryAfter": 5})
    assert jobs.get(other["id"], "app")["status"] == "failed"
    with pytest.raises(ValueError, match="wait"):
        jobs.submit_read("/api/categories")
