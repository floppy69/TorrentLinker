"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  view: "torrents",
  setup: null,
  settingsSection: "connections",
  clientId: "",
  addingClient: false,
  offset: 0,
  sort: "name",
  descending: false,
  searchPage: 1,
  searchPages: 1,
  libraryOffset: 0,
  selected: new Set(),
  searchSelected: new Set(),
  queueSelected: new Set(),
  queueRows: [],
  planSelected: new Set(),
  jobs: new Map(),
  searchRows: [],
  planRows: [],
  localItem: "",
};
const french = {
  mediaFullscreen: "Plein écran", mediaExitFullscreen: "Quitter le plein écran",
  mediaCenterMode: "Mode Media Center", mediaCenterReturn: "Revenir à TorrentLinker",
  interfaceSettings: "Interface", mediaLayout: "Disposition des médias", mediaLayoutShort: "Disposition",
  mediaLayoutCinematic: "Accueil cinéma", mediaLayoutFocus: "Focus", mediaLayoutCollection: "Collection",
  mediaLayoutHelp: "Choisissez la présentation de la médiathèque dans ce navigateur. La lecture continue lorsque vous changez de disposition.",
  mediaHome: "Accueil", mediaFilms: "Films", mediaSeries: "Séries", mediaContinue: "Reprendre la lecture",
  mediaLibraryOptions: "Options de bibliothèque", mediaYourLibrary: "Votre médiathèque", mediaYourCollection: "Votre collection",
  mediaExpandPlayer: "Agrandir le lecteur", mediaAddFolder: "Ajouter un dossier de bibliothèque",
  mediaRefreshPreview: "Actualiser l’aperçu",
  mediaStop: "Arrêter",
  mediaVideo: 'Vidéo',
  mediaMusic: 'Musique',
  mediaRefresh: 'Actualiser les médias',
  mediaCancelScan: 'Annuler l’analyse',
  mediaMore: 'Afficher la suite',
  mediaChat: 'Discuter de ce média',
  mediaCloseChat: 'Fermer la discussion',
  turnOffPartialNames: 'Le désactiver dans Transmission et réessayer',
  checkAllCandidates: 'Vérifier tous les Candidats',
  reseedAllMatches: 'Remettre en seed toutes les correspondances complètes',
  mediaPrevious: 'Précédent',
  mediaNext: 'Suivant',
  mediaShuffle: 'Aléatoire',
  mediaExternal: 'Ouvrir / télécharger pour un lecteur externe',

  agentMedia: "Lecture des médias et playlists",
  allStates: "Tous les états", seedingState: "En partage", downloadingState: "Téléchargement",
  pausedState: "En pause", checkingState: "Vérification", errorState: "Erreur",
  uploadHelp: "Choisissez un élément local dans la Bibliothèque pour préparer un Upload.",
  categoryLabel: "Catégorie", subcategoryLabel: "Sous-catégorie", imageUrl: "URL de l’image",
  releaseName: "Nom de la release", updatePreview: "Actualiser l’aperçu",
  reviewUpload: "J’ai relu les fichiers, la description et les avertissements de catégorie.",
  closeNavigation: "Fermer la navigation",
  navigation: "Navigation", catalogueTab: "Catalogue", planCategory: "Catégorie / sous-catégorie",
  allCategories: "Toutes les catégories", optimizeFor: "Optimiser pour", maxSeeders: "Sources maximum",
  minTorrentGiB: "Taille minimum par torrent, Gio", maxTorrentGiB: "Taille maximum par torrent, Gio",
  refreshProfile: "Actualiser le profil",
  planZeroHelp: "Un budget ou une taille maximum de 0 ne fixe aucune limite supplémentaire. L’espace disponible reste pris en compte dans le plan.",
  seedingTab: "En partage", planTab: "Plan", expandAll: "Tout développer", collapseAll: "Tout réduire",
  seedingSort: "Trier les torrents par", torrentName: "Torrent", torrentSize: "Taille",
  seedAge: "Âge du seed (jours)", seedingOrder: "Ordre", descending: "Décroissant", ascending: "Croissant",
  classComparison: "Comparaison des classes",
  zenPerDay: "≈ Zen/jour",
  agentAccess: "Accès agent (MCP)", enableAgents: "Activer l’accès agent",
  agentHelp: "Les nouvelles connexions proposent uniquement des changements. Approuvez-les ci-dessous ou autorisez certaines actions dans les limites quotidiennes. Le retrait et la suppression de fichiers nécessitent toujours votre accord.",
  agentEndpoint: "Adresse MCP", agentClients: "Clients autorisés", agentMode: "Mode",
  agentPropose: "Propositions uniquement", agentExecute: "Exécuter les actions autorisées",
  agentPermissions: "Actions automatiques", agentControls: "Pause, vérification et reprise des torrents complets",
  agentUploads: "Brouillons d’upload et mise en seed", agentDailyGiB: "Budget quotidien (Gio)",
  agentDailyCount: "Torrents par jour", agentReserve: "Espace à conserver, Gio (0 = désactivé)",
  agentCreate: "Créer la connexion", agentConnections: "Connexions", agentProposals: "Propositions et tâches",
  agentGoals: "Objectifs enregistrés", agentHide: "Masquer le jeton",
  agentTokenHelp: "Copiez ce jeton maintenant. Il ne sera affiché qu’une fois. Utilisez-le comme jeton Bearer ou TL_MCP_TOKEN pour le pont stdio. Gardez-le privé.",
  targetClient: "Client cible", addClient: "Ajouter un client", defaultClient: "Définir par défaut",
  removeClient: "Retirer ce client", clientName: "Nom du client", planDestinations: "Destinations du Plan",
  planDestinationHelp: "Choisissez un client ou répartissez entre plusieurs clients. Budget 0 : espace disponible.",
  welcome: "Vos torrents, où qu’ils soient.",
  webPassword: "Mot de passe de l’interface web",
  signIn: "Se connecter",
  passwordHelp: "Utilisez le mot de passe choisi au démarrage du serveur.",
  torrents: "Torrents",
  search: "Recherche",
  queue: "File de téléchargement",
  library: "Bibliothèque",
  activity: "Activité",
  settings: "Paramètres",
  theme: "Thème",
  system: "Système",
  light: "Clair",
  dark: "Sombre",
  signOut: "Déconnexion",
  setupIntro:
    "Connectez votre client, vérifiez ses dossiers, puis ajoutez c411. Chaque connexion reste modifiable.",
  stepClient: "1 · Client torrent",
  stepStorage: "2 · Dossiers",
  stepIndexer: "3 · c411",
  stepReady: "4 · Prêt",
  connectClient: "Connecter votre client torrent",
  addressHelp:
    "Indiquez une adresse accessible depuis ce serveur. Pour une seedbox, utilisez l’adresse de son interface web.",
  client: "Client torrent",
  address: "Adresse du serveur",
  username: "Identifiant",
  password: "Mot de passe",
  advanced: "Paramètres avancés",
  dockerAddress:
    "Dans Docker, localhost désigne ce conteneur. Utilisez le nom du service client sur un réseau partagé, ou l’adresse HTTPS de votre seedbox.",
  test: "Tester la connexion",
  saveContinue: "Enregistrer et continuer",
  checkFolders: "Retrouver vos fichiers",
  storageIntro:
    "La gestion des torrents fonctionne sans accès aux fichiers. L’analyse, le reseed, la préparation des uploads et les téléchargements sûrs nécessitent un stockage accessible depuis ce serveur.",
  serverFolder: "Dossier visible par TorrentLinker",
  clientFolder: "Même dossier dans le client torrent",
  browse: "Parcourir",
  purpose: "Utiliser ce dossier pour",
  downloads: "Téléchargements",
  kind: "Type de contenu",
  depth: "Regroupement des éléments",
  checkMapping: "Vérifier la correspondance",
  addFolder: "Ajouter un dossier",
  continue: "Continuer",
  skipStorage: "Continuer sans accès aux fichiers",
  connectIndexer: "Connecter c411",
  keyHelp:
    "Votre clé API reste sur ce serveur. Vous pouvez gérer votre client sans configurer c411.",
  skip: "Configurer plus tard",
  ready: "Votre espace est prêt",
  revisit:
    "Revenez dans les paramètres pour ajouter des dossiers ou modifier une connexion. Les tâches continuent après la fermeture du navigateur.",
  openTorrents: "Ouvrir les torrents",
  refresh: "Actualiser",
  start: "Démarrer",
  pause: "Mettre en pause",
  recheck: "Revérifier",
  remove: "Retirer le torrent",
  deleteFiles: "Supprimer le torrent et les fichiers",
  dailyZen: "Estimation Zen / jour",
  seeding: "Torrents en seed",
  planner: "Planificateur",
  planHelp:
    "Créez une proposition à partir du catalogue et du stockage vérifié. Les estimations Zen et les notes issues du cache sont provisoires. Relisez le plan avant l’ajout à la file.",
  cachedPlan: "Utiliser le catalogue en cache sans actualiser",
  maxTorrents: "Nombre maximal de torrents",
  maxGiB: "Budget de téléchargement, Gio",
  updateCatalogue: "Actualiser le catalogue",
  buildPlan: "Créer un plan",
  queueSelected: "Ajouter la sélection à la file",
  moreFilters: "Plus de filtres",
  queueHelp:
    "Démarrer envoie les torrents au client. Mettre la tâche en pause arrête les prochains envois ; les téléchargements déjà lancés continuent.",
  startQueue: "Démarrer la file",
  removeSelected: "Retirer la sélection",
  scan: "Analyser les dossiers",
  jobsHelp:
    "Les tâches appartiennent au serveur. Vous pouvez fermer le navigateur et revenir plus tard. Aucune action interrompue n’est relancée automatiquement.",
};
let language =
  localStorage.getItem("tl-language") ||
  (navigator.language.startsWith("fr") ? "fr" : "en");
