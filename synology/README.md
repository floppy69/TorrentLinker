# TorrentLinker — Synology DSM 7.3 / 7.4

This directory contains **additive** packaging work for the user's fork.
The original application code from [Vietnoirien/TorrentLinker](https://github.com/Vietnoirien/TorrentLinker)
must not be changed. The integrity check below is the first required gate.

## Target

- Native Synology Package Center installation (`.spk`), without Docker.
- Run the TorrentLinker application **on the NAS**, with its Python runtime and
dependencies shipped in the package.
- Browser access directly to the NAS on TorrentLinker's existing **port 8787**.
- No DSM desktop launcher, no DSM application window, no Web Station dependency.
- Run as a restricted package account; preserve application state on upgrades.
- Target compatible Synology architectures for DSM 7.3 and DSM 7.4 after
compilation and testing on each ABI. No `noarch` claim for native binaries.

## Source policy

The upstream baseline commit is recorded in [upstream.sha](upstream.sha).

- No original file may be edited, deleted, renamed, or replaced.
- All new project files must live under `synology/`, except the dedicated
  `.github/workflows/synology-integrity.yml` check.
- Generated build files must be created outside the checked-out source tree.
- Later upstream updates require an explicit review of this baseline and a
  fresh dependency/build validation.
- No upstream catalogue export or private key is included by default.

The branch remains **preparatory** until a functional SPK is built and tested.

## Integrity gate

From the repository root:

```bash
python3 synology/tools/check_upstream_integrity.py --check-worktree
python3 -m unittest discover -s synology/tests -v
```

The script compares each tracked file in `upstream.sha` with the current
commit by Git object ID and mode, then checks the allowlist for new files.
The optional working-tree check also refuses local or untracked changes.

## Validation milestones

1. **FEAT-01**: branch, source-integrity guard, and automated tests.
2. **FEAT-02**: DSM 7.3 x86_64 SPK structure and local Python runtime.
3. **FEAT-03**: dependencies including native libraries, offline installation,
   secure service lifecycle, and direct port 8787 exposure.
4. **FEAT-04**: ARM64 and DSM 7.4 matrix.
5. **FEAT-05**: ARM32/platform-specific validation and full regression suite.

No public SPK distribution until the upstream licensing/redistribution rights
are clarified. The repository currently has no explicit LICENSE file.
