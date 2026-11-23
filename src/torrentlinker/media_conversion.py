"""Bounded, cancellable compatible playback. Original files are read, never changed.

Both hosts resolve an authorized library item before calling this module. No caller
can pass FFmpeg switches, output paths or network URLs. Output stays in a pipe.
"""

from __future__ import annotations

import io
import json
import math
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from torrentlinker.media_tracks import language

PRESETS = {
    "360": (640, 360, 500, 64),
    "480": (854, 480, 900, 96),
    "720": (1280, 720, 1800, 128),
    "1080": (1920, 1080, 4000, 192),
}


def inspect(path: Path) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if not executable or not shutil.which("ffmpeg"):
        return {"available": False, "qualities": ["original"], "audio": []}
    try:
        result = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=15,
            check=True,
        )
        data = json.loads(result.stdout)
        video = next(s for s in data["streams"] if s.get("codec_type") == "video")
        duration = float(data["format"].get("duration", 0))
        if not math.isfinite(duration) or not 0 < duration <= 86400:
            raise ValueError
        audio: list[dict[str, Any]] = []
        for stream in data["streams"]:
            if stream.get("codec_type") != "audio":
                continue
            tags = stream.get("tags", {})
            lang = language(str(tags.get("language", "")))
            audio.append(
                {
                    "id": len(audio),
                    "language": lang,
                    "label": str(tags.get("title") or lang or f"Audio {len(audio) + 1}")[:100],
                }
            )
        return {
            "available": True,
            "qualities": ["original", *PRESETS],
            "audio": audio,
            "duration": duration,
            "width": int(video.get("width", 0)),
            "height": int(video.get("height", 0)),
            "hdr": video.get("color_transfer") in {"smpte2084", "arib-std-b67"},
        }
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration):
        raise ValueError("Cannot inspect this video for compatible playback.") from None


@dataclass(frozen=True)
class PlaybackChoice:
    quality: str
    start: float = 0
    audio: int = 0

    def command(self, path: Path, facts: dict[str, Any]) -> list[str]:
        if (
            self.quality not in PRESETS
            or not math.isfinite(self.start)
            or not 0 <= self.start < facts.get("duration", 0)
            or type(self.audio) is not int
            or not 0 <= self.audio < max(1, len(facts.get("audio", [])))
        ):
            raise ValueError("Invalid playback quality, position or audio track.")
        executable = shutil.which("ffmpeg")
        if not executable or not facts.get("available"):
            raise ValueError("Install FFmpeg on the machine running TorrentLinker.")
        width, height, video, audio = PRESETS[self.quality]
        filters = (
            f"scale=w=min({width}\\,iw):h=min({height}\\,ih):"
            "force_original_aspect_ratio=decrease:force_divisible_by=2"
        )
        if facts.get("hdr"):
            filters += (
                ",zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
            )
        return [
            executable,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-threads",
            "4",
            "-protocol_whitelist",
            "file,pipe",
            "-ss",
            str(self.start),
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            f"0:a:{self.audio}?",
            "-sn",
            "-dn",
            "-filter_threads",
            "2",
            "-vf",
            filters + ",format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-b:v",
            f"{video}k",
            "-maxrate",
            f"{video}k",
            "-bufsize",
            f"{video * 2}k",
            "-threads",
            "4",
            "-g",
            "48",
            "-keyint_min",
            "48",
            "-sc_threshold",
            "0",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-b:a",
            f"{audio}k",
            "-movflags",
            "+frag_keyframe+empty_moov+default_base_moof",
            "-f",
            "mp4",
            "pipe:1",
        ]


class Conversion:
    def __init__(self, process: subprocess.Popen, seconds: float, release):
        self.process, self.release = process, release
        self.lock = threading.Lock()
        self.closed = False
        # Allows pauses; still reaps an abandoned/blocked decoder without user action.
        self.timer = threading.Timer(min(86400, max(600, seconds * 2 + 300)), self.close)
        self.timer.daemon = True
        self.timer.start()

    def read(self) -> bytes:
        if self.closed:
            return b""
        try:
            assert self.process.stdout is not None
            assert isinstance(self.process.stdout, io.BufferedReader)
            data = self.process.stdout.read1(65536)
            if not data and self.process.wait() and not self.closed:
                raise ValueError("Video conversion failed. Try Original or an external player.")
            return data
        except (OSError, ValueError):
            if self.closed:
                return b""
            raise

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.timer.cancel()
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            if self.process.stdout:
                self.process.stdout.close()
            self.release()


class Conversions:
    """At most two encoders per app instance, shared by all Members/Viewers."""

    def __init__(self, maximum: int = 2):
        self.maximum = maximum
        self.lock = threading.RLock()
        self.jobs: dict[tuple[str, ...], Conversion] = {}

    def open(
        self, key: tuple[str, ...], path: Path, choice: PlaybackChoice, facts: dict[str, Any]
    ) -> Conversion:
        command = choice.command(path, facts)
        with self.lock:
            if key in self.jobs or len(self.jobs) >= self.maximum:
                raise ValueError("Compatible playback is busy. Stop another conversion and retry.")
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            job = Conversion(process, facts["duration"] - choice.start, lambda: self._release(key))
            self.jobs[key] = job
            return job

    def _release(self, key: tuple[str, ...]) -> None:
        with self.lock:
            self.jobs.pop(key, None)

    def cancel(self, key: tuple[str, ...]) -> None:
        with self.lock:
            job = self.jobs.get(key)
        if job:
            job.close()

    def close(self) -> None:
        with self.lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            job.close()
