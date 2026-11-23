"use strict";
const state = { clientId: "" };
const zenSeeding = {
  generation: 0,
  expanded: new Set(),
  groups: [],
  category: "all",
  offset: 0,
  total: 0,
  sort: "zen",
  descending: true,
  query: "",
  filters: { state: "", category: "", tracker: "", tag: "" },
  metrics: {
    sizeMin: "",
    sizeMax: "",
    noteMin: "",
    zenMin: "",
    weightMin: "",
    seedMax: "",
    daysMin: "",
  },
  units: { sizeMin: "GiB", sizeMax: "GiB" },
};
let loading = false,
  requestingRefresh = false,
  revision = -1,
  started = false;
const pageSize = 100;

let filterTimer;
const metricFields = {
  sizeMin: "size_min",
  sizeMax: "size_max",
  noteMin: "note_min",
  zenMin: "zen_min",
  weightMin: "weight_min",
  seedMax: "seed_max",
  daysMin: "days_min",
};
function filterParameters() {
  const params = {
    state: zenSeeding.filters.state,
    tracker: zenSeeding.filters.tracker,
    tag: zenSeeding.filters.tag,
  };
  for (const [field, key] of Object.entries(metricFields)) {
    const value = zenSeeding.metrics[field];
    if (value !== "")
      params[key] =
        Number(value) *
        (zenSeeding.units[field]
          ? zenSeeding.units[field] === "GiB"
            ? 1024 ** 3
            : 1024 ** 2
          : 1);
  }
  return params;
}
function renderFilters(options = zenSeeding.filterOptions || {}) {
  zenSeeding.filterOptions = options;
  const active = document.activeElement,
    top = scrollY,
    queryFocused = active?.id === "seeding-query",
    metric = active?.dataset?.metric,
    filter = active?.dataset?.filter,
    typed = active?.value,
    expanded = document.querySelector(".metric-filters")?.open;
  $("seeding-filters").innerHTML =
    TLTorrentFilters.controls({
      query: zenSeeding.query,
      queryId: "seeding-query",
      filters: zenSeeding.filters,
      options: {
        ...options,
        category: (options.category || []).map((item) => ({
          ...item,
          label: item.label || say("Unknown category", "Catégorie inconnue"),
        })),
      },
      language,
    }) +
    TLTorrentFilters.metrics({
      metrics: zenSeeding.metrics,
      sizeUnits: zenSeeding.units,
      language,
      scope: false,
    });
  if (expanded !== undefined)
    document.querySelector(".metric-filters").open = expanded;
  const reload = () => {
    zenSeeding.offset = 0;
    guard(loadZenSeeding);
  };
  $("seeding-query").oninput = (event) => {
    zenSeeding.query = event.target.value;
    zenSeeding.generation++;
    clearTimeout(filterTimer);
    filterTimer = setTimeout(reload, 200);
  };
  document.querySelectorAll("[data-filter]").forEach(
    (node) =>
      (node.onchange = () => {
        zenSeeding.filters[node.dataset.filter] = node.value;
        zenSeeding.category = zenSeeding.filters.category || "all";
        reload();
      }),
  );
  document.querySelectorAll("[data-metric]").forEach(
    (node) =>
      (node.onchange = () => {
        if (!node.checkValidity()) return;
        zenSeeding.metrics[node.dataset.metric] = node.value;
        reload();
      }),
  );
  document.querySelectorAll("[data-unit]").forEach(
    (node) =>
      (node.onclick = () => {
        const field = node.dataset.unit,
          input = document.querySelector(`[data-metric="${field}"]`),
          toMiB = zenSeeding.units[field] === "GiB";
        zenSeeding.units[field] = toMiB ? "MiB" : "GiB";
        zenSeeding.metrics[field] =
          input.value === ""
            ? ""
            : String(Number(input.value) * (toMiB ? 1024 : 1 / 1024));
        renderFilters();
        reload();
      }),
  );
  $("clear-filters").onclick = () => {
    clearTimeout(filterTimer);
    zenSeeding.query = "";
    zenSeeding.category = "all";
    for (const key of Object.keys(zenSeeding.filters))
      zenSeeding.filters[key] = "";
    for (const key of Object.keys(zenSeeding.metrics))
      zenSeeding.metrics[key] = "";
    renderFilters();
    reload();
  };
  const focus = queryFocused
    ? $("seeding-query")
    : metric
      ? document.querySelector(`[data-metric="${metric}"]`)
      : filter
        ? document.querySelector(`[data-filter="${filter}"]`)
        : null;
  if (focus) {
    if (metric) focus.value = typed;
    focus.focus({ preventScroll: true });
  }
  scrollTo(0, top);
}

