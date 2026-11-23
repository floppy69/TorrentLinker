"use strict";
/* Helpers shared by the Media browsing view and the Web player host. */
const mediaLayouts = ["cinematic", "focus", "horizon"];
const mediaHorizonViews = ["home", "showcase", "wall"];
// Horizon replaced Collection; a saved Collection choice opens Horizon.
const mediaLayoutValue = value => value === "collection" ? "horizon" : mediaLayouts.includes(value) ? value : "cinematic";
const mediaHorizonValue = value => mediaHorizonViews.includes(value) ? value : "home";
const mediaClient = () => state.clientId === "all" ? state.setup?.default_client_id || "default" : state.clientId || "default";
const mediaQuery = values => new URLSearchParams({client_id: mediaClient(), ...values}).toString();
function mediaOption(select, value, label) { const option = element("option", label); option.value = value; select.append(option); }
const mediaTime = n => {
  const seconds = Math.max(0, Math.floor(Number(n) || 0)), clock = `${String(seconds % 60).padStart(2, "0")}`;
  return seconds >= 3600 ? `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}:${clock}` : `${Math.floor(seconds / 60)}:${clock}`;
};
let mediaLogoId = 0;
function mediaLogo() {
  const id = `media-logo-${++mediaLogoId}`, template = document.createElement("template");
  template.innerHTML = `<svg class="media-art-logo" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <!-- TorrentLinker: the T (tracker, signal above it) links straight into the L (your files) -->
  <defs>
    <linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="100" y1="0" x2="176" y2="0">
      <stop offset="0" stop-color="#45bdb2"/><stop offset="1" stop-color="#e8f1ee"/>
    </linearGradient>
  </defs>
  <path d="M64 56 Q90 34 116 56" fill="none" stroke="#45bdb2" stroke-width="9" stroke-linecap="round" opacity=".5"/>
  <path d="M76 68 Q90 57 104 68" fill="none" stroke="#45bdb2" stroke-width="9" stroke-linecap="round" opacity=".85"/>
  <path d="M90 92 V202" stroke="#45bdb2" stroke-width="28" stroke-linecap="round"/>
  <path d="M176 68 V202 H216" fill="none" stroke="#e8f1ee" stroke-width="28" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M46 92 H176" stroke="url(#${id})" stroke-width="28" stroke-linecap="round"/>
  <path d="M200 140 H218 M200 164 H212" stroke="#e8f1ee" stroke-width="9" stroke-linecap="round" opacity=".55"/>
</svg>`;
  return template.content.firstElementChild;
}
function mediaArt(row, className = "") {
  const art = element("div", undefined, `media-art ${className}`);
  if (row.artwork_url) {
    const image = element("img"); if (typeof mediaImage === "function") mediaImage(image, row); else image.src = row.artwork_url; image.alt = ""; image.loading = "lazy";
    image.onerror = () => { image.remove(); art.classList.add("missing-art"); };
    art.append(image);
  } else art.classList.add("missing-art");
  if (row.kind === "video" && className !== "media-feature-art") {
    art.append(mediaLogo());
  }
  const fallback = element("span", row.title || row.album || say("Artwork unavailable", "Illustration indisponible"), "media-art-title");
  art.append(fallback); return art;
}
