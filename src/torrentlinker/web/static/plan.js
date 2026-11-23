"use strict";
const planFrame = document.createElement("iframe");
planFrame.id = "plan-frame";
planFrame.title = "Plan";
planFrame.src = "static/plan/view.html";
planFrame.style.cssText =
  "width:100%;height:75vh;min-height:300px;border:0;display:block";
$("zen-plan-panel").append(planFrame);
const planHost = {
  client: "",
  generation: 0,
  value: null,
  job: null,
  progress: null,
  options: null,
  finished: new Set(),
  sentResult: null,
  pending: null,
  operations: new Map(),
};
function planOperation(client, advance = false) {
  const value = (planHost.operations.get(client) || 0) + (advance ? 1 : 0);
  if (advance) planHost.operations.set(client, value);
  return value;
}
function planEnvironment(force = false) {
  shellEnvironment();
  const active =
    state.view === "zen" &&
    !$("zen-plan-panel").hidden &&
    !$("workspace").hidden;
  if (active)
    planFrame.style.height = `${Math.max(300, innerHeight - planFrame.getBoundingClientRect().top - 24)}px`;
  let value = planHost.value;
  if (value?.result) {
    const result = value.result;
    if (!force && planHost.sentResult === result) {
      const { rows, on_disk, ...summary } = result;
      value = { ...value, result: { ...summary, rows_unchanged: true } };
    }
    planHost.sentResult = result;
  }
  planFrame.contentWindow?.postMessage(
    {
      type: "plan-environment",
      value: {
        mode: "web",
        language,
        theme: document.documentElement.dataset.theme || "dark",
        active,
        state: value || {
          ready: false,
          client_id: state.clientId,
          result: { plan_id: "", rows: [] },
        },
      },
    },
    location.origin,
  );
}
function planJobState(row) {
  if (!planHost.value) return;
  planHost.job = row?.id || null;
  planHost.progress = row?.progress || null;
  Object.assign(planHost.value, {
    busy: Boolean(row),
    fetching: Boolean(
      row && row.kind === "plan" && row.progress?.phase !== "planning",
    ),
    progress:
      row?.kind === "send-plan" ? row.progress || { done: 0, total: 0 } : null,
    testing: row?.kind === "speed-test",
    message:
      row?.kind === "plan"
        ? say("Preparing the Plan…", "Préparation du Plan…")
        : "",
  });
  planEnvironment();
}
function planJobs(rows) {
  if (planHost.client !== state.clientId || !planHost.value) return;
  rows = rows.filter((r) => !planHost.finished.has(r.id));
  const row =
    rows.find(
      (r) =>
        r.client_id === state.clientId &&
        ["plan", "send-plan", "speed-test"].includes(r.kind) &&
        r.status === "running",
    ) ||
    rows.find(
      (r) =>
        r.client_id === state.clientId &&
        ["plan", "send-plan", "speed-test"].includes(r.kind) &&
        r.status === "queued",
    );
  if (!row) return; // Terminal callbacks clear the current operation, not older idle polls.
  planJobState(row);
  if (!state.jobs.has(row.id)) trackPlanJob(row.id, row.client_id, row.kind);
}
function trackPlanJob(id, client, kind) {
  state.jobs.set(id, {
    body: { client_id: client, kind },
    done: (result) =>
      finishPlanJob(client, null, id, kind === "send-plan" ? result : null),
    failed: (error, result) =>
      finishPlanJob(client, error, id, kind === "send-plan" ? result : null),
    progress: (p) => {
      if (planHost.client === client) planJobState({ id, kind, progress: p });
    },
  });
}
async function loadZenPlan() {
  const client = state.clientId,
    generation = ++planHost.generation,
    operation = planOperation(client);
  if (client === "all") {
    planHost.client = client;
    planHost.value = {
      client_id: client,
      result: { plan_id: "", rows: [] },
      message: say(
        "Choose a target client to review its Plan.",
        "Choisissez un client cible pour afficher son Plan.",
      ),
    };
    planEnvironment();
    return;
  }
  const [result, preferences, setup, jobs] = await Promise.all([
    api(`zen/plan?client_id=${encodeURIComponent(client)}`),
    api("zen/preferences"),
    api(`setup?client_id=${encodeURIComponent(client)}`),
    api("jobs"),
  ]);
  if (
    generation !== planHost.generation ||
    client !== state.clientId ||
    operation !== planOperation(client)
  )
    return;
  const categories = [],
    seen = new Set();
  function append(id, entry, depth = 0) {
    if (seen.has(id)) return;
    seen.add(id);
    categories.push([Number(id), entry.name, depth > 0]);
    for (const [child, value] of Object.entries(setup.indexer_categories || {}))
      if (String(value.parent) === id) append(child, value, depth + 1);
  }
  for (const [id, entry] of Object.entries(setup.indexer_categories || {}))
    if (!entry.parent || !setup.indexer_categories[entry.parent])
      append(id, entry);
  planHost.client = client;
  planHost.value = {
    ready: true,
    client_id: client,
    result,
    preferences,
    options: preferences.plan_options,
    chosen_categories: preferences.plan_categories,
    categories,
    without_folder: categories
      .filter(([id]) => !setup.download_folders?.effective?.[id])
      .map(([id]) => id),
    clients: setup.clients,
    busy: false,
    fetching: false,
    progress: null,
    download_speed: preferences.download_speed,
    download_speed_tested: preferences.download_speed_tested,
  };
  planJobState(null);
  planJobs(jobs);
  if (planHost.pending?.client === client)
    planJobState({ id: null, kind: planHost.pending.kind });
  planEnvironment();
}
async function finishPlanJob(client, error, id, report) {
  planOperation(client, true);
  planHost.finished.add(id);
  if (client !== state.clientId) return;
  await loadZenPlan();
  if (client !== state.clientId || planHost.client !== client) return;
  if (report && planHost.value) {
    planHost.value.report = report;
    planEnvironment();
  }
  if (error && planHost.value) {
    planHost.value.message = error;
    planEnvironment();
  }
  guard(refreshCatalogue);
}
async function submitPlanJob(body) {
  const client = body.client_id || state.clientId;
  if (client === "all")
    throw Error(
      say("Choose a target client first.", "Choisissez un client cible."),
    );
  const operation = planOperation(client, true);
  planHost.pending = { client, kind: body.kind, operation };
  if (client === planHost.client) planJobState({ id: null, kind: body.kind });
  try {
    const result = await api("jobs", { ...body, client_id: client });
    planOperation(client, true);
    if (
      planHost.pending?.client === client &&
      planHost.pending.operation === operation
    )
      planHost.pending = null;
    trackPlanJob(result.id, client, body.kind);
    if (client === state.clientId && client === planHost.client)
      planJobState({ id: result.id, kind: body.kind, progress: null });
    await pollJobs();
    return result.id;
  } catch (error) {
    if (
      planHost.pending?.client === client &&
      planHost.pending.operation === operation
    ) {
      planHost.pending = null;
      if (client === planHost.client) planJobState(null);
    }
    throw error;
  }
}
async function startCachedPlan() {
  const client = state.clientId;
  await loadZenPlan();
  if (client !== state.clientId || planHost.client !== client) return;
  const p = planHost.value?.preferences,
    o = p?.plan_options || {};
  await submitPlanJob({
    kind: "plan",
    cached_only: true,
    client_id: client,
    plan_goal: o.goal || "note",
    maximum_bytes: o.max_download_bytes || 0,
    maximum_torrents: o.max_torrents || 100,
    limit_torrents: o.max_torrents != null,
    max_seeders: o.max_seeders,
    min_seeders: o.min_seeders || 0,
    minimum_torrents: o.min_torrents || 0,
    min_size: o.min_size || 0,
    max_size: o.max_size || 0,
    categories: p?.plan_categories,
  });
}
window.addEventListener("message", async (event) => {
  if (
    event.source !== planFrame.contentWindow ||
    event.origin !== location.origin
  )
    return;
  const message = event.data;
  if (message?.type === "plan-ready") {
    planEnvironment(true);
    return;
  }
  if (message?.type !== "plan-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    const { _client, ...body } = message.body || {},
      client = state.clientId;
    if (_client !== client || client === "all")
      throw Error(
        say(
          "The target client changed. Reopen Plan.",
          "Le client cible a changé. Rouvrez le Plan.",
        ),
      );
    let value = null;
    if (message.path === "state") {
      await loadZenPlan();
      value = planHost.value;
    } else if (message.path === "configure") {
      planHost.options = body.options;
    } else if (message.path === "build") {
      planHost.options = body.options;
      await submitPlanJob({
        ...body.options,
        kind: "plan",
        cached_only: Boolean(body.cached_only),
        client_id: client,
      });
    } else if (message.path === "review")
      value = await api("zen/plan/review", {
        kind: "send-plan",
        client_id: client,
        plan_id: body.plan_id,
        plan_selection: body.hashes,
      });
    else if (message.path === "send")
      await submitPlanJob({
        kind: "send-plan",
        client_id: client,
        plan_id: body.plan_id,
        plan_selection: body.hashes,
        confirmation: body.confirmation,
      });
    else if (message.path === "stop-fetch" || message.path === "stop-send") {
      if (!planHost.job) throw Error("No active Plan operation.");
      await api(
        `jobs/${planHost.job}/${message.path === "stop-fetch" ? "plan-now" : "cancel"}`,
        {},
      );
    } else if (message.path === "preferences") {
      value = await api("zen/preferences", body);
      await loadZenPlan();
      guard(loadZenSeeding);
    } else if (message.path === "speed-test")
      await submitPlanJob({ kind: "speed-test", client_id: client });
    else if (message.path === "folders") {
      if (body.browse)
        value = await api(
          `folders?path=${encodeURIComponent(body.path || "")}`,
        );
      else {
        const setup = await api(
          `setup?client_id=${encodeURIComponent(body.client_id || client)}`,
        );
        value = {
          path: body.category
            ? setup.download_folders.effective[body.category] || ""
            : setup.download_folder,
        };
      }
    } else if (message.path === "save-folder") {
      const id = await job({
        kind: "configure-download-folder",
        client_id: body.client_id || client,
        category: body.category,
        path: body.path,
      });
      await waitForJob(id);
      await refreshSetup();
      await loadZenPlan();
      value = { saved: true };
    } else if (message.path === "queue") {
      const current = await api(
        `zen/plan?client_id=${encodeURIComponent(client)}`,
      );
      if (
        !body.plan_id ||
        body.plan_id !== current.plan_id ||
        !Array.isArray(body.hashes) ||
        !body.hashes.length
      )
        throw Error("Review the current Plan before queueing.");
      const selected = current.rows.filter(
        (r) => !r.reseed && body.hashes.includes(r.hash),
      );
      if (
        new Set(selected.map((r) => r.hash)).size !== new Set(body.hashes).size
      )
        throw Error("Select downloads from the current Plan.");
      const groups = new Map();
      for (const row of selected) {
        const target = row.client_id || client;
        if (!groups.has(target)) groups.set(target, []);
        groups.get(target).push(row.hash);
      }
      for (const [target, hashes] of groups)
        for (let offset = 0; offset < hashes.length; offset += 1000) {
          const id = await job({
            kind: "enqueue",
            client_id: target,
            hashes: hashes.slice(offset, offset + 1000),
          });
          await waitForJob(id);
        }
      value = { queued: selected.length };
    } else throw Error("Unknown Plan operation.");
    planFrame.contentWindow?.postMessage(
      { type: "plan-response", id: message.id, value },
      location.origin,
    );
  } catch (error) {
    planFrame.contentWindow?.postMessage(
      {
        type: "plan-response",
        id: message.id,
        ...(error.action
          ? { value: { action: error.action, message: error.message } }
          : { error: error.message }),
      },
      location.origin,
    );
  }
});
window.addEventListener("resize", planEnvironment);
document.addEventListener("tl-language-changed", planEnvironment);
new MutationObserver(planEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});
for (const node of [$("zen-plan-panel"), $("view-zen"), $("workspace")])
  new MutationObserver(planEnvironment).observe(node, {
    attributes: true,
    attributeFilter: ["hidden"],
  });
