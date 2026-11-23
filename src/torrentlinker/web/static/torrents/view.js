let queryTimer;
const sizeUnits = { sizeMin: "GiB", sizeMax: "GiB" };
const $ = (id) => document.getElementById(id),
  q = new URLSearchParams(location.search);
let lang = "en",
  mode = q.get("mode") || "desktop",
  theme = q.get("theme") || "dark",
  scenario = "loading",
  page = 0,
  focus = "",
  tab = "summary",
  selected = new Set(),
  query = "",
  filters = { state: "", category: "", tracker: "", tag: "" },
  client = "all",
  sortKey = "name",
  sortDir = 1,
  metrics = {
    scope: "",
    sizeMin: "",
    sizeMax: "",
    noteMin: "",
    zenMin: "",
    weightMin: "",
    seedMax: "",
    daysMin: "",
  };
const t = (fr, en) => (lang === "fr" ? fr : en);
const escape = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const cols = {
  client: true,
  size: true,
  progress: true,
  down: true,
  up: true,
  ratio: true,
  note: true,
  zen: true,
  weight: false,
  seeds: false,
  seedtime: false,
};
const labels = {
  client: () => t("Client", "Client"),
  size: () => t("Taille", "Size"),
  progress: () => t("Progression", "Progress"),
  down: () => t("Réception", "Download"),
  up: () => t("Envoi", "Upload"),
  ratio: () => t("Ratio", "Ratio"),
  note: () => t("Note c411", "c411 Note"),
  zen: () => t("≈ Zen / jour", "≈ Zen / day"),
  weight: () => t("Poids", "Weight"),
  seeds: () => t("Sources / pairs", "Seeders / peers"),
  seedtime: () => t("Durée de seed", "Seed time"),
};
let data = [],
  snapshot = {
    total: 0,
    clients: [],
    trackers: [],
    categories: [],
    tags: [],
    summary: {},
  },
  rowCache = new Map();
function matching() {
  return data;
}
function sortHeader(k, label) {
  return `<th aria-sort="${sortKey === k ? (sortDir === 1 ? "ascending" : "descending") : "none"}"><button class="sort-head" data-sort="${k}">${label} <span aria-hidden="true">${sortKey === k ? (sortDir === 1 ? "↑" : "↓") : "↕"}</span></button></th>`;
}
function metricControls() {
  return TLTorrentFilters.metrics({ metrics, sizeUnits, language: lang });
}

function stateText(s) {
  return {
    seeding: t("En partage", "Seeding"),
    paused: t("En pause", "Paused"),
    downloading: t("Téléchargement", "Downloading"),
    checking: t("Vérification", "Checking"),
    error: t("Erreur", "Error"),
    other: t("Autre", "Other"),
  }[s];
}
function notify(s, kind = "bad") {
  TLToast.show(s, kind);
}

