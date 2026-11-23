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

from tests.shell_support import media_option, shell_navigate

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def media_browse(page):
    return page.frame_locator("#media-frame")


def media_locator(page, selector):
    return media_browse(page).locator(selector)


def open_films_grid(page):
    """Films shows rows; a row's See all opens the card grid these steps use."""
    from playwright.sync_api import expect

    expect(page.locator("#media-frame")).to_be_visible()
    films = media_locator(page, '[data-media-view="films"]')
    if films.is_visible():
        films.click()
    else:
        # The phone player keeps browsing filters in Options.
        media_option(page, "#media-view").select_option("films")
        media_locator(page, "#media-library-options > summary").click()
    expect(media_locator(page, "#media-home-rows")).to_be_visible(timeout=15000)
    more = media_locator(page, "#media-home-rows .media-home-row").first.get_by_role(
        "button", name="See all", exact=True
    )
    if more.is_visible():
        more.focus()
        more.press("Enter")
    else:
        # A short row needs no See all link. The explicit all-videos view remains available.
        if media_locator(page, "#media-library-options").get_attribute("open") is None:
            media_locator(page, "#media-library-options > summary").click()
        media_locator(page, "#media-view").select_option("all")
        media_locator(page, "#media-library-options > summary").click()
    expect(media_locator(page, "#media-results")).to_be_visible()


def watch_control(page, selector):
    """A control of the playing film's picture, brought back first if it has left."""
    screen = media_locator(page, "#media-screen")
    if screen.get_attribute("data-controls") == "off":
        box = screen.bounding_box()
        screen.click(position={"x": box["width"] / 2, "y": box["height"] - 6})
    control = media_locator(page, selector)
    control.wait_for(state="visible")
    return control


def player_locator(page, selector):
    return page.frame_locator("#player-frame").locator(selector)


