# Persistent symlink layouts for Reseed

The Reseed board in desktop and Web UI uses a dedicated Link Folder to reproduce a torrent's filenames while keeping original files at their existing paths. This is an opt-in alternative to ADR-0002's client renames and ADR-0013/0017's disk renames; those older flows remain available in Local Items. The approved column-board prototype is the design reference.

Links are permanent for the lifetime of a Reseed, not temporary verification files. Their targets use the Torrent Client's Path Mappings, so a link may be dangling from TorrentLinker's own filesystem view. A client-scoped manifest records the original file identities and the exact link layout. Library classification uses this manifest to recognize the original Local Item as Seeded.

The board requires every torrent file, including ignored small files. It verifies source pieces locally before adding the torrent stopped, then verifies again in the Torrent Client before starting it. Archives, incomplete matches and ambiguous candidates stop for review. The board never falls back to a disk rename, creates replacement media, or automatically downloads missing content. It retains link layouts on cancellation or failure; removing them while seeding would break the Reseed.

One shared workflow drives both interfaces. Run all processes each item through search, comparison, links, verification and sharing. Pause takes effect between operations and during local hashing; a client hash check already in flight may finish while paused. Cancellation retains completed steps. Restart never automatically resumes a run or starts a torrent.
