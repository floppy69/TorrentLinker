"use strict";
// The host owns source changes; the shared view only sends source-bound commands.
const mediaStreams = new WeakMap();
const mediaPlaybackFacts = new Map();
let mediaQuality = "original", mediaAudioChoice = 0, mediaSwitching = false;
function mediaFilmPosition(player) { return (player.currentTime || 0) + Number(player.dataset.streamOffset || 0); }
function mediaFilmDuration(player) {
  return player.dataset.streamOffset ? Number(mediaItems.get(player.dataset.mediaId)?.duration || mediaPlaybackFacts.get(player.dataset.mediaId)?.duration || 0) : (Number.isFinite(player.duration) && player.duration > 0 ? player.duration : Number(mediaItems.get(player.dataset.mediaId)?.duration || mediaPlaybackFacts.get(player.dataset.mediaId)?.duration || 0));
}
async function mediaStreamStop(player) {
  const stream = mediaStreams.get(player);
  if (!stream) return;
  mediaStreams.delete(player); stream.abort.abort();
  if (stream.objectURL) URL.revokeObjectURL(stream.objectURL);
  await api(stream.cancel, undefined, "DELETE").catch(() => {});
}
function mediaStreamError(player, stream, error) {
  if (stream.abort.signal.aborted || mediaStreams.get(player) !== stream) return;
  stream.abort.abort();
  api(stream.cancel, undefined, "DELETE").catch(() => {});
  $("media-codec-message").textContent = error.message || say("Compatible playback failed.", "La lecture compatible a échoué.");
  $("media-codec-error").hidden = false;
  mediaPlayerEnvironment();
}
function mediaWait(target, event, signal) {
  return new Promise((resolve, reject) => {
    const clean = () => {target.removeEventListener(event, done); target.removeEventListener("error", failed); signal.removeEventListener("abort", failed);};
    const done = () => {clean(); resolve();};
    const failed = () => {clean(); reject(signal.aborted ? new DOMException("Cancelled", "AbortError") : Error("Video stream failed."));};
    if (signal.aborted) {failed(); return;}
    target.addEventListener(event, done, {once: true}); target.addEventListener("error", failed, {once: true}); signal.addEventListener("abort", failed, {once: true});
  });
}
function mediaStreamLoad(player, id, start) {
  const playbackId = mediaNewSourceToken(), client = media.playerClient || mediaClient();
  const base = `media/items/${encodeURIComponent(id)}/playback`;
  const query = new URLSearchParams({client_id:client, playback_id:playbackId, quality:mediaQuality, start, audio:mediaAudioChoice});
  const url = new URL(`api/${base}/stream?${query}`,location.href).href;
  const stream = {abort:new AbortController(), cancel:`${base}/${playbackId}?${new URLSearchParams({client_id:client})}`, objectURL:null};
  mediaStreams.set(player,stream);
  player.dataset.streamOffset=String(start); player.dataset.streamQuality=mediaQuality;
  const mime='video/mp4; codecs="avc1.640028,mp4a.40.2"';
  if (!window.MediaSource || !MediaSource.isTypeSupported(mime)) {
    player.src=url; player.load(); return;
  }
  const source=new MediaSource(), signal=stream.abort.signal;
  const opened=mediaWait(source,"sourceopen",signal);
  stream.objectURL=URL.createObjectURL(source); player.src=stream.objectURL; player.load();
  (async()=>{
    await opened;
    const buffer=source.addSourceBuffer(mime);
    const response=await fetch(url,{signal});
    if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(detail||`Playback failed (${response.status}).`);}
    const reader=response.body.getReader();
    try {
      while(!signal.aborted){
        while(buffer.buffered.length && buffer.buffered.end(buffer.buffered.length-1)-player.currentTime>120)await mediaWait(player,"timeupdate",signal);
        if(player.currentTime>60 && buffer.buffered.length && buffer.buffered.start(0)<player.currentTime-60){const removed=mediaWait(buffer,"updateend",signal);buffer.remove(0,player.currentTime-30);await removed;}
        const {done,value}=await reader.read();if(done)break;
        const appended=mediaWait(buffer,"updateend",signal);buffer.appendBuffer(value);await appended;
        mediaPlayerEnvironment();
      }
      if(!signal.aborted&&source.readyState==="open")source.endOfStream();
    } finally {await reader.cancel().catch(()=>{});}
  })().catch(error=>mediaStreamError(player,stream,error));
}
async function mediaChangeQuality(values={}) {
  if(mediaSwitching)throw Error(say("Playback is changing. Please wait.","Le lecteur change de source. Patientez."));
  const player=mediaPlayer(), id=player.dataset.mediaId, facts=mediaPlaybackFacts.get(id);
  const quality=values.quality ?? mediaQuality;
  if(!id || media.preview || !(facts?.qualities||["original"]).includes(quality))throw Error(say("Quality unavailable.","Qualité indisponible."));
  if(values.audio!==undefined && !facts.audio.some(track=>track.id===values.audio))throw Error("Audio track unavailable.");
  const paused=player.paused, rate=player.playbackRate, source=player.dataset.sourceToken;
  const start=Math.max(0, Math.min((facts?.duration || mediaFilmDuration(player))-0.1,values.position ?? mediaFilmPosition(player)));
  mediaSwitching=true;
  try {
    await mediaStreamStop(player);
    if(player.dataset.sourceToken!==source)return;
    player.pause(); player.removeAttribute("src");player.load();
    mediaQuality=quality; if(values.audio!==undefined)mediaAudioChoice=values.audio;
    player.dataset.sourceToken=mediaNewSourceToken(); media.trackResult=null;
    $("media-codec-error").hidden=true;
    player.onloadedmetadata=()=>{if(quality==="original")player.currentTime=start;};
    if(quality==="original"){delete player.dataset.streamOffset;delete player.dataset.streamQuality;player.src=mediaURL(id);player.load();}
    else mediaStreamLoad(player,id,start);
    mediaPositionCaptions();
    player.defaultPlaybackRate=rate;player.playbackRate=rate;
    if(!paused)await mediaTryPlay(player);
    mediaPlayerEnvironment();
  } finally {mediaSwitching=false;}
}
async function mediaSeek(position) {
  const player=mediaPlayer();
  if(!player.dataset.streamOffset){player.currentTime=Math.max(0,Math.min(mediaFilmDuration(player),position));return;}
  const local=position-Number(player.dataset.streamOffset);
  for(let i=0;i<player.buffered.length;i++)if(local>=player.buffered.start(i)&&local<=player.buffered.end(i)){player.currentTime=local;return;}
  await mediaChangeQuality({position});
}
