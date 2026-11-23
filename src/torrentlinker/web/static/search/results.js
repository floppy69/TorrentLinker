/* Search: category pills, filter row, sort chips, numbered pages and rich result rows.
   Both desktop and Web load this bundled panel. */
const SS = {
  loaded: false,
  loading: null,
  searched: false,
  native: false,
  adultNote: false,
  category: "",
  categories: {},
  colors: {},
  rootCounts: {},
  facetDefs: [],
  chosen: new Map(),
  inputs: { year: "", team: "", uploader: "" },
  exclusive: false,
  palliative: "",
  palliativeCount: null,
  crew: false,
  sort: { key: "createdAt", order: "desc" },
  page: 1,
  pages: 1,
  total: 0,
  totalSize: null,
  rows: [],
  listing: {},
  known: {},
  timer: null,
  density: "comfortable",
  posters: true,
};
const FALLBACK_COLORS = [
  "#3b82f6",
  "#f59e0b",
  "#a855f7",
  "#6366f1",
  "#10b981",
  "#8b5cf6",
  "#ef4444",
];
const TAG_KINDS = ["lang", "resolution", "source", "audio", "codec", "hdr"];
const VIDEO_LABELS = () => ({
  resolution: say("Resolution", "Résolution"),
  source: "Source",
  codec: "Codec",
  hdr: "HDR",
  audioType: "Audio",
  channels: say("Channels", "Canaux"),
  lang: say("Language", "Langue"),
  profile: say("Profile", "Profil"),
});
const PROFILE_LABELS = () => ({
  compatibility: say("Compatibility", "Compatibilité"),
  pure: say("Home Cinema Pure", "Home Cinéma Pure"),
  hc_optimized: say("Home Cinema Optimized", "Home Cinéma Optimisé"),
  optimization: say("Optimization", "Optimisation"),
});
const SORTS = () => [
  ["createdAt", say("Age", "Âge")],
  ["seeders", "Seeders"],
  ["leechers", "Leechers"],
  ["size", say("Size", "Taille")],
  ["completions", say("Completed", "Complétés")],
  ["comments", say("Comments", "Commentaires")],
  ["name", say("Name", "Nom")],
  ["category", "Type"],
  ["relevance", say("Relevance", "Pertinence")],
];

let preferences = null,
  preferencesReady = null;
function searchStore(key, value) {
  if (!preferences) return null;
  if (value === undefined) return preferences[key];
  if (preferences[key] === value) return;
  preferences[key] = value;
  guard(() => request("preferences", { [key]: value }));
}
const searchRoot = (id) => {
  let node = String(id || "");
  const seen = new Set();
  while (
    node &&
    SS.categories[node] &&
    SS.categories[node].parent != null &&
    !seen.has(node)
  ) {
    seen.add(node);
    node = String(SS.categories[node].parent);
  }
  return node;
};
const searchRoots = () =>
  Object.entries(SS.categories).filter(
    ([, c]) => c.parent == null || !SS.categories[c.parent],
  );
const searchColor = (rootId, index = 0) =>
  SS.colors[rootId] || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
const searchQuery = () => $("search-query").value.trim();
const searchNumber = (n) =>
  Number(n).toLocaleString(language === "fr" ? "fr-FR" : "en-US");

/* The page numbers to link: the ends, the neighbours of the current page, and the first or
   last three near an end. A single hidden page is shown rather than an ellipsis. */
function pageNumbers(current, total) {
  if (total < 1) return [];
  current = Math.min(Math.max(1, current), total);
  const wanted = new Set([1, total, current - 1, current, current + 1]);
  if (current <= 3) [1, 2, 3].forEach((n) => wanted.add(n));
  if (current >= total - 2)
    [total - 2, total - 1, total].forEach((n) => wanted.add(n));
  const pages = [...wanted]
    .filter((n) => n >= 1 && n <= total)
    .sort((a, b) => a - b);
  const result = [];
  for (const n of pages) {
    const last = result[result.length - 1];
    if (last !== undefined && last !== null) {
      if (n - last === 2) result.push(last + 1);
      else if (n - last > 2) result.push(null);
    }
    result.push(n);
  }
  return result;
}

function chipButton(text, pressed, callback, cls = "chip") {
  const b = button(text, callback, cls);
  b.setAttribute("aria-pressed", String(!!pressed));
  return b;
}

