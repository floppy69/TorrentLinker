"use strict";
let trackerDialogGeneration = 0;
const trackerReason = (reason) =>
  ({
    supported: t("Pris en charge", "Supported"),
    update: t("À modifier", "To update"),
    already_current: t(
      "À jour ou groupe non sélectionné",
      "Current or unselected group",
    ),
    unsupported_client: t(
      "Modification avec réannonce non prise en charge par ce client",
      "Tracker editing with reannounce is unavailable for this client",
    ),
    client_unavailable: t("Client indisponible", "Client unavailable"),
    tracker_read_failed: t(
      "Lecture des trackers impossible",
      "Could not read trackers",
    ),
    unsupported_passkey_format: t(
      "Format de passkey non reconnu",
      "Unrecognized passkey format",
    ),
    mixed_passkeys: t(
      "Plusieurs passkeys dans ce torrent",
      "Multiple passkeys in this torrent",
    ),
    duplicate_target: t(
      "Le remplacement créerait un doublon",
      "Replacement would create a duplicate",
    ),
    tier_limit: t("Limite de niveaux atteinte", "Tracker tier limit reached"),
    updated: t("Modifié et réannoncé", "Updated and reannounced"),
    uncertain: t(
      "Résultat incertain · refaire un aperçu avant de réessayer",
      "Uncertain result · preview again before retrying",
    ),
    changed_since_preview: t(
      "Trackers modifiés depuis l’aperçu",
      "Trackers changed since preview",
    ),
    updated_reannounce_failed: t(
      "Modifié · réannonce à vérifier",
      "Updated · check reannounce",
    ),
  })[reason] || reason;
