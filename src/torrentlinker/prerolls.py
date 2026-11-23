"""Managed pre-roll clips, sequences and calendar rules; no feature progress is written."""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from torrentlinker.accounts import OWNER_ACTOR, Actor
from torrentlinker.age_ratings import SCALE
from torrentlinker.web.security import atomic_private

Rating = Literal["TP", "10", "12", "16", "18"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Clip(Model):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    title: str = Field(min_length=1, max_length=150)
    category: str = Field(default="welcome", max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=30)
    rating: Rating | None = None
    duration: float = Field(default=0, ge=0, le=600)
    source: Literal["local", "community", "generated", "youtube"] = "local"
    youtube: str = Field(default="", pattern=r"^(?:[A-Za-z0-9_-]{11})?$")
    community_id: str = ""
    community_version: int = 0
    sha256: str = ""


class Step(Model):
    kind: Literal["clip", "random", "trailer", "pause"] = "clip"
    clip: str = ""
    fallback: str = ""
    category: str = Field(default="", max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=30)
    seconds: float = Field(default=2, ge=0, le=60)


class Rules(Model):
    kind: Literal["any", "film", "episode"] = "any"
    genres: list[str] = Field(default_factory=list, max_length=100)
    audio: list[str] = Field(default_factory=list, max_length=50)
    accounts: list[str] = Field(default_factory=list, max_length=500)
    viewers: list[str] = Field(default_factory=list, max_length=500)
    start: str = Field(default="00:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="00:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @field_validator("start", "end")
    @classmethod
    def valid_time(cls, value):
        time.fromisoformat(value)
        return value


class Sequence(Model):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=120)
    steps: list[Step] = Field(default_factory=list, max_length=50)
    rules: Rules = Field(default_factory=Rules)


class Schedule(Model):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=120)
    sequence: str
    priority: int = Field(default=0, ge=-1000, le=1000)
    enabled: bool = True
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), max_length=7)
    date_from: str = ""
    date_to: str = ""
    yearly: bool = False
    start: str = Field(default="00:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="00:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Europe/Paris"

    @model_validator(mode="after")
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid timezone.") from None
        time.fromisoformat(self.start)
        time.fromisoformat(self.end)
        for value in (self.date_from, self.date_to):
            if value:
                date.fromisoformat(value)
        if any(day not in range(7) for day in self.weekdays):
            raise ValueError("Choose weekdays from Monday to Sunday.")
        if not self.yearly and self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("The event ends before it starts.")
        return self

    def active(self, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo(self.timezone))
        if self.start > self.end and local.time().replace(tzinfo=None) < time.fromisoformat(
            self.end
        ):
            local -= timedelta(days=1)
        if not self.enabled or local.weekday() not in self.weekdays:
            return False
        if self.yearly:
            current, start, end = local.strftime("%m-%d"), self.date_from[5:], self.date_to[5:]
            if start and end and start > end:
                if not (current >= start or current <= end):
                    return False
            elif (start and current < start) or (end and current > end):
                return False
        elif (self.date_from and local.date().isoformat() < self.date_from) or (
            self.date_to and local.date().isoformat() > self.date_to
        ):
            return False
        return during(local.time(), self.start, self.end)


class Configuration(Model):
    enabled: bool = False
    default_sequence: str = ""
    timezone: str = "Europe/Paris"
    sequences: list[Sequence] = Field(default_factory=list, max_length=200)
    schedules: list[Schedule] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid timezone.") from None
        identifiers = [s.id for s in self.sequences]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Sequence IDs must be unique.")
        if self.default_sequence and self.default_sequence not in identifiers:
            raise ValueError("Choose an existing default sequence.")
        if any(s.sequence not in identifiers for s in self.schedules):
            raise ValueError("Every calendar entry needs an existing sequence.")
        return self


def during(current: time, start: str, end: str) -> bool:
    first, last = time.fromisoformat(start), time.fromisoformat(end)
    current = current.replace(tzinfo=None)
    return first == last or (
        first <= current < last if first < last else current >= first or current < last
    )


def probe(path: Path) -> dict:
    executable = shutil.which("ffprobe")
    if not executable:
        raise ValueError("Install ffmpeg and ffprobe on the machine running TorrentLinker.")
    try:
        result = subprocess.run(
            [executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            timeout=30,
            check=True,
        )
        info = json.loads(result.stdout)
        videos = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
        audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
        duration = float(info.get("format", {}).get("duration", 0))
        if (
            len(videos) != 1
            or videos[0].get("codec_name") != "h264"
            or videos[0].get("width", 0) > 1920
            or videos[0].get("height", 0) > 1080
            or any(s.get("codec_name") != "aac" for s in audio)
            or not 0 < duration <= 600
        ):
            raise ValueError()
        return {"duration": duration, "width": videos[0]["width"], "height": videos[0]["height"]}
    except (ValueError, KeyError, subprocess.SubprocessError):
        raise ValueError(
            "Use an MP4 with H.264 video and optional AAC audio, at most 1080p and ten minutes."
        ) from None


class Prerolls:
    def __init__(self, setup):
        self.setup = setup
        self.root = setup.path.parent / "prerolls"
        self.root.mkdir(exist_ok=True)
        self.path = self.root / "library.json"
        self.lock = threading.RLock()
        self.random = random.SystemRandom()
        self.data = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {
                "clips": [],
                "configuration": Configuration().model_dump(),
                "history": {},
            }
        )

    def _save(self):
        atomic_private(self.path, json.dumps(self.data, ensure_ascii=False).encode())

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps({k: self.data[k] for k in ("clips", "configuration")}))

    def configure(self, body):
        config = Configuration.model_validate(body)
        with self.lock:
            self.data["configuration"] = config.model_dump()
            self._save()
        return self.snapshot()

    def clip(self, identifier) -> Clip:
        with self.lock:
            for row in self.data["clips"]:
                if row["id"] == identifier:
                    return Clip.model_validate(row)
        raise ValueError("Pre-roll clip not found.")

    def file(self, identifier) -> Path:
        clip = self.clip(identifier)
        path = (self.root / (clip.id + ".mp4")).resolve()
        if path.parent != self.root.resolve() or not path.is_file() or clip.source == "youtube":
            raise ValueError("Pre-roll clip unavailable.")
        return path

    def add(self, source: Path, title: str, *, rating=None, origin="local", **metadata):
        import hashlib

        limit = 50_000_000 if origin == "community" else 2_000_000_000
        if source.suffix.lower() != ".mp4" or source.stat().st_size > limit:
            raise ValueError("Choose an MP4 within the local 2 GB or Community 50 MB limit.")
        info = probe(source)
        clip = Clip(
            title=title, rating=rating, source=origin, duration=info["duration"], **metadata
        )
        destination = self.root / (clip.id + ".mp4")
        temporary = destination.with_suffix(".tmp")
        try:
            shutil.copyfile(source, temporary)
            if temporary.stat().st_size > limit:
                raise ValueError("The source grew beyond the file limit.")
            probe(temporary)
            with temporary.open("rb") as stream:
                clip.sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            with self.lock:
                if len(self.data["clips"]) >= 2000:
                    raise ValueError("The pre-roll library is full.")
                temporary.replace(destination)
                self.data["clips"].append(clip.model_dump())
                self._save()
        finally:
            temporary.unlink(missing_ok=True)
        return clip.model_dump()

    def import_file(self, path: str, title: str = "", rating=None):
        source = self.setup.path_under_root(path, directory=False)
        return self.add(source, title or source.stem, rating=rating)

    def import_folder(self, path: str):
        folder = self.setup.path_under_root(path)
        results = []
        for source in sorted(folder.glob("*.mp4"))[:200]:
            try:
                results.append({"clip": self.import_file(str(source))})
            except ValueError as error:
                results.append({"name": source.name, "error": str(error)})
        return {"results": results}

    def update(self, identifier, body):
        with self.lock:
            current = self.clip(identifier).model_dump()
            allowed = {"title", "category", "tags", "rating"}
            if set(body) - allowed:
                raise ValueError("Only the clip's title, category, tags and rating can be edited.")
            value = Clip.model_validate({**current, **body}).model_dump()
            self.data["clips"] = [value if r["id"] == identifier else r for r in self.data["clips"]]
            self._save()
        return value

    def delete(self, identifier):
        with self.lock:
            self.clip(identifier)
            self.data["clips"] = [r for r in self.data["clips"] if r["id"] != identifier]
            self._save()
            (self.root / (identifier + ".mp4")).unlink(missing_ok=True)
        return {"ok": True}

    @staticmethod
    def allowed(clip: Clip, feature: dict, actor: Actor = OWNER_ACTOR) -> bool:
        feature_rating = (feature.get("age_rating") or {}).get("rating")
        # Unknown feature/clip ratings cannot broaden what a watcher can see.
        ceiling = SCALE.index(feature_rating) if feature_rating in SCALE else 0
        if actor.age_limit is not None:
            ceiling = min(ceiling, actor.age_limit)
        return clip.rating is not None and SCALE.index(clip.rating) <= ceiling

    @staticmethod
    def matches(rules: Rules, feature: dict, actor: Actor, now: datetime) -> bool:
        kind = "episode" if feature.get("series") or bool(feature.get("episode")) else "film"
        if rules.kind != "any" and rules.kind != kind:
            return False
        if rules.accounts and actor.account not in rules.accounts:
            return False
        if rules.viewers and actor.viewer not in rules.viewers:
            return False
        genres = feature.get("genres", feature.get("genre", []))
        genres = genres if isinstance(genres, list) else re.split(r"[,/|]", str(genres))
        if rules.genres and not {g.casefold() for g in rules.genres} & {
            str(g).strip().casefold() for g in genres
        }:
            return False
        audio = str(feature.get("audio", "")) + " " + str(feature.get("audio_codecs", ""))
        if rules.audio and not any(word.casefold() in audio.casefold() for word in rules.audio):
            return False
        return during(now.time(), rules.start, rules.end)

    def plan(self, feature: dict, actor: Actor = OWNER_ACTOR, *, now=None) -> dict:
        with self.lock:
            config = Configuration.model_validate(self.data["configuration"])
            if not config.enabled or feature.get("kind") != "video":
                return {"steps": []}
            now = now or datetime.now(ZoneInfo(config.timezone))
            local = now.astimezone(ZoneInfo(config.timezone))
            sequences = {s.id: s for s in config.sequences}
            chosen = [
                s.sequence
                for s in sorted(config.schedules, key=lambda s: (-s.priority, s.id))
                if s.active(now)
            ]
            if config.default_sequence:
                chosen.append(config.default_sequence)
            sequence = next(
                (
                    sequences[s]
                    for s in chosen
                    if s in sequences and self.matches(sequences[s].rules, feature, actor, local)
                ),
                None,
            )
            if sequence is None:
                return {"steps": []}
            clips = {
                c.id: c
                for c in map(Clip.model_validate, self.data["clips"])
                if self.allowed(c, feature, actor)
            }
            clips = {
                k: c
                for k, c in clips.items()
                if c.source == "youtube" or (self.root / (k + ".mp4")).is_file()
            }
            history_key = f"{sequence.id}:{actor.account}:{actor.viewer}"
            history = self.data["history"].get(history_key, [])
            steps, used = [], set()
            for step in sequence.steps:
                if step.kind == "pause":
                    steps.append({"kind": "pause", "seconds": step.seconds, "title": "Pause"})
                    continue
                clip = clips.get(step.clip) if step.kind == "clip" else None
                if step.kind in {"random", "trailer"}:
                    pool = [
                        c
                        for c in clips.values()
                        if c.id not in used
                        and (step.kind != "trailer" or c.category == "trailer")
                        and (not step.category or c.category == step.category)
                        and set(step.tags) <= set(c.tags)
                    ]
                    fresh = [c for c in pool if c.id not in history]
                    if not fresh and pool:
                        history = []
                        fresh = pool
                    if fresh:
                        clip = self.random.choice(fresh)
                clip = clip or clips.get(step.fallback)
                if clip is None:
                    continue
                used.add(clip.id)
                history.append(clip.id)
                steps.append(
                    {
                        "kind": "youtube" if clip.source == "youtube" else "clip",
                        "clip": clip.id,
                        "title": clip.title,
                        "seconds": clip.duration,
                        "youtube": clip.youtube,
                    }
                )
            self.data["history"][history_key] = history[-2000:]
            while len(self.data["history"]) > 1000:
                self.data["history"].pop(next(iter(self.data["history"])))
            self._save()
            return {"sequence": sequence.name, "steps": steps}


def prerolls(setup) -> Prerolls:
    root = setup._root or setup
    with root.lock:
        if not hasattr(root, "_prerolls"):
            root._prerolls = Prerolls(root)
        return root._prerolls
