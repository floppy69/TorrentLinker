"""Local Draft snapshots and an explicit, revision-bound handoff to c411."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from torrentlinker.store import Store
from torrentlinker.upload import PreparedUpload, UploadRequest
from torrentlinker.upload_presentation import assess, require_complete

# Desktop and MCP can share a database through separate Store objects in this process.
_active_lock = threading.Lock()
_active_sends: set[tuple[str, str]] = set()


def _key(store: Store, identifier: str) -> tuple[str, str]:
    return str(store.torrent_dir.resolve()), identifier


def reset_local(store: Store, identifier: str, revision: int) -> dict:
    with _active_lock:
        if _key(store, identifier) in _active_sends:
            raise ValueError(
                "This Local Draft is still being sent. Wait for the operation to finish."
            )
        return store.reset_local_draft(identifier, revision)


def edited_form(previous: dict, form: dict) -> dict:
    """Replace the previous hosted image without regenerating the user's presentation."""
    result = dict(form)
    old, new = previous.get("image", ""), form.get("image", "")
    if old and old != new:
        result["description"] = form.get("description", "").replace(
            f"[img]{old}[/img]", f"[img]{new}[/img]" if new else ""
        )
    return result


def file_state(request: UploadRequest) -> list[dict]:
    result = []
    for file in request.files:
        path = request.item.save_path / file.local_path
        stat = path.stat()
        result.append({"path": file.local_path, "size": stat.st_size, "mtime": stat.st_mtime_ns})
    return sorted(result, key=lambda row: row["path"])


def save_local(
    store: Store,
    request: UploadRequest,
    form: dict,
    *,
    identifier: str = "",
    revision: int = 0,
    review: dict | None = None,
) -> dict:
    review = dict(review or {})
    from torrentlinker.upload_assets import Assets
    from torrentlinker.upload_facts import prepare_presentation

    request, form, evidence = prepare_presentation(
        request,
        form,
        Assets(store.torrent_dir.parent),
    )
    completeness = assess(form, evidence, local=True)
    review["file_facts"] = evidence
    review["presentation"] = completeness
    review["refusals"] = list(
        dict.fromkeys(
            [
                *review.get("refusals", []),
                *(f"{f['field']}: {f['message']}" for f in completeness["missing_fields"]),
            ]
        )
    )
    history = store.local_draft(identifier).get("history", []) if identifier else []
    history = [*history, {"at": time.time(), "revision": revision + 1, "action": "saved"}]
    # Saving is metadata-only: no hashing, announce key, remote Draft or seeding.
    return store.save_local_draft(
        {
            "history": history,
            "path": str(request.item.path),
            "form": {**form, "reviewed": False},
            "files": file_state(request),
            "extra": request.extra,
            "review": review or {},
        },
        identifier,
        revision,
    )


def send_local(
    store: Store,
    identifier: str,
    revision: int,
    request: UploadRequest,
    send: Callable[[], PreparedUpload],
) -> PreparedUpload:
    key = _key(store, identifier)
    with _active_lock:
        if key in _active_sends:
            raise ValueError("This Local Draft is already being sent.")
        record = store.local_draft(identifier)
        if record["revision"] != revision:
            raise ValueError("Local Draft changed. Review the current revision before sending.")
        if record["files"] != file_state(request):
            raise ValueError("Local files changed. Save and review the Local Draft again.")
        from torrentlinker.upload_assets import Assets
        from torrentlinker.upload_facts import prepare_presentation

        _, checked_form, evidence = prepare_presentation(
            request,
            record["form"],
            Assets(store.torrent_dir.parent),
        )
        require_complete(checked_form, evidence)
        store.claim_local_draft(identifier, revision)
        _active_sends.add(key)
    try:
        try:
            prepared = send()
        except Exception:
            store.local_draft_outcome(
                identifier,
                "uncertain",
                {
                    "message": (
                        "Send interrupted or failed. Check c411 before allowing another attempt."
                    )
                },
            )
            raise
        store.local_draft_outcome(identifier, "sent", sent_result(prepared))
        return prepared
    finally:
        with _active_lock:
            _active_sends.discard(key)


def sent_result(prepared: PreparedUpload) -> dict[str, Any]:
    return {
        "hash": prepared.meta.infohash,
        "title": prepared.saved.title,
        "draft_id": prepared.saved.draft_id,
        "message": "Draft sent to c411. Review and publish it there. Seeding has not started.",
    }
