"use strict";
window.TLTorrentFilters = (() => {
  const escape = (value) =>
    String(value ?? "").replace(
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
  function controls({
    query = "",
    filters = {},
    options = {},
    language = "en",
    queryId = "query",
  }) {
    const t = (fr, en) => (language === "fr" ? fr : en);
    const labels = {
      state: t("Tous les états", "All states"),
      category: t("Toutes les catégories", "All categories"),
      tracker: t("Tous les trackers", "All trackers"),
      tag: t("Tous les tags", "All tags"),
    };
    const states = {
      seeding: t("En partage", "Seeding"),
      paused: t("En pause", "Paused"),
      downloading: t("Téléchargement", "Downloading"),
      checking: t("Vérification", "Checking"),
      error: t("Erreur", "Error"),
      other: t("Autre", "Other"),
    };
    return `<div class="filters"><input id="${escape(queryId)}" aria-label="${t("Rechercher un torrent…", "Find a torrent…")}" value="${escape(query)}" placeholder="${t("Rechercher un torrent…", "Find a torrent…")}">${Object.keys(
      labels,
    )
      .map(
        (key) =>
          `<select data-filter="${key}" aria-label="${labels[key]}"><option value="">${labels[key]}</option>${(
            options[key] || []
          )
            .map((item) => {
              const value = typeof item === "object" ? item.value : item,
                label =
                  typeof item === "object"
                    ? item.label
                    : key === "state"
                      ? states[item] || item
                      : item;
              return `<option value="${escape(value)}" ${filters[key] === value ? "selected" : ""}>${escape(label)}</option>`;
            })
            .join("")}</select>`,
      )
      .join("")}</div>`;
  }
  function metricControls({
    metrics,
    sizeUnits,
    language = "en",
    scope = true,
  }) {
    const t = (fr, en) => (language === "fr" ? fr : en);
    const fields = [
      ["sizeMin", t("Taille min.", "Min. size")],
      ["sizeMax", t("Taille max.", "Max. size")],
      ["noteMin", t("Note c411 min.", "Min. c411 Note")],
      ["zenMin", t("Zen/jour min.", "Min. Zen/day")],
      ["weightMin", t("Poids min.", "Min. weight")],
      ["seedMax", t("Sources max.", "Max. seeders")],
      ["daysMin", t("Seed min. (jours)", "Min. seed (days)")],
    ];
    return `<details class="metric-filters" ${Object.values(metrics).some((v) => v !== "") ? "open" : ""}><summary>${t("Filtres de seed et c411", "Seed and c411 filters")} · ${Object.values(metrics).filter((v) => v !== "").length} ${t("actifs", "active")}</summary><div class="metric-grid">${scope ? `<label>${t("Réseau", "Network")}<select data-metric="scope"><option value="">${t("Tous", "All")}</option><option value="c411" ${metrics.scope === "c411" ? "selected" : ""}>c411</option><option value="other" ${metrics.scope === "other" ? "selected" : ""}>${t("Hors c411", "Non-c411")}</option></select></label>` : ""}${fields.map(([k, l]) => `<label>${l}<span class="metric-value"><input type="number" min="0" step="any" data-metric="${k}" value="${escape(metrics[k])}" placeholder="${t("Sans limite", "No limit")}">${sizeUnits[k] ? `<button type="button" class="unit-toggle" data-unit="${k}" aria-label="${l} : ${t("changer l’unité", "switch unit")}, ${sizeUnits[k]}">${sizeUnits[k]}</button>` : ""}</span></label>`).join("")}</div><p class="muted">${t("Note, Zen et poids filtrent uniquement les torrents c411 renseignés. Les sources désignent les seeders disponibles.", "Note, Zen and weight only match c411 torrents with known values. Seeders means available sources.")}</p><button id="clear-filters">${t("Effacer les filtres", "Clear filters")}</button></details>`;
  }
  return { controls, metrics: metricControls };
})();