const english = new Map();
function translate() {
  document.documentElement.lang = language;
  $("language").value = language;
  document.querySelectorAll("[data-en][data-fr]").forEach(el => {
    el.textContent = language === "fr" ? el.dataset.fr : el.dataset.en;
  });
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    if (!english.has(el)) english.set(el, el.textContent);
    el.textContent =
      language === "fr"
        ? french[el.dataset.i18n] || english.get(el)
        : english.get(el);
  });
}
const say = (en, fr) => (language === "fr" ? fr : en);
function element(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function button(text, callback, cls) {
  const e = element("button", text, cls);
  e.type = "button";
  e.onclick = () => guard(callback);
  return e;
}
function toast(text) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("toast").hidden = true), 7000);
}
async function guard(fn) {
  try {
    await fn();
  } catch (error) {
    toast(error.message);
  }
}
async function api(path, body, method) {
  const scoped = ["reseed-workspace", "setup", "torrents", "library", "queue", "upload/queue", "upload/drafts"];
  if (body === undefined && scoped.includes(path.split("?")[0]) && state.clientId && !new URLSearchParams(path.split("?")[1]).has("client_id")) {
    const id = state.clientId === "all" && path === "setup" ? state.setup?.default_client_id || "" : state.clientId;
    path += (path.includes("?") ? "&" : "?") + "client_id=" + encodeURIComponent(id);
  }
  if (body !== undefined && (path === "jobs" || path === "confirm" || (path.startsWith("setup/") && !path.startsWith("setup/assistant")))) {
    body = {client_id: state.clientId === "all" ? state.setup?.default_client_id : state.clientId, ...body};
    if (path === "jobs" && body.kind === "refresh") body.client_id = state.clientId;
  }
  const response = await fetch(`api/${path}`, {
    method: method || (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-TorrentLinker": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      clearAgentToken();
      $("workspace").hidden = true;
      $("login-screen").hidden = false;
    }
    // An `action` tells the page what it may offer, such as fixing a client option.
    throw Object.assign(Error(result.detail || "Request failed"), {action: result.action});
  }
  return result;
}
const bytes = (n) => {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let i = 0;
  while (n >= 1024 && i < 5) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
};
const num = (n) => (n === null || n === undefined ? "—" : Number(n).toFixed(2));
function age(timestamp) {
  if (!timestamp) return "—";
  const seconds = Math.max(0, Date.now() / 1000 - timestamp);
  const [value, unit] =
    seconds < 3600
      ? [Math.floor(seconds / 60), say("minutes", "minutes")]
      : seconds < 86400
        ? [Math.floor(seconds / 3600), say("hours", "heures")]
        : [Math.floor(seconds / 86400), say("days", "jours")];
  return `${value} ${unit}`;
}
function table(target, rows, columns, selection, key = "hash", onChange, onRow) {
  const host = $(target);
  host.replaceChildren();
  if (!rows.length) {
    host.append(
      element(
        "p",
        say("Nothing to display yet.", "Aucun élément à afficher."),
        "empty",
      ),
    );
    return;
  }
  const t = element("table"),
    head = element("tr");
  if (selection) {
    const cell = element("th"),
      input = document.createElement("input");
    input.type = "checkbox";
    input.setAttribute(
      "aria-label",
      say("Select page", "Sélectionner la page"),
    );
    input.checked = rows.every((r) => selection.has(r[key]));
    input.onchange = () => {
      rows.forEach((r) =>
        input.checked ? selection.add(r[key]) : selection.delete(r[key]),
      );
      table(target, rows, columns, selection, key, onChange);
      if (onChange) onChange();
    };
    cell.append(input);
    head.append(cell);
  }
  for (const column of columns) {
    const cell = element("th");
    if (column.title) cell.title = column.title;
    if (column.sort)
      cell.append(
        button(column.label, () => {
          state.sort = column.sort;
          state.descending = !state.descending;
          return loadTorrents();
        }),
      );
    else cell.textContent = column.label;
    head.append(cell);
  }
  const thead = element("thead");
  thead.append(head);
  t.append(thead);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr");
    tr.dataset.key = row[key];
    if (onRow) {
      tr.onclick = (e) => {
        if (!e.target.closest("button, input, a")) onRow(row);
      };
      if (row[key] === state.current) tr.className = "current";
    }
    if (selection) {
      const cell = element("td"),
        input = document.createElement("input");
      input.type = "checkbox";
      input.checked = selection.has(row[key]);
      input.setAttribute("aria-label", row.name || row.title || row[key]);
      input.onchange = () => {
        input.checked ? selection.add(row[key]) : selection.delete(row[key]);
        if (onChange) onChange();
      };
      cell.append(input);
      tr.append(cell);
    }
    for (const column of columns) {
      const cell = element("td", undefined, column.name ? "name" : "");
      const value = column.render(row);
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? "—";
      if (column.name) cell.title = row.name || row.title;
      tr.append(cell);
    }
    body.append(tr);
  }
  t.append(body);
  host.append(t);
}
function step(name) {
  document
    .querySelectorAll(".setup-step")
    .forEach((el) => (el.hidden = el.id !== `step-${name}`));
  document
    .querySelectorAll(".steps button")
    .forEach((b) => b.classList.toggle("active", b.dataset.step === name));
  if (name === "ready") renderCapabilities();
}
async function refreshSetup() {
  state.setup = await api("setup");
  // The form below represents this saved profile, even after leaving Add client.
  state.addingClient = false;
  $("client-password").value = "";
  $("client-key").value = "";
  // XXX choices and the Media XXX panel only once adult content is enabled.
  for (const node of document.querySelectorAll("[data-adult]")) node.hidden = !state.setup.adult_content;
  if (!state.clientId) state.clientId = state.setup.client_id;
  const selector = $("target-client");
  selector.replaceChildren(new Option(say("All clients · overview", "Tous les clients · aperçu"), "all"),
    ...state.setup.clients.map(p => new Option(p.name, p.id)));
  selector.value = state.clientId;
  const oldCategories = new Set([...$("plan-category").selectedOptions].map(o => o.value));
  $("plan-category").replaceChildren(new Option(say("All categories", "Toutes les catégories"), ""));
  const categories = Object.entries(state.setup.indexer_categories || {});
  const appendCategory = (id, category, depth = 0, visited = new Set()) => {
    if (visited.has(id)) return;
    visited.add(id);
    const missing = !state.setup.download_folders?.effective?.[id];
    $("plan-category").append(new Option("　".repeat(depth) + category.name + (missing ? say(" · no folder", " · sans dossier") : ""), id));
    for (const [child, value] of categories.filter(([, v]) => String(v.parent) === id)) appendCategory(child, value, depth + 1, visited);
  };
  for (const [id, category] of categories.filter(([, c]) => !c.parent || !categories.some(([key]) => key === String(c.parent)))) appendCategory(id, category);
  for (const option of $("plan-category").options) option.selected = oldCategories.has(option.value);
  $("client-name").value = state.setup.name;
  $("reseed-folder-settings").hidden = false;
  $("reseed-root").value = state.setup.reseed_link_root || localStorage.getItem(`reseed-root:${state.setup.client_id}`) || "";
  const oldDestinations = $("plan-clients").dataset.owner === state.setup.client_id ? new Map(
    [...$("plan-clients").querySelectorAll("input[data-client-id]")].map(e => [e.dataset.clientId, {
      checked:e.checked, budget:$("plan-clients").querySelector(`input[data-budget-id="${CSS.escape(e.dataset.clientId)}"]`).value,
    }])) : new Map();
  $("plan-clients").dataset.owner = state.setup.client_id;
  $("plan-clients").replaceChildren(...state.setup.clients.filter(p => p.enabled).map(p => {
    const row = element("label");
    const check = document.createElement("input"); check.type = "checkbox";
    check.dataset.clientId = p.id; check.checked = oldDestinations.get(p.id)?.checked ?? (p.id === state.setup.client_id);
    const budget = document.createElement("input"); budget.type = "number"; budget.min = "0"; budget.step = "any"; budget.value = oldDestinations.get(p.id)?.budget ?? "0";
    budget.dataset.budgetId = p.id; budget.setAttribute("aria-label", p.name + " · GiB");
    row.append(check, element("span", p.name + " · GiB"), budget); return row;
  }));
  $("client-kind").value = state.setup.client;
  $("client-host").value = state.setup.host;
  $("client-username").value = state.setup.username;
  $("indexer-url").value = state.setup.indexer_url;
  $("indexer-key-count").textContent = `${state.setup.indexer_key_count || 0} ${say("API key(s) saved · up to 5 per account", "clé(s) API enregistrée(s) · jusqu’à 5 par compte")}`;
  $("connection-status").textContent = state.setup.configured
    ? `${state.setup.name} · ${state.setup.client.toUpperCase()} · ${new URL(state.setup.host).host}`
    : "TORRENTLINKER WEB";
  $("saved-folders").replaceChildren(
    ...state.setup.folders.map((f) =>
      savedFolder(f.local, "library", `${f.local} · ${f.kind} · ${f.depth ?? say("Automatic", "Automatique")}`),
    ),
  );
  if (state.setup.download_folder)
    $("saved-folders").append(
      savedFolder(
        state.setup.download_folder,
        "download",
        `${say("Downloads", "Téléchargements")} · ${state.setup.download_folder}`,
      ),
    );
  $("proxy-address").value = state.setup.proxy.address;
  $("proxy-username").value = state.setup.proxy.username;
  $("proxy-client").checked = state.setup.proxy.torrent_client;
  clientKind();
  renderCapabilities();
  if (typeof renderLibraryDownloads === "function") renderLibraryDownloads();
}
function savedFolder(local, purpose, label) {
  const row = element("div", undefined, "toolbar");
  row.append(
    element("span", label),
    button(say("Remove folder", "Retirer ce dossier"), async () => {
      await api("setup/remove-folder", { local, purpose });
      await refreshSetup();
    }),
  );
  return row;
}
function renderCapabilities() {
  if (!state.setup) return;
  const features = [
    [
      say("Torrent management", "Gestion des torrents"),
      state.setup.capabilities.manage,
    ],
    [
      say("Search and Zen profile", "Recherche et profil Zen"),
      state.setup.indexer_configured,
    ],
    [
      say("Library scanning and reseeding", "Analyse et reseed"),
      state.setup.capabilities.scan,
    ],
    [
      say("Downloads and planning", "Téléchargements et planification"),
      state.setup.capabilities.download,
    ],
  ];
  $("capabilities").replaceChildren(
    ...features.map(([label, ready]) => {
      const row = element("div", undefined, "capability");
      row.append(
        element("span", ready ? "✓" : "○"),
        element("span", label),
        element(
          "small",
          ready
            ? say("Ready", "Prêt")
            : say("Needs configuration", "À configurer"),
        ),
      );
      return row;
    }),
  );
}
function renderSecretHints() {
  const setup = state.setup || {};
  const editingSavedClient = !state.addingClient && $("client-kind").value === setup.client;
  const fields = [
    ["client-password", editingSavedClient && setup.has_password],
    ["client-key", editingSavedClient && setup.has_api_key],
    ["proxy-password", setup.has_proxy_password],
    ["announce-url", setup.has_announce_url],
  ];
  for (const [id, saved] of fields) {
    $(id).placeholder = saved
      ? say("Saved · leave blank to keep", "Enregistré · laisser vide pour conserver")
      : say("Not saved", "Non enregistré");
  }
}
function clientKind() {
  renderSecretHints();
  $("username-label").hidden = $("client-kind").value === "deluge";
  $("client-key").parentElement.hidden =
    $("client-kind").value !== "qbittorrent";
}
function connection() {
  return {
    ...(state.addingClient ? {password: $("client-password").value, api_key: $("client-key").value} : {}),
    name: $("client-name").value.trim(),
    client: $("client-kind").value,
    host: $("client-host").value,
    username: $("client-username").value,
    ...($("client-password").value
      ? { password: $("client-password").value }
      : {}),
    ...($("client-key").value ? { api_key: $("client-key").value } : {}),
  };
}
function folder() {
  return {
    local: $("folder-local").value,
    client_path: $("folder-client").value,
    purpose: $("folder-purpose").value,
    kind: $("folder-kind").value,
    depth: $("folder-depth").value === "auto" ? null : Number($("folder-depth").value),
  };
}
function indexer() {
  return {
    url: $("indexer-url").value,
    ...($("indexer-key").value ? { api_key: $("indexer-key").value } : {}),
    ...($("indexer-replace-keys").checked ? {extra_keys: [1,2,3,4].map(i => $(`indexer-extra-${i}`).value).filter(Boolean)} : {}),
  };
}
function showFolders(rows) {
  $("import-folders").replaceChildren(
    ...rows
      .filter((f) => f.path)
      .map((f) =>
        button(
          `${f.name || say("Default folder", "Dossier par défaut")} · ${f.path}`,
          () => {
            $("folder-client").value = f.path;
            if (state.setup.storage_roots.includes(f.path))
              $("folder-local").value = f.path;
          },
        ),
      ),
  );
}
async function testClient(save = false, turnOffPartialNames = false) {
  $("client-result").textContent = say("Connecting…", "Connexion…");
  $("client-partial-names").hidden = true;
  try {
    const result = await api(
      save && state.addingClient ? "clients" : `setup/${save ? "client" : "test-client"}`,
      {...connection(), turn_off_partial_names: turnOffPartialNames},
    );
    $("client-result").textContent = `✓ ${result.version}\n${result.warning}`;
    showFolders(result.folders);
    if (save) {
      if (result.client_id) state.clientId = result.client_id;
      state.addingClient = false;
      $("client-password").value = "";
      $("client-key").value = "";
      await refreshSetup();
      step("storage");
    }
  } catch (e) {
    $("client-result").textContent = e.message;
    if (e.action === "turn_off_partial_names") {
      // Transmission is reachable; it would rename files to .part. Offer the desktop's fix.
      const fix = $("client-partial-names");
      fix.hidden = false;
      fix.onclick = () => guard(() => testClient(save, true));
      return;
    }
    throw e;
  }
}
async function testFolder(save = false) {
  $("folder-result").textContent = say("Checking access with the Torrent Client…", "Vérification de l’accès avec le client torrent…");
  const r = await api(`setup/${save ? "folder" : "test-folder"}`, folder());
  $("folder-result").textContent = r.sample
    ? `${r.sample.local}\n→ ${r.sample.client}\n✓ ${say("Matching file and size", "Même fichier, même taille")}`
    : r.verification === "temporary-file"
      ? say("✓ Temporary file verified by the Torrent Client. Test file and torrent removed.", "✓ Fichier temporaire vérifié par le client torrent. Fichier et torrent de test supprimés.")
      : r.warning;
  if (save) await refreshSetup();
}
async function testIndexer(save = false) {
  $("indexer-result").textContent = say(
    "Checking key…",
    "Vérification de la clé…",
  );
  const r = await api(`setup/${save ? "indexer" : "test-indexer"}`, indexer());
  $("indexer-result").textContent =
    `✓ ${r.categories} ${say("categories", "catégories")}`;
  if (save) {
    $("indexer-key").value = "";
    for (const i of [1,2,3,4]) $(`indexer-extra-${i}`).value = "";
    $("indexer-replace-keys").checked = false;
    await refreshSetup();
    step("ready");
  }
}
async function browse(path = "") {
  const r = await api(`folders?${new URLSearchParams({ path })}`),
    content = $("dialog-content");
  content.replaceChildren(
    element("h2", say("Folders on this server", "Dossiers de ce serveur")),
    element(
      "p",
      r.path || say("Configured storage roots", "Stockages configurés"),
    ),
  );
  if (r.path)
    content.append(
      button(
        say("Use this folder", "Utiliser ce dossier"),
        () => {
          $("folder-local").value = r.path;
          $("dialog").close();
        },
        "primary",
      ),
    );
  if (r.path) content.append(button("↑", () => browse(r.parent)));
  for (const path of r.folders)
    content.append(button(path, () => browse(path), "directory-button"));
  if (!r.folders.length && !r.path)
    content.append(
      element(
        "p",
        say(
          "No storage roots configured. Mount your media and set TL_STORAGE_ROOTS on the server. Remote torrent management is still available.",
          "Aucun stockage configuré. Montez vos médias et définissez TL_STORAGE_ROOTS sur le serveur. La gestion distante des torrents reste disponible.",
        ),
      ),
    );
  if (!$("dialog").open) $("dialog").showModal();
}
let agentTokenGeneration = 0;
function clearAgentToken() {
  agentTokenGeneration += 1;
  $("agent-token").value = "";
  $("agent-token-box").hidden = true;
}
async function settingsSection(section, detail) {
  rememberTab("setup", section, detail);
  state.settingsSection = section;
  document.querySelectorAll("[data-settings-panel]").forEach(el => {
    el.hidden = el.dataset.settingsPanel !== section;
  });
  document.querySelectorAll("[data-settings-section]").forEach(el => {
    if (el.dataset.settingsSection === section) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  if (section !== "agents") clearAgentToken();
  if (section === "agents") {
    agentTab(detail || "connections");
    await loadAgents();
  }
  if (section === "assistant") await loadAssistantConnections();
  if (section === "companion") await loadZenProfile();
}
document.querySelectorAll("[data-settings-section]").forEach(el => {
  el.onclick = () => guard(() => settingsSection(el.dataset.settingsSection));
});
function agentTab(name) {
  rememberTab("setup", "agents", name === "connections" ? undefined : name);
  document.querySelectorAll("[data-agent-panel]").forEach(panel => {
    panel.hidden = panel.dataset.agentPanel !== name;
  });
  document.querySelectorAll("[data-agent-tab]").forEach(tab => {
    if (tab.dataset.agentTab === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  if (name !== "new") clearAgentToken();
}
document.querySelectorAll("[data-agent-tab]").forEach(el => {
  el.onclick = () => agentTab(el.dataset.agentTab);
});

// Only workspace locations belong in the fragment. Form state and filters stay local.
const viewTabs = {
  torrents: [], zen: ["profile", "seeding", "plan", "catalogue", "community"], search: [],
  feeds: [], queue: [], media: ["video", "music"], library: ["reseed", "items", "folders", "activity"],
  upload: ["local", "remote", "sources"], assistant: [], jobs: [], documentation: [],
  setup: ["connections", "interface", "companion", "assistant", "agents"],
};
const agentTabs = ["connections", "new", "activity"];
const mediaViewsByKind = {
  video: ["recent", "continue", "films", "series", "anime", "rated", "unwatched", "all", "adult"],
  music: ["albums", "artists", "tracks"],
};
const rememberedTabs = {};
let activeRoute = "";
function resolveRoute(fragment) {
  const fallback = state.setup?.configured ? ["torrents"] : ["setup", "connections"];
  const parts = fragment.replace(/^#\//, "").split("/");
  const [view, tab, detail] = parts;
  // Incomplete setup selects the landing page; it does not block explicit routes
  // such as configuring the Assistant or reviewing saved Upload drafts.
  if (!fragment.startsWith("#/") || !Object.hasOwn(viewTabs, view)) return fallback;
  const tabs = viewTabs[view];
  const validDetail = view === "setup" && tab === "agents" && agentTabs.includes(detail) ||
    view === "media" && mediaViewsByKind[tab]?.includes(detail) &&
      (detail !== "adult" || state.setup?.adult_content);
  if (parts.length > 3 || (tab !== undefined && !tabs.includes(tab)) ||
      (detail !== undefined && !validDetail)) return fallback;
  const defaultDetail = view === "media" ? mediaViewsByKind[tab || tabs[0]][0] : "connections";
  return tabs.length ? [view, tab || tabs[0], ...(detail && detail !== defaultDetail ? [detail] : [])] : [view];
}
function routeFragment(parts) { return "#/" + parts.join("/"); }
function writeRoute(parts, replace = false) {
  activeRoute = routeFragment(parts);
  if (location.hash === activeRoute) return;
  if (replace) history.replaceState(null, "", activeRoute);
  else location.hash = activeRoute;
}
function rememberTab(view, tab, detail) {
  if (state.view !== view || $("workspace").hidden) return;
  const parts = [view, tab, ...(detail ? [detail] : [])];
  rememberedTabs[view] = parts.slice(1);
  writeRoute(parts);
}
async function openFragment() {
  if ($("workspace").hidden) return;
  const parts = resolveRoute(location.hash);
  const fragment = routeFragment(parts);
  if (location.hash !== fragment) history.replaceState(null, "", fragment);
  if (activeRoute !== fragment) await navigate(...parts);
}
window.addEventListener("hashchange", () => guard(openFragment));
async function navigate(view, section, detail) {
  if (view === "agents") { view = "setup"; section = "agents"; }
  const requested = [view, ...(section ? [section, ...(detail ? [detail] : [])] : rememberedTabs[view] || [])];
  const parts = resolveRoute(routeFragment(requested));
  [view, section, detail] = parts;
  rememberedTabs[view] = parts.slice(1);
  const route = routeFragment(parts);
  writeRoute(parts);
  if (view !== "media" && document.body.classList.contains("media-center-mode")) await mediaExitCenter();
  if (activeRoute !== route) return;
  if (typeof mediaCloseChat === "function" && media.chat) mediaCloseChat();
  state.view = view;
  document.body.classList.toggle("media-view", view === "media");
  document.body.classList.toggle("chat-view", view === "assistant");
  document
    .querySelectorAll(".view")
    .forEach((el) => (el.hidden = el.id !== `view-${view}`));
  document
    .querySelectorAll("[data-view]")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("page-title").textContent =
    document.querySelector(`[data-view="${view}"]`)?.textContent || view;
  if (view === "setup") {
    await refreshSetup();
    if (activeRoute !== route) return;
    step("client");
    await settingsSection(section, detail);
  }
  if (view === "assistant") await loadAssistant();
  if (view === "media") {
    media.kind = section;
    media.view = detail || mediaViewsByKind[section][0];
    mediaViews();
    await loadMedia(); guard(mediaAutoScan);
  }
  if (view !== "setup") clearAgentToken();
  if (view === "documentation") await loadGuides();
  if (view === "torrents") await loadTorrents();
  if (view === "queue") await loadQueue();
  if (view === "feeds") await loadFeeds();
  if (view === "upload") {
    showUploadView(section);
    if (section === "remote") await loadRemoteUploads();
    else if (section === "sources") await loadUploadSources();
    else await loadUploadQueue();
  }
  if (view === "library") await libraryTab(section);
  if (view === "jobs") await loadJobs();
  if (view === "zen") {
    zenTab(section);
    await refreshSetup();
    await Promise.all([loadZenProfile(true), loadZenSeeding(), api("zen/catalogue").then(showCatalogue), loadZenPlan()]);
  }
  if (view === "search" && state.setup.indexer_configured) await loadSearchPage();
}
async function job(body, done, failed, progress) {
  body = {client_id: state.clientId, ...body};
  if (body.client_id === "all" && body.kind !== "refresh")
    throw Error(say("Choose a target client first.", "Choisissez un client cible."));
  const r = await api("jobs", body);
  state.jobs.set(r.id, { body, done, failed, progress });
  workStatus("Working…", "En cours…");
  await pollJobs();
  return r.id;
}
function workStatus(en, fr) {
  const status = $("work-status");
  status.dataset.en = en;
  status.dataset.fr = fr;
  status.textContent = say(en, fr);
}
async function pollJobs() {
  if ($("workspace").hidden) return;
  const rows = await api("jobs");
  let running = 0;
  for (const row of rows) {
    if (["running", "queued"].includes(row.status)) running++;
    const pending = state.jobs.get(row.id);
    if (pending?.progress && pending.body.client_id === state.clientId && row.progress) pending.progress(row.progress);
    if (pending && !["running", "queued"].includes(row.status)) {
      state.jobs.delete(row.id);
      const full = await api(`jobs/${row.id}`);
      if (["completed", "partial"].includes(full.status)) {
        if (pending.done && (pending.body.client_id === state.clientId || ["enqueue", "configure-download-folder", "catalogue"].includes(pending.body.kind))) await pending.done(full.result);
        if (full.status === "partial") toast(say("Scan incomplete. Some paths could not be read; previous items were kept. See job details.", "Analyse incomplète. Certains chemins sont inaccessibles ; les éléments précédents ont été conservés. Consultez les détails de la tâche."));
      } else {
        if (pending.body.kind === "refresh" && pending.body.client_id === state.clientId && state.view === "zen") await loadZenSeeding();
        if (pending.failed && (pending.body.client_id === state.clientId || ["configure-download-folder", "catalogue"].includes(pending.body.kind))) await pending.failed(full.error);
        toast(full.error || say("Job cancelled", "Tâche annulée"));
      }
    }
  }
  if (running) workStatus(`${running} active job(s)`, `${running} tâche(s) active(s)`);
  else if (rows.find(row => row.kind === "scan" && row.client_id === state.clientId)?.status === "partial")
    workStatus("Scan incomplete · see jobs", "Analyse incomplète · voir les tâches");
  else workStatus("Up to date", "À jour");
  if (state.view === "jobs") renderJobs(rows);
  if (state.view === "queue") await loadQueue();
  if (state.view === "library" && !$("library-reseed").hidden && reseedUI.job) await loadReseed();
}
async function loadJobs() {
  renderJobs(await api("jobs"));
}
function renderJobs(rows) {
  const clientName = id => state.setup?.clients?.find(p => p.id === id)?.name || id;
  $("job-list").replaceChildren(
    ...rows.map((r) => {
      const card = element("div", undefined, "card job"),
        text = element("div");
      text.append(
        element("strong", `${r.kind} · ${clientName(r.client_id)}`),
        element("p", r.status),
        element("small", r.error || (r.progress?.stage === "client-files"
          ? say(`Reading client files: ${r.progress.done}/${r.progress.total} · up to ${Number(r.progress.requests_per_second).toFixed(2)} requests/s`,
              `Lecture des fichiers du client : ${r.progress.done}/${r.progress.total} · jusqu’à ${Number(r.progress.requests_per_second).toFixed(2)} requêtes/s`)
          : JSON.stringify(r.progress || {}))),
      );
      card.append(text);
      if (["queued", "running"].includes(r.status) && r.progress?.cancellable !== false)
        card.append(
          button(say("Stop", "Arrêter"), () => api(`jobs/${r.id}/cancel`, {})),
        );
      else
        card.append(
          button(say("Details", "Détails"), async () => {
            const full = await api(`jobs/${r.id}`);
            $("dialog-content").replaceChildren(
              element("h2", r.kind),
              element(
                "pre",
                JSON.stringify(full.result || full.error, null, 2),
              ),
            );
            $("dialog").showModal();
          }),
        );
      return card;
    }),
  );
}
function options(select, values, label) {
  const old = select.value;
  select.replaceChildren(
    new Option(label, ""),
    ...values.map((v) => new Option(v, v)),
  );
  select.value = old;
}
function duration(seconds) {
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}
const statusLabel = (s) =>
  ({
    downloading: say("Downloading", "Téléchargement"),
    seeding: say("Seeding", "En partage"),
    paused: say("Paused", "En pause"),
    checking: say("Checking", "Vérification"),
    error: say("Error", "Erreur"),
    other: say("Other", "Autre"),
  })[s] || s;
function labelTorrentBar() {
  const titles = {
    start: say("Start", "Démarrer"),
    pause: say("Pause", "Mettre en pause"),
    recheck: say("Recheck", "Revérifier"),
    remove: say("Remove torrent", "Retirer le torrent"),
    deleteFiles: say("Delete torrent and files", "Supprimer le torrent et les fichiers"),
    refresh: say("Refresh", "Actualiser"),
  };
  document.querySelectorAll(".torrent-bar [data-title]").forEach((b) => {
    b.title = titles[b.dataset.title];
    b.setAttribute("aria-label", titles[b.dataset.title]);
  });
}
const STATUSES = ["downloading", "seeding", "paused", "checking", "error", "other"];
function sidebar(counts) {
  const side = $("torrent-side");
  side.replaceChildren();
  const section = (title, select, entries, total) => {
    side.append(element("h3", title));
    const pick = (value, label, n) => {
      const b = element("button");
      b.append(element("span", label), element("span", String(n)));
      b.setAttribute("aria-pressed", String($(select).value === value));
      b.onclick = () => {
        $(select).value = value;
        state.offset = 0;
        guard(loadTorrents);
      };
      side.append(b);
    };
    pick("", say("All", "Tous"), total);
    for (const [value, n] of entries) pick(value, select === "torrent-state" ? statusLabel(value) : value, n);
  };
  section(say("Status", "Statut"), "torrent-state", STATUSES.filter((s) => counts.status[s]).map((s) => [s, counts.status[s]]), counts.all);
  section(say("Categories", "Catégories"), "torrent-category", Object.entries(counts.categories), counts.all);
  section("Tags", "torrent-tag", Object.entries(counts.tags), counts.all);
  section("Trackers", "torrent-tracker", Object.entries(counts.trackers), counts.all);
}
/* The pane under the table has the same three tabs as the desktop: Information, Files, Activity. */
function selectedTorrents() {
  return (state.torrentRows || []).filter((r) => state.selected.has(r.hash));
}
function syncTorrentSelection() {
  document.querySelectorAll("#torrent-table tbody tr").forEach((tr) => tr.classList.toggle("selected", state.selected.has(tr.dataset.hash)));
  const none = !state.selected.size;
  document.querySelectorAll(".torrent-actions [data-action]").forEach((b) => (b.disabled = none));
  renderTorrentDetails();
}
function selectTorrentRow(event, row, rows) {
  const index = rows.findIndex((r) => r.hash === row.hash);
  if (event.shiftKey && state.anchor !== undefined) {
    const [from, to] = [state.anchor, index].sort((x, y) => x - y);
    if (!(event.ctrlKey || event.metaKey)) state.selected.clear();
    rows.slice(from, to + 1).forEach((r) => state.selected.add(r.hash));
  } else if (event.ctrlKey || event.metaKey) {
    state.selected.has(row.hash) ? state.selected.delete(row.hash) : state.selected.add(row.hash);
    state.anchor = index;
  } else {
    state.selected.clear();
    state.selected.add(row.hash);
    state.anchor = index;
  }
  syncTorrentSelection();
}
function renderTorrentTable(rows, columns) {
  const host = $("torrent-table");
  host.replaceChildren();
  if (!rows.length) {
    host.append(element("p", say("No torrents match these filters.", "Aucun torrent ne correspond à ces filtres."), "empty"));
    return;
  }
  const head = element("tr");
  for (const c of columns) {
    const th = element("th");
    if (c.title) th.title = c.title;
    const b = button(c.label + (state.sort === c.key ? (state.descending ? " ↓" : " ↑") : ""), () => {
      state.descending = state.sort === c.key ? !state.descending : false;
      state.sort = c.key;
      return loadTorrents();
    }, "quiet header-sort");
    th.append(b);
    head.append(th);
  }
  const thead = element("thead");
  thead.append(head);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr");
    tr.dataset.hash = row.hash;
    tr.tabIndex = 0;
    tr.onclick = (event) => selectTorrentRow(event, row, rows);
    for (const c of columns) {
      const cell = element("td", undefined, c.key === "name" ? "name" : "");
      const value = c.render(row);
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? "—";
      if (c.key === "name") cell.title = row.name;
      tr.append(cell);
    }
    body.append(tr);
  }
  const table = element("table");
  table.append(thead, body);
  host.append(table);
}
state.detailTab = "info";
state.activity = [];
function renderTorrentDetails() {
  const pane = $("torrent-details");
  pane.hidden = false;
  const tabs = element("div", undefined, "detail-tabs");
  for (const [key, label] of [["info", say("Information", "Informations")], ["files", say("Files", "Fichiers")], ["activity", say("Activity", "Activité")]]) {
    const b = button(label, () => {
      state.detailTab = key;
      renderTorrentDetails();
    }, "detail-tab");
    b.setAttribute("aria-pressed", String(state.detailTab === key));
    tabs.append(b);
  }
  const body = element("div", undefined, "detail-body");
  const chosen = selectedTorrents();
  const row = chosen.length === 1 ? chosen[0] : null;
  if (state.detailTab === "activity") {
    body.append(element("pre", state.activity.join("\n") || "—"));
  } else if (!row) {
    body.append(element("p", say(`${state.selected.size} torrents selected.`, `${state.selected.size} torrents sélectionnés.`), "muted"));
  } else if (state.detailTab === "files") {
    body.append(element("p", say("Loading…", "Chargement…"), "muted"));
    const hash = row.hash;
    api(`torrents/${hash}/files?client_id=${encodeURIComponent(row.client_id || state.clientId)}`)
      .then((files) => {
        if (state.detailTab !== "files" || !state.selected.has(hash)) return;
        const list = element("table", undefined, "dense");
        const head = element("tr");
        [say("File", "Fichier"), say("Size", "Taille"), say("Download", "Télécharger")].forEach((h) => head.append(element("th", h)));
        const thead = element("thead");
        thead.append(head);
        const tbody = element("tbody");
        files.forEach((f) => {
          const tr = element("tr");
          tr.append(element("td", f.name, "name"), element("td", bytes(f.size)), element("td", f.wanted ? "✓" : "—"));
          tbody.append(tr);
        });
        list.append(thead, tbody);
        body.replaceChildren(list);
      })
      .catch((error) => body.replaceChildren(element("p", error.message, "muted")));
  } else {
    // The same lines as the desktop's Information tab.
    body.append(
      element(
        "pre",
        [
          row.name,
          `${say("Status", "État")} : ${statusLabel(row.status)}`,
          `${say("Download Folder", "Dossier de téléchargement")} : ${row.folder}`,
          `Trackers : ${row.trackers.join(", ") || say("No tracker", "Aucun tracker")}`,
          `Tags : ${row.tags.join(", ")}`,
          `Hash : ${row.hash}`,
        ].join("\n"),
      ),
    );
  }
  pane.replaceChildren(tabs, body);
}
async function loadTorrents() {
  const params = new URLSearchParams({
    q: $("torrent-query").value,
    offset: state.offset,
    sort: state.sort,
    descending: state.descending,
    tracker: $("torrent-tracker").value,
    state: $("torrent-state").value,
    category: $("torrent-category").value,
    tag: $("torrent-tag").value,
  });
  const r = await api(`torrents?${params}`);
  state.torrentRows = r.rows;
  options($("torrent-tag"), r.tags, say("All tags", "Tous les tags"));
  sidebar(r.counts);
  options(
    $("torrent-tracker"),
    r.trackers,
    say("All trackers", "Tous les trackers"),
  );
  options(
    $("torrent-category"),
    r.categories,
    say("All categories", "Toutes les catégories"),
  );
  const labels = [
    ...(state.clientId === "all" ? [["client_name", say("Client", "Client"), (v) => v.client_name]] : []),
    ["name", say("Torrent", "Torrent"), (v) => v.name],
    ["status", say("Status", "État"), (v) => statusLabel(v.status)],
    ["progress", say("Progress", "Progression"), (v) => {
      const bar = element("div", undefined, "bar"), fill = element("i");
      fill.style.width = `${v.progress * 100}%`;
      bar.append(fill, element("span", `${(v.progress * 100).toFixed(1)} %`));
      return bar;
    }],
    ["size", say("Size", "Taille"), (v) => bytes(v.size)],
    ["download", say("Download/s", "Réception/s"), (v) => bytes(v.download)],
    ["upload", say("Upload/s", "Envoi/s"), (v) => bytes(v.upload)],
    ["seeds", say("Seeders", "Seeders"), (v) => `${v.seeds >= 0 ? v.seeds : "?"} (${v.total_seeds >= 0 ? v.total_seeds : "?"})`],
    ["peers", say("Peers", "Pairs"), (v) => `${v.peers >= 0 ? v.peers : "?"} (${v.total_peers >= 0 ? v.total_peers : "?"})`],
    ["ratio", "Ratio", (v) => num(v.ratio)],
    ["eta", "ETA", (v) => (v.eta >= 0 && v.eta < 8640000 ? duration(v.eta) : "∞")],
    ["zen", "≈ Zen / j", (v) => num(v.zen) + (v.provisional ? " *" : "")],
    ["note", "≈ Note", (v) => num(v.note) + (v.provisional ? " *" : "")],
  ];
  const sortable = new Set(["name", "client_name", "status", "size", "progress", "download", "upload", "ratio", "seeds", "peers", "zen", "note"]);
  renderTorrentTable(
    r.rows,
    labels
      .filter(([key]) => sortable.has(key) || key === "eta")
      .map(([key, label, render]) => ({
        key,
        label,
        render,
        title: ["seeds", "peers"].includes(key) ? say(
          "Connected (swarm total). ? = unknown. Sorted by total when known.",
          "Connectés (total de l'essaim). ? = inconnu. Tri par total lorsqu'il est connu.",
        ) : "",
      })),
  );
  syncTorrentSelection();
  $("torrent-count").textContent =
    `${r.total} torrents · ${Math.floor(state.offset / 100) + 1}` + (r.client_errors?.length ? " · " + r.client_errors.map(e => `${e.name}: ${e.message}`).join(" · ") : "");
  $("torrent-prev").disabled = !state.offset;
  $("torrent-next").disabled = state.offset + 100 >= r.total;
  $("zen-daily").textContent = num(r.zen.daily);
  $("zen-count").textContent = r.zen.count ?? "—";
}
async function manage(action) {
  if (state.clientId === "all") throw Error(say("Choose a client to manage its torrents.", "Choisissez un client pour gérer ses torrents."));
  const hashes = [...state.selected];
  if (!hashes.length)
    throw Error(say("Select torrents first.", "Sélectionnez des torrents."));
  const body = { kind: "manage", action, hashes, client_id: state.clientId };
  if (["delete", "remove"].includes(action)) {
    const preview = await api("confirm", body),
      content = $("dialog-content");
    content.replaceChildren(
      element(
        "h2",
        action === "delete"
          ? say("Delete files?", "Supprimer les fichiers ?")
          : say("Remove torrents?", "Retirer les torrents ?"),
      ),
      element("p", preview.warning),
    );
    const list = element("ul");
    preview.torrents.forEach((t) =>
      list.append(element("li", `${t.name} · ${t.folder}`)),
    );
    content.append(
      list,
      button(say("Cancel", "Annuler"), () => $("dialog").close(), "quiet"),
      button(
        say("Confirm", "Confirmer"),
        async () => {
          state.activity.push(`${new Date().toLocaleTimeString()}  ${action}: ${hashes.length}`);
          await job({ ...body, confirmation: preview.token }, () =>
            job({ kind: "refresh" }, loadTorrents),
          );
          $("dialog").close();
        },
        "danger",
      ),
    );
    $("dialog").showModal();
    content.querySelector("button").focus();
    return;
  }
  state.activity.push(`${new Date().toLocaleTimeString()}  ${action}: ${hashes.length}`);
  await job(body, () => job({ kind: "refresh" }, loadTorrents));
}
function searchColumns() {
  return [
    {
      label: "Torrent",
      name: true,
      render: (r) => button(r.title, () => details(r)),
    },
    { label: say("Size", "Taille"), render: (r) => bytes(r.size) },
    { label: "Seeds", render: (r) => r.seeders },
    { label: "≈ Zen / j", render: (r) => num(r.zen) },
    { label: "≈ Note", render: (r) => num(r.note) },
    { label: say("Age", "Âge"), render: (r) => age(r.published_at) },
  ];
}
async function enqueue(hashes) {
  if (!hashes.length)
    throw Error(say("Select torrents first.", "Sélectionnez des torrents."));
  await job({ kind: "enqueue", hashes }, async () => {
    toast(
      say("Added to download queue.", "Ajouté à la file de téléchargement."),
    );
    await navigate("queue");
  });
}
function showCatalogue(r) {
  const parts = [
    `${r.count} torrents`,
    say(
      "Coverage is not guaranteed complete.",
      "La couverture complète n’est pas garantie.",
    ),
  ];
  if (r.updated_at)
    parts.push(`${say("Updated", "Actualisé")} · ${age(r.updated_at)}`);
  if (r.limited_categories.length)
    parts.push(
      say(
        "Indexer paging limit reached.",
        "Limite de pagination de l’indexeur atteinte.",
      ),
    );
  if (r.paused)
    parts.push(
      say("Historical fetch paused.", "Récupération de l’historique en pause."),
    );
  if (r.snapshot_imported_at)
    parts.push(
      say(
        "Includes Zen Lab baseline metadata; direct c411 data takes priority.",
        "Inclut les métadonnées de base Zen Lab ; les données c411 sont prioritaires.",
      ),
    );
  $("catalogue-status").textContent = parts.join(" · ");
}
async function loadQueue() {
  const clientId = state.clientId;
  const rows = await api("queue");
  if (clientId !== state.clientId) return;
  const snapshot = JSON.stringify([clientId, language, rows]);
  if (state.queueSnapshot === snapshot) return;
  state.queueSnapshot = snapshot;
  state.queueRows = rows;
  const keys = new Set(rows.map((r) => r.key));
  for (const key of state.queueSelected) {
    if (!keys.has(key)) state.queueSelected.delete(key);
  }
  closeQueueMenu();
  const count = (status) => rows.filter((r) => r.status === status).length;
  const attention = rows.filter((r) => ["failed", "refused", "uncertain"].includes(r.status)).length;
  $("queue-summary").textContent = say(
    `${rows.length} total · ${count("queued")} queued · ${count("sending")} sending · ${count("sent")} sent · ${attention} need attention`,
    `${rows.length} au total · ${count("queued")} en attente · ${count("sending")} en cours d’envoi · ${count("sent")} envoyés · ${attention} à vérifier`,
  );
  table(
    "queue-table",
    rows,
    [
      { label: "Torrent", name: true, render: (r) => r.title },
      { label: "Client", render: (r) => r.client_name },
      { label: say("Size", "Taille"), render: (r) => bytes(r.size) },
      { label: "≈ Zen / j", render: (r) => num(r.zen) },
      { label: "≈ Note", render: (r) => num(r.note) },
      { label: say("Folder", "Dossier"), render: (r) => r.folder },
      { label: say("Status", "État"), render: (r) => r.status === "uncertain" ? say("Check Torrent Client before retrying", "Vérifier le client torrent avant de réessayer") : r.status },
      { label: say("Details", "Détails"), render: (r) => r.status === "uncertain" ? say("Check the Torrent Client before removing and queueing this entry again.", "Vérifier le client torrent avant de retirer et remettre cette entrée en file.") : r.reason },
    ],
    state.queueSelected,
    "key",
    queueControls,
  );
  queueControls();
}
function queueControls() {
  const rows = state.queueRows;
  $("start-queue").disabled = !rows.some((r) => r.status === "queued");
  $("remove-queue").disabled = !state.queueSelected.size;
  $("retry-queue").disabled = !rows.some((r) => state.queueSelected.has(r.key)
    && (r.status === "refused" || (r.status === "failed" && r.retry_safe)));
  $("clear-sent-queue").disabled = !rows.some((r) => r.status === "sent");
}
function closeQueueMenu() {
  $("queue-menu").hidden = true;
}
function openQueueMenu(event) {
  const row = event.target.closest("tbody tr[data-key]");
  if (!row) return;
  event.preventDefault();
  if (!state.queueSelected.has(row.dataset.key)) {
    state.queueSelected.clear();
    state.queueSelected.add(row.dataset.key);
  }
  $("queue-table").querySelectorAll("tbody tr").forEach((tr) => {
    tr.querySelector("input").checked = state.queueSelected.has(tr.dataset.key);
  });
  const selectAll = $("queue-table").querySelector("thead input");
  selectAll.checked = state.queueRows.every((r) => state.queueSelected.has(r.key));
  queueControls();
  const menu = $("queue-menu");
  menu.replaceChildren();
  for (const id of ["start-queue", "retry-queue", "remove-queue", "clear-sent-queue"]) {
    const source = $(id);
    const action = element("button", source.textContent.trim());
    action.type = "button";
    action.role = "menuitem";
    action.disabled = source.disabled;
    action.onclick = () => { closeQueueMenu(); source.click(); };
    menu.append(action);
  }
  menu.hidden = false;
  const bounds = row.getBoundingClientRect();
  const x = event.type === "keydown" ? bounds.left : event.clientX;
  const y = event.type === "keydown" ? bounds.bottom : event.clientY;
  menu.style.left = `${Math.max(0, Math.min(x, innerWidth - menu.offsetWidth))}px`;
  menu.style.top = `${Math.max(0, Math.min(y, innerHeight - menu.offsetHeight))}px`;
  menu.querySelector("button:not(:disabled)")?.focus();
}
$("queue-table").addEventListener("contextmenu", openQueueMenu);
$("queue-table").addEventListener("keydown", (event) => {
  if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) openQueueMenu(event);
});
$("queue-menu").addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeQueueMenu();
    $("queue-table").querySelector("tbody input:checked")?.focus();
  }
  if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    const buttons = [...$("queue-menu").querySelectorAll("button:not(:disabled)")];
    const index = buttons.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
      : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
  }
});
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest("#queue-menu")) closeQueueMenu();
});
window.addEventListener("resize", closeQueueMenu);
document.addEventListener("scroll", closeQueueMenu, true);
async function details(row, queueAction = null) {
  const content = $("dialog-content");
  const chip = (text, kind) => element("span", text, "dt-chip" + (kind ? " dt-" + kind : ""));
  const flags = element("div", undefined, "dt-flags"),
    badge = element("span", undefined, "dt-badge"),
    byline = element("p", undefined, "muted"),
    banner = element("div", undefined, "dt-banner"),
    stats = element("div", undefined, "dt-row"),
    hash = element("p", `${say("Hash", "Hash")}: ${row.hash}`, "muted dt-hash"),
    facts = element("div", undefined, "dt-row"),
    card = element("div", undefined, "dt-card"),
    ids = element("div", undefined, "dt-row"),
    trust = element("div", undefined, "dt-trust"),
    extras = element("div");
  badge.hidden = banner.hidden = card.hidden = trust.hidden = true;
  const head = element("div", undefined, "dt-head");
  head.append(badge, flags, element("span", undefined, "spacer"));
  if (row.website && /^https?:\/\//.test(row.website)) {
    const link = element("a", say("Open on website", "Ouvrir sur le site"), "button-link");
    link.href = row.website;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    head.append(link);
  }
  if (row.published_at) byline.textContent = say("Published ", "Publié ") + new Date(row.published_at * 1000).toLocaleString(language === "fr" ? "fr-FR" : "en-GB");
  stats.append(chip(bytes(row.size)), chip(say(`${row.seeders} seeders`, `${row.seeders} seeders`), "up"), chip(`≈ ${num(row.zen)} Zen / ${say("day", "j")}`, "zen"));
  const bar = element("div", undefined, "dt-bar");
  bar.append(button(say("Add to queue", "Ajouter à la file"), queueAction || (() => enqueue([row.hash])), "primary"));
  content.replaceChildren(head, element("h2", row.title, "dt-title"), byline, banner, stats, hash, facts, extras, card, ids, trust, bar);
  $("dialog").showModal();
  if (new URL(state.setup.indexer_url).hostname !== "c411.org") return;
  await job({ kind: "details", hashes: [row.hash] }, (r) => {
    if (!$("dialog").open) return;
    const info = r.info || {};
    const kind = info.subcategory || info.category;
    if (kind) {
      badge.textContent = kind.toUpperCase();
      badge.hidden = false;
    }
    if (info.exclusive) flags.append(chip("★ " + say("Exclusive", "Exclusivité"), "warn"));
    if (info.low_bitrate) flags.append(chip(say("Low bitrate", "Bitrate faible"), "warn"));
    const tr = info.trust || {};
    flags.append(chip(tr.tested ? say("Tested", "Testé") : say("Not tested", "Non testé"), tr.tested ? "ok" : "warn"));
    const by = [];
    if (info.uploader) by.push(say(`Sent by ${info.uploader}`, `Envoyé par ${info.uploader}`));
    if (info.team) by.push(`Team ${info.team}`);
    if (info.created_at) by.push(say("Published ", "Publié ") + new Date(info.created_at * 1000).toLocaleString(language === "fr" ? "fr-FR" : "en-GB"));
    if (by.length) byline.textContent = by.join(" · ");
    if (tr.status && !tr.tested) {
      banner.append(
        element("strong", say("Torrent not tested by the community", "Torrent non testé par la communauté")),
        element("p", say("This torrent has not yet received enough trust votes. Be careful and check the content before use.", "Ce torrent n’a pas encore reçu suffisamment de votes de confiance. Soyez prudent et vérifiez le contenu avant utilisation.")),
      );
      banner.hidden = false;
    }
    if (info.leechers !== null && info.leechers !== undefined) stats.append(chip(say(`${info.leechers} leechers`, `${info.leechers} leechers`), "down"));
    if (info.completions !== null && info.completions !== undefined) stats.append(chip(say(`${info.completions} completed`, `${info.completions} complétés`), "done"));
    if (info.seeders === 0) stats.append(chip(say("Seeds wanted", "Demande de seeds"), "warn"));
    if (r.files?.length) hash.textContent += `  ·  ${say("Files", "Fichiers")}: ${r.files.length}`;
    for (const [name, values] of info.facts || []) facts.append(chip(`${name}: ${values.join(", ")}`));
    const m = info.media;
    if (m && (m.title || m.tmdb_id)) {
      if (info.poster) {
        const img = element("img", undefined, "dt-poster");
        img.alt = "";
        img.src = "api/poster?url=" + encodeURIComponent(info.poster);
        img.onerror = () => img.remove();
        card.append(img);
      }
      const text = element("div");
      const year = m.year ? ` (${m.year})` : "";
      const type = { movie: "Film", tv: say("TV series", "Série TV") }[m.kind];
      text.append(element("h3", m.title + year + (type ? "  ·  " + type : ""), "dt-card-title"));
      if (m.original_title && m.original_title !== m.title) text.append(element("p", m.original_title, "muted"));
      if (m.genres?.length) {
        const g = element("div", undefined, "dt-row");
        m.genres.forEach((x) => g.append(chip(x)));
        text.append(g);
      }
      const line = [];
      if (m.rating) line.push(`★ ${m.rating.toFixed(1)}/10 TMDB` + (m.votes ? ` · ${m.votes} ${say("votes", "votes")}` : ""));
      if (m.runtime) line.push(`${m.runtime} min`);
      if (m.directors?.length) line.push(say("Director: ", "Réalisateur : ") + m.directors.join(", "));
      if (line.length) text.append(element("p", line.join("  ·  ")));
      if (m.cast?.length) text.append(element("p", say("With ", "Avec ") + m.cast.join(", ") + "…", "muted"));
      const links = element("div", undefined, "dt-row");
      const site = (label, url) => {
        const a = element("a", label);
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        links.append(a);
      };
      if (m.tmdb_id) site(say("View on TMDB", "Voir sur TMDB"), `https://www.themoviedb.org/${m.kind === "tv" ? "tv" : "movie"}/${m.tmdb_id}`);
      if (m.imdb_id) site(say("View on IMDb", "Voir sur IMDb"), `https://www.imdb.com/title/${m.imdb_id}/`);
      text.append(links);
      card.append(text);
      card.hidden = false;
      if (m.tmdb_id) ids.append(chip(`TMDB ${m.tmdb_id}`, "id"));
      if (m.imdb_id) ids.append(chip(`IMDb ${m.imdb_id}`, "id"));
    }
    if (tr.status || tr.positive || tr.negative) {
      trust.append(
        element("strong", say("Community trust", "Confiance communautaire")),
        element("p", `${tr.tested ? say("Tested", "Testé") : say("Not tested", "Non testé")}  ·  👍 ${tr.positive}  ·  👎 ${tr.negative}` + (tr.required && !tr.tested ? `  ·  ${say(`(${tr.required} votes required)`, `(${tr.required} votes requis)`)}` : "")),
      );
      trust.hidden = false;
    }
    if (r.nfo) {
      const d = element("details");
      d.append(element("summary", say("Show the NFO", "Afficher le NFO")), element("pre", r.nfo));
      extras.append(d);
    }
    if (r.files?.length) {
      const d = element("details");
      d.append(element("summary", say(`Show the files (${r.files.length})`, `Afficher les fichiers (${r.files.length})`)));
      const list = element("ul", undefined, "dt-files");
      r.files.forEach(([path, size]) => list.append(element("li", `${path}  ·  ${bytes(size)}`)));
      d.append(list);
      extras.append(d);
    }
    const description = element("div", undefined, "description");
    description.innerHTML = r.description;
    description.querySelectorAll("a").forEach((a) => {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    });
    content.insertBefore(description, bar);
    if (r.images.length) {
      const links = element("details");
      links.append(element("summary", say("Images on the host website", "Images sur le site hébergeur")));
      r.images.forEach((url) => {
        if (!/^https?:\/\//.test(url)) return;
        const a = element("a", url);
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const p = element("p");
        p.append(a);
        links.append(p);
      });
      content.insertBefore(links, bar);
    }
  });
}
// Library batch actions, as on the desktop: they use the Candidates earlier searches found.
async function checkAllCandidates() {
  await job({ kind: "check-all" }, async (r) => {
    toast(say(
      `Checked ${r.items} Local Items: ${r.full} full, ${r.partial} partial, ${r.none} without a Match, ${r.archive} in archives.`,
      `${r.items} éléments vérifiés : ${r.full} complètes, ${r.partial} partielles, ${r.none} sans correspondance, ${r.archive} dans des archives.`,
    ));
    if (libraryUI.item) await reviewLibraryItem(libraryUI.item);
  });
}
async function reseedAllMatches() {
  if (!confirm(say(
    "Reseed every confirmed Full Match across the Library? Archives and disk renames are left for each item's own review.",
    "Remettre en seed toutes les correspondances complètes de la bibliothèque ? Les archives et les renommages sur disque restent à traiter élément par élément.",
  ))) return;
  await job({ kind: "reseed-all" }, (r) => toast(say(
    `${r.started} verifications started, ${r.already_present} already in the client, ${r.skipped} left for review.`,
    `${r.started} vérifications lancées, ${r.already_present} déjà dans le client, ${r.skipped} à traiter à la main.`,
  )));
}
async function enter() {
  await refreshSetup();
  $("logout").hidden = state.setup.web_auth === "proxy";
  $("login-screen").hidden = true;
  $("workspace").hidden = false;
  const parts = resolveRoute(location.hash);
  writeRoute(parts, true);
  await navigate(...parts);
  if (state.setup.configured) await job({ kind: "refresh" }, loadTorrents);
  await pollJobs();
}
$("library-check-all").onclick = () => guard(checkAllCandidates);
$("library-reseed-all").onclick = () => guard(reseedAllMatches);
$("login-form").onsubmit = (e) => {
  e.preventDefault();
  guard(async () => {
    await api("login", { password: $("login-password").value });
    $("login-password").value = "";
    await enter();
  });
};
$("client-form").onsubmit = (e) => {
  e.preventDefault();
  guard(() => testClient(true));
};
$("test-client").onclick = () => guard(() => testClient());
$("client-kind").onchange = clientKind;
$("folder-form").onsubmit = (e) => {
  e.preventDefault();
  guard(() => testFolder(true));
};
$("test-folder").onclick = () => guard(() => testFolder());
$("browse").onclick = () => guard(() => browse());
$("indexer-form").onsubmit = (e) => {
  e.preventDefault();
  guard(() => testIndexer(true));
};
$("test-indexer").onclick = () => guard(() => testIndexer());
$("finish-setup").onclick = () =>
  guard(async () => {
    await navigate("torrents");
    if (state.setup.configured) await job({ kind: "refresh" }, loadTorrents);
  });
document
  .querySelectorAll("[data-view]")
  .forEach((b) => (b.onclick = () => guard(() => navigate(b.dataset.view))));
document
  .querySelectorAll("[data-step]")
  .forEach((b) => (b.onclick = () => step(b.dataset.step)));
document
  .querySelectorAll("[data-action]")
  .forEach((b) => (b.onclick = () => guard(() => manage(b.dataset.action))));
$("logout").onclick = () =>
  guard(async () => {
    await api("logout", {});
    state.jobs.clear();
    clearAgentToken();
    $("workspace").hidden = true;
    $("login-screen").hidden = false;
  });
$("theme").value = localStorage.getItem("tl-theme") || "auto";
function theme() {
  const value = $("theme").value;
  document.documentElement.dataset.theme = value === "auto"
    ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : value;
  localStorage.setItem("tl-theme", value);
}
$("theme").onchange = theme;
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", theme);
theme();
$("language").onchange = () => {
  if (state.view === "documentation") setTimeout(() => guard(loadGuides), 0);
  language = $("language").value;
  localStorage.setItem("tl-language", language);
  translate();
  renderSecretHints();
  document.dispatchEvent(new Event("tl-language-changed"));
  if (state.view === "setup" && state.settingsSection === "agents") guard(loadAgents);
  if (state.view === "zen") { guard(loadZenSeeding); retranslatePlan(); if (profileState) showZenProfile(profileState); }
  if (state.view === "search") searchRetranslate();
  if (state.view === "upload") { renderUploadQueue(); uploadEditorState(); }
  labelTorrentBar();
  if (state.view === "torrents") guard(loadTorrents);
  if (state.view === "media") { mediaViews(); guard(loadMedia); mediaQueueRender(); }
  $("page-title").textContent =
    document.querySelector(`[data-view="${state.view}"]`)?.textContent ||
    state.view;
};
translate();
labelTorrentBar();
$("refresh").onclick = () =>
  guard(() => job({ kind: "refresh" }, loadTorrents));
let filterTimer;
function filter() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    state.offset = 0;
    guard(loadTorrents);
  }, 250);
}
$("torrent-query").oninput = filter;
["torrent-state", "torrent-tracker", "torrent-category", "torrent-tag"].forEach(
  (id) => ($(id).onchange = filter),
);
$("torrent-prev").onclick = () => {
  state.offset = Math.max(0, state.offset - 100);
  guard(loadTorrents);
};
$("torrent-next").onclick = () => {
  state.offset += 100;
  guard(loadTorrents);
};
$("queue-plan").onclick = () => guard(async () => {
  if (state.planDirty) throw Error(say("Rebuild the Plan after changing its settings.", "Recréez le Plan après modification des paramètres."));
  const grouped = new Map();
  for (const row of state.planRows.filter(r => !r.reseed && state.planSelected.has(r.hash))) {
    const id = row.client_id || state.clientId;
    if (!grouped.has(id)) grouped.set(id, []);
    grouped.get(id).push(row.hash);
  }
  $("queue-plan").disabled = true;
  try {
    for (const [id, hashes] of grouped) {
      for (let offset = 0; offset < hashes.length; offset += 1000) {
        const identifier = await job({kind: "enqueue", hashes: hashes.slice(offset, offset + 1000), client_id: id}, loadQueue);
        await waitForJob(identifier);
      }
    }
    await navigate("queue");
  } finally { $("queue-plan").disabled = false; }
});
$("start-queue").onclick = () =>
  guard(() => job({ kind: "send-queue" }, loadQueue));