/* ---- filter dropdowns ------------------------------------------------------------ */
function dropdown(label) {
  const d = element("details", undefined, "fdrop");
  const summary = element("summary", label, "chip");
  const panel = element("div", undefined, "fdrop-panel");
  d.append(summary, panel);
  d.setLabel = (count, text = "") => {
    summary.textContent = label + (count ? ` · ${text || count}` : "");
    summary.classList.toggle("active", !!count);
  };
  d.panel = panel;
  return d;
}
document.addEventListener("click", (event) => {
  document.querySelectorAll(".fdrop[open]").forEach((d) => {
    if (!d.contains(event.target)) d.open = false;
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape")
    document.querySelectorAll(".fdrop[open]").forEach((d) => (d.open = false));
});

function checklist(def) {
  const d = dropdown(def.label);
  const chosen = () => SS.chosen.get(def.key) || new Set();
  const find = element("input");
  find.type = "search";
  find.placeholder = say("Filter choices…", "Filtrer les choix…");
  find.setAttribute("aria-label", find.placeholder);
  const list = element("div", undefined, "fdrop-list");
  const boxes = [];
  for (const [text, value] of def.choices) {
    const row = element("label", undefined, "fdrop-item");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = chosen().has(value);
    box.onchange = () => {
      const set = new Set(chosen());
      box.checked ? set.add(value) : set.delete(value);
      set.size ? SS.chosen.set(def.key, set) : SS.chosen.delete(def.key);
      criteriaChanged();
    };
    boxes.push([box, value]);
    row.append(box, element("span", text));
    row.dataset.text = text.toLowerCase();
    list.append(row);
  }
  find.oninput = () =>
    list
      .querySelectorAll(".fdrop-item")
      .forEach(
        (row) =>
          (row.hidden = !row.dataset.text.includes(find.value.toLowerCase())),
      );
  const clear = button(
    say("Clear", "Effacer"),
    () => {
      SS.chosen.delete(def.key);
      criteriaChanged();
    },
    "quiet",
  );
  d.panel.append(find, list, clear);
  d.sync = () => {
    const set = chosen();
    boxes.forEach(([box, value]) => (box.checked = set.has(value)));
    d.setLabel(set.size);
    d.title = [...set]
      .map((v) => def.choices.find((c) => c[1] === v)?.[0] || v)
      .join(", ");
  };
  d.sync();
  return d;
}

function inputFilter(key, label, placeholder, attrs = {}) {
  const d = dropdown(label);
  const input = element("input");
  input.placeholder = placeholder;
  input.setAttribute("aria-label", label);
  Object.entries(attrs).forEach(([k, v]) => input.setAttribute(k, v));
  input.value = SS.inputs[key];
  input.oninput = () => {
    SS.inputs[key] = input.value.trim();
    criteriaChanged();
  };
  input.onkeydown = (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      d.open = false;
    }
  };
  const clear = button(
    say("Clear", "Effacer"),
    () => {
      input.value = "";
      SS.inputs[key] = "";
      criteriaChanged();
    },
    "quiet",
  );
  d.panel.append(input, clear);
  d.sync = () => {
    input.value = SS.inputs[key];
    d.setLabel(!!SS.inputs[key], SS.inputs[key]);
    d.title = SS.inputs[key] || label;
  };
  d.sync();
  return d;
}

function renderFacets() {
  const host = $("search-facets");
  host.replaceChildren();
  if (!SS.native) return;
  if (SS.adultNote) {
    // XXX through Torznab: c411's own filters need the signed-in companion.
    host.append(
      element("p", say("Connect the extension for XXX filters", "Connectez l'extension pour les filtres XXX"), "muted"),
    );
    return;
  }
  SS.facetDefs.forEach((def) => host.append(checklist(def)));
  host.append(
    inputFilter("year", say("Year", "Année"), say("Year", "Année"), {
      type: "number",
      min: 1900,
      max: 2100,
    }),
    inputFilter(
      "team",
      "Team",
      say("Team name or slug", "Nom ou slug de la team"),
    ),
    inputFilter("uploader", "Uploader", "Uploader", { maxlength: 100 }),
  );
}

function renderChosen() {
  const host = $("search-chosen");
  const chips = [];
  for (const def of SS.facetDefs)
    for (const value of SS.chosen.get(def.key) || []) {
      const text = def.choices.find((c) => c[1] === value)?.[0] || value;
      chips.push(
        button(
          `${def.label}: ${text}  ✕`,
          () => {
            const set = new Set(SS.chosen.get(def.key));
            set.delete(value);
            set.size ? SS.chosen.set(def.key, set) : SS.chosen.delete(def.key);
            criteriaChanged();
          },
          "chip pill",
        ),
      );
    }
  host.replaceChildren(...chips);
  chips.forEach(
    (c) => (c.title = say("Remove this filter", "Retirer ce filtre")),
  );
  host.hidden = chips.length < 4;
}

function syncToggles() {
  const native = SS.native;
  const root = searchRoot(SS.category);
  $("search-exclusive").hidden = !native;
  $("search-palliative").hidden = !native;
  $("search-crew").hidden = !(native && root === "1");
  if (!(native && root === "1")) SS.crew = false;
  $("search-exclusive").setAttribute("aria-pressed", String(SS.exclusive));
  $("search-exclusive").textContent = "☆ " + say("Exclusive", "Exclusivités");
  $("search-crew").setAttribute("aria-pressed", String(SS.crew));
  const count = SS.palliativeCount !== null ? ` · ${SS.palliativeCount}` : "";
  const states = [
    [
      "♡ Soins palliatifs" + count,
      say(
        "Click to include soins palliatifs torrents in the results.",
        "Cliquez pour inclure les torrents en soins palliatifs dans les résultats.",
      ),
    ],
    [
      say("♥ With soins palliatifs", "♥ Avec soins palliatifs"),
      say(
        "Soins palliatifs are included. Click to show only those.",
        "Les soins palliatifs sont inclus. Cliquez pour ne voir qu’eux.",
      ),
    ],
    [
      say("♥ Soins palliatifs only", "♥ Soins palliatifs seuls"),
      say(
        "Only soins palliatifs. Click to hide them again.",
        "Soins palliatifs seulement. Cliquez pour les masquer à nouveau.",
      ),
    ],
  ];
  const index = ["", "include", "only"].indexOf(SS.palliative);
  $("search-palliative").textContent = states[index][0];
  $("search-palliative").title = states[index][1];
  $("search-palliative").setAttribute("aria-pressed", String(index > 0));
}

/* ---- pills, sort, pages ---------------------------------------------------------- */
function renderPills() {
  const roots = searchRoots();
  const host = $("search-pills");
  host.hidden = !roots.length;
  const counts = SS.rootCounts;
  const shown = Object.keys(counts).length;
  const total = roots.reduce((n, [id]) => n + (counts[id] || 0), 0);
  const current = searchRoot(SS.category);
  const pill = (id, name, count, color) => {
    const b = chipButton(
      "",
      id === current,
      () => pickCategory(id),
      "chip pill",
    );
    const dot = element("span", undefined, "dot");
    dot.style.background = color;
    b.append(dot, element("span", name));
    if (shown) b.append(element("span", searchNumber(count), "pill-count"));
    return b;
  };
  host.replaceChildren(
    pill("", say("All", "Tout"), total, "#3b82f6"),
    ...roots.map(([id, c], i) =>
      pill(id, c.name, counts[id] || 0, searchColor(id, i + 1)),
    ),
  );
}

// Nothing to subscribe to without a query, nothing to clear while the filters are untouched.
function renderActions() {
  $("subscribe-search").disabled = !searchQuery();
  $("search-clear").disabled = !(
    SS.chosen.size ||
    Object.values(SS.inputs).some(Boolean) ||
    SS.exclusive ||
    SS.palliative ||
    SS.crew ||
    SS.category ||
    SS.sort.key !== "createdAt" ||
    SS.sort.order !== "desc"
  );
}

function renderSort() {
  const host = $("search-sort");
  host.hidden = !SS.native;
  host.closest(".results-sort").hidden = !SS.native;
  renderActions();
  host.replaceChildren(
    ...SORTS()
      .filter(([key]) => key !== "relevance" || searchQuery())
      .map(([key, label]) => {
        const active = SS.sort.key === key;
        return chipButton(
          label + (active ? (SS.sort.order === "desc" ? " ↓" : " ↑") : ""),
          active,
          () => {
            if (active)
              SS.sort.order = SS.sort.order === "desc" ? "asc" : "desc";
            else SS.sort = { key, order: key === "name" ? "asc" : "desc" };
            renderSort();
            if (SS.searched) return runSearch(1);
          },
          "chip sort",
        );
      }),
  );
}

function renderPages() {
  for (const id of ["search-pages-top", "search-pages-bottom"]) {
    const host = $(id);
    host.hidden = !SS.rows.length && SS.page <= 1;
    const go = (n) => () => runSearch(n);
    const parts = [];
    if (SS.page > 1)
      parts.push(
        button(say("← Previous", "← Précédent"), go(SS.page - 1), "chip page"),
      );
    for (const n of pageNumbers(SS.page, SS.pages)) {
      if (n === null) parts.push(element("span", "…", "muted"));
      else {
        const b = chipButton(String(n), n === SS.page, go(n), "chip page");
        b.setAttribute("aria-label", say(`Page ${n}`, `Page ${n}`));
        if (n === SS.page) b.setAttribute("aria-current", "page");
        parts.push(b);
      }
    }
    if (SS.page < SS.pages)
      parts.push(
        button(say("Next →", "Suivant →"), go(SS.page + 1), "chip page"),
      );
    if (SS.page < SS.pages - 1)
      parts.push(
        button(say("Last »", "Dernière »"), go(SS.pages), "chip page"),
      );
    host.replaceChildren(...parts);
  }
}

/* ---- rows ------------------------------------------------------------------------ */
function rootColorByName(label) {
  const first = (label || "").split(" / ")[0];
  const roots = searchRoots();
  const index = roots.findIndex(([, c]) => c.name === first);
  return index < 0 ? "#64748b" : searchColor(roots[index][0], index + 1);
}
function markChip(hash) {
  const kind = SS.known[hash];
  if (!kind) return null;
  return element(
    "span",
    "● " +
      (kind === "client"
        ? say("In client", "Dans le client")
        : say("Queued", "En file")),
    "tag mark-" + kind,
  );
}
function downloadButton(row) {
  const b = element("button", undefined, "dl-button");
  b.type = "button";
  b.title = say(
    "Add to the download queue",
    "Ajouter à la file de téléchargement",
  );
  b.setAttribute("aria-label", b.title);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "18");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M12 4v10m0 0l-4-4m4 4l4-4M5 19h14");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  b.append(svg);
  b.onclick = (event) => {
    event.stopPropagation();
    guard(() => searchEnqueue([row.hash]));
  };
  return b;
}
function cover(row, info) {
  const box = element("div", undefined, "cover");
  const label = (row.native_category_label || "?").split(" / ").pop();
  const fallback = element(
    "span",
    label.slice(0, 2).toUpperCase(),
    "cover-letters",
  );
  const color = rootColorByName(row.native_category_label);
  box.style.setProperty("--cover", color);
  box.append(fallback);
  if (SS.posters && info && info.poster_url) {
    const img = element("img");
    img.loading = "lazy";
    img.alt = "";
    loadPoster(img, info.poster_url);
    img.onload = () => fallback.remove();
    img.onerror = () => img.remove();
    box.append(img);
  }
  return box;
}
function richRow(row) {
  const info = SS.listing[row.hash];
  const el = element("div", undefined, "sr-row");
  const check = document.createElement("input");
  check.type = "checkbox";
  check.checked = state.searchSelected.has(row.hash);
  check.setAttribute("aria-label", row.title);
  check.onchange = () => {
    check.checked
      ? state.searchSelected.add(row.hash)
      : state.searchSelected.delete(row.hash);
    el.classList.toggle("selected", check.checked);
    syncSelection();
  };
  el.classList.toggle("selected", check.checked);
  const main = element("div", undefined, "sr-main");
  const line1 = element("div", undefined, "sr-line");
  const badge = (row.native_category_label || "").split(" / ").pop();
  if (badge) {
    const b = element("span", badge, "tag kind");
    b.style.setProperty("--tag", rootColorByName(row.native_category_label));
    line1.append(b);
  }
  const title = button(
    info?.title || row.title,
    () => details(row),
    "sr-title link",
  );
  if (!info) title.title = row.title; // with details, the hover card replaces the tooltip
  line1.append(title, releaseScorePill(row));
  if (info?.year) line1.append(element("span", String(info.year), "muted"));
  if (info?.rating)
    line1.append(element("span", `★ ${info.rating.toFixed(1)}`, "tag rating"));
  if (row.revival) line1.append(element("span", "♥", "mark-revival"));
  if (info?.exclusive) line1.append(element("span", "★", "mark-exclusive"));
  const mark = markChip(row.hash);
  if (mark) line1.append(element("span", undefined, "spacer"), mark);
  const release = element("div", row.title, "sr-release");
  const tags = element("div", undefined, "sr-line");
  for (const [kind, text] of info?.tags || []) {
    const t = element("span", text, "tag tag-" + kind);
    tags.append(t);
  }
  main.append(line1, release, tags);
  const stats = element("div", undefined, "sr-stats");
  const leech = info?.leechers ?? 0;
  const bar = element("div", undefined, "seedbar");
  const total = row.seeders + leech;
  bar.style.setProperty(
    "--seeds",
    total ? `${Math.round((100 * row.seeders) / total)}%` : "0%",
  );
  bar.classList.toggle("no-peers", !total);
  stats.append(
    element("strong", bytes(row.size), "sr-size"),
    element("span", undefined, "sr-peers"),
    bar,
  );
  stats
    .querySelector(".sr-peers")
    .append(
      element("span", `↑ ${row.seeders}`, "up"),
      element("span", `↓ ${leech}`, "down"),
    );
  const when = element("div", undefined, "sr-age");
  when.append(element("span", age(row.published_at)));
  if (info) {
    when.append(
      element(
        "span",
        say(`${info.completions} compl.`, `${info.completions} compl.`),
        "muted",
      ),
    );
    if (info.uploader)
      when.append(element("span", info.uploader, "muted sr-uploader"));
  }
  const zen = element("div", undefined, "sr-zen");
  if (row.zen !== null && row.zen !== undefined) {
    const z = element(
      "span",
      `≈ ${num(row.zen)} Zen/${say("day", "j")}`,
      "tag tag-zen",
    );
    z.title =
      say(
        "Estimated Zen per day once seeding. Note: ",
        "Zen estimé par jour une fois en partage. Note : ",
      ) + num(row.note);
    zen.append(z);
  }
  if (row.note !== null && row.note !== undefined) {
    zen.append(element("small", `≈ ${num(row.note)} Note`, "muted"));
  }
  el.append(
    check,
    cover(row, info),
    main,
    stats,
    when,
    zen,
    downloadButton(row),
  );
  return el;
}

