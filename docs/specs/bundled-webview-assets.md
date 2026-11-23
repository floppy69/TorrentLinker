# Shared WebViews in packaged desktop builds

Issue #123 fixes asset paths that pass through a directory symlink, including PyInstaller's macOS Frameworks-to-Resources layout. `BundledView` resolves its asset directory once at construction. Requests, initial navigation and every allow-list entry then use the same canonical root.

The boundary still permits only the named assets. Directory-prefix access is not allowed. An unlisted script, navigation outside `view.html`, or a named asset symlink pointing outside the root remains blocked. The newly added Torrents audit script is explicitly included in that named list.

Packaged `--smoke-test` now opens the real shared shell header and checks its rendered title, nonzero geometry and loaded theme styles. It fails after 20 seconds if the page stays blank. Existing Linux, Windows and macOS release jobs already run this command, so the packaged macOS `.app` now exercises WebEngine as well as native playback and Library scanning.

The Linux reproduction first passed with a real assets directory and failed with the same directory reached through a symlink. Both pass after the fix. Regression coverage also checks shared CSS/JavaScript, the audit script, forbidden scripts, an escaping asset symlink and forbidden navigation. A separate smoke test renders the actual shared header. This validates the bundle layout on Linux; a packaged macOS run remains part of release CI, and no release was published for this change.