async function editQueue(action, keys) {
  try {
    for (let offset = 0; offset < keys.length; offset += 1000) {
      await api(`queue/${action}`, keys.slice(offset, offset + 1000));
    }
  } finally {
    await loadQueue();
  }
}
$("retry-queue").onclick = () => guard(() => editQueue("retry", [...state.queueSelected]));
$("clear-sent-queue").onclick = () => guard(() => editQueue("remove",
  state.queueRows.filter((r) => r.status === "sent").map((r) => r.key)));
$("remove-queue").onclick = () => guard(() => editQueue("remove", [...state.queueSelected]));
$("scan").onclick = () => guard(() => job({ kind: "scan" }, loadLibrary));
$("library-query").oninput = () => {
  state.libraryOffset = 0;
  guard(loadLibrary);
};
$("library-prev").onclick = () => {
  state.libraryOffset = Math.max(0, state.libraryOffset - 100);
  guard(loadLibrary);
};
$("library-next").onclick = () => {
  state.libraryOffset += 100;
  guard(loadLibrary);
};
setInterval(() => {
  if (!$("workspace").hidden) guard(pollJobs);
}, 2000);
setInterval(() => {
  if (
    !$("workspace").hidden &&
    state.setup?.configured &&
    ["torrents", "zen"].includes(state.view) &&
    !state.jobs.size
  )
    guard(() => job({ kind: "refresh" }, loadTorrents));
}, 15000);
guard(async () => {
  try {
    await api("setup");
    await enter();
  } catch (error) {
    if (!error.message.includes("Sign in")) toast(error.message);
  }
});

