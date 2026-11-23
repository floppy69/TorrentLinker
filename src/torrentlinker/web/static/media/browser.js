/* Shared Media browsing. The host keeps the player, its queue and the chat. */
const media = {kind: "video", view: "recent", animeFilters: {}, rows: [], homeRows: [], gridMode: false, selected: null, featureId: null, continueRows: [], next: null, scan: "", request: 0};
const mediaItems = new Map();
const mediaPreferences = window.mediaHostPreferences || localStorage;
media.layout = mediaLayoutValue(mediaPreferences.getItem("tl-media-layout"));
media.horizon = "home"; // Horizon's view, chosen in Settings
// "See all" from Horizon's Home shows the Wall: compact posters that load as they scroll.
const mediaHorizonScreen = () => media.gridMode && media.horizon === "home" ? "wall" : media.horizon;
const mediaHorizon = view => media.layout === "horizon" && mediaHorizonScreen() === view;
function mediaSetLayout(value) {
  media.layout = mediaLayoutValue(value);
  mediaPreferences.setItem("tl-media-layout", media.layout);
  $("view-media").dataset.layout = media.layout;
  $("media-layout-switch").value = media.layout;
  guard(loadMedia); // Horizon's Home draws rows the other views do not
}
function mediaSetHorizon(value) {
  media.horizon = mediaHorizonValue(value);
  mediaPreferences.setItem("tl-media-horizon", media.horizon);
  guard(loadMedia);
}
function mediaStatus(text) { $("media-status").textContent = text; }
function mediaViews() {
  rememberMediaView();
  $("media-layout-switch").setAttribute("aria-label", say("Media layout", "Disposition des médias"));
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
  const queryKey=JSON.stringify({client:mediaClient(),grid:media.gridMode,...query,offset:0});
  const keepCount=!append&&media.queryKey===queryKey?media.rows.length:0;
  const home = !append && mediaHomeActive();
  const [result, continuing, rows] = await Promise.all([
    api(`media?${mediaQuery(query)}`),
    media.kind === "video" ? api(`media?${mediaQuery({...query, view: "continue", offset: 0, limit: 8})}`) : Promise.resolve({rows: []}),
    home ? api(`media/home?${mediaQuery({scope: {films: "films", series: "series", anime: "anime", adult: "adult"}[media.view] || "home"})}`) : Promise.resolve({rows: []}),
  ]);
  if (version !== media.request) return;
  while(result.has_more&&result.rows.length<keepCount){
    const page=await api(`media?${mediaQuery({...query,offset:result.next_offset,limit:Math.min(200,keepCount-result.rows.length)})}`);
    if(version!==media.request)return;
    result.rows.push(...page.rows);result.has_more=page.has_more;result.next_offset=page.next_offset;
  }
  media.queryKey=queryKey;
  if (!append) { media.editRatings = !!result.edit_ratings; media.unrated = result.unrated || 0; if (typeof mediaRatingsNav === "function") mediaRatingsNav(); }
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
  mediaStatus(result.scanning ? say("Scanning Library Folders...", "Analyse des dossiers de bibliothèque…") : `${result.total} ${say(noun, ({video:"vidéo",album:"album",artist:"artiste",track:"piste"})[noun])}${result.total === 1 ? "" : "s"}${result.errors?.length ? say(" · Some folders are unavailable. Previous items were kept.", " · Certains dossiers sont indisponibles. Les médias précédents sont conservés.") : ""}`);
  const scroller=document.querySelector(".media-scroll"),savedScroll=window.scrollY,savedInner=scroller.scrollTop;
  mediaRender();
  window.scrollTo(0,savedScroll);scroller.scrollTop=savedInner;
  if(version!==media.request)return;
  if (media.kind === "music") await mediaPlaylists();
}
function mediaCanPreview(row) {
  return row.kind === "video" && row.availability === "unfinished" && row.preview_supported === true;
}
function mediaPreviewAction(row, className = "") {
  return button(say("Preview downloaded portion", "Prévisualiser la partie téléchargée"), () => mediaPreview(row.id), className);
}
function mediaSelectFeature(row) { media.featureId = row.id; media.selected = row; mediaRenderFeature(); mediaMarkSelected(); mediaRenderEpisodes(row).catch(() => {}); }
// Every card of the featured title is pressed, wherever it is, so that Horizon can grow it.
function mediaMarkSelected() {
  for (const card of document.querySelectorAll(".media-row-card[data-id], .media-poster-button[data-id]")) card.setAttribute("aria-pressed", String(card.dataset.id === media.featureId));
}
// A chosen series unfolds under its description: one tab per season, then its episodes.
async function mediaRenderEpisodes(row) {
  const root = $("media-episodes");
  if (!row || media.kind !== "video" || !row.series) { root.hidden = true; root.replaceChildren(); return; }
  const version=media.request;
  const detail = await api(`media/items/${encodeURIComponent(row.id)}?${mediaQuery({})}`);
  if (media.featureId !== row.id || version!==media.request) return;
  const previousSeason=root.dataset.owner===row.id?Number(root.querySelector("[data-season][aria-pressed=true]")?.dataset.season):row.season;
  const episodes = detail.episodes || [];
  root.hidden = !episodes.length; root.replaceChildren();root.dataset.owner=row.id;
  if (!episodes.length) return;
  const header = element("div", undefined, "media-episodes-header"), list = element("div", undefined, "media-row-track media-episode-track");
  header.append(element("h2", detail.series));
  const seasons = [...new Set(episodes.map(e => e.season).filter(s => s !== null && s !== undefined))].sort((a, b) => a - b);
  const show = season => {
    for (const tab of header.querySelectorAll("button[data-season]")) tab.setAttribute("aria-pressed", String(Number(tab.dataset.season) === season));
    list.replaceChildren();
    episodes.forEach((episode, index) => {
      if (season !== undefined && episode.season !== season) return;
      const preview = mediaCanPreview(episode);
      const card = button("", () => preview ? mediaPreview(episode.id) : mediaStart(episodes.map(e => e.id), index), "media-episode-card");
      const number = episode.episode ?? null;
      const name = episode.episode_title ? `${number !== null ? `${number}. ` : ""}${episode.episode_title}` : number !== null ? say(`Episode ${number}`, `Épisode ${number}`) : episode.release || episode.title;
      const facts = [episode.duration ? mediaTime(episode.duration) : "", episode.watched ? say("watched", "vu") : episode.position ? say(`resume at ${mediaTime(episode.position)}`, `reprendre à ${mediaTime(episode.position)}`) : "", episode.available === false ? say("unavailable", "indisponible") : ""].filter(Boolean).join(" · ");
      const still = mediaArt({...row, title: name}, "media-episode-still");
      if (episode.duration && episode.position && !episode.watched) {
        const progress = element("progress"); progress.max = episode.duration; progress.value = episode.position; still.append(progress);
      }
      card.append(still, element("strong", name), element("span", facts));
      if (preview) card.append(element("span", say("Preview downloaded portion", "Prévisualiser la partie téléchargée")));
      card.setAttribute("aria-label", preview ? `${say("Preview", "Prévisualiser")}: ${name}` : name); card.disabled = episode.available === false && !preview;
      list.append(card);
    });
  };
  for (const season of seasons) {
    const tab = button(say(`Season ${season}`, `Saison ${season}`), () => show(season), "quiet");
    tab.dataset.season = season; header.append(tab);
  }
  root.append(header, list);
  show(seasons.includes(previousSeason) ? previousSeason : seasons.includes(detail.season) ? detail.season : seasons[0]);
}
function mediaFileSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0 || value == null) return "";
  const units = language === "fr" ? ["o", "ko", "Mo", "Go", "To"] : ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(units.length - 1, Math.max(0, Math.floor(Math.log10(bytes || 1) / 3)));
  return `${new Intl.NumberFormat(language, {maximumFractionDigits: unit ? 1 : 0}).format(bytes / 1000 ** unit)} ${units[unit]}`;
}
function mediaRenderFeature() {
  const root = $("media-feature");
  const candidates = [...media.rows, ...media.continueRows, ...media.homeRows.flatMap(r => r.rows)];
  const row = candidates.find(item => item.id === media.featureId) || candidates.find(item => item.available !== false && item.artwork_url) || candidates.find(item => item.available !== false) || candidates[0];
  root.hidden = media.kind !== "video" || !row;
  $("view-media").dataset.feature = root.hidden ? "hidden" : "shown";
  if (root.hidden) {
    if (media.selected?.kind !== media.kind) media.selected = null;
    if(typeof mediaSelectionChanged === "function")mediaSelectionChanged(media.selected);
    return;
  }
  // Another film fades in behind its title; nothing moves.
  const changed = media.shownFeature !== undefined && media.shownFeature !== row.id;
  const synopsisScroll = changed ? 0 : root.querySelector(".media-feature-description")?.scrollTop || 0;
  media.shownFeature = row.id;
  root.classList.remove("fade"); if (changed) { void root.offsetWidth; root.classList.add("fade"); }
  media.featureId = row.id; media.selected = row;
  if(typeof mediaSelectionChanged === "function")mediaSelectionChanged(row);
  const scroll = root.querySelector(".media-focus-strip")?.scrollLeft || 0;
  const focused = document.activeElement?.closest?.(".media-focus-choice")?.dataset.id;
  root.replaceChildren();
  const art = mediaArt(row, "media-feature-art"); root.append(art);
  // Horizon draws the featured artwork, blurred, behind the whole page.
  const backdrop = art.querySelector("img"), page = $("view-media");
  if (!backdrop) page.style.removeProperty("--horizon-art");
  else backdrop.addEventListener("load", () => { if (media.featureId === row.id) page.style.setProperty("--horizon-art", `url("${backdrop.src}")`); }, {once: true});
  const copy = element("div", undefined, "media-feature-copy");
  // The poster sits left of the title and description, over the same artwork backdrop.
  copy.classList.add("has-poster"); copy.append(mediaArt(row, "media-feature-poster"));
  const content = element("div", undefined, "media-feature-content"); copy.append(content);
  content.append(element("h2", row.title));
  const facts = [row.year, row.duration > 0 ? mediaTime(row.duration) : "", row.rating ? `★ ${row.rating}` : ""].filter(Boolean);
  const meta = element("p", facts.join(" · "), "media-feature-meta");
  if (typeof mediaRatingBadge === "function") mediaRatingBadge(row, meta);
  content.append(meta);
  if (media.layout === "horizon" && typeof mediaFlags === "function") {
    const flags = element("ul", undefined, "media-feature-flags");
    for (const [text, strong] of mediaFlags(row)) flags.append(element("li", text, strong ? "strong" : ""));
    if (flags.childElementCount) content.append(flags);
  }
  const description = element("div", undefined, "media-feature-description");
  description.tabIndex = 0; description.setAttribute("aria-label", say("Full synopsis", "Synopsis complet"));
  description.append(element("p", row.description || say("No local synopsis available.", "Aucun synopsis local disponible.")));
  content.append(description);
  // A status refresh must not send someone reading a long synopsis back to its start.
  requestAnimationFrame(() => { if (description.isConnected) description.scrollTop = synopsisScroll; });
  const tags = element("dl", undefined, "media-feature-tags"); tags.id = "media-feature-details";
  const flags = typeof mediaFlags === "function" ? mediaFlags({...row, release: row.tracker?.name || row.release}) : [];
  const languages = row.language || flags.map(([text]) => text).find(text => ["MULTI", "VF", "VOSTFR"].includes(text));
  for (const [label, value] of [[say("Languages", "Langues"), languages], [say("Genre", "Genre"), row.genre], [say("Version", "Version"), flags.map(([text]) => text).join(" · ")], [say("File size", "Poids"), mediaFileSize(row.tracker?.size ?? row.size)]]) {
    const tag = element("div", undefined, "media-feature-tag");
    tag.append(element("dt", label), element("dd", value || say("Unknown", "Inconnu"))); tags.append(tag);
  }
  content.append(tags);
  const actions = element("div", undefined, "media-feature-actions");
  if (row.tracker) {
    // A film on c411, not in the library: its best release, and a way to queue it.
    description.append(mediaTrackerRelease(row.tracker));
    // A Member asks instead (requests.js).
    if (state.setup?.owner === false) { mediaRequestActions(row, description, actions); content.append(actions); root.append(copy); return; }
    const queue = button(say("Download", "Télécharger"), () => guard(async () => {
      queue.disabled = true;
      try {
        await api(`media/tracker/${encodeURIComponent(row.tracker.hash)}/download`, {});
        toast(say(`Sending ${row.tracker.name} to the client.`, `Envoi de ${row.tracker.name} au client.`));
      } finally { queue.disabled = false; }
    }), "media-primary");
    actions.append(queue); content.append(actions); root.append(copy);
    return;
  }
  const play = mediaCanPreview(row) ? mediaPreviewAction(row, "media-primary") : button(row.position > 0 && !row.watched ? say("Resume", "Reprendre") : say("Play", "Lire"), () => mediaStart([row.id]), "media-primary"); play.disabled = row.available === false && !mediaCanPreview(row);
  const seen = button("", () => guard(async () => {
    seen.disabled = true;
    try {
      await api(`media/items/${encodeURIComponent(row.id)}/watched`, {client_id: mediaClient(), watched: !row.watched});
      toast(row.watched ? say("Marked as unwatched", "Marqué comme non vu") : say("Marked as watched", "Marqué comme vu"));
      await loadMedia();
    } finally { seen.disabled = false; }
  }), "media-secondary media-seen");
  seen.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  seen.title = row.watched ? say("Mark unwatched", "Marquer comme non vu") : say("Mark watched", "Marquer comme vu");
  seen.setAttribute("aria-label", seen.title);
  seen.setAttribute("aria-pressed", String(!!row.watched));
  const info = element("details", undefined, "media-selection-info"), summary = element("summary", "ⓘ");
  summary.setAttribute("aria-label", say("About this selection", "À propos de la sélection"));
  const infoBody = element("div", undefined, "media-selection-info-body");
  infoBody.append(element("p", say("A poster selects this banner. Play starts the selected film. The banner stays pinned while the rows scroll.", "Une affiche change cette bannière. Lire lance le film sélectionné. La bannière reste épinglée pendant le défilement des rangées.")));
  if (row.identity_source === "filename") infoBody.append(element("p", say("Filename metadata", "Métadonnées du nom de fichier"), "media-metadata-source"));
  if (typeof mediaRatingEditor === "function") mediaRatingEditor(row, infoBody);
  infoBody.append(button(say("File details", "Détails du fichier"), () => mediaDetails(row.id), "media-secondary"));
  if (row.available === false) infoBody.append(element("p", row.reason || say("Unavailable", "Indisponible"), "media-availability-note"));
  info.append(summary, infoBody); info.open = !!media.infoOpen;
  info.ontoggle = () => { if (info.isConnected) media.infoOpen = info.open; };
  actions.append(play, seen, info);
  content.append(actions);
  root.append(copy);
  const strip = element("div", undefined, "media-focus-strip"); strip.id = "media-focus-strip"; strip.setAttribute("aria-label", say("Select a featured title", "Choisir le titre mis en avant"));
  for (const item of media.rows) {
    const choice = button("", () => mediaSelectFeature(item), "media-focus-choice");
    choice.dataset.id = item.id; choice.setAttribute("aria-label", item.title); choice.setAttribute("aria-pressed", String(item.id === row.id));
    choice.ondblclick = () => guard(() => mediaStart([item.id]));
    choice.append(mediaArt(item), element("span", item.title)); strip.append(choice);
  }
  root.append(strip); strip.scrollLeft = scroll;
  if (focused) strip.querySelector(`[data-id="${CSS.escape(focused)}"]`)?.focus({preventScroll: true});
  // Horizon's Showcase keeps the chosen poster in view as the carousel grows it.
  if (mediaHorizon("showcase")) strip.querySelector('[aria-pressed="true"]')?.scrollIntoView({block: "nearest", inline: "center", behavior: "smooth"});
  // ...and fetches the next titles before the selection reaches the end.
  if (mediaHorizon("showcase") && media.next && !media.loadingMore && media.rows.findIndex(item => item.id === row.id) >= media.rows.length - 8) {
    media.loadingMore = true; guard(() => loadMedia(true)).finally(() => { media.loadingMore = false; });
  }
}
// "2 days ago", from a Unix time in seconds; empty when c411 gave no date.
function mediaAge(seconds) {
  if (!seconds) return "";
  const days = (seconds * 1000 - Date.now()) / 86400000, format = new Intl.RelativeTimeFormat(language === "fr" ? "fr" : "en", {numeric: "auto"});
  if (days > -1) return format.format(Math.round(days * 24), "hour");
  if (days > -30) return format.format(Math.round(days), "day");
  if (days > -365) return format.format(Math.round(days / 30.4), "month");
  return format.format(Math.round(days / 365), "year");
}
function mediaTrackerRelease(release) {
  const box = element("div", undefined, "media-tracker-release");
  const pill = element("span", String(release.score), `media-score score-${release.color || "green"}`);
  pill.title = "ReleaseScore";
  const size = release.size >= 1e9 ? `${(release.size / 1e9).toFixed(1)} ${say("GB", "Go")}` : `${Math.round(release.size / 1e6)} ${say("MB", "Mo")}`;
  box.append(pill, element("span", release.name, "media-tracker-name"), element("span", [size, say(`${release.seeders} seeders`, `${release.seeders} sources`), mediaAge(release.published_at)].filter(Boolean).join(" · "), "media-tracker-facts"));
  if (release.own_score !== undefined) box.append(element("span", say(`Your file scores ${release.own_score}`, `Votre fichier obtient ${release.own_score}`), "media-tracker-facts"));
  return box;
}
function mediaRenderContinue() {
  const root = $("media-continue-items"); root.replaceChildren();
  $("media-continue").hidden = media.kind !== "video" || !media.continueRows.length;
  for (const row of media.continueRows) {
    const choice = button("", () => mediaStart([row.id]), "media-resume-card"); choice.setAttribute("aria-label", `${say("Resume", "Reprendre")} ${row.title}`);
    const art = mediaArt(row); const progress = element("progress"); progress.max = row.duration || Math.max(row.position, 1); progress.value = row.position || 0;
    choice.append(art, progress, element("strong", row.title), element("span", mediaTime(row.position), "media-resume-position"));
    const card = element("div", undefined, "media-resume-item");
    const remove = button("×", async () => {
      remove.disabled = true;
      try {
        await api(`media/items/${encodeURIComponent(row.id)}/forget-progress`, {});
        await loadMedia();
      } finally { remove.disabled = false; }
    }, "media-resume-remove");
    remove.title = say("Remove from Continue watching", "Retirer de la reprise");
    remove.setAttribute("aria-label", remove.title);
    card.append(choice, remove); root.append(card);
  }
}
// The video home shows rows (genres, series…); each row's "See all" opens the grid with its filters.
function mediaHomeActive() {
  return media.kind === "video" && ["recent", "films", "series", "anime", "adult"].includes(media.view) && !media.gridMode && (media.layout === "cinematic" || mediaHorizon("home")) && !$("media-search").value.trim()
    && ["genre", "year", "language", "availability"].every(key => !$(`media-${key}`).value);
}
const mediaRowTitle = row => row.key === "genre" ? row.title : ({recent: say("Recently added", "Récemment ajoutés"), series: say("Series", "Séries"), oav: say("OAV", "OAV"), films: say("Films", "Films"), rated: say("Highly rated", "Les mieux notés"), unwatched: say("Not watched yet", "Pas encore vus"), tracker: say("Available on the tracker", "Disponible sur le tracker"), upgrades: say("Better versions on the tracker", "Meilleures versions sur le tracker")})[row.key] || row.title;
const mediaRowKey = row => `${row.key}:${row.title}`;
// Horizon's Home shows one category at a time, chosen from its title.
const mediaHorizonRow = () => media.homeRows.find(row => mediaRowKey(row) === media.horizonRow) || media.homeRows[0];
function mediaRenderHome() {
  const root = $("media-home-rows"), active = mediaHomeActive() && media.homeRows.length > 0;
  root.hidden = !active; document.querySelector(".media-library-layout").hidden = active;
  $("view-media").dataset.home = String(active);
  root.replaceChildren();
  if (!active) return;
  const horizon = media.layout === "horizon";
  for (const row of horizon ? [mediaHorizonRow()] : media.homeRows) {
    const section = element("section", undefined, "media-home-row"), header = element("div", undefined, "media-home-row-header");
    const title = mediaRowTitle(row);
    section.setAttribute("aria-label", title);
    const track = element("div", undefined, "media-row-track");
    const step = direction => track.scrollBy({left: direction * Math.max(180, track.clientWidth - 180), behavior: "smooth"});
    track.addEventListener("wheel", event => mediaRowWheel(track, event), {passive: false});
    const back = button("‹", () => step(-1), "icon-button"), forward = button("›", () => step(1), "icon-button");
    back.setAttribute("aria-label", say("Scroll left", "Défiler à gauche")); forward.setAttribute("aria-label", say("Scroll right", "Défiler à droite"));
    const all = button(say("See all", "Voir tout"), () => guard(() => mediaSeeAll(row.filters)), "quiet media-see-all");
    all.dataset.total = String(row.total || row.rows.length);
    let heading = element("h2", title);
    if (horizon && media.homeRows.length > 1) {
      heading = document.createElement("select"); heading.className = "media-row-category"; heading.setAttribute("aria-label", say("Category", "Catégorie"));
      for (const other of media.homeRows) heading.append(new Option(mediaRowTitle(other), mediaRowKey(other)));
      heading.value = mediaRowKey(row);
      heading.onchange = () => {
        media.horizonRow = heading.value; mediaRenderHome();
        root.querySelector(".media-row-card")?.click(); // the category's first title
        root.querySelector(".media-row-category")?.focus();
      };
    }
    header.append(heading, element("span", row.state && row.state !== "ready" ? "" : say(`${row.total} titles`, `${row.total} titres`), "media-home-row-count"));
    if (!row.filters?.tracker) header.append(all);
    else if (row.key === "tracker" && typeof requestPermission === "function" && requestPermission("wish")) header.append(button(say("Make a wish", "Faire un vœu"), requestWishDialog, "quiet"));
    header.append(back, forward);
    for (const item of row.rows) track.append(mediaRowCard(item, row, track));
    if (!row.rows.length && row.state) track.append(...mediaRowPlaceholder(row));
    section.append(header, track); root.append(section);
    if (horizon) requestAnimationFrame(() => track.querySelector('[aria-pressed="true"]')?.scrollIntoView({block: "nearest", inline: "center"}));
  }
  // Rows can be drawn while the page is hidden; measure again whenever a row's size changes.
  mediaRowObserver ||= new ResizeObserver(mediaRowArrows);
  mediaRowObserver.disconnect();
  for (const track of root.querySelectorAll(".media-row-track")) mediaRowObserver.observe(track);
}
// A tracker row shows before its first answer: pulsing cards, or why it is empty.
function mediaRowPlaceholder(row) {
  if (row.state === "unavailable") {
    const why = {
      key: say("Add your c411 API key in Settings to list the tracker's releases.", "Ajoutez votre clé API c411 dans les paramètres pour lister les releases du tracker."),
      limit: say("c411 asked to wait; the tracker's releases will load on a later refresh.", "c411 demande d’attendre ; les releases du tracker se chargeront à une prochaine actualisation."),
      unreachable: say("c411 is not answering; the tracker's releases will load on a later refresh.", "c411 ne répond pas ; les releases du tracker se chargeront à une prochaine actualisation."),
    }[row.reason] || say("The tracker's releases are not available yet.", "Les releases du tracker ne sont pas encore disponibles.");
    const note = element("p", why, "media-row-note");
    return row.reason === "key" ? [note, button(say("Open Settings", "Ouvrir les paramètres"), navigate, "quiet")] : [note];
  }
  if (row.state === "empty") return [element("p", say(`No release reaches ${row.threshold} with this ReleaseScore profile.`, `Aucune release n’atteint ${row.threshold} avec ce profil ReleaseScore.`), "media-row-note")];
  const note = element("p", row.key === "upgrades" ? say("Comparing your films with the Catalogue…", "Comparaison de vos films avec le Catalogue…") : say("Reading the tracker's latest releases…", "Lecture des dernières releases du tracker…"), "media-row-note");
  const cards = Array.from({length: 6}, () => { const card = element("div", undefined, "media-row-skeleton"); card.setAttribute("aria-hidden", "true"); return card; });
  return [note, ...cards];
}
function mediaRowCard(item, row, track) {
  const card = button("", () => {
    mediaSelectFeature(item);
    for (const other of $("media-home-rows").querySelectorAll(".media-row-card")) other.setAttribute("aria-pressed", String(other.dataset.id === item.id));
    if (media.layout === "horizon") {
      // Horizon's row is a carousel: the chosen poster comes to the middle, and the
      // rest of the category arrives before the end is reached.
      card.scrollIntoView({block: "nearest", inline: "center", behavior: "smooth"});
      if ([...track.children].indexOf(card) >= track.childElementCount - 8) guard(() => mediaRowMore(row, track));
    }
  }, "media-row-card");
  card.dataset.id = item.id;
  card.setAttribute("aria-label", item.title); card.setAttribute("aria-pressed", String(item.id === media.featureId));
  if (!item.tracker) card.ondblclick = () => guard(() => mediaStart([item.id]));
  const art = mediaArt(item); if (typeof mediaRequestBadge === "function") mediaRequestBadge(item, art);
  card.append(art, element("strong", item.title), element("span", item.series_card ? say(`${item.episode_count} episodes`, `${item.episode_count} épisodes`) : [item.year, item.rating ? `★ ${item.rating}` : ""].filter(Boolean).join(" · ")));
  return card;
}
async function mediaRowMore(row, track) {
  if (row.loading || row.rows.length >= row.total) return;
  row.loading = true;
  try {
    const page = await api(`media?${mediaQuery({kind: "video", ...row.filters, offset: row.rows.length, limit: 40})}`);
    const known = new Set(row.rows.map(item => item.id));
    for (const item of page.rows) {
      if (known.has(item.id)) continue;
      row.rows.push(item); mediaItems.set(item.id, item);
      if (track.isConnected) track.append(mediaRowCard(item, row, track));
    }
    if (!page.has_more) row.total = row.rows.length;
  } finally { row.loading = false; }
}
let mediaRowObserver = null, mediaPinnedObserver = null;
function mediaWatchLayout() {
  if (mediaPinnedObserver) return;
  // The top bar sits over the film: the title leaves room for it.
  mediaPinnedObserver = new ResizeObserver(() => {
    const style = document.documentElement.style;
    style.setProperty("--media-topbar-height", `${document.querySelector(".media-topbar").offsetHeight}px`);
    style.setProperty("--media-nav-height", `${document.querySelector(".media-browse-nav").offsetHeight}px`);
  });
  for (const node of [document.querySelector(".media-topbar"), document.querySelector(".media-browse-nav")]) mediaPinnedObserver.observe(node);
  addEventListener("wheel", mediaHorizonWheel, {passive: false});
}
// Horizon's Home and Showcase fill one screen, like a living-room interface: the wheel moves
// the selection along the posters, one title per step, instead of scrolling anything.
let mediaWheelTotal = 0;
function mediaHorizonWheel(event) {
  const home = mediaHorizon("home") && $("view-media").dataset.home === "true", showcase = mediaHorizon("showcase");
  if (media.kind !== "video" || !(home || showcase) || event.ctrlKey) return;
  if (event.target.closest?.("dialog, .media-options-panel, select, #media-episodes, #media-search")) return;
  const delta = (Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY) * (event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? 400 : 1);
  event.preventDefault();
  mediaWheelTotal += delta;
  if (Math.abs(mediaWheelTotal) < 50) return;
  const step = Math.sign(mediaWheelTotal); mediaWheelTotal = 0;
  const cards = [...document.querySelectorAll(home ? "#media-home-rows .media-row-card" : "#media-focus-strip .media-focus-choice")];
  const index = cards.findIndex(card => card.dataset.id === media.featureId);
  cards[Math.max(0, Math.min(cards.length - 1, index + step))]?.click();
}
// The wheel over a row only ever scrolls that row, even at its ends.
function mediaRowWheel(track, event) {
  if (media.layout === "horizon" || event.shiftKey || event.ctrlKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
  event.preventDefault();
  const delta = event.deltaY * (event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? track.clientWidth : 1);
  // Snapping would pull small wheel steps back to the same card; it returns once the wheel rests.
  track.style.scrollSnapType = "none";
  track.scrollLeft += delta;
  clearTimeout(track.wheelRest);
  track.wheelRest = setTimeout(() => { track.style.scrollSnapType = ""; }, 250);
}
function mediaRowArrows() {
  // The arrows appear only when a row is wider than the page.
  for (const section of document.querySelectorAll(".media-home-row")) {
    const track = section.querySelector(".media-row-track"), overflow = track.scrollWidth > track.clientWidth + 2;
    for (const arrow of section.querySelectorAll(".media-home-row-header .icon-button")) arrow.hidden = !overflow;
    const all = section.querySelector(".media-see-all");
    if (all) all.hidden = !overflow && Number(all.dataset.total) <= track.querySelectorAll(".media-row-card").length;
  }
}
async function mediaSeeAll(filters) {
  media.homeReturn = {view: media.view, filters: Object.fromEntries(["genre", "year", "language", "availability"].map(key => [key, $(`media-${key}`).value])), animeFilters: {...media.animeFilters}};
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
  window.scrollTo({top: 0}); document.querySelector(".media-scroll").scrollTop = 0;
}
function mediaRender() {
  if (typeof watchRender === "function") watchRender();
  $("view-media").dataset.kind = media.kind; $("view-media").dataset.layout = media.layout; $("view-media").dataset.horizon = mediaHorizonScreen(); mediaWatchLayout();
  $("media-layout-switch").value = media.layout; // the saved layout, also when the view loads
  $("media-horizon-control").hidden = media.layout !== "horizon"; $("media-horizon-switch").value = media.horizon;
  // Horizon is a cinema skin: dark whatever the app's theme, like Kodi's.
  document.documentElement.dataset.theme = media.layout === "horizon" ? "dark" : environment.theme || "dark";
  $("view-media").dataset.musicView = media.view;
  $("view-media").dataset.empty = String(media.rows.length === 0);
  for (const item of document.querySelectorAll("[data-media-view]")) { item.classList.toggle("active", item.dataset.mediaView === media.view); item.setAttribute("aria-current", item.dataset.mediaView === media.view ? "page" : "false"); }
  for (const item of document.querySelectorAll("[data-media-music-view]")) { item.classList.toggle("active", item.dataset.mediaMusicView === media.view); item.setAttribute("aria-current", item.dataset.mediaMusicView === media.view ? "page" : "false"); }
  mediaRenderFeature(); mediaRenderContinue(); mediaRenderHome(); mediaRenderEpisodes(media.selected).catch(() => {});
  $("media-shelf-title").textContent = media.kind === "music" ? ({albums: say("Albums", "Albums"), artists: say("Artists", "Artistes"), tracks: say("Tracks", "Pistes")})[media.view] : ({recent: say("Recently added", "Récemment ajoutés"), continue: say("Continue watching", "Reprendre la lecture"), films: say("Films", "Films"), series: say("Series", "Séries"), anime: say("Anime", "Animés"), adult: "XXX"})[media.view] || say("Your videos", "Vos vidéos");
  $("media-shelf-count").textContent = say("From your Library Folders", "Dans vos dossiers de bibliothèque");
  $("media-home-back")?.remove();
  if (media.kind === "video" && media.gridMode && media.homeReturn) {
    const back = button(say("Back to rows", "Retour aux rangées"), () => guard(async () => {
      const previous = media.homeReturn;
      media.gridMode = false; media.view = previous.view; media.animeFilters = previous.animeFilters;
      for (const [key, value] of Object.entries(previous.filters)) $(`media-${key}`).value = value;
      $("media-view").value = media.view;
      await loadMedia();
    }), "media-see-all");
    back.id = "media-home-back"; $("media-shelf-count").after(back);
  }
  const root = $("media-results"); root.replaceChildren();
  if (!media.rows.length) { root.append(element("p", say("No media found. Add a Library Folder in Library options, then refresh the inventory.", "Aucun média trouvé. Ajoutez un dossier dans les options de bibliothèque, puis actualisez les médias."), "media-empty")); root.append(button(say("Add Library Folder", "Ajouter un dossier de bibliothèque"), () => navigate("setup"))); return; }
  if (media.kind === "music" && media.view === "tracks") { mediaRenderTracks(root); return; }
  const groups = new Map();
  for (const row of media.rows) {
    const key = media.kind === "music" && media.view === "albums" ? row.album_id || row.id : media.kind === "music" && media.view === "artists" ? row.artist || say("Unknown artist", "Artiste inconnu") : media.kind === "video" ? row.content_id || row.id : row.id;
    if (!groups.has(key)) groups.set(key, []); groups.get(key).push(row);
  }
  for (const rows of groups.values()) {
    const row = rows[0], card = element("article", undefined, `media-card ${media.kind === "music" ? "media-music-card" : "media-video-card"}`);
    const title = media.kind === "music" && media.view === "albums" ? row.album || say("Unknown album", "Album inconnu") : media.kind === "music" && media.view === "artists" ? row.artist || say("Unknown artist", "Artiste inconnu") : row.title;
    // A series card unfolds its episodes; any other card opens its details.
    const wall = media.kind === "video" && mediaHorizon("wall");
    const artwork = button("", () => wall ? mediaSelectFeature(row) : row.series_card ? (mediaSelectFeature(row), $("media-feature").scrollIntoView({block: "nearest", behavior: "smooth"})) : mediaDetails(row.id), "media-poster-button"); artwork.setAttribute("aria-label", wall ? title : `${say("Details", "Détails")}: ${title}`);
    if (wall) { artwork.dataset.id = row.id; artwork.setAttribute("aria-pressed", String(row.id === media.featureId)); artwork.ondblclick = () => guard(() => mediaDetails(row.id)); }
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
    const play = mediaCanPreview(row) ? mediaPreviewAction(row) : button(say("Play", "Lire"), () => mediaStart(mediaGroupIds(rows))); play.disabled = row.available === false && !mediaCanPreview(row);
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
  if(typeof mediaSelectionChanged === "function")mediaSelectionChanged(row);
  const root = $("media-details"); root.replaceChildren(); root.hidden = false;
  root.append(mediaArt(row, "media-detail-art"));
  if (!root.open) root.showModal();
  root.append(button(say("Close details", "Fermer les détails"), () => { root.close(); }), element("h2", row.title));
  root.append(element("p", row.description || say("No local synopsis available.", "Aucun synopsis local disponible.")));
  if (row.identity_source) root.append(element("p", say(`Metadata: ${row.identity_source}`, `Métadonnées : ${row.identity_source}`), "muted"));
  if (row.release) root.append(element("p", say(`Release: ${row.release}`, `Version : ${row.release}`), "muted"));
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
    if (row.language) root.append(element("p", say(`Audio languages from file metadata: ${row.language}. Playback support depends on the selected player.`, `Langues audio d’après les métadonnées du fichier : ${row.language}. La prise en charge dépend du lecteur choisi.`)));
    if (row.available !== false && !(typeof environment !== "undefined" && environment.mode === "desktop")) {
      const external = element("a", say("Open / download the original for an external player", "Ouvrir / télécharger l’original pour un lecteur externe"));
      external.href = typeof mediaExternalURL === "function" ? mediaExternalURL(id) : `api/media/items/${encodeURIComponent(id)}/stream?${mediaQuery({})}`; external.target = "_blank"; external.rel = "noopener"; external.download = ""; root.append(external);
    }
  }
  if (mediaCanPreview(row)) {
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
        const preview = mediaCanPreview(item), title = item.release || item.title;
        const choice = button(preview ? `${say("Preview", "Prévisualiser")}: ${title}` : title, () => { root.close(); return preview ? mediaPreview(item.id) : mediaStart([item.id]); });
        choice.disabled = item.available === false && !preview; choice.title = item.reason || ""; list.append(choice);
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
    root.append(element("h3", artistView ? row.artist || say("Unknown artist", "Artiste inconnu") : row.album || say("Track", "Piste")), button(artistView ? say("Play artist", "Lire cet artiste") : say("Play album", "Lire cet album"), () => { root.close(); return mediaStart(ids); }), button(say("Add to queue", "Ajouter à la file"), () => mediaEnqueue(ids)));
    const list = element("ol");
    tracks.forEach((item, index) => { const entry = element("li"); entry.append(button(`${item.title}${artistView ? ` · ${item.album || say("Unknown album", "Album inconnu")}` : ""}`, () => { root.close(); return mediaStart(ids, index); }), element("span", item.duration > 0 ? ` ${mediaTime(item.duration)}` : say(" Duration unknown", " Durée inconnue"), "muted")); list.append(entry); });
    root.append(list);
  }
}
// Horizon follows the focus, as with a remote: a poster reached with the keyboard becomes the featured title.
let mediaFocusTimer;
document.addEventListener("focusin", event => {
  const card = event.target.closest?.(".media-row-card[data-id], .media-focus-choice[data-id], .media-poster-button[data-id]");
  if (media.layout !== "horizon" || !card || card.dataset.id === media.featureId || !card.matches(":focus-visible")) return;
  clearTimeout(mediaFocusTimer);
  mediaFocusTimer = setTimeout(() => {
    const row = mediaItems.get(card.dataset.id);
    if (row && document.activeElement === card) mediaSelectFeature(row);
  }, 180);
});
// Horizon's clock, as on a living-room screen.
function mediaClock() {
  const clock = $("media-clock"); if (!clock) return;
  const now = new Date();
  clock.textContent = now.toLocaleTimeString(language === "fr" ? "fr-FR" : "en-GB", {hour: "2-digit", minute: "2-digit"});
  clock.dateTime = now.toISOString();
}
mediaClock(); setInterval(mediaClock, 15000);
