import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_profile import PROFILE
from tests.test_web_jobs import login
from torrentlinker.profile import parse_profile
from torrentlinker.profile_workspace import ProfileWorkspace

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
INDEXER = "https://c411.org/api/torznab"


def serve(monkeypatch, avatar_url, image=PNG, kind="image/png", seen=None):
    """c411's profile and avatar host, answering by path."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/api/user/profile":
            return httpx.Response(200, json={**PROFILE, "avatarUrl": avatar_url})
        return httpx.Response(200, content=image, headers={"content-type": kind})

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_the_parser_keeps_the_avatar_url():
    assert parse_profile({**PROFILE, "avatarUrl": "/a.png"}).avatar_url == "/a.png"
    assert parse_profile(PROFILE).avatar_url is None


def test_a_refresh_caches_the_avatar_without_sending_the_key(tmp_path, monkeypatch):
    seen: list[httpx.Request] = []
    serve(monkeypatch, "https://cdn.c411.org/avatars/42.png", seen=seen)
    workspace = ProfileWorkspace(tmp_path)

    workspace.refresh(INDEXER, "K")

    image = [r for r in seen if r.url.host == "cdn.c411.org"]
    assert len(image) == 1 and "authorization" not in image[0].headers
    assert workspace.avatar() == (PNG, "image/png")
    assert workspace.state()["avatar"]
    assert (tmp_path / "profile-avatar.img").stat().st_mode & 0o777 == 0o600


def test_a_relative_avatar_is_read_from_the_indexer_site(tmp_path, monkeypatch):
    seen: list[httpx.Request] = []
    serve(monkeypatch, "/uploads/avatars/42.png", seen=seen)
    workspace = ProfileWorkspace(tmp_path)

    workspace.refresh(INDEXER, "K")

    assert str(seen[-1].url) == "https://c411.org/uploads/avatars/42.png"
    assert workspace.avatar() is not None


def test_an_unchanged_avatar_is_not_downloaded_again(tmp_path, monkeypatch):
    seen: list[httpx.Request] = []
    serve(monkeypatch, "https://cdn.c411.org/a.png", seen=seen)
    workspace = ProfileWorkspace(tmp_path)
    workspace.refresh(INDEXER, "K")
    workspace._client = None  # skip the 30-second profile cache

    workspace.refresh(INDEXER, "K")

    assert [r.url.host for r in seen].count("cdn.c411.org") == 1


@pytest.mark.parametrize(
    ("url", "image", "kind"),
    [
        ("https://cdn.c411.org/a.png", b"<html>not an image</html>", "image/png"),
        ("https://cdn.c411.org/a.svg", b"<svg onload=alert(1)>", "image/svg+xml"),
        ("https://cdn.c411.org/a.png", PNG + b"\0" * 2_100_000, "image/png"),
        ("http://cdn.c411.org/a.png", PNG, "image/png"),
        ("https://user:pass@cdn.c411.org/a.png", PNG, "image/png"),
        ("https://127.0.0.1/a.png", PNG, "image/png"),
        ("https://10.0.0.5/a.png", PNG, "image/png"),
    ],
)
def test_unsafe_or_non_image_avatars_fall_back_to_the_initial(
    tmp_path, monkeypatch, url, image, kind
):
    serve(monkeypatch, url, image, kind)
    workspace = ProfileWorkspace(tmp_path)

    workspace.refresh(INDEXER, "K")

    assert workspace.avatar() is None
    assert workspace.state()["avatar"] is None
    assert workspace.state()["api"]["username"] == "viet"  # the refresh itself succeeded


def test_a_removed_avatar_or_new_key_clears_the_cached_image(tmp_path, monkeypatch):
    serve(monkeypatch, "https://cdn.c411.org/a.png")
    workspace = ProfileWorkspace(tmp_path)
    workspace.refresh(INDEXER, "K")
    assert workspace.avatar() is not None

    workspace.bind(INDEXER, "other-key")

    assert workspace.avatar() is None
    assert not (tmp_path / "profile-avatar.img").exists()
    serve(monkeypatch, "https://cdn.c411.org/a.png")
    workspace.refresh(INDEXER, "other-key")
    serve(monkeypatch, None)
    workspace._client = None
    workspace.refresh(INDEXER, "other-key")
    assert workspace.avatar() is None


def test_the_web_avatar_route_serves_the_cached_image(tmp_path, monkeypatch):
    from tests.test_web_profile import prepared

    app, setup = prepared(tmp_path, monkeypatch)
    serve(monkeypatch, "https://cdn.c411.org/a.png")
    with TestClient(app) as browser:
        assert browser.get("/api/zen/profile/avatar").status_code == 401
        login(browser)
        assert browser.get("/api/zen/profile/avatar").status_code == 404
        token = browser.post("/api/zen/profile/refresh", headers={"X-TorrentLinker": "1"}).json()[
            "avatar"
        ]
        response = browser.get(f"/api/zen/profile/avatar?v={token}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == PNG


def test_the_desktop_header_shows_the_avatar_or_the_initial(qtbot, tmp_path, request):
    from tests.test_profile_view import isolated_profile_test

    if isolated_profile_test(request.node.nodeid):
        return
    from PySide6.QtCore import QBuffer, QSettings
    from PySide6.QtGui import QColor, QImage

    from torrentlinker.gui.profile_view import ProfileView

    view = ProfileView(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(view)
    from tests.test_community_interfaces import js, wait_js

    view.show()
    view.show_state({"api": {"username": "viet"}})
    wait_js(qtbot, view, "document.querySelector('#profile-avatar').textContent === 'V'")
    picture = QImage(80, 40, QImage.Format.Format_RGB32)
    picture.fill(QColor("red"))
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    picture.save(buffer, "PNG")

    view.show_avatar(bytes(buffer.data()))
    view.show_state({"api": {"username": "viet", "level": 3}})

    wait_js(qtbot, view, "document.querySelector('#profile-avatar img')?.naturalWidth === 80")
    view.show_avatar(b"not an image")
    wait_js(qtbot, view, "document.querySelector('#profile-avatar').textContent === 'V'")
    assert js(qtbot, view, "document.querySelectorAll('#profile-avatar img').length") == 0
    view.close()
