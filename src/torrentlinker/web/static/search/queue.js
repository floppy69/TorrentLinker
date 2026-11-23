/* Queue actions share the same persistent service on desktop and Web. */
let queueActive = null,
  queueSnapshot = "",
  polling = false;
const retryable = (r) =>
  r.status === "refused" || (r.status === "failed" && r.retry_safe);
const selectedQueue = () =>
  state.queueRows.filter((r) => state.queueSelected.has(r.key));
const labels = () => ({
  queued: say("Waiting", "En attente"),
  sending: say("Sending", "Envoi en cours"),
  sent: say("Sent", "Envoyé"),
  refused: say("Refused", "Refusé"),
  failed: say("Failed", "Échec"),
  uncertain: say("Check client", "Vérifier le client"),
});
function queueControls() {
  const rows = state.queueRows,
    selected = selectedQueue();
  $("start-queue").disabled =
    !!queueActive || !rows.some((r) => r.status === "queued");
  $("pause-queue").disabled = !queueActive;
  $("start-selected-queue").disabled =
    !!queueActive || !selected.some((r) => r.status === "queued");
  $("retry-queue").disabled = !!queueActive || !selected.some(retryable);
  $("remove-queue").disabled =
    !!queueActive || !selected.some((r) => r.status !== "sending");
  $("clear-sent-queue").disabled =
    !!queueActive || !rows.some((r) => r.status === "sent");
}
async function loadQueue() {
  const value = await request("state");
  queueActive = value.active;
  const snapshot = JSON.stringify([value, language]);
  if (snapshot !== queueSnapshot) {
    queueSnapshot = snapshot;
    state.queueRows = value.rows;
    state.queueSelected = new Set(
      [...state.queueSelected].filter((k) =>
        value.rows.some((r) => r.key === k),
      ),
    );
    const rows = value.rows,
      count = (status) => rows.filter((r) => r.status === status).length;
    $("queue-summary").textContent = say(
      `${rows.length} total · ${count("queued")} waiting · ${count("sent")} sent · ${rows.filter((r) => ["failed", "refused", "uncertain"].includes(r.status)).length} need attention`,
      `${rows.length} au total · ${count("queued")} en attente · ${count("sent")} envoyés · ${rows.filter((r) => ["failed", "refused", "uncertain"].includes(r.status)).length} à vérifier`,
    );
    // Nothing to start, pause or remove while the queue is empty.
    document.querySelector(".queue-foot").hidden = !rows.length;
    table(
      "queue-table",
      rows,
      [
        { label: "Torrent", name: true, render: (r) => r.title },
        { label: say("Size", "Taille"), render: (r) => bytes(r.size) },
        { label: "≈ Zen / " + say("d", "j"), render: (r) => num(r.zen) },
        { label: "≈ Note", render: (r) => num(r.note) },
        { label: say("Folder", "Dossier"), render: (r) => r.folder },
        {
          label: say("Status", "État"),
          render: (r) =>
            element(
              "span",
              labels()[r.status] || r.status,
              "badge " + r.status,
            ),
        },
        {
          label: say("Details", "Détails"),
          render: (r) =>
            r.status === "uncertain"
              ? say(
                  "Check the client before removing and queueing again.",
                  "Vérifier le client avant de retirer et remettre en file.",
                )
              : r.reason,
        },
        { label: "Client", render: (r) => r.client_name },
        {
          label: "",
          render: (r) => {
            const b = button("⋯", () =>
              openQueueMenu(r.key, b.getBoundingClientRect()),
            );
            b.setAttribute("aria-label", "Actions " + r.title);
            return b;
          },
        },
      ],
      state.queueSelected,
      "key",
      queueControls,
    );
    $("queue-progress").textContent = value.last?.error
      ? value.last.error
      : queueActive
        ? say(
            "Sending… You can pause further sends.",
            "Envoi en cours… Vous pouvez suspendre les prochains envois.",
          )
        : say(
            "Queue saved. Start when ready.",
            "File enregistrée. Démarrez quand vous êtes prêt.",
          );
  }
  queueControls();
}
async function queueAction(action, body = {}) {
  try {
    if (["remove", "retry"].includes(action)) {
      const keys = body.keys || [];
      for (let offset = 0; offset < keys.length; offset += 1000) {
        await request(action, {
          ...body,
          keys: keys.slice(offset, offset + 1000),
        });
      }
    } else {
      await request(action, body);
    }
  } finally {
    queueSnapshot = "";
    await loadQueue();
  }
}
$("start-queue").onclick = (event) => guard(() => queueAction("start"), event.currentTarget);
$("start-selected-queue").onclick = (event) =>
  guard(() =>
    queueAction("start", {
      keys: selectedQueue()
        .filter((r) => r.status === "queued")
        .map((r) => r.key),
    }), event.currentTarget);
