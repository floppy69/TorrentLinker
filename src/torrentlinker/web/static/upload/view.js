const t = (...args) => window.TLPanel.t(...args);
const $ = (id) => document.getElementById(id),
  esc = (x) =>
    String(x ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const stages = () => [
  "Sources",
  t("Vérifier l’existant"),
  t("Préparer"),
  t("Présentation"),
  t("Révision"),
  t("Envoyer & suivre"),
];
let mode = "web",
  tab = "sources",
  filter = "all",
  query = "",
  selected = 1,
  step = 0,
  drawer = false,
  animating = false,
  items = [],
  nextId = 10;
const reasons = () => ({
  none: [t("Aucun candidat trouvé"), "ok"],
  rejected: [t("Candidats incompatibles"), "blue"],
  unchecked: [t("Recherche incomplète"), "warn"],
  manual: [t("Ajout manuel"), ""],
});
const current = () => items.find((i) => i.id === selected);
function visible() {
  return items.filter(
    (i) =>
      (tab === "sources"
        ? !i.draft
        : tab === "drafts"
          ? i.draft && !i.tracking
          : i.tracking) &&
      (!query || i.name.toLowerCase().includes(query.toLowerCase())) &&
      (filter === "all" || i.reason === filter),
  );
}
function toast(s) {
  $("toast").textContent = s;
  $("toast").hidden = false;
  setTimeout(() => ($("toast").hidden = true), 4200);
}
let dialogRenderer = null;
function dialog(content) {
  dialogRenderer = typeof content === "function" ? content : () => content;
  const html = dialogRenderer();
  $("dialog-content").innerHTML =
    html +
    `<div class="dialogactions"><button data-action="close">${t("Fermer")}</button></div>`;
  if (!$("dialog").open) $("dialog").showModal();
}
function event(i, s) {
  i.events.push(s);
}
let displayLimit = 100;
let loadMoreObserver;
function render() {
  document.body.dataset.mode = mode;
  document
    .querySelectorAll("[data-mode]")
    .forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  document
    .querySelectorAll("[data-tab]")
    .forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $("sources-count").textContent = items.filter((i) => !i.draft).length;
  $("drafts-count").textContent = items.filter(
    (i) => i.draft && !i.tracking,
  ).length;
  $("tracking-count").textContent = items.filter((i) => i.tracking).length;
  animating = pending.size > 0;
  const i = current(),
    rows = visible();
  $("content").innerHTML =
    `<div class="intro row between"><div><h2>${tab === "sources" ? t("Un nouveau partage commence ici.") : tab === "drafts" ? t("Chaque brouillon avance à son rythme.") : t("Gardez le fil de vos partages.")}</h2><p class="muted">${tab === "sources" ? t("Les recherches de votre bibliothèque suggèrent des fichiers à examiner.") : tab === "drafts" ? t("Préparez, complétez et relisez. Vos autres brouillons continuent d’avancer.") : t("Retrouvez les envois, les corrections attendues et leur historique.")}</p></div><div class="actions"><button data-action="file">${t("+ Choisir un fichier")}</button><button class="primary" data-action="folder">${t("+ Choisir un dossier")}</button></div></div>
<div class="steps" aria-label="${t("Parcours de l’élément sélectionné")}">${stages()
      .map(
        (name, n) =>
          `<button class="step ${step === n ? "on" : ""} ${i && i.stage > n ? "done" : ""}" data-step="${n}"><b><span class="num">${i && i.stage > n ? "✓" : String(n + 1).padStart(2, "0")}</span>${name}</b><small>${[t("Bibliothèque ou ajout manuel"), t("Rechercher les équivalents"), t("Fichiers et informations"), t("Description, NFO et images"), t("Relire la version enregistrée"), t("Brouillon c411 et publication")][n]}</small></button>`,
      )
      .join("")}</div>
<div class="running"><span><i class="dot ${animating ? "pulse" : ""}"></i>${animating ? t("Préparation en cours") : t("Vous gardez la main sur chaque envoi")}</span><span>${items.filter((i) => i.busy).length}${t(" opérations en cours · ")}${items.filter((i) => i.draft && !i.tracking).length}${t(" brouillons locaux")}</span><span>${t("Envoi uniquement après votre confirmation")}</span></div>
${tab === "tracking" ? tracking() : `<div class="workspace">${tab === "drafts" && step > 0 ? editor(i) : list(rows)}${inspector(i)}</div>`}`;
  loadMoreObserver?.disconnect();
  const more = document.querySelector("[data-load-more]");
  if (more) {
    loadMoreObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          displayLimit += 100;
          render();
        }
      },
      { rootMargin: "200px" },
    );
    loadMoreObserver.observe(more);
  }
}
function list(rows) {
  return `<section class="panel"><div class="tools"><label class="sr" for="search">${t("Rechercher")}</label><input class="search" id="search" placeholder="${t("Rechercher dans ")}${tab === "sources" ? t("mes sources") : t("mes brouillons")}…" value="${esc(query)}"><div class="chips">${[
    ["all", t("Tous")],
    ["none", t("Sans candidat")],
    ["rejected", t("Candidats écartés")],
    ["manual", t("Ajouts manuels")],
    ["unchecked", t("À vérifier")],
  ]
    .map(
      ([k, label]) =>
        `<button class="chip ${filter === k ? "on" : ""}" data-filter="${k}">${label}</button>`,
    )
    .join(
      "",
    )}</div></div><div class="listhead"><span>${tab === "sources" ? t("Sources proposées") : t("Brouillons locaux")}</span><span>${tab === "sources" ? t("Origine de la suggestion") : t("Étape actuelle")}</span></div>${
    rows
      .slice(0, displayLimit)
      .map(
        (i) =>
          `<div class="item ${i.id === selected ? "selected" : ""}" role="button" tabindex="0" data-item="${esc(i.id)}"><div class="cover">${{ Film: "VID", Livre: "EPUB", Audio: "FLAC", "Modèle 3D": "STL" }[i.kind] || "FILE"}</div><div><strong>${esc(i.name)}</strong><small>${esc(i.kind)} · ${i.size}</small><small>${esc(i.events[0])}</small>${i.busy ? `<div class="progress"><i style="width:${i.progress || 15}%"></i></div>` : ""}</div><div><span class="badge ${reasons()[i.reason][1]}">${i.busy ? t("Analyse en cours") : tab === "sources" ? reasons()[i.reason][0] : i.status}</span></div></div>`,
      )
      .join("") ||
    `<div class="empty">${t("Aucun élément pour ce filtre.")}</div>`
  }${rows.length > displayLimit ? `<div data-load-more aria-label="${t("Chargement des sources", "Loading sources")}"></div>` : ""}<div class="foot">${rows.length}${t(" élément(s) ·  Un candidat incompatible ne prouve pas l’absence du contenu sur c411.")}</div></section>`;
}
function inspector(i) {
  if (!i) return "";
  return `<aside class="panel inspector ${drawer ? "open" : ""}"><button class="mobileclose" data-action="drawer-close">${t("Fermer l’inspecteur")}</button><div class="eyebrow">${i.draft ? t("LE BROUILLON SÉLECTIONNÉ") : t("LA SOURCE SÉLECTIONNÉE")}</div><div class="detailtitle"><span class="badge ${reasons()[i.reason][1]}">${i.status}</span><h2>${esc(i.name)}</h2><small>${i.kind} · ${i.size}</small></div><div class="callout"><b>${i.reason === "rejected" ? t("Pourquoi cette suggestion ?") : i.reason === "unchecked" ? t("Recherche encore nécessaire") : t("Avant de préparer l’upload")}</b><p class="muted">${i.reason === "rejected" ? t("Les candidats examinés ne correspondent pas à vos fichiers. Vérifiez les autres éditions ou releases avant de créer le brouillon.") : i.reason === "unchecked" ? t("La recherche reste à effectuer ou à compléter. Cet élément n’est pas considéré comme absent du site.") : t("L’absence de résultat est une piste. Confirmez le contenu et vérifiez les éventuels doublons.")}</p>${!i.draft ? `<button class="primary" data-action="prepare">${t("Examiner cette source →")}</button>` : `<button data-action="edit">${i.sent ? t("Voir le suivi") : t("Ouvrir le brouillon →")}</button>`}</div><div class="section"><div class="eyebrow">${t("FICHIERS D’ORIGINE")}</div><p style="overflow-wrap:anywhere;margin-top:8px;font-size:12px">${esc(i.path)}</p><small>${t("Les fichiers restent à leur emplacement.")}</small></div><div class="section"><div class="row between"><b>${t("Son parcours")}</b><small>${i.draft ? t("Révision ") + i.revision : t("Pas encore de brouillon")}</small></div><div class="timeline">${i.events
    .slice(-5)
    .map((s, n) => `<p><small></small>${esc(s)}</p>`)
    .join("")}</div></div></aside>`;
}
function tracking() {
  const rows = items.filter((i) => i.tracking);
  return `<section class="panel"><div class="tools row between"><div><h3>${t("Envois et publication")}</h3><small>${t("La préparation locale, le brouillon c411 et la publication sont des étapes distinctes.")}</small></div><button data-action="refresh-tracking">${t("Actualiser")}</button></div>${rows.map((i) => `<div class="track"><div><strong>${esc(i.name)}</strong><small style="display:block">${t("Révision ")}${i.revision} · ${i.kind} · ${i.size}</small></div><span class="badge ${i.status === t("Correction demandée") ? "warn" : "ok"}">${i.status}</span><button data-history="${esc(i.id)}">${t("Voir le détail →")}</button></div>`).join("") || `<div class="empty">${t("Vos envois apparaîtront ici.")}</div>`}<div class="foot">${t("Un problème d’envoi reste visible. Aucun nouvel envoi n’est tenté sans votre accord.")}</div></section>`;
}

