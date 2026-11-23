# Upgrade and offline restore checks, 2026-11-20

Refreshed source-level evidence for #50 against application commit `6b9748d8f03c1e176b3746655240799d18d09060`. The checks ran from a clean temporary checkout of that commit, with this report's corrected checker. Canonical checkout edits and the running app were left intact. Environment: Linux, Python 3.13.11, development dependencies. [Raw results](upgrade-restore-2026-11-20.json).

| Source | Upgrade | Second restart | Offline restore | Original backup unchanged |
| --- | --- | --- | --- | --- |
| 0.12.2 | Passed | Passed | Passed | Yes |
| beta.27 | Passed | Passed | Passed | Yes |
| beta.43 | Passed | Passed | Passed | Yes |

The [existing fixture method](upgrade-restore-2026-10-31.md#method) still checks settings, two clients, Library Folders, Download Folders, Path Mappings, Local Draft identities/revisions, queued and interrupted work, conversations, encrypted fixture credentials, attachment bytes and SQLite integrity. All three sources made zero network connections. Keyring access remains blocked; no user data or tracker publication is involved.

The first run exposed an outdated checker comparison. New client profile defaults `reseed_layout` and `reseed_link_root` made whole-dictionary equality fail, while every historical field remained unchanged. The checker now compares historical values recursively, allowing new dictionary fields. It still rejects removed keys, changed values, removed list entries and reordered clients. Five regression tests cover that distinction. This corrects the evidence checker, not an application migration failure.

Reproduce against a clean source checkout:

```sh
.venv/bin/python scripts/check_upgrade.py --refs v0.12.2 v1.0.0-beta.27 v1.0.0-beta.43 --output /tmp/upgrade-results.json
```

#50 stays open. This does not establish installed Windows, Linux AppImage or Docker upgrades, OS-keyring transfers, reverse-proxy workflows, real-user observation or RC readiness. No version, tag or release was published. Repeat against the exact eventual release candidate.
