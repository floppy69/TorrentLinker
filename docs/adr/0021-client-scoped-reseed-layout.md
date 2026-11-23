# One Reseed layout choice per Torrent Client

Issue #116 makes the Reseed board and Local Items use the same client-profile choice. Clients that can rename paths inside a torrent default to that layout and need no Link Folder. Links remain an explicit option for keeping the torrent's original paths, including cross-seed setups. µTorrent Classic, BitTorrent Classic and rTorrent require links because their renames would change original files on disk.

This supersedes ADR-0020's unconditional Link Folder requirement for the board and ADR-0013/0017's disk-rename path for configured client workflows. Low-level recovery of existing disk-rename journals remains available. Changing the preference affects new preparation; saved layouts keep their recorded mode, and older manifests without a mode remain link layouts. TorrentLinker never converts or removes those layouts automatically.

The board still requires every torrent file, checks source identities and hashes locally, and verifies in the Torrent Client before seeding. Its verification remains separate from the automatic Local Items verifier so an explicit Verify step cannot start sharing. Links require their persistent manifest and source identities to remain valid. Client renames retain the occupied-source guard, settling checks and Path Mappings from ADR-0002. Existing originals are never moved by the configured workflows.

Automatic Local Items link manifests are keyed by client and torrent hash, separately from board progress keyed by Local Item. Several Full Matches for one item can verify independently without replacing its prepared board layout.