const COMPACT_SORTS = {
  type: "category",
  name: "name",
  comments: "comments",
  age: "createdAt",
  size: "size",
  done: "completions",
  seeds: "seeders",
  leech: "leechers",
};
function compactColumns() {
  const num0 = (v, cls) =>
    element(
      "span",
      v === null || v === undefined ? "—" : String(v),
      v ? cls : "muted",
    );
  return [
    {
      label: say("Type", "Type"),
      sortKey: "type",
      render: (r) => {
        const badge = element(
          "span",
          (
            (r.native_category_label || "").split(" / ").pop() || "?"
          ).toUpperCase(),
          "type-badge",
        );
        badge.style.setProperty(
          "--tag",
          rootColorByName(r.native_category_label),
        );
        return badge;
      },
    },
    {
      label: say("Name", "Nom"),
      sortKey: "name",
      name: true,
      render: (r) => {
        const info = SS.listing[r.hash];
        const wrap = element("div", undefined, "compact-name");
        const line = element("div", undefined, "sr-line");
        line.append(
          button(r.title, () => details(r), "link sr-release"),
          releaseScorePill(r),
        );
        const mark = markChip(r.hash);
        if (mark) line.append(element("span", undefined, "spacer"), mark);
        const tags = element("div", undefined, "sr-line");
        if (info?.exclusive)
          tags.append(
            element("span", say("EXCLU", "EXCLU"), "tag kind-exclusive"),
          );
        if (r.revival) tags.append(element("span", "♥", "mark-revival"));
        if (info?.language)
          tags.append(element("span", info.language, "tag tag-lang"));
        if (info?.quality)
          tags.append(element("span", info.quality, "tag tag-hdr"));
        wrap.append(line, tags);
        return wrap;
      },
    },
    {
      label: say("Comm.", "Comm."),
      sortKey: "comments",
      render: (r) => num0(SS.listing[r.hash]?.comments, ""),
    },
    {
      label: say("Age", "Âge"),
      sortKey: "age",
      render: (r) => age(r.published_at),
    },
    {
      label: say("Size", "Taille"),
      sortKey: "size",
      render: (r) => bytes(r.size),
    },
    {
      label: say("Done", "Compl."),
      sortKey: "done",
      render: (r) => num0(SS.listing[r.hash]?.completions, ""),
    },
    {
      label: "Seeders",
      sortKey: "seeds",
      render: (r) => num0(r.seeders, "up"),
    },
    {
      label: "Leechers",
      sortKey: "leech",
      render: (r) => num0(SS.listing[r.hash]?.leechers, "down"),
    },
    { label: "≈ Zen / j", render: (r) => num(r.zen) },
    { label: "≈ Note", render: (r) => num(r.note) },
    { label: "", render: (r) => downloadButton(r) },
  ];
}

