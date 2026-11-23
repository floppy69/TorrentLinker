/* RSS uses the same authenticated API, tables and metadata dialog as Search. */
const feedState = {
  id: "",
  filter: "all",
  selected: new Set(),
  feeds: [],
  rows: [],
};
const feedText = (en, fr) => say(en, fr);
const feedCall = (path, body, method = "POST") => api(path, body, method);
const FEED_MODES = () => ({
  review_only: feedText("Notify me", "Me prévenir"),
  app_queue: feedText("Add to queue", "Ajouter à la file"),
  automatic_download: feedText(
    "Download automatically",
    "Télécharger automatiquement",
  ),
});
const feedHuman = {
  when(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000),
      now = new Date();
    const time = d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate());
    const days = Math.round((day(now) - day(d)) / 864e5);
    if (days === 0) return feedText(`Today ${time}`, `Aujourd’hui ${time}`);
    if (days === 1) return feedText(`Yesterday ${time}`, `Hier ${time}`);
    return d.toLocaleDateString(
      [],
      d.getFullYear() === now.getFullYear()
        ? { day: "numeric", month: "short" }
        : { day: "numeric", month: "short", year: "numeric" },
    );
  },
  updated(ts) {
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 3600) {
      const n = Math.max(1, Math.round(s / 60));
      return feedText(`Updated ${n} min ago`, `Mis à jour il y a ${n} min`);
    }
    if (s < 86400) {
      const n = Math.round(s / 3600);
      return feedText(`Updated ${n} h ago`, `Mis à jour il y a ${n} h`);
    }
    const n = Math.round(s / 86400);
    return feedText(`Updated ${n} d ago`, `Mis à jour il y a ${n} j`);
  },
  size: (n) => (n > 0 ? bytes(n) : "—"),
};
function feedIconMenu(items) {
  const wrap = element("div", undefined, "assistant-menu-wrap");
  const more = aIconButton("⋯", feedText("More", "Plus"), () =>
    aMenu(more, items),
  );
  more.setAttribute("aria-haspopup", "menu");
  wrap.append(more);
  return wrap;
}
let loadSequence = 0;
async function loadFeeds() {
  const scroll = document.scrollingElement.scrollTop;
  const sequence = ++loadSequence;
  const found = await api("feeds");
  if (sequence !== loadSequence) return;
  feedState.feeds = found;
  const feeds = feedState.feeds;
  const head = $("feeds-side-head");
  head.replaceChildren(
    element("span", feedText("Subscriptions", "Abonnements"), "muted"),
    aIconButton("＋", feedText("New subscription", "Nouvel abonnement"), () =>
      editFeed(),
    ),
  );
  const community = $("feeds-community");
  community.replaceChildren(button(feedText("Community rules","Règles communautaires"),()=>communityBrowseDialog("rss",async result=>{for(const rule of result.data.rules){if(rule.include?.length||rule.exclude?.length)throw Error(feedText("Legacy text filters need manual conversion before import.","Les anciens filtres textuels nécessitent une conversion manuelle."));await feedCall("feeds",{subscription:{name:rule.name.slice(0,100),query:rule.query||"",categories:rule.categories||[],preferences:rule.preferences||{},paused:true,mode:"review_only"}})}await navigate("feeds")})));
  const sidebar = $("feeds-sidebar");
  const row = (name, detail, unread, id) => {
    const b = button(
      "",
      () => {
        feedState.id = id;
        feedState.selected.clear();
        return loadFeeds();
      },
      "feed-row",
    );
    b.setAttribute("aria-current", String(id === feedState.id));
    b.append(
      element("span", name, "feed-row-name"),
      element("span", detail, "feed-row-detail muted"),
      element("span", unread ? String(unread) : "", "feed-row-badge"),
    );
    return b;
  };
  sidebar.replaceChildren(
    row(
      feedText("All feeds", "Tous les flux"),
      "",
      feeds.reduce((n, f) => n + f.unread_count, 0),
      "",
    ),
    ...feeds.map((f) =>
      row(
        f.name,
        (f.paused ? feedText("Paused", "En pause") + " · " : "") +
          (FEED_MODES()[f.mode] || f.mode),
        f.unread_count,
        f.id,
      ),
    ),
  );
  const empty = !feeds.length;
  $("feeds-empty").hidden = !empty;
  $("feeds-body").hidden = empty;
  if (empty) {
    $("feeds-empty").replaceChildren(
      element(
        "p",
        feedText(
          "Follow a search to see new releases here, or let rules queue them for you.",
          "Suivez une recherche pour voir ici les nouvelles publications, ou laissez des règles les mettre en file.",
        ),
        "muted",
      ),
      button(
        feedText("New subscription", "Nouvel abonnement"),
        () => editFeed(),
        "primary",
      ),
    );
    return;
  }
  const active = feeds.find((f) => f.id === feedState.id);
  if (!active) feedState.id = "";
  const refresh = async () => {
    for (const f of active ? [active] : feeds)
      await feedCall(`feeds/${f.id}/refresh`, {});
    await loadFeeds();
  };
  const shared = [
    [feedText("Compare clients…", "Comparer les clients…"), compareFeedClients],
    [
      feedText("Saved selections", "Sélections enregistrées"),
      feedSavedSelections,
    ],
  ];
  const items = active
    ? [
        [feedText("Edit…", "Modifier…"), () => editFeed(active)],
        [
          active.paused
            ? feedText("Resume", "Reprendre")
            : feedText("Pause", "Suspendre"),
          async () => {
            await feedCall(
              `feeds/${active.id}/pause?paused=${!active.paused}`,
              {},
            );
            await loadFeeds();
          },
        ],
        [
          feedText("Process rules", "Évaluer les règles"),
          async () =>
            feedReport(await feedCall(`feeds/${active.id}/process`, {})),
        ],
        [
          feedText("Decisions", "Décisions"),
          async () => feedReport(await api(`feeds/${active.id}/decisions`)),
        ],
        [
          feedText("Delete…", "Supprimer…"),
          async () => {
            if (
              !confirm(
                feedText(
                  `Delete “${active.name}”? Its releases leave the inbox.`,
                  `Supprimer « ${active.name} » ? Ses publications quittent la boîte de réception.`,
                ),
              )
            )
              return;
            await api(`feeds/${active.id}`, undefined, "DELETE");
            feedState.id = "";
            await loadFeeds();
          },
        ],
        ...shared,
      ]
    : [[feedText("Refresh all", "Tout actualiser"), refresh], ...shared];
  let status;
  if (!active)
    status = feedText(
      `Subscriptions: ${feeds.length}`,
      `Abonnements : ${feeds.length}`,
    );
  else if (active.error) status = active.error;
  else if (active.last_success) status = feedHuman.updated(active.last_success);
  else
    status = feedText(
      "Waiting for the first update",
      "En attente de la première mise à jour",
    );
  if (active?.paused && !active.error)
    status = `${feedText("Paused", "En pause")} · ${status}`;
  const titles = element("div", undefined, "feed-titles");
  titles.append(
    element(
      "h2",
      active ? active.name : feedText("All feeds", "Tous les flux"),
    ),
    element("p", status, active?.error ? "danger" : "muted"),
  );
  const info = aIconButton(
    "ⓘ",
    active?.coverage ||
      feedText(
        "Limited RSS discovery. History and gap-free updates are not guaranteed.",
        "Découverte RSS limitée. Historique et mises à jour sans lacunes non garantis.",
      ),
    () => {},
  );
  info.disabled = false;
  $("feeds-header").replaceChildren(
    titles,
    info,
    active
      ? button(
          feedText("Refresh now", "Actualiser maintenant"),
          refresh,
          "primary",
        )
      : button(
          feedText("New subscription", "Nouvel abonnement"),
          () => editFeed(),
          "primary",
        ),
    feedIconMenu(items),
  );
  const filters = [
    ["all", "All", "Tous"],
    ["unread", "Unread", "Non lus"],
    ["saved", "Saved", "Enregistrés"],
    ["in-client", "In client", "Dans un client"],
    ["queued", "Queued", "En file"],
  ];
  $("feeds-filters").replaceChildren(
    ...filters.map(([id, en, fr]) => {
      const b = button(
        feedText(en, fr),
        () => {
          feedState.filter = id;
          return loadFeeds();
        },
        "tab",
      );
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(id === feedState.filter));
      return b;
    }),
  );
  let rows = await api(
    `feed-inbox?feed_id=${encodeURIComponent(feedState.id)}&unread=${feedState.filter === "unread"}&saved=${feedState.filter === "saved"}`,
  );
  if (sequence !== loadSequence) return;
  if (feedState.filter === "in-client")
    rows = rows.filter((r) => r.in_clients.length);
  if (feedState.filter === "queued") rows = rows.filter((r) => r.queued);
  feedState.rows = rows;
  for (const hash of feedState.selected)
    if (!rows.some((r) => r.infohash === hash)) feedState.selected.delete(hash);
  const bar = $("feeds-actions");
  const mark = (action) => async () => {
    await feedCall("feed-inbox/mark", {
      hashes: [...feedState.selected],
      feed_id: feedState.id,
      action,
    });
    await loadFeeds();
  };
  const count = element("span", "", "muted");
  count.id = "feeds-count";
  bar.replaceChildren(
    count,
    element("span", undefined, "spacer"),
    button(feedText("Mark read", "Marquer lus"), mark("read"), "quiet"),
    button(feedText("Save", "Enregistrer"), mark("save"), "quiet"),
    button(feedText("Dismiss", "Masquer"), mark("dismiss"), "quiet"),
    button(feedText("Save selection", "Enregistrer la sélection"), async () => {
      feedReport(
        await feedCall("feed-selections", { hashes: [...feedState.selected] }),
      );
    }),
    button(
      feedText("Add to queue", "Ajouter à la file"),
      () => feedEnqueue([...feedState.selected]),
      "primary",
    ),
  );
  const selectionChanged = () => {
    bar.hidden = !feedState.selected.size;
    count.textContent = feedText(
      `${feedState.selected.size} selected`,
      `${feedState.selected.size} sélectionné(s)`,
    );
  };
  selectionChanged();
  const columns = [
    {
      label: feedText("Title", "Titre"),
      render: (r) =>
        button(
          `${r.unread ? "● " : ""}${r.title}`,
          () =>
            details({
              ...r,
              hash: r.infohash,
              website: r.details_url,
              queueSource: "feed",
            }),
          "link-button",
        ),
    },
    {
      label: feedText("Size", "Taille"),
      render: (r) => feedHuman.size(r.size),
    },
    {
      label: feedText("Seeds", "Seeders"),
      render: (r) => r.seeders,
    },
    {
      label: feedText("Discovered", "Découvert"),
      render: (r) => feedHuman.when(r.discovered_at),
    },
    {
      label: feedText("Published", "Publié"),
      render: (r) => feedHuman.when(r.published_at),
    },
    {
      label: feedText("State", "État"),
      render: (r) =>
        r.queue_status ||
        r.in_clients.join(", ") ||
        (r.client_inventory_unknown.length
          ? feedText(
              "Client comparison needed",
              "Comparaison des clients nécessaire",
            )
          : ""),
    },
  ];
  table(
    "feeds-results",
    rows.map((r) => ({
      ...r,
      hash: r.infohash,
    })),
    columns,
    feedState.selected,
    "hash",
    selectionChanged,
  );
  document.scrollingElement.scrollTop = scroll;
}
function feedDefinition(raw) {
  const keys = [
    "id",
    "name",
    "query",
    "categories",
    "paused",
    "interval_minutes",
    "mode",
    "client_id",
    "folder",
    "preferences",
    "include_current",
    "wait_minutes",
    "replace_pending",
    "download_hours",
    "daily_bytes",
    "daily_torrents",
    "reserve_bytes",
  ];
  return Object.fromEntries(
    keys.filter((k) => k in raw).map((k) => [k, raw[k]]),
  );
}
function feedReport(value) {
  $("dialog-content").replaceChildren(
    element("pre", JSON.stringify(value, null, 2)),
  );
  if (value.id && value.hashes)
    $("dialog-content").append(
      button(feedText("Queue selected", "Mettre la sélection en file"), () =>
        feedEnqueue([], value.id),
      ),
    );
  $("dialog").showModal();
}
async function feedEnqueue(hashes, selectionId = "") {
  if (!hashes.length && !selectionId)
    throw Error(
      feedText("Select releases first.", "Sélectionnez des torrents."),
    );
  const saved = selectionId
    ? await api(`feed-selections/${selectionId}`)
    : await feedCall("feed-selections", {
        hashes,
      });
  const options = await api("feed-options");
  const content = $("dialog-content");
  content.replaceChildren(
    element(
      "h2",
      feedText("Queue selected releases", "Mettre les torrents en file"),
    ),
  );
  const client = element("select"),
    folder = element("select");
  for (const p of options.clients) client.append(new Option(p.name, p.id));
  client.value =
    state.clientId === "all" ? options.clients[0]?.id : state.clientId;
  const update = () =>
    folder.replaceChildren(
      ...(
        options.clients.find((p) => p.id === client.value)?.folders || []
      ).map((p) => new Option(p, p)),
    );
  client.onchange = update;
  update();
  content.append(
    client,
    folder,
    element(
      "p",
      feedText(
        "This saves an app queue entry. Disk and daily limits apply when downloads start.",
        "La file est enregistrée dans l'application. L'espace disque et les limites journalières sont vérifiés au démarrage.",
      ),
    ),
    button(
      feedText("Add to app queue", "Ajouter à la file de l'application"),
      async () => {
        await feedCall(`feed-selections/${saved.id}/enqueue`, {
          client_id: client.value,
          folder: folder.value,
        });
        $("dialog").close();
        await loadFeeds();
      },
    ),
  );
  $("dialog").showModal();
}
const FEED_STARTERS = {
  quality: ["2160p", "1080p", "720p", "480p"],
  codec: ["HEVC", "H264", "AV1"],
  audio: ["fr", "en", "multi"],
  subtitles: ["fr", "en"],
  format: [],
  bitrate: [],
  platform: [],
  license: [],
};
const FEED_COMMON = ["quality", "codec", "audio", "subtitles"];
const FEED_MORE = ["format", "bitrate", "platform", "license"];
const FEED_INTERVALS = [15, 30, 60, 120, 360, 720, 1440];
const FEED_NEXT_CHIP = {
  none: "prefer",
  prefer: "must",
  must: "avoid",
  avoid: "none",
};
const FEED_GIB = 1024 ** 3,
  FEED_MIB = 1024 ** 2;
