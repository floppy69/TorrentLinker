"""CPU compositor shared by preview and host rendering. Inputs never use network protocols."""

from __future__ import annotations

import io
import math
import shutil
import subprocess
import wave
from contextlib import ExitStack
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from torrentlinker.studio import Project, envelope, value


def command():
    executable = shutil.which("ffmpeg")
    if not executable:
        raise ValueError("Install ffmpeg on the machine running TorrentLinker.")
    return [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "1"]


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if process.stdout:
        process.stdout.close()


class Decoder:
    def __init__(self, studio, clip, when, fps, width, audio=False):
        source = studio.path("assets", clip.asset)
        args = command() + [
            "-protocol_whitelist",
            "file,pipe",
            "-ss",
            str(clip.offset + when),
            "-i",
            str(source),
        ]
        self.audio = audio
        if audio:
            args += ["-vn", "-ac", "2", "-ar", "48000", "-f", "f32le", "pipe:1"]
            self.size = 48000 // fps * 8
        else:
            meta = studio.asset(clip.asset)
            factor = min(width / max(1, meta["width"]), (width * 9 / 16) / max(1, meta["height"]))
            out_width = max(2, round(meta["width"] * factor / 2) * 2)
            out_height = max(2, round(meta["height"] * factor / 2) * 2)
            args += [
                "-an",
                "-vf",
                f"scale={out_width}:{out_height},fps={fps}",
                "-pix_fmt",
                "rgba",
                "-f",
                "rawvideo",
                "pipe:1",
            ]
            self.shape = (out_width, out_height)
            self.size = out_width * out_height * 4
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.last = None

    def read(self):
        assert self.process.stdout is not None
        data = self.process.stdout.read(self.size)
        if self.audio:
            data += b"\0" * (self.size - len(data))
            return np.frombuffer(data, dtype="<f4").reshape((-1, 2)).copy()
        if len(data) == self.size:
            self.last = Image.frombytes("RGBA", self.shape, data)
        return self.last.copy() if self.last is not None else None

    def close(self):
        stop(self.process)


