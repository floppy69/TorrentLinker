"use strict";
/* Approved theatre preview: the player scrolls with the page; the library banner pins independently.
   The host draws the picture behind the transparent slot; the shared view draws bottom controls.
   The host owns playback; this view shows what it publishes in environment.playback and sends commands. */
const WATCH_ICONS = {
  play: '<path d="M8 5l11 7-11 7z" fill="currentColor"/>', pause: '<path d="M8 5v14M16 5v14"/>',
  rew: '<path d="M11 7l-6 5 6 5M19 7l-6 5 6 5"/>', fwd: '<path d="M13 7l6 5-6 5M5 7l6 5-6 5"/>',
  full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>', exit: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  subs: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 13h4M13 13h4M7 16h7"/>',
  next: '<path d="M6 5l9 7-9 7zM18 5v14"/>', check: '<path d="M5 12l5 5 9-10"/>',
};
const watchIcon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${WATCH_ICONS[name]}</svg>`;
function watchSetIcon(id, name) {
  const button = $(id);
  if (button.dataset.icon === name) return;
  button.dataset.icon = name;
  button.innerHTML = watchIcon(name);
}
const WATCH_HIDE_MS = 3000;
let watchBarHeld = false, watchTimer = 0, watchWasPlaying = false, watchSource = "", watchSignature = "", watchLayoutSent = "", watchLastTop = 0;
const watchScroller = () => document.querySelector(".media-scroll");
const watchPlayback = () => media.kind === "video" && environment.playback?.media_id && environment.playback.kind === "video" ? environment.playback : null;
const watchClock = seconds => {
  const total = Math.max(0, Math.floor(Number(seconds) || 0)), hours = Math.floor(total / 3600), minutes = Math.floor(total / 60) % 60;
  return `${hours ? `${hours}:${String(minutes).padStart(2, "0")}` : minutes}:${String(total % 60).padStart(2, "0")}`;
};
// Commands go to the host with the source they were drawn for, so a stale control never acts on a new film.
function watchSend(action, values = {}) {
  const play = watchPlayback();
  if (!play) return Promise.resolve();
  return host("player", {action, values, client_id: play.client_id, media_id: play.media_id, source_token: play.source_token, queue_revision: play.queue_revision});
}
function watchReveal() {
  const screen = $("media-screen");
  screen.dataset.controls = "on";
  clearTimeout(watchTimer);
  watchTimer = setTimeout(() => { if (watchPlayback()?.playing && $("watch-settings-menu").hidden) screen.dataset.controls = "off"; }, WATCH_HIDE_MS);
}
function watchTap() { watchReveal(); }
function watchTracksDialog() {
  const play = watchPlayback(), root = $("media-watch-tracks");
  if (!play) return;
  const tracks = play.tracks || {};
  root.replaceChildren(button(say("Close", "Fermer"), () => root.close()), element("h2", say("Audio and subtitles", "Audio et sous-titres")));
  const error = element("p", undefined, "media-error"); error.hidden = true;
  const group = (title, rows, kind) => {
    const section = element("section"), list = element("div", undefined, "media-detail-choices");
    for (const row of rows) {
      const choice = button(row.text, async () => {
        error.hidden = true;
        try { await watchSend("select_track", {kind, track_id: row.id}); }
        catch (failure) { error.textContent = failure.message; error.hidden = false; }
      });
      choice.setAttribute("aria-pressed", String(row.selected));
      list.append(choice);
    }
    section.append(element("h3", title), list);
    return section;
  };
  const text = (row, index, fallback) => [...new Set(String(row.label || "").split(" · ").filter(Boolean).filter(part => !/^(audio|subtitle|sous-titre|embedded subtitle|sous-titre intégré) \d+$/i.test(part)).filter(part => part.toLowerCase() !== String(row.language || "").toLowerCase()))].join(" · ") || row.language || `${fallback} ${index + 1}`;
  const audio = (tracks.audio || []).map((row, index) => ({id: row.id, text: text(row, index, say("Audio", "Audio")), selected: !!row.selected}));
  const subtitles = (tracks.subtitles || []).map((row, index) => ({id: row.id, text: text(row, index, say("Subtitle", "Sous-titre")), selected: !!row.selected}));
  subtitles.unshift({id: "off", text: say("Off", "Aucun"), selected: !subtitles.some(row => row.selected)});
  if (audio.length) root.append(group(say("Audio", "Audio"), audio, "audio"));
  if (subtitles.length > 1) root.append(group(say("Subtitles", "Sous-titres"), subtitles, "subtitle"));
  if (!audio.length && subtitles.length < 2) root.append(element("p", tracks.ready ? say("This file offers no other audio or subtitle choice.", "Ce fichier ne propose pas d’autre choix d’audio ou de sous-titres.") : say("The tracks are still loading.", "Les pistes se chargent encore."), "muted"));
  root.append(error);
  // The browser decides which embedded tracks it exposes: say so, and offer the file to another player.
  if (environment.mode === "web") root.append(element("p", say("Embedded track selection depends on this browser. Use an external player if a track is unavailable.", "La sélection des pistes intégrées dépend du navigateur. Utilisez un lecteur externe si une piste manque."), "media-track-support"));
  if (play.external_available) {
    if (environment.mode === "web") { const link = element("a", say("Open / download for an external player", "Ouvrir / télécharger pour un lecteur externe")); link.id = "media-watch-external"; link.href = play.external_url; link.target = "_blank"; link.rel = "noopener"; link.download = ""; root.append(link); }
    else { const open = button(say("Open in external player", "Ouvrir dans un lecteur externe"), () => watchSend("external")); open.id = "media-watch-external"; root.append(open); }
  }
  if (!root.open) root.showModal();
}
// A dialog drawn once would keep its old selection; it follows the host's tracks while it is open.
function watchTracksRefresh() { if ($("media-watch-tracks").open) watchTracksDialog(); }
function watchDetails(play) {
  const root = $("media-watch"), parts = [];
  root.hidden = !play.preview;
  if (play.preview) {
    const note = element("p", say(`Partial preview · fixed verified prefix · ${mediaBytes(play.preview.verified_bytes)} / ${mediaBytes(play.preview.total_bytes)}. Refresh explicitly after more data downloads.`, `Aperçu partiel · début vérifié fixe · ${mediaBytes(play.preview.verified_bytes)} / ${mediaBytes(play.preview.total_bytes)}. Actualisez l’aperçu après téléchargement de données supplémentaires.`), "media-watch-note");
    note.append(" ", button(say("Refresh preview", "Actualiser l’aperçu"), () => watchSend("refresh-preview"), "quiet"));
    parts.push(note);
  }
  root.replaceChildren(...parts);
}
const mediaBytes = value => {
  const number = Number(value) || 0;
  return number >= 1e9 ? `${(number / 1e9).toFixed(1)} ${say("GB", "Go")}` : `${Math.round(number / 1e6)} ${say("MB", "Mo")}`;
};
function watchRender() {
  const view = $("view-media"), play = watchPlayback(), was = view.dataset.watch === "true";
  // The page header is hidden on Médias; on the Web the navigation opens from here.
  $("media-navigation").hidden = environment.mode !== "web" || !!environment.center_mode;
  $("media-navigation").setAttribute("aria-label", say("Navigation", "Navigation")); $("media-navigation").title = say("Navigation", "Navigation");
  $("media-brand").hidden = !environment.center_mode;
  view.dataset.watch = String(!!play);
  view.dataset.full = String(!!play && !!play.full);
  $("media-watch-slot").hidden = !play;
  $("media-watch").hidden = !play?.preview;
  if (!play) {
    watchSettingsClose(false);
    if (was) { clearTimeout(watchTimer); $("media-watch-tracks").open && $("media-watch-tracks").close(); delete view.dataset.bar; watchLayoutSent = ""; watchSignature = ""; $("media-watch").replaceChildren(); watchWasPlaying = false; }
    return;
  }
  if (!was) {
    // As in the preview, the bar shows over the film until the page scrolls down, on every screen.
    delete view.dataset.bar; watchBarHeld = false;
    watchLastTop = 0; watchScroller().scrollTop = 0; watchWasPlaying = false; }
  // At the top of the page the bar is always there, unless the phone's start is holding it back.
  if (!watchBarHeld && view.dataset.bar === "hidden" && watchScroller().scrollTop < 40) delete view.dataset.bar;
  // Another film or source closes the track choices drawn for the old one.
  const source = `${play.client_id}/${play.media_id}/${play.source_token}`;
  if (source !== watchSource) {
    watchSource = source; watchSettingsClose(false);
    if (play.item) { media.featureId = play.media_id; media.selected = {...play.item, id: play.media_id, kind: "video"}; }
    mediaRenderFeature(); mediaMarkSelected();
    watchScroller().scrollTop = 0; if ($("media-watch-tracks").open) $("media-watch-tracks").close(); }
  const label = (id, en, fr) => { $(id).setAttribute("aria-label", say(en, fr)); $(id).title = say(en, fr); };
  label("watch-rew", "Back 10 seconds", "Reculer de 10 secondes"); watchSetIcon("watch-rew", "rew");
  label("watch-fwd", "Forward 10 seconds", "Avancer de 10 secondes"); watchSetIcon("watch-fwd", "fwd");
  label("watch-toggle", play.playing ? "Pause" : "Play", play.playing ? "Pause" : "Lecture"); watchSetIcon("watch-toggle", play.playing ? "pause" : "play");
  label("watch-full", play.full ? "Exit full screen" : "Full screen", play.full ? "Quitter le plein écran" : "Plein écran"); watchSetIcon("watch-full", play.full ? "exit" : "full");
  label("watch-tracks", "Audio and subtitles", "Audio et sous-titres"); watchSetIcon("watch-tracks", "subs");
  label("watch-next", "Next", "Suivant"); watchSetIcon("watch-next", "next"); $("watch-next").disabled = !play.has_next;
  label("watch-stop", "Close the player", "Fermer le lecteur"); watchSetIcon("watch-stop", "close");
  label("watch-seek", "Seek", "Position");
  label("watch-volume", "Volume", "Volume");
  label("watch-settings", "Player settings", "Paramètres du lecteur");
  $("watch-settings-menu").setAttribute("aria-label", say("Player settings", "Paramètres du lecteur"));
  if (document.activeElement !== $("watch-volume")) $("watch-volume").value = play.volume ?? 1;
  const seek = $("watch-seek");
  if (!seek.dataset.seeking) { seek.max = Math.max(0, play.duration || 0); seek.value = play.position || 0; }
  seek.parentElement.style.setProperty("--progress", `${play.duration ? Math.min(100, 100 * (Number(seek.value) / play.duration)) : 0}%`);
  const bufferedLayers = (play.buffered || []).flatMap(([start, end]) => {
    if (!(play.duration > 0) || !Number.isFinite(start) || !Number.isFinite(end)) return [];
    const left = Math.max(0, Math.min(100, 100 * start / play.duration));
    const right = Math.max(left, Math.min(100, 100 * end / play.duration));
    return right > left ? [`linear-gradient(90deg,transparent ${left}%,#b1b7bc ${left}%,#b1b7bc ${right}%,transparent ${right}%)`] : [];
  });
  seek.parentElement.style.setProperty("--buffered-track", bufferedLayers.length ? bufferedLayers.join(",") : "linear-gradient(transparent,transparent)");
  seek.disabled = !play.duration;
  $("watch-time").textContent = `${watchClock(play.position)} / ${watchClock(play.duration)}`;
  $("watch-rew").disabled = $("watch-fwd").disabled = $("watch-toggle").disabled = !play.media_id;
  const note = $("media-screen-note");
  note.hidden = !play.error;
  const errorSignature = JSON.stringify([play.error, play.source_token, play.qualities, language]);
  if (play.error && watchErrorSignature !== errorSignature) {
    note.replaceChildren(element("span", play.error));
    if ((play.qualities || []).length > 1) {
      const compatible = element("button", say("Choose compatible quality", "Choisir une qualité compatible"));
      compatible.type = "button"; compatible.onclick = () => watchSettingsOpen("quality"); note.append(" ", compatible);
    }
    if (play.external_available && play.external_url) { const link = element("a", say("Open / download for an external player", "Ouvrir / télécharger pour un lecteur externe")); link.href = play.external_url; link.target = "_blank"; link.rel = "noopener"; link.download = ""; note.append(" ", link); }
  }
  watchErrorSignature = errorSignature;
  const signature = JSON.stringify([play.client_id, play.media_id, play.source_token, language, play.item, play.tracks, play.has_next, play.preview, play.queue_revision, play.external_url]);
  if (signature !== watchSignature) { watchSignature = signature; watchDetails(play); watchTracksRefresh(); }
  // Paused, the controls stay; a film that starts playing clears the picture after the usual delay.
  if (!play.playing) { clearTimeout(watchTimer); $("media-screen").dataset.controls = "on"; }
  else if (!watchWasPlaying) watchReveal();
  watchWasPlaying = !!play.playing;
  watchSettingsRefresh();
  watchReport();
}
// The host draws the picture behind the slot: it needs to know where, and that wherever the page moves.
function watchReport() {
  if (!watchPlayback()) return;
  const rect = node => { const box = node.getBoundingClientRect(); return {x: box.left, y: box.top, width: box.width, height: box.height}; };
  const value = {band: rect($("media-watch-slot")), screen: rect($("media-screen")), menu: $("watch-settings-menu").hidden ? null : rect($("watch-settings-menu"))};
  const key = JSON.stringify(value);
  if (key === watchLayoutSent) return;
  watchLayoutSent = key;
  host("watch-layout", value).catch(() => { watchLayoutSent = ""; });
}
// Keep the menu above the pinned banner; only the theatre picture lets it hide.
function watchScrolled(event) {
  const view = $("view-media");
  if (view.dataset.kind !== "video") return;
  const watching = view.dataset.watch === "true", scroller = watchScroller();
  if (event.target !== (watching ? scroller : document)) return;
  const top = watching ? scroller.scrollTop : scrollY;
  watchBarHeld = false;
  const aboveBanner = media.layout === "cinematic" && (!watching || $("media-screen").getBoundingClientRect().bottom <= document.querySelector(".media-topbar").offsetHeight);
  if (aboveBanner) delete view.dataset.bar;
  else if (top > watchLastTop + 6 && top > 40 && view.dataset.bar !== "hidden") view.dataset.bar = "hidden";
  else if ((top < watchLastTop - 6 || top < 40) && view.dataset.bar === "hidden") delete view.dataset.bar;
  watchLastTop = top;
  watchReport();
}
function watchSetUp() {
  const screen = $("media-screen");
  screen.addEventListener("pointermove", watchReveal);
  screen.addEventListener("focusin", watchReveal);
  screen.addEventListener("click", event => { if (event.target.closest("button, input")) return; watchTap(); });
  const act = (id, action, values) => { $(id).onclick = () => { watchReveal(); guard(() => typeof values === "function" ? watchSend(action, values()) : watchSend(action, values)); }; };
  act("watch-toggle", "toggle");
  act("watch-rew", "seek", () => ({position: Math.max(0, (watchPlayback()?.position || 0) - 10)}));
  act("watch-fwd", "seek", () => ({position: (watchPlayback()?.position || 0) + 10}));
  act("watch-full", "fullscreen");
  act("watch-stop", "stop");
  act("watch-next", "next");
  $("watch-tracks").onclick = () => watchSettingsOpen('subtitles');
  $("watch-settings").innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z"/><circle cx="12" cy="12" r="3"/></svg>';
  $("watch-settings").onclick=()=>$("watch-settings-menu").hidden?watchSettingsOpen():watchSettingsClose();
  document.addEventListener('pointerdown',e=>{if(!e.target.closest('#watch-settings-menu,#watch-settings'))watchSettingsClose(false);});
  document.addEventListener('keydown',e=>{if(!$("watch-settings-menu").hidden&&e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();watchSettingsClose();}},true);
  $("watch-volume").oninput = () => { watchReveal(); guard(() => watchSend("volume", {volume: Number($("watch-volume").value)})); };
  const seek = $("watch-seek");
  seek.oninput = () => { seek.dataset.seeking = "1"; watchReveal(); seek.parentElement.style.setProperty("--progress", `${seek.max > 0 ? 100 * Number(seek.value) / seek.max : 0}%`); };
  seek.onchange = () => { const position = Number(seek.value); delete seek.dataset.seeking; guard(() => watchSend("seek", {position})); };
  $("media-navigation").onclick = () => guard(() => host("navigation"));
  document.addEventListener("scroll", watchScrolled, true);
  const observer = new ResizeObserver(watchReport);
  observer.observe($("media-watch-slot")); observer.observe(screen);
  const bannerObserver = new ResizeObserver(() => {
    document.documentElement.style.setProperty("--media-feature-height", `${$("media-feature").offsetHeight}px`);
    watchReport();
  });
  bannerObserver.observe($("media-feature"));
  addEventListener("resize", watchReport);
  document.addEventListener("keydown", event => {
    if (!watchPlayback() || event.target.closest?.("input, select, textarea, dialog, [contenteditable]")) return;
    if (event.key === "Escape" && environment.playback.full) { event.preventDefault(); guard(() => watchSend("fullscreen")); }
    else if (event.key === "f" || event.key === "F") { event.preventDefault(); guard(() => watchSend("fullscreen")); }
    else if (event.key === " " && !event.target.closest?.("button")) { event.preventDefault(); watchReveal(); guard(() => watchSend("toggle")); }
    else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      if (event.target.closest?.(".media-row-card, .media-focus-choice")) return;
      event.preventDefault(); watchReveal();
      guard(() => watchSend("seek", {position: Math.max(0, (environment.playback.position || 0) + (event.key === "ArrowRight" ? 10 : -10))}));
    }
  });
}
window.addEventListener("DOMContentLoaded", watchSetUp);
window.addEventListener("media-environment", watchRender);

