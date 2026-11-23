# Shared RSS panel, issue #102

The owner approved the category-aware editor extension on 2026-11-18, then
requested an info button explaining its selection icons. The existing RSS page
layout remains the reference in `../rss-redesign.md`. The approved prototype is
archived at `e3f4d33` on local branch `prototypes/rss-categories-102`, file
`docs/specs/rss-guided/category-prototype.html`.

Both hosts load `web/static/feeds/view.html`. The page keeps its subscription
sidebar, header actions, filters, inbox selection toolbar, client comparison and
saved selections. One editor replaces the native criteria/editor widgets and the
old Web implementation. Desktop opens the existing shared readonly details dialog;
Web opens Search's shared details tabs. Both can queue an RSS saved selection with
an explicit client and configured Download Folder.

## Category rules

Size and seeders are shared limits. Category badges identify the scope of each
metadata criterion. Only criteria applicable to selected categories are rendered,
including in ranking controls. Incompatible saved rules have a separate read-only
summary and explicit removal action; no new unrelated rule can be added there. New criteria take the selected relevant Torznab categories,
including known descendants. Existing criteria without a scope remain global;
opening and saving them does not silently change their meaning. Changing the
subscription's source categories preserves stored rules and their scopes.
Removing a criterion then configuring it without categories clears its old scope.

The source of truth is Torznab category IDs, not native c411 Search IDs. Some
Applications, Games, Emulation, GPS and Nulled entries share Torznab IDs; RSS cannot
distinguish native categories that the source has collapsed. Category names come
from the configured indexer. Unknown categories expose no guessed metadata criteria. No
platform, format or licence is inferred from a release name. Structured platform
and licence attributes are retained when the RSS source supplies them; their
presence on c411 is not guaranteed. Required or excluded metadata that is missing
remains unverifiable, including when the release has no category information.

The legend explains Prefer, Require, Avoid and Clear, scope badges, missing
metadata and keyboard access to preference ordering. Selection and scroll survive
periodic inbox refresh. An open editor is not replaced by polling. Language
changes translate open-form labels while retaining inputs.

## Verification and lifecycle

The owner confirmed public RSS/subscription and queue services plus desktop/Web
workflows and rendering as test boundaries. Fixtures simulate sources and clients;
no live tracker download or client mutation is performed.

Desktop operations use the shared Qt worker pool, including its client-switch and
shutdown coordination. Replies in either host are checked against the selected
client. Saving is locked while in progress, and cancelling a pending preview does
not submit its subscription. Approval and automatic-download budgets remain
service-enforced.

Validation results and the local commit will be recorded on #102. This document
does not claim a release or push.

Local validation: 64 browser acceptance tests passed, plus the RSS desktop test on
Wayland. The full suite reported 2,131 passed and 186 skipped, with one lazy-startup
regression: reading the RSS environment started the desktop service while hidden.
The host now reads its existing settings without starting that service. The failed
startup test and RSS desktop workflow both pass after that fix. Ruff and mypy pass.
