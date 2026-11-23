"""Disposable pre-roll player; never writes feature progress or exposes an app bridge."""

import json

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class PrerollPlayer(QDialog):
    def __init__(self, library, plan, parent=None):
        super().__init__(parent)
        self.library = library
        self.steps = plan.get("steps", [])
        self.index = -1
        self.youtube = None
        self.setWindowTitle(self.tr("Before your film"))
        self.resize(960, 650)
        layout = QVBoxLayout(self)
        self.title = QLabel(self)
        layout.addWidget(self.title)
        self.video = QVideoWidget(self)
        layout.addWidget(self.video)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        self.player.mediaStatusChanged.connect(self.status)
        self.player.errorOccurred.connect(lambda *_: self.advance())
        actions = QHBoxLayout()
        for label, callback in [
            (self.tr("Play"), self.player.play),
            (self.tr("Skip clip"), self.advance),
            (self.tr("Skip all / start film"), self.accept),
        ]:
            button = QPushButton(label, self)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.finished.connect(self.cleanup)
        QTimer.singleShot(0, self.advance)

    def status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.advance()

    def cleanup(self, *_):
        self.timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        if self.youtube is not None:
            self.youtube.stop()
            self.youtube.setUrl(QUrl("about:blank"))
            self.youtube.deleteLater()
            self.youtube = None

    def advance(self):
        self.cleanup()
        self.index += 1
        if self.index >= len(self.steps):
            self.accept()
            return
        step = self.steps[self.index]
        self.title.setText(f"{self.index + 1} / {len(self.steps)} · {step['title']}")
        self.video.setVisible(step["kind"] == "clip")
        if step["kind"] == "pause":
            self.timer.start(round(step["seconds"] * 1000))
        elif step["kind"] == "clip":
            try:
                self.player.setSource(QUrl.fromLocalFile(str(self.library.file(step["clip"]))))
                self.player.play()
                self.timer.start(610_000)
            except ValueError:
                QTimer.singleShot(0, self.advance)
        elif step["kind"] == "youtube":
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
            from PySide6.QtWebEngineWidgets import QWebEngineView

            self.youtube = QWebEngineView(self)
            # Off-the-record profile, no WebChannel, no local-file URL.
            profile = QWebEngineProfile(self.youtube)
            page = QWebEnginePage(profile, self.youtube)
            self.youtube.setPage(page)
            self.layout().insertWidget(1, self.youtube)
            self.youtube.titleChanged.connect(
                lambda title: self.advance() if title == "tl-ended" else None
            )
            identifier = json.dumps(step["youtube"])
            self.youtube.setHtml(
                """<!doctype html><html>
<head><meta name="referrer" content="strict-origin-when-cross-origin"></head>
<body style="margin:0;background:black">
<div id="player"></div>
<script src="https://www.youtube.com/iframe_api"></script>
<script>function onYouTubeIframeAPIReady(){
new YT.Player('player',{width:'100%',height:540,
host:'https://www.youtube-nocookie.com',videoId:"""
                + identifier
                + """,playerVars:{autoplay:1,origin:'https://torrentlinker.fr'},events:{onStateChange:function(e){if(e.data===0)document.title='tl-ended'},onError:function(){document.title='tl-ended'}}})}</script></body></html>""",
                QUrl("https://torrentlinker.fr/"),
            )
            self.timer.start(610_000)


def preview(setup, identifier, parent):
    from torrentlinker.prerolls import prerolls

    library = prerolls(setup)
    clip = library.clip(identifier)
    dialog = PrerollPlayer(
        library,
        {
            "steps": [
                {
                    "kind": "youtube" if clip.source == "youtube" else "clip",
                    "clip": clip.id,
                    "title": clip.title,
                    "youtube": clip.youtube,
                }
            ]
        },
        parent,
    )
    dialog.exec()
    dialog.deleteLater()
