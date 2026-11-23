"""Media user flows through the native player and saved library interfaces."""

from pathlib import Path

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def video_js(qtbot, tab, script):
    from tests.test_community_interfaces import js

    return js(qtbot, tab.browser, script)


def video_wait(qtbot, tab, script):
    from tests.test_community_interfaces import wait_js

    wait_js(qtbot, tab.browser, script)


def player_js(qtbot, tab, script):
    from tests.test_community_interfaces import js, wait_js

    wait_js(qtbot, tab.video_controls, "typeof request === 'function'")
    return js(qtbot, tab.video_controls, script)


def player_select(qtbot, tab, kind, identifier):
    """A video's tracks are chosen from the page's "Audio and subtitles" (layout A)."""
    import json

    video_wait(qtbot, tab, "typeof watchPlayback === 'function' && !!watchPlayback()")
    values = json.dumps({"kind": kind, "track_id": identifier})
    video_js(qtbot, tab, f"watchSend('select_track', {values})")


def video_details(qtbot, tab, title):
    import json

    video_wait(qtbot, tab, "!!document.querySelector('#media-feature h2')")
    video_js(qtbot, tab, "document.querySelector('#media-details').close()")
    video_js(
        qtbot,
        tab,
        "document.querySelector('#media-search').value="
        + json.dumps(title)
        + ";document.querySelector('#media-search').dispatchEvent(new Event('input'))",
    )
    video_wait(
        qtbot,
        tab,
        "document.querySelector('#media-feature h2')?.textContent===" + json.dumps(title),
    )
    video_js(
        qtbot,
        tab,
        "[...document.querySelectorAll('#media-feature button')]"
        ".find(b=>b.textContent==='File details').click()",
    )
    video_wait(qtbot, tab, "document.querySelector('#media-details').open")


def video_action(qtbot, tab, label):
    import json

    video_js(
        qtbot,
        tab,
        "[...document.querySelectorAll('#media-details button')].find(b=>b.textContent==="
        + json.dumps(label)
        + ").click()",
    )


