"use strict";
// One approved dialog for both hosts. Jobs are pinned to the client at submission.
let recovery = null;
for (const id of ["recovery-dialog", "recovery-confirm", "recovery-folder"]) {
  const node = document.createElement("dialog");
  node.id = id;
  document.body.append(node);
}
const recoveryCurrent = (s) => recovery === s && s.generation === generation;
const recoverySteps = (names, current) =>
  `<div class="recovery-steps">${names.map((name, i) => `<div class="${i === current ? "on" : ""}"><small>0${i + 1}</small>${i < current ? "✓ " : ""}${name}</div>`).join("")}</div>`;
const recoveryButtons = (text) => `<div class="recovery-actions">${text}</div>`;
const recoveryClose = () =>
  `<button data-recovery="close">${t("Fermer", "Close")}</button>`;
const repairStatus = (status) => {
  const names = {
    "awaiting-confirmation": ["Diagnostic admissible", "Eligible diagnosis"],
    ineligible: ["Hors des limites de réparation", "Outside repair limits"],
    preparing: ["Préparation de la copie", "Preparing copy"],
    adding: [
      "Ajout incertain · inspecter le client",
      "Addition uncertain · inspect client",
    ],
    checking: ["Vérification du client", "Client verification"],
    ready: ["Prêt pour confirmation", "Ready for confirmation"],
    "needs-review": ["Client à inspecter", "Inspect client"],
    starting: [
      "Démarrage incertain · inspecter le client",
      "Start uncertain · inspect client",
    ],
    downloading: ["Téléchargement dans la copie", "Downloading into copy"],
    completed: ["Réparation terminée", "Repair completed"],
  };
  return names[status] ? t(...names[status]) : status;
};
function recoveryPhase(s) {
  if (s.view === "history") return t("Chargement…", "Loading…");
  if (s.progress?.cancellable === false)
    return t("Démarrage de la vérification…", "Starting verification…");
  return t(
    {
      "refresh-unpack": "Vérification du client…",
      "preview-unpack": "Examen de l’archive…",
      "unpack-reseed": "Extraction en cours…",
      "diagnose-repair": "Diagnostic en cours…",
      "prepare-repair": "Préparation de la copie…",
      "refresh-repair": "Actualisation de la vérification…",
      "start-repair": "Démarrage du téléchargement…",
    }[s.kind],
    {
      "refresh-unpack": "Client verification…",
      "preview-unpack": "Reviewing archive…",
      "unpack-reseed": "Extracting…",
      "diagnose-repair": "Diagnosing…",
      "prepare-repair": "Preparing copy…",
      "refresh-repair": "Refreshing verification…",
      "start-repair": "Starting download…",
    }[s.kind],
  );
}
function recoveryMeter(s) {
  if (!s.busy) return "";
  const p = s.progress || {},
    percent = p.total > 0 ? Math.min(100, (100 * p.done) / p.total) : null;
  return `<p role="status">${esc(recoveryPhase(s))}</p><progress ${percent === null ? "" : `value="${percent}" max="100"`}></progress>${percent === null ? "" : `<small>${bytes(p.done)} / ${bytes(p.total)}</small>`}`;
}
function recoveryHistory(s) {
  let html = "";
  html = `<div class="eyebrow">${t("COPIES DE RÉPARATION", "REPAIR COPIES")}</div><h2>${t("Historique des réparations", "Repair history")}</h2><p class="muted">${t("Retrouvez les copies préparées, même sans candidat sélectionné.", "Find prepared copies, even without a selected Candidate.")}</p><div class="recovery-history">${(s.history || []).map((r) => `<button data-repair-id="${esc(r.id)}"><b>${esc(r.name)}</b><small>${esc(repairStatus(r.status))}</small><small>${esc(r.copy || r.source)}</small></button>`).join("") || (!s.busy ? `<p>${t("Aucune réparation enregistrée.", "No repairs recorded.")}</p>` : "")}</div>${recoveryMeter(s)}${recoveryButtons(recoveryClose())}`;

  return html;
}
function recoveryArchive(s) {
  let html = "";
  const a = s.archive,
    verifying =
      ["verifying", "verified-stopped", "needs-review"].includes(
        s.result?.status,
      ) || s.progress?.cancellable === false;
  html = `<div class="eyebrow">${t("ARCHIVE", "ARCHIVE")}${a ? " · " + esc(a.title) : ""}</div><h2>${t("Extraire et remettre en seed", "Unpack and reseed")}</h2><p class="muted">${environment.mode === "web" ? t("Extraction sur le serveur TorrentLinker.", "Extraction on the TorrentLinker server.") : t("Extraction sur cet ordinateur.", "Extraction on this computer.")} ${t("L’archive originale est conservée.", "The original archive is kept.")}</p>${recoverySteps([t("Examiner", "Review"), t("Extraire", "Extract"), t("Vérifier", "Verify"), t("Partager", "Share")], s.result?.status === "seeding" ? 3 : verifying ? 2 : s.kind === "unpack-reseed" && s.busy ? 1 : 0)}`;
  if (a)
    html += `<div class="review-facts"><div><small>${t("À extraire", "To extract")}</small>${bytes(a.size)} · ${a.files} ${t("fichiers", "files")}</div><div><small>${t("Espace disponible", "Available space")}</small>${bytes(a.free)}</div><div><small>${t("Correspondance", "Match")}</small>${matchLabel(a.match)} · ${t("tailles", "sizes")}</div><div><small>${t("Client cible", "Target client")}</small>${esc(snapshot.setup.clients?.find((c) => c.id === environment.client)?.name || snapshot.setup.client || environment.client)}</div></div><div class="callout"><small>${t("Archive d’origine", "Original archive")}</small><p class="recovery-path">${esc(a.archive)}</p><small>${t("Destination prévue · nouveau dossier", "Planned destination · new folder")}</small><p class="recovery-path">${esc(a.destination)}</p><small>${t("Aucun fichier existant ne sera écrasé.", "No existing file will be overwritten.")}</small></div><p>${t("Le client vérifie le contenu extrait avant le partage. Aucun fichier manquant ne sera téléchargé.", "The client checks extracted content before sharing. Missing files will not be downloaded.")}</p>${a.match === "partial" ? `<p class="callout">${a.missing} ${t("fichiers manquants. Tous les fichiers restent ignorés dans le client : seules les pièces disponibles seront partagées.", "missing files. Every file stays skipped in the client: only available pieces will be shared.")}</p>` : ""}`;
  html += recoveryMeter(s);
  if (s.result?.status === "verifying")
    html += `<p role="status" class="callout">${t("Vérification lancée. L’archive est conservée. Suivez la vérification dans Torrents.", "Verification started. The archive is kept. Follow verification in Torrents.")}</p>`;
  if (s.result && s.result.status !== "verifying")
    html += `<p role="status" class="callout">${s.result.status === "seeding" ? (s.result.partial ? t("Contenu disponible vérifié · partage partiel", "Available content verified · partial sharing") : t("Contenu vérifié · en partage", "Content verified · sharing")) : s.result.status === "verified-stopped" ? t("Contenu vérifié · arrêté dans le client", "Content verified · stopped in the client") : t("Vérification à examiner dans le client. Aucun nouvel envoi automatique.", "Inspect verification in the client. No automatic resubmission.")}</p>`;
  if (s.cancelled)
    html += `<p role="status">${t("Extraction annulée. L’archive est conservée.", "Extraction cancelled. The archive is kept.")}</p>`;
  html += recoveryButtons(
    s.busy
      ? `${recoveryClose()}${s.kind === "unpack-reseed" && !verifying && s.job ? `<button data-recovery="cancel" ${s.cancelling ? "disabled" : ""}>${t("Annuler l’extraction", "Cancel extraction")}</button>` : ""}`
      : a && !s.result && !s.cancelled && !s.error
        ? `<button data-recovery="close">${t("Annuler", "Cancel")}</button><button class="primary" data-recovery="extract">${t("Extraire et remettre en seed", "Unpack and reseed")}</button>`
        : `${recoveryClose()}${s.result ? `<button data-recovery="archive-refresh">${t("Actualiser la vérification", "Refresh verification")}</button>` : ""}${!s.result ? `<button data-recovery="review">${t("Réexaminer l’archive", "Review archive again")}</button>` : ""}`,
  );

  return html;
}
function recoveryRepair(s) {
  let html = "";
  const r = s.row;
  html = `<div class="eyebrow">${t("COPIE INDÉPENDANTE · EXPÉRIMENTAL", "INDEPENDENT COPY · EXPERIMENTAL")}</div><h2>${t("Réparer sans toucher à l’original", "Repair without touching the original")}</h2>`;
  if (r) {
    const initial = r.status === "awaiting-confirmation" && r.eligible,
      uncertain = ["preparing", "adding", "starting", "needs-review"].includes(
        r.status,
      );
    const step =
      s.kind === "prepare-repair" && s.busy
        ? 1
        : ["checking", "ready"].includes(r.status)
          ? 2
          : ["downloading", "completed"].includes(r.status)
            ? 3
            : 0;
    html += `<p class="muted">${esc(r.name)} · qBittorrent · ${t("torrent v1 d’un fichier", "single-file v1 torrent")}</p>${recoverySteps([t("Diagnostic", "Diagnosis"), t("Préparer la copie", "Prepare copy"), t("Vérifier", "Verify"), t("Compléter", "Complete")], step)}<span class="badge ${!r.eligible || uncertain ? "warn" : ""}">${esc(repairStatus(r.status))}</span><div class="review-facts"><div><small>${t("Contenu vérifié par pièces", "Piece-verified content")}</small>${Math.round((100 * r.verified_bytes) / r.target_bytes)} % · ${bytes(r.verified_bytes)}</div><div><small>${t("Contenu manquant estimé", "Estimated missing content")}</small>${bytes(r.missing_bytes)}</div><div><small>${t("Écart de taille", "Size difference")}</small>${r.size_difference == null ? "—" : bytes(r.size_difference)}</div><div><small>${t("Seeders annoncés", "Reported seeders")}</small>${esc(r.seeders)} · ${t("disponibilité non garantie", "availability not guaranteed")}</div></div><details ${s.details ? "open" : ""} id="repair-limits"><summary>${t("Limites du diagnostic", "Diagnosis limits")}</summary><p class="muted">${t("Écart ≤ min(1 %, 50 Mio), au moins 90 % vérifiés, au plus 500 Mio manquants et 2 seeders annoncés. Ce diagnostic ne prouve ni la source ni l’auteur du contenu.", "Difference ≤ min(1%, 50 MiB), at least 90% verified, at most 500 MiB missing and 2 reported seeders. This diagnosis proves neither source nor authorship.")}</p></details><div class="callout"><small>${t("Original conservé", "Original kept")}</small><p class="recovery-path">${esc(r.source)}</p>${r.copy ? `<small>${t("Copie indépendante", "Independent copy")}</small><p class="recovery-path">${esc(r.copy)}</p>` : `<small>${t("Une copie indépendante sera créée. Aucun lien dur ni modification de l’original.", "An independent copy will be created. No hard links or changes to the original.")}</small>`}</div>`;
    if (initial)
      html += `<label for="repair-path">${environment.mode === "web" ? t("Dossier du serveur pour la copie", "Server folder for the copy") : t("Dossier pour la copie", "Folder for the copy")}</label><div class="row"><input id="repair-path" value="${esc(s.destination)}" ${s.busy ? "disabled" : ""}><button data-recovery="browse" ${s.busy ? "disabled" : ""}>${t("Parcourir…", "Browse…")}</button></div><label class="recovery-check"><input id="repair-opt" type="checkbox" ${s.opt ? "checked" : ""} ${s.busy ? "disabled" : ""}><span>${t("Activer la réparation expérimentale", "Enable experimental repair")}<small>${t("Essais sur des bibliothèques réelles encore en attente.", "Real-library trials still pending.")}</small></span></label><p class="muted">${t("Préparer la copie l’ajoute arrêtée au client pour vérification. Le téléchargement demandera une confirmation séparée.", "Preparing the copy adds it stopped to the client for verification. Downloading requires separate confirmation.")}</p>`;
    if (!r.eligible)
      html += `<p class="callout">${t("Ce candidat dépasse les limites de réparation. Aucune copie ne sera créée.", "This Candidate is outside repair limits. No copy will be created.")}</p>`;
    if (r.status === "ready")
      html += `<p class="callout"><b>${t("Vérification terminée · téléchargement arrêté", "Verification complete · download stopped")}</b><small>${t("Le client a confirmé les pièces présentes dans la copie. Vous pouvez maintenant confirmer le téléchargement du contenu manquant.", "The client confirmed the pieces present in the copy. You can now confirm downloading the missing content.")}</small></p>`;
    if (uncertain)
      html += `<p class="callout"><b>${t("Inspectez le client avant de continuer", "Inspect the client before continuing")}</b><small>${t("Le dernier envoi peut être incomplet ou incertain. Aucun téléchargement ne sera relancé automatiquement.", "The last submission may be incomplete or uncertain. Downloads will not be retried automatically.")}</small></p>`;
    html +=
      recoveryMeter(s) +
      recoveryButtons(
        `${recoveryClose()}${!s.busy && initial ? `<button class="primary" id="repair-prepare" data-recovery="prepare" ${s.opt && s.destination.trim() ? "" : "disabled"}>${t("Préparer une copie indépendante", "Prepare an independent copy")}</button>` : ""}${!s.busy && r.copy ? `<button data-recovery="refresh">${t("Actualiser la vérification", "Refresh verification")}</button>` : ""}${!s.busy && r.status === "ready" ? `<button class="primary" data-recovery="confirm">${t("Confirmer le téléchargement…", "Confirm download…")}</button>` : ""}`,
      );
  } else html += recoveryMeter(s) + recoveryButtons(recoveryClose());

  return html;
}
function drawRecovery() {
  const s = recovery;
  if (!s || !recoveryCurrent(s)) return;
  const modal = $("recovery-dialog"),
    scroll = modal.scrollTop,
    focus = document.activeElement?.id;
  let html =
    s.view === "history"
      ? recoveryHistory(s)
      : s.view === "archive"
        ? recoveryArchive(s)
        : recoveryRepair(s);
  html += `<p class="error" role="alert">${esc(s.error || "")}</p>`;
  modal.innerHTML = html;
  modal.scrollTop = scroll;
  if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
}
async function recoveryJob(s, kind, body = {}, existingId = null) {
  if (!recoveryCurrent(s) || s.busy) return;
  s.busy = true;
  s.error = "";
  s.progress = null;
  s.kind = kind;
  s.job = null;
  s.cancelling = false;
  drawRecovery();
  try {
    const job = existingId ? {id:existingId} : await api("recovery-start", { kind, ...body });
    if (!recoveryCurrent(s)) return;
    s.job = job.id;
    for (;;) {
      const result = await api("recovery-job", { id: job.id });
      if (!recoveryCurrent(s)) return;
      s.progress = result.progress;
      if (result.status === "completed") {
        if (kind === "preview-unpack") {
          s.archive = result.result;
          s.result = null;
          s.cancelled = false;
        } else if (kind === "unpack-reseed") {
          s.result = result.result;
          api("scan", {}).catch((error) => {
            if (recoveryCurrent(s)) {
              s.error = error.message;
              drawRecovery();
            }
          });
        } else if (kind === "refresh-unpack")
          s.result = { ...s.result, ...result.result };
        else s.row = result.result;
        break;
      }
      if (result.status === "cancelled") {
        s.cancelled = true;
        break;
      }
      if (!["queued", "running"].includes(result.status))
        throw new Error(
          result.error ||
            t(
              "Opération interrompue. Inspectez le client avant de réessayer.",
              "Operation interrupted. Inspect the client before retrying.",
            ),
        );
      drawRecovery();
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  } catch (error) {
    if (recoveryCurrent(s)) {
      s.error = error.message;
      // Reload the persisted journal after an uncertain mutation, never replay the request.
      if (
        ["prepare-repair", "start-repair", "refresh-repair"].includes(kind) &&
        s.row
      ) {
        try {
          const rows = await api("inspect", { path: "", action: "repairs" });
          if (recoveryCurrent(s))
            s.row = rows.find((r) => r.id === s.row.id) || {
              ...s.row,
              status: "needs-review",
            };
        } catch {
          s.row = { ...s.row, status: "needs-review" };
        }
      }
    }
  } finally {
    if (recoveryCurrent(s)) {
      s.busy = false;
      drawRecovery();
    }
  }
}
async function openRecovery(view, body = {}) {
  if (recoveryCurrent(recovery || {}) && recovery.busy) {
    $("recovery-dialog").showModal();
    return;
  }
  if (
    recoveryCurrent(recovery || {}) &&
    view === "archive" &&
    recovery.view === "archive" &&
    recovery.body.path === body.path &&
    recovery.body.key === body.key &&
    recovery.result
  ) {
    drawRecovery();
    if (!$("recovery-dialog").open) $("recovery-dialog").showModal();
    return;
  }
  const s = (recovery = {
    view,
    generation,
    body,
    busy: false,
    error: "",
    destination: "",
    opt: false,
    row: null,
    history: [],
    details: false,
  });
  drawRecovery();
  if (!$("recovery-dialog").open) $("recovery-dialog").showModal();
  if (view === "history") {
    s.busy = true;
    s.phase = t("Chargement…", "Loading…");
    drawRecovery();
    try {
      const rows = await api("inspect", { path: "", action: "repairs" });
      if (recoveryCurrent(s)) s.history = rows;
    } catch (e) {
      s.error = e.message;
    } finally {
      if (recoveryCurrent(s)) {
        s.busy = false;
        drawRecovery();
      }
    }
  } else {
    const pending = (snapshot.jobs || []).find(j => j.subject?.path === body.path && (view === "archive" ? /unpack/.test(j.kind) : /repair/.test(j.kind)) && ["queued", "running"].includes(j.status));
    await recoveryJob(
      s,
      pending?.kind || (view === "archive" ? "preview-unpack" : "diagnose-repair"),
      { path: body.path, candidate_key: body.key },
      pending?.id,
    );
  }
}
function drawRecoveryFolder(s) {
  const d = $("recovery-folder");
  d.innerHTML = `<h2>${t("Dossiers du serveur TorrentLinker", "Folders on the TorrentLinker server")}</h2><p class="recovery-path">${esc(s.folder.path || t("Racines montées", "Mounted roots"))}</p>${s.folder.path ? `<button data-recovery-folder="${esc(s.folder.parent)}">↑</button><button data-recovery-pick="${esc(s.folder.path)}">${t("Choisir ce dossier", "Choose this folder")}</button>` : ""}${s.folder.folders.map((p) => `<button data-recovery-folder="${esc(p)}">${esc(p)}</button>`).join("")}<button data-recovery="close-folder">${t("Annuler", "Cancel")}</button>`;
}
function drawRecoveryConfirmation(s) {
  const d = $("recovery-confirm");
  d.innerHTML = `<div class="eyebrow">${t("CONFIRMATION SÉPARÉE", "SEPARATE CONFIRMATION")}</div><h2>${t("Télécharger dans cette copie ?", "Download into this copy?")}</h2><p class="recovery-path">${esc(s.row.copy)}</p><p>${t("L’original est conservé. Le trafic réseau peut dépasser le contenu manquant estimé.", "The original is kept. Network traffic may exceed the estimated missing content.")} ${bytes(s.row.missing_bytes)}</p>${recoveryButtons(`<button data-recovery="cancel-confirm">${t("Annuler", "Cancel")}</button><button class="primary" data-recovery="download">${t("Confirmer le téléchargement", "Confirm download")}</button>`)}`;
}
async function browseRecovery(path = "") {
  const s = recovery;
  try {
    const result = await api("browse", { path });
    if (!recoveryCurrent(s)) return;
    if (environment.mode === "desktop") {
      if (result.selected) s.destination = result.selected;
      drawRecovery();
      return;
    }
    s.folder = result;
    drawRecoveryFolder(s);
    const d = $("recovery-folder");
    if (!d.open) d.showModal();
  } catch (e) {
    if (recoveryCurrent(s)) {
      s.error = e.message;
      drawRecovery();
    }
  }
}
document.addEventListener(
  "click",
  async (e) => {
    const button = e.target.closest(
      "[data-recovery],[data-repair-id],[data-recovery-folder],[data-recovery-pick]",
    );
    if (!button || !recoveryCurrent(recovery || {})) return;
    e.stopImmediatePropagation();
    const s = recovery,
      a = button.dataset.recovery;
    if (button.dataset.repairId) {
      s.row = s.history.find((r) => r.id === button.dataset.repairId);
      s.view = "repair";
      s.opt = false;
      drawRecovery();
      const pending = (snapshot.jobs || []).find(j => j.subject?.repair_id === s.row.id && ["queued", "running"].includes(j.status));
      if (pending) await recoveryJob(s, pending.kind, {}, pending.id);
      return;
    }
    if (button.hasAttribute("data-recovery-folder")) {
      await browseRecovery(button.dataset.recoveryFolder);
      return;
    }
    if (button.hasAttribute("data-recovery-pick")) {
      s.destination = button.dataset.recoveryPick;
      $("recovery-folder").close();
      drawRecovery();
      return;
    }
    if (a === "close") {
      $("recovery-dialog").close();
      return;
    }
    if (a === "close-folder") {
      $("recovery-folder").close();
      return;
    }
    if (a === "cancel-confirm") {
      $("recovery-confirm").close();
      return;
    }
    if (s.busy && a !== "cancel") return;
    if (a === "browse") return browseRecovery(s.destination);
    if (a === "review")
      return recoveryJob(s, "preview-unpack", {
        path: s.body.path,
        candidate_key: s.body.key,
      });
    if (a === "extract")
      return recoveryJob(s, "unpack-reseed", {
        path: s.body.path,
        candidate_key: s.body.key,
        confirmation: s.archive.token,
      });
    if (a === "prepare" && s.opt && s.destination.trim())
      return recoveryJob(s, "prepare-repair", {
        repair_id: s.row.id,
        client_path: s.destination.trim(),
        experimental: true,
      });
    if (a === "archive-refresh")
      return recoveryJob(s, "refresh-unpack", { hashes: [s.result.hash] });
    if (a === "refresh")
      return recoveryJob(s, "refresh-repair", { repair_id: s.row.id });
    if (a === "cancel") {
      s.cancelling = true;
      drawRecovery();
      try {
        await api("recovery-cancel", { id: s.job });
      } catch (e) {
        s.error = e.message;
      }
      drawRecovery();
      return;
    }
    if (a === "confirm" && s.row.status === "ready") {
      const d = $("recovery-confirm");
      s.confirmation = s.row.id;
      drawRecoveryConfirmation(s);
      d.showModal();
    }
    if (
      a === "download" &&
      $("recovery-confirm").open &&
      s.confirmation === s.row.id
    ) {
      $("recovery-confirm").close();
      const confirmation = s.confirmation;
      s.confirmation = null;
      return recoveryJob(s, "start-repair", {
        repair_id: s.row.id,
        confirmation,
      });
    }
  },
  true,
);
document.addEventListener("input", (e) => {
  if (!recovery) return;
  if (e.target.id === "repair-path") recovery.destination = e.target.value;
  if (e.target.id === "repair-opt") recovery.opt = e.target.checked;
  const b = $("repair-prepare");
  if (b) b.disabled = !recovery.opt || !recovery.destination.trim();
});
document.addEventListener(
  "toggle",
  (e) => {
    if (e.target.id === "repair-limits" && recovery)
      recovery.details = e.target.open;
  },
  true,
);
let recoveryRequestId = null,
  recoveryLanguage = environment.language;
window.addEventListener("reseed-environment", () => {
  if (recovery && !recoveryCurrent(recovery)) {
    for (const id of ["recovery-dialog", "recovery-confirm", "recovery-folder"])
      $(id).close();
    recovery = null;
  } else if (
    recovery &&
    $("recovery-dialog").open &&
    recoveryLanguage !== environment.language
  ) {
    drawRecovery();
    if ($("recovery-confirm").open) drawRecoveryConfirmation(recovery);
    if ($("recovery-folder").open) drawRecoveryFolder(recovery);
  }
  recoveryLanguage = environment.language;
  const request = environment.recovery_request;
  if (request && request.id !== recoveryRequestId) {
    recoveryRequestId = request.id;
    openRecovery(request.view, { path: request.path, key: request.key });
  }
});

setInterval(() => {
  const s = recovery;
  if (
    s &&
    recoveryCurrent(s) &&
    active &&
    $("recovery-dialog").open &&
    !s.busy &&
    !s.error &&
    s.view === "repair" &&
    ["checking", "downloading"].includes(s.row?.status)
  )
    recoveryJob(s, "refresh-repair", { repair_id: s.row.id });
  if (
    s &&
    recoveryCurrent(s) &&
    active &&
    $("recovery-dialog").open &&
    !s.busy &&
    !s.error &&
    s.view === "archive" &&
    s.result?.status === "verifying"
  )
    recoveryJob(s, "refresh-unpack", { hashes: [s.result.hash] });
}, 4000);
