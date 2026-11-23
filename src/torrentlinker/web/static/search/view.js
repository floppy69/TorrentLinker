"use strict";
const $ = (id) => document.getElementById(id);
let language = "en",
  env = {},
  generation = 0,
  activePage = "search";
const state = {
  searchSelected: new Set(),
  queueSelected: new Set(),
  queueRows: [],
};
const say = (en, fr) => (language === "fr" ? fr : en);
function element(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function button(text, callback, cls) {
  const node = element("button", text, cls);
  node.type = "button";
  node.onclick = () =>
    TLToast.busy(node, async () => {
      await callback();
    });
  return node;
}
const toast = (text) => TLToast.show(text, "ok");
// An action started by a button keeps that button busy until it ends.
async function guard(fn, node) {
  node ??= TLToast.trigger();
  if (node) return TLToast.press(node, fn);
  try {
    return await fn();
  } catch (e) {
    TLToast.error(e);
  }
}
async function request(action, body = {}) {
  const g = generation;
  const send = await window.searchTransport;
  const value = await send(action, { ...body, _client: env.client });
  if (g !== generation)
    throw Error(say("The target client changed.", "Le client cible a changé."));
  return value;
}
async function job(body, done) {
  const g = generation;
  const { job: id } = await request("job", body);
  for (;;) {
    const result = await request("job-status", { job: id });
    if (g !== generation) return;
    if (!["queued", "running"].includes(result.status)) {
      if (result.status !== "completed")
        throw Error(result.error || result.status);
      if (done) done(result.result);
      return result.result;
    }
    await new Promise((r) => setTimeout(r, 150));
  }
}
async function api() {
  const value = await request("state", {
    hashes: SS.rows.map((row) => row.hash),
  });
  refreshScoreProfiles(value);
  await refreshDetailScores(value);
  let changed = false;
  for (const fresh of value.search || []) {
    const row = SS.rows.find((row) => row.hash === fresh.hash);
    if (
      row &&
      (JSON.stringify(row.release_score) !==
        JSON.stringify(fresh.release_score) ||
        row.zen !== fresh.zen ||
        row.note !== fresh.note ||
        (SS.known[row.hash] || "") !== fresh.known)
    ) {
      row.release_score = fresh.release_score;
      row.zen = fresh.zen;
      row.note = fresh.note;
      SS.known[row.hash] = fresh.known;
      changed = true;
    }
  }
  if (changed) {
    const y = scrollY;
    renderResults();
    scrollTo(0, y);
  }
  return value.rows;
}
const details = (row) => openDetail(row);
async function navigate(page) {
  if (page === "details" && selectedDetail) {
    selectDetail(selectedDetail);
    return;
  }
  activePage = page;
  $("detail-pages").hidden = true;
  renderDetailTabs();
  $("results").hidden = page !== "search";
  $("queue").hidden = page !== "queue";
  hideHover();
  if (page === "queue") await loadQueue();
  else await loadSearchPage();
}
function translate() {
  document.documentElement.lang = language;
  document
    .querySelectorAll("[data-en]")
    .forEach((n) => (n.textContent = n.dataset[language] || n.dataset.en));
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
function table(
  target,
  rows,
  columns,
  selection,
  key = "hash",
  onChange,
  onRow,
) {
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
    cell.textContent = column.label;
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
