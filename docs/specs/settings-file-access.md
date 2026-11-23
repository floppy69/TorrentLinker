# Reusable file access in Settings

Issue #119 adds optional SFTP access under Settings → Connections. Both desktop and WebUI use `settings/file-access.js` and the same `panel/file-access.js` editor as Transfers. The editor saves independently of the connection form, so configuring SFTP preserves unsaved Torrent Client API settings.

The focused preview is archived on branch `codex/remote-access-settings-prototype`, commit `536fde3c46003667135dee568f93cac52d605af4`, at `docs/specs/remote-access-settings/prototype.html`. It reuses the approved Settings layout and #118 editor. Preview responses are simulated.

## Ownership and checks

Each client owns an optional SFTP endpoint, username, authentication mode, pinned server key and client-root/file-root mapping. Secrets remain in the existing secret store under a separate key. Snapshots expose only whether a credential exists. Settings exports do not include SFTP secrets.

Settings and Transfers route through the same `TorrentWorkspace` and `RemoteAccess` instance. Desktop requests use the existing application coordinator once. WebUI connections and file operations run on the TorrentLinker server.

Discovery retrieves the public host key without authenticating. The owner compares its fingerprint with the provider's value before saving. A changed identity fails ordinary access checks; reopening the editor requires reviewing the new fingerprint. Saving invalidates the checked state and the configuration fingerprint used by transfer previews. Removal requires confirmation, clears the SFTP secret and identity, and invalidates affected previews without changing remote files or Torrent Client API credentials. Active transfers block edits/removal. A client with saved file access cannot be removed until that access has been explicitly removed in Connections.

An access check verifies the mapped directory and available-space reporting. It does not prove permission for every file operation. Transfers retain their per-operation permission, path, collision, identity and verification gates.

## Workflow audit

| Workflow | Current support | Reason and required checks |
| --- | --- | --- |
| Client transfers | Reuses saved SFTP access | Existing #118 transfer preflight and execution validate mapped paths, capabilities, source/destination identities and available space. Destructive source cleanup keeps its separate confirmation after destination verification. |
| Remote folder browsing | Reuses saved SFTP access | Enumerates through the existing SFTP service, rejects traversal and symlink paths, and reports permission failures. |
| Library scan and Reseed | Requires locally accessible storage | Scanning records local filesystem identities; reseed verification and linking operate on local files and configured client path mappings. SFTP metadata does not establish those identities or shared storage. |
| Upload preparation | Requires local files and preparation tools | Hashing, extraction and media tooling consume local paths. No remote execution or streaming preparation contract exists. |
| Media inspection and playback | Requires files accessible to the desktop or WebUI server | Discovery uses filesystem walks and native decoding/file responses. SFTP configuration alone does not provide a seekable decoder source. |

Settings displays these limits. No additional file workflow is silently enabled. Category-folder defaults and operation-specific destination overrides retain their existing behavior.

## Validation

`tests/test_settings_file_access.py` covers shared ownership, authentication and CSRF, secret separation, removal confirmation, active transfers, disabled clients, client deletion and secret-store failure recovery. Settings interface tests exercise the desktop bridge and credential draft disposal. Disposable SFTP tests exercise configuration from Settings, reuse by Transfers, browsing, denied permissions, changed identity, lost connectivity, explicit removal and bilingual browser layouts.

Local validation for this implementation: 25 Settings/workspace checks passed, followed by 9 desktop/service checks on Wayland including the client-removal race. All 9 disposable SFTP tests passed, including the existing real-client transfer browser flow. The 3 existing Settings browser workflows passed. The final bilingual SFTP editor check passed with explicit dark/light themes and a 390px viewport. Ruff and mypy passed across the repository. The Docker browser fixture reloads only when network creation cancels asset requests with Chromium's `ERR_NETWORK_CHANGED`; JavaScript failures still fail acceptance.
