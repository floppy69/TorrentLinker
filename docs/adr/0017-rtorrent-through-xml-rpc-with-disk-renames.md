# rTorrent through its XML-RPC, with confirmed disk renames and no Partial Matches

Seedbox users asked for rTorrent, which most seedboxes run behind ruTorrent. It joins the other Torrent Clients behind the same port (ADR-0009), in `rtorrent.py`. The adapter speaks rTorrent's XML-RPC with the standard library: over HTTP(S) at the address the seedbox publishes (usually `/RPC2`, with the web server's username and password), or directly on rTorrent's SCGI port as `scgi://host:port`. The web interface accepts SCGI over TCP only, never a socket path. rTorrent 0.15.2 is tested in CI, in a Docker image built from Alpine's package (`scripts/rtorrent`).

Most of the port maps directly. rTorrent checks a stopped torrent without starting it, so no speed guard is needed. It reports verified pieces as a hex bitfield. Its states are translated into qBittorrent's names. The port's tags live in a custom field of their own (`torrentlinker_tags`), so the user's ruTorrent label (`custom1`) is never read as a tag or replaced.

## What rTorrent cannot do

- **Rename a file inside a torrent.** rTorrent has no such command. A Reseed whose names differ uses the confirmed disk renames of ADR-0013: the user approves each torrent after seeing every path, the local data is checked first, and a journal restores the names on failure. This extends that exception to rTorrent.
- **Check without creating absent files.** On 0.15.2, a check created each missing file of the torrent inside the user's folder, even a skipped one (priority 0). A Partial Match would write files the app did not create (ADR-0004), so Partial Matches are refused before anything is added.
- **Download sequentially.** rTorrent has no sequential mode: films and series download in its normal order.
- **Delete a torrent's files.** Its XML-RPC only removes the torrent. Removing with files is refused rather than silently keeping them.
- **Create a missing download folder.** A started torrent whose folder is missing stays inactive without saying so. Before a download starts, the adapter asks rTorrent to run `mkdir -p` on its own machine, which may be the seedbox.

## Consequences

- With rTorrent, Partial Matches cannot be Reseeded, and Reseeds with other names need a disk-rename confirmation, as with µTorrent. Disk-rename confirmations remain in the desktop application.
- A seedbox whose rTorrent forbids `execute` commands cannot have download folders created for it; the error names the folder.

Configured client workflows now use the per-client layout choice in ADR-0021. Existing layouts and recovery journals remain intact.
