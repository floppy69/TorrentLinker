"use strict";
const auditNames = () => ({
  present: t("Présent", "Present"),
  deleted: t("Supprimé (confirmé)", "Deleted (confirmed)"),
  suspect: t("Suspect", "Suspect"),
  unknown: t("Inconnu", "Unknown"),
});
const auditReasons = () => ({
  single_404: t(
    "Un seul 404, confirmation en attente",
    "One 404, awaiting confirmation",
  ),
  two_404: t(
    "Deux 404 espacés d’au moins 60 s",
    "Two 404s at least 60 seconds apart",
  ),
  rate_limited: t("Limite de requêtes", "Rate limited"),
  key_refused: t("Clé refusée", "Key refused"),
  timeout: t("Délai dépassé", "Timeout"),
  server_error: t("Erreur serveur", "Server error"),
  network_error: t("Erreur réseau", "Network error"),
  lookup_failed: t("Lecture impossible", "Lookup failed"),
  not_checked: t("En attente", "Pending"),
  stopped_before_checking: t(
    "Arrêté avant vérification",
    "Stopped before checking",
  ),
  interrupted: t("Interrompu au redémarrage", "Interrupted by restart"),
  audit_unavailable: t("Audit indisponible", "Audit unavailable"),
  report_not_saved: t(
    "Le rapport n’a pas pu être enregistré",
    "The report could not be saved",
  ),
  client_unavailable: t("Client indisponible", "Client unavailable"),
  stopped_before_listing: t(
    "Arrêté avant lecture du client",
    "Stopped before listing client",
  ),
});
let auditToken = 0;
async function openAudit() {
  const token = ++auditToken,
    d = $("dialog");
  const { reports } = await request("audit-list");
  if (token !== auditToken) return;
  d.innerHTML = `<h2>${t("Audit c411", "c411 audit")}</h2><p class="muted">${t("Lecture seule. Tous les torrents c411 du client cible sont examinés, avec le filtre de tag actuel. Les autres filtres ne s’appliquent pas. Aucun torrent n’est modifié. Une suppression nécessite deux 404 espacés d’au moins 60 secondes.", "Read only. Checks all c411 torrents on the target client, narrowed by the current tag filter. Other filters do not apply. No torrent is changed. Deletion requires two 404s at least 60 seconds apart.")}</p><p>${t("Client cible", "Target client")}: ${escape(client)} · ${t("Tag", "Tag")}: ${escape(filters.tag || t("Tous", "All"))}</p><button id="audit-start" class="primary">${t("Lancer l’audit", "Start audit")}</button><div id="audit-reports">${reports.map((r) => `<p><button data-audit="${escape(r.id)}">${escape(new Date(r.created_at * 1000).toLocaleString())} · ${r.total} torrents</button></p>`).join("")}</div><button id="audit-close">${t("Fermer", "Close")}</button>`;
  d.showModal();
  $("audit-close").onclick = () => {
    auditToken++;
    d.close();
  };
  d.querySelectorAll("[data-audit]").forEach(
    (b) => (b.onclick = (event) => guard(() => showAudit(b.dataset.audit), event.currentTarget)),
  );
  $("audit-start").onclick = (event) =>
    guard(async () => {
      $("audit-start").disabled = true;
      try {
        const report = await request("audit-start", {
          client_id: client,
          tag: filters.tag,
        });
        if (token === auditToken && d.open) await showAudit(report.id);
      } finally {
        if ($("audit-start")) $("audit-start").disabled = false;
      }
    }, event.currentTarget);
}
async function showAudit(id, offset = 0) {
  const token = ++auditToken,
    d = $("dialog");
  const report = await request("audit-report", { id, offset, limit: 100 });
  if (token !== auditToken) return;
  const names = auditNames(),
    reasons = auditReasons();
  const statuses = {
    running: t("En cours", "Running"),
    complete: t("Terminé", "Complete"),
    stopped: t("Arrêté", "Stopped"),
    interrupted: t("Interrompu", "Interrupted"),
    failed: t("Échec", "Failed"),
  };
  d.innerHTML = `<h2>${t("Rapport d’audit c411", "c411 audit report")}</h2><p role="status">${statuses[report.status] || ""}</p><p>${Object.entries(
    report.counts,
  )
    .map(([key, n]) => `${names[key]}: ${n}`)
    .join(
      " · ",
    )}</p><p class="muted">${report.checked_hashes} ${t("empreintes vérifiées", "distinct hashes checked")}</p>${Object.entries(
    report.clients,
  )
    .map(
      ([key, counts]) =>
        `<p>${escape(key)}: ${Object.entries(counts)
          .map(([k, n]) => `${names[k]} ${n}`)
          .join(" · ")}</p>`,
    )
    .join(
      "",
    )}${report.errors.map((e) => `<p role="status">${escape(e.client_id || "")}: ${escape(reasons[e.reason] || t("Indisponible", "Unavailable"))}</p>`).join("")}<div class="table-scroll"><table class="torrent-list"><thead><tr><th>${t("Torrent / client", "Torrent / client")}</th><th>${t("Résultat", "Result")}</th></tr></thead><tbody>${report.rows.map((r) => `<tr><td class="name">${escape(r.name)}<br><small>${escape(r.client_name)} · ${escape(r.hash)}<br>${escape(r.tags.join(", "))}</small></td><td>${names[r.classification]}<br><small>${escape(reasons[r.reason] || "")}</small></td></tr>`).join("")}</tbody></table></div><p>${Math.min(offset + 1, report.total)}–${Math.min(offset + report.rows.length, report.total)} / ${report.total}</p><div class="toolbar"><button id="audit-prev" ${offset ? "" : "disabled"}>${t("Précédent", "Previous")}</button><button id="audit-next" ${offset + report.rows.length < report.total ? "" : "disabled"}>${t("Suivant", "Next")}</button><button id="audit-refresh">${t("Actualiser", "Refresh")}</button>${report.status === "running" ? `<button id="audit-stop">${t("Arrêter l’audit", "Stop audit")}</button>` : ""}<button data-export="json">JSON</button><button data-export="csv">CSV</button><button id="audit-back">${t("Historique", "History")}</button><button id="audit-close">${t("Fermer", "Close")}</button></div>`;
  if (!d.open) d.showModal();
  $("audit-close").onclick = () => {
    auditToken++;
    d.close();
  };
  $("audit-back").onclick = (event) => guard(openAudit, event.currentTarget);
  $("audit-refresh").onclick = (event) => guard(() => showAudit(id, offset), event.currentTarget);
  $("audit-prev").onclick = (event) =>
    guard(() => showAudit(id, Math.max(0, offset - 100)), event.currentTarget);
  $("audit-next").onclick = (event) => guard(() => showAudit(id, offset + 100), event.currentTarget);
  if ($("audit-stop"))
    $("audit-stop").onclick = (event) =>
      guard(async () => {
        await request("audit-stop", { id });
        if (token === auditToken && d.open) await showAudit(id, offset);
      }, event.currentTarget);
  d.querySelectorAll("[data-export]").forEach(
    (button) =>
      (button.onclick = (event) =>
        guard(async () => {
          if (environment.mode === "desktop") {
            await request("audit-save-export", {
              id,
              format: button.dataset.export,
            });
            return;
          }
          const result = await request("audit-export", {
            id,
            format: button.dataset.export,
          });
          const link = document.createElement("a"),
            url = URL.createObjectURL(
              new Blob([result.content], {
                type:
                  button.dataset.export === "json"
                    ? "application/json"
                    : "text/csv",
              }),
            );
          link.href = url;
          link.download = result.filename;
          link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }, event.currentTarget)),
  );
  if (report.status === "running")
    setTimeout(() => {
      if (d.open && token === auditToken) guard(() => showAudit(id, offset));
    }, 2000);
}

window.addEventListener("DOMContentLoaded", () => {
  $("dialog").addEventListener("close", () => {
    auditToken++;
  });
  $("dialog").addEventListener("cancel", () => {
    auditToken++;
  });
});
