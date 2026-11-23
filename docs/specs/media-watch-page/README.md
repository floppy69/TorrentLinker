# Approved theatre design

Approved by the owner on 2026-11-22 after the theatre preview walkthrough.

- The full-width theatre player scrolls with the page, with controls at the bottom.
- The large library hero is the pinned selection: backdrop, poster, title, facts and actions.
- The compact menu contains Home, Films, Series, Resume, search and Media Center; extra controls are grouped under Options. The two-colour wordmark appears in the topbar only in enlarged view, avoiding a duplicate beside the sidebar.
- The menu remains visible above the pinned banner. It only hides while scrolling over the theatre player.
- The cover and title align just below the menu; the library eyebrow label is removed.
- A poster click selects the banner. Play starts that selection.
- The enlarged poster accompanies the full synopsis, always visible. Compact cards show language, genre, version and file size; playback/download controls sit at the bottom.
- The banner stays 380 px high, or 300 px on short screens. Its cover slot, title and bottom actions keep the same positions across films. Only the synopsis scrolls when needed. Missing or broken artwork shows the transparent TL mark in the same cover slot.
- The watched action is an eye icon, green when watched. The info popover contains file details.
- Rows have no visible horizontal scrollbar. Unboxed arrows follow a small See all link, shown only when the row overflows or more items are available. The grid offers Back to rows.
- Desktop and Web use the same view. Leaving player fullscreen keeps Media Center active.

The working preview is `theatre-prototype.html`. The earlier variants below were rejected and are retained only as design history.

---

# Médias with the player in the page

Design preview, not decided yet. Médias keeps its Netflix-style browsing, and the player becomes part of the
page, like YouTube, on every screen: no floating box, no separate screen.

Built only from the shared palette (`panel/base.css`), embedded in `media-watch-prototype.html`. The bottom bar
switches the layout, the device (phone, phone in landscape, computer) and Media Center (enlarged) mode. The film
is a moving gradient.

Shared by all three layouts:
- **Top bar.** It sits over the film instead of pushing the page, hides while you scroll down and comes back
  as soon as you scroll up.
- **Calm selection.** The selected film no longer stays pinned while the rows scroll; choosing another card
  fades the picture behind the title, nothing moves.
- **Player.** A tap shows −10 s, play/pause, +10 s, the timeline, full screen and ×. While a film plays, a card
  plays its film.

Layouts, `?variant=A|B|C`:
- **A · Lecteur fixé en haut.** The picture stays at the top while the details and rows scroll under it
  (YouTube on a phone).
- **B · Mini-lecteur en défilant.** The player scrolls away with the page and a mini player takes over at the
  bottom; a tap on it goes back to the top (YouTube on a computer).
- **C · Lecteur + À suivre à côté.** On a computer the player and its details on the left, what comes next on
  the right; on a phone it behaves like A.
