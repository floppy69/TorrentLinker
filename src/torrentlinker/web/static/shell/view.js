"use strict";
const $ = (id) => document.getElementById(id);
let state = {},
  request;
const say = (en, fr) => (state.language === "fr" ? fr : en);
const pages = {
  zen: [
    "Zen",
    "Zen",
    "Track your earnings and plan what to seed next.",
    "Suivez vos gains et préparez vos prochains torrents à partager.",
  ],
  library: [
    "Library",
    "Bibliothèque",
    "Find Orphans, compare Candidates and Reseed your files.",
    "Retrouvez les fichiers orphelins, comparez les candidats et remettez vos fichiers en partage.",
  ],
  upload: [
    "Upload",
    "Upload",
    "Prepare an Upload, then review and publish its Draft on c411.",
    "Préparez un upload, puis vérifiez et publiez son brouillon sur c411.",
  ],
  search: [
    "Search",
    "Recherche",
    "Search torrents and queue the ones you want to download.",
    "Recherchez des torrents et ajoutez vos choix à la file de téléchargement.",
  ],
  feeds: [
    "RSS",
    "RSS",
    "Review RSS releases and manage subscription rules.",
    "Consultez les publications RSS et gérez vos règles d’abonnement.",
  ],
  torrents: [
    "Torrents",
    "Torrents",
    "Manage downloads and seeds in your Torrent Client.",
    "Gérez les téléchargements et les partages de votre client torrent.",
  ],
  assistant: [
    "Assistant",
    "Assistant",
    "Discuss tasks, review proposals and schedule automations.",
    "Discutez des tâches, vérifiez les propositions et programmez des automatisations.",
  ],
  media: [
    "Media",
    "Médias",
    "Play videos and music from your Library Folders.",
    "Lisez les vidéos et la musique de vos dossiers de bibliothèque.",
  ],
  "member-assistant": ["Assistant", "Assistant", "Your private discussions and permitted tools.", "Vos discussions privées et vos outils autorisés."],
  "member-search": ["Search", "Recherche", "Search the tracker and request a film.", "Consultez le tracker et demandez un film."],
  "member-queue": ["My queue", "Ma file", "Your accepted Requests.", "Vos demandes acceptées."],
  "member-torrents": ["My downloads", "Mes téléchargements", "Downloads from your accepted Requests.", "Les téléchargements de vos demandes acceptées."],
  notifications: ["Notifications", "Notifications", "Updates for your account.", "Les nouvelles de votre compte."],
  requests: ["Requests", "Demandes", "Review and answer Members’ Requests.", "Examinez les demandes des membres."],
  queue: [
    "Download queue",
    "File de téléchargement",
    "Review downloads before sending them to a client.",
    "Vérifiez les téléchargements avant de les envoyer à un client.",
  ],
  jobs: [
    "Activity",
    "Activité",
    "Follow running tasks and their results.",
    "Suivez les tâches en cours et leurs résultats.",
  ],
  reading: [
    "Reading room",
    "Salon de lecture",
    "Ten thousand books kept alive. Take a moment to read one.",
    "Dix mille livres préservés. Prenez un moment pour en lire un.",
  ],
  documentation: [
    "Documentation",
    "Documentation",
    "Browse the guides and find help for your current task.",
    "Parcourez les guides et trouvez de l’aide pour votre tâche.",
  ],
  setup: [
    "Settings",
    "Paramètres",
    "Manage connections and application preferences.",
    "Gérez les connexions et les préférences de l’application.",
  ],
};
const name = (key) => (pages[key] ? say(...pages[key].slice(0, 2)) : key);
function text(id, en, fr) {
  $(id).textContent = say(en, fr);
}
async function send(action, values = {}) {
  $("error").hidden = true;
  try {
    return await request(action, values);
  } catch (error) {
    // This header frame is too small for a toast; the message stays in its own line.
    $("error").textContent = TLToast.translate(error.message);
    $("error").hidden = false;
  }
}
function options(select, rows, selected) {
  const signature = JSON.stringify(rows);
  if (select.dataset.signature !== signature) {
    select.replaceChildren(
      ...rows.map(([value, label]) => new Option(label, value)),
    );
    select.dataset.signature = signature;
  }
  select.value = selected;
}
function render() {
  document.documentElement.lang = state.language || "en";
  document.documentElement.dataset.theme = state.theme || "dark";
  document.body.dataset.compact = String(!!state.compact);
  for (const id of ["navigation", "header", "band", "update", "help"])
    $(id).hidden = state.region !== id;
  if (state.region === "navigation") {
    const keys = state.pages || [];
    const signature = JSON.stringify([keys, state.language]);
    if ($("pages").dataset.signature !== signature) {
      $("pages").replaceChildren(
        ...keys.map((key) => {
          const button = document.createElement("button");
          button.type = "button";
          button.dataset.view = key;
          button.textContent = name(key);
          button.onclick = () => send("navigate", { view: key });
          return button;
        }),
      );
      $("pages").dataset.signature = signature;
    }
    for (const button of $("pages").children) {
      if (button.dataset.view === state.page)
        button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    options(
      $("page-select"),
      keys.map((key) => [key, name(key)]),
      state.page,
    );
    text("navigation-label", "Navigation", "Navigation");
    text("theme-label", "Theme", "Thème");
    text("language-label", "Language", "Langue");
    options(
      $("theme"),
      [
        ["auto", say("System", "Système")],
        ["light", say("Light", "Clair")],
        ["dark", say("Dark", "Sombre")],
      ],
      state.theme_choice || "auto",
    );
    $("language").value = state.language || "en";
    text("shortcuts", "Keyboard shortcuts", "Raccourcis clavier");
    // On a Shared Screen: back to "Qui regarde ?".
    text("switch-profile", "Change profile", "Changer de profil");
    $("switch-profile").hidden = state.mode !== "web" || !state.shared_screen;
    text("logout", "Sign out", "Se déconnecter");
    $("logout").hidden = state.mode !== "web" || !state.can_logout;
  }
  if (state.region === "header") {
    $("page-title").textContent = name(state.page);
    $("page-description").textContent = pages[state.page]
      ? say(...pages[state.page].slice(2))
      : "";
    text("client-title", "Target client", "Client cible");
    options(
      $("target-client"),
      [
        ...(state.allow_all
          ? [
              [
                "all",
                say("All clients · overview", "Tous les clients · aperçu"),
              ],
            ]
          : []),
        ...(state.clients || []).map((row) => [row.id, row.name]),
      ],
      state.client_id,
    );
    $("target-client").disabled = !!state.client_busy;
    // A Member never chooses the Torrent Client.
    $("client-label").hidden = !state.allow_all && !(state.clients || []).length;
    $("setup-notice").hidden = !state.setup_needed;
    text(
      "setup-message",
      "Add your Indexer API key to get started.",
      "Ajoutez votre clé API d’indexeur pour commencer.",
    );
    text("open-settings", "Open settings", "Ouvrir les paramètres");
    // The key is added on that very page.
    $("open-settings").hidden = state.page === "setup";
    const problems = {
      "no-key": say(
        "Add your c411 API key in Settings → Connections.",
        "Ajoutez votre clé API c411 dans Paramètres → Connexions.",
      ),
      unauthorized: say(
        "c411 refused the key. Check Settings → Connections.",
        "c411 a refusé la clé. Vérifiez Paramètres → Connexions.",
      ),
      "missing-scope": say(
        "Your c411 key needs profile:read access.",
        "Votre clé c411 nécessite le droit profile:read.",
      ),
      "rate-limited": say(
        "c411 is limiting requests. Refresh your profile later.",
        "c411 limite les requêtes. Actualisez votre profil plus tard.",
      ),
      failed: say(
        "Profile unavailable. Check your connection and refresh.",
        "Profil indisponible. Vérifiez la connexion puis actualisez.",
      ),
    };
    $("profile-notice").textContent =
      state.profile_notice || problems[state.profile_problem] || "";
    $("profile-notice").hidden = !$("profile-notice").textContent;
  }
  if (state.region === "band") {
    const band = state.band || {},
      unknown = "—";
    $("balance").textContent =
      say("Zen Balance: ", "Solde Zen : ") + (band.balance ?? unknown);
    $("seeding").textContent =
      say("Seeding: ", "En partage : ") +
      (band.seeding ?? unknown) +
      say(" Zen/day", " Zen/jour");
    $("plan").textContent =
      say("with Plan: ", "avec le Plan : ") + (band.plan ?? unknown);
    $("catalogue").textContent =
      say("Catalogue: ", "Catalogue : ") + (band.catalogue ?? unknown);
    $("refresh-profile").disabled = !!band.busy;
    $("refresh-profile").title = say("Refresh profile", "Actualiser le profil");
    $("refresh-profile").setAttribute("aria-label", $("refresh-profile").title);
  }
  if (state.region === "update") {
    const version = state.release?.tag || "";
    $("update-message").textContent =
      state.mode === "web"
        ? say(
            `TorrentLinker ${version} is available. Update the Web server installation.`,
            `TorrentLinker ${version} est disponible. Mettez à jour l’installation du serveur Web.`,
          )
        : say(
            `TorrentLinker ${version} is available for this desktop.`,
            `TorrentLinker ${version} est disponible pour ce bureau.`,
          );
    text("release", "View release", "Voir la version");
    text("dismiss", "Dismiss", "Masquer");
  }
  if (state.region === "help") {
    text("help-title", "Keyboard shortcuts", "Raccourcis clavier");
    text("help-close", "Close", "Fermer");
    $("help-text").textContent =
      state.mode === "web"
        ? say(
            "Browser shortcuts remain with the browser. Use navigation and search controls, or Tab and Enter.",
            "Les raccourcis du navigateur restent au navigateur. Utilisez la navigation et la recherche, ou Tab et Entrée.",
          )
        : say(
            "Navigate without interrupting the current task.",
            "Naviguez sans interrompre la tâche en cours.",
          );
    $("help-keys").replaceChildren();
    if (state.mode !== "web")
      for (const [key, value] of [
        ...(state.shortcuts || []).map((view, index) => [
          `Ctrl+${index + 1}`,
          name(view),
        ]),
        ["Ctrl+,", name("setup")],
        [
          "Ctrl+F",
          say(
            "Focus search or the Assistant composer; otherwise open Library search",
            "Activer la recherche ou le message Assistant ; sinon ouvrir la recherche Bibliothèque",
          ),
        ],
      ]) {
        const term = document.createElement("dt"),
          detail = document.createElement("dd");
        term.textContent = key;
        detail.textContent = value;
        $("help-keys").append(term, detail);
      }
  }
}
window.addEventListener("shell-environment", (event) => {
  state = event.detail;
  render();
});
window.addEventListener("DOMContentLoaded", async () => {
  request = await TLPanel.connect("shell", { asynchronous: true });
  $("target-client").onchange = () =>
    send("client", { client_id: $("target-client").value });
  $("page-select").onchange = () =>
    send("navigate", { view: $("page-select").value });
  $("theme").onchange = () => send("theme", { value: $("theme").value });
  $("language").onchange = () =>
    send("language", { value: $("language").value });
  for (const [id, action] of [
    ["shortcuts", "shortcuts"],
    ["switch-profile", "profile"],
    ["logout", "logout"],
    ["release", "release"],
    ["dismiss", "dismiss"],
    ["refresh-profile", "refresh-profile"],
    ["help-close", "close"],
  ])
    $(id).onclick = () => send(action);
  $("open-settings").onclick = () => send("navigate", { view: "setup" });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.region === "help") send("close");
  });
  let height = 0;
  new ResizeObserver(() => {
    const next = Math.ceil(document.body.getBoundingClientRect().height);
    if (next !== height) {
      height = next;
      request("layout", { height }).catch(() => {});
    }
  }).observe(document.body);
  window.shellReady();
});
