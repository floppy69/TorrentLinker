# Seedbox transfers, #118

The owner approved the seedbox preview and requested implementation. `seedbox-prototype.html` retains that workflow. It extends the approved #105 transfer dialog with separate SFTP access, identity verification and path mapping, preserving desktop/Web parity and French/English light/dark rendering.

## Scope

Configure file access from the transfer dialog. Torrent API credentials remain separate. Use the destination client's category folders by default and allow per-transfer overrides. Exclude source clients from destination choices. Verify all selected items before enabling Start, and highlight each blocker.

File transfers run in TorrentLinker, on the desktop or Web server. Remote-to-remote copying relays through that process. The browser only controls the operation. A matching path or hostname never proves shared storage.

Show per-item progress, speed and remaining time. Persist recovery state; reconcile partial files and revalidate source, destination and server identities before resuming. Confirm destination content and seeding before offering the approved separate source-cleanup confirmation.

SFTP is the first remote transport. Unknown available capacity blocks the reviewed workflow. Credentials must use the existing secret store, not transfer journals. Changed server identity blocks authentication until reviewed.

Reusable seedbox settings and expansion into other app workflows are deferred to #119 after the interface backlog.

## Validation environment

Use temporary generated files and real disposable clients/SFTP servers on a throwaway Docker network. Never use configured user clients, seedboxes or library files. The owner confirmed the public remote-access and transfer services and desktop/Web workflows as test boundaries, with a throwaway Docker network required for transfer tests.

## Supported access

The first transport is SFTP to POSIX folders. Passwords and unencrypted SSH private keys use the existing secret store. The owner confirms the SHA256 server fingerprint before authentication. A changed key blocks reconnection. SSH agent and local SSH configuration are not inherited.

The server must report available space through SFTP. Paths containing symlinks or parent traversal are rejected. Remote storage is copied; matching hostnames or paths never enable shared-folder reuse. Remote-to-remote copies relay through TorrentLinker.

Before deleting source files, the service compares their contents with the verified destination again. Interrupted remote copies compare the existing prefix before resuming, because SFTP does not supply a portable file inode.

## Transport reference

AsyncSSH documents SSH key/password authentication, host-key validation and SFTP file operations. Capacity reporting depends on a server extension and may be unsupported.

- https://asyncssh.readthedocs.io/en/latest/
- https://asyncssh.readthedocs.io/en/latest/api.html
