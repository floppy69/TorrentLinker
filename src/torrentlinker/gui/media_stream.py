"""Private loopback transport for native FFmpeg playback, with no filesystem URLs."""

from __future__ import annotations

import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from torrentlinker.media_conversion import Conversions, PlaybackChoice


class NativeStream:
    def __init__(self):
        self.lock = threading.RLock()
        self.conversions = Conversions(maximum=1)
        self.token = secrets.token_urlsafe(32)
        self.selection: tuple[Path, PlaybackChoice, dict] | None = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.serve(False)

            def do_GET(self):
                self.serve(True)

            def log_message(self, *_args):
                pass  # Neither tokens nor original paths belong in request logs.

            def serve(self, body):
                with owner.lock:
                    selection = owner.selection
                    if self.path != "/" + owner.token or selection is None:
                        self.send_error(404)
                        return
                    if self.headers.get("Range", "bytes=0-") != "bytes=0-":
                        self.send_error(416)
                        return
                    if not body:
                        self.send_response(200)
                        self.send_header("Content-Type", "video/mp4")
                        self.end_headers()
                        return
                    try:
                        job = owner.conversions.open((owner.token,), *selection)
                    except (OSError, ValueError):
                        self.send_error(409)
                        return
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    while data := job.read():
                        self.wfile.write(data)
                except (OSError, ValueError):
                    pass
                finally:
                    job.close()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def open(self, path: Path, choice: PlaybackChoice, facts: dict) -> str:
        choice.command(path, facts)  # Validate before replacing a working stream.
        with self.lock:
            self.stop()
            self.token = secrets.token_urlsafe(32)
            self.selection = (path, choice, facts)
            return f"http://127.0.0.1:{self.server.server_port}/{self.token}"

    def stop(self) -> None:
        with self.lock:
            self.selection = None
            self.conversions.close()

    def close(self) -> None:
        self.stop()
        self.server.shutdown()
        self.server.server_close()
