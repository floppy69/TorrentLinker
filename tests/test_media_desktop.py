"""Media user flows through the native player and saved library interfaces."""

from pathlib import Path

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


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
    from PySide6.QtWidgets import QListView

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
    qtbot.mouseClick(tab.kind_tabs["music"], Qt.LeftButton)
    assert tab.media_toolbar.height() <= 70
    assert (
        tab.kind_tabs["music"].mapTo(tab.media_toolbar, tab.kind_tabs["music"].rect().center()).y()
        == tab.chat.mapTo(tab.media_toolbar, tab.chat.rect().center()).y()
    )
    assert not tab.kind.isVisible()
    qtbot.mouseClick(tab.search_toggle, Qt.LeftButton)
    assert tab.search.isVisible()
    qtbot.mouseClick(tab.search_toggle, Qt.LeftButton)
    assert not tab.search.isVisible()
    tab.library_action.trigger()
    assert tab.category_cards["albums"].isVisible()
    tab.library_action.trigger()
    assert not tab.library_panel.isVisible()
    assert all(button.isVisible() for button in tab.music_tabs.values())
    qtbot.mouseClick(tab.music_tabs["tracks"], Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.results.count() == 3)
    qtbot.waitUntil(lambda: tab.results.count() > 0 and tab.results.isEnabled())
    assert tab.results.viewMode() == QListView.ViewMode.ListMode
    assert "Fixture Artist" in tab.results.item(0).text()
    assert "Fixture Album" in tab.results.item(0).text()
    assert "0:12" in tab.results.item(0).text()
    assert tab.music_playlists.isVisible()
    for view in ("albums", "artists"):
        tab.view.setCurrentIndex(tab.view.findData(view))
        qtbot.waitUntil(
            lambda: (
                tab.results.isEnabled() and tab.results.viewMode() == QListView.ViewMode.IconMode
            )
        )
        assert not tab.results.item(0).icon().isNull()
        assert tab.results.iconSize().width() >= 128
        assert tab.results.iconSize().width() == tab.results.iconSize().height()
    tab.view.setCurrentIndex(tab.view.findData("tracks"))
    qtbot.waitUntil(
        lambda: tab.results.isEnabled() and tab.results.viewMode() == QListView.ViewMode.ListMode
    )
    tab.results.item(0).setSelected(True)
    qtbot.mouseClick(tab.play_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.player.duration() == 12000, timeout=15000)
    qtbot.waitUntil(lambda: tab.player.position() > 0, timeout=10000)
    tab.command("seek", position=5)
    qtbot.waitUntil(lambda: tab.player.position() >= 5000)
    tab.results.clearSelection()
    tab.results.item(1).setSelected(True)
    tab.results.item(2).setSelected(True)
    qtbot.mouseClick(tab.enqueue_button, Qt.LeftButton)
    assert tab.queue.count() == 3
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", lambda *_args: ("Evening", True))
    qtbot.wait(20)  # Let the newly opened queue panel finish its layout and paint.
    assert tab.queue_panel.isVisible()
    assert tab.save_playlist.visibleRegion().contains(tab.save_playlist.rect().center()), (
        tab.size(),
        tab.save_playlist.geometry(),
        tab.queue_panel.geometry(),
    )
    qtbot.mouseClick(tab.save_playlist, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.playlists.currentText() == "Evening")
    assert len(service.agent.media.playlists("default")[0]["media_ids"]) == 3
    source = tab.player.source()
    selected = tab.selected_ids()
    for layout in ("focus", "collection", "cinematic"):
        tab.layout_combo.setCurrentIndex(tab.layout_combo.findData(layout))
        assert tab.media_layout == layout
        assert tab.player.source() == source
        assert tab.selected_ids() == selected
        assert tab.hero.isHidden()
        assert tab.results.isVisible()
    tab.set_media_layout("collection")
    tab.set_media_layout("cinematic")
    assert tab.selected_ids() == selected
    tab.search.setText("no such track")
    tab.kind.setCurrentIndex(tab.kind.findData("video"))
    qtbot.waitUntil(lambda: tab.results.count() == 0)
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
    assert tab.assistant.folder_column.isHidden()
    assert tab.assistant.pages.tabBar().isHidden()
    assert not tab.assistant.move_chat.isVisible() and not tab.assistant.send.isHidden()
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
    tab.assistant.conversationRequested.emit("")
    assert tab.conversation_id != first_conversation
    assert tab.assistant.conversation_id == tab.conversation_id
    tab.assistant.conversationRequested.emit(first_conversation)
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
    tab.pending_seek = None
    tab.command("shuffle", shuffle=True)
    tab.command("repeat", repeat="all")
    tab.command("play", media_ids=tab.state["queue"], index=1)
    qtbot.waitUntil(lambda: tab.player.duration() == 12000)
    playing = tab.player.source()
    tab.queue.setCurrentRow(0)
    tab.remove_from_queue()
    assert tab.player.source() == playing
    assert tab.state["index"] == 0
    assert tab.queue.count() == 2
    tab.stop()
    restored = MediaTab(lambda: service, lambda: "default", lambda: None)
    qtbot.addWidget(restored)
    restored.activate()
    assert restored.session_id == tab.session_id
    assert restored.state["queue"] == tab.state["queue"]
    assert restored.shuffle.isChecked()
    assert restored.repeat.currentData() == "all"
    assert restored.conversation_id == first_conversation
    qtbot.waitUntil(lambda: restored.player.duration() == 12000)
    assert restored.player.source() == playing
    assert restored.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    restored.report()
    current = restored.state["current_id"]
    restored.forget_progress(current)
    assert restored.state["queue"] == []
    assert service.agent.media.detail("default", current)["position"] == 0
    restored.stop()


