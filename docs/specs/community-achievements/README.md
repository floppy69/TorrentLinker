# Community achievements

Local implementation of [issue #163](https://github.com/Vietnoirien/TorrentLinker/issues/163). The product design is in the site repository's `docs/community-linker-design.md`; the deployed website v0.3.0 implements its side of the contract. This app work is not published yet.

## Eligibility and coverage

The private SQLite ledger records qualifying completions, separately for each local actor and Site Account. Matching torrent identities form a set, so repeated operations and peer imports cannot add the same torrent twice. Full reseeds qualify at 1, 10 and 100 distinct torrents only after a successful complete recheck and a later complete-and-seeding observation. Issuing `start`, queued/checking states, partial reseeds and old layout flags do not qualify. Both the guided board and legacy reseed flow use the same ledger.

Saved non-empty music playlists, completed Studio renders with output artifacts, live-tested then saved identical RSS configurations, and validated Community imports retain durable completion evidence. Viewer's playlists have separate local attribution and are never submitted through the Owner's Site Account.

An explicit history check can recover retained valid Owner playlists and recognise currently complete seeding torrents under the separate Already seeding badge. It does not estimate historical reseed totals from current inventory, old job states, arbitrary videos or saved RSS rules. Historical imported items without retained validation evidence are not guessed. The UI shows tracking start and scan coverage. Recovered events never enter the future-only sharing queue. After changing Site Accounts, legacy playlists cannot be adopted into the new account; the separate current-state seeding scan remains available.

Current reseed adapters supply the v1 infohash from the verified torrent metadata; supported clients normalize states before observation. The ledger accepts full v1 or v2 identifiers, but does not infer aliases from truncated v2 hashes. A future v2-only reseed adapter must supply its verified canonical identity before participating in these milestones.

## Consent and account isolation

Sharing starts off. Future sharing and submitting existing badges are separate actions. The site must first allow achievements for the linked app. Queued submissions are bound to the authenticated Site Account and consent epoch. Opt-out, expiry, unlinking, a changed linked token or a changed account cancels stale queues. Renewed consent never silently backfills old badges.

“Pause on this installation” immediately cancels its queue and stops its submissions. Account-wide opt-out is the linked site's consent action, where the user chooses whether to keep or hide published badges. It invalidates the site epoch for every installation. Other installations are not disabled by a local pause. Hiding is not deletion.

The site receives only allowlisted codes, definition version and consent epoch through a short-lived `achievements:write` capability. No torrent identifiers, names, paths, trackers, RSS rules, project contents, peer addresses or raw ledger pages are sent. Badges are app-reported and confer no community contribution progress or essential permissions.

Account changes select a separate ledger partition. Detaching immediately selects a fresh unattributed partition, so new activity cannot enter the previous account's history. A previous partition is recovered only when the authenticated Site Account matches again. A membership-secret rotation changes the opaque account identity, requiring explicit re-link/re-pair; old history is not silently assigned to that new identity.

## Paired installations

Pairing is independent of site badge sharing. Both installations must enable site pairing consent, exchange and review invitations, and confirm the counterpart. At most four peers are retained. Each installation explicitly supplies a private LAN/VPN IP address and port. No router ports are opened and no cloud relay receives ledger data.

Peers use TLS 1.3 with pinned certificates in both directions. The account proof binds a certificate fingerprint to a different installation of the same Site Account, expires after five minutes, and can be consumed once. Each synchronization session verifies fresh proofs in both directions before sending ledger evidence. The private key is persisted only through the application's secret store; short-lived private files are used to load it into the TLS context.

Peer HTTP sessions last at most two minutes and are bound to the pinned certificate and current account. Each request is capped at 500 KB and each ledger page at 500 events. Reconciliation is an idempotent set union, including when peers reconnect after being offline. Conflicting records converge on the earliest qualifying evidence with a canonical tie break. If this makes an implicit future submission historical, it is removed from the queue; explicit consent to share existing badges is preserved. Bounded reconciliation saves both cursors across sessions and reports completion only after both ends are reached. Removal immediately invalidates sessions and removes trust for future exchanges. Previously merged evidence remains local.

Background synchronization runs every five minutes, with one deterministic initiator per pair. Site and peer failures back off to at most hourly attempts. An unavailable site prevents fresh peer authentication; evidence remains local until connectivity returns. The implementation uses Python's [mutual TLS verification](https://docs.python.org/3/library/ssl.html) and cryptography's [certificate builder](https://cryptography.io/en/stable/x509/reference/).

## Backups, reset and controls

Settings → Join the community contains the same collection and controls in desktop Qt WebEngine and Web UI. The desktop panel uses the running application's service, avoiding a second consent cache. The original local preview is in `preview/`.

Private JSON backups contain only versioned ledger pages and their opaque account identity, not keys, consent or pending uploads. A reviewed restore validates every page before merging into the same authenticated account. It stops sharing and removes pairings. Unknown schemas are rejected. Local reset also removes local progress and peer trust, and does not delete published badges. Larger ledgers above the 50,000-event JSON export bound require a private application-data backup.

The ledger and all mutations are behind the Owner route/desktop bridge. There is no generic HTTP endpoint for claiming arbitrary achievements. Member-only visibility of published collections, assets and profiles is enforced by the separate website.

## Local verification

Tests at the user-approved seams include qualifying operation handlers with fake clients, actor/account isolation, persistence, deduplication, consent, backup/reset, real localhost mutual TLS, proof replay and removal, Owner/member authorization, a real browser and native Qt WebEngine. The opt-in `tests/test_achievement_site_contract.py` exercises the actual local website on port 3192, creates only disposable local fixtures, and cleans them afterward. It rejects production URLs.

Run `TL_WEB_BROWSER=1 pytest -q tests/test_achievement_browser.py` for the Web Settings flow and `pytest -q tests/test_achievement_native.py` for the native panel. Run `TL_ACHIEVEMENT_SITE=http://localhost:3192 pytest -q tests/test_achievement_site_contract.py` only against the separate local site Compose project. Ordinary tests never contact the owner's torrent clients, tracker or real Site Account.

Verification on 2026-11-22: the full suite reported 3,210 passed, 280 skipped and two native video failures caused by shared Qt rendering state. Those tests now use the existing process-isolation helper; all 13 native media tests passed afterward. The final affected service/hook run passed 112 tests with one skip. Separate browser, native settings, TLS peer and disposable local-site contract runs passed. Ruff, formatting and mypy passed. This is not a claim of a second fully green full-suite run, Windows validation or a release build. Both code reviews completed with no remaining findings.

The account link uses `/{locale}/space/account` in both Web UI and the native URL opener. Account and consent links have their own spacing above action buttons; browser geometry and native navigation checks cover the reported regression.
