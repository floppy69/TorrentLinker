"use strict";
const fileAccessValues = new Map();
const fileAccessLoads = new Map();
let fileAccessEditor = null;
let fileAccessGeneration = 0;
const fileAccessText = (fr, en) => say(en, fr);
const fileAccessError = (message) =>
  TLFileAccess.error(message, fileAccessText) || message;
function clearFileAccess() {
  fileAccessGeneration++;
  fileAccessLoads.clear();
  fileAccessEditor?.destroy();
  fileAccessEditor = null;
  document.getElementById("file-access-editor")?.close();
  fileAccessValues.clear();
}
async function fileAccessRequest(owner, action, value = {}) {
  const generation = fileAccessGeneration;
  if (environment.client_id !== owner || snapshot?.client_id !== owner)
    throw Error(
      say(
        "The target client changed. Reopen Settings.",
        "Le client cible a changé. Rouvrez les paramètres.",
      ),
    );
  const result = await request("file-access", { action, value });
  if (environment.client_id !== owner || generation !== fileAccessGeneration)
    throw Error(
      say(
        "The target client changed. Reopen Settings.",
        "Le client cible a changé. Rouvrez les paramètres.",
      ),
    );
  return result;
}
function fileAccessCard(form) {
  const card = element("section", undefined, "settings-card file-access-card");
  card.id = "file-access-card";
  card.dataset.clientId = environment.client_id;
  form.append(card);
  drawFileAccess(card);
  if (!fileAccessValues.has(environment.client_id))
    loadFileAccess(environment.client_id);
}
async function loadFileAccess(owner, force = false) {
  if (fileAccessLoads.has(owner)) return fileAccessLoads.get(owner);
  if (!force && fileAccessValues.has(owner)) return;
  const generation = fileAccessGeneration;
  const pending = (async () => {
    try {
      fileAccessValues.set(owner, await fileAccessRequest(owner, "snapshot"));
    } catch (error) {
      if (
        environment.client_id === owner &&
        generation === fileAccessGeneration
      )
        fileAccessValues.set(owner, { error: error.message });
    } finally {
      if (generation !== fileAccessGeneration) return;
      fileAccessLoads.delete(owner);
      const card = $("file-access-card");
      if (card?.dataset.clientId === owner) drawFileAccess(card);
    }
  })();
  fileAccessLoads.set(owner, pending);
  return pending;
}
function drawFileAccess(card) {
  const owner = card.dataset.clientId,
    access = fileAccessValues.get(owner);
  card.replaceChildren(
    element("h3", say("Remote file access", "Accès aux fichiers distants")),
  );
  card.append(
    element(
      "p",
      say(
        "Optional SFTP access for this client. Transfers reuse the saved connection.",
        "Accès SFTP facultatif pour ce client. Les transferts réutilisent cette connexion.",
      ),
      "muted",
    ),
  );
  if (!access) {
    card.append(
      element(
        "p",
        say("Loading file access…", "Chargement de l’accès aux fichiers…"),
      ),
    );
    return;
  }
  if (access.error) {
    card.append(
      element("p", fileAccessError(access.error), "settings-error"),
      button(say("Retry", "Réessayer"), () => loadFileAccess(owner, true)),
    );
    return;
  }
  const status = !access.configured
    ? say("Not configured", "Non configuré")
    : access.checked
      ? say("Checked · SFTP", "Vérifié · SFTP")
      : say("Recheck required · SFTP", "À revérifier · SFTP");
  card.append(element("p", status, "file-access-status"));
  if (access.configured)
    card.append(
      element(
        "p",
        `${access.username}@${access.host}:${access.port} · ${access.client_root} → ${access.file_root}`,
        "file-access-address",
      ),
    );
  const actions = element("div", undefined, "settings-actions");
  const edit = button(
    say("Configure file access…", "Configurer l’accès aux fichiers…"),
    () => openFileAccess(owner),
  );
  edit.disabled = access.busy || !access.enabled;
  actions.append(edit);
  if (access.configured) {
    const check = button(say("Check access", "Tester l’accès"), async () => {
      const generation = fileAccessGeneration;
      check.disabled = true;
      try {
        const value = await fileAccessRequest(owner, "check");
        fileAccessValues.set(owner, { ...access, ...value });
      } catch (error) {
        if (
          environment.client_id !== owner ||
          generation !== fileAccessGeneration
        )
          return;
        fileAccessValues.set(owner, {
          ...access,
          checked: false,
          check_error: error.message,
        });
      }
      if (card.isConnected && environment.client_id === owner)
        drawFileAccess(card);
    });
    check.disabled = !access.enabled || access.busy;
    const remove = button(say("Remove access…", "Supprimer l’accès…"), () =>
      removeFileAccess(owner),
    );
    remove.disabled = access.busy;
    actions.append(check, remove);
  }
  card.append(actions);
  if (access.busy)
    card.append(
      element(
        "p",
        say(
          "Interrupt active transfers before changing file access.",
          "Interrompez les transferts actifs avant de modifier l’accès aux fichiers.",
        ),
        "file-access-note",
      ),
    );
  if (!access.enabled)
    card.append(
      element(
        "p",
        say(
          "Enable this Torrent Client before connecting to its files.",
          "Activez ce client torrent avant de vous connecter à ses fichiers.",
        ),
        "file-access-note",
      ),
    );
  if (access.check_error)
    card.append(
      element(
        "p",
        fileAccessError(access.check_error),
        "file-access-note settings-error",
      ),
    );
  card.append(
    element("h4", say("Available workflows", "Fonctions disponibles")),
  );
  const table = element("table", undefined, "file-access-capabilities");
  const available =
    access.enabled && access.checked
      ? say(
          "Available; operations recheck permissions and paths.",
          "Disponible ; les opérations revérifient leurs droits et chemins.",
        )
      : say(
          "Configure and check file access first.",
          "Configurez et testez d’abord l’accès aux fichiers.",
        );
  for (const [name, reason] of [
    [say("Transfers", "Transferts"), available],
    [
      say("Remote folder browsing", "Parcours des dossiers distants"),
      available,
    ],
    [
      say(
        "Library scan and Reseed",
        "Analyse de bibliothèque et remise en seed",
      ),
      say(
        "Needs locally accessible files. SFTP alone is not supported.",
        "Nécessite des fichiers accessibles localement. SFTP seul n’est pas pris en charge.",
      ),
    ],
    [
      say("Upload preparation", "Préparation des envois"),
      say(
        "Needs local files and preparation tools.",
        "Nécessite les fichiers et outils de préparation locaux.",
      ),
    ],
    [
      say("Media inspection and playback", "Inspection et lecture des médias"),
      say(
        "Needs media files accessible on this computer or the TorrentLinker server.",
        "Nécessite des médias accessibles sur cet ordinateur ou le serveur TorrentLinker.",
      ),
    ],
  ]) {
    const row = element("tr");
    row.append(element("th", name), element("td", reason));
    table.append(row);
  }
  card.append(
    table,
    element(
      "p",
      say(
        "Category-folder defaults and per-transfer destinations still apply. Editing access invalidates affected transfer previews; review them again before sending files.",
        "Les dossiers par catégorie et destinations propres à chaque transfert restent applicables. Une modification de l’accès invalide les aperçus concernés : vérifiez-les avant d’envoyer des fichiers.",
      ),
      "file-access-note",
    ),
  );
}
function openFileAccess(owner) {
  fileAccessEditor?.destroy();
  const dialog = element("dialog");
  dialog.id = "file-access-editor";
  document.body.append(dialog);
  dialog.showModal();
  const client = {
    id: owner,
    name: snapshot.clients.find((c) => c.id === owner)?.name || owner,
    access: fileAccessValues.get(owner),
  };
  const editor = TLFileAccess.open({
    dialog,
    client,
    mode: environment.mode,
    t: fileAccessText,
    formatBytes: (value) =>
      new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(
        value / 1024 ** 3,
      ) + " GiB",
    errorText: fileAccessError,
    returnLabel: () => say("Back to Settings", "Revenir aux paramètres"),
    isCurrent: () =>
      dialog.open &&
      environment.client_id === owner &&
      section === "connections" &&
      environment.active,
    send: (action, value) => fileAccessRequest(owner, action, value),
    onSaved: (value) => {
      fileAccessValues.set(owner, {
        ...fileAccessValues.get(owner),
        ...value,
        check_error: "",
      });
      const card = $("file-access-card");
      if (card?.dataset.clientId === owner) drawFileAccess(card);
    },
    onClose: () => {
      dialog.close();
    },
  });
  fileAccessEditor = editor;
  dialog.addEventListener(
    "close",
    () => {
      editor.destroy();
      dialog.remove();
      if (fileAccessEditor === editor) fileAccessEditor = null;
      if (environment.active && environment.client_id === owner)
        loadFileAccess(owner, true);
    },
    { once: true },
  );
}
function removeFileAccess(owner) {
  const dialog = element("dialog");
  dialog.className = "file-access-confirm";
  dialog.append(
    element(
      "h2",
      say("Remove file access?", "Supprimer l’accès aux fichiers ?"),
    ),
    element(
      "p",
      say(
        "The saved SFTP secret and server identity will be removed. Transfers must be checked again. Torrent API credentials and files are kept.",
        "Le secret SFTP et l’identité du serveur seront supprimés. Les transferts devront être revérifiés. Les identifiants de l’API torrent et les fichiers sont conservés.",
      ),
    ),
  );
  const actions = element("div", undefined, "settings-actions");
  actions.append(
    button(say("Cancel", "Annuler"), () => dialog.close()),
    button(say("Remove access", "Supprimer l’accès"), async () => {
      await fileAccessRequest(owner, "remove", { confirmed: true });
      dialog.close();
      await loadFileAccess(owner, true);
    }),
  );
  dialog.append(actions);
  document.body.append(dialog);
  dialog.showModal();
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
}
