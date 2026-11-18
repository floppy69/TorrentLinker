"""Render src/torrentlinker/assets/logo.svg into the 256 px icon.png the app and packages use."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication(sys.argv)
assets = Path(__file__).parent.parent / "src" / "torrentlinker" / "assets"
size = 256
img = QImage(size, size, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
QSvgRenderer(str(assets / "logo.svg")).render(p)
p.end()
out = assets / "icon.png"
img.save(str(out))
print(out)
