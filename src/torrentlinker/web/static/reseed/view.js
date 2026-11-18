"use strict";
const t = (...args) => window.TLPanel.t(...args);
// Shared owner workspace. All data and mutations come from the host bridge.
const labels = {
  get find() {
    return t("À retrouver");
  },
  get candidates() {
    return t("Comparer");
  },
  get links() {
    return t("Préparer les noms");
  },
  get verify() {
    return t("Vérifier");
  },
  get incomplete() {
    return t("Compléter");
  },
  get seeding() {
    return t("En partage");
  },
};
let snapshot = {
    rows: [],
    setup: { folders: [], clients: [] },
    progress: {},
    running: false,
  },
  tab = "reseed",
  filter = "",
  query = "",
  selected = "",
  checked = new Set(),
  limit = 100,
  drawer = false,
  active = false,
  generation = 0,
  busy = false;
let environment = { mode: "web", language: "fr", theme: "dark" },
  browseTarget = "",
  browseForm = null;
const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const bytes = (n) =>
  n >= 1073741824
    ? (n / 1073741824).toFixed(1) + t(" Go")
    : n >= 1048576
      ? (n / 1048576).toFixed(1) + t(" Mo")
      : (n / 1024).toFixed(0) + t(" Ko");
const api = async (action, body = {}) =>
  (await window.reseedTransport)(action, {
    ...body,
    _client: environment.client,
  });