async function trackerJob(action, body, token) {
  const { id } = await request(action, body);
  while (token === trackerDialogGeneration && $("dialog").open) {
    const job = await request("tracker-job", { id });
    if (token !== trackerDialogGeneration || !$("dialog").open) return null;
    $("tracker-progress").textContent =
      job.status === "queued"
        ? t("En attente…", "Queued…")
        : `${t("En cours", "Running")} · ${job.progress?.done || 0}${job.progress?.total != null ? "/" + job.progress.total : ""}`;
    if (!["queued", "running"].includes(job.status)) {
      $("tracker-progress").textContent = "";
      if (job.status !== "completed")
        throw Error(
          job.error || t("Opération interrompue", "Operation interrupted"),
        );
      return job.result;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return null;
}
async function openTrackerUpdates() {
  const token = ++trackerDialogGeneration;
  const settings = await request("tracker-settings");
  if (token !== trackerDialogGeneration) return;
  const d = $("dialog");
  d.innerHTML = `<h2>${t("Trackers c411", "c411 trackers")}</h2><p class="muted">${t("Tous les torrents c411 des clients choisis, y compris ceux ajoutés ailleurs. Les autres trackers restent inchangés. Seules des empreintes de passkey sont affichées.", "All c411 torrents on the chosen clients, including torrents added elsewhere. Other trackers stay unchanged. Only passkey fingerprints are shown.")}</p><fieldset><legend>${t("Clients", "Clients")}</legend>${settings.clients.map((p) => `<label><input type="checkbox" data-tracker-client="${escape(p.id)}" ${client === "all" || client === p.id ? "checked" : ""}> ${escape(p.name)}</label>`).join("")}</fieldset><label class="tracker-field">${t("Action", "Action")}<select id="tracker-action"><option value="add-backup">${t("Ajouter un hôte de secours", "Add backup host")}</option><option value="replace-host">${t("Remplacer un hôte", "Replace host")}</option><option value="update-passkey">${t("Utiliser la passkey de Settings", "Use passkey from Settings")}</option></select></label><label class="tracker-field" id="tracker-source-field">${t("Ancien hôte", "Old host")}<input id="tracker-source" value="${escape(settings.hosts[0] || "c411.org")}"></label><label class="tracker-field" id="tracker-target-field">${t("Nouvel hôte / secours", "New / backup host")}<select id="tracker-target">${settings.hosts.map((h, i) => `<option ${i === 1 ? "selected" : ""}>${escape(h)}</option>`).join("")}</select></label><div id="tracker-groups"></div><div class="toolbar"><button id="tracker-preview" class="primary">${t("Aperçu", "Preview")}</button><button id="tracker-apply" disabled>${t("Appliquer les changements examinés", "Apply reviewed changes")}</button><button id="tracker-close">${t("Fermer", "Close")}</button></div><p id="tracker-progress" role="status"></p><p id="tracker-error" class="error" role="alert"></p><div id="tracker-report"></div>`;
  d.dataset.trackerDialog = "true";
  d.showModal();
  let reviewed = null,
    reviewedIntent = "",
    busy = false;
  const intent = () => ({
    client_ids: [...d.querySelectorAll("[data-tracker-client]:checked")].map(
      (n) => n.dataset.trackerClient,
    ),
    tracker_action: $("tracker-action").value,
    tracker_source_host: $("tracker-source").value.trim(),
    tracker_target_host: $("tracker-target").value,
    tracker_groups: [...d.querySelectorAll("[data-tracker-group]:checked")].map(
      (n) => n.dataset.trackerGroup,
    ),
  });
  const changed = () => {
    const action = $("tracker-action").value;
    $("tracker-source-field").hidden = action !== "replace-host";
    $("tracker-target-field").hidden = action === "update-passkey";
    $("tracker-groups").hidden = action !== "update-passkey";
    $("tracker-apply").disabled =
      busy ||
      !reviewed ||
      reviewedIntent !== JSON.stringify(intent()) ||
      !reviewed.counts.update;
  };
  d.oninput = changed;
  d.addEventListener(
    "close",
    () => {
      d.oninput = null;
      delete d.dataset.trackerDialog;
    },
    { once: true },
  );
  $("tracker-close").onclick = () => {
    trackerDialogGeneration++;
    d.close();
  };
  const run = async (apply) => {
    if (busy) return;
    const body = intent();
    if (!body.client_ids.length)
      throw Error(t("Choisissez un client.", "Choose a client."));
    if (apply && (!reviewed || reviewedIntent !== JSON.stringify(body)))
      throw Error(t("Refaites l’aperçu.", "Preview again."));
    if (
      apply &&
      !confirm(
        t(
          `Appliquer aux ${reviewed.counts.update} torrents examinés ?`,
          `Apply to the ${reviewed.counts.update} reviewed torrents?`,
        ),
      )
    )
      return;
    busy = true;
    changed();
    $("tracker-preview").disabled = true;
    $("tracker-error").textContent = "";
    try {
      const result = await trackerJob(
        apply ? "tracker-update" : "tracker-preview",
        { ...body, tracker_preview_id: apply ? reviewed.preview_id : "" },
        token,
      );
      if (!result || token !== trackerDialogGeneration) return;
      if (apply) {
        reviewed = null;
        $("tracker-report").replaceChildren();
        const summary = document.createElement("p");
        const counts = {};
        for (const row of result.rows)
          counts[row.status] = (counts[row.status] || 0) + 1;
        summary.textContent = Object.entries(counts)
          .map(([status, n]) => `${n} ${trackerReason(status)}`)
          .join(" · ");
        $("tracker-report").append(summary);
        trackerRows($("tracker-report"), result.rows);
      } else {
        reviewed = result;
        reviewedIntent = JSON.stringify(body);
        const groups = Object.keys(result.groups);
        $("tracker-groups").innerHTML =
          `<fieldset><legend>${t("Groupes de passkey à remplacer", "Passkey groups to update")}</legend>${groups.map((group) => `<label><input type="checkbox" data-tracker-group="${escape(group)}" ${body.tracker_groups.includes(group) ? "checked" : ""} ${group === result.settings_group ? "disabled" : ""}> ${escape(group)} ${group === result.settings_group ? t("· Settings", "· Settings") : ""}</label>`).join("")}<small>${t("Sélectionnez les groupes puis refaites l’aperçu. Les actions d’hôte conservent chaque passkey.", "Select groups, then preview again. Host actions retain each passkey.")}</small></fieldset>`;
        $("tracker-report").innerHTML =
          Object.entries(result.clients)
            .map(
              ([id, counts]) =>
                `<h3>${escape(settings.clients.find((p) => p.id === id)?.name || id)}</h3><p>${escape(trackerReason(result.capabilities[id]))}</p><p>${Object.entries(
                  counts,
                )
                  .map(([reason, n]) => `${n} ${escape(trackerReason(reason))}`)
                  .join(" · ")}</p>`,
            )
            .join("") +
          Object.entries({ ...result.hosts, ...result.groups })
            .map(
              ([key, counts]) =>
                `<p>${escape(key)} · ${Object.entries(counts)
                  .map(([reason, n]) => `${n} ${escape(trackerReason(reason))}`)
                  .join(" · ")}</p>`,
            )
            .join("");
        trackerRows($("tracker-report"), result.rows);
      }
    } catch (error) {
      if (token === trackerDialogGeneration)
        $("tracker-error").textContent = error.message;
    } finally {
      if (token === trackerDialogGeneration) {
        busy = false;
        $("tracker-preview").disabled = false;
        changed();
      }
    }
  };
  changed();
  $("tracker-preview").onclick = (event) => guard(() => run(false), event.currentTarget);
  $("tracker-apply").onclick = (event) => guard(() => run(true), event.currentTarget);
}
window.addEventListener("DOMContentLoaded", () => {
  $("dialog").addEventListener("close", () => trackerDialogGeneration++);
  $("dialog").addEventListener("cancel", () => trackerDialogGeneration++);
});

function trackerRows(parent, rows) {
  const details = document.createElement("details");
  details.innerHTML = `<summary>${rows.length} ${t("torrents examinés", "reviewed torrents")}</summary><label><input type="checkbox" data-skipped> ${t("Ignorés / échecs uniquement", "Skipped / failed only")}</label><div data-rows></div><div class="toolbar"><button data-previous>${t("Précédent", "Previous")}</button><span data-page></span><button data-next>${t("Suivant", "Next")}</button></div>`;
  parent.append(details);
  let page = 0;
  const render = () => {
    const selected = details.querySelector("[data-skipped]").checked
      ? rows.filter((r) => (r.reason ? !r.update : r.status !== "updated"))
      : rows;
    const pages = Math.max(1, Math.ceil(selected.length / 100));
    page = Math.min(page, pages - 1);
    details.querySelector("[data-rows]").innerHTML = selected
      .slice(page * 100, (page + 1) * 100)
      .map(
        (row) =>
          `<p>${escape(row.client_id)} · ${escape(row.hash)}<br>${escape((row.hosts || []).join(", "))} · ${escape((row.groups || []).join(", "))}<br>${escape(trackerReason(row.reason || row.status))}</p>`,
      )
      .join("");
    details.querySelector("[data-page]").textContent = `${page + 1} / ${pages}`;
    details.querySelector("[data-previous]").disabled = page === 0;
    details.querySelector("[data-next]").disabled = page + 1 >= pages;
  };
  details.querySelector("[data-skipped]").onchange = () => {
    page = 0;
    render();
  };
  details.querySelector("[data-previous]").onclick = () => {
    page--;
    render();
  };
  details.querySelector("[data-next]").onclick = () => {
    page++;
    render();
  };
  render();
}
