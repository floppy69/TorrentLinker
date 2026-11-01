"""Opt-in browser playback through owner HTTP APIs and real local media."""

import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def open_films_grid(page):
    """Films shows rows; a row's See all opens the card grid these steps use."""
    from playwright.sync_api import expect

    page.locator('[data-media-view="films"]').click()
    expect(page.locator("#media-home-rows")).to_be_visible(timeout=15000)
    page.locator("#media-home-rows .media-home-row").first.get_by_role(
        "button", name="See all", exact=True
    ).click()
    expect(page.locator("#media-results")).to_be_visible()


def player_action(page, identifier):
    control = page.locator(identifier)
    if not control.is_visible():
        page.locator("#media-player-menu-toggle").focus()
        page.locator("#media-player-menu-toggle").press("Enter")
    control.click()


def test_media_playback_survives_browsing_and_contextual_chat(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_agent_media import invoke
    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for a real playable video fixture")
    root = tmp_path / "media"
    root.mkdir()
    subprocess.run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=10",
            "-t",
            "20",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(root / "Validation.Film.2026.mp4"),
        ],
        check=True,
    )
    (root / "Validation.Film.2026.en.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nValidation subtitle\n"
    )
    shutil.copy(Path(__file__).parent / "fixtures/audio/track16.flac", root / "Validation.flac")
    shutil.copy(Path(__file__).parent / "fixtures/audio/track24.flac", root / "Second.flac")
    (root / "Unsupported.Video.mp4").write_bytes(b"An unsupported local media container")
    edition = root / "Different edition"
    edition.mkdir()
    shutil.copy(root / "Validation.flac", edition / "Validation.flac")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with ThreadPoolExecutor(max_workers=1) as model, sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            page = browser.new_page(
                viewport={"width": 1280, "height": 900}, locale="en-US", has_touch=True
            )

            def choose_layout(value):
                options = page.locator("#media-library-options")
                if not options.evaluate("node => node.open"):
                    options.locator("summary").click()
                page.locator("#media-layout-switch").select_option(value)
                options.locator("summary").click()

            reports = []
            report_statuses = []
            pending_commands = []
            response_failure = {}
            command_sequence = 0

            def player_transport(route):
                body = route.request.post_data_json
                response = route.fetch()
                if body and body.get("report"):
                    reports.append(body["report"])
                    report_statuses.append(response.status)
                    payload = response.json()
                    payload["commands"] = [*payload.get("commands", []), *pending_commands]
                    pending_commands.clear()
                    if response_failure:
                        payload["state"]["track_request"] = dict(response_failure)
                        response_failure.clear()
                    route.fulfill(response=response, json=payload)
                else:
                    route.fulfill(response=response)

            def wait_report(predicate):
                for _ in range(120):
                    if reports and predicate(reports[-1]):
                        return reports[-1]
                    page.wait_for_timeout(50)
                raise AssertionError(f"Expected player report, received {reports[-1:]}")

            def send_player_command(command):
                nonlocal command_sequence
                command_sequence = max(command_sequence, reports[-1]["command_ack"]) + 1
                pending_commands.append({"sequence": command_sequence, **command})
                return wait_report(lambda report: report["command_ack"] >= command_sequence)

            page.route("**/api/media/sessions/*", player_transport)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator('[data-view="media"]').click()
            expect(page.locator("#view-media")).to_have_attribute("data-layout", "cinematic")
            # The toolbar ⟳ refreshes the library and shows that a refresh is running.
            page.locator("#media-toolbar-refresh").click()
            expect(page.locator("#media-toolbar-refresh")).to_have_attribute("aria-pressed", "true")
            expect(page.locator("#media-toolbar-refresh")).to_have_attribute(
                "aria-pressed", "false", timeout=15000
            )
            # The video home shows rows; the card grid is under Films.
            expect(page.locator("#media-home-rows")).to_contain_text("Validation", timeout=15000)
            page.locator("#media-home-rows .media-home-row").first.get_by_role(
                "button", name="See all", exact=True
            ).click()
            expect(page.locator("#media-home-rows")).to_be_hidden()
            expect(page.locator("#media-results")).to_contain_text("Validation")
            open_films_grid(page)
            expect(page.locator("#media-results")).to_contain_text("Validation", timeout=15000)
            page.locator(".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Details", exact=True
            ).click()
            expect(page.locator("#media-details")).to_contain_text("External subtitle files")
            expect(page.locator("#media-details")).to_contain_text("Validation.Film.2026.en")
            assert page.locator("#media-video").get_attribute("src") is None
            page.get_by_role("button", name="Close details", exact=True).click()
            page.locator(".media-card").filter(has_text="Unsupported Video").get_by_role(
                "button", name="Details", exact=True
            ).click()
            expect(page.locator("#media-details")).to_contain_text(
                "No external subtitle files are known for this release."
            )
            expect(page.locator("#media-details")).to_contain_text("Embedded subtitle tracks")
            page.get_by_role("button", name="Close details", exact=True).click()
            page.locator(".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            video = page.locator("#media-video")
            page.wait_for_function("() => document.querySelector('#media-video').currentTime > 0.1")
            source = video.get_attribute("src")
            video_element = video.element_handle()
            control_screenshots = os.getenv("TL_MEDIA_SCREENSHOT_DIR") or os.getenv(
                "TL_WEB_SCREENSHOTS"
            )
            if control_screenshots:
                Path(control_screenshots).mkdir(parents=True, exist_ok=True)
            video.evaluate("node => node.pause()")
            expect(page.locator("#media-player-menu-toggle")).to_be_visible()
            page.locator("#media-player-menu-toggle").focus()
            page.keyboard.press("Enter")
            expect(page.get_by_role("dialog", name="Player options", exact=True)).to_be_visible()
            expect(page.get_by_label("Subtitle track", exact=True)).to_be_visible()
            expect(page.get_by_label("Audio track", exact=True)).to_be_hidden()
            page.get_by_label("Subtitle track", exact=True).select_option("subtitle:0")
            assert video.evaluate("node => node.textTracks[0].mode") == "showing"
            video.evaluate("node => { node.currentTime = 1; }")
            page.wait_for_function(
                "() => document.querySelector('#media-video').textTracks[0].activeCues?.length > 0"
            )
            page.keyboard.press("Escape")
            expect(page.locator("#media-player-menu")).to_be_hidden()
            expect(page.locator("#media-player-menu-toggle")).to_be_focused()
            if control_screenshots:
                page.screenshot(path=str(Path(control_screenshots) / "player-caption-controls.png"))
            video.evaluate("node => node.play()")
            page.locator("#media-search").focus()
            page.mouse.move(20, 20)
            expect(page.locator(".media-video-overlay")).to_have_css("opacity", "0")
            video.evaluate("node => node.pause()")
            expect(page.locator(".media-video-overlay")).to_have_css("opacity", "1")
            video.click(button="right", position={"x": 40, "y": 40})
            expect(page.locator("#media-player-menu")).to_be_visible()
            page.keyboard.press("Tab")
            expect(page.get_by_label("Subtitle track", exact=True)).to_be_focused()
            page.get_by_label("Subtitle track", exact=True).select_option("off")
            assert video.evaluate("node => node.textTracks[0].mode") == "disabled"
            page.locator("#media-queue-details summary").click()
            queue_remove = page.locator("#media-player-queue").get_by_role("button", name="Remove")
            queue_remove.focus()
            page.wait_for_timeout(1200)
            expect(queue_remove).to_be_focused()
            page.locator("#media-queue-details summary").click()
            if control_screenshots:
                page.screenshot(path=str(Path(control_screenshots) / "player-context-menu.png"))
            page.locator("#media-player-menu-close").click()
            page.locator("#media-player-menu-toggle").tap()
            expect(page.locator("#media-player-menu")).to_be_visible()
            page.locator("#media-player-menu-close").click()
            page.locator("#media-video-stage").focus()
            page.keyboard.press("Shift+F10")
            expect(page.locator("#media-player-menu")).to_be_visible()
            page.keyboard.press("Escape")
            assert video_element.evaluate("node => node === document.querySelector('#media-video')")
            assert video.get_attribute("src") == source
            expect(page.locator("#media-playing-description")).to_contain_text("0:20")
            assert (
                not page.locator("#media-video-stage").locator("#media-playing-description").count()
            )
            video.evaluate("node => node.play()")
            expect(page.locator("#media-track-support")).to_contain_text(
                "If sound or a track is missing"
            )
            expect(page.locator("#media-track-external")).to_have_attribute("href", source)
            track_report = wait_report(lambda report: report.get("track_state", {}).get("ready"))
            track_state = track_report["track_state"]
            assert track_state["subtitle_supported"]
            assert re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                track_state["source_token"],
            )
            assert track_state["subtitles"][0]["language"] == "en"
            assert track_state["subtitles"][0]["id"] == "subtitle:0"
            original_label = video.locator("track").get_attribute("label")
            long_label = "Long track " + "𝄞" * 320
            video.locator("track").evaluate(
                "(track, label) => { track.label = label; }", long_label
            )
            bounded = wait_report(
                lambda report: report["track_state"]["subtitles"][0]["label"].startswith(
                    "Long track"
                )
            )
            assert bounded["track_state"]["subtitles"][0]["label"] == long_label[:300]
            assert report_statuses[-1] == 200
            assert video.locator("track").get_attribute("label") == long_label
            video.locator("track").evaluate(
                "(track, label) => { track.label = label; }", original_label
            )
            selected = send_player_command(
                {
                    "action": "select_track",
                    "kind": "subtitle",
                    "track_id": "subtitle:0",
                    "source_token": track_state["source_token"],
                    "media_id": track_state["media_id"],
                }
            )
            assert selected["track_result"]["applied"]
            assert selected["track_state"]["subtitles"][0]["selected"]
            video.evaluate("v => { v.currentTime = 1; }")
            page.wait_for_function(
                "() => document.querySelector('#media-video').textTracks[0].activeCues?.length > 0"
            )
            assert (
                video.evaluate("v => v.textTracks[0].activeCues[0].text") == "Validation subtitle"
            )
            rejected = send_player_command(
                {
                    "action": "select_track",
                    "kind": "audio",
                    "track_id": "audio:0",
                    "source_token": track_state["source_token"],
                    "media_id": track_state["media_id"],
                }
            )
            assert not rejected["track_result"]["applied"]
            assert "unavailable" in rejected["track_result"]["error"].lower()
            off = send_player_command(
                {
                    "action": "select_track",
                    "kind": "subtitle",
                    "track_id": "off",
                    "source_token": track_state["source_token"],
                    "media_id": track_state["media_id"],
                }
            )
            assert off["track_result"]["applied"]
            assert video.evaluate("v => v.textTracks[0].mode") == "disabled"
            loading_subtitles = []

            def hold_subtitles(route):
                loading_subtitles.append((route, route.fetch()))

            subtitle_pattern = "**/api/media/items/*/subtitles/*?*"
            page.route(subtitle_pattern, hold_subtitles)
            page.locator("#media-player-menu-toggle").focus()
            page.locator("#media-player-menu-toggle").press("Enter")
            expect(page.locator("#media-player-menu")).to_be_visible()
            load_token = "00000000-0000-4000-8000-000000000001"
            prepared = send_player_command(
                {
                    "action": "play",
                    "media_ids": [track_state["media_id"]],
                    "start_paused": True,
                    "load_token": load_token,
                    "position": 1,
                }
            )
            assert prepared["paused"]
            expect(page.locator("#media-player-menu")).to_be_hidden()
            assert prepared["track_state"]["source_token"] == load_token
            assert not prepared["track_state"]["ready"]
            assert loading_subtitles
            subtitle_route, subtitle_response = loading_subtitles.pop()
            subtitle_route.fulfill(response=subtitle_response)
            page.unroute(subtitle_pattern, hold_subtitles)
            prepared = wait_report(lambda report: report["track_state"]["ready"])
            assert prepared["paused"]
            assert prepared["track_state"]["subtitles"][0]["id"] == "subtitle:0"
            stale = send_player_command(
                {
                    "action": "select_track",
                    "kind": "subtitle",
                    "track_id": "subtitle:0",
                    "source_token": track_state["source_token"],
                    "media_id": track_state["media_id"],
                }
            )
            assert not stale["track_result"]["applied"]
            assert "source changed" in stale["track_result"]["error"].lower()
            assert not stale["track_state"]["subtitles"][0]["selected"]
            selected = send_player_command(
                {
                    "action": "select_track",
                    "kind": "subtitle",
                    "track_id": "subtitle:0",
                    "source_token": load_token,
                    "media_id": track_state["media_id"],
                }
            )
            assert selected["track_result"]["applied"]
            stale_resume = send_player_command(
                {
                    "action": "play",
                    "source_token": track_state["source_token"],
                    "media_id": track_state["media_id"],
                }
            )
            assert not stale_resume["track_result"]["applied"]
            assert stale_resume["paused"]
            response_failure.update(
                {
                    "status": "failed",
                    "source_token": load_token,
                    "media_id": track_state["media_id"],
                    "error": "Requested audio language is unavailable.",
                }
            )
            expect(page.locator("#media-track-request-error")).to_have_text(
                "Requested audio language is unavailable."
            )
            resumed = send_player_command(
                {
                    "action": "play",
                    "source_token": load_token,
                    "media_id": track_state["media_id"],
                }
            )
            assert resumed["track_result"]["sequence"] == command_sequence
            assert resumed["track_result"]["applied"]
            assert not resumed["paused"]
            page.unroute("**/api/media/sessions/*", player_transport)
            # Complete a real MCP -> player -> backend preparation, without injected commands.
            with page.expect_response(lambda reply: reply.url.endswith("/chat")) as attached:
                player_action(page, "#media-chat")
            discussion = attached.value.json()["conversation_id"]
            actor = app.state.assistant.conversation(discussion)[1]
            page.locator("#media-chat-close").click()

            def model_tool(name, **arguments):
                return model.submit(invoke, app, actor, name, **arguments).result(timeout=10)

            selection = model_tool(
                "search_media", client_id="default", kind="video", query="Validation Film"
            )["selection_id"]
            assert model_tool("play_media", selection_id=selection, subtitle_language="en")[
                "queued"
            ]
            for _ in range(100):
                player_state = model_tool("get_media_player")
                if player_state.get("track_request", {}).get("status") == "completed":
                    break
                page.wait_for_timeout(100)
            assert player_state["track_request"]["status"] == "completed", player_state
            tracks = model_tool("read_media_tracks")
            assert tracks["preparation"]["status"] == "completed"
            assert tracks["subtitles"][0]["selected"]
            assert tracks["last_result"]["applied"]
            assert video.evaluate("node => !node.paused")
            # An unavailable requested audio track fails preparation and stays paused.
            assert model_tool("play_media", selection_id=selection, audio_language="en")["queued"]
            for _ in range(100):
                tracks = model_tool("read_media_tracks")
                if tracks.get("preparation", {}).get("status") == "failed":
                    break
                page.wait_for_timeout(100)
            assert tracks["preparation"]["status"] == "failed", tracks
            expect(page.locator("#media-track-request-error")).to_have_text(
                tracks["preparation"]["error"]
            )
            assert video.evaluate("node => node.paused")
            open_films_grid(page)
            page.locator(".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function("() => !document.querySelector('#media-video').paused")
            page.locator("#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === document.documentElement")
            expect(page.locator("#app-sidebar")).to_be_hidden()
            expect(page.locator("main > header")).to_be_hidden()
            expect(page.locator("#media-search")).to_be_visible()
            expect(page.locator("#media-center-mode")).to_have_attribute(
                "aria-label", "Return to TorrentLinker"
            )
            page.locator("#media-music-tab").click()
            expect(page.locator("#media-results article")).to_have_count(2)
            page.locator("#media-video-tab").click()
            player_action(page, "#media-chat")
            expect(page.locator("#media-chat-panel")).to_be_visible()
            page.locator("#media-chat-close").click()
            assert video.get_attribute("src") == source
            page.locator("#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === null")
            expect(page.locator("#app-sidebar")).to_be_visible()
            page.locator("#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement !== null")
            page.keyboard.press("Escape")
            page.wait_for_function("() => document.fullscreenElement === null")
            expect(page.locator("main > header")).to_be_visible()
            page.locator("#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === document.documentElement")
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement?.id === 'media-player-shell'")
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement === document.documentElement")
            expect(page.locator("#media-center-mode")).to_have_attribute(
                "aria-label", "Return to TorrentLinker"
            )
            expect(page.locator("#app-sidebar")).to_be_hidden()
            assert video.get_attribute("src") == source
            page.locator("#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === null")
            player_action(page, "#media-player-expand")
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement?.id === 'media-player-shell'")
            expect(page.locator("#media-fullscreen")).to_have_text("Exit fullscreen")
            video.click(button="right", position={"x": 40, "y": 40})
            expect(page.locator("#media-player-menu")).to_be_visible()
            expect(page.get_by_label("Subtitle track", exact=True)).to_be_visible()
            page.wait_for_function(
                "node => { const r = node.getBoundingClientRect(); "
                "return r.x === 0 && r.y === 0 && r.width === innerWidth "
                "&& r.height === innerHeight; }",
                arg=video_element,
            )
            expect(page.locator("#media-now-playing")).to_be_hidden()
            expect(page.locator("#media-playing-description")).to_be_hidden()
            if control_screenshots:
                page.screenshot(path=str(Path(control_screenshots) / "player-fullscreen-menu.png"))
            page.locator("#media-player-menu-close").click()
            assert video_element.evaluate("node => node === document.querySelector('#media-video')")
            assert video.get_attribute("src") == source
            assert video.evaluate("node => !node.paused && node.currentTime > 0")
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement === null")
            expect(page.locator("#media-fullscreen")).to_have_text("Fullscreen")
            player_action(page, "#media-player-expand")
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement !== null")
            page.keyboard.press("Escape")
            page.wait_for_function("() => document.fullscreenElement === null", timeout=3000)
            for layout in ("focus", "collection", "cinematic"):
                choose_layout(layout)
                expect(page.locator("#view-media")).to_have_attribute("data-layout", layout)
                player_action(page, "#media-fullscreen")
                page.wait_for_function("() => document.fullscreenElement !== null")
                assert page.locator("#media-player-shell").evaluate(
                    "node => { const r = node.getBoundingClientRect(); "
                    "return r.x === 0 && r.y === 0 && r.width === innerWidth "
                    "&& r.height === innerHeight; }"
                )
                player_action(page, "#media-fullscreen")
                page.wait_for_function("() => document.fullscreenElement === null")
                if layout == "collection":
                    expect(page.locator("#media-feature")).to_be_hidden()
                else:
                    expect(page.locator("#media-feature")).to_be_visible()
                assert video.get_attribute("src") == source
                if layout == "focus":
                    page.locator("#media-focus-strip").get_by_role(
                        "button", name="Unsupported Video", exact=True
                    ).click()
                    expect(page.locator("#media-feature h2")).to_have_text("Unsupported Video")
                    assert video.get_attribute("src") == source
                    page.locator("#media-search").fill("No matching local title")
                    expect(page.locator(".media-empty")).to_be_visible()
                    expect(
                        page.locator("#media-results").get_by_role(
                            "button", name="Add Library Folder", exact=True
                        )
                    ).to_be_visible()
                    page.locator("#media-search").fill("")
                    expect(page.locator("#view-media")).to_have_attribute("data-empty", "false")
            page.locator('[data-view="setup"][data-i18n="settings"]').click()
            page.locator("[data-settings-section=interface]").click()
            page.locator("#settings-media-layout").select_option("collection")
            page.reload()
            page.locator('[data-view="media"]').click()
            expect(page.locator("#view-media")).to_have_attribute("data-layout", "collection")
            choose_layout("cinematic")
            expect(video).to_have_attribute("src", source)

            player_action(page, "#media-chat")
            expect(page.locator("#media-chat-panel")).to_be_visible()
            # No model is connected here: the panel offers to connect one instead of a composer.
            expect(page.locator("#media-chat-content .assistant-connect")).to_be_visible()
            assert video.get_attribute("src") == source
            screenshots = os.getenv("TL_MEDIA_SCREENSHOT_DIR") or os.getenv("TL_WEB_SCREENSHOTS")
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshots) / "media-contextual-chat.png"))
            # The side panel is one discussion: header icons, no Assistant tabs or folders.
            expect(page.locator("#media-chat-history")).to_be_visible()
            expect(page.locator("#media-chat-content .assistant-conversations")).to_be_hidden()
            assert page.locator("#media-chat-content #view-assistant > .toolbar").count() == 0
            expect(page.locator("#assistant-chat-settings")).to_be_hidden()
            # Dragging the edge resizes the chat; the width is remembered for the next opening.
            panel = page.locator("#media-chat-panel")
            before = panel.bounding_box()["width"]
            edge = page.locator("#media-chat-resize").bounding_box()
            page.mouse.move(edge["x"] + 4, edge["y"] + 200)
            page.mouse.down()
            page.mouse.move(edge["x"] - 80, edge["y"] + 200, steps=4)
            page.mouse.up()
            widened = panel.bounding_box()["width"]
            assert abs(widened - (before + 84)) <= 6, (before, widened)
            assert int(page.evaluate("localStorage.getItem('tl-media-chat-width')")) == round(
                widened
            )
            # The button that opened the chat closes it, and reopening keeps the width.
            player_action(page, "#media-chat")
            expect(panel).to_be_hidden()
            player_action(page, "#media-chat")
            expect(panel).to_be_visible()
            assert abs(panel.bounding_box()["width"] - widened) <= 1
            # The toolbar's ✦ icon toggles the same panel and shows its state.
            toolbar_chat = page.locator("#media-toolbar-chat")
            expect(toolbar_chat).to_have_attribute("aria-pressed", "true")
            toolbar_chat.click()
            expect(panel).to_be_hidden()
            expect(toolbar_chat).to_have_attribute("aria-pressed", "false")
            toolbar_chat.click()
            expect(panel).to_be_visible()
            page.locator("#media-chat-close").click()
            page.locator('[data-view="library"]').click()
            expect(video).to_be_visible()
            assert video.get_attribute("src") == source
            page.locator('[data-view="media"]').click()
            video.evaluate("node => { node.pause(); node.currentTime = 5; }")
            page.wait_for_timeout(1300)
            page.reload()
            page.locator('[data-view="media"]').click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').currentTime >= 4.9"
            )
            assert video.evaluate("node => node.paused") is True
            if screenshots:
                for layout in ("cinematic", "focus", "collection"):
                    choose_layout(layout)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(
                        path=str(Path(screenshots) / f"media-layout-{layout}.png"), full_page=True
                    )
                choose_layout("cinematic")
                page.locator("#theme").select_option("light")
                page.wait_for_timeout(250)
                page.screenshot(path=str(Path(screenshots) / "media-layout-light.png"))
                page.locator("#theme").select_option("dark")

            with page.expect_popup() as opening:
                page.evaluate("() => window.open(location.href)")
            other = opening.value
            other.locator('[data-view="media"]').click()
            expect(other.locator("#media-player-shell")).to_be_hidden()
            open_films_grid(other)
            other.locator(".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            other.wait_for_function("() => document.querySelector('#media-video').currentTime > 0")
            assert video.evaluate("node => node.paused && node.currentTime >= 4.9")
            other.close()
            page.locator("#media-music-tab").click()
            expect(page.locator("#media-results article")).to_have_count(2)
            assert video.get_attribute("src") == source
            music_nav = page.get_by_role("navigation", name="Music browsing")
            expect(music_nav.get_by_role("button", name="Albums", exact=True)).to_be_visible()
            music_nav.get_by_role("button", name="Artists", exact=True).click()
            expect(page.locator("#media-results article")).to_have_count(1)
            expect(page.locator("#media-results")).to_contain_text("Daft Punk")
            music_nav.get_by_role("button", name="Tracks", exact=True).click()
            expect(page.locator(".media-track-row")).to_have_count(3)
            expect(page.locator(".media-track-row").first).to_contain_text("Discovery")
            expect(page.locator(".media-track-row").first).to_contain_text("Daft Punk")
            expect(
                page.locator(".media-track-row").first.locator(".media-track-duration")
            ).to_have_text("<0:01")
            music_nav.get_by_role("button", name="Albums", exact=True).click()
            expect(page.locator("#media-results article")).to_have_count(2)
            page.locator(".media-card").filter(has_text="2 tracks").get_by_role(
                "button", name="Details", exact=True
            ).click()
            expect(page.get_by_role("dialog", name="Media details")).to_be_visible()
            expect(page.locator("#media-details li")).to_have_count(2)
            page.get_by_role("button", name="Close details").click()
            page.locator(".media-card").filter(has_text="1 track").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function("() => document.querySelector('#media-audio').currentTime > 0")
            page.locator("#media-player-shell summary").click()
            expect(page.locator("#media-player-queue li")).to_have_count(1)
            page.locator("#media-audio").evaluate("node => node.pause()")
            page.locator(".media-card").filter(has_text="1 track").get_by_role(
                "button", name="Add to queue"
            ).click()
            expect(page.locator("#media-player-queue li")).to_have_count(2)
            page.locator("#media-player-queue li").nth(1).get_by_role(
                "button", name="Remove"
            ).click()
            expect(page.locator("#media-player-queue li")).to_have_count(1)
            assert page.locator("#media-audio").evaluate("node => node.paused") is True
            page.locator("#media-playlist-name").fill("Evening listening")
            page.locator("#media-save-playlist button").click()
            expect(page.locator("#media-playlist-list")).to_contain_text("Evening listening")
            if screenshots:
                page.locator("#media-player-shell summary").click()
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(Path(screenshots) / "media-music-albums.png"))
            music_nav.get_by_role("button", name="Artists", exact=True).click()
            expect(page.locator(".media-artist-card")).to_have_count(1)
            if screenshots:
                page.screenshot(path=str(Path(screenshots) / "media-music-artists.png"))
            music_nav.get_by_role("button", name="Tracks", exact=True).click()
            expect(page.locator(".media-track-row")).to_have_count(3)
            page.locator(".media-track-row").first.get_by_role(
                "button", name="Add to queue"
            ).click()
            expect(page.locator("#media-show-queue")).to_have_text("Playback queue · 2")
            assert page.locator("#media-audio").evaluate("node => node.paused") is True
            # Paused music leaves its bar behind when switching to Video, and finds it again.
            expect(page.locator("#media-player-shell")).to_be_visible()
            page.locator("#media-video-tab").click()
            expect(page.locator("#media-player-shell")).to_be_hidden()
            page.locator("#media-music-tab").click()
            expect(page.locator("#media-player-shell")).to_be_visible()
            music_nav.get_by_role("button", name="Tracks", exact=True).click()
            if screenshots:
                page.screenshot(path=str(Path(screenshots) / "media-music-tracks.png"))
                page.locator("#theme").select_option("light")
                page.wait_for_timeout(250)
                page.screenshot(path=str(Path(screenshots) / "media-music-light.png"))
                page.locator("#theme").select_option("dark")
                page.wait_for_timeout(250)
                page.locator("#media-center-mode").click()
                page.wait_for_function(
                    "() => document.fullscreenElement === document.documentElement"
                )
                music_nav.get_by_role("button", name="Albums", exact=True).click()
                expect(page.locator("#media-results article")).to_have_count(2)
                page.screenshot(path=str(Path(screenshots) / "media-music-center.png"))
                page.locator("#media-center-mode").click()
                page.wait_for_function("() => document.fullscreenElement === null")
            music_nav.get_by_role("button", name="Tracks", exact=True).click()
            page.locator(".media-track-row").filter(has_text="Aerodynamic").get_by_role(
                "button", name="Add to queue"
            ).click()
            expect(page.locator("#media-show-queue")).to_have_text("Playback queue · 3")
            page.locator("#media-playlist-name").fill("Full listening")
            page.locator("#media-save-playlist button").click()
            expect(page.locator("#media-playlist-list")).to_contain_text("Full listening")
            page.wait_for_timeout(1300)
            page.reload()
            page.locator('[data-view="media"]').click()
            page.locator("#media-music-tab").click()
            expect(page.locator("#media-playlist-list")).to_contain_text("Evening listening")
            expect(page.locator("#media-show-queue")).to_have_text("Playback queue · 3")
            assert not page.locator("#media-player-shell details").evaluate("node => node.open")
            expect(page.locator("#media-save-playlist button")).to_be_enabled()
            page.locator("#media-playlist-name").fill("Restored listening")
            page.locator("#media-save-playlist button").click()
            expect(page.locator("#media-playlist-list")).to_contain_text("Restored listening")
            page.set_viewport_size({"width": 600, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.locator("#media-video-tab").click()
            open_films_grid(page)
            page.locator(".media-card").filter(has_text="Unsupported Video").get_by_role(
                "button", name="Play", exact=True
            ).click()
            expect(page.locator("#media-codec-error")).to_be_visible()
            expect(page.locator("#media-external")).to_have_attribute("href", re.compile("/stream"))
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement !== null")
            player_action(page, "#media-stop")
            page.wait_for_function("() => document.fullscreenElement === null")
            expect(page.locator("#media-player-shell")).to_be_hidden()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


def test_explicit_fixed_prefix_video_preview_can_refresh_and_stop(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder, Torrent
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for a playable partial video fixture")
    root = tmp_path / "media"
    root.mkdir()
    video_file = root / "Preview.Film.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=15",
            "-t",
            "20",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video_file),
        ],
        check=True,
    )
    shutil.copy(video_file, root / "Complete.Film.mp4")
    shutil.copy(video_file, root / "Other.Film.mp4")
    size = video_file.stat().st_size
    piece_size = 16384
    piece_count = (size + piece_size - 1) // piece_size

    class Client:
        verified = piece_count // 2

        def check(self):
            return "qBittorrent preview fixture"

        def folder_settings(self):
            return []

        def torrents(self, **kwargs):
            return [
                Torrent(
                    "a" * 40,
                    video_file.name,
                    root,
                    files={video_file.name: size},
                    size=size,
                    progress=0.5,
                    state="downloading",
                )
            ]

        def torrent(self, hash, **kwargs):
            return self.torrents()[0]

        def media_preview_state(self, hash):
            return {
                "sequential": True,
                "files": [
                    {"name": video_file.name, "size": size, "piece_range": [0, piece_count - 1]}
                ],
                "piece_size": piece_size,
                "piece_states": [2] * self.verified + [0] * (piece_count - self.verified),
            }

    client = Client()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    (config / "client.ready").write_text("connected")
    app = create_app(
        config,
        password="test-password-long",
        roots=(root,),
        connector=lambda *args: client,
        monitor_verifications=False,
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            page = browser.new_page(locale="en-US")
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator('[data-view="media"]').click()
            expect(page.locator("#view-media")).to_have_attribute("data-layout", "cinematic")
            page.locator("#media-library-options summary").click()
            page.locator("#media-refresh").click()
            open_films_grid(page)
            card = page.locator(".media-card").filter(has_text="Preview Film")
            expect(card).to_be_visible(timeout=15000)
            expect(card.get_by_role("button", name="Play", exact=True)).to_be_disabled()

            def start_preview():
                if not page.locator("#media-details").is_visible():
                    card.get_by_role("button", name="Details", exact=True).click()
                page.get_by_role("button", name="Preview downloaded portion", exact=True).click()

            start_preview()
            page.wait_for_function("() => document.querySelector('#media-video').currentTime > .1")
            expect(page.locator("#media-preview-state")).to_contain_text("fixed")
            screenshots = os.getenv("TL_MEDIA_SCREENSHOT_DIR") or os.getenv("TL_WEB_SCREENSHOTS")
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshots) / "media-partial-preview.png"))
            preview_source = page.locator("#media-video").evaluate("node => node.src")
            assert "/previews/" in preview_source
            prefix = page.request.get(preview_source)
            assert len(prefix.body()) == client.verified * piece_size
            client.verified += 1
            # The old preview remains fixed even when the Torrent Client downloads more.
            assert len(page.request.get(preview_source).body()) == len(prefix.body())
            player_action(page, "#media-refresh-preview")
            page.wait_for_function(
                "old => document.querySelector('#media-video').src !== "
                "new URL(old, location.href).href",
                arg=preview_source,
            )
            refreshed = page.locator("#media-video").evaluate("node => node.src")
            assert len(page.request.get(refreshed).body()) == client.verified * piece_size
            page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').src.includes('/items/')"
            )
            expect(page.locator("#media-preview-state")).to_be_hidden()
            assert page.request.get(refreshed).status >= 400
            start_preview()
            expect(page.locator("#media-preview-state")).to_be_visible()
            stopped_source = page.locator("#media-video").evaluate("node => node.src")
            player_action(page, "#media-stop")
            expect(page.locator("#media-preview-state")).to_be_hidden()
            assert page.request.get(stopped_source).status >= 400
            assert page.locator("#media-video").get_attribute("src") is None
            # The same cancellation rule applies while ordinary item metadata is delayed.
            normal_metadata = []

            def delay_metadata(route):
                normal_metadata.append((route, route.fetch()))

            page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').src.includes('/items/')"
            )
            normal_id = (
                page.locator("#media-video")
                .evaluate("node => node.src")
                .split("/items/", 1)[1]
                .split("/", 1)[0]
            )
            metadata_pattern = f"**/api/media/items/{normal_id}?*"
            page.route(metadata_pattern, delay_metadata)
            for decision in ("stop", "play"):
                page.locator(".media-card").filter(has_text="Other Film").get_by_role(
                    "button", name="Play", exact=True
                ).click()
                expect(page.locator("#media-now-playing")).to_have_text("Other Film")
                expect(page.locator("#media-video")).to_have_attribute(
                    "src", re.compile("/items/[^/]+/stream")
                )
                replacement_source = page.locator("#media-video").get_attribute("src")
                page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                    "button", name="Play", exact=True
                ).click()
                for _ in range(100):
                    if normal_metadata:
                        break
                    page.wait_for_timeout(50)
                assert normal_metadata, "Ordinary playback metadata was not requested"
                route, response = normal_metadata.pop()
                if decision == "stop":
                    player_action(page, "#media-stop")
                else:
                    page.locator(".media-card").filter(has_text="Other Film").get_by_role(
                        "button", name="Play", exact=True
                    ).click()
                route.fulfill(response=response)
                page.wait_for_timeout(250)
                assert page.locator("#media-video").get_attribute("src") == (
                    None if decision == "stop" else replacement_source
                )
            page.unroute(metadata_pattern, delay_metadata)
            # A preview response can arrive after a later playback decision.
            held = []

            def delay_preview(route):
                held.append((route, route.fetch()))

            page.route("**/api/media/items/*/preview", delay_preview)
            for decision in ("stop", "play", "client"):
                page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                    "button", name="Play", exact=True
                ).click()
                expect(page.locator("#media-player-shell")).to_be_visible()
                expect(page.locator("#media-video")).to_have_attribute(
                    "src", re.compile(f"/items/{normal_id}/stream")
                )
                normal_source = page.locator("#media-video").get_attribute("src")
                start_preview()
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(50)
                assert held, "Preview creation request was not received"
                route, response = held.pop()
                preview_id = response.json()["preview_id"]
                if decision == "stop":
                    player_action(page, "#media-stop")
                elif decision == "play":
                    page.locator(".media-card").filter(has_text="Complete Film").get_by_role(
                        "button", name="Play", exact=True
                    ).click()
                else:
                    page.locator("#target-client").select_option("all")
                with page.expect_response(
                    lambda reply, expected=preview_id: (
                        reply.request.method == "DELETE" and f"/previews/{expected}" in reply.url
                    ),
                    timeout=4000,
                ):
                    route.fulfill(response=response)
                expect(page.locator("#media-preview-state")).to_be_hidden()
                assert page.locator("#media-video").get_attribute("src") == (
                    None if decision == "stop" else normal_source
                )

            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
