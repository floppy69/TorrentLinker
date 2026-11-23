"use strict";
const $ = (id) => document.getElementById(id);
let language = "en";
const say = (en, fr) => (language === "fr" ? fr : en);
const num = (value) =>
  value == null
    ? "—"
    : Number(value).toLocaleString(language, { maximumFractionDigits: 2 });
const bytes = (value) =>
  value >= 1e9
    ? num(value / 1e9) + " GB"
    : value >= 1e6
      ? num(value / 1e6) + " MB"
      : value >= 1e3
        ? num(value / 1e3) + " kB"
        : num(value) + " B";
function element(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function button(text, action) {
  const node = element("button", text);
  node.type = "button";
  node.onclick = (event) => guard(action, event.currentTarget);
  return node;
}
// An action started by a button keeps that button busy until it ends.
async function guard(work, node) {
  node ??= TLToast.trigger();
  if (node) return TLToast.press(node, work);
  try {
    return await work();
  } catch (error) {
    TLToast.error(error);
  }
}
const labels = {
  expandAll: ["Expand categories", "Développer les catégories"],
  collapseAll: ["Collapse categories", "Réduire les catégories"],
  refresh: ["Refresh", "Actualiser"],
  seedingSort: ["Sort torrents by", "Trier les torrents par"],
  zenPerDay: ["≈ Zen/day", "≈ Zen/jour"],
  torrentName: ["Torrent", "Torrent"],
  torrentSize: ["Size", "Taille"],
  seedAge: ["Seed age (days)", "Âge du seed (jours)"],
  seedingOrder: ["Order", "Ordre"],
  descending: ["Descending", "Décroissant"],
  ascending: ["Ascending", "Croissant"],
  classComparison: ["Class comparison", "Comparaison des classes"],
  yourUploads: ["Your uploads", "Vos uploads"],
  saveComparison: ["Save comparison input", "Enregistrer le nombre d’uploads"],
};
function translate() {
  document.documentElement.lang = language;
  for (const node of document.querySelectorAll("[data-i18n]")) {
    const pair = labels[node.dataset.i18n];
    if (pair) node.textContent = say(...pair);
  }
  for (const node of document.querySelectorAll("[data-en]"))
    node.textContent = say(node.dataset.en, node.dataset.fr);
}
