/* The player lives outside navigation views, so browsing never replaces its DOM. */
const media = {kind: "video", view: "recent", animeFilters: {}, rows: [], homeRows: [], gridMode: false, selected: null, session: null,
  playerClient: "", queue: [], index: 0, shuffle: false, repeat: "off", ack: 0,
  busy: false, preview: null, playbackGeneration: 0, featureId: null, continueRows: [], next: null, chat: false, scan: "", scanQuiet: false, request: 0};
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
const mediaLayouts = ["cinematic", "focus", "collection"];
media.layout = mediaLayouts.includes(localStorage.getItem("tl-media-layout")) ? localStorage.getItem("tl-media-layout") : "cinematic";
function mediaSetLayout(value) {
  media.layout = mediaLayouts.includes(value) ? value : "cinematic";
  localStorage.setItem("tl-media-layout", media.layout);
  $("view-media").dataset.layout = media.layout;
  $("media-layout-switch").value = media.layout; $("settings-media-layout").value = media.layout;
  mediaRender();
}
const mediaClient = () => state.clientId === "all" ? state.setup?.default_client_id || "default" : state.clientId || "default";
const mediaQuery = values => new URLSearchParams({client_id: mediaClient(), ...values}).toString();
const mediaURL = (id, suffix = "stream") => `api/media/items/${encodeURIComponent(id)}/${suffix}?${new URLSearchParams({client_id: media.playerClient || mediaClient()})}`;
const mediaPlayer = () => $("media-audio").hidden ? $("media-video") : $("media-audio");
const mediaTime = n => {
  const seconds = Math.max(0, Math.floor(Number(n) || 0)), clock = `${String(seconds % 60).padStart(2, "0")}`;
  return seconds >= 3600 ? `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}:${clock}` : `${Math.floor(seconds / 60)}:${clock}`;
};
function mediaStatus(text) { $("media-status").textContent = text; }
function mediaOption(select, value, label) { const option = element("option", label); option.value = value; select.append(option); }
function mediaViews() {
  rememberMediaView();
  $("media-player-menu-toggle").setAttribute("aria-label", say("Player options", "Options du lecteur"));
  $("media-player-menu-toggle").title = say("Player options", "Options du lecteur");
  $("media-player-menu").setAttribute("aria-label", say("Player options", "Options du lecteur"));
  $("media-player-audio-track").setAttribute("aria-label", say("Audio track", "Piste audio"));
  $("media-player-subtitle-track").setAttribute("aria-label", say("Subtitle track", "Piste de sous-titres"));
  $("media-layout-switch").setAttribute("aria-label", say("Media layout", "Disposition des médias"));
  $("settings-media-layout").setAttribute("aria-label", say("Settings Media layout", "Disposition des médias dans les paramètres"));
  $("media-search").placeholder = say("Search your media", "Rechercher dans vos médias");
  $("media-playlist-name").placeholder = say("Playlist name", "Nom de la playlist");
  const select = $("media-view"); select.replaceChildren();
  const choices = media.kind === "video" ? [["recent", say("Recent", "Récents")], ["continue", say("Continue watching", "Reprendre")], ["films", say("Films", "Films")], ["series", say("Series", "Séries")], ["anime", say("Anime", "Animés")], ["rated", say("Highly rated", "Les mieux notés")], ["unwatched", say("Not watched yet", "Pas encore vus")], ["all", say("All videos", "Toutes les vidéos")], ...(state.setup?.adult_content ? [["adult", "XXX"]] : [])] : [["albums", say("Albums", "Albums")], ["artists", say("Artists", "Artistes")], ["tracks", say("Tracks", "Pistes")]];
  for (const [value, label] of choices) mediaOption(select, value, label);
  select.value = media.view;
  $("media-video-tab").setAttribute("aria-selected", String(media.kind === "video"));
  $("media-music-tab").setAttribute("aria-selected", String(media.kind === "music"));
  $("media-music-nav").hidden = media.kind !== "music";
  $("media-music-nav").setAttribute("aria-label", say("Music browsing", "Navigation musicale"));
  for (const item of document.querySelectorAll("[data-media-music-view]")) item.textContent = ({albums: say("Albums", "Albums"), artists: say("Artists", "Artistes"), tracks: say("Tracks", "Pistes")})[item.dataset.mediaMusicView];
  $("media-playlists").hidden = media.kind !== "music";
}
function rememberMediaView() {
  const defaultView = mediaViewsByKind[media.kind][0];
  rememberTab("media", media.kind, media.view === defaultView ? undefined : media.view);
}
async function loadMedia(append = false) {
  rememberMediaView();
  if (!$("media-view").options.length) mediaViews();
  const version = ++media.request;
  // The XXX panel is its own view: recent first, from XXX folders only.
  const adult = media.view === "adult";
  const query = {kind: media.kind, view: adult ? "recent" : media.view, q: $("media-search").value, offset: append ? media.next || 0 : 0, limit: 100};
  if (adult) query.adult = true;
  // The Anime panel likewise, or one of its rows' See all; Films and Series leave anime to it.
  if (media.view === "anime") Object.assign(query, {view: "recent", anime: true}, media.animeFilters);
  else if (["films", "series"].includes(media.view)) query.anime = false;
  for (const key of ["genre", "year", "language", "availability"]) if ($(`media-${key}`).value) query[key] = $(`media-${key}`).value;
  const home = !append && mediaHomeActive();
  const [result, continuing, rows] = await Promise.all([
    api(`media?${mediaQuery(query)}`),
    media.kind === "video" ? api(`media?${mediaQuery({...query, view: "continue", offset: 0, limit: 8})}`) : Promise.resolve({rows: []}),
    home ? api(`media/home?${mediaQuery({scope: {films: "films", series: "series", anime: "anime", adult: "adult"}[media.view] || "home"})}`) : Promise.resolve({rows: []}),
  ]);
  if (version !== media.request) return;
  media.continueRows = continuing.rows;
  if (!append) media.homeRows = rows.rows.filter(row => row.key !== "continue");
  for (const row of [...result.rows, ...continuing.rows, ...media.homeRows.flatMap(r => r.rows)]) mediaItems.set(row.id, row);
  media.rows = append ? [...media.rows, ...result.rows] : result.rows;
  media.next = result.has_more ? result.next_offset : null;
  $("media-more").hidden = !result.has_more;
  for (const key of ["genre", "year", "language", "availability"]) {
    const select = $(`media-${key}`), old = select.value;
    select.replaceChildren(); mediaOption(select, "", say(`All ${key === "availability" ? "availability" : key === "year" ? "years" : key === "language" ? "languages" : "genres"}`, ({availability: "Toute disponibilité", year: "Toutes les années", language: "Toutes les langues", genre: "Tous les genres"})[key]));
    for (const entry of result.filters?.[key] || result.filters?.[`${key}s`] || (key === "availability" ? ["available", "unavailable", "unfinished"] : [])) mediaOption(select, typeof entry === "object" ? entry.value : entry, typeof entry === "object" ? entry.label : entry);
    select.value = old;
  }
  const noun = media.kind === "video" ? "video" : media.view === "albums" ? "album" : media.view === "artists" ? "artist" : "track";
  mediaStatus(result.scanning ? "Scanning Library Folders..." : `${result.total} ${noun}${result.total === 1 ? "" : "s"}${result.errors?.length ? " · Some folders are unavailable. Previous items were kept." : ""}`);
  mediaRender();
  if (!media.session && sessionStorage.getItem(`tl-media-session:${mediaClient()}`)) await mediaSession();
  if (media.kind === "music") await mediaPlaylists();
}
function mediaArt(row, className = "") {
  const art = element("div", undefined, `media-art ${className}`);
  if (row.artwork_url) {
    const image = element("img"); image.src = row.artwork_url; image.alt = ""; image.loading = "lazy";
    image.onerror = () => { image.remove(); art.classList.add("missing-art"); };
    art.append(image);
  } else art.classList.add("missing-art");
  const fallback = element("span", row.title || row.album || say("Artwork unavailable", "Illustration indisponible"), "media-art-title");
  art.append(fallback); return art;
}
function mediaSelectFeature(row) { media.featureId = row.id; media.selected = row; mediaRenderFeature(); mediaRenderEpisodes(row).catch(() => {}); }
// A chosen series unfolds under its description: one tab per season, then its episodes.
async function mediaRenderEpisodes(row) {
  const root = $("media-episodes");
  if (!row || media.kind !== "video" || !row.series) { root.hidden = true; root.replaceChildren(); return; }
  const detail = await api(`media/items/${encodeURIComponent(row.id)}?${mediaQuery({})}`);
  if (media.featureId !== row.id) return;
  const episodes = detail.episodes || [];
  root.hidden = !episodes.length; root.replaceChildren();
  if (!episodes.length) return;
  const header = element("div", undefined, "media-episodes-header"), list = element("div", undefined, "media-row-track media-episode-track");
  header.append(element("h2", detail.series));
  const seasons = [...new Set(episodes.map(e => e.season).filter(s => s !== null && s !== undefined))].sort((a, b) => a - b);
  const show = season => {
    for (const tab of header.querySelectorAll("button[data-season]")) tab.setAttribute("aria-pressed", String(Number(tab.dataset.season) === season));
    list.replaceChildren();
    episodes.forEach((episode, index) => {
      if (season !== undefined && episode.season !== season) return;
      const card = button("", () => mediaStart(episodes.map(e => e.id), index), "media-episode-card");
      const number = episode.episode ?? null;
      const name = episode.episode_title ? `${number !== null ? `${number}. ` : ""}${episode.episode_title}` : number !== null ? say(`Episode ${number}`, `Épisode ${number}`) : episode.release || episode.title;
      const facts = [episode.duration ? mediaTime(episode.duration) : "", episode.watched ? say("watched", "vu") : episode.position ? say(`resume at ${mediaTime(episode.position)}`, `reprendre à ${mediaTime(episode.position)}`) : "", episode.available === false ? say("unavailable", "indisponible") : ""].filter(Boolean).join(" · ");
      const still = mediaArt({...row, title: name}, "media-episode-still");
      if (episode.duration && episode.position && !episode.watched) {
        const progress = element("progress"); progress.max = episode.duration; progress.value = episode.position; still.append(progress);
      }
      card.append(still, element("strong", name), element("span", facts));
      card.setAttribute("aria-label", name); card.disabled = episode.available === false;
      list.append(card);
    });
  };
  for (const season of seasons) {
    const tab = button(say(`Season ${season}`, `Saison ${season}`), () => show(season), "quiet");
    tab.dataset.season = season; header.append(tab);
  }
  root.append(header, list);
  show(seasons.includes(detail.season) ? detail.season : seasons[0]);
}
function mediaRenderFeature() {
  const root = $("media-feature");
  const candidates = [...media.rows, ...media.continueRows, ...media.homeRows.flatMap(r => r.rows)];
  const row = candidates.find(item => item.id === media.featureId) || candidates.find(item => item.available !== false && item.artwork_url) || candidates.find(item => item.available !== false) || candidates[0];
  root.hidden = media.kind !== "video" || !row;
  if (root.hidden) { media.selected = null; return; }
  media.featureId = row.id; media.selected = row;
  const scroll = root.querySelector(".media-focus-strip")?.scrollLeft || 0;
  root.replaceChildren();
  const art = mediaArt(row, "media-feature-art"); root.append(art);
  const copy = element("div", undefined, "media-feature-copy");
  // The poster sits left of the title and description, over the same artwork backdrop.
  if (row.artwork_url) { copy.classList.add("has-poster"); copy.append(mediaArt(row, "media-feature-poster")); }
  copy.append(element("p", say("In your library", "Dans votre médiathèque"), "media-eyebrow"), element("h2", row.title));
  const facts = [row.year, row.duration > 0 ? mediaTime(row.duration) : "", row.genre, row.language, row.rating ? `★ ${row.rating}` : ""].filter(Boolean);
  copy.append(element("p", facts.join(" · "), "media-feature-meta"));
  if (row.identity_source === "filename") copy.append(element("p", say("Filename metadata", "Métadonnées du nom de fichier"), "media-metadata-source"));
  copy.append(element("p", row.description || say("No local synopsis available.", "Aucun synopsis local disponible."), "media-feature-description"));
  const actions = element("div", undefined, "media-feature-actions");
  const play = button(row.position > 0 && !row.watched ? say("Resume", "Reprendre") : say("Play", "Lire"), () => mediaStart([row.id]), "media-primary"); play.disabled = row.available === false;
  actions.append(play, button(say("Details", "Détails"), () => mediaDetails(row.id), "media-secondary"), Object.assign(button(say("Assistant", "Assistant"), async () => { media.selected = row; await mediaToggleChat(); }, "media-secondary"), {id: "media-feature-chat"}));
  copy.append(actions);
  if (row.available === false) copy.append(element("p", row.reason || say("Unavailable", "Indisponible"), "media-availability-note"));
  root.append(copy);
  const strip = element("div", undefined, "media-focus-strip"); strip.id = "media-focus-strip"; strip.setAttribute("aria-label", say("Select a featured title", "Choisir le titre mis en avant"));
  for (const item of media.rows) {
    const choice = button("", () => mediaSelectFeature(item), "media-focus-choice");
    choice.setAttribute("aria-label", item.title); choice.setAttribute("aria-pressed", String(item.id === row.id));
    choice.append(mediaArt(item), element("span", item.title)); strip.append(choice);
  }
  root.append(strip); strip.scrollLeft = scroll;
}
function mediaRenderContinue() {
  const root = $("media-continue-items"); root.replaceChildren();
  $("media-continue").hidden = media.kind !== "video" || !media.continueRows.length;
  for (const row of media.continueRows) {
    const choice = button("", () => mediaStart([row.id]), "media-resume-card"); choice.setAttribute("aria-label", `${say("Resume", "Reprendre")} ${row.title}`);
    const art = mediaArt(row); const progress = element("progress"); progress.max = row.duration || Math.max(row.position, 1); progress.value = row.position || 0;
    choice.append(art, progress, element("strong", row.title), element("span", mediaTime(row.position), "media-resume-position")); root.append(choice);
  }
}
// The video home shows rows (genres, series…); each row's "See all" opens the grid with its filters.
function mediaHomeActive() {
  return media.kind === "video" && ["recent", "films", "series", "anime", "adult"].includes(media.view) && !media.gridMode && media.layout === "cinematic" && !$("media-search").value.trim()
    && ["genre", "year", "language", "availability"].every(key => !$(`media-${key}`).value);
}
function mediaRenderHome() {
  const root = $("media-home-rows"), active = mediaHomeActive() && media.homeRows.length > 0;
  root.hidden = !active; document.querySelector(".media-library-layout").hidden = active;
  root.replaceChildren();
  if (!active) return;
  const titles = {recent: say("Recently added", "Récemment ajoutés"), series: say("Series", "Séries"), oav: say("OAV", "OAV"), films: say("Films", "Films"), rated: say("Highly rated", "Les mieux notés"), unwatched: say("Not watched yet", "Pas encore vus")};
  for (const row of media.homeRows) {
    const section = element("section", undefined, "media-home-row"), header = element("div", undefined, "media-home-row-header");
    const title = row.key === "genre" ? row.title : titles[row.key] || row.title;
    section.setAttribute("aria-label", title);
    const track = element("div", undefined, "media-row-track");
    const step = direction => track.scrollBy({left: direction * Math.max(180, track.clientWidth - 180), behavior: "smooth"});
    const back = button("‹", () => step(-1), "icon-button"), forward = button("›", () => step(1), "icon-button");
    back.setAttribute("aria-label", say("Scroll left", "Défiler à gauche")); forward.setAttribute("aria-label", say("Scroll right", "Défiler à droite"));
    const all = button(say("See all", "Voir tout"), () => guard(() => mediaSeeAll(row.filters)), "quiet");
    header.append(element("h2", title), element("span", say(`${row.total} titles`, `${row.total} titres`), "media-home-row-count"), back, forward, all);
    for (const item of row.rows) {
      const card = button("", () => {
        mediaSelectFeature(item);
        for (const other of root.querySelectorAll(".media-row-card")) other.setAttribute("aria-pressed", String(other.dataset.id === item.id));
        $("media-feature").scrollIntoView({block: "nearest", behavior: "smooth"});
      }, "media-row-card");
      card.dataset.id = item.id;
      card.setAttribute("aria-label", item.title); card.setAttribute("aria-pressed", String(item.id === media.featureId));
      card.ondblclick = () => guard(() => mediaStart([item.id]));
      card.append(mediaArt(item), element("strong", item.title), element("span", item.series_card ? say(`${item.episode_count} episodes`, `${item.episode_count} épisodes`) : [item.year, item.rating ? `★ ${item.rating}` : ""].filter(Boolean).join(" · ")));
      track.append(card);
    }
    section.append(header, track); root.append(section);
  }
  // Rows can be drawn while the page is hidden; measure again whenever a row's size changes.
  mediaRowObserver ||= new ResizeObserver(mediaRowArrows);
  mediaRowObserver.disconnect();
  for (const track of root.querySelectorAll(".media-row-track")) mediaRowObserver.observe(track);
}
let mediaRowObserver = null;
function mediaRowArrows() {
  // The arrows appear only when a row is wider than the page.
  for (const section of document.querySelectorAll(".media-home-row")) {
    const track = section.querySelector(".media-row-track"), overflow = track.scrollWidth > track.clientWidth + 2;
    for (const arrow of section.querySelectorAll(".media-home-row-header .icon-button")) arrow.hidden = !overflow;
  }
}
async function mediaSeeAll(filters) {
  const genre = $("media-genre");
  if (filters.genre) {
    if (![...genre.options].some(option => option.value === filters.genre)) mediaOption(genre, filters.genre, filters.genre);
    genre.value = filters.genre;
  }
  // The grid stays until a browse tab is chosen again.
  media.gridMode = true;
  media.animeFilters = filters.anime ? Object.fromEntries(["view", "oav"].filter(key => key in filters).map(key => [key, filters[key]])) : {};
  media.view = filters.adult ? "adult" : filters.anime ? "anime" : filters.view || "all"; $("media-view").value = media.view;
  await loadMedia();
  window.scrollTo({top: 0});
}
// In Video, a music track keeps its bar only while it plays, so it can still be paused.
function mediaMusicBar() {
  const shell = $("media-player-shell");
  shell.classList.toggle("media-shell-parked", shell.dataset.kind === "music" && media.kind === "video" && $("media-audio").paused);
}
function mediaRender() {
  $("view-media").dataset.kind = media.kind; $("view-media").dataset.layout = media.layout;
  $("view-media").dataset.musicView = media.view;
  $("view-media").dataset.empty = String(media.rows.length === 0);
  for (const item of document.querySelectorAll("[data-media-view]")) { item.classList.toggle("active", item.dataset.mediaView === media.view); item.setAttribute("aria-current", item.dataset.mediaView === media.view ? "page" : "false"); }
  for (const item of document.querySelectorAll("[data-media-music-view]")) { item.classList.toggle("active", item.dataset.mediaMusicView === media.view); item.setAttribute("aria-current", item.dataset.mediaMusicView === media.view ? "page" : "false"); }
  mediaMusicBar();
  mediaRenderFeature(); mediaRenderContinue(); mediaRenderHome(); mediaRenderEpisodes(media.selected).catch(() => {});
  $("media-shelf-title").textContent = media.kind === "music" ? ({albums: say("Albums", "Albums"), artists: say("Artists", "Artistes"), tracks: say("Tracks", "Pistes")})[media.view] : ({recent: say("Recently added", "Récemment ajoutés"), continue: say("Continue watching", "Reprendre la lecture"), films: say("Films", "Films"), series: say("Series", "Séries"), anime: say("Anime", "Animés"), adult: "XXX"})[media.view] || say("Your videos", "Vos vidéos");
  $("media-shelf-count").textContent = say("From your Library Folders", "Dans vos dossiers de bibliothèque");
  const root = $("media-results"); root.replaceChildren();
  if (!media.rows.length) { root.append(element("p", say("No media found. Add a Library Folder in Library options, then refresh the inventory.", "Aucun média trouvé. Ajoutez un dossier dans les options de bibliothèque, puis actualisez les médias."), "media-empty")); root.append(button(say("Add Library Folder", "Ajouter un dossier de bibliothèque"), () => navigate("setup"))); return; }
  if (media.kind === "music" && media.view === "tracks") { mediaRenderTracks(root); return; }
  const groups = new Map();
  for (const row of media.rows) {
    const key = media.kind === "music" && media.view === "albums" ? row.album_id || row.id : media.kind === "music" && media.view === "artists" ? row.artist || "Unknown artist" : media.kind === "video" ? row.content_id || row.id : row.id;
    if (!groups.has(key)) groups.set(key, []); groups.get(key).push(row);
  }
  for (const rows of groups.values()) {
    const row = rows[0], card = element("article", undefined, `media-card ${media.kind === "music" ? "media-music-card" : "media-video-card"}`);
    const title = media.kind === "music" && media.view === "albums" ? row.album || "Unknown album" : media.kind === "music" && media.view === "artists" ? row.artist || "Unknown artist" : row.title;
    // A series card unfolds its episodes; any other card opens its details.
    const artwork = button("", () => row.series_card ? (mediaSelectFeature(row), $("media-feature").scrollIntoView({block: "nearest", behavior: "smooth"})) : mediaDetails(row.id), "media-poster-button"); artwork.setAttribute("aria-label", `${say("Details", "Détails")}: ${title}`);
    if (media.kind === "music" && media.view === "artists") {
      const initials = title.split(/\s+/).slice(0, 2).map(part => [...part][0]).join("");
      const portrait = element("div", undefined, "media-artist-art"); portrait.append(element("span", initials)); artwork.append(portrait); card.classList.add("media-artist-card");
    } else artwork.append(mediaArt({...row, title}));
    const badge = element("span", row.available === false ? row.availability === "unfinished" ? say("Downloading", "Téléchargement") : say("Unavailable", "Indisponible") : say("Available", "Disponible"), "media-poster-badge");
    if (media.kind === "video" || row.available === false) artwork.append(badge);
    card.append(artwork, element("h3", title));
    card.append(element("p", media.kind === "music" && media.view === "artists" ? say("Artist", "Artiste") : row.series_card ? say(`${row.episode_count} episodes`, `${row.episode_count} épisodes`) : [row.artist, row.year, row.genre].filter(Boolean).join(" · "), "media-card-meta"));
    if (media.kind === "music" && row.track_count) card.append(element("p", say(`${row.track_count} track${row.track_count === 1 ? "" : "s"}`, `${row.track_count} piste${row.track_count === 1 ? "" : "s"}`), "media-card-meta"));
    if (row.identity_source === "filename") card.append(element("p", say("Filename metadata", "Métadonnées du nom de fichier"), "media-card-source"));
    if (row.series || row.episode) card.append(element("p", `${row.series || "Episode"} ${row.season ? `S${row.season}` : ""}${row.episode ? ` E${row.episode}` : ""}`, "media-card-meta"));
    const actions = element("div", undefined, "media-card-actions");
    const play = button(say("Play", "Lire"), () => mediaStart(mediaGroupIds(rows))); play.disabled = row.available === false;
    actions.append(play, button(say("Details", "Détails"), () => mediaDetails(row.id)));
    if (media.kind === "music") actions.append(button(say("Add to queue", "Ajouter à la file"), async () => mediaEnqueue(await mediaGroupIds(rows))));
    card.append(actions); root.append(card);
  }
}
function mediaRenderTracks(root) {
  const heading = element("div", undefined, "media-track-heading");
  for (const label of [say("Play", "Lire"), say("Title / artist", "Titre / artiste"), say("Album", "Album"), say("Duration", "Durée"), say("Actions", "Actions")]) heading.append(element("span", label));
  root.append(heading);
  for (const row of media.rows) {
    const item = element("article", undefined, "media-track-row");
    const play = button("▶", () => mediaStart([row.id]), "media-track-play"); play.setAttribute("aria-label", `${say("Play", "Lire")} ${row.title}`); play.disabled = row.available === false;
    const title = element("div", undefined, "media-track-title"), copy = element("div");
    const details = button(row.title, () => mediaDetails(row.id), "media-track-name");
    copy.append(details, element("span", row.artist || say("Unknown artist", "Artiste inconnu")));
    title.append(mediaArt(row), copy);
    const actions = element("div", undefined, "media-track-actions");
    actions.append(button(say("Add to queue", "Ajouter à la file"), () => mediaEnqueue([row.id])));
    if (row.available === false) copy.append(element("span", row.reason || say("Unavailable", "Indisponible"), "media-error"));
    item.append(play, title, element("span", row.album || say("Unknown album", "Album inconnu"), "media-track-album"), element("span", row.duration > 0 ? row.duration < 1 ? "<0:01" : mediaTime(row.duration) : "—", "media-track-duration"), actions); root.append(item);
  }
}
async function mediaTrackGroup(row, view) {
  if (view === "albums" && !row.album_id) return [row];
  const found = []; let offset = 0;
  do {
    const page = await api(`media?${mediaQuery({kind: "music", view: "tracks", offset, limit: 200, ...(view === "albums" ? {album_id: row.album_id} : {artist: row.artist || ""})})}`);
    for (const item of page.rows) mediaItems.set(item.id, item);
    found.push(...page.rows.filter(item => view === "albums" ? item.album_id === row.album_id : item.artist === row.artist));
    offset = page.has_more ? page.next_offset : null;
  } while (offset !== null);
  return found;
}
async function mediaGroupIds(rows) {
  if (media.kind !== "music" || media.view === "tracks") return rows.map(item => item.id);
  return (await mediaTrackGroup(rows[0], media.view)).map(item => item.id);
}
async function mediaDetails(id) {
  const row = await api(`media/items/${encodeURIComponent(id)}?${mediaQuery({})}`); media.selected = row;
  const root = $("media-details"); root.replaceChildren(); root.hidden = false;
  root.append(mediaArt(row, "media-detail-art"));
  if (!root.open) root.showModal();
  root.append(button(say("Close details", "Fermer les détails"), () => { root.close(); media.selected = null; }), element("h2", row.title));
  root.append(element("p", row.description || "No local synopsis available."));
  if (row.identity_source) root.append(element("p", `Metadata: ${row.identity_source}`, "muted"));
  if (row.release) root.append(element("p", `Release: ${row.release}`, "muted"));
  if (row.kind === "video") {
    const subtitles = element("section", undefined, "media-subtitle-availability");
    subtitles.append(element("h3", say("External subtitle files", "Fichiers de sous-titres externes")));
    if (row.subtitles?.length) {
      const list = element("ul");
      for (const subtitle of row.subtitles) list.append(element("li", subtitle.label || subtitle.language || say("Unknown language", "Langue inconnue")));
      subtitles.append(list);
    } else subtitles.append(element("p", say("No external subtitle files are known for this release.", "Aucun fichier de sous-titres externe n’est connu pour cette version.")));
    if (row.embedded_subtitles?.length) {
      subtitles.append(element("h3", say("Embedded subtitle tracks", "Pistes de sous-titres intégrées")));
      const embedded = element("ul");
      for (const track of row.embedded_subtitles) embedded.append(element("li", [track.label || track.language || say("Unknown language", "Langue inconnue"), track.format].filter(Boolean).join(" · ")));
      subtitles.append(embedded, element("p", say("These embedded tracks are file metadata. They may not appear in this browser’s subtitle controls. Use an external player for tracks the browser does not expose.", "Ces pistes intégrées sont des métadonnées du fichier. Elles peuvent ne pas apparaître dans les commandes de sous-titres de ce navigateur. Utilisez un lecteur externe pour les pistes non proposées.")));
    } else subtitles.append(element("p", say("Embedded subtitle tracks may also be available during playback, depending on the file and player.", "Des pistes de sous-titres intégrées peuvent aussi être disponibles pendant la lecture, selon le fichier et le lecteur.")));
    root.append(subtitles);
    if (row.language) root.append(element("p", say(`Audio languages from file metadata: ${row.language}. Browser playback may not support every audio track.`, `Langues audio d’après les métadonnées du fichier : ${row.language}. Le navigateur peut ne pas prendre en charge toutes les pistes audio.`)));
    if (row.available !== false) {
      const external = element("a", say("Open / download the original for an external player", "Ouvrir / télécharger l’original pour un lecteur externe"));
      external.href = `api/media/items/${encodeURIComponent(id)}/stream?${mediaQuery({})}`; external.target = "_blank"; external.rel = "noopener"; external.download = ""; root.append(external);
    }
  }
  if (row.kind === "video" && row.availability === "unfinished") {
    root.append(element("p", say("Preview is optional. Only a verified downloaded prefix from a sequential qBittorrent single-file download can play. Some formats require the missing end of the file.", "L’aperçu est facultatif. Seul le début vérifié d’un téléchargement séquentiel qBittorrent à fichier unique peut être lu. Certains formats exigent la fin du fichier."), "muted"));
    root.append(button(say("Preview downloaded portion", "Prévisualiser la partie téléchargée"), () => { root.close(); return mediaPreview(id); }));
  }
  if (row.kind === "video" && row.available !== false) root.append(button(say("Play", "Lire"), () => { root.close(); return mediaStart([id]); }, "media-primary"));
  if (row.kind === "video") root.append(button(row.watched ? say("Mark unwatched", "Marquer comme non vu") : say("Mark watched", "Marquer comme vu"), async () => { await api(`media/items/${encodeURIComponent(id)}/watched`, {client_id: mediaClient(), watched: !row.watched}); await mediaDetails(id); await loadMedia(); }));
  for (const [key, label] of [["releases", say("Releases", "Versions")], ["episodes", say("Episodes", "Épisodes")]]) {
    if (!row[key]?.length) continue;
    const group = element("section"), list = element("div", undefined, "media-detail-choices");
    group.append(element("h3", label), list); root.append(group);
    const append = items => {
      for (const item of items) {
        const choice = button(item.release || item.title, () => { root.close(); return mediaStart([item.id]); });
        choice.disabled = item.available === false; choice.title = item.reason || ""; list.append(choice);
      }
    };
    append(row[key]);
    let next = row[`${key}_next_offset`];
    const more = button(key === "episodes" ? say("More episodes", "Plus d’épisodes") : say("More releases", "Plus de versions"), async () => {
      more.disabled = true;
      try {
        const page = await api(`media/items/${encodeURIComponent(id)}?${mediaQuery({[`${key}_offset`]: next, limit: 200})}`);
        if (media.selected?.id !== id || !group.isConnected || !root.open) return;
        append(page[key] || []); next = page[`${key}_next_offset`]; more.hidden = !page[`${key}_has_more`];
      } finally { more.disabled = false; }
    });
    more.hidden = !row[`${key}_has_more`]; group.append(more);
  }
  if (row.kind === "music") {
    const artistView = media.view === "artists";
    const tracks = await mediaTrackGroup(row, artistView ? "artists" : "albums");
    if (media.selected?.id !== id || !root.open) return;
    const ids = tracks.map(item => item.id);
    root.append(element("h3", artistView ? row.artist || "Unknown artist" : row.album || "Track"), button(artistView ? say("Play artist", "Lire cet artiste") : say("Play album", "Lire cet album"), () => { root.close(); return mediaStart(ids); }), button(say("Add to queue", "Ajouter à la file"), () => mediaEnqueue(ids)));
    const list = element("ol");
    tracks.forEach((item, index) => { const entry = element("li"); entry.append(button(`${item.title}${artistView ? ` · ${item.album || "Unknown album"}` : ""}`, () => { root.close(); return mediaStart(ids, index); }), element("span", item.duration > 0 ? ` ${mediaTime(item.duration)}` : " Duration unknown", "muted")); list.append(entry); });
    root.append(list);
  }
}
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
  if (error) mediaStatus(error);
}
function mediaClosePlayerMenu(focus = false) {
  $("media-player-menu").hidden = true; $("media-video-stage").dataset.menuOpen = "false";
  $("media-player-menu-toggle").setAttribute("aria-expanded", "false");
  if (focus) $("media-player-menu-toggle").focus();
}
function mediaPositionPlayerMenu(point) {
  const menu = $("media-player-menu"), box = $("media-video-stage").getBoundingClientRect();
  if (menu.hidden) return;
  const width = menu.offsetWidth, height = menu.offsetHeight;
  menu.style.left = `${Math.max(12, Math.min(point?.x ?? box.right - width - 8, innerWidth - width - 12))}px`;
  menu.style.top = `${Math.max(12, Math.min(point?.y ?? box.top + 42, innerHeight - height - 12))}px`;
}
function mediaRenderPlayerTracks() {
  const state = mediaTrackState();
  for (const kind of ["audio", "subtitle"]) {
    const select = $(`media-player-${kind}-track`), rows = state[kind === "audio" ? "audio" : "subtitles"];
    $(`media-player-${kind}-control`).hidden = !state.ready || !state[`${kind}_supported`] || !rows.length;
    const signature = JSON.stringify([state.source_token, rows.map(row => [row.id, row.label, row.language])]);
    if (select.dataset.signature !== signature) {
      select.replaceChildren();
      if (kind === "subtitle") mediaOption(select, "off", say("Off", "Désactivés"));
      for (const row of rows) mediaOption(select, row.id, [row.label, row.language].filter(Boolean).join(" · ") || row.id);
      select.dataset.signature = signature; select.dataset.sourceToken = state.source_token; select.dataset.mediaId = state.media_id;
    }
    select.value = rows.find(row => row.selected)?.id || (kind === "subtitle" ? "off" : "");
  }
}
function mediaOpenPlayerMenu(point) {
  if ($("media-video-stage").hidden) return;
  mediaRenderPlayerTracks(); $("media-player-menu").hidden = false; $("media-video-stage").dataset.menuOpen = "true";
  $("media-player-menu-toggle").setAttribute("aria-expanded", "true"); mediaPositionPlayerMenu(point);
  $("media-player-menu-close").focus();
}
function mediaPlayerComposition(kind) {
  mediaClosePlayerMenu();
  const shell = $("media-player-shell"), menu = $("media-player-menu"), video = kind === "video";
  $("media-video-stage").hidden = !video;
  $("media-playing-description").hidden = !video;
  (video ? menu : shell.querySelector(".media-player-heading")).append($("media-chat"));
  const transport = shell.querySelector(".media-player-transport");
  for (const item of [shell.querySelector(".media-player-actions"), $("media-queue-details"), $("media-track-support")]) (video ? menu : shell).append(item);
  (video ? $("media-queue-details") : shell).append(transport);
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
  $("media-preview-state").hidden = true; $("media-refresh-preview").hidden = true;
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
  if (document.fullscreenElement === $("media-player-shell")) await document.exitFullscreen().catch(() => {});
  for (const player of [$("media-video"), $("media-audio")]) { player.pause(); delete player.dataset.mediaId; delete player.dataset.sourceToken; player.removeAttribute("src"); player.load(); }
  media.trackResult = null;
  $("media-track-request-error")?.remove();
  const closing = mediaReleasePreview(); media.queue = []; media.index = 0;
  $("media-player-shell").hidden = true; mediaQueueRender();
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
  const old = mediaPlayer(); old.pause();
  await mediaReleasePreview();
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  media.preview = preview;
  if (preview) { media.queue = [id]; media.index = 0; }
  else if (request.queue) { media.queue = request.queue; media.index = request.index; }
  $("media-player-shell").dataset.kind = row.kind; mediaMusicBar();
  mediaPlayerComposition(row.kind);
  const player = $(row.kind === "music" ? "media-audio" : "media-video");
  $("media-audio").hidden = row.kind !== "music"; $("media-video").hidden = row.kind === "music";
  player.volume = old.volume; player.dataset.mediaId = id; player.dataset.sourceToken = request.sourceToken || mediaNewSourceToken(); media.trackResult = null;
  $("media-track-request-error")?.remove();
  player.src = preview ? mediaPreviewURL(preview.preview_id) : mediaURL(id); player.load();
  $("media-player-shell").hidden = false; $("media-player-shell").scrollIntoView({block: "nearest"}); $("media-now-playing").textContent = [row.title, row.artist].filter(Boolean).join(" · ");
  $("media-playing-description").textContent = [[row.year, row.duration > 0 ? mediaTime(row.duration) : "", row.genre, row.language].filter(Boolean).join(" · "), row.description].filter(Boolean).join(" · ");
  $("media-playing-description").hidden = row.kind !== "video" || !$("media-playing-description").textContent;
  $("media-player-shell").querySelector(".media-playing-art")?.remove();
  if (row.kind === "music") $("media-player-shell").prepend(mediaArt(row, "media-playing-art"));
  $("media-codec-error").hidden = true;
  const fallback = $("media-external"); fallback.href = player.src;
  $("media-track-support").hidden = row.kind !== "video" || !!preview;
  $("media-track-external").href = mediaURL(id);
  fallback.textContent = preview ? say("Download fixed partial preview for an external player", "Télécharger l’aperçu partiel fixe pour un lecteur externe") : say("Open / download for an external player", "Ouvrir / télécharger pour un lecteur externe");
  if (preview) {
    $("media-preview-state").hidden = false; $("media-refresh-preview").hidden = false;
    $("media-preview-state").textContent = say(`Partial preview · fixed verified prefix · ${bytes(preview.verified_bytes)} / ${bytes(preview.total_bytes)}. Refresh explicitly after more data downloads.`, `Aperçu partiel · début vérifié fixe · ${bytes(preview.verified_bytes)} / ${bytes(preview.total_bytes)}. Actualisez l’aperçu après téléchargement de données supplémentaires.`);
  }
  for (const child of [...$("media-video").querySelectorAll("track")]) child.remove();
  for (const subtitle of row.subtitles || []) {
    const track = element("track"); track.kind = "subtitles"; track.label = subtitle.label || subtitle.language || "Subtitles"; track.srclang = subtitle.language || "en";
    track.src = subtitle.url || mediaURL(id, `subtitles/${encodeURIComponent(subtitle.id)}`); $("media-video").append(track);
    // A prepared paused player must load external cues before reporting its selectable tracks.
    track.track.mode = "hidden";
  }
  player.onloadedmetadata = () => { const seek = position === null ? row.position || 0 : position; if (seek > 0 && Number.isFinite(player.duration)) player.currentTime = Math.min(seek, player.duration); };
  if (!paused) await mediaTryPlay(player);
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  mediaQueueRender(); return true;
}
async function mediaTryPlay(player = mediaPlayer()) {
  try { await player.play(); return true; }
  catch (error) { if (error.name === "NotAllowedError") mediaStatus("Press Play in the player to continue playback."); else if (error.name !== "AbortError") mediaCodecError(); return false; }
}
function mediaCodecError() { $("media-codec-error").hidden = false; $("media-codec-message").textContent = media.preview ? say("This partial preview cannot play yet. The format may need the missing end of the file, or its codec may be unsupported. Wait for more data and use Refresh preview.", "Cet aperçu partiel ne peut pas encore être lu. Le format peut exiger la fin du fichier ou son codec peut être incompatible. Attendez davantage de données, puis actualisez l’aperçu.") : "This browser could not play the file. Its codec may be unsupported. Open or download the file for an external player."; }
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
    else { delete mediaPlayer().dataset.mediaId; delete mediaPlayer().dataset.sourceToken; media.trackResult = null; mediaPlayer().removeAttribute("src"); mediaPlayer().load(); await mediaReleasePreview(); }
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
  $("media-shuffle").setAttribute("aria-pressed", String(media.shuffle)); $("media-repeat").value = media.repeat;
  $("media-show-queue").textContent = say(`Playback queue · ${media.queue.length}`, `File de lecture · ${media.queue.length}`);
  // Restored queues can contain uncached tracks; the server validates every saved item.
  $("media-save-playlist").querySelector("button").disabled = !media.queue.length || media.queue.some(id => { const row = mediaItems.get(id); return row && row.kind !== "music"; });
  const list = $("media-player-queue"), signature = JSON.stringify([language, media.index, media.queue.map(id => [id, mediaItems.get(id)?.title])]);
  if (list.dataset.signature === signature) return;
  list.dataset.signature = signature; list.replaceChildren();
  media.queue.forEach((id, index) => {
    const row = mediaItems.get(id), item = element("li");
    const select = button(`${index + 1}. ${row?.title || "Unavailable item"}`, async () => { media.index = index; await mediaLoad(id, 0); });
    if (index === media.index) select.setAttribute("aria-current", "true");
    item.append(select, button(say("Remove", "Retirer"), () => mediaRemoveAt(index), "quiet")); list.append(item);
  });
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
        media.trackResult = {sequence: command.sequence, applied: false, error}; mediaStatus(error);
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
    if (command.action === "seek") { const seek = () => { player.currentTime = Math.max(0, command.position || 0); }; if (player.readyState) seek(); else player.addEventListener("loadedmetadata", seek, {once: true}); }
    if (command.action === "volume") for (const output of [$("media-video"), $("media-audio")]) output.volume = Math.min(1, Math.max(0, command.volume));
    if (command.action === "queue") {
      media.queue = command.media_ids || []; media.index = command.index || 0;
      if (media.queue.length && media.queue[media.index] !== player.dataset.mediaId) await mediaLoad(media.queue[media.index], 0, player.paused);
      else if (!media.queue.length) { player.pause(); delete player.dataset.mediaId; delete player.dataset.sourceToken; media.trackResult = null; player.removeAttribute("src"); player.load(); await mediaReleasePreview(); }
    }
    if (command.action === "next") await mediaAdvance(1);
    if (command.action === "previous") await mediaAdvance(-1);
    if (command.action === "shuffle") media.shuffle = !!command.shuffle;
    if (command.action === "repeat") media.repeat = command.repeat || "off";
    media.ack = command.sequence;
  }
  mediaQueueRender();
}
async function mediaHeartbeat() {
  if (!media.session || media.busy || $("workspace").hidden) return;
  media.busy = true;
  try {
    const player = mediaPlayer();
    const report = {current_id: player.dataset.mediaId || null, queue: media.queue, index: media.index, position: player.currentTime || 0, duration: Number.isFinite(player.duration) ? player.duration : 0, paused: player.paused, volume: player.volume, shuffle: media.shuffle, repeat: media.repeat, command_ack: media.ack, track_state: mediaTrackState(), track_result: media.trackResult || null};
    const response = await api(`media/sessions/${encodeURIComponent(media.session.id)}`, {token: media.session.token, report, context: {preview: media.preview ? {item_id: media.preview.item_id, verified_bytes: media.preview.verified_bytes, total_bytes: media.preview.total_bytes} : null, kind: media.kind, view: media.view, selection: media.selected?.id || null, filters: {q: $("media-search").value, genre: $("media-genre").value, year: $("media-year").value, language: $("media-language").value}}});
    mediaTrackRequestFailure(response.state?.track_request);
    await mediaCommands(response.commands || []);
    if (!$("media-player-menu").hidden && !$("media-player-tracks").contains(document.activeElement)) { mediaRenderPlayerTracks(); mediaPositionPlayerMenu(); }
  } finally { media.busy = false; }
}
async function mediaPlaylists() {
  const rows = await api(`media/playlists?${mediaQuery({})}`), root = $("media-playlist-list"); root.replaceChildren();
  const playlists = rows.rows || rows;
  if (!playlists.length) root.append(element("p", say("Your saved playlists will appear here. Start with a track or album, then save its queue.", "Vos playlists apparaîtront ici. Lancez une piste ou un album, puis enregistrez la file."), "media-playlist-empty"));
  for (const row of playlists) {
    const item = element("article", undefined, "media-playlist-card"), actions = element("div", undefined, "media-card-actions");
    const count = row.media_ids?.length || 0;
    item.append(element("h3", row.name), element("p", say(`${count} track${count === 1 ? "" : "s"}`, `${count} piste${count === 1 ? "" : "s"}`), "media-card-meta"));
    actions.append(button(say("Play", "Lire"), () => mediaStart(row.media_ids || [])), button(say("Add to queue", "Ajouter à la file"), () => mediaEnqueue(row.media_ids || [])));
    const options = element("details"), more = element("summary", say("Edit playlist", "Modifier la playlist"));
    options.append(more, button(say("Replace with queue", "Remplacer par la file"), async () => { await api("media/playlists", {client_id: mediaClient(), id: row.id, name: row.name, media_ids: media.queue}); await mediaPlaylists(); }), button(say("Delete", "Supprimer"), async () => { await api(`media/playlists/${encodeURIComponent(row.id)}?${mediaQuery({})}`, undefined, "DELETE"); await mediaPlaylists(); }));
    item.append(actions, options); root.append(item);
  }
  mediaQueueRender();
}
async function mediaScan(quiet = false) {
  if (!quiet) $("media-library-options").open = false;
  const job = await api("media/scan", {client_id: mediaClient()}); media.scan = job.id; media.scanQuiet = quiet;
  $("media-cancel-scan").hidden = false; $("media-refresh").disabled = true;
  mediaScanIcon();
  if (!quiet) mediaStatus("Scanning Library Folders...");
}
// New films and episodes appear on their own: a quiet rescan reloads only what changed.
const MEDIA_AUTO_REFRESH = 60000;
async function mediaAutoScan() {
  if (state.view !== "media" || $("workspace").hidden || media.scan || !state.setup?.capabilities?.scan) return;
  await mediaScan(true);
}
// The toolbar ⟳ refreshes the library; while a refresh runs, the same button cancels it.
function mediaScanIcon() {
  const running = !!media.scan, icon = $("media-toolbar-refresh");
  const label = running ? say("Cancel library refresh", "Annuler l’actualisation") : say("Refresh library", "Actualiser la médiathèque");
  icon.setAttribute("aria-pressed", String(running)); icon.title = label; icon.setAttribute("aria-label", label);
}
async function mediaPollScan() {
  if (!media.scan) return;
  const job = await api(`jobs/${encodeURIComponent(media.scan)}`);
  const quiet = media.scanQuiet;
  if (!quiet) mediaStatus(job.progress?.message || (job.progress?.items !== undefined ? `Scanning Library Folders... ${job.progress.items} items found` : job.message || `Scan ${job.status}`));
  if (!["queued", "running"].includes(job.status)) {
    media.scan = ""; media.scanQuiet = false; mediaScanIcon(); $("media-cancel-scan").hidden = true; $("media-refresh").disabled = false;
    if (!quiet || job.result?.changed) await loadMedia();
    if (job.error && !quiet) mediaStatus(job.error);
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
  for (const [id, label] of [["media-chat-history", say("Discussions", "Discussions")], ["media-chat-more", say("More", "Plus")], ["media-chat-close", say("Close chat", "Fermer la discussion")]]) {
    $(id).title = label; $(id).setAttribute("aria-label", label);
  }
  $("media-chat-resize").setAttribute("aria-label", say("Resize chat", "Redimensionner la discussion"));
  for (const id of ["media-chat", "media-feature-chat", "media-toolbar-chat"]) $(id)?.setAttribute("aria-pressed", String(media.chat));
  $("media-toolbar-chat").title = say("Chat", "Discussion"); $("media-toolbar-chat").setAttribute("aria-label", say("Chat", "Discussion"));
}
async function mediaOpenChat(conversationId = "", fresh = false) {
  await mediaSession(); await mediaHeartbeat();
  const result = await api(`media/sessions/${encodeURIComponent(media.session.id)}/chat`, {token: media.session.token, conversation_id: conversationId, new: fresh});
  if (!media.chat) mediaRestoreChatWidth();
  media.chat = true; $("media-chat-panel").hidden = false; document.body.classList.add("media-chat-open");
  mediaChatButtons(); mediaCloseChatMenu();
  await mountMediaAssistant($("media-chat-content"), result.conversation_id);
  $("assistant-prompt")?.focus();
}
async function mediaToggleChat() { if (media.chat) mediaCloseChat(); else await mediaOpenChat(); }
function mediaCloseChat() { media.chat = false; mediaCloseChatMenu(); $("media-chat-panel").hidden = true; document.body.classList.remove("media-chat-open"); mediaChatButtons(); restoreMediaAssistant(); }
function mediaCloseChatMenu() { $("media-chat-menu").hidden = true; $("media-chat-menu").replaceChildren(); }
function mediaChatMenu(anchor, items) {
  const menu = $("media-chat-menu");
  if (!menu.hidden && menu.dataset.anchor === anchor.id) return mediaCloseChatMenu();
  menu.replaceChildren(...items.map(([label, action, checked]) => {
    const item = button(label, () => { mediaCloseChatMenu(); guard(action); });
    item.setAttribute("role", checked === undefined ? "menuitem" : "menuitemradio");
    if (checked !== undefined) item.setAttribute("aria-checked", String(checked));
    return item;
  }));
  menu.dataset.anchor = anchor.id; menu.hidden = false;
  menu.querySelector("button")?.focus();
}
async function mediaChatHistory() {
  const conversations = (await api("assistant/conversations")).filter(c => c.folder === "Media").slice(0, 20);
  mediaChatMenu($("media-chat-history"), [
    [say("New discussion", "Nouvelle discussion"), () => mediaOpenChat("", true)],
    ...conversations.map(c => [c.name, () => mediaOpenChat(c.id), c.id === assistantConversation]),
  ]);
}
function mediaChatMore() {
  mediaChatMenu($("media-chat-more"), [
    [say("Discussion settings", "Paramètres de la discussion"), () => $("assistant-chat-settings")?.click()],
    [say("Delete discussion", "Supprimer la discussion"), async () => {
      if (!assistantConversation || !confirm(say("Delete this discussion and its history? Pending proposals will be rejected. Torrents and files will not be removed.", "Supprimer cette discussion et son historique ? Les propositions en attente seront refusées. Les torrents et fichiers ne seront pas supprimés."))) return;
      await api(`assistant/conversations/${assistantConversation}`, undefined, "DELETE");
      await mediaOpenChat("", true);
    }],
  ]);
}
function mediaStartChatResize(event) {
  event.preventDefault();
  // Listen on the window: pointer capture is not available for every input device.
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
  document.body.classList.toggle("media-center-mode", enabled);
  const label = enabled ? say("Return to TorrentLinker", "Revenir à TorrentLinker") : say("Media Center mode", "Mode Media Center");
  $("media-center-mode").title = label; $("media-center-mode").setAttribute("aria-label", label);
  $("media-center-mode").setAttribute("aria-pressed", String(enabled));
}
async function mediaExitCenter() {
  if (document.fullscreenElement === document.documentElement) await document.exitFullscreen();
  mediaCenterAppearance(false);
}
$("media-center-mode").onclick = () => guard(async () => {
  if (document.body.classList.contains("media-center-mode")) await mediaExitCenter();
  else {
    if (document.fullscreenEnabled) await document.documentElement.requestFullscreen();
    mediaCenterAppearance(true);
  }
});
$("media-layout-switch").onchange = event => mediaSetLayout(event.target.value);
$("settings-media-layout").onchange = event => mediaSetLayout(event.target.value);
for (const item of document.querySelectorAll("[data-media-view]")) item.onclick = () => guard(async () => {
  // A browse tab returns to its rows, so it clears the filters a row's "See all" applied.
  media.gridMode = false; media.animeFilters = {};
  for (const key of ["genre", "year", "language", "availability"]) $(`media-${key}`).value = "";
  media.view = item.dataset.mediaView; $("media-view").value = media.view; await loadMedia();
});
$("media-details").addEventListener("click", event => { if (event.target === $("media-details")) { const box = event.target.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) event.target.close(); } });
$("media-player-expand").onclick = () => { const expanded = $("media-player-shell").classList.toggle("media-player-expanded"); $("media-player-expand").textContent = expanded ? say("Compact player", "Réduire le lecteur") : say("Expand player", "Agrandir le lecteur"); };
$("media-fullscreen").hidden = !document.fullscreenEnabled;
$("media-fullscreen").onclick = () => guard(async () => {
  if (document.fullscreenElement === $("media-player-shell")) await document.exitFullscreen();
  else await $("media-player-shell").requestFullscreen();
});
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement) mediaCenterAppearance(false);
  const fullscreen = document.fullscreenElement === $("media-player-shell");
  $("media-fullscreen").textContent = fullscreen ? say("Exit fullscreen", "Quitter le plein écran") : say("Fullscreen", "Plein écran");
  $("media-fullscreen").dataset.i18n = fullscreen ? "mediaExitFullscreen" : "mediaFullscreen";
  $("media-fullscreen").setAttribute("aria-pressed", String(fullscreen));
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.fullscreenElement === $("media-player-shell")) {
    guard(() => document.exitFullscreen());
  } else if (event.key === "Escape" && document.body.classList.contains("media-center-mode")) {
    guard(mediaExitCenter);
  }
});
mediaSetLayout(media.layout);
$("logout").addEventListener("click", () => { mediaInvalidatePlayback(); mediaPlayer().pause(); });
$("target-client").addEventListener("change", mediaInvalidatePlayback);
$("media-stop").onclick = () => guard(mediaStop);
$("media-refresh-preview").onclick = () => guard(() => { if (media.preview) return mediaPreview(media.preview.item_id, true); });
$("media-video-tab").onclick = () => guard(async () => { media.kind = "video"; media.view = "recent"; mediaViews(); await loadMedia(); });
$("media-music-tab").onclick = () => guard(async () => { media.kind = "music"; media.view = "albums"; mediaViews(); await loadMedia(); });
$("media-view").onchange = () => guard(async () => { media.view = $("media-view").value; await loadMedia(); });
for (const item of document.querySelectorAll("[data-media-music-view]")) item.onclick = () => guard(async () => { media.view = item.dataset.mediaMusicView; $("media-view").value = media.view; await loadMedia(); });
for (const key of ["genre", "year", "language", "availability"]) $(`media-${key}`).onchange = () => guard(loadMedia);
let mediaSearchTimer;
$("media-search").oninput = () => { clearTimeout(mediaSearchTimer); mediaSearchTimer = setTimeout(() => guard(loadMedia), 250); };
$("media-refresh").onclick = () => guard(mediaScan);
for (const event of ["play", "pause", "ended", "emptied"]) $("media-audio").addEventListener(event, mediaMusicBar);
$("media-toolbar-refresh").onclick = () => guard(async () => { if (media.scan) await api(`jobs/${encodeURIComponent(media.scan)}/cancel`, {}); else await mediaScan(); });
mediaScanIcon();
$("media-more").onclick = () => guard(() => loadMedia(true));
$("media-cancel-scan").onclick = () => guard(async () => { if (media.scan) await api(`jobs/${encodeURIComponent(media.scan)}/cancel`, {}); });
$("media-chat").onclick = () => guard(mediaToggleChat); $("media-toolbar-chat").onclick = () => guard(mediaToggleChat); $("media-chat-close").onclick = mediaCloseChat;
mediaCenterAppearance(document.body.classList.contains("media-center-mode")); mediaChatButtons();
$("media-chat-history").onclick = () => guard(mediaChatHistory); $("media-chat-more").onclick = mediaChatMore;
$("media-chat-resize").addEventListener("pointerdown", mediaStartChatResize); $("media-chat-resize").addEventListener("keydown", mediaChatResizeKey);
$("media-chat-panel").addEventListener("keydown", e => { if (e.key === "Escape" && !$("media-chat-menu").hidden) { e.stopPropagation(); mediaCloseChatMenu(); } });
window.addEventListener("resize", () => { if (media.chat) mediaChatWidth($("media-chat-panel").getBoundingClientRect().width); });
$("media-previous").onclick = () => guard(() => mediaAdvance(-1)); $("media-next").onclick = () => guard(() => mediaAdvance(1));
$("media-shuffle").onclick = () => { media.shuffle = !media.shuffle; mediaQueueRender(); guard(mediaHeartbeat); };
$("media-repeat").onchange = () => { media.repeat = $("media-repeat").value; guard(mediaHeartbeat); };
$("media-queue-details").ontoggle = event => { if (event.target.open) { guard(mediaQueueMetadata); mediaPositionPlayerMenu(); } };
$("media-show-queue").onclick = () => { if (!media.queue.length) return; if (mediaPlayer() === $("media-video")) mediaOpenPlayerMenu(); $("media-queue-details").open = true; $("media-player-shell").scrollIntoView({block: "nearest"}); };
$("media-player-menu-toggle").onclick = () => $("media-player-menu").hidden ? mediaOpenPlayerMenu() : mediaClosePlayerMenu(true);
$("media-player-menu-close").onclick = () => mediaClosePlayerMenu(true);
$("media-video-stage").oncontextmenu = event => { event.preventDefault(); mediaOpenPlayerMenu({x: event.clientX, y: event.clientY}); };
$("media-video-stage").addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("media-player-menu").hidden) { event.preventDefault(); event.stopPropagation(); mediaClosePlayerMenu(true); }
  if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) { event.preventDefault(); mediaOpenPlayerMenu(); }
});
document.addEventListener("pointerdown", event => { if (!$("media-player-menu").hidden && !$("media-player-menu").contains(event.target) && event.target !== $("media-player-menu-toggle")) mediaClosePlayerMenu(); });
$("media-player-menu").addEventListener("click", event => { if (["media-stop", "media-fullscreen", "media-player-expand", "media-chat", "media-previous", "media-next", "media-refresh-preview"].includes(event.target.id)) mediaClosePlayerMenu(); });
for (const kind of ["audio", "subtitle"]) $(`media-player-${kind}-track`).onchange = event => {
  const select = event.target;
  mediaSelectTrack({kind, track_id: select.value, source_token: select.dataset.sourceToken, media_id: select.dataset.mediaId});
  guard(mediaHeartbeat);
};
let mediaOverlayTimer;
$("media-video-stage").addEventListener("pointermove", () => {
  $("media-video-stage").classList.add("media-controls-revealed"); clearTimeout(mediaOverlayTimer);
  mediaOverlayTimer = setTimeout(() => $("media-video-stage").classList.remove("media-controls-revealed"), 1600);
});
$("media-video-stage").addEventListener("pointerdown", () => {
  $("media-video-stage").classList.add("media-controls-revealed"); clearTimeout(mediaOverlayTimer);
  mediaOverlayTimer = setTimeout(() => $("media-video-stage").classList.remove("media-controls-revealed"), 1600);
});
for (const event of ["play", "pause", "ended", "emptied"]) $("media-video").addEventListener(event, () => { $("media-video-stage").dataset.playing = String(!$("media-video").paused && !$("media-video").ended); });
window.addEventListener("resize", () => mediaPositionPlayerMenu());
document.addEventListener("fullscreenchange", () => mediaPositionPlayerMenu());
$("media-save-playlist").onsubmit = e => { e.preventDefault(); guard(async () => { await api("media/playlists", {client_id: media.playerClient || mediaClient(), name: $("media-playlist-name").value, media_ids: media.queue}); $("media-playlist-name").value = ""; await mediaPlaylists(); }); };
for (const player of [$("media-video"), $("media-audio")]) { player.onerror = mediaCodecError; player.onwaiting = () => { if (media.preview && player.currentTime > 0) mediaStatus(say("The fixed partial preview has no more playable data here. Wait for more download progress, then refresh preview.", "L’aperçu partiel fixe ne contient plus de données lisibles à cet endroit. Attendez la progression du téléchargement, puis actualisez l’aperçu.")); }; player.onended = () => guard(async () => { if (media.preview) { mediaStatus(say("End of fixed partial preview. Wait for more data, then refresh preview.", "Fin de l’aperçu partiel fixe. Attendez davantage de données, puis actualisez l’aperçu.")); } else if (media.repeat === "one") { player.currentTime = 0; await mediaTryPlay(player); } else await mediaAdvance(1); await mediaHeartbeat(); }); }
setInterval(() => { guard(mediaHeartbeat); guard(mediaPollScan); }, 1000);
setInterval(() => guard(mediaAutoScan), MEDIA_AUTO_REFRESH);