// Shared settings menu: choices come from the active host, never inferred here.
let watchErrorSignature = "";
let watchSettingsPage='main', watchSettingsSignature='';
const watchQualities={'original':['Original',''],'360':['360p','≈ 250 MB/h'],'480':['480p','≈ 450 MB/h'],'720':['720p · HD','≈ 870 MB/h'],'1080':['1080p · Full HD','≈ 1.89 GB/h']};
function watchSettingsClose(focus=true){
  const menu=$('watch-settings-menu'); if(!menu||menu.hidden)return;
  menu.hidden=true;$('watch-settings').setAttribute('aria-expanded','false');
  if(focus)$('watch-settings').focus();watchReveal();watchReport();
}
function watchSettingsOpen(page='main'){
  watchSettingsPage=page;$('watch-settings-menu').hidden=false;
  $('watch-settings').setAttribute('aria-expanded','true');watchReveal();watchSettingsDraw();
  $('watch-settings-menu').querySelector('button,a')?.focus();
}
function watchSettingsRefresh(){
  if($('watch-settings-menu').hidden)return;
  const p=watchPlayback();const sig=JSON.stringify([p?.quality,p?.rate,p?.repeat,p?.tracks,p?.audio_choice]);
  if(sig!==watchSettingsSignature){watchSettingsSignature=sig;watchSettingsDraw();}
}
function watchSettingsDraw(){
  const menu=$('watch-settings-menu'),play=watchPlayback();if(!play)return;
  menu.replaceChildren();
  const row=(label,value,action,selected=false,icon='')=>{
    const b=document.createElement('button');b.type='button';b.className='watch-setting-row';b.setAttribute('role',selected?'menuitemradio':'menuitem');
    if(selected)b.setAttribute('aria-checked','true');
    const mark=element('span',selected?'✓':icon,'watch-setting-icon'),text=element('span',label,'watch-setting-label'),detail=element('span',value,'watch-setting-value');
    mark.setAttribute('aria-hidden','true');
    b.append(mark,text,detail);b.onclick=async()=>{try{await action();}catch(error){const p=element('p',error.message,'watch-setting-note');p.setAttribute('role','alert');menu.append(p);}};menu.append(b);return b;
  };
  const choice=(label,value,action,selected)=>{const b=row(label,value,action,selected);b.setAttribute('role','menuitemradio');b.setAttribute('aria-checked',String(selected));};
  const apply=async(action,values)=>{await watchSend(action,values);watchSettingsClose();};
  const names={quality:say('Quality','Qualité'),speed:say('Playback speed','Vitesse de lecture'),audio:'Audio',subtitles:say('Subtitles','Sous-titres'),repeat:say('Repeat','Répétition'),queue:say('Playback queue','File de lecture')};
  if(watchSettingsPage!=='main')row(names[watchSettingsPage],'',()=>watchSettingsOpen(),false,'‹').classList.add('watch-settings-back');
  if(watchSettingsPage==='main'){
    row(say('Audio','Audio'),play.audio_choices?.find(t=>t.id===play.audio_choice)?.label||play.tracks?.audio?.find(t=>t.selected)?.label||say('Default','Par défaut'),()=>watchSettingsOpen('audio'),false,'♫');
    row(say('Subtitles','Sous-titres'),play.tracks?.subtitles?.find(t=>t.selected)?.label||say('Off','Désactivés'),()=>watchSettingsOpen('subtitles'),false,'▤');
    row(say('Playback speed','Vitesse de lecture'),play.rate===1?say('Normal','Normale'):`${play.rate}×`,()=>watchSettingsOpen('speed'),false,'◷');
    row(say('Quality','Qualité'),play.quality==='original'?'Original':`${play.quality}p`,()=>watchSettingsOpen('quality'),false,'⚙');
    row(say('Repeat','Répétition'),play.repeat==='one'?say('This title','Ce titre'):play.repeat==='all'?say('All','Tous'):say('Off','Non'),()=>watchSettingsOpen('repeat'),false,'↻');
    row(say('Playback queue','File de lecture'),String(play.queue_count||0),()=>watchSettingsOpen('queue'),false,'☷');
    if(play.external_available&&environment.mode!=='web')row(say('External player','Lecteur externe'),'',()=>apply('external',{}));
    if(play.external_url){const link=element('a',say('Open / download original','Ouvrir / télécharger l’original'),'watch-setting-external');link.href=play.external_url;link.target='_blank';link.rel='noopener';link.setAttribute('role','menuitem');menu.append(link);}
  }else if(watchSettingsPage==='quality'){
    for(const value of play.qualities||['original']){const [label,cost]=watchQualities[value];choice(label,environment.mode==='web'?cost:'',()=>apply('quality',{quality:value}),play.quality===value);}
    if((play.qualities||[]).length<2)menu.append(element('p',say('Compatible quality requires FFmpeg on the host.','La qualité compatible nécessite FFmpeg sur la machine hôte.'),'watch-setting-note'));
  }else if(watchSettingsPage==='speed'){
    for(const rate of [.5,.75,1,1.25,1.5,1.75,2])choice(rate===1?say('Normal','Normale'):`${rate}×`,'',()=>apply('rate',{rate}),play.rate===rate);
  }else if(watchSettingsPage==='audio'){
    if(play.audio_choices?.length){for(const track of play.audio_choices)choice(track.label,'',()=>apply('audio',{audio:track.id}),play.audio_choice===track.id);}else{for(const track of play.tracks?.audio||[])choice(track.label||track.language,'',()=>apply('select_track',{kind:'audio',track_id:track.id}),track.selected);}

  }else if(watchSettingsPage==='subtitles'){
    const tracks=play.tracks?.subtitles||[];
    choice(say('Off','Désactivés'),'',()=>apply('select_track',{kind:'subtitle',track_id:'off'}),!tracks.some(t=>t.selected));
    for(const track of tracks)choice(track.label||track.language||'Sous-titre','',()=>apply('select_track',{kind:'subtitle',track_id:track.id}),track.selected);
    if(!tracks.length)menu.append(element('p',say('No tracks available in this player.','Aucune piste disponible pour ce lecteur.'),'watch-setting-note'));
  }else if(watchSettingsPage==='queue'){
    for(const [index,track] of (play.queue||[]).entries())choice(track.title||'Titre',index===play.index?say('Playing','En lecture'):'',()=>apply('queue-play',{index}),index===play.index);
  }else if(watchSettingsPage==='repeat'){
    for(const [repeat,label] of [['off',say('Off','Non')],['one',say('This title','Ce titre')],['all',say('Whole queue','Toute la file')]])choice(label,'',()=>apply('repeat',{repeat}),play.repeat===repeat);
  }
  watchReport();
  menu.onkeydown=e=>{const buttons=[...menu.querySelectorAll('button,a')];let index=buttons.indexOf(document.activeElement);if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();e.stopPropagation();buttons[(index+(e.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();}};
}
