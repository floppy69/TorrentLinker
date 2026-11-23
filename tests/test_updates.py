import json

import httpx
import pytest

from torrentlinker import updates
from torrentlinker.updates import CHECK_INTERVAL, Release, check_for_update


def mock_release(monkeypatch, payload=None, *, status=200, error=None):
    calls = []

    def respond(request):
        calls.append(request)
        if error:
            raise error
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(
        updates.net,
        "client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(respond), **kw),
    )
    return calls


def stable(tag="v0.5.0"):
    return {"tag_name": tag, "draft": False, "prerelease": False}


def test_web_shell_checks_the_running_server_version_after_login(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from torrentlinker.web import app as web_app

    monkeypatch.setattr(web_app, "installed_version", lambda: "0.4.0")
    calls = mock_release(monkeypatch, stable())
    with TestClient(web_app.create_app(tmp_path, password="test-password-long")) as browser:
        assert browser.get("/api/shell").status_code == 401
        assert not calls
        browser.post(
            "/api/login", json={"password": "test-password-long"}, headers={"X-TorrentLinker": "1"}
        )
        expected = {
            "version": "0.4.0",
            "release": {
                "tag": "v0.5.0",
                "url": Release("v0.5.0").url,
            },
        }
        shell = browser.get("/api/shell").json()
        assert shell["actor"]["owner"]
        assert {k: shell[k] for k in expected} == expected
        assert {k: v for k, v in browser.get("/api/shell").json().items() if k in expected} == (
            expected
        )
        assert len(calls) == 1


@pytest.mark.parametrize(
    ("current", "tag", "newer"),
    [
        ("0.4.0", "v0.5.0", True),
        ("0.9.0", "v0.10.0", True),
        ("0.4.0", "v0.4.0", False),
        ("0.5.0", "v0.4.0", False),
        ("0.5.0rc1", "v0.5.0", False),
        ("unknown", "v0.5.0", False),
    ],
)
def test_only_newer_stable_versions_notify(monkeypatch, tmp_path, current, tag, newer):
    mock_release(monkeypatch, stable(tag))
    result = check_for_update(tmp_path / "release.json", current=current)
    assert result == (Release(tag) if newer else None)
    if result:
        assert result.url == f"https://github.com/Vietnoirien/TorrentLinker/releases/tag/{tag}"


@pytest.mark.parametrize(
    "payload",
    [
        {**stable(), "prerelease": True},
        {**stable(), "draft": True},
        stable("v0.5.0-beta.1"),
        stable("https://example.test"),
        stable(5),
        {},
        [],
        None,
    ],
)
def test_invalid_or_preview_releases_are_ignored(monkeypatch, tmp_path, payload):
    mock_release(monkeypatch, payload)
    assert check_for_update(tmp_path / "release.json", current="0.4.0") is None


def test_cache_is_recompared_to_the_running_version(monkeypatch, tmp_path):
    clock = [100000.0]
    monkeypatch.setattr(updates.time, "time", lambda: clock[0])
    calls = mock_release(monkeypatch, stable())
    cache = tmp_path / "release.json"
    assert check_for_update(cache, current="0.4.0") == Release("v0.5.0")
    assert check_for_update(cache, current="0.4.0") == Release("v0.5.0")
    assert check_for_update(cache, current="0.5.0") is None
    assert len(calls) == 1
    assert str(calls[0].url) == updates.LATEST_RELEASE
    assert "authorization" not in calls[0].headers
    clock[0] += CHECK_INTERVAL
    check_for_update(cache, current="0.4.0")
    assert len(calls) == 2


def test_new_release_is_found_after_thirty_minutes(monkeypatch, tmp_path):
    clock = [100000.0]
    monkeypatch.setattr(updates.time, "time", lambda: clock[0])
    cache = tmp_path / "release.json"
    mock_release(monkeypatch, stable("v0.5.0"))
    assert check_for_update(cache, current="0.5.0") is None
    calls = mock_release(monkeypatch, stable("v0.5.1"))
    clock[0] += 1799
    assert check_for_update(cache, current="0.5.0") is None
    assert not calls
    clock[0] += 1
    assert check_for_update(cache, current="0.5.0") == Release("v0.5.1")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_api_failures_are_silent_and_can_retry(monkeypatch, tmp_path, status):
    calls = mock_release(monkeypatch, status=status)
    cache = tmp_path / "release.json"
    assert check_for_update(cache, current="0.4.0") is None
    assert not cache.exists()
    assert len(calls) == 1


def test_offline_and_unwritable_cache_do_not_block_use(monkeypatch, tmp_path):
    cache = tmp_path / "release.json"
    mock_release(monkeypatch, error=httpx.ConnectTimeout("offline"))
    assert check_for_update(cache, current="0.4.0") is None
    mock_release(monkeypatch, stable())
    cache.mkdir()
    assert check_for_update(cache, current="0.4.0") == Release("v0.5.0")


@pytest.mark.parametrize(
    "content",
    ["{bad json", "[]", '{"tag":5,"checked_at":0}', '{"tag":"v0.5.0","checked_at":"wrong"}'],
)
def test_bad_cache_is_refetched(monkeypatch, tmp_path, content):
    cache = tmp_path / "release.json"
    cache.write_text(content)
    calls = mock_release(monkeypatch, stable())
    assert check_for_update(cache, current="0.4.0") == Release("v0.5.0")
    assert len(calls) == 1


def test_clock_moving_backwards_does_not_cache_forever(monkeypatch, tmp_path):
    monkeypatch.setattr(updates.time, "time", lambda: 100)
    cache = tmp_path / "release.json"
    cache.write_text(json.dumps({"tag": "v0.5.0", "checked_at": 200}))
    calls = mock_release(monkeypatch, stable())
    check_for_update(cache, current="0.4.0")
    assert len(calls) == 1


def test_notice_opens_release_and_remembers_dismissal(qtbot, monkeypatch):
    from torrentlinker.gui.update_notice import QDesktopServices, UpdateNotice

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    notice = UpdateNotice()
    qtbot.addWidget(notice)
    assert notice.isHidden()
    notice.show_release(None)
    assert notice.isHidden()
    notice.show_release(Release("v0.5.0"))
    assert not notice.isHidden()
    notice.command("release", {})
    assert opened == [Release("v0.5.0").url]
    notice.command("dismiss", {})
    notice.show_release(Release("v0.5.0"))
    assert notice.isHidden()
    notice.show_release(Release("v0.6.0"))
    assert not notice.isHidden()


def test_main_window_checks_in_background(qtbot, tmp_path, monkeypatch):
    import threading

    from torrentlinker.config import Settings
    from torrentlinker.gui import main_window
    from torrentlinker.store import Store

    entered, release = threading.Event(), threading.Event()
    cache_paths = []
    compared_versions = []

    def check(cache, *, current=None):
        cache_paths.append(cache)
        compared_versions.append(current)
        entered.set()
        release.wait(5)
        return Release("v0.5.0")

    monkeypatch.setattr(main_window, "check_for_update", check)
    monkeypatch.setattr(main_window, "installed_version", lambda: "0.5.0")
    window = main_window.MainWindow(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    # Installing an update on disk must not change the version of this running window.
    monkeypatch.setattr(main_window, "installed_version", lambda: "0.5.1")
    try:
        window.check_for_updates()
        qtbot.waitUntil(entered.is_set)
        # Navigation still responds while the network worker is waiting.
        window.tabs.setCurrentIndex(1)
        assert window.tabs.currentIndex() == 1
        assert window.update_notice.isHidden()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not window.update_notice.isHidden())
    assert cache_paths == [tmp_path / "release-check.json"]
    assert compared_versions == ["0.5.0"]
