"use strict";
const shellFrames = new Map();
const shellState = {
  ready: false,
  lastClient: "",
  clientGeneration: 0,
  clientBusy: false,
  release: null,
  dismissed: "",
  seeding: null,
  seedingClient: "",
  bandClient: "",
  bandAt: 0,
};
const shellPages = [
  "zen",
  "library",
  "upload",
  "search",
  "feeds",
  "torrents",
  "assistant",
  "media",
  "queue",
  "requests",
  "notifications",
  "jobs",
  "documentation",
  "setup",
];
for (const region of ["navigation", "header", "band", "update", "help"]) {
  const frame = document.getElementById(`shell-${region}-frame`);
  shellFrames.set(region, frame);
}
function shellSnapshot(region) {
  const catalogue = catalogueUI.value || {},
    count = catalogue.count;
  const age = catalogue.updated_at
    ? Math.max(0, Math.floor((Date.now() / 1000 - catalogue.updated_at) / 60))
    : null;
  const catalogueText =
    count === undefined
      ? null
      : `${count} torrents${age === null ? "" : say(` · ${age} min old`, ` · vieux de ${age} min`)}`;
  return {
    mode: "web",
    region,
    language,
    theme: document.documentElement.dataset.theme || "dark",
    theme_choice: themeChoice,
    page: state.view,
    pages: state.pages || shellPages.filter(p => !["requests", "notifications"].includes(p) || state.setup?.members_enabled),
    client_id: state.clientId,
    allow_all: state.view === "torrents",
    clients: (state.setup?.clients || []).filter((row) => row.enabled),
    client_busy: shellState.clientBusy,
    // The phone drawer is as wide as the desktop sidebar, so it shows the same list.
    compact: false,
    can_logout: state.setup?.web_auth !== "proxy",
    shared_screen: !!state.actor?.screen,
    setup_needed: !signedInMember() && !state.setup?.indexer_configured,
    release: shellState.release,
    band: {
      balance:
        profileState?.overview?.zen?.balance ??
        profileState?.api?.balance ??
        null,
      seeding:
        shellState.seedingClient === state.clientId &&
        shellState.seeding !== null
          ? num(shellState.seeding)
          : null,
      plan:
        planHost.client === state.clientId &&
        planHost.value?.result?.zen !== undefined
          ? "+" + num(planHost.value.result.zen)
          : null,
      catalogue: catalogueText,
      busy: profileLoading,
    },
    profile_problem: state.view === "zen" ? profileState?.error || "" : "",
  };
}
async function shellEnsureBand() {
  if (!["library", "upload", "search", "feeds"].includes(state.view)) return;
  if (
    shellState.bandClient === state.clientId &&
    Date.now() - shellState.bandAt < 60000
  )
    return;
  shellState.bandClient = state.clientId;
  shellState.bandAt = Date.now();
  await Promise.allSettled([
    loadZenProfile(),
    loadZenSeeding(),
    loadZenPlan(),
    loadCatalogue(),
  ]);
  shellEnvironment();
}
function shellEnvironment() {
  if (!shellState.ready) return;
  const active = !$("workspace").hidden;
  $("shell-band-host").hidden =
    !active ||
    !["zen", "library", "upload", "search", "feeds"].includes(state.view) ||
    document.body.classList.contains("media-center-mode");
  $("shell-update-host").hidden =
    !active ||
    !shellState.release ||
    shellState.release.tag === shellState.dismissed;
  for (const [region, frame] of shellFrames) {
    frame.title = say(
      {
        navigation: "Navigation",
        header: "Workspace",
        band: "Zen overview",
        update: "Update notice",
        help: "Keyboard shortcuts",
      }[region],
      {
        navigation: "Navigation",
        header: "Espace de travail",
        band: "Résumé Zen",
        update: "Mise à jour",
        help: "Raccourcis clavier",
      }[region],
    );
    frame.contentWindow?.postMessage(
      { type: "shell-environment", value: shellSnapshot(region) },
      location.origin,
    );
  }
}
function shellSetSeeding(client, value) {
  shellState.seedingClient = client;
  shellState.seeding = value;
  shellEnvironment();
}
async function shellRelease() {
  try {
    const value = await api("shell");
    shellState.release = value.release;
    shellEnvironment();
  } catch {
    /* An unavailable update check does not block navigation. */
  }
}
function shellSpecificClient() {
  const clients = (state.setup?.clients || []).filter((row) => row.enabled);
  return clients.some((row) => row.id === shellState.lastClient)
    ? shellState.lastClient
    : clients.find((row) => row.id === state.setup?.default_client_id)?.id ||
        clients[0]?.id ||
        "";
}
async function shellSelectClient(identifier) {
  if (
    identifier === "all"
      ? state.view !== "torrents"
      : !(state.setup?.clients || []).some(
          (row) => row.enabled && row.id === identifier,
        )
  )
    throw Error("Unknown target client.");
  const generation = ++shellState.clientGeneration;
  if (state.clientId !== "all") shellState.lastClient = state.clientId;
  state.clientId = identifier;
  shellState.clientBusy = true;
  document.dispatchEvent(new Event("tl-client-changed"));
  state.selected.clear();
  state.queueSelected.clear();
  state.offset = 0;
  state.libraryOffset = 0;
  state.localItem = "";
  shellEnvironment();
  try {
    await refreshSetup();
    if (generation !== shellState.clientGeneration) return;
    await navigate(state.view);
    if (
      generation === shellState.clientGeneration &&
      state.setup.configured &&
      state.view !== "media"
    )
      await job(
        { kind: "refresh" },
        state.view === "zen" ? loadZenSeeding : loadTorrents,
      );
  } finally {
    if (generation === shellState.clientGeneration) {
      shellState.clientBusy = false;
      shellEnvironment();
    }
  }
}
const shellActions = {
  navigation: new Set(["navigate", "theme", "language", "shortcuts", "profile", "logout"]),
  header: new Set(["navigate", "client"]),
  band: new Set(["refresh-profile"]),
  update: new Set(["release", "dismiss"]),
  help: new Set(["close"]),
};
window.addEventListener("message", async (event) => {
  if (event.origin !== location.origin) return;
  const entry = [...shellFrames].find(
    ([, frame]) => event.source === frame.contentWindow,
  );
  if (!entry) return;
  const [region, frame] = entry,
    message = event.data;
  if (message?.type === "shell-ready") {
    shellEnvironment();
    return;
  }
  if (message?.type !== "shell-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    const values = message.body;
    if (!values || typeof values !== "object" || Array.isArray(values))
      throw Error("Invalid shell action.");
    const action = message.path;
    if (action === "layout") {
      if (region !== "navigation" || innerWidth < 650)
        frame.style.height = `${Math.max(28, Math.min(600, Number(values.height) || 28))}px`;
      if (region === "band") document.documentElement.style.setProperty("--shell-band-height", frame.style.height);
    } else {
      if (!shellActions[region].has(action))
        throw Error("Unknown shell action.");
      if (action === "navigate") {
        if (!(state.pages || shellPages).includes(values.view))
          throw Error("Unknown workspace.");
        await navigate(values.view);
        // On a phone the list is a drawer: it closes once a page is chosen.
        if (innerWidth < 650) setNavigation(false);
      } else if (action === "client") await shellSelectClient(values.client_id);
      else if (action === "theme") {
        if (!["auto", "light", "dark"].includes(values.value))
          throw Error("Unknown theme.");
        theme(values.value);
      } else if (action === "language") {
        if (!["en", "fr"].includes(values.value))
          throw Error("Unknown language.");
        changeLanguage(values.value);
      } else if (action === "profile") {
        if (!state.actor?.screen) throw Error("This browser is not a Shared Screen.");
        await whoWatches();
      } else if (action === "logout") {
        if (state.setup?.web_auth === "proxy")
          throw Error("Authentication is managed by the proxy.");
        await logout();
      } else if (action === "shortcuts") {
        $("shell-help-dialog").showModal();
        shellEnvironment();
      } else if (action === "close") $("shell-help-dialog").close();
      else if (action === "refresh-profile") await refreshZenProfile();
      else if (action === "dismiss")
        shellState.dismissed = shellState.release?.tag || "";
      else if (action === "release" && shellState.release) {
        const link = document.createElement("a");
        link.href = shellState.release.url;
        link.target = "_blank";
        link.rel = "noopener";
        link.click();
      }
      shellEnvironment();
    }
    frame.contentWindow?.postMessage(
      { type: "shell-response", id: message.id, value: null },
      location.origin,
    );
  } catch (error) {
    frame.contentWindow?.postMessage(
      { type: "shell-response", id: message.id, error: error.message },
      location.origin,
    );
    shellEnvironment();
  }
});
let shellWasCompact = innerWidth < 650;
window.addEventListener("DOMContentLoaded", () => {
  if (shellWasCompact) setNavigation(false);
  shellState.ready = true;
  shellEnvironment();
});
window.addEventListener("resize", () => {
  const compact = innerWidth < 650;
  if (compact !== shellWasCompact) setNavigation(!compact);
  shellWasCompact = compact;
  if (innerWidth >= 650) shellFrames.get("navigation").style.height = "100%";
  shellEnvironment();
});
document.addEventListener("tl-language-changed", shellEnvironment);
window.addEventListener("media-host-changed", shellEnvironment);
new MutationObserver(shellEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});
new MutationObserver(shellEnvironment).observe($("workspace"), {
  attributes: true,
  attributeFilter: ["hidden"],
});
