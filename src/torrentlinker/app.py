from __future__ import annotations

import multiprocessing
import os
import sys
from collections.abc import MutableMapping
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from torrentlinker import i18n
from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.gui.theme import apply_theme
from torrentlinker.store import Store
from torrentlinker.updates import CHECK_INTERVAL, installed_version


def data_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))


def smoke_checks() -> None:
    """Exercise what a broken bundle would miss: guessit data, translations, assets, and
    the SOCKS support imported only once a SOCKS proxy is set."""
    import httpx
    from packaging.version import Version

    from torrentlinker import documentation
    from torrentlinker.domain import LocalItem
    from torrentlinker.queries import parse_name

    httpx.Client(proxy="socks5://127.0.0.1:1080").close()  # needs socksio
    import socks  # noqa: F401 - requests' SOCKS support, for qBittorrent's adapter
    import sockshandler  # noqa: F401

    info = parse_name(LocalItem(Path("Amelie.2001.1080p.mkv"), {"Amelie.2001.1080p.mkv": 1}))
    assert info.get("title") == "Amelie" and info.get("year") == 2001, info
    assert (Path(i18n.__file__).parent / "torrentlinker_fr.qm").exists()
    assert (Path(__file__).parent / "assets" / "icon.png").exists()
    # Installed package metadata follows PEP 440, including normalized beta labels.
    # Stable update-channel filtering is a separate concern.
    Version(installed_version())
    for language in ("fr", "en"):
        for guide in documentation.guides(language):
            assert documentation.document_path(guide["path"]).read_text(encoding="utf-8")
    assert documentation.document_path("guide/images/zen.png").is_file()
    assert documentation.document_path("guide/images/en/zen.png").is_file()
    from torrentlinker.library_smoke import library_smoke_checks
    from torrentlinker.webview_smoke import webview_smoke_checks

    webview_smoke_checks()
    media_smoke_checks()
    library_smoke_checks()
    agent_smoke_checks()
    print("smoke test OK")


def media_smoke_checks() -> None:
    """Decode local audio and exercise cleanup with the actual bundled Qt plugins."""
    import tempfile
    import time
    import wave

    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QUrl
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import QPushButton, QWidget

    from torrentlinker.gui.media_audio import create_audio_output

    with tempfile.TemporaryDirectory(prefix="torrentlinker-media-smoke-") as folder:
        path = Path(folder) / "silence.wav"
        with wave.open(str(path), "wb") as track:
            track.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            track.writeframes(b"\0\0" * 22050 * 2)
        for _ in range(8):
            parent = QWidget()
            player = QMediaPlayer(parent)
            try:
                output = create_audio_output(parent)
                output.setMuted(True)
                player.setAudioOutput(output)
                player.setSource(QUrl.fromLocalFile(str(path)))
                player.play()
                deadline = time.monotonic() + 5
                while player.position() == 0 and time.monotonic() < deadline:
                    loop = QEventLoop()
                    QTimer.singleShot(10, loop.quit)
                    loop.exec()
                if player.position() == 0:
                    raise RuntimeError(
                        f"Bundled audio playback did not advance: {player.errorString()}"
                    )
                player.stop()
                for _ in range(200):
                    QPushButton("Playback cleanup check", parent)
            finally:
                player.stop()
                player.setSource(QUrl())
                parent.deleteLater()
                QCoreApplication.sendPostedEvents(parent, QEvent.Type.DeferredDelete)
    print("native media playback smoke test OK")


def agent_smoke_checks() -> None:
    """Start the bundled desktop MCP transport, including in Windows windowed builds."""
    import tempfile
    import time

    import httpx

    from torrentlinker.agent.access import Grant
    from torrentlinker.agent.desktop import DesktopServer

    with tempfile.TemporaryDirectory(prefix="torrentlinker-mcp-smoke-") as folder:
        directory = Path(folder)
        store = Store(directory / "state.db")
        runtime = DesktopServer(Settings(), directory / "settings.json", store, port=0)
        try:
            runtime.start()
            from torrentlinker.diagnostics import build_report

            report = build_report(runtime.setup.settings, store, runtime.service.jobs)
            assert report["runtime"]["app_version"] == installed_version()
            assert report["runtime"]["pyside"] != "unavailable", "Bundled PySide metadata missing"
            with httpx.Client(
                base_url=runtime.url.removesuffix("/mcp/"), trust_env=False
            ) as client:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        if client.get("/healthz", timeout=0.2).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    raise RuntimeError("The bundled desktop MCP server did not become ready.")
                grant = runtime.service.access.create(Grant(name="Smoke test", clients=["default"]))
                runtime.service.access.enable(True)
                response = client.post(
                    "/mcp/",
                    headers={
                        "Authorization": f"Bearer {grant['token']}",
                        "Accept": "application/json, text/event-stream",
                    },
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                )
                assert response.status_code == 200, "Bundled MCP tool discovery failed"
                assert "overview" in {t["name"] for t in response.json()["result"]["tools"]}
        finally:
            runtime.close()
            if runtime.app is not None:
                runtime.service.feed_control.feeds.db.close()
                runtime.service.access.db.close()
            store._db.close()  # release the temporary database before removal on Windows