def test_native_video_plays_with_local_subtitles(qtbot, tmp_path):
    import shutil
    import subprocess
    import threading

    import pytest
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QListView

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
    tab.show()
    tab.activate()
    qtbot.waitUntil(lambda: tab.results.count() > 0 and tab.results.isEnabled())
    assert tab.results.viewMode() == QListView.ViewMode.IconMode
    assert tab.results.gridSize().width() >= 180
    assert tab.results.iconSize().height() >= 170
    assert not tab.results.item(0).icon().isNull()
    tab.set_media_layout("focus")
    assert tab.hero.strip.count() == 4
    fourth = tab.hero.strip.item(3)
    fourth_id = fourth.data(Qt.ItemDataRole.UserRole)
    tab.hero.strip.clearSelection()
    fourth.setSelected(True)
    assert tab.selected_ids() == [fourth_id]
    tab.set_media_layout("cinematic")
    tab.results.clearSelection()
    other = next(index for index, row in enumerate(tab.rows) if row["release"] == "Other 0.mp4")
    tab.results.item(other).setSelected(True)
    qtbot.mouseClick(tab.info_button, Qt.LeftButton)
    assert "No known external subtitles." in tab.description.text()
    tab.details.close()
    tab.results.clearSelection()
    clip = next(index for index, row in enumerate(tab.rows) if row["release"] == "Clip.mp4")
    tab.results.item(clip).setSelected(True)
    qtbot.mouseClick(tab.info_button, Qt.LeftButton)
    assert tab.details.isVisible()
    assert "External subtitles: Clip" in tab.description.text()
    assert "Embedded subtitle tracks are discovered during playback." in tab.description.text()
    assert "Filename metadata" in tab.hero.metadata.text()
    tab.details.close()
    qtbot.mouseClick(tab.play_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.player.hasVideo(), timeout=15000)
    qtbot.waitUntil(lambda: tab.subtitles.count() == 2)
    tab.subtitles.setCurrentIndex(1)
    tab.command("seek", position=2)
    qtbot.waitUntil(lambda: tab.caption.text() == "A local caption")
    qtbot.waitUntil(lambda: tab.player.videoSink().videoFrame().isValid(), timeout=10000)
    assert tab.video_controls.isVisible()
    assert tab.video.rect().contains(
        tab.video_controls.mapTo(tab.video, tab.video_controls.rect().center())
    )
    rendered = tab.video.grab().toImage()
    sample = rendered.pixelColor(rendered.width() // 2, rendered.height() // 3)
    assert sample.blue() > 150 and sample.red() < 80
    from PySide6.QtCore import QCoreApplication, QPoint
    from PySide6.QtGui import QContextMenuEvent

    tab.video.setFocus()
    tab.controls_timer.setInterval(120)
    qtbot.mouseMove(tab.video.viewport(), QPoint(20, 20))
    qtbot.waitUntil(lambda: tab.video_controls.isHidden(), timeout=2000)
    assert tab.player_back.isHidden()
    qtbot.mouseMove(tab.video.viewport(), QPoint(35, 20))
    qtbot.waitUntil(lambda: tab.video_controls.isVisible())
    assert tab.player_back.isVisible()
    qtbot.keyClick(tab.video, Qt.Key_Space)
    assert tab.video_controls.isVisible()
    local = QPoint(60, 60)
    context = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, local, tab.video.viewport().mapToGlobal(local)
    )
    QCoreApplication.sendEvent(tab.video.viewport(), context)
    assert tab.player_menu.isVisible()
    tab.player.play()
    qtbot.wait(180)
    assert tab.video_controls.isVisible()
    tab.player.pause()
    qtbot.keyClick(tab.player_menu, Qt.Key_Escape)
    qtbot.waitUntil(lambda: not tab.player_menu.isVisible())
    assert tab.player.playbackState() != tab.player.PlaybackState.PlayingState
    source, position = tab.player.source(), tab.player.position()
    original_parent = tab.player_panel.parentWidget()
    qtbot.mouseClick(tab.fullscreen_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.player_panel.window().isFullScreen())
    assert tab.caption.isVisible()
    assert tab.subtitles.currentIndex() == 1
    assert tab.video.mapTo(tab.fullscreen_dialog, tab.video.rect().topLeft()).isNull()
    assert tab.video.size() == tab.fullscreen_dialog.size()
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
    qtbot.keyClick(tab.fullscreen_button, Qt.Key_Escape)
    qtbot.waitUntil(lambda: tab.player_panel.parentWidget() is original_parent)
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
    qtbot.mouseClick(tab.fullscreen_button, Qt.LeftButton)
    qtbot.mouseClick(tab.fullscreen_button, Qt.LeftButton)
    assert tab.player_panel.parentWidget() is original_parent
    qtbot.mouseClick(tab.fullscreen_button, Qt.LeftButton)
    qtbot.mouseClick(tab.player_back, Qt.LeftButton)
    assert not tab.fullscreen_dialog.isVisible()
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
    tab.view.setCurrentIndex(tab.view.findData("films"))
    assert not tab.video.isVisible()
    assert not tab.player_panel.isVisible()
    tab.command("play", media_ids=saved_queue, index=0)
    qtbot.waitUntil(lambda: tab.video.isVisible())
    tab.kind.setCurrentIndex(tab.kind.findData("music"))
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
    from PySide6.QtCore import QCoreApplication, Qt, QThreadPool

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
    tab.show()
    tab.activate()
    qtbot.waitUntil(lambda: tab.results.count() > 0 and tab.results.isEnabled())
    tab.results.item(0).setSelected(True)
    assert tab.preview_button.isVisible()
    qtbot.mouseClick(tab.preview_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: tab.preview_device is not None, timeout=10000)
    qtbot.waitUntil(lambda: tab.player.videoSink().videoFrame().isValid(), timeout=15000)
    assert tab.player.sourceDevice().size() == total  # the whole file, read as it downloads
    assert tab.player.source().toString() == "verified-preview.mp4"
    assert tab.refresh_preview.isVisible()
    tab.command("seek", position=1)
    qtbot.waitUntil(lambda: tab.player.position() >= 1000)
    completed = root / "Complete.mp4"
    shutil.copy(source, completed)
    service.agent.media.scan("default", threading.Event(), lambda _progress: None)
    tab.refresh()
    qtbot.waitUntil(lambda: tab.results.count() == 2 and tab.results.isEnabled())

    def select_release(name):
        tab.results.clearSelection()
        index = next(i for i, row in enumerate(tab.rows) if row["release"] == name)
        tab.results.item(index).setSelected(True)

    def delayed_preview():
        client.entered.clear()
        client.release.clear()
        client.delay = True
        select_release(source.name)
        qtbot.mouseClick(tab.preview_button, Qt.LeftButton)
        qtbot.waitUntil(client.entered.is_set)

    delayed_preview()
    select_release(completed.name)
    qtbot.mouseClick(tab.play_button, Qt.LeftButton)
    expected = tab.player.source()
    assert expected.toLocalFile() == str(completed)
    client.release.set()
    qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
    QCoreApplication.processEvents()
    assert tab.player.source() == expected
    assert tab.preview_id == ""
    assert tab.preview_device is None
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


