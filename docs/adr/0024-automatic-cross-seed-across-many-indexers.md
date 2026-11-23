# Automatic Cross-seed across many Indexers

Users keep asking for cross-seed: seeding the same data on every tracker they belong to. Until now TorrentLinker had one Indexer, c411, and Reseeds waited for a review, one Match at a time. Reseed already covered one direction by hand: local files, including other trackers' torrents, matched to c411 torrents.

TorrentLinker now has many Indexers and cross-seeds in both directions, automatically. Indexers come from a Prowlarr or Jackett instance in one step, or are added by hand as a Torznab URL and key; c411 stays one of them. Every torrent in the Torrent Client, once complete, and every Library Item is a source. Each is searched on the other Indexers, by IMDb or TMDb id where the Indexer supports it, by name otherwise. A Full Match, or a Partial Match covering at least 95 % of the torrent (a setting), is added without a review: stopped, verified at 100 % by the client's hash check, then started, with missing files skipped and never downloaded. A Partial Match under the threshold, or a Match inside an archive, waits for review. The layout follows the same per-client choice as a Reseed (ADR-0021). A Cross-seed carries the tag `cross-seed` plus its Indexer's name and keeps the original's category and save path, so the user's own client rules keep working. It is an independent torrent: removing the original leaves it alone, and TorrentLinker flags it if its data disappears.

We set no search cap of our own, but each Indexer's rate limits and `Retry-After` are obeyed, and c411 keeps its hourly budget and its Catalogue-first search. Cross-seed is a tab of the Reseed board (activity and review) with Indexers and rules in Settings; it is the Owner's alone, since it acts on the Owner's tracker accounts (ADR-0022).

This extends ADR-0001: still our own engine and cross-seed's borrowed matching rules, now across many Indexers and without a click for safe Matches.

## Considered Options

- **Drive the cross-seed daemon**: rejected again (ADR-0001); a second service to run, hardlink layouts, and no review board or Catalogue.
- **Review every Match**: rejected; with many Indexers the board would never empty. Safe Matches (Full, or Partial above the threshold, always verified) go in alone.
- **Hardlinks or a per-Indexer layout**: rejected for the one per-client layout Reseed already has.
- **A cap of our own on searches**: rejected by the Owner; the Indexers' own limits and c411's budget are kept.
- **Removing Cross-seeds with their original**: rejected; they are torrents of their own, possibly still seeding from the same data.

## Consequences

Settings move from one Indexer to a list, with secrets per Indexer and a migration that keeps c411 as the first. Searches run on download completion and over the whole library, so a backlog of searches is queued and paced per Indexer. "Cross-seed" leaves the glossary's Avoid list.
