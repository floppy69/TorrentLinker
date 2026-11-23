import httpx
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage

from tests.test_torrent_search import fake_indexer
from torrentlinker.gui.torrent_details import decode_preview
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.torrent_details import fetch_image, parse_details, preview_html, website_url

DETAILS = {
    "name": "Example",
    "descriptionFormat": "standard",
    "description": '<h2>Synopsis</h2><p>A journey.</p><img src="https://images.example/poster.png">',
    "metadata": {
        "hasNfo": True,
        "nfoContent": "┌── NFO ──┐\n<plain text>\n1080p",
        "tmdbData": {"posterUrl": "https://images.example/poster.png"},
    },
    "files": [{"path": ["Folder", "film.mkv"], "length": 1024}],
}


def png():
    image = QImage(60, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkCyan)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def test_details_parse_flat_response_and_preserve_nfo_as_plain_text():
    details = parse_details(DETAILS)
    assert details.nfo == "┌── NFO ──┐\n<plain text>\n1080p"
    assert details.has_nfo
    assert details.files == (("Folder/film.mkv", 1024),)
    rendered, images = preview_html(details.description, details.poster)
    assert "<h2>Synopsis</h2>" in rendered
    assert images == ("https://images.example/poster.png",)
    assert '<img src="preview-image:0"' in rendered


def test_preview_strips_active_content_and_local_resources_but_keeps_formatting():
    rendered, images = preview_html("""<script>alert(1)</script><style>body{color:red}</style>
      <p style="background:url(file:///etc/passwd)">Hello <strong>world</strong></p>
      <img src="file:///etc/passwd"><img src="https://images.example/a.png" onerror="alert(2)">
      <a href="javascript:alert(3)">bad</a><a href="https://example.org/info">good</a>""")
    assert "alert" not in rendered and "file:" not in rendered and "javascript:" not in rendered
    assert "<strong>world</strong>" in rendered and 'href="https://example.org/info"' in rendered
    assert images == ("https://images.example/a.png",)
    markup, images = preview_html(
        "[b]Title[/b]\n[img]https://images.example/b.png[/img]", "https://images.example/a.png"
    )
    assert "<b>Title</b>" in markup
    assert len(images) == 2


def test_website_links_use_hash_and_reject_non_web_schemes():
    indexer = fake_indexer(lambda r: httpx.Response(200, json=DETAILS))
    assert (
        website_url(Candidate("title", 1, "download", infohash="A" * 40), indexer)
        == "https://c411.org/torrents/" + "a" * 40
    )
    generic = Indexer("https://example.test/api", "key")
    assert not website_url(
        Candidate("title", 1, "download", details_url="file:///tmp/file"), generic
    )
    assert (
        website_url(
            Candidate("title", 1, "download", details_url="https://example.test/details"), generic
        )
        == "https://example.test/details"
    )


def test_image_requests_do_not_send_api_credentials_or_follow_local_redirects(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(ValueError, match="Local"):
        fetch_image("https://images.example/a.png")
    assert len(seen) == 1
    assert "authorization" not in seen[0].headers and "cookie" not in seen[0].headers


def test_image_byte_limit_and_decoder(monkeypatch, qtbot):
    monkeypatch.setattr("torrentlinker.torrent_details.MAX_IMAGE_BYTES", 8)
    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kw: httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, content=b"a" * 9, headers={"content-type": "image/png"}
                )
            ),
            **kw,
        ),
    )
    with pytest.raises(ValueError, match="exceeds"):
        fetch_image("https://images.example/a.png")
    assert not decode_preview(png()).isNull()
    with pytest.raises(ValueError):
        decode_preview(b"not image data")


def test_large_valid_cover_is_not_rejected_by_old_ten_mib_limit(monkeypatch, qtbot):
    # The reported cover is a 17,018,281-byte PNG, well within the decoder's pixel limit.
    content = png() + b"\0" * 17_018_281
    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kw: httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, content=content, headers={"content-type": "image/png"}
                )
            ),
            **kw,
        ),
    )
    assert not decode_preview(fetch_image("https://images.example/cover.png")).isNull()