function paint() {
  document.documentElement.dataset.theme = theme;
  const rows = matching(),
    slice = rows;
  const multi = client === "all";
  $("app").innerHTML =
    `${
      multi
        ? `<div class="stats">${[
            [
              snapshot.summary.count || 0,
              t("Torrents · tous les clients", "Torrents · all clients"),
            ],
            [
              formatBytes(snapshot.summary.download || 0) + "/s",
              t("Réception cumulée", "Total download"),
            ],
            [
              formatBytes(snapshot.summary.upload || 0) + "/s",
              t("Envoi cumulé", "Total upload"),
            ],
          ]
            .map(
              ([v, k]) =>
                `<div class="panel stat"><small>${k}</small><strong>${v}</strong></div>`,
            )
            .join("")}</div>`
        : ""
    }<div class="toolbar"><button id="columns">${t("Colonnes", "Columns")}</button><button id="refresh">${t("Actualiser", "Refresh")}</button><button id="tracker-updates">${t("Trackers c411…", "c411 trackers…")}</button><button id="audit-history">${t("Audit c411", "c411 audit")}</button><button id="transfer-history">${t("Transferts", "Transfers")}</button><button id="trackers">${t("Vue par tracker", "Group by tracker")}</button><span class="muted">${t("Actualisation toutes les 5 s · sélection conservée", "Refresh every 5 s · selection preserved")}</span></div><div class="workspace"><section class="panel">${TLTorrentFilters.controls({ query, filters, language: lang, options: { state: ["seeding", "downloading", "paused", "checking", "error", "other"], category: snapshot.categories, tracker: snapshot.trackers, tag: snapshot.tags } })}${metricControls()}<div class="status"><span>${selected.size} ${t("sélectionné(s)", "selected")}</span><div class="toolbar"><button data-action="resume" ${selected.size ? "" : "disabled"}>${t("Reprendre", "Resume")}</button><button data-action="pause" ${selected.size ? "" : "disabled"}>${t("Suspendre", "Pause")}</button><button id="transfer-selection" ${selected.size ? "" : "disabled"}>${t("Transférer…", "Transfer…")}</button><button id="more-actions" ${selected.size ? "" : "disabled"}>${t("Plus…", "More…")}</button><button data-action="remove" ${selected.size ? "" : "disabled"}>${t("Retirer…", "Remove…")}</button></div></div>${
      scenario === "normal"
        ? `<div class="table-scroll"><table class="torrent-list"><thead><tr><th><input type="checkbox" id="select-page" aria-label="${t("Sélectionner la page", "Select page")}" ${slice.length && slice.every((r) => selected.has(r.id)) ? "checked" : ""}></th>${sortHeader("name", t("Torrent / état", "Torrent / state"))}${Object.entries(
            cols,
          )
            .filter(([, v]) => v)
            .map(([k]) => sortHeader(k, labels[k]()))
            .join(
              "",
            )}</tr></thead><tbody>${!slice.length ? `<tr><td colspan="${2 + Object.values(cols).filter(Boolean).length}" class="empty">${t("Aucun torrent pour ces filtres.", "No torrents match these filters.")}</td></tr>` : ""}${slice
            .map(
              (r) =>
                `<tr class="${focus === r.id ? "active" : ""}"><td><input data-select="${escape(r.id)}" type="checkbox" ${selected.has(r.id) ? "checked" : ""} aria-label="${escape(r.name)}"></td><td class="name"><button class="link" data-open="${escape(r.id)}">${escape(r.name)}</button><br><small>${stateText(r.state)} · ${escape(r.category)}</small></td>${Object.entries(
                  cols,
                )
                  .filter(([, v]) => v)
                  .map(
                    ([k]) =>
                      `<td>${{ client: escape(r.client), size: formatBytes(r.raw.size), progress: r.progress + '%<div class="progress"><i style="width:' + r.progress + '%"></i></div>', down: formatBytes(r.raw.download) + "/s", up: formatBytes(r.raw.upload) + "/s", ratio: r.ratio.toFixed(2), note: r.note == null ? "—" : r.note.toFixed(2), zen: r.zen == null ? "—" : "≈ " + r.zen.toFixed(2), weight: r.weight == null ? "—" : r.weight.toFixed(3), seeds: peerText(r.raw.seeds, r.raw.total_seeds) + " / " + peerText(r.raw.peers, r.raw.total_peers), seedtime: r.seedtime.toFixed(1) + " " + t("jours", "days") }[k]}</td>`,
                  )
                  .join("")}</tr>`,
            )
            .join("")}</tbody></table></div>`
        : `<div class="empty">${{ empty: t("Aucun torrent pour ces filtres.", "No torrents match these filters."), loading: t("Chargement des torrents…", "Loading torrents…"), error: escape(TLToast.translate(lastError)) }[scenario]}${scenario === "error" ? `<p><button id="retry">${t("Réessayer", "Retry")}</button></p>` : ""}</div>`
    }<div class="status"><small>${snapshot.total.toLocaleString()} torrents · ${t("100 lignes par page", "100 rows per page")}</small><div><button id="prev" ${page ? "" : "disabled"}>←</button> ${page + 1} / ${Math.max(1, Math.ceil(snapshot.total / 100))} <button id="next" ${(page + 1) * 100 >= snapshot.total ? "disabled" : ""}>→</button></div></div></section><section class="panel inspector" id="inspector"></section></div>`;
  bind();
  inspect();
}
function inspect() {
  const r = rowCache.get(focus);
  if (!r) {
    $("inspector").textContent = t(
      "Sélectionnez un torrent.",
      "Select a torrent.",
    );
    return;
  }
  const kv = (label, value) =>
    `<div class="kv"><span>${label}</span><b>${escape(value ?? "—")}</b></div>`;
  $("inspector").innerHTML =
    `<small>${t("LE TORRENT SÉLECTIONNÉ", "SELECTED TORRENT")}</small><h2>${escape(r.name)}</h2><p><span class="badge">${stateText(r.state)}</span> <small>${escape(r.client)}</small></p><div class="tabs">${[
      ["summary", t("Résumé", "Summary")],
      ["files", t("Fichiers", "Files")],
      ["trackers", "Trackers"],
    ]
      .map(
        ([id, n]) =>
          `<button data-tab="${id}" class="${tab === id ? "selected" : ""}">${n}</button>`,
      )
      .join("")}</div><div id="inspection-body"></div>`;
  const body = $("inspection-body");
  if (tab === "summary") {
    body.innerHTML =
      kv(t("Taille", "Size"), formatBytes(r.raw.size)) +
      kv("Ratio", r.ratio.toFixed(2)) +
      kv(t("Catégorie", "Category"), r.category) +
      kv("Tags", r.raw.tags.join(", ")) +
      `<h3>${t("Seed et récompenses", "Seed and rewards")}</h3>` +
      kv(
        t("Sources / pairs", "Seeders / peers"),
        peerText(r.raw.seeds, r.raw.total_seeds) +
          " / " +
          peerText(r.raw.peers, r.raw.total_peers),
      ) +
      kv(
        t("Durée de seed", "Seed time"),
        r.seedtime.toFixed(1) + " " + t("jours", "days"),
      ) +
      (r.c411
        ? kv("≈ Note c411", r.note?.toFixed(2)) +
          kv(t("≈ Poids", "≈ Weight"), r.weight?.toFixed(3)) +
          kv(t("≈ Zen / jour", "≈ Zen / day"), r.zen?.toFixed(2)) +
          `<p class="muted">${t("Estimation locale selon votre profil. Certaines règles Zen restent incertaines. Sources : client et catalogue ; ? = inconnu.", "Local estimate using your profile. Some Zen rules remain uncertain. Sources: client and catalogue; ? = unknown.")}</p>`
        : `<p class="muted">${t("Hors c411 : Note, poids et Zen non applicables.", "Non-c411: Note, weight and Zen are not applicable.")}</p>`) +
      `<p class="muted">${t("Client observé", "Client observed")}: ${r.raw.observed_at ? escape(new Date(r.raw.observed_at * 1000).toLocaleString(lang)) : "—"}</p>` +
      `<p class="muted">${escape(r.raw.folder)}</p><button id="focus-toggle">${r.state === "paused" ? t("Reprendre", "Resume") : t("Suspendre", "Pause")}</button>`;
    $("focus-toggle").onclick = (event) =>
      guard(() =>
        confirmAction(r.state === "paused" ? "resume" : "pause", [r]), event.currentTarget);
  } else if (tab === "trackers")
    body.textContent =
      r.raw.trackers.filter(Boolean).join(" · ") ||
      t("Aucun tracker", "No tracker");
  else {
    body.textContent = t("Chargement…", "Loading…");
    const key = focus;
    guard(async () => {
      const result = await request("files", {
        client_id: r.raw.client_id,
        hash: r.raw.hash,
      });
      if (focus !== key || tab !== "files") return;
      body.innerHTML = `<table class="files">${result.files.map((f) => `<tr><td>${escape(f.name)}<br><small>${formatBytes(f.size)}</small></td><td><select data-file="${f.index}" aria-label="${escape(f.name)}"><option value="want_files" ${f.wanted ? "selected" : ""}>${t("Télécharger", "Download")}</option><option value="skip_files" ${!f.wanted ? "selected" : ""}>${t("Ignorer", "Skip")}</option></select></td></tr>`).join("")}</table>`;
      body.querySelectorAll("[data-file]").forEach(
        (e) =>
          (e.onchange = () => {
            const action = e.value;
            const file = result.files.find(
              (f) => f.index === Number(e.dataset.file),
            );
            // Keep the observed state until the reviewed command succeeds.
            e.value = file.wanted ? "want_files" : "skip_files";
            guard(() =>
              confirmAction(action, [r], {
                file_indexes: [file.index],
              }),
            );
          }),
      );
    });
  }
  $("inspector")
    .querySelectorAll("[data-tab]")
    .forEach(
      (b) =>
        (b.onclick = () => {
          tab = b.dataset.tab;
          inspect();
        }),
    );
}
function moreActions() {
  const chosen = [...selected].map((k) => rowCache.get(k)).filter(Boolean),
    d = $("dialog");
  const actions = [
    ["recheck", t("Vérifier les fichiers", "Recheck files")],
    ["reannounce", t("Réannoncer", "Reannounce")],
    ["limits", t("Limites de vitesse", "Speed limits")],
    ["category", t("Catégorie et tags", "Category and tags")],
    ["location", t("Changer le dossier", "Change location")],
  ];
  d.innerHTML = `<h2>${t("Actions sur la sélection", "Selection actions")}</h2><p>${chosen.length} torrents</p><div class="toolbar">${actions.map(([a, n]) => `<button data-more="${a}" ${chosen.every((r) => r.raw.capabilities.includes(a)) ? "" : `disabled title="${t("Non pris en charge par un client sélectionné", "Unsupported by a selected client")}"`}>${n}</button>`).join("")}</div><p class="muted">${t("Les opérations non prises en charge sont désactivées.", "Unsupported operations are disabled.")}</p><button id="close-more">${t("Fermer", "Close")}</button>`;
  d.showModal();
  $("close-more").onclick = () => d.close();
  d.querySelectorAll("[data-more]").forEach(
    (b) =>
      (b.onclick = () => {
        d.close();
        guard(() =>
          ["limits", "category", "location"].includes(b.dataset.more)
            ? editAction(b.dataset.more)
            : confirmAction(b.dataset.more),
        );
      }),
  );
}
function editAction(action) {
  const d = $("dialog");
  d.innerHTML = `<h2>${{ limits: t("Limites de vitesse", "Speed limits"), category: t("Catégorie et tags", "Category and tags"), location: t("Dossier du client actuel", "Current client folder") }[action]}</h2><p><label>${action === "limits" ? t("Réception KiB/s · 0 = illimité", "Download KiB/s · 0 = unlimited") : action === "category" ? t("Catégorie", "Category") : t("Chemin accessible au client", "Client-accessible path")}<input id="value" ${action === "limits" ? 'type="number" min="0" value="0"' : ""}></label></p>${action === "limits" ? `<label>${t("Envoi KiB/s", "Upload KiB/s")}<input id="second-value" type="number" min="0" value="0"></label>` : action === "category" ? `<label>Tags <input id="second-value"></label>` : ""}<p><button id="cancel-edit">${t("Annuler", "Cancel")}</button> <button id="apply-edit">${t("Examiner", "Review")}</button></p>`;
  d.showModal();
  $("cancel-edit").onclick = () => d.close();
  $("apply-edit").onclick = () => {
    const v = $("value").value,
      second = $("second-value")?.value;
    const payload =
      action === "limits"
        ? {
            download_limit: Number(v) * 1024,
            upload_limit: Number(second) * 1024,
          }
        : action === "category"
          ? {
              category: v,
              tags: (second || "")
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean),
            }
          : { path: v };
    d.close();
    guard(() => confirmAction(action, undefined, payload));
  };
}
function bind() {
  $("refresh").onclick = (event) => guard(load, event.currentTarget);
  $("tracker-updates").onclick = (event) => guard(openTrackerUpdates, event.currentTarget);
  $("audit-history").onclick = (event) => guard(openAudit, event.currentTarget);
  document.querySelectorAll("[data-sort]").forEach(
    (b) =>
      (b.onclick = () => {
        sortDir = sortKey === b.dataset.sort ? -sortDir : 1;
        sortKey = b.dataset.sort;
        page = 0;
        guard(load);
      }),
  );
  document.querySelectorAll("[data-metric]").forEach(
    (e) =>
      (e.onchange = () => {
        metrics[e.dataset.metric] = e.value;
        page = 0;
        guard(load);
      }),
  );
  document.querySelectorAll("[data-unit]").forEach((button) => {
    button.onclick = () => {
      const key = button.dataset.unit;
      const input = document.querySelector(`[data-metric="${key}"]`);
      const value = input.value;
      const toMiB = sizeUnits[key] === "GiB";
      sizeUnits[key] = toMiB ? "MiB" : "GiB";
      metrics[key] =
        value === "" ? "" : String(Number(value) * (toMiB ? 1024 : 1 / 1024));
      page = 0;
      render();
      guard(load);
    };
  });
  $("clear-filters").onclick = () => {
    Object.keys(metrics).forEach((k) => (metrics[k] = ""));
    Object.keys(filters).forEach((k) => (filters[k] = ""));
    query = "";
    page = 0;
    guard(load);
  };
  $("more-actions").onclick = moreActions;
  $("transfer-selection").onclick = (event) => guard(openTransfer, event.currentTarget);
  $("transfer-history").onclick = (event) => guard(transferHistory, event.currentTarget);
  $("query").oninput = (e) => {
    query = e.target.value;
    page = 0;
    clearTimeout(queryTimer);
    queryTimer = setTimeout(() => guard(load), 200);
  };
  document.querySelectorAll("[data-filter]").forEach(
    (s) =>
      (s.onchange = () => {
        filters[s.dataset.filter] = s.value;
        page = 0;
        guard(load);
      }),
  );
  document.querySelectorAll("[data-open]").forEach(
    (b) =>
      (b.onclick = () => {
        focus = b.dataset.open;
        render();
      }),
  );
  document.querySelectorAll("[data-select]").forEach(
    (c) =>
      (c.onchange = () => {
        c.checked
          ? selected.add(c.dataset.select)
          : selected.delete(c.dataset.select);
        render();
      }),
  );
  $("select-page") &&
    ($("select-page").onchange = (e) => {
      matching().forEach((r) =>
        e.target.checked ? selected.add(r.id) : selected.delete(r.id),
      );
      render();
    });
  $("prev").onclick = () => {
    page--;
    guard(load);
  };
  $("next").onclick = () => {
    page++;
    guard(load);
  };
  $("retry") &&
    ($("retry").onclick = () => {
      guard(load);
    });
  $("columns").onclick = () => {
    const d = $("dialog");
    d.innerHTML = `<h2>${t("Colonnes affichées", "Visible columns")}</h2><p class="muted">${t("Choix et largeurs conservés sur cet appareil.", "Choices and widths are saved on this device.")}</p>${Object.keys(
      cols,
    )
      .map(
        (k) =>
          `<label class="column"><input data-col="${k}" type="checkbox" ${cols[k] ? "checked" : ""}> ${labels[k]()}</label>`,
      )
      .join("")}<button id="done">${t("Terminé", "Done")}</button>`;
    d.showModal();
    d.querySelectorAll("[data-col]").forEach(
      (c) =>
        (c.onchange = () => {
          cols[c.dataset.col] = c.checked;
          savePreferences();
          render();
        }),
    );
    $("done").onclick = () => d.close();
  };
  $("trackers").onclick = () => {
    const d = $("dialog");
    d.innerHTML = `<h2>${t("Trackers et clients", "Trackers and clients")}</h2>${snapshot.trackers.map((tr) => `<details open><summary>${escape(tr)}</summary>${snapshot.clients.map((c) => `<p><button data-tr="${escape(tr)}" data-client="${escape(c.id)}">${escape(c.name)}</button></p>`).join("")}</details>`).join("")}<button id="close-tree">${t("Fermer", "Close")}</button>`;
    d.showModal();
    d.querySelectorAll("[data-tr]").forEach(
      (b) =>
        (b.onclick = () => {
          d.close();
          guard(() => request("target-client", {client_id:b.dataset.client, tracker:b.dataset.tr}));
        }),
    );
    $("close-tree").onclick = () => d.close();
  };
  document
    .querySelectorAll("[data-action]")
    .forEach(
      (b) => (b.onclick = (event) => guard(() => confirmAction(b.dataset.action), event.currentTarget)),
    );
}
async function confirmAction(
  action,
  chosen = [...selected].map((k) => rowCache.get(k)).filter(Boolean),
  extra = {},
) {
  const d = $("dialog"),
    payload = {
      action,
      items: chosen.map((r) => ({
        client_id: r.raw.client_id,
        hash: r.raw.hash,
      })),
      ...extra,
    };
  const review = await request("review", payload);
  d.innerHTML = `<h2>${actionLabel(action)}</h2><p>${review.rows.length} torrents</p><div style="max-height:200px;overflow:auto">${review.rows.map((r) => `<p>${escape(r.name)} · ${escape(r.client_name)}<br><small>${escape(r.folder)}</small>${r.files ? `<ul>${r.files.map((f) => `<li>${escape(f.name)} · ${formatBytes(f.size)}</li>`).join("")}</ul>` : ""}</p>`).join("")}</div><p>${action === "delete" ? t("Les fichiers seront définitivement supprimés. D’autres torrents peuvent les utiliser.", "Files will be permanently deleted. Other torrents may use them.") : action === "remove" ? t("Les fichiers seront conservés.", "Files will be kept.") : t("Appliquer aux torrents affichés ci-dessus ?", "Apply to the torrents listed above?")}</p>${action === "remove" ? `<label><input type="checkbox" id="delete-files">${t("Supprimer aussi les fichiers", "Also delete files")}</label>` : ""}${reviewParameters(extra)}<p><button id="cancel">${t("Annuler", "Cancel")}</button> <button id="confirm" class="primary">${t("Confirmer", "Confirm")}</button></p>`;
  d.showModal();
  $("cancel").onclick = () => d.close();
  $("confirm").onclick = (event) =>
    guard(async () => {
      if (action === "remove" && $("delete-files").checked) {
        d.close();
        return confirmAction("delete", chosen);
      }
      $("confirm").disabled = true;
      try {
        const result = await request("apply", {
          ...payload,
          token: review.token,
        });
        d.close();
        selected.clear();
        await load();
        notify(
          result.rows
            .map(
              (r) =>
                `${chosen.find((c) => c.raw.client_id === r.client_id && c.raw.hash === r.hash)?.name || r.hash}: ${{ failed: t("Échec", "Failed"), missing: t("Torrent absent", "Torrent no longer present"), verifying: t("Ignoré : vérification en cours", "Skipped: verification in progress"), sent: t("Envoyé", "Sent") }[r.outcome] || r.outcome}${r.detail ? " · " + r.detail : ""}`,
            )
            .join(" · "),
          "ok",
        );
      } catch (error) {
        d.close();
        throw error;
      }
    }, event.currentTarget);
  $("cancel").focus();
}
function reviewParameters(extra) {
  const fields = [
    [
      "download_limit",
      t("Réception", "Download"),
      (v) => (v ? formatBytes(v) + "/s" : t("Illimité", "Unlimited")),
    ],
    [
      "upload_limit",
      t("Envoi", "Upload"),
      (v) => (v ? formatBytes(v) + "/s" : t("Illimité", "Unlimited")),
    ],
    ["category", t("Catégorie", "Category"), (v) => v || t("Aucune", "None")],
    [
      "tags",
      t("Tags à ajouter", "Tags to add"),
      (v) => v.join(", ") || t("Aucun", "None"),
    ],
    ["path", t("Dossier de destination", "Destination folder"), (v) => v],
    [
      "file_indexes",
      t("Fichiers sélectionnés", "Selected files"),
      (v) => v.length,
    ],
  ];
  return fields
    .filter(([key]) => key in extra)
    .map(
      ([key, label, display]) =>
        `<p>${label}: ${escape(display(extra[key]))}</p>`,
    )
    .join("");
}
function actionLabel(a) {
  return {
    pause: t("Suspendre", "Pause"),
    resume: t("Reprendre", "Resume"),
    recheck: t("Vérifier les fichiers", "Recheck files"),
    reannounce: t("Réannoncer", "Reannounce"),
    remove: t("Retirer les torrents", "Remove torrents"),
    delete: t("Supprimer les fichiers", "Delete files"),
    skip_files: t("Ignorer les fichiers", "Skip files"),
    want_files: t("Télécharger les fichiers", "Download files"),
    limits: t("Limites de vitesse", "Speed limits"),
    category: t("Catégorie et tags", "Category and tags"),
    location: t("Changer le dossier", "Change location"),
  }[a];
}

