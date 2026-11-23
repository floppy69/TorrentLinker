"use strict";
document.querySelector("#view-library > p").hidden = true;
const reseedUI = { root: "", job: null, tab: "reseed" };
const reseedFrame = document.createElement("iframe");
reseedFrame.id = "reseed-frame";
reseedFrame.title = "Bibliothèque";
reseedFrame.src = "static/reseed/view.html";
reseedFrame.style.cssText =
  "width:100%;height:calc(100vh - 200px);min-height:240px;border:0;display:block";
$("library-reseed").replaceChildren(reseedFrame);
const reseedEnvironment = () => {
  if (!$("library-reseed").hidden)
    reseedFrame.style.height = `${Math.max(240, innerHeight - reseedFrame.getBoundingClientRect().top - 40)}px`;
  reseedFrame.contentWindow?.postMessage(
    {
      type: "reseed-environment",
      value: {
        mode: "web",
        tab: reseedUI.tab,
        language,
        theme: ["light", "dark"].includes(
          document.documentElement.dataset.theme,
        )
          ? document.documentElement.dataset.theme
          : matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light",
        client: state.clientId,
        active: !$("library-reseed").hidden && !$("workspace").hidden,
        clear: $("workspace").hidden,
      },
    },
    location.origin,
  );
};
async function loadReseed() {
  reseedEnvironment();
}
async function waitReseedJob(body) {
  const client = state.clientId;
  const created = await api("jobs", { ...body, client_id: client });
  for (;;) {
    if (client !== state.clientId)
      throw new Error("The target client changed. Reopen the Library.");
    const result = await api(`jobs/${created.id}`);
    if (result.status === "completed") return result.result;
    if (!["queued", "running"].includes(result.status))
      throw new Error(result.error || "Operation cancelled.");
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}
async function reseedRequest(action, body) {
  if (body._client !== state.clientId)
    throw new Error("The target client changed. Reopen the Library.");
  body = { ...body };
  delete body._client;
  if (action === "state") {
    const client = state.clientId;
    const [data, setup, jobs] = await Promise.all([
      api("reseed-workspace"),
      api("setup"),
      api("jobs"),
    ]);
    const current = jobs.find(
      (j) =>
        j.kind === "reseed-workspace" &&
        j.client_id === client &&
        ["running", "queued"].includes(j.status),
    );
    reseedUI.job = current?.id || null;
    reseedUI.root = data.link_root;
    reseedUI.rows = data.rows;
    const latest =
      current ||
      jobs.find((j) => j.kind === "reseed-workspace" && j.client_id === client);
    const progress = { ...current?.progress, paused_paths: data.paused_paths };
    const error = [
      latest?.error,
      ...(latest?.progress?.errors || []).map((e) => e.message),
    ]
      .filter(Boolean)
      .join("\n");
    return {
      error,
      jobs: jobs.filter(j => j.client_id === client && jobPage(j.kind) === "library").map(j => ({...j, subject: {...j.subject, path: j.subject?.path || data.repair_sources?.[j.subject?.repair_id]}, display: jobStatus(j), title: jobTitle(j)})),
      activity: jobs
        .filter(
          (j) =>
            j.client_id === client &&
            /^(scan|check|reseed|search-library|library-|unpack|find-compatible|combine-library|.*repair)/.test(
              j.kind,
            ),
        )
        .map((j) => ({
          at: j.created || 0,
          kind: j.kind,
          status: j.status,
          message: j.error || jobStatus(j),
        })),
      rows: data.rows,
      folder_errors: data.folder_errors,
      setup,
      running: !!current,
      paused: !!progress.paused,
      progress,
      scanning:
        Object.hasOwn(progress.active || {}, "") ||
        jobs.some(
          (j) =>
            j.kind === "scan" &&
            j.client_id === client &&
            ["running", "queued"].includes(j.status),
        ),
    };
  }
  if (action === "cancel-job") {
    const row = await api(`jobs/${encodeURIComponent(body.id)}`);
    if (row.client_id !== state.clientId) throw Error("The target client changed.");
    return api(`jobs/${encodeURIComponent(body.id)}/cancel`, {});
  }
  if (action === "inspect")
    return waitReseedJob({
      kind: "candidate-inspector",
      path: body.path,
      inspector_action: body.action,
      candidate_key: body.key || "",
      torrent_data: body.torrent_data || "",
    });
  if (action === "combine")
    return waitReseedJob({
      kind: "combine-library",
      paths: body.paths,
      selection_name: body.name,
    });
  if (action === "selection") return {};
  if (action === "tab") {
    reseedUI.tab = body.tab;
    return {};
  }
  if (action === "cross-seed" || action.startsWith("cross-seed-")) {
    const client = `client_id=${encodeURIComponent(state.clientId === "all" ? state.setup?.default_client_id || "" : state.clientId)}`;
    if (action === "cross-seed") return api(`cross-seed?${client}`);
    const verb = action.slice("cross-seed-".length);
    if (!["accept", "reject", "retry", "remove"].includes(verb))
      throw new Error("Unknown Cross-seed operation.");
    return api(`cross-seed/${encodeURIComponent(body.id)}/${verb}?${client}`, {});
  }
  if (action === "preview-folder") return api("setup/preview-folder", body);
  if (action === "remove-folder") return api("setup/remove-folder", body);
  if (action === "run")
    return api("jobs", {
      kind: "reseed-workspace",
      paths: body.paths,
      reseed_action: "all",
      link_root: reseedUI.root,
      candidate_key: body.key || "",
    });
  if (action === "pause-item" || action === "enqueue")
    return api(
      `reseed-workspace/control?client_id=${encodeURIComponent(state.clientId)}`,
      { ...body, action },
    );
  if (action === "pause")
    return api(`jobs/${reseedUI.job}/pause-reseed?paused=${!!body.paused}`, {});
  if (action === "stop") return api(`jobs/${reseedUI.job}/cancel`, {});
  if (action === "scan") {
    if (reseedUI.job)
      return api(
        `reseed-workspace/control?client_id=${encodeURIComponent(state.clientId)}`,
        { action: "scan", folders: body.folders },
      );
    return job({ kind: "scan", paths: body.folders || [] }, loadReseed);
  }
  if (action === "browse")
    return api(`folders?path=${encodeURIComponent(body.path || "")}`);
  if (action === "save-root") return api("setup/reseed-folder", body);
  if (action === "add-folder") return api("setup/folder", body);
  if (action === "add-client") {
    const result = await api("clients", body);
    state.clientId = result.client_id;
    await refreshSetup();
    await navigate("library", "reseed");
    return result;
  }
  if (action === "manage-folders") {
    await libraryTab("folders");
    return {};
  }
  if (action === "settings") {
    await openReseedSettings();
    return {};
  }
  if (action === "recovery-start") {
    if (
      ![
        "preview-unpack",
        "refresh-unpack",
        "unpack-reseed",
        "diagnose-repair",
        "prepare-repair",
        "refresh-repair",
        "start-repair",
      ].includes(body.kind)
    )
      throw new Error("Unknown archive or repair operation.");
    return api("jobs", { ...body, client_id: state.clientId });
  }
  if (action === "recovery-job" || action === "recovery-cancel") {
    const row = await api(`jobs/${encodeURIComponent(body.id)}`);
    if (row.client_id !== state.clientId)
      throw new Error("Select the Torrent Client used for this operation.");
    if (action === "recovery-cancel")
      await api(`jobs/${encodeURIComponent(body.id)}/cancel`, {});
    return row;
  }
  throw new Error("Unknown reseed operation.");
}
window.addEventListener("message", async (event) => {
  if (
    event.source !== reseedFrame.contentWindow ||
    event.origin !== location.origin
  )
    return;
  const message = event.data;
  if (message?.type === "reseed-ready") {
    reseedEnvironment();
    return;
  }
  if (message?.type !== "reseed-request") return;
  try {
    if ($("workspace").hidden)
      throw new Error("Open your signed-in workspace first.");
    const value = await reseedRequest(message.path, message.body || {});
    reseedFrame.contentWindow?.postMessage(
      { type: "reseed-response", id: message.id, value },
      location.origin,
    );
  } catch (error) {
    reseedFrame.contentWindow?.postMessage(
      { type: "reseed-response", id: message.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", reseedEnvironment);
document.addEventListener("tl-language-changed", reseedEnvironment);
for (const node of [
  $("library-reseed"),
  $("workspace"),
  document.documentElement,
])
  new MutationObserver(reseedEnvironment).observe(node, {
    attributes: true,
    attributeFilter: ["hidden", "data-theme"],
  });
async function openReseedSettings() {
  await navigate("setup", "connections");
}
