# Demandes page design preview, #127

Status: layout **A** (list and inspector) chosen by the owner on 2026-11-21, for the
Requests and Wishes of ADR-0022. Implemented in the Web UI Requests page.

Built only from approved components: the shared palette (`panel/base.css`) and the
Community page's stylesheet, embedded in `requests-prototype.html` so it opens anywhere.
The only additions are the segmented margin bar, the ReleaseScore colours from Search,
and the prototype's switcher. Fictional data; nothing is sent anywhere.

Open `requests-prototype.html` directly. `?variant=A` is the chosen layout; B (poster
tiles with a drawer) and C (a board from asked to available in Médias) stay in the file
as the rejected alternatives. The bottom bar also switches light/dark and a tight margin.

Decided:
- **Layout A.** Community's list (search, member filters, rows with cover, release score,
  size and state) beside its inspector: cover and pills, alerts, a segmented control to
  choose the release, the margin bar, the member's quotas, the request's timeline, a note
  for the member, then Accepter / Refuser. A Wish is resolved in the inspector by finding
  the film.
- **Download margin: a bar.** The Owner's c411 margin (upload ÷ 0,8 − download), with the
  downloads in progress still to come, what the Request would take and the other pending
  Requests. Shown at the top of the page and in the inspector; a Request that would go past
  the margin turns red and is flagged, since c411 would block downloading.

Review paths:
- Choose another release for Dune and accept it; the margin, Léa's quotas and the count
  in the sidebar follow.
- Open Hugo's Oppenheimer: rated -12 above his -10 limit, shown as an alert.
- Resolve Léa's Wish ("le dernier Miyazaki") by picking the film, then accept it.
- With "Marge serrée" (60 Go), choose Dune's 71 Go remux: quota and margin alerts.
- History tab: accepted, downloading and refused Requests with their timelines.

The implementation uses tracker release search, the checked download queue and its send receipts. Failed or interrupted sends require Retry; a torrent already present in the client is not added again. Status refresh marks a completed download available once it appears in Médias. Tests use fake tracker and client responses.