def test_media_profile_editor_keeps_the_player_and_media_workspace(qtbot, tmp_path, request):
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from shiboken6 import isValid

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
    window.navigation.setCurrentRow(window.tabs.indexOf(window.media_tab))
    tab = window.media_tab
    qtbot.waitUntil(lambda: tab.results.isEnabled())
    tab.command("shuffle", shuffle=True)
    tab.command("repeat", repeat="all")
    player = tab.player
    window.set_media_center(True)
    qtbot.waitUntil(window.isFullScreen)
    assert window.media_center_active

    def save_editor():
        dialog = QApplication.activeModalWidget()
        buttons = dialog.findChild(QDialogButtonBox)
        qtbot.mouseClick(buttons.button(QDialogButtonBox.Save), Qt.LeftButton)

    QTimer.singleShot(0, save_editor)
    window.open_client_profiles()
    replacement = QApplication.instance().torrentlinker_window
    windows.append(replacement)
    assert replacement.tabs.currentWidget() is tab
    assert not replacement.isFullScreen()
    assert not replacement.media_center_active
    assert not tab.center_button.isChecked()
    assert replacement.media_tab.player is player
    assert tab.heartbeat.isActive()
    assert tab.shuffle.isChecked()
    assert tab.repeat.currentData() == "all"
    cleanup()


