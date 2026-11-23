"use strict";
const seedingFrame = document.createElement("iframe");
seedingFrame.id = "seeding-frame";
seedingFrame.title = "Seeding";
seedingFrame.src = "static/seeding/view.html";
seedingFrame.style.cssText =
  "width:100%;height:75vh;min-height:300px;border:0;display:block";
$("zen-seeding-panel").append(seedingFrame);
const seedingHost = { revision: 0, generation: 0, busy: new Set(), error: "" };
const seedingPreferenceKey = (client) =>
  `${location.pathname}:seeding:${client}`;
function expandedCategories() {
  try {
    return JSON.parse(
      localStorage.getItem(seedingPreferenceKey(state.clientId)) || "[]",
    );
  } catch {
    return [];
  }
}
function seedingEnvironment() {
  const active =
    state.view === "zen" &&
    !$("zen-seeding-panel").hidden &&
    !$("workspace").hidden;
  if (active)
    seedingFrame.style.height = `${Math.max(300, innerHeight - seedingFrame.getBoundingClientRect().top - 24)}px`;
  seedingFrame.contentWindow?.postMessage(
    {
      type: "seeding-environment",
      value: {
        mode: "web",
        language,
        theme: document.documentElement.dataset.theme || "dark",
        active,
        state: {
          client_id: state.clientId,
          expanded: expandedCategories(),
          revision: seedingHost.revision,
          busy: seedingHost.busy.has(state.clientId),
          error: seedingHost.error,
        },
      },
    },
    location.origin,
  );
}
async function loadZenSeeding() {
  const client = state.clientId,
    generation = ++seedingHost.generation;
  seedingHost.error = "";
  try {
    const [result, jobs] = await Promise.all([
      api(`zen/seeding?client_id=${encodeURIComponent(client)}`),
      api("jobs"),
    ]);
    if (client !== state.clientId || generation !== seedingHost.generation)
      return;
    const running = jobs.filter(
      (row) => row.kind === "refresh" && row.client_id === client &&
        ["queued", "running"].includes(row.status),
    );
    for (const row of running) {
      if (!state.jobs.has(row.id))
        state.jobs.set(row.id, {
          body: { kind: "refresh", client_id: client },
          done: () => finishSeeding(client),
          failed: (error) => finishSeeding(client, error),
        });
    }
    if (running.length)
      seedingHost.busy.add(client);
    else seedingHost.busy.delete(client);
    shellSetSeeding(client, result.summary.daily);
    $("zen-daily").textContent = num(result.summary.daily);
    $("zen-count").textContent = result.summary.count;
  } catch (error) {
    if (client !== state.clientId || generation !== seedingHost.generation)
      return;
    seedingHost.error = error.message;
  }
  seedingHost.revision++;
  seedingEnvironment();
}
async function finishSeeding(client, error = "") {
  seedingHost.busy.delete(client);
  if (client !== state.clientId) return;
  await loadZenSeeding();
  if (client === state.clientId && error) {
    seedingHost.error = error;
    seedingEnvironment();
  }
}
window.addEventListener("message", async (event) => {
  if (
    event.source !== seedingFrame.contentWindow ||
    event.origin !== location.origin
  )
    return;
  const message = event.data;
  if (message?.type === "seeding-ready") {
    seedingEnvironment();
    return;
  }
  if (message?.type !== "seeding-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    const { _client, ...body } = message.body || {},
      client = state.clientId;
    if (_client !== client)
      throw Error("The target client changed. Reopen Seeding.");
    let value = null;
    if (message.path === "page")
      value = await api(
        `zen/seeding?${new URLSearchParams({ ...body, client_id: client })}`,
      );
    else if (message.path === "expanded") {
      if (
        !Array.isArray(body.groups) ||
        body.groups.some((value) => typeof value !== "string")
      )
        throw Error("Invalid expanded categories.");
      localStorage.setItem(
        seedingPreferenceKey(client),
        JSON.stringify(body.groups),
      );
    } else if (message.path === "refresh") {
      seedingHost.generation++;
      seedingHost.busy.add(client);
      seedingEnvironment();
      try {
        await job(
          { kind: "refresh", client_id: client },
          () => finishSeeding(client),
          (error) => finishSeeding(client, error),
        );
        if (client === state.clientId) seedingHost.generation++;
      } catch (error) {
        seedingHost.busy.delete(client);
        seedingEnvironment();
        throw error;
      }
    } else if (message.path === "uploads") {
      await api("zen/preferences", { uploads: body.uploads });
      await loadZenSeeding();
    } else throw Error("Unknown Seeding operation.");
    seedingFrame.contentWindow?.postMessage(
      { type: "seeding-response", id: message.id, value },
      location.origin,
    );
  } catch (error) {
    seedingFrame.contentWindow?.postMessage(
      { type: "seeding-response", id: message.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", seedingEnvironment);
document.addEventListener("tl-language-changed", seedingEnvironment);
new MutationObserver(seedingEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});
for (const node of [$("zen-seeding-panel"), $("view-zen"), $("workspace")])
  new MutationObserver(seedingEnvironment).observe(node, {
    attributes: true,
    attributeFilter: ["hidden"],
  });
