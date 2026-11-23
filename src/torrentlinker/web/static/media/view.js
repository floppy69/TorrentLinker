"use strict";
const mediaExternalURL=id=>new URL(`../../api/media/items/${encodeURIComponent(id)}/stream?${mediaQuery({})}`,location.href).href;
const mediaStart=async(ids,index=0)=>host("play",{media_ids:await ids,index});
const mediaPreview=id=>host("preview",{media_id:id});
const mediaToggleChat=async()=>{await mediaSelectionChanged(media.selected);return host("chat",{selected_ids:media.selected?[media.selected.id]:[]})};
function mediaSelectionChanged(row){
  return guard(async()=>{
    await host("context",{kind:media.kind,view:media.view,q:$("media-search").value,...Object.fromEntries(["genre","year","language","availability"].map(key=>[key,$(`media-${key}`).value]))});
    await host("selection",{selected_ids:row&&!row.tracker?[row.id]:[]}); // a tracker film is not in the library
  });
}
async function mediaKind(kind){
  media.kind=kind;media.view=mediaViewsByKind[kind][0];media.ratingsPage=false;media.gridMode=false;media.animeFilters={};
  for(const key of ["genre","year","language","availability"])$(`media-${key}`).value="";
  mediaViews();await host("kind",{kind});await loadMedia();
}
const mediaEnqueue=async ids=>host("enqueue",{media_ids:await ids});
// The host owns the playback queue; the view reads it from the environment.
function mediaQueueLabel(){
  const queue=environment.queue||[];
  $("media-show-queue").textContent=say(`Playback queue · ${queue.length}`,`File de lecture · ${queue.length}`);
  $("media-save-playlist").querySelector("button").disabled=!queue.length||!environment.queue_music;
}
async function mediaPlaylists(){
  const rows=await api(`media/playlists?${mediaQuery({})}`),root=$("media-playlist-list");root.replaceChildren();
  const playlists=rows.rows||rows;
  if(!playlists.length)root.append(element("p",say("Your saved playlists will appear here. Start with a track or album, then save its queue.","Vos playlists apparaîtront ici. Lancez une piste ou un album, puis enregistrez la file."),"media-playlist-empty"));
  for(const row of playlists){
    const item=element("article",undefined,"media-playlist-card"),actions=element("div",undefined,"media-card-actions");
    const count=row.media_ids?.length||0;
    item.append(element("h3",row.name),element("p",say(`${count} track${count===1?"":"s"}`,`${count} piste${count===1?"":"s"}`),"media-card-meta"));
    actions.append(button(say("Play","Lire"),()=>mediaStart(row.media_ids||[])),button(say("Add to queue","Ajouter à la file"),()=>mediaEnqueue(row.media_ids||[])));
    const options=element("details"),more=element("summary",say("Edit playlist","Modifier la playlist"));
    options.append(more,button(say("Replace with queue","Remplacer par la file"),async()=>{await api("media/playlists",{id:row.id,name:row.name,media_ids:environment.queue||[]});await mediaPlaylists()}),button(say("Delete","Supprimer"),async()=>{await api(`media/playlists/${encodeURIComponent(row.id)}?${mediaQuery({})}`,undefined,"DELETE");await mediaPlaylists()}));
    item.append(actions,options);root.append(item);
  }
  mediaQueueLabel();
}
$("media-save-playlist").onsubmit=event=>{event.preventDefault();guard(async()=>{await api("media/playlists",{name:$("media-playlist-name").value,media_ids:environment.queue||[]});$("media-playlist-name").value="";await mediaPlaylists()})};
$("media-show-queue").onclick=()=>guard(()=>host("queue"));
$("media-music-tab").onclick=()=>guard(()=>mediaKind("music"));
$("media-video-tab").onclick=()=>guard(()=>mediaKind("video"));
for(const node of document.querySelectorAll("[data-media-music-view]"))node.onclick=()=>guard(async()=>{media.view=node.dataset.mediaMusicView;$("media-view").value=media.view;await loadMedia()});
$("media-toolbar-chat").onclick=()=>guard(mediaToggleChat);
$("media-toolbar-chat").title=say("Assistant","Assistant");
$("media-center-mode").onclick=()=>guard(()=>host("center"));
$("media-client").onchange=()=>guard(()=>host("client",{client_id:$("media-client").value}));
$("media-center-mode").title=say("Media Center mode","Mode Media Center");
$("media-layout-switch").onchange=event=>mediaSetLayout(event.target.value);
$("media-horizon-switch").onchange=event=>mediaSetHorizon(event.target.value);
for(const node of document.querySelectorAll("[data-view=setup]"))node.onclick=()=>guard(navigate);
for(const node of document.querySelectorAll("[data-media-view]"))node.onclick=()=>guard(async()=>{
  media.gridMode=false;media.ratingsPage=false;media.animeFilters={};
  for(const key of ["genre","year","language","availability"])$(`media-${key}`).value="";
  media.view=node.dataset.mediaView;$("media-view").value=media.view;await loadMedia();
});
$("media-view").onchange=()=>guard(async()=>{media.view=$("media-view").value;await loadMedia()});
for(const key of ["genre","year","language","availability"])$(`media-${key}`).onchange=()=>guard(loadMedia);
let searchTimer;
$("media-search").oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>guard(loadMedia),250)};
$("media-more").onclick=()=>guard(()=>loadMedia(true));$("media-more").tabIndex=-1;
async function mediaScan(){
  const result=await api("media/scan",{client_id:state.clientId});media.scan=result.id;mediaStatus(say("Scanning Library Folders…","Analyse des dossiers…"));
  $("media-toolbar-refresh").setAttribute("aria-pressed","true");
}
async function refreshOrCancel(){if(media.scan)await api(`jobs/${encodeURIComponent(media.scan)}/cancel`,{});else await mediaScan()}
$("media-refresh").onclick=()=>guard(refreshOrCancel);
$("media-toolbar-refresh").onclick=()=>guard(refreshOrCancel);
$("media-toolbar-refresh").title=say("Refresh library","Actualiser la médiathèque");
$("media-cancel-scan").onclick=()=>guard(refreshOrCancel);
setInterval(()=>{if(!media.scan)return;guard(async()=>{
  const job=await api(`jobs/${encodeURIComponent(media.scan)}`);
  if(["queued","running"].includes(job.status))return;
  media.scan="";$("media-toolbar-refresh").setAttribute("aria-pressed","false");await loadMedia();if(job.error)toast(job.error,"bad");
})},1000);
$("media-details").addEventListener("click",event=>{if(event.target!==event.currentTarget)return;const box=event.target.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)event.target.close()});
document.addEventListener("keydown",event=>{
  const card=event.target.closest(".media-row-card,.media-focus-choice");if(!card)return;
  const direction={ArrowLeft:-1,ArrowRight:1}[event.key];
  if(direction){event.preventDefault();const cards=[...card.parentElement.querySelectorAll("button")];cards[(cards.indexOf(card)+direction+cards.length)%cards.length]?.focus()}
});

