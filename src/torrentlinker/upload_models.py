"""Application-owned 3D inspection and rendering jobs for all frontends."""

from __future__ import annotations

import base64
from pathlib import Path

from torrentlinker.model_rendering import Camera, inspect_models, render_models
from torrentlinker.scan import scan_item
from torrentlinker.upload_assets import Assets, publish_render_pages


def local_models(uploads, path, stop, *, registered=True):
    if registered:
        uploads.library.entry(path)
    uploads.library.check_tree(Path(path), stop)
    item = scan_item(Path(path))
    paths = {
        name: item.save_path / name
        for name in item.files
        if Path(name).suffix.lower()
        in {".stl", ".obj", ".3mf", ".step", ".stp", ".blend", ".f3d", ".sldprt", ".gcode"}
    }
    return item, paths


def inspect(uploads, path, stop, *, registered=True):
    item, paths = local_models(uploads, path, stop, registered=registered)
    result = inspect_models(list(paths.values()), stop)
    # The tool uses file names relative to the Local Item's parent, just like Uploads.
    reverse = {str(value): key for key, value in paths.items()}
    for row in result["models"]:
        row["file"] = reverse[row["file"]]
        row["group"] = str(Path(row["file"]).parent)
    result["path"] = str(item.path)
    return result


def render(uploads, path, pieces, cameras, stop, progress, *, registered=True):
    item, paths = local_models(uploads, path, stop, registered=registered)
    if not pieces:
        pieces = list(paths)
    if len(set(pieces)) != len(pieces) or any(name not in paths for name in pieces):
        raise ValueError("Select distinct file names from inspect_3d_models for this Local Item.")
    if set(cameras) - set(pieces):
        raise ValueError("Camera keys must name selected pieces.")
    states = []
    for name in pieces:
        values = dict(cameras.get(name, {}))
        preset = values.pop("preset", "isometric")
        states.append(Camera.preset(preset, **values))
    result = render_models([paths[name] for name in pieces], states, stop, progress)
    assets = Assets(uploads.setup.store.torrent_dir.parent)
    reverse = {str(value): key for key, value in paths.items()}
    pages = result.pop("pages")
    artifacts = publish_render_pages(
        pages, assets, str(item.path), result["renderer"], reverse, pieces
    )
    images = [
        {"type": "image", "mimeType": "image/png", "data": base64.b64encode(page["png"]).decode()}
        for page in pages
    ]
    result["covered"] = [reverse[name] for name in result["covered"]]
    for row in result["unsupported"]:
        row["file"] = reverse[row["file"]]
    return {
        **result,
        "artifacts": artifacts,
        "content": images,
        "notice": "Private local renders. Public hosting is required only before sending.",
    }
