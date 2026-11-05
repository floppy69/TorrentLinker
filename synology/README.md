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

1. **FEAT-01**: branch, source-integrity guard, and automated tests — completed.
2. **FEAT-02**: DSM 7.3 x86_64 SPK structure, deterministic builder, DSM
   lifecycle hooks, and native service template — structurally implemented.
   Not yet deployable without FEAT-03's real runtime and dependencies.
3. **FEAT-03**: automated candidate SPK build with Python 3.12, fully resolved
   offline Python wheelhouse, MediaInfo + 7-Zip, credential provisioning and
   native dependency audit. NAS acceptance test remains pending.
4. **FEAT-04**: ARM64 and DSM 7.4 matrix.
5. **FEAT-05**: ARM32/platform-specific validation and full regression suite.

No public SPK distribution until the upstream licensing/redistribution rights
are clarified. The repository currently has no explicit LICENSE file.

## DSM 7.3 x86_64 SPK builder (FEAT-02)

The offline assembler is `synology/tools/build_spk.py`. It never downloads
dependencies, compiles on the NAS, or modifies upstream files. It requires a
**separately prepared, DSM-compatible** payload outside the Git checkout:

```text
payload/
└── runtime/
    ├── bin/python3.12                    # native x86_64 ELF
    └── lib/python3.12/
        ├── ...                           # complete Python standard library
        └── site-packages/
            ├── torrentlinker/web/server.py
            ├── torrentlinker/web/static/index.html
            └── ...                       # all Python modules and extensions
```

Use two appropriately sized PNG icons generated from the project's image:

```bash
python3 synology/tools/build_spk.py \
  --payload /tmp/torrentlinker-dsm73-payload \
  --icon64 /tmp/torrentlinker-icons/icon64.png \
  --icon256 /tmp/torrentlinker-icons/icon256.png \
  --output-dir /tmp/torrentlinker-spk
```

The assembler checks the required Python binary, x86_64 ELF identity,
application entry point, static UI and PNG dimensions; it creates the SPK
atomically and deterministically. **These checks do not prove ABI compatibility
or the completeness of shared libraries and transitive Python packages.**
That validation is explicitly deferred to FEAT-03.

DSM metadata is restricted to **7.3** and `x86_64`, using package identity
`TorrentLinkerSynology`. The `conf/privilege` policy requests a package
account, not root. No DSM desktop integration is installed.

The native lifecycle script starts `python3.12 -m torrentlinker.web.server`
on the unchanged port `8787` and uses the persistent Synology package
directory for configuration, logs and PID. Startup **fails closed** until
`$SYNOPKG_PKGVAR/secrets/web-password` exists and is readable by the
package account. This is a temporary admin-provisioning prerequisite for
FEAT-02; the next milestone must supply a safe first-install experience.

**Do not install the structural test artifact on a NAS.** The unit tests use
a deliberately fake ELF header, not a working Python interpreter. No
functional SPK is declared until the runtime is cross-built and tested.

## DSM 7.3 x86_64 candidate build (FEAT-03)

GitHub Actions workflow: `.github/workflows/synology-dsm73-build.yml`. The
workflow writes ALL generated materials beneath `$RUNNER_TEMP`, never into
upstream sources. It produces a **candidate** SPK artifact, not a published
release or a claim of DSM compatibility.

- Python: Astral python-build-standalone 3.12.16 (2026-10-26), pinned SHA256.
- Python dependencies: `pip download` resolves *all transitive dependencies*
  for CPython 3.12 / Linux x86_64; no source-built wheels, no PySide6.
  `pymediainfo==7.0.1` uses the Linux wheel bundling `libmediainfo`.
- Archives: upstream 7-Zip `7zz` v26.05 (SHA256 pinned); includes RAR and 7z
  readers, therefore the optional `unrar-free` fallback is not necessary.
- ELF audit: inspect each executable and native extension, vendor non-glibc
  libraries, fail on unresolved dependencies and symbols newer than
  `GLIBC_2.36` (DSM 7.3 toolkit generation).
- Smoke test: actual standalone Python imports all major dependencies,
  `MediaInfo.can_parse()`, `7zz i`, and starts the original Web server on
  loopback port 18787 before hitting `/healthz`. NAS browser access stays on
  the unchanged port **8787**.
- Reproducibility: deterministic archive, source version recorded,
  a JSON dependency inventory with wheel SHA256s inside the SPK.
- Licenses: upstream project lacks an explicit LICENSE; candidate artifacts
  must **not** be published as official releases before redistribution rights
  are established.

### First installation and authentication

The package's `postinst` script securely generates a fresh random 48-character
Web password using the NAS kernel's random source. It is preserved on upgrades
and never embedded in the SPK or written to CI logs. Retrieve it as a NAS admin
via SSH:

```sh
sudo cat /var/packages/TorrentLinkerSynology/var/secrets/web-password
```

Then browse to `http://NAS_IP:8787` (trusted LAN only; prefer HTTPS through
a configured reverse proxy for Internet exposure). There is no DSM desktop
launcher or Web Station dependency. Grant the package's internal user access
to any NAS shared folders that should be visible from TorrentLinker, and
configure appropriate library roots separately.

**Physical NAS acceptance is mandatory.** The GitHub runner cannot prove
DS1817+ ABI, DSM permissions, native libc loader, shared-folder ACLs or
multimodel compatibility. It must not be advertised as validated yet.