def test_media_workspace_opens_without_starting_connected_services(qtbot, tmp_path: Path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    assert "Media" in [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert window.agent_runtime is None
    assert window.media_tab.player is None


def test_native_track_playback_seek_and_browsing_keep_the_same_player(qtbot, tmp_path, monkeypatch):

    import math
    import struct
    import threading
    import wave

    from PySide6.QtCore import Qt
    from PySide6.QtMultimedia import QMediaPlayer

    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.web.app import create_app

    root = tmp_path / "music"
    root.mkdir()
    with wave.open(str(root / "tone.wav"), "wb") as track:
        track.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        track.writeframes(
            b"".join(struct.pack("<h", int(3000 * math.sin(i / 10))) for i in range(22050 * 12))
        )
    import shutil

    shutil.copy(root / "tone.wav", root / "second.wav")
    shutil.copy(root / "tone.wav", root / "third.wav")
    from mutagen.id3 import TALB, TIT2, TPE1, TRCK
    from mutagen.wave import WAVE

    for index, name in enumerate(("tone.wav", "second.wav", "third.wav"), 1):
        tags = WAVE(root / name)
        tags.add_tags()
        tags.tags.add(TIT2(encoding=3, text=[f"Tone {index}"]))
        tags.tags.add(TPE1(encoding=3, text=["Fixture Artist"]))
        tags.tags.add(TALB(encoding=3, text=["Fixture Album"]))
        tags.tags.add(TRCK(encoding=3, text=[str(index)]))
        tags.save()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    config = tmp_path / "config"
    config.mkdir()
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    service.agent.media.scan("default", threading.Event(), lambda _progress: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(800, 800)
    tab.show()
    tab.activate()
    video_wait(qtbot, tab, "!!document.querySelector('#media-status')?.textContent")
    video_js(qtbot, tab, "document.querySelector('#media-music-tab').click()")
    video_wait(
        qtbot,
        tab,
        "document.querySelector('#view-media').dataset.kind==='music'"
        "&&document.querySelectorAll('#media-results .media-music-card').length===1",
    )
    assert tab.browse_kind == "music"
    assert video_js(qtbot, tab, "!document.querySelector('#media-playlists').hidden")
    video_js(qtbot, tab, "document.querySelector('[data-media-music-view=tracks]').click()")
    video_wait(qtbot, tab, "document.querySelectorAll('.media-track-row').length===3")
    first = video_js(qtbot, tab, "document.querySelector('.media-track-row').textContent")
    assert "Fixture Artist" in first and "Fixture Album" in first and "0:12" in first
    for view, card in (("albums", ".media-music-card"), ("artists", ".media-artist-card")):
        video_js(qtbot, tab, f"document.querySelector('[data-media-music-view={view}]').click()")
        video_wait(qtbot, tab, f"document.querySelectorAll('#media-results {card}').length===1")
    video_js(qtbot, tab, "document.querySelector('[data-media-music-view=tracks]').click()")
    video_wait(qtbot, tab, "document.querySelectorAll('.media-track-row').length===3")
    video_js(qtbot, tab, "document.querySelector('.media-track-play').click()")
    qtbot.waitUntil(lambda: tab.player.duration() == 12000, timeout=15000)
    qtbot.waitUntil(lambda: tab.player.position() > 0, timeout=10000)
    tab.command("seek", position=5)
    qtbot.waitUntil(lambda: tab.player.position() >= 5000)
    for index in (1, 2):
        video_js(
            qtbot,
            tab,
            f"document.querySelectorAll('.media-track-row')[{index}]"
            ".querySelector('.media-track-actions button').click()",
        )
        qtbot.waitUntil(lambda index=index: len(tab.queue_rows) == index + 1)
    video_wait(
        qtbot,
        tab,
        "document.querySelector('#media-show-queue').textContent.endsWith('3')"
        "&&!document.querySelector('#media-save-playlist button').disabled",
    )
    tab._open_queue()
    player_js(
        qtbot,
        tab,
        "window.prompt=()=> 'Evening';document.getElementById('player-playlist-save').click()",
    )
    qtbot.waitUntil(
        lambda: bool(tab.saved_playlists) and tab.saved_playlists[0]["name"] == "Evening"
    )
    assert len(service.agent.media.playlists("default")[0]["media_ids"]) == 3
    # The view saves the host queue as a playlist too and lists both.
    video_js(
        qtbot,
        tab,
        "document.querySelector('#media-playlist-name').value='Morning';"
        "document.querySelector('#media-save-playlist').requestSubmit()",
    )
    video_wait(qtbot, tab, "document.querySelectorAll('.media-playlist-card').length===2")
    assert sorted(p["name"] for p in service.agent.media.playlists("default")) == [
        "Evening",
        "Morning",
    ]
    assert all(len(p["media_ids"]) == 3 for p in service.agent.media.playlists("default"))
    qtbot.waitUntil(lambda: len(tab.saved_playlists) == 2)
    video_js(
        qtbot,
        tab,
        "[...document.querySelectorAll('.media-playlist-card')]"
        ".find(c=>c.querySelector('h3').textContent==='Morning')"
        ".querySelector('details button:last-child').click()",
    )
    video_wait(qtbot, tab, "document.querySelectorAll('.media-playlist-card').length===1")
    qtbot.waitUntil(lambda: len(tab.saved_playlists) == 1)
    video_js(qtbot, tab, "document.querySelector('.media-track-name').click()")
    video_wait(qtbot, tab, "document.querySelector('#media-details').open")
    qtbot.waitUntil(lambda: bool(tab.browse_selection))
    selected = tab.browse_selection[:]
    video_action(qtbot, tab, "Close details")
    assert tab.browse_selection == selected
    video_js(qtbot, tab, "document.querySelector('#media-show-queue').click()")
    qtbot.waitUntil(lambda: tab.queue_open)
    source = tab.player.source()
    for layout in ("focus", "horizon", "cinematic"):
        tab.set_media_layout(layout)
        assert tab.media_layout == layout
        assert tab.player.source() == source
        video_wait(qtbot, tab, "document.querySelector('#view-media').dataset.kind==='music'")
    video_js(qtbot, tab, "document.querySelector('#media-video-tab').click()")
    qtbot.waitUntil(lambda: tab.browse_kind == "video")
    assert tab.player.source() == source
    assert tab.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    # In Video, playing music keeps its bar so it can be paused; paused, the bar leaves.
    assert tab.player_panel.isVisible()
    tab.player.pause()
    qtbot.waitUntil(lambda: not tab.player_panel.isVisible())
    tab.player.play()
    qtbot.waitUntil(lambda: tab.player_panel.isVisible())
    from torrentlinker.gui.media import CHAT_MIN_WIDTH, MEDIA_MIN_WIDTH

    tab.resize(1280, 720)
    qtbot.mouseClick(tab.chat, Qt.LeftButton)
    assert tab.assistant.conversation_id == tab.conversation_id
    assert isinstance(tab.conversation_id, str)
    first_conversation = tab.conversation_id
    # The side panel is one discussion: no folders, tabs or full-width buttons.
    assert tab.chat.isChecked() and tab.assistant.isVisible()
    from tests.test_community_interfaces import js, wait_js

    wait_js(qtbot, tab.assistant, "!!document.querySelector('#media-chat-close')")
    assert js(qtbot, tab.assistant, "document.querySelectorAll('.assistant-tabs').length===0")
    assert js(
        qtbot,
        tab.assistant,
        "getComputedStyle(document.querySelector('.assistant-conversations')).display==='none'",
    )
    # Both sides fit a 1280-wide window with room to drag the divider.
    media_side = tab.splitter.widget(0).minimumSizeHint().width()
    chat_side = tab.assistant.minimumSizeHint().width()
    assert media_side <= MEDIA_MIN_WIDTH and chat_side <= CHAT_MIN_WIDTH, (media_side, chat_side)
    total = sum(tab.splitter.sizes())
    tab.splitter.moveSplitter(total - 450, 1)
    qtbot.waitUntil(lambda: abs(tab.splitter.sizes()[1] - 450) <= 8)
    width = tab.splitter.sizes()[1]
    # ✦ closes what it opened; the width is remembered for the next opening.
    qtbot.mouseClick(tab.chat, Qt.LeftButton)
    assert tab.assistant.isHidden() and not tab.chat.isChecked()
    qtbot.mouseClick(tab.chat, Qt.LeftButton)
    assert tab.assistant.isVisible()
    assert tab.splitter.sizes()[1] == width
    assert tab.conversation_id == first_conversation
    # The ☰ menu starts a new media discussion and switches back, both bound to this player.
    tab.assistant.conversationRequested.emit("", True)
    assert tab.conversation_id != first_conversation
    assert tab.assistant.conversation_id == tab.conversation_id
    tab.assistant.conversationRequested.emit(first_conversation, False)
    assert tab.conversation_id == first_conversation
    assert tab.assistant.isVisible()
    tab.assistant.closeRequested.emit()
    assert tab.assistant.isHidden() and not tab.chat.isChecked()
    assert int(tab.credentials.value("chat_width")) == width
    # A restarted app opens the chat at the remembered width.
    restarted = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(restarted)
    restarted.resize(1280, 720)
    restarted.show()
    restarted.activate()
    qtbot.mouseClick(restarted.chat, Qt.LeftButton)
    assert restarted.splitter.sizes()[1] == width
    restarted.close_chat()
    restarted.stop()
    assert tab.player.source() == source
    assert tab.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    tab.command("pause")
    tab.report()
    saved = service.agent.media.detail("default", tab.state["current_id"])
    assert saved["position"] >= 5
    # While a resume point is still pending, the heartbeat must not overwrite it with 0.
    tab.pending_seek = 9000
    tab.report()
    assert service.agent.media.detail("default", tab.state["current_id"])["position"] == 9
    # The periodic heartbeat saves from a worker: a slow disk sync must not drop frames.
    import threading

    library, threads = service.agent.media, []
    original = library.session

    def recorded(*args, **kwargs):
        threads.append(threading.current_thread())
        return original(*args, **kwargs)

    library.session = recorded
    tab.pending_seek = 11000
    tab._heartbeat()
    assert tab.report_pending
    qtbot.waitUntil(lambda: not tab.report_pending)
    library.session = original
    assert threads and all(thread is not threading.main_thread() for thread in threads)
    assert library.detail("default", tab.state["current_id"])["position"] == 11
    tab.pending_seek = None
    tab.command("shuffle", shuffle=True)
    tab.command("repeat", repeat="all")
    tab.command("play", media_ids=tab.state["queue"], index=1)
    qtbot.waitUntil(lambda: tab.player.duration() == 12000)
    playing = tab.player.source()
    tab.remove_from_queue(0)
    assert tab.player.source() == playing
    assert tab.state["index"] == 0
    assert len(tab.queue_rows) == 2
    tab.stop()
    restored = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(restored)
    restored.activate()
    assert restored.session_id == tab.session_id
    assert restored.state["queue"] == tab.state["queue"]
    assert restored.state["shuffle"]
    assert restored.state["repeat"] == "all"
    assert restored.conversation_id == first_conversation
    qtbot.waitUntil(lambda: restored.player.duration() == 12000)
    assert restored.player.source() == playing
    assert restored.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    restored.report()
    restored.stop()


def test_native_video_plays_with_local_subtitles(qtbot, tmp_path, request):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    import shutil
    import subprocess
    import threading

    import pytest
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg fixture generator unavailable")
    root = tmp_path / "video"
    root.mkdir()
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=10",
            "-t",
            "12",
            "-c:v",
            "mpeg4",
            str(root / "Clip.mp4"),
        ],
        check=True,
        capture_output=True,
    )
    for index in range(3):
        shutil.copy(root / "Clip.mp4", root / f"Other {index}.mp4")
    (root / "Clip.srt").write_text("1\n00:00:01,000 --> 00:00:10,000\nA local caption\n")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    service.agent.media.scan("default", threading.Event(), lambda _progress: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(760, 560)  # the picture fills the space the page gives it (layout A)
    tab.show()
    tab.activate()
    video_details(qtbot, tab, "Other 0")
    assert "No external subtitle files" in video_js(
        qtbot, tab, "document.querySelector('#media-details').innerText"
    )
    video_details(qtbot, tab, "Clip")
    details = video_js(qtbot, tab, "document.querySelector('#media-details').innerText")
    assert "External subtitle files" in details and "Clip" in details
    assert "Filename metadata" in video_js(
        qtbot,
        tab,
        "document.querySelector('#media-feature .media-selection-info-body').textContent",
    )
    video_action(qtbot, tab, "Play")
    qtbot.waitUntil(lambda: tab.player.hasVideo(), timeout=15000)
    qtbot.waitUntil(lambda: len(tab._track_state()["subtitles"]) == 1)
    player_select(qtbot, tab, "subtitle", tab._track_state()["subtitles"][0]["id"])
    tab.command("seek", position=2)
    qtbot.waitUntil(lambda: tab.caption.text() == "A local caption")
    qtbot.waitUntil(lambda: tab.player.videoSink().videoFrame().isValid(), timeout=10000)
    # The shared theatre draws controls over the picture; the old control bar stays hidden.
    assert not tab.video_controls.isVisible()
    video_wait(qtbot, tab, "!!document.getElementById('watch-toggle')")

    def blue_picture():
        rendered = tab.video.grab().toImage()
        sample = rendered.pixelColor(rendered.width() // 2, rendered.height() // 3)
        return sample.blue() > 150 and sample.red() < 80

    # The picture behind the page shows the film once a frame is drawn after the seek.
    qtbot.waitUntil(blue_picture, timeout=5000)
    from PySide6.QtCore import QPoint

    tab.player.pause()
    source, position = tab.player.source(), tab.player.position()
    video_js(qtbot, tab, "watchSend('volume', {volume: 0.4})")
    qtbot.waitUntil(lambda: abs(tab.audio.volume() - 0.4) < 0.01)
    video_js(qtbot, tab, "watchSend('volume', {volume: 1})")
    qtbot.waitUntil(lambda: tab.audio.volume() == 1)
    original_parent = tab.player_panel.parentWidget()
    video_js(qtbot, tab, "watchSend('fullscreen')")
    qtbot.waitUntil(lambda: tab.player_panel.window().isFullScreen())
    assert tab.caption.isVisible()
    assert tab.subtitle_choice == tab.current_row["subtitles"][0]["id"]
    assert tab.video.mapTo(tab.fullscreen_dialog, tab.video.rect().topLeft()).isNull()
    # The page measures its full-screen slot again, then the picture follows it.
    qtbot.waitUntil(lambda: tab.video.size() == tab.fullscreen_dialog.size())
    assert tab.player.source() == source
    assert tab.player.position() == position
    size = max(16, min(56, tab.video.overlay.height() // 20))
    assert f"font-size: {size}px" in tab.caption.styleSheet()
    # What the label really draws with, after the page stylesheet is applied.
    tab.caption.ensurePolished()
    assert tab.caption.fontInfo().pixelSize() >= size - 1
    # Two, three and wrapped lines all keep their full height inside the picture.
    for text, lines in (
        ("Un ange est descendu\ndes sphères célestes", 2),
        ("Un ange est descendu\ndes sphères célestes\npour nous parler", 3),
        ("Un ange est descendu des sphères célestes " * 6, 3),
    ):
        tab.caption.setText(text)
        tab._fit_caption()
        qtbot.wait(20)
        assert tab.caption.height() >= lines * tab.caption.fontInfo().pixelSize()
        # Qt's own wrapping at the label's real width fits the height it was given.
        assert tab.caption.heightForWidth(tab.caption.width()) <= tab.caption.height()
        bottom = tab.caption.mapTo(tab.video, tab.caption.rect().bottomLeft())
        assert tab.video.rect().contains(bottom)
    fullscreen_size = tab.caption_size
    fullscreen_height = tab.video.overlay.height()
    qtbot.keyClick(tab.fullscreen_dialog, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: tab.player_panel.parentWidget() is original_parent)
    # Back in the window, the picture returns to the page's slot once the page measures it.
    qtbot.waitUntil(lambda: tab.video.overlay.height() < fullscreen_height)
    tab.caption.setText("Viens à moi.")
    tab._fit_caption()
    assert tab.caption_size == max(16, min(56, tab.video.overlay.height() // 20))
    assert tab.caption_size <= fullscreen_size
    assert tab.player.source() == source
    # Double-clicking the picture enters and leaves fullscreen without pausing or playing.
    state = tab.player.playbackState()
    qtbot.mouseDClick(tab.video.overlay, Qt.LeftButton, pos=QPoint(80, 80))
    qtbot.waitUntil(lambda: tab.player_panel.window().isFullScreen())
    qtbot.mouseDClick(tab.video.overlay, Qt.LeftButton, pos=QPoint(80, 80))
    qtbot.waitUntil(lambda: tab.player_panel.parentWidget() is original_parent)
    qtbot.wait(QApplication.doubleClickInterval() + 50)
    assert tab.player.playbackState() == state
    assert tab.player.position() == position
    video_js(qtbot, tab, "watchSend('fullscreen')")
    qtbot.waitUntil(lambda: tab.player_panel.window().isFullScreen())
    video_js(qtbot, tab, "watchSend('stop')")
    qtbot.waitUntil(lambda: not tab.fullscreen_dialog.isVisible())
    assert tab.player_panel.window() is tab
    assert not tab.video.isVisible()
    assert not tab.player_panel.isVisible()
    assert tab.player.source().isEmpty()
    assert not tab.last_source
    assert tab.heartbeat.isActive()
    saved_queue = list(tab.state["queue"])
    assert saved_queue
    tab.command("play", media_ids=saved_queue, index=0)
    qtbot.waitUntil(lambda: tab.video.isVisible())
    tab._browser_action("kind", {"kind": "video"})
    assert not tab.video.isVisible()
    assert not tab.player_panel.isVisible()
    tab.command("play", media_ids=saved_queue, index=0)
    qtbot.waitUntil(lambda: tab.video.isVisible())
    tab._browser_action("kind", {"kind": "music"})
    assert not tab.video.isVisible()
    assert tab.player.source().isEmpty()
    assert tab.state["queue"] == saved_queue
    assert tab.heartbeat.isActive()
    tab.stop()
    # A restart opens the library, not the dismissed film still in the saved queue.
    restarted = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(restarted)
    restarted.activate()
    assert not restarted.last_source
    assert restarted.player.source().isEmpty()
    restarted.stop()


def test_native_explicit_preview_decodes_h264_without_reading_missing_pieces(qtbot, tmp_path):
    import math
    import shutil
    import subprocess
    import threading

    import pytest
    from PySide6.QtCore import QCoreApplication, QThreadPool

    from torrentlinker.domain import LibraryFolder, Torrent
    from torrentlinker.gui.media import DownloadingFileDevice, MediaTab
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg fixture generator unavailable")
    root = tmp_path / "video"
    root.mkdir()
    source = root / "Downloading.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=10",
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "10",
            "-movflags",
            "+faststart",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    total = source.stat().st_size
    pieces = math.ceil(total / 4096)
    verified_pieces = pieces // 2
    verified_bytes = verified_pieces * 4096

    class SequentialQbit:
        delay = False
        entered = threading.Event()
        release = threading.Event()

        def torrents(self, **_kwargs):
            return [self.torrent("a" * 40)]

        def torrent(self, _hash, **_kwargs):
            return Torrent("a" * 40, source.name, root, {source.name: total}, progress=0.5)

        def media_preview_state(self, _hash):
            if self.delay:
                self.delay = False
                self.entered.set()
                assert self.release.wait(10), "The delayed preview fixture was not released"
            return {
                "sequential": True,
                "files": [{"name": source.name, "size": total, "piece_range": [0, pieces - 1]}],
                "piece_size": 4096,
                "piece_states": [2] * verified_pieces + [0] + [2] * (pieces - verified_pieces - 1),
            }

    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    client = SequentialQbit()
    service.agent.setup._client = client
    service.agent.setup.configured = True
    service.agent.media.scan("default", threading.Event(), lambda _progress: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    try:
        tab.show()
        tab.activate()
        video_details(qtbot, tab, "Downloading")
        video_js(qtbot, tab, "document.querySelector('#media-details').close()")
        video_wait(
            qtbot,
            tab,
            "[...document.querySelectorAll('#media-feature button')]"
            ".some(b=>b.textContent==='Preview downloaded portion'&&!b.disabled)",
        )
        video_js(
            qtbot,
            tab,
            "[...document.querySelectorAll('#media-feature button')]"
            ".find(b=>b.textContent==='Preview downloaded portion').click()",
        )
        qtbot.waitUntil(lambda: tab.preview_device is not None, timeout=10000)
        qtbot.waitUntil(lambda: tab.player.videoSink().videoFrame().isValid(), timeout=15000)
        assert tab.player.sourceDevice().size() == total  # the whole file, read as it downloads
        assert tab.player.source().toString() == "verified-preview.mp4"
        assert tab._player_snapshot()["preview"]
        assert not tab._player_snapshot()["preview_loading"]
        tab.command("seek", position=1)
        qtbot.waitUntil(lambda: tab.player.position() >= 1000)
        completed = root / "Complete.mp4"
        shutil.copy(source, completed)
        service.agent.media.scan("default", threading.Event(), lambda _progress: None)
        tab.refresh()
        tab.dismiss_video()

        def select_release(name):
            video_details(qtbot, tab, name.removesuffix(".mp4"))

        def delayed_preview():
            client.entered.clear()
            client.release.clear()
            client.delay = True
            select_release(source.name)
            video_action(qtbot, tab, "Preview downloaded portion")
            qtbot.waitUntil(client.entered.is_set)

        delayed_preview()
        select_release(completed.name)
        video_action(qtbot, tab, "Play")
        qtbot.waitUntil(lambda: tab.player.source().toLocalFile() == str(completed))
        expected = tab.player.source()
        assert expected.toLocalFile() == str(completed)
        client.release.set()
        qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
        QCoreApplication.processEvents()
        assert tab.player.source() == expected
        assert tab.preview_id == ""
        assert tab.preview_device is None
        tab.dismiss_video()
        delayed_preview()
        tab.stop()
        client.release.set()
        qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
        QCoreApplication.processEvents()
        assert tab.preview_id == ""
        assert tab.preview_device is None
        assert tab.player.playbackState() == tab.player.PlaybackState.StoppedState
        states = [True] * verified_pieces + [False] + [True] * (pieces - verified_pieces - 1)
        data = source.read_bytes()
        downloading = DownloadingFileDevice(source, total, 4096, states)
        # Verified pieces are read; the missing one is never read.
        assert downloading.readData(total) == data[:verified_bytes]
        assert downloading.seek(verified_bytes + 4096)
        assert downloading.readData(100) == data[verified_bytes + 4096 :][:100]
        # A read of the missing piece waits until qBittorrent verifies it.
        assert downloading.seek(verified_bytes)
        later = threading.Timer(0.3, downloading.update, ([True] * pieces,))
        later.start()
        assert downloading.readData(4096) == data[verified_bytes : verified_bytes + 4096]
        # Stopping the preview ends a wait at once.
        waiting = DownloadingFileDevice(source, total, 4096, states)
        assert waiting.seek(verified_bytes)
        threading.Timer(0.3, waiting.abort).start()
        assert waiting.readData(4096) == b""
        assert waiting.atEnd()  # Qt's reader stops only at end of file; an empty read loops
        waiting.close()
        downloading.close()

    finally:
        tab.stop()


def test_media_profile_editor_keeps_the_player_and_media_workspace(
    qtbot, tmp_path, request, monkeypatch
):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    from tests.settings_support import edit_field, save_group
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.web.app import create_app

    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.save(config / "settings.json")
    app = create_app(config, password="test-password-long", monitor_verifications=False)
    window = MainWindow(settings, config / "settings.json", Store(config / "state.db"))
    windows = [window]

    def cleanup():
        for widget in windows:
            if isValid(widget):
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    request.addfinalizer(cleanup)
    window.media_tab.get_service = lambda: app.state.assistant
    window.show()
    window.tabs.setCurrentWidget(window.media_tab)
    tab = window.media_tab
    qtbot.waitUntil(lambda: tab.browser is not None and tab.player is not None)
    tab.command("shuffle", shuffle=True)
    tab.command("repeat", repeat="all")
    player = tab.player
    window.set_media_center(True)
    qtbot.waitUntil(window.isFullScreen)
    assert window.media_center_active

    def save_editor(dialog):
        wait_js(qtbot, dialog.view, "Boolean(document.querySelector('.settings-form h2'))")
        js(
            qtbot,
            dialog.view,
            "[...document.querySelectorAll('#settings-navigation button"
            "')].find(b=>b.textContent==='Connections').click()",
        )
        edit_field(qtbot, dialog.view, "Client name", "Media client")
        save_group(qtbot, dialog)

    # Settings is a page: edit it once opened, then leave it, which applies it.
    original_open = MainWindow.open_settings

    def open_then_edit(self, **kwargs):
        original_open(self, **kwargs)
        if self._settings_page is not None:
            save_editor(self._settings_page)
            self.close_settings()

    monkeypatch.setattr(MainWindow, "open_settings", open_then_edit)
    window.open_client_profiles()
    replacement = window
    assert replacement.settings.profile().name == "Media client"
    assert replacement.tabs.currentWidget() is tab
    assert replacement.isFullScreen()
    assert replacement.media_center_active
    assert tab.center_button.isChecked()
    assert replacement.media_tab.player is player
    assert tab.heartbeat.isActive()
    assert tab.state["shuffle"]
    assert tab.state["repeat"] == "all"
    replacement.assistant_tab.get_service = lambda: app.state.assistant
    opened = []
    replacement.assistant_tab.select_conversation = opened.append
    tab.discussion_requested.emit("media-discussion")
    assert replacement.tabs.currentWidget() is replacement.assistant_tab
    assert opened == ["media-discussion"]
    cleanup()


def test_native_media_layout_shortcut_emits_only_user_changes(qtbot):
    from torrentlinker.gui.media import MediaTab

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    assert tab.media_layout == "cinematic"
    changes = []
    tab.layout_changed.connect(changes.append)
    tab.set_media_layout("horizon")
    assert changes == []
    tab._browser_action("layout", {"layout": "focus"})
    assert changes == ["focus"]
    assert tab.media_layout == "focus"


def test_player_menu_opens_and_closes_the_queue_and_playlists(qtbot):
    from torrentlinker.gui.media import MediaTab

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.browse_kind = "music"
    tab.resize(900, 700)
    tab.show()
    tab._open_queue()
    assert player_js(qtbot, tab, "document.getElementById('player-queue-details').open")
    player_js(qtbot, tab, "document.getElementById('player-queue-title').click()")
    assert not player_js(qtbot, tab, "document.getElementById('player-queue-details').open")


def test_native_multitrack_switching_decodes_audio_and_subtitles_and_keeps_choices(
    qtbot, tmp_path, request
):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    import shutil
    import struct
    import subprocess
    import threading

    import pytest
    from PySide6 import QtMultimedia
    from PySide6.QtMultimedia import QAudioFormat

    QAudioBufferOutput = getattr(QtMultimedia, "QAudioBufferOutput", None)
    if QAudioBufferOutput is None:
        pytest.skip("Decoded audio observation requires Qt 6.8 or later")

    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.web.app import create_app

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg fixture generator unavailable")
    root = tmp_path / "tracks"
    root.mkdir()
    french, english = tmp_path / "fr.srt", tmp_path / "en.srt"
    for path, caption in ((french, "French fixture caption"), (english, "English fixture caption")):
        path.write_text(
            "\n".join(
                f"{i}\n00:00:0{i},000 --> 00:00:0{i},900\n{caption}\n" for i in range(1, 9, 2)
            )
        )
    source = root / "Multitrack.mkv"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000",
            "-i",
            str(french),
            "-i",
            str(english),
            "-map",
            "0",
            "-map",
            "1",
            "-map",
            "2",
            "-map",
            "3",
            "-map",
            "4",
            "-t",
            "10",
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            "-c:s",
            "srt",
            "-metadata:s:a:0",
            "language=fra",
            "-metadata:s:a:0",
            "title=Low tone",
            "-metadata:s:a:1",
            "language=eng",
            "-metadata:s:a:1",
            "title=High tone " + "x" * 450,
            "-metadata:s:s:0",
            "language=fra",
            "-metadata:s:s:1",
            "language=eng",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    shutil.copy(source, root / "Other.mkv")
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    web = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = web.state.assistant
    service.agent.media.scan("default", threading.Event(), lambda _: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(1000, 800)
    try:
        tab.show()
        tab.activate()
        tab.audio.setMuted(True)
        output = QAudioBufferOutput(tab)
        tab.player.setAudioBufferOutput(output)
        frequencies = []

        def decoded(buffer):
            formats = {
                QAudioFormat.SampleFormat.Int16: "h",
                QAudioFormat.SampleFormat.Int32: "i",
                QAudioFormat.SampleFormat.Float: "f",
            }
            code = formats.get(buffer.format().sampleFormat())
            if not code or buffer.frameCount() < 100:
                return
            samples = [row[0] for row in struct.iter_unpack("<" + code, bytes(buffer.constData()))]
            samples = samples[:: buffer.format().channelCount()]
            crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:], strict=False))
            frequencies.append(crossings * buffer.format().sampleRate() / len(samples))

        output.audioBufferReceived.connect(decoded)
        captions = []
        tab.player.videoSink().subtitleTextChanged.connect(lambda text: captions.append(text))
        tab.player.videoSink().videoFrameChanged.connect(
            lambda frame: captions.append(frame.subtitleText())
        )
        video_details(qtbot, tab, "Multitrack")
        video_js(qtbot, tab, "document.querySelector('#media-details').close()")

        def deliver(action, **values):
            sequence = tab.command_ack + 1
            tab.apply_player_commands([{"sequence": sequence, "action": action, **values}])
            return sequence

        media_id = tab.selected_ids()[0]
        deliver(
            "play", media_ids=[media_id], index=0, start_paused=True, load_token="prepared-fixture"
        )
        qtbot.waitUntil(
            lambda: len(tab.player.audioTracks()) == 2 and len(tab._track_state()["subtitles"]) == 2
        )
        from PySide6.QtMultimedia import QMediaPlayer

        assert tab.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        tab.report()
        reported = service.agent.media.session(tab.session_id, tab.token)["state"]["track_state"]
        assert reported["ready"]
        assert reported["media_id"] == media_id
        assert reported["source_token"] == "prepared-fixture"
        assert reported["audio"][1]["id"] == "audio:1"
        assert reported["audio"][1]["language"] == "en"
        assert len(reported["audio"][1]["label"]) == 300
        assert len(tab._track_label(tab.player.audioTracks()[1], "Audio 2")) > 400
        rejected = deliver(
            "select_track",
            kind="audio",
            track_id="audio:1",
            media_id=media_id,
            source_token="old-source",
        )
        tab.report()
        failure = service.agent.media.session(tab.session_id, tab.token)["state"]["track_result"]
        assert failure["sequence"] == rejected
        assert not failure["applied"]
        assert tab.player.activeAudioTrack() == 0
        assert "French" in tab._track_state()["audio"][0]["label"]
        assert "Low tone" in tab._track_state()["audio"][0]["label"]
        assert "English" in tab._track_state()["audio"][1]["label"]
        assert "French" in tab._track_state()["subtitles"][0]["label"]
        deliver("play", media_id=media_id, source_token="prepared-fixture")
        qtbot.waitUntil(lambda: any(400 < value < 480 for value in frequencies), timeout=10000)
        selected_sequence = deliver(
            "select_track",
            kind="audio",
            track_id="audio:1",
            media_id=media_id,
            source_token="prepared-fixture",
        )
        tab.report()
        selection = service.agent.media.session(tab.session_id, tab.token)["state"]["track_result"]
        assert selection == {"sequence": selected_sequence, "applied": True, "error": ""}
        deliver(
            "select_track",
            kind="subtitle",
            track_id="embedded:1",
            media_id=media_id,
            source_token="prepared-fixture",
        )
        qtbot.waitUntil(lambda: tab.player.activeAudioTrack() == 1)
        qtbot.waitUntil(lambda: any(830 < value < 930 for value in frequencies), timeout=10000)
        deliver("seek", position=2)
        qtbot.waitUntil(
            lambda: any("English fixture caption" in text for text in captions), timeout=10000
        )
        qtbot.waitUntil(lambda: "English fixture caption" in tab.caption.text(), timeout=10000)
        assert tab.caption.isVisible()
        qtbot.waitUntil(
            lambda: tab.video.rect().contains(
                tab.caption.mapTo(tab.video, tab.caption.rect().center())
            ),
            timeout=5000,
        )
        caption_pixels = tab.caption.grab().toImage()
        white_pixels = sum(
            caption_pixels.pixelColor(x, y).lightness() > 200
            for x in range(caption_pixels.width())
            for y in range(caption_pixels.height())
        )
        assert white_pixels > 15
        qtbot.waitUntil(lambda: tab.player.position() >= 4050, timeout=3000)
        assert tab.player.position() < 4800
        assert tab.caption.text() == ""
        assert not tab.caption.isVisible()
        deliver("seek", position=3)
        tab.player.tracksChanged.emit()
        tab.toggle_fullscreen()
        assert tab.audio_choice == 1
        assert tab.subtitle_choice == 1
        assert tab.player.activeAudioTrack() == 1
        assert tab.player.activeSubtitleTrack() == 1
        tab.toggle_fullscreen()
        # A choice the page drew for this film, kept to be sent after the film has changed.
        video_wait(qtbot, tab, "typeof watchPlayback === 'function' && !!watchPlayback()")
        video_js(
            qtbot,
            tab,
            "window.staleAudioChange=(play=>()=>host('player',{action:'select_track',"
            "values:{kind:'audio',track_id:'audio:1'},client_id:play.client_id,"
            "media_id:play.media_id,source_token:play.source_token,"
            "queue_revision:play.queue_revision}))(watchPlayback())",
        )
        player_select(qtbot, tab, "audio", "audio:0")
        qtbot.waitUntil(lambda: tab.player.activeAudioTrack() == 0)
        player_select(qtbot, tab, "subtitle", "embedded:0")
        frequencies.clear()
        qtbot.waitUntil(lambda: any(400 < value < 480 for value in frequencies), timeout=10000)
        qtbot.waitUntil(
            lambda: any("French fixture caption" in text for text in captions), timeout=10000
        )
        qtbot.waitUntil(lambda: tab.player.videoSink().videoFrame().isValid())
        player_select(qtbot, tab, "audio", "audio:1")
        qtbot.waitUntil(lambda: tab.player.activeAudioTrack() == 1)
        current = tab.state["current_id"]
        other = next(
            row["id"]
            for row in service.agent.media.listing("default", kind="video")["rows"]
            if row["id"] != current
        )
        deliver("play", media_ids=[other], index=0)
        tab.report()
        replacement = service.agent.media.session(tab.session_id, tab.token)["state"]["track_state"]
        assert replacement["source_token"] != "prepared-fixture"
        qtbot.waitUntil(lambda: tab.player.activeAudioTrack() >= 0)
        stale_track = tab.player.activeAudioTrack()
        video_js(qtbot, tab, "window.staleAudioChange()")
        qtbot.waitUntil(lambda: "changed" in tab.notice.text())
        assert tab.player.activeAudioTrack() == stale_track
        deliver("pause")
        stale_resume = deliver("play", media_id=media_id, source_token="prepared-fixture")
        assert tab.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        tab.report()
        failure = service.agent.media.session(tab.session_id, tab.token)["state"]["track_result"]
        assert failure["sequence"] == stale_resume
        assert not failure["applied"]
        qtbot.waitUntil(
            lambda: tab.player.duration() == 10000 and len(tab.player.audioTracks()) == 2
        )
        assert tab.audio_choice == 0
        assert tab.player.activeAudioTrack() == 0
        assert tab.subtitle_choice == -1
        assert tab.player.activeSubtitleTrack() == -1
        from tests.test_agent_media import invoke

        discussion = service.media_chat(tab.session_id, tab.token)["conversation_id"]
        actor = service.conversation(discussion)[1]
        saved = invoke(
            web, actor, "search_media", client_id="default", kind="video", query="Multitrack"
        )
        prepared = invoke(
            web,
            actor,
            "play_media",
            selection_id=saved["selection_id"],
            audio_language="en",
            subtitle_language="en",
        )
        assert prepared["queued"]
        tab.report()
        assert tab.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState

        def request_status():
            return (
                service.agent.media.session(tab.session_id, tab.token)["state"]
                .get("track_request", {})
                .get("status")
            )

        qtbot.waitUntil(lambda: request_status() == "completed", timeout=10000)
        assert tab.player.activeAudioTrack() == 1
        assert tab.player.activeSubtitleTrack() == 1
        assert tab.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        bad_preference = invoke(
            web, actor, "play_media", selection_id=saved["selection_id"], audio_language="zz"
        )
        assert bad_preference["queued"]
        qtbot.waitUntil(lambda: request_status() == "failed", timeout=10000)
        assert tab.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        assert "No available track matches" in tab.notice.text()
        current_token = service.agent.media.session(tab.session_id, tab.token)["state"][
            "track_state"
        ]["source_token"]
        corrected = invoke(
            web,
            actor,
            "select_media_track",
            kind="audio",
            track_id="audio:0",
            source_token=current_token,
        )
        assert corrected["queued"]
        qtbot.waitUntil(lambda: not tab.notice.text(), timeout=5000)
        assert tab.player.activeAudioTrack() == 0
        tab.stop()
        stopped = service.agent.media.session(tab.session_id, tab.token)["state"]["track_state"]
        assert not stopped["ready"]
        assert stopped["source_token"] == ""

    finally:
        tab.stop()


def test_media_grid_scroll_appends_and_filter_resets(qtbot, tmp_path):
    import threading

    from tests.test_media_api import media_app
    from torrentlinker.gui.media import MediaTab

    app, root = media_app(tmp_path)
    for i in range(205):
        (root / f"Film {i}.2020.mkv").write_bytes(b"\0" * 64)
    service = app.state.assistant
    service.agent.media.scan("default", threading.Event(), lambda _: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(1100, 850)
    tab.show()
    tab.activate()
    video_wait(qtbot, tab, "!!document.querySelector('.media-home-row')")
    video_js(qtbot, tab, "document.querySelector('.media-home-row-header .quiet').click()")
    video_wait(qtbot, tab, "document.querySelectorAll('#media-results .media-card').length===100")
    selected = tab.selected_ids()
    qtbot.wait(600)  # let the approved See all scroll animation finish
    video_js(qtbot, tab, "window.scrollTo(0,document.body.scrollHeight)")
    video_wait(qtbot, tab, "document.querySelectorAll('#media-results .media-card').length>=200")
    assert tab.selected_ids() == selected
    video_js(qtbot, tab, "window.scrollTo(0,document.body.scrollHeight)")
    video_wait(qtbot, tab, "document.querySelectorAll('#media-results .media-card').length===205")
    scroll = video_js(qtbot, tab, "window.scrollY")
    tab.refresh()
    video_wait(qtbot, tab, "document.querySelectorAll('#media-results .media-card').length===205")
    qtbot.wait(400)
    assert (
        video_js(qtbot, tab, "document.querySelectorAll('#media-results .media-card').length")
        == 205
    )
    assert video_js(qtbot, tab, "window.scrollY") >= scroll - 2
    video_js(
        qtbot,
        tab,
        "document.querySelector('#media-search').value='Film 204';"
        "document.querySelector('#media-search').dispatchEvent(new Event('input'))",
    )
    video_wait(qtbot, tab, "document.querySelectorAll('#media-results .media-card').length===1")
    assert "Film 204" in video_js(qtbot, tab, "document.querySelector('#media-results').innerText")
    tab.stop()


def test_player_time_shows_hours_for_long_films():
    from torrentlinker.gui.media import MediaTab

    assert MediaTab._time_label(56) == "0:56"
    assert MediaTab._time_label(8034) == "2:13:54"


def test_video_home_shows_rows_and_see_all_opens_the_filtered_grid(qtbot, tmp_path):
    import json
    import threading

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.web.app import create_app

    root = tmp_path / "films"
    root.mkdir()
    genres = ["Horreur", "Horreur, Drame", "Horreur", "Comédie"]
    for number in range(len(genres)):
        (root / f"Film {number} (2020).mkv").write_bytes(b"\0" * 64)
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    media = service.agent.media
    media.scan("default", threading.Event(), lambda _p: None)
    with media.db:
        for row in media.db.execute("SELECT id, body FROM media_items").fetchall():
            body = json.loads(row["body"])
            body["genre"] = genres[int(body["title"].split()[-1])]
            media.db.execute(
                "UPDATE media_items SET body=? WHERE id=?", (json.dumps(body), row["id"])
            )
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    tab.activate()
    video_wait(qtbot, tab, "document.querySelector('[aria-label=Horreur]')!==null")
    assert "Recently added" in video_js(
        qtbot, tab, "document.querySelector('#media-home-rows').innerText"
    )
    video_js(
        qtbot, tab, "document.querySelectorAll('[aria-label=Horreur] .media-row-card')[1].click()"
    )
    qtbot.waitUntil(lambda: bool(tab.selected_ids()))
    selected = tab.selected_ids()
    video_js(qtbot, tab, "document.querySelector('[aria-label=Horreur] .quiet').click()")
    video_wait(qtbot, tab, "document.querySelectorAll('#media-results .media-card').length===3")
    assert video_js(qtbot, tab, "document.querySelector('#media-genre').value") == "Horreur"
    assert tab.selected_ids() == selected
    video_js(qtbot, tab, "document.querySelector('[data-media-view=recent]').click()")
    video_wait(qtbot, tab, "!document.querySelector('#media-home-rows').hidden")
    assert not video_js(qtbot, tab, "document.querySelector('#media-genre').value")
    tab.stop()


def test_series_card_unfolds_its_seasons_and_episodes(qtbot, tmp_path):
    import threading

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.web.app import create_app

    root = tmp_path / "videos"
    root.mkdir()
    for name in ["Show.S01E01.mkv", "Show.S01E02.mkv", "Show.S02E01.mkv", "Film.2020.mkv"]:
        (root / name).write_bytes(b"\0" * 64)
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    service.agent.media.scan("default", threading.Event(), lambda _p: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(1280, 900)
    tab.show()
    tab.activate()
    video_wait(qtbot, tab, "!!document.querySelector('#media-feature h2')")
    video_js(qtbot, tab, "document.querySelector('[data-media-view=series]').click()")
    video_wait(
        qtbot,
        tab,
        "document.querySelectorAll('.media-home-row:first-child .media-row-card').length===1",
    )
    video_js(qtbot, tab, "document.querySelector('.media-home-row .media-row-card').click()")
    video_wait(qtbot, tab, "document.querySelectorAll('#media-episodes [data-season]').length===2")
    assert (
        video_js(
            qtbot, tab, "document.querySelectorAll('#media-episodes .media-episode-card').length"
        )
        == 2
    )
    video_js(qtbot, tab, "document.querySelector('[data-season=\"2\"]').click()")
    assert (
        video_js(
            qtbot, tab, "document.querySelectorAll('#media-episodes .media-episode-card').length"
        )
        == 1
    )
    played = []
    tab.browser.hostRequested.connect(lambda action, body: played.append((action, body)))
    video_js(qtbot, tab, "document.querySelector('#media-episodes .media-episode-card').click()")
    qtbot.waitUntil(lambda: any(action == "play" for action, _ in played))
    body = next(body for action, body in played if action == "play")
    assert body["index"] == 2 and len(body["media_ids"]) == 3
    tab.dismiss_video()
    video_js(qtbot, tab, "document.querySelector('[data-media-view=films]').click()")
    video_wait(
        qtbot,
        tab,
        "document.querySelector('.media-home-row .media-row-card')?.innerText.includes('Film')",
    )
    assert "Show" not in video_js(
        qtbot, tab, "document.querySelector('#media-home-rows').innerText"
    )
    tab.stop()


def test_toolbar_refreshes_the_library_and_reopening_rescans_quietly(qtbot, tmp_path):
    import threading

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.web.app import create_app

    root = tmp_path / "videos"
    root.mkdir()
    (root / "Film.2020.mkv").write_bytes(b"\0" * 64)
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings()
    settings.library_folders = [LibraryFolder(root)]
    settings.save(config / "settings.json")
    app = create_app(
        config, password="test-password-long", roots=(root,), monitor_verifications=False
    )
    service = app.state.assistant
    media = service.agent.media
    scans = []
    real_scan = media.scan
    release = threading.Event()

    def scan(client, stop, progress):
        scans.append(client)
        release.wait(5)
        return real_scan(client, stop, progress)

    media.scan = scan
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.refresh_on_first_open = True
    tab.show()
    tab.activate()
    qtbot.waitUntil(lambda: len(scans) == 1)
    assert tab.scan_stop is not None  # a refresh is running
    assert "Scanning" not in tab.notice.text()  # quietly: the saved library is already shown
    release.set()
    qtbot.waitUntil(lambda: tab.scan_stop is None)
    video_wait(qtbot, tab, "document.querySelector('#media-feature').innerText.includes('Film')")
    reloads = []
    real_refresh = tab.refresh
    tab.refresh = lambda *a, **k: (reloads.append(1), real_refresh(*a, **k))  # type: ignore[method-assign]
    tab._set_notice("")
    tab.activate()  # opening Media again rescans quietly
    qtbot.waitUntil(lambda: len(scans) == 2)
    qtbot.waitUntil(lambda: tab.scan_stop is None)
    assert "Scanning" not in tab.notice.text()
    assert len(reloads) == 1  # only the open itself: nothing changed on disk
    (root / "Film.2021.mkv").write_bytes(b"\0" * 64)
    tab.auto_refresh.timeout.emit()  # the next automatic refresh finds the new film
    qtbot.waitUntil(lambda: len(scans) == 3)
    qtbot.waitUntil(lambda: len(reloads) == 2)
    assert tab.auto_refresh.isActive()
    # The view's ⟳ runs the same scan as a background job.
    video_js(qtbot, tab, "document.querySelector('#media-toolbar-refresh').click()")
    qtbot.waitUntil(lambda: len(scans) == 4)
    video_wait(qtbot, tab, "document.querySelector('#media-toolbar-refresh').ariaPressed==='false'")
    tab.stop()


def test_native_compatible_quality_preserves_time_pause_and_subtitles(qtbot, tmp_path, request):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    import threading

    from PySide6.QtMultimedia import QMediaPlayer

    from tests.test_media_api import media_app
    from tests.test_media_conversion import video
    from torrentlinker.gui.media import MediaTab

    app, root = media_app(tmp_path)
    video(root / "Compatible.2024.mkv", seconds=30)
    (root / "Compatible.2024.srt").write_text(
        "1\n00:00:08,000 --> 00:00:28,000\nCaption at film time\n"
    )
    service = app.state.assistant
    service.agent.media.scan("default", threading.Event(), lambda _p: None)
    tab = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(1000, 800)
    tab.show()
    tab.activate()
    video_details(qtbot, tab, "Compatible")
    video_action(qtbot, tab, "Play")
    qtbot.waitUntil(lambda: tab.player.hasVideo(), timeout=15000)
    video_wait(qtbot, tab, "watchPlayback()?.qualities?.includes('360')")
    video_js(qtbot, tab, "watchSend('toggle')")
    qtbot.waitUntil(lambda: tab.player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
    video_js(qtbot, tab, "watchSend('seek', {position: 10})")
    qtbot.waitUntil(lambda: tab.player.position() >= 10000)
    video_wait(qtbot, tab, "watchPlayback()?.tracks?.subtitles?.length === 1")
    video_js(
        qtbot,
        tab,
        "watchSend('select_track', {kind:'subtitle',"
        "track_id:watchPlayback().tracks.subtitles[0].id})",
    )
    qtbot.waitUntil(lambda: tab.caption.text() == "Caption at film time")
    video_js(qtbot, tab, "watchSend('quality', {quality:'360'})")
    video_wait(qtbot, tab, "watchPlayback()?.quality === '360' && watchPlayback().tracks.ready")
    assert tab.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    assert video_js(qtbot, tab, "watchPlayback().position") >= 10
    assert 29 < video_js(qtbot, tab, "watchPlayback().duration") < 31
    assert tab.caption.text() == "Caption at film time"
    video_js(qtbot, tab, "watchSend('toggle')")
    video_wait(qtbot, tab, "watchPlayback()?.playing && watchPlayback().position > 10.2")
    video_js(qtbot, tab, "watchSend('rate', {rate:1.5})")
    qtbot.waitUntil(lambda: tab.player.playbackRate() == 1.5)
    video_js(qtbot, tab, "watchSend('seek', {position:15})")
    video_wait(qtbot, tab, "watchPlayback()?.position >= 15 && watchPlayback().playing")
    tab.report()
    assert tab.state["position"] >= 15
    assert 29 < tab.state["duration"] < 31
    video_js(qtbot, tab, "watchSend('stop')")
    qtbot.waitUntil(lambda: tab.player.source().isEmpty())
