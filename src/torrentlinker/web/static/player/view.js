"use strict";
const $ = (id) => document.getElementById(id);
let state = {},
  request,
  menuOpen = false,
  seeking = false,
  volumeChanging = false;
const say = (en, fr) => (state.language === "fr" ? fr : en);
const scope = () => ({
  client_id: state.client_id,
  media_id: state.media_id,
  source_token: state.source_token,
  queue_revision: state.queue_revision,
});
const time = (value) => {
  const total = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(total / 3600),
    minutes = Math.floor(total / 60) % 60;
  return `${hours ? hours + ":" + String(minutes).padStart(2, "0") : minutes}:${String(total % 60).padStart(2, "0")}`;
};
async function send(action, values = {}, source = scope()) {
  $("player-error").hidden = true;
  try {
    return await request("command", { action, values, ...source });
  } catch (error) {
    const translations = {
      "Player source changed. Use the current controls.":
        "Le média a changé. Utilisez les commandes actuelles.",
      "The playback queue changed. Use the current controls.":
        "La file de lecture a changé. Utilisez les commandes actuelles.",
      "Playlists are not ready for this client.":
        "Les playlists de ce client ne sont pas encore prêtes.",
      "Playlist is unavailable.": "Cette playlist n’est pas disponible.",
      "Queue item is unavailable.":
        "Cet élément de la file n’est pas disponible.",
      "Enter a playlist name.": "Saisissez un nom de playlist.",
    };
    $("player-error").textContent =
      state.language === "fr"
        ? translations[error.message] || error.message
        : error.message;
    $("player-error").hidden = false;
  }
}
function label(id, en, fr) {
  $(id).textContent = say(en, fr);
}
function accessible(id, en, fr) {
  const text = say(en, fr);
  $(id).setAttribute("aria-label", text);
  $(id).title = text;
}
function setMenu(open) {
  menuOpen = open;
  $("player-menu").hidden = !open;
  $("player-options").setAttribute("aria-expanded", String(open));
  if (open) $("player-menu-close").focus();
  horizon(); // the menu replaces Horizon's pause details
}
function tracks(id, rows, selected, disabled, off = false) {
  const select = $(id);
  const signature = JSON.stringify([
    state.source_token,
    state.language,
    rows.map((row) => [row.id, row.label, row.language]),
    off,
  ]);
  if (select.dataset.signature !== signature) {
    select.replaceChildren();
    if (off)
      select.add(
        new Option(say("Subtitles off", "Sous-titres désactivés"), "off"),
      );
    for (const row of rows)
      select.add(
        new Option(
          [row.label, row.language].filter(Boolean).join(" · "),
          row.id,
        ),
      );
    select.dataset.signature = signature;
  }
  select.value = selected || (off ? "off" : "");
  select.disabled = disabled;
  const source = scope();
  select.onchange = () =>
    send(
      "select_track",
      { kind: off ? "subtitle" : "audio", track_id: select.value },
      source,
    );
}
function fitMenu() {
  const reserved =
    $("player-controls").getBoundingClientRect().height +
    $("player-error").getBoundingClientRect().height;
  $("player-menu").style.maxHeight =
    `${Math.max(60, Math.min(380, state.available_height || 380) - reserved)}px`;
}
function render() {
  document.documentElement.lang = state.language || "en";
  document.documentElement.dataset.theme = state.theme || "dark";
  document.body.dataset.kind = state.kind || "video";
  fitMenu();
  const video = state.kind !== "music",
    playing = Boolean(state.playing);
  accessible(
    "player-play",
    playing ? "Pause" : "Play",
    playing ? "Pause" : "Lecture",
  );
  $("player-play").textContent = playing ? "Ⅱ" : "▶";
  accessible(
    "player-previous",
    video ? "Back 10 seconds" : "Previous",
    video ? "Reculer de 10 secondes" : "Précédent",
  );
  accessible(
    "player-next",
    video ? "Forward 10 seconds" : "Next",
    video ? "Avancer de 10 secondes" : "Suivant",
  );
  accessible("player-seek", "Seek", "Position");
  accessible("player-volume", "Volume", "Volume");
  accessible("player-options", "Player options", "Options du lecteur");
  accessible("player-menu-close", "Close", "Fermer");
  accessible(
    "player-fullscreen",
    state.fullscreen ? "Exit fullscreen" : "Fullscreen",
    state.fullscreen ? "Quitter le plein écran" : "Plein écran",
  );
  $("player-fullscreen").hidden = !video;
  $("player-title").textContent = video ? "" : state.title || "";
  $("player-time").textContent =
    `${time(state.position)} / ${time(state.duration)}`;
  if (!seeking) {
    $("player-seek").max = Math.max(0, state.duration || 0);
    $("player-seek").value = state.position || 0;
  }
  $("player-seek").disabled = !state.duration;
  $("player-play").disabled = !state.media_id;
  $("player-previous").disabled = $("player-next").disabled = !state.media_id;
  if (!volumeChanging) $("player-volume").value = state.volume ?? 1;
  label("player-menu-title", "Player options", "Options du lecteur");
  accessible("player-menu", "Player options", "Options du lecteur");
  label("audio-label", "Audio track", "Piste audio");
  accessible("player-audio", "Audio track", "Piste audio");
  accessible("player-subtitle", "Subtitle track", "Piste de sous-titres");
  label("subtitle-label", "Subtitle track", "Piste de sous-titres");
  label("repeat-label", "Repeat", "Répétition");
  label("player-shuffle", "Shuffle", "Aléatoire");
  $("player-shuffle").setAttribute(
    "aria-pressed",
    String(Boolean(state.shuffle)),
  );
  const repeat = $("player-repeat"),
    repeatSignature = state.language || "en";
  if (repeat.dataset.language !== repeatSignature) {
    repeat.replaceChildren(
      new Option(say("Repeat off", "Sans répétition"), "off"),
      new Option(say("Repeat all", "Tout répéter"), "all"),
      new Option(say("Repeat one", "Répéter le morceau"), "one"),
    );
    repeat.dataset.language = repeatSignature;
  }
  repeat.value = state.repeat || "off";
  const inventory = state.tracks || {};
  tracks(
    "player-audio",
    inventory.audio || [],
    (inventory.audio || []).find((row) => row.selected)?.id,
    !inventory.audio_supported,
  );
  tracks(
    "player-subtitle",
    inventory.subtitles || [],
    (inventory.subtitles || []).find((row) => row.selected)?.id,
    !inventory.subtitle_supported,
    true,
  );
  label(
    "player-external",
    state.mode === "web"
      ? "Open / download for an external player"
      : "Open in external player",
    state.mode === "web"
      ? "Ouvrir / télécharger pour un lecteur externe"
      : "Ouvrir dans un lecteur externe",
  );
  $("player-external").disabled = !state.external_available;
  label("player-chat", "Chat about this", "Discuter de ce média");
  label(
    "player-center",
    state.center ? "Return to TorrentLinker" : "Media Center mode",
    state.center ? "Retour à TorrentLinker" : "Mode Media Center",
  );
  label(
    "player-expand",
    state.expanded ? "Collapse player" : "Expand player",
    state.expanded ? "Réduire le lecteur" : "Agrandir le lecteur",
  );
  $("player-expand").hidden = !state.can_expand;
  label("player-stop", "Stop", "Arrêter");
  label("player-refresh-preview", "Refresh preview", "Actualiser l’aperçu");
  $("player-refresh-preview").hidden = !state.preview;
  $("player-refresh-preview").disabled = !!state.preview_loading;
  label(
    "player-track-limit",
    "Embedded track selection depends on this browser. Use an external player if a track is unavailable.",
    "La sélection des pistes intégrées dépend du navigateur. Utilisez un lecteur externe si une piste manque.",
  );
  $("player-track-limit").hidden = state.mode !== "web";
  label("player-queue-title", "Playback queue", "File de lecture");
  const queue = $("player-queue"),
    signature = JSON.stringify([
      scope(),
      state.language,
      state.index,
      state.queue,
    ]);
  if (queue.dataset.signature !== signature) {
    queue.dataset.signature = signature;
    queue.replaceChildren(
      ...(state.queue || []).map((row, index) => {
        const item = document.createElement("li"),
          play = document.createElement("button"),
          remove = document.createElement("button"),
          source = scope();
        play.textContent = `${index + 1}. ${row.title || say("Unavailable item", "Élément indisponible")}`;
        if (index === state.index) play.setAttribute("aria-current", "true");
        play.onclick = () => send("queue-play", { index }, source);
        remove.textContent = say("Remove", "Retirer");
        remove.onclick = () => send("queue-remove", { index }, source);
        item.append(play, remove);
        return item;
      }),
    );
  }
  label(
    "player-playlist-save",
    "Save queue as playlist…",
    "Enregistrer la file en playlist…",
  );
  label("player-playlist-load", "Load playlist", "Charger la playlist");
  label("player-playlist-delete", "Delete playlist", "Supprimer la playlist");
  accessible("player-playlists", "Saved playlists", "Playlists enregistrées");
  const playlists = $("player-playlists"),
    playlistSignature = JSON.stringify([state.language, state.playlists]);
  if (playlists.dataset.signature !== playlistSignature) {
    const selected = playlists.value;
    playlists.replaceChildren(
      ...(state.playlists || []).map((row) => new Option(row.name, row.id)),
    );
    if ([...playlists.options].some((row) => row.value === selected))
      playlists.value = selected;
    playlists.dataset.signature = playlistSignature;
  }
  $("player-playlist-save").disabled = !(state.queue || []).length;
  $("player-playlist-load").disabled = $("player-playlist-delete").disabled =
    !playlists.options.length;
}
// Horizon: the playing film's facts in the bar, and its details over the picture on pause.
let horizonPosterFor = "";
function horizonFacts(item) {
  const minutes = Math.round((Number(item.duration) || 0) / 60),
    rating = Number(item.rating);
  return [
    item.year,
    minutes
      ? say(
          `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`,
          `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`,
        )
      : "",
    item.genre,
    rating > 0
      ? `★ ${rating.toLocaleString(state.language === "fr" ? "fr-FR" : "en-US", { maximumFractionDigits: 1 })}`
      : "",
  ]
    .filter(Boolean)
    .join(" · ");
}
function horizonFlags(root, item) {
  root.replaceChildren(
    ...mediaFlags(item).map(([text, strong]) => {
      const flag = document.createElement("li");
      flag.textContent = text;
      if (strong) flag.className = "strong";
      return flag;
    }),
  );
}
function horizon() {
  const item = state.item,
    on = state.skin === "horizon" && state.kind !== "music" && !!item;
  document.body.dataset.skin = on ? "horizon" : "";
  $("horizon-osd").hidden = !on;
  const paused = on && !state.playing && !!state.media_id && !menuOpen;
  $("horizon-pause").hidden = !paused;
  // Paused, the view covers the picture: details on top, the bar at the foot.
  document.body.style.minHeight = paused
    ? `${Math.max(180, state.available_height || 0)}px`
    : "";
  if (!on) return;
  const facts = horizonFacts(item);
  $("horizon-title").textContent = item.title || "";
  $("horizon-meta").textContent = facts;
  $("horizon-poster-title").textContent = item.title || "";
  horizonFlags($("horizon-flags"), item);
  $("horizon-paused").textContent = say("Paused", "En pause");
  $("horizon-pause-title").textContent = item.title || "";
  $("horizon-pause-meta").textContent = facts;
  horizonFlags($("horizon-pause-flags"), item);
  $("horizon-pause-plot").textContent = item.description || "";
  $("horizon-pause-plot").hidden = !item.description;
  $("horizon-pause-people").textContent = [
    item.director ? `${say("Director", "Réalisation")} · ${item.director}` : "",
    item.actors ? `${say("Starring", "Avec")} · ${item.actors}` : "",
  ]
    .filter(Boolean)
    .join("  —  ");
  const key = `${state.client_id}/${state.media_id}`;
  if (horizonPosterFor === key) return;
  horizonPosterFor = key;
  const poster = $("horizon-poster");
  poster.classList.remove("has-art");
  poster.querySelector("img")?.remove();
  if (!item.artwork) return;
  request("artwork", { media_id: state.media_id })
    .then((result) => {
      if (horizonPosterFor !== key || !result?.data_url) return;
      const image = document.createElement("img");
      image.alt = "";
      image.src = result.data_url;
      poster.prepend(image);
      poster.classList.add("has-art");
    })
    .catch(() => {});
}
window.addEventListener("player-environment", (event) => {
  if (
    state.source_token !== event.detail.source_token ||
    state.client_id !== event.detail.client_id
  ) {
    setMenu(false);
    seeking = volumeChanging = false;
  }
  state = event.detail;
  render();
  horizon();
});
window.addEventListener("message", (event) => {
  if (
    event.origin !== location.origin ||
    event.source !== parent ||
    event.data?.type !== "player-menu"
  )
    return;
  setMenu(!!event.data.open);
  if (event.data.queue) $("player-queue-details").open = true;
});
window.addEventListener("DOMContentLoaded", async () => {
  request = await TLPanel.connect("player", { asynchronous: true });
  const actions = {
    "player-play": "toggle",
    "player-fullscreen": "fullscreen",
    "player-stop": "stop",
    "player-external": "external",
    "player-chat": "chat",
    "player-center": "center",
    "player-expand": "expand",
    "player-refresh-preview": "refresh-preview",
  };
  for (const [id, action] of Object.entries(actions))
    $(id).onclick = () => {
      if (
        [
          "fullscreen",
          "stop",
          "chat",
          "center",
          "expand",
          "refresh-preview",
        ].includes(action)
      )
        setMenu(false);
      if (action === "external" && state.mode === "web") {
        const link = document.createElement("a");
        link.href = state.external_url;
        link.target = "_blank";
        link.rel = "noopener";
        link.download = "";
        link.click();
      } else send(action);
    };
  for (const [id, direction] of [
    ["player-previous", -1],
    ["player-next", 1],
  ])
    $(id).onclick = () =>
      send(
        state.kind === "music" ? (direction < 0 ? "previous" : "next") : "seek",
        { position: Math.max(0, (state.position || 0) + direction * 10) },
      );
  $("player-options").onclick = () => setMenu(!menuOpen);
  $("player-menu-close").onclick = () => {
    setMenu(false);
    $("player-options").focus();
  };
  $("player-shuffle").onclick = () =>
    send("shuffle", { shuffle: !state.shuffle });
  $("player-repeat").onchange = () =>
    send("repeat", { repeat: $("player-repeat").value });
  for (const [id, action] of [
    ["player-seek", "seek"],
    ["player-volume", "volume"],
  ]) {
    const input = $(id);
    let source;
    input.onpointerdown = input.onkeydown = () => {
      source = scope();
    };
    input.oninput = () => {
      source ||= scope();
      if (action === "seek") seeking = true;
      else volumeChanging = true;
    };
    input.onchange = () => {
      send(
        action,
        { [action === "seek" ? "position" : "volume"]: Number(input.value) },
        source || scope(),
      );
      source = null;
      seeking = volumeChanging = false;
    };
  }
  $("player-playlist-save").onclick = () => {
    const source = scope(),
      name = prompt(say("Playlist name", "Nom de la playlist"));
    if (name?.trim()) send("playlist-save", { name: name.trim() }, source);
  };
  for (const action of ["load", "delete"])
    $(`player-playlist-${action}`).onclick = () =>
      send(`playlist-${action}`, { id: $("player-playlists").value });
  window.addEventListener("blur", () =>
    request("interaction", { keyboard: false }).catch(() => {}),
  );
  let interactionTime = 0;
  document.addEventListener("pointermove", () => {
    if (performance.now() - interactionTime < 500) return;
    interactionTime = performance.now();
    request("interaction", { keyboard: false }).catch(() => {});
  });
  document.addEventListener("keydown", (event) => {
    request("interaction", { keyboard: true }).catch(() => {});
    if (event.key === "Escape" && menuOpen) {
      event.preventDefault();
      setMenu(false);
      $("player-options").focus();
    } else if (event.key === "Escape" && state.fullscreen) {
      event.preventDefault();
      send("fullscreen");
    }
  });
  let height = 0;
  new ResizeObserver(() => {
    fitMenu();
    const next = Math.ceil(document.body.getBoundingClientRect().height);
    if (next !== height) {
      height = next;
      request("layout", { height, menu_open: menuOpen }).catch(() => {});
    }
  }).observe(document.body);
  window.playerReady();
});