function render() {
  const top = window.scrollY,
    scroller = document.querySelector(".table-scroll"),
    scrollTop = scroller?.scrollTop || 0,
    scrollLeft = scroller?.scrollLeft || 0;
  const expanded = document.querySelector(".metric-filters")?.open;
  const active = document.activeElement,
    id = active?.id,
    metric = active?.dataset?.metric,
    sorting = active?.dataset?.sort,
    filtering = active?.dataset?.filter,
    selecting = active?.dataset?.select,
    unit = active?.dataset?.unit,
    draftValue = active?.value,
    selectionStart = active?.selectionStart,
    selectionEnd = active?.selectionEnd;
  paint();
  if (expanded !== undefined)
    document.querySelector(".metric-filters").open = expanded;
  const next = document.querySelector(".table-scroll");
  if (next) {
    next.scrollTop = scrollTop;
    next.scrollLeft = scrollLeft;
  }
  window.scrollTo(0, top);
  const target = metric
    ? document.querySelector(`[data-metric="${metric}"]`)
    : sorting
      ? document.querySelector(`[data-sort="${sorting}"]`)
      : filtering
        ? document.querySelector(`[data-filter="${CSS.escape(filtering)}"]`)
        : selecting
          ? document.querySelector(`[data-select="${CSS.escape(selecting)}"]`)
          : unit
            ? document.querySelector(`[data-unit="${unit}"]`)
            : id
              ? $(id)
              : null;
  if (target && draftValue !== undefined && (metric || id === "query"))
    target.value = draftValue;
  target?.focus({ preventScroll: true });
  if (target && selectionStart != null && selectionEnd != null)
    target.setSelectionRange(selectionStart, selectionEnd);
  applyWidths();
}
