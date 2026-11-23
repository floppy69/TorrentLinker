# Shared application shell (#115)

The approved #88 design uses `web/static/shell/view.html` in both hosts. The same bundled view renders navigation, the page heading and description, the target-client selector, the Zen band, update notices and shortcut help. Regions receive explicit host snapshots and accept only their permitted commands. They share the panel palette and English/French strings.

The desktop adapter is `gui/shell_host.py`; the Web adapter is `web/static/shell_host.js`. Native decoding, workspace services and job ownership remain outside the view. The native QListWidget navigation, title/description labels, client combo, Zen labels and update buttons have been removed, along with their separate Web renderers. Torrents no longer has a duplicate client selector. Selecting a client through its tracker hierarchy uses the shell owner.

All clients is offered only in Torrents. Leaving that page restores a specific client before scoped work starts. Web remembers the previously selected enabled client, falling back to the configured default. Desktop retains its active profile behind aggregate mode. A refused desktop client switch preserves aggregate mode. Selecting a different desktop client retains the existing workspace replacement and job guards.

At narrow widths navigation becomes a page selector. Theme and language remain available. Desktop language changes update existing bundled environments, preserving drafts, selections and Media ownership instead of replacing the workspace. Native Ctrl+1 through Ctrl+8, Ctrl+, and Ctrl+F retain their behavior. Shortcut help describes the host-specific behavior.

The Zen band uses the existing profile, seeding, Plan and catalogue services. It appears on Zen and the related Library, Upload, Search and RSS workspaces. The Web loads its summaries when opening those pages directly. Client-scoped summaries are guarded against stale responses. Profile problems use explanatory bilingual text.

Update checks use the version of the running host and the existing validated release checker/cache. The Web endpoint requires authentication. A Web notice explicitly refers to updating the server installation. Dismissal lasts for the current session; a different release can be shown later.

Deliberate platform differences:

- Browser shortcuts remain reserved for the browser. Navigation and help controls are available without overriding them.
- Web login, sign-out and global Activity remain Web services. Proxy-authenticated sessions have no sign-out action.
- Desktop settings persist locally; Web language/theme preferences belong to the browser.
- Desktop status messages and background-job indicators retain their existing host controls. The Zen summary itself is shared.

Verification covers simulated clients and temporary settings, aggregate restoration/refusal, English/French headings, both themes, narrow navigation, shortcut help, update dismissal, authenticated server-version checks, and real-display desktop rendering. No live tracker posting or user-library mutation is part of these checks.

Acceptance evidence on 19 November 2026: the desktop regression group passed 80 tests; the real-display shell check passed four tests, including draft retention and narrow rendering. Browser regression groups covered all CI browser files, including the final 21-test Media/Plan/Settings group. Repository-wide Ruff and mypy checks passed. Screenshots were inspected at 390 pixels on Web and 600/1100 pixels on desktop in English/French and light/dark themes.
