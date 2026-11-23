"""Measure the current shared Torrents panel with synthetic local data only.

Run each count in a separate process. Requires the development Qt dependencies.
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_shared_torrents.py --count 50000
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("count must be positive")
    with tempfile.TemporaryDirectory(prefix="tl-shared-torrents-") as folder:
        root = Path(folder)
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            os.environ[key] = str(root / key)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        from PySide6.QtCore import QTimer, qVersion
        from PySide6.QtWidgets import QApplication

        from torrentlinker.agent.desktop import DesktopOperations
        from torrentlinker.domain import Torrent
        from torrentlinker.gui import tasks
        from torrentlinker.gui.torrents_view import TorrentsTab
        from torrentlinker.torrents_workspace import TorrentWorkspace
        from torrentlinker.web.security import ServerSecrets
        from torrentlinker.web.setup import Setup

        rows = [
            Torrent(
                f"{i:040x}",
                f"Fixture {i:06d} with a moderately long release name",
                root / "downloads",
                tags=frozenset({f"tag-{i % 32:05d}", "benchmark"}),
                category=f"Category {i % 8}/Subcategory {i % 24}",
                trackers=(f"https://tracker-{i % 4}.example/announce",),
                state="uploading" if i % 4 else "downloading",
                progress=1.0 if i % 4 else 0.4,
                size=(i + 1) * 1024 * 1024,
                upload_rate=i % 1000,
            )
            for i in range(args.count)
        ]

        class Client:
            def torrents(self, **kwargs):
                return rows

        setup = Setup(root, (), ServerSecrets(root), lambda *args: Client())
        setup.configured = True
        setup.settings.language = "en"
        operation = DesktopOperations(setup)
        service = TorrentWorkspace(setup, lambda _: operation)
        app = QApplication([])
        app.setOrganizationName("TorrentLinkerBenchmark")
        app.setApplicationName("SharedTorrents")
        view = TorrentsTab(SimpleNamespace(settings=setup.settings), lambda: service)
        view.resize(1280, 850)
        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
        heartbeat.start()

        def spin(predicate, timeout=60):
            deadline = time.perf_counter() + timeout
            while not predicate():
                app.processEvents()
                if time.perf_counter() >= deadline:
                    raise TimeoutError("Shared Torrents did not become ready")
                time.sleep(0.001)

        def js(source):
            if view.web is None:
                return None
            result = []
            view.web.page().runJavaScript(source, lambda value: result.append(value))
            spin(lambda: bool(result))
            return result[0]

        def measure(action, done):
            ticks.clear()
            ticks.append(time.perf_counter())
            start = ticks[0]
            action()
            spin(done)
            until = time.perf_counter() + 0.02
            spin(lambda: time.perf_counter() >= until)
            return {
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                "qt_heartbeat_gap_ms": round(
                    max((b - a for a, b in zip(ticks, ticks[1:], strict=False)), default=0) * 1000,
                    2,
                ),
            }

        def load(query="", refresh=False):
            if refresh:
                service.updated.clear()
            js(
                "window.benchmarkDone=false;query="
                + json.dumps(query)
                + ";page=0;load().then(()=>{window.benchmarkDone=true});"
            )

        def loaded():
            return js("window.benchmarkDone===true && !busy && !pendingReload")

        try:
            measurements = {
                "first_display": measure(
                    view.show,
                    lambda: js(
                        "typeof snapshot !== 'undefined' && !busy && !pendingReload && "
                        "snapshot.total === " + str(args.count)
                    ),
                )
            }
            js(
                "environment.active=false;window.benchmarkGaps=[];"
                "window.benchmarkTick=performance.now();"
                "window.benchmarkTimer=setInterval(()=>{const now=performance.now();"
                "benchmarkGaps.push(now-benchmarkTick);benchmarkTick=now},10)"
            )
            measurements["unchanged_refresh"] = [
                measure(lambda: load(refresh=True), loaded) for _ in range(3)
            ]
            for i in range(3):
                rows = [
                    replace(row, upload_rate=row.upload_rate + 1, ratio=i + 1.5) for row in rows
                ]
                measurements.setdefault("changing_refresh", []).append(
                    measure(lambda: load(refresh=True), loaded)
                )
            measurements["filter"] = measure(lambda: load(f"{args.count - 1:06d}"), loaded)
            assert js("snapshot.total") == 1
            measurements["clear_filter"] = measure(load, loaded)
            assert js("snapshot.total") == args.count
            assert js("document.querySelectorAll('tbody tr').length") == min(100, args.count)
            js("document.querySelector('tbody input').click()")
            selected = js("JSON.stringify([...selected])")
            measurements["selected_refresh"] = measure(lambda: load(refresh=True), loaded)
            assert js("JSON.stringify([...selected])") == selected
            gaps = js("clearInterval(benchmarkTimer);benchmarkGaps")
            if args.screenshot:
                view.grab().save(str(args.screenshot))
            result = {
                "count": args.count,
                "python": platform.python_version(),
                "qt": qVersion(),
                "platform": platform.platform(),
                "qt_platform": app.platformName(),
                "peak_app_rss_mib": round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2
                ),
                "renderer_heartbeat_max_ms": round(max(gaps), 2) if gaps else None,
                "measurements": measurements,
                "limits": "Synthetic client and empty catalogue; no network or keyring. "
                "Desktop shared WebView including startup. App RSS excludes renderer subprocesses. "
                "Refreshes force the client snapshot. Timings include a 20 ms event drain; "
                "filter timings exclude typing debounce. No cancellation workload. "
                "Offscreen renderer timers may be throttled; no samples are reported as null.",
            }
            if args.output:
                args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
        finally:
            heartbeat.stop()
            view.close()
            tasks.shutdown()
            app.processEvents()
            setup.store._db.close()


if __name__ == "__main__":
    main()
