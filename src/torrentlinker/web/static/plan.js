"use strict";

// The same Plan data and sending engine as desktop, with browser-local review controls.
const planUI = {
  generation: 0,
  job: null,
  catalogueJob: null,
  busy: false,
  result: null,
};
Object.assign(french, {
  previous: "Précédent",
  next: "Suivant",
  pauseCatalogue: "Suspendre après la page en cours",
  yourUploads: "Vos uploads",
  saveComparison: "Enregistrer le nombre d’uploads",
  planFolders: "Dossiers par catégorie…",
  planNoteHelp:
    "Note privilégie la note initiale de chaque torrent, sans bonus de durée de seed. À note égale, les téléchargements plus petits sont prioritaires. Zen/jour maximise les gains estimés.",
  planReseedHelp:
    "Les correspondances complètes vérifiées de la bibliothèque sont incluses comme Reseeds avec une seule destination sans budget par client. Elles ne consomment pas de budget de téléchargement. Les limites de taille, de seeders et de nombre restent applicables.",
  planNow: "Arrêter la collecte et planifier maintenant",
  planPreferences: "Profil Zen, réserve disque et exclusions",
  zenClass: "Classe utilisée pour les estimations",
  treeBonus: "Bonus d’arbre, %",
  badgeBonus: "Bonus de badges, %",
  seedHours: "Heures de seed par jour",
  torrentCap: "Limite globale de torrents, 0 = illimité",
  diskReserve: "Espace conservé libre par disque, %",
  planExcluded: "Mots exclus des titres, un par ligne",
  savePlanPreferences: "Enregistrer les paramètres",
  downloadRate: "Débit de téléchargement, Mbit/s",
  saveRate: "Utiliser ce débit",
  testServerSpeed: "Tester le débit du serveur",
  serverSpeedHelp:
    "Le test télécharge anonymement depuis Cloudflare pendant environ 8 secondes sur l’hôte TorrentLinker. Saisissez un débit si le client torrent utilise une autre connexion.",
  planSort: "Trier la proposition par",
  planOrder: "Ordre du Plan",
  selectWholePlan: "Sélectionner tout le Plan",
  clearSelection: "Vider la sélection",
  queuePlanDownloads: "Mettre les téléchargements sélectionnés en file",
  sendPlan: "Envoyer la sélection aux clients…",
  stopPlan: "Arrêter après le torrent en cours",
});
translate();