const feedFieldNames = () => ({
  quality: feedText("Quality", "Qualité"),
  codec: "Codec",
  audio: "Audio",
  subtitles: feedText("Subtitles", "Sous-titres"),
  format: "Format",
  bitrate: feedText("Bitrate", "Débit"),
  platform: feedText("Platform", "Plateforme"),
  license: feedText("License", "Licence"),
  size: feedText("Smaller size", "Taille plus petite"),
  seeders: feedText("More seeders", "Plus de seeders"),
});
function feedChipState(p, f, v) {
  if ((p.excluded[f] || []).includes(v)) return "avoid";
  if ((p.required[f] || []).includes(v)) return "must";
  if ((p.preferred[f] || []).includes(v)) return "prefer";
  return "none";
}
function feedEnsurePriorities(p) {
  for (const k of Object.keys(p.preferred))
    if (!p.priorities.includes(k)) p.priorities.push(k);
  if (p.prefer_small && !p.priorities.includes("size"))
    p.priorities.push("size");
}
// Moves one value to a state and leaves every other value as it was (mirrors feed_units.set_chip).
function feedSetChip(p, f, v, state) {
  const drop = (...groups) =>
    groups.forEach((g) => {
      const rest = (p[g][f] || []).filter((x) => x !== v);
      if (rest.length) p[g][f] = rest;
      else delete p[g][f];
    });
  const add = (g) => {
    p[g][f] = [...(p[g][f] || [])];
    if (!p[g][f].includes(v)) p[g][f].push(v);
  };
  if (state === "none") drop("required", "preferred", "excluded");
  else if (state === "prefer") {
    drop("required", "excluded");
    add("preferred");
  } else if (state === "must") {
    drop("excluded");
    add("required");
  } else {
    drop("required", "preferred");
    add("excluded");
  }
  feedEnsurePriorities(p);
}
function feedMove(list, item, step) {
  const i = list.indexOf(item);
  if (i < 0) return list;
  const out = [...list];
  out.splice(i, 1);
  out.splice(Math.max(0, Math.min(list.length - 1, i + step)), 0, item);
  return out;
}
// A size as a number with a MiB/GiB unit. Untouched, it keeps the exact stored bytes.
function feedSizeField(value, unlimited = false) {
  let current = value;
  const number = element("input"),
    unit = element("select");
  number.type = "number";
  number.min = "0";
  number.step = "0.5";
  unit.append(new Option("MiB", "MiB"), new Option("GiB", "GiB"));
  const tenths = Math.round(((value || 0) / FEED_GIB) * 10);
  const inGib =
    value >= FEED_GIB && Math.round((tenths * FEED_GIB) / 10) === value;
  unit.value = inGib || !value ? "GiB" : "MiB";
  number.value = value
    ? String(inGib ? tenths / 10 : Math.round((value / FEED_MIB) * 10) / 10)
    : unlimited
      ? ""
      : "0";
  if (unlimited) number.placeholder = feedText("No limit", "Sans limite");
  const edited = () => {
    const n = number.value === "" ? 0 : Number(number.value);
    current =
      unlimited && n === 0
        ? null
        : Math.round(n * (unit.value === "GiB" ? FEED_GIB : FEED_MIB));
  };
  number.oninput = unit.onchange = edited;
  const box = element("div", undefined, "feed-size");
  box.append(number, unit);
  return {
    el: box,
    get: () => current,
    onchange: (fn) => {
      number.addEventListener("input", fn);
      unit.addEventListener("change", fn);
    },
  };
}
// Allowed hours in local time, stored as UTC. Untouched, they keep the stored UTC hours.
function feedHoursField(utcHours) {
  const offset = -new Date().getTimezoneOffset();
  const toLocal = (hs) =>
    [
      ...new Set(
        hs
          .map((h) => Math.floor((h * 60 + offset) / 60) % 24)
          .map((h) => (h + 24) % 24),
      ),
    ].sort((a, b) => a - b);
  const toUtc = (hs) =>
    [
      ...new Set(
        hs.map((h) => ((Math.floor((h * 60 - offset) / 60) % 24) + 24) % 24),
      ),
    ].sort((a, b) => a - b);
  let utc = [...utcHours];
  const local = toLocal(utcHours);
  const night = [1, 2, 3, 4, 5, 6];
  const kind =
    local.length === 24
      ? "any"
      : local.join() === night.join()
        ? "night"
        : "custom";
  const preset = element("select");
  preset.append(
    new Option(feedText("Any time", "À tout moment"), "any"),
    new Option(
      feedText("Night only (1:00–7:00)", "La nuit seulement (1 h–7 h)"),
      "night",
    ),
    new Option(feedText("Custom hours", "Heures personnalisées"), "custom"),
  );
  preset.value = kind;
  const grid = element("div", undefined, "feed-hours");
  const cells = Array.from({ length: 24 }, (_, h) => {
    const c = element("label", String(h), "feed-hour");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = local.includes(h);
    box.setAttribute("aria-label", feedText(`Hour ${h}`, `Heure ${h}`));
    box.onchange = () => {
      utc = toUtc(cells.filter((x) => x.box.checked).map((x) => x.h));
    };
    c.prepend(box);
    grid.append(c);
    return { box, h };
  });
  grid.hidden = kind !== "custom";
  preset.onchange = () => {
    grid.hidden = preset.value !== "custom";
    if (preset.value !== "custom") {
      const wanted =
        preset.value === "any"
          ? Array.from({ length: 24 }, (_, h) => h)
          : night;
      cells.forEach((x) => {
        x.box.checked = wanted.includes(x.h);
      });
      utc = toUtc(wanted);
    }
  };
  const box = element("div");
  box.append(
    preset,
    grid,
    element(
      "p",
      feedText(
        "Local time. Downloads start only in the hours you tick.",
        "Heure locale. Les téléchargements ne démarrent que pendant les heures cochées.",
      ),
      "muted",
    ),
  );
  return { el: box, get: () => utc };
}
function feedCategoryField(selected, onchange) {
  const known =
    (typeof state !== "undefined" && state.setup?.indexer_categories) || {};
  const chosen = [...selected];
  const pills = element("div", undefined, "feed-category-pills");
  const boxes = new Map();
  const details = element("details", undefined, "feed-cats");
  const summary = element("summary");
  const list = element("div", undefined, "feed-cat-list");
  const label = (id) => known[id]?.name || `#${id}`;
  const refresh = () => {
    summary.textContent = feedText(
      "Subcategories and full selection",
      "Sous-catégories et sélection complète",
    );
    const visible = ids.filter(
      (id) =>
        known[id].parent == null ||
        !known[known[id].parent] ||
        chosen.includes(id),
    );
    pills.replaceChildren(
      ...visible.map((id) => {
        const pill = button(
          label(id),
          () => {
            const at = chosen.indexOf(id);
            if (at < 0) chosen.push(id);
            else chosen.splice(at, 1);
            refresh();
            onchange();
          },
          "feed-category",
        );
        pill.setAttribute("aria-pressed", String(chosen.includes(id)));
        return pill;
      }),
    );
    for (const [id, box] of boxes) box.checked = chosen.includes(id);
  };
  const ids = Object.keys(known)
    .map(Number)
    .sort((a, b) => known[a].name.localeCompare(known[b].name));
  const depth = (id) => {
    let d = 0,
      p = known[id]?.parent;
    while (p != null && known[p] && d < 5) {
      d++;
      p = known[p].parent;
    }
    return d;
  };
  const ordered = [];
  const place = (parent, seen) =>
    ids
      .filter((i) => (known[i].parent ?? null) === parent && !seen.has(i))
      .forEach((i) => {
        seen.add(i);
        ordered.push(i);
        place(i, seen);
      });
  const seen = new Set();
  place(null, seen);
  ids.filter((i) => !seen.has(i)).forEach((i) => ordered.push(i));
  for (const id of ordered) {
    const row = element("label", known[id].name, "feed-cat");
    row.style.paddingLeft = `${depth(id) * 16}px`;
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = chosen.includes(id);
    boxes.set(id, box);
    box.onchange = () => {
      const at = chosen.indexOf(id);
      if (box.checked && at < 0) chosen.push(id);
      if (!box.checked && at >= 0) chosen.splice(at, 1);
      refresh();
      onchange();
    };
    row.prepend(box);
    list.append(row);
  }
  if (!ordered.length)
    list.append(
      element(
        "p",
        feedText(
          "Category names appear once the indexer has been connected.",
          "Les noms de catégories apparaissent une fois l’indexeur connecté.",
        ),
        "muted",
      ),
    );
  refresh();
  details.append(summary, list);
  const wrapper = element("div");
  wrapper.append(pills, details);
  return { el: wrapper, get: () => chosen };
}
let editorSequence = 0;
async function editFeed(existing = null, query = "") {
  const editorId = ++editorSequence;
  const options = await api("feed-options");
  if (editorId !== editorSequence) return;
  const content = $("dialog-content");
  const root = element("div", undefined, "feed-editor");
  content.replaceChildren(root);
  const names = feedFieldNames();
  const base = existing ? feedDefinition(existing) : {};
  const prefs = structuredClone(existing?.preferences || {});
  for (const k of ["required", "preferred", "excluded"]) prefs[k] ??= {};
  prefs.category_scopes ??= {};
  prefs.priorities ??= ["quality", "codec", "audio", "subtitles", "size"];
  prefs.min_size ??= 0;
  prefs.min_seeders ??= 0;
  prefs.max_size ??= null;
  prefs.prefer_small ??= false;
  const ed = {
    rows: [],
    previewed: "",
    previewedAt: 0,
    token: 0,
    order: {},
    suggestions: {},
  };
  const section = (title) => {
    root.append(element("h3", title));
  };
  const field = (label, control, group = false) => {
    const l = element(group ? "div" : "label", undefined, "feed-field");
    l.append(element("span", label), control);
    root.append(l);
    return l;
  };
  const text = (value) => {
    const i = element("input");
    i.value = value ?? "";
    return i;
  };
  const check = (label, on) => {
    const l = element("label", undefined, "feed-check");
    const i = document.createElement("input");
    i.type = "checkbox";
    i.checked = Boolean(on);
    l.append(i, element("span", label));
    root.append(l);
    return i;
  };
  const spin = (value, max = 1e9) => {
    const i = element("input");
    i.type = "number";
    i.min = "0";
    i.max = String(max);
    i.value = String(value);
    return i;
  };
  const fold = (title, ...nodes) => {
    const d = element("details", undefined, "feed-fold");
    d.append(element("summary", title), ...nodes);
    root.append(d);
    return d;
  };
  // 1. What to follow
  root.append(element("h2", feedText("RSS subscription", "Abonnement RSS")));
  section(feedText("What to follow", "Ce qu’il faut suivre"));
  const name = text(existing?.name || "RSS");
  field(feedText("Name", "Nom"), name);
  const queryInput = text(existing?.query ?? query);
  queryInput.placeholder = feedText(
    "Words the title must contain",
    "Mots que le titre doit contenir",
  );
  field(feedText("Title contains", "Le titre contient"), queryInput);
  const categories = feedCategoryField(existing?.categories || [], () => {
    renderChips();
    renderPriorities();
    sourceChanged();
  });
  field(feedText("Categories", "Catégories"), categories.el, true);
  // 2. What you accept
  section(feedText("What you accept", "Ce que vous acceptez"));
  root.append(
    element(
      "p",
      feedText(
        "Shared limits · all selected categories",
        "Limites communes · toutes les catégories sélectionnées",
      ),
      "muted",
    ),
  );
  const minSize = feedSizeField(prefs.min_size);
  field(feedText("At least", "Au moins"), minSize.el);
  const maxSize = feedSizeField(prefs.max_size, true);
  field(feedText("At most", "Au plus"), maxSize.el);
  const minSeeders = spin(prefs.min_seeders);
  field(feedText("Minimum seeders", "Seeders minimum"), minSeeders);
  const help = element("div", undefined, "criterion-help");
  help.append(
    element(
      "strong",
      feedText("Criteria by category", "Critères par catégorie"),
    ),
  );
  const legend = element("div", undefined, "note");
  legend.id = "criteria-legend";
  legend.hidden = true;
  legend.textContent = feedText(
    "1. ♡ Prefer: ranks matches. 2. ✓ Require: must be verified. 3. ✕ Avoid: excludes matches. 4. Clear. Category badges show where each rule applies. Missing required metadata is never accepted. Right-click or Shift+F10 to change preference order.",
    "1. ♡ Préférer : classe les résultats. 2. ✓ Exiger : doit être vérifié. 3. ✕ Éviter : exclut les résultats. 4. Retirer. Les étiquettes indiquent les catégories concernées. Une information requise manquante n’est jamais acceptée. Clic droit ou Maj+F10 pour changer l’ordre des préférences.",
  );
  const info = aIconButton(
    "ⓘ",
    feedText("Selection legend", "Légende de sélection"),
    () => {
      legend.hidden = !legend.hidden;
      info.setAttribute("aria-expanded", String(!legend.hidden));
    },
  );
  info.setAttribute("aria-controls", legend.id);
  info.setAttribute("aria-expanded", "false");
  help.append(info);
  root.append(help, legend);
  const chipHost = element("div", undefined, "feed-chips"),
    moreHost = element("div", undefined, "feed-chips");
  const priorityHost = element("div", undefined, "feed-priorities");
  const chipValues = (f) => {
    ed.order[f] ??= [];
    const all = [
      ...(prefs.preferred[f] || []),
      ...(prefs.required[f] || []),
      ...(prefs.excluded[f] || []),
      ...FEED_STARTERS[f],
      ...(ed.suggestions[f] || []),
    ];
    for (const v of all)
      if (!ed.order[f].some((x) => x.toLowerCase() === v.toLowerCase()))
        ed.order[f].push(v);
    return ed.order[f];
  };
  const stateWords = (s) =>
    ({
      none: feedText("Not set", "Non défini"),
      prefer: feedText("Preferred", "Préféré"),
      must: feedText("Required", "Exigé"),
      avoid: feedText("Avoided", "Évité"),
    })[s];
  const criteriaChanged = () => {
    renderChips();
    renderPriorities();
    judge();
    advancedRefresh();
  };
  function categoryFields(id) {
    if ((id >= 2000 && id < 3000) || (id >= 5000 && id < 7000))
      return FEED_COMMON;
    if (id >= 3000 && id < 4000) return ["format", "bitrate"];
    if (id >= 7000 && id < 9000) return ["format"];
    if (id >= 1000 && id < 2000) return ["platform"];
    if (id >= 4000 && id < 5000) return ["platform", "license"];
    return [];
  }
  function owners(f) {
    return categories.get().filter((id) => categoryFields(id).includes(f));
  }
  function scope(f) {
    // Existing global rules stay global. New criteria take the displayed categories.
    if (
      !(f in prefs.required) &&
      !(f in prefs.preferred) &&
      !(f in prefs.excluded)
    ) {
      const ids = owners(f);
      if (ids.length) {
        const known = state.setup.indexer_categories;
        const descendants = Object.keys(known)
          .map(Number)
          .filter((id) => {
            let parent = known[id]?.parent,
              seen = new Set();
            while (parent != null && !seen.has(parent)) {
              if (ids.includes(parent)) return true;
              seen.add(parent);
              parent = known[parent]?.parent;
            }
            return false;
          });
        prefs.category_scopes[f] = [...new Set([...ids, ...descendants])];
      } else {
        delete prefs.category_scopes[f];
      }
    }
  }
  function renderChips() {
    const focused = document.activeElement?.dataset.criterion;
    const scroll = $("dialog").scrollTop;
    const names = feedFieldNames();
    const relevant = [
      ...new Set(
        categories.get().length
          ? categories.get().flatMap(categoryFields)
          : [],
      ),
    ];
    const preserved = [...FEED_COMMON, ...FEED_MORE].filter(
      (f) => !relevant.includes(f) &&
        [prefs.required, prefs.preferred, prefs.excluded].some((g) => g[f]?.length),
    );
    preservedFold.hidden = !preserved.length;
    moreHost.replaceChildren(...preserved.map((f) => {
      const row = element("div", undefined, "feed-preserved-rule");
      const values = ["required", "preferred", "excluded"]
        .filter((kind) => prefs[kind][f]?.length)
        .map((kind) => `${{required: feedText("Required", "Exigé"), preferred: feedText("Preferred", "Préféré"), excluded: feedText("Avoided", "Évité")}[kind]}: ${prefs[kind][f].join(", ")}`).join(" · ");
      const ids = prefs.category_scopes[f] || [];
      const scopeLabel = ids.length
        ? ids.map((id) => state.setup.indexer_categories[id]?.name || `#${id}`).join(", ")
        : feedText("Legacy rule without category scope", "Ancienne règle sans catégorie définie");
      row.append(element("strong", names[f]), element("p", values),
        element("p", scopeLabel, "muted"),
        button(feedText("Remove this rule", "Supprimer cette règle"), () => {
          for (const kind of ["required", "preferred", "excluded", "category_scopes"])
            delete prefs[kind][f];
          prefs.priorities = prefs.priorities.filter((k) => k !== f);
          criteriaChanged();
        }));
      return row;
    }));
    for (const [host, fields] of [[chipHost, relevant]]) {
      host.replaceChildren(
        ...fields.map((f) => {
          const row = element("div", undefined, "feed-chip-row");
          const label = element("span", names[f], "feed-chip-label");
          const tags = element("span", undefined, "category-tags");
          const configured = [
            prefs.required,
            prefs.preferred,
            prefs.excluded,
          ].some((g) => (g[f] || []).length);
          const ids = configured ? prefs.category_scopes[f] : owners(f);
          if (!ids?.length)
            tags.append(
              element(
                "span",
                feedText("Legacy rule without category scope", "Ancienne règle sans catégorie définie"),
                "category-tag",
              ),
            );
          else
            for (const id of ids)
              tags.append(
                element(
                  "span",
                  state.setup.indexer_categories[id]?.name || `#${id}`,
                  "category-tag",
                ),
              );
          label.append(tags);
          row.append(label);
          const flow = element("div", undefined, "feed-chip-flow");
          for (const v of chipValues(f)) {
            const s = feedChipState(prefs, f, v);
            const rank =
              s === "prefer" ? (prefs.preferred[f] || []).indexOf(v) + 1 : 0;
            const wrap = element("span", undefined, "assistant-menu-wrap");
            const chip = button(
              ({ prefer: "♡ ", must: "✓ ", avoid: "✕ " }[s] || "") +
                (rank ? `${rank}. ` : "") +
                v,
              () => {
                scope(f);
                feedSetChip(
                  prefs,
                  f,
                  v,
                  FEED_NEXT_CHIP[feedChipState(prefs, f, v)],
                );
                criteriaChanged();
              },
              `feed-chip ${s}`,
            );
            chip.title = stateWords(s);
            chip.dataset.criterion = JSON.stringify([f, v]);
            chip.setAttribute("aria-label", `${v}, ${stateWords(s)}`);
            chip.oncontextmenu = (e) => {
              e.preventDefault();
              if (!(prefs.preferred[f] || []).includes(v)) return;
              aMenu(chip, [
                [
                  feedText("Rank higher", "Classer plus haut"),
                  () => {
                    prefs.preferred[f] = feedMove(prefs.preferred[f], v, -1);
                    criteriaChanged();
                  },
                ],
                [
                  feedText("Rank lower", "Classer plus bas"),
                  () => {
                    prefs.preferred[f] = feedMove(prefs.preferred[f], v, 1);
                    criteriaChanged();
                  },
                ],
              ]);
            };
            chip.onkeydown = (e) => {
              if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
                e.preventDefault();
                chip.oncontextmenu(e);
              }
            };
            wrap.append(chip);
            flow.append(wrap);
          }
          const add = text("");
          add.placeholder = feedText("Add…", "Ajouter…");
          add.className = "feed-chip-add";
          add.onkeydown = (e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            const v = add.value.trim();
            if (!v) return;
            const known =
              chipValues(f).find((x) => x.toLowerCase() === v.toLowerCase()) ||
              v;
            scope(f);
            feedSetChip(
              prefs,
              f,
              known,
              FEED_NEXT_CHIP[feedChipState(prefs, f, known)],
            );
            criteriaChanged();
          };
          flow.append(add);
          row.append(flow);
          return row;
        }),
      );
    }
    if (focused) {
      [...root.querySelectorAll(".feed-chip")]
        .find((chip) => chip.dataset.criterion === focused)
        ?.focus({ preventScroll: true });
      $("dialog").scrollTop = scroll;
    }
  }
  function renderPriorities() {
    const names = feedFieldNames();
    const allowed = [...new Set(categories.get().flatMap(categoryFields)), "size"];
    const rows = prefs.priorities.filter((k) => allowed.includes(k)).map((k, i) => {
      const row = element("div", undefined, "feed-priority");
      let label = `${i + 1}. ${names[k] || k}`;
      if (k === "size" && !prefs.prefer_small)
        label += ` — ${feedText("only when “Prefer smaller releases” is on", "seulement si « Préférer les publications plus petites » est coché")}`;
      const up = aIconButton("▲", feedText("Move up", "Monter"), () => {
        prefs.priorities = feedMove(prefs.priorities, k, -1);
        criteriaChanged();
      });
      const down = aIconButton("▼", feedText("Move down", "Descendre"), () => {
        prefs.priorities = feedMove(prefs.priorities, k, 1);
        criteriaChanged();
      });
      const drop = aIconButton(
        "✕",
        feedText("Remove from ranking", "Retirer du classement"),
        () => {
          prefs.priorities = prefs.priorities.filter((x) => x !== k);
          criteriaChanged();
        },
      );
      up.disabled = i === 0;
      down.disabled = i === prefs.priorities.length - 1;
      drop.disabled = k in prefs.preferred;
      row.append(element("span", label), up, down, drop);
      return row;
    });
    const missing = Object.keys(names).filter(
      (k) => allowed.includes(k) && !prefs.priorities.includes(k),
    );
    const add = element("div", undefined, "feed-priority-add");
    if (missing.length) {
      const select = element("select");
      for (const k of missing) select.append(new Option(names[k], k));
      add.append(
        select,
        button(feedText("Add to ranking", "Ajouter au classement"), () => {
          prefs.priorities.push(select.value);
          criteriaChanged();
        }),
      );
    }
    const small = document.createElement("input");
    small.type = "checkbox";
    small.checked = prefs.prefer_small;
    small.onchange = () => {
      prefs.prefer_small = small.checked;
      if (small.checked) feedEnsurePriorities(prefs);
      criteriaChanged();
    };
    const smallLabel = element("label", undefined, "feed-check");
    smallLabel.append(
      small,
      element(
        "span",
        feedText(
          "Prefer smaller releases",
          "Préférer les publications plus petites",
        ),
      ),
    );
    priorityHost.replaceChildren(...rows, add, smallLabel);
  }
  root.append(chipHost);
  const preservedFold = fold(
    feedText("Saved rules outside selected categories", "Règles enregistrées hors des catégories sélectionnées"),
    element("p", feedText(
      "These rules remain saved. Remove them if they no longer apply; select their category to edit them.",
      "Ces règles restent enregistrées. Supprimez-les si elles ne conviennent plus ; sélectionnez leur catégorie pour les modifier."), "muted"),
    moreHost,
  );
  fold(feedText("What matters most", "Ce qui compte le plus"), priorityHost);
  // 3. What happens
  section(feedText("What happens", "Ce qui se passe"));
  const modeValue = { value: existing?.mode || "review_only" };
  const cards = element("div", undefined, "feed-cards");
  const descriptions = {
    review_only: feedText(
      "New releases appear in the RSS inbox. Nothing is queued.",
      "Les nouvelles publications arrivent dans la boîte RSS. Rien n’est mis en file.",
    ),
    app_queue: feedText(
      "Matching releases join TorrentLinker's queue. Nothing reaches your client until you start it.",
      "Les publications correspondantes rejoignent la file de TorrentLinker. Rien n’atteint votre client avant que vous la démarriez.",
    ),
    automatic_download: feedText(
      "Matching releases are sent to your client on their own, within your limits.",
      "Les publications correspondantes sont envoyées seules à votre client, dans vos limites.",
    ),
  };
  for (const [id, title] of Object.entries(FEED_MODES())) {
    const card = element("label", undefined, "feed-card");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "feed-mode";
    radio.value = id;
    radio.checked = modeValue.value === id;
    radio.onchange = () => {
      modeValue.value = id;
      modeChanged();
    };
    card.append(
      radio,
      element("strong", title),
      element("span", descriptions[id], "muted"),
    );
    cards.append(card);
  }
  root.append(cards);
  const where = element("div", undefined, "feed-where");
  const client = element("select"),
    folder = element("select");
  for (const p of options.clients) client.append(new Option(p.name, p.id));
  client.value = existing?.client_id || state.clientId;
  const loadFolders = () => {
    const names =
      options.clients.find((p) => p.id === client.value)?.folders || [];
    folder.replaceChildren(
      new Option("—", ""),
      ...names.map((p) => new Option(p, p)),
    );
    if (existing?.folder && !names.includes(existing.folder))
      folder.append(new Option(existing.folder, existing.folder));
    folder.value = existing?.folder || "";
  };
  client.onchange = loadFolders;
  loadFolders();
  const wrapField = (label, control, host) => {
    const l = element("label", undefined, "feed-field");
    l.append(element("span", label), control);
    host.append(l);
  };
  wrapField(feedText("Torrent Client", "Client torrent"), client, where);
  wrapField(
    feedText("Download Folder", "Dossier de téléchargement"),
    folder,
    where,
  );
  root.append(where);
  const limits = element("div", undefined, "feed-limits");
  const dailySize = feedSizeField(existing?.daily_bytes ?? 10 * FEED_GIB);
  const dailyCount = spin(existing?.daily_torrents ?? 20, 1000);
  const reserve = feedSizeField(existing?.reserve_bytes ?? 10 * FEED_GIB);
  const hours = feedHoursField(
    existing?.download_hours || Array.from({ length: 24 }, (_, i) => i),
  );
  wrapField(
    feedText("Per day, at most", "Par jour, au plus"),
    dailySize.el,
    limits,
  );
  wrapField(
    feedText("Torrents per day", "Torrents par jour"),
    dailyCount,
    limits,
  );
  wrapField(
    feedText("Keep free on disk", "Garder libre sur le disque"),
    reserve.el,
    limits,
  );
  wrapField(feedText("Allowed hours", "Heures autorisées"), hours.el, limits);
  const approveLabel = element("label", undefined, "feed-check");
  const approve = document.createElement("input");
  approve.type = "checkbox";
  approveLabel.append(
    approve,
    element(
      "span",
      feedText(
        "I explicitly authorize automatic downloads under these limits",
        "J'autorise explicitement les téléchargements automatiques selon ces limites",
      ),
    ),
  );
  limits.append(approveLabel);
  root.append(limits);
  const modeChanged = () => {
    where.hidden = modeValue.value === "review_only";
    limits.hidden = modeValue.value !== "automatic_download";
  };
  modeChanged();
  // 4. How often
  const interval = element("select");
  for (const m of [
    ...new Set([...FEED_INTERVALS, existing?.interval_minutes || 30]),
  ].sort((a, b) => a - b))
    interval.append(new Option(m % 60 === 0 ? `${m / 60} h` : `${m} min`, m));
  interval.value = existing?.interval_minutes || 30;
  const wait = spin(existing?.wait_minutes || 0, 10080);
  const includeLabel = element("label", undefined, "feed-check"),
    replaceLabel = element("label", undefined, "feed-check");
  const include = document.createElement("input"),
    replace = document.createElement("input");
  include.type = replace.type = "checkbox";
  include.checked = Boolean(existing?.include_current);
  replace.checked = Boolean(existing?.replace_pending);
  includeLabel.append(
    include,
    element(
      "span",
      feedText(
        "Include currently available releases",
        "Inclure les torrents actuels",
      ),
    ),
  );
  replaceLabel.append(
    replace,
    element(
      "span",
      feedText(
        "Replace better matches while still pending",
        "Remplacer par un meilleur choix uniquement en attente",
      ),
    ),
  );
  const often = element("div", undefined, "feed-where");
  wrapField(feedText("Check every", "Vérifier toutes les"), interval, often);
  wrapField(
    feedText(
      "Wait for better releases (min)",
      "Attendre de meilleures publications (min)",
    ),
    wait,
    often,
  );
  often.append(includeLabel, replaceLabel);
  fold(feedText("How often", "Fréquence"), often);
  // Advanced
  const advancedText = element("pre");
  const advanced = fold(
    feedText("Advanced: full definition", "Avancé : définition complète"),
    advancedText,
  );
  const advancedRefresh = () => {
    if (!advanced.open) return;
    try {
      advancedText.textContent = JSON.stringify(definition(), null, 2);
    } catch (e) {
      advancedText.textContent = e.message;
    }
  };
  advanced.addEventListener("toggle", advancedRefresh);
  function definition() {
    const hoursValue = hours.get();
    if (modeValue.value === "automatic_download" && !hoursValue.length)
      throw Error(
        feedText(
          "Choose at least one hour for automatic downloads.",
          "Choisissez au moins une heure pour les téléchargements automatiques.",
        ),
      );
    return {
      ...base,
      id: existing?.id || "",
      name: name.value,
      query: queryInput.value,
      categories: categories.get(),
      paused: existing?.paused || false,
      mode: modeValue.value,
      client_id: client.value,
      folder: folder.value,
      interval_minutes: Number(interval.value),
      wait_minutes: Number(wait.value),
      include_current: include.checked,
      replace_pending: replace.checked,
      download_hours: hoursValue,
      daily_bytes: dailySize.get() ?? 0,
      daily_torrents: Number(dailyCount.value),
      reserve_bytes: reserve.get() ?? 0,
      preferences: {
        ...prefs,
        min_size: minSize.get() ?? 0,
        max_size: maxSize.get(),
        min_seeders: Number(minSeeders.value),
      },
    };
  }
  // Live preview: the source is asked once typing pauses; criteria are re-judged locally.
  const strip = element("p", undefined, "feed-strip"),
    stripTitles = element("p", undefined, "feed-strip-titles muted");
  const showStrip = (message, titles = "", warning = false) => {
    strip.textContent = message;
    strip.className = warning ? "feed-strip danger" : "feed-strip";
    stripTitles.textContent = titles;
    stripTitles.hidden = !titles;
  };
  const alive = () =>
    $("dialog").open && content.contains(root) && editorId === editorSequence;
  async function runPreview(strict = false) {
    if (!alive()) return;
    let def;
    try {
      def = definition();
    } catch (e) {
      showStrip(e.message, "", true);
      if (strict) throw e;
      return;
    }
    const token = ++ed.token;
    showStrip(feedText("Checking the source…", "Vérification de la source…"));
    try {
      const result = await feedCall("feeds/preview", def);
      if (token !== ed.token || !alive()) return;
      ed.previewed = JSON.stringify(def);
      ed.previewedAt = Date.now();
      ed.rows = result.rows;
      for (const f of [...FEED_COMMON, ...FEED_MORE]) {
        const counts = {};
        for (const r of ed.rows) {
          const m = r.metadata?.[f];
          for (const v of Array.isArray(m) ? m : [m])
            if (v != null && v !== "") counts[v] = (counts[v] || 0) + 1;
        }
        ed.suggestions[f] = Object.keys(counts)
          .sort((a, b) => counts[b] - counts[a] || a.localeCompare(b))
          .slice(0, 8);
      }
      renderChips();
      summarize(result.evaluations);
    } catch (e) {
      if (token === ed.token && alive()) showStrip(e.message, "", true);
      if (strict) throw e;
    }
  }
  function summarize(evaluations) {
    const judged = ed.rows
      .map((r) => [r, evaluations[r.infohash]])
      .filter(([, e]) => e);
    const matching = judged
      .filter(([, e]) => e.eligible)
      .sort((a, b) =>
        JSON.stringify(a[1].rank).localeCompare(
          JSON.stringify(b[1].rank),
          undefined,
          { numeric: true },
        ),
      );
    const unknown = judged.filter(
      ([, e]) => e.unknown.length && !e.excluded.length,
    ).length;
    let message = feedText(
      `Would match now: ${matching.length} of ${ed.rows.length} releases`,
      `Correspondrait maintenant : ${matching.length} publications sur ${ed.rows.length}`,
    );
    if (unknown)
      message +=
        " · " +
        feedText(
          `${unknown} can't be checked (missing details)`,
          `${unknown} non vérifiables (informations manquantes)`,
        );
    showStrip(
      message,
      matching
        .slice(0, 3)
        .map(([r]) => r.title)
        .join("\n"),
    );
  }
  let judgeTimer, sourceTimer;
  function judge() {
    if (!ed.rows.length) return;
    clearTimeout(judgeTimer);
    judgeTimer = setTimeout(async () => {
      try {
        const r = await feedCall("feeds/judge", {
          subscription: definition(),
          rows: ed.rows,
        });
        if (alive()) summarize(r.evaluations);
      } catch (e) {
        if (alive()) showStrip(e.message, "", true);
      }
    }, 250);
  }
  function sourceChanged() {
    clearTimeout(sourceTimer);
    sourceTimer = setTimeout(() => runPreview(), 1200);
  }
  queryInput.addEventListener("input", sourceChanged);
  minSize.onchange(judge);
  maxSize.onchange(judge);
  minSeeders.addEventListener("input", judge);
  renderChips();
  renderPriorities();
  let saving = false;
  const footer = element("div", undefined, "feed-footer");
  footer.append(element("div", undefined, "feed-strip-box"));
  footer.firstChild.append(strip, stripTitles);
  footer.append(
    button(
      feedText("Check again", "Vérifier à nouveau"),
      () => runPreview(),
      "quiet",
    ),
    element("span", undefined, "spacer"),
    button(feedText("Cancel", "Annuler"), () => $("dialog").close(), "quiet"),
    button(
      feedText("Save", "Enregistrer"),
      async () => {
        if (saving || !alive()) return;
        saving = true;
        const saveButton = footer.querySelector(".primary");
        saveButton.disabled = true;
        clearTimeout(sourceTimer);
        try {
          const def = definition();
          const sourceMoved =
            !existing ||
            def.query !== existing.query ||
            JSON.stringify(def.categories) !==
              JSON.stringify(existing.categories);
          const fresh =
            ed.previewed === JSON.stringify(def) &&
            Date.now() - ed.previewedAt < 840000;
          if (sourceMoved && !fresh) await runPreview(true);
          if (!alive()) return;
          if (JSON.stringify(definition()) !== JSON.stringify(def))
            throw Error(
              feedText(
                "The form changed. Save again to review the new values.",
                "Le formulaire a changé. Enregistrez à nouveau les nouvelles valeurs.",
              ),
            );
          await feedCall("feeds", {
            subscription: def,
            approve_automatic: approve.checked,
          });
          if (alive()) {
            $("dialog").close();
            await navigate("feeds");
          }
        } finally {
          saving = false;
          saveButton.disabled = false;
        }
      },
      "primary",
    ),
  );
  footer.append(button(feedText("Share rules","Partager les règles"),()=>{const def=definition();return communityShareDialog("rss",{},{rules:[{name:"Shared rule",query:def.query,categories:def.categories,preferences:def.preferences,include:[],exclude:[]}]})}));
  content.append(footer);
  $("dialog").showModal();
}

