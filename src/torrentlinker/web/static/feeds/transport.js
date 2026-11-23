"use strict";
const $ = (id) => document.getElementById(id);
let environment = {},
  generation = 0,
  commandId = 0,
  loaded = false;
const state = { clientId: "default", setup: {} };
const translations = new Map();
let currentLanguage = "en";
const say = (en, fr) => {
  translations.set(en, fr);
  return TLPanel.t(fr, en);
};
function translateOpenForm(language) {
  const french = language.startsWith("fr");
  const mapping = new Map(
    [...translations].map(([en, fr]) => (french ? [en, fr] : [fr, en])),
  );
  const walk = document.createTreeWalker($("dialog"), NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) {
    const node = walk.currentNode;
    if (
      !node.parentElement.closest("pre,input,textarea") &&
      mapping.has(node.textContent)
    )
      node.textContent = mapping.get(node.textContent);
  }
  $("dialog")
    .querySelectorAll("[aria-label],[title],[placeholder]")
    .forEach((node) => {
      for (const attr of ["aria-label", "title", "placeholder"])
        if (mapping.has(node.getAttribute(attr)))
          node.setAttribute(attr, mapping.get(node.getAttribute(attr)));
    });
}
window.feedsTransport = TLPanel.connect("feeds", { asynchronous: true });
async function request(path, body = {}) {
  const g = generation,
    send = await window.feedsTransport;
  const value = await send(path, { ...body, _client: environment.client });
  if (g !== generation)
    throw Error(say("The target client changed.", "Le client cible a changé."));
  return value;
}
const api = (path, body, method = body === undefined ? "GET" : "POST") =>
  request("api", { path, body, method });
function element(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function button(text, callback, cls) {
  const el = element("button", text, cls);
  el.type = "button";
  el.onclick = () => guard(callback, el);
  return el;
}
const toast = (text) => TLToast.show(text, "ok");
// An action started by a button keeps that button busy until it ends.
async function guard(fn, node) {
  node ??= TLToast.trigger();
  if (node) return TLToast.press(node, fn);
  try {
    return await fn();
  } catch (error) {
    TLToast.error(error);
  }
}
function bytes(n) {
  let i = 0;
  while (n >= 1024 && i < 4) {
    n /= 1024;
    i++;
  }
  return `${Number(n.toFixed(1))} ${["B", "KiB", "MiB", "GiB", "TiB"][i]}`;
}
function aIconButton(glyph, label, callback) {
  const b = button(glyph, callback, "icon-button");
  b.title = label;
  b.setAttribute("aria-label", label);
  return b;
}
function aMenu(anchor, items) {
  document.querySelectorAll(".assistant-menu").forEach((x) => x.remove());
  const menu = element("div", undefined, "assistant-menu");
  menu.setAttribute("role", "menu");
  for (const [label, action, disabled] of items) {
    const b = button(label, async () => {
      menu.remove();
      await action();
    });
    b.setAttribute("role", "menuitem");
    b.disabled = !!disabled;
    menu.append(b);
  }
  anchor.after(menu);
  menu.querySelector("button")?.focus();
  menu.onkeydown = (e) => {
    if (e.key === "Escape") {
      menu.remove();
      anchor.focus();
    }
  };
  setTimeout(
    () =>
      document.addEventListener("click", function close(e) {
        if (!menu.contains(e.target)) {
          menu.remove();
          document.removeEventListener("click", close);
        }
      }),
    0,
  );
}
function table(target, rows, columns, selection, key = "hash", onChange) {
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
    head = element("tr"),
    th = element("th"),
    all = element("input");
  all.type = "checkbox";
  all.setAttribute("aria-label", say("Select page", "Sélectionner la page"));
  all.checked = rows.every((r) => selection.has(r[key]));
  all.onchange = () => {
    rows.forEach((r) =>
      all.checked ? selection.add(r[key]) : selection.delete(r[key]),
    );
    table(target, rows, columns, selection, key, onChange);
    onChange();
  };
  th.append(all);
  head.append(th);
  columns.forEach((c) => head.append(element("th", c.label)));
  const h = element("thead");
  h.append(head);
  t.append(h);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr"),
      td = element("td"),
      box = element("input");
    box.type = "checkbox";
    box.setAttribute("aria-label", row.title);
    box.checked = selection.has(row[key]);
    box.onchange = () => {
      box.checked ? selection.add(row[key]) : selection.delete(row[key]);
      onChange();
    };
    td.append(box);
    tr.append(td);
    for (const c of columns) {
      const cell = element("td"),
        value = c.render(row);
      value instanceof Node
        ? cell.append(value)
        : (cell.textContent = value ?? "—");
      tr.append(cell);
    }
    body.append(tr);
  }
  t.append(body);
  host.append(t);
}
const details = (row) => request("details", { row });
const navigate = () => loadFeeds();
window.addEventListener("feeds-environment", (e) =>
  guard(async () => {
    const next = e.detail,
      changed = environment.client !== next.client;
    if (changed) {
      generation++;
      loaded = false;
      $("dialog").close();
    }
    environment = next;
    state.clientId = next.client;
    const languageChanged = currentLanguage !== next.language;
    currentLanguage = next.language || "en";
    TLPanel.setLanguage(currentLanguage);
    document.documentElement.dataset.theme = next.theme || "dark";
    if (languageChanged && $("dialog").open) translateOpenForm(currentLanguage);
    if (!next.active) return;
    if (!loaded || languageChanged) {
      const options = await api("feed-options");
      state.setup.indexer_categories = options.categories || {};
      await loadFeeds();
      loaded = true;
    }
    if (next.command && next.command.id !== commandId) {
      commandId = next.command.id;
      if (next.command.action === "edit")
        await editFeed(null, next.command.query || "");
      if (next.command.action === "queue")
        await feedEnqueue(next.command.hashes || []);
    }
  }),
);
window.addEventListener("DOMContentLoaded", () => {
  $("dialog").querySelector(".close").onclick = () => $("dialog").close();
  window.feedsTransport.then(() => window.feedsReady());
  setInterval(() => {
    if (environment.active && !$("dialog").open) guard(() => loadFeeds());
  }, 30000);
});
