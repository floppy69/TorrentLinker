"""Reviewed Community transfers. Credentials stay in the host; imports never execute."""

from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import urlencode
from uuid import UUID, uuid4

from pydantic import Field

from torrentlinker import net
from torrentlinker.community_site import SITE_URL
from torrentlinker.feeds import Preferences as FeedPreferences
from torrentlinker.prerolls import Model, prerolls
from torrentlinker.release_score.preferences import Profile
from torrentlinker.studio import studio
from torrentlinker.web.security import atomic_private

KINDS = {"preroll", "studio", "rss", "release-score", "prompt"}
LICENSES = {"own-work", "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "MIT"}


class Rule(Model):
    name: str = Field(min_length=1, max_length=120)
    include: list[str] = Field(default_factory=list, max_length=30)
    exclude: list[str] = Field(default_factory=list, max_length=30)
    category: str = Field(default="", max_length=80)
    query: str = Field(default="", max_length=500)
    categories: list[int] = Field(default_factory=list, max_length=100)
    preferences: FeedPreferences = Field(default_factory=FeedPreferences)


class RSS(Model):
    rules: list[Rule] = Field(min_length=1, max_length=100)


def identifier(value):
    return str(UUID(str(value)))


def portable(kind, data):
    if kind == "release-score":
        return Profile.model_validate(data).model_dump()
    if kind == "rss":
        return RSS.model_validate(data).model_dump()
    if kind == "prompt":
        if (
            set(data) != {"prompt"}
            or not isinstance(data["prompt"], str)
            or not 10 <= len(data["prompt"]) <= 20000
        ):
            raise ValueError("Use a prompt between 10 and 20000 characters.")
        return data
    raise ValueError("Unknown preset kind.")


def scrub(setup, value):
    if isinstance(value, dict):
        return {
            k: scrub(setup, v)
            for k, v in value.items()
            if not re.search(
                r"passkey|password|secret|token|api.?key|username|feed.?url|path|directory|folder|client.?id|endpoint",
                k,
                re.I,
            )
        }
    if isinstance(value, list):
        return [scrub(setup, v) for v in value]
    if not isinstance(value, str):
        return value
    text = setup.secrets.redact(value, public_urls=True)
    text = re.sub(r"(?:https?://|file://|magnet:)[^\s<>\"']+", "[removed]", text, flags=re.I)
    text = re.sub(
        r"(?:\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b[a-f0-9]{32,64}\b)",
        "[removed]",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"(?:[A-Za-z]:[\\/]|/(?:home|Users|tmp|mnt|media|var|etc)/|~/|\\\\)[^\s\"']+",
        "[removed]",
        text,
    )
    text = re.sub(
        r"\b(?:passkey|api[_ -]?key|access[_ -]?token|password|username)\s*[:=]\s*\S+",
        "[removed]",
        text,
        flags=re.I,
    )
    names = [p.name for p in setup.settings.client_profiles]
    cached = getattr(setup.profile_workspace(), "data", {}).get("api") or {}
    names.append(str(cached.get("username", "")))
    for name in names:
        if len(name) >= 3:
            text = re.sub(re.escape(name), "[name removed]", text, flags=re.I)
    return text


class CommunityItems:
    def __init__(self, site):
        self.site, self.setup = site, site.setup
        self.stages = {}
        self.root = self.setup.path.parent / "community-imports"
        self.root.mkdir(exist_ok=True)

    def stage(self, value):
        now = time.time()
        for key, row in list(self.stages.items()):
            if row["expires"] < now:
                self.stages.pop(key)
                if row.get("temporary"):
                    row["path"].unlink(missing_ok=True)
        if len(self.stages) >= 16:
            raise ValueError("Finish or cancel an existing Community review first.")
        key = uuid4().hex
        self.stages[key] = {**value, "expires": now + 900}
        return key

    def get(self, key):
        row = self.stages.get(key)
        if row is None or row["expires"] < time.time():
            raise ValueError("Review expired. Prepare it again.")
        return row

    def prepare(self, body):
        kind = body["kind"]
        if kind not in KINDS:
            raise ValueError("Unknown creation kind.")
        supplied = body.get("metadata", {})
        meta = {
            key: scrub(self.setup, supplied.get(key, ""))
            for key in ("title", "description", "category", "notes")
        }
        meta.update(
            kind=kind,
            license=supplied.get("license", "CC-BY-4.0"),
            tags=scrub(self.setup, supplied.get("tags", [])),
            rights=True,
        )
        if (
            not 3 <= len(meta["title"]) <= 120
            or not 10 <= len(meta["description"]) <= 4000
            or not 2 <= len(meta["category"]) <= 60
            or meta["license"] not in LICENSES
        ):
            raise ValueError("Check title, description, category and licence.")
        if supplied.get("itemId"):
            meta["itemId"] = identifier(supplied["itemId"])
        source = body.get("source", {})
        preview = None
        if kind == "preroll":
            path = prerolls(self.setup).file(source["id"])
            payload = path.read_bytes()
            filename, mime = "preroll.mp4", "video/mp4"
            preview = {"bytes": len(payload), "clip": prerolls(self.setup).clip(source["id"]).title}
        elif kind == "studio":
            workspace = studio(self.setup)
            path = workspace.bundle(source["id"], source.get("assets", []), community=True)
            try:
                # Preserve structural IDs/hashes while removing names, paths and credentials
                # from every user-authored string in the manifest.
                import zipfile

                with zipfile.ZipFile(path) as archive:
                    manifest = json.loads(archive.read("project.json"))
                    p = manifest["project"]
                    p["license"] = meta["license"]
                    for key in ("name", "creator", "license"):
                        p[key] = scrub(self.setup, p[key])
                    for track in p["tracks"]:
                        track["name"] = scrub(self.setup, track["name"])
                        for clip in track["clips"]:
                            clip["text"] = scrub(self.setup, clip["text"])
                    for index, asset in enumerate(manifest["assets"]):
                        asset["name"] = f"Media {index + 1}"
                    import io

                    target = io.BytesIO()
                    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
                        output.writestr("project.json", json.dumps(manifest))
                        for asset in manifest["assets"]:
                            output.writestr(
                                "assets/" + asset["id"], archive.read("assets/" + asset["id"])
                            )
                    payload = target.getvalue()
                    preview = manifest
            finally:
                path.unlink(missing_ok=True)
            filename, mime = "project.tlstudio", "application/zip"
        else:
            data = portable(kind, scrub(self.setup, body.get("data", {})))
            preview = {
                "format": "torrentlinker-community",
                "schemaVersion": 1,
                "kind": kind,
                "data": data,
            }
            payload = json.dumps(preview, ensure_ascii=False, indent=2).encode()
            filename, mime = "preset.json", "application/json"
            if len(payload) > 250000:
                raise ValueError("Shared presets must fit 250 KB.")
        if len(payload) > 50_000_000:
            raise ValueError("Community uploads are limited to 50 MB.")
        key = self.stage(
            {
                "operation": "publish",
                "metadata": meta,
                "payload": payload,
                "filename": filename,
                "mime": mime,
                "identity": self.site._link().get("identity"),
            }
        )
        return {
            "review": key,
            "metadata": meta,
            "content": preview,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def download(self, body):
        item = identifier(body["id"])
        detail = self.site._json(
            self.site._request("GET", f"/api/items/{item}", authenticated=True)
        )
        # API returns {item, versions}; never trust a URL supplied by remote metadata.
        record = detail.get("item", detail)
        versions = detail.get("versions", [])
        version = (
            next((v for v in versions if str(v["id"]) == str(body.get("version", ""))), None)
            if body.get("version")
            else next(iter(versions), None)
        )
        if not version or record.get("kind") not in KINDS:
            raise ValueError("Choose a published creation version.")
        version_id = identifier(version["id"])
        expected = version.get("sha256", "")
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError("Creation checksum missing.")
        token = self.site._link().get("token")
        if not token:
            raise ValueError("Link this app to the community first.")
        temporary = self.root / (
            uuid4().hex + (".mp4" if record["kind"] == "preroll" else ".download")
        )
        limit = 50_000_000 if record["kind"] in {"preroll", "studio"} else 250000
        try:
            digest, length = hashlib.sha256(), 0
            with net.client(
                timeout=60, follow_redirects=False, transport=self.site.transport
            ) as client:
                with client.stream(
                    "GET",
                    f"{SITE_URL}/api/items/{item}/download?version={version_id}",
                    headers={"Authorization": "Bearer " + token},
                ) as response:
                    if response.status_code != 200:
                        raise ValueError("Creation download unavailable.")
                    with temporary.open("wb") as stream:
                        for chunk in response.iter_bytes(65536):
                            length += len(chunk)
                            if length > limit:
                                raise ValueError("Creation exceeds its download limit.")
                            digest.update(chunk)
                            stream.write(chunk)
            if digest.hexdigest() != expected or length != int(version["bytes"]):
                raise ValueError("Creation checksum or size mismatch.")
            if record["kind"] == "preroll":
                from torrentlinker.prerolls import probe

                preview = probe(temporary)
            elif record["kind"] == "studio":
                import zipfile

                with zipfile.ZipFile(temporary) as archive:
                    entry = archive.getinfo("project.json")
                    if entry.file_size > 2_000_000:
                        raise ValueError("Project manifest too large.")
                    from torrentlinker.studio import Project

                    manifest = json.loads(archive.read(entry))
                    preview = {
                        "project": Project.model_validate(manifest["project"]).model_dump(),
                        "assets": manifest.get("assets", []),
                    }
            else:
                envelope = json.loads(temporary.read_text())
                if (
                    envelope.get("format") != "torrentlinker-community"
                    or envelope.get("schemaVersion") != 1
                    or envelope.get("kind") != record["kind"]
                ):
                    raise ValueError("Unsupported preset format.")
                preview = portable(record["kind"], envelope["data"])
            metadata = {
                "id": item,
                "version": int(version["version"]),
                "kind": record["kind"],
                "title": str(record.get("title", "Community creation")),
                "license": record.get("license", ""),
                "sha256": expected,
            }
            key = self.stage(
                {
                    "operation": "import",
                    "path": temporary,
                    "temporary": True,
                    "metadata": metadata,
                    "content": preview,
                }
            )
            return {
                "review": key,
                "metadata": metadata,
                "content": preview,
                "bytes": length,
                "notice": "Import creates a local copy. Existing edits are kept.",
            }
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def request(self, action, body):
        if action == "browse":
            kind = body.get("kind", "")
            if kind and kind not in KINDS:
                raise ValueError("Unknown creation kind.")
            response = self.site._request(
                "GET",
                "/api/items?"
                + urlencode(
                    {
                        "kind": kind,
                        "q": str(body.get("q", ""))[:200],
                        "offset": max(0, min(10000, int(body.get("offset", 0)))),
                    }
                ),
                authenticated=True,
            )
            if not response.is_success:
                self.site._json(response)
            rows = response.json()
            if not isinstance(rows, list):
                raise ValueError("Invalid Community list.")
            return {"items": rows}
        if action == "prepare":
            return self.prepare(body)
        if action == "download":
            return self.download(body)
        if action == "updates":
            path = self.root / "imports.json"
            history = json.loads(path.read_text()) if path.exists() else []
            latest = {}
            for saved in history:
                if not body.get("kind") or saved["kind"] == body["kind"]:
                    latest[saved["id"]] = saved
            rows, unavailable = [], 0
            offset = max(0, int(body.get("offset", 0)))
            for saved in list(latest.values())[offset : offset + 30]:
                try:
                    item = self.site._json(
                        self.site._request(
                            "GET", "/api/items/" + identifier(saved["id"]), authenticated=True
                        )
                    )
                    versions = [
                        v for v in item.get("versions", []) if v.get("status") == "published"
                    ]
                    if versions and int(versions[0]["version"]) > saved["version"]:
                        newest = versions[0]
                        rows.append(
                            {
                                **item,
                                **newest,
                                "id": item["id"],
                                "version_id": newest["id"],
                                "installed_version": saved["version"],
                            }
                        )
                except ValueError:
                    unavailable += 1
            return {
                "items": rows,
                "unavailable": unavailable,
                "next_offset": offset + 30 if len(latest) > offset + 30 else None,
            }
        if action == "history":
            path = self.root / "imports.json"
            return {"items": json.loads(path.read_text()) if path.exists() else []}
        row = self.get(body["review"])
        if action == "cancel":
            self.stages.pop(body["review"], None)
            if row.get("temporary"):
                row["path"].unlink(missing_ok=True)
            return {"ok": True}
        if body.get("confirmed") is not True:
            raise ValueError("Review the content and confirm first.")
        if action == "publish" and row["operation"] == "publish":
            if row["identity"] != self.site._link().get("identity"):
                raise ValueError("Community account changed. Prepare a new review.")
            result = self.site._json(
                self.site._request(
                    "POST",
                    "/api/items",
                    authenticated=True,
                    data={"metadata": json.dumps(row["metadata"])},
                    files={"file": (row["filename"], row["payload"], row["mime"])},
                )
            )
            self.stages.pop(body["review"], None)
            return result
        if action == "apply" and row["operation"] == "import":
            meta = row["metadata"]
            kind = meta["kind"]
            if kind == "preroll":
                result = prerolls(self.setup).add(
                    row["path"],
                    meta["title"][:150],
                    origin="community",
                    community_id=meta["id"],
                    community_version=meta["version"],
                )
            elif kind == "studio":
                result = studio(self.setup).import_bundle(row["path"], source_project=meta["id"])
            else:
                result = row["content"]
            path = self.root / "imports.json"
            history = json.loads(path.read_text()) if path.exists() else []
            history.append({**meta, "local_id": result.get("id", ""), "imported": time.time()})
            atomic_private(path, json.dumps(history[-2000:]).encode())
            from torrentlinker.achievements import record_completion

            record_completion(self.setup.path.parent, "community-import", meta["id"])
            self.stages.pop(body["review"], None)
            row["path"].unlink(missing_ok=True)
            return {"kind": kind, "data": result, "metadata": meta}
        raise ValueError("Unknown Community operation.")
