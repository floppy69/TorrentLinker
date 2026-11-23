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

let creationReview="";
async function creation(operation,value){const result=await chrome.runtime.sendMessage({action:"creation",operation,value});if(result.error)throw Error(result.error);return result}
$("creation-prepare").onclick=async()=>{try{const file=$("creation-file").files[0];if(!file||file.size>50000)throw Error("Choose a preset JSON of at most 50 KB in the companion; larger presets can be shared in the app.");const preset=JSON.parse(await file.text());if(preset.format!=="torrentlinker-community"||preset.schemaVersion!==1)throw Error("Choose an exported Community preset.");if(creationReview)await creation("cancel",{review:creationReview});const result=await creation("prepare",{kind:preset.kind,data:preset.data,metadata:{title:$("creation-title").value,description:$("creation-description").value,category:preset.kind,license:$("creation-license").value}});creationReview=result.review;$("creation-preview").textContent=JSON.stringify(result,null,2);$("creation-publish").disabled=false;$("creation-rights").checked=false;$("creation-status").textContent="Review the exact content above."}catch(error){$("creation-status").textContent=error.message}};
$("creation-publish").onclick=async()=>{if(!$("creation-rights").checked){$("creation-status").textContent="Confirm your review and rights first.";return}$("creation-publish").disabled=true;try{const result=await creation("publish",{review:creationReview,confirmed:true});creationReview="";$("creation-status").textContent=`${result.status} · version ${result.version}`}catch(error){$("creation-status").textContent=error.message;$("creation-publish").disabled=false}};
