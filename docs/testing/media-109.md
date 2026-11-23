# Media music in the shared WebView (#109), 19 November 2026

## Checks

The browser tests in `tests/test_web_media_browser.py` pass with `TL_WEB_BROWSER=1`: 3 passed, including the shared video panel regression. Albums, artists, tracks, album details, Add to queue, playlist saves and the paused music bar now run inside the Media frame.

The desktop Media, startup and controls regression run passed with 26 passed and 1 opt-in browser check skipped. The desktop Media tests (`test_media_desktop.py`, `test_media_video_panel.py`), `test_startup.py`, `test_controls.py`, `test_media_api.py`, `test_web_navigation.py` and `test_i18n.py` pass under `LC_ALL=C.UTF-8`. The desktop music test plays a track from the view, adds two tracks to the native queue, saves one playlist from the player and one from the view, and switches back to Video with the track still playing.

Real display: the desktop Media tab ran with `QT_QPA_PLATFORM=xcb` on screen DP-4. Albums, Artists and Tracks rendered with the playlist column, and a track played in the native player bar. On this GNOME Wayland machine the page stays black under xcb unless `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` is set. The app adds that flag only for the Wayland platform, so the check used it by hand.

Ruff check, ruff format, mypy and `git diff --check` pass.

## Test boundaries

Tests use temporary Library Folders and simulated clients. They do not contact a real torrent client or c411.

## Limits

The player, its queue and the compact chat stay with each host until #110 and #111. The native "Remove from Continue watching" control is gone with the native shelves. It was already unreachable since #108 hid those shelves in Video, and Music never showed them.

The browser was tested headless only. No Windows or macOS run was made.

## Continuation verification

The continuation fixed late worker responses after panel deletion, synchronized the native playlist selector after shared-view saves/deletes, preserved Music selection for contextual chat, and translated missing-metadata and accessible labels. Playlist creation retains the playback Torrent Client while browsing another; replacement refuses a queue owned by another client.

The real-display Music workflow passed again on DP-4 with xcb and GPU rendering disabled. The captured Tracks view was inspected at 800 × 800. Browser tests exercise shared Music alongside Video, playback, playlist persistence and both languages/themes. No real tracker or Torrent Client actions were performed.