def test_native_media_layout_shortcut_emits_only_user_changes(qtbot):
    from torrentlinker.gui.media import MediaTab

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    assert tab.media_layout == "cinematic"
    assert tab.layout_combo.objectName() == "media-layout"
    changes = []
    tab.layout_changed.connect(changes.append)
    tab.set_media_layout("collection")
    assert changes == []
    assert tab.hero.isHidden()
    tab.layout_combo.setCurrentIndex(tab.layout_combo.findData("focus"))
    assert changes == ["focus"]
    assert tab.hero.isHidden()


def test_player_menu_opens_and_closes_the_queue_and_playlists(qtbot):
    from torrentlinker.gui.media import MediaTab

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.queue_action.trigger()
    assert tab.queue_disclosure.isChecked()
    tab.queue_action.trigger()
    assert not tab.queue_disclosure.isChecked()


def test_native_multitrack_switching_decodes_audio_and_subtitles_and_keeps_choices(qtbot, tmp_path):
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
    qtbot.waitUntil(lambda: tab.results.count() == 2 and tab.results.isEnabled())

    def deliver(action, **values):
        sequence = tab.command_ack + 1
        tab.apply_player_commands([{"sequence": sequence, "action": action, **values}])
        return sequence

    media_id = tab.selected_ids()[0]
    deliver("play", media_ids=[media_id], index=0, start_paused=True, load_token="prepared-fixture")
    qtbot.waitUntil(lambda: tab.audio_tracks.count() == 2 and tab.subtitles.count() == 3)
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
    assert len(tab.audio_tracks.itemText(1)) > 400
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
    assert "French" in tab.audio_tracks.itemText(0)
    assert "Low tone" in tab.audio_tracks.itemText(0)
    assert "English" in tab.audio_tracks.itemText(1)
    assert "French" in tab.subtitles.itemText(1)
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
    assert tab.video.rect().contains(tab.caption.mapTo(tab.video, tab.caption.rect().center()))
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
    assert tab.audio_tracks.currentData() == 1
    assert tab.subtitles.currentData() == 1
    assert tab.player.activeAudioTrack() == 1
    assert tab.player.activeSubtitleTrack() == 1
    tab.toggle_fullscreen()
    tab.player_menu.popup(tab.video.mapToGlobal(tab.video.rect().center()))
    qtbot.waitUntil(lambda: tab.player_menu.isVisible())
    french_action = next(
        action for action in tab.audio_menu.actions() if action.data() == "audio:0"
    )
    french_action.trigger()
    tab.player_menu.close()
    qtbot.waitUntil(lambda: tab.player.activeAudioTrack() == 0)
    tab.subtitles.setCurrentIndex(1)
    frequencies.clear()
    qtbot.waitUntil(lambda: any(400 < value < 480 for value in frequencies), timeout=10000)
    qtbot.waitUntil(
        lambda: any("French fixture caption" in text for text in captions), timeout=10000
    )
    qtbot.waitUntil(lambda: tab.player.videoSink().videoFrame().isValid())
    tab.audio_tracks.setCurrentIndex(1)
    assert tab.player.activeAudioTrack() == 1
    current = tab.state["current_id"]
    other = next(row["id"] for row in tab.rows if row["id"] != current)
    deliver("play", media_ids=[other], index=0)
    tab.report()
    replacement = service.agent.media.session(tab.session_id, tab.token)["state"]["track_state"]
    assert replacement["source_token"] != "prepared-fixture"
    stale_track = tab.player.activeAudioTrack()
    french_action.trigger()
    assert tab.player.activeAudioTrack() == stale_track
    deliver("pause")
    stale_resume = deliver("play", media_id=media_id, source_token="prepared-fixture")
    assert tab.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    tab.report()
    failure = service.agent.media.session(tab.session_id, tab.token)["state"]["track_result"]
    assert failure["sequence"] == stale_resume
    assert not failure["applied"]
    qtbot.waitUntil(lambda: tab.player.duration() == 10000 and tab.audio_tracks.count() == 2)
    assert tab.audio_tracks.currentData() == 0
    assert tab.player.activeAudioTrack() == 0
    assert tab.subtitles.currentData() == -1
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
    current_token = service.agent.media.session(tab.session_id, tab.token)["state"]["track_state"][
        "source_token"
    ]
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