$("pause-queue").onclick = (event) => guard(() => queueAction("pause"), event.currentTarget);
$("retry-queue").onclick = (event) =>
  guard(() => queueAction("retry", { keys: [...state.queueSelected] }), event.currentTarget);
$("remove-queue").onclick = (event) =>
  guard(() => queueAction("remove", { keys: [...state.queueSelected] }), event.currentTarget);
$("clear-sent-queue").onclick = (event) => guard(() => queueAction("clear-sent"), event.currentTarget);
$("back-results").onclick = (event) =>
  guard(() => request("navigate", { page: "search" }), event.currentTarget);
$("queue-torrents").onclick = (event) =>
  guard(() =>
    request("torrents", { hashes: selectedQueue().map((r) => r.hash) }), event.currentTarget);
$("subscribe-search").onclick = (event) =>
  guard(() => request("subscribe", { query: searchQuery() }), event.currentTarget);
function openQueueMenu(key, rect) {
  if (!state.queueSelected.has(key)) {
    state.queueSelected.clear();
    state.queueSelected.add(key);
  }
  $("queue-table")
    .querySelectorAll("tbody tr")
    .forEach(
      (tr) =>
        (tr.querySelector("input").checked = state.queueSelected.has(
          tr.dataset.key,
        )),
    );
  queueControls();
  const menu = $("queue-menu");
  menu.replaceChildren();
  for (const id of [
    "start-selected-queue",
    "pause-queue",
    "retry-queue",
    "remove-queue",
    "clear-sent-queue",
  ]) {
    const source = $(id),
      b = button(source.textContent, () => {
        menu.hidden = true;
        source.click();
      });
    b.setAttribute("role", "menuitem");
    b.disabled = source.disabled;
    menu.append(b);
  }
  menu.hidden = false;
  menu.style.left =
    Math.max(0, Math.min(rect.left, innerWidth - menu.offsetWidth)) + "px";
  menu.style.top =
    Math.max(0, Math.min(rect.bottom, innerHeight - menu.offsetHeight)) + "px";
  menu.querySelector("button:not(:disabled)")?.focus();
}
$("queue-table").oncontextmenu = (e) => {
  const row = e.target.closest("tr[data-key]");
  if (row) {
    e.preventDefault();
    openQueueMenu(row.dataset.key, { left: e.clientX, bottom: e.clientY });
  }
};
document.addEventListener("pointerdown", (e) => {
  if (!e.target.closest("#queue-menu")) $("queue-menu").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
    const row = e.target.closest("#queue-table tr[data-key]");
    if (row) {
      e.preventDefault();
      openQueueMenu(row.dataset.key, row.getBoundingClientRect());
    }
  }
  if (e.key === "Escape") {
    $("queue-menu").hidden = true;
    document.querySelectorAll(".fdrop[open]").forEach((d) => (d.open = false));
  }
});
window.addEventListener("scroll", () => ($("queue-menu").hidden = true), true);

async function pickFolder(input) {
  if (env.mode === "desktop") {
    const result = await request("pick");
    if (result.selected) input.value = result.selected;
    return;
  }
  const dialog = $("picker");
  async function browse(path = "") {
    const result = await request("browse", { path });
    dialog.replaceChildren(
      element("h2", say("Choose a folder", "Choisir un dossier")),
    );
    if (result.parent !== null && result.path)
      dialog.append(
        button("↑", () => browse(result.parent || ""), "browser-row"),
      );
    for (const folder of result.folders)
      dialog.append(
        button(
          typeof folder === "string" ? folder : folder.name || folder.path,
          () => browse(typeof folder === "string" ? folder : folder.path),
          "browser-row",
        ),
      );
    const foot = element("div", undefined, "dialog-foot");
    foot.append(button(say("Cancel", "Annuler"), () => dialog.close()));
    if (result.path)
      foot.append(
        button(
          say("Choose this folder", "Choisir ce dossier"),
          () => {
            input.value = result.path;
            dialog.close();
          },
          "primary",
        ),
      );
    dialog.append(foot);
  }
  await browse();
  dialog.showModal();
}
async function configureFolders(hashes) {
  const value = await request("folders", { hashes });
  if (!value.missing.length) return true;
  const client = env.client,
    dialog = $("folder-dialog");
  dialog.replaceChildren(
    element("h2", say("Category folders", "Dossiers par catégorie")),
    element(
      "p",
      say(
        "Each torrent uses its category folder configured for this client.",
        "Chaque torrent utilise le dossier de sa catégorie, configuré pour ce client.",
      ),
      "muted",
    ),
  );
  const inputs = [];
  for (const row of value.missing) {
    const section = element("section", undefined, "notice");
    section.append(
      element("strong", row.label),
      element(
        "p",
        say(
          "No folder defined for this category.",
          "Aucun dossier défini pour cette catégorie.",
        ),
      ),
    );
    const pathrow = element("div", undefined, "path-row"),
      input = element("input");
    input.className = "path";
    input.setAttribute("aria-label", row.label);
    inputs.push([row.category, input]);
    pathrow.append(
      input,
      button(say("Browse…", "Parcourir…"), () => pickFolder(input)),
    );
    section.append(pathrow);
    dialog.append(section);
  }
  dialog.append(
    element(
      "p",
      say(
        "New folders will be saved in this client’s settings and reused for future downloads in these categories.",
        "Les nouveaux dossiers seront enregistrés dans les réglages de ce client et utilisés pour les prochains téléchargements de ces catégories.",
      ),
      "muted",
    ),
  );
  return new Promise((resolve) => {
    let saved = false;
    dialog.onclose = () => resolve(saved);
    const foot = element("div", undefined, "dialog-foot");
    const save = button(
      say("Save and add to queue", "Enregistrer et ajouter à la file"),
      async () => {
        if (client !== env.client)
          throw Error(
            say("The target client changed.", "Le client cible a changé."),
          );
        if (inputs.some(([, i]) => !i.value.trim()))
          throw Error(
            say(
              "Choose a folder for each missing category.",
              "Choisissez un dossier pour chaque catégorie manquante.",
            ),
          );
        save.disabled = true;
        try {
          for (const [category, input] of inputs) {
            if (
              (await request("folders", { hashes })).missing.some(
                (r) => r.category === category,
              )
            )
              await request("configure-folder", {
                hashes,
                category,
                path: input.value.trim(),
              });
          }
          saved = true;
          dialog.close();
        } finally {
          save.disabled = false;
        }
      },
      "primary",
    );
    foot.append(
      button(say("Close", "Fermer"), () => dialog.close()),
      save,
    );
    dialog.append(foot);
    dialog.showModal();
  });
}
const posterPromises = new Map(),
  posterWaiters = [];
