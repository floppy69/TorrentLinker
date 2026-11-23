"""Recover only retained evidence; never infer lifetime totals from present files."""

from __future__ import annotations

import json

from torrentlinker.achievements import seeding, torrent_identity


def recover(sync, agent):
    """Explicit owner scan. Reads configured clients without changing their torrents."""
    if agent is None:
        raise ValueError("The local application service is not ready.")
    playlists = seeded = unavailable = 0
    history_allowed = sync.ledger.history_recovery_allowed("owner")
    if history_allowed:
        media = agent.media
        with media.lock:
            rows = list(
                media.db.execute(
                    "SELECT * FROM media_playlists WHERE account='owner' AND viewer='' LIMIT 10000"
                )
            )
            for row in rows:
                try:
                    ids = json.loads(row["items"])
                    if not ids or len(ids) > 1000:
                        continue
                    tracks = [media.record(row["client"], identifier) for identifier in ids]
                    if not all(json.loads(track["body"])["kind"] == "music" for track in tracks):
                        continue
                    playlists += int(
                        sync.ledger.complete("owner", "playlist", row["id"], recovered=True)
                    )
                except (ValueError, KeyError, TypeError):
                    continue
    # Old reseed states, saved RSS rules and arbitrary render files are not
    # recheck/test/completion evidence. Their history starts with the new hooks.
    for profile in agent.setup.settings.client_profiles:
        if not profile.enabled:
            continue
        try:
            setup = agent.setup.for_client(profile.id)
            for torrent in setup.client().torrents(with_files=False):
                if seeding(torrent.state, torrent.progress):
                    seeded += int(
                        sync.ledger.complete(
                            "owner",
                            "already-seeding",
                            torrent_identity(torrent.hash),
                            recovered=True,
                        )
                    )
        except Exception:
            unavailable += 1
    return {
        "playlistsRecovered": playlists,
        "seedingObserved": seeded,
        "unavailableClients": unavailable,
        "reseedHistoryEstimated": False,
        "historicalPlaylistsSkipped": not history_allowed,
    }