def test_media_grid_scroll_appends_and_filter_resets(qtbot):
    from PySide6.QtCore import QSignalBlocker

    from torrentlinker.gui.media import MediaTab

    rows = [
        {"id": str(i), "title": f"Film {i}", "kind": "video", "available": True} for i in range(205)
    ]

    class Library:
        def listing(self, _client, *, offset=0, view="all", q="", **_kwargs):
            entries = [] if view == "continue" else rows[:1] if q else rows
            end = min(offset + 100, len(entries))
            return {
                "rows": entries[offset:end],
                "total": len(entries),
                "next_offset": end if end < len(entries) else None,
            }

        def playlists(self, _client):
            return []

        def detail(self, _client, identifier):
            return rows[int(identifier)]

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.library = Library()
    tab.resize(1100, 850)
    tab.show()
    # The continuous grid is what a row's See all opens.
    tab.grid_mode = True
    with QSignalBlocker(tab.view):
        tab.view.setCurrentIndex(tab.view.findData("films"))
    tab.refresh()
    qtbot.waitUntil(lambda: tab.results.isEnabled() and tab.results.count() == 100)
    qtbot.waitUntil(lambda: tab.results.height() > 850)
    assert not tab.results.verticalScrollBar().isVisible()
    selected = tab.selected_ids()
    scroll = tab.content_scroll.verticalScrollBar()
    scroll.setValue(scroll.maximum())
    qtbot.waitUntil(lambda: tab.results.isEnabled() and tab.results.count() == 200)
    assert tab.selected_ids() == selected
    # The description sits outside the scroll area, so card scrolling never moves it.
    assert not tab.content_scroll.isAncestorOf(tab.hero)
    assert tab.hero.isVisible()
    assert tab.hero.height() <= tab.media_column.height() // 2 or tab.hero.height() <= 440
    qtbot.waitUntil(lambda: scroll.value() < scroll.maximum())
    scroll.setValue(scroll.maximum())
    qtbot.waitUntil(lambda: tab.results.isEnabled() and tab.results.count() == 205)
    assert len({row["id"] for row in tab.rows}) == 205
    assert tab.next_offset is None
    tab.search.setText("Film 0")
    tab.refresh()
    qtbot.waitUntil(lambda: tab.results.isEnabled() and tab.results.count() == 1)
    assert tab.rows == rows[:1]
    assert tab.next_offset is None


def test_player_time_shows_hours_for_long_films():
    from torrentlinker.gui.media import MediaTab

    assert MediaTab._time_label(56) == "0:56"
    assert MediaTab._time_label(8034) == "2:13:54"


