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
  GitHub workflows `.github/workflows/synology-integrity.yml` and
  `.github/workflows/synology-dsm73-build.yml`.
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
4. **FEAT-04**: DSM 7.4 x86_64 matrix candidate — implemented; NAS acceptance
   pending. ARM64 and the remaining architectures follow separately.
   DSM data-share credential management (package revision `1.0.0-0002`) is
   implemented structurally; File Station access needs DS1817+ validation.
   Revision `1.0.0-0003` fixes Web guide resource placement and adds end-to-end
   HTTP checks for guides, screenshots, static assets and the browser companion.
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

## DSM 7.3 / 7.4 x86_64 candidate builds (FEAT-03 and FEAT-04)

GitHub Actions workflow: `.github/workflows/synology-dsm73-build.yml`. The
workflow writes ALL generated materials beneath `$RUNNER_TEMP`, never into
upstream sources. A two-target build matrix produces **separate candidate**
SPK artifacts, not published releases or proof of NAS compatibility:

| Target | SPK suffix | Package minimum DSM | Maximum |
| ------ | ---------- | ------------------- | ------- |
| `dsm73-x86_64` | `-dsm73-x86_64.spk` | `7.3-81180` | `7.3-99999` |
| `dsm74-x86_64` | `-dsm74-x86_64.spk` | `7.4-90075` | none (allows `7.4.1`) |

The DSM 7.4.1 patch version must not be accidentally excluded by an
`os_max_ver="7.4-99999"` ceiling. Later DSM major/minor versions are not
validated simply because the 7.4 package has no maximum restriction.

- Python: Astral python-build-standalone 3.12.16 (2026-10-26), pinned SHA256.
- Python dependencies: `pip download` resolves *all transitive dependencies*
  for CPython 3.12 / Linux x86_64; no source-built wheels, no PySide6.
  `pymediainfo==7.0.1` uses the Linux wheel bundling `libmediainfo`.
- Archives: upstream 7-Zip `7zz` v26.05 (SHA256 pinned); includes RAR and 7z
  readers, therefore the optional `unrar-free` fallback is not necessary.
- ELF audit: inspect each executable and native extension, vendor non-glibc
  libraries, fail on unresolved dependencies and symbols newer than
  `GLIBC_2.36` (DSM 7.3 and 7.4 x86_64 toolkit generation).
- Smoke test: actual standalone Python imports all major dependencies,
  `MediaInfo.can_parse()`, `7zz i`, and starts the original Web server on
  loopback port 18787 before hitting `/healthz`, logging in, and loading the
  32 French/English guides, all linked guide images, all HTML static resources,
  standalone guide pages and the authenticated browser companion ZIP endpoint.
  NAS browser access stays on the unchanged port **8787**.
- Reproducibility: deterministic archive, source version recorded,
  a JSON dependency inventory with wheel SHA256s inside the SPK.
- Licenses: upstream project lacks an explicit LICENSE; candidate artifacts
  must **not** be published as official releases before redistribution rights
  are established.

### First installation and authentication (revision 0002)

The package's `postinst` script securely generates a fresh random 48-character
Web password using the NAS kernel's random source. The DSM `data-share` worker
creates a visible **TorrentLinker-Config** shared folder on the selected
Synology volume when the service first starts, and grants read/write access to
the package's system account. The service initializes
`TorrentLinker-Config/web-password.txt` from the private install-time secret
exactly once. Existing values in the share are **never overwritten** during
an upgrade or later service restart. The password never ships inside the SPK
or CI logs.

Open **DSM → File Station → TorrentLinker-Config → web-password.txt** as an
administrator. The installer is assumed to be a DSM administrator, who is
responsible for managing the share's permissions. **Do not grant other DSM
accounts access to this share**: the password is stored as plaintext. The
initial file is created with Unix mode `0600`; actual File Station access and
DSM ACL inheritance must be verified on the DS1817+ before declaring this
feature production-ready.

To change the password, edit `web-password.txt` to contain **one line of
12–128 characters**, then **restart the package in Package Center**. The
original Web server reads its password only when starting, and there is no
DSM desktop launcher. An invalid password makes startup fail closed instead
of silently resetting credentials.

The original seed remains in package-private storage for safe initialization
on a new share. It is not an additional active login credential once the
shared file exists. Advanced SSH retrieval of the seed remains possible:

```sh
sudo cat /var/packages/TorrentLinkerSynology/var/secrets/web-password
```

The shared folder is **not deleted on uninstallation** by Synology's
data-share resource worker. Remove it manually via DSM only after you have
confirmed that no configuration or password must be retained. If a share
named `TorrentLinker-Config` already exists, Synology will reuse it and
apply the package user permission; check its contents and ACLs first.

Then browse to `http://NAS_IP:8787` (trusted LAN only; prefer HTTPS through
a configured reverse proxy for Internet exposure). There is no DSM desktop
launcher or Web Station dependency. Grant the package's internal user access
to any NAS shared folders that should be visible from TorrentLinker, and
configure appropriate library roots separately.

### Documentation and browser extension (revision 0003)

Upstream `documentation.root()` expects `sys.prefix/share/torrentlinker/docs`,
but installing its wheel with `pip --target` places wheel data files in a
different tree. The Synology builder now copies the complete, unmodified
upstream `docs/` directory to the runtime's expected prefix and fails the CI
build if a packaged guide, image, Web asset or companion file is missing.
The smoke test also checks the real, authenticated Web routes and ZIP bytes.

**TorrentLinker companion** is a Chromium/Brave/Chrome Manifest V3 extension.
Once logged into the Web interface, download it from
`http://NAS_IP:8787/api/zen/profile/extension` (not `localhost` on a remote PC),
unzip and load the folder containing `manifest.json` as an unpacked extension.
This is the upstream extension; no modified third-party JavaScript ships.

**Pairing from a remote browser requires HTTPS.** The original extension
intentionally refuses `http://NAS_IP:8787` for remote pairing, permitting HTTP
only when the Web server runs on that browser's own localhost. Use a NAS HTTPS
reverse proxy with a trusted certificate, access TorrentLinker through HTTPS,
then re-download the extension from that exact HTTPS address so the extension
is correctly scoped to the host.

### NAS filesystem access

The package declares internal user `TorrentLinkerSynology` in `conf/privilege`,
not `sc-torrentlinker`. DSM package accounts are intentionally non-root. To
access media/download shared folders, grant this **actual internal package user**
the necessary read/write permissions through DSM Control Panel → Shared Folder
→ Edit → Permissions → System internal user. Do not assume a request for NAS
administrator group membership has taken effect; no administrator elevation is
performed by this candidate SPK. Confirm the account identity and intended
scope of group membership on the DS1817+ before any privileged migration.

**Physical NAS acceptance is mandatory.** The GitHub runner cannot prove
DS1817+ ABI, DSM permissions, native libc loader, shared-folder ACLs or
multimodel compatibility. It must not be advertised as validated yet.
