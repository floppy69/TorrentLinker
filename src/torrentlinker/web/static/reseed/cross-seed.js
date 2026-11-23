"use strict";
// The Cross-seed tab (ADR-0024): what the automatic searches found, added or left for review.
let cross = { rows: [], counts: {}, indexers: [], settings: {} },
  crossFilter = "",
  crossQuery = "",
  crossSelected = "",
  crossLoaded = false,
  crossRefreshing = false;
const crossStates = {
  queued: ["En attente", "Waiting", ""],
  review: ["À vérifier", "To review", "warn"],
  verifying: ["Vérification", "Verifying", "blue"],
  added: ["Ajouté", "Added", "ok"],
  failed: ["Échec", "Failed", "bad"],
  orphan: ["Données disparues", "Data gone", "bad"],
};
const crossTiles = [
  ["", "Tous", "All"],
  ["review", "À vérifier", "To review"],
  ["added", "Ajoutés", "Added"],
  ["queued", "En attente", "Waiting"],
  ["failed", "Échecs", "Failed"],
  ["orphan", "Données disparues", "Data gone"],
];
const crossSteps = [
  ["Recherché", "Searched"],
  ["Comparé", "Compared"],
  ["Ajouté arrêté", "Added stopped"],
  ["Vérifié à 100 %", "Verified at 100 %"],
  ["En partage", "Seeding"],
];
// Searches that finished leave a row each; they are bookkeeping, not Cross-seeds.
const crossShown = () => cross.rows.filter((r) => r.state !== "searched");
const crossCount = (state) =>
  state ? cross.counts[state] || 0 : crossShown().length;
