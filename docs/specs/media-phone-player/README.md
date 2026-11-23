# Phone video player preview

Status: layout **C** (Plein écran + mini-barre) chosen by the owner on 2026-11-22.

Design preview for playing a video in Médias on a phone (650 px wide or less). Today a video opens in a boxed
player in the corner of the page, with no close button.

Built only from the shared palette (`panel/base.css`), embedded in `media-phone-player-prototype.html`. On a
computer it shows a 390 × 844 phone; on a phone it fills the screen. The film is a moving gradient.

Open the file directly; `?variant=A|B|C` picks a layout. Press "Reprendre" to play. "Tourner le téléphone" shows
landscape.

- **A · Plein écran.** Like a streaming app: the video fills a black screen; a tap shows ← and the title, −10 s,
  play/pause, +10 s, the timeline, "Audio et sous-titres" and full screen, which hide again after 3 s. ← stops and
  returns to the page.
- **B · Vidéo en haut + fiche.** The video sits at the top in 16:9 with its details, versions and actions below. ⌄
  shrinks it to a mini bar above the page; × stops. Landscape fills the screen.
- **C · Plein écran + mini-barre.** As A, but ← does not stop: the film keeps playing in a mini bar at the bottom of
  Médias; a tap brings it back full screen, × stops.