def setup_logging(path: Path) -> None:
    import logging

    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8")]
        + ([logging.StreamHandler()] if sys.stderr is not None else []),
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def show_unexpected_errors() -> None:
    """Errors raised inside Qt callbacks would otherwise only reach the terminal."""
    import logging
    import traceback
    from types import TracebackType

    from PySide6.QtWidgets import QMessageBox

    def hook(kind: type[BaseException], error: BaseException, tb: TracebackType | None) -> None:
        details = "".join(traceback.format_exception(kind, error, tb))
        logging.getLogger("torrentlinker").error("unexpected error\n%s", details)
        if "--smoke-test" in sys.argv:
            return
        box = QMessageBox(QMessageBox.Icon.Critical, "TorrentLinker", f"{kind.__name__}: {error}")
        box.setDetailedText(details)
        report = box.addButton(
            QCoreApplication.translate("CrashReport", "Report the problem"),
            QMessageBox.ButtonRole.ActionRole,
        )
        box.exec()
        if box.clickedButton() is report:
            from torrentlinker.gui.crash_reports import offer_report

            offer_report(error)

    sys.excepthook = hook


def apply_ui_scale(scale: float, environ: MutableMapping[str, str] = os.environ) -> None:
    """Qt reads the scale factor once, before the application starts. It multiplies the
    desktop's own scaling; a QT_SCALE_FACTOR set by the user wins."""
    if scale != 1.0 and "QT_SCALE_FACTOR" not in environ:
        environ["QT_SCALE_FACTOR"] = f"{scale:g}"


def main() -> int:
    multiprocessing.freeze_support()  # a frozen build re-runs itself for child processes
    QCoreApplication.setApplicationName("TorrentLinker")
    QCoreApplication.setOrganizationName("TorrentLinker")
    apply_ui_scale(Settings.load(data_dir() / "settings.json").ui_scale)
    from torrentlinker.gui.windows_identity import set_app_id

    set_app_id()
    QGuiApplication.setDesktopFileName("torrentlinker")
    app = QApplication(sys.argv)
    show_unexpected_errors()
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "icon.png")))
    setup_logging(data_dir() / "torrentlinker.log")
    settings_path = data_dir() / "settings.json"
    settings = Settings.load(settings_path)
    apply_theme(app, settings.theme)
    translators = i18n.install(app, i18n.pick_language(settings.language))  # noqa: F841
    store = Store(data_dir() / "state.db")
    window = MainWindow(settings, settings_path, store)
    window.show()
    cross_seed = None
    from torrentlinker.gui.stall_watchdog import install as watch_for_stalls

    watch_for_stalls(window)
    from torrentlinker.gui.garbage import keep_collections_short

    keep_collections_short(window)
    try:
        if "--smoke-test" in sys.argv:  # used by CI on packaged builds
            try:
                smoke_checks()
            except Exception:
                import logging

                logging.getLogger("torrentlinker").exception("Packaged smoke test failed")
                return 1  # no modal error dialog that could hang a headless build
            QTimer.singleShot(500, app.quit)
        else:
            update_timer = QTimer(window)
            update_timer.setInterval(CHECK_INTERVAL * 1000)
            update_timer.timeout.connect(window.check_for_updates)
            update_timer.start()
            QTimer.singleShot(1000, window.check_for_updates)
            QTimer.singleShot(0, window.startup)
            QTimer.singleShot(2000, window.start_saved_agent_access)
            from torrentlinker.crossseed_desktop import DesktopCrossSeed

            cross_seed = DesktopCrossSeed(
                settings_path,
                store,
                # the window is replaced when the settings change
                lambda: list(getattr(app, "torrentlinker_window", window).library_model.entries),
            )
            app.aboutToQuit.connect(cross_seed.stop)
            cross_seed.start()
        return app.exec()
    finally:
        from torrentlinker.gui.tasks import shutdown

        if cross_seed is not None:
            cross_seed.stop()
        window.close()
        shutdown()


if __name__ == "__main__":
    sys.exit(main())
