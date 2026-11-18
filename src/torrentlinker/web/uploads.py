"""Server-side Upload preparation with the desktop category profiles."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from torrentlinker.client_limits import client_name
from torrentlinker.options import category_options, options_body
from torrentlinker.paths import PathMapper
from torrentlinker.scan import scan_item
from torrentlinker.torrent_details import web_url
from torrentlinker.upload import (
    PROFILES,
    PreparedUpload,
    UploadRequest,
    create_upload,
    default_category,
    missing_options,
    seed_upload,
    upload_files,
)
from torrentlinker.upload_presentation import assess, extend_template
from torrentlinker.upload_queue import edited_form, save_local, send_local, sent_result
from torrentlinker.web.library import Library
from torrentlinker.web.setup import Setup


class FieldProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["research", "user_supplied", "unknown"] = "unknown"
    source: str = Field(default="", max_length=2048)


class UploadForm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def path_belongs_to_operation(cls, values):
        if isinstance(values, dict) and "path" in values:
            raise ValueError(
                "Put the Local Item path in operation.path (or "
                "preview_upload/save_upload_draft path), not inside upload. upload"
                " contains metadata only."
            )
        return values

    manual_source: bool = False
    workflow_step: int = Field(default=1, ge=1, le=5)
    existing_reviewed: bool = False
    category: int | None = None
    subcategory: int | None = None
    source: str = Field(default="", max_length=200)
    image: str = Field(default="", max_length=2048)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=15000)
    nfo: str = Field(default="", max_length=100000)
    nfo_origin: Literal["", "generated", "original"] = ""
    options: dict[int, list[int]] = Field(default_factory=dict, max_length=50)
    assets: list[str] = Field(default_factory=list, max_length=24)
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict, max_length=50)
    reviewed: bool = False


class Uploads:
    def __init__(self, setup: Setup, library: Library):
        self.setup = setup
        self.library = library
        self.prepared: dict[str, tuple[PreparedUpload, str]] = {}

    def prepare(
        self, path: str, form: UploadForm, stop: threading.Event, *, stored: bool = False
    ) -> tuple[UploadRequest, dict[str, Any]]:
        if form.manual_source:
            from torrentlinker.domain import ContentKind

            content_kind = ContentKind.OTHER
        elif stored:
            folder = next(
                (
                    f
                    for f in self.setup.settings.library_folders
                    if Path(path).is_relative_to(f.path)
                ),
                None,
            )
            if folder is None:
                raise ValueError("This Local Draft's Library Folder was removed.")
            content_kind = folder.kind
        else:
            content_kind = self.library.entry(path).folder.kind
        self.library.check_tree(Path(path), stop)
        item = scan_item(Path(path))
        cid = form.category or default_category(content_kind)
        profile = PROFILES.get(cid) if cid is not None else None
        if profile is None:
            raise ValueError("Choose a supported Upload Category.")
        ignore = self.setup.settings.matching.ignore
        profile.inspect(item, ignore)
        sub = form.subcategory or profile.default_subcategory(item, ignore)
        if sub not in {s.id for s in profile.subcategories}:
            raise ValueError("Choose a subcategory from the selected Upload Category.")
        title = form.title or profile.suggested_name(item, ignore, form.source, sub)
        if not title or title in {".", ".."} or any(c in title for c in "/\\\x00"):
            raise ValueError("Use a release name without directory separators.")
        files = upload_files(item, title, ignore, profile.media_extensions)
        types = (
            category_options(self.setup.store, self.setup.indexer().category_options, sub)
            if self.setup.secrets.get("indexer-api-key")
            else []
        )
        chosen = (
            form.options
            if stored
            else (form.options or profile.suggested_options(item, ignore, types))
        )
        for kind in types:
            values = chosen.get(kind.id, [])
            if len(values) > (100 if kind.multiple else 1) or not set(values).issubset(
                {v.id for v in kind.values}
            ):
                raise ValueError("Invalid category option.")
        image = web_url(form.image)
        if form.image and not image:
            raise ValueError("Use a direct HTTP(S) image link.")
        description = form.description or extend_template(
            profile.category, sub, profile.description(title, files, form.source, image)
        )
        if image and image not in description:
            description = f"[center][img]{image}[/img][/center]\n" + description
        nfo = form.nfo or profile.nfo(title, files)
        request = UploadRequest(
            item,
            title,
            files,
            nfo,
            description,
            profile.category,
            sub,
            options_body(types, chosen),
            profile.draft_fields(item, ignore, files),
        )
        refusals = profile.refusals(item, ignore, sub) + missing_options(types, chosen)
        from torrentlinker.provenance import Provenance

        original_names = Provenance(self.setup.store.torrent_dir.parent).names(item)
        preview: dict[str, Any] = {
            "original_names": original_names,
            "title": title,
            "category": profile.category,
            "subcategory": sub,
            "subcategories": [asdict(s) for s in profile.subcategories],
            "files": [asdict(f) for f in files],
            "nfo": nfo,
            "description": description,
            "options": [asdict(t) for t in types],
            "chosen": chosen,
            "refusals": [f"{r.problem.value}: {r.detail}" for r in refusals],
            "warnings": [
                f"{w.judgement.value}: {w.detail}" for w in profile.warnings(item, ignore, sub)
            ],
        }
        from torrentlinker.upload_assets import Assets
        from torrentlinker.upload_facts import prepare_presentation

        request, prepared_form, evidence = prepare_presentation(
            request,
            form.model_dump(),
            Assets(self.setup.store.torrent_dir.parent),
            generated_description=not form.description,
            generated_nfo=not form.nfo,
        )
        preview.update(
            description=request.description,
            nfo=request.nfo,
            nfo_origin=prepared_form["nfo_origin"],
            assets=prepared_form["assets"],
        )
        completeness = assess(
            {
                **form.model_dump(),
                **{
                    key: preview[key]
                    for key in ("category", "subcategory", "title", "nfo", "description")
                },
            },
            evidence,
            local=True,
        )
        preview["presentation"] = completeness
        preview["file_facts"] = evidence
        extraction = evidence.get("artwork_extraction", {})
        if extraction.get("remaining") or extraction.get("error_count"):
            preview["warnings"].append(
                f"Artwork extraction: {extraction.get('remaining', 0)} candidates deferred, "
                f"{extraction.get('error_count', 0)} unreadable. See file_facts.artwork_extraction."
            )
        preview["refusals"].extend(
            f"{f['field']}: {f['message']}" for f in completeness["missing_fields"]
        )
        return request, preview

    def queue(
        self,
        path: str,
        form: UploadForm,
        stop: threading.Event,
        identifier: str = "",
        revision: int = 0,
    ) -> dict:
        if identifier:
            record = self.setup.store.local_draft(identifier)
            if record["path"] != path:
                raise ValueError("A Local Draft cannot be moved to another Local Item.")
            form = UploadForm.model_validate(edited_form(record["form"], form.model_dump()))
        request, preview = self.prepare(path, form, stop, stored=bool(identifier))
        values = form.model_dump()
        values.update(
            {
                key: preview[key]
                for key in ("title", "category", "subcategory", "nfo", "description")
            }
        )
        values["options"] = preview["chosen"]
        values["nfo_origin"] = preview["nfo_origin"]
        values["assets"] = preview["assets"]
        return save_local(
            self.setup.store,
            request,
            values,
            identifier=identifier,
            revision=revision,
            review={"warnings": preview["warnings"], "refusals": preview["refusals"]},
        )

    def send(
        self, identifier: str, revision: int, stop: threading.Event, progress: Callable[[Any], None]
    ) -> dict:
        record = self.setup.store.local_draft(identifier)
        if record["revision"] != revision:
            raise ValueError("Local Draft changed. Review the current revision before sending.")
        if record["status"] == "sent":
            return record["result"]
        form = UploadForm.model_validate({**record["form"], "reviewed": True})
        request, preview = self.prepare(record["path"], form, stop, stored=True)
        request = replace(request, extra=record.get("extra", request.extra))
        if (
            preview["refusals"]
            or not web_url(form.image)
            or not form.description.strip()
            or not form.nfo.strip()
        ):
            raise ValueError("Resolve the Upload refusals and add a hosted image before sending.")
        if not self.setup.secrets.get("announce-url"):
            raise ValueError("Set your Announce URL before sending to c411.")
        indexer = self.setup.indexer()
        directory = self.setup.path.parent / "uploads"
        directory.mkdir(exist_ok=True)
        prepared = send_local(
            self.setup.store,
            identifier,
            revision,
            request,
            lambda: create_upload(
                request,
                self.setup.secrets.get("announce-url"),
                directory,
                indexer.save_draft,
                self.setup.store,
                report=lambda done, total: progress({"done": done, "total": total}),
                stopped=stop.is_set,
            ),
        )
        client_path = PathMapper(self.setup.settings.path_mappings).to_qbit(str(request.item.path))
        self.prepared[prepared.meta.infohash] = (prepared, client_path)
        return sent_result(prepared)

    def draft(
        self, path: str, form: UploadForm, stop: threading.Event, progress: Callable[[Any], None]
    ) -> dict:
        if not form.reviewed:
            raise ValueError("Review the Upload description, files and category warnings first.")
        request, preview = self.prepare(path, form, stop)
        if preview["refusals"]:
            raise ValueError("Resolve the Upload refusals before saving the Draft.")
        if not web_url(form.image):
            raise ValueError("Add a hosted image to the description before saving the Draft.")
        directory = self.setup.path.parent / "uploads"
        directory.mkdir(exist_ok=True)
        prepared = create_upload(
            request,
            self.setup.secrets.get("announce-url"),
            directory,
            self.setup.indexer().save_draft,
            self.setup.store,
            report=lambda done, total: progress({"done": done, "total": total}),
            stopped=stop.is_set,
        )
        client_path = PathMapper(self.setup.settings.path_mappings).to_qbit(str(request.item.path))
        self.prepared[prepared.meta.infohash] = (prepared, client_path)
        return {
            "hash": prepared.meta.infohash,
            "title": prepared.saved.title,
            "draft_id": prepared.saved.draft_id,
            "message": (
                "Draft saved. Review and publish it on c411. It has not been seeded automatically."
            ),
        }

    def seed(self, hash: str, stop: threading.Event) -> dict:
        record = self.prepared.get(hash)
        if record is None:
            raise ValueError("This prepared Upload is not available in this server session.")
        prepared, client_path = record
        if not any(
            prepared.saved.item_path.is_relative_to(folder.path)
            for folder in self.setup.settings.library_folders
        ):
            raise ValueError("This Upload's Library Folder was removed. Register it again first.")
        current_path = PathMapper(self.setup.settings.path_mappings).to_qbit(
            str(prepared.saved.item_path)
        )
        if current_path != client_path:
            raise ValueError(
                "This Upload's Path Mapping changed. Review its destination before seeding."
            )
        self.library.check_tree(prepared.saved.item_path, stop)
        item = scan_item(prepared.saved.item_path)
        client = self.library.client()
        if client.requires_disk_renames:
            raise ValueError(
                f"{client_name(client)} cannot rename files inside a torrent. Seed this "
                "Upload from the desktop application, which shows the files to rename on disk."
            )
        result = seed_upload(client, self.setup.store, item, prepared)
        return {"hash": result, "status": "verifying"}