function invalidatePlan() {
  state.planDirty = Boolean(state.planRows.length);
  if (state.planDirty)
    $("plan-progress").textContent = say(
      "Settings changed. Build a new Plan before sending or queueing.",
      "Paramètres modifiés. Recréez le Plan avant l’envoi ou la mise en file.",
    );
  planActions();
}
function planActions() {
  const selected = state.planRows.filter((r) => state.planSelected.has(r.hash));
  const unavailable = planUI.busy || state.planDirty || !state.planId;
  $("plan-send").disabled = unavailable || !selected.length;
  $("queue-plan").disabled = unavailable || !selected.some((r) => !r.reseed);
  $("plan-selection").textContent =
    `${selected.length} ${say("selected", "sélectionnés")} · ${bytes(selected.reduce((n, r) => n + (r.download_size ?? r.size), 0))} ${say("to download", "à télécharger")}`;
  $("plan-stop").hidden = !planUI.busy || !planUI.sending;
  $("plan-now").hidden =
    !planUI.busy ||
    planUI.sending ||
    planUI.phase === "planning" ||
    $("plan-cached").checked;
  for (const input of document.querySelectorAll(
    "#plan-form input, #plan-form select, #plan-clients input, #plan-form button",
  ))
    input.disabled = planUI.busy;
  $("plan-now").disabled = !planUI.job;
  if (!planUI.busy) {
    $("plan-count").disabled = !$("plan-limit-count").checked;
    $("plan-seeders").disabled = !$("plan-limit-seeders").checked;
  }
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
  showCatalogue(result.catalogue);
  state.planId = result.plan_id;
  state.planRows = result.rows || [];
  state.planSelected = new Set(state.planRows.map((r) => r.hash));
  state.planOffset = 0;
  state.planDirty = false;
  $("plan-diagnostics").replaceChildren(
    ...(result.issues || []).map((i) => element("p", i.message)),
  );
  if (result.notice)
    $("plan-diagnostics").prepend(
      element(
        "p",
        say(
          result.notice,
          "Échec de l’actualisation du catalogue. Ce Plan provisoire utilise les métadonnées en cache.",
        ),
      ),
    );
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
  renderPlan();
}
function renderPlan() {
  const key = $("plan-sort").value,
    direction = $("plan-sort-order").value === "asc" ? 1 : -1;
  const ordered = [...state.planRows];
  if (key !== "plan")
    ordered.sort(
      (a, b) =>
        direction *
        (typeof a[key] === "string"
          ? a[key].localeCompare(b[key])
          : (a[key] || 0) - (b[key] || 0)),
    );
  const offset = state.planOffset || 0,
    rows = ordered.slice(offset, offset + 100);
  table(
    "plan-result",
    rows,
    [
      { label: say("Torrent", "Torrent"), render: (r) => r.title },
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
        render: (r) => (r.reseed ? r.path : r.folder),
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
    planActions,
  );
  $("plan-page").textContent =
    `${state.planRows.length ? offset + 1 : 0}–${offset + rows.length} / ${state.planRows.length}`;
  $("plan-prev").disabled = offset === 0;
  $("plan-next").disabled = offset + 100 >= state.planRows.length;
  planActions();
}
function retranslatePlan() {
  const all = $("plan-category").querySelector('option[value=""]');
  if (all) all.textContent = say("All categories", "Toutes les catégories");
  if (!planUI.result) return;
  const selected = state.planSelected,
    dirty = state.planDirty,
    offset = state.planOffset;
  showPlan(planUI.result);
  state.planSelected = selected;
  state.planDirty = dirty;
  state.planOffset = offset;
  renderPlan();
}
function fillZenPreferences(p, restoreOptions = false) {
  $("seeding-uploads").value = p.uploads;
  $("plan-speed").value = p.download_speed ? (p.download_speed * 8) / 1e6 : "";
  $("plan-zen-class").value = p.zen_class;
  $("plan-tree").value = p.tree_bonus * 100;
  $("plan-badge").value = p.badge_bonus * 100;
  $("plan-hours").value = p.seed_hours;
  $("plan-cap").value = p.torrent_cap;
  $("plan-reserve").value = p.free_space_margin * 100;
  $("plan-exclusions").value = p.plan_exclusions.join("\n");
  if (restoreOptions) {
    const o = p.plan_options;
    $("plan-goal").value = o.goal;
    $("plan-budget").value = o.max_download_bytes / 1024 ** 3;
    $("plan-count").value = o.max_torrents ?? 100;
    $("plan-limit-count").checked = o.max_torrents !== null;
    $("plan-seeders").value = o.max_seeders ?? 10;
    $("plan-limit-seeders").checked = o.max_seeders !== null;
    $("plan-min-size").value = o.min_size / 1024 ** 3;
    $("plan-max-size").value = o.max_size / 1024 ** 3;
    for (const option of $("plan-category").options)
      option.selected =
        p.plan_categories === null
          ? !option.value
          : p.plan_categories.includes(Number(option.value));
  }
}
async function loadZenPlan() {
  const generation = ++planUI.generation,
    client = state.clientId;
  planUI.busy = false;
  planUI.job = null;
  if (client === "all") {
    state.planRows = [];
    state.planId = "";
    renderPlan();
    $("plan-progress").textContent = say(
      "Choose a target client to review its Plan.",
      "Choisissez un client cible pour afficher son Plan.",
    );
    return;
  }
  const [result, preferences, jobs] = await Promise.all([
    api(`zen/plan?client_id=${encodeURIComponent(client)}`),
    api("zen/preferences"),
    api("jobs"),
  ]);
  if (generation !== planUI.generation || client !== state.clientId) return;
  fillZenPreferences(preferences, true);
  showPlan(result);
  const active = jobs.find(
    (j) =>
      j.client_id === client &&
      ["queued", "running"].includes(j.status) &&
      ["plan", "send-plan"].includes(j.kind),
  );
  if (active) {
    planUI.job = active.id;
    planUI.busy = true;
    planUI.sending = active.kind === "send-plan";
    state.jobs.set(active.id, {
      body: { client_id: client, kind: active.kind },
      done: finishPlanJob,
      failed: finishPlanJob,
      progress: planProgress,
    });
    if (active.progress) planProgress(active.progress);
  }
  const catalogue = jobs.find(
    (j) => j.kind === "catalogue" && ["queued", "running"].includes(j.status),
  );
  planUI.catalogueJob = catalogue?.id || null;
  $("catalogue-pause").hidden = !catalogue;
  $("catalogue").disabled = Boolean(catalogue);
  if (catalogue && !state.jobs.has(catalogue.id))
    state.jobs.set(catalogue.id, {
      body: { client_id: catalogue.client_id, kind: "catalogue" },
      done: finishCatalogue,
      failed: finishCatalogue,
    });
  planActions();
}
function planProgress(p) {
  if (p.phase) planUI.phase = p.phase;
  if (p.total !== undefined && p.done !== undefined) {
    $("plan-progress").textContent =
      `${p.done}/${p.total} · ${p.added || 0} ${say("added", "ajoutés")} · ${p.refused || 0} ${say("refused", "refusés")} · ${p.failed || 0} ${say("failed", "échecs")} · ${p.title || ""}` +
      (p.retry_at
        ? ` · ${say("Rate limited; resumes at", "Limite atteinte ; reprise à")} ${new Date(p.retry_at * 1000).toLocaleTimeString()}`
        : "");
    $("plan-progress").textContent +=
      ` · ≈ +${num(p.zen_added || 0)} Zen/${say("day", "jour")} · ${say("elapsed", "écoulé")} ${planDuration(p.elapsed)} · ${say("remaining", "restant")} ≈ ${planDuration(p.remaining_seconds)}`;
  } else
    $("plan-progress").textContent =
      p.phase === "planning"
        ? say("Calculating the Plan…", "Calcul du Plan…")
        : say(
            "Fetching the Catalogue… You can stop fetching and plan now.",
            "Collecte du catalogue… Vous pouvez arrêter la collecte et planifier maintenant.",
          );
  if (p.phase === "planning") $("plan-now").hidden = true;
}
async function finishPlanJob(result) {
  planUI.busy = false;
  planUI.job = null;
  if (result?.rows) showPlan(result);
  else
    showPlan(
      await api(`zen/plan?client_id=${encodeURIComponent(state.clientId)}`),
    );
  if (result?.added)
    $("plan-progress").textContent =
      `${result.added.length} ${say("download(s) sent", "téléchargement(s) envoyé(s)")} · ${result.reseeded.length} Reseeds · ${result.refused.length} ${say("refused", "refusés")} · ${result.failed.length} ${say("failed", "échecs")}`;
  else if (typeof result === "string") $("plan-progress").textContent = result;
  else $("plan-progress").textContent = "";
  for (const [title, reason] of [
    ...(result?.refused || []),
    ...(result?.failed || []),
  ])
    $("plan-diagnostics").append(element("p", `${title}: ${reason}`));
  planActions();
}
async function startPlanJob(body) {
  planUI.busy = true;
  planUI.sending = body.kind === "send-plan";
  planUI.job = null;
  planUI.phase = "fetching";
  planActions();
  try {
    const id = await job(body, finishPlanJob, finishPlanJob, planProgress);
    if (state.jobs.has(id)) planUI.job = id;
    planActions();
  } catch (error) {
    planUI.busy = false;
    planActions();
    if (error.action?.kind === "plan-folder")
      await planFolderDialog(error.action.client_id, error.action.category);
    else throw error;
  }
}
$("plan-form").onsubmit = (e) => {
  e.preventDefault();
  guard(async () => {
    const clients = [
      ...$("plan-clients").querySelectorAll("input[data-client-id]:checked"),
    ].map((e) => e.dataset.clientId);
    if (!clients.length)
      throw Error(
        say(
          "Select at least one Torrent Client.",
          "Sélectionnez au moins un client torrent.",
        ),
      );
    await startPlanJob({
      kind: "plan",
      client_ids: clients,
      client_budgets: Object.fromEntries(
        [...$("plan-clients").querySelectorAll("input[data-budget-id]")].map(
          (e) => [e.dataset.budgetId, Math.round(Number(e.value) * 1024 ** 3)],
        ),
      ),
      categories: [...$("plan-category").selectedOptions]
        .filter((o) => o.value)
        .map((o) => Number(o.value)),
      plan_goal: $("plan-goal").value,
      maximum_bytes: Math.round(Number($("plan-budget").value) * 1024 ** 3),
      maximum_torrents: $("plan-limit-count").checked
        ? Number($("plan-count").value)
        : 100,
      limit_torrents: $("plan-limit-count").checked,
      max_seeders: $("plan-limit-seeders").checked
        ? Number($("plan-seeders").value)
        : null,
      min_size: Math.round(Number($("plan-min-size").value) * 1024 ** 3),
      max_size: Math.round(Number($("plan-max-size").value) * 1024 ** 3),
      cached_only: $("plan-cached").checked,
    });
  });
};
$("plan-form").addEventListener("input", invalidatePlan);
$("plan-form").addEventListener("change", invalidatePlan);
$("plan-clients").addEventListener("input", invalidatePlan);
$("plan-sort").onchange = $("plan-sort-order").onchange = () => {
  state.planOffset = 0;
  renderPlan();
};
$("plan-select-all").onclick = () => {
  state.planSelected = new Set(state.planRows.map((r) => r.hash));
  renderPlan();
};
$("plan-select-none").onclick = () => {
  state.planSelected.clear();
  renderPlan();
};
$("plan-now").onclick = () =>
  guard(async () => {
    if (planUI.job) await api(`jobs/${planUI.job}/plan-now`, {});
    $("plan-now").disabled = true;
  });
$("plan-stop").onclick = () =>
  guard(async () => {
    if (planUI.job) await api(`jobs/${planUI.job}/cancel`, {});
    $("plan-stop").disabled = true;
    $("plan-progress").textContent = say(
      "Stopping after the current torrent…",
      "Arrêt après le torrent en cours…",
    );
  });
$("plan-send").onclick = () =>
  guard(async () => {
    if (state.planDirty || planUI.busy) return;
    const rows = state.planRows.filter((r) => state.planSelected.has(r.hash)),
      reseeds = rows.filter((r) => r.reseed).length;
    const id = state.planId,
      hashes = rows.map((r) => r.hash);
    const body = {
      kind: "send-plan",
      client_id: state.clientId,
      plan_id: id,
    plan_selection: hashes.length === state.planRows.length ? [] : hashes,
    };
    const review = await api("zen/plan/review", body);
    $("dialog").setAttribute(
      "aria-label",
      say("Send this Plan?", "Envoyer ce Plan ?"),
    );
    $("dialog-content").replaceChildren(
      element("h2", say("Send this Plan?", "Envoyer ce Plan ?")),
      element(
        "p",
        `${rows.length - reseeds} ${say("download(s)", "téléchargement(s)")} · ${reseeds} Reseeds · ${bytes(rows.reduce((n, r) => n + (r.download_size ?? r.size), 0))}`,
      ),
      element(
        "p",
        say(
          "Downloads start in their assigned Torrent Clients. Reseeds must pass hash verification before seeding. Existing files are never overwritten.",
          "Les téléchargements démarrent dans leurs clients torrent. Les Reseeds doivent réussir la vérification des hashes avant le seed. Les fichiers existants ne sont jamais écrasés.",
        ),
      ),
      button(say("Cancel", "Annuler"), () => $("dialog").close()),
      button(
        say("Send selected", "Envoyer la sélection"),
        () =>
          guard(async () => {
            $("dialog").close();
            $("plan-stop").disabled = false;
            await startPlanJob({ ...body, confirmation: review.token });
          }),
        "primary",
      ),
    );
    if (review.renames.length) {
      const warning = element("section");
      warning.append(
        element(
          "h3",
          say(
            "Your Torrent Client cannot rename files inside a torrent: these files will be renamed on disk",
            "Votre client torrent ne sait pas renommer un fichier dans un torrent : ces fichiers seront renommés sur le disque",
          ),
        ),
        element(
          "p",
          say(
            "Sending this selection also approves the renames below. This can break other torrents, readers or shortcuts using the old paths. Contents stay unchanged; occupied destinations are refused. If verification fails, original names are restored only when safe.",
            "L’envoi de cette sélection approuve également les renommages ci-dessous. Cela peut casser d’autres torrents, lecteurs ou raccourcis utilisant les anciens chemins. Le contenu reste intact ; les destinations occupées sont refusées. Si la vérification échoue, les noms sont restaurés uniquement si cela est sûr.",
          ),
        ),
      );
      for (const move of review.renames)
        warning.append(element("p", `${move.source} → ${move.target}`));
      $("dialog-content").insertBefore(
        warning,
        $("dialog-content").querySelector("button"),
      );
      $("dialog-content").querySelector("button.primary").textContent = say(
        "Rename files and send selected",
        "Renommer les fichiers et envoyer la sélection",
      );
    }
    $("dialog").showModal();
  });
async function saveZenPreferences(body) {
  fillZenPreferences(await api("zen/preferences", body));
  await Promise.all([loadZenSeeding(), loadZenPlan()]);
  $("plan-progress").textContent = say(
    "Preferences saved. Build a new Plan to use them.",
    "Paramètres enregistrés. Créez un nouveau Plan pour les appliquer.",
  );
}
$("zen-preferences-form").onsubmit = (e) => {
  e.preventDefault();
  guard(() =>
    saveZenPreferences({
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
    }),
  );
};
$("seeding-save-uploads").onclick = () =>
  guard(() =>
    saveZenPreferences({ uploads: Number($("seeding-uploads").value) }),
  );
$("plan-speed-save").onclick = () =>
  guard(() =>
    saveZenPreferences({
      download_speed: (Number($("plan-speed").value) * 1e6) / 8,
    }),
  );
$("plan-speed-test").onclick = () =>
  guard(async () => {
    $("plan-speed-test").disabled = true;
    try {
      await job(
        { kind: "speed-test" },
        async (p) => {
          fillZenPreferences(p);
          $("plan-speed-test").disabled = false;
          showPlan(
            await api(
              `zen/plan?client_id=${encodeURIComponent(state.clientId)}`,
            ),
          );
        },
        () => {
          $("plan-speed-test").disabled = false;
        },
      );
    } catch (e) {
      $("plan-speed-test").disabled = false;
      throw e;
    }
  });
async function finishCatalogue() {
  planUI.catalogueJob = null;
  $("catalogue-pause").hidden = true;
  $("catalogue").disabled = false;
  const value = await api("zen/catalogue");
  showCatalogue(value);
  $("catalogue").textContent = value.paused
    ? say("Resume catalogue", "Reprendre le catalogue")
    : say("Update catalogue", "Actualiser le catalogue");
}
$("catalogue").onclick = () =>
  guard(async () => {
    $("catalogue").disabled = true;
    try {
      const id = await job(
        { kind: "catalogue" },
        finishCatalogue,
        finishCatalogue,
      );
      if (state.jobs.has(id)) {
        planUI.catalogueJob = id;
        $("catalogue-pause").hidden = false;
      }
    } catch (e) {
      $("catalogue").disabled = false;
      throw e;
    }
  });
$("catalogue-pause").onclick = () =>
  guard(async () => {
    if (planUI.catalogueJob)
      await api(`jobs/${planUI.catalogueJob}/cancel`, {});
    $("catalogue-status").textContent = say(
      "Pausing after the current page…",
      "Suspension après la page en cours…",
    );
  });
async function planFolderDialog(clientId = state.clientId, category = null) {
  const content = $("dialog-content");
  $("dialog").setAttribute(
    "aria-label",
    say(
      "Category Download Folders",
      "Dossiers de téléchargement par catégorie",
    ),
  );
  const clients = element("select"),
    cats = element("select"),
    path = element("input"),
    feedback = element("p"),
    folders = element("div");
  clients.setAttribute("aria-label", say("Torrent Client", "Client torrent"));
  cats.setAttribute("aria-label", say("Category", "Catégorie"));
  path.setAttribute(
    "aria-label",
    say("Folder on the TorrentLinker host", "Dossier sur l’hôte TorrentLinker"),
  );
  for (const p of state.setup.clients.filter((p) => p.enabled))
    clients.add(new Option(p.name, p.id));
  clients.value = clientId;
  cats.add(new Option(say("Default", "Par défaut"), ""));
  for (const [id, c] of Object.entries(state.setup.indexer_categories))
    cats.add(new Option(c.name, id));
  cats.value = category === null ? "" : String(category);
  const categoryTree = categoryPicker(cats, state.setup.indexer_categories);
  async function load() {
    const setup = await api(
      `setup?client_id=${encodeURIComponent(clients.value)}`,
    );
    path.value = cats.value
      ? setup.download_folders.effective[cats.value] || ""
      : setup.download_folder;
  }
  clients.onchange = cats.onchange = () => guard(load);
  async function browsePlanFolder(current = "") {
    const result = await api(`folders?path=${encodeURIComponent(current)}`);
    folders.replaceChildren(
      element("p", result.path || say("Mounted roots", "Racines montées")),
    );
    if (result.path)
      folders.append(
        button(say("Use this folder", "Utiliser ce dossier"), () => {
          path.value = result.path;
          folders.replaceChildren();
        }),
        button("↑", () => browsePlanFolder(result.parent)),
      );
    for (const value of result.folders)
      folders.append(
        button(value, () => browsePlanFolder(value), "directory-button"),
      );
  }
  content.replaceChildren(
    element(
      "p",
      say(
        "Paths belong to the TorrentLinker host. Empty folders are checked automatically with a temporary file, then the test file and torrent are removed.",
        "Ces chemins appartiennent à l’hôte TorrentLinker. Les dossiers vides sont vérifiés automatiquement avec un fichier temporaire, puis le fichier et le torrent de test sont supprimés.",
      ),
    ),
    clients,
    cats,
    categoryTree,
    path,
    button(say("Browse host folders", "Parcourir les dossiers de l’hôte"), () =>
      browsePlanFolder(),
    ),
    folders,
    feedback,
    button(
      say("Save folder", "Enregistrer le dossier"),
      () =>
        guard(async () => {
          await job(
            {
              kind: "configure-download-folder",
              client_id: clients.value,
              category: cats.value ? Number(cats.value) : null,
              path: path.value,
            },
            async () => {
              feedback.textContent = say(
                "Folder verified and saved. Build the Plan again.",
                "Dossier vérifié et enregistré. Recréez le Plan.",
              );
              await refreshSetup();
              invalidatePlan();
            },
            (error) => {
              feedback.textContent = error;
            },
          );
        }),
      "primary",
    ),
  );
  if (!$("dialog").open) $("dialog").showModal();
  await load();
}
$("plan-folders").onclick = () => guard(() => planFolderDialog());
