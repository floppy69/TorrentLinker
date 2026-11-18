"""Native media browsing and playback, backed by the shared saved inventory."""

from __future__ import annotations

import random
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from functools import partial
from typing import Any
from uuid import uuid4

from PySide6.QtCore import (
    QEvent,
    QFile,
    QIODevice,
    QLocale,
    QObject,
    QRect,
    QRectF,
    QSettings,
    QSignalBlocker,
    QSize,
    QSizeF,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QActionGroup,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QTextDocumentFragment,
)
from PySide6.QtMultimedia import (
    QMediaMetaData,
    QMediaPlayer,
    QVideoFrame,
    QVideoFrameFormat,
    QVideoSink,
)
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGraphicsDropShadowEffect,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.gui.controls import icon_button, set_role
from torrentlinker.gui.media_audio import create_audio_output
from torrentlinker.gui.media_rows import MediaRow, SeriesEpisodes
from torrentlinker.gui.tasks import run_in_background

# The Media Center chat panel and the media beside it never shrink below these.
CHAT_MIN_WIDTH = 320
MEDIA_MIN_WIDTH = 560
PREVIEW_WAIT_SECONDS = 300.0  # how long playback waits for the next downloaded pieces
PREVIEW_WAIT_AHEAD = 64 * 1024 * 1024  # how far past the downloaded part a read waits
AUTO_REFRESH_MS = 60_000  # Media rescans the Library Folders this often while open


class DownloadingFileDevice(QIODevice):
    """A read-only, seekable view of a file qBittorrent is downloading, like qBittorrent's own
    preview: the player sees the whole file, but only verified pieces are ever read.

    A read just past the downloaded part waits for the next pieces; a read far ahead (an
    index at the end of the file) finds nothing until its pieces arrive. Qt reads off the GUI
    thread, so waiting never freezes the window; abort() ends a wait before the player stops.
    """

    def __init__(self, path, size: int, piece_size: int, pieces, parent=None) -> None:
        super().__init__(parent)
        self.file = QFile(str(path))
        self.total, self.piece_size = int(size), int(piece_size)
        self.pieces = list(pieces)
        self.changed = threading.Condition()
        self.aborted = False
        self.stalled = False  # no new pieces within PREVIEW_WAIT_SECONDS: the preview ends
        if not self.file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise ValueError("The preview file cannot be opened read-only.")
        if self.total <= 0 or self.piece_size <= 0 or not self.available(0):
            self.file.close()
            raise ValueError("The start of this file is not downloaded yet.")
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)

    def update(self, pieces) -> None:
        """qBittorrent verified more pieces: wake a read waiting for them."""
        with self.changed:
            self.pieces = list(pieces)
            self.changed.notify_all()

    def abort(self) -> None:
        with self.changed:
            self.aborted = True
            self.changed.notify_all()

    def available(self, position: int) -> int:
        """Verified bytes from `position` on, up to the next missing piece."""
        piece = position // self.piece_size
        last = piece
        while last < len(self.pieces) and self.pieces[last]:
            last += 1
        return max(0, min(self.total, last * self.piece_size) - position)

    def downloaded(self) -> int:
        """The verified bytes from the start of the file."""
        return self.available(0)

    def isSequential(self) -> bool:
        return False

    def size(self) -> int:
        return self.total

    def seek(self, position: int) -> bool:
        if position < 0 or position > self.total:
            return False
        return super().seek(position)

    def bytesAvailable(self) -> int:
        return self.available(self.pos())

    def gives_up(self, position: int) -> bool:
        """Whether a read here ends instead of waiting for pieces."""
        return (
            self.aborted
            or self.stalled
            or position >= self.total
            or not self.available(position)
            and position > self.downloaded() + PREVIEW_WAIT_AHEAD
        )

    def atEnd(self) -> bool:
        # Qt's FFmpeg reader ends only when atEnd() says so: an empty read alone makes
        # it read again, forever.
        return self.gives_up(self.pos())

    def readData(self, maximum: int) -> bytes:
        position = self.pos()
        deadline = time.monotonic() + PREVIEW_WAIT_SECONDS
        with self.changed:
            while not (count := self.available(position)):
                if self.gives_up(position):
                    return b""
                if time.monotonic() >= deadline:
                    self.stalled = True
                    return b""
                self.changed.wait(0.5)
        if not self.file.seek(position):
            return b""
        return bytes(self.file.read(min(max(0, maximum), count)).data())

    def writeData(self, _data: bytes | bytearray | memoryview, _length: int) -> int:
        return -1

    def close(self) -> None:
        self.abort()
        super().close()
        self.file.close()


class MediaTileButton(QPushButton):
    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize() if self.layout() else super().minimumSizeHint()


class MediaHero(QWidget):
    """Artwork stays behind a readable, native title and action composition."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.picture = QImage()
        self.mode = "cinematic"
        self.height_cap = 10_000
        self.setObjectName("mediaHero")
        self.setMinimumHeight(440)
        self.box = QHBoxLayout(self)
        self.box.setContentsMargins(34, 34, 34, 34)
        self.box.setSpacing(28)
        # The poster sits left of the title and description, over the same artwork backdrop.
        self.poster = QLabel()
        self.poster.setObjectName("mediaHeroPoster")
        self.poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster.hide()
        self.box.addWidget(self.poster, 0, Qt.AlignmentFlag.AlignVCenter)
        self.copy = QWidget()
        self.copy.setMaximumWidth(620)
        text = QVBoxLayout(self.copy)
        text.setContentsMargins(0, 0, 0, 0)
        text.addStretch()
        self.kicker = QLabel(self.tr("FROM YOUR LIBRARY FOLDERS"))
        self.kicker.setStyleSheet("color: #85d8cb; font-size: 10px; letter-spacing: 2px;")
        text.addWidget(self.kicker)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 48px; font-weight: 750; color: #f3f4ef;")
        text.addWidget(self.title)
        self.metadata = QLabel()
        self.metadata.setTextFormat(Qt.TextFormat.PlainText)
        self.metadata.setWordWrap(True)
        self.metadata.setStyleSheet("color: #c7d0d2; font-size: 12px;")
        text.addWidget(self.metadata)
        self.synopsis = QLabel()
        self.synopsis.setTextFormat(Qt.TextFormat.PlainText)
        self.synopsis.setWordWrap(True)
        self.synopsis.setStyleSheet("color: #c7d0d2; font-size: 13px; line-height: 1.7;")
        text.addSpacing(12)
        text.addWidget(self.synopsis)
        self.action_layout = QHBoxLayout()
        self.action_layout.setSpacing(10)
        text.addSpacing(16)
        text.addLayout(self.action_layout)
        text.addStretch()
        self.box.addWidget(self.copy, 3, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.strip = QListWidget()
        self.strip.setObjectName("mediaFocusStrip")
        self.strip.setViewMode(QListView.ViewMode.IconMode)
        self.strip.setFlow(QListView.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setMovement(QListView.Movement.Static)
        self.strip.setResizeMode(QListView.ResizeMode.Adjust)
        self.strip.setWordWrap(True)
        self.strip.setGridSize(QSize(130, 196))
        self.strip.setIconSize(QSize(112, 148))
        self.strip.setFixedHeight(208)
        self.strip.setMinimumWidth(200)
        self.strip.setMaximumWidth(430)
        self.box.addWidget(self.strip, 2, Qt.AlignmentFlag.AlignBottom)
        self.strip.hide()

    def set_picture(self, picture):
        self.picture = picture
        self._show_poster()
        self.update()

    def _show_poster(self):
        narrow_focus = self.mode == "focus" and self.width() < 900
        visible = not self.picture.isNull() and self.width() >= 700 and not narrow_focus
        self.poster.setVisible(visible)
        if not visible:
            return
        height = max(150, min(300, self.height() - 68))
        size = QSize(height * 2 // 3, height)
        scaled = self.picture.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        rounded = QPixmap(scaled.size())
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rounded.rect()), 8, 8)
        painter.setClipPath(path)
        painter.drawImage(0, 0, scaled)
        painter.end()
        self.poster.setFixedSize(scaled.size())
        self.poster.setPixmap(rounded)

    def set_mode(self, mode):
        self.mode = mode
        self.strip.setVisible(mode == "focus")
        self._arrange()

    def _arrange(self):
        narrow_focus = self.mode == "focus" and self.width() < 900
        self.box.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow_focus else QBoxLayout.Direction.LeftToRight
        )
        wanted = 630 if narrow_focus else 490 if self.mode == "focus" else 440
        self.setMinimumHeight(min(wanted, self.height_cap))
        self.setMaximumHeight(max(wanted, self.height_cap))
        self.title.setStyleSheet(
            "font-size: "
            + ("36" if self.width() < 700 else "48")
            + "px; font-weight: 750; color: #f3f4ef;"
        )
        self._show_poster()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#12212a"))
        if not self.picture.isNull():
            scale = max(self.width() / self.picture.width(), self.height() / self.picture.height())
            width, height = self.width() / scale, self.height() / scale
            source = QRectF(
                (self.picture.width() - width) / 2,
                (self.picture.height() - height) / 2,
                width,
                height,
            )
            painter.drawImage(QRectF(self.rect()), self.picture, source)
        horizontal = QLinearGradient(0, 0, self.width(), 0)
        horizontal.setColorAt(0, QColor(12, 18, 22, 245))
        horizontal.setColorAt(0.55, QColor(12, 18, 22, 172))
        horizontal.setColorAt(1, QColor(12, 18, 22, 28))
        painter.fillRect(self.rect(), horizontal)
        vertical = QLinearGradient(0, 0, 0, self.height())
        vertical.setColorAt(0, QColor(16, 19, 21, 40))
        vertical.setColorAt(0.65, QColor(16, 19, 21, 0))
        vertical.setColorAt(1, QColor("#101315"))
        painter.fillRect(self.rect(), vertical)
        painter.end()


# Frame layouts DisplayFrames can halve: bytes per sample, and whether chroma is interleaved.
HALVABLE = {
    QVideoFrameFormat.PixelFormat.Format_P010: (2, True),
    QVideoFrameFormat.PixelFormat.Format_P016: (2, True),
    QVideoFrameFormat.PixelFormat.Format_NV12: (1, True),
    QVideoFrameFormat.PixelFormat.Format_NV21: (1, True),
    QVideoFrameFormat.PixelFormat.Format_YUV420P: (1, False),
    QVideoFrameFormat.PixelFormat.Format_YUV420P10: (2, False),
    QVideoFrameFormat.PixelFormat.Format_YV12: (1, False),
}


class DisplayFrames(QObject):
    """Prepares decoded frames for the picture, on the frame thread.

    The picture converts every frame on the GUI thread; a 4K frame took about 50 ms there,
    longer than a 24 fps frame lasts, so playback stuttered. While a frame is at least twice
    the picture's size it is halved first, a quarter of the work.

    Qt also draws HDR10 with two faults. It reads the mastering peak brightness 10,000 times
    too high, so highlights clip; and converting BT.2020's most saturated reds overflows into
    black blotches. HDR10 frames get the real peak and the BT.601 matrix, whose conversion
    stays in range at the cost of a slight hue shift.

    Frames reach convert() queued: Qt's video thread only posts them, so it never waits for
    the interpreter lock, which the GUI thread may hold while stopping it.
    """

    ready = Signal(QVideoFrame)

    def __init__(self) -> None:
        super().__init__()
        self.size = QSize()  # the picture, in device pixels; set from the GUI thread

    def convert(self, frame: QVideoFrame) -> None:
        self.ready.emit(self.prepared(frame, self.size))

    @staticmethod
    def prepared(frame: QVideoFrame, size: QSize = QSize()) -> QVideoFrame:
        source = frame.surfaceFormat()
        hdr = source.colorTransfer() == QVideoFrameFormat.ColorTransfer.ColorTransfer_ST2084
        layout = HALVABLE.get(source.pixelFormat())
        step = 1
        while (
            layout
            and size.width() > 0
            and frame.width() // (step * 2) >= size.width()
            and frame.height() // (step * 2) >= size.height()
        ):
            step *= 2
        if step == 1 and not hdr:
            return frame
        target = QVideoFrameFormat(source)
        if step > 1:
            target.setFrameSize(QSize(frame.width() // step & ~1, frame.height() // step & ~1))
            target.setViewport(QRect(0, 0, target.frameWidth(), target.frameHeight()))
        if hdr:
            if target.maxLuminance() > 10_000:  # 1,000 nits read as 10,000,000
                target.setMaxLuminance(target.maxLuminance() / 10_000)
            target.setColorSpace(QVideoFrameFormat.ColorSpace.ColorSpace_BT601)
        copy = QVideoFrame(target)
        if not frame.map(QVideoFrame.MapMode.ReadOnly):
            return frame
        try:
            if not copy.map(QVideoFrame.MapMode.WriteOnly):
                return frame
            if layout:
                DisplayFrames._sample(frame, copy, step, *layout)
            else:
                DisplayFrames._copy(frame, copy)
            copy.unmap()
        finally:
            frame.unmap()
        copy.setStartTime(frame.startTime())
        copy.setEndTime(frame.endTime())
        return copy

    @staticmethod
    def _plane(video: QVideoFrame, plane: int, rows: int, dtype):
        import numpy

        line = video.bytesPerLine(plane) // numpy.dtype(dtype).itemsize
        bits = numpy.frombuffer(video.bits(plane), dtype)
        rows = min(rows, bits.size // line)
        return bits[: rows * line].reshape(rows, line)

    @staticmethod
    def _sample(frame, copy, step: int, size: int, interleaved: bool) -> None:
        """Every step-th sample of each plane; numpy releases the interpreter lock."""
        import numpy

        dtype = numpy.uint16 if size == 2 else numpy.uint8
        width, height = copy.width(), copy.height()
        planes = [(0, height, width, 1)]
        planes += (
            [(1, height // 2, width // 2, 2)]
            if interleaved
            else [(1, height // 2, width // 2, 1), (2, height // 2, width // 2, 1)]
        )
        for plane, rows, columns, channels in planes:
            source = DisplayFrames._plane(frame, plane, rows * step, dtype)[::step]
            target = DisplayFrames._plane(copy, plane, rows, dtype)
            rows = min(rows, source.shape[0], target.shape[0])
            # Rows of (sample, channel): an interleaved chroma pair moves as one sample.
            picked = source[:rows, : columns * step * channels]
            picked = picked.reshape(rows, columns * step, channels)[:, ::step]
            placed = target[:rows, : columns * channels].reshape(rows, columns, channels)
            numpy.copyto(placed, picked)

    @staticmethod
    def _copy(frame, copy) -> None:
        import numpy

        for plane in range(frame.planeCount()):
            source = numpy.frombuffer(frame.bits(plane), numpy.uint8)
            target = numpy.frombuffer(copy.bits(plane), numpy.uint8)
            source_line, target_line = frame.bytesPerLine(plane), copy.bytesPerLine(plane)
            if source_line == target_line:
                count = min(source.size, target.size)
                numpy.copyto(target[:count], source[:count])
                continue
            rows = min(source.size // source_line, target.size // target_line)
            width = min(source_line, target_line)
            numpy.copyto(
                target[: rows * target_line].reshape(rows, target_line)[:, :width],
                source[: rows * source_line].reshape(rows, source_line)[:, :width],
            )


_FRAME_THREAD: QThread | None = None


def frame_thread() -> QThread:
    """The one thread that prepares frames, for every player; it stops when Python exits."""
    global _FRAME_THREAD
    if _FRAME_THREAD is None:
        import atexit

        _FRAME_THREAD = QThread()
        _FRAME_THREAD.setObjectName("TorrentLinker frames")
        _FRAME_THREAD.start()
        atexit.register(_stop_frame_thread)
    return _FRAME_THREAD


def _stop_frame_thread() -> None:
    if _FRAME_THREAD is not None and isValid(_FRAME_THREAD):
        _FRAME_THREAD.quit()
        _FRAME_THREAD.wait(5000)


class VideoSurface(QGraphicsView):
    """Qt video rendering and ordinary widget controls share one composited surface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self.item = QGraphicsVideoItem()
        scene.addItem(self.item)
        self.frames: DisplayFrames | None = None
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QColor("black"))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.overlay = QWidget(self.viewport())
        self.overlay.setObjectName("mediaVideoOverlay")
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.overlay.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.viewport().rect()
        self.setSceneRect(QRectF(rect))
        self.item.setSize(QSizeF(rect.size()))
        self.overlay.setGeometry(rect)
        self.overlay.raise_()
        self.measure()

    def measure(self) -> None:
        """Tell the frame preparer how many device pixels the picture covers."""
        if self.frames is not None:
            ratio = self.devicePixelRatioF()
            size = self.viewport().size()
            self.frames.size = QSize(round(size.width() * ratio), round(size.height() * ratio))