const statusLabel = (s) =>
  ({
    queued: t("À compléter"),
    sending: t("Envoi lancé · vérifier sur c411"),
    sent: t("Brouillon c411"),
    uncertain: t("Envoi à vérifier"),
  })[s] || s;
let environment = { client: "", active: false },
  categories = [],
  generation = 0;
const sizes = (n) =>
  n > 1073741824
    ? (n / 1073741824).toFixed(1) + t(" Go")
    : (n / 1048576).toFixed(1) + t(" Mo");
const pending = new Set();
const api = async (action, body = {}) => {
  const client = environment.client,
    g = generation;
  const result = await (
    await window.uploadTransport
  )(action, { ...body, _client: client });
  if (g !== generation || client !== environment.client)
    throw Error(t("Le client cible a changé. Rouvrez Upload."));
  return result;
};
function recordItem(r) {
  return {
    id: r.id,
    path: r.path,
    name: r.form.title || r.path.split("/").pop(),
    kind: categories.find((c) => c.id === r.form.category)?.name || "",
    size: sizes(r.files.reduce((n, f) => n + f.size, 0)),
    reason: r.form.manual_source ? "manual" : "unchecked",
    existing: r.form.existing_reviewed,
    draft: true,
    sent: r.status === "sent",
    stage: r.status === "sent" ? 5 : r.form.workflow_step || 1,
    status: statusLabel(r.status),
    tracking: r.status !== "queued",
    revision: r.revision,
    form: r.form,
    review: r.review,
    record: r,
    description: r.form.description,
    events: [
      ...(r.history || []).map(
        (e) =>
          new Date(e.at * 1000).toLocaleString() +
          t(" · Révision ") +
          e.revision +
          t(" enregistrée"),
      ),
      `${t("État : ")}${statusLabel(r.status)}`,
      r.result?.error || "",
    ].filter(Boolean),
  };
}
async function refresh(force = false) {
  if (!force && current()?.dirty) return;
  const g = generation;
  try {
    const data = await api("state");
    if (g !== generation) return;
    categories = data.categories;
    const old = new Map(items.map((i) => [i.id, i]));
    const drafts = data.drafts.map((r) => ({
      ...recordItem(r),
      ...[
        "existing",
        "found",
        "preview",
        "reviewed",
        "stage",
        "dirty",
        "form",
        "description",
      ].reduce((v, k) => {
        if (old.get(r.id)?.revision === r.revision) v[k] = old.get(r.id)?.[k];
        return v;
      }, {}),
    }));
    const paths = new Set(drafts.map((r) => r.path));
    items = [
      ...data.sources
        .filter((r) => !paths.has(r.path))
        .map((r) => ({
          ...r,
          id: r.path,
          kind: categories.find((c) => c.id === r.category)?.name || "",
          size: sizes(r.size),
          stage: 0,
          draft: false,
          status: t("À examiner"),
          form: { category: r.category },
          description: "",
          events: [],
          revision: 0,
        })),
      ...drafts,
    ];
    if (!current()) selected = visible()[0]?.id || items[0]?.id;
    render();
  } catch (e) {
    $("error").textContent = e.message;
  }
}
function adopt(r, previous) {
  const item = {
    ...recordItem(r),
    existing: previous?.existing,
    found: previous?.found,
    preview: previous?.preview,
  };
  items = items.filter((i) => i.id !== r.id && i.id !== previous?.id);
  items.push(item);
  if (!previous || selected === previous.id) selected = item.id;
  return item;
}
function capture(i) {
  if (!i || i !== current()) return;
  if ($("confirm-existing")) i.existing = $("confirm-existing").checked;
  if ($("reviewed")) i.reviewed = $("reviewed").checked;
  const f = { ...i.form };
  if ($("release-name")) {
    f.title = $("release-name").value;
    f.category = Number($("category").value);
    f.subcategory = Number($("subcategory").value) || null;
    f.source = $("release-source").value;
    f.options = {};
    document.querySelectorAll("[data-option]").forEach((n) => {
      f.options[n.dataset.option] = [...n.selectedOptions]
        .map((o) => Number(o.value))
        .filter(Boolean);
    });
  }
  if ($("description")) {
    f.description = $("description").value;
    f.nfo = $("nfo").value;
    f.image = $("image-url").value;
  }
  if (JSON.stringify(f) !== JSON.stringify(i.form)) {
    i.reviewed = false;
    i.dirty = true;
  }
  i.form = f;
  i.description = f.description || "";
}
async function saveItem() {
  let i = current();
  capture(i);
  const submitted = JSON.stringify(i.form);
  const r = await api("save", {
    path: i.path,
    form: i.form,
    id: i.draft ? i.id : "",
    revision: i.revision,
  });
  capture(i);
  const later = JSON.stringify(i.form) !== submitted ? i.form : null;
  i = adopt(r, i);
  if (later) {
    i.form = later;
    i.description = later.description || "";
  }
  i.reviewed = false;
  i.dirty = !!later;
  return i;
}
function editor(i) {
  if (!i)
    return `<section class="panel empty">${t("Choisissez un brouillon.")}</section>`;
  let body = "";
  const f = i.form || {},
    p = i.preview || {},
    findings = i.review?.refusals || [];
  if (step === 1)
    body = `<div class="callout"><b>${t("Vérifier ce qui existe déjà")}</b><p class="muted">${t("Une recherche sans résultat ne prouve pas l’absence du contenu sur le site. Examinez les éditions et formats.")}</p><button data-action="search-site" ${pending.has(i.id) ? "disabled" : ""}>${t("Rechercher sur c411")}</button></div>${i.found ? i.found.map((r) => `<div class="file"><strong>${esc(r.title)}</strong><small>${sizes(r.size)}</small></div>`).join("") || `<p>${t("Aucun résultat pour cette recherche.")}</p>` : `<p class="muted">${t("Recherche à effectuer.")}</p>`}<label><input type="checkbox" id="confirm-existing" ${i.existing ? "checked" : ""}>${t(" J’ai examiné les résultats et retenu cette source.")}</label>`;
  if (step === 2)
    body = `<label for="release-name">${t("Nom de la release")}</label><input id="release-name" value="${esc(f.title || i.name)}"><div class="columns"><div><label for="category">${t("Catégorie")}</label><select id="category">${categories.map((c) => `<option value="${c.id}" ${c.id === f.category ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></div><div><label for="subcategory">${t("Sous-catégorie")}</label><select id="subcategory">${(p.subcategories || [{ id: f.subcategory, name: String(f.subcategory || t("Choisir")) }]).map((c) => `<option value="${c.id || ""}" ${c.id === f.subcategory ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></div></div><label for="release-source">Source</label><input id="release-source" value="${esc(f.source || "")}"><div class="options">${(p.options || []).map((o) => `<label>${esc(o.name)}<select data-option="${o.id}" ${o.multiple ? "multiple" : ""}><option value="">${t("Choisir…")}</option>${o.values.map((v) => `<option value="${v.id}" ${(f.options?.[o.id] || []).includes(v.id) ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label>`).join("")}</div><div class="section"><b>${t("Contenu sélectionné")}</b>${(
      i.record?.files || []
    )
      .slice(0, 100)
      .map(
        (r) =>
          `<div class="file"><span>${esc(r.path)}</span><small>${sizes(r.size)}</small></div>`,
      )
      .join(
        "",
      )}<button data-action="technical">${t("Informations techniques")}</button><button data-action="advanced">${t("Outils de préparation")}</button></div>`;
  if (step === 3)
    body = `<label for="description">${t("Description du partage · BBCode")}</label><textarea id="description">${esc(f.description || "")}</textarea><div class="row" style="margin-top:12px"><button data-action="template">${t("Insérer un modèle")}</button></div><details class="section"><summary>NFO</summary><textarea id="nfo">${esc(f.nfo || "")}</textarea></details><div class="section"><div class="row between"><b>${t("Illustrations et captures")}</b><button data-action="artwork">${t("+ Ajouter une image")}</button></div><label for="image-url">${t("Lien direct de l’image hébergée")}</label><input id="image-url" type="url" value="${esc(f.image || "")}"><p class="muted">${t("Postimages · le lien est inclus dans la présentation à l’enregistrement.")}</p></div>`;
  if (step === 4)
    body = `<div class="callout"><b>${t("Relire la révision ")}${i.revision}</b><p class="muted">${t("Toute modification demande un nouvel enregistrement et une nouvelle relecture.")}</p></div>${findings.map((s) => `<p class="error">${esc(s)}</p>`).join("")}${(i.review?.warnings || []).map((s) => `<p class="notice">${esc(s)}</p>`).join("")}<div class="file"><span>${t("Fichiers")}</span><b>${i.record?.files.length || 0}</b></div><details open><summary>${t("Présentation enregistrée")}</summary><pre>${esc(f.description || "")}</pre></details><details><summary>${t("NFO enregistré")}</summary><pre>${esc(f.nfo || "")}</pre></details><label><input id="reviewed" type="checkbox" ${i.reviewed ? "checked" : ""} ${findings.length ? "disabled" : ""}>${t(" J’ai relu cette version, les fichiers et les avertissements.")}</label>`;
  if (step === 5)
    body = `<div class="callout"><b>${i.sent ? t("Brouillon c411 créé") : t("Prêt pour l’envoi du brouillon ?")}</b><p class="muted">${t("La publication finale reste manuelle sur c411.")}</p></div><div class="file"><span>Source</span><b>${esc(i.name)}</b></div><div class="file"><span>${t("Révision enregistrée")}</span><b>${i.revision}</b></div><div class="file"><span>${t("Relecture")}</span><span class="badge">${i.reviewed ? t("Confirmée") : t("À effectuer")}</span></div><button class="primary" data-action="send" ${!i.reviewed || i.sent ? "disabled" : ""}>${t("Créer le brouillon c411…")}</button>`;
  return `<section class="panel editor"><div class="row between"><div><div class="eyebrow">${String(step + 1).padStart(2, "0")} · ${stages()[step].toUpperCase()}</div><h2>${esc(i.name)}</h2></div><button data-action="draft-list">${t("Voir la liste")}</button></div>${body}<div class="bottomactions"><button data-action="previous">${t("← Précédente")}</button><div class="row"><button data-action="save">${t("Enregistrer")}</button>${step < 5 ? `<button class="primary" data-action="next">${t("Enregistrer et continuer →")}</button>` : ""}</div></div></section>`;
}
function manual(type) {
  dialog(
    () =>
      `<div class="eyebrow">${t("AJOUT MANUEL · ")}${mode === "desktop" ? t("CET ORDINATEUR") : t("SERVEUR TORRENTLINKER")}</div><h2>${t("Choisir ")}${type === "file" ? t("un fichier") : t("un dossier")}</h2><p class="muted">${mode === "web" ? t("Parcourez les fichiers accessibles au serveur.") : t("Sélectionnez vos fichiers sur cet ordinateur.")}</p><form id="manual-form"><label for="manual-path">${t("Chemin")}</label><div class="row"><input id="manual-path" required><button type="button" data-picker="${type}">${t("Parcourir…")}</button></div><label for="manual-kind">${t("Catégorie")}</label><select id="manual-kind">${categories.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select><p class="notice">${t("L’ajout prépare un brouillon local. Aucun envoi sur c411.")}</p><button class="primary">${t("Ajouter aux sources")}</button></form>`,
  );
}
async function browse(type, path = "") {
  if (mode === "desktop") {
    const value = await api("pick", { type, path });
    if (value.selected) $("manual-path").value = value.selected;
    return;
  }
  const listing = await api("browse", { path });
  dialog(
    () =>
      `<h2>${t("Parcourir le serveur")}</h2><p>${esc(listing.path || t("Emplacements accessibles"))}</p><button data-browse="${esc(listing.parent)}" data-type="${type}">${t("↑ Remonter")}</button>${listing.path && type === "folder" ? `<button data-picked="${esc(listing.path)}" data-type="folder">${t("Choisir ce dossier")}</button>` : ""}${listing.folders.map((p) => `<button class="choice" data-browse="${esc(p)}" data-type="${type}">▸ ${esc(p.split("/").pop())}</button>`).join("")}${type === "file" ? listing.files.map((p) => `<button class="choice" data-picked="${esc(p)}" data-type="file">${esc(p.split("/").pop())}</button>`).join("") : ""}`,
  );
}
async function act(action) {
  let i = current();
  if (action === "file" || action === "folder") {
    manual(action);
    return;
  }
  if (action === "close") {
    $("dialog").close();
    return;
  }
  if (action === "drawer-close") {
    drawer = false;
    render();
    return;
  }
  if (action === "prepare") {
    const r = await api("save", { path: i.path, form: i.form });
    i = adopt(r, i);
    if (selected === i.id) {
      tab = "drafts";
      step = 1;
      drawer = false;
    }
  }
  if (action === "edit") {
    tab = i.tracking ? "tracking" : "drafts";
    step = i.stage || 1;
    if (!i.sent)
      i.preview = await api("prepare", {
        path: i.path,
        id: i.id,
        form: i.form,
      });
  }
  if (action === "draft-list") step = 0;
  if (action === "previous") {
    capture(i);
    step = Math.max(0, step - 1);
  }
  if (action === "save") {
    i = await saveItem();
    toast(
      i.dirty
        ? t(
            "Version enregistrée. Les nouvelles modifications restent à enregistrer.",
          )
        : t("Brouillon enregistré localement."),
    );
  }
  if (action === "next") {
    if (step === 1) {
      i.existing = !!$("confirm-existing").checked;
      if (!i.existing)
        throw Error(t("Examinez les résultats puis confirmez cette source."));
    }
    if (step === 4) {
      if (i.dirty)
        throw Error(
          t("Enregistrez les modifications avant de relire cette révision."),
        );
      i.reviewed = !!$("reviewed").checked;
      if (!i.reviewed) throw Error(t("Relisez et confirmez cette révision."));
    } else {
      i.form.workflow_step = step + 1;
      if (step === 1) i.form.existing_reviewed = i.existing;
      i = await saveItem();
      if (i.dirty) {
        render();
        toast(t("Enregistrez les nouvelles modifications avant de continuer."));
        return;
      }
    }
    i.stage = Math.min(5, i.form.workflow_step || step + 1);
    if (i.reviewed) i.stage = 5;
    if (selected === i.id) step = i.stage;
    if (i.stage === 2) {
      const p = await api("prepare", { path: i.path, form: i.form, id: i.id });
      capture(i);
      i.preview = p;
    }
  }
  if (action === "search-site") {
    const id = i.id;
    pending.add(id);
    i.busy = true;
    render();
    try {
      i.found = await api("existing", { path: i.path, form: i.form });
    } finally {
      pending.delete(id);
      i.busy = false;
      capture(current());
    }
  }
  if (action === "technical") {
    dialog(
      () =>
        `<h2>${t("Informations techniques")}</h2><pre>${esc(JSON.stringify(i.review?.file_facts || i.preview?.file_facts || {}, null, 2))}</pre>`,
    );
    return;
  }
  if (action === "advanced") {
    await api("advanced", { path: i.path, id: i.id });
    return;
  }
  if (action === "template") {
    capture(i);
    const p = await api("prepare", {
      path: i.path,
      id: i.id,
      form: { ...i.form, description: "" },
    });
    i.form.description = p.description;
    i.reviewed = false;
    i.dirty = true;
  }
  if (action === "send") {
    dialog(
      () =>
        `<h2>${t("Créer ce brouillon sur c411 ?")}</h2><p>${esc(i.name)}${t(" · révision ")}${i.revision}</p><p>${t("La publication finale restera manuelle sur c411.")}</p><button class="primary" data-action="confirm-send">${t("Confirmer l’envoi")}</button>`,
    );
    return;
  }
  if (action === "confirm-send") {
    if (!i.reviewed || i.dirty)
      throw Error(t("Relisez la révision enregistrée."));
    try {
      await api("send", {
        id: i.id,
        revision: i.revision,
        reviewed_revision: i.revision,
      });
    } finally {
      i.dirty = false;
      i.reviewed = false;
      $("dialog").close();
      tab = "tracking";
      step = 0;
      await refresh(true);
    }
  }
  if (action === "reset-send") {
    const r = await api("reset", { id: i.id, revision: i.revision });
    adopt(r, i);
    $("dialog").close();
    tab = "drafts";
    step = 4;
    render();
    return;
  }
  if (action === "refresh-tracking") {
    const r = await api("remote");
    dialog(
      () =>
        `<h2>${t("Brouillons c411")}</h2>${r.map((d) => `<div class="file">${esc(d.title || d.name || d.id)}</div>`).join("") || `<p>${t("Aucun brouillon distant.", "No remote drafts.")}</p>`}`,
    );
    return;
  }
  if (action === "artwork") {
    capture(i);
    openImageHost(i);
    return;
  }
  if (current() && current() !== i) capture(current());
  render();
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button"),
    row = e.target.closest("[data-item]");
  try {
    if (b?.dataset.tab) {
      capture(current());
      tab = b.dataset.tab;
      step = 0;
      filter = "all";
      query = "";
      selected = visible()[0]?.id;
      render();
      return;
    }
    if (b && "filter" in b.dataset) {
      filter = b.dataset.filter;
      displayLimit = 100;
      render();
      return;
    }
    if (row) {
      capture(current());
      selected = row.dataset.item;
      drawer = true;
      render();
      return;
    }
    if (b && "step" in b.dataset) {
      capture(current());
      const n = +b.dataset.step;
      if (n && !current()?.draft)
        throw Error(t("Choisissez une source puis examinez-la."));
      if (n >= 4 && current()?.dirty) {
        const saved = await saveItem();
        if (saved.dirty) {
          render();
          throw Error(
            t("Enregistrez les nouvelles modifications avant la relecture."),
          );
        }
      }
      step = n;
      if (n === 2) {
        const i = current();
        i.preview = await api("prepare", {
          path: i.path,
          id: i.id,
          form: i.form,
        });
        capture(i);
      }
      render();
      return;
    }
    if (b?.dataset.picker) {
      await browse(b.dataset.picker, $("manual-path").value);
      return;
    }
    if (b && "browse" in b.dataset) {
      await browse(b.dataset.type, b.dataset.browse);
      return;
    }
    if (b?.dataset.picked) {
      manual(b.dataset.type);
      $("manual-path").value = b.dataset.picked;
      return;
    }
    if (b?.dataset.history) {
      const i = items.find((i) => i.id === b.dataset.history);
      selected = i.id;
      dialog(
        () =>
          `<h2>${esc(i.name)}</h2><div class="timeline">${i.events.map((s) => `<p>${esc(s)}</p>`).join("")}</div><pre>${esc(JSON.stringify(i.record.result || {}, null, 2))}</pre>${["sending", "uncertain"].includes(i.record.status) ? `<p>${t("Vérifiez les brouillons sur c411 avant de permettre un nouvel essai.")}</p><button data-action="reset-send" data-id="${esc(i.id)}">${t("J’ai vérifié c411, autoriser un nouvel essai")}</button>` : ""}`,
      );
      return;
    }
    if (b?.dataset.action) {
      b.disabled = true;
      await act(b.dataset.action);
    }
  } catch (err) {
    $("error").textContent = err.message;
    toast(err.message);
  } finally {
    if (b?.isConnected) b.disabled = false;
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "search") {
    query = e.target.value;
    displayLimit = 100;
    const pos = e.target.selectionStart;
    render();
    $("search").focus();
    $("search").setSelectionRange(pos, pos);
  } else if (e.target.id === "reviewed") {
    current().reviewed = e.target.checked;
  } else if (current() && e.target.closest(".editor")) {
    current().reviewed = false;
    current().dirty = true;
  }
});
document.addEventListener("change", async (e) => {
  if (["category", "subcategory"].includes(e.target.id)) {
    const i = current();
    capture(i);
    if (e.target.id === "category") i.form.subcategory = null;
    i.form.options = {};
    try {
      i.preview = await api("prepare", {
        path: i.path,
        id: i.id,
        form: i.form,
      });
      capture(i);
      i.form.subcategory = i.preview.subcategory;
      i.form.options = i.preview.chosen;
      render();
    } catch (err) {
      $("error").textContent = err.message;
    }
  }
});
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "manual-form") return;
  e.preventDefault();
  try {
    const r = await api("save", {
      path: $("manual-path").value,
      form: { manual_source: true, category: Number($("manual-kind").value) },
    });
    adopt(r);
    tab = "drafts";
    step = 1;
    $("dialog").close();
    render();
  } catch (err) {
    toast(err.message);
  }
});
window.addEventListener("upload-environment", (e) => {
  const changed = environment.client !== e.detail.client;
  const languageChanged = environment.language !== e.detail.language;
  if (!changed) capture(current());
  environment = e.detail;
  mode = environment.mode;
  window.TLPanel.setLanguage(environment.language);
  document
    .querySelector(".tabs")
    .setAttribute("aria-label", t("Espaces Upload"));
  for (const [key, label] of Object.entries({
    sources: "Sources",
    drafts: "Brouillons",
    tracking: "Suivi",
  }))
    document.querySelector(`[data-tab="${key}"]`).firstChild.textContent =
      t(label) + " ";
  if (languageChanged && !changed) {
    if ($("dialog").open && dialogRenderer)
      window.TLPanel.refreshForm($("dialog"), () => dialog(dialogRenderer));
    // Recompute derived labels without discarding unsaved forms or review state.
    items.forEach((i) => {
      if (i.record) {
        const derived = recordItem(i.record);
        i.status = derived.status;
        i.size = derived.size;
        i.events = derived.events;
      } else i.status = t("À examiner");
    });
    render();
  }
  if (changed) {
    generation++;
    items = [];
    step = 0;
    selected = "";
  }
  document.documentElement.dataset.theme = environment.theme;
  if (environment.active) {
    if (current()?.dirty) {
      capture(current());
      return;
    }
    refresh();
  }
});
window.uploadTransport.then(() => window.uploadReady());

// Protocol documented by Postimages' official forum integration. The external
// picker uploads only images the user selects, then returns their hosted BBCode.
let imageUpload = null;
function openImageHost(item) {
  if (imageUpload?.popup && !imageUpload.popup.closed)
    imageUpload.popup.close();
  const id =
    "tl_" +
    Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) =>
      n.toString(16).padStart(2, "0"),
    ).join("");
  const params = new URLSearchParams({
    mode: "fluxbb",
    areaid: id,
    hash: "1",
    pm: "1",
    lang: "french",
    code: "hotlink",
    forumurl: location.href,
  });
  const popup = window.open(
    "https://postimages.org/upload?" + params,
    id,
    "popup,width=720,height=680",
  );
  if (!popup)
    throw Error(t("Autorisez la fenêtre Postimages pour choisir votre image."));
  imageUpload = { id, popup, item, client: environment.client };
  toast(
    t(
      "Choisissez une image dans Postimages. Son lien sera ajouté à la présentation.",
    ),
  );
}
window.addEventListener("message", (e) => {
  const job = imageUpload;
  if (
    !job ||
    e.origin !== "https://postimages.org" ||
    e.source !== job.popup ||
    e.data?.id !== job.id ||
    typeof e.data.message !== "string"
  )
    return;
  if (job.client !== environment.client) return;
  try {
    const code = decodeURIComponent(e.data.message);
    if (code.length > 12000) throw Error(t("Réponse image trop longue."));
    const images = [
      ...code.matchAll(/\[img\](https:\/\/[^\s\[\]]+)\[\/img\]/gi),
    ];
    if (
      !images.length ||
      images.some(
        (m) =>
          !["i.postimg.cc", "postimg.cc", "i.postimg.org"].includes(
            new URL(m[1]).hostname,
          ),
      )
    )
      throw Error(t("Postimages n’a pas retourné de lien image valide."));
    const item = items.find((i) => i.id === job.item.id);
    if (!item)
      throw Error(t("Le brouillon a changé. Rouvrez le sélecteur d’image."));
    if (current() === item) capture(item);
    item.form.description = (item.form.description || "") + "\n" + code;
    item.form.image = images[0][1];
    item.description = item.form.description;
    item.reviewed = false;
    item.dirty = true;
    if (current() === item) render();
    toast(
      t(
        "Image hébergée et ajoutée à la présentation. Enregistrez le brouillon.",
      ),
    );
  } catch (error) {
    toast(error.message);
  }
});

document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-item]")) {
    e.preventDefault();
    e.target.click();
  }
});