let posterActive = 0;
async function fetchPoster(url) {
  if (posterActive >= 3)
    await new Promise((resolve) => posterWaiters.push(resolve));
  else posterActive++;
  try {
    return (await request("poster", { url })).src;
  } catch {
    return null;
  } finally {
    const next = posterWaiters.shift();
    if (next) next();
    else posterActive--;
  }
}
async function loadPoster(img, url) {
  if (!posterPromises.has(url)) {
    if (posterPromises.size >= 120)
      posterPromises.delete(posterPromises.keys().next().value);
    posterPromises.set(url, fetchPoster(url));
  }
  const src = await posterPromises.get(url);
  if (src) img.src = src;
  else img.remove();
}
window.addEventListener("search-environment", (event) => {
  const next = event.detail,
    changed = env.client !== next.client,
    langChanged = language !== (next.language?.startsWith("fr") ? "fr" : "en"),
    pageChanged = env.page !== next.page,
    adultChanged = "adult" in env && env.adult !== next.adult;
  if (changed) {
    generation++;
    clearDetailTabs();
    SS.loaded = false;
    SS.loading = null;
    SS.searched = false;
    SS.rows = [];
    SS.listing = {};
    SS.known = {};
    state.searchSelected.clear();
    state.queueSelected.clear();
    queueSnapshot = "";
    $("folder-dialog").close();
    $("picker").close();
  }
  env = next;
  language = next.language?.startsWith("fr") ? "fr" : "en";
  document.documentElement.dataset.theme = next.theme || "dark";
  translate();
  if (langChanged) {
    renderDetailTabs();
    for (const tab of detailTabs.values()) guard(() => loadDetail(tab));
  }
  if (next.standalone) {
    if (next.active && next.row) guard(() => openDetail(next.row));
    return;
  }
  // Adult content adds or removes the XXX root: read the category tree again now, since
  // coming back to Search does not reload it.
  if (adultChanged && !changed && SS.loaded) {
    const reset = !next.adult && SS.category !== "";
    if (reset) {
      SS.category = "";
      SS.chosen.clear();
    }
    guard(() => loadSearchOptions(reset ? () => guard(() => runSearch(1)) : undefined));
  }
  if (changed || langChanged) searchRetranslate();
  if (next.active)
    guard(() =>
      navigate(changed || pageChanged ? next.page || "search" : activePage),
    );
});
setInterval(async () => {
  if (polling || !env.active || env.standalone) return;
  polling = true;
  try {
    if (activePage === "queue") await loadQueue();
    else await refreshQueueCount();
  } catch {
  } finally {
    polling = false;
  }
}, 2000);

window.addEventListener("message", (event) => {
  if (
    event.source === parent &&
    event.origin === location.origin &&
    event.data?.type === "search-enqueue"
  )
    guard(() => searchEnqueue([event.data.hash]));
});

$("queue-refresh").onclick = (event) => guard(loadQueue, event.currentTarget);
