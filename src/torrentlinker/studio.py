"""Local multitrack projects, portable bundles and bounded host render jobs."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from torrentlinker.prerolls import Model
from torrentlinker.web.security import atomic_private

ID = r"^[a-f0-9]{32}$"
PROPERTIES = {
    "x": (-2.0, 2.0),
    "y": (-2.0, 2.0),
    "scale": (0.01, 4.0),
    "rotation": (-3600.0, 3600.0),
    "opacity": (0.0, 1.0),
    "volume": (0.0, 4.0),
}
DEFAULTS = {"x": 0.5, "y": 0.5, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "volume": 1.0}


class Keyframe(Model):
    time: float = Field(ge=0, le=600)
    value: float
    interpolation: Literal["linear", "ease-in", "ease-out", "ease-in-out", "bezier"] = "linear"
    curve: tuple[float, float, float, float] = (0.25, 0.1, 0.25, 1.0)

    @model_validator(mode="after")
    def valid(self):
        if any(not 0 <= v <= 1 for v in self.curve):
            raise ValueError("Curve handles must be between zero and one.")
        return self


class Segment(Model):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=ID)
    kind: Literal["video", "image", "text", "audio"] = "text"
    asset: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    text: str = Field(default="", max_length=2000)
    color: str = Field(default="#ffffff", pattern=r"^#[a-fA-F0-9]{6}$")
    font_size: int = Field(default=72, ge=8, le=300)
    start: float = Field(default=0, ge=0, lt=600)
    duration: float = Field(default=5, gt=0, le=600)
    offset: float = Field(default=0, ge=0, le=86400)
    animation_offset: float = Field(default=0, ge=0, le=600)
    x: float = Field(default=0.5, ge=-2, le=2)
    y: float = Field(default=0.5, ge=-2, le=2)
    scale: float = Field(default=1, ge=0.01, le=4)
    rotation: float = Field(default=0, ge=-3600, le=3600)
    opacity: float = Field(default=1, ge=0, le=1)
    volume: float = Field(default=1, ge=0, le=4)
    crop: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    fade_in: float = Field(default=0, ge=0, le=600)
    fade_out: float = Field(default=0, ge=0, le=600)
    keyframes: dict[str, list[Keyframe]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        left, top, right, bottom = self.crop
        if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
            raise ValueError("Crop must have a positive area inside the image.")
        if self.start + self.duration > 600 or max(self.fade_in, self.fade_out) > self.duration:
            raise ValueError("Clips and fades must fit the ten-minute project.")
        for name, frames in self.keyframes.items():
            if name not in PROPERTIES or len(frames) > 200:
                raise ValueError("Unsupported animation property or too many keyframes.")
            times = [f.time for f in frames]
            if times != sorted(set(times)) or any(t > 600 for t in times):
                raise ValueError("Keyframes must be ordered, unique and inside the clip.")
            low, high = PROPERTIES[name]
            if any(not low <= f.value <= high for f in frames):
                raise ValueError("Keyframe value outside the property's limits.")
        return self


class Track(Model):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=ID)
    name: str = Field(default="Track", min_length=1, max_length=100)
    muted: bool = False
    clips: list[Segment] = Field(default_factory=list, max_length=200)


class Project(Model):
    format: Literal["torrentlinker-studio"] = "torrentlinker-studio"
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=ID)
    name: str = Field(default="Untitled", min_length=1, max_length=150)
    duration: float = Field(default=10, gt=0, le=600)
    width: Literal[1920, 1280] = 1920
    height: Literal[1080, 720] = 1080
    fps: Literal[24, 25, 30] = 25
    background: str = Field(default="#101827", pattern=r"^#[a-fA-F0-9]{6}$")
    tracks: list[Track] = Field(default_factory=list, max_length=24)
    creator: str = Field(default="", max_length=150)
    license: str = Field(default="CC-BY-4.0", max_length=80)
    source_project: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def valid(self):
        if (self.width, self.height) not in {(1920, 1080), (1280, 720)}:
            raise ValueError("Choose 1080p or 720p.")
        clips = [c for t in self.tracks for c in t.clips]
        ids = [t.id for t in self.tracks] + [c.id for c in clips]
        if len(ids) != len(set(ids)) or len(clips) > 500:
            raise ValueError("Duplicate IDs or too many clips.")
        if any(c.start + c.duration > self.duration + 0.000001 for c in clips):
            raise ValueError("All clips must fit the project duration.")
        return self


def interpolate(frames: list[Keyframe], when: float, default: float) -> float:
    if not frames:
        return default
    if when <= frames[0].time:
        return frames[0].value
    for a, b in zip(frames, frames[1:], strict=False):
        if when <= b.time:
            u = (when - a.time) / (b.time - a.time)
            if a.interpolation == "ease-in":
                u *= u
            elif a.interpolation == "ease-out":
                u = 1 - (1 - u) ** 2
            elif a.interpolation == "ease-in-out":
                u = u * u * (3 - 2 * u)
            elif a.interpolation == "bezier":
                x1, y1, x2, y2 = a.curve

                def bez(t, p, q):
                    return 3 * (1 - t) ** 2 * t * p + 3 * (1 - t) * t * t * q + t**3

                low, high = 0.0, 1.0
                for _ in range(24):
                    mid = (low + high) / 2
                    if bez(mid, x1, x2) < u:
                        low = mid
                    else:
                        high = mid
                u = bez((low + high) / 2, y1, y2)
            return a.value + (b.value - a.value) * u
    return frames[-1].value


def value(clip: Segment, name: str, when: float) -> float:
    return interpolate(
        clip.keyframes.get(name, []), when + clip.animation_offset, getattr(clip, name)
    )


def envelope(clip: Segment, when: float) -> float:
    return min(
        1.0,
        when / clip.fade_in if clip.fade_in else 1.0,
        (clip.duration - when) / clip.fade_out if clip.fade_out else 1.0,
    )


def inspect_asset(path: Path) -> dict:
    from PIL import Image

    if path.stat().st_size > 2_000_000_000:
        raise ValueError("Local assets must be smaller than 2 GB.")
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            if im.width * im.height > 40_000_000:
                raise ValueError("Image exceeds 40 megapixels.")
            return {"kind": "image", "width": im.width, "height": im.height, "duration": 0}
    except (OSError, SyntaxError):
        pass
    executable = shutil.which("ffprobe")
    if not executable:
        raise ValueError("Install ffmpeg on the TorrentLinker host.")
    try:
        data = json.loads(
            subprocess.run(
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
                check=True,
                timeout=30,
            ).stdout
        )
        formats = set(str(data.get("format", {}).get("format_name", "")).split(","))
        if not formats & {
            "mov",
            "mp4",
            "matroska",
            "webm",
            "wav",
            "mp3",
            "flac",
            "ogg",
            "aac",
            "avi",
        }:
            raise ValueError("Unsupported media container.")
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = any(s.get("codec_type") == "audio" for s in streams)
        duration = float(data.get("format", {}).get("duration", 0))
        if not math.isfinite(duration) or not 0 < duration <= 86400 or not (video or audio):
            raise ValueError()
        return {
            "kind": "video" if video else "audio",
            "width": (video or {}).get("width", 0),
            "height": (video or {}).get("height", 0),
            "duration": duration,
            "audio": audio,
        }
    except (ValueError, subprocess.SubprocessError):
        raise ValueError("Unsupported or damaged media file.") from None


class Studio:
    def __init__(self, setup):
        self.setup = setup
        self.root = setup.path.parent / "studio"
        self.root.mkdir(exist_ok=True)
        for folder in ("projects", "assets", "exports"):
            (self.root / folder).mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.job: dict = {"status": "idle"}
        self.cancel = threading.Event()

    def path(self, folder: str, identifier: str, suffix="") -> Path:
        import re

        if not re.fullmatch(ID, identifier):
            raise ValueError("Invalid Studio identifier.")
        path = self.root / folder / (identifier + suffix)
        if path.is_symlink():
            raise ValueError("Studio files cannot be symbolic links.")
        return path

    def asset(self, identifier):
        return json.loads(self.path("assets", identifier, ".json").read_text())

    def add_asset(self, source: Path, name=""):
        identifier = uuid4().hex
        destination = self.path("assets", identifier)
        try:
            shutil.copyfile(source, destination)
            info = inspect_asset(destination)
            info.update(
                id=identifier,
                name=(name or source.name)[:150],
                bytes=destination.stat().st_size,
                sha256=hashlib.file_digest(destination.open("rb"), "sha256").hexdigest(),
            )
            atomic_private(self.path("assets", identifier, ".json"), json.dumps(info).encode())
            return info
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def state(self):
        with self.lock:
            projects, assets = [], []
            for path in sorted((self.root / "projects").glob("*.json")):
                try:
                    project = self.load(path.stem)
                    projects.append({"id": project.id, "name": project.name})
                except (ValueError, OSError):
                    continue
            for path in sorted((self.root / "assets").glob("*.json")):
                try:
                    assets.append(json.loads(path.read_text()))
                except (ValueError, OSError):
                    continue
            return {
                "projects": projects,
                "assets": assets,
                "job": dict(self.job),
                "ffmpeg": bool(shutil.which("ffmpeg")),
            }

    def load(self, identifier):
        path = self.path("projects", identifier, ".json")
        try:
            return Project.model_validate_json(path.read_bytes())
        except (ValueError, OSError):
            backup = path.with_suffix(".recovery")
            if not backup.exists():
                raise ValueError("Project unavailable.") from None
            return Project.model_validate_json(backup.read_bytes())

    def save(self, body):
        project = Project.model_validate(body)
        with self.lock:
            path = self.path("projects", project.id, ".json")
            if path.exists():
                previous = path.read_bytes()
                try:
                    Project.model_validate_json(previous)
                except ValueError:
                    pass
                else:
                    atomic_private(path.with_suffix(".recovery"), previous)
            atomic_private(path, project.model_dump_json().encode())
        return project.model_dump()

    def template(self, kind, title, server=""):
        if kind not in {"welcome", "announcement", "coming-soon"}:
            raise ValueError("Unknown template.")
        heading = (
            title
            or {"welcome": "Welcome", "announcement": "Announcement", "coming-soon": "Coming soon"}[
                kind
            ]
        )
        title_clip = Segment(
            text=heading,
            duration=8,
            y=0.42,
            fade_in=1,
            fade_out=1,
            keyframes={
                "scale": [
                    Keyframe(time=0, value=0.85, interpolation="ease-out"),
                    Keyframe(time=2, value=1),
                ]
            },
        )
        subtitle = Segment(
            text={
                "welcome": (server.strip()[:100] or "Your library") + " · Enjoy the film",
                "announcement": "Write your announcement here",
                "coming-soon": "Add a film title and its library artwork",
            }[kind],
            font_size=36,
            y=0.62,
            start=1,
            duration=7,
            fade_in=0.5,
            fade_out=1,
        )
        tracks = [Track(name="Titles", clips=[title_clip, subtitle])]
        if kind == "coming-soon":
            tracks.insert(
                0,
                Track(
                    name="Library artwork",
                    clips=[
                        Segment(
                            kind="image", duration=8, scale=0.6, opacity=0.45, fade_in=1, fade_out=1
                        )
                    ],
                ),
            )
        project = Project(name=heading, tracks=tracks)
        return self.save(project.model_dump())

    def bundle(self, identifier, selected, *, community=False):
        project = self.load(identifier)
        referenced = {c.asset for t in project.tracks for c in t.clips if c.asset}
        if len(selected) != len(set(selected)) or set(selected) - referenced:
            raise ValueError("Only assets referenced by this project can be bundled.")
        assets = [self.asset(i) for i in selected]
        manifest = {"project": project.model_dump(), "assets": assets}
        target = self.path("exports", uuid4().hex, ".tlstudio")
        try:
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("project.json", json.dumps(manifest, ensure_ascii=False))
                for asset in assets:
                    archive.write(self.path("assets", asset["id"]), "assets/" + asset["id"])
            if community and target.stat().st_size > 50_000_000:
                raise ValueError(
                    "Community project bundles are limited to 50 MB. Select fewer media files."
                )
            return target
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def import_bundle(self, source: Path, *, source_project=""):
        # Never extract ZIP names to the filesystem. Every member is explicitly validated.
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if any(i.compress_type != zipfile.ZIP_STORED for i in entries):
                raise ValueError("Use an uncompressed portable Studio bundle.")
            names = [i.filename for i in entries]
            if (
                len(names) != len(set(names))
                or len(names) > 501
                or sum(i.file_size for i in entries) > 2_000_000_000
            ):
                raise ValueError("Invalid or oversized project bundle.")
            if "project.json" not in names or archive.getinfo("project.json").file_size > 2_000_000:
                raise ValueError("Project manifest missing or too large.")
            manifest = json.loads(archive.read("project.json"))
            project = Project.model_validate(manifest["project"])
            metadata = manifest.get("assets", [])
            expected = {"project.json"} | {"assets/" + str(a["id"]) for a in metadata}
            if set(names) != expected:
                raise ValueError("Unexpected files in project bundle.")
            mapping = {}
            created = []
            try:
                for row in metadata:
                    # Validate ID before touching a file; hashes bind bytes to the manifest.
                    self.path("assets", row["id"])
                    temporary = self.path("exports", uuid4().hex, ".incoming")
                    try:
                        with (
                            archive.open("assets/" + row["id"]) as src,
                            temporary.open("wb") as dst,
                        ):
                            shutil.copyfileobj(src, dst)
                        with temporary.open("rb") as stream:
                            digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        if digest != row["sha256"]:
                            raise ValueError("Project media checksum mismatch.")
                        asset = self.add_asset(temporary, row.get("name", "Media"))
                        mapping[row["id"]] = asset["id"]
                        created.append(asset["id"])
                    finally:
                        temporary.unlink(missing_ok=True)
                # Missing media gets fresh IDs, never resolves against unrelated local assets.
                for track in project.tracks:
                    for clip in track.clips:
                        if clip.asset:
                            clip.asset = mapping.setdefault(clip.asset, uuid4().hex)
                project.source_project = source_project or project.source_project or project.id
                project.id = uuid4().hex
                return self.save(project.model_dump())
            except Exception:
                for identifier in created:
                    self.path("assets", identifier).unlink(missing_ok=True)
                    self.path("assets", identifier, ".json").unlink(missing_ok=True)
                raise

    def request(self, action, body):
        if action == "upload-start":
            identifier = uuid4().hex
            self.path("exports", identifier, ".upload").touch(mode=0o600)
            return {"id": identifier}
        if action == "upload-chunk":
            path = self.path("exports", body["id"], ".upload")
            chunk = base64.b64decode(body["data"], validate=True)
            with self.lock:
                if (
                    len(chunk) > 150_000
                    or not path.exists()
                    or path.stat().st_size != body["offset"]
                ):
                    raise ValueError("Invalid upload chunk or offset.")
                if (
                    path.stat().st_size + len(chunk) > 2_000_000_000
                    or shutil.disk_usage(self.root).free < 1_000_000_000
                ):
                    raise ValueError("Upload exceeds the local asset or free space limit.")
                with path.open("ab") as stream:
                    stream.write(chunk)
            return {"offset": path.stat().st_size}
        if action == "upload-finish":
            path = self.path("exports", body["id"], ".upload")
            try:
                if body.get("bundle"):
                    return self.import_bundle(path)
                return self.add_asset(path, body.get("name", "Media"))
            finally:
                path.unlink(missing_ok=True)
        if action == "upload-cancel":
            self.path("exports", body["id"], ".upload").unlink(missing_ok=True)
            return {"ok": True}
        if action == "add-render":
            from torrentlinker.prerolls import prerolls

            filename = str(body["file"])
            if Path(filename).suffix != ".mp4":
                raise ValueError("Choose a rendered MP4.")
            return prerolls(self.setup).add(
                self.path("exports", Path(filename).stem, ".mp4"),
                body.get("title", "Studio render"),
                origin="generated",
                rating=body.get("rating"),
            )
        if action == "state":
            return self.state()
        if action == "load":
            return self.load(body["id"]).model_dump()
        if action == "save":
            return self.save(body["project"])
        if action == "template":
            return self.template(
                body.get("kind", "welcome"), body.get("title", ""), body.get("server", "")
            )
        if action == "asset":
            return self.add_asset(self.setup.path_under_root(body["path"], directory=False))
        if action == "preview":
            from torrentlinker.studio_render import frame

            project = Project.model_validate(body["project"])
            when = max(0.0, min(float(body.get("time", 0)), project.duration))
            image = frame(self, project, when, 640)
            output = io.BytesIO()
            image.save(output, "JPEG", quality=80)
            return {
                "data_url": "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()
            }
        if action == "render":
            from torrentlinker.studio_render import render

            project = self.load(body["id"])
            with self.lock:
                if self.job["status"] == "running":
                    raise ValueError("A Studio render is already running.")
                self.cancel.clear()
                self.job = {"status": "running", "progress": 0, "project": project.id}
                threading.Thread(target=render, args=(self, project), daemon=True).start()
                return dict(self.job)
        if action == "cancel":
            self.cancel.set()
            return {"ok": True}
        if action == "bundle":
            path = self.bundle(body["id"], body.get("assets", []))
            return {"file": path.name, "bytes": path.stat().st_size}
        if action == "import":
            return self.import_bundle(self.setup.path_under_root(body["path"], directory=False))
        raise ValueError("Unknown Studio operation.")


def studio(setup):
    root = setup._root or setup
    with root.lock:
        if not hasattr(root, "_studio"):
            root._studio = Studio(root)
        return root._studio