$("save-announce").onclick = () =>
  guard(async () => {
    const value = $("announce-url").value;
    await api("setup/announce", { value });
    if ($("announce-url").value === value) $("announce-url").value = "";
    state.setup.has_announce_url = true;
    renderSecretHints();
    toast(say("Announce URL saved.", "URL d’annonce enregistrée."));
  });
$("refresh-profile").onclick = () =>
  guard(() =>
    job({ kind: "profile" }, (r) => {
      toast(`${r.balance} Zen · ${r.class || ""}`);
      return job({ kind: "refresh" }, state.view === "zen" ? loadZenSeeding : loadTorrents);
    }),
  );

$("save-proxy").onclick = () =>
  guard(async () => {
    const password = $("proxy-password").value;
    await api("setup/proxy", {
      address: $("proxy-address").value,
      username: $("proxy-username").value,
      torrent_client: $("proxy-client").checked,
      ...(password ? { password } : {}),
    });
    if (password) state.setup.has_proxy_password = true;
    if ($("proxy-password").value === password) $("proxy-password").value = "";
    renderSecretHints();
    toast(
      say(
        "Proxy settings saved. Test the connection again.",
        "Proxy enregistré. Testez à nouveau la connexion.",
      ),
    );
  });
$("suggest-mappings").onclick = () =>
  guard(async () => {
    const result = await api("setup/suggest-mappings", {});
    $("mapping-suggestions").replaceChildren(
      ...result.suggestions.map((s) =>
        button(`${s.mapping.local} → ${s.mapping.qbit}`, () => {
          $("folder-local").value = s.mapping.local;
          $("folder-client").value = s.mapping.qbit;
        }),
      ),
    );
    if (!result.suggestions.length)
      $("mapping-suggestions").append(
        element(
          "p",
          result.same_paths
            ? say(
                "Some torrents already use the same path. Select that folder below.",
                "Certains torrents utilisent déjà le même chemin. Sélectionnez ce dossier ci-dessous.",
              )
            : say(
                "No matching file found. Check your mount, then enter both folder paths below.",
                "Aucun fichier correspondant. Vérifiez le montage puis indiquez les deux chemins ci-dessous.",
              ),
        ),
      );
  });

