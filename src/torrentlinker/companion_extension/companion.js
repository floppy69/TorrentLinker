const $ = (id) => document.getElementById(id);
async function update(action = "status") {
  const data = await chrome.runtime.sendMessage({ action });
  if (data.error) {
    $("status").textContent = data.error;
    return;
  }
  $("status").textContent =
    data.message || "Click Connect companion in TorrentLinker’s Profile tab.";
  $("destination").textContent = data.connected
    ? `${data.target} · Account ${data.accountId}`
    : "Not connected";
  $("last-sync").textContent = data.lastSync
    ? `Last update: ${new Date(data.lastSync).toLocaleString()}`
    : "No update received yet.";
  $("pause").disabled = !data.connected;
  $("pause").textContent = data.paused
    ? "Resume companion"
    : "Pause companion";
  $("forget").disabled = !data.connected;
}
$("pause").onclick = () => update("pause");
$("forget").onclick = () => update("disconnect");
chrome.storage.onChanged.addListener(() => update());
update();
