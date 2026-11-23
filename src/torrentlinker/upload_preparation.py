"""Preparation tools for a saved Upload Draft, shared by both interfaces."""

from __future__ import annotations

import shutil
from pathlib import Path

from torrentlinker.reseed_layout import needs_disk_rename_review
from torrentlinker.web.uploads import UploadForm


def prepare_tool(uploads, action, body, stop, report):
    record = uploads.setup.store.local_draft(body["id"])
    path = Path(body["path"])
    if str(path) != record["path"]:
        raise ValueError("Select the source of this saved Draft.")
    uploads.library.check_tree(path, stop)
    if stop.is_set():
        raise ValueError("Preparation cancelled.")
    if action == "seed-upload":
        from torrentlinker.torrent_meta import read_torrent
        from torrentlinker.upload import PreparedUpload, seed_upload
        from torrentlinker.upload_queue import file_state

        if record["status"] != "sent" or body.get("revision") != record["revision"]:
            raise ValueError("Choose the sent revision of this Draft.")
        request, _ = uploads.prepare(
            str(path), UploadForm.model_validate(record["form"]), stop, stored=True
        )
        if file_state(request) != record["files"]:
            raise ValueError("Local files changed since this Draft was sent.")
        saved = next(
            (
                s
                for s in uploads.setup.store.uploads()
                if s.infohash == record["result"].get("hash") and s.item_path == path
            ),
            None,
        )
        if saved is None:
            raise ValueError("The saved torrent is unavailable.")
        torrent = uploads.setup.path.parent / "uploads" / (saved.title + ".torrent")
        meta = read_torrent(torrent.read_bytes())
        if meta.infohash != saved.infohash:
            raise ValueError("The saved torrent changed. Review the upload before seeding.")
        prepared = PreparedUpload(saved, meta, request.files)
        client = uploads.library.client()
        if needs_disk_rename_review(client) and uploads.approve_disk_renames is None:
            raise ValueError(
                "This client requires disk renaming. Use the desktop application "
                "to review the file changes before seeding."
            )
        report({"phase": "submitting", "cancellable": False})
        if stop.is_set():
            raise InterruptedError("Seeding cancelled before client submission.")
        return {
            "hash": seed_upload(
                client,
                uploads.setup.store,
                request.item,
                prepared,
                approve_disk_renames=uploads.approve_disk_renames,
            ),
            "status": "verifying",
            "path": str(path),
        }
    if action in {"model-inspect", "model-render"}:
        from torrentlinker import upload_models

        if action == "model-inspect":
            return upload_models.inspect(uploads, str(path), stop, registered=False)
        return upload_models.render(
            uploads,
            str(path),
            body.get("files", []),
            body.get("cameras", {}),
            stop,
            report,
            registered=False,
        )
    if action == "model-geometry":
        import numpy as np

        from torrentlinker.mesh import limit_triangles, load_mesh
        from torrentlinker.upload_models import local_models

        _, paths = local_models(uploads, str(path), stop, registered=False)
        source = paths.get(body.get("file"))
        if source is None or source.suffix.lower() not in {".stl", ".obj", ".3mf"}:
            raise ValueError("Select a previewable piece from this Draft.")
        if source.stat().st_size > 16_000_000:
            raise ValueError(
                "Live preview is limited to 16 MB. Use a rendered preview for this piece."
            )
        mesh = limit_triangles(load_mesh(source), 2000)
        if not mesh.triangle_count or not np.isfinite(mesh.vertices).all():
            raise ValueError("This piece has no finite geometry to display.")
        low, high = mesh.bounds()
        scale = float(max(high - low)) or 1
        vertices = (mesh.vertices - (low + high) / 2) / scale
        return {"triangles": vertices[mesh.triangles].tolist()}
    if action in {"archive-preview", "archive-extract"}:
        from torrentlinker.archives import unpack, unpacked
        from torrentlinker.scan import scan_item

        target = unpacked(scan_item(path))
        if target is None:
            raise ValueError("Select a readable ZIP, RAR or 7z archive.")
        destination = target.item.path
        if body.get("destination") and body["destination"] != str(destination):
            from dataclasses import replace

            from torrentlinker.agent.desktop import DesktopSetup
            from torrentlinker.domain import LocalItem

            chosen = Path(body["destination"])
            if not chosen.is_absolute() or chosen.name in {"", ".", ".."}:
                raise ValueError("Choose an absolute destination for extraction.")
            parent = chosen.parent.resolve(strict=True)
            if isinstance(uploads.setup, DesktopSetup):
                if parent not in getattr(uploads.setup, "_upload_destinations", set()):
                    uploads.setup.path_under_root(str(parent))
            else:
                uploads.setup.path_under_root(str(parent))
            chosen = parent / chosen.name
            old = target.item.path
            if target.into != old and chosen.name != old.name:
                raise ValueError("Keep the archive’s top-level folder name in the destination.")
            files = {
                str(Path(chosen.name) / Path(name).relative_to(old.name)): size
                for name, size in target.item.files.items()
            }
            target = replace(
                target, into=chosen if target.into == old else parent, item=LocalItem(chosen, files)
            )
            destination = chosen
        if destination.exists():
            raise ValueError("The extraction destination already exists. Choose its files instead.")
        free = shutil.disk_usage(destination.parent).free
        stat = path.stat()
        fingerprint = f"{stat.st_size}:{stat.st_mtime_ns}"
        preview = {
            "destination": str(destination),
            "size": target.size,
            "files": len(target.item.files),
            "free": free,
            "fingerprint": fingerprint,
        }
        if action == "archive-preview":
            return preview
        if body.get("destination") != str(destination) or body.get("fingerprint") != fingerprint:
            raise ValueError("The archive changed. Review the extraction again.")
        if free < target.size:
            raise ValueError("Not enough free disk space to unpack this archive.")
        # Web roots must also allow the new destination. Desktop grants only the
        # sibling destination calculated from this explicitly selected archive.
        from torrentlinker.agent.desktop import DesktopSetup

        if isinstance(uploads.setup, DesktopSetup):
            uploads.setup._folder_candidate = destination
        else:
            uploads.setup.path_under_root(str(destination.parent))

        def progress(done, total):
            if stop.is_set():
                raise InterruptedError("Extraction cancelled.")
            report({"done": done, "total": total})

        unpack(target, progress)
        uploads.setup.store.remember_unpacked(destination, path)
        form = UploadForm.model_validate(
            {**record["form"], "manual_source": True, "workflow_step": 2, "reviewed": False}
        )
        saved = uploads.queue(str(destination), form, stop)
        return {"draft": saved, "destination": str(destination)}
    raise ValueError("Unknown Upload preparation tool.")
