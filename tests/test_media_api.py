"""Media behavior through authenticated owner APIs and generated local fixtures."""

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from torrentlinker.config import Settings
from torrentlinker.domain import LibraryFolder
from torrentlinker.web.app import create_app


def media_app(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    shutil.copy(Path(__file__).parent / "fixtures/audio/track16.flac", root / "track.flac")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    return create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    ), root


def login(browser):
    browser.headers["X-TorrentLinker"] = "1"
    assert browser.post("/api/login", json={"password": "test-password-long"}).is_success


def scan(browser):
    response = browser.post("/api/media/scan", json={"client_id": "default"})
    assert response.status_code == 202, response.text
    for _ in range(200):
        result = browser.get("/api/jobs/" + response.json()["id"]).json()
        if result["status"] not in {"queued", "running"}:
            assert result["status"] == "completed", result
            return result
        time.sleep(0.01)
    raise AssertionError("Media scan did not finish")


def test_registered_audio_is_playable_without_tracker_or_torrent_client(tmp_path):
    app, root = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        page = browser.get("/api/media", params={"client_id": "default", "kind": "music"})
        assert page.status_code == 200, page.text
        assert page.json()["total"] == 1
        item = page.json()["rows"][0]
        assert item["available"] is True
        assert item["size"] == (root / "track.flac").stat().st_size
        assert str(root) not in page.text
        stream = browser.get(
            f"/api/media/items/{item['id']}/stream?client_id=default",
            headers={"Range": "bytes=0-3"},
        )
        assert stream.status_code == 206, stream.text
        assert stream.content == b"fLaC"
        assert stream.headers["content-range"].startswith("bytes 0-3/")


def test_media_session_resume_and_playlists_persist_and_tokens_isolate_players(tmp_path):
    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default").json()["rows"][0]
        first = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        second = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        response = browser.post(
            "/api/media/sessions/" + first["id"],
            json={"token": first["token"], "action": "play", "media_ids": [item["id"]]},
        )
        assert response.status_code == 200
        sequence = response.json()["commands"][0]["sequence"]
        wrong = browser.post("/api/media/sessions/" + first["id"], json={"token": second["token"]})
        assert wrong.status_code == 400
        browser.post(
            "/api/media/sessions/" + first["id"],
            json={
                "token": first["token"],
                "report": {
                    "current_id": item["id"],
                    "queue": [item["id"]],
                    "position": 12,
                    "duration": 100,
                    "paused": False,
                    "command_ack": sequence,
                },
            },
        )
        assert (
            browser.post(
                "/api/media/sessions/" + first["id"], json={"token": first["token"]}
            ).json()["commands"]
            == []
        )
        assert (
            browser.post(
                "/api/media/sessions/" + second["id"], json={"token": second["token"]}
            ).json()["state"]["current_id"]
            == ""
        )
        saved = browser.post(
            "/api/media/playlists",
            json={"client_id": "default", "name": "Evening", "media_ids": [item["id"]]},
        ).json()
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(tmp_path / "library",),
            monitor_verifications=False,
        )
    ) as browser:
        login(browser)
        assert (
            browser.get("/api/media?client_id=default&view=continue").json()["rows"][0]["position"]
            == 12
        )
        assert browser.get("/api/media/playlists?client_id=default").json() == [saved]


def test_removed_folder_and_replaced_symlink_cannot_stream_saved_media(tmp_path):
    app, root = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default").json()["rows"][0]
        outside = tmp_path / "secret.flac"
        outside.write_bytes(b"private")
        (root / "track.flac").unlink()
        (root / "track.flac").symlink_to(outside)
        response = browser.get(f"/api/media/items/{item['id']}/stream?client_id=default")
        assert response.status_code == 409
        assert b"private" not in response.content
        app.state.agent_service.setup.settings.library_folders = []
        response = browser.get(f"/api/media/items/{item['id']}/stream?client_id=default")
        assert response.status_code == 409


