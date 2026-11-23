"""Public display data for the same Plan on either host."""

from dataclasses import asdict

from torrentlinker.plan import Plan, ReseedSource
from torrentlinker.plan_diagnostics import issue_text


def plan_data(
    proposed: Plan,
    *,
    client_id: str = "default",
    download_speed: float | None = None,
    indexer_keys: int = 1,
) -> dict:
    """The desktop Plan's summary and rows, without serializing private torrent data."""
    return {
        "issues": [{**asdict(issue), "message": issue_text(issue)} for issue in proposed.issues],
        "provisional": True,
        "rows": [
            {
                "hash": i.candidate.infohash,
                "title": i.candidate.title,
                "size": i.candidate.size,
                "download_size": i.candidate.download_size,
                "reseed": i.candidate.reseed,
                "path": (
                    str(i.candidate.source.entry.item.path)
                    if isinstance(i.candidate.source, ReseedSource)
                    else ""
                ),
                "seeders": i.candidate.seeders,
                "category": i.candidate.category,
                "zen": i.zen,
                "note": i.note,
                "folder": str(i.candidate.folder) if i.candidate.folder else "",
                "client_id": i.candidate.client_id or client_id,
            }
            for i in proposed.items
        ],
        "zen": proposed.zen_added,
        "size": proposed.download_size,
        "excluded": len(proposed.on_disk),
        "on_disk": [asdict(row) | {"path": str(row.path)} for row in proposed.on_disk],
        "average_note": proposed.average_note,
        "payback_days": proposed.payback_days,
        "sending_seconds": proposed.sending_seconds(max(1, indexer_keys)),
        "download_seconds": (proposed.download_seconds(download_speed) if download_speed else None),
        "storage": plan_storage(proposed),
    }


def plan_storage(proposed: Plan) -> list[dict]:
    return [
        {
            "folder": str(space.folder),
            "free": space.free,
            "reserved": space.reserved,
            "download": space.download,
            "after_plan": space.after_plan,
        }
        for space in proposed.disk_spaces
    ]
