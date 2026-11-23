"use strict";
// Media browsing is shared with Qt; the player, its queue and the chat remain host-owned.
const mediaFrame = document.createElement("iframe");
mediaFrame.id="media-frame";mediaFrame.title="Media";mediaFrame.src="static/media/view.html";
mediaFrame.style.cssText="width:100%;min-height:300px;border:0;display:block";
// The panel's own colours never fill the picture's slot: the host's video is drawn behind it (media.css).
mediaFrame.setAttribute("allowtransparency","true");
let mediaRevision=0;
async function loadMedia(){
  if(!mediaFrame.isConnected)$("view-media").append(mediaFrame);
  mediaPlayerLabels();mediaMusicBar();mediaRefreshView();
  if(!media.session && sessionStorage.getItem(`tl-media-session:${mediaClient()}`))await mediaSession();
}
function mediaRefreshView(){mediaRevision++;mediaEnvironment()}
function mediaEnvironment(){
  const active=state.view==="media"&&!$("workspace").hidden;
  if(active)mediaFrame.style.height=`${Math.max(300,innerHeight-mediaFrame.getBoundingClientRect().top-20)}px`;
  mediaPlaceStage();
  // Restored queues can contain uncached tracks; the server validates every saved item.
  const music=media.queue.every(id=>{const row=mediaItems.get(id);return !row||row.kind==="music"});
  mediaFrame.contentWindow?.postMessage({type:"media-environment",value:{mode:"web",active,kind:media.kind,view:media.view,queue:[...media.queue],queue_client:media.playerClient||mediaClient(),queue_music:music,player_clearance:$("media-player-shell").hidden||$("media-player-shell").dataset.kind==="video"?0:$("media-player-shell").getBoundingClientRect().height,playback:mediaPlaybackSnapshot(),chat_open:media.chat,center_mode:document.body.classList.contains("media-center-mode"),clients:(state.setup?.clients||[]).filter(row=>row.enabled).map(row=>({id:row.id,name:row.name})),client_busy:!!shellState.clientBusy,revision:mediaRevision,language,theme:document.documentElement.dataset.theme||"dark",client_id:mediaClient(),adult_content:state.setup?.adult_content,owner:!signedInMember(),permissions:state.actor?.permissions||[]}},location.origin);
}
// A playing video's picture sits behind the view's transparent slot, where the view says it is (media.css).
function mediaPlaceStage(){
  const shell=$("media-player-shell"),layout=media.watchLayout;
  if(!layout||shell.dataset.kind!=="video"||shell.hidden||media.kind!=="video"||!mediaFrame.isConnected){shell.dataset.placed="false";return}
  const frame=mediaFrame.getBoundingClientRect(),set=(name,value)=>shell.style.setProperty(name,`${Math.round(value*100)/100}px`);
  set("--watch-x",frame.left+layout.band.x);set("--watch-y",frame.top+layout.band.y);set("--watch-width",layout.band.width);set("--watch-height",layout.band.height);
  set("--watch-screen-x",layout.screen.x-layout.band.x);set("--watch-screen-y",layout.screen.y-layout.band.y);set("--watch-screen-width",layout.screen.width);set("--watch-screen-height",layout.screen.height);
  let glass=document.getElementById('media-menu-glass');
  if(!glass){glass=document.createElement('div');glass.id='media-menu-glass';glass.style.cssText='position:absolute;z-index:1;pointer-events:none;border-radius:12px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)';$('media-video-stage').append(glass);}
  glass.hidden=!layout.menu;
  if(layout.menu){Object.assign(glass.style,{left:(layout.menu.x-layout.screen.x)+'px',top:(layout.menu.y-layout.screen.y)+'px',width:layout.menu.width+'px',height:layout.menu.height+'px'});}
  shell.dataset.placed="true";
}
addEventListener("scroll",mediaPlaceStage,{passive:true});
// Media Center and the sidebar move the view without scrolling: place the picture again when it moves.
addEventListener("resize",mediaPlaceStage);
new ResizeObserver(mediaPlaceStage).observe(mediaFrame);
window.addEventListener("message",async event=>{
  if(event.source!==mediaFrame.contentWindow||event.origin!==location.origin)return;
  const message=event.data;
  if(message?.type==="media-ready"){mediaEnvironment();return}
  if(message?.type!=="media-request")return;
  try{
    if($("workspace").hidden)throw Error("Sign in first.");
    let value=null;
    if(message.path==="host"){
      const {action,values={}}=message.body;
      if(action==="play")await mediaStart(values.media_ids,values.index||0);
      else if(action==="preroll-preview"&&!signedInMember())await previewPreroll(values.clip);
      else if(action==="studio-preview"&&!signedInMember()){if(!/^[a-f0-9]{32}\.mp4$/.test(values.file))throw Error("Unknown export");await playPrerolls({steps:[{kind:"clip",title:"Studio",url:`api/studio/exports/${values.file}`}]})}
      else if(action==="studio-export"&&!signedInMember()){if(!/^[a-f0-9]{32}\.(mp4|tlstudio)$/.test(values.file))throw Error("Unknown export");const link=document.createElement("a");link.href=`api/studio/exports/${values.file}`;link.download=values.file;link.click()}
      else if(action==="preview")await mediaPreview(values.media_id);
      else if(action==="enqueue")await mediaEnqueue(values.media_ids||[]);
      else if(action==="queue")mediaShowQueue();
      else if(action==="player"){
        // The view's controls: the same commands as the player's, for the source they were drawn for.
        if(!["toggle","seek","volume","fullscreen","stop","next","select_track","refresh-preview","quality","audio","rate","repeat","queue-play"].includes(values.action))throw Error("Unknown player control.");
        await mediaPlayerControl(values);
      }
      else if(action==="watch-layout"){media.watchLayout=values;mediaPlaceStage()}
      else if(action==="navigation")setNavigation(document.body.classList.contains("navigation-collapsed"));
      else if(action==="kind"&&mediaViewsByKind[values.kind]){media.kind=values.kind;if(values.kind==="music"&&$("media-player-shell").dataset.kind==="video")$("media-video").pause();media.view=mediaViewsByKind[values.kind][0];mediaMusicBar();rememberTab("media",media.kind);mediaEnvironment()}
      else if(action==="context"){
        media.browseContext=values;
        if(mediaViewsByKind[values.kind]?.includes(values.view)||values.view==="adult"){media.kind=values.kind;media.view=values.view;rememberTab("media",media.kind,media.view===mediaViewsByKind[media.kind][0]?undefined:media.view)}
      }
      else if(action==="selection")media.selected=values.selected_ids?.[0]?{id:values.selected_ids[0]}:null;
      else if(action==="chat"&&!signedInMember())await mediaToggleChat();
      else if(action==="center")await mediaToggleCenter();
      else if(action==="client")await shellSelectClient(values.client_id);
      else if(action==="settings")await navigate("setup");
      else throw Error("Unknown Media action");
    }else if(message.path==="preferences"){
      if(mediaLayouts.includes(message.body.layout)){
        media.layout=message.body.layout;try{localStorage.setItem("tl-media-layout",media.layout)}catch{}
        $("view-media").dataset.layout=media.layout;mediaPlayerEnvironment();
      }
      if(mediaHorizonViews.includes(message.body.horizon)){media.horizon=message.body.horizon;try{localStorage.setItem("tl-media-horizon",media.horizon)}catch{}}
      value={layout:mediaLayoutValue(media.layout),horizon:mediaHorizonValue(media.horizon)};
    }else{
      if(!/^(prerolls(?:\/[a-z-]+)?$|media(?:\?|\/home\?|\/items\/[^/]+(?:\?|\/(?:watched|forget-progress|rating)$|\/artwork\?)|\/ratings(?:\?|\/confirm$)|\/playlists(?:$|\?|\/[^/?]+\?)|\/tracker\/[0-9a-f]{40}\/download$)|media\/scan$|requests(?:\?|\/seen$|\/[0-9a-f]{32}\/cancel$|$)|wishes$|jobs\/[^/]+(?:\/cancel)?$)/.test(message.path))throw Error("Unknown Media operation");
      let client=mediaClient();
      if(message.path==="media/playlists" && message.body.method==="POST"){
        const owner=media.playerClient||client;
        if(message.body.body?.id && owner!==client)throw Error(say("Choose the playing Torrent Client before replacing a playlist.","Choisissez le client Torrent en lecture avant de remplacer une playlist."));
        client=owner;
      }
      const url=new URL("api/"+message.path,document.baseURI);url.searchParams.set("client_id",client);
      const path=url.pathname.replace(/^.*\/api\//,"")+url.search;
      if(url.pathname.endsWith("/artwork")){
        value={data_url:await mediaArtworkDataURL(url)};
      }else {
        if(url.pathname.includes("/jobs/")){
          const job=await api(`jobs/${url.pathname.split("/jobs/")[1].split("/")[0]}`);
          if(job.kind!=="media-scan"||job.client_id!==mediaClient())throw Error("This is not a Media scan for the selected client");
        }
        value=await api(path,message.body.body?{...message.body.body,client_id:client}:undefined,message.body.method);
      }
    }
    mediaFrame.contentWindow?.postMessage({type:"media-response",id:message.id,value},location.origin);
  }catch(error){mediaFrame.contentWindow?.postMessage({type:"media-response",id:message.id,error:error.message},location.origin)}
});
window.addEventListener("resize",mediaEnvironment);
document.addEventListener("tl-language-changed",mediaEnvironment);
new MutationObserver(mediaEnvironment).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
new MutationObserver(mediaEnvironment).observe($("view-media"),{attributes:true,attributeFilter:["hidden"]});

window.addEventListener("media-host-changed",mediaEnvironment);

new ResizeObserver(mediaEnvironment).observe($("media-player-shell"));