function renderResults() {
  const host = $("search-table");
  host.classList.toggle("compact", SS.density === "compact");
  if (!SS.rows.length) {
    host.replaceChildren(
      element(
        "p",
        SS.searched
          ? say(
              "No torrent matches. Try fewer filters, or another spelling of the title.",
              "Aucun torrent ne correspond. Essayez moins de filtres, ou une autre orthographe du titre.",
            )
          : say(
              "Search for torrents, then select the ones to download.",
              "Cherchez des torrents, puis sélectionnez ceux à télécharger.",
            ),
        "empty",
      ),
    );
  } else if (SS.density === "compact") {
    table(
      "search-table",
      SS.rows,
      compactColumns(),
      state.searchSelected,
      "hash",
      syncSelection,
    );
    // A header sorts the whole search, as on c411, instead of only this page.
    const heads = [...$("search-table").querySelectorAll("thead th")].slice(1);
    compactColumns().forEach((column, index) => {
      const key = COMPACT_SORTS[column.sortKey];
      if (!key || !SS.native) return;
      const active = SS.sort.key === key;
      const b = button(
        column.label + (active ? (SS.sort.order === "desc" ? " ↓" : " ↑") : ""),
        () => {
          if (active) SS.sort.order = SS.sort.order === "desc" ? "asc" : "desc";
          else SS.sort = { key, order: key === "name" ? "asc" : "desc" };
          renderSort();
          return runSearch(1);
        },
        "quiet header-sort",
      );
      heads[index].replaceChildren(b);
    });
  } else {
    host.replaceChildren(...SS.rows.map(richRow));
  }
  renderPages();
  syncSelection();
}

