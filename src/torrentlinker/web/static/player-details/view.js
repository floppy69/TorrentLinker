"use strict";
// Details of the playing film under the picture. The host owns playback; this view only
// shows what it publishes and asks it to switch tracks.
const $ = (id) => document.getElementById(id);
let state = {},
  request,
  artworkFor = "";
const say = (en, fr) => (state.language === "fr" ? fr : en);
const scope = () => ({
  client_id: state.client_id,
  media_id: state.media_id,
  source_token: state.source_token,
});

function runtime(seconds) {
  const minutes = Math.round((Number(seconds) || 0) / 60);
  if (!minutes) return "";
  const hours = Math.floor(minutes / 60),
    rest = String(minutes % 60).padStart(2, "0");
  if (!hours) return say(`${minutes} min`, `${minutes} min`);
  return say(`${hours}h ${rest}m`, `${hours} h ${rest}`);
}

function rating(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "";
  return number.toLocaleString(state.language === "fr" ? "fr-FR" : "en-US", {
    maximumFractionDigits: 1,
  });
}

function chips(root, rows, kind) {
  const buttons = rows.map((row) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = row.text;
    button.setAttribute("aria-pressed", String(row.selected));
    const source = scope();
    button.onclick = async () => {
      $("error").hidden = true;
      try {
        await request("command", {
          action: "select_track",
          values: { kind, track_id: row.id },
          ...source,
        });
      } catch (error) {
        $("error").textContent = error.message;
        $("error").hidden = false;
      }
    };
    return button;
  });
  root.replaceChildren(...buttons);
}

// Hosts number tracks and repeat their language; a chip keeps the words that tell them apart.
function trackText(row, index, fallback) {
  const parts = String(row.label || "")
    .split(" · ")
    .filter((part) => !/^(audio|subtitle|sous-titre|embedded subtitle|sous-titre intégré) \d+$/i.test(part))
    .filter((part) => part.toLowerCase() !== String(row.language || "").toLowerCase());
  const unique = parts.filter((part, i) => parts.findIndex((other) => other.toLowerCase() === part.toLowerCase()) === i);
  return unique.join(" · ") || row.language || `${fallback} ${index + 1}`;
}

async function artwork(item) {
  const key = `${state.client_id}/${state.media_id}`;
  if (artworkFor === key) return;
  artworkFor = key;
  const poster = $("poster");
  poster.classList.remove("has-art");
  poster.querySelector("img")?.remove();
  if (!item.artwork) return;
  try {
    const result = await request("artwork", { media_id: state.media_id });
    if (artworkFor !== key || !result?.data_url) return;
    const image = document.createElement("img");
    image.alt = "";
    image.src = result.data_url;
    poster.prepend(image);
    poster.classList.add("has-art");
  } catch {
    // The title stays on the placeholder.
  }
}

function render() {
  document.documentElement.lang = state.language || "en";
  document.documentElement.dataset.theme = state.theme || "dark";
  const item = state.item;
  $("details").hidden = !item;
  if (!item) return;
  $("title").textContent = item.title || "";
  $("poster-title").textContent = item.title || "";
  const original = item.original_title && item.original_title !== item.title;
  $("original").hidden = !original;
  $("original").textContent = original ? item.original_title : "";
  const meta = [item.year, runtime(item.duration), item.genre]
    .filter(Boolean)
    .map((text) => {
      const span = document.createElement("span");
      span.textContent = text;
      return span;
    });
  if (rating(item.rating)) {
    const span = document.createElement("span");
    span.className = "rating";
    span.textContent = `★ ${rating(item.rating)}`;
    span.setAttribute(
      "aria-label",
      say(
        `Rated ${rating(item.rating)} out of 10`,
        `Note ${rating(item.rating)} sur 10`,
      ),
    );
    meta.push(span);
  }
  $("meta").replaceChildren(...meta);
  $("tagline").textContent = item.tagline || "";
  $("tagline").hidden = !item.tagline;
  $("plot").textContent = item.description || "";
  $("plot").title = say("Show the whole plot", "Afficher tout le résumé");
  $("plot").onclick = () => $("plot").classList.toggle("open");
  $("plot").hidden = !item.description;
  const people = [
    [say("Director", "Réalisation"), item.director],
    [say("Starring", "Avec"), item.actors],
  ].filter(([, value]) => value);
  $("people").replaceChildren(
    ...people.flatMap(([label, value]) => {
      const term = document.createElement("dt"),
        detail = document.createElement("dd");
      term.textContent = label;
      detail.textContent = value;
      return [term, detail];
    }),
  );
  $("people").hidden = !people.length;
  const found = mediaFlags(item);
  $("flags-label").textContent = say("File", "Fichier");
  $("flags").replaceChildren(
    ...found.map(([text, strong]) => {
      const li = document.createElement("li");
      li.textContent = text;
      if (strong) li.className = "strong";
      return li;
    }),
  );
  $("flags-section").hidden = !found.length;
  const tracks = state.tracks || {};
  $("audio-label").textContent = say("Audio", "Audio");
  const audio = (tracks.audio || []).map((row, index) => ({
    id: row.id,
    text: trackText(row, index, say("Audio", "Audio")),
    selected: !!row.selected,
  }));
  chips($("audio"), audio, "audio");
  $("audio-section").hidden = !tracks.ready || !audio.length;
  $("subtitle-label").textContent = say("Subtitles", "Sous-titres");
  const subtitles = (tracks.subtitles || []).map((row, index) => ({
    id: row.id,
    text: trackText(row, index, say("Subtitle", "Sous-titre")),
    selected: !!row.selected,
  }));
  subtitles.unshift({
    id: "off",
    text: say("Off", "Aucun"),
    selected: !subtitles.some((row) => row.selected),
  });
  chips($("subtitles"), subtitles, "subtitle");
  // "Off" alone is no choice: the section waits for a real subtitle track.
  $("subtitle-section").hidden = !tracks.ready || subtitles.length < 2;
  artwork(item);
}

window.addEventListener("nowplaying-environment", (event) => {
  if (event.detail.source_token !== state.source_token) $("error").hidden = true;
  state = event.detail || {};
  if (request) render();
});

tlPanelReady.then(async () => {
  request = await TLPanel.connect("nowplaying", { asynchronous: true });
  let height = 0;
  new ResizeObserver(() => {
    const next = Math.ceil(document.body.getBoundingClientRect().height);
    if (next !== height) {
      height = next;
      request("layout", { height }).catch(() => {});
    }
  }).observe(document.body);
  render();
  window.nowplayingReady();
});
