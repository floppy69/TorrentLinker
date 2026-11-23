"use strict";
const state = {
  clientId: "default",
  setup: { clients: [] },
  planRows: [],
  planSelected: new Set(),
  planId: "",
  planDirty: false,
  planOffset: 0,
  sortKey: "plan",
  sortDirection: 1,
  sizeUnits: { min: 1024 ** 3, max: 1024 ** 3 },
  categories: [],
};
const planUI = {
  busy: false,
  result: null,
  phase: "",
  job: null,
  sending: false,
  pending: false,
};
let environmentReady = false,
  initialized = false,
  configureTimer,
  reviewAfter = false,
  preferencesDirty = false,
  reviewRevision = 0,
  sendingStarted = 0,
  fieldsKey = "";
function planActions() {
  const selected = state.planRows.filter((r) => state.planSelected.has(r.hash));
  const unavailable = planUI.busy || state.planDirty || !state.planId;
  $("plan-send").disabled = unavailable || !selected.length;
  $("queue-plan").disabled = unavailable || !selected.some((r) => !r.reseed);
  $("plan-selection").textContent =
    `${selected.length} ${say("selected", "sélectionnés")} · ${bytes(selected.reduce((n, r) => n + r.download_size, 0))} ${say("to download", "à télécharger")}`;
  $("plan-stop").hidden = !planUI.sending;
  $("plan-now").hidden =
    !planUI.busy || planUI.sending || planUI.phase !== "fetching";
  for (const input of document.querySelectorAll(
    "#plan-form input,#plan-form select,#plan-form button,#plan-clients input,#plan,#plan-folders,#zen-preferences-form input,#zen-preferences-form select,#zen-preferences-form textarea,#zen-preferences-form button,#plan-speed-save",
  ))
    input.disabled = planUI.busy || !environmentReady;
  if (!planUI.busy && environmentReady) {
    $("plan-count").disabled = !$("plan-limit-count").checked;
    $("plan-seeders").disabled = !$("plan-limit-seeders").checked;
  }
  $("plan-now").disabled = planUI.pending;
  $("plan-stop").disabled = planUI.pending;
  for (const input of document.querySelectorAll(
    "#plan-result input,#plan-select-all,#plan-select-none",
  ))
    input.disabled = planUI.busy || !environmentReady;
}
function planDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.ceil(seconds)} s`;
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} min`;
  return `${num(seconds / 3600)} h`;
}
function showPlan(result) {
  if (result.cancelled) return;
  planUI.result = result;
  state.planId = result.plan_id;
  state.planRows = result.rows || [];
  state.planSelected = new Set(state.planRows.map((r) => r.hash));
  state.planOffset = 0;
  state.planDirty = false;
  $("plan-diagnostics").replaceChildren(
    ...(result.issues || []).map((i) =>
      element("p", diagnostic(i), "info-box"),
    ),
  );
  if (result.notice)
    $("plan-diagnostics").prepend(element("p", result.notice, "info-box"));
  if (result.on_disk?.length) {
    const details = element("details"),
      summary = element(
        "summary",
        say("Files already on disk", "Fichiers déjà présents"),
      );
    details.append(summary);
    for (const row of result.on_disk)
      details.append(element("p", `${row.title} · ${row.path}`));
    $("plan-diagnostics").append(details);
  }
  if (result.interrupted)
    $("plan-diagnostics").append(
      element(
        "p",
        say(
          "Sending was interrupted. Check the Torrent Clients before resuming this saved Plan.",
          "L’envoi a été interrompu. Vérifiez les clients torrent avant de reprendre ce Plan.",
        ),
      ),
    );
  $("plan-summary").textContent = state.planRows.length
    ? `${state.planRows.length} torrents · ${bytes(result.size)} ${say("to download", "à télécharger")} · ≈ +${num(result.zen)} Zen/${say("day", "jour")} · ${say("paid back in", "amorti en")} ≈ ${result.payback_days === null ? "—" : num(result.payback_days)} ${say("days", "jours")} · ${say("average note", "note moyenne")} ${result.average_note === null ? "—" : num(result.average_note)}`
    : say(
        "Build a Plan to see eligible downloads and Reseeds.",
        "Créez un Plan pour voir les téléchargements et Reseeds éligibles.",
      );
  $("plan-storage").hidden = !result.storage?.length;
  table("plan-storage", result.storage || [], [
    {
      label: say(
        "Disk / Download Folder",
        "Disque / dossier de téléchargement",
      ),
      render: (r) => r.folder,
    },
    {
      label: say("Free / uncommitted", "Libre / non engagé"),
      render: (r) => bytes(r.free),
    },
    { label: say("Reserved", "Réservé"), render: (r) => bytes(r.reserved) },
    {
      label: say("Plan downloads", "Téléchargements du Plan"),
      render: (r) => bytes(r.download),
    },
    {
      label: say("Free after Plan", "Libre après le Plan"),
      render: (r) => bytes(r.after_plan),
    },
  ]);
  $("plan-times").textContent =
    `${say("Sending to clients", "Envoi aux clients")} ≈ ${planDuration(result.sending_seconds)} · ${say("Downloading, best case", "Téléchargement, au mieux")} ≈ ${planDuration(result.download_seconds)}`;
  proposalFilters();
  renderPlan();
}
function renderPlan() {
  const key = state.sortKey,
    direction = state.sortDirection;
  const query = $("plan-query").value.trim().toLocaleLowerCase();
  const category = $("plan-filter-category").value;
  const action = $("plan-filter-action").value;
  const ordered = state.planRows.filter(
    (r) =>
      (!query || r.title.toLocaleLowerCase().includes(query)) &&
      (!category || String(r.category ?? "unknown") === category) &&
      (!action || (action === "reseed") === r.reseed),
  );
  if (key !== "plan")
    ordered.sort((a, b) =>
      a[key] == null
        ? b[key] == null
          ? 0
          : 1
        : b[key] == null
          ? -1
          : direction *
            (typeof a[key] === "string"
              ? a[key].localeCompare(b[key])
              : (a[key] || 0) - (b[key] || 0)),
    );
  state.planOffset = Math.min(
    state.planOffset,
    Math.max(0, Math.floor((ordered.length - 1) / 100) * 100),
  );
  const offset = state.planOffset || 0,
    rows = ordered.slice(offset, offset + 100);
  table(
    "plan-result",
    rows,
    [
      {
        label: say("Torrent / action", "Torrent / action"),
        render: (r) => {
          const content = element("div"),
            title = element("span", r.title, "torrent-title");
          title.title = r.title;
          content.append(
            title,
            element("br"),
            element(
              "small",
              [
                r.reseed ? "Reseed" : say("Download", "Téléchargement"),
                categoryName(r.category),
              ].join(" · "),
            ),
          );
          return content;
        },
      },
      {
        label: say("Action / download", "Action / téléchargement"),
        render: (r) => (r.reseed ? "Reseed · 0 B" : bytes(r.size)),
      },
      { label: "Seeders", render: (r) => r.seeders },
      { label: "≈ Note", render: (r) => (r.note === null ? "—" : num(r.note)) },
      { label: say("≈ Zen/day", "≈ Zen/jour"), render: (r) => num(r.zen) },
      {
        label: say(
          "Download Folder / existing data",
          "Dossier de téléchargement / données existantes",
        ),
        render: (r) => {
          const path = element(
            "span",
            r.reseed ? r.path : r.folder,
            "torrent-path",
          );
          path.title = path.textContent;
          return path;
        },
      },
      {
        label: "Client",
        render: (r) =>
          state.setup.clients.find(
            (p) => p.id === (r.client_id || state.clientId),
          )?.name || r.client_id,
      },
    ],
    state.planSelected,
    "hash",
    renderPlan,
  );
  $("plan-result").classList.add("torrent-list-scroll");
  $("plan-result").querySelector("table")?.classList.add("torrent-list");
  const keys = [
    "title",
    "download_size",
    "seeders",
    "note",
    "zen",
    "folder",
    "client_id",
  ];
  $("plan-result")
    .querySelectorAll("thead th")
    .forEach((cell, i) => {
      if (!i) return;
      const sortKey = keys[i - 1],
        active = sortKey === key;
      cell.setAttribute(
        "aria-sort",
        active ? (direction === 1 ? "ascending" : "descending") : "none",
      );
      const control = button(
        cell.textContent + (active ? (direction === 1 ? " ↑" : " ↓") : " ↕"),
        () => {
          state.sortDirection = active ? -direction : 1;
          state.sortKey = sortKey;
          state.planOffset = 0;
          renderPlan();
        },
        "sort-head",
      );
      control.dataset.sort = sortKey;
      cell.replaceChildren(control);
    });
  $("plan-page").textContent =
    `${ordered.length ? offset + 1 : 0}–${offset + rows.length} / ${ordered.length}`;
  $("plan-prev").disabled = offset === 0;
  $("plan-next").disabled = offset + 100 >= ordered.length;
  planActions();
}
function categoryName(id) {
  return (
    state.categories.find((c) => c[0] === id)?.[1] ||
    String(id ?? say("Unknown", "Inconnue"))
  );
}
function proposalFilters() {
  const select = $("plan-filter-category"),
    previous = select.value;
  select.replaceChildren(
    new Option(say("All categories", "Toutes les catégories"), ""),
  );
  for (const id of new Set(state.planRows.map((r) => r.category)))
    select.add(new Option(categoryName(id), String(id ?? "unknown")));
  select.value = [...select.options].some((o) => o.value === previous)
    ? previous
    : "";
  $("plan-query").placeholder = say(
    "Search proposal…",
    "Rechercher dans le Plan…",
  );
  $("plan-query").setAttribute("aria-label", $("plan-query").placeholder);
  select.setAttribute("aria-label", say("Category", "Catégorie"));
  $("plan-filter-action").setAttribute("aria-label", "Action");
}
function fillOptions(options, categories) {
  const value = options || {};
  $("plan-goal").value = value.goal || "note";
  $("plan-budget").value = (value.max_download_bytes || 0) / 1e9;
  $("plan-min-count").value = value.min_torrents || 0;
  $("plan-min-seeders").value = value.min_seeders || 0;
  $("plan-count").value = value.max_torrents ?? 100;
  $("plan-limit-count").checked = value.max_torrents != null;
  $("plan-seeders").value = value.max_seeders ?? 10;
  $("plan-limit-seeders").checked = value.max_seeders != null;
  $("plan-min-size").value = (value.min_size || 0) / state.sizeUnits.min;
  $("plan-max-size").value = (value.max_size || 0) / state.sizeUnits.max;
  for (const option of $("plan-category").options)
    option.selected = categories?.length
      ? categories.includes(Number(option.value))
      : option.value === "";
}
function fillPreferences(p = {}) {
  $("plan-speed").value = p.download_speed ? (p.download_speed * 8) / 1e6 : "";
  $("plan-zen-class").value = p.zen_class || "tanker";
  $("plan-tree").value = (p.tree_bonus || 0) * 100;
  $("plan-badge").value = (p.badge_bonus || 0) * 100;
  $("plan-hours").value = p.seed_hours ?? 24;
  $("plan-cap").value = p.torrent_cap || 0;
  $("plan-reserve").value = (p.free_space_margin ?? 0.1) * 100;
  $("plan-exclusions").value = (p.plan_exclusions || []).join("\n");
}
function configureFields(value) {
  state.categories = value.categories || [];
  const selected = [...$("plan-category").selectedOptions].map((o) => o.value);
  $("plan-category").replaceChildren(
    new Option(say("All categories", "Toutes les catégories"), ""),
  );
  for (const [id, name, sub] of value.categories || []) {
    const option = new Option(
      (sub ? "　" : "") +
        name +
        (value.without_folder?.includes(id)
          ? say(" · no folder", " · sans dossier")
          : ""),
      String(id),
    );
    option.selected = selected.includes(String(id));
    $("plan-category").append(option);
  }
  const clients =
    value.clients ||
    Object.entries(value.client_names || {})
      .filter(([id]) => id)
      .map(([id, name]) => ({ id, name, enabled: true }));
  state.setup.clients = clients.length
    ? clients
    : [{ id: state.clientId, name: state.clientId, enabled: true }];
  $("plan-clients").replaceChildren(
    ...state.setup.clients
      .filter((c) => c.enabled !== false)
      .map((client) => {
        const row = element("section", undefined, "plan-client-card"),
          heading = element("label", undefined, "plan-client-heading"),
          budgetLabel = element("label"),
          check = element("input"),
          budget = element("input");
        check.type = "checkbox";
        check.dataset.clientId = client.id;
        check.checked = value.destinations
          ? Object.hasOwn(value.destinations, client.id)
          : client.id === state.clientId;
        budget.type = "number";
        budget.min = "0";
        budget.step = "any";
        budget.value = (value.destinations?.[client.id] || 0) / 1e9;
        budget.dataset.budgetId = client.id;
        budget.setAttribute(
          "aria-label",
          say("Budget in GB for ", "Budget en Go pour ") + client.name,
        );
        heading.append(check, element("strong", client.name));
        budgetLabel.append(
          element("span", say("Client budget, GB", "Budget du client, Go")),
          budget,
        );
        row.append(heading, budgetLabel);
        return row;
      }),
  );
}
function planApplyEnvironment(env) {
  const value = env.state || {},
    client = value.client_id || "default",
    newClient = state.clientId !== client;
  const languageChanged = language !== (env.language || "en");
  language = env.language || "en";
  document.documentElement.dataset.theme = env.theme || "dark";
  translate();
  environmentReady = value.ready !== false;
  if (!environmentReady) {
    planActions();
    return;
  }
  if (newClient) {
    state.planId = "";
    initialized = false;
    preferencesDirty = false;
    planUI.pending = false;
    $("dialog").close();
    reviewAfter = false;
    clearTimeout(configureTimer);
  }
  state.clientId = client;
  const nextFields = JSON.stringify([
    value.categories,
    value.without_folder,
    value.clients,
    value.client_names,
    language,
  ]);
  if (!initialized) {
    configureFields(value);
    fillOptions(value.options, value.chosen_categories);
    fillPreferences(value.preferences);
    initialized = true;
    fieldsKey = nextFields;
  } else {
    if (nextFields !== fieldsKey) {
      const drafts = optionsBody();
      configureFields(value);
      for (const input of $("plan-clients").querySelectorAll(
        "input[data-client-id]",
      ))
        input.checked = drafts.client_ids.includes(input.dataset.clientId);
      for (const input of $("plan-clients").querySelectorAll(
        "input[data-budget-id]",
      ))
        input.value =
          (drafts.client_budgets[input.dataset.budgetId] || 0) / 1e9;
      fieldsKey = nextFields;
    }
    if (
      !preferencesDirty &&
      !$("zen-preferences-form").contains(document.activeElement)
    ) {
      const speed = $("plan-speed").value;
      fillPreferences(value.preferences);
      if (document.activeElement === $("plan-speed"))
        $("plan-speed").value = speed;
    }
  }
  planUI.busy = Boolean(value.busy) || planUI.pending;
  planUI.sending = Boolean(value.progress);
  planUI.phase = value.fetching ? "fetching" : "planning";
  const incoming = value.result || { rows: [], issues: [] };
  const next = incoming.rows_unchanged
      ? { ...planUI.result, ...incoming }
      : incoming,
    changed = next.plan_id !== state.planId;
  const selected = state.planSelected,
    dirty = state.planDirty,
    offset = state.planOffset;
  if (
    !incoming.rows_unchanged ||
    languageChanged ||
    changed ||
    next.notice !== planUI.result?.notice
  ) {
    showPlan(next);
    if (!changed) {
      state.planSelected = new Set(
        [...selected].filter((hash) =>
          state.planRows.some((row) => row.hash === hash),
        ),
      );
      state.planDirty = dirty;
      state.planOffset = Math.min(
        offset,
        Math.max(0, Math.ceil(state.planRows.length / 100) - 1) * 100,
      );
      renderPlan();
    }
  }
  const report = value.report;
  $("plan-outcome").replaceChildren();
  if (report) {
    $("plan-outcome").append(
      element(
        "p",
        `${report.added?.length || 0} ${say("added", "ajoutés")} · ${report.reseeded?.length || 0} Reseeds · ${report.refused?.length || 0} ${say("refused", "refusés")} · ${report.failed?.length || 0} ${say("failed", "échecs")}`,
      ),
    );
    if (report.stopped)
      $("plan-outcome").append(
        element(
          "p",
          say(
            "Stopped. The remaining Plan is saved.",
            "Arrêté. Le reste du Plan est enregistré.",
          ),
        ),
      );
    for (const [title, reason] of [
      ...(report.refused || []),
      ...(report.failed || []),
    ])
      $("plan-outcome").append(element("p", `${title}: ${reason}`));
  }
  $("plan-progress").textContent = value.message || "";
  $("plan-send-progress").hidden = !value.progress;
  if (value.progress) {
    const p = value.progress;
    if (!sendingStarted) sendingStarted = Date.now();
    const elapsed = p.elapsed ?? (Date.now() - sendingStarted) / 1000,
      remaining =
        p.remaining_seconds ??
        (p.done ? (elapsed / p.done) * (p.total - p.done) : null);
    $("plan-send-progress").value = p.done / Math.max(1, p.total);
    $("plan-send-progress").setAttribute(
      "aria-label",
      say("Torrents sent", "Torrents envoyés"),
    );
    $("plan-progress").textContent =
      `${p.done}/${p.total} · ${p.added || 0} ${say("added", "ajoutés")} · ${p.refused || 0} ${say("refused", "refusés")} · ${p.failed || 0} ${say("failed", "échecs")} · ${p.title || ""} · ≈ +${num(p.zen_added)} Zen/${say("day sent", "jour envoyés")} · ${say("elapsed", "écoulé")} ${planDuration(elapsed)} · ${say("remaining", "restant")} ≈ ${planDuration(remaining)}` +
      (p.retry_at
        ? say(
            " · c411 is limiting downloads. Next try at ",
            " · c411 limite les téléchargements. Prochain essai à ",
          ) + new Date(p.retry_at * 1000).toLocaleTimeString(language)
        : "");
  } else sendingStarted = 0;

  const profile = value.preferences || {};
  $("plan-profile-summary").textContent =
    `${{ tanker: "Tanker", "swarm-keeper": "Swarm Keeper", reuploader: "Reuploader" }[profile.zen_class] || "Tanker"} · ${profile.seed_hours ?? 24} ${say("seed hours/day", "h de partage/jour")} · ${num((profile.free_space_margin ?? 0.1) * 100)}% ${say("disk reserve", "de réserve disque")}`;
  $("plan-speed-test").disabled = Boolean(value.testing) || planUI.busy;
  if (changed && reviewAfter && !planUI.busy) {
    reviewAfter = false;
    if (state.planRows.length) guard(reviewPlan);
  }
  if (value.review_revision && value.review_revision !== reviewRevision) {
    reviewRevision = value.review_revision;
    if (state.planRows.length) guard(reviewPlan);
  }
  planActions();
}
function optionsBody() {
  return {
    plan_goal: $("plan-goal").value,
    maximum_bytes: Math.round(Number($("plan-budget").value) * 1e9),
    minimum_torrents: Number($("plan-min-count").value),
    min_seeders: Number($("plan-min-seeders").value),
    maximum_torrents: Number($("plan-count").value),
    limit_torrents: $("plan-limit-count").checked,
    max_seeders: $("plan-limit-seeders").checked
      ? Number($("plan-seeders").value)
      : null,
    min_size: Math.round(
      Number($("plan-min-size").value) * state.sizeUnits.min,
    ),
    max_size: Math.round(
      Number($("plan-max-size").value) * state.sizeUnits.max,
    ),
    categories: [...$("plan-category").selectedOptions]
      .filter((o) => o.value)
      .map((o) => Number(o.value)),
    client_ids: [
      ...$("plan-clients").querySelectorAll("input[data-client-id]:checked"),
    ].map((el) => el.dataset.clientId),
    client_budgets: Object.fromEntries(
      [...$("plan-clients").querySelectorAll("input[data-budget-id]")].map(
        (el) => [el.dataset.budgetId, Math.round(Number(el.value) * 1e9)],
      ),
    ),
  };
}
function invalidatePlan() {
  state.planDirty = true;
  planActions();
  clearTimeout(configureTimer);
  configureTimer = setTimeout(
    () => guard(() => planRequest("configure", { options: optionsBody() })),
    200,
  );
}
async function buildPlan(refreshFirst = false) {
  clearTimeout(configureTimer);
  $("plan-error").hidden = true;
  const options = optionsBody();
  if (!options.client_ids.length)
    throw Error(
      say("Choose at least one client.", "Choisissez au moins un client."),
    );
  reviewAfter = refreshFirst;
  planUI.busy = true;
  planUI.phase = $("plan-cached").checked ? "planning" : "fetching";
  planActions();
  try {
    await planRequest("build", {
      options,
      cached_only: refreshFirst ? false : $("plan-cached").checked,
    });
  } catch (error) {
    reviewAfter = false;
    planUI.busy = false;
    planActions();
    if (error.action?.kind === "plan-folder") {
      await folderDialog(error.action.client_id, error.action.category);
      return;
    }
    throw error;
  }
}
async function reviewPlan() {
  if (state.planDirty || planUI.busy) return;
  const client = state.clientId,
    id = state.planId,
    rows = state.planRows.filter((r) => state.planSelected.has(r.hash));
  if (!rows.length) return;
  const body = { plan_id: id, hashes: rows.map((r) => r.hash) },
    review = await planRequest("review", body);
  if (client !== state.clientId || id !== state.planId || state.planDirty)
    return;
  const downloads = rows.filter((r) => !r.reseed),
    reseeds = rows.length - downloads.length;
  const content = $("dialog-content");
  content.replaceChildren(
    element(
      "h2",
      say("Send the selected Plan?", "Envoyer la sélection du Plan ?"),
    ),
    element(
      "p",
      `${downloads.length} ${say("download(s)", "téléchargement(s)")} · ${reseeds} Reseeds · ${bytes(downloads.reduce((sum, row) => sum + row.download_size, 0))} · ≈ +${num(rows.reduce((sum, row) => sum + row.zen, 0))} Zen/${say("day", "jour")}`,
    ),
    element(
      "p",
      say(
        "Each torrent is added to its reviewed Download Folder. Existing files are never downloaded over.",
        "Chaque torrent est ajouté au dossier de téléchargement examiné. Les fichiers existants ne sont jamais écrasés par un téléchargement.",
      ),
    ),
  );
  if (review.renames?.length) {
    content.append(
      element(
        "h3",
        say(
          "Files will be renamed on disk",
          "Des fichiers seront renommés sur le disque",
        ),
      ),
      element(
        "p",
        say(
          "Sending also approves these renames. Other torrents, readers or shortcuts may use the old paths. Occupied destinations are refused; original names are restored only when safe.",
          "L’envoi approuve ces renommages. D’autres torrents, lecteurs ou raccourcis peuvent utiliser les anciens chemins. Les destinations occupées sont refusées ; les noms d’origine sont restaurés uniquement si cela est sûr.",
        ),
      ),
    );
    for (const move of review.renames)
      content.append(element("p", `${move.source} → ${move.target}`));
  }
  content.append(
    button(say("Cancel", "Annuler"), () => $("dialog").close()),
    button(say("Refresh first", "Actualiser d’abord"), () => {
      $("dialog").close();
      guard(() => buildPlan(true));
    }),
    button(
      review.renames?.length
        ? say(
            "Rename files and send selected",
            "Renommer les fichiers et envoyer la sélection",
          )
        : say("Send selected", "Envoyer la sélection"),
      () =>
        guard(async () => {
          $("dialog").close();
          const sendingClient = state.clientId;
          planUI.pending = planUI.busy = true;
          planActions();
          try {
            await planRequest("send", { ...body, confirmation: review.token });
          } finally {
            if (sendingClient === state.clientId) {
              planUI.pending = false;
              planUI.busy = Boolean(planEnvironment.state.busy);
            }
            planActions();
          }
        }),
      "primary",
    ),
  );
  $("dialog").setAttribute(
    "aria-label",
    say("Review Plan", "Examiner le Plan"),
  );
  $("dialog").showModal();
}
async function folderDialog(clientId = state.clientId, category = null) {
  const content = $("dialog-content"),
    clients = element("select"),
    categories = element("select"),
    path = element("input"),
    feedback = element("p"),
    folders = element("div");
  clients.setAttribute("aria-label", say("Torrent Client", "Client torrent"));
  categories.setAttribute("aria-label", say("Category", "Catégorie"));
  path.setAttribute(
    "aria-label",
    say("Folder on the TorrentLinker host", "Dossier sur l’hôte TorrentLinker"),
  );
  for (const client of state.setup.clients)
    clients.add(new Option(client.name, client.id));
  clients.value = clientId;
  categories.add(new Option(say("Default", "Par défaut"), ""));
  for (const option of $("plan-category").options)
    if (option.value)
      categories.add(new Option(option.textContent, option.value));
  categories.value = category === null ? "" : String(category);
  let generation = 0,
    loading = false;
  const save = button(
    say("Save folder", "Enregistrer le dossier"),
    () => guard(saveFolder),
    "primary",
  );
  const browseButton = button(
    say("Browse folders", "Parcourir les dossiers"),
    () => guard(() => browse()),
  );
  function setLoading(value) {
    loading = value;
    save.disabled = value;
    browseButton.disabled = value;
    path.disabled = value;
  }
  async function load() {
    const request = ++generation,
      client = clients.value,
      category = categories.value;
    setLoading(true);
    path.value = "";
    folders.replaceChildren();
    feedback.textContent = "";
    try {
      const result = await planRequest("folders", {
        client_id: client,
        category: category ? Number(category) : null,
      });
      if (request !== generation || !content.contains(path)) return;
      path.value = result.path || "";
      setLoading(false);
    } catch (error) {
      if (request !== generation || !content.contains(path)) return;
      feedback.textContent = error.message;
      // Keep Save disabled until a current destination has loaded.
    }
  }
  async function saveFolder() {
    if (loading) return;
    const request = generation;
    const destination = {
      client_id: clients.value,
      category: categories.value ? Number(categories.value) : null,
      path: path.value,
    };
    setLoading(true);
    clients.disabled = categories.disabled = true;
    try {
      await planRequest("save-folder", destination);
      if (request !== generation || !content.contains(path)) return;
      feedback.textContent =
        planEnvironment.mode === "web"
          ? say(
              "Folder verified and saved. Build the Plan again.",
              "Dossier vérifié et enregistré. Recréez le Plan.",
            )
          : say(
              "Folder saved. Build the Plan again.",
              "Dossier enregistré. Recréez le Plan.",
            );
      invalidatePlan();
    } finally {
      if (request === generation && content.contains(path)) {
        setLoading(false);
        clients.disabled = categories.disabled = false;
      }
    }
  }
  async function browse(current = "") {
    const request = ++generation;
    const result = await planRequest(
      planEnvironment.mode === "desktop" ? "pick" : "folders",
      { browse: true, path: current },
    );
    if (request !== generation || !content.contains(path)) return;
    if (result.selected !== undefined) {
      if (result.selected) path.value = result.selected;
      return;
    }
    folders.replaceChildren(
      element("p", result.path || say("Mounted roots", "Racines montées")),
    );
    if (result.path)
      folders.append(
        button(say("Use this folder", "Utiliser ce dossier"), () => {
          path.value = result.path;
          folders.replaceChildren();
        }),
        button("↑", () => guard(() => browse(result.parent))),
      );
    for (const item of result.folders || [])
      folders.append(button(item, () => guard(() => browse(item))));
  }
  content.replaceChildren(
    element("h2", say("Category Download Folders", "Dossiers par catégorie")),
    element(
      "p",
      say(
        "Paths belong to the TorrentLinker host.",
        "Les chemins appartiennent à l’hôte TorrentLinker.",
      ),
    ),
    clients,
    categories,
    path,
    browseButton,
    folders,
    feedback,
    save,
  );
  clients.onchange = categories.onchange = () => guard(load);
  $("dialog").setAttribute(
    "aria-label",
    say("Category Download Folders", "Dossiers par catégorie"),
  );
  $("dialog").showModal();
  await load();
}
function planInit() {
  planActions();
  $("plan-info").onclick = () => {
    const box = $("plan-info-box");
    box.hidden = !box.hidden;
    $("plan-info").setAttribute("aria-expanded", String(!box.hidden));
  };
  $("plan-form").onsubmit = (event) => {
    event.preventDefault();
    guard(() => buildPlan());
  };
  for (const container of [$("plan-form"), $("plan-clients")]) {
    container.addEventListener("input", invalidatePlan);
    container.addEventListener("change", invalidatePlan);
  }
  document.addEventListener(
    "wheel",
    (event) => {
      if (event.target.matches('input[type="number"]')) event.preventDefault();
    },
    { passive: false },
  );
  $("plan-query").oninput =
    $("plan-filter-category").onchange =
    $("plan-filter-action").onchange =
      () => {
        state.planOffset = 0;
        renderPlan();
      };
  for (const toggle of document.querySelectorAll("[data-size-unit]"))
    toggle.onclick = () => {
      const bound = toggle.dataset.sizeUnit,
        input = $(`plan-${bound}-size`);
      const bytes = Number(input.value) * state.sizeUnits[bound];
      state.sizeUnits[bound] =
        state.sizeUnits[bound] === 1024 ** 3 ? 1024 ** 2 : 1024 ** 3;
      input.value = bytes / state.sizeUnits[bound];
      toggle.textContent = state.sizeUnits[bound] === 1024 ** 3 ? "GiB" : "MiB";
    };
  $("plan-select-all").onclick = () => {
    state.planSelected = new Set(state.planRows.map((r) => r.hash));
    renderPlan();
  };
  $("plan-select-none").onclick = () => {
    state.planSelected.clear();
    renderPlan();
  };
  $("plan-prev").onclick = () => {
    state.planOffset = Math.max(0, state.planOffset - 100);
    renderPlan();
  };
  $("plan-next").onclick = () => {
    state.planOffset += 100;
    renderPlan();
  };
  $("plan-send").onclick = (event) => guard(reviewPlan, event.currentTarget);
  $("plan-now").onclick = (event) => guard(() => planRequest("stop-fetch"), event.currentTarget);
  $("plan-stop").onclick = (event) => guard(() => planRequest("stop-send"), event.currentTarget);
  $("queue-plan").onclick = (event) =>
    guard(async () => {
      await planRequest("queue", {
        plan_id: state.planId,
        hashes: state.planRows
          .filter((r) => !r.reseed && state.planSelected.has(r.hash))
          .map((r) => r.hash),
      });
      $("plan-progress").textContent = say(
        "Selected downloads added to the queue.",
        "Téléchargements sélectionnés ajoutés à la file.",
      );
    }, event.currentTarget);
  $("plan-folders").onclick = (event) => guard(() => folderDialog(), event.currentTarget);
  $("plan-profile-edit").onclick = () => {
    $("plan-preferences").open = true;
    $("plan-preferences").scrollIntoView({ block: "nearest" });
    $("plan-zen-class").focus();
  };
  $("zen-preferences-form").oninput = () => {
    preferencesDirty = true;
  };
  $("zen-preferences-form").onsubmit = (event) => {
    event.preventDefault();
    guard(async () => {
      await planRequest("preferences", {
        zen_class: $("plan-zen-class").value,
        tree_bonus: Number($("plan-tree").value) / 100,
        badge_bonus: Number($("plan-badge").value) / 100,
        seed_hours: Number($("plan-hours").value),
        torrent_cap: Number($("plan-cap").value),
        free_space_margin: Number($("plan-reserve").value) / 100,
        plan_exclusions: $("plan-exclusions")
          .value.split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      preferencesDirty = false;
      invalidatePlan();
    });
  };
  $("plan-speed-save").onclick = (event) =>
    guard(() =>
      planRequest("preferences", {
        download_speed: (Number($("plan-speed").value) * 1e6) / 8,
      }), event.currentTarget);
  $("plan-speed-test").onclick = (event) => guard(() => planRequest("speed-test"), event.currentTarget);
  translate();
}