def player_action(page, identifier):
    """Music keeps the player frame's bar; a video's controls are the Médias view's own."""
    video_controls = {"#media-fullscreen": "#watch-full", "#media-stop": "#watch-stop"}
    if identifier in video_controls:
        watch_control(page, video_controls[identifier]).click()
        return
    if identifier == "#media-chat":
        media_option(page, "#media-toolbar-chat").click()
        return
    identifier = {"#media-player-expand": "#player-expand"}.get(
        identifier, identifier.replace("#media-", "#player-")
    )
    control = player_locator(page, identifier)
    if not control.is_visible():
        player_locator(page, "#player-options").focus()
        player_locator(page, "#player-options").press("Enter")
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
    from torrentlinker.config import ClientProfile

    settings.ensure_profiles()
    settings.client_profiles.append(
        ClientProfile(id="other", name="Other", host="http://127.0.0.1:9")
    )
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
                # The menu sits over the page and leaves on a scroll down: back at the top it shows.
                media_locator(page, ".media-scroll").evaluate("node => { node.scrollTop = 0; }")
                media_browse(page).locator("body").evaluate("() => window.scrollTo(0, 0)")
                page.wait_for_timeout(600)
                options = media_locator(page, "#media-library-options")
                if not options.evaluate("node => node.open"):
                    options.locator("summary").evaluate("node => node.click()")
                media_locator(page, "#media-layout-switch").select_option(value)
                options.locator("summary").evaluate("node => node.click()")

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
            shell_navigate(page, "media")
            expect(media_locator(page, "#view-media")).to_have_attribute("data-layout", "cinematic")
            # The toolbar ⟳ refreshes the library and shows that a refresh is running.
            media_option(page, "#media-refresh").click()
            media_locator(page, "#media-library-options > summary").click()
            expect(media_locator(page, "#media-toolbar-refresh")).to_have_attribute(
                "aria-pressed", "true"
            )
            expect(media_locator(page, "#media-toolbar-refresh")).to_have_attribute(
                "aria-pressed", "false", timeout=15000
            )
            # The video home shows rows; the card grid is under Films.
            expect(media_locator(page, "#media-home-rows")).to_contain_text(
                "Validation", timeout=15000
            )
            open_films_grid(page)
            expect(media_locator(page, "#media-home-rows")).to_be_hidden()
            expect(media_locator(page, "#media-results")).to_contain_text("Validation")
            open_films_grid(page)
            expect(media_locator(page, "#media-results")).to_contain_text(
                "Validation", timeout=15000
            )
            media_locator(page, ".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Details", exact=True
            ).click()
            expect(media_locator(page, "#media-details")).to_contain_text("External subtitle files")
            expect(media_locator(page, "#media-details")).to_contain_text("Validation.Film.2026.en")
            assert page.locator("#media-video").get_attribute("src") is None
            media_browse(page).get_by_role("button", name="Close details", exact=True).click()
            media_locator(page, ".media-card").filter(has_text="Unsupported Video").get_by_role(
                "button", name="Details", exact=True
            ).click()
            expect(media_locator(page, "#media-details")).to_contain_text(
                "No external subtitle files are known for this release."
            )
            expect(media_locator(page, "#media-details")).to_contain_text(
                "Embedded subtitle tracks"
            )
            media_browse(page).get_by_role("button", name="Close details", exact=True).click()
            media_locator(page, ".media-card").filter(has_text="Validation Film").get_by_role(
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
            # A film plays in the page: the Médias view draws its controls and details.
            expect(media_locator(page, "#view-media")).to_have_attribute("data-watch", "true")
            expect(page.locator("#player-frame")).to_be_hidden()
            video.evaluate("node => node.pause()")
            expect(media_locator(page, "#watch-toggle")).to_have_attribute("aria-label", "Play")
            media_browse(page).get_by_role("button", name="Audio and subtitles", exact=True).click()
            track_dialog = media_locator(page, "#watch-settings-menu")
            expect(track_dialog).to_be_visible()
            expect(
                track_dialog.get_by_role("menuitemradio", name="Off", exact=True)
            ).to_have_attribute("aria-checked", "true")
            track_dialog.get_by_role(
                "menuitemradio", name="Validation.Film.2026.en", exact=True
            ).click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').textTracks[0].mode === 'showing'"
            )
            video.evaluate("node => { node.currentTime = 1; }")
            page.wait_for_function(
                "() => document.querySelector('#media-video').textTracks[0].activeCues?.length > 0"
            )
            page.keyboard.press("Escape")
            expect(track_dialog).to_be_hidden()
            if control_screenshots:
                page.screenshot(path=str(Path(control_screenshots) / "player-caption-controls.png"))
            # Playing, the controls leave after a moment; a tap on the picture brings them back.
            video.evaluate("node => node.play()")
            screen = media_locator(page, "#media-screen")
            expect(screen).to_have_attribute("data-controls", "off", timeout=6000)
            screen_box = screen.bounding_box()
            screen.click(position={"x": 200, "y": screen_box["height"] - 6})
            expect(screen).to_have_attribute("data-controls", "on")
            video.evaluate("node => node.pause()")
            expect(media_locator(page, "#watch-toggle")).to_have_attribute("aria-label", "Play")
            watch_control(page, "#watch-toggle").click()
            page.wait_for_function("() => !document.querySelector('#media-video').paused")
            media_browse(page).get_by_role("button", name="Audio and subtitles", exact=True).click()
            track_dialog.get_by_role("menuitemradio", name="Off", exact=True).click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').textTracks[0].mode === 'disabled'"
            )
            expect(track_dialog).to_be_hidden()
            assert video_element.evaluate("node => node === document.querySelector('#media-video')")
            assert video.get_attribute("src") == source
            expect(media_locator(page, "#media-feature h2")).to_have_text("Validation Film")
            expect(media_locator(page, "#media-feature .media-feature-meta")).to_contain_text(
                "2026"
            )
            assert not page.locator("#media-video-stage").locator("#player-details-frame").count()
            video.evaluate("node => node.play()")
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
            media_browse(page).get_by_role("button", name="Audio and subtitles", exact=True).click()
            expect(track_dialog).to_be_visible()
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
            expect(track_dialog).to_be_hidden()
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
            page.frame_locator("#media-assistant-frame").locator("#media-chat-close").click()

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
            media_locator(page, ".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function("() => !document.querySelector('#media-video').paused")
            # (The grid Play button scrolled the page; the bar returns at the top.)
            media_locator(page, ".media-scroll").evaluate("node => { node.scrollTop = 0; }")
            page.wait_for_timeout(600)
            media_locator(page, "#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === document.documentElement")
            expect(page.locator("#app-sidebar")).to_be_hidden()
            expect(page.locator("main > header")).to_be_hidden()
            expect(media_locator(page, "#media-search")).to_be_visible()
            expect(media_locator(page, "#media-center-mode")).to_have_attribute(
                "aria-label", "Return to TorrentLinker"
            )
            media_option(page, "#media-music-tab").click()
            expect(page.locator("#media-frame")).to_be_visible()
            expect(media_locator(page, "#media-results article")).to_have_count(2)
            media_option(page, "#media-video-tab").click()
            expect(page.locator("#media-frame")).to_be_visible()
            player_action(page, "#media-chat")
            expect(page.locator("#media-chat-panel")).to_be_visible()
            page.frame_locator("#media-assistant-frame").locator("#media-chat-close").click()
            assert video.get_attribute("src") == source
            media_locator(page, "#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === null")
            expect(page.locator("#app-sidebar")).to_be_visible()
            media_locator(page, "#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement !== null")
            page.keyboard.press("Escape")
            page.wait_for_function("() => document.fullscreenElement === null")
            expect(page.locator("#app-sidebar")).to_be_visible()
            # Media has its own menu: the page header stays hidden on it.
            expect(page.locator("main > header")).to_be_hidden()
            media_locator(page, "#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === document.documentElement")
            # Media Center is full screen already: the player's full screen fills the app
            # instead, and leaving it keeps Media Center.
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.body.classList.contains('media-player-full')")
            assert page.evaluate("document.fullscreenElement === document.documentElement")
            expect(media_locator(page, "#view-media")).to_have_attribute("data-full", "true")
            page.wait_for_function(
                "() => { const r = document.querySelector('#media-player-shell')"
                ".getBoundingClientRect(); return r.x === 0 && r.y === 0 "
                "&& r.width === innerWidth && r.height === innerHeight; }"
            )
            expect(media_locator(page, "#watch-full")).to_have_attribute(
                "aria-label", "Exit full screen"
            )
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => !document.body.classList.contains('media-player-full')")
            assert page.evaluate("document.fullscreenElement === document.documentElement")
            assert page.evaluate("document.body.classList.contains('media-center-mode')")
            expect(media_locator(page, "#media-center-mode")).to_have_attribute(
                "aria-label", "Return to TorrentLinker"
            )
            expect(page.locator("#app-sidebar")).to_be_hidden()
            assert video.get_attribute("src") == source
            media_locator(page, "#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === null")
            # (Browsing Music paused the film; it plays again.)
            video.evaluate("node => node.play()")
            # Outside Media Center the player asks for full screen itself and gives it back.
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement === document.documentElement")
            expect(media_locator(page, "#watch-full")).to_have_attribute(
                "aria-label", "Exit full screen"
            )
            page.wait_for_function(
                "node => { const r = node.getBoundingClientRect(); "
                "return r.x === 0 && r.y === 0 && r.width === innerWidth "
                "&& r.height === innerHeight; }",
                arg=video_element,
            )
            if control_screenshots:
                page.screenshot(path=str(Path(control_screenshots) / "player-fullscreen.png"))
            assert video_element.evaluate("node => node === document.querySelector('#media-video')")
            assert video.get_attribute("src") == source
            assert video.evaluate("node => !node.paused && node.currentTime > 0")
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement === null")
            expect(media_locator(page, "#watch-full")).to_have_attribute(
                "aria-label", "Full screen"
            )
            player_action(page, "#media-fullscreen")
            page.wait_for_function("() => document.fullscreenElement !== null")
            page.keyboard.press("Escape")
            page.wait_for_function("() => document.fullscreenElement === null", timeout=3000)
            expect(media_locator(page, "#view-media")).to_have_attribute("data-full", "false")
            for layout in ("focus", "horizon", "cinematic"):
                choose_layout(layout)
                expect(media_locator(page, "#view-media")).to_have_attribute("data-layout", layout)
                player_action(page, "#media-fullscreen")
                page.wait_for_function("() => document.fullscreenElement !== null")
                page.wait_for_function(
                    "() => { const r = document.querySelector('#media-player-shell')"
                    ".getBoundingClientRect(); return r.x === 0 && r.y === 0 "
                    "&& r.width === innerWidth && r.height === innerHeight; }"
                )
                player_action(page, "#media-fullscreen")
                page.wait_for_function("() => document.fullscreenElement === null")
                # The selected library banner remains available during playback.
                expect(media_locator(page, "#media-feature")).to_be_visible()
                if layout == "horizon":
                    # The Media options switch Horizon's view.
                    page.wait_for_timeout(600)
                    media_locator(page, "#media-library-options summary").evaluate(
                        "node => node.click()"
                    )
                    media_locator(page, "#media-horizon-switch").select_option("showcase")
                    expect(media_locator(page, "#view-media")).to_have_attribute(
                        "data-horizon", "showcase"
                    )
                    media_locator(page, "#media-horizon-switch").select_option("home")
                    media_locator(page, "#media-library-options summary").evaluate(
                        "node => node.click()"
                    )
                assert video.get_attribute("src") == source
                if layout == "focus":
                    # While a film plays, a card plays its film.
                    media_locator(page, "#media-focus-strip").get_by_role(
                        "button", name="Validation Film", exact=True
                    ).click()
                    expect(media_locator(page, "#media-feature h2")).to_have_text("Validation Film")
                    assert video.get_attribute("src") == source
                    media_locator(page, "#media-search").fill("No matching local title")
                    expect(media_locator(page, ".media-empty")).to_be_visible()
                    expect(
                        media_locator(page, "#media-results").get_by_role(
                            "button", name="Add Library Folder", exact=True
                        )
                    ).to_be_visible()
                    media_locator(page, "#media-search").fill("")
                    expect(media_locator(page, "#view-media")).to_have_attribute(
                        "data-empty", "false"
                    )
            shell_navigate(page, "setup")
            settings = page.frame_locator("#settings-frame")
            settings.get_by_role("button", name="General", exact=True).click()
            settings.get_by_label("Media interface", exact=True).select_option("horizon")
            settings.get_by_label("Horizon view", exact=True).select_option("wall")
            settings.get_by_role("button", name="Save", exact=True).click()
            expect(settings.locator("#settings-status")).to_contain_text("Settings saved")
            page.reload()
            shell_navigate(page, "media")
            expect(media_locator(page, "#view-media")).to_have_attribute("data-layout", "horizon")
            expect(media_locator(page, "#view-media")).to_have_attribute("data-horizon", "wall")
            expect(media_locator(page, "#media-layout-switch")).to_have_value("horizon")
            # In the Wall, a poster selects its title into the band instead of opening details.
            poster = media_locator(page, "#media-results .media-poster-button").first
            poster.click()
            expect(media_locator(page, "#media-details")).not_to_be_visible()
            expect(poster).to_have_attribute("aria-pressed", "true")
            choose_layout("cinematic")
            expect(video).to_have_attribute("src", source)

            player_action(page, "#media-chat")
            expect(page.locator("#media-chat-panel")).to_be_visible()
            # No model is connected here: the panel offers to connect one instead of a composer.
            expect(
                page.frame_locator("#media-assistant-frame").locator(".assistant-connect")
            ).to_be_visible(timeout=15000)
            assert video.get_attribute("src") == source
            screenshots = os.getenv("TL_MEDIA_SCREENSHOT_DIR") or os.getenv("TL_WEB_SCREENSHOTS")
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshots) / "media-contextual-chat.png"))
            # The side panel is one discussion: header icons, no Assistant tabs or folders.
            expect(
                page.frame_locator("#media-assistant-frame").locator("#media-chat-history")
            ).to_be_visible()
            expect(
                page.frame_locator("#media-assistant-frame").locator(".assistant-conversations")
            ).to_be_hidden()
            assert (
                page.frame_locator("#media-assistant-frame")
                .locator("#view-assistant > .toolbar")
                .count()
                == 0
            )
            expect(
                page.frame_locator("#media-assistant-frame").locator("#assistant-chat-settings")
            ).to_be_hidden()
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
            toolbar_chat = media_locator(page, "#media-toolbar-chat")
            expect(toolbar_chat).to_have_attribute("aria-pressed", "true")
            media_option(page, "#media-toolbar-chat").click()
            expect(panel).to_be_hidden()
            expect(toolbar_chat).to_have_attribute("aria-pressed", "false")
            media_option(page, "#media-toolbar-chat").click()
            expect(panel).to_be_visible()
            page.frame_locator("#media-assistant-frame").locator("#media-chat-close").click()
            # A video belongs to Médias: elsewhere it pauses out of sight, then comes back.
            shell_navigate(page, "library")
            expect(video).to_be_hidden()
            assert video.evaluate("node => node.paused")
            assert video.get_attribute("src") == source
            shell_navigate(page, "media")
            expect(video).to_be_visible()
            video.evaluate("node => { node.pause(); node.currentTime = 5; }")
            page.wait_for_timeout(1300)
            page.reload()
            shell_navigate(page, "media")
            page.wait_for_function(
                "() => document.querySelector('#media-video').currentTime >= 4.9"
            )
            assert video.evaluate("node => node.paused") is True
            if screenshots:
                for layout in ("cinematic", "focus", "horizon"):
                    choose_layout(layout)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(
                        path=str(Path(screenshots) / f"media-layout-{layout}.png"), full_page=True
                    )
                choose_layout("cinematic")
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "light"
                )
                page.wait_for_timeout(250)
                page.screenshot(path=str(Path(screenshots) / "media-layout-light.png"))
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "dark"
                )

            with page.expect_popup() as opening:
                page.evaluate("() => window.open(location.href)")
            other = opening.value
            shell_navigate(other, "media")
            expect(other.locator("#media-player-shell")).to_be_hidden()
            open_films_grid(other)
            media_locator(other, ".media-card").filter(has_text="Validation Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            other.wait_for_function("() => document.querySelector('#media-video').currentTime > 0")
            assert video.evaluate("node => node.paused && node.currentTime >= 4.9")
            other.close()
            media_option(page, "#media-music-tab").click()
            expect(page.locator("#media-frame")).to_be_visible()
            expect(media_locator(page, "#media-results article")).to_have_count(2)
            assert video.get_attribute("src") == source
            music_nav = media_browse(page).get_by_role("navigation", name="Music browsing")
            expect(music_nav.get_by_role("button", name="Albums", exact=True)).to_be_visible()
            music_nav.get_by_role("button", name="Artists", exact=True).click()
            expect(media_locator(page, "#media-results article")).to_have_count(1)
            expect(media_locator(page, "#media-results")).to_contain_text("Daft Punk")
            music_nav.get_by_role("button", name="Tracks", exact=True).click()
            expect(media_locator(page, ".media-track-row")).to_have_count(3)
            expect(media_locator(page, ".media-track-row").first).to_contain_text("Discovery")
            expect(media_locator(page, ".media-track-row").first).to_contain_text("Daft Punk")
            expect(
                media_locator(page, ".media-track-row").first.locator(".media-track-duration")
            ).to_have_text("<0:01")
            music_nav.get_by_role("button", name="Albums", exact=True).click()
            expect(media_locator(page, "#media-results article")).to_have_count(2)
            media_locator(page, ".media-card").filter(has_text="2 tracks").get_by_role(
                "button", name="Details", exact=True
            ).click()
            expect(media_browse(page).get_by_role("dialog", name="Media details")).to_be_visible()
            expect(media_locator(page, "#media-details li")).to_have_count(2)
            media_browse(page).get_by_role("button", name="Close details").click()
            media_locator(page, ".media-card").filter(has_text="1 track").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function("() => document.querySelector('#media-audio').currentTime > 0")
            player_locator(page, "#player-options").click()
            player_locator(page, "#player-queue-details summary").click()
            expect(player_locator(page, "#player-queue li")).to_have_count(1)
            page.locator("#media-audio").evaluate("node => node.pause()")
            player_locator(page, "#player-queue li button").last.evaluate(
                "node => window.staleRemove = node.onclick"
            )
            player_locator(page, "#player-menu-close").click()
            media_locator(page, ".media-card").filter(has_text="1 track").get_by_role(
                "button", name="Add to queue"
            ).click()
            expect(player_locator(page, "#player-queue li")).to_have_count(2)
            player_locator(page, "#player-options").click()
            player_locator(page, "#player-queue").evaluate("() => window.staleRemove()")
            expect(player_locator(page, "#player-error")).to_contain_text("queue changed")
            expect(player_locator(page, "#player-queue li")).to_have_count(2)
            player_locator(page, "#player-queue li").nth(1).get_by_role(
                "button", name="Remove"
            ).click()
            expect(player_locator(page, "#player-queue li")).to_have_count(1)
            assert page.locator("#media-audio").evaluate("node => node.paused") is True
            page.once("dialog", lambda dialog: dialog.accept("Evening listening"))
            player_locator(page, "#player-playlist-save").click()
            expect(media_locator(page, "#media-playlist-list")).to_contain_text("Evening listening")
            cache_check = page.evaluate("""async () => {
              const owner = playerPlaylistsClient, queue = [...media.queue];
              try {
                playerPlaylistsClient = 'another-client';
                const snapshot = mediaPlayerSnapshot();
                let error = '';
                try { await mediaPlayerControl({...snapshot, action:'playlist-load',
                  values:{id:playerPlaylists[0].id}});
                } catch (failure) { error = failure.message; }
                return {hidden:snapshot.playlists.length === 0, error,
                  unchanged:JSON.stringify(queue) === JSON.stringify(media.queue)};
              } finally { playerPlaylistsClient = owner; }
            }""")
            assert cache_check["hidden"] and cache_check["unchanged"]
            assert "this client" in cache_check["error"]
            player_locator(page, "#player-menu-close").click()
            if screenshots:
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(Path(screenshots) / "media-music-albums.png"))
            music_nav.get_by_role("button", name="Artists", exact=True).click()
            expect(media_locator(page, ".media-artist-card")).to_have_count(1)
            if screenshots:
                page.screenshot(path=str(Path(screenshots) / "media-music-artists.png"))
            music_nav.get_by_role("button", name="Tracks", exact=True).click()
            expect(media_locator(page, ".media-track-row")).to_have_count(3)
            media_locator(page, ".media-track-row").first.get_by_role(
                "button", name="Add to queue"
            ).click()
            expect(media_locator(page, "#media-show-queue")).to_have_text("Playback queue · 2")
            assert page.locator("#media-audio").evaluate("node => node.paused") is True
            # Paused music leaves its bar behind when switching to Video, and finds it again.
            expect(page.locator("#media-player-shell")).to_be_visible()
            media_option(page, "#media-video-tab").click()
            expect(page.locator("#media-frame")).to_be_visible()
            expect(page.locator("#media-player-shell")).to_be_hidden()
            media_option(page, "#media-music-tab").click()
            expect(page.locator("#media-frame")).to_be_visible()
            expect(page.locator("#media-player-shell")).to_be_visible()
            music_nav.get_by_role("button", name="Tracks", exact=True).click()
            expect(media_locator(page, ".media-track-row")).to_have_count(3)
            if screenshots:
                page.screenshot(path=str(Path(screenshots) / "media-music-tracks.png"))
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "light"
                )
                page.wait_for_timeout(250)
                page.screenshot(path=str(Path(screenshots) / "media-music-light.png"))
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "dark"
                )
                page.wait_for_timeout(250)
                media_locator(page, "#media-center-mode").click()
                page.wait_for_function(
                    "() => document.fullscreenElement === document.documentElement"
                )
                music_nav.get_by_role("button", name="Albums", exact=True).click()
                expect(media_locator(page, "#media-results article")).to_have_count(2)
                page.screenshot(path=str(Path(screenshots) / "media-music-center.png"))
                media_locator(page, "#media-center-mode").click()
                page.wait_for_function("() => document.fullscreenElement === null")
            music_nav.get_by_role("button", name="Tracks", exact=True).click()
            media_locator(page, ".media-track-row").filter(has_text="Aerodynamic").get_by_role(
                "button", name="Add to queue"
            ).click()
            expect(media_locator(page, "#media-show-queue")).to_have_text("Playback queue · 3")
            media_locator(page, "#media-playlist-name").fill("Full listening")
            media_locator(page, "#media-save-playlist button").click()
            expect(media_locator(page, "#media-playlist-list")).to_contain_text("Full listening")
            page.wait_for_timeout(1300)
            page.reload()
            shell_navigate(page, "media")
            media_option(page, "#media-music-tab").click()
            expect(page.locator("#media-frame")).to_be_visible()
            expect(media_locator(page, "#media-playlist-list")).to_contain_text("Evening listening")
            expect(media_locator(page, "#media-show-queue")).to_have_text("Playback queue · 3")
            assert not player_locator(page, "#player-queue-details").evaluate("node => node.open")
            expect(media_locator(page, "#media-save-playlist button")).to_be_enabled()
            media_locator(page, "#media-playlist-name").fill("Restored listening")
            media_locator(page, "#media-save-playlist button").click()
            expect(media_locator(page, "#media-playlist-list")).to_contain_text(
                "Restored listening"
            )
            # A saved queue belongs to its playback client even while browsing another.
            media_option(page, "#media-client").select_option("other")
            expect(media_option(page, "#media-music-tab")).to_be_visible()
            media_option(page, "#media-music-tab").click()
            media_locator(page, "#media-playlist-name").fill("Original client queue")
            with page.expect_response(
                lambda r: "/api/media/playlists" in r.url and r.request.method == "POST"
            ) as saved:
                media_locator(page, "#media-save-playlist button").click()
            assert saved.value.ok
            assert "Original client queue" in [
                p["name"]
                for p in page.request.get(
                    f"http://127.0.0.1:{port}/api/media/playlists?client_id=default"
                ).json()
            ]
            assert (
                page.request.get(
                    f"http://127.0.0.1:{port}/api/media/playlists?client_id=other"
                ).json()
                == []
            )
            media_option(page, "#media-client").select_option("default")
            page.set_viewport_size({"width": 600, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            media_option(page, "#media-video-tab").click()
            expect(page.locator("#media-frame")).to_be_visible()
            open_films_grid(page)
            media_locator(page, ".media-card").filter(has_text="Unsupported Video").get_by_role(
                "button", name="Play", exact=True
            ).click()
            # The picture says it cannot play, and offers the file to another player.
            expect(media_locator(page, "#media-screen-note")).to_be_visible()
            expect(media_locator(page, "#media-screen-note a")).to_have_attribute(
                "href", re.compile("/stream")
            )
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
            shell_navigate(page, "media")
            expect(media_locator(page, "#view-media")).to_have_attribute("data-layout", "cinematic")
            media_locator(page, "#media-library-options summary").click()
            media_locator(page, "#media-refresh").click()
            open_films_grid(page)
            card = media_locator(page, ".media-card").filter(has_text="Preview Film")
            expect(card).to_be_visible(timeout=15000)
            expect(
                card.get_by_role("button", name="Preview downloaded portion", exact=True)
            ).to_be_enabled()

            if folder := os.getenv("TL_MEDIA_SCREENSHOT_DIR"):
                Path(folder).mkdir(parents=True, exist_ok=True)
                card.screenshot(path=str(Path(folder) / "media-preview-action.png"))

            def start_preview():
                card.get_by_role("button", name="Preview downloaded portion", exact=True).click()

            start_preview()
            page.wait_for_function("() => document.querySelector('#media-video').currentTime > .1")
            expect(media_locator(page, ".media-watch-note")).to_contain_text("fixed")
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
            media_browse(page).get_by_role("button", name="Refresh preview", exact=True).click()
            page.wait_for_function(
                "old => document.querySelector('#media-video').src !== "
                "new URL(old, location.href).href",
                arg=preview_source,
            )
            refreshed = page.locator("#media-video").evaluate("node => node.src")
            assert len(page.request.get(refreshed).body()) == client.verified * piece_size
            media_locator(page, ".media-card").filter(has_text="Complete Film").get_by_role(
                "button", name="Play", exact=True
            ).click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').src.includes('/items/')"
            )
            expect(media_locator(page, ".media-watch-note")).to_have_count(0)
            assert page.request.get(refreshed).status >= 400
            start_preview()
            expect(media_locator(page, ".media-watch-note")).to_be_visible()
            stopped_source = page.locator("#media-video").evaluate("node => node.src")
            player_action(page, "#media-stop")
            expect(media_locator(page, ".media-watch-note")).to_have_count(0)
            assert page.request.get(stopped_source).status >= 400
            assert page.locator("#media-video").get_attribute("src") is None
            # The same cancellation rule applies while ordinary item metadata is delayed.
            normal_metadata = []

            def delay_metadata(route):
                normal_metadata.append((route, route.fetch()))

            media_locator(page, ".media-card").filter(has_text="Complete Film").get_by_role(
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
                media_locator(page, ".media-card").filter(has_text="Other Film").get_by_role(
                    "button", name="Play", exact=True
                ).click()
                expect(page.locator("#media-now-playing")).to_have_text("Other Film")
                expect(page.locator("#media-video")).to_have_attribute(
                    "src", re.compile("/items/[^/]+/stream")
                )
                replacement_source = page.locator("#media-video").get_attribute("src")
                media_locator(page, ".media-card").filter(has_text="Complete Film").get_by_role(
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
                    media_locator(page, ".media-card").filter(has_text="Other Film").get_by_role(
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
                media_locator(page, ".media-card").filter(has_text="Complete Film").get_by_role(
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
                    media_locator(page, ".media-card").filter(has_text="Complete Film").get_by_role(
                        "button", name="Play", exact=True
                    ).click()
                else:
                    shell_navigate(page, "torrents")
                    page.frame_locator("#shell-header-frame").locator(
                        "#target-client"
                    ).select_option("all")
                with page.expect_response(
                    lambda reply, expected=preview_id: (
                        reply.request.method == "DELETE" and f"/previews/{expected}" in reply.url
                    ),
                    timeout=4000,
                ):
                    route.fulfill(response=response)
                expect(media_locator(page, ".media-watch-note")).to_have_count(0)
                assert page.locator("#media-video").get_attribute("src") == (
                    None if decision == "stop" else normal_source
                )

            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


def test_cinematic_home_keeps_the_banner_and_menu_pinned_while_rows_scroll(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    root = tmp_path / "media"
    root.mkdir()
    for number in range(30):
        (root / f"Pinned.Film.{number:02d}.20{number:02d}.mp4").write_bytes(b"not a real video")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(language="en")
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
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
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 650}, locale="en-US")
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "media")
            if media_locator(page, "#media-toolbar-refresh").is_visible():
                media_option(page, "#media-refresh").click()
                media_locator(page, "#media-library-options > summary").click()
            else:
                media_locator(page, "#media-library-options > summary").click()
                media_locator(page, "#media-refresh").click()
                media_locator(page, "#media-library-options > summary").click()
            expect(media_locator(page, "#media-home-rows")).to_contain_text("Pinned", timeout=15000)
            frame = page.frame(name="media-frame") or next(
                f for f in page.frames if f.url.endswith("/media/view.html") or "media" in f.url
            )
            track = media_locator(page, ".media-row-track").first
            assert track.evaluate("node => node.scrollWidth > node.clientWidth")
            # The wheel over a row scrolls the row, not the page.
            track.hover()
            before = frame.evaluate("scrollY")
            page.mouse.wheel(0, 300)
            # The row scrolls smoothly; give it time on a slow machine.
            for _ in range(30):
                if track.evaluate("node => node.scrollLeft") > 0:
                    break
                page.wait_for_timeout(100)
            assert track.evaluate("node => node.scrollLeft") > 0
            assert frame.evaluate("scrollY") == before
            # At either end the wheel stays with the row; the page scrolls from the title.
            page.mouse.wheel(0, 20000)
            page.wait_for_timeout(400)
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(400)
            assert frame.evaluate("scrollY") == before
            assert frame.evaluate("document.documentElement.scrollHeight > innerHeight")
            media_locator(page, ".media-feature-poster").hover()
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(400)
            assert frame.evaluate("scrollY") > before
            # The menu and selected banner remain fixed together while browsing.
            assert frame.evaluate("document.querySelector('.media-topbar').offsetHeight") > 0
            frame.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(400)
            assert frame.evaluate("scrollY") > 0
            view = media_locator(page, "#view-media")
            expect(view).not_to_have_attribute("data-bar", "hidden")
            for selector in (".media-topbar", "#media-feature"):
                assert (
                    frame.locator(selector).evaluate("node => node.getBoundingClientRect().top")
                    == 0
                )
            frame.evaluate("window.scrollBy(0, -50)")
            expect(view).not_to_have_attribute("data-bar", "hidden")
            frame.evaluate("window.scrollBy(0, 80)")
            expect(view).not_to_have_attribute("data-bar", "hidden")
            frame.evaluate("window.scrollTo(0, 0)")
            # Choosing another film changes the title with a soft fade; nothing else moves.
            fade = """() => {
                const card = document.querySelectorAll('.media-row-card')[3];
                card.click();
                const art = document.querySelector('#media-feature .media-feature-art');
                return [document.querySelector('#media-feature h2').textContent,
                    getComputedStyle(art).animationName, getComputedStyle(art).animationDuration];
            }"""
            title, animation, duration = frame.evaluate(fade)
            assert title.startswith("Pinned Film")
            assert (animation, duration) == ("media-fade", "0.35s")
            # Media Center ("enlarged") mode keeps the same calm title.
            media_locator(page, "#media-center-mode").click()
            page.wait_for_function("() => document.fullscreenElement === document.documentElement")
            frame.evaluate("window.scrollTo(0, 600)")
            page.wait_for_timeout(300)
            assert (
                frame.evaluate(
                    "getComputedStyle(document.querySelector('#media-feature')).position"
                )
                == "sticky"
            )
            assert (
                frame.evaluate(
                    "document.querySelector('#media-feature').getBoundingClientRect().bottom"
                )
                < 600
            )
            frame.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
            media_locator(page, "#media-center-mode").click()
            # Reduced motion: the new title appears at once.
            calm = browser.new_page(
                viewport={"width": 1280, "height": 900}, locale="en-US", reduced_motion="reduce"
            )
            calm.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            calm.locator("#login-password").fill("test-password-long")
            calm.locator("#login-form button").click()
            shell_navigate(calm, "media")
            expect(media_locator(calm, "#media-home-rows")).to_contain_text("Pinned", timeout=15000)
            calm_frame = calm.frame(name="media-frame")
            assert calm_frame is not None
            media_locator(calm, ".media-row-card").nth(2).wait_for()
            _, calm_animation, _ = calm_frame.evaluate(fade)
            assert calm_animation == "none"
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_horizon_home_and_showcase_fill_one_screen_and_the_wheel_moves_the_selection(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    root = tmp_path / "media"
    root.mkdir()
    for number in range(70):
        (root / f"Horizon.Film.{number:02d}.{1950 + number}.mp4").write_bytes(b"not a real video")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(language="en")
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
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
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 950}, locale="en-US")
            page.add_init_script(
                "try{localStorage.setItem('tl-media-layout','horizon');"
                "localStorage.setItem('tl-media-horizon','home')}catch{}"
            )
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "media")
            media_option(page, "#media-refresh").click()
            media_locator(page, "#media-library-options > summary").click()
            expect(media_locator(page, ".media-row-card")).to_have_count(20, timeout=15000)
            frame = page.frame(name="media-frame")

            def selected():
                return frame.evaluate("mediaItems.get(media.featureId).title")

            # One screen: nothing scrolls, and the Assistant lives in the menu's ✦ only.
            assert frame.evaluate("document.documentElement.scrollHeight <= innerHeight")
            expect(media_locator(page, "#media-feature-chat")).to_have_count(0)
            # The wheel moves the selection, one title per step, kept in the middle.
            first = selected()
            page.mouse.move(700, 400)
            for _ in range(3):
                page.mouse.wheel(0, 100)
                page.wait_for_timeout(150)
            assert selected() != first
            assert frame.evaluate("scrollY") == 0
            # The rest of the category arrives as the selection moves along it.
            for _ in range(15):
                page.mouse.wheel(0, 100)
                page.wait_for_timeout(80)
            expect(media_locator(page, ".media-row-card")).to_have_count(60, timeout=5000)
            # The category's title is its menu.
            category = media_locator(page, ".media-row-category")
            category.select_option(label="Not watched yet")
            expect(media_locator(page, ".media-home-row")).to_have_attribute(
                "aria-label", "Not watched yet"
            )
            # See all opens the Wall's compact grid, which scrolls.
            media_locator(page, ".media-home-row").get_by_role("button", name="See all").click()
            expect(media_locator(page, "#view-media")).to_have_attribute("data-horizon", "wall")
            # More titles load as it scrolls: the "Load more" button never shows.
            assert media_locator(page, "#media-more").evaluate(
                "node => node.hidden || getComputedStyle(node).opacity === '0'"
            )
            # Showcase: one screen too, and the wheel moves its carousel's selection.
            frame.evaluate("mediaSetHorizon('showcase')")
            media_locator(page, '[data-media-view="recent"]').click()
            expect(media_locator(page, "#view-media")).to_have_attribute("data-horizon", "showcase")
            page.wait_for_timeout(500)
            assert frame.evaluate("document.documentElement.scrollHeight <= innerHeight")
            first = selected()
            page.mouse.wheel(0, 100)
            page.wait_for_timeout(300)
            assert selected() != first
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


WATCH_SCREENS = {
    "phone": {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True},
    "phone-landscape": {
        "viewport": {"width": 915, "height": 412},
        "is_mobile": True,
        "has_touch": True,
    },
    "computer": {"viewport": {"width": 1280, "height": 800}},
    "media-center": {"viewport": {"width": 1280, "height": 800}},
}


@pytest.mark.parametrize("screen_name", list(WATCH_SCREENS))
def test_a_film_plays_at_the_top_of_the_page_on_every_screen(tmp_path, screen_name):
    """Approved theatre design: full-width player, pinned selection and independent playback."""
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for a real playable video fixture")
    root = tmp_path / "media"
    root.mkdir()
    for name in ("First.Watch.2026", "Second.Watch.2025"):
        (root / name).mkdir()
        subprocess.run(
            [ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=10"]
            + ["-t", "60", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
            + [str(root / name / f"{name}.mp4")],
            check=True,
        )
    from PIL import Image

    Image.new("RGB", (200, 300), "#447c88").save(root / "First.Watch.2026" / "poster.jpg")
    synopsis = "A long synopsis that must remain readable without moving the film rows. " * 40
    (root / "First.Watch.2026" / "movie.nfo").write_text(
        f"<movie><title>First Watch</title><plot>{synopsis}</plot></movie>"
    )
    (root / "Second.Watch.2025" / "movie.nfo").write_text(
        "<movie><title>Second Watch across the distant horizons "
        "and the last forgotten islands</title></movie>"
    )
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(language="en")
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
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
            context = browser.new_context(locale="en-US", **WATCH_SCREENS[screen_name])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "media")
            if media_locator(page, "#media-toolbar-refresh").is_visible():
                media_option(page, "#media-refresh").click()
                media_locator(page, "#media-library-options > summary").click()
            else:
                media_locator(page, "#media-library-options > summary").click()
                media_locator(page, "#media-refresh").click()
                media_locator(page, "#media-library-options > summary").click()
            expect(media_locator(page, "#media-home-rows")).to_contain_text("Watch", timeout=15000)
            expect(media_locator(page, "#media-toolbar-refresh")).to_have_attribute(
                "aria-pressed", "false", timeout=15000
            )
            center = screen_name == "media-center"
            if center:
                media_locator(page, "#media-center-mode").click()
                page.wait_for_function(
                    "() => document.fullscreenElement === document.documentElement"
                )
                page.wait_for_function(
                    "() => document.querySelector('#media-frame')"
                    ".getBoundingClientRect().left === 0"
                )
            # Selection geometry stays fixed with artwork, without artwork and long text.
            feature = media_locator(page, "#media-feature")
            first_card = media_locator(page, ".media-row-card").filter(has_text="First Watch").first
            second_card = (
                media_locator(page, ".media-row-card").filter(has_text="Second Watch").first
            )
            first_card.click()
            expect(
                feature.locator(".media-feature-poster > img:not(.media-art-logo)")
            ).to_be_visible()
            frame_height = page.locator("#media-frame").bounding_box()["height"]
            banner_height = 300 if frame_height <= 600 else 380
            assert feature.bounding_box()["height"] == banner_height

            def geometry():
                return feature.evaluate("""node => [
              node.getBoundingClientRect().height,
              ...['.media-feature-poster', 'h2', '.media-feature-actions'].flatMap(selector => {
                const r = node.querySelector(selector).getBoundingClientRect();
                const banner = node.getBoundingClientRect();
                return [r.x - banner.x, r.y - banner.y, r.width, r.height];
              })]""")

            before_selection = geometry()
            description = feature.locator(".media-feature-description")
            assert description.evaluate("node => node.scrollHeight > node.clientHeight")
            description.focus()
            if screen_name.startswith("phone"):
                description.evaluate("node => { node.scrollTop = node.scrollHeight; }")
            else:
                description.press("End")
            expect(description).to_contain_text(synopsis.strip())
            expect(description).to_have_js_property(
                "scrollTop", description.evaluate("node => node.scrollHeight - node.clientHeight")
            )
            second_card.click()
            expect(feature.locator(".media-feature-poster .media-art-logo")).to_be_visible()
            assert geometry() == before_selection
            expect(feature.locator(".media-feature-description")).to_contain_text(
                "No local synopsis"
            )
            seen = feature.locator(".media-seen")
            expect(seen).to_have_attribute("aria-pressed", "false")
            seen.click()
            expect(seen).to_have_attribute("aria-pressed", "true")
            assert seen.evaluate("node => getComputedStyle(node).color") == "rgb(110, 213, 154)"
            first_card.click()
            expect(seen).to_have_attribute("aria-pressed", "false")
            second_card.click()
            expect(seen).to_have_attribute("aria-pressed", "true")
            seen.click()
            expect(seen).to_have_attribute("aria-pressed", "false")
            assert geometry() == before_selection
            # Médias has no page heading: not before the film, and not after it either.
            expect(page.locator("main > header")).to_be_hidden()
            media_locator(page, ".media-feature-actions .media-primary").click()
            video = page.locator("#media-video")
            page.wait_for_function("() => document.querySelector('#media-video').currentTime > 0.2")
            view = media_locator(page, "#view-media")
            expect(view).to_have_attribute("data-watch", "true")
            feature = media_locator(page, "#media-feature")
            expect(feature).to_be_visible()
            expect(feature.locator(".media-description-toggle")).to_have_count(0)
            expect(feature.locator(".media-feature-tag")).to_have_count(4)
            expect(feature.locator(".media-feature-description")).to_be_visible()
            screen = media_locator(page, "#media-screen")
            frame = page.locator("#media-frame")
            assert screen.bounding_box()["width"] >= frame.bounding_box()["width"] - 2
            if screen_name in ("computer", "media-center"):
                assert screen.bounding_box()["height"] >= 500
            toggle = watch_control(page, "#watch-toggle")
            assert (
                toggle.bounding_box()["y"]
                > screen.bounding_box()["y"] + screen.bounding_box()["height"] * 0.7
            )
            toggle.click()
            expect(toggle).to_have_attribute("aria-label", "Play")
            assert video.evaluate("node => node.paused")
            toggle.click()
            page.wait_for_function("() => !document.querySelector('#media-video').paused")
            volume = media_locator(page, "#watch-volume")
            volume.press("Home")
            page.wait_for_function("() => document.querySelector('#media-video').volume === 0")
            volume.press("End")
            page.wait_for_function("() => document.querySelector('#media-video').volume === 1")
            # The banner, not the video, pins; the menu never changes its offset.
            scroller = media_locator(page, ".media-scroll")
            stage_height = screen.bounding_box()["height"]
            scroller.evaluate("node => { node.scrollTop = 60; }")
            expect(view).to_have_attribute("data-bar", "hidden")
            scroller.evaluate("(node, y) => { node.scrollTop = y; }", stage_height + 120)
            expect(view).not_to_have_attribute("data-bar", "hidden")
            before = feature.bounding_box()
            assert abs(before["y"] - frame.bounding_box()["y"]) <= 1
            scroller.evaluate("node => { node.scrollTop -= 30; }")
            expect(view).not_to_have_attribute("data-bar", "hidden")
            after = feature.bounding_box()
            assert before["y"] == after["y"]
            assert before["height"] == after["height"]
            # A single poster click selects without restarting or replacing playback.
            source = video.get_attribute("src")
            playing = feature.locator("h2").inner_text()
            other = "Second Watch" if "First" in playing else "First Watch"
            media_locator(page, ".media-row-card").filter(has_text=other).first.click()
            expect(feature.locator("h2")).to_contain_text(other)
            assert video.get_attribute("src") == source
            feature.locator(".media-primary").click()
            page.wait_for_function(
                "old => document.querySelector('#media-video').getAttribute('src') !== old",
                arg=source,
            )
            # Full screen preserves Media Center and returns to the theatre view.
            scroller.evaluate("node => { node.scrollTop = 0; }")
            watch_control(page, "#watch-full").click()
            expect(view).to_have_attribute("data-full", "true")
            expect(feature).to_be_hidden()
            page.wait_for_function(
                "() => { const r = document.querySelector('#media-player-shell')"
                ".getBoundingClientRect(); return r.x === 0 && r.y === 0 && "
                "r.width === innerWidth && r.height === innerHeight; }"
            )
            watch_control(page, "#watch-full").click()
            expect(view).to_have_attribute("data-full", "false")
            expect(feature).to_be_visible()
            if center:
                assert page.evaluate("document.body.classList.contains('media-center-mode')")
            watch_control(page, "#watch-stop").click()
            expect(view).to_have_attribute("data-watch", "false")
            expect(feature).to_be_visible()
            assert video.get_attribute("src") is None
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


def test_compatible_quality_keeps_film_time_captions_and_clicks(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_media_api import media_app
    from tests.test_media_conversion import video

    app, root = media_app(tmp_path)
    video(root / "Compatible.2024.mkv", seconds=30)
    (root / "Compatible.2024.srt").write_text(
        "1\n00:00:08,000 --> 00:00:28,000\nCaption at film time\n"
    )
    app.state.agent_service.media.scan("default", threading.Event(), lambda _p: None)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "media")
            media_locator(page, ".media-row-card").filter(has_text="Compatible").first.click()
            media_locator(page, ".media-feature-actions .media-primary").click()
            page.wait_for_function("() => document.querySelector('#media-video').currentTime > 0")
            toggle = watch_control(page, "#watch-toggle")
            toggle.click()
            page.wait_for_function("() => document.querySelector('#media-video').paused")
            seek = watch_control(page, "#watch-seek")
            seek.fill("10")
            seek.dispatch_event("change")
            page.wait_for_function("() => document.querySelector('#media-video').currentTime >= 10")
            watch_control(page, "#watch-settings").click()
            menu = media_locator(page, "#watch-settings-menu")
            menu.get_by_role("menuitem", name=re.compile("Quality")).click()
            menu.get_by_role("menuitemradio", name=re.compile("360p")).click()
            page.wait_for_function("() => document.querySelector('#media-video').readyState >= 2")
            expect(watch_control(page, "#watch-time")).to_contain_text("0:30")
            assert page.locator("#media-video").evaluate("p => p.paused")
            watch_control(page, "#watch-settings").click()
            menu.get_by_role("menuitem", name=re.compile("Subtitles")).click()
            expect(menu.get_by_role("menuitemradio")).to_have_count(2)
            menu.get_by_role("menuitemradio").last.click()
            watch_control(page, "#watch-toggle").click()
            page.wait_for_function("() => document.querySelector('#media-video').currentTime > 0.2")
            # The cue starts at film second 8, even though the new stream starts at 10.
            page.wait_for_function("""() => [...document.querySelector('#media-video').textTracks]
                .some(t => t.mode === 'showing' && [...(t.activeCues || [])]
                .some(c => c.text.includes('Caption at film time')))""")
            # Holding the pointer across a progress render must not lose the click.
            for paused in (True, False, True, False, True):
                button = watch_control(page, "#watch-toggle")
                button.click(delay=350)
                page.wait_for_function(
                    "expected => document.querySelector('#media-video').paused === expected",
                    arg=paused,
                )
            page.wait_for_function(
                "() => document.querySelector('#media-video').buffered.length > 0"
            )
            expect(media_locator(page, ".media-timeline")).to_have_attribute(
                "style", re.compile("--buffered-track:.*linear-gradient")
            )
            watch_control(page, "#watch-settings").click()
            menu.get_by_role("menuitem", name=re.compile("Playback speed")).click()
            menu.get_by_role("menuitemradio", name="1.5×", exact=True).click()
            page.wait_for_function(
                "() => document.querySelector('#media-video').playbackRate === 1.5"
            )
            watch_control(page, "#watch-stop").click()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