const moreObserver=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)&&media.next&&!media.loadingMore){media.loadingMore=true;guard(()=>loadMedia(true)).finally(()=>media.loadingMore=false)}},{rootMargin:"200px"});
moreObserver.observe($("media-more"));
document.addEventListener("keydown",event=>{
  if(!["ArrowUp","ArrowDown"].includes(event.key))return;
  const card=event.target.closest(".media-row-card"),row=card?.closest(".media-home-row");if(!row)return;
  const rows=[...document.querySelectorAll(".media-home-row")];
  const next=rows[rows.indexOf(row)+(event.key==="ArrowDown"?1:-1)];
  if(next){event.preventDefault();const index=[...row.querySelectorAll(".media-row-card")].indexOf(card),cards=next.querySelectorAll(".media-row-card");cards[Math.min(index,cards.length-1)]?.focus()}
});

document.addEventListener("keydown",event=>{if(event.key==="Escape"&&environment.center_mode&&!$("media-details").open)guard(()=>host("center"))});

// Extra navigation stays accessible without filling the theatre bar.
const mediaOptions = $("media-library-options");
mediaOptions.addEventListener("click", event => {
  if (event.target.closest("#media-video-tab,#media-music-tab,[data-media-view],#media-ratings-entry,#media-toolbar-chat,#media-prerolls")) mediaOptions.open = false;
});
document.addEventListener("click", event => {
  if (mediaOptions.open && !mediaOptions.contains(event.target)) mediaOptions.open = false;
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && mediaOptions.open) {
    mediaOptions.open = false; mediaOptions.querySelector("summary").focus();
    event.preventDefault(); event.stopImmediatePropagation();
  }
}, true);

// Announce readiness only after the browsing state and event handlers exist.
TLPanel.connect("media",{asynchronous:true}).then(request=>{panelRequest=request;window.mediaReady()});
