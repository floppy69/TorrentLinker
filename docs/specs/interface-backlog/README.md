# Approved interface backlog designs

The owner approved all three review areas on 19 November 2026: "Design is good go ahead."

- #79: Zen Catalogue, Plan, Seeding and the Zen band. Implementation: #90, #92, #93 and #94.
- #87: Settings Connections, Clients, Companion, Agent access, Assistant, General, Library Folders, Download Folders, Client Paths, Search & Matching and Zen. Implementation: #112 and #113.
- #88: the application shell and Documentation. Implementation: #114 and #115.

The approved [standalone prototype](https://github.com/Vietnoirien/TorrentLinker/blob/c871785deb9e1f4310826d5116d8db55e547a258/docs/specs/interface-backlog/prototype.html), [review paths and parity decisions](https://github.com/Vietnoirien/TorrentLinker/blob/c871785deb9e1f4310826d5116d8db55e547a258/docs/specs/interface-backlog/README.md) and [implementation boundaries](https://github.com/Vietnoirien/TorrentLinker/blob/c871785deb9e1f4310826d5116d8db55e547a258/docs/specs/interface-backlog/implementation.md) are archived at commit `c871785` on the separate prototype branch. Their pending-review wording describes the draft before this approval.

Use the existing shared palette and component language. Each production page has one bundled view for desktop and Web. Keep the approved designs of existing pages, including Profile. Do not copy the throwaway prototype's simulated services into production.

Verification uses public services and desktop/browser workflows, temporary settings and libraries, simulated Torrent Clients, both languages/themes, narrow viewports and a real-display desktop rendering check. No live tracker posting or user-library mutations are part of validation. Preserve drafts and selection across refreshes, and retain existing client ownership, secret storage, confirmation and cancellation rules.

The approval covers these designs. It does not change #89's outstanding packaged-platform playback measurements or the decision to retain native decoding.

The subsequent owner corrections require globally paged Seeding for 10,000+ torrents and the current Torrents row design for Plan. Plan's full controls remain present in a collapsible card that starts open and preserves values. The [corrected Plan prototype](https://github.com/Vietnoirien/TorrentLinker/blob/82137a9/docs/specs/interface-backlog/prototype.html) records the restored controls and row styling. Native playback remains the decision for #89; the remaining packaged-platform measurements are tracked separately in #122.

The next review clarified that the approved component includes the filter bar, expandable Seed and c411 filters, independent MiB/GiB size toggles and clickable column-header sorting from #103. It is not a standalone sort dropdown. Seeding now reuses the actual Torrents filter component. Plan uses the same compact field and table styling, with proposal search, category/action filters and column-header sorting.

Plan must expose minimum torrent count and minimum seeders, alongside its existing maximums, sizes, budget and destinations. The owner explicitly confirmed that minimum torrents means count. A Plan that cannot meet that count must explain the shortfall while respecting every other limit. Destination clients each have their own card, with selection beside the name and budget below. These corrections are recorded in the [updated prototype](https://github.com/Vietnoirien/TorrentLinker/blob/46f2820/docs/specs/interface-backlog/prototype.html). Settings sections also retain a consistent 16-pixel gap between section title and first card.