const guideHistory = [];
let currentGuide = "";
async function loadGuides() {
  const guides = await api(`documentation?language=${language}`);
  $("guide-select").replaceChildren(...guides.map(g => new Option(g.title, g.path)));
  guideHistory.length = 0;
  currentGuide = "";
  $("guide-back").title = say("Previous guide", "Guide précédent");
  $("guide-back").setAttribute("aria-label", $("guide-back").title);
  await openGuide(guides[0].path);
}
async function openGuide(path, fragment = "", remember = true) {
  const result = await api(`documentation/page/${path.split("/").map(encodeURIComponent).join("/")}`);
  if (remember && currentGuide && path !== currentGuide) guideHistory.push(currentGuide);
  currentGuide = path;
  $("guide-content").innerHTML = result.html;
  $("guide-select").value = path;
  $("guide-back").disabled = !guideHistory.length;
  $("guide-online").href = `https://github.com/Vietnoirien/TorrentLinker/blob/main/docs/${path}`;
  if (fragment) document.getElementById(decodeURIComponent(fragment))?.scrollIntoView();
  else if (state.view === "documentation") window.scrollTo(0, 0);
}
$("guide-select").onchange = () => guard(() => openGuide($("guide-select").value));
$("guide-back").onclick = () => {
  const previous = guideHistory.pop();
  if (previous) guard(() => openGuide(previous, "", false));
};
$("guide-content").onclick = event => {
  const link = event.target.closest("a[data-guide]");
  if (!link) return;
  event.preventDefault();
  guard(() => openGuide(link.dataset.guide, link.hash.slice(1)));
};

