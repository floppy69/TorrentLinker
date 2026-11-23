"use strict";
// State is scoped to one client and Local Item. Replies from older selections cannot repaint it.
let candidateReview = null;
const candidateChoices = new Map();
let candidateChoicesGeneration = -1;
function candidateSignature(row) {
  const completed = (snapshot.jobs || []).filter(j => !["queued", "running"].includes(j.status) &&
    (j.subject?.path === row.path || j.subject?.paths?.includes(row.path) || ["check-all", "reseed-all"].includes(j.kind)) &&
    ["search", "check", "reject", "import-file", "seed", "repair"].includes(reviewJobAction(j)));
  return JSON.stringify([row.candidates || [], completed.map(j => j.id)]);
}
function reviewState(row) {
  if (candidateChoicesGeneration !== generation) {
    candidateChoices.clear();
    candidateChoicesGeneration = generation;
  }
  if (
    !candidateReview ||
    candidateReview.path !== row.path ||
    candidateReview.generation !== generation
  ) {
    candidateReview = {
      path: row.path,
      generation,
      rows: [],
      key: candidateChoices.get(row.path) || "",
      tab: "summary",
      loading: true,
      message: "",
      provenance: null,
      evidence: null,
      details: new Map(),
      pending: new Set(),
      signature: candidateSignature(row),
    };
    const state = candidateReview;
    queueMicrotask(() => reviewRequest(state, "review"));
  }
  const signature = candidateSignature(row);
  if (
    candidateReview.signature !== signature &&
    !candidateReview.pending.size
  ) {
    candidateReview.signature = signature;
    const state = candidateReview;
    state.provenance = null;
    state.evidence = null;
    state.details.clear();
    queueMicrotask(async () => {
      await reviewRequest(state, "review");
      if (reviewCurrent(state)) await loadReviewTab(state);
    });
  }
  return candidateReview;
}
function reviewCurrent(state) {
  return (
    candidateReview === state &&
    state.generation === generation &&
    selected === state.path
  );
}
async function reviewRequest(state, action, body = {}) {
  if (!reviewCurrent(state) || state.pending.has(action)) return;
  state.pending.add(action);
  state.message = "";
  if (reviewCurrent(state)) render();
  try {
    const value = await api("inspect", {
      path: state.path,
      action,
      key: state.key,
      ...body,
    });
    if (!reviewCurrent(state)) return;
    if (["review", "search", "check", "reject"].includes(action)) {
      state.rows = value;
      if (!value.some((c) => c.key === state.key))
        state.key = value[0]?.key || "";
      state.loading = false;
    } else if (action === "evidence") {
      state.evidence = value;
      state.provenance = value.provenance;
    } else if (["provenance", "import"].includes(action))
      state.provenance = value;
    else if (action === "details")
      state.details.set(body.key || state.key, value);
    if (action === "check")
      state.message = t(
        "Comparaison des noms et tailles terminée. Les hashes restent à vérifier.",
        "Names and sizes compared. Content hashes still need verification.",
      );
  } catch (error) {
    if (reviewCurrent(state)) {
      state.message = error.message;
      state.loading = false;
    }
  } finally {
    state.pending.delete(action);
    if (reviewCurrent(state)) render();
  }
}
const matchLabel = (value) =>
  t(
    {
      full: "Correspondance complète",
      partial: "Correspondance partielle",
      none: "Aucune correspondance",
      unchecked: "Non vérifié",
    }[value] || value,
    {
      full: "Full Match",
      partial: "Partial Match",
      none: "No Match",
      unchecked: "Not checked",
    }[value] || value,
  );
const evidenceLabel = (value) =>
  t(
    {
      verified: "Association vérifiée",
      unverified: "Non vérifiée",
      ambiguous: "Ambiguë",
      partial: "Partielle",
      stale: "Périmée",
      measured: "Mesuré",
      hint: "Indice",
      review: "À examiner",
    }[value] || value,
    {
      verified: "Verified association",
      unverified: "Unverified",
      ambiguous: "Ambiguous",
      partial: "Partial",
      stale: "Stale",
      measured: "Measured",
      hint: "Hint",
      review: "Needs review",
    }[value] || value,
  );
