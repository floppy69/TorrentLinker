"""A system-aware palette and shared visual hierarchy, retaining native Qt controls."""

import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication, mode: str = "auto") -> None:
    app.setStyle("Fusion")
    if not app.findChild(ThemeFollower):
        ThemeFollower(app)
    set_theme(mode)


def set_theme(mode: str) -> None:
    app = QApplication.instance()
    follower = app.findChild(ThemeFollower) if app else None
    if follower:
        follower.mode = mode if mode in ("light", "dark") else "auto"
        follower.refresh()


def gnome_desktop() -> bool:
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    return sys.platform == "linux" and bool(set(desktops) & {"gnome", "unity", "budgie"})


def desktop_environment() -> dict[str, str]:
    """Host gsettings must not load the frozen app's bundled GLib/GIO libraries."""
    environment = os.environ.copy()
    if getattr(sys, "frozen", False):
        original = environment.get("LD_LIBRARY_PATH_ORIG")
        if original is None:
            environment.pop("LD_LIBRARY_PATH", None)
        else:
            environment["LD_LIBRARY_PATH"] = original
    return environment


class ThemeFollower(QObject):
    """GNOME's explicit preference can disagree with Qt's GTK platform plugin."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        self.mode = "auto"
        self.fallback = (
            Qt.ColorScheme.Dark
            if app.palette().window().color().lightness() < 128
            else Qt.ColorScheme.Light
        )
        self.preference = Qt.ColorScheme.Unknown
        self.monitor = QProcess(self)
        self.monitor.readyReadStandardOutput.connect(self._changed)
        app.aboutToQuit.connect(self.stop)
        app.styleHints().colorSchemeChanged.connect(self.refresh)
        if gnome_desktop():
            environment = desktop_environment()
            monitor_environment = QProcessEnvironment()
            for name, value in environment.items():
                monitor_environment.insert(name, value)
            self.monitor.setProcessEnvironment(monitor_environment)
            try:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                    check=False,
                    env=environment,
                )
                self.set_preference(result.stdout)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.monitor.start(
                "gsettings", ["monitor", "org.gnome.desktop.interface", "color-scheme"]
            )
        self.refresh()

    def _changed(self) -> None:
        while self.monitor.canReadLine():
            self.set_preference(bytes(self.monitor.readLine().data()).decode(errors="replace"))

    def set_preference(self, text: str) -> None:
        self.preference = (
            Qt.ColorScheme.Dark
            if "'prefer-dark'" in text
            else Qt.ColorScheme.Light
            if "'prefer-light'" in text
            else Qt.ColorScheme.Unknown
        )
        self.refresh()

    def refresh(self) -> None:
        scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(
            self.mode, self.preference
        )
        if scheme == Qt.ColorScheme.Unknown:
            scheme = self.app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Unknown:
            scheme = self.fallback
        _update_theme(self.app, scheme)

    def stop(self) -> None:
        self.monitor.terminate()
        self.monitor.waitForFinished(200)


@lru_cache(maxsize=2)
def _panel_colors(dark: bool) -> dict[str, str]:
    """Read the two literal palette blocks shared with the Web shell.

    This is deliberately not a general CSS parser. Layout rules and page-specific
    overrides are not part of the native palette.
    """
    source = (Path(__file__).parents[1] / "web/static/panel/base.css").read_text()
    blocks = dict(re.findall(r"(:root(?:\[data-theme=\"light\"\])?)\s*\{([^}]+)\}", source))
    declarations = blocks[":root"]
    if not dark:
        declarations += blocks[':root[data-theme="light"]']
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6});", declarations))


def _update_theme(app: QApplication, scheme: Qt.ColorScheme) -> None:
    dark = scheme == Qt.ColorScheme.Dark or (
        scheme == Qt.ColorScheme.Unknown and app.palette().window().color().lightness() < 128
    )
    colors = _panel_colors(dark)
    bg, panel, alt = (colors[name] for name in ("bg", "panel", "raised"))
    text, muted, border = (colors[name] for name in ("text", "muted", "line"))
    accent, hover = colors["accent"], colors["hover"]
    accent_text = colors["accent-text"]
    brand = accent
    error, warning, selection, ok = (
        colors[name] for name in ("danger", "warning", "tint", "success")
    )
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: bg,
        QPalette.ColorRole.WindowText: text,
        QPalette.ColorRole.Base: panel,
        QPalette.ColorRole.AlternateBase: alt,
        QPalette.ColorRole.Text: text,
        QPalette.ColorRole.Button: panel,
        QPalette.ColorRole.ButtonText: text,
        QPalette.ColorRole.Highlight: selection,
        QPalette.ColorRole.HighlightedText: text,
        QPalette.ColorRole.ToolTipBase: panel,
        QPalette.ColorRole.ToolTipText: text,
        QPalette.ColorRole.Link: colors["link"],
        QPalette.ColorRole.PlaceholderText: muted,
        QPalette.ColorRole.Mid: border,
        QPalette.ColorRole.Light: border,
        QPalette.ColorRole.Dark: border,
    }.items():
        palette.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(muted))
    app.setPalette(palette)
    app.setStyleSheet(f"""
        QMainWindow, QDialog {{ background: {bg}; }}
        QWidget {{ font-size: 13px; }}
        QLabel[role="heading"] {{ font-size: 25px; font-weight: 600; }}
        QLabel[role="brand"] {{ font-size: 18px; font-weight: 600; color: {brand}; }}
        QLabel[role="error"] {{ color: {error}; }}
        QLabel[role="warning"] {{ color: {warning}; }}
        QLabel[role="muted"] {{ color: {muted}; }}
        QFrame#sidebar {{ background: {panel}; border-right: 1px solid {border}; }}
        QListWidget#navigation {{ background: transparent; border: 0; outline: 0; }}
        QListWidget#navigation::item {{ padding: 13px 12px; margin: 3px 0; border-radius: 7px; }}
        QListWidget#navigation::item:selected {{ background: {selection}; color: {text};
            font-weight: 600; }}
        QListWidget#navigation::item:hover {{ background: {hover}; }}
        QFrame#zenBand {{ background: transparent; border: none; }}
        QFrame#catalogueCard {{ background: {panel}; border: 1px solid {border};
            border-radius: 10px; }}
        QFrame#catalogueCard[active="true"] {{ border: 1px solid {brand}; }}
        QFrame#catalogueCard QLabel {{ background: transparent; }}
        QLabel[role="cardTitle"] {{ font-size: 14px; font-weight: 600; }}
        QLabel[role="cardNumber"] {{ font-size: 20px; font-weight: 600; }}
        QLabel[role="gain"] {{ color: {ok}; font-weight: 600; }}
        QLabel[chip] {{ border-radius: 6px; padding: 1px 7px; border: 1px solid {border};
            color: {muted}; }}
        QLabel[chip="done"] {{ color: {ok}; border-color: {ok}; }}
        QLabel[chip="running"] {{ color: {brand}; border-color: {brand}; }}
        QLabel[chip="year"], QLabel[chip="prune"], QLabel[chip="paused"] {{
            color: {warning}; border-color: {warning}; }}
        QFrame#zenBand QLabel {{ background: transparent; }}
        QFrame#updateNotice {{ background: {panel}; border: 1px solid {warning};
            border-radius: 8px; }}
        QFrame#updateNotice QLabel {{ color: {warning}; background: transparent; }}
        QGroupBox {{ background: {panel}; border: 1px solid {border}; border-radius: 8px;
                     margin-top: 13px; padding: 14px 10px 10px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 5px;
            font-weight: 600; }}
        QTabWidget::pane {{ border: 0; padding-top: 10px; }}
        QTabBar::tab {{ padding: 10px 18px; border-bottom: 2px solid transparent; color: {muted}; }}
        QTabBar::tab:selected {{ border-bottom: 2px solid {accent}; color: {text};
            font-weight: 600; }}
        QTabBar::tab:hover {{ background: {hover}; }}
        QTabWidget#searchBrowser::pane {{ padding-top: 12px; }}
        QTabBar#searchBrowserBar::tab {{ background: {panel}; border: 1px solid {border};
            border-radius: 7px; margin-right: 5px; padding: 9px 12px;
            min-width: 160px; max-width: 250px; color: {muted}; }}
        QTabBar#searchBrowserBar::tab:selected {{ background: {selection};
            border: 1px solid {accent}; color: {text}; font-weight: 600; }}
        QTabBar#searchBrowserBar::tab:hover {{ background: {hover}; }}
        QPushButton, QToolButton {{ background: {panel}; border: 1px solid {border};
                                   border-radius: 6px; padding: 7px 12px; }}
        QPushButton:hover, QToolButton:hover {{ background: {hover}; border-color: {accent}; }}
        QPushButton:pressed, QToolButton:pressed {{ background: {selection}; }}
        QPushButton[primary="true"] {{ background: {accent}; color: {accent_text};
            border-color: {accent}; font-weight: 600; }}
        QPushButton:disabled, QToolButton:disabled {{ background: {alt}; color: {muted};
            border-color: {border}; }}
        QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus,
        QAbstractSpinBox:focus {{ border: 2px solid {accent}; }}
        /* Button roles (gui/controls.py). Secondary is the plain style above. */
        QPushButton[role="primary"], QToolButton[role="primary"] {{ background: {accent};
            color: {accent_text}; border-color: {accent}; font-weight: 600; }}
        QPushButton[role="quiet"], QToolButton[role="quiet"] {{ background: transparent;
            border-color: transparent; color: {muted}; padding: 7px 8px; }}
        QPushButton[role="quiet"]:hover, QToolButton[role="quiet"]:hover {{
            background: {hover}; border-color: transparent; color: {text}; }}
        QPushButton[role="icon"], QToolButton[role="icon"] {{ background: transparent;
            border: 1px solid transparent; border-radius: 6px; padding: 0; font-size: 16px;
            min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }}
        QPushButton[role="icon"]:hover, QToolButton[role="icon"]:hover {{
            background: {hover}; border-color: transparent; }}
        QPushButton[role="icon"]:checked, QToolButton[role="icon"]:checked {{
            background: {selection}; border-color: {accent}; }}
        QPushButton[role="icon"]:focus, QToolButton[role="icon"]:focus {{
            border: 1px solid {accent}; }}
        QToolButton[role="icon"]::menu-indicator {{ image: none; width: 0; }}
        QFrame#chatExample {{ background: {panel}; border: 1px solid {border};
            border-radius: 10px; }}
        QFrame#chatExample:hover, QFrame#chatExample:focus {{ border-color: {accent}; }}
        QFrame#chatExample QLabel {{ background: transparent; }}
        QPushButton[chip="prefer"] {{ border-color: {accent}; color: {accent}; }}
        QPushButton[chip="must"] {{ background: {accent}; border-color: {accent}; color: white; }}
        QPushButton[chip="avoid"] {{ border-color: {error}; color: {error}; }}
        /* Search page (gui/search_widgets.py, gui/search_filters.py, gui/pagination.py) */
        QFrame#searchBar {{ background: {panel}; border: 1px solid {border};
            border-radius: 12px; }}
        QFrame#searchBar:focus-within {{ border-color: {accent}; }}
        QFrame#searchBar QLineEdit {{ background: transparent; border: 0; font-size: 15px;
            padding: 8px 0; }}
        QFrame#searchBar QLineEdit:focus {{ border: 0; }}
        /* Torrent detail tab (gui/torrent_details.py) */
        QLabel#detailCrumb {{ color: {muted}; }}
        QLabel#detailTitle {{ font-size: 22px; font-weight: 600; }}
        QLabel#detailBadge {{ background: {selection}; border-radius: 6px; padding: 5px 12px;
            font-weight: 700; color: {accent}; }}
        QLabel#detailChip {{ background: {panel}; border: 1px solid {border}; border-radius: 8px;
            padding: 4px 10px; }}
        QLabel#detailChip[kind="up"] {{ color: {ok}; }}
        QLabel#detailChip[kind="down"] {{ color: {error}; }}
        QLabel#detailChip[kind="done"] {{ color: {accent}; }}
        QLabel#detailChip[kind="wanted"], QLabel#detailChip[kind="warning"],
        QLabel#detailChip[kind="untested"], QLabel#detailChip[kind="exclusive"] {{
            color: {warning}; border-color: {warning}; }}
        QLabel#detailChip[kind="tested"] {{ color: {ok}; border-color: {ok}; }}
        QLabel#detailChip[kind="id"] {{ font-family: monospace; color: {muted}; }}
        QFrame#detailBanner {{ background: {panel}; border: 1px solid {accent};
            border-radius: 10px; }}
        QFrame#detailBanner QLabel {{ background: transparent; }}
        QFrame#detailCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {panel}, stop:1 {selection}); border: 1px solid {accent}; border-radius: 10px; }}
        QFrame#detailTrust {{ background: {panel}; border: 1px solid {border};
            border-radius: 10px; }}
        QFrame#detailCard QLabel, QFrame#detailTrust QLabel {{ background: transparent; }}
        QFrame#detailCard QLabel#detailChip {{ background: {alt}; }}
        QLabel#detailCardTitle {{ font-size: 17px; font-weight: 600; }}
        QLabel#detailPoster {{ background: {alt}; border-radius: 6px; }}
        QFrame#detailBar {{ background: {panel}; border-top: 1px solid {border}; }}
        QFrame#detailBar QLabel {{ background: transparent; }}
        QFrame#resultsCard {{ background: {panel}; border: 1px solid {border};
            border-radius: 10px; }}
        QFrame#resultsCard QWidget {{ background: transparent; }}
        QFrame#resultsCard QTableWidget {{ background: transparent; border: 0;
            border-top: 1px solid {border}; border-radius: 0; }}
        QLabel#resultsTitle {{ font-size: 16px; font-weight: 600; }}
        QFrame#selectionBar {{ background: {panel}; border: 1px solid {border};
            border-radius: 10px; }}
        QPushButton[chip="pill"] {{ border-radius: 15px; padding: 6px 14px; }}
        QPushButton[chip="pill"]:checked {{ background: {selection}; border-color: {accent};
            color: {text}; font-weight: 600; }}
        QToolButton[chip="filter"], QPushButton[chip="filter"], QComboBox[chip="filter"],
        QLineEdit[chip="filter"] {{ border-radius: 15px; padding: 5px 12px; min-height: 18px; }}
        QPushButton[chip="filter"]:checked, QToolButton[chip="filter"][active="true"] {{
            background: {selection}; border-color: {accent}; color: {text}; }}
        QComboBox[chip="filter"]::drop-down {{ border: 0; width: 22px; }}
        QPushButton[chip="sort"] {{ background: transparent; border: 1px solid transparent;
            border-radius: 6px; color: {muted}; padding: 4px 9px; }}
        QPushButton[chip="sort"]:hover {{ background: {hover}; color: {text}; }}
        QPushButton[chip="sort"]:checked {{ background: {selection}; border-color: {accent};
            color: {text}; }}
        QPushButton[chip="page"] {{ min-width: 18px; padding: 6px 10px; }}
        QPushButton[chip="page"]:checked {{ background: {accent}; border-color: {accent};
            color: {accent_text}; font-weight: 600; }}
        QFrame#choiceCard {{ background: {panel}; border: 1px solid {border};
            border-radius: 10px; }}
        QFrame#choiceCard:hover {{ border-color: {accent}; }}
        QFrame#choiceCard[selected="true"] {{ border: 2px solid {accent}; }}
        QFrame#choiceCard QLabel, QFrame#choiceCard QRadioButton {{ background: transparent; }}
        QFrame#automationCard {{ background: {panel}; border: 1px solid {border};
            border-radius: 10px; }}
        QFrame#automationCard QLabel {{ background: transparent; }}
        QLabel#automationName {{ font-size: 14px; font-weight: 600; }}
        QLabel#runHeading {{ color: {muted}; font-size: 12px; font-weight: 600;
            padding: 14px 0 2px; border-top: 1px solid {border}; }}
        QLabel#chatTitle {{ font-size: 15px; font-weight: 600; }}
        /* Chat composer (gui/chat_composer.py): one rounded field, chips under it. */
        QFrame#chatComposer {{ background: {panel}; border: 1px solid {border};
            border-radius: 14px; }}
        QFrame#chatComposer QPlainTextEdit {{ background: transparent; border: 0; padding: 4px 0; }}
        QToolButton#chatSend {{ background: {accent}; color: {accent_text}; border-radius: 15px; }}
        QToolButton#chatSend:hover {{ background: #0a958b; }}
        QToolButton#chatSend:disabled {{ background: {alt}; color: {muted}; }}
        QComboBox#chatModelChip {{ background: transparent; border: 1px solid transparent;
            border-radius: 6px; color: {muted}; padding: 4px 8px; }}
        QComboBox#chatModelChip:hover {{ background: {hover}; color: {text}; }}
        QComboBox#chatModelChip::drop-down {{ border: 0; width: 14px; }}
        QPushButton[role="tab"] {{ background: transparent; border: 0; border-radius: 0;
            border-bottom: 2px solid transparent; color: {muted}; padding: 6px 2px; }}
        QPushButton[role="tab"]:hover {{ color: {text}; background: transparent; }}
        QPushButton[role="tab"]:checked {{ color: {text}; border-bottom: 2px solid {accent};
            font-weight: 600; }}
        QToolButton#browserTabClose {{ background: transparent; border: 0;
            border-radius: 4px; padding: 0; color: {muted}; font-size: 18px; }}
        QToolButton#browserTabClose:hover {{ background: {bg}; color: {text}; }}
        QToolButton#browserTabClose:focus {{ border: 1px solid {accent}; }}
        QTabBar#searchBrowserBar::scroller {{ width: 64px; }}
        QTabBar#searchBrowserBar QToolButton#ScrollLeftButton,
        QTabBar#searchBrowserBar QToolButton#ScrollRightButton {{ padding: 0;
            border-radius: 5px; }}
        QToolButton#browserHome {{ margin-right: 6px; padding: 11px 18px; }}
        QToolButton#browserHome:checked {{ background: {selection}; border-color: {accent};
            font-weight: 600; }}
        QToolButton#browserTabList {{ margin-left: 6px; padding: 8px 16px 8px 10px; }}
        QFrame#estimateInfo {{ background: {panel}; border: 1px solid {border};
            border-radius: 7px; }}
        QFrame#estimateInfo QLabel {{ background: transparent; }}
        QPushButton#readingRoomButton:checked {{ background: {selection}; color: {text}; }}
        QToolButton#estimateToggle {{ background: transparent; border: 0; padding: 3px;
            color: {muted}; }}
        QToolButton#estimateToggle:hover {{ color: {text}; }}
        QToolButton#estimateToggle:focus {{ border: 1px solid {accent}; }}
        QLineEdit, QComboBox, QAbstractSpinBox {{ background: {panel}; border: 1px solid {border};
                                               border-radius: 6px; padding: 6px;
            min-height: 18px; }}
        QPlainTextEdit, QTextBrowser, QTableView, QTreeView {{ background: {panel};
            border: 1px solid {border}; border-radius: 7px; }}
        QHeaderView::section {{ background: {alt}; color: {muted}; border: 0;
                                border-bottom: 1px solid {border}; padding: 9px 8px;
            font-weight: 600; }}
        QTableView::item, QTreeView::item {{ padding: 5px; border: 0; }}
        QTableView::item:selected, QTreeView::item:selected {{
            background: {selection}; color: {text}; }}
        QToolBar {{ border: 0; spacing: 6px; background: transparent; padding: 0; }}
        QScrollArea {{ border: 0; background: transparent; }}
        QSplitter::handle, QWidget#paneGrip {{ background: {border}; }}
        QStatusBar {{ color: {muted}; border-top: 1px solid {border}; }}
        QProgressBar {{ border: 1px solid {border}; border-radius: 5px; background: {alt};
            text-align: center; }}
        QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
        QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 6px; }}
    """)