$("target-client").onchange = () => guard(async () => {
  state.clientId = $("target-client").value;
  resetUploadWorkspace();
  state.uploadDraft = null;
  state.uploadSavedOptions = null;
  state.addingClient = false;
  $("client-password").value = ""; $("client-key").value = "";
  state.selected.clear(); state.queueSelected.clear(); state.planSelected.clear();
  state.offset = 0; state.libraryOffset = 0; state.localItem = "";
  $("candidates").hidden = true; $("upload-editor").hidden = true;
  await refreshSetup();
  await navigate(state.clientId === "all" && state.view !== "zen" ? "torrents" : state.view);
  if (state.setup.configured && state.view !== "media") await job({kind: "refresh"}, state.view === "zen" ? loadZenSeeding : loadTorrents);
});
$("add-client").onclick = () => {
  state.addingClient = true;
  $("reseed-folder-settings").hidden = true;
  $("client-name").value = ""; $("client-host").value = "";
  $("client-username").value = ""; $("client-password").value = ""; $("client-key").value = "";
  renderSecretHints();
  $("client-name").focus();
};
$("default-client").onclick = () => guard(async () => {
  await api("clients/default", {client_id: state.setup.client_id}); await refreshSetup();
});
$("remove-client").onclick = () => guard(async () => {
  if (!confirm(say("Remove this client profile? Torrents and files will be kept.", "Retirer ce profil ? Les torrents et fichiers seront conservés."))) return;
  await api("clients/remove", {client_id: state.setup.client_id}); state.clientId = ""; await refreshSetup();
});