function syncSelection() {
  const count = state.searchSelected.size;
  $("search-selection").hidden = !count;
  $("search-selected-count").textContent = say(
    `${count} selected`,
    `${count} sélectionné(s)`,
  );
  $("search-details").hidden = !count;
}

/* ---- the search itself ---------------------------------------------------------- */
function searchFilters() {
  const filters = {};
  if (!SS.native) return filters;
  const options = [];
  for (const def of SS.facetDefs) {
    const values = [...(SS.chosen.get(def.key) || [])];
    if (!values.length) continue;
    if (def.kind === "option") options.push(...values);
    else filters[def.param] = values.join(",");
  }
  if (options.length) filters.options = options.join(",");
  for (const key of ["year", "team", "uploader"])
    if (SS.inputs[key]) filters[key] = SS.inputs[key];
  if (SS.exclusive) filters.exclusive = "true";
  if (SS.palliative) filters.palliative = SS.palliative;
  if (SS.crew && searchRoot(SS.category) === "1" && searchQuery())
    filters.crew = "true";
  filters.sortBy =
    SS.sort.key === "relevance" && !searchQuery() ? "createdAt" : SS.sort.key;
  filters.sortOrder = SS.sort.order;
  return filters;
}

function yearAcceptable() {
  return (
    !SS.inputs.year ||
    (/^\d{4}$/.test(SS.inputs.year) &&
      +SS.inputs.year >= 1900 &&
      +SS.inputs.year <= 2100)
  );
}