def font(size):
    for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def frame(studio, project: Project, when: float, width=1920, decoders=None):
    height = round(width * project.height / project.width)
    canvas = Image.new("RGBA", (width, height), project.background)
    for track in project.tracks:
        if track.muted:
            continue
        for clip in track.clips:
            local = when - clip.start
            if clip.kind == "audio" or not 0 <= local < clip.duration:
                continue
            picture = None
            if clip.kind == "text":
                picture = Image.new("RGBA", (width, height))
                draw = ImageDraw.Draw(picture)
                draw.multiline_text(
                    (width / 2, height / 2),
                    clip.text,
                    fill=clip.color,
                    font=font(max(8, round(clip.font_size * width / project.width))),
                    anchor="mm",
                    align="center",
                )
            elif clip.asset and studio.path("assets", clip.asset).exists():
                try:
                    meta = studio.asset(clip.asset)
                except (OSError, ValueError):
                    meta = {"kind": "missing"}
                if clip.kind == "image" and meta["kind"] == "image":
                    with Image.open(studio.path("assets", clip.asset)) as image:
                        picture = image.convert("RGBA")
                        picture.thumbnail((width, height))
                elif clip.kind == "video" and meta["kind"] == "video":
                    if decoders is not None:
                        if clip.id not in decoders:
                            decoders[clip.id] = Decoder(studio, clip, local, project.fps, width)
                        picture = decoders[clip.id].read()
                    else:
                        result = subprocess.run(
                            command()
                            + [
                                "-protocol_whitelist",
                                "file,pipe",
                                "-ss",
                                str(clip.offset + local),
                                "-i",
                                str(studio.path("assets", clip.asset)),
                                "-frames:v",
                                "1",
                                "-vf",
                                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                                "-f",
                                "image2pipe",
                                "-vcodec",
                                "png",
                                "pipe:1",
                            ],
                            capture_output=True,
                            timeout=30,
                            check=True,
                        )
                        if result.stdout:
                            picture = Image.open(io.BytesIO(result.stdout)).convert("RGBA")
            if picture is None:
                picture = Image.new("RGBA", (width // 2, height // 3), "#333333")
                ImageDraw.Draw(picture).text(
                    (20, 20), "Missing media", font=font(max(12, width // 40)), fill="white"
                )
            left, top, right, bottom = clip.crop
            picture = picture.crop(
                (
                    round(left * picture.width),
                    round(top * picture.height),
                    round(right * picture.width),
                    round(bottom * picture.height),
                )
            )
            size = value(clip, "scale", local)
            picture = picture.resize(
                (max(1, round(picture.width * size)), max(1, round(picture.height * size))),
                Image.Resampling.BILINEAR,
            )
            angle = value(clip, "rotation", local)
            if angle:
                picture = picture.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
            alpha = max(0.0, min(1.0, value(clip, "opacity", local) * envelope(clip, local)))
            picture.putalpha(picture.getchannel("A").point(lambda p, alpha=alpha: round(p * alpha)))
            x, y = (
                round(value(clip, "x", local) * width - picture.width / 2),
                round(value(clip, "y", local) * height - picture.height / 2),
            )
            canvas.alpha_composite(picture, (x, y))
    return canvas.convert("RGB")


def render(studio, project):
    identifier = uuid4().hex
    output = studio.path("exports", identifier, ".mp4")
    video = studio.path("exports", identifier, ".video.mp4")
    audio = studio.path("exports", identifier, ".wav")
    decoders, sounds = {}, {}
    encoder = None
    try:
        if shutil.disk_usage(studio.root).free < 1_000_000_000:
            raise ValueError("Studio rendering needs at least 1 GB of free host space.")
        with ExitStack() as stack:
            encoder = subprocess.Popen(
                command()
                + [
                    "-y",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-s",
                    f"{project.width}x{project.height}",
                    "-r",
                    str(project.fps),
                    "-i",
                    "pipe:0",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            stack.callback(stop, encoder)
            assert encoder.stdin is not None
            wavefile = stack.enter_context(wave.open(str(audio), "wb"))
            wavefile.setnchannels(2)
            wavefile.setsampwidth(2)
            wavefile.setframerate(48000)
            count = math.ceil(project.duration * project.fps)
            samples = 48000 // project.fps
            for number in range(count):
                if studio.cancel.is_set():
                    raise InterruptedError()
                when = number / project.fps
                encoder.stdin.write(frame(studio, project, when, project.width, decoders).tobytes())
                mix = np.zeros((samples, 2), dtype=np.float32)
                active = set()
                for track in project.tracks:
                    if track.muted:
                        continue
                    for clip in track.clips:
                        local = when - clip.start
                        if (
                            clip.kind not in {"audio", "video"}
                            or not 0 <= local < clip.duration
                            or not clip.asset
                        ):
                            continue
                        try:
                            meta = studio.asset(clip.asset)
                        except OSError:
                            continue
                        if not meta.get("audio", meta["kind"] == "audio"):
                            continue
                        active.add(clip.id)
                        if clip.id not in sounds:
                            sounds[clip.id] = Decoder(
                                studio, clip, local, project.fps, project.width, audio=True
                            )
                        chunk = sounds[clip.id].read()
                        # Smooth envelope across each audio block avoids clicks at keyframes.
                        first = value(clip, "volume", local) * envelope(clip, local)
                        last_time = min(clip.duration, local + 1 / project.fps)
                        last = value(clip, "volume", last_time) * envelope(clip, last_time)
                        mix += chunk * np.linspace(first, last, samples, dtype=np.float32)[:, None]
                wavefile.writeframesraw((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
                for key in list(sounds):
                    if key not in active:
                        sounds.pop(key).close()
                active_video = {
                    c.id
                    for t in project.tracks
                    for c in t.clips
                    if c.start <= when < c.start + c.duration
                }
                for key in list(decoders):
                    if key not in active_video:
                        decoders.pop(key).close()
                with studio.lock:
                    studio.job["progress"] = round((number + 1) / count * 0.9, 3)
            encoder.stdin.close()
            if encoder.wait(timeout=60) != 0:
                raise ValueError("Video encoding failed. Check ffmpeg codec support.")
        if studio.cancel.is_set():
            raise InterruptedError()
        subprocess.run(
            command()
            + [
                "-y",
                "-i",
                str(video),
                "-i",
                str(audio),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                str(project.duration),
                "-movflags",
                "+faststart",
                str(output),
            ],
            capture_output=True,
            check=True,
            timeout=180,
        )
        with studio.lock:
            studio.job = {
                "status": "complete",
                "progress": 1,
                "project": project.id,
                "file": output.name,
                "bytes": output.stat().st_size,
                "shareable": output.stat().st_size <= 50_000_000,
            }
        from torrentlinker.achievements import record_completion

        record_completion(studio.setup.path.parent, "studio", identifier)
    except InterruptedError:
        output.unlink(missing_ok=True)
        with studio.lock:
            studio.job = {"status": "cancelled", "project": project.id}
    except Exception as error:
        output.unlink(missing_ok=True)
        with studio.lock:
            studio.job = {
                "status": "failed",
                "project": project.id,
                "error": str(error)
                if isinstance(error, ValueError)
                else "Rendering failed. Check the host's ffmpeg installation and available space.",
            }
    finally:
        for decoder in [*decoders.values(), *sounds.values()]:
            decoder.close()
        if encoder:
            if encoder.stdin and not encoder.stdin.closed:
                encoder.stdin.close()
            stop(encoder)
        video.unlink(missing_ok=True)
        audio.unlink(missing_ok=True)
