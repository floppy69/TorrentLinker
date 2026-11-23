"use strict";
const french = {
  planHelp:
    "Créez une proposition à partir du catalogue et du stockage vérifié. Les estimations Zen et les notes issues du cache sont provisoires. Relisez le plan avant l’ajout à la file.",
  planDestinations: "Destinations du Plan",
  planDestinationHelp:
    "Choisissez un client ou répartissez entre plusieurs clients. Budget 0 : espace disponible.",
  planCategory: "Catégorie / sous-catégorie",
  allCategories: "Toutes les catégories",
  optimizeFor: "Optimiser pour",
  zenPerDay: "≈ Zen/jour",
  maxGB: "Budget de téléchargement, Go",
  minTorrentGB: "Taille minimale du torrent, Go",
  maxTorrentGB: "Taille maximale du torrent, Go",
  maxTorrents: "Nombre maximal de torrents",
  maxSeeders: "Sources maximum",
  planNoteHelp:
    "Note privilégie la note initiale de chaque torrent, sans bonus de durée de seed. À note égale, les téléchargements plus petits sont prioritaires. Zen/jour maximise les gains estimés.",
  planZeroHelp:
    "Un budget ou une taille maximum de 0 ne fixe aucune limite supplémentaire. L’espace disponible reste pris en compte dans le plan.",
  planReseedHelp:
    "Les correspondances complètes vérifiées de la bibliothèque sont incluses comme Reseeds avec une seule destination sans budget par client. Elles ne consomment pas de budget de téléchargement. Les limites de taille, de seeders et de nombre restent applicables.",
  planFolders: "Dossiers par catégorie…",
  buildPlan: "Créer un plan",
  planNow: "Arrêter la collecte et planifier maintenant",
  cachedPlan: "Utiliser le catalogue en cache sans actualiser",
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
  torrentName: "Torrent",
  torrentSize: "Taille",
  ascending: "Croissant",
  descending: "Décroissant",
  selectWholePlan: "Sélectionner tout le Plan",
  clearSelection: "Vider la sélection",
  previous: "Précédent",
  next: "Suivant",
  queuePlanDownloads: "Mettre les téléchargements sélectionnés en file",
  sendPlan: "Envoyer la sélection aux clients…",
  stopPlan: "Arrêter après le torrent en cours",
};
const $ = (id) => document.getElementById(id);
let language = "en";
const say = (en, fr) => (language === "fr" ? fr : en);
const num = (n) =>
  Number(n || 0).toLocaleString(language, { maximumFractionDigits: 2 });