function runSearch(page = 1) {
  if (!yearAcceptable())
    throw Error(
      say(
        "Enter a year between 1900 and 2100.",
        "Saisissez une année entre 1900 et 2100.",
      ),
    );
  $("search-status").textContent = say("Searching…", "Recherche…");
  return job(
    {
      kind: "search",
      query: $("search-query").value,
      page,
      category: Number(SS.category) || null,
      filters: searchFilters(),
      search_listing: true,
    },
    (r) => {
      SS.searched = true;
      SS.page = r.page;
      SS.pages = Math.max(1, r.pages);
      SS.total = r.total;
      SS.totalSize = r.total_size;
      SS.rows = r.rows;
      SS.listing = r.listing || {};
      SS.known = r.known || {};
      if (r.root_counts && Object.keys(r.root_counts).length)
        SS.rootCounts = r.root_counts;
      SS.palliativeCount = r.palliative_count ?? SS.palliativeCount;
      state.searchSelected.clear();
      let summary =
        r.total === null || r.total === undefined
          ? ""
          : say(
              `${searchNumber(r.total)} torrents`,
              `${searchNumber(r.total)} torrents`,
            );
      if (SS.totalSize) summary += (summary ? " · " : "") + bytes(SS.totalSize);
      $("search-summary").textContent = summary;
      $("search-status").textContent = r.window_limited
        ? say(
            `c411 limits this search to ${r.per_page * r.pages} accessible results. Narrow your filters.`,
            `c411 limite cette recherche à ${r.per_page * r.pages} résultats accessibles. Affinez vos filtres.`,
          )
        : "";
      renderPills();
      syncToggles();
      renderSort();
      renderResults();
      refreshQueueCount();
    },
  );
}

/* Queueing stays on the Search page; the row shows a Queued mark and the header count rises. */
async function searchEnqueue(hashes, now = false) {
  if (!hashes.length)
    throw Error(say("Select torrents first.", "Sélectionnez des torrents."));
  if (!(await configureFolders(hashes))) return;
  await job({ kind: "enqueue", hashes }, () => {
    toast(
      say("Added to download queue.", "Ajouté à la file de téléchargement."),
    );
    hashes.forEach((h) => {
      if (!SS.known[h]) SS.known[h] = "queued";
    });
    state.searchSelected.clear();
    renderResults();
    refreshQueueCount();
  });
  if (now) {
    const rows = (await request("state")).rows.filter(
      (r) => hashes.includes(r.hash) && r.status === "queued",
    );
    if (rows.length) await request("start", { keys: rows.map((r) => r.key) });
    await request("navigate", { page: "queue" });
  }
}

function schedule() {
  clearTimeout(SS.timer);
  SS.timer = setTimeout(() => {
    if (!yearAcceptable()) return; // a half-typed year is not a search yet
    guard(() => runSearch(1));
  }, 700);
}

function criteriaChanged() {
  document
    .querySelectorAll("#search-facets .fdrop")
    .forEach((d) => d.sync && d.sync());
  renderChosen();
  syncToggles();
  renderActions();
  schedule();
}