def test_context_chat_binds_only_its_player_without_requiring_a_provider(tmp_path):
    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        first = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        second = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        chat = browser.post(
            "/api/media/sessions/" + first["id"] + "/chat", json={"token": first["token"]}
        )
        assert chat.status_code == 200, chat.text
        conversation = chat.json()["conversation_id"]
        rows = browser.get("/api/assistant/conversations").json()
        assert rows[0]["id"] == conversation
        assert rows[0]["folder"] == "Media"
        assert (
            browser.post(
                "/api/media/sessions/" + first["id"] + "/chat", json={"token": first["token"]}
            ).json()["conversation_id"]
            == conversation
        )
        assert (
            browser.post(
                "/api/media/sessions/" + second["id"] + "/chat", json={"token": first["token"]}
            ).status_code
            == 400
        )


def test_embedded_album_art_is_exposed_as_private_checked_artwork(tmp_path):
    from io import BytesIO

    from mutagen.flac import FLAC, Picture
    from PIL import Image

    app, root = media_app(tmp_path)
    picture = BytesIO()
    Image.new("RGB", (8, 8), "#cc5533").save(picture, format="PNG")
    audio = FLAC(root / "track.flac")
    cover = Picture()
    cover.type, cover.mime, cover.data = 3, "image/png", picture.getvalue()
    audio.add_picture(cover)
    audio.save()
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default&kind=music").json()["rows"][0]
        assert item["artwork_url"]
        image = browser.get("/" + item["artwork_url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG")


def test_incomplete_torrent_paths_are_mapped_before_playback_check(tmp_path):
    from torrentlinker.domain import PathMapping, Torrent

    app, root = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        agent = app.state.agent_service
        agent.setup.settings.path_mappings = [PathMapping(str(root), "/downloads")]
        target = agent.for_client("default")
        target.observed = [
            Torrent(
                "a" * 40,
                "track.flac",
                Path("/downloads"),
                {"track.flac": (root / "track.flac").stat().st_size},
                progress=0.5,
            )
        ]
        item = browser.get("/api/media?client_id=default").json()["rows"][0]
        assert item["available"] is False
        assert item["availability"] == "unfinished"
        assert (
            browser.get(f"/api/media/items/{item['id']}/stream?client_id=default").status_code
            == 409
        )


def test_subtitle_conversion_and_range_rejection_do_not_read_outside_library(tmp_path):
    app, root = media_app(tmp_path)
    (root / "Film.2026.mp4").write_bytes(b"generated-test-video")
    (root / "Film.2026.en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default&kind=video").json()["rows"][0]
        subtitle = item["subtitles"][0]
        endpoint = f"/api/media/items/{item['id']}/subtitles/{subtitle['id']}?client_id=default"
        response = browser.get(endpoint)
        assert response.status_code == 200
        assert response.text.startswith("WEBVTT")
        assert "00:00:01.000 --> 00:00:02.000" in response.text
        (root / "Film.2026.en.srt").unlink()
        (root / "Film.2026.en.srt").symlink_to("/etc/passwd")
        assert browser.get(endpoint).status_code == 404
        assert (
            browser.get(
                f"/api/media/items/{item['id']}/stream?client_id=default",
                headers={"Range": "bytes=900000-"},
            ).status_code
            == 416
        )


def test_a_refresh_says_whether_the_library_changed(tmp_path):
    app, root = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        assert scan(browser)["result"]["changed"] is True
        assert scan(browser)["result"]["changed"] is False  # nothing new: no reload
        (root / "Film.2026.mp4").write_bytes(b"generated-test-video")
        assert scan(browser)["result"]["changed"] is True
        (root / "Film.2026.mp4").unlink()
        assert scan(browser)["result"]["changed"] is True


def test_refresh_picks_up_new_video_sidecars_without_changing_video(tmp_path):
    app, root = media_app(tmp_path)
    (root / "Film.2026.mp4").write_bytes(b"generated-test-video")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        before = browser.get("/api/media?client_id=default&kind=video").json()["rows"][0]
        assert before["description"] == ""
        (root / "Film.2026.nfo").write_text(
            "<movie><title>Verified title</title><plot>A local story.</plot>"
            '<uniqueid type="tmdb">42</uniqueid></movie>'
        )
        (root / "Film.2026.en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        scan(browser)
        after = browser.get("/api/media?client_id=default&kind=video").json()["rows"][0]
        assert after["id"] == before["id"]
        assert after["title"] == "Verified title"
        assert after["description"] == "A local story."
        assert len(after["subtitles"]) == 1


def test_unavailable_mount_keeps_inventory_and_streams_require_owner_auth(tmp_path):
    app, root = media_app(tmp_path)
    with TestClient(app) as browser:
        assert browser.get("/api/media/items/missing/stream").status_code == 401
        login(browser)
        assert (
            browser.post(
                "/api/media/scan", json={"client_id": "default"}, headers={"X-TorrentLinker": "0"}
            ).status_code
            == 403
        )
        scan(browser)
        item = browser.get("/api/media?client_id=default").json()["rows"][0]
        head = browser.head(f"/api/media/items/{item['id']}/stream?client_id=default")
        assert head.status_code == 200
        assert head.content == b""
        root.rename(tmp_path / "offline-library")
        scan(browser)
        page = browser.get("/api/media?client_id=default").json()
        assert page["total"] == 1
        assert page["rows"][0]["available"] is False
        assert page["errors"]


@pytest.mark.parametrize("partial_suffix", ["", ".!qB"])
def test_explicit_sequential_preview_never_serves_download_gaps(tmp_path, partial_suffix):
    from torrentlinker.domain import Torrent

    app, root = media_app(tmp_path)
    logical_name = "Film.2026.mp4"
    source = root / (logical_name + partial_suffix)
    source.write_bytes(b"V" * 16384 + b"UNVERIFIED" * 2000)
    total = 65536

    class SequentialQbit:
        sequential = True
        pieces = [2, 0, 2, 0]

        def torrents(self, **_kwargs):
            return [self.torrent("a" * 40)]

        def torrent(self, _hash, **_kwargs):
            return Torrent("a" * 40, logical_name, root, {logical_name: total}, progress=0.4)

        def media_preview_state(self, _hash):
            return {
                "sequential": self.sequential,
                "files": [{"name": logical_name, "size": total, "piece_range": [0, 3]}],
                "piece_size": 16384,
                "piece_states": self.pieces,
            }

    client = SequentialQbit()
    # External Torrent Client adapter fixture, while every observation is through owner APIs.
    app.state.agent_service.setup._client = client
    app.state.agent_service.setup.configured = True
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default&kind=video").json()["rows"][0]
        assert not item["available"]
        assert (
            browser.get(f"/api/media/items/{item['id']}/stream?client_id=default").status_code
            == 409
        )
        preview = browser.post(
            f"/api/media/items/{item['id']}/preview", json={"client_id": "default"}
        )
        assert preview.status_code == 200, preview.text
        data = preview.json()
        assert data["verified_bytes"] == 16384
        endpoint = f"/api/media/previews/{data['preview_id']}/stream?client_id=default"
        assert browser.get(endpoint, headers={"Range": "bytes=0-3"}).content == b"VVVV"
        assert browser.get(endpoint, headers={"Range": "bytes=16384-16390"}).status_code == 416
        assert b"UNVERIFIED" not in browser.get(endpoint).content
        player = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        browser.post(
            "/api/media/sessions/" + player["id"],
            json={
                "token": player["token"],
                "report": {
                    "queue": [item["id"]],
                    "current_id": item["id"],
                    "position": 100,
                    "duration": 100,
                    "paused": True,
                },
                "context": {"preview_id": data["preview_id"]},
            },
        )
        progress = browser.get(f"/api/media/items/{item['id']}?client_id=default").json()
        assert progress["position"] == 100
        assert progress["watched"] is False
        client.sequential = False
        assert browser.get(endpoint).status_code == 409


def test_movie_group_chooses_an_accessible_release_and_availability_filter_is_current(tmp_path):
    app, root = media_app(tmp_path)
    for name in ("A", "B"):
        (root / f"{name}.mp4").write_bytes(b"generated-test-video")
        (root / f"{name}.nfo").write_text(
            '<movie><title>One film</title><uniqueid type="tmdb">42</uniqueid></movie>'
        )
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        original = browser.get("/api/media?client_id=default&kind=video").json()["rows"][0]
        (root / original["release"]).unlink()
        grouped = browser.get("/api/media?client_id=default&kind=video").json()["rows"]
        assert len(grouped) == 1
        assert grouped[0]["available"] is True
        assert grouped[0]["id"] != original["id"]
        available = browser.get(
            "/api/media?client_id=default&kind=video&availability=available"
        ).json()
        assert all(row["available"] for row in available["rows"])
        unavailable = browser.get(
            "/api/media?client_id=default&kind=video&availability=unavailable"
        ).json()
        assert len(unavailable["rows"]) == 1
        assert unavailable["rows"][0]["available"] is False


def test_episode_details_have_explicit_pagination(tmp_path):
    app, root = media_app(tmp_path)
    for episode in range(1, 6):
        (root / f"Show.S01E{episode:02}.mp4").write_bytes(b"generated-test-video")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default&kind=video").json()["rows"][0]
        endpoint = f"/api/media/items/{item['id']}?client_id=default&limit=2"
        first = browser.get(endpoint).json()
        assert first["episodes_total"] == 5
        assert len(first["episodes"]) == 2
        assert first["episodes_next_offset"] == 2
        second = browser.get(endpoint + "&episodes_offset=2").json()
        assert second["episodes"][0]["episode"] == 3


def test_invalid_player_command_does_not_poison_later_commands(tmp_path):
    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        player = browser.post("/api/media/sessions", json={"client_id": "default"}).json()
        endpoint = "/api/media/sessions/" + player["id"]
        assert (
            browser.post(endpoint, json={"token": player["token"], "action": "seek"}).status_code
            == 400
        )
        assert (
            browser.post(
                endpoint, json={"token": player["token"], "report": {"index": "not-an-index"}}
            ).status_code
            == 400
        )
        result = browser.post(endpoint, json={"token": player["token"], "action": "pause"}).json()
        assert [command["action"] for command in result["commands"]] == ["pause"]


def test_refresh_removes_moved_files_from_available_folder(tmp_path):
    app, root = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        (root / "track.flac").rename(tmp_path / "moved.flac")
        scan(browser)
        page = browser.get("/api/media?client_id=default&kind=music").json()
        assert page["total"] == 0
        assert page["rows"] == []


@pytest.mark.parametrize(
    "kind", ["qbittorrent", "transmission", "deluge", "rtorrent", "utorrent", "bittorrent"]
)
def test_partial_preview_capability_follows_selected_client(tmp_path, kind):
    app, root = media_app(tmp_path)
    (root / "Downloading.mp4.!qB").write_bytes(b"incomplete fixture")
    settings = app.state.agent_service.setup.settings
    settings.client = kind
    settings.capture_client()
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        rows = browser.get("/api/media?client_id=default&kind=video").json()["rows"]
        assert len(rows) == 1
        assert rows[0]["availability"] == "unfinished"
        assert rows[0]["preview_supported"] is (kind == "qbittorrent")
        detail = browser.get(f"/api/media/items/{rows[0]['id']}?client_id=default").json()
        assert detail["preview_supported"] is (kind == "qbittorrent")