async function refresh() {
  if (!active || busy) return;
  const g = generation;
  try {
    const value = await api("state");
    if (g !== generation) return;
    if (JSON.stringify(snapshot) === JSON.stringify(value)) return;
    snapshot = value;
    $("error").textContent = value.error || "";
    if (!snapshot.rows.some((r) => r.path === selected))
      selected = snapshot.rows[0]?.path || "";
    render();
  } catch (e) {
    $("error").textContent = e.message;
  }
}
async function perform(action, body = {}) {
  busy = true;
  try {
    const value = await api(action, body);
    $("error").textContent = "";
    $("dialog-error").textContent = "";
    return value;
  } catch (e) {
    $("error").textContent = e.message;
    $("dialog-error").textContent = e.message;
    throw e;
  } finally {
    busy = false;
  }
}
const visible = () =>
  snapshot.rows.filter(
    (r) =>
      (!filter || r.stage === filter) &&
      r.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
function stateFor(r) {
  const p = snapshot.progress?.active?.[r.path];
  if (snapshot.progress?.paused_paths?.includes(r.path)) return t("En pause");
  if (r.error) return t("À examiner");
  if (p)
    return (
      (labels[r.stage] || p.phase) +
      (p.fraction != null
        ? " · " + Math.round(p.fraction * 100) + " %"
        : t(" · en cours"))
    );
  return r.stage === "seeding"
    ? t("En partage")
    : t("En attente · ") + labels[r.stage];
}
function render() {
  const focusSearch = document.activeElement?.id === "search";
  const cursor = focusSearch ? document.activeElement.selectionStart : 0;
  const scroll = window.scrollY;
  const oldStages = new Map(
    [...document.querySelectorAll("[data-item]")].map((n) => [
      n.dataset.item,
      n.dataset.stage,
    ]),
  );
  document.body.dataset.mode = environment.mode;
  document.documentElement.dataset.theme = environment.theme;
  document
    .querySelectorAll("[data-tab]")
    .forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  let folders = snapshot.setup.folders || [];
  if (tab === "folders") {
    $("content").innerHTML = `<div class="row between"><h2>${t("Dossiers de bibliothèque")}</h2><button data-command="add-folder">${t("+ Ajouter un dossier")}</button></div><p class="muted">${t("Les emplacements analysés par le parcours.")}</p><div class="panel folder-list">${folders.map(f => `<div class="folder-entry"><div><b>${esc(f.local)}</b><small>${kindName(f.kind)} · ${f.depth == null ? t("Automatique") : t("Profondeur ")+f.depth}</small></div><span class="badge">${(snapshot.folder_errors || []).some(path=>path===f.local || path.startsWith(f.local+"/")) ? t("Analyse incomplète · éléments précédents conservés") : t("Analyser pour vérifier l’accès aux fichiers")}</span><button data-edit-folder="${esc(f.local)}">${t("Modifier")}</button><button data-remove-folder="${esc(f.local)}">${t("Retirer")}</button></div>`).join("") || `<p class="muted">${t("Aucun dossier configuré.")}</p>`}<p><button data-command="disk">${t("Analyser maintenant")}</button></p></div>`;
    window.scrollTo(0, scroll);
    return;
  }
  if (tab === "activity") {
    const events = [...snapshot.rows.flatMap(r => (r.events || []).map(e => ({...e, name:r.name}))), ...(snapshot.activity || [])].sort((a,b) => b.at-a.at);
    $("content").innerHTML = `<h2>${t("Activité du parcours")}</h2><p class="muted">${t("Chaque élément conserve ses propres étapes.")}</p><div class="panel" style="margin-top:20px">${events.map(e => `<div class="tools"><small>${new Date(e.at*1000).toLocaleString(environment.language)}</small><b>${esc(e.kind ? t(activityKinds[e.kind] || e.kind) : e.name)}</b><span>${esc(e.message || (e.status ? t(activityStates[e.status] || e.status) : "") || ({prepared:t("Liens prêts"),verified:t("Contenu vérifié"),checking:t("Vérification du client")}[e.phase] || labels[e.phase] || e.phase))}</span></div>`).join("") || `<div class="empty">${t("Les prochaines transitions apparaîtront ici.")}</div>`}</div>`;
    window.scrollTo(0, scroll);
    return;
  }
  const rows = visible(),
    progress = snapshot.progress || {},
    running = snapshot.running,
    current = Object.values(progress.active || {});
  $("content").innerHTML =
    `<div class="intro row between"><div><h2>${t("Chaque fichier avance à son rythme.")}</h2><p class="muted">${t("Retrouvez, vérifiez et partagez. Intervenez seulement quand c’est nécessaire.")}</p></div><button class="primary" data-command="run">${running ? (snapshot.paused ? t("Reprendre le parcours") : t("Suspendre le parcours")) : t("Tout enchaîner")}</button></div><div class="guided"><button data-command="settings"><strong>01</strong><span>${t("Réglages")}<small>${esc(snapshot.setup.name || t("Client à configurer"))} · ${snapshot.setup.reseed_link_root ? t("Dossier de liens configuré") : t("Dossier de liens à choisir")}</small></span></button><button data-command="disk"><strong>02</strong><span>${t("Disque")}<small>${folders.length}${t(" dossiers · ")}${snapshot.scanning ? t("Analyse en cours…") : t("parcourir et analyser")}</small></span></button><span class="hint">${t("Les éléments avancent indépendamment. Les décisions attendues ne bloquent pas les autres.")}</span></div><div class="stages"><button class="stage ${filter ? "" : "on"}" data-filter=""><b>${snapshot.rows.length}</b>${t("Tous les éléments")}<br><small>${t("Vue d’ensemble")}</small></button>${Object.entries(
      labels,
    )
      .map(
        ([key, label]) =>
          `<button class="stage ${filter === key ? "on" : ""}" data-filter="${key}"><b>${snapshot.rows.filter((r) => r.stage === key).length}</b>${label}<br><small>${snapshot.rows.filter((r) => r.stage === key && progress.active?.[r.path]).length}${t(" en cours")}</small></button>`,
      )
      .join(
        "",
      )}</div><div class="running"><span><i class="dot" style="animation-play-state:${running && !snapshot.paused ? "running" : "paused"}"></i>${running ? (snapshot.paused ? t("Parcours suspendu") : t("Parcours actif")) : t("Prêt à commencer")}</span><small>${current.length}${t(" opérations simultanées · ")}${snapshot.rows.filter((r) => r.error).length}${t(" décisions attendues")}</small><small style="margin-left:auto">${t("Vérification : 1 à la fois · Recherche : 2 maximum")}</small>${running ? `<button data-command="stop">${t("Arrêter")}</button>` : ""}</div><div class="workspace"><section class="panel"><div class="tools"><input id="search" placeholder="${t("Rechercher dans mes fichiers…")}" aria-label="${t("Rechercher")}" value="${esc(query)}"><button data-command="select">${checked.size ? checked.size + t(" sélectionnés") : t("Sélectionner la liste")}</button><button data-command="batch" ${checked.size ? "" : "disabled"}>${t("Enchaîner la sélection")}</button></div>${
      rows
        .slice(0, limit)
        .map((r) => {
          const p = progress.active?.[r.path];
          return `<div class="torrent ${selected === r.path ? "selected" : ""}" data-item="${esc(r.path)}" data-stage="${r.stage}" role="button" tabindex="0"><input type="checkbox" data-check="${esc(r.path)}" aria-label="${t("Sélectionner ")}${esc(r.name)}" ${checked.has(r.path) ? "checked" : ""}><div class="cover" aria-hidden="true">${esc(r.name.slice(0, 2).toUpperCase())}</div><div><div class="title">${esc(r.name)}</div><small>${bytes(r.size)} · ${esc(r.folder || "")}</small></div><div><span class="badge ${r.error ? "warn" : p ? "blue" : ""}">${esc(stateFor(r))}</span>${p ? `<div class="progress"><i style="width:${p.fraction == null ? 35 : Math.round(p.fraction * 100)}%"></i></div>` : ""}</div></div>`;
        })
        .join("") ||
      `<div class="empty">${t("Aucun élément ici. Ajoutez un dossier ou changez le filtre.")}</div>`
    }<div id="more" class="foot">${Math.min(limit, rows.length)} / ${rows.length}${t(" éléments")}</div></section>${inspector()}</div>`;
  if (focusSearch) {
    $("search").focus({ preventScroll: true });
    $("search").setSelectionRange(cursor, cursor);
  }
  window.scrollTo(0, scroll);
  for (const node of document.querySelectorAll("[data-item]")) {
    if (
      oldStages.has(node.dataset.item) &&
      oldStages.get(node.dataset.item) !== node.dataset.stage
    )
      node.classList.add("pulse");
  }
  observer.disconnect();
  if (rows.length > limit) observer.observe($("more"));
}
const observer = new IntersectionObserver(
  (entries) => {
    if (entries.some((e) => e.isIntersecting)) {
      limit += 100;
      render();
    }
  },
  { rootMargin: "250px" },
);
function inspector() {
  const r = snapshot.rows.find((r) => r.path === selected);
  if (!r) return "";
  const steps = Object.keys(labels),
    index = steps.indexOf(r.stage),
    paused = snapshot.progress?.paused_paths?.includes(r.path);
  return `<aside class="panel inspector ${drawer ? "open" : ""}"><button class="close" data-command="close-inspector">${t("Fermer")}</button><div class="eyebrow">${t("L’ÉLÉMENT SÉLECTIONNÉ")}</div><div class="detail-head"><h2>${esc(r.name)}</h2><small>${bytes(r.size)} · ${esc(r.path)}</small></div><span class="badge ${r.error ? "warn" : ""}">${esc(stateFor(r))}</span><div class="callout">${r.error ? `<p class="error">${esc(r.error)}</p>` : ""}<p class="muted">${r.stage === "verify" ? t("Un seul hash à la fois protège le disque. Les recherches continuent.") : t("Les fichiers originaux conservent leurs noms.")}</p><small>${t("La pause prend effet à la fin de l’opération en cours.")}</small>${snapshot.running ? `<button data-command="pause-item">${paused ? t("Reprendre cet élément") : t("Suspendre cet élément")}</button>` : r.stage !== "seeding" ? `<button data-command="run-item">${t("Continuer cet élément")}</button>` : ""}<button data-command="review">${t("Examiner les fichiers et les réparations")}</button></div>${(
    r.candidates || []
  )
    .slice(0, 20)
    .map(
      (c) =>
        `<div class="candidate"><b>${esc(c.title)}</b><p class="muted">${esc(c.match)} · ${bytes(c.size || 0)}</p>${(c.files || []).map((f) => `<pre>${esc(f.local || t("Manquant"))}<br>↳ ${esc(f.torrent)}</pre>`).join("")}${c.match === "full" && !c.archive ? `<button ${snapshot.progress?.active?.[r.path] ? "disabled" : ""} data-candidate="${esc(c.key)}">${t("Choisir ce candidat")}</button>` : ""}</div>`,
    )
    .join(
      "",
    )}<div class="section"><b>${t("Son parcours")}</b><ol class="steps">${steps.map((key, i) => `<li class="${index === i ? "current" : ""}">${i < index ? "✓" : i === index ? "●" : "○"}　${labels[key]}${key === "links" ? "<small> · Symlink</small>" : ""}</li>`).join("")}</ol></div>${r.destination ? `<div class="section"><b>${t("Dossier de liens à conserver")}</b><pre>${esc(r.destination)}</pre>${(r.files || []).map((f) => `<pre>${esc(f.source)}<br>↳ ${esc(f.name)}</pre>`).join("")}</div>` : ""}<div class="section"><b>${t("Historique de cet élément")}</b><div class="events">${
    (r.events || [])
      .slice()
      .reverse()
      .map(
        (e) =>
          `<p><small>${new Date(e.at * 1000).toLocaleString()}</small><br>${esc({ prepared: t("Liens prêts"), verified: t("Contenu vérifié"), checking: t("Vérification du client") }[e.phase] || labels[e.phase] || e.phase)}</p>`,
      )
      .join("") || `<p>${t("Aucune opération enregistrée.")}</p>`
  }</div></div></aside>`;
}
let dialogRenderer = null;
function dialog(content) {
  dialogRenderer = typeof content === "function" ? content : () => content;
  const html = dialogRenderer();
  $("dialog-error").textContent = "";
  $("dialog-body").innerHTML = html;
  $("dialog").classList.toggle("folder-dialog", !!$("folder-form"));
  $("dialog").querySelector(":scope > [data-command=close]").hidden = !!$("folder-form");
  if (!$("dialog").open) $("dialog").showModal();
}
function settings() {
  dialog(
    () =>
      `<div class="eyebrow">${t("01 · RÉGLAGES")}</div><h2>${t("Réglages du parcours")}</h2><p>${t("Client cible : ")}${esc(snapshot.setup.name)}</p><button data-command="add-client">${t("+ Ajouter un client")}</button><button data-command="client-settings">${t("Paramètres du client")}</button><form id="root-form"><label>${t("Dossier de liens à conserver")}<div class="row"><input name="path" required value="${esc(snapshot.setup.reseed_link_root)}" style="min-width:0;width:100%"><button type="button" data-command="browse-root">${t("Parcourir…")}</button></div></label><p class="muted">${t("Hors bibliothèque, accessible au client. Les fichiers originaux gardent leurs noms.")}</p><button class="primary">${t("Enregistrer")}</button></form><button data-command="disk">${t("Continuer vers Disque →")}</button>`,
  );
}
function disk() {
  dialog(
    () =>
      `<div class="eyebrow">${t("02 · DISQUE")}</div><h2>${t("Parcourir mes dossiers")}</h2><p class="muted">${environment.mode === "desktop" ? t("Dossiers sur cet ordinateur") : t("Dossiers accessibles au serveur TorrentLinker")}</p>${(snapshot.setup.folders || []).map((f) => `<label><input type="checkbox" data-scan-folder="${esc(f.local)}" checked> ${esc(f.local)}</label>`).join("")}<button data-command="add-folder">${t("+ Ajouter un dossier")}</button><p><button class="primary" data-command="scan" ${snapshot.scanning ? "disabled" : ""}>${snapshot.scanning ? t("Analyse en cours…") : t("Parcourir mon disque maintenant")}</button></p>`,
  );
}
const activityKinds = {scan:"Analyse des dossiers",check:"Recherche de candidats","check-all":"Recherche de candidats",reseed:"Remise en seed","reseed-all":"Remise en seed","reseed-workspace":"Remise en seed","search-library":"Recherche de candidats","library-review":"Examen des candidats","library-reject":"Candidat écarté","check-candidate":"Vérification du candidat","preview-unpack":"Aperçu de l’extraction","unpack-reseed":"Extraction et remise en seed","library-evidence":"Éléments de preuve","import-provenance":"Import de provenance","find-compatible":"Recherche de torrents compatibles","combine-library":"Regroupement des éléments","diagnose-repair":"Diagnostic de réparation","prepare-repair":"Préparation de la réparation","refresh-repair":"Actualisation de la réparation","start-repair":"Réparation"};
const activityStates = {queued:"En attente",running:"En cours",completed:"Terminé",partial:"Partiel",failed:"Échec",cancelled:"Annulé",interrupted:"Interrompu"};
const kinds = {movie:"Films",series:"Séries",music:"Audio",ebook:"Livres",game:"Jeux vidéo","3d-model":"Impression 3D",other:"Autre",adult:"Adulte"};
const kindName = kind => t(kinds[kind] || kind);
let previewTimer, previewSequence = 0, previewRunning = false;
function folderForm(folder = null) {
  browseForm = null;
  dialog(() => `<div class="eyebrow">${t("DOSSIER DE BIBLIOTHÈQUE")}</div><h2>${t(folder ? "Modifier le dossier" : "Ajouter à la bibliothèque")}</h2><form id="folder-form"><input type="hidden" name="original_local" value="${esc(folder?.local || "")}"><label for="folder-local">${t("Chemin accessible à TorrentLinker")}</label><div class="row"><input id="folder-local" name="local" required value="${esc(folder?.local || "")}"><button type="button" data-command="browse-folder">${t("Parcourir…")}</button></div><small>${environment.mode === "desktop" ? t("Sur cet ordinateur") : t("Sur le serveur TorrentLinker")}</small><div class="folder-grid"><div><label for="folder-kind">${t("Contenu")}</label><select id="folder-kind" name="kind">${Object.keys(kinds).filter(k => k !== "adult" || snapshot.setup.adult_content || folder?.kind === "adult").map(k=>`<option value="${k}" ${k === (folder?.kind || "movie") ? "selected" : ""}>${kindName(k)}</option>`).join("")}</select></div><div><label for="folder-depth">${t("Regroupement des éléments")}</label><select id="folder-depth" name="depth"><option value="auto">${t("Automatique")}</option>${Array.from({length:11},(_,i)=>`<option value="${i}" ${folder?.depth === i ? "selected" : ""}>${t("Profondeur ")}${i}</option>`).join("")}</select></div></div><div class="callout" aria-live="polite"><div class="eyebrow">${t("APERÇU DES ÉLÉMENTS LOCAUX")}</div><div id="folder-live"></div></div><label><input type="checkbox" name="scan" checked> ${t("Analyser après l’enregistrement")}</label><div class="folder-actions"><button type="button" data-command="close">${t("Annuler")}</button><button class="primary">${t(folder ? "Enregistrer" : "Ajouter le dossier")}</button></div></form>`);
  schedulePreview();
}
function schedulePreview() {
  previewSequence++;
  clearTimeout(previewTimer);
  if (!$("folder-live")) return;
  $("folder-live").textContent = t("Recherche des éléments locaux…");
  previewTimer = setTimeout(loadFolderPreview, 350);
}
async function loadFolderPreview() {
  const form = $("folder-form");
  if (!form || !$("dialog").open) return;
  if (previewRunning) { previewTimer = setTimeout(loadFolderPreview, 350); return; }
  const sequence = previewSequence, clientGeneration = generation;
  const body = Object.fromEntries(new FormData(form));
  if (!body.local.trim()) { $("folder-live").textContent=t("Choisissez un dossier pour voir comment ses éléments seront regroupés."); return; }
  body.depth = body.depth === "auto" ? null : Number(body.depth);
  previewRunning = true;
  try {
    const result = await api("preview-folder", body);
    if (sequence !== previewSequence || clientGeneration !== generation || !$("folder-live")) return;
    $("folder-live").innerHTML = `<p><b>${result.count} ${t("éléments locaux")}${result.episodes ? ` · ${result.episodes} ${t("épisodes inclus")}` : ""}</b></p><p class="muted">${body.depth == null ? t("Les dossiers contenant une release restent entiers. Les dossiers de genres et de collections sont parcourus.") : t("Chaque entrée à la profondeur choisie forme un élément local. Les fichiers rencontrés avant comptent aussi.")}</p><ul class="sample-list">${result.items.map(item=>`<li>${esc(item.name)}${item.within ? `<small>${t("Épisode inclus dans le pack")}</small>` : ""}</li>`).join("")}</ul><p><small>${t("L’analyse affinera ces résultats avec les torrents déjà en partage.")}</small></p>${result.errors.map(error=>`<p class="error">${esc(error)}</p>`).join("")}`;
  } catch(error) {
    if (sequence === previewSequence && clientGeneration === generation && $("folder-live")) $("folder-live").textContent=error.message;
  } finally { previewRunning=false; }
}
function removeFolder(path) {
  dialog(() => `<h2>${t("Retirer ce dossier ?")}</h2><p>${esc(path)}</p><p class="muted">${t("Il ne sera plus analysé par la bibliothèque. Tous les fichiers restent sur le disque.")}</p><div class="folder-actions"><button data-command="close">${t("Annuler")}</button><button class="primary" data-confirm-remove="${esc(path)}">${t("Retirer de la bibliothèque")}</button></div>`);
}
function clientForm() {
  dialog(
    () =>
      `<h2>${t("Connecter un client torrent")}</h2><form id="client-form"><label>${t("Nom")}<input name="name" required></label><label>Type<select name="client"><option value="qbittorrent">qBittorrent</option><option value="transmission">Transmission</option><option value="rtorrent">rTorrent</option><option value="deluge">Deluge</option><option value="utorrent">µTorrent</option><option value="bittorrent">BitTorrent</option></select></label><label>${t("Adresse")}<input name="host" required placeholder="http://localhost:8080"></label><label>${t("Utilisateur")}<input name="username" autocomplete="off"></label><label>${t("Mot de passe")}<input name="password" type="password" autocomplete="new-password"></label><button class="primary">${t("Tester et ajouter")}</button></form>`,
  );
}
async function browse(target, path = "") {
  browseTarget = target;
  const result = await perform("browse", { path });
  if (result.selected !== undefined) {
    if (result.selected) { document.querySelector(target).value = result.selected; schedulePreview(); }
    return;
  }
  if (!browseForm)
    browseForm = {
      renderer: dialogRenderer,
      values: [...$("dialog-body").querySelectorAll("input,select")].map(
        (n) => [n.name, n.value, n.checked],
      ),
    };
  dialog(
    () =>
      `<h2>${t("Dossiers du serveur TorrentLinker")}</h2><p>${esc(result.path || t("Racines montées"))}</p>${result.parent ? `<button data-browse="${esc(result.parent)}">↑ Parent</button>` : ""}${(result.folders || result.children || []).map((f) => `<button data-browse="${esc(typeof f === "string" ? f : f.path)}">${esc(typeof f === "string" ? f : f.name)}</button>`).join("")}${result.path ? `<button id="choose-folder" class="primary">${t("Choisir ce dossier")}</button>` : ""}`,
  );
  const choose = $("choose-folder");
  if (choose) choose.onclick = () => restoreBrowse(result.path);
}
function restoreBrowse(path) {
  const saved = browseForm;
  if (!saved) return;
  dialog(saved.renderer);
  for (const [name, value, checked] of saved.values) {
    const node = [...$("dialog-body").querySelectorAll("input,select")].find(n=>n.name===name);
    if (node) { node.value=value; node.checked=checked; }
  }
  if (path) document.querySelector(browseTarget).value = path;
  browseForm = null;
  schedulePreview();
}
async function start(paths, key = "") {
  if (!paths.length) return;
  if (snapshot.running) {
    await perform("enqueue", { paths, key });
    return;
  }
  if (!snapshot.setup.reseed_link_root) {
    settings();
    return;
  }
  if (
    !confirm(
      `${paths.length}${t(" élément(s). Créer les liens, vérifier le contenu puis partager ? Les fichiers originaux restent inchangés.")}`,
    )
  )
    return;
  await perform("run", { paths, key });
  await refresh();
}
document.addEventListener("click", (e) => {
  handleClick(e).catch(() => {});
});
async function handleClick(e) {
  const b = e.target.closest("button");
  if (b?.dataset.tab) {
    tab = b.dataset.tab;
    await api("tab", {tab});
    render();
    return;
  }
  if (b && "filter" in b.dataset) {
    filter = b.dataset.filter;
    limit = 100;
    render();
    return;
  }
  if (e.target.dataset.check) {
    e.target.checked
      ? checked.add(e.target.dataset.check)
      : checked.delete(e.target.dataset.check);
    render();
    return;
  }
  const row = e.target.closest("[data-item]");
  if (row) {
    selected = row.dataset.item;
    drawer = true;
    render();
    return;
  }
  if (b?.dataset.candidate) {
    await start([selected], b.dataset.candidate);
    return;
  }
  if (b && "browse" in b.dataset) {
    await browse(browseTarget, b.dataset.browse);
    return;
  }
  if (b?.dataset.editFolder) { folderForm(snapshot.setup.folders.find(f=>f.local===b.dataset.editFolder)); return; }
  if (b?.dataset.removeFolder) { removeFolder(b.dataset.removeFolder); return; }
  if (b?.dataset.confirmRemove) { await perform("remove-folder", {local:b.dataset.confirmRemove}); $("dialog").close(); await refresh(); return; }
  const cmd = b?.dataset.command;
  if (!cmd) return;
  switch (cmd) {
    case "close":
      if (browseForm) { restoreBrowse(); break; }
      previewSequence++;
      $("dialog").close();
      break;
    case "close-inspector":
      drawer = false;
      render();
      break;
    case "settings":
      settings();
      break;
    case "manage-folders":
      await perform("manage-folders");
      break;
    case "disk":
      disk();
      break;
    case "add-folder":
      folderForm();
      break;
    case "add-client":
      clientForm();
      break;
    case "client-settings":
      $("dialog").close();
      await perform("settings");
      break;
    case "browse-folder":
      browseForm = null;
      schedulePreview();
      await browse("#folder-form [name=local]");
      break;
    case "browse-root":
      browseForm = null;
      schedulePreview();
      await browse("#root-form [name=path]");
      break;
    case "scan":
      {
        const folders = [
          ...document.querySelectorAll("[data-scan-folder]:checked"),
        ].map((n) => n.dataset.scanFolder);
        if (!folders.length)
          throw new Error(t("Choisissez au moins un dossier."));
        await perform("scan", { folders });
      }
      $("dialog").close();
      break;
    case "run":
      if (snapshot.running)
        await perform("pause", { paused: !snapshot.paused });
      else
        await start(
          visible()
            .filter((r) => r.stage !== "seeding")
            .map((r) => r.path),
        );
      break;
    case "run-item":
      await start([selected]);
      break;
    case "batch":
      await start([...checked]);
      break;
    case "select":
      visible().forEach((r) => checked.add(r.path));
      render();
      break;
    case "pause-item":
      await perform("pause-item", {
        paths: [selected],
        paused: !snapshot.progress?.paused_paths?.includes(selected),
      });
      break;
    case "stop":
      await perform("stop");
      break;
    case "review":
      await perform("review", { path: selected });
      break;
  }
  await refresh();
}
document.addEventListener("input", (e) => {
  if (e.target.closest("#folder-form")) schedulePreview();
  if (e.target.id === "search") {
    query = e.target.value;
    limit = 100;
    const pos = e.target.selectionStart;
    e.target.blur();
    render();
    $("search").focus();
    $("search").setSelectionRange(pos, pos);
  }
});
document.addEventListener("submit", (e) => {
  e.preventDefault();
  submit(e).catch(() => {});
});
async function submit(e) {
  const body = Object.fromEntries(new FormData(e.target));
  if (e.target.id === "folder-form") {
    const scan = !!body.scan;
    delete body.scan;
    const saved = await perform("add-folder", { ...body, depth: body.depth === "auto" ? null : Number(body.depth) });
    if (scan) await perform("scan", {folders:[saved.local]});
  } else if (e.target.id === "client-form") await perform("add-client", body);
  else if (e.target.id === "root-form") await perform("save-root", body);
  $("dialog").close();
  await refresh();
}
window.addEventListener("reseed-environment", (e) => {
  const value = e.detail;
  const languageChanged = value.language !== environment.language;
  const openFolder = value.folder_dialog_request && value.folder_dialog_request !== environment.folder_dialog_request;
  if (value.clear || value.client !== environment.client) {
    generation++;
    previewSequence++;
    browseForm = null;
    snapshot = { rows: [], setup: { folders: [] }, progress: {} };
    selected = "";
    checked.clear();
    $("dialog").close();
  }
  if (value.tab && value.tab !== environment.tab) tab = value.tab;
  environment = value;
  window.TLPanel.setLanguage(value.language);
  if (languageChanged && $("dialog").open && dialogRenderer)
    window.TLPanel.refreshForm($("dialog-body"), () => dialog(dialogRenderer));
  document.title = t("Bibliothèque");
  for (const [key, label] of Object.entries({
    reseed: "Remise en seed",
    folders: "Dossiers",
    activity: "Activité",
  }))
    document.querySelector(`[data-tab="${key}"]`).textContent = t(label);
  document.querySelector('[data-command="close"]').textContent = t("Fermer");
  active = !!value.active;
  render();
  if (languageChanged && $("folder-form")) schedulePreview();
  if (openFolder) folderForm();
  if (active) refresh();
});
window.reseedTransport.then(() => window.reseedReady());
setInterval(refresh, 1200);

document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-item]")) {
    e.preventDefault();
    selected = e.target.dataset.item;
    drawer = true;
    render();
  }
});