function agentReviewInUse() {
  return !document.querySelector('[data-agent-panel="new"]').hidden ||
    $("view-agents").querySelector("details[open]") ||
    ["agent-connections", "agent-proposals", "agent-goals", "agent-activity"]
      .some(id => $(id).contains(document.activeElement));
}
let agentRequest = 0;
async function loadAgents(background = false) {
  const request = ++agentRequest;
  const data = await api("agents");
  if (request !== agentRequest || (background && agentReviewInUse())) return;
  const snapshot = JSON.stringify([data, state.setup.clients, language]);
  if (state.agentSnapshot === snapshot) return;
  state.agentSnapshot = snapshot;
  $("agents-enabled").checked = data.enabled;
  $("agents-endpoint").textContent = new URL("mcp/", location.href).href;
  const choices = $("agent-clients");
  const previous = new Set([...choices.querySelectorAll("input:checked")].map(e => e.value));
  const firstLoad = !choices.children.length;
  choices.replaceChildren(...state.setup.clients.filter(p => p.enabled).map(p => {
    const label = element("label"), input = document.createElement("input");
    input.type = "checkbox"; input.value = p.id;
    input.checked = firstLoad ? p.id === state.setup.client_id : previous.has(p.id);
    label.append(input, document.createTextNode(p.name)); return label;
  }));
  $("agent-permissions").disabled = $("agent-mode").value === "propose";
  const connections = data.connections.filter(g => !g.id.startsWith("assistant-"));
  const permissions = Object.fromEntries([...$("agent-permissions").querySelectorAll("label")]
    .map(label => [label.querySelector("input").value, label.textContent.trim()]));
  const clientNames = new Map(state.setup.clients.map(p => [p.id, p.name]));
  $("agent-connections").replaceChildren(...connections.map(g => {
    const row = element("div", undefined, "card");
    const heading = element("div", undefined, "toolbar");
    heading.append(element("h3", g.name), element("span", g.revoked ? say("Revoked", "Révoquée") : say("Active", "Active"), "badge"));
    const details = element("dl", undefined, "agent-connection-details");
    const fields = [
      [say("Torrent Clients", "Clients torrent"), g.clients.map(id => clientNames.get(id) || id).join(", ")],
      [say("Mode", "Mode"), g.mode === "execute" ? say("Execute permitted actions", "Exécuter les actions autorisées") : say("Proposals only", "Propositions uniquement")],
      [say("Automatic actions", "Actions automatiques"), g.mode === "execute" && g.permissions.length ? g.permissions.map(p => permissions[p] || p).join(", ") : say("None", "Aucune")],
      [say("Daily download budget", "Budget quotidien"), bytes(g.daily_bytes)],
      [say("Torrents per day", "Torrents par jour"), String(g.daily_torrents)],
      [say("Keep free", "Espace à conserver"), bytes(g.reserve_bytes)],
    ];
    fields.forEach(([label, value]) => details.append(element("dt", label), element("dd", value)));
    row.append(heading, details);
    if (!g.revoked) row.append(button(say("Revoke connection", "Révoquer la connexion"), async () => {
      await api(`agents/${g.id}/revoke`, {}); await loadAgents();
    }));
    return row;
  }));
  if (!connections.length) $("agent-connections").append(element("p", say(
    "No connections yet. Choose New connection to create one.",
    "Aucune connexion. Choisissez Nouvelle connexion pour en créer une."
  ), "empty"));
  $("agent-proposals").replaceChildren(...data.proposals.map(p => {
    const row = element("details", undefined, "card");
    const name = data.connections.find(g => g.id === p.grant_id)?.name || p.grant_id;
    row.append(element("summary", `${name} · ${p.body.kind} · ${p.body.client_id} · ${p.status}`));
    const details = element("pre", JSON.stringify(p.body, null, 2)); row.append(details);
    if (p.status === "pending") {
      row.append(button(say("Approve", "Approuver"), async () => {
        if (["upload-send", "upload-reset", "upload-remove"].includes(p.body.kind) ||
          (p.body.kind === "edit-queue-selection" && p.body.queue_action === "remove")) {
          await aReview(p.id, loadAgents); return;
        }
        const destructive = p.body.kind === "manage" && ["remove", "delete"].includes(p.body.action);
        if (destructive) {
          const preview = await api(`agents/proposals/${p.id}/review`);
          if (!confirm(preview.client + "\n" + preview.warning + "\n\n" +
            preview.torrents.map(t => t.name + "\n" + t.folder).join("\n"))) return;
        }
        await api(`agents/proposals/${p.id}/approve`, {}); await loadAgents();
      }), button(say("Reject", "Refuser"), async () => {
        await api(`agents/proposals/${p.id}/reject`, {}); await loadAgents();
      }));
    }
    if (p.job_id) row.append(button(say("View job", "Voir la tâche"), async () => {
      const job = await api(`jobs/${p.job_id}`);
      details.textContent = JSON.stringify(job, null, 2);
    }), button(say("Cancel job", "Annuler la tâche"), async () => {
      await api(`jobs/${p.job_id}/cancel`, {}); await loadAgents();
    }));
    if (p.body.kind === "send-queue") row.append(button(
      say("Release uncertain storage reservation", "Libérer la réserve disque incertaine"), async () => {
        if (!confirm(say(
          "Check the Torrent Client first. Confirm that this send has finished or did not start. Daily spending stays counted.",
          "Vérifiez d'abord le client torrent. Confirmez que cet envoi est terminé ou n'a pas démarré. Le budget quotidien reste débité."
        ))) return;
        await api(`agents/proposals/${p.id}/release-storage`, {}); await loadAgents();
      }
    ));
    return row;
  }));
  $("agent-goals").replaceChildren(...data.goals.map(g => element("pre", JSON.stringify(g.body, null, 2))));
  $("agent-activity").replaceChildren(...data.activity.map(e =>
    element("p", `${new Date(e.created * 1000).toLocaleString()} · ${e.action} · ${e.detail}`)));
}
$("agents-refresh").onclick = () => guard(loadAgents);
let agentPolling = false;
setInterval(() => {
  if (agentPolling || document.hidden || $("workspace").hidden || state.view !== "setup" || state.settingsSection !== "agents") return;
  // Do not replace a form or review the owner is currently using. Refresh is always available.
  if (agentReviewInUse()) return;
  agentPolling = true;
  guard(() => loadAgents(true)).finally(() => { agentPolling = false; });
}, 3000);
$("agents-enabled").onchange = () => guard(async () => {
  await api("agents", {enabled: $("agents-enabled").checked}, "PUT"); await loadAgents();
});
$("agent-mode").onchange = () => { $("agent-permissions").disabled = $("agent-mode").value === "propose"; };
$("agent-token-hide").onclick = clearAgentToken;
$("agent-token-save").onclick = () => {
  const token = $("agent-token").value;
  if (!token) return;
  const url = URL.createObjectURL(new Blob([token + "\n"], {type: "text/plain;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "torrentlinker-token.txt";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$("agent-form").onsubmit = event => {
  event.preventDefault();
  guard(async () => {
    const generation = agentTokenGeneration;
    const grant = await api("agents", {
      name: $("agent-name").value,
      clients: [...$("agent-clients").querySelectorAll("input:checked")].map(e => e.value),
      mode: $("agent-mode").value,
      permissions: $("agent-mode").value === "propose" ? [] : [...$("agent-permissions").querySelectorAll("input:checked")].map(e => e.value),
      daily_bytes: Number($("agent-bytes").value) * 1024 ** 3,
      daily_torrents: Number($("agent-count").value),
      reserve_bytes: Number($("agent-reserve").value) * 1024 ** 3,
    });
    if (generation === agentTokenGeneration) {
      $("agent-token").value = grant.token; $("agent-token-box").hidden = false;
    } else {
      toast(say("Connection created. Its token was dismissed when you left New connection. Revoke it and create another if needed.",
        "Connexion créée. Son jeton a été masqué lorsque vous avez quitté Nouvelle connexion. Révoquez-la et recréez-en une si nécessaire."));
    }
    await loadAgents();
  });
};

$("navigation-toggle").onclick = () => {
  const collapsed = document.body.classList.toggle("navigation-collapsed");
  $("navigation-toggle").setAttribute("aria-expanded", String(!collapsed));
};

if (matchMedia("(max-width: 1050px)").matches) {
  document.body.classList.add("navigation-collapsed");
  $("navigation-toggle").setAttribute("aria-expanded", "false");
}

$("plan-prev").onclick = () => { state.planOffset = Math.max(0, (state.planOffset || 0) - 100); renderPlan(); };
$("plan-next").onclick = () => { state.planOffset = (state.planOffset || 0) + 100; renderPlan(); };

$("navigation-close").onclick = () => {
  document.body.classList.add("navigation-collapsed");
  $("navigation-toggle").setAttribute("aria-expanded", "false");
  $("navigation-toggle").focus();
};

async function waitForJob(identifier) {
  while (true) {
    const result = await api(`jobs/${identifier}`);
    if (result.status === "completed") return;
    if (!["queued", "running"].includes(result.status))
      throw Error(result.error || say("Job cancelled", "Tâche annulée"));
    await new Promise(resolve => setTimeout(resolve, 500));
  }
}
