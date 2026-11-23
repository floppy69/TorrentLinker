"""Probe installed Qt WebEngine with synthetic media; never reads a user library.

Run: QT_QPA_PLATFORM=wayland python scripts/probe_media_webengine.py --output /tmp/media.json
Requires ffmpeg and the desktop extra. Results describe this runtime, not other builds.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

# Representative codecs for every container extension indexed by MediaLibrary.
FORMATS = [
    ("h264.mp4", "libx264", 'video/mp4; codecs="avc1.42E01E"'),
    ("h264.m4v", "libx264", "video/mp4"),
    ("hevc.mkv", "libx265", 'video/mp4; codecs="hvc1.1.6.L93.B0"'),
    ("vp9.webm", "libvpx-vp9", 'video/webm; codecs="vp9"'),
    ("mpeg4.avi", "mpeg4", "video/x-msvideo"),
    ("h264.mov", "libx264", "video/quicktime"),
    ("mpeg2.mpeg", "mpeg2video", "video/mpeg"),
    ("mpeg2.mpg", "mpeg2video", "video/mpeg"),
    ("h264.ts", "libx264", "video/mp2t"),
    ("wmv.wmv", "wmv2", "video/x-ms-wmv"),
    ("mp3.mp3", "libmp3lame", "audio/mpeg"),
    ("flac.flac", "flac", "audio/flac"),
    ("aac.m4a", "aac", 'audio/mp4; codecs="mp4a.40.2"'),
    ("aac.aac", "aac", "audio/aac"),
    ("vorbis.ogg", "libvorbis", 'audio/ogg; codecs="vorbis"'),
    ("opus.opus", "libopus", 'audio/ogg; codecs="opus"'),
    ("pcm.wav", "pcm_s16le", "audio/wav"),
    ("pcm.aiff", "pcm_s16be", "audio/aiff"),
    ("wma.wma", "wmav2", "audio/x-ms-wma"),
    ("wavpack.wv", "wavpack", "audio/wavpack"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg is required to generate the disposable fixtures")
    # Match the shipped panel's Wayland policy before importing WebEngine.
    if os.environ.get("QT_QPA_PLATFORM", "").startswith("wayland"):
        flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()
    import PySide6
    from PySide6.QtCore import QTimer, QUrl, qVersion
    from PySide6.QtWebEngineCore import QWebEngineSettings, qWebEngineChromiumVersion
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    with tempfile.TemporaryDirectory(prefix="tl-codec-probe-") as directory:
        fixtures = []
        for name, codec, mime in FORMATS:
            video = mime.startswith("video/")
            source = (
                "testsrc2=size=160x120:rate=25" if video else "sine=frequency=440:sample_rate=48000"
            )
            command = [
                ffmpeg,
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                source,
                "-t",
                "2",
                "-threads",
                "1",
                "-c:v" if video else "-c:a",
                codec,
            ]
            if codec == "libx265":
                command += ["-x265-params", "pools=1:frame-threads=1"]
            if name.endswith(("mp4", "m4v", "mov", "m4a")):
                command += ["-movflags", "+faststart"]
            result = subprocess.run(
                command + [str(Path(directory) / name)], capture_output=True, timeout=60
            )
            fixtures.append(
                {
                    "name": name,
                    "mime": mime,
                    "video": video,
                    "generated": result.returncode == 0,
                    "generation_error": result.stderr.decode(errors="replace")[-500:]
                    if result.returncode
                    else "",
                }
            )
        app = QApplication([])
        view = QWebEngineView()
        view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
        )
        view.resize(640, 480)
        view.show()
        html = """<!doctype html><meta charset=utf-8><title>Disposable codec probe</title>
        <p id=status>Checking synthetic media</p><video id=player muted style='width:320px'></video>
        <script>
        window.results=[]; window.done=false;
        async function run(fixtures) {
          for(const f of fixtures) {
            if(!f.generated) { results.push(f); continue; }
            document.getElementById('status').textContent=f.name;
            const player=document.createElement('video');
            player.id='player'; player.muted=true; player.style.width='320px';
            document.getElementById('player').replaceWith(player);
            const entry={...f,canPlayType:player.canPlayType(f.mime),played:false};
            await new Promise(resolve=>{
              let timer;
              const finish=()=>{
                clearTimeout(timer);
                entry.time=player.currentTime; entry.readyState=player.readyState;
                entry.frames=player.getVideoPlaybackQuality?.().totalVideoFrames;
                entry.videoWidth=player.videoWidth;
                player.ontimeupdate=null; player.onerror=null; resolve();
              };
              timer=setTimeout(()=>{entry.timeout=true;finish()},4000);
              player.ontimeupdate=()=>{
                if(player.currentTime>=0.25){entry.played=true;finish()}
              };
              player.onerror=()=>{
                entry.error=player.error?.message;entry.code=player.error?.code;finish();
              };
              player.src=f.name;
              player.play().catch(e=>{entry.rejected=e.message;finish()});
            });
            player.pause(); results.push(entry);
          }
          window.done=true;
        }
        </script>"""
        path = Path(directory) / "index.html"
        path.write_text(html)
        view.loadFinished.connect(
            lambda ok: (
                view.page().runJavaScript("run(" + json.dumps(fixtures) + ")")
                if ok
                else app.exit(2)
            )
        )
        view.load(QUrl.fromLocalFile(str(path)))
        report = {
            "platform": platform.platform(),
            "qt_platform": app.platformName(),
            "pyside": PySide6.__version__,
            "qt": qVersion(),
            "chromium": qWebEngineChromiumVersion(),
            "flags": os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""),
        }

        def collect(value):
            if value:
                report["formats"] = json.loads(value)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                app.quit()

        timer = QTimer()
        timer.timeout.connect(
            lambda: view.page().runJavaScript(
                "window.done ? JSON.stringify(window.results) : ''", collect
            )
        )
        timer.start(250)
        QTimer.singleShot(150000, lambda: app.exit(3))
        raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