def test_description_centers_blocks_and_preserves_explicit_alignment(qtbot):
    from torrentlinker.gui.torrent_details import DescriptionBrowser

    browser = DescriptionBrowser()
    qtbot.addWidget(browser)
    markup, _ = preview_html(
        '<h2>Heading</h2><p>Summary</p><p style="text-align: right">Credit</p>'
    )
    browser.setHtml(markup)
    block = browser.document().begin()
    alignments = {}
    while block.isValid():
        if block.text():
            alignments[block.text()] = block.blockFormat().alignment()
        block = block.next()
    assert alignments["Heading"] & Qt.AlignmentFlag.AlignHCenter
    assert alignments["Summary"] & Qt.AlignmentFlag.AlignHCenter
    assert alignments["Credit"] & Qt.AlignmentFlag.AlignRight


RICH = {
    **DETAILS,
    "uploader": "Anonyme",
    "team": {"id": 142, "name": "MTLQC", "slug": "mtlqc"},
    "createdAt": "2026-10-27T23:07:54Z",
    "seeders": 0,
    "leechers": 3,
    "completions": 4,
    "metadata": {
        **DETAILS["metadata"],
        "isExclusive": True,
        "lowBitrateWarning": True,
        "category": {"name": "Films & Vidéos"},
        "subcategory": {"name": "Émission TV"},
        "options": [
            {"name": "Langue", "values": [{"value": "Québecois (VFQ/French)"}]},
            {"name": "Saison", "values": [{"value": "Saison 10"}]},
            {"name": "Vide", "values": []},
        ],
        "tmdbData": {
            "id": 74342,
            "type": "tv",
            "title": "Occupation Double",
            "originalTitle": "Occupation Double",
            "year": 2017,
            "posterUrl": "https://images.example/poster.png",
            "genres": ["Reality"],
            "rating": 4.0,
            "ratingCount": 3,
            "cast": [{"name": "Alicia"}, {"name": "Frédérick"}],
            "directors": ["Jonathan"],
        },
    },
    "externalIds": [{"kind": "imdb", "value": "tt11947282"}, {"kind": "x", "value": "?"}],
    "trust": {
        "status": "untested",
        "isTested": False,
        "positiveCount": 1,
        "negativeCount": 2,
        "minVotesRequired": 3,
    },
}


def test_details_parse_the_facts_the_page_shows():
    d = parse_details(RICH)
    assert (d.uploader, d.team, d.exclusive, d.low_bitrate) == ("Anonyme", "MTLQC", True, True)
    assert (d.seeders, d.leechers, d.completions) == (0, 3, 4)
    assert d.category == "Films & Vidéos" and d.subcategory == "Émission TV"
    assert d.facts == (
        ("Langue", ("Québecois (VFQ/French)",)),
        ("Saison", ("Saison 10",)),
    )
    assert (d.trust.status, d.trust.positive, d.trust.negative, d.trust.required) == (
        "untested",
        1,
        2,
        3,
    )
    assert d.created_at is not None
    m = d.media
    assert m is not None and (m.title, m.year, m.kind, m.rating, m.votes) == (
        "Occupation Double",
        2017,
        "tv",
        4.0,
        3,
    )
    assert m.tmdb_id == "74342" and m.imdb_id == "tt11947282"
    assert m.cast == ("Alicia", "Frédérick") and m.directors == ("Jonathan",)


def test_details_ignore_malformed_facts():
    d = parse_details(
        {
            "team": "nope",
            "trust": [],
            "seeders": "many",
            "metadata": {
                "tmdbData": {"id": "x", "imdbId": "not-an-id", "year": 99999, "rating": 50},
                "options": "bad",
            },
        }
    )
    assert d.team == "" and d.trust.status == "" and d.seeders is None and d.facts == ()
    assert d.media is not None and (d.media.year, d.media.rating) == (None, None)
    assert d.media.tmdb_id == "" and d.media.imdb_id == ""
    assert parse_details({}).media is None
