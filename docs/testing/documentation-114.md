# Shared Documentation, issue #114

The main desktop and Web Documentation pages load `static/documentation/view.html`. The native QTextBrowser implementation and the Web shell's separate guide renderer are removed. The shared reader has guide filtering, Back/Forward, an independent guide-language selector, local images and Open online. Assistant citations open the same reader in a nonmodal desktop dialog with the requested heading visible.

The existing authenticated standalone `/documentation/…` URLs remain available for Web citations and agent references. Their Markdown uses the same server renderer, escaping embedded HTML and blocking remote images; they remain plain document links rather than another application workspace.

## Verification

The native workflow was first red against the old widget and passed after the shared view was connected. The Web workflow was first red without its frame and passed after integration. The checks found and fixed the guide-language selector's accessible name and a late-image scroll reset.

The final focused run passed 17 tests across Documentation, Web guides, agent citations, reverse-proxy mounts and the existing full Web setup/navigation workflow. Ruff, formatting, mypy and whitespace checks pass. Browser tests cover English/French, light/dark host state, independent guide language, filtering, empty results, history, bundled images, server failure/retry, leaving/reopening the page and 390-pixel layout. Guide path allowlists and authenticated image routes retain their existing checks.

A separate real-display check passed on DP-4 with xcb and GPU rendering disabled, rendering English/dark and French/light at 1280 × 800. The French/light capture was visually inspected. Tests use bundled guides and temporary app state. No tracker or Torrent Client actions are required.

Guide history and language live in the open reader, matching the existing per-window behavior. Native external links open through the desktop browser; Web links use ordinary browser navigation. The application package remains 1.0.0b43.

Final browser capture run: 2 passed. [Desktop](documentation-114-desktop.png) and [390-pixel Web](documentation-114-web-mobile.png) captures were inspected. The current Web shell remains outside this page and is replaced separately by #115.
