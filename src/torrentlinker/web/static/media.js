"use strict";
/* The Web player host. Browsing runs in the shared media/view.html frame. */
const media = {kind: "video", view: "recent", selected: null, session: null, playerClient: "", queue: [], index: 0, shuffle: false, repeat: "off", ack: 0,
  preview: null, playbackGeneration: 0, chat: false, scan: "", scanQuiet: false, browseContext: null};
const mediaTab = Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
const mediaChannel = typeof BroadcastChannel === "function" ? new BroadcastChannel("torrentlinker-media") : null;
const mediaClaims = new Set();
if (mediaChannel) mediaChannel.onmessage = event => {
  const message = event.data;
  if (message?.type === "probe" && message.tab !== mediaTab && message.id === media.session?.id)
    mediaChannel.postMessage({type: "claimed", tab: message.tab, id: message.id});
  if (message?.type === "claimed" && message.tab === mediaTab) mediaClaims.add(message.id);
};
async function mediaSessionClaimed(id) {
  if (!mediaChannel) return false;
  mediaChannel.postMessage({type: "probe", tab: mediaTab, id});
  await new Promise(resolve => setTimeout(resolve, 100));
  return mediaClaims.delete(id);
}
const mediaItems = new Map();
const mediaAutomaticCues = new WeakSet();
const mediaCueTimes = new WeakMap();
function mediaPositionCaptions() {
  const video = $("media-video");
  const offset = Number(video.dataset.streamOffset || 0);
  const line = Math.max(10, 100 * (1 - 96 / video.clientHeight));
  for (const track of Array.from(video.textTracks || [])) for (const cue of Array.from(track.cues || [])) {
    if (!mediaCueTimes.has(cue)) mediaCueTimes.set(cue, [cue.startTime, cue.endTime]);
    const [start, end] = mediaCueTimes.get(cue);
    cue.startTime = Math.max(0, start - offset); cue.endTime = Math.max(0, end - offset);
    if (cue.line === "auto") mediaAutomaticCues.add(cue);
    if (mediaAutomaticCues.has(cue) && cue.line !== line) {
      cue.snapToLines = false; cue.lineAlign = "end"; cue.line = line;
    }
  }
}
const mediaURL = (id, suffix = "stream") => `api/media/items/${encodeURIComponent(id)}/${suffix}?${new URLSearchParams({client_id: media.playerClient || mediaClient()})}`;
const mediaPlayer = () => $("media-audio").hidden ? $("media-video") : $("media-audio");
function mediaStatus(text, kind = "ok") { if (text) toast(text, kind); }
function mediaSetLayout(value) {
  media.layout = mediaLayoutValue(value);
  try { localStorage.setItem("tl-media-layout", media.layout); } catch {}
  $("view-media").dataset.layout = media.layout;
  if (typeof mediaRefreshView === "function") mediaRefreshView();
  if (typeof mediaPlayerEnvironment === "function") mediaPlayerEnvironment(); // Horizon's player
}
// Horizon's view is chosen in Settings; like the layout, each browser keeps its own.
function mediaSetHorizon(value) {
  media.horizon = mediaHorizonValue(value);
  try { localStorage.setItem("tl-media-horizon", media.horizon); } catch {}
  if (typeof mediaRefreshView === "function") mediaRefreshView();
}
try { media.layout = mediaLayoutValue(localStorage.getItem("tl-media-layout")); media.horizon = mediaHorizonValue(localStorage.getItem("tl-media-horizon")); } catch {}
// In Video, a music track keeps its bar only while it plays, so it can still be paused.
function mediaMusicBar() {
  const shell = $("media-player-shell");
  $("view-media").dataset.kind = media.kind;
  shell.classList.toggle("media-shell-parked", shell.dataset.kind === "music" && media.kind === "video" && $("media-audio").paused);
}
function mediaPlayerLabels() { mediaPlayerEnvironment(); }
let mediaSessionPending = null;
async function mediaSession() {
  if (media.session) return media.session;
  if (mediaSessionPending) return mediaSessionPending;
  mediaSessionPending = mediaOpenSession();
  try { return await mediaSessionPending; } finally { mediaSessionPending = null; }
}
async function mediaOpenSession() {
  const restoreRequest = {generation: media.playbackGeneration, client: mediaClient(), selectedClient: state.clientId, session: null};
  media.playerClient = restoreRequest.client;
  const key = `tl-media-session:${media.playerClient}`;
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(key)); } catch (_) { /* Invalid local credentials are replaced. */ }
  let result;
  if (saved?.id && saved?.token && !await mediaSessionClaimed(saved.id)) {
    try { result = await api(`media/sessions/${encodeURIComponent(saved.id)}`, {token: saved.token}); result.token = saved.token; }
    catch (_) { sessionStorage.removeItem(key); }
  }
  if (!result) result = await api("media/sessions", {client_id: media.playerClient, platform: "web"});
  media.session = {id: result.id, token: result.token};
  sessionStorage.setItem(key, JSON.stringify(media.session));
  restoreRequest.session = {...media.session};
  if (!mediaRequestCurrent(restoreRequest)) return media.session;
  const restored = result.state || {};
  media.queue = restored.queue || []; media.index = restored.index || 0;
  media.shuffle = !!restored.shuffle; media.repeat = restored.repeat || "off"; media.ack = restored.command_ack || 0;
  if (restored.current_id && !restored.context?.preview) await mediaLoad(restored.current_id, restored.position || 0, true, null, restoreRequest, false);
  else if (restored.context?.preview) mediaStatus(say("Select Preview downloaded portion again to create a new verified partial preview.", "Sélectionnez à nouveau Prévisualiser la partie téléchargée pour créer un nouvel aperçu partiel vérifié."));
  if (!mediaRequestCurrent(restoreRequest)) return media.session;
  for (const player of [$("media-video"), $("media-audio")]) player.volume = restored.volume ?? 1;
  await mediaCommands(result.commands || []);
  return media.session;
}
function mediaInvalidatePlayback() { return ++media.playbackGeneration; }
function mediaNewSourceToken() {
  // getRandomValues also works when the owner opens the app over plain HTTP on a LAN.
  const data = crypto.getRandomValues(new Uint8Array(16)); data[6] = (data[6] & 15) | 64; data[8] = (data[8] & 63) | 128;
  const hex = Array.from(data, value => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function mediaTrackState() {
  const player = mediaPlayer(), active = !!player.dataset.sourceToken && !!player.dataset.mediaId;
  const trackText = value => Array.from(value || "").slice(0, 300).join("");
  const external = [...player.querySelectorAll("track")];
  const ready = active && player.readyState >= 1 && external.every(track => track.readyState >= 2);
  return {media_id: player.dataset.mediaId || "", source_token: player.dataset.sourceToken || "", ready,
    audio_supported: active && !!player.audioTracks, subtitle_supported: active && !!player.textTracks,
    audio: active ? Array.from(player.audioTracks || []).slice(0, 100).map((track, index) => ({id: `audio:${index}`, label: trackText(track.label), language: trackText(track.language), selected: !!track.enabled})) : [],
    subtitles: active ? Array.from(player.textTracks || [], (track, index) => ({track, index}))
      .filter(({track}) => { const source = external.find(item => item.track === track); return !source || source.readyState === 2; })
      .slice(0, 100).map(({track, index}) => ({id: `subtitle:${index}`, label: trackText(track.label), language: trackText(track.language), selected: track.mode === "showing"})) : []};
}
function mediaSourceMatches(command) {
  const player = mediaPlayer();
  return !!command.source_token && command.source_token === player.dataset.sourceToken && command.media_id === player.dataset.mediaId;
}
function mediaTrackRequestFailure(request) {
  if (request?.status !== "failed" || !mediaSourceMatches(request) || media.failedTrackSource === request.source_token) return;
  media.failedTrackSource = request.source_token;
  const message = element("p", request.error || say("The requested playback tracks are unavailable.", "Les pistes demandées ne sont pas disponibles."), "media-error");
  message.id = "media-track-request-error"; message.setAttribute("role", "alert");
  $("media-track-request-error")?.remove(); $("media-player-shell").append(message);
  mediaStatus(message.textContent, "bad"); // a video's shell is only its picture
}
function mediaSelectTrack(command) {
  let error = "";
  const state = mediaTrackState(), player = mediaPlayer();
  if (!mediaSourceMatches(command)) error = "The playback source changed. Refresh its tracks before selecting.";
  else if (!state.ready) error = "Playback tracks are not ready yet.";
  else if (command.kind !== "audio" && command.kind !== "subtitle") error = "Choose audio or subtitle tracks.";
  else if (!state[command.kind === "audio" ? "audio_supported" : "subtitle_supported"]) error = `${command.kind === "audio" ? "Audio" : "Subtitle"} track switching is unavailable in this browser.`;
  else {
    const tracks = state[command.kind === "audio" ? "audio" : "subtitles"];
    const off = command.kind === "subtitle" && command.track_id === "off";
    if (!off && !tracks.some(track => track.id === command.track_id)) error = "That track is unavailable in the current browser player.";
    else try {
      const available = command.kind === "audio" ? player.audioTracks : player.textTracks;
      Array.from(available).forEach((track, index) => {
        const selected = command.track_id === `${command.kind}:${index}`;
        if (command.kind === "audio") track.enabled = selected;
        else track.mode = selected ? "showing" : "disabled";
      });
      const selected = mediaTrackState()[command.kind === "audio" ? "audio" : "subtitles"].filter(track => track.selected);
      if (off ? selected.length !== 0 : selected.length !== 1 || selected[0].id !== command.track_id) error = "The browser did not apply the requested track.";
    } catch (_) { error = "The browser could not switch that track."; }
  }
  if (command.sequence) media.trackResult = {sequence: command.sequence, applied: !error, error};
  if (error) mediaStatus(error, "bad");
}
function mediaClosePlayerMenu() { mediaPlayerMenu(false); }
function mediaOpenPlayerMenu() { mediaPlayerMenu(true); }
function mediaPlayerComposition(kind) {
  mediaClosePlayerMenu();
  $("media-video-stage").hidden = kind !== "video";
  $("player-details-frame").hidden = kind !== "video";
  const parent = kind === "video" ? $("media-video-stage") : $("media-player-shell");
  if ($("player-frame").parentElement !== parent) parent.append($("player-frame"));
}
function mediaRequestCurrent(request) {
  return request.generation === media.playbackGeneration && (request.browsingClient || request.client) === mediaClient()
    && request.selectedClient === state.clientId && (!request.session || (
      request.client === media.playerClient && request.session.id === media.session?.id
      && request.session.token === media.session?.token));
}
async function mediaClosePreviewHandle(preview, client) {
  try { await api(`media/previews/${encodeURIComponent(preview.preview_id)}?${new URLSearchParams({client_id: client})}`, undefined, "DELETE"); }
  catch (_) { /* Closing an expired preview must not replace the current playback decision. */ }
}
const mediaPreviewURL = previewId => `api/media/previews/${encodeURIComponent(previewId)}/stream?${new URLSearchParams({client_id: media.playerClient})}`;
async function mediaReleasePreview() {
  const previous = media.preview; media.preview = null;
  $("media-preview-state").hidden = true;
  if (previous) await mediaClosePreviewHandle(previous, previous.client_id);
}
async function mediaPreview(id, refresh = false) {
  const request = {generation: mediaInvalidatePlayback(), client: mediaClient(), selectedClient: state.clientId, session: null};
  if (media.session && media.playerClient !== request.client) { mediaPlayer().pause(); media.session = null; }
  await mediaSession();
  if (!mediaRequestCurrent(request)) return;
  request.session = {...media.session};
  const position = refresh ? mediaPlayer().currentTime || 0 : 0;
  const preview = await api(`media/items/${encodeURIComponent(id)}/preview`, {client_id: request.client});
  if (!mediaRequestCurrent(request)) { await mediaClosePreviewHandle(preview, request.client); return; }
  try {
    const loaded = await mediaLoad(id, position, false, {...preview, item_id: id, client_id: request.client}, request);
    if (loaded) await mediaHeartbeat();
  } catch (error) {
    await mediaClosePreviewHandle(preview, request.client);
    if (mediaRequestCurrent(request)) throw error;
  }
}
async function mediaStop() {
  mediaInvalidatePlayback();
  mediaClosePlayerMenu();
  await mediaLeaveFull();
  for (const player of [$("media-video"), $("media-audio")]) { await mediaStreamStop(player); player.pause(); delete player.dataset.mediaId; delete player.dataset.sourceToken; player.removeAttribute("src"); player.load(); }
  media.trackResult = null;
  $("media-track-request-error")?.remove();
  const closing = mediaReleasePreview(); media.queue = []; media.index = 0;
  $("media-player-shell").hidden = true; media.watchLayout = null; mediaQueueRender();
  await closing; await mediaHeartbeat();
}
async function mediaLoad(id, position = null, paused = false, preview = null, request = null, invalidate = true) {
  if (!request) {
    request = {generation: invalidate ? mediaInvalidatePlayback() : media.playbackGeneration,
      client: media.playerClient || mediaClient(), selectedClient: state.clientId,
      browsingClient: invalidate ? mediaClient() : null, session: media.session ? {...media.session} : null};
  }
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  const row = await api(`media/items/${encodeURIComponent(id)}?${new URLSearchParams({client_id: request?.client || media.playerClient})}`);
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  mediaItems.set(id, row);
  const old = mediaPlayer(); old.pause(); await mediaStreamStop(old);
  await mediaReleasePreview();
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  if (!preview && !paused && row.kind === "video" && !(position ?? row.position ?? 0)) {
    try {
      const plan = await api(`media/items/${encodeURIComponent(id)}/prerolls?${new URLSearchParams({client_id:request.client})}`);
      if (mediaRequestCurrent(request)) await playPrerolls(plan,()=>mediaRequestCurrent(request));
    } catch { /* An unavailable pre-roll must not prevent the feature from playing. */ }
    if (!mediaRequestCurrent(request)) return false;
  }
  media.preview = preview;
  if (preview) { media.queue = [id]; media.index = 0; }
  else if (request.queue) { media.queue = request.queue; media.index = request.index; }
  $("media-player-shell").dataset.kind = row.kind; mediaMusicBar();
  mediaPlayerComposition(row.kind);
  const player = $(row.kind === "music" ? "media-audio" : "media-video");
  $("media-audio").hidden = row.kind !== "music"; $("media-video").hidden = row.kind === "music";
  player.volume = old.volume; player.dataset.mediaId = id; player.dataset.sourceToken = request.sourceToken || mediaNewSourceToken(); media.trackResult = null;
  $("media-track-request-error")?.remove();
  delete player.dataset.streamOffset; delete player.dataset.streamQuality;
  if (row.kind === "video" && !preview) {
    try {mediaPlaybackFacts.set(id, await api(`media/items/${encodeURIComponent(id)}/playback?${new URLSearchParams({client_id:request.client})}`));}
    catch {mediaPlaybackFacts.set(id,{qualities:["original"],audio:[]});}
    if (!mediaRequestCurrent(request)) return false;
  }
  mediaAudioChoice=0;
  const converted=!preview && row.kind==="video" && mediaQuality!=="original" && mediaPlaybackFacts.get(id)?.qualities.includes(mediaQuality);
  if(converted)mediaStreamLoad(player,id,position ?? row.position ?? 0);
  else {player.src = preview ? mediaPreviewURL(preview.preview_id) : mediaURL(id); player.load();}
  $("media-player-shell").hidden = false;
  $("media-now-playing").textContent = [row.title, row.artist].filter(Boolean).join(" · ");
  $("media-player-shell").querySelector(".media-playing-art")?.remove();
  if (row.kind === "music") $("media-player-shell").prepend(mediaArt(row, "media-playing-art"));
  $("media-codec-error").hidden = true;
  const fallback = $("media-external"); fallback.href = player.src;
  fallback.textContent = preview ? say("Download fixed partial preview for an external player", "Télécharger l’aperçu partiel fixe pour un lecteur externe") : say("Open / download for an external player", "Ouvrir / télécharger pour un lecteur externe");
  if (preview) {
    $("media-preview-state").hidden = false;
    $("media-preview-state").textContent = say(`Partial preview · fixed verified prefix · ${bytes(preview.verified_bytes)} / ${bytes(preview.total_bytes)}. Refresh explicitly after more data downloads.`, `Aperçu partiel · début vérifié fixe · ${bytes(preview.verified_bytes)} / ${bytes(preview.total_bytes)}. Actualisez l’aperçu après téléchargement de données supplémentaires.`);
  }
  for (const child of [...$("media-video").querySelectorAll("track")]) child.remove();
  for (const subtitle of row.subtitles || []) {
    const track = element("track"); track.kind = "subtitles"; track.label = subtitle.label || subtitle.language || "Subtitles"; track.srclang = subtitle.language || "en";
    track.src = subtitle.url || mediaURL(id, `subtitles/${encodeURIComponent(subtitle.id)}`);
    // Keep automatically positioned captions above the shared transport bar.
    track.addEventListener("load", mediaPositionCaptions);
    $("media-video").append(track);
    // A prepared paused player must load external cues before reporting its selectable tracks.
    track.track.mode = "hidden";
  }
  player.onloadedmetadata = () => { const seek = position === null ? row.position || 0 : position; if (!converted && seek > 0 && Number.isFinite(player.duration)) player.currentTime = Math.min(seek, player.duration); };
  if (!paused) await mediaTryPlay(player);
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  mediaQueueRender(); return true;
}
async function mediaTryPlay(player = mediaPlayer()) {
  try { await player.play(); return true; }
  catch (error) { if (error.name === "NotAllowedError") mediaStatus("Press Play in the player to continue playback."); else if (error.name !== "AbortError") mediaCodecError(); return false; }
}
function mediaCodecError() { if (typeof mediaEnvironment === "function") queueMicrotask(mediaEnvironment); $("media-codec-error").hidden = false; $("media-codec-message").textContent = media.preview ? say("This partial preview cannot play yet. The format may need the missing end of the file, or its codec may be unsupported. Wait for more data and use Refresh preview.", "Cet aperçu partiel ne peut pas encore être lu. Le format peut exiger la fin du fichier ou son codec peut être incompatible. Attendez davantage de données, puis actualisez l’aperçu.") : say("This browser could not play this format. Choose a compatible quality or open the original in an external player.", "Ce navigateur ne peut pas lire ce format. Choisissez une qualité compatible ou ouvrez l’original dans un lecteur externe."); }
async function mediaStart(ids, index = 0) {
  const request = {generation: mediaInvalidatePlayback(), client: mediaClient(), selectedClient: state.clientId, session: null};
  ids = await ids;
  if (!mediaRequestCurrent(request) || !ids.length) return;
  if (media.session && media.playerClient !== request.client) { mediaPlayer().pause(); media.session = null; }
  await mediaSession();
  if (!mediaRequestCurrent(request)) return;
  request.session = {...media.session}; request.queue = [...ids]; request.index = index;
  const loaded = await mediaLoad(ids[index], null, false, null, request);
  if (loaded && mediaRequestCurrent(request)) await mediaHeartbeat();
}
async function mediaEnqueue(ids) { if (media.session && media.playerClient !== mediaClient()) throw Error("Choose the playing client before adding to its queue."); await mediaSession(); media.queue.push(...ids); mediaQueueRender(); await mediaHeartbeat(); }
async function mediaAdvance(delta) {
  if (!media.queue.length) return;
  let index = media.index + delta;
  if (media.shuffle && delta > 0 && media.queue.length > 1) index = (media.index + 1 + Math.floor(Math.random() * (media.queue.length - 1))) % media.queue.length;
  if (media.repeat === "all") index = (index + media.queue.length) % media.queue.length;
  if (index < 0 || index >= media.queue.length) return;
  media.index = index; await mediaLoad(media.queue[index], 0); mediaQueueRender();
}
async function mediaRemoveAt(index) {
  const previous = media.index;
  media.queue.splice(index, 1);
  if (index < previous) media.index--;
  else if (index === previous) {
    mediaPlayer().pause(); media.index = Math.min(index, Math.max(0, media.queue.length - 1));
    if (media.queue.length) await mediaLoad(media.queue[media.index], 0);
    else { await mediaStreamStop(mediaPlayer()); delete mediaPlayer().dataset.mediaId; delete mediaPlayer().dataset.sourceToken; media.trackResult = null; mediaPlayer().removeAttribute("src"); mediaPlayer().load(); await mediaReleasePreview(); }
  }
  mediaQueueRender(); await mediaHeartbeat();
}
async function mediaQueueMetadata() {
  if (!media.session) return;
  const ids = [...new Set(media.queue.filter(id => !mediaItems.has(id)))];
  const results = await Promise.allSettled(ids.map(id => api(`media/items/${encodeURIComponent(id)}?${new URLSearchParams({client_id: media.playerClient})}`)));
  for (const result of results) if (result.status === "fulfilled") mediaItems.set(result.value.id, result.value);
  mediaQueueRender();
}
function mediaQueueRender() {
  if (typeof mediaEnvironment === "function") mediaEnvironment();
  mediaPlayerEnvironment();
}
async function mediaCommands(commands) {
  for (const command of [...commands].sort((a, b) => a.sequence - b.sequence)) {
    if (command.sequence <= media.ack) continue;
    const player = mediaPlayer();
    if (command.action === "play") {
      if (command.media_ids?.length) {
        const request = {generation: mediaInvalidatePlayback(), client: media.playerClient || mediaClient(), selectedClient: state.clientId,
          session: media.session ? {...media.session} : null, queue: [...command.media_ids], index: command.index || 0, sourceToken: command.load_token};
        await mediaLoad(request.queue[request.index], command.position ?? null, !!command.start_paused, null, request);
      } else if ((command.media_id || command.source_token) && !mediaSourceMatches(command)) {
        const error = "The playback source changed. The prepared player was not resumed.";
        media.trackResult = {sequence: command.sequence, applied: false, error}; mediaStatus(error, "bad");
      } else {
        const played = await mediaTryPlay();
        if (command.source_token) {
          const applied = played && mediaSourceMatches(command);
          media.trackResult = {sequence: command.sequence, applied, error: applied ? "" : "The browser did not resume the prepared media source."};
        }
      }
    }
    if (command.action === "select_track") mediaSelectTrack(command);
    if (command.action === "pause") player.pause();
    if (command.action === "seek") { const seek = () => { guard(() => mediaSeek(Math.max(0, command.position || 0))); }; if (player.readyState) seek(); else player.addEventListener("loadedmetadata", seek, {once: true}); }
    if (command.action === "volume") for (const output of [$("media-video"), $("media-audio")]) output.volume = Math.min(1, Math.max(0, command.volume));
    if (command.action === "queue") {
      media.queue = command.media_ids || []; media.index = command.index || 0;
      if (media.queue.length && media.queue[media.index] !== player.dataset.mediaId) await mediaLoad(media.queue[media.index], 0, player.paused);
      else if (!media.queue.length) { await mediaStreamStop(player); player.pause(); delete player.dataset.mediaId; delete player.dataset.sourceToken; media.trackResult = null; player.removeAttribute("src"); player.load(); await mediaReleasePreview(); }
    }
    if (command.action === "next") await mediaAdvance(1);
    if (command.action === "previous") await mediaAdvance(-1);
    if (command.action === "shuffle") media.shuffle = !!command.shuffle;
    if (command.action === "repeat") media.repeat = command.repeat || "off";
    media.ack = command.sequence;
  }
  mediaQueueRender();
}
let mediaHeartbeatPending=null;
async function mediaHeartbeat(fresh=false) {
  while(mediaHeartbeatPending){if(!fresh)return;await mediaHeartbeatPending}
  if(!media.session || $("workspace").hidden)return;
  mediaHeartbeatPending=(async()=>{
    const browsing=media.browseContext||{};
    const player = mediaPlayer();
    const report = {current_id: player.dataset.mediaId || null, queue: media.queue, index: media.index, position: mediaFilmPosition(player), duration: mediaFilmDuration(player), paused: player.paused, volume: player.volume, shuffle: media.shuffle, repeat: media.repeat, command_ack: media.ack, track_state: mediaTrackState(), track_result: media.trackResult || null};
    const response = await api(`media/sessions/${encodeURIComponent(media.session.id)}`, {token: media.session.token, report, context: {preview: media.preview ? {item_id: media.preview.item_id, verified_bytes: media.preview.verified_bytes, total_bytes: media.preview.total_bytes} : null, kind: media.kind, view: browsing.view || media.view, selection: media.selected?.id || null, filters: browsing}});
    mediaTrackRequestFailure(response.state?.track_request);
    await mediaCommands(response.commands || []);
    mediaPlayerEnvironment();
  })();
  try {await mediaHeartbeatPending} finally {mediaHeartbeatPending=null}
}
async function mediaScan() {
  const job = await api("media/scan", {client_id: mediaClient()}); media.scan = job.id; media.scanQuiet = true;
}
// New films and episodes appear on their own: a quiet rescan reloads only what changed.
const MEDIA_AUTO_REFRESH = 60000;
async function mediaAutoScan() {
  if (state.view !== "media" || $("workspace").hidden || media.scan || !state.setup?.capabilities?.scan) return;
  await mediaScan();
}
async function mediaPollScan() {
  if (!media.scan) return;
  const job = await api(`jobs/${encodeURIComponent(media.scan)}`);
  if (!["queued", "running"].includes(job.status)) {
    media.scan = ""; media.scanQuiet = false;
    if (job.result?.changed) await loadMedia();
  }
}
const MEDIA_CHAT_MIN = 320, MEDIA_SIDE_MIN = 480;
function mediaChatWidth(width) {
  // The chat keeps its remembered width, leaving the media side its minimum.
  const navigation = document.querySelector("main")?.getBoundingClientRect().left || 0;
  const clamped = Math.round(Math.max(MEDIA_CHAT_MIN, Math.min(width, window.innerWidth - navigation - MEDIA_SIDE_MIN)));
  document.body.style.setProperty("--media-chat-width", `${clamped}px`);
  return clamped;
}
function mediaRestoreChatWidth() {
  let saved = 0;
  try { saved = Number(localStorage.getItem("tl-media-chat-width")) || 0; } catch {}
  mediaChatWidth(saved || window.innerWidth * 0.38);
}
function mediaRememberChatWidth(width) { try { localStorage.setItem("tl-media-chat-width", String(width)); } catch {} }
function mediaChatButtons() {
  queueMicrotask(()=>window.dispatchEvent(new Event("media-host-changed")));
  $("media-chat-resize").setAttribute("aria-label", say("Resize chat", "Redimensionner la discussion"));
  mediaPlayerEnvironment();
}
async function mediaOpenChat(conversationId = "", fresh = false) {
  await mediaSession(); await mediaHeartbeat(true);
  const result = await api(`media/sessions/${encodeURIComponent(media.session.id)}/chat`, {token: media.session.token, conversation_id: conversationId, new: fresh});
  if (!media.chat) mediaRestoreChatWidth();
  media.chat = true; $("media-chat-panel").hidden = false; document.body.classList.add("media-chat-open");
  mediaChatButtons();
  await mountMediaAssistant($("media-chat-content"), result.conversation_id);
  $("assistant-prompt")?.focus();
}
async function mediaToggleChat() { if (media.chat) mediaCloseChat(); else await mediaOpenChat(); }
function mediaCloseChat() { media.chat = false; $("media-chat-panel").hidden = true; document.body.classList.remove("media-chat-open"); mediaChatButtons(); restoreMediaAssistant(); }
function mediaStartChatResize(event) {
  event.preventDefault();
  // Keep drag events in the host when the pointer crosses the browsing iframe.
  event.currentTarget.setPointerCapture(event.pointerId);
  document.body.classList.add("media-chat-resizing");
  let width = 0;
  const move = e => { width = mediaChatWidth(window.innerWidth - e.clientX); };
  const done = () => {
    window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", done); window.removeEventListener("pointercancel", done);
    document.body.classList.remove("media-chat-resizing");
    if (width) mediaRememberChatWidth(width);
  };
  window.addEventListener("pointermove", move); window.addEventListener("pointerup", done); window.addEventListener("pointercancel", done);
}
function mediaChatResizeKey(event) {
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  const current = $("media-chat-panel").getBoundingClientRect().width;
  mediaRememberChatWidth(mediaChatWidth(current + (event.key === "ArrowLeft" ? 24 : -24)));
}
function mediaCenterAppearance(enabled) {
  queueMicrotask(()=>window.dispatchEvent(new Event("media-host-changed")));
  document.body.classList.toggle("media-center-mode", enabled);
}
async function mediaExitCenter() {
  if (document.fullscreenElement === document.documentElement) await document.exitFullscreen();
  mediaCenterAppearance(false);
}
const mediaToggleCenter = () => guard(async () => {
  if (document.body.classList.contains("media-center-mode")) await mediaExitCenter();
  else {
    if (document.fullscreenEnabled) await document.documentElement.requestFullscreen();
    mediaCenterAppearance(true);
  }
});
// A video belongs to Médias: elsewhere it pauses and its player waits out of sight. Music keeps its bar.
function mediaPageChanged(onMedia) {
  const shell = $("media-player-shell"), away = !onMedia && shell.dataset.kind === "video";
  if (away && !shell.hidden) $("media-video").pause();
  shell.classList.toggle("media-shell-away", away);
}
// Full screen shows the film alone: the Médias view fills the window over the picture. Media Center is full screen
// already, so there the player only fills the app, and leaving it never ends Media Center.
const mediaFull = () => document.body.classList.contains("media-player-full");
async function mediaLeaveFull() {
  document.body.classList.remove("media-player-full");
  const owned = media.fullOwned; media.fullOwned = false;
  if (owned && document.fullscreenElement) await document.exitFullscreen().catch(() => {});
  if (typeof mediaEnvironment === "function") mediaEnvironment();
}
async function mediaToggleFullscreen() {
  if (mediaFull()) { await mediaLeaveFull(); return; }
  document.body.classList.add("media-player-full");
  if (!document.fullscreenElement && document.fullscreenEnabled) {
    try { await document.documentElement.requestFullscreen(); media.fullOwned = true; } catch { /* the window fills the page instead */ }
  }
  if (typeof mediaEnvironment === "function") mediaEnvironment();
}
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement) { document.body.classList.remove("media-player-full"); media.fullOwned = false; mediaCenterAppearance(false); }
  mediaPlayerEnvironment();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && mediaFull()) {
    guard(mediaLeaveFull);
  } else if (event.key === "Escape" && document.body.classList.contains("media-center-mode")) {
    guard(mediaExitCenter);
  }
});
mediaSetLayout(media.layout);
document.addEventListener("tl-logout", () => { mediaInvalidatePlayback(); mediaPlayer().pause(); });
document.addEventListener("tl-client-changed", mediaInvalidatePlayback);
for (const event of ["play", "pause", "ended", "emptied"]) $("media-audio").addEventListener(event, mediaMusicBar);
mediaCenterAppearance(document.body.classList.contains("media-center-mode")); mediaChatButtons();
$("media-chat-resize").addEventListener("pointerdown", mediaStartChatResize); $("media-chat-resize").addEventListener("keydown", mediaChatResizeKey);
window.addEventListener("resize", () => { if (media.chat) mediaChatWidth($("media-chat-panel").getBoundingClientRect().width); });
const mediaShowQueue = () => {
  mediaPlayerMenu(true, true);
  guard(mediaQueueMetadata);
};
$("media-video-stage").oncontextmenu = event => { event.preventDefault(); mediaOpenPlayerMenu(); };
$("media-video-stage").addEventListener("keydown", event => {
  if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) { event.preventDefault(); mediaOpenPlayerMenu(); }
});
for (const event of ["pointermove", "pointerdown"]) $("media-video-stage").addEventListener(event, () => mediaRevealControls(false));
for (const player of [$("media-video"), $("media-audio")]) {
  for (const event of ["play", "pause", "ended", "emptied", "timeupdate", "progress", "durationchange", "volumechange", "loadedmetadata", "ratechange"])
    player.addEventListener(event, () => {
      $("media-video-stage").dataset.playing = String(!$("media-video").paused && !$("media-video").ended);
      mediaPlayerEnvironment();
    });
}
for (const player of [$("media-video"), $("media-audio")]) { player.onerror = mediaCodecError; player.onwaiting = () => { if (media.preview && player.currentTime > 0) mediaStatus(say("The fixed partial preview has no more playable data here. Wait for more download progress, then refresh preview.", "L’aperçu partiel fixe ne contient plus de données lisibles à cet endroit. Attendez la progression du téléchargement, puis actualisez l’aperçu.")); }; player.onended = () => guard(async () => { if (media.preview) { mediaStatus(say("End of fixed partial preview. Wait for more data, then refresh preview.", "Fin de l’aperçu partiel fixe. Attendez davantage de données, puis actualisez l’aperçu.")); } else if (media.repeat === "one") { await mediaSeek(0); await mediaTryPlay(player); } else await mediaAdvance(1); await mediaHeartbeat(); }); }
setInterval(() => { guard(mediaHeartbeat); guard(mediaPollScan); }, 1000);
setInterval(() => guard(mediaAutoScan), MEDIA_AUTO_REFRESH);