const crossPercent = (value) => Math.round((value ?? 0) * 100);
function crossAgo(seconds) {
  const age = Math.max(0, Date.now() / 1000 - seconds);
  if (age < 90) return t("à l’instant", "just now");
  if (age < 5400) return t(`il y a ${Math.round(age / 60)} min`, `${Math.round(age / 60)} min ago`);
  if (age < 129600) return t(`il y a ${Math.round(age / 3600)} h`, `${Math.round(age / 3600)} h ago`);
  return t(`il y a ${Math.round(age / 86400)} j`, `${Math.round(age / 86400)} d ago`);
}
// The engine's reasons are English; the common ones are said in the app's language.
function crossReason(row) {
  const reason = row.reason || "";
  const partial = /^Partial Match covering (\d+)%, under the (\d+)% threshold$/.exec(reason);
  if (partial)
    return t(
      `${partial[1]} % des fichiers présents, sous le seuil de ${partial[2]} %.`,
      reason,
    );
  const known = {
    "The Match is inside an archive": [
      "Les fichiers sont dans une archive : la décompresser d’abord.",
    ],
    "Automatic adds are off": ["Les ajouts automatiques sont désactivés : à vous de décider."],
    "Its data is missing from disk": [
      "Le torrent d’origine a disparu avec ses fichiers ; ce cross-seed n’a plus de données.",
    ],
    "No Match": ["Aucune correspondance."],
  }[reason];
  if (known) return t(known[0], reason);
  if (reason) return reason;
  if (row.state === "added")
    return row.full
      ? t("Correspondance complète, vérifiée à 100 %.", "Full Match, verified at 100 %.")
      : t(
          `${crossPercent(row.coverage)} % présents : les fichiers manquants sont ignorés, jamais téléchargés.`,
          `${crossPercent(row.coverage)} % present: missing files are skipped, never downloaded.`,
        );
  if (row.state === "verifying")
    return t(
      "Ajouté arrêté, vérification par le client.",
      "Added stopped, being verified by the client.",
    );
  if (row.state === "queued")
    return t("En attente de recherche sur cet indexeur.", "Waiting for a search on this Indexer.");
  return "";
}
function crossBadge(row) {
  const [fr, en, kind] = crossStates[row.state] || [row.state, row.state, ""];
  return `<span class="badge ${kind}">${t(fr, en)}</span>`;
}
const crossSize = (row) => (row.size ? bytes(row.size) : "");
function crossRoute(row) {
  const from = row.origin === "item" ? t("Bibliothèque", "Library") : t("Client", "Client");
  const kind = row.coverage == null ? "" : row.archive ? t("archive", "archive") : row.full ? t("complète", "full") : `${crossPercent(row.coverage)} %`;
  return `<small>${esc(from)} → <b>${esc(row.indexer)}</b>${crossSize(row) ? ` · ${crossSize(row)}` : ""}${kind ? ` · ${esc(kind)}` : ""}</small>`;
}
const crossTitle = (row) => row.title || row.source;
function crossVisible() {
  const needle = crossQuery.trim().toLocaleLowerCase();
  return crossShown().filter(
    (r) =>
      (!crossFilter || r.state === crossFilter) &&
      `${r.title} ${r.source} ${r.indexer}`.toLocaleLowerCase().includes(needle),
  );
}
function crossRunning() {
  const paused = cross.settings.paused,
    threshold = crossPercent(cross.settings.threshold);
  const waiting = crossCount("queued"),
    verifying = crossCount("verifying");
  return `<div class="running"><span><i class="dot" style="animation-play-state:${paused ? "paused" : "running"}"></i>${paused ? t("Cross-seed suspendu", "Cross-seed paused") : t("Cross-seed actif", "Cross-seed active")}</span><small>${waiting} ${t("en attente", "waiting")} · ${verifying} ${t("en vérification", "verifying")} · ${crossCount("review")} ${t("à vérifier", "to review")} · ${cross.settings.auto_add ? t(`ajout automatique : complètes et partielles ≥ ${threshold} %`, `automatic adds: full, and partial ≥ ${threshold} %`) : t("ajout automatique désactivé", "automatic adds off")}</small><small style="margin-left:auto">${(cross.indexers || []).length} ${t("indexeurs", "Indexers")} · ${t("tag", "tag")} « cross-seed »</small></div>`;
}
function crossRow(row) {
  const busy = row.state === "verifying";
  return `<div class="torrent ${crossSelected === row.id ? "selected" : ""}" data-cross="${esc(row.id)}" role="button" tabindex="0"><span></span><div class="cover" aria-hidden="true">${esc(row.indexer.slice(0, 2).toUpperCase())}</div><div><div class="title">${esc(crossTitle(row))}</div>${crossRoute(row)}</div><div>${crossBadge(row)}${busy ? `<div class="progress"><i style="width:62%"></i></div>` : ""}<small style="display:block;text-align:right">${crossAgo(row.updated)}</small></div></div>`;
}
function crossDecision(row) {
  if (row.state === "review")
    return `${
      row.archive
        ? `<button class="primary" data-cross-unpack="${esc(row.id)}">${t("Décompresser et remettre en seed", "Unpack and reseed")}</button>`
        : `<button class="primary" data-cross-do="accept" data-id="${esc(row.id)}">${row.missing.length ? t("Ajouter sans les fichiers manquants", "Add without the missing files") : t("Ajouter", "Add")}</button>`
    }<button data-cross-do="reject" data-id="${esc(row.id)}">${t("Écarter", "Dismiss")}</button>`;
  if (row.state === "failed")
    return `<button data-cross-do="retry" data-id="${esc(row.id)}">${t("Réessayer", "Retry")}</button>`;
  if (row.state === "orphan")
    return `<button data-cross-do="remove" data-id="${esc(row.id)}">${t("Retirer du client (garder les données)", "Remove from the client (keep the data)")}</button>`;
  return "";
}
function crossCoverage(row) {
  if (row.coverage == null) return "";
  const threshold = crossPercent(cross.settings.threshold);
  return `<div class="coverage" title="${t("Seuil", "Threshold")} ${threshold} %"><i style="width:${crossPercent(row.coverage)}%"></i><b style="left:${threshold}%"></b></div><small>${crossPercent(row.coverage)} % ${t("présents · seuil d’ajout automatique", "present · automatic add threshold")} ${threshold} %</small>`;
}
function crossInspector() {
  const list = crossVisible();
  const row = list.find((r) => r.id === crossSelected) || list[0];
  if (!row) return "";
  const layout = snapshot.setup?.reseed_effective_layout === "client"
    ? t("renommage dans le client", "renames inside the client")
    : t("liens vers les fichiers d’origine", "links to the original files");
  const at = row.steps.findIndex((s) => !s.done);
  const current = at < 0 ? row.steps.length : at;
  return `<aside class="panel inspector ${drawer ? "open" : ""}"><button class="close" data-command="close-inspector">${t("Fermer")}</button><div class="eyebrow">${t("LE CROSS-SEED SÉLECTIONNÉ", "THE SELECTED CROSS-SEED")}</div><div class="detail-head"><h2>${esc(crossTitle(row))}</h2>${crossRoute(row)}</div>${crossBadge(row)}
<div class="callout"><b>${row.state === "review" ? t("Votre décision", "Your decision") : row.state === "added" ? t("Ajouté automatiquement", "Added automatically") : t(...crossStates[row.state].slice(0, 2))}</b><p class="muted">${esc(crossReason(row))}</p>${crossCoverage(row)}${row.missing.length ? `<div class="files">${row.missing.map((m) => `<div class="miss"><span>${esc(m)}</span><span>${t("absent · ignoré", "missing · skipped")}</span></div>`).join("")}</div>` : ""}${crossDecision(row)}</div>
<div class="section"><b>${t("Dans le client", "In the client")}</b><p class="muted" style="margin-top:6px">${t(`Tags « cross-seed » et « ${row.indexer} » · même catégorie et même dossier que l’original · disposition : ${layout}.`, `Tags “cross-seed” and “${row.indexer}” · same category and folder as the original · layout: ${layout}.`)}</p></div>
<div class="section"><b>${t("Son parcours", "Its steps")}</b><ol class="steps">${row.steps.map((step, i) => `<li class="${i === current ? "current" : ""}">${i < current ? "✓" : i === current ? "●" : "○"}　${t(...crossSteps[i])}${i === 0 ? ` ${esc(row.indexer)}` : ""}</li>`).join("")}</ol></div></aside>`;
}
function crossView() {
  const list = crossVisible();
  const tiles = crossTiles
    .map(
      ([key, fr, en]) =>
        `<button class="stage ${crossFilter === key ? "on" : ""}" data-cross-filter="${key}"><b>${crossCount(key)}</b>${t(fr, en)}</button>`,
    )
    .join("");
  return `${crossRunning()}<div class="stages">${tiles}</div><div class="workspace"><section class="panel"><div class="tools"><input id="cross-search" placeholder="${t("Rechercher un torrent…", "Search a torrent…")}" aria-label="${t("Rechercher")}" value="${esc(crossQuery)}"></div>${list.map(crossRow).join("") || `<div class="empty">${crossLoaded ? t("Rien dans cet état.", "Nothing in this state.") : t("Chargement…", "Loading…")}</div>`}<div class="foot">${list.length} ${t("affichés", "shown")} · ${crossCount("added")} ${t("en partage grâce au cross-seed", "seeding thanks to Cross-seed")}</div></section>${crossInspector()}</div>`;
}
function renderCross() {
  const focus = document.activeElement?.id === "cross-search";
  const cursor = focus ? document.activeElement.selectionStart : 0;
  const inspectorScroll = document.querySelector(".inspector")?.scrollTop || 0;
  $("content").innerHTML = crossView();
  if (focus) {
    $("cross-search").focus({ preventScroll: true });
    $("cross-search").setSelectionRange(cursor, cursor);
  }
  if (document.querySelector(".inspector"))
    document.querySelector(".inspector").scrollTop = inspectorScroll;
}
async function refreshCross() {
  if (!active || tab !== "cross" || crossRefreshing) return;
  crossRefreshing = true;
  const g = generation;
  try {
    const value = await api("cross-seed");
    if (g !== generation) return;
    crossLoaded = true;
    if (JSON.stringify(cross) === JSON.stringify(value) && tab === "cross") return;
    cross = value;
    if (!crossShown().some((r) => r.id === crossSelected)) crossSelected = crossShown()[0]?.id || "";
    if (tab === "cross") render();
  } catch (error) {
    $("error").textContent = error.message;
  } finally {
    crossRefreshing = false;
  }
}
// An archive Match is Reseeded through the Reseed board's own unpack flow, for its item.
async function crossUnpack(id) {
  const row = cross.rows.find((r) => r.id === id);
  const item = snapshot.rows.find((r) => r.path === row?.item_path);
  if (!item) {
    $("error").textContent = t(
      "Cet élément n’est plus dans la bibliothèque : lancez une analyse des dossiers.",
      "This item is no longer in the Library: scan the folders.",
    );
    return;
  }
  tab = "reseed";
  filter = "";
  query = "";
  localFolder = "";
  localState = "";
  selected = item.path;
  drawer = true;
  $("error").textContent = "";
  await api("tab", { tab });
  render();
}
document.addEventListener("click", (e) => {
  if (tab !== "cross") return;
  const b = e.target.closest("button");
  if (b && "crossFilter" in b.dataset) {
    crossFilter = b.dataset.crossFilter;
    render();
  } else if (b?.dataset.crossUnpack) crossUnpack(b.dataset.crossUnpack).catch(() => {});
  else if (b?.dataset.crossDo) {
    const id = b.dataset.id;
    TLToast.press(b, () =>
      perform(`cross-seed-${b.dataset.crossDo}`, { id }).then(refreshCross),
    );
  } else if (!b && e.target.closest("[data-cross]")) {
    crossSelected = e.target.closest("[data-cross]").dataset.cross;
    drawer = true;
    render();
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id !== "cross-search") return;
  crossQuery = e.target.value;
  render();
});
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-cross]")) {
    e.preventDefault();
    crossSelected = e.target.dataset.cross;
    drawer = true;
    render();
  }
});
setInterval(refreshCross, 1500);
