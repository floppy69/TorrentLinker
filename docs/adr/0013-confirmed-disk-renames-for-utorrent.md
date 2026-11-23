# Confirm disk renames for µTorrent Reseeds and Upload seeding

µTorrent Classic 3.6's WebUI cannot rename individual files inside a torrent. On 2026-10-24 the user chose to allow disk renames after a confirmation showing all affected paths, rather than refuse every Reseed or Upload whose release names differ. This is a µTorrent-only exception to ADR-0002, ADR-0004 and ADR-0011. Other Torrent Clients retain the existing behavior.

Approval is per torrent, never remembered globally. The warning explains that existing torrents and other applications can lose track of renamed files. Complete local piece verification precedes renaming; µTorrent must still verify all files before starting. No existing destination is overwritten, file contents stay unchanged, and a journal bound to the µTorrent connection permits restoration after a failed or interrupted setup. Restoration refuses changed files or occupied original names. Partial Matches remain unsupported because this WebUI does not report verified pieces.

## BitTorrent Classic

BitTorrent Classic 7.11 uses the same WebUI protocol and file-renaming limitation. The same per-torrent confirmation and verification rules apply. Live tests against build 47391 on 2026-10-24 covered single-file and multifile Reseeds, confirmed disk renames, Upload seeding and rejection of incorrect data. This extends the exception above to BitTorrent Classic. BitTorrent Web is a separate protocol variant and is not covered.

Configured client workflows now use the per-client layout choice in ADR-0021. Existing layouts and recovery journals remain intact.