function controls() {
  const busy = loading || requestingRefresh || Boolean(environment.state?.busy);
  for (const id of [
    "seeding-expand",
    "seeding-collapse",
    "seeding-refresh",
    "seeding-jump",
  ])
    $(id).disabled = busy;
  $("seeding-prev").disabled = busy || zenSeeding.offset === 0;
  $("seeding-first").disabled = busy || zenSeeding.offset === 0;
  $("seeding-next").disabled =
    busy || zenSeeding.offset + pageSize >= zenSeeding.total;
  $("seeding-last").disabled =
    busy || zenSeeding.offset + pageSize >= zenSeeding.total;
}
function applyEnvironment(env) {
  const value = env.state || {},
    changed = state.clientId !== value.client_id,
    translated = language !== (env.language || "en");
  language = env.language || "en";
  translate();
  document.documentElement.dataset.theme = env.theme || "dark";
  if (changed) {
    clearTimeout(filterTimer);
    zenSeeding.generation++;
    zenSeeding.groups = [];
    zenSeeding.total = 0;
    loading = false;
    $("seeding-groups").replaceChildren();
    $("seeding-result").replaceChildren();
    state.clientId = value.client_id;
    zenSeeding.expanded = new Set(value.expanded || []);
    zenSeeding.category = "all";
    zenSeeding.offset = 0;
    zenSeeding.query = "";
    for (const key of Object.keys(zenSeeding.filters))
      zenSeeding.filters[key] = "";
    for (const key of Object.keys(zenSeeding.metrics))
      zenSeeding.metrics[key] = "";
    renderFilters({});
    started = false;
  }
  controls();
  $("seeding-error").textContent = value.error || "";
  const tags = value.tags;
  $("seeding-tags").textContent = !tags
    ? ""
    : !tags.supported
      ? say(
          "Category tags: Deluge’s single label is kept for Verification. Categories remain available here.",
          "Étiquettes de catégorie : le libellé unique de Deluge est conservé pour la Vérification. Les catégories restent disponibles ici.",
        )
      : `${say("Category tags", "Étiquettes de catégorie")}: ${tags.updated} ${say("updated", "mises à jour")} · ${tags.failed} ${say("failed; next refresh retries", "échecs ; nouvel essai à la prochaine actualisation")}`;
  if (
    env.active &&
    (changed || !started || revision !== value.revision || translated)
  ) {
    revision = value.revision;
    started = true;
    guard(loadZenSeeding);
  }
}
function groupName(group) {
  return (
    group.name ||
    (group.category === null
      ? say("Unknown category", "Catégorie inconnue")
      : say("Category ", "Catégorie ") + group.category)
  );
}
function chooseCategory(id) {
  zenSeeding.category = id;
  zenSeeding.filters.category = id === "all" ? "" : id;
  zenSeeding.offset = 0;
  return loadZenSeeding();
}
function categoryBranch(group, children) {
  const branch = element("details", undefined, "seeding-category");
  branch.dataset.group = group.id;
  const heading = element("summary"),
    select = button(`${groupName(group)} · ${group.count}`, () =>
      chooseCategory(group.id),
    );
  select.dataset.category = group.id;
  select.setAttribute("aria-pressed", String(zenSeeding.category === group.id));
  select.title = `${bytes(group.size)} · ≈ ${num(group.zen)} Zen/${say("day", "jour")}`;
  heading.append(select);
  branch.append(heading);
  for (const child of children.get(group.id) || [])
    branch.append(categoryBranch(child, children));
  if (!(children.get(group.id) || []).length) branch.classList.add("leaf");
  branch.open =
    zenSeeding.expanded.has(group.id) || Boolean($("seeding-query").value);
  branch.addEventListener("toggle", () => {
    if (!branch.isConnected || $("seeding-query").value) return;
    branch.open
      ? zenSeeding.expanded.add(group.id)
      : zenSeeding.expanded.delete(group.id);
    guard(() =>
      seedingRequest("expanded", { groups: [...zenSeeding.expanded] }),
    );
  });
  return branch;
}
function renderCategories(result) {
  const children = new Map();
  for (const group of result.groups) {
    if (!children.has(group.parent)) children.set(group.parent, []);
    children.get(group.parent).push(group);
  }
  for (const groups of children.values())
    groups.sort((a, b) => groupName(a).localeCompare(groupName(b)));
  const all = button(
    `${say("All categories", "Toutes les catégories")} · ${result.matched}`,
    () => chooseCategory("all"),
  );
  all.id = "seeding-all";
  all.setAttribute("aria-pressed", String(zenSeeding.category === "all"));
  $("seeding-groups").replaceChildren(
    all,
    ...(children.get("") || []).map((group) => categoryBranch(group, children)),
  );
}
function renderRows(result) {
  const table = element("table", undefined, "torrent-list"),
    head = element("thead"),
    heading = element("tr"),
    body = element("tbody");
  const columns = [
    ["name", say("Torrent / state", "Torrent / état")],
    ["size", say("Size", "Taille")],
    ["seeders", "Seeders"],
    ["seed_days", say("Seed time", "Durée de seed")],
    ["note", "≈ Note"],
    ["zen", say("≈ Zen / day", "≈ Zen / jour")],
    ["ratio", "Ratio"],
  ];
  for (const [key, label] of columns) {
    const cell = element("th"),
      active = zenSeeding.sort === key;
    cell.setAttribute(
      "aria-sort",
      active ? (!zenSeeding.descending ? "ascending" : "descending") : "none",
    );
    const sort = button(
      label + (active ? (!zenSeeding.descending ? " ↑" : " ↓") : " ↕"),
      () => {
        zenSeeding.descending = active ? !zenSeeding.descending : false;
        zenSeeding.sort = key;
        zenSeeding.offset = 0;
        return loadZenSeeding();
      },
    );
    sort.className = "sort-head";
    sort.dataset.sort = key;
    cell.append(sort);
    heading.append(cell);
  }
  head.append(heading);
  for (const row of result.rows) {
    const line = element("tr"),
      name = element("td", undefined, "name"),
      title = element("span", row.name, "torrent-title");
    title.title = row.name;
    const category =
      row.category || say("Unknown category", "Catégorie inconnue");
    const detail = element(
      "small",
      `${row.seeding ? say("Seeding", "En partage") : say("Inactive", "Inactif")} · ${category}${row.provisional_category ? " ≈" : ""}`,
    );
    detail.title = row.provisional_category
      ? say(
          "Category from the cached Catalogue",
          "Catégorie du Catalogue en cache",
        )
      : category;
    name.append(title, element("br"), detail);
    line.append(name);
    for (const value of [
      bytes(row.size),
      num(row.seeders),
      num(row.seed_days) + " " + say("days", "jours"),
      num(row.note),
      row.zen == null ? "—" : "≈ " + num(row.zen),
      num(row.ratio),
    ])
      line.append(element("td", value));
    body.append(line);
  }
  table.append(head, body);
  $("seeding-result").replaceChildren(table);
  if (!result.rows.length)
    $("seeding-result").append(
      element(
        "p",
        say(
          "No torrents match these filters.",
          "Aucun torrent pour ces filtres.",
        ),
        "empty",
      ),
    );
}
function renderSummary(result) {
  $("seeding-total").textContent =
    `${result.summary.count} ${say("torrents seeding", "torrents en partage")} · ≈ ${num(result.summary.daily)} Zen/${say("day", "jour")} (${say("paid", "payés")} ≈ ${result.summary.paid})`;
  $("seeding-page").textContent =
    `${result.total ? result.offset + 1 : 0}–${result.offset + result.rows.length} / ${result.total}`;
  $("seeding-jump").max = Math.max(1, Math.ceil(result.total / pageSize));
  if (document.activeElement !== $("seeding-jump"))
    $("seeding-jump").value = Math.floor(result.offset / pageSize) + 1;
  const names = {
    tanker: "Tanker",
    "swarm-keeper": "Swarm Keeper",
    reuploader: "Reuploader",
  };
  $("seeding-classes").replaceChildren(
    ...result.classes.map((cls) =>
      element(
        cls.current ? "strong" : "span",
        `${names[cls.id]} : ≈ ${num(cls.daily)} Zen/${say("day", "jour")}${cls.id === "reuploader" ? say(" (rough)", " (approximatif)") : ""}${cls.current ? say(" ← your Class", " ← votre Classe") : ""}`,
      ),
    ),
  );
  if (document.activeElement !== $("seeding-uploads"))
    $("seeding-uploads").value = result.uploads;
}
async function loadZenSeeding() {
  loading = true;
  controls();
  const generation = ++zenSeeding.generation;
  $("seeding-status").textContent = say("Loading…", "Chargement…");
  try {
    const result = await seedingRequest("page", {
      q: zenSeeding.query,
      ...filterParameters(),
      group: zenSeeding.category,
      descendants: true,
      sort: zenSeeding.sort,
      descending: zenSeeding.descending,
      offset: zenSeeding.offset,
      limit: pageSize,
    });
    if (generation !== zenSeeding.generation) return;
    if (result.total && zenSeeding.offset >= result.total) {
      zenSeeding.offset = Math.floor((result.total - 1) / pageSize) * pageSize;
      return await loadZenSeeding();
    }
    zenSeeding.total = result.total;
    zenSeeding.groups = result.groups;
    renderFilters(result.filter_options);
    renderCategories(result);
    renderRows(result);
    renderSummary(result);
    const errors = (result.client_errors || [])
      .map((error) => `${error.name}: ${error.message}`)
      .join(" · ");
    $("seeding-status").textContent =
      errors ||
      say(
        "Search and sorting cover every torrent. 100 rows per page. Estimates use client seed age and the cached Catalogue.",
        "La recherche et le tri couvrent tous les torrents. 100 lignes par page. Les estimations utilisent l’âge du seed du client et le Catalogue en cache.",
      );
  } catch (error) {
    if (generation === zenSeeding.generation)
      TLToast.error(error);
  } finally {
    if (generation === zenSeeding.generation) {
      loading = false;
      controls();
    }
  }
}
function init() {
  renderFilters();
  $("seeding-expand").onclick = () => {
    for (const group of zenSeeding.groups) zenSeeding.expanded.add(group.id);
    $("seeding-groups")
      .querySelectorAll("details")
      .forEach((branch) => {
        branch.open = true;
      });
    guard(() =>
      seedingRequest("expanded", { groups: [...zenSeeding.expanded] }),
    );
  };
  $("seeding-collapse").onclick = () => {
    zenSeeding.expanded.clear();
    $("seeding-groups")
      .querySelectorAll("details")
      .forEach((branch) => {
        branch.open = false;
      });
    guard(() => seedingRequest("expanded", { groups: [] }));
  };
  $("seeding-refresh").onclick = (event) =>
    guard(async () => {
      requestingRefresh = true;
      controls();
      try {
        await seedingRequest("refresh");
      } finally {
        requestingRefresh = false;
        controls();
      }
    }, event.currentTarget);
  for (const [id, offset] of [
    ["seeding-first", () => 0],
    ["seeding-prev", () => Math.max(0, zenSeeding.offset - pageSize)],
    ["seeding-next", () => zenSeeding.offset + pageSize],
    [
      "seeding-last",
      () => Math.floor(Math.max(0, zenSeeding.total - 1) / pageSize) * pageSize,
    ],
  ])
    $(id).onclick = () => {
      zenSeeding.offset = offset();
      guard(loadZenSeeding);
    };
  $("seeding-jump").onchange = () => {
    zenSeeding.offset =
      Math.max(
        0,
        Math.min(
          Number($("seeding-jump").max),
          Math.floor(Number($("seeding-jump").value)) || 1,
        ) - 1,
      ) * pageSize;
    guard(loadZenSeeding);
  };
  $("seeding-save-uploads").onclick = (event) =>
    guard(async () => {
      await seedingRequest("uploads", {
        uploads: Number($("seeding-uploads").value),
      });
      await loadZenSeeding();
    }, event.currentTarget);
}
