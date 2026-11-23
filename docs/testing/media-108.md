# Media video browsing in the shared WebView (#108), 19 November 2026

## Checks

The browser tests in `tests/test_web_media_browser.py` pass with `TL_WEB_BROWSER=1`: 2 passed. One of them pauses a music track, switches to Video and back. The music bar hides in Video and comes back in Music.

The desktop Media tests (`test_media_video_panel.py`, `test_media_desktop.py`) and `test_startup.py` pass under `LC_ALL=C.UTF-8`: 23 passed, 1 skipped. The native decoding tests in that set cover playback with local subtitles, H.264 preview and multitrack switching.

Before the last two fixes, the full suite ran with 2,116 passed, 205 skipped and 1 failed. The failure was an outdated native toolbar assertion, which was updated and passes on its own. The two final changes only affect the WebView scripts, so the full suite was not run again.

Ruff check, ruff format, mypy and `git diff --check` pass.

## Test boundaries

Tests use temporary Library Folders and simulated clients. They do not contact a real torrent client or c411. Native decoding is still tracked in #89. Music (#109), the player (#110) and chat (#111) are separate issues.

## Limits

With the shell locale set to `fr_FR.UTF-8`, five desktop Media tests fail: three native playback tests, the video home rows test and the desktop video panel test. They expect English labels such as "Recently added". These failures also occur without this change. They pass under `C.UTF-8`.

The browser was tested headless only. No Windows or macOS run was made.
