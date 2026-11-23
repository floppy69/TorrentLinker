# Browser companion

[Documentation](../../README.md) · [Français](../fr/companion.md)

The optional TorrentLinker companion connects a signed-in c411 browser tab to
TorrentLinker. It supports Chrome, Brave and Edge. Firefox is not supported.
Manage the connection in **Settings → Companion** on desktop and WebUI. View the
account statistics in **Zen → Profile**.

## What it can do

| Capability | How it works |
| --- | --- |
| Sync account statistics | Updates account identity, Zen balance, Class, level, transfer totals, total seed time, validated upload count and active seed count every two minutes. |
| Fill earlier Zen history | Every six hours, reads about three months of your c411 Zen ledger (the date and amount of each entry, never its reason) so the Profile's Zen curve covers days before TorrentLinker started recording. Days recorded from the API are never replaced. |
| Read XXX search results | With **Show XXX content** on, Search reads the XXX category through your c411 session. Update the extension for this. The first read can take about 30 seconds. |
| Fetch `.torrent` files through your browser session | Optional, off by default. Uses the signed-in c411 account when TorrentLinker needs torrent metadata, including Library checks, queue sends and Plan sends. |

The companion supplements the API profile; it does not replace API values or your
planning settings. You still configure your c411 API key in TorrentLinker for
search and API access. The key needs `profile:read` so TorrentLinker can identify
the account to connect.

The browser fetches `.torrent` metadata, not the media itself. TorrentLinker still
sends work to your configured torrent client, which downloads or verifies the
files. The companion does not directly manage torrent clients or publish uploads.

## Install and connect

1. Open **Settings → Companion**. Choose **Save extension…** on desktop or
   **Download extension** in the WebUI, then extract the ZIP to a folder you will
   keep. For a local desktop installation, you can also use
   `TorrentLinker-companion.zip` from the release downloads.
2. Open `chrome://extensions`, `brave://extensions` or `edge://extensions` in the
   browser you will use. Enable **Developer mode**, choose **Load unpacked**, and
   select the extracted `torrentlinker-companion` folder containing `manifest.json`.
3. Sign in to c411 in that browser with the same account as the API key configured
   in TorrentLinker. Keep a c411 tab open.
4. Return to **Settings → Companion** and click **Connect companion**. TorrentLinker
   opens a connection page and passes the connection details to the installed
   extension. There is no code to copy. On desktop, this opens your default browser;
   install the extension and sign in to c411 in that browser profile.
5. Check the connection status in Settings and the statistics in **Zen → Profile**.
   Clicking the extension icon opens its connection and sync status page. That page
   can be closed; the signed-in c411 tab must stay open.

If **Connect companion** is disabled, check the API key and refresh the API profile
in **Zen → Profile**. A successful API account lookup is required before connecting.
If you installed the extension after opening the connection page, return to
TorrentLinker and click **Connect companion** again.

### Remote WebUI and Docker

Use HTTPS and download the extension from **Settings → Companion on that server**.
That ZIP is configured for the server's address and reverse-proxy path. The ZIP
from a release supports the local desktop receiver and a localhost WebUI; it is
not configured for your remote server. Install the server's ZIP in the browser on
your computer, not inside the Docker container. The browser must be able to reach
both c411 and the WebUI.

Over plain HTTP the browser does not let a remote page talk to the extension, so
an address like `http://100.x.y.z:8787` cannot connect. On Tailscale, run
`tailscale serve --bg 8787` on the server and open the `https://….ts.net`
address it prints, then download the extension again from there.

When a reverse proxy signs users in for the WebUI, the extension sends no cookies
and cannot pass that sign-in. Route its five paths around it, as described in
[Sign in through a reverse proxy](web-docker.md#sign-in-through-a-reverse-proxy).

## Enable session downloads

After connecting, enable **Download .torrent files with my c411 session** in
**Settings → Companion**. This setting is off by default and survives restarts
while the connection remains valid.

For `.torrent` files not already cached, TorrentLinker now asks the browser to
fetch them using the c411 session instead of the API key. Queue and Plan sends can
request up to 100 files ahead, with four concurrent browser requests by default.
TorrentLinker adds no download quota of its own, but c411's permissions and rate
limits still apply. This is not a guarantee of unlimited downloads or throughput.

- A session refusal, such as HTTP 401 or 403, stops the send. Check the signed-in
  account and reconnect. TorrentLinker does not fall back to the API key.
- HTTP 429 makes TorrentLinker respect c411's requested wait. The status in Settings
  shows the remaining delay; reconnecting does not clear that delay.
- A missing torrent or an individual timeout is reported for that item. A closed,
  signed-out or unresponsive browser tab can prevent the batch from completing.

Turn the setting off to use the API key for subsequent uncached `.torrent`
requests. Disconnecting the companion also turns the setting off.

## Data exchanged and stored

Profile synchronization sends account statistics only, without torrent titles,
info hashes or file lists. Session downloads exchange the requested info hashes
and return `.torrent` files to TorrentLinker. Those files contain torrent metadata,
including file names and tracker URLs. TorrentLinker checks the account, metadata
size and expected info hash before accepting a file.

Browser login cookies and the c411 API key are not exported by the extension.
The extension stores its connection token locally; TorrentLinker stores a hash of
that token and cached profile data. Session-download requests temporarily hold
metadata in memory, but accepted `.torrent` files can also be saved in
TorrentLinker's normal metadata cache and passed to the torrent client. They are
not guaranteed to remain only in memory.

## Pause, disconnect and update

- **Pause automatic sync** in the extension pauses profile updates and polling for
  session-download requests. Resume it before using session downloads again.
- **Disconnect & clear** in TorrentLinker revokes the connection, clears the saved
  companion statistics and disables session downloads. It does not remove cached
  torrent metadata or stop torrents already running in the client.
- Changing the Indexer address or API key clears the connection and cached account
  data. Connect again for the new account.
- To update, download a fresh ZIP from the same TorrentLinker installation, replace
  the files in your extracted extension folder, then click **Reload** on the
  browser's Extensions page. Reconnect if asked. A remote WebUI needs its own ZIP
  again, rather than the generic release ZIP.

The connection normally survives application and browser restarts. If the browser
is closed, c411 is signed out or the account differs, the last profile statistics
stay visible with their sync time. After five minutes they are marked as waiting
for a browser update. Profile sync resumes when the matching signed-in tab is
available and the extension is not paused. A refused download session may still
require reconnecting before another send.