async function feedSavedSelections() {
  const selections = await api("feed-selections");
  const content = $("dialog-content");
  content.replaceChildren(
    element("h2", feedText("Saved selections", "Sélections enregistrées")),
  );
  for (const saved of selections)
    content.append(
      button(
        `${saved.name} · ${saved.hashes.length} · ${new Date(saved.created * 1000).toLocaleString()}`,
        async () => feedReport(await api(`feed-selections/${saved.id}`)),
      ),
    );
  $("dialog").showModal();
}
async function compareFeedClients() {
  const options = await api("feed-options");
  const content = $("dialog-content");
  content.replaceChildren(
    element("h2", feedText("Compare clients", "Comparer les clients")),
  );
  const choices = options.clients.map((client) => {
    const label = element("label", client.name),
      input = element("input");
    input.type = "checkbox";
    input.checked = true;
    label.append(input);
    content.append(label);
    return {
      client,
      input,
    };
  });
  content.append(
    button(feedText("Compare", "Comparer"), async () => {
      const client_ids = choices
        .filter((value) => value.input.checked)
        .map((value) => value.client.id);
      if (!client_ids.length)
        throw Error(
          feedText(
            "Choose at least one Torrent Client.",
            "Choisissez au moins un client torrent.",
          ),
        );
      const result = await feedCall("feed-inbox/compare", {
        client_ids,
      });
      $("dialog").close();
      await loadFeeds();
      feedReport(result);
    }),
  );
  $("dialog").showModal();
}