def test_video_home_shows_rows_and_see_all_opens_the_filtered_grid(qtbot, tmp_path):
    import json
    import threading

    from PySide6.QtCore import Qt

    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.media import MediaTab
    from torrentlinker.gui.media_rows import MediaRow
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
    qtbot.waitUntil(
        lambda: len(tab.findChildren(MediaRow)) >= 2 and tab.home_rows_panel.isVisible()
    )
    rows = {row.title.text(): row for row in tab.home_row_widgets}
    assert {"Recently added", "Horreur"} <= set(rows)
    assert not tab.results.isVisible()
    # Choosing a card in a row makes it the selection the description and Play act on.
    horror = rows["Horreur"]
    card = horror.cards.item(1)
    horror.cards.itemClicked.emit(card)
    chosen = card.data(Qt.ItemDataRole.UserRole)
    assert tab.selected_ids() == [chosen]
    qtbot.waitUntil(lambda: tab.featured_id == chosen)
    # See all opens the continuous grid with the row's filter; Home brings the rows back.
    horror.seeAll.emit()
    qtbot.waitUntil(lambda: tab.results.isVisible() and tab.results.count() == 3)
    assert tab.filters["genre"].currentData() == "Horreur"
    tab.video_tabs["all"].click()
    qtbot.waitUntil(lambda: tab.home_rows_panel.isVisible())
    assert not tab.filters["genre"].currentData()
    tab.stop()


def test_hero_shows_the_poster_beside_the_description(qtbot):
    from PySide6.QtGui import QImage

    from torrentlinker.gui.media import MediaHero

    hero = MediaHero()
    qtbot.addWidget(hero)
    hero.resize(1200, 440)
    hero.show()
    assert hero.poster.isHidden()  # no artwork yet
    picture = QImage(400, 600, QImage.Format.Format_RGB32)
    picture.fill(0x336699)
    hero.set_picture(picture)
    assert hero.poster.isVisible()
    assert hero.poster.width() * 3 == hero.poster.height() * 2
    qtbot.waitUntil(lambda: hero.poster.geometry().right() < hero.copy.geometry().left())
    hero.resize(640, 440)  # a narrow window keeps the room for the text
    qtbot.waitUntil(lambda: hero.poster.isHidden())


def test_series_card_unfolds_its_seasons_and_episodes(qtbot, tmp_path):
    import threading

    from PySide6.QtCore import Qt

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
    tab.video_tabs["series"].click()
    qtbot.waitUntil(lambda: tab.home_rows_panel.isVisible() and bool(tab.home_row_widgets))
    cards = tab.home_row_widgets[0].cards
    assert cards.count() == 1 and cards.item(0).text().startswith("Show\n3 episodes")
    tab.home_row_widgets[0].cards.itemClicked.emit(cards.item(0))
    qtbot.waitUntil(lambda: tab.series_panel.isVisible())
    panel = tab.series_panel
    assert sorted(panel.season_buttons) == [1, 2]
    assert panel.cards.count() == 2  # a row of episode cards, not a long list
    assert panel.cards.height() < 220
    assert panel.cards.item(0).text().startswith("Episode 1")
    panel.season_buttons[2].click()
    assert panel.cards.count() == 1
    played = []
    tab.command = lambda action, **values: played.append((action, values))
    panel.cards.itemActivated.emit(panel.cards.item(0))
    ids = [episode["id"] for episode in panel.episodes]
    assert played == [("play", {"media_ids": ids, "index": 2})]
    # Films keep their own rows and never list the series.
    tab.video_tabs["films"].click()
    qtbot.waitUntil(
        lambda: (
            bool(tab.home_row_widgets)
            and tab.home_row_widgets[0].cards.item(0).text().startswith("Film")
        )
    )
    shown = tab.home_row_widgets[0].cards
    assert not {shown.item(i).data(Qt.ItemDataRole.UserRole) for i in range(shown.count())} & set(
        ids
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
    assert tab.refresh_icon.isChecked()  # a refresh is running
    assert tab.refresh_icon.toolTip() == "Cancel library refresh"
    release.set()
    qtbot.waitUntil(lambda: not tab.refresh_icon.isChecked())
    qtbot.waitUntil(lambda: tab.results.count() == 1 or bool(tab.home_row_widgets))
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
    tab.refresh_icon.click()
    qtbot.waitUntil(lambda: len(scans) == 4)
    qtbot.waitUntil(lambda: not tab.refresh_icon.isChecked())
    assert tab.refresh_icon.toolTip() == "Refresh library"
    tab.stop()