function loadSearchOptions(then) {
  return job(
    { kind: "search-options", category: Number(SS.category) || null },
    (r) => {
      SS.native = r.backend === "c411-native";
      SS.categories = r.categories || {};
      SS.colors = r.root_colors || {};
      SS.adultNote = r.adult_filters === "extension";
      const labels = VIDEO_LABELS();
      const defs = [];
      for (const [name, values] of Object.entries(r.video_filters || {}))
        defs.push({
          key: "v:" + name,
          kind: "video",
          param: name,
          label: labels[name] || name,
          choices: values.map((v) => [
            name === "profile" ? PROFILE_LABELS()[v] || v : v,
            v,
          ]),
        });
      for (const f of r.facets || [])
        defs.push({
          key: "o:" + f.slug,
          kind: "option",
          label: f.label,
          choices: f.choices,
        });
      SS.facetDefs = defs;
      const keep = new Set(defs.map((d) => d.key));
      for (const key of [...SS.chosen.keys()])
        if (!keep.has(key)) SS.chosen.delete(key);
      fillCategorySelect();
      renderPills();
      renderFacets();
      renderChosen();
      syncToggles();
      renderSort();
      SS.loaded = true;
      if (then) then();
    },
  );
}

/* The pills pick the root; this select only narrows to one of its sub-categories. */
function fillCategorySelect() {
  const select = $("search-category");
  const root = searchRoot(SS.category);
  const children = root
    ? Object.entries(SS.categories).filter(([, v]) => String(v.parent) === root)
    : [];
  select.hidden = !children.length;
  select.ariaLabel = say("Sub-category", "Sous-catégorie");
  select.replaceChildren(
    new Option(say("All sub-categories", "Toutes les sous-catégories"), root),
    ...children.map(([child, v]) => new Option(v.name, child)),
  );
  select.value = SS.category;
}

function pickCategory(id) {
  const rootChanged = searchRoot(id) !== searchRoot(SS.category);
  SS.category = id;
  if (rootChanged) SS.chosen.clear();
  loadSearchOptions(() => guard(() => runSearch(1)));
}

async function refreshQueueCount() {
  try {
    const rows = await api("queue");
    const queued = rows.length;
    $("search-queue-link").textContent = say(
      `Download queue (${queued})`,
      `File de téléchargement (${queued})`,
    );
  } catch {
    /* The count is a convenience. */
  }
}

function setDensity(density) {
  SS.density = density;
  searchStore("tl-search-density", density);
  $("search-density-compact").setAttribute(
    "aria-pressed",
    String(density === "compact"),
  );
  $("search-density-comfortable").setAttribute(
    "aria-pressed",
    String(density === "comfortable"),
  );
  renderResults();
}
function setPosters(on) {
  SS.posters = on;
  searchStore("tl-search-posters", on ? "1" : "0");
  $("search-posters").setAttribute("aria-pressed", String(on));
  $("search-posters").title = say(
    "Show posters. They are fetched from TMDB by this server, a few at a time, and kept on disk.",
    "Affiche les affiches. Ce serveur les récupère sur TMDB, quelques-unes à la fois, et les garde sur disque.",
  );
  if (SS.rows.length) renderResults();
}

function searchRetranslate() {
  $("search-query").placeholder = say(
    "Title, original title, release name…",
    "Titre, titre original, nom de release…",
  );
  setPosters(SS.posters);
  if (SS.loaded) {
    fillCategorySelect();
    renderPills();
    renderFacets();
    renderChosen();
    renderSort();
  }
  syncToggles();
  renderResults();
  refreshQueueCount();
}

async function loadSearchPage() {
  if (!preferencesReady)
    preferencesReady = request("preferences")
      .then((value) => (preferences = value))
      .catch((error) => {
        preferencesReady = null;
        throw error;
      });
  await preferencesReady;
  if (!SS.loaded) {
    SS.density =
      searchStore("tl-search-density") === "compact"
        ? "compact"
        : "comfortable";
    SS.posters = searchStore("tl-search-posters") !== "0";
    setDensity(SS.density);
    searchRetranslate();
    if (!SS.loading) {
      const loading = (async () => {
        await loadSearchOptions();
        await runSearch(1);
      })();
      SS.loading = loading;
      try {
        await loading;
      } finally {
        if (SS.loading === loading) SS.loading = null;
      }
    } else {
      await SS.loading;
    }
  } else {
    refreshQueueCount();
  }
}

$("search-form").onsubmit = (event) => {
  event.preventDefault();
  clearTimeout(SS.timer);
  guard(() => runSearch(1), event.submitter);
};
$("search-query").oninput = () => renderSort();
renderSort();
$("search-category").onchange = () => pickCategory($("search-category").value);
$("search-density-compact").onclick = () => setDensity("compact");
$("search-density-comfortable").onclick = () => setDensity("comfortable");
$("search-posters").onclick = () => setPosters(!SS.posters);
$("search-queue-link").onclick = (event) =>
  guard(() => request("navigate", { page: "queue" }), event.currentTarget);
