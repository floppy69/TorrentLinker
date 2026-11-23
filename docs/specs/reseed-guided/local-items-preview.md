# Local Items controls preview, issue #96

Review requested by the owner on 2026-11-18 before implementing the design gaps.
The approved Reseed page and #95 folder dialog are retained. Only compact folder
and seed-state filters, expandable pack episodes, and Combine controls are added.
This is a single focused version, as requested, rather than alternative layouts.

Run from the repository:

```sh
python3 -m http.server 18775 --bind 127.0.0.1 --directory docs/specs/reseed-guided
```

Open `http://127.0.0.1:18775/local-items-prototype.html?mode=desktop`, or use
`mode=web`. The bottom switch changes hosts without changing the layout.

## Review paths

- Expand/collapse Au fil des saisons. Select an episode to inspect it.
- Filter to /media/Séries and Orphelins. The pack remains as context, while only
  matching episodes can be selected through Select list.
- Select S01E02 and S01E03, then Combine selection. Inspect the member list and
  create the simulated group. The original rows remain.
- Select the pack and an episode together: the preview explains the overlap.
- Select items in different registered folders: this prototype refuses it.
  Production must use the existing service's common-parent and mapping checks,
  not this simplified fixture rule. Existing qBittorrent support is unchanged.
- Clear the selection; use Replay to reset fixtures; try a query with no results.
- At 390px, controls wrap and an item opens the existing inspector drawer.

All data is in memory. No requests, disk operations, client actions or tracker
writes are made. Desktop/Web interactions and the 390px layout were checked
in the browser. No automated tests were added for this throwaway preview.

Approved by the owner on 2026-11-18 for desktop and Web implementation.
The exact preview is archived at `167716a` on the local branch
`prototypes/library-local-items-96`. Keep the existing Library layout and add
only the controls and grouping reviewed here. The simplified same-folder
fixture check does not replace the existing common-parent validation.

## Implementation

The production page remains `web/static/reseed/view.html`, shared by the desktop
WebView and Web iframe. Folder and seed-state filters combine with search and
workflow stages. A pack remains visible as context when only its episodes match;
that context row cannot enter Select list. Selection survives filtering and can
be cleared explicitly.

Combine uses the public Library service on both hosts. It accepts 2–100 real
Local Items, rejects pack/episode overlap, and retains the existing qBittorrent,
Content Kind, common-parent and Path Mapping checks. The named virtual group
appears beside its original items; it never moves or copies files. Groups remain
available during the host session, including page reloads, and are isolated by
client. They are not persisted across an app/server restart.

The native Local Items tree and Web table were removed. Advanced candidate,
evidence and repair tools remain in their existing review interfaces for #97
and #98. Their batch actions remain available there. Folders and Activity retain
their approved presentation.

Validation includes the public Library service, real browser pack/filter/Combine
flows, native bridge client isolation, and rendered Wayland checks. A 5,000-item
browser fixture verifies combined filtering and incremental initial rendering.
The existing list still adds rows while scrolling; bounding that accumulated DOM
is a possible future performance improvement, not a new layout in this change.