function bytes(n) {
  const value = Number(n || 0);
  if (value < 1000) return `${value} B`;
  const index = Math.min(4, Math.floor(Math.log(value) / Math.log(1000)));
  return `${num(value / 1000 ** index)} ${["B", "KB", "MB", "GB", "TB"][index]}`;
}
function element(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function button(text, callback, cls) {
  const el = element("button", text, cls);
  el.type = "button";
  el.onclick = () => TLToast.press(el, async () => callback());
  return el;
}
const english = new Map();
function translate() {
  const info = $("plan-info");
  info.title = say("About Plan", "À propos du Plan");
  info.setAttribute("aria-label", info.title);
  document.documentElement.lang = language;
  for (const el of document.querySelectorAll("[data-i18n]")) {
    if (!english.has(el)) english.set(el, el.textContent);
    el.textContent =
      language === "fr"
        ? french[el.dataset.i18n] || english.get(el)
        : english.get(el);
  }
  for (const el of document.querySelectorAll("[data-en][data-fr]"))
    el.textContent = el.dataset[language];
  $("dialog")
    .querySelector(".close")
    .setAttribute("aria-label", say("Close", "Fermer"));
}
function table(
  target,
  rows,
  columns,
  selection = null,
  key = "hash",
  changed = () => {},
) {
  const host = $(target);
  host.replaceChildren();
  if (!rows.length) {
    host.append(
      element(
        "p",
        say("Nothing to display yet.", "Aucun élément à afficher."),
        "muted",
      ),
    );
    return;
  }
  const result = element("table"),
    head = element("thead"),
    header = element("tr"),
    body = element("tbody");
  if (selection) {
    const cell = element("th"),
      check = element("input");
    check.type = "checkbox";
    check.setAttribute(
      "aria-label",
      say("Select page", "Sélectionner la page"),
    );
    check.checked = rows.every((r) => selection.has(r[key]));
    check.onchange = () => {
      for (const row of rows)
        check.checked ? selection.add(row[key]) : selection.delete(row[key]);
      table(target, rows, columns, selection, key, changed);
      changed();
    };
    cell.append(check);
    header.append(cell);
  }
  for (const column of columns) header.append(element("th", column.label));
  head.append(header);
  for (const row of rows) {
    const line = element("tr");
    if (selection) {
      const cell = element("td"),
        check = element("input");
      check.type = "checkbox";
      check.setAttribute(
        "aria-label",
        say("Select ", "Sélectionner ") + row.title,
      );
      check.checked = selection.has(row[key]);
      check.onchange = () => {
        check.checked ? selection.add(row[key]) : selection.delete(row[key]);
        changed();
      };
      cell.append(check);
      line.append(cell);
    }
    for (const column of columns) {
      const cell = element("td"),
        value = column.render(row);
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? "";
      line.append(cell);
    }
    body.append(line);
  }
  result.append(head, body);
  host.append(result);
}
// An action started by a button keeps that button busy until it ends; any error becomes a toast.
async function guard(work, node) {
  node ??= TLToast.trigger();
  if (node) return TLToast.press(node, work);
  try {
    return await work();
  } catch (error) {
    TLToast.error(error);
  }
}

const frenchIssues = {
  catalogue_empty:
    "Le Catalogue est vide. Récupérez les catégories choisies, puis relancez le Plan.",
  category:
    "{count} torrents en cache sont hors des catégories choisies. Actualisez ces catégories ou élargissez la sélection.",
  unknown_category:
    "{count} torrents en cache n'ont pas de catégorie. Actualisez leurs métadonnées avant de préparer un Plan.",
  in_client:
    "{count} torrents sont déjà dans le client cible. Choisissez d'autres catégories ou actualisez le Catalogue pour trouver de nouveaux torrents.",
  no_seeders:
    "{count} torrents n'ont aucune source connue. Actualisez les catégories choisies pour mettre à jour les sources.",
  excluded_title:
    "{count} torrents correspondent à vos mots exclus. Vérifiez les exclusions du Plan dans les Paramètres.",
  no_folder:
    "{count} torrents n'ont pas de Dossier de téléchargement pour leur catégorie. Définissez ce dossier dans les Paramètres ou choisissez une catégorie qui en a un.",
  on_disk:
    "{count} torrents semblent déjà présents sur le disque. Recherchez-les dans la Bibliothèque pour les remettre en partage.",
  torrent_cap:
    "Votre plafond total de torrents est atteint. Augmentez-le dans Paramètres > Zen pour ajouter des torrents.",
  plan_cap:
    "La limite du Plan est de zéro torrent. Augmentez-la ou désactivez cette limite.",
  minimum_torrents:
    "Ce Plan contient moins que le minimum demandé de {count} torrents. Élargissez les filtres, augmentez l’espace disponible ou réduisez le nombre minimal.",
  filters:
    "{count} torrents ne respectent pas les filtres de taille ou de sources. Élargissez les filtres du Plan.",
  zen_class:
    "Votre Classe ne gagne pas de Zen en partageant des torrents. Choisissez une Classe rémunérée pour le partage dans Paramètres > Zen.",
  seed_hours:
    "Le temps de partage est réglé à zéro. Définissez le nombre d'heures par jour dans Paramètres > Zen.",
  no_gain:
    "Aucun candidat n'ajoute de Zen estimé avec ce profil. Vérifiez les paramètres Zen ou optimisez pour la Note.",
  disk_space:
    "{count} torrents dépassent l'espace disque utilisable après la réserve. Libérez de l'espace ou vérifiez la réserve dans les Paramètres.",
  download_limit:
    "{count} torrents dépassent la limite de téléchargement du Plan. Augmentez cette limite ou choisissez des torrents plus petits.",
  client_budget:
    "Aucun torrent ne respecte les budgets des clients choisis. Augmentez un budget ou choisissez des torrents plus petits.",
  no_candidates:
    "Aucun torrent admissible ne reste pour ce Plan. Vérifiez les catégories choisies et les filtres.",
};
function diagnostic(issue) {
  return language === "fr"
    ? (frenchIssues[issue.code] || issue.message).replaceAll(
        "{count}",
        num(issue.count),
      )
    : issue.message;
}
