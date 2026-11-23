"use strict";
// HTML media elements decode playback; both hosts render the bundled player view.
let playerQueueSignature = "",
  playerQueueRevision = 0,
  playerPlaylists = [],
  playerPlaylistsClient = "",
  playerMenuOpen = false;
let playerOverlayTimer,
  playerPlaylistGeneration = 0;
function mediaPlayerSnapshot() {
  const player = mediaPlayer(),
    shell = $("media-player-shell");
  const signature = JSON.stringify([media.playerClient, media.queue]);
  if (signature !== playerQueueSignature) {
    playerQueueSignature = signature;
    playerQueueRevision++;
  }
  return {
    mode: "web",
    language,
    theme: document.documentElement.dataset.theme || "dark",
    client_id: media.playerClient || mediaClient(),
    media_id: player.dataset.mediaId || "",
    source_token: player.dataset.sourceToken || "",
    queue_revision: playerQueueRevision,
    kind: shell.dataset.kind || media.kind,
    title: $("media-now-playing").textContent,
    playing: !player.paused,
    position: mediaFilmPosition(player),
    duration: mediaFilmDuration(player),
    volume: player.volume,
    shuffle: media.shuffle,
    repeat: media.repeat,
    tracks: mediaTrackState(),
    queue: media.queue.map((id) => ({
      id,
      title: mediaItems.get(id)?.title || "",
    })),
    index: media.index,
    playlists:
      playerPlaylistsClient === (media.playerClient || mediaClient())
        ? playerPlaylists
        : [],
    fullscreen: mediaFull(),
    center: document.body.classList.contains("media-center-mode"),
    can_expand: shell.dataset.kind === "video",
    expanded: shell.classList.contains("media-player-expanded"),
    external_available: !!player.dataset.mediaId,
    external_url: player.dataset.mediaId ? new URL(mediaURL(player.dataset.mediaId),location.href).href : "",
    preview: !!media.preview,
    available_height:
      shell.dataset.kind === "video"
        ? Math.max(180, $("media-video-stage").clientHeight)
        : 380,
    // Horizon draws its own bar and pause screen from the playing film's facts.
    skin: media.layout === "horizon" ? "horizon" : "",
    item: mediaPlayerDetailsSnapshot().item,
  };
}
// The Médias view draws a playing video's controls and details over its picture, from this.
function mediaPlaybackSnapshot() {
  const player = mediaPlayer(),
    shell = $("media-player-shell");
  if (shell.hidden || shell.dataset.kind !== "video" || !player.dataset.mediaId) return null;
  const snapshot = mediaPlayerSnapshot(),
    row = mediaItems.get(player.dataset.mediaId);
  const fields = ["title", "original_title", "year", "duration", "genre", "rating", "tagline", "description", "director", "actors", "release", "codec", "watched", "age_rating"];
  const error = !$("media-codec-error").hidden ? $("media-codec-message").textContent : "";
  return {
    kind: "video",
    media_id: snapshot.media_id,
    client_id: snapshot.client_id,
    source_token: snapshot.source_token,
    queue_revision: snapshot.queue_revision,
    title: snapshot.title,
    playing: snapshot.playing,
    position: snapshot.position,
    buffered: Array.from({length:player.buffered.length},(_,i)=>[player.buffered.start(i)+Number(player.dataset.streamOffset||0),player.buffered.end(i)+Number(player.dataset.streamOffset||0)]),
    quality: player.dataset.streamQuality || "original",
    qualities: media.preview ? ["original"] : (mediaPlaybackFacts.get(snapshot.media_id)?.qualities || ["original"]),
    audio_choices: media.preview ? [] : (mediaPlaybackFacts.get(snapshot.media_id)?.audio || []),
    audio_choice: mediaAudioChoice,
    rate: player.playbackRate,
    repeat: media.repeat,
    queue_count: media.queue.length, queue:snapshot.queue, index:snapshot.index,
    volume: snapshot.volume,
    duration: snapshot.duration,
    tracks: snapshot.tracks,
    item: row ? Object.fromEntries(fields.map((key) => [key, row[key] ?? null])) : null,
    has_next: media.index < media.queue.length - 1 || (media.repeat === "all" && media.queue.length > 1),
    preview: media.preview ? { verified_bytes: media.preview.verified_bytes, total_bytes: media.preview.total_bytes } : null,
    full: snapshot.fullscreen,
    error,
    external_available: snapshot.external_available,
    external_url: snapshot.media_id ? new URL(mediaURL(snapshot.media_id),location.href).href : "",
  };
}
function mediaPlayerEnvironment() {
  if (typeof mediaPositionCaptions !== "function") return;
  mediaPositionCaptions();
  if (typeof mediaEnvironment === "function") mediaEnvironment();
  $("player-frame").title = say(
    "Media player controls",
    "Commandes du lecteur multimédia",
  );
  $("player-frame").contentWindow?.postMessage(
    { type: "player-environment", value: mediaPlayerSnapshot() },
    location.origin,
  );
  $("player-details-frame").title = say("Now playing", "En lecture");
  mediaPlayerDetails();
}
function mediaPlayerMenu(open, queue = false) {
  mediaPlayerEnvironment();
  $("player-frame").contentWindow?.postMessage(
    { type: "player-menu", open, queue },
    location.origin,
  );
  if (open) {
    guard(mediaPlayerPlaylists);
    mediaRevealControls(true);
  }
}
function mediaRevealControls(keyboard) {
  const stage = $("media-video-stage");
  stage.classList.add("media-controls-revealed");
  clearTimeout(playerOverlayTimer);
  playerOverlayTimer = setTimeout(
    () => stage.classList.remove("media-controls-revealed"),
    1600,
  );
}
async function mediaPlayerPlaylists() {
  const client = media.playerClient || mediaClient(),
    generation = ++playerPlaylistGeneration;
  const result = await api(
    `media/playlists?${new URLSearchParams({ client_id: client })}`,
  );
  if (
    generation !== playerPlaylistGeneration ||
    client !== (media.playerClient || mediaClient())
  )
    return;
  playerPlaylists = result.rows || result;
  playerPlaylistsClient = client;
  mediaPlayerEnvironment();
}
function mediaPlayerValidate(body) {
  const snapshot = mediaPlayerSnapshot();
  for (const key of ["client_id", "media_id", "source_token"])
    if (body[key] !== snapshot[key])
      throw Error("Player source changed. Use the current controls.");
  if (
    ["queue-play", "queue-remove", "playlist-save"].includes(body.action) &&
    body.queue_revision !== snapshot.queue_revision
  )
    throw Error("The playback queue changed. Use the current controls.");
}
async function mediaPlayerControl(body) {
  mediaPlayerValidate(body);
  const { action, values = {} } = body,
    player = mediaPlayer();
  if (!values || typeof values !== "object" || Array.isArray(values))
    throw Error("Invalid player values.");
  const numeric = (key) => {
    if (!Number.isFinite(values[key])) throw Error("Invalid player value.");
    return values[key];
  };
  if(action === "quality") await mediaChangeQuality({quality:values.quality});
  else if(action === "audio") await mediaChangeQuality({quality:mediaQuality==="original"?"720":mediaQuality,audio:values.audio});
  else if(action === "rate") {
    if(![.5,.75,1,1.25,1.5,1.75,2].includes(values.rate))throw Error("Invalid playback speed.");
    player.defaultPlaybackRate=values.rate;player.playbackRate=values.rate;
  } else if (action === "toggle") {
    if (player.paused) await mediaTryPlay(player);
    else player.pause();
  } else if (action === "seek") await mediaSeek(numeric("position"));
  else if (action === "volume")
    for (const output of [$("media-video"), $("media-audio")])
      output.volume = Math.max(0, Math.min(1, numeric("volume")));
  else if (action === "previous" || action === "next")
    await mediaAdvance(action === "previous" ? -1 : 1);
  else if (action === "shuffle") media.shuffle = !!values.shuffle;
  else if (action === "repeat") {
    if (!["off", "one", "all"].includes(values.repeat))
      throw Error("Invalid repeat mode.");
    media.repeat = values.repeat;
  } else if (action === "select_track")
    mediaSelectTrack({
      ...values,
      media_id: body.media_id,
      source_token: body.source_token,
    });
  else if (action === "fullscreen") await mediaToggleFullscreen();
  else if (action === "stop") await mediaStop();
  else if (action === "chat") await mediaToggleChat();
  else if (action === "center") await mediaToggleCenter();
  else if (action === "expand")
    $("media-player-shell").classList.toggle("media-player-expanded");
  else if (action === "refresh-preview") {
    if (media.preview) await mediaPreview(media.preview.item_id, true);
  } else if (action === "queue-play" || action === "queue-remove") {
    const index = numeric("index");
    if (!Number.isInteger(index) || index < 0 || index >= media.queue.length)
      throw Error("Queue item is unavailable.");
    if (action === "queue-remove") await mediaRemoveAt(index);
    else {
      media.index = index;
      await mediaLoad(media.queue[index], 0);
    }
  } else if (action === "playlist-save") {
    if (typeof values.name !== "string" || !values.name.trim())
      throw Error("Enter a playlist name.");
    await api("media/playlists", {
      client_id: body.client_id,
      name: values.name.trim(),
      media_ids: [...media.queue],
    });
    await mediaPlayerPlaylists();
    mediaRefreshView();
  } else if (action === "playlist-load" || action === "playlist-delete") {
    if (playerPlaylistsClient !== body.client_id)
      throw Error("Playlists are not ready for this client.");
    const playlist = playerPlaylists.find((row) => row.id === values.id);
    if (!playlist) throw Error("Playlist is unavailable.");
    if (action === "playlist-load") {
      media.queue = [...playlist.media_ids];
      media.index = 0;
      if (media.queue.length) await mediaLoad(media.queue[0], 0);
      mediaQueueRender();
    } else {
      await api(
        `media/playlists/${encodeURIComponent(playlist.id)}?${new URLSearchParams({ client_id: body.client_id })}`,
        undefined,
        "DELETE",
      );
      await mediaPlayerPlaylists();
      mediaRefreshView();
    }
  } else throw Error("Unknown player control.");
  mediaPlayerEnvironment();
  await mediaHeartbeat();
}
window.addEventListener("message", async (event) => {
  const frame = $("player-frame"),
    message = event.data;
  if (event.origin !== location.origin || event.source !== frame.contentWindow)
    return;
  if (message?.type === "player-ready") {
    mediaPlayerEnvironment();
    return;
  }
  if (message?.type !== "player-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    const body = message.body;
    if (!body || typeof body !== "object" || Array.isArray(body))
      throw Error("Invalid player request.");
    if (message.path === "command") await mediaPlayerControl(body);
    else if (message.path === "layout") {
      // Horizon's pause screen covers the picture; the page never asks for more.
      frame.style.height = `${Math.max(72, Math.min(2000, Number(body.height) || 80))}px`;
      const opened = !playerMenuOpen && !!body.menu_open;
      playerMenuOpen = !!body.menu_open;
      $("media-video-stage").dataset.menuOpen = String(playerMenuOpen);
      if (opened) {
        await mediaPlayerPlaylists();
        await mediaQueueMetadata();
      }
    } else if (message.path === "interaction")
      mediaRevealControls(!!body.keyboard);
    else if (message.path === "artwork") {
      const current = mediaPlayerDetailsSnapshot();
      if (body.media_id !== current.media_id || !current.item?.artwork)
        throw Error("Player source changed.");
      const url = new URL(
        `api/media/items/${encodeURIComponent(current.media_id)}/artwork`,
        document.baseURI,
      );
      url.searchParams.set("client_id", current.client_id);
      frame.contentWindow?.postMessage(
        {
          type: "player-response",
          id: message.id,
          value: { data_url: await mediaArtworkDataURL(url) },
        },
        location.origin,
      );
      return;
    }
    else throw Error("Unknown player operation.");
    frame.contentWindow?.postMessage(
      { type: "player-response", id: message.id, value: null },
      location.origin,
    );
  } catch (error) {
    frame.contentWindow?.postMessage(
      { type: "player-response", id: message.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", mediaPlayerEnvironment);
document.addEventListener("tl-language-changed", mediaPlayerEnvironment);
new MutationObserver(mediaPlayerEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});

// Posters reach the bundled views as data URLs: their pages may not load images.
async function mediaArtworkDataURL(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) throw Error("Artwork unavailable");
  const blob = await response.blob();
  if (blob.size > 8 * 1024 * 1024) throw Error("Artwork too large");
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

// The playing video's details under the picture: the same view as the desktop's.
let playerDetailsPublished = "";
function mediaPlayerDetailsSnapshot() {
  const player = mediaPlayer(),
    id = player.dataset.mediaId || "",
    row = mediaItems.get(id),
    video = !!row && $("media-player-shell").dataset.kind === "video";
  const fields = [
    "title",
    "original_title",
    "year",
    "duration",
    "genre",
    "rating",
    "tagline",
    "description",
    "director",
    "actors",
    "release",
    "codec",
  ];
  return {
    language,
    theme: document.documentElement.dataset.theme || "dark",
    client_id: media.playerClient || mediaClient(),
    media_id: id,
    source_token: player.dataset.sourceToken || "",
    item: video
      ? {
          ...Object.fromEntries(fields.map((key) => [key, row[key] ?? null])),
          artwork: !!row.artwork_url,
        }
      : null,
    tracks: video ? mediaTrackState() : {},
  };
}
function mediaPlayerDetails() {
  // The frame can be ready before media.js has loaded; its first publish then waits.
  if (typeof mediaPositionCaptions !== "function") return;
  const value = mediaPlayerDetailsSnapshot(),
    encoded = JSON.stringify(value);
  // Called with every player update: the page renders only when its details change.
  if (encoded === playerDetailsPublished) return;
  playerDetailsPublished = encoded;
  $("player-details-frame").contentWindow?.postMessage(
    { type: "nowplaying-environment", value },
    location.origin,
  );
}
window.addEventListener("message", async (event) => {
  const frame = $("player-details-frame"),
    message = event.data;
  if (event.origin !== location.origin || event.source !== frame.contentWindow)
    return;
  if (message?.type === "nowplaying-ready") {
    playerDetailsPublished = "";
    mediaPlayerDetails();
    return;
  }
  if (message?.type !== "nowplaying-request") return;
  const reply = (value, error) =>
    frame.contentWindow?.postMessage(
      { type: "nowplaying-response", id: message.id, value, error },
      location.origin,
    );
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    const body = message.body;
    if (!body || typeof body !== "object" || Array.isArray(body))
      throw Error("Invalid details request.");
    let value = null;
    if (message.path === "layout")
      frame.style.height = `${Math.max(0, Math.min(600, Number(body.height) || 0))}px`;
    else if (message.path === "artwork") {
      const current = mediaPlayerDetailsSnapshot();
      if (body.media_id !== current.media_id || !current.item?.artwork)
        throw Error("Player source changed.");
      const url = new URL(
        `api/media/items/${encodeURIComponent(current.media_id)}/artwork`,
        document.baseURI,
      );
      url.searchParams.set("client_id", current.client_id);
      value = { data_url: await mediaArtworkDataURL(url) };
    } else if (message.path === "command") {
      if (body.action !== "select_track") throw Error("Unknown details control.");
      await mediaPlayerControl(body);
    } else throw Error("Unknown details operation.");
    reply(value);
  } catch (error) {
    reply(undefined, error.message);
  }
});