class MediaTab(QWidget):
    """One native player session whose lifetime is independent of browsing and chat."""

    PICTURE_CACHE_LIMIT = 24 * 1024 * 1024

    scan_progress = Signal(object)
    # A video plays: background work that would hold the interpreter lock should wait,
    # or the frame thread misses frames.
    video_playing_changed = Signal(bool)
    layout_changed = Signal(str)
    center_mode_requested = Signal(bool)
    connections_requested = Signal()

    def __init__(
        self,
        get_service: Callable[[], Any],
        client_id: Callable[[], str],
        add_folder: Callable[[], None],
    ) -> None:
        super().__init__()
        self.get_service = get_service
        self.client_id = client_id
        self.service: Any = None
        self.library: Any = None
        self.session_id = ""
        self.token = ""
        self.session_client = ""
        self.command_ack = 0
        self.credentials: QSettings | None = None
        self.state: dict[str, Any] = {
            "current_id": "",
            "queue": [],
            "index": 0,
            "position": 0,
            "duration": 0,
            "paused": True,
            "volume": 1.0,
            "shuffle": False,
            "repeat": "off",
        }
        self.rows: list[dict[str, Any]] = []
        self.conversation_id = ""
        self.current_playlist = ""
        self.assistant: Any = None
        self.scan_stop: threading.Event | None = None
        self.scan_quiet = False  # an automatic refresh shows no progress
        self.pending_seek: int | None = None
        self.last_source = ""
        self.current_row: dict[str, Any] = {}
        self.subtitle_cues: list[tuple[float, float, str]] = []
        self.track_source_token = ""
        self.tracks_ready = False
        self.track_result: dict[str, Any] = {}
        self.last_track_failure: tuple[str, str] | None = None
        self.audio_choice: int | None = None
        self.subtitle_choice: int | str = -1
        self.offset = 0
        self.next_offset: int | None = None
        self.preview_id = ""
        self.preview_item = ""
        self.preview_device: DownloadingFileDevice | None = None
        self.preview_generation = 0
        self.preview_checked = 0.0
        self.preview_check_pending = False
        self.browse_generation = 0
        self.art_generation = 0
        self.detail_row: dict[str, Any] = {}
        self.art_stop = threading.Event()
        self.player: Any = None
        self.audio: Any = None
        self.video = VideoSurface(self)
        self.embedded_caption = ""
        self._player_video_mode = False

        self._build_presentation(add_folder)

    def _build_presentation(self, add_folder) -> None:
        self.media_layout = "cinematic"
        self.adult = False  # the XXX tab, once adult content is enabled in Settings
        self.anime_filters: dict[str, Any] = {}
        self.video_playing = False  # an Anime row's See all: series, OAV, films
        self.featured_id = ""
        self.picture_cache: OrderedDict[str, QImage] = OrderedDict()
        self._picture_cache_bytes = 0
        self.continue_rows: list[dict[str, Any]] = []
        # The video home shows rows (genres, series…); a card chosen in a row is the selection.
        self.home_data: dict[str, Any] | None = None
        self.home_row_widgets: list[MediaRow] = []
        self.row_choice = ""
        self.grid_mode = False  # a row's See all shows the grid until a browse tab is chosen
        # The app refreshes the library the first time Media opens after it starts.
        self.refresh_on_first_open = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.setObjectName("mediaWorkspace")
        self.setStyleSheet("""
            QWidget#mediaWorkspace, QWidget#mediaCanvas { background: #101315; color: #f1f3ef; }
            QListWidget#mediaPosters, QListWidget#mediaFocusStrip {
                background: transparent; color: #edf0ee; border: none; outline: 0;
            }
            QListWidget#mediaPosters::item:selected,
            QListWidget#mediaFocusStrip::item:selected {
                background: rgba(121, 211, 197, 43); border-radius: 7px; }
            QListWidget#mediaPosters::item:hover,
            QListWidget#mediaFocusStrip::item:hover {
                background: rgba(255, 255, 255, 14); border-radius: 7px; }
            /* The Media Center is always dark: it recolors the shared button roles
               (gui/controls.py) and keeps their shapes. */
            QWidget#mediaWorkspace QPushButton, QWidget#mediaWorkspace QToolButton {
                background: rgba(255, 255, 255, 22); color: #eef2ef;
                border: 1px solid rgba(255, 255, 255, 34); }
            QWidget#mediaWorkspace QPushButton:hover, QWidget#mediaWorkspace QToolButton:hover {
                background: rgba(255, 255, 255, 38); border-color: #79d3c5; }
            QWidget#mediaWorkspace QPushButton:disabled,
            QWidget#mediaWorkspace QToolButton:disabled {
                background: rgba(255, 255, 255, 10); color: #75817f;
                border-color: rgba(255, 255, 255, 18); }
            QWidget#mediaWorkspace [role="primary"] { background: #eff3ed; color: #13211f;
                border-color: #eff3ed; font-weight: 650; }
            QWidget#mediaWorkspace [role="primary"]:hover { background: #ffffff;
                border-color: #79d3c5; }
            QWidget#mediaWorkspace [role="quiet"], QWidget#mediaWorkspace [role="icon"] {
                background: transparent; border-color: transparent; color: #c9d3d1; }
            QWidget#mediaWorkspace [role="quiet"]:hover,
            QWidget#mediaWorkspace [role="icon"]:hover {
                background: rgba(255, 255, 255, 30); border-color: transparent; color: #f3f6f4; }
            QWidget#mediaWorkspace [role="icon"]:checked { background: #203d39;
                border-color: #79d3c5; color: #93dfce; }
            QWidget#mediaWorkspace [role="tab"] { background: transparent; color: #b8c2c1;
                border: 0; border-bottom: 2px solid transparent; }
            QWidget#mediaWorkspace [role="tab"]:hover { color: #f0f5f1; background: transparent; }
            QWidget#mediaWorkspace [role="tab"]:checked { color: #f0f5f1;
                border-bottom: 2px solid #79d3c5; }
            QLineEdit#mediaSearch { background: #172024; color: #e6eeeb;
                border: 1px solid #354644; border-radius: 8px; padding: 6px 10px; }
            QWidget#mediaWorkspace QPushButton#mediaCategoryCard { background: #1b3436;
                color: #eef5ee; border: 1px solid #304f4e; border-radius: 8px; font-size: 15px; }
            QLabel#mediaSection { color: #f1f3ef; font-size: 20px; font-weight: 600; }
        """)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter)
        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.setSpacing(0)
        self.splitter.addWidget(left)
        self.media_column = left
        left.installEventFilter(self)
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas = QWidget()
        self.canvas.setObjectName("mediaCanvas")
        self.body = QVBoxLayout(self.canvas)
        self.body.setContentsMargins(0, 0, 0, 24)
        self.body.setSpacing(18)
        self.content_scroll.setWidget(self.canvas)
        left_box.addWidget(self.content_scroll, 1)
        widget: QWidget
        self.header_box = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.header_box.setSpacing(12)
        self.brand = QLabel("TL")
        self.brand.setStyleSheet("font-size: 17px; font-weight: 750; color: #86d8cb;")
        self.brand.hide()
        self.header_box.addWidget(self.brand)
        navigation = QWidget()
        header = QHBoxLayout(navigation)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        self.kind = QComboBox(self)
        self.kind.addItem(self.tr("Video"), "video")
        self.kind.addItem(self.tr("Music"), "music")
        self.kind.hide()
        self.kind_tabs: dict[str, QPushButton] = {}
        self.kind_tab_group = QButtonGroup(self)
        for value, label in (("video", self.tr("Video")), ("music", self.tr("Music"))):
            button = QPushButton(label)
            set_role(button, "tab")
            button.setCheckable(True)
            button.setFixedWidth(button.fontMetrics().horizontalAdvance(label) + 24)
            button.setFixedHeight(32)
            button.clicked.connect(
                lambda _checked=False, name=value: self.kind.setCurrentIndex(
                    self.kind.findData(name)
                )
            )
            self.kind_tab_group.addButton(button)
            self.kind_tabs[value] = button
            header.addWidget(button)
        self.view = QComboBox(self)
        self.view.hide()
        self.video_navigation = QWidget()
        video_navigation_box = QHBoxLayout(self.video_navigation)
        video_navigation_box.setContentsMargins(12, 0, 0, 0)
        video_navigation_box.setSpacing(4)
        self.video_tabs: dict[str, QPushButton] = {}
        self.video_tab_group = QButtonGroup(self)
        for value, label in (
            ("all", self.tr("Home")),
            ("films", self.tr("Films")),
            ("series", self.tr("Series")),
            ("anime", self.tr("Anime")),
            ("adult", "XXX"),
        ):
            button = QPushButton(label)
            set_role(button, "tab")
            button.setCheckable(True)
            button.setFixedWidth(button.fontMetrics().horizontalAdvance(label) + 20)
            button.setFixedHeight(32)
            button.clicked.connect(lambda _checked=False, name=value: self._browse(name))
            self.video_tab_group.addButton(button)
            self.video_tabs[value] = button
            video_navigation_box.addWidget(button)
        self.video_tabs["adult"].hide()
        header.addWidget(self.video_navigation)
        header.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search saved media"))
        self.search.setObjectName("mediaSearch")
        self.search.setMaximumWidth(220)
        self.search.setMinimumWidth(120)
        self.search.hide()
        header.addWidget(self.search)
        self.header_box.addWidget(navigation, 1)
        tools = QWidget()
        tools_box = QHBoxLayout(tools)
        tools_box.setContentsMargins(0, 0, 0, 0)
        tools_box.setSpacing(6)
        self.search_toggle = QToolButton()
        self.search_toggle.setIcon(self._navigation_icon("search"))
        self.search_toggle.setIconSize(QSize(22, 22))
        self.search_toggle.setCheckable(True)
        self.search_toggle.setAccessibleName(self.tr("Search saved media"))
        self.search_toggle.setToolTip(self.tr("Search saved media"))
        self.search_toggle.toggled.connect(self._toggle_search)
        self.chat = QPushButton("✦")
        self.chat.setAccessibleName(self.tr("Chat"))
        self.chat.setToolTip(self.tr("Chat"))
        self.center_button = QPushButton("⤢")
        self.center_button.setCheckable(True)
        self.center_button.setAccessibleName(self.tr("Media Center mode"))
        self.center_button.setToolTip(self.tr("Media Center mode"))
        self.center_button.clicked.connect(lambda checked: self.center_mode_requested.emit(checked))
        self.layout_combo = QComboBox(self)
        self.layout_combo.setObjectName("media-layout")
        self.layout_combo.setAccessibleName(self.tr("Media layout"))
        self.layout_combo.addItem(self.tr("Cinematic home"), "cinematic")
        self.layout_combo.addItem(self.tr("Focus"), "focus")
        self.layout_combo.addItem(self.tr("Collection"), "collection")
        self.layout_combo.hide()
        self.library_disclosure = QPushButton(self.tr("Library options"), self)
        self.library_disclosure.setCheckable(True)
        self.library_disclosure.hide()
        self.options_button = QToolButton()
        self.options_button.setText("⋯")
        self.options_button.setAccessibleName(self.tr("Library options"))
        self.options_button.setToolTip(self.tr("Library options"))
        self.options_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.options_menu = QMenu(self.options_button)
        self.layout_menu = self.options_menu.addMenu(self.tr("Media layout"))
        self.layout_actions = []
        self.layout_action_group = QActionGroup(self)
        for index in range(self.layout_combo.count()):
            action = self.layout_menu.addAction(self.layout_combo.itemText(index))
            action.setCheckable(True)
            self.layout_action_group.addAction(action)
            action.triggered.connect(
                lambda _checked=False, i=index: self.layout_combo.setCurrentIndex(i)
            )
            self.layout_actions.append(action)
        self.library_action = self.options_menu.addAction(self.tr("Library options"))
        self.library_action.setCheckable(True)
        self.library_action.toggled.connect(self.library_disclosure.setChecked)
        self.library_disclosure.toggled.connect(self.library_action.setChecked)
        self.options_menu.addSeparator()
        self.view_actions = []
        for value, label in (
            ("recent", self.tr("Recent")),
            ("continue", self.tr("Continue watching")),
        ):
            action = self.options_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, name=value: self.view.setCurrentIndex(
                    self.view.findData(name)
                )
            )
            self.view_actions.append(action)
        self.options_button.setMenu(self.options_menu)
        self.refresh_icon = icon_button("⟳", self.tr("Refresh library"))
        self.refresh_icon.setCheckable(True)
        self.refresh_icon.clicked.connect(self._toggle_scan)
        for widget in (
            self.search_toggle,
            self.refresh_icon,
            self.chat,
            self.center_button,
            self.options_button,
        ):
            set_role(widget, "icon")
            tools_box.addWidget(widget)
        self.header_box.addWidget(tools)
        self.media_toolbar = QWidget()
        self.media_toolbar.setLayout(self.header_box)
        self.media_toolbar.setFixedHeight(58)
        self.header_box.setContentsMargins(20, 10, 20, 10)
        left_box.insertWidget(0, self.media_toolbar)
        self.content_scroll.viewport().installEventFilter(self)
        self.library_panel = QWidget()
        maintenance = QVBoxLayout(self.library_panel)
        maintenance.setContentsMargins(24, 12, 24, 12)
        category_row = QHBoxLayout()
        self.category_cards = {}
        for value, label in (
            ("all", self.tr("Home")),
            ("films", self.tr("Films")),
            ("series", self.tr("Series")),
            ("albums", self.tr("Albums")),
            ("artists", self.tr("Artists")),
            ("tracks", self.tr("Tracks")),
        ):
            button = QPushButton(label)
            button.setMinimumHeight(64)
            button.setObjectName("mediaCategoryCard")
            button.clicked.connect(
                lambda _checked=False, name=value: self.view.setCurrentIndex(
                    self.view.findData(name)
                )
            )
            self.category_cards[value] = button
            category_row.addWidget(button)
        maintenance.addLayout(category_row)
        folder_row = QHBoxLayout()
        self.refresh_button = QPushButton(self.tr("Refresh folders"))
        self.cancel_scan = QPushButton(self.tr("Cancel scan"))
        set_role(self.cancel_scan, "quiet")
        self.cancel_scan.setEnabled(False)
        self.folder_button = QPushButton(self.tr("Add folder…"))
        self.folder_button.clicked.connect(add_folder)
        for widget in (self.refresh_button, self.cancel_scan, self.folder_button):
            folder_row.addWidget(widget)
        folder_row.addStretch()
        maintenance.addLayout(folder_row)
        filters_row = QHBoxLayout()
        self.filter_labels = {
            "genre": self.tr("Any genre"),
            "year": self.tr("Any year"),
            "language": self.tr("Any language"),
            "availability": self.tr("Any availability"),
        }
        self.filters: dict[str, QComboBox] = {}
        for name in ("genre", "year", "language", "availability"):
            combo = QComboBox()
            combo.addItem(self.filter_labels[name], "")
            combo.currentIndexChanged.connect(self.refresh)
            self.filters[name] = combo
            filters_row.addWidget(combo)
        self.filter_panel = QWidget()
        self.filter_panel.setLayout(filters_row)
        filters_row.setContentsMargins(24, 0, 24, 0)
        self.library_panel.hide()
        self.library_disclosure.toggled.connect(self.library_panel.setVisible)
        self.library_disclosure.toggled.connect(
            lambda checked: self.filter_panel.setVisible(
                checked
                or (self.media_layout == "collection" and self.kind.currentData() == "video")
            )
        )
        self.body.addWidget(self.library_panel)
        self.body.addWidget(self.filter_panel)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.hide()
        self.body.addWidget(self.notice)
        self.empty = QLabel(
            self.tr(
                "Add a Library Folder, then Refresh folders to find videos and music. "
                "Media discovery does not need an Indexer connection."
            )
        )
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color: #a7b3b6; padding: 24px 0;")
        self.body.addWidget(self.empty)
        self.hero = MediaHero()
        self.play_button = QPushButton(self.tr("Play selected"))
        set_role(self.play_button, "primary")
        self.play_button.clicked.connect(self.play_selected)
        self.info_button = QPushButton(self.tr("More info"))
        set_role(self.info_button, "secondary")
        self.info_button.clicked.connect(self.open_details)
        self.enqueue_button = QPushButton(self.tr("Add to queue"))
        set_role(self.enqueue_button, "secondary")
        self.enqueue_button.clicked.connect(self.enqueue_selected)
        self.preview_button = QPushButton(self.tr("Preview downloaded portion"))
        set_role(self.preview_button, "primary")
        self.preview_button.clicked.connect(self.start_preview)
        self.refresh_preview = QPushButton(self.tr("Refresh preview"))
        set_role(self.refresh_preview, "quiet")
        self.refresh_preview.clicked.connect(self.start_preview)
        self.action_bar = QWidget()
        actions_box = QHBoxLayout(self.action_bar)
        actions_box.setContentsMargins(0, 0, 0, 0)
        for widget in (
            self.play_button,
            self.preview_button,
            self.info_button,
            self.enqueue_button,
            self.refresh_preview,
        ):
            actions_box.addWidget(widget)
        actions_box.addStretch()
        self.hero.action_layout.addWidget(self.action_bar)
        # The selected-title description stays fixed while the cards scroll beneath it.
        left_box.insertWidget(left_box.indexOf(self.content_scroll), self.hero)
        self.collection_heading = QLabel(self.tr("Your collection"))
        self.collection_heading.setContentsMargins(24, 12, 24, 0)
        self.collection_heading.setStyleSheet("font-size: 34px; font-weight: 650; color: #f2f4f0;")
        self.body.addWidget(self.collection_heading)
        self.music_navigation = QWidget()
        music_navigation_box = QHBoxLayout(self.music_navigation)
        music_navigation_box.setContentsMargins(24, 0, 24, 0)
        self.music_tabs: dict[str, QPushButton] = {}
        self.music_tab_group = QButtonGroup(self)
        for value, label in (
            ("albums", self.tr("Albums")),
            ("artists", self.tr("Artists")),
            ("tracks", self.tr("Tracks")),
        ):
            button = QPushButton(label)
            set_role(button, "tab")
            button.setCheckable(True)
            self.music_tab_group.addButton(button)
            button.clicked.connect(
                lambda _checked=False, view=value: self.view.setCurrentIndex(
                    self.view.findData(view)
                )
            )
            music_navigation_box.addWidget(button)
            self.music_tabs[value] = button
        music_navigation_box.addStretch()
        self.music_queue = QPushButton(self.tr("Queue ({0})").format(0))
        self.music_queue.clicked.connect(self._open_music_queue)
        set_role(self.music_queue, "quiet")
        self.music_playlists = QPushButton(self.tr("Playlists"))
        self.music_playlists.clicked.connect(self._open_music_playlists)
        set_role(self.music_playlists, "quiet")
        music_navigation_box.addWidget(self.music_queue)
        music_navigation_box.addWidget(self.music_playlists)
        self.body.addWidget(self.music_navigation)
        self.collection_selection = QWidget()
        self.collection_selection.setObjectName("mediaSelection")
        collection_box = QHBoxLayout(self.collection_selection)
        collection_box.setContentsMargins(20, 20, 20, 20)
        collection_box.setSpacing(24)
        self.music_cover = QLabel()
        self.music_cover.setFixedSize(160, 160)
        self.music_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        collection_box.addWidget(self.music_cover)
        selection_copy = QVBoxLayout()
        collection_box.addLayout(selection_copy, 1)
        self.collection_title = QLabel()
        self.collection_title.setStyleSheet("font-size: 20px; color: #f1f3ef; font-weight: 600;")
        self.collection_title.setTextFormat(Qt.TextFormat.PlainText)
        selection_copy.addWidget(self.collection_title)
        self.music_metadata = QLabel()
        self.music_metadata.setTextFormat(Qt.TextFormat.PlainText)
        self.music_metadata.setWordWrap(True)
        self.music_metadata.setStyleSheet("color: #b4c9c6; font-size: 13px;")
        selection_copy.addWidget(self.music_metadata)
        self.collection_actions = QHBoxLayout()
        selection_copy.addLayout(self.collection_actions)
        self.body.addWidget(self.collection_selection)
        self.series_panel = SeriesEpisodes()
        self.series_panel.play.connect(self._play_episode)
        self.series_panel.hide()
        self.body.addWidget(self.series_panel)
        self.continue_heading = QLabel(self.tr("Continue watching"))
        self.continue_heading.setObjectName("mediaSection")
        self.continue_heading.setContentsMargins(24, 12, 24, 0)
        self.body.addWidget(self.continue_heading)
        self.continue_panel = QWidget()
        self.continue_box = QHBoxLayout(self.continue_panel)
        self.continue_box.setContentsMargins(24, 0, 24, 0)
        self.continue_box.setSpacing(16)
        self.body.addWidget(self.continue_panel)
        self.home_rows_panel = QWidget()
        self.home_rows_box = QVBoxLayout(self.home_rows_panel)
        self.home_rows_box.setContentsMargins(0, 0, 0, 0)
        self.home_rows_box.setSpacing(22)
        self.home_rows_panel.hide()
        self.body.addWidget(self.home_rows_panel)
        shelf_header = QHBoxLayout()
        shelf_header.setContentsMargins(24, 0, 24, 0)
        self.shelf_heading = QLabel(self.tr("Recently added"))
        self.shelf_heading.setObjectName("mediaSection")
        self.page_count = QLabel()
        self.page_count.setStyleSheet("color: #9aa9ad; font-size: 11px;")
        shelf_header.addWidget(self.shelf_heading)
        shelf_header.addStretch()
        shelf_header.addWidget(self.page_count)
        self.body.addLayout(shelf_header)
        self.results = QListWidget()
        self.results.setObjectName("mediaPosters")
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.itemSelectionChanged.connect(self.show_detail)
        self.results.itemDoubleClicked.connect(lambda _item: self.play_selected())
        self.hero.strip.itemSelectionChanged.connect(self._focus_selection)
        self.body.addWidget(self.results)
        self.results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_scroll.verticalScrollBar().valueChanged.connect(self._load_more_media)
        self.details = QDialog(self)
        self.details.setWindowTitle(self.tr("Media details"))
        self.details.resize(620, 560)
        detail_box = QVBoxLayout(self.details)
        self.artwork = QLabel()
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_box.addWidget(self.artwork)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        detail_box.addWidget(self.description)
        self.releases = QComboBox()
        self.episodes = QComboBox()
        self.more_releases = QPushButton(self.tr("More releases"))
        self.more_episodes = QPushButton(self.tr("More episodes"))
        self.more_releases.clicked.connect(lambda: self._more_detail("releases"))
        self.more_episodes.clicked.connect(lambda: self._more_detail("episodes"))
        for combo, more in (
            (self.releases, self.more_releases),
            (self.episodes, self.more_episodes),
        ):
            line = QHBoxLayout()
            line.addWidget(combo, 1)
            line.addWidget(more)
            detail_box.addLayout(line)
        self.watched = QCheckBox(self.tr("Watched"))
        self.watched.clicked.connect(self._watched)
        detail_box.addWidget(self.watched)
        detail_actions = QHBoxLayout()
        detail_play = QPushButton(self.tr("Play selected"))
        set_role(detail_play, "primary")
        detail_play.clicked.connect(self.play_selected)
        detail_play.clicked.connect(self.details.hide)
        detail_preview = QPushButton(self.tr("Preview downloaded portion"))
        detail_preview.clicked.connect(self.start_preview)
        detail_preview.clicked.connect(self.details.hide)
        close_details = QPushButton(self.tr("Close"))
        set_role(close_details, "quiet")
        close_details.clicked.connect(self.details.hide)
        for widget in (detail_play, detail_preview, close_details):
            detail_actions.addWidget(widget)
        detail_box.addLayout(detail_actions)
        self.detail_widgets = [
            self.artwork,
            self.description,
            self.releases,
            self.episodes,
            self.watched,
        ]
        self.player_panel = QWidget()
        self.player_home_layout = left_box
        self.player_base_layout = left_box
        self.fullscreen_dialog = QDialog(self)
        self.fullscreen_dialog.setWindowTitle(self.tr("Media player"))
        self.fullscreen_layout = QVBoxLayout(self.fullscreen_dialog)
        self.fullscreen_layout.setContentsMargins(0, 0, 0, 0)
        self.fullscreen_dialog.finished.connect(self._leave_fullscreen)
        player_box = QVBoxLayout(self.player_panel)
        self.player_box = player_box
        player_box.setContentsMargins(12, 8, 12, 8)
        player_box.setSpacing(6)
        self.video.setMinimumHeight(300)
        player_box.addWidget(self.video, 1)
        self.video_overlay_box = QVBoxLayout(self.video.overlay)
        self.video_overlay_box.setContentsMargins(0, 0, 0, 0)
        self.player_back = QToolButton()
        self.player_back.setText("←")
        self.player_back.setToolTip(self.tr("Home"))
        self.player_back.setAccessibleName(self.tr("Home"))
        self.player_back.clicked.connect(self.dismiss_video)
        set_role(self.player_back, "icon")
        self.video_overlay_box.addWidget(self.player_back, 0, Qt.AlignmentFlag.AlignLeft)
        self.video_overlay_box.addStretch()
        self.caption = QLabel()
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        # Outlined text instead of a box, sized to the picture in _scale_caption.
        outline = QGraphicsDropShadowEffect(self.caption)
        outline.setOffset(0, 0)
        outline.setBlurRadius(8)
        outline.setColor(QColor(0, 0, 0, 255))
        self.caption.setGraphicsEffect(outline)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.video.overlay.installEventFilter(self)
        self._scale_caption()
        self.video_overlay_box.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignHCenter)
        self.video_controls = QWidget()
        self.video_controls.setObjectName("mediaVideoControls")
        self.video_controls.setStyleSheet("""
            QWidget#mediaVideoControls { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 rgba(0,0,0,50),stop:1 rgba(0,0,0,210)); color: white; }
            QWidget#mediaVideoControls [role="icon"] { color: white; }
        """)
        controls_box = QVBoxLayout(self.video_controls)
        controls_box.setContentsMargins(14, 10, 14, 8)
        controls_box.setSpacing(5)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName(self.tr("Seek"))
        self.seek.setRange(0, 0)
        self.seek.sliderReleased.connect(lambda: self.command("seek", position=self.seek.value()))
        controls_box.addWidget(self.seek)
        self.transport = QHBoxLayout()
        controls_box.addLayout(self.transport)
        self.previous_button = QPushButton()
        self.previous_button.clicked.connect(lambda: self._transport_step(-1))
        self.pause = QPushButton()
        self.pause.setAccessibleName(self.tr("Play / pause"))
        self.pause.clicked.connect(self.toggle_pause)
        self.next_button = QPushButton()
        self.next_button.clicked.connect(lambda: self._transport_step(1))
        previous, next_button = self.previous_button, self.next_button
        self.now_playing = QLabel(self.tr("Nothing playing"))
        self.now_playing.setTextFormat(Qt.TextFormat.PlainText)
        self.player_heading = QWidget()
        self.player_heading_box = QVBoxLayout(self.player_heading)
        self.player_heading_box.setContentsMargins(8, 8, 8, 8)
        self.player_heading_box.addWidget(self.now_playing)
        self.playing_description = QLabel()
        self.playing_description.setTextFormat(Qt.TextFormat.PlainText)
        self.playing_description.setWordWrap(True)
        self.player_heading_box.addWidget(self.playing_description)
        self.preview_refresh_home = QHBoxLayout()
        self.player_heading_box.addLayout(self.preview_refresh_home)
        player_box.addWidget(self.player_heading)
        self.elapsed = QLabel("0:00 / 0:00")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.setMaximumWidth(90)
        self.volume.setAccessibleName(self.tr("Volume"))
        self.volume.setToolTip(self.tr("Volume"))
        self.volume.sliderReleased.connect(
            lambda: self.command("volume", volume=self.volume.value() / 100)
        )
        for widget in (previous, self.pause, next_button, self.elapsed, self.volume):
            self.transport.addWidget(widget)
        self.transport.addStretch()
        self.fullscreen_button = QPushButton()
        self.fullscreen_button.setObjectName("media-fullscreen")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        self.player_options = QToolButton()
        self.player_options.setText("⋯")
        self.player_options.setAccessibleName(self.tr("Player options"))
        self.player_options.setToolTip(self.tr("Player options"))
        self.player_options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.player_menu = QMenu(self.player_options)
        self.player_options.setMenu(self.player_menu)
        self.audio_menu = self.player_menu.addMenu(self.tr("Audio track"))
        self.subtitle_menu = self.player_menu.addMenu(self.tr("Subtitle track"))
        self.repeat_menu = self.player_menu.addMenu(self.tr("Repeat off"))
        self.shuffle_action = self.player_menu.addAction(self.tr("Shuffle"))
        self.shuffle_action.setCheckable(True)
        self.shuffle_action.triggered.connect(
            lambda checked: self.command("shuffle", shuffle=checked)
        )
        self.queue_action = self.player_menu.addAction(self.tr("Queue & playlists"))
        self.queue_action.setCheckable(True)
        self.player_menu.aboutToShow.connect(self._build_player_menu)
        self.player_menu.aboutToShow.connect(self._show_video_controls)
        self.player_menu.aboutToHide.connect(self._show_video_controls)
        self.transport.addWidget(self.player_options)
        self.transport.addWidget(self.fullscreen_button)
        for widget in (
            previous,
            self.pause,
            next_button,
            self.player_options,
            self.fullscreen_button,
        ):
            set_role(widget, "icon")
            widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.fullscreen_button.setObjectName("media-fullscreen")
        self.fullscreen_button.setIcon(
            self._player_icon(QStyle.StandardPixmap.SP_TitleBarMaxButton)
        )
        self.fullscreen_button.setToolTip(self.tr("Fullscreen"))
        self.fullscreen_button.setAccessibleName(self.tr("Fullscreen"))
        self.video_overlay_box.addWidget(self.video_controls)
        self.music_controls_home = QVBoxLayout()
        self.music_controls_home.setContentsMargins(0, 0, 0, 0)
        player_box.addLayout(self.music_controls_home)
        self.shuffle = QCheckBox(self.tr("Shuffle"), self.player_panel)
        self.shuffle.clicked.connect(lambda on: self.command("shuffle", shuffle=on))
        self.repeat = QComboBox(self.player_panel)
        for label, value in (
            (self.tr("Repeat off"), "off"),
            (self.tr("Repeat all"), "all"),
            (self.tr("Repeat one"), "one"),
        ):
            self.repeat.addItem(label, value)
        self.repeat.currentIndexChanged.connect(
            lambda: self.command("repeat", repeat=self.repeat.currentData())
        )
        self.audio_tracks = QComboBox(self.player_panel)
        self.audio_tracks.setAccessibleName(self.tr("Audio track"))
        self.audio_tracks.currentIndexChanged.connect(self._select_audio)
        self.subtitles = QComboBox(self.player_panel)
        self.subtitles.setAccessibleName(self.tr("Subtitle track"))
        self.subtitles.addItem(self.tr("Subtitles off"), -1)
        self.subtitles.currentIndexChanged.connect(self._select_subtitle)
        self.queue_disclosure = QPushButton(self.tr("Queue & playlists"), self.player_panel)
        self.queue_disclosure.setCheckable(True)
        self.queue_action.triggered.connect(
            lambda checked: self.queue_disclosure.setChecked(checked)
        )
        for widget in (
            self.shuffle,
            self.repeat,
            self.audio_tracks,
            self.subtitles,
            self.queue_disclosure,
        ):
            widget.hide()
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.toggle_pause)
        self._swallow_release = False
        self.controls_timer = QTimer(self)
        self.controls_timer.setSingleShot(True)
        self.controls_timer.setInterval(2200)
        self.controls_timer.timeout.connect(self._hide_video_controls)
        for widget in (
            self.video,
            self.video.viewport(),
            self.video.overlay,
            self.video_controls,
            *self.video_controls.findChildren(QWidget),
        ):
            widget.installEventFilter(self)
        self._playback_controls_changed()
        self.external = QPushButton(self.tr("Open in external player"))
        self.external.clicked.connect(self.open_external)
        self.external.hide()
        player_box.addWidget(self.external)
        self.queue_panel = QWidget()
        queue_box = QHBoxLayout(self.queue_panel)
        self.queue = QListWidget()
        self.queue.setMaximumHeight(150)
        self.queue.itemDoubleClicked.connect(self._queue_play)
        queue_box.addWidget(self.queue, 1)
        queue_controls = QVBoxLayout()
        remove = QPushButton(self.tr("Remove from queue"))
        remove.clicked.connect(self.remove_from_queue)
        self.save_playlist = QPushButton(self.tr("Save queue as playlist…"))
        self.save_playlist.clicked.connect(self._save_playlist)
        self.playlists = QComboBox()
        self.playlists.setPlaceholderText(self.tr("Saved playlists"))
        self.load_playlist = QPushButton(self.tr("Load playlist"))
        self.load_playlist.clicked.connect(self._load_playlist)
        delete_playlist = QPushButton(self.tr("Delete playlist"))
        delete_playlist.clicked.connect(self._delete_playlist)
        for widget in (
            remove,
            self.save_playlist,
            self.playlists,
            self.load_playlist,
            delete_playlist,
        ):
            queue_controls.addWidget(widget)
        queue_box.addLayout(queue_controls)
        self.queue_panel.hide()
        self.queue_disclosure.toggled.connect(self.queue_panel.setVisible)
        player_box.addWidget(self.queue_panel)
        self.playback_widgets = [
            self.now_playing,
            previous,
            self.pause,
            next_button,
            self.seek,
            self.elapsed,
            self.volume,
            self.shuffle,
            self.repeat,
            self.audio_tracks,
            self.subtitles,
            self.fullscreen_button,
        ]
        self.queue_widgets = [
            self.queue,
            remove,
            self.save_playlist,
            self.playlists,
            self.load_playlist,
            delete_playlist,
        ]
        left_box.addWidget(self.player_panel)
        self.refresh_button.clicked.connect(self.start_scan)
        self.cancel_scan.clicked.connect(self._cancel_media_scan)
        self.scan_progress.connect(self._scan_progress)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.view.currentIndexChanged.connect(self._leave_video_for_navigation)
        self.view.currentIndexChanged.connect(self.refresh)
        self.view.currentIndexChanged.connect(self._sync_music_tabs)
        self.search.textChanged.connect(self.refresh)
        self.chat.setCheckable(True)
        self.chat.clicked.connect(self.toggle_chat)
        self.layout_combo.currentIndexChanged.connect(self._layout_selected)
        self._kind_changed()
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(1000)
        self.heartbeat.timeout.connect(self.report)
        # New films and episodes appear on their own while Media is open.
        self.auto_refresh = QTimer(self)
        self.auto_refresh.setInterval(AUTO_REFRESH_MS)
        self.auto_refresh.timeout.connect(self._auto_scan)
        self.set_media_layout("cinematic")
        self._update_panes()

    def _navigation_icon(self, name: str) -> QIcon:
        pixmap = QPixmap(22, 22)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#dbe5e2"))
        if name == "search":
            painter.drawEllipse(3, 3, 11, 11)
            painter.drawLine(12, 12, 19, 19)
        painter.end()
        return QIcon(pixmap)

    def _set_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _toggle_search(self, checked: bool) -> None:
        self.search.setVisible(checked)
        if checked:
            self.search.setFocus()
        self._arrange_toolbar()

    def _arrange_toolbar(self) -> None:
        width = self.content_scroll.viewport().width()
        self.header_box.setDirection(QBoxLayout.Direction.LeftToRight)
        self.video_navigation.setVisible(
            self.kind.currentData() == "video"
            and width >= 760
            and not (self.search.isVisible() and width < 1000)
        )
        self.search.setMaximumWidth(220 if width >= 1100 else 150)
        self.brand.setText("TorrentLinker" if width >= 1100 else "TL")

    def _sync_music_tabs(self) -> None:
        for name, button in self.kind_tabs.items():
            with QSignalBlocker(button):
                button.setChecked(self.kind.currentData() == name)
        for name, button in self.video_tabs.items():
            with QSignalBlocker(button):
                button.setChecked(self.view.currentData() == name)
        for name, button in self.music_tabs.items():
            with QSignalBlocker(button):
                button.setChecked(self.view.currentData() == name)

    def _open_music_queue(self) -> None:
        self.queue_disclosure.setChecked(True)
        self._update_panes()
        self.queue.setFocus()

    def _open_music_playlists(self) -> None:
        self._open_music_queue()
        self.playlists.setFocus()

    def _cancel_media_scan(self) -> None:
        if self.scan_stop:
            self.scan_stop.set()

    def _layout_selected(self) -> None:
        value = self.layout_combo.currentData()
        self.set_media_layout(value)
        self.layout_changed.emit(value)

    def set_adult(self, enabled: bool) -> None:
        """Show or hide the XXX tab (Settings → Adult content)."""
        if enabled == self.adult:
            return
        self.adult = enabled
        self.video_tabs["adult"].setVisible(enabled)
        if not enabled and self.view.currentData() == "adult":
            self.view.setCurrentIndex(0)
        if self.kind.currentData() == "video":
            current = self.view.currentData()
            self._kind_changed()
            self.view.setCurrentIndex(max(0, self.view.findData(current)))

    def set_media_layout(self, value: str) -> None:
        value = value if value in {"cinematic", "focus", "collection"} else "cinematic"
        self.media_layout = value
        for index, action in enumerate(self.layout_actions):
            action.setChecked(self.layout_combo.itemData(index) == value)
        with QSignalBlocker(self.layout_combo):
            self.layout_combo.setCurrentIndex(self.layout_combo.findData(value))
        self.hero.set_mode(value)
        collection = value == "collection" or self.kind.currentData() == "music"
        if collection:
            self.collection_actions.addWidget(self.action_bar)
        else:
            self.hero.action_layout.addWidget(self.action_bar)
        self.library_disclosure.setChecked(False)
        self.filter_panel.setVisible(value == "collection" and self.kind.currentData() == "video")
        self._configure_browse_layout()
        self._refresh_focus_strip()
        self._update_panes()

    def open_details(self) -> None:
        if self.selected_ids():
            self.details.show()
            self.details.raise_()

    def set_center_mode(self, enabled: bool) -> None:
        self.center_button.setChecked(enabled)
        self.center_button.setText("↩" if enabled else "⤢")
        label = self.tr("Return to TorrentLinker") if enabled else self.tr("Media Center mode")
        self.center_button.setAccessibleName(label)
        self.center_button.setToolTip(label)
        self.brand.setVisible(enabled)
        self._arrange_toolbar()

    def _transport_step(self, direction: int) -> None:
        if self._player_video_mode:
            self.command("seek", position=max(0, self.player.position() / 1000 + direction * 10))
        else:
            self.command("next" if direction > 0 else "previous")

    def _player_icon(self, standard: QStyle.StandardPixmap) -> QIcon:
        pixmap = self.style().standardIcon(standard).pixmap(24, 24)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor("white"))
        painter.end()
        return QIcon(pixmap)

    def _playback_controls_changed(self, *_args) -> None:
        playing = (
            self.player is not None
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self.pause.setIcon(
            self._player_icon(
                QStyle.StandardPixmap.SP_MediaPause
                if playing
                else QStyle.StandardPixmap.SP_MediaPlay
            )
        )
        self.pause.setToolTip(self.tr("Pause") if playing else self.tr("Play"))
        video = playing and self.current_row.get("kind") != "music"
        if video != self.video_playing:
            self.video_playing = video
            self.video_playing_changed.emit(video)
        self._show_video_controls()
        if self.kind.currentData() == "video" and self.current_row.get("kind") == "music":
            self._update_panes()  # the music bar follows play and pause while in Video

    def _scale_caption(self) -> None:
        self._fit_caption()

    def _fit_caption(self) -> None:
        """Size subtitles to the picture as it is now, and give every wrapped line room.

        The label gets the exact width it is measured at, so it never wraps onto more
        lines than its height allows; a long cue shrinks rather than leave the picture.
        """
        height = self.video.overlay.height() or 480
        width = max(200, self.video.overlay.width() * 9 // 10)
        text = self.caption.text()
        flags = int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap)
        size = max(16, min(56, height // 20))
        while True:
            font = QFont(self.caption.font())
            font.setPixelSize(size)
            font.setWeight(QFont.Weight.DemiBold)
            lines = QFontMetrics(font).boundingRect(QRect(0, 0, width, 100000), flags, text)
            if size <= 12 or lines.height() <= height * 2 // 5:
                break
            size -= 2
        if getattr(self, "caption_size", None) != size:
            self.caption_size = size
            # The page stylesheet would override a font set in code, so the size goes here.
            self.caption.setStyleSheet(
                f"color: white; background: transparent; font-size: {size}px; font-weight: 600;"
            )
        self.caption.setContentsMargins(0, 0, 0, size // 2)
        self.caption.setFixedWidth(width)
        self.caption.setFixedHeight(lines.height() + size // 2 + 4)

    def _show_video_controls(self) -> None:
        self.video_controls.show()
        self.player_back.show()
        if self._player_video_mode:
            self.video.viewport().unsetCursor()
            self.controls_timer.start()

    def _hide_video_controls(self) -> None:
        focus = QApplication.focusWidget()
        if not self._player_video_mode:
            self.controls_timer.stop()
            return
        if (
            self.player is None
            or self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
            or self.player_menu.isVisible()
            or (focus is not None and self.video_controls.isAncestorOf(focus))
        ):
            self.controls_timer.start()
            return
        self.video_controls.hide()
        self.player_back.hide()
        self.video.viewport().setCursor(Qt.CursorShape.BlankCursor)

    def _choose_menu_track(
        self, kind: str, identifier: str, token: str, media_id: str, _checked: bool = False
    ) -> None:
        if token != self.track_source_token or media_id != self.last_source:
            self.player_menu.close()
            return
        self.report()
        if token == self.track_source_token and media_id == self.last_source:
            self.command("select_track", kind=kind, track_id=identifier, source_token=token)

    def _build_player_menu(self) -> None:
        snapshot = self._track_state()
        token, media_id = snapshot["source_token"], snapshot["media_id"]
        for kind, menu, rows in (
            ("audio", self.audio_menu, snapshot["audio"]),
            ("subtitle", self.subtitle_menu, snapshot["subtitles"]),
        ):
            menu.clear()
            for previous_group in menu.findChildren(QActionGroup):
                previous_group.deleteLater()
            group = QActionGroup(menu)
            choices = (
                [
                    {
                        "id": "off",
                        "label": self.tr("Subtitles off"),
                        "selected": not any(row["selected"] for row in rows),
                    }
                ]
                if kind == "subtitle"
                else []
            ) + rows
            for row in choices:
                action = menu.addAction(row["label"])
                action.setCheckable(True)
                action.setChecked(row["selected"])
                action.setData(row["id"])
                group.addAction(action)
                action.triggered.connect(
                    partial(self._choose_menu_track, kind, row["id"], token, media_id)
                )
            menu.setEnabled(snapshot[f"{kind}_supported"])
        self.repeat_menu.clear()
        for previous_group in self.repeat_menu.findChildren(QActionGroup):
            previous_group.deleteLater()
        repeat_group = QActionGroup(self.repeat_menu)
        for index in range(self.repeat.count()):
            action = self.repeat_menu.addAction(self.repeat.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.repeat.currentIndex())
            repeat_group.addAction(action)
            action.triggered.connect(lambda _checked=False, i=index: self.repeat.setCurrentIndex(i))
        self.shuffle_action.setChecked(self.shuffle.isChecked())
        self.queue_action.setChecked(self.queue_disclosure.isChecked())

    def _arrange_player(self) -> None:
        active_video = bool(self.last_source) and self.current_row.get("kind") == "video"
        entering_video = active_video and not self._player_video_mode
        self._player_video_mode = active_video
        if active_video:
            if not self.fullscreen_dialog.isVisible() and self.player_home_layout is not self.body:
                self.body.insertWidget(0, self.player_panel)
                self.player_home_layout = self.body
            if self.video_overlay_box.indexOf(self.video_controls) < 0:
                self.video_overlay_box.addWidget(self.video_controls)
            if self.player_heading_box.indexOf(self.now_playing) < 0:
                self.player_heading_box.insertWidget(0, self.now_playing)
            self.now_playing.setStyleSheet("font-size: 23px; font-weight: 600; color: #f1f3ef;")
            self.playing_description.setText(str(self.current_row.get("description") or ""))
            self.playing_description.setVisible(bool(self.playing_description.text()))
        else:
            if (
                not self.fullscreen_dialog.isVisible()
                and self.player_home_layout is not self.player_base_layout
            ):
                self.player_base_layout.addWidget(self.player_panel)
                self.player_home_layout = self.player_base_layout
            if self.music_controls_home.indexOf(self.video_controls) < 0:
                self.music_controls_home.addWidget(self.video_controls)
            if self.transport.indexOf(self.now_playing) < 0:
                self.transport.insertWidget(3, self.now_playing, 1)
            self.now_playing.setStyleSheet("color: #e7eeeb;")
        if self.preview_id:
            self.preview_refresh_home.addWidget(self.refresh_preview)
        elif self.preview_refresh_home.indexOf(self.refresh_preview) >= 0:
            actions = self.action_bar.layout()
            if isinstance(actions, QBoxLayout):
                actions.insertWidget(4, self.refresh_preview)
        self.player_heading.setVisible(active_video and not self.fullscreen_dialog.isVisible())
        self.fullscreen_button.setVisible(active_video)
        for button, icon, label in (
            (
                self.previous_button,
                QStyle.StandardPixmap.SP_MediaSeekBackward,
                self.tr("Back 10 seconds") if active_video else self.tr("Previous"),
            ),
            (
                self.next_button,
                QStyle.StandardPixmap.SP_MediaSeekForward,
                self.tr("Forward 10 seconds") if active_video else self.tr("Next"),
            ),
        ):
            button.setIcon(self._player_icon(icon))
            button.setToolTip(label)
            button.setAccessibleName(label)
        if active_video and not self.fullscreen_dialog.isVisible():
            self.video.setFixedHeight(
                min(
                    max(300, self.content_scroll.viewport().height() - 90),
                    max(300, self.content_scroll.viewport().width() * 9 // 16),
                )
            )
        self._show_video_controls()
        if entering_video:
            self.content_scroll.verticalScrollBar().setValue(0)
            QTimer.singleShot(0, self._reveal_player)

    def _reveal_player(self) -> None:
        if isValid(self) and self._player_video_mode:
            self.content_scroll.verticalScrollBar().setValue(0)

    def _embedded_subtitle_text(self, text: str) -> None:
        self.embedded_caption = (
            QTextDocumentFragment.fromHtml(text).toPlainText() if "<" in text else text
        )
        self._render_caption()

    def _render_caption(self) -> None:
        if isinstance(self.subtitle_choice, str):
            seconds = self.player.position() / 1000
            text = "\n".join(
                caption for start, end, caption in self.subtitle_cues if start <= seconds < end
            )
        else:
            text = self.embedded_caption if self.subtitle_choice >= 0 else ""
        if text != self.caption.text():
            self.caption.setText(text)
            self._fit_caption()
        self.caption.setVisible(bool(text) and self._player_video_mode)

    def toggle_fullscreen(self) -> None:
        if self.fullscreen_dialog.isVisible():
            self.fullscreen_dialog.reject()
        elif self.last_source:
            self._player_home_index = self.player_home_layout.indexOf(self.player_panel)
            self.fullscreen_layout.addWidget(self.player_panel)
            self.player_box.setContentsMargins(0, 0, 0, 0)
            self.video.setMinimumHeight(0)
            self.video.setMaximumHeight(16777215)
            self.fullscreen_button.setToolTip(self.tr("Exit fullscreen"))
            self.fullscreen_button.setAccessibleName(self.tr("Exit fullscreen"))
            self.player_heading.hide()
            self.fullscreen_dialog.showFullScreen()
            self.fullscreen_button.setFocus()

    def _leave_fullscreen(self) -> None:
        self.player_box.setContentsMargins(12, 8, 12, 8)
        self.player_home_layout.insertWidget(self._player_home_index, self.player_panel)
        self._arrange_player()
        self.fullscreen_button.setToolTip(self.tr("Fullscreen"))
        self.fullscreen_button.setAccessibleName(self.tr("Fullscreen"))
        self.player_panel.show()
        self.fullscreen_button.setFocus()

    def _focus_selection(self) -> None:
        items = self.hero.strip.selectedItems()
        if not items:
            return
        identifier = items[0].data(Qt.ItemDataRole.UserRole)
        for index in range(self.results.count()):
            item = self.results.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == identifier:
                with QSignalBlocker(self.results):
                    self.results.clearSelection()
                    item.setSelected(True)
                self.show_detail()
                break

    def _refresh_focus_strip(self) -> None:
        with QSignalBlocker(self.hero.strip):
            self.hero.strip.clear()
            rows = list(self.rows)
            featured = next((row for row in rows if row["id"] == self.featured_id), None)
            if featured:
                rows = [featured, *[row for row in rows if row["id"] != self.featured_id]]
            for row in rows:
                item = QListWidgetItem(self._card_title(row))
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                picture = self.picture_cache.get(row["id"])
                item.setIcon(
                    self._cover_icon(picture, QSize(112, 148))
                    if picture is not None
                    else self._placeholder_icon(row["kind"])
                )
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.hero.strip.addItem(item)
                item.setSelected(row["id"] == self.featured_id)

    @staticmethod
    def _time_label(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return (
            f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
            if seconds >= 3600
            else f"{seconds // 60}:{seconds % 60:02d}"
        )

    def _show_feature(self, row: dict[str, Any]) -> None:
        self.featured_id = row["id"]
        self.hero.title.setText(row["title"])
        self.collection_title.setText(row["title"])
        if row["kind"] == "music":
            view = self.view.currentData()
            title = (
                row.get("album")
                if view == "albums"
                else row.get("artist")
                if view == "artists"
                else row["title"]
            ) or row["title"]
            self.collection_title.setText(str(title))
            tags = [str(row[key]) for key in ("artist", "year") if row.get(key)]
            if view == "tracks" and row.get("album"):
                tags.append(str(row["album"]))
            if row.get("track_count"):
                tags.append(self.tr(" · {0} tracks").format(row["track_count"]).lstrip(" ·"))
            if view == "tracks" and row.get("duration"):
                tags.append(self._time_label(float(row["duration"])))
            self.music_metadata.setText(" · ".join(tags))
            picture = self.picture_cache.get(row["id"])
            icon = (
                self._cover_icon(picture, QSize(160, 160))
                if picture is not None
                else self._placeholder_icon("music")
            )
            self.music_cover.setPixmap(icon.pixmap(160, 160))
        facts = [
            str(row[key])
            for key in ("year", "artist", "album", "genre", "language")
            if row.get(key)
        ]
        if row.get("identity_source") == "filename":
            facts.insert(0, self.tr("Filename metadata"))
        if row.get("rating"):
            facts.append("★ " + str(row["rating"]))
        if row.get("duration"):
            facts.append(self._time_label(float(row["duration"])))
        if row.get("position"):
            facts.append(self.tr("Resume at {0}").format(self._time_label(float(row["position"]))))
        self.hero.metadata.setText(" · ".join(facts))
        synopsis = str(row.get("description") or "")
        self.hero.synopsis.setText(synopsis[:360] + ("…" if len(synopsis) > 360 else ""))
        self.hero.set_picture(self.picture_cache.get(row["id"], QImage()))
        self.play_button.setText(
            self.tr("Resume") if row.get("position") else self.tr("Play selected")
        )
        self._refresh_focus_strip()

    def _render_continue(self) -> None:
        while self.continue_box.count():
            item = self.continue_box.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self.continue_heading.setText(
            self.tr("Continue watching")
            if self.kind.currentData() == "video"
            else self.tr("Continue listening")
        )
        for row in self.continue_rows[:4]:
            button = MediaTileButton()
            button.setMinimumHeight(165)
            button.setStyleSheet(
                "QPushButton { border: 0; background: transparent; padding: 0; "
                "text-align: left; color: #edf1ef; }"
            )
            button.setMinimumWidth(140)
            column = QVBoxLayout(button)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(5)
            still = QLabel()
            still.setFixedHeight(105)
            still.setAlignment(Qt.AlignmentFlag.AlignCenter)
            still.setStyleSheet("background: #17242b; border-radius: 6px;")
            picture = self.picture_cache.get(row["id"])
            if picture is not None:
                still.setPixmap(
                    QPixmap.fromImage(picture).scaled(
                        240,
                        105,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                still.setPixmap(self._placeholder_icon(row["kind"]).pixmap(80, 90))
            column.addWidget(still)
            progress = QProgressBar()
            progress.setTextVisible(False)
            progress.setFixedHeight(3)
            progress.setRange(0, 100)
            duration = float(row.get("duration") or 0)
            progress.setValue(
                min(100, round(100 * float(row.get("position") or 0) / duration)) if duration else 0
            )
            progress.setStyleSheet(
                "QProgressBar { background: rgba(255, 255, 255, 37); border: none; } "
                "QProgressBar::chunk { background: #79d3c5; }"
            )
            column.addWidget(progress)
            label = QLabel(row["title"])
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setStyleSheet("color: #e9eeeb; font-size: 12px;")
            column.addWidget(label)
            position = QLabel(self._time_label(float(row.get("position") or 0)))
            position.setStyleSheet("color: #9eacb0; font-size: 10px;")
            column.addWidget(position)
            for child in button.findChildren(QWidget):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            button.clicked.connect(
                lambda _checked=False, identifier=row["id"]: self.command(
                    "play", media_ids=[identifier], index=0
                )
            )
            tile = QWidget()
            tile_box = QGridLayout(tile)
            tile_box.setContentsMargins(0, 0, 0, 0)
            tile_box.addWidget(button, 0, 0)
            remove = icon_button("✕", self.tr("Remove from Continue watching"))
            remove.setObjectName("continueRemove")
            # An icon over artwork keeps a dark backdrop to stay readable.
            remove.setStyleSheet(
                "QToolButton { background: rgba(0, 0, 0, 150); color: #f1f3ef; } "
                "QToolButton:hover { background: #b84a4a; }"
            )
            remove.clicked.connect(
                lambda _checked=False, identifier=row["id"]: self.forget_progress(identifier)
            )
            tile_box.addWidget(
                remove, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
            )
            self.continue_box.addWidget(tile, 1)
        self.continue_box.addStretch()

    def forget_progress(self, identifier: str) -> None:
        """Drop a title from Continue watching and close it if it is the one loaded."""
        if not self.library:
            return
        if self.last_source == identifier:
            self.dismiss_video()
            self.state.update(queue=[], index=0)
        try:
            self.library.forget_progress(self.session_client, identifier)
        except (OSError, ValueError) as error:
            self._set_notice(str(error))
        self.refresh()

    def rebind(
        self,
        get_service: Callable[[], Any],
        client_id: Callable[[], str],
        add_folder: Callable[[], None],
    ) -> None:
        """Keep the current player when a settings change replaces its main window."""
        self._invalidate_preview_request()
        self.get_service = get_service
        self.client_id = client_id
        self.folder_button.clicked.disconnect()
        self.folder_button.clicked.connect(add_folder)
        if self.assistant:
            self.assistant.get_service = get_service
        if self.library and self.state["current_id"] and not self.preview_id:
            try:
                self.library.resolve(self.session_client, self.state["current_id"])
            except (OSError, ValueError) as error:
                self.player.stop()
                self.player.setSource(QUrl())
                self.state["current_id"] = ""
                self.last_source = ""
                self._set_notice(str(error))

    def activate(self) -> None:
        try:
            if self.library is not None and self.session_client != self.client_id():
                self.stop()
                self.player.deleteLater()
                self.audio.deleteLater()
                self.library = None
                self.state.update(current_id="", queue=[], index=0, position=0)
                self.last_source = ""
                self.command_ack = 0
                self.conversation_id = ""
            if self.library is None:
                self.service = self.get_service()
                self.library = self.service.agent.media
                self.session_client = self.client_id()
                self.credentials = QSettings(
                    str(self.service.agent.setup.path.with_name("media-desktop.ini")),
                    QSettings.Format.IniFormat,
                )
                self.credentials.beginGroup(self.session_client)
                saved_id = str(self.credentials.value("session", ""))
                saved_token = str(self.credentials.value("token", ""))
                session = None
                if saved_id and saved_token:
                    try:
                        session = self.library.session(saved_id, saved_token)
                        self.session_id, self.token = saved_id, saved_token
                        self.conversation_id = str(self.credentials.value("conversation", ""))
                    except (OSError, ValueError):
                        pass
                if session is None:
                    session = self.library.open_session(self.session_client, "desktop")
                    self.session_id, self.token = session["id"], session["token"]
                    self.conversation_id = ""
                self.credentials.setValue("session", self.session_id)
                self.credentials.setValue("token", self.token)
                self.credentials.setValue("conversation", self.conversation_id)
                self.credentials.sync()
                QFile.setPermissions(
                    self.credentials.fileName(),
                    QFile.Permission.ReadOwner | QFile.Permission.WriteOwner,
                )
                self.state.update(session["state"])
                self.current_playlist = self.state.get("context", {}).get("playlist", "")
                self.command_ack = int(self.state.get("command_ack", 0))
                self.player = QMediaPlayer(self)
                self.audio = create_audio_output(self)
                self.player.setAudioOutput(self.audio)
                self.decoder_sink = QVideoSink(self.player)
                self.display_frames = DisplayFrames()
                self.display_frames.moveToThread(frame_thread())
                self.destroyed.connect(self.display_frames.deleteLater)
                self.video.frames = self.display_frames
                self.video.measure()
                self.decoder_sink.videoFrameChanged.connect(
                    self.display_frames.convert, Qt.ConnectionType.QueuedConnection
                )
                self.display_frames.ready.connect(self.video.item.videoSink().setVideoFrame)
                self.decoder_sink.subtitleTextChanged.connect(self._embedded_subtitle_text)
                self.player.setVideoSink(self.decoder_sink)
                self.player.playbackStateChanged.connect(self._playback_controls_changed)
                self.player.errorOccurred.connect(self._codec_error)
                self.player.positionChanged.connect(self._position_changed)
                self.player.durationChanged.connect(self._duration_changed)
                self.player.mediaStatusChanged.connect(self._media_status)
                self.player.tracksChanged.connect(self._playback_tracks)
                self.player.sourceChanged.connect(self._track_source_changed)
                self.audio.setVolume(float(self.state["volume"]))
                self.volume.setValue(round(float(self.state["volume"]) * 100))
                with QSignalBlocker(self.shuffle), QSignalBlocker(self.repeat):
                    self.shuffle.setChecked(bool(self.state["shuffle"]))
                    self.repeat.setCurrentIndex(max(0, self.repeat.findData(self.state["repeat"])))
                self.heartbeat.start()
                try:
                    # Start on the library; Continue watching keeps the saved video position.
                    queue, index = self.state["queue"], int(self.state["index"])
                    current = queue[max(0, min(index, len(queue) - 1))] if queue else ""
                    if (
                        current
                        and self.library.detail(self.session_client, current)["kind"] == "video"
                    ):
                        self.state.update(current_id="", queue=[], index=0, position=0)
                    self._load_current(play=False)
                except (OSError, ValueError) as error:
                    self._set_notice(str(error))
                    self._render_queue()
                self.apply_player_commands(session.get("commands", []))
                if self.refresh_on_first_open:
                    self.refresh_on_first_open = False
                    folders = self.library.setup(self.session_client).settings.library_folders
                    if folders:
                        QTimer.singleShot(0, self.start_scan)
            self.refresh()
            QTimer.singleShot(0, self, self._auto_scan)  # dropped if the tab is deleted
            self.auto_refresh.start()
        except Exception as error:
            self._set_notice(str(error))

    def dismiss_video(self) -> None:
        """Return to browsing while preserving progress and the saved queue."""
        if self.fullscreen_dialog.isVisible():
            self.fullscreen_dialog.reject()
        self._invalidate_preview_request()
        if self.player is not None:
            self.player.pause()
            self.report()
            self._clear_track_source()
            self.player.stop()
            self.player.setSource(QUrl())
        self._close_preview()
        self.last_source = ""
        self.current_row = {}
        self.state.update(current_id="", position=0, duration=0, paused=True)
        self.subtitle_cues = []
        self.caption.clear()
        self.now_playing.setText(self.tr("Nothing playing"))
        self._update_panes()
        self.content_scroll.verticalScrollBar().setValue(0)
        self.report()

    def _leave_video_for_navigation(self, *_args) -> None:
        if self._player_video_mode:
            self.dismiss_video()

    def _kind_changed(self) -> None:
        self._leave_video_for_navigation()
        values = (
            (
                (self.tr("All"), "all"),
                (self.tr("Recent"), "recent"),
                (self.tr("Continue watching"), "continue"),
                (self.tr("Films"), "films"),
                (self.tr("Series"), "series"),
                (self.tr("Anime"), "anime"),
                (self.tr("Highly rated"), "rated"),
                (self.tr("Not watched yet"), "unwatched"),
                *((("XXX", "adult"),) if self.adult else ()),
            )
            if self.kind.currentData() == "video"
            else (
                (self.tr("Albums"), "albums"),
                (self.tr("Artists"), "artists"),
                (self.tr("Tracks"), "tracks"),
            )
        )
        with QSignalBlocker(self.view):
            self.view.clear()
            for label, value in values:
                self.view.addItem(label, value)
        self._sync_music_tabs()
        self.set_media_layout(self.media_layout)
        self.refresh()

    def _configure_browse_layout(self) -> bool:
        cards = self.kind.currentData() == "video" or self.view.currentData() in {
            "albums",
            "artists",
        }
        self.results.setViewMode(
            QListView.ViewMode.IconMode if cards else QListView.ViewMode.ListMode
        )
        self.results.setFlow(QListView.Flow.LeftToRight if cards else QListView.Flow.TopToBottom)
        self.results.setResizeMode(QListView.ResizeMode.Adjust)
        self.results.setMovement(QListView.Movement.Static)
        self.results.setWrapping(cards)
        self.results.setWordWrap(cards)
        self.results.setUniformItemSizes(cards)
        self.results.setSpacing(8 if cards else 2)
        music = self.kind.currentData() == "music"
        dense = self.media_layout == "collection" and not music
        self.results.setGridSize(
            QSize(180, 220)
            if music and cards
            else QSize(156, 226)
            if cards and dense
            else QSize(180, 248)
            if cards
            else QSize()
        )
        self.results.setIconSize(
            QSize(148, 148)
            if music and cards
            else QSize(116, 154)
            if cards and dense
            else QSize(128, 170)
            if cards
            else QSize(44, 44)
        )
        QTimer.singleShot(0, self._resize_media_grid)
        return cards

    def eventFilter(self, watched, event):
        if (
            watched is getattr(self, "media_column", None)
            and hasattr(self, "hero")
            and event.type() == QEvent.Type.Resize
        ):
            # Leave at least half of short windows to the scrolling cards.
            self.hero.height_cap = max(220, watched.height() // 2)
            self.hero._arrange()
        if watched is self.content_scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._arrange_toolbar()
            QTimer.singleShot(0, self._resize_media_grid)
            if hasattr(self, "controls_timer"):
                self._arrange_player()
        if hasattr(self, "controls_timer"):
            surface = watched in (self.video, self.video.viewport(), self.video.overlay)
            if (
                event.type()
                in {
                    QEvent.Type.MouseMove,
                    QEvent.Type.Enter,
                    QEvent.Type.FocusIn,
                    QEvent.Type.KeyPress,
                }
                and watched is not self.content_scroll.viewport()
            ):
                self._show_video_controls()
            if surface and event.type() == QEvent.Type.ContextMenu:
                self.player_menu.popup(event.globalPos())
                return True
            if watched is self.video.overlay and event.type() == QEvent.Type.Resize:
                self._scale_caption()
            if (
                surface
                and event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton
            ):
                # The click that started this double-click must not pause.
                self.click_timer.stop()
                self._swallow_release = True
                self.toggle_fullscreen()
                return True
            if (
                surface
                and event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self.video.setFocus()
                if self._swallow_release:
                    self._swallow_release = False
                else:
                    self.click_timer.start(QApplication.doubleClickInterval())
                return True
            if surface and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Space:
                    self.toggle_pause()
                    return True
                if event.key() in {Qt.Key.Key_Left, Qt.Key.Key_Right}:
                    self._transport_step(1 if event.key() == Qt.Key.Key_Right else -1)
                    return True
                if event.key() == Qt.Key.Key_F:
                    self.toggle_fullscreen()
                    return True
                if event.key() == Qt.Key.Key_Escape and self.fullscreen_dialog.isVisible():
                    self.fullscreen_dialog.reject()
                    return True
        return super().eventFilter(watched, event)

    def _cover_icon(self, picture: QImage, size: QSize | None = None) -> QIcon:
        size = size or self.results.iconSize()
        pixmap = QPixmap.fromImage(picture).scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = max(0, (pixmap.width() - size.width()) // 2)
        top = max(0, (pixmap.height() - size.height()) // 2)
        cropped = pixmap.copy(left, top, size.width(), size.height())
        if self.kind.currentData() == "music" and self.view.currentData() == "artists":
            rounded = QPixmap(size)
            rounded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            mask = QPainterPath()
            mask.addEllipse(QRectF(rounded.rect()))
            painter.setClipPath(mask)
            painter.drawPixmap(0, 0, cropped)
            painter.end()
            cropped = rounded
        return QIcon(cropped)

    def _placeholder_icon(self, kind: str) -> QIcon:
        music = kind == "music"
        cover = QPixmap(160, 160) if music else QPixmap(128, 170)
        palette = self.palette()
        cover.fill(Qt.GlobalColor.transparent)
        painter = QPainter(cover)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.setBrush(palette.color(QPalette.ColorRole.AlternateBase))
        if music and self.view.currentData() == "artists":
            painter.drawEllipse(cover.rect().adjusted(2, 2, -2, -2))
        else:
            painter.drawRoundedRect(cover.rect().adjusted(1, 1, -2, -2), 8, 8)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        if not music:
            triangle = QPainterPath()
            triangle.moveTo(48, 53)
            triangle.lineTo(48, 105)
            triangle.lineTo(88, 79)
            triangle.closeSubpath()
            painter.fillPath(triangle, palette.color(QPalette.ColorRole.Highlight))
        else:
            font = QFont(painter.font())
            font.setPointSize(40)
            painter.setFont(font)
            painter.drawText(cover.rect().adjusted(0, 0, 0, -32), Qt.AlignmentFlag.AlignCenter, "♪")
        font = QFont(painter.font())
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(
            cover.rect().adjusted(0, 124, 0, -10),
            Qt.AlignmentFlag.AlignCenter,
            self.tr("Music") if music else self.tr("Video"),
        )
        painter.end()
        return QIcon(cover)

    def _card_title(self, row: dict[str, Any]) -> str:
        view = self.view.currentData()
        title = (
            row.get("album")
            if view == "albums"
            else row.get("artist")
            if view == "artists"
            else row["title"]
        ) or row["title"]
        title = str(title)
        if len(title) > 52:
            title = title[:49] + "…"
        subtitle = str(row.get("artist") or "") if view == "albums" else str(row.get("year") or "")
        if row.get("series_card"):
            subtitle = self.tr("{0} episodes").format(row["episode_count"])
        if row.get("track_count"):
            count = self.tr(" · {0} tracks").format(row["track_count"]).lstrip(" ·")
            subtitle = subtitle + "\n" + count if view == "albums" and subtitle else count
        if not row.get("available", True):
            subtitle += self.tr(" · unavailable")
        return title + ("\n" + subtitle[:30] if subtitle else "")

    def _context(self) -> dict[str, Any]:
        return {
            "kind": self.kind.currentData(),
            "view": self.view.currentData(),
            "q": self.search.text(),
            **{key: combo.currentData() for key, combo in self.filters.items()},
            "selected_ids": self.selected_ids(),
            "preview_id": self.preview_id,
            "playlist": self.current_playlist,
        }

    def _resize_media_grid(self) -> None:
        if not isValid(self) or not hasattr(self, "results"):
            return
        self.results.doItemsLayout()
        last = self.results.item(self.results.count() - 1)
        height = self.results.visualItemRect(last).bottom() + 24 if last else 120
        remaining = self.content_scroll.viewport().height() - self.results.y() - 24
        self.results.setFixedHeight(max(120, remaining, height))

    def _load_more_media(self, _value: int) -> None:
        scroll = self.content_scroll.verticalScrollBar()
        if (
            self.next_offset is not None
            and self.results.isEnabled()
            and self.results.isVisible()
            and scroll.maximum() > 0
            and scroll.maximum() - scroll.value() < 320
        ):
            self.offset = self.next_offset
            self.refresh(keep_page=True)

    def refresh(self, *_args: Any, keep_page: bool = False) -> None:
        if self.library is None:
            return
        context = self._context()
        context.pop("selected_ids")
        context.pop("preview_id")
        context.pop("playlist")
        if not keep_page:
            self.offset = 0
            self.next_offset = None
        self.browse_generation += 1
        generation = self.browse_generation
        library, client, offset = self.library, self.session_client, self.offset
        home = self._home_active() and not keep_page
        scope = {"films": "films", "series": "series", "anime": "anime", "adult": "adult"}.get(
            self.view.currentData(), "home"
        )
        if context["view"] == "adult":  # the XXX panel: its folders only, newest first
            context.update(view="recent", adult=True)
        elif context["view"] == "anime":  # the Anime panel, or one of its rows' See all
            context.update(view="recent", anime=True, **self.anime_filters)
        elif context["view"] in {"films", "series"}:
            context.update(anime=False)  # anime has its own panel
        self.results.setEnabled(False)
        self._set_notice(self.tr("Loading saved media…"))

        def work():
            continuation = {**context, "view": "continue"}
            return (
                library.listing(client, offset=offset, **context),
                library.playlists(client),
                library.listing(client, limit=4, **continuation)["rows"],
                library.home_rows(client, kind="video", scope=scope) if home else None,
            )

        def done(payload):
            if not isValid(self) or generation != self.browse_generation:
                return
            if not keep_page:
                self.home_data = payload[3]
                self._render_home_rows()
            self._show_listing(*payload[:3], append=keep_page)
            self.results.setEnabled(True)

        def failed(error):
            if isValid(self) and generation == self.browse_generation:
                self.results.setEnabled(True)
                self._set_notice(str(error))

        run_in_background(work, done, failed)

    def _show_listing(
        self,
        result: dict[str, Any],
        playlists: list[dict[str, Any]],
        continuation: list[dict[str, Any]],
        *,
        append: bool = False,
    ) -> None:
        try:
            selected = self.selected_ids()
            self.continue_rows = continuation
            self.next_offset = result.get("next_offset")
            self.page_count.setText(self.tr("{0} saved items").format(result["total"]))
            if append:
                seen = {row["id"] for row in self.rows}
                added = [row for row in result["rows"] if row["id"] not in seen]
                self.rows.extend(added)
            else:
                added = result["rows"]
                self.rows = added
            cards = self._configure_browse_layout()
            placeholder = self._placeholder_icon(self.kind.currentData())
            if not append:
                self.results.clear()
            for row in added:
                title = row["title"]
                if row.get("artist"):
                    title = f"{row['artist']} · {title}"
                if row.get("album"):
                    title += f" · {row['album']}"
                if row.get("track_count"):
                    title += self.tr(" · {0} tracks").format(row["track_count"])
                if row.get("release") and self.view.currentData() not in {"albums", "artists"}:
                    title += f" · {row['release']}"
                if not row.get("available", True):
                    title += self.tr(" · unavailable")
                if row["kind"] == "music" and not cards:
                    tags = [str(row[key]) for key in ("artist", "album") if row.get(key)]
                    if row.get("duration"):
                        tags.append(self._time_label(float(row["duration"])))
                    title = row["title"] + ("\n" + " · ".join(tags) if tags else "")
                item = QListWidgetItem(self._card_title(row) if cards else title)
                item.setToolTip(title)
                item.setIcon(placeholder)
                if cards:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                    grid = self.results.gridSize()
                    item.setSizeHint(QSize(grid.width() - 4, grid.height() - 8))
                if row["kind"] == "music" and not cards:
                    item.setSizeHint(QSize(0, 62))
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                self.results.addItem(item)
            if self.rows:
                identifier = next(
                    (value for value in selected if any(row["id"] == value for row in self.rows)),
                    self.featured_id,
                )
                for index in range(self.results.count()):
                    item = self.results.item(index)
                    if item.data(Qt.ItemDataRole.UserRole) == identifier:
                        item.setSelected(True)
                if not self.selected_ids():
                    self.results.item(0).setSelected(True)
            else:
                self.detail_row = {}
                self.featured_id = ""
                self.hero.title.setText(self.tr("Your library"))
                self.hero.synopsis.clear()
                self.hero.metadata.clear()
                self.hero.set_picture(QImage())
            self._render_continue()
            self._load_artwork([*self.rows, *continuation, *self._home_row_items()])
            for name, combo in self.filters.items():
                current = combo.currentData()
                values = result.get("filters", {}).get(name, [])
                if name == "availability":
                    values = ["available", "unfinished", "unavailable"]
                with QSignalBlocker(combo):
                    combo.clear()
                    combo.addItem(self.filter_labels[name], "")
                    for value in values:
                        combo.addItem(str(value), str(value))
                    combo.setCurrentIndex(max(0, combo.findData(current)))
            self._set_notice("; ".join(str(error) for error in result.get("errors", [])))
            playlist_name = self.current_playlist or self.playlists.currentText()
            with QSignalBlocker(self.playlists):
                self.playlists.clear()
                for playlist in playlists:
                    self.playlists.addItem(playlist["name"], playlist)
                if playlists:
                    self.playlists.setCurrentIndex(max(0, self.playlists.findText(playlist_name)))
            self.empty.setVisible(not bool(self.rows))
            if not self.rows:
                self.empty.setText(
                    self.tr(
                        "No media matches this view. Add a Library Folder or Refresh folders "
                        "to discover local files, then adjust the search and filters."
                    )
                )
            self._update_panes()
        except Exception as error:
            self._set_notice(str(error))

    def _update_panes(self) -> None:
        chosen = bool(self.selected_ids())
        active = bool(self.last_source)
        if not active and self.fullscreen_dialog.isVisible():
            self.fullscreen_dialog.reject()
        video = self.kind.currentData() == "video"
        self.music_navigation.setVisible(not video)
        self.music_cover.setVisible(not video)
        self.music_metadata.setVisible(not video)
        self.view.hide()
        self.kind.hide()
        self.layout_combo.hide()
        self.layout_menu.menuAction().setVisible(video)
        for action in self.view_actions:
            action.setVisible(video)
        for name, button in self.category_cards.items():
            button.setVisible(
                name in {"all", "films", "series"}
                if video
                else name in {"albums", "artists", "tracks"}
            )
        self._arrange_toolbar()
        self.music_queue.setText(self.tr("Queue ({0})").format(len(self.state["queue"])))
        self.collection_title.setStyleSheet(
            "font-size: 30px; color: #f1f3ef; font-weight: 650;"
            if not video
            else "font-size: 20px; color: #f1f3ef; font-weight: 600;"
        )
        self.collection_selection.setStyleSheet(
            "QWidget#mediaSelection { background: qlineargradient("
            "x1:0,y1:0,x2:1,y2:1,stop:0 #284441,stop:1 #142321);"
            "border-radius: 10px; }"
            if not video
            else ""
        )
        collection = self.media_layout == "collection" or not video
        focus = self.media_layout == "focus" and video
        active_video = active and self.current_row.get("kind") == "video"
        self.hero.setVisible(not collection and bool(self.rows) and chosen and not active_video)
        self.collection_heading.setVisible(collection)
        self.collection_heading.setText(self.tr("Your collection") if video else self.tr("Music"))
        self.collection_selection.setVisible(collection and chosen)
        rows_home = bool(self.home_row_widgets) and self._home_active() and not active_video
        self.series_panel.setVisible(
            video
            and not active_video
            and bool(self.detail_row.get("series"))
            and bool(self.detail_row.get("episodes"))
            and bool(self.rows)
        )
        self.home_rows_panel.setVisible(rows_home)
        self.results.setVisible(not focus and bool(self.rows) and not rows_home)
        self.shelf_heading.setVisible(not focus and bool(self.rows) and not rows_home)
        self.shelf_heading.setText(
            self.tr("Recently added")
            if self.view.currentData() == "all"
            else self.view.currentText()
        )
        self.page_count.setVisible(bool(self.rows) and not rows_home)
        continuation = bool(self.continue_rows) and not collection
        self.continue_heading.setVisible(continuation)
        self.continue_panel.setVisible(continuation)
        for widget in self.detail_widgets:
            widget.setVisible(chosen)
        self.more_episodes.setVisible(chosen and bool(self.detail_row.get("episodes_has_more")))
        self.more_releases.setVisible(chosen and bool(self.detail_row.get("releases_has_more")))
        self.action_bar.setVisible(chosen)
        self.play_button.setVisible(bool(self.detail_row.get("available")))
        self.play_button.setEnabled(bool(self.detail_row.get("available")))
        self.enqueue_button.setEnabled(bool(self.detail_row.get("available")))
        self.preview_button.setVisible(
            chosen
            and self.detail_row.get("kind") == "video"
            and self.detail_row.get("availability") == "unfinished"
        )
        self.refresh_preview.setVisible(
            chosen and self.preview_item == self.detail_row.get("id") and bool(self.preview_id)
        )
        playing = (
            self.player is not None
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        # In Video, a music track keeps its bar only while it plays, so it can be paused.
        background_music = active and not active_video and video
        self.player_panel.setVisible(
            (active and not background_music)
            or (background_music and playing)
            or (not video and (bool(self.state["queue"]) or self.queue_disclosure.isChecked()))
        )
        self.video.setVisible(active_video)
        self._arrange_player()
        self._render_caption()
        for widget in self.playback_widgets:
            widget.setVisible(
                active
                and widget not in {self.shuffle, self.repeat, self.audio_tracks, self.subtitles}
            )
        self.fullscreen_button.setVisible(active_video)
        for widget in self.queue_widgets:
            widget.setVisible(bool(self.state["queue"]) or self.kind.currentData() == "music")

    def selected_ids(self) -> list[str]:
        if self.row_choice and self.home_rows_panel.isVisibleTo(self):
            return [self.row_choice]
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.results.selectedItems()]

    def _home_active(self) -> bool:
        return (
            self.kind.currentData() == "video"
            and self.view.currentData() in {"all", "films", "series", "anime", "adult"}
            and not self.grid_mode
            and self.media_layout == "cinematic"
            and not self.search.text().strip()
            and not any(combo.currentData() for combo in self.filters.values())
        )

    def _home_row_items(self) -> list[dict[str, Any]]:
        if not self.home_data:
            return []
        return [item for row in self.home_data["rows"] for item in row["rows"]]

    def _render_home_rows(self) -> None:
        for row_widget in self.home_row_widgets:
            row_widget.deleteLater()
        self.home_row_widgets = []
        titles = {
            "recent": self.tr("Recently added"),
            "series": self.tr("Series"),
            "oav": self.tr("OAV"),
            "films": self.tr("Films"),
            "rated": self.tr("Highly rated"),
            "unwatched": self.tr("Not watched yet"),
        }
        placeholder = self._placeholder_icon("video")
        known = {item["id"] for item in self._home_row_items()}
        if self.row_choice not in known:
            self.row_choice = ""
        for row in (self.home_data or {}).get("rows", []):
            if row["key"] == "continue":
                continue  # Continue watching already has its own band
            title = row["title"] if row["key"] == "genre" else titles.get(row["key"], "")
            row_widget = MediaRow(title, row["total"])
            row_widget.set_rows(
                row["rows"],
                self._card_title,
                lambda item: (
                    self._cover_icon(self.picture_cache[item["id"]])
                    if item["id"] in self.picture_cache
                    else placeholder
                ),
            )
            row_widget.chosen.connect(self._choose_row_card)
            row_widget.activated.connect(self._play_row_card)
            row_widget.seeAll.connect(lambda filters=row["filters"]: self._see_all(filters))
            self.home_rows_box.addWidget(row_widget)
            self.home_row_widgets.append(row_widget)
        self._update_panes()

    def _choose_row_card(self, identifier: str) -> None:
        self.row_choice = identifier
        chooser = self.sender()
        for row_widget in self.home_row_widgets:
            if row_widget is not chooser:
                row_widget.clear_choice()
        self.show_detail()

    def _play_row_card(self, identifier: str) -> None:
        self._choose_row_card(identifier)
        self.play_selected()

    def _see_all(self, filters: dict[str, str]) -> None:
        """Open the full grid for a row, with that row's filters."""
        self.row_choice = ""
        self.grid_mode = True
        genre = self.filters.get("genre")
        if genre is not None and filters.get("genre"):
            with QSignalBlocker(genre):
                if genre.findData(filters["genre"]) < 0:
                    genre.addItem(filters["genre"], filters["genre"])
                genre.setCurrentIndex(genre.findData(filters["genre"]))
        self.anime_filters = (
            {key: filters[key] for key in ("view", "oav") if key in filters}
            if filters.get("anime")
            else {}
        )
        view = (
            "adult"
            if filters.get("adult")
            else "anime"
            if filters.get("anime")
            else filters.get("view", "all")
        )
        index = max(0, self.view.findData(view))
        if index == self.view.currentIndex():
            self.refresh()
        self.view.setCurrentIndex(index)

    def _browse(self, view: str) -> None:
        """A browse tab returns to its rows, so it clears the filters a row's See all set."""
        self.grid_mode = False
        self.anime_filters = {}
        for combo in self.filters.values():
            with QSignalBlocker(combo):
                combo.setCurrentIndex(0)
        if self.view.currentData() == view:
            self.refresh()
        self.view.setCurrentIndex(self.view.findData(view))

    def _play_episode(self, identifier: str) -> None:
        """Play from this episode on, in series order."""
        ids = [episode["id"] for episode in self.series_panel.episodes]
        self.command("play", media_ids=ids, index=ids.index(identifier) if identifier in ids else 0)

    def show_detail(self) -> None:
        ids = self.selected_ids()
        if not ids or self.library is None:
            self._update_panes()
            return
        try:
            row = self.library.detail(self.session_client, ids[0])
            self.detail_row = row
            self._show_feature(row)
            info = [row["title"]]
            if row.get("identity_source") == "filename":
                info.append(self.tr("Title and release details guessed from filename"))
            if row.get("original_title") and row["original_title"] != row["title"]:
                info.append(self.tr("Original title: {0}").format(row["original_title"]))
            for name in ("year", "genre", "language", "description", "reason"):
                if row.get(name):
                    info.append(str(row[name]))
            for name, label in (
                ("director", self.tr("Directed by {0}")),
                ("actors", self.tr("With {0}")),
            ):
                if row.get(name):
                    info.append(label.format(row[name]))
            if row.get("season") is not None or row.get("episode") is not None:
                info.append(
                    self.tr("Filename metadata: season {0}, episode {1}").format(
                        row.get("season", "?"), row.get("episode", "?")
                    )
                )
            if row["kind"] == "video":
                labels = [str(track["label"]) for track in row.get("subtitles", [])]
                info.append(
                    self.tr("External subtitles: {0}").format(", ".join(labels))
                    if labels
                    else self.tr("No known external subtitles.")
                )
                info.append(self.tr("Embedded subtitle tracks are discovered during playback."))
            self.description.setText("\n".join(info))
            self.watched.setChecked(bool(row.get("watched")))
            if row["kind"] == "video" and row.get("series") and row.get("episodes"):
                self.series_panel.title.setText(row["series"])
                picture = self.picture_cache.get(row["id"])
                still = (
                    self._cover_icon(picture, QSize(216, 122))
                    if picture is not None
                    else self._placeholder_icon("video")
                )
                self.series_panel.set_episodes(
                    row["episodes"], self._time_label, row.get("season"), lambda _episode: still
                )
            for combo, name in ((self.releases, "releases"), (self.episodes, "episodes")):
                combo.clear()
                combo.addItem(
                    self.tr("Choose releases")
                    if name == "releases"
                    else self.tr("Choose episodes"),
                    "",
                )
                for entry in row.get(name, []):
                    combo.addItem(entry.get("release") or entry["title"], entry["id"])
            self.artwork.clear()
            self.preview_button.setVisible(
                row["kind"] == "video" and row.get("availability") == "unfinished"
            )
            self.refresh_preview.setVisible(
                self.preview_item == row["id"] and bool(self.preview_id)
            )
            self._load_artwork([row], detail=True)
            self._update_panes()

        except Exception as error:
            self._set_notice(str(error))

    def _more_detail(self, name: str) -> None:
        ids = self.selected_ids()
        offset = self.detail_row.get(name + "_next_offset")
        if not ids or offset is None:
            return
        library, client, identifier = self.library, self.session_client, ids[0]
        button = self.more_episodes if name == "episodes" else self.more_releases
        button.setEnabled(False)

        def work():
            return library.detail(client, identifier, **{name + "_offset": offset})

        def done(row):
            if not isValid(self) or ids != self.selected_ids():
                return
            button.setEnabled(True)
            combo = self.episodes if name == "episodes" else self.releases
            for entry in row.get(name, []):
                combo.addItem(entry.get("release") or entry["title"], entry["id"])
            self.detail_row[name + "_next_offset"] = row.get(name + "_next_offset")
            self.detail_row[name + "_has_more"] = row.get(name + "_has_more")
            self._update_panes()

        def failed(error):
            if isValid(self):
                button.setEnabled(True)
                self._set_notice(str(error))

        run_in_background(work, done, failed)

    def _cache_picture(self, identifier: str, picture: QImage) -> QImage:
        previous = self.picture_cache.pop(identifier, None)
        if previous is not None:
            self._picture_cache_bytes -= previous.sizeInBytes()
            if previous.width() * previous.height() >= picture.width() * picture.height():
                picture = previous
        size = picture.sizeInBytes()
        if size <= self.PICTURE_CACHE_LIMIT:
            self.picture_cache[identifier] = picture
            self._picture_cache_bytes += size
        while self._picture_cache_bytes > self.PICTURE_CACHE_LIMIT:
            _, evicted = self.picture_cache.popitem(last=False)
            self._picture_cache_bytes -= evicted.sizeInBytes()
        # Displayed QImages and QPixmaps own their shared pixels after cache eviction.
        return picture

    def _load_artwork(self, rows: list[dict[str, Any]], *, detail: bool = False) -> None:
        if not detail:
            self.art_stop.set()
            self.art_stop = threading.Event()
            self.art_generation += 1
        generation, stop = self.art_generation, self.art_stop
        library, client = self.library, self.session_client
        selected = self.selected_ids()

        def work():
            images = []
            for row in rows:
                if stop.is_set():
                    break
                if not row.get("artwork_url"):
                    continue
                try:
                    path = library.artwork(client, row["id"])
                    if not path:
                        continue
                    reader = QImageReader(str(path))
                    dimensions = reader.size()
                    if dimensions.width() * dimensions.height() > 32_000_000:
                        continue
                    reader.setScaledSize(
                        dimensions.scaled(
                            1600 if detail else 256,
                            900 if detail else 340,
                            Qt.AspectRatioMode.KeepAspectRatio,
                        )
                    )
                    picture = reader.read()
                    if not picture.isNull():
                        images.append((row["id"], picture))
                except (OSError, ValueError):
                    continue
            return images

        def done(images):
            if not isValid(self) or generation != self.art_generation or stop.is_set():
                return
            for identifier, picture in images:
                cached = self._cache_picture(identifier, picture)
                if identifier == self.featured_id:
                    self.hero.set_picture(cached)
                    if self.kind.currentData() == "music":
                        self.music_cover.setPixmap(
                            self._cover_icon(cached, QSize(160, 160)).pixmap(160, 160)
                        )
                if detail:
                    if selected == self.selected_ids():
                        self.artwork.setPixmap(
                            QPixmap.fromImage(picture).scaled(
                                160,
                                160,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                else:
                    for index in range(self.results.count()):
                        item = self.results.item(index)
                        if item.data(Qt.ItemDataRole.UserRole) == identifier:
                            item.setIcon(self._cover_icon(picture))
                            break
                    for row_widget in self.home_row_widgets:
                        row_widget.set_icon(identifier, self._cover_icon(picture))
            self._refresh_focus_strip()
            self._render_continue()

        run_in_background(work, done, lambda _error: None)

    def start_preview(self) -> None:
        ids = self._chosen_ids()
        if not ids:
            return
        identifier = ids[0]
        self.preview_generation += 1
        generation = self.preview_generation
        library, client, session_id = self.library, self.session_client, self.session_id
        self.preview_button.setEnabled(False)
        self.refresh_preview.setEnabled(False)
        self._set_notice(self.tr("Checking downloaded pieces with qBittorrent…"))

        def work():
            preview = library.create_preview(client, identifier)
            try:
                path, _prefix = library.preview_source(client, preview["preview_id"])
                return preview, path, library.preview_map(client, preview["preview_id"])
            except Exception:
                library.close_preview(client, preview["preview_id"])
                raise

        def apply_preview(result):
            preview, path, (size, piece_size, pieces) = result
            if (
                not isValid(self)
                or generation != self.preview_generation
                or self.library is not library
                or self.session_client != client
                or self.session_id != session_id
            ):
                library.close_preview(client, preview["preview_id"])
                return
            self._close_preview()
            self.preview_id = preview["preview_id"]
            self.preview_item = identifier
            self.preview_device = DownloadingFileDevice(path, size, piece_size, pieces, self)
            self.preview_checked = time.monotonic()
            self.last_source = identifier
            self.current_row = library.detail(client, identifier)
            self.subtitle_cues = []
            self.caption.clear()
            self.state.update(current_id=identifier, queue=[identifier], index=0)
            self.pending_seek = None
            self._prepare_track_source()
            self.player.setSourceDevice(self.preview_device, QUrl("verified-preview.mp4"))
            self.now_playing.setText(
                self.tr("Preview of downloaded portion · {0}% verified").format(
                    round(100 * preview["progress"])
                )
            )
            self._set_notice(
                self.tr(
                    "Playing while it downloads: playback waits for the next pieces "
                    "when it catches up. Some formats need the missing end before they "
                    "can play."
                )
            )
            self.video.show()
            self.external.hide()
            self.preview_button.setEnabled(True)
            self.refresh_preview.setEnabled(True)
            self.refresh_preview.show()
            self._render_queue()
            self.player.play()
            self.report()

        def ready(result):
            try:
                apply_preview(result)
            except Exception as error:
                library.close_preview(client, result[0]["preview_id"])
                self._close_preview()
                failed(error)

        def failed(error):
            if isValid(self) and generation == self.preview_generation:
                self._set_notice(str(error))
                self.preview_button.setEnabled(True)
                self.refresh_preview.setEnabled(True)

        run_in_background(work, ready, failed)

    def _invalidate_preview_request(self) -> None:
        self.preview_generation += 1
        self.preview_button.setEnabled(True)
        self.refresh_preview.setEnabled(True)

    def _close_preview(self) -> None:
        if self.preview_device is not None:
            self.preview_device.abort()  # end a read waiting for pieces before stopping
            self.player.setSource(QUrl())
            self.preview_device.close()
            self.preview_device.deleteLater()
            self.preview_device = None
        if self.preview_id and self.library:
            self.library.close_preview(self.session_client, self.preview_id)
        self.preview_id = ""
        self.preview_item = ""
        self.refresh_preview.hide()

    def _check_preview(self) -> None:
        if self.preview_check_pending or time.monotonic() - self.preview_checked < 2:
            return
        preview_id, library, client = self.preview_id, self.library, self.session_client
        device = self.preview_device
        self.preview_check_pending = True
        self.preview_checked = time.monotonic()

        def done(result):
            if isValid(self):
                self.preview_check_pending = False
                if device is not None and device is self.preview_device:
                    device.update(result[2])
                    self.now_playing.setText(
                        self.tr("Preview of downloaded portion · {0}% verified").format(
                            round(100 * sum(result[2]) / max(1, len(result[2])))
                        )
                    )

        def failed(error):
            if isValid(self):
                self.preview_check_pending = False
                if self.preview_id == preview_id:
                    self._close_preview()
                    self.state["current_id"] = ""
                    self.last_source = ""
                    self._set_notice(str(error))

        run_in_background(lambda: library.preview_map(client, preview_id), done, failed)

    def _chosen_ids(self) -> list[str]:
        for combo in (self.episodes, self.releases):
            if combo.currentData():
                return [combo.currentData()]
        selected = self.selected_ids()
        view = self.view.currentData()
        if self.kind.currentData() != "music" or view not in {"albums", "artists"}:
            return selected
        ids = []
        for row in self.rows:
            if row["id"] not in selected:
                continue
            filters = (
                {"album_id": row["album_id"]}
                if view == "albums" and row.get("album_id")
                else {"artist": row["artist"]}
                if view == "artists" and row.get("artist")
                else {}
            )
            if not filters:
                ids.append(row["id"])
                continue
            offset = 0
            while len(ids) < 1000:
                page = self.library.listing(
                    self.session_client,
                    kind="music",
                    view="tracks",
                    offset=offset,
                    limit=200,
                    **filters,
                )
                ids.extend(entry["id"] for entry in page["rows"])
                if not page.get("has_more"):
                    break
                offset = page["next_offset"]
        return list(dict.fromkeys(ids))[:1000]

    def play_selected(self) -> None:
        try:
            ids = self._chosen_ids()
            if ids:
                self.command("play", media_ids=ids, index=0)
        except Exception as error:
            self._set_notice(str(error))

    def enqueue_selected(self) -> None:
        try:
            ids = self._chosen_ids()
            if ids:
                self.queue_disclosure.setChecked(True)
                self.command(
                    "queue", media_ids=[*self.state["queue"], *ids], index=self.state["index"]
                )
        except Exception as error:
            self._set_notice(str(error))

    def toggle_pause(self) -> None:
        self.command(
            "pause"
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            else "play"
        )

    def command(self, action: str, **values: Any) -> None:
        if self.library is None:
            return
        try:
            if action in {"queue", "pause", "next", "previous"} or (
                action == "play" and (not self.preview_id or "media_ids" in values)
            ):
                self._invalidate_preview_request()
            result = self.library.session(self.session_id, self.token, action=action, **values)
            self.apply_player_commands(result.get("commands", []))
            self.report()
        except Exception as error:
            self._set_notice(str(error))

    def apply_player_commands(self, commands: list[dict[str, Any]]) -> None:
        """Apply sequenced commands from the attached authenticated player session."""
        for command in commands:
            sequence = int(command["sequence"])
            if sequence <= self.command_ack:
                continue
            action = command["action"]
            scoped_resume = (
                action == "play"
                and "media_ids" not in command
                and ("source_token" in command or "media_id" in command)
            )
            if scoped_resume:
                error = self._track_command_source_error(command)
                if error:
                    self.track_result = {"sequence": sequence, "applied": False, "error": error}
                    self.command_ack = sequence
                    continue
            if action in {"queue", "pause", "next", "previous"} or (
                action == "play" and (not self.preview_id or "media_ids" in command)
            ):
                self._invalidate_preview_request()
            if action == "select_track":
                self._apply_track_command(command)
                self.command_ack = sequence
                continue
            if action == "play" and self.preview_id and "media_ids" not in command:
                self.player.pause() if command.get("start_paused") else self.player.play()
                if scoped_resume:
                    self._track_resume_result(sequence)
                self.command_ack = sequence
                continue
            if action in {"play", "queue"}:
                was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                if "media_ids" in command:
                    self.state["queue"] = command["media_ids"]
                    self.state["index"] = command.get("index", 0)
                start_paused = bool(command.get("start_paused")) and action == "play"
                if start_paused:
                    self.player.pause()
                self._load_current(
                    play=(action == "play" or was_playing) and not start_paused,
                    load_token=str(command.get("load_token") or ""),
                )
                if action == "play":
                    self.player.pause() if start_paused else self.player.play()
            elif action == "pause":
                self.player.pause()
            elif action == "seek":
                self.player.setPosition(int(float(command["position"]) * 1000))
            elif action == "volume":
                self.audio.setVolume(float(command["volume"]))
                self.volume.setValue(round(float(command["volume"]) * 100))
            elif action in {"next", "previous"}:
                self._advance(1 if action == "next" else -1)
            elif action == "shuffle":
                self.state["shuffle"] = bool(command["shuffle"])
                with QSignalBlocker(self.shuffle):
                    self.shuffle.setChecked(self.state["shuffle"])
            elif action == "repeat":
                self.state["repeat"] = command["repeat"]
                with QSignalBlocker(self.repeat):
                    self.repeat.setCurrentIndex(max(0, self.repeat.findData(command["repeat"])))
            if scoped_resume:
                self._track_resume_result(sequence)
            self.command_ack = sequence

    def _load_current(self, play: bool, load_token: str = "") -> None:
        queue = self.state["queue"]
        if not queue:
            self._clear_track_source()
            self._close_preview()
            self.player.stop()
            self.player.setSource(QUrl())
            self.state.update(current_id="", index=0)
            self.last_source = ""
            self.queue.clear()
            self.now_playing.setText(self.tr("Nothing playing"))
            self._update_panes()
            return
        index = max(0, min(int(self.state["index"]), len(queue) - 1))
        self.state["index"] = index
        identifier = queue[index]
        if identifier != self.last_source or self.preview_id or load_token:
            self._invalidate_preview_request()
            path = self.library.resolve(self.session_client, identifier)
            row = self.library.detail(self.session_client, identifier)
            self._close_preview()
            self.last_source = identifier
            self.current_row = row
            self.subtitle_cues = []
            self.caption.clear()
            self.state["current_id"] = identifier
            self.pending_seek = round(float(row.get("position") or 0) * 1000)
            self.external.hide()
            self.now_playing.setText(row["title"])
            self._prepare_track_source(load_token)
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            if self.player.mediaStatus() in {
                QMediaPlayer.MediaStatus.LoadedMedia,
                QMediaPlayer.MediaStatus.BufferedMedia,
            }:
                self._playback_tracks()
            self.video.setVisible(row["kind"] == "video")
        if not self.track_source_token:
            self._prepare_track_source(load_token)
            self._playback_tracks()
        if play:
            self.player.play()
        self._render_queue()

    def _render_queue(self) -> None:
        self.queue.clear()
        for media_id in self.state["queue"]:
            try:
                title = self.library.detail(self.session_client, media_id)["title"]
            except Exception:
                title = self.tr("Unavailable media")
            self.queue.addItem(title)
        self.queue.setCurrentRow(int(self.state["index"]))
        self._update_panes()

    def _advance(self, step: int) -> None:
        queue = self.state["queue"]
        if not queue:
            return
        index = int(self.state["index"]) + step
        if self.state["shuffle"] and len(queue) > 1:
            index = random.choice([i for i in range(len(queue)) if i != self.state["index"]])
        if index >= len(queue) or index < 0:
            if self.state["repeat"] != "all":
                self.player.pause()
                return
            index %= len(queue)
        self.state["index"] = index
        self._load_current(play=True)

    def _queue_play(self, item: QListWidgetItem) -> None:
        self.command("play", media_ids=self.state["queue"], index=self.queue.row(item))

    def remove_from_queue(self) -> None:
        index = self.queue.currentRow()
        if index < 0:
            return
        queue = list(self.state["queue"])
        queue.pop(index)
        current_index = int(self.state["index"])
        if index < current_index:
            current_index -= 1
        self.command("queue", media_ids=queue, index=max(0, min(current_index, len(queue) - 1)))
        if not queue:
            self.player.stop()
            self.player.setSource(QUrl())
            self.last_source = ""
            self.state["current_id"] = ""
            self.queue.clear()

    def _save_playlist(self) -> None:
        if self.library is None or not self.state["queue"]:
            return
        name, ok = QInputDialog.getText(self, self.tr("Playlist"), self.tr("Name"))
        if ok and name.strip():
            try:
                self.library.save_playlist(self.session_client, name.strip(), self.state["queue"])
                self.current_playlist = name.strip()
                self.refresh()
            except Exception as error:
                self._set_notice(str(error))

    def _load_playlist(self) -> None:
        playlist = self.playlists.currentData()
        if playlist:
            self.current_playlist = playlist["name"]
            self.command("queue", media_ids=playlist["media_ids"], index=0)

    def _delete_playlist(self) -> None:
        playlist = self.playlists.currentData()
        if playlist:
            try:
                self.library.delete_playlist(self.session_client, playlist["id"])
                self.refresh()
            except Exception as error:
                self._set_notice(str(error))

    def _watched(self, watched: bool) -> None:
        ids = self.selected_ids()
        if ids and self.library:
            try:
                self.library.watched(self.session_client, ids[0], watched)
            except Exception as error:
                self._set_notice(str(error))

    def report(self) -> None:
        if not self.library:
            return
        try:
            if self.preview_id:
                self._check_preview()
            elif self.state["current_id"]:
                try:
                    self.library.resolve(self.session_client, self.state["current_id"])
                except (OSError, ValueError):
                    self.player.stop()
                    self.player.setSource(QUrl())
                    self.state["current_id"] = ""
                    self.last_source = ""
                    raise
            # Until the saved resume point is applied, the player reports 0; keep the saved one.
            position = self.player.position() if self.pending_seek is None else self.pending_seek
            self.state.update(
                position=position / 1000,
                duration=self.player.duration() / 1000,
                paused=self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState,
                volume=self.audio.volume(),
            )
            result = self.library.session(
                self.session_id,
                self.token,
                report={
                    **self.state,
                    "command_ack": self.command_ack,
                    "track_state": self._track_state(),
                    **({"track_result": self.track_result} if self.track_result else {}),
                },
                context=self._context(),
            )
            self.apply_player_commands(result.get("commands", []))
            request = result.get("state", {}).get("track_request", {})
            if request.get("status") == "failed":
                failure = (str(request.get("source_token") or ""), str(request.get("error") or ""))
                if failure != self.last_track_failure:
                    self.last_track_failure = failure
                    self._set_notice(failure[1])
        except Exception as error:
            self._set_notice(str(error))

    def _position_changed(self, position: int) -> None:
        self._render_caption()
        if not self.seek.isSliderDown():
            self.seek.setValue(position // 1000)
        self.elapsed.setText(
            f"{self._time_label(position / 1000)} / "
            f"{self._time_label(self.player.duration() / 1000)}"
        )

    def _duration_changed(self, duration: int) -> None:
        self.seek.setMaximum(duration // 1000)

    def _media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in {QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia}:
            self.tracks_ready = bool(self.track_source_token)
            if self.pending_seek is not None:
                self.player.setPosition(self.pending_seek)
                self.pending_seek = None
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.preview_id:
                self.player.pause()
                self._set_notice(
                    self.tr("End of downloaded portion. Refresh preview after more pieces arrive.")
                )
                return
            if self.state["repeat"] == "one":
                self.player.setPosition(0)
                self.player.play()
            else:
                self._advance(1)

    def _select_subtitle(self) -> bool:
        if self.player is None:
            return False
        value = self.subtitles.currentData()
        if value is None:
            return False
        self.subtitle_error = ""
        if isinstance(value, int):
            self.embedded_caption = ""
            self.subtitle_choice = value
            self.subtitle_cues = []
            self.caption.clear()
            self.player.setActiveSubtitleTrack(value)
            return self.player.activeSubtitleTrack() == value
        try:
            data, _mime = self.library.subtitle(self.session_client, self.last_source, value)
            text = data.decode("utf-8-sig", errors="replace").replace("\r", "")
            timing = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})")
            cues = []
            for block in re.split(r"\n\s*\n", text):
                lines = block.splitlines()
                for index, line in enumerate(lines):
                    if "-->" not in line:
                        continue
                    times = timing.findall(line)
                    if len(times) != 2:
                        continue
                    seconds = [
                        int(hour or 0) * 3600 + int(minute) * 60 + int(second) + int(ms) / 1000
                        for hour, minute, second, ms in times
                    ]
                    caption = re.sub(r"<[^>]*>", "", "\n".join(lines[index + 1 :]))
                    cues.append((seconds[0], seconds[1], caption))
            if not cues:
                raise ValueError(self.tr("Subtitle file has no readable timed cues."))
            self.subtitle_choice = value
            self.subtitle_cues = cues
            self.player.setActiveSubtitleTrack(-1)
            self._position_changed(self.player.position())
            self._update_panes()
            return True
        except Exception as error:
            self.subtitle_error = str(error)
            self._set_notice(str(error))
            with QSignalBlocker(self.subtitles):
                self.subtitles.setCurrentIndex(self.subtitles.findData(self.subtitle_choice))
            return False

    def _prepare_track_source(self, token: str = "") -> None:
        self.player_menu.close()
        self.track_source_token = token or str(uuid4())
        self.track_result = {}
        self.tracks_ready = False
        self._reset_track_choices()

    def _clear_track_source(self) -> None:
        self.track_source_token = ""
        self.track_result = {}
        self.tracks_ready = False

    def _track_source_changed(self) -> None:
        self._reset_track_choices()
        if self.player.source().isEmpty() and not self.preview_id:
            self._clear_track_source()

    @staticmethod
    def _track_language(metadata: QMediaMetaData) -> str:
        language = metadata.value(QMediaMetaData.Key.Language)
        if isinstance(language, QLocale.Language):
            if language in {QLocale.Language.AnyLanguage, QLocale.Language.C}:
                return ""
            return QLocale.languageToCode(language)
        return language if isinstance(language, str) else ""

    def _track_state(self) -> dict[str, Any]:
        ready = (
            self.tracks_ready
            and bool(self.track_source_token)
            and self.player is not None
            and self.player.error() == QMediaPlayer.Error.NoError
        )
        audio, subtitles = [], []
        if ready:
            for index, track in enumerate(self.player.audioTracks()[:100]):
                audio.append(
                    {
                        "id": f"audio:{index}",
                        "label": self._track_label(track, self.tr("Audio {0}").format(index + 1)),
                        "language": self._track_language(track),
                        "selected": self.player.activeAudioTrack() == index,
                    }
                )
            for index, track in enumerate(self.player.subtitleTracks()[:100]):
                subtitles.append(
                    {
                        "id": f"embedded:{index}",
                        "label": self._track_label(
                            track, self.tr("Embedded subtitle {0}").format(index + 1)
                        ),
                        "language": self._track_language(track),
                        "selected": self.player.activeSubtitleTrack() == index,
                    }
                )
            for track in self.current_row.get("subtitles", [])[: max(0, 100 - len(subtitles))]:
                subtitles.append(
                    {
                        "id": "external:" + track["id"],
                        "label": track["label"],
                        "language": str(track.get("language") or ""),
                        "selected": self.subtitle_choice == track["id"]
                        and self.player.activeSubtitleTrack() == -1,
                    }
                )
        for entry in audio + subtitles:
            entry["label"] = str(entry["label"])[:300]
            entry["language"] = str(entry["language"])[:300]
        return {
            "media_id": self.last_source,
            "source_token": self.track_source_token,
            "ready": ready,
            "audio_supported": ready and bool(audio),
            "subtitle_supported": ready,
            "audio": audio,
            "subtitles": subtitles[:100],
        }

    def _track_command_source_error(self, command: dict[str, Any]) -> str:
        if (
            not self.track_source_token
            or command.get("source_token") != self.track_source_token
            or command.get("media_id") != self.last_source
        ):
            return self.tr("Player source changed before track selection.")
        return ""

    def _track_resume_result(self, sequence: int) -> None:
        applied = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.track_result = {
            "sequence": sequence,
            "applied": applied,
            "error": "" if applied else self.tr("Player did not resume playback."),
        }
        if applied:
            self._clear_track_failure_notice()

    def _apply_track_command(self, command: dict[str, Any]) -> None:
        error = self._track_command_source_error(command)
        inventory = self._track_state()
        kind, identifier = command.get("kind"), str(command.get("track_id") or "")
        if not error and not inventory["ready"]:
            error = self.tr("Track metadata is not ready.")
        if not error:
            options = inventory["audio"] if kind == "audio" else inventory["subtitles"]
            supported = inventory.get(f"{kind}_supported", False)
            valid = any(track["id"] == identifier for track in options)
            if not supported or (not valid and not (kind == "subtitle" and identifier == "off")):
                error = self.tr("Requested track is unavailable.")
        if not error:
            if kind == "audio":
                index = int(identifier.removeprefix("audio:"))
                with QSignalBlocker(self.audio_tracks):
                    self.audio_tracks.setCurrentIndex(self.audio_tracks.findData(index))
                self._select_audio()
                applied = self.player.activeAudioTrack() == index
            else:
                value = (
                    -1
                    if identifier == "off"
                    else int(identifier.removeprefix("embedded:"))
                    if identifier.startswith("embedded:")
                    else identifier.removeprefix("external:")
                )
                with QSignalBlocker(self.subtitles):
                    self.subtitles.setCurrentIndex(self.subtitles.findData(value))
                applied = self._select_subtitle()
            if not applied:
                error = self.tr("Player did not apply the requested track.")
                if kind == "subtitle":
                    error = getattr(self, "subtitle_error", "") or error
        self.track_result = {
            "sequence": int(command["sequence"]),
            "applied": not bool(error),
            "error": error,
        }
        if not error:
            self._clear_track_failure_notice()

    def _clear_track_failure_notice(self) -> None:
        if self.last_track_failure and self.notice.text() == self.last_track_failure[1]:
            self._set_notice("")

    def _reset_track_choices(self) -> None:
        self.audio_choice = None
        self.subtitle_choice = -1
        self.embedded_caption = ""
        self.subtitle_cues = []
        self.caption.clear()
        with QSignalBlocker(self.audio_tracks), QSignalBlocker(self.subtitles):
            self.audio_tracks.clear()
            self.subtitles.clear()
            self.subtitles.addItem(self.tr("Subtitles off"), -1)

    def _track_label(self, metadata: QMediaMetaData, fallback: str) -> str:
        labels = [fallback]
        language = metadata.value(QMediaMetaData.Key.Language)
        if isinstance(language, QLocale.Language) and language not in {
            QLocale.Language.AnyLanguage,
            QLocale.Language.C,
        }:
            labels.append(QLocale.languageToString(language))
        elif isinstance(language, str) and language:
            labels.append(language)
        title = metadata.stringValue(QMediaMetaData.Key.Title)
        if title and title not in labels:
            labels.append(title)
        return " · ".join(labels)

    def _select_audio(self) -> None:
        choice = self.audio_tracks.currentData()
        if self.player is not None and isinstance(choice, int):
            self.audio_choice = choice
            self.player.setActiveAudioTrack(choice)

    def _playback_tracks(self) -> None:
        self.tracks_ready = bool(self.track_source_token) and bool(
            self.player.audioTracks() or self.player.subtitleTracks() or self.player.videoTracks()
        )
        audio = self.player.audioTracks()
        if audio:
            choice = self.audio_choice
            if choice is None or not 0 <= choice < len(audio):
                choice = max(0, self.player.activeAudioTrack())
            with QSignalBlocker(self.audio_tracks):
                self.audio_tracks.clear()
                for index, track in enumerate(audio):
                    self.audio_tracks.addItem(
                        self._track_label(track, self.tr("Audio {0}").format(index + 1)), index
                    )
                self.audio_tracks.setCurrentIndex(self.audio_tracks.findData(choice))
            self.audio_choice = choice
            if self.player.activeAudioTrack() != choice:
                self.player.setActiveAudioTrack(choice)
        with QSignalBlocker(self.subtitles):
            self.subtitles.clear()
            self.subtitles.addItem(self.tr("Subtitles off"), -1)
            for index, track in enumerate(self.player.subtitleTracks()[:100]):
                self.subtitles.addItem(
                    self._track_label(track, self.tr("Embedded subtitle {0}").format(index + 1)),
                    index,
                )
            for subtitle in self.current_row.get("subtitles", []):
                self.subtitles.addItem(subtitle["label"], subtitle["id"])
            self.subtitles.setCurrentIndex(max(0, self.subtitles.findData(self.subtitle_choice)))
        choice = self.subtitle_choice if isinstance(self.subtitle_choice, int) else -1
        if self.player.activeSubtitleTrack() != choice:
            self.player.setActiveSubtitleTrack(choice)

    def _codec_error(self, *_args: Any) -> None:
        if self.player.error() != QMediaPlayer.Error.NoError:
            self._set_notice(
                (
                    self.tr(
                        "Preview cannot play yet. "
                        "This format may need the missing end of the file. "
                        "Wait and refresh preview. "
                    )
                    if self.preview_id
                    else self.tr("Playback failed. This format or codec may be unsupported. ")
                )
                + self.player.errorString()
            )
            self.external.setVisible(not bool(self.preview_id))

    def open_external(self) -> None:
        if self.library and self.state["current_id"] and not self.preview_id:
            try:
                path = self.library.resolve(self.session_client, self.state["current_id"])
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            except Exception as error:
                self._set_notice(str(error))

    def _auto_scan(self) -> None:
        """Rescan quietly; the screen reloads only when the library changed."""
        if not self.isVisible() or self.library is None or self.video_playing:
            return
        if self.library.setup(self.session_client).settings.library_folders:
            self.start_scan(quiet=True)

    def start_scan(self, quiet: bool = False) -> None:
        if self.library is None or self.scan_stop is not None:
            return
        self.scan_quiet = quiet
        self.scan_stop = threading.Event()
        stop = self.scan_stop
        self.refresh_button.setEnabled(False)
        self.cancel_scan.setEnabled(True)
        self._scan_icon(True)
        if not quiet:
            self._set_notice(self.tr("Scanning Library Folders…"))
        run_in_background(
            lambda: self.library.scan(self.session_client, stop, self.scan_progress.emit),
            self._scan_done,
            self._scan_failed,
        )

    def _scan_progress(self, value: Any) -> None:
        if self.scan_quiet:
            return
        if isinstance(value, dict) and "film_details" in value:
            self._set_notice(
                self.tr("Fetching film details from c411… {0} / {1}").format(
                    value["film_details"], value.get("of", "?")
                )
            )
        elif isinstance(value, dict) and "items" in value:
            self._set_notice(self.tr("Scanning Library Folders… {0} files").format(value["items"]))

    def _scan_done(self, result: Any) -> None:
        if not isValid(self):
            return
        self.scan_stop = None
        self.refresh_button.setEnabled(True)
        self.cancel_scan.setEnabled(False)
        self._scan_icon(False)
        if not self.scan_quiet or (isinstance(result, dict) and result.get("changed")):
            self.refresh()

    def _toggle_scan(self) -> None:
        """The toolbar ⟳ refreshes the library; while it runs, the same button cancels."""
        if self.scan_stop is not None:
            self._cancel_media_scan()
        else:
            self.start_scan()
        self._scan_icon(self.scan_stop is not None)

    def _scan_icon(self, running: bool) -> None:
        with QSignalBlocker(self.refresh_icon):
            self.refresh_icon.setChecked(running)
        label = self.tr("Cancel library refresh") if running else self.tr("Refresh library")
        self.refresh_icon.setToolTip(label)
        self.refresh_icon.setAccessibleName(label)

    def _scan_failed(self, error: Exception) -> None:
        if not isValid(self):
            return
        quiet = self.scan_quiet
        self._scan_done(None)
        if not quiet:
            self._set_notice(str(error))

    def toggle_chat(self, checked: bool = True) -> None:
        if checked:
            self.open_chat()
        else:
            self.close_chat()

    def open_chat(self, conversation_id: str = "", *, new: bool = False) -> None:
        if self.library is None:
            self.chat.setChecked(False)
            return
        try:
            self.report()
            self.conversation_id = self.service.media_chat(
                self.session_id,
                self.token,
                conversation_id or ("" if new else self.conversation_id),
                new=new,
            )["conversation_id"]
            if self.credentials:
                self.credentials.setValue("conversation", self.conversation_id)
                self.credentials.sync()
            opening = self.assistant is None or self.assistant.isHidden()
            if self.assistant is None:
                from torrentlinker.gui.assistant import AssistantTab

                self.assistant = AssistantTab(self.get_service, compact=True)
                self.assistant.setMinimumWidth(CHAT_MIN_WIDTH)
                self.assistant.closeRequested.connect(self.close_chat)
                self.assistant.connectionsRequested.connect(self.connections_requested.emit)
                self.assistant.conversationRequested.connect(
                    lambda identifier: self.open_chat(identifier, new=not identifier)
                )
                self.splitter.addWidget(self.assistant)
                self.splitter.setChildrenCollapsible(False)
                self.splitter.splitterMoved.connect(self._remember_chat_width)
            if opening:
                # Also on the first opening after a restart, when the panel is new.
                self.assistant.show()
                self._restore_chat_width()
            self.chat.setChecked(True)
            self.assistant.activate()
            self.assistant.select_conversation(self.conversation_id)
            self.assistant.prompt.setFocus()
        except Exception as error:
            self.chat.setChecked(False)
            self._set_notice(str(error))

    def close_chat(self) -> None:
        if self.assistant is not None and self.assistant.isVisible():
            self._remember_chat_width()
            self.assistant.hide()
        self.chat.setChecked(False)

    def _restore_chat_width(self) -> None:
        total = sum(self.splitter.sizes()) or self.splitter.width()
        saved = self.credentials.value("chat_width", 0) if self.credentials else 0
        try:
            width = int(str(saved or 0))
        except (TypeError, ValueError):
            width = 0
        width = width or total * 38 // 100
        # Keep the remembered width, but always leave the media side its minimum.
        width = max(CHAT_MIN_WIDTH, min(width, total - MEDIA_MIN_WIDTH))
        self.splitter.setSizes([max(0, total - width), width])

    def _remember_chat_width(self, *_args: Any) -> None:
        if self.assistant is None or not self.assistant.isVisible() or not self.credentials:
            return
        self.credentials.setValue("chat_width", self.splitter.sizes()[-1])
        self.credentials.sync()

    def stop(self) -> None:
        if self.fullscreen_dialog.isVisible():
            self.fullscreen_dialog.reject()
        self._invalidate_preview_request()
        if self.player is None or not self.heartbeat.isActive():
            return
        if self.scan_stop:
            self.scan_stop.set()
        self.player.pause()
        self._clear_track_source()
        self.report()
        self.heartbeat.stop()
        self.auto_refresh.stop()
        self.player.stop()
        self._close_preview()
        self.art_stop.set()