$("search-exclusive").onclick = () => {
  SS.exclusive = !SS.exclusive;
  criteriaChanged();
};
$("search-palliative").onclick = () => {
  SS.palliative = { "": "include", include: "only", only: "" }[SS.palliative];
  criteriaChanged();
};
$("search-crew").onclick = () => {
  SS.crew = !SS.crew;
  criteriaChanged();
};
$("search-clear").onclick = () => {
  SS.chosen.clear();
  SS.inputs = { year: "", team: "", uploader: "" };
  SS.exclusive = false;
  SS.palliative = "";
  SS.crew = false;
  SS.sort = { key: "createdAt", order: "desc" };
  SS.category = "";
  renderSort();
  loadSearchOptions(() => guard(() => runSearch(1)));
};
$("queue-search").onclick = (event) =>
  guard(() => searchEnqueue([...state.searchSelected]), event.currentTarget);
$("search-details").onclick = () => {
  SS.rows
    .filter((r) => state.searchSelected.has(r.hash))
    .forEach((row) => guard(() => details(row)));
};

/* The card that opens when the pointer rests on a result, like c411's. */
const hoverCard = { node: null, timer: null, hash: "" };
function hideHover() {
  clearTimeout(hoverCard.timer);
  hoverCard.hash = "";
  if (hoverCard.node) hoverCard.node.hidden = true;
}
function showHover(row, anchor) {
  const info = SS.listing[row.hash];
  if (!info || !(info.title || info.overview)) return;
  if (!hoverCard.node) {
    hoverCard.node = element("div", undefined, "hover-card");
    hoverCard.node.setAttribute("role", "tooltip");
    document.body.append(hoverCard.node);
  }
  const card = hoverCard.node;
  const kind = (row.native_category_label || "").split(" / ").pop();
  const head = element("div", undefined, "hc-head");
  if (info.backdrop_url) {
    const img = element("img", undefined, "hc-backdrop");
    img.alt = "";
    loadPoster(img, info.backdrop_url);
    img.onerror = () => img.remove();
    head.append(img);
  }
  head.append(element("span", kind.toUpperCase(), "hc-kind"));
  if (info.rating)
    head.append(element("span", `★ ${info.rating.toFixed(1)}`, "hc-rating"));
  const lead = element("div", undefined, "hc-lead");
  if (info.poster_url) {
    const poster = element("img", undefined, "hc-poster");
    poster.alt = "";
    loadPoster(poster, info.poster_url);
    poster.onerror = () => poster.remove();
    lead.append(poster);
  }
  const names = element("div", undefined, "hc-names");
  const runtime = info.runtime
    ? info.runtime >= 60
      ? `${Math.floor(info.runtime / 60)}h${String(info.runtime % 60).padStart(2, "0")}`
      : `${info.runtime} min`
    : "";
  names.append(element("strong", row.title, "hc-title"));
  if (info.original_title && info.original_title !== info.title)
    names.append(element("span", info.original_title, "muted"));
  names.append(
    element(
      "span",
      [info.year || "", runtime, info.directors?.[0] || ""]
        .filter(Boolean)
        .join(" · "),
      "muted",
    ),
  );
  lead.append(names);
  const body = element("div", undefined, "hc-body");
  if (info.genres?.length) {
    const genres = element("div", undefined, "dt-row");
    info.genres
      .slice(0, 3)
      .forEach((g) => genres.append(element("span", g, "hc-genre")));
    body.append(genres);
  }
  if (info.overview)
    body.append(
      element(
        "p",
        info.overview.length > 260
          ? info.overview.slice(0, 257).replace(/\s+\S*$/, "") + "…"
          : info.overview,
      ),
    );
  (info.cast || [])
    .slice(0, 3)
    .forEach((n) => body.append(element("div", n, "hc-cast")));
  card.replaceChildren(head, lead, body);
  card.hidden = false;
  const box = anchor.getBoundingClientRect();
  const width = 360;
  // Over the right end of the row, inside the page.
  const left = Math.max(
    8,
    Math.min(box.right - width - 12, innerWidth - width - 8),
  );
  card.style.left = `${left}px`;
  card.style.top = `${Math.min(Math.max(8, box.top - 20), Math.max(8, innerHeight - card.offsetHeight - 8))}px`;
  hoverCard.hash = row.hash;
}
function watchHover(host) {
  host.addEventListener("pointerover", (event) => {
    const el = event.target.closest(".sr-row, tbody tr");
    if (!el || !host.contains(el) || event.pointerType === "touch") return;
    const index = [
      ...host.querySelectorAll(
        el.classList.contains("sr-row") ? ".sr-row" : "tbody tr",
      ),
    ].indexOf(el);
    const row = SS.rows[index];
    if (!row || hoverCard.hash === row.hash) return;
    hideHover();
    hoverCard.timer = setTimeout(() => showHover(row, el), 450);
  });
  host.addEventListener("pointerleave", hideHover);
  host.addEventListener("scroll", hideHover, true);
}
watchHover($("search-table"));
window.addEventListener("scroll", hideHover, true);
