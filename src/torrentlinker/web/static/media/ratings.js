"use strict";
/* Age Ratings (layout A of docs/specs/members-ratings): the rating before the year on the title
   panel, its source and "Modifier" for editors, and the "Unrated" page of the Media menu.
   The server checks the Permission again; hiding is only presentation. */
const mediaRatingScale = ["TP", "10", "12", "16", "18"];
const mediaRatingShort = rating => rating === "TP" ? "TP" : `−${rating}`;
const mediaRatingName = rating => rating === "TP" ? say("All ages", "Tous publics") : `−${rating}`;
const mediaRatingCountry = code => ({FR: "France", US: say("United States", "États-Unis"), GB: say("United Kingdom", "Royaume-Uni"), DE: say("Germany", "Allemagne")})[code] || code;
function mediaRatingSource(age) {
  if (age.source === "nfo") return say("NFO file", "fichier NFO");
  if (age.source === "tmdb") return "TMDb (France)";
  return age.by || say("the owner", "le propriétaire");
}
media.editingRating = "";
// "TMDb: R (United States) → −16?" with its "Confirm" button.
function mediaRatingSuggestion(row, after) {
  const hint = row.age_rating?.suggestion || row.suggestion;
  if (!hint) return null;
  const line = element("p", `${hint.source === "nfo" ? "NFO" : "TMDb"} : ${hint.original} (${mediaRatingCountry(hint.country)}) → ${mediaRatingShort(hint.rating)} ?`, "media-rating-suggest");
  line.append(button(say(`Confirm ${mediaRatingShort(hint.rating)}`, `Confirmer ${mediaRatingShort(hint.rating)}`), () => mediaRate(row, hint.rating, after), "media-secondary"));
  return line;
}
function mediaRatingPicker(row, after) {
  const group = element("div", undefined, "media-rating-pick");
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", say(`Rating of ${row.title}`, `Classification de ${row.title}`));
  for (const rating of mediaRatingScale) {
    const choice = button(mediaRatingName(rating), () => mediaRate(row, rating, after), "media-secondary");
    choice.setAttribute("aria-pressed", String(row.age_rating?.rating === rating));
    group.append(choice);
  }
  return group;
}
async function mediaRate(row, rating, after) {
  const unrated = !row.age_rating?.rating;
  const age = await api(`media/items/${encodeURIComponent(row.id)}/rating`, {rating});
  // A series is rated as a whole: every episode shown takes the rating.
  for (const item of [row, ...mediaItems.values()]) if (item === row || (row.series && item.series === row.series)) item.age_rating = age;
  if (unrated) media.unrated = Math.max(0, (media.unrated || 0) - 1);
  media.editingRating = "";
  mediaRatingsNav();
  toast(`${row.title} : ${mediaRatingName(rating)}`);
  await after();
}
// The rating, before the year.
function mediaRatingBadge(row, meta) {
  const age = row.age_rating;
  if (!age) return;
  if (age.rating) {
    const badge = element("span", mediaRatingShort(age.rating), "media-age-rating");
    badge.title = mediaRatingSource(age);
    meta.prepend(badge);
  } else if (media.editRatings) meta.prepend(element("span", "?", "media-age-rating none"));
}
// For whoever may edit: the source and "Edit", or "Unrated" with the suggestion and the scale.
function mediaRatingEditor(row, copy) {
  const age = row.age_rating;
  if (!age || !media.editRatings) return;
  const redraw = async () => mediaRenderFeature();
  if (age.rating) {
    const editing = media.editingRating === row.id;
    const line = element("p", `${say("Rating", "Classification")} ${mediaRatingName(age.rating)} · ${mediaRatingSource(age)}`, "media-rating-line");
    line.append(button(editing ? say("Close", "Fermer") : say("Edit", "Modifier"), () => { media.editingRating = editing ? "" : row.id; mediaRenderFeature(); }, "quiet"));
    copy.append(line);
    if (editing) copy.append(mediaRatingPicker(row, redraw));
    return;
  }
  copy.append(element("p", say("Unrated: hidden from profiles with an age limit.", "Sans classification : masqué pour les profils limités."), "media-rating-line"));
  const hint = mediaRatingSuggestion(row, redraw);
  if (hint) copy.append(hint);
  copy.append(mediaRatingPicker(row, redraw));
}
function mediaRatingsNav() {
  const entry = $("media-ratings-entry");
  entry.hidden = !media.editRatings || media.kind !== "video";
  entry.textContent = `${say("Unrated", "Sans classification")}${media.unrated ? ` (${media.unrated})` : ""}`;
  entry.classList.toggle("active", !!media.ratingsPage);
  entry.setAttribute("aria-current", media.ratingsPage ? "page" : "false");
  $("view-media").dataset.page = media.ratingsPage ? "ratings" : "";
  $("media-ratings").hidden = !media.ratingsPage;
}
// The "Unrated" page: every unrated film and series, its suggestion, and the scale.
async function mediaRatingsPage() {
  media.ratingsPage = true;
  for (const item of document.querySelectorAll("[data-media-view]")) { item.classList.remove("active"); item.setAttribute("aria-current", "false"); }
  const data = await api(`media/ratings?${mediaQuery({})}`);
  if (!media.ratingsPage) return;
  media.unrated = data.rows.length;
  mediaRatingsNav();
  const root = $("media-ratings");
  root.replaceChildren(
    element("p", say("Ratings", "Classifications"), "media-eyebrow"),
    element("h1", say("Unrated", "Sans classification")),
    element("p", say(
      "These titles are hidden from profiles with an age limit until they have a rating. French ratings from TMDb and NFO files apply on their own; a foreign rating waits for your confirmation.",
      "Ces films sont masqués pour les profils limités tant qu'ils n'ont pas de classification. Les classifications françaises de TMDb et des fichiers NFO s'appliquent seules ; une classification étrangère attend votre confirmation.",
    ), "lead"),
  );
  const again = () => mediaRatingsPage();
  if (data.suggestions) {
    const actions = element("div", undefined, "media-feature-actions");
    actions.append(button(say(`Confirm the ${data.suggestions} suggestions`, `Confirmer les ${data.suggestions} suggestions`), async () => {
      const result = await api("media/ratings/confirm", {});
      toast(say(`${result.confirmed} ratings confirmed`, `${result.confirmed} classifications confirmées`));
      await again();
    }, "media-primary"));
    root.append(actions);
  }
  if (!data.rows.length) root.append(element("p", say("Every film has a rating.", "Tous les films ont une classification."), "media-ratings-done"));
  for (const row of data.rows) {
    const line = element("div", undefined, "media-unrated"), about = element("div"), pick = element("div");
    about.append(element("strong", row.title), element("small", [row.year, row.genre].filter(Boolean).join(" · ")));
    about.append(mediaRatingSuggestion(row, again) || element("small", say("No rating found.", "Aucune classification trouvée.")));
    pick.append(mediaRatingPicker(row, again));
    line.append(mediaArt(row), about, pick);
    root.append(line);
  }
}
$("media-ratings-entry").onclick = () => guard(mediaRatingsPage);