function observationLabel(value) {
  const labels = {
    filename: ["Nom du fichier", "Filename"],
    "embedded-title": ["Titre intégré", "Embedded title"],
    "writing-application": ["Application d’écriture", "Writing application"],
    resolution: ["Résolution", "Resolution"],
    "video-codec": ["Codec vidéo", "Video codec"],
    "audio-codec": ["Codec audio", "Audio codec"],
    "audio-channels": ["Canaux audio", "Audio channels"],
    processing: ["Indice de traitement", "Processing clue"],
  };
  return esc(labels[value] ? t(...labels[value]) : value);
}
function reviewDescription(markup) {
  const doc = new DOMParser().parseFromString(markup, "text/html");
  for (const a of doc.querySelectorAll("a")) {
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  }
  for (const img of doc.querySelectorAll("img"))
    img.replaceWith(
      doc.createTextNode(
        t("[Image de la présentation]", "[Presentation image]"),
      ),
    );
  return doc.body.innerHTML;
}
function reviewContent(state, candidate) {
  if (state.tab === "evidence") {
    const report = state.evidence;
    return `<h3>${t("Éléments de preuve", "Evidence")}</h3><p class="muted">${t("Comparez les déclarations aux mesures. Une différence ou un outil d’encodage ne prouve pas une réattribution.", "Compare claims with measurements. A difference or encoding tool does not prove reattribution.")}</p><button class="review-field" data-review-action="evidence" ${state.pending.size ? "disabled" : ""}>${t("Inspecter les métadonnées", "Inspect metadata")}</button>${report ? (report.observations || []).map((o) => `<div class="review-file"><b>${esc(o.file)}</b><small>${observationLabel(o.source)} · ${observationLabel(o.field)}</small><small>${t("Déclaration", "Claim")} : ${esc(o.claim || "—")}<br>${t("Observation", "Observation")} : ${esc(o.observed)}</small><span class="badge ${o.confidence === "hint" ? "blue" : "warn"}">${evidenceLabel(o.confidence)}</span></div>`).join("") + (report.unreadable || []).map((file) => `<p class="muted">${t("Métadonnées indisponibles", "Metadata unavailable")} : ${esc(file)}</p>`).join("") + (!(report.observations || []).length ? `<p class="muted">${t("Aucune divergence mesurable signalée. Les informations absentes ne prouvent pas une correspondance.", "No measurable discrepancy reported. Missing information does not establish a match.")}</p>` : "") : `<div class="callout">${t("Aucune mesure enregistrée pour cet élément.", "No measurements recorded for this item.")}</div>`}<h3>${t("Provenance", "Provenance")}</h3><button class="review-field" data-review-action="import-file" ${state.pending.size ? "disabled" : ""}>${t("Importer un ancien .torrent", "Import a historical .torrent")}</button><input id="provenance-file" type="file" accept=".torrent" hidden ${state.pending.size ? "disabled" : ""}><small>${t("Lecture locale hors ligne. Aucun ajout au client ; l’adresse d’annonce n’est pas conservée.", "Read locally, offline. No client addition; the announce address is not retained.")}</small><button class="review-field" data-review-action="provenance" ${state.pending.size ? "disabled" : ""}>${t("Actualiser la provenance", "Refresh provenance")}</button>${state.provenance === null ? `<p>${t("Chargement…", "Loading…")}</p>` : state.provenance.map((p) => `<div class="callout"><b>${esc(p.name)}</b><p><span class="badge ${p.status === "verified" ? "" : "warn"}">${evidenceLabel(p.status)}</span></p><small>${bytes(p.verified_bytes)} / ${bytes(p.target_bytes)} · ${t("Association avec ce .torrent uniquement, sans preuve d’auteur.", "Association with this .torrent only, not proof of authorship.")}</small>${(p.files || []).map((f) => `<div class="review-file"><b>${esc(f.original)}</b><small>↳ ${esc(f.local || t("Association à examiner", "Association needs review"))}</small></div>`).join("")}</div>`).join("") || `<p class="muted">${t("Aucune provenance importée.", "No imported provenance.")}</p>`}<details><summary>${t("Comprendre les états de provenance", "Understanding provenance states")}</summary><p>${t("Non vérifiée : association à contrôler. Ambiguë : plusieurs fichiers possibles. Partielle : seule une partie est vérifiée. Vérifiée : les hashes correspondent. Périmée : le fichier a changé.", "Unverified: association needs checking. Ambiguous: several possible files. Partial: only part is verified. Verified: hashes match. Stale: the file changed.")}</p></details>`;
  }
  if (!candidate)
    return `<p>${t("Aucun candidat. Lancez une recherche pour cet élément.", "No Candidates. Search this item to find matching torrents.")}</p>`;
  if (state.tab === "files")
    return `<h3>${t("Correspondance des fichiers", "File comparison")}</h3>${(candidate.files || []).map((f) => `<div class="review-file"><b>${esc(f.local || f.torrent)}</b><small>↳ ${esc(f.torrent)}</small><span class="badge ${f.status === "missing" ? "warn" : ""}">${t({ missing: "Manquant", renamed: "Nom différent", matched: "Présent", ignored: "Ignoré" }[f.status] || f.status, { missing: "Missing", renamed: "Different name", matched: "Present", ignored: "Ignored" }[f.status] || f.status)}</span></div>`).join("") || `<p>${t("Vérifiez le candidat pour comparer ses fichiers.", "Check the Candidate to compare its files.")}</p>`}<p class="muted">${t("Les fichiers locaux ne seront pas renommés. Le hash du contenu reste à vérifier.", "Local files will not be renamed. Content hashes still need verification.")}</p>`;
  if (["description", "nfo"].includes(state.tab)) {
    const detail = state.details.get(candidate.key);
    if (!detail)
      return `<p>${state.pending.has("details") ? t("Chargement…", "Loading…") : t("Détails indisponibles.", "Details unavailable.")}</p><button data-review-action="details">${t("Réessayer", "Retry")}</button>`;
    if (state.tab === "nfo")
      return `<h3>${t("NFO du candidat", "Candidate NFO")}</h3><pre>${esc(detail.nfo || t("Aucun NFO.", "No NFO supplied."))}</pre>`;
    // preview_html strips executable markup and replaces remote images with placeholders.
    return `<h3>${esc(candidate.title)}</h3><div class="review-description">${detail.description ? reviewDescription(detail.description) : esc(t("Aucune description.", "No description supplied."))}</div><p class="muted">${t("Présentation fournie par l’indexeur. Ces déclarations ne constituent pas une vérification du fichier local.", "Description supplied by the Indexer. These claims do not verify the local file.")}</p>`;
  }
  return `<span class="badge ${candidate.match === "partial" ? "warn" : ""}">${matchLabel(candidate.match)} · ${t("tailles", "sizes")}</span><div class="review-facts"><div><small>${t("Taille", "Size")}</small>${bytes(candidate.size)}</div><div><small>${t("Seeders annoncés", "Reported seeders")}</small>${esc(candidate.seeders ?? "—")}</div><div><small>${t("Fichiers présents", "Files present")}</small>${(candidate.files || []).filter((f) => f.local).length} / ${(candidate.files || []).filter((f) => f.status !== "ignored").length}</div><div><small>${t("Couverture", "Coverage")}</small>${candidate.coverage == null ? "—" : Math.round(candidate.coverage * 100) + " %"}</div></div><p>${t("La correspondance compare les noms et tailles. Cela ne prouve pas encore l’identité du contenu.", "A Match compares names and sizes. It does not yet prove content identity.")}</p><div class="callout">${candidate.match === "partial" ? t("Examinez les fichiers manquants avant de poursuivre.", "Review missing files before continuing.") : t("Le client torrent vérifiera les hashes avant le partage. Les originaux gardent leurs noms.", "The Torrent Client will check hashes before sharing. Originals keep their names.")}</div><p class="muted">${candidate.evidence?.scope ? esc(candidate.evidence.scope) + " · " : ""}${t("Couverture limitée aux résultats renvoyés par l’indexeur.", "Coverage is limited to results returned by the Indexer.")}</p>`;
}
function candidateInspector(row) {
  const s = reviewState(row),
    c = s.rows.find((c) => c.key === s.key),
    pending = s.pending.size > 0 || !!snapshot.progress?.active?.[row.path];
  return `<div class="section review-header"><b>${t("Candidats", "Candidates")}</b>${s.loading ? `<p>${t("Chargement…", "Loading…")}</p>` : s.rows.length ? `<select class="review-field" id="review-candidate" aria-label="${t("Candidat", "Candidate")}" ${pending ? "disabled" : ""}>${s.rows.map((c) => `<option value="${esc(c.key)}" ${s.key === c.key ? "selected" : ""}>${esc(c.title)} · ${bytes(c.size)} · ${esc(c.seeders)} seeders</option>`).join("")}</select>` : `<p>${t("Aucun candidat", "No Candidates")}</p>`}<button data-review-action="search" ${pending ? "disabled" : ""}>${t("Chercher des torrents compatibles", "Find compatible torrents")}</button><div class="review-tabs" role="tablist">${Object.entries(
    {
      summary: t("Résumé", "Summary"),
      files: t("Fichiers", "Files"),
      description: t("Description", "Description"),
      nfo: "NFO",
      evidence: t("Preuves", "Evidence"),
    },
  )
    .map(
      ([key, label]) =>
        `<button role="tab" aria-selected="${s.tab === key}" class="${s.tab === key ? "on" : ""}" data-review-tab="${key}">${label}</button>`,
    )
    .join(
      "",
    )}</div><div class="review-content" role="tabpanel">${reviewContent(s, c)}</div><div class="review-actions"><button data-review-action="check" ${!c || pending ? "disabled" : ""}>${t("Vérifier le candidat", "Check Candidate")}</button><button data-review-action="reject" ${!c || pending ? "disabled" : ""}>${t("Écarter", "Reject")}</button></div><div class="review-actions"><button class="primary" data-review-action="seed" ${!c || !(c.match === "full" || (c.archive && c.match === "partial")) || pending || snapshot.progress?.active?.[row.path] ? "disabled" : ""}>${c?.archive ? t("Extraire et remettre en seed…", "Unpack and reseed…") : t("Vérifier et remettre en seed", "Verify and reseed")}</button></div><div class="review-actions"><button data-review-action="repair" ${!c || pending ? "disabled" : ""}>${t("Diagnostiquer une réparation…", "Diagnose repair…")}</button><button data-review-action="repair-history">${t("Historique des réparations…", "Repair history…")}</button></div><p class="review-message" role="status">${esc(s.message)}</p></div>`;
}
async function loadReviewTab(s) {
  if (s.tab === "evidence" && s.provenance === null)
    await reviewRequest(s, "provenance");
  const c = s.rows.find((c) => c.key === s.key);
  if (["description", "nfo"].includes(s.tab) && c && !s.details.has(c.key))
    await reviewRequest(s, "details", { key: c.key });
}
document.addEventListener(
  "click",
  (e) => {
    const b = e.target.closest("[data-review-tab],[data-review-action]");
    if (!b || !candidateReview) return;
    e.stopImmediatePropagation();
    const s = candidateReview;
    if (b.dataset.reviewTab) {
      s.tab = b.dataset.reviewTab;
      render();
      loadReviewTab(s);
      return;
    }
    const action = b.dataset.reviewAction;
    if (
      action === "reject" &&
      !confirm(
        t(
          "Écarter ce candidat pour cet élément ?",
          "Reject this Candidate for this item?",
        ),
      )
    )
      return;
    if (action === "import-file") {
      $("provenance-file").click();
      return;
    }
    if (action === "repair-history") {
      openRecovery("history");
      return;
    }
    if (action === "repair") {
      openRecovery("repair", { path: s.path, key: s.key });
      return;
    }
    if (action === "seed") {
      const c = s.rows.find((c) => c.key === s.key);
      if (c && (c.match === "full" || (c.archive && c.match === "partial"))) {
        if (c.archive)
          openRecovery("archive", { path: s.path, key: c.key });
        else
          start([s.path], c.key)
            .then(refresh)
            .catch(() => {});
      }
      return;
    }
    reviewRequest(s, action);
  },
  true,
);
document.addEventListener("change", async (e) => {
  const s = candidateReview;
  if (!s) return;
  if (e.target.id === "review-candidate") {
    s.key = e.target.value;
    candidateChoices.set(s.path, s.key);
    s.message = "";
    render();
    await loadReviewTab(s);
  }
  if (e.target.id === "provenance-file") {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) {
      s.message = t(
        "Fichier .torrent trop volumineux.",
        "Torrent file is too large.",
      );
      render();
      return;
    }
    const data = new Uint8Array(await file.arrayBuffer());
    if (!reviewCurrent(s)) return;
    let raw = "";
    for (let offset = 0; offset < data.length; offset += 8192)
      raw += String.fromCharCode(...data.subarray(offset, offset + 8192));
    await reviewRequest(s, "import", { torrent_data: btoa(raw) });
  }
});

document.addEventListener("click", (e) => {
  const link = e.target.closest(".review-description a[href]");
  if (link && environment.mode === "desktop") {
    e.preventDefault();
    api("open-link", { url: link.href }).catch((error) => {
      $("error").textContent = error.message;
    });
  }
});
