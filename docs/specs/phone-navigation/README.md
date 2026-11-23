# Phone navigation preview

Status: layout **A** (side drawer) is what the app ships for now; the owner has not reviewed this preview yet.

Design preview for how the shared web shell is navigated on a phone (650 px wide or less).

Built only from the shared palette (`panel/base.css`), embedded in `phone-navigation-prototype.html` so it opens
anywhere. On a computer it shows a 390 × 844 phone; on a phone it fills the screen. Fictional torrents; nothing is
sent.

Open `phone-navigation-prototype.html` directly; `?variant=A|B|C` picks a layout, the arrows switch, "Membres"
adds Demandes and Notifications, "Thème" switches light and dark.

- **A · Side drawer.** A top bar with ☰, the page title, the client and the status. ☰ opens the desktop sidebar
  over the dimmed page (same list, theme, language, sign-out); a page choice, a tap beside it or Escape closes it.
- **B · Bottom tabs + Plus.** Torrents, Recherche, Médias and Zen always one tap away at the bottom, where the thumb
  is. "Plus" raises a sheet with the other pages as tiles, then theme, language and sign-out. Nothing covers the page
  until you ask for more.
- **C · Icon rail.** A 68 px column of icons with short names is always visible on the left. The TL logo widens it
  to full names and the preferences.

Review paths:
- Open each variant, go from Torrents to Activité and back.
- Turn "Membres" on: the list grows to 14 pages; see which layout still fits.
