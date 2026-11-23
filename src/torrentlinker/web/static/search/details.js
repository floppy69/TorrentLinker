async function loadDetail(tab) {
  const row = tab.row,
    content = tab.content,
    epoch = generation;
  const revision = (tab.revision = (tab.revision || 0) + 1);
  const current = () =>
    generation === epoch &&
    detailTabs.get(row.hash) === tab &&
    tab.revision === revision;
  const chip = (text, kind) =>
    element("span", text, "dt-chip" + (kind ? " dt-" + kind : ""));
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
    const link = element(
      "a",
      say("Open on website", "Ouvrir sur le site"),
      "button-link",
    );
    link.href = row.website;
    link.target = env.mode === "desktop" ? "_self" : "_blank";
    link.rel = "noopener noreferrer";
    head.append(link);
  }
  if (row.published_at)
    byline.textContent =
      say("Published ", "Publié ") +
      new Date(row.published_at * 1000).toLocaleString(
        language === "fr" ? "fr-FR" : "en-GB",
      );
  const seeds = chip(
    say(`${row.seeders} seeders`, `${row.seeders} seeders`),
    "up",
  );
  stats.append(
    chip(bytes(row.size)),
    seeds,
    chip(`≈ ${num(row.zen)} Zen / ${say("day", "j")}`, "zen"),
  );
  if (row.note != null) stats.append(chip(`≈ ${num(row.note)} Note`, "zen"));
  const bar = element("div", undefined, "dt-bar");
  bar.append(
    button(
      say("Add to queue", "Ajouter à la file"),
      () =>
        row.queueSource === "feed"
          ? request("feed-queue", { hashes: [row.hash] })
          : searchEnqueue([row.hash]),
      "primary",
    ),
  );
  content.replaceChildren(
    head,
    element("h2", row.title, "dt-title"),
    byline,
    banner,
    stats,
    hash,
    facts,
    extras,
    card,
    ids,
    trust,
    bar,
  );
  if (row.queueSource !== "feed")
    bar.append(
      button(
        say("Download now", "Télécharger maintenant"),
        () => searchEnqueue([row.hash], true),
        "primary",
      ),
    );
  const destination = element(
    "span",
    say("Configured category folder", "Dossier configuré pour la catégorie"),
    "muted",
  );
  bar.prepend(destination);
  bar.append(
    button(
      say("Retry", "Réessayer"),
      () => {
        tab.document = null;
        return guard(() => loadDetail(tab));
      },
      "quiet",
    ),
  );
  if (env.readonly)
    bar.replaceChildren(
      button(
        say("Retry", "Réessayer"),
        () => {
          tab.document = null;
          return guard(() => loadDetail(tab));
        },
        "quiet",
      ),
    );
  if (env.indexer && new URL(env.indexer).hostname !== "c411.org") return;
  const r = tab.document || (await request("detail", { hash: row.hash }));
  if (!current()) return;
  tab.document = r;
  if (r.release_score) extras.append(releaseScoreDetails(r.release_score));
  {
    const info = r.info || {};
    if (info.seeders != null) seeds.textContent = `${info.seeders} seeders`;
    const kind = info.subcategory || info.category;
    if (kind) {
      badge.textContent = kind.toUpperCase();
      badge.hidden = false;
    }
    if (info.exclusive)
      flags.append(chip("★ " + say("Exclusive", "Exclusivité"), "warn"));
    if (info.low_bitrate)
      flags.append(chip(say("Low bitrate", "Bitrate faible"), "warn"));
    const tr = info.trust || {};
    flags.append(
      chip(
        tr.tested ? say("Tested", "Testé") : say("Not tested", "Non testé"),
        tr.tested ? "ok" : "warn",
      ),
    );
    const by = [];
    if (info.uploader)
      by.push(say(`Sent by ${info.uploader}`, `Envoyé par ${info.uploader}`));
    if (info.team) by.push(`Team ${info.team}`);
    if (info.created_at)
      by.push(
        say("Published ", "Publié ") +
          new Date(info.created_at * 1000).toLocaleString(
            language === "fr" ? "fr-FR" : "en-GB",
          ),
      );
    if (by.length) byline.textContent = by.join(" · ");
    if (tr.status && !tr.tested) {
      banner.append(
        element(
          "strong",
          say(
            "Torrent not tested by the community",
            "Torrent non testé par la communauté",
          ),
        ),
        element(
          "p",
          say(
            "This torrent has not yet received enough trust votes. Be careful and check the content before use.",
            "Ce torrent n’a pas encore reçu suffisamment de votes de confiance. Soyez prudent et vérifiez le contenu avant utilisation.",
          ),
        ),
      );
      banner.hidden = false;
    }
    if (info.leechers !== null && info.leechers !== undefined)
      stats.append(
        chip(
          say(`${info.leechers} leechers`, `${info.leechers} leechers`),
          "down",
        ),
      );
    if (info.completions !== null && info.completions !== undefined)
      stats.append(
        chip(
          say(`${info.completions} completed`, `${info.completions} complétés`),
          "done",
        ),
      );
    if (info.seeders === 0)
      stats.append(chip(say("Seeds wanted", "Demande de seeds"), "warn"));
    if (r.files?.length)
      hash.textContent += `  ·  ${say("Files", "Fichiers")}: ${r.files.length}`;
    for (const [name, values] of info.facts || [])
      facts.append(chip(`${name}: ${values.join(", ")}`));
    const m = info.media;
    if (m && (m.title || m.tmdb_id)) {
      if (info.poster) {
        const img = element("img", undefined, "dt-poster");
        img.alt = "";
        loadPoster(img, info.poster);
        img.onerror = () => img.remove();
        card.append(img);
      }
      const text = element("div");
      const year = m.year ? ` (${m.year})` : "";
      const type = { movie: "Film", tv: say("TV series", "Série TV") }[m.kind];
      text.append(
        element(
          "h3",
          m.title + year + (type ? "  ·  " + type : ""),
          "dt-card-title",
        ),
      );
      if (m.original_title && m.original_title !== m.title)
        text.append(element("p", m.original_title, "muted"));
      if (m.genres?.length) {
        const g = element("div", undefined, "dt-row");
        m.genres.forEach((x) => g.append(chip(x)));
        text.append(g);
      }
      const line = [];
      if (m.rating)
        line.push(
          `★ ${m.rating.toFixed(1)}/10 TMDB` +
            (m.votes ? ` · ${m.votes} ${say("votes", "votes")}` : ""),
        );
      if (m.runtime) line.push(`${m.runtime} min`);
      if (m.directors?.length)
        line.push(say("Director: ", "Réalisateur : ") + m.directors.join(", "));
      if (line.length) text.append(element("p", line.join("  ·  ")));
      if (m.cast?.length)
        text.append(
          element(
            "p",
            say("With ", "Avec ") + m.cast.join(", ") + "…",
            "muted",
          ),
        );
      const links = element("div", undefined, "dt-row");
      const site = (label, url) => {
        const a = element("a", label);
        a.href = url;
        a.target = env.mode === "desktop" ? "_self" : "_blank";
        a.rel = "noopener noreferrer";
        links.append(a);
      };
      if (m.tmdb_id)
        site(
          say("View on TMDB", "Voir sur TMDB"),
          `https://www.themoviedb.org/${m.kind === "tv" ? "tv" : "movie"}/${m.tmdb_id}`,
        );
      if (m.imdb_id)
        site(
          say("View on IMDb", "Voir sur IMDb"),
          `https://www.imdb.com/title/${m.imdb_id}/`,
        );
      text.append(links);
      card.append(text);
      card.hidden = false;
      if (m.tmdb_id) ids.append(chip(`TMDB ${m.tmdb_id}`, "id"));
      if (m.imdb_id) ids.append(chip(`IMDb ${m.imdb_id}`, "id"));
    }
    if (tr.status || tr.positive || tr.negative) {
      trust.append(
        element("strong", say("Community trust", "Confiance communautaire")),
        element(
          "p",
          `${tr.tested ? say("Tested", "Testé") : say("Not tested", "Non testé")}  ·  👍 ${tr.positive}  ·  👎 ${tr.negative}` +
            (tr.required && !tr.tested
              ? `  ·  ${say(`(${tr.required} votes required)`, `(${tr.required} votes requis)`)}`
              : ""),
        ),
      );
      trust.hidden = false;
    }
    if (r.nfo) {
      const d = element("details");
      d.append(
        element("summary", say("Show the NFO", "Afficher le NFO")),
        element("pre", r.nfo),
      );
      extras.append(d);
    }
    if (r.files?.length) {
      const d = element("details");
      d.append(
        element(
          "summary",
          say(
            `Show the files (${r.files.length})`,
            `Afficher les fichiers (${r.files.length})`,
          ),
        ),
      );
      const list = element("ul", undefined, "dt-files");
      r.files.forEach(([path, size]) =>
        list.append(element("li", `${path}  ·  ${bytes(size)}`)),
      );
      d.append(list);
      extras.append(d);
    }
    const description = element("div", undefined, "description");
    description.innerHTML = r.description.replace(
      /src="preview-image:(\d+)"/g,
      'data-preview-index="$1"',
    );
    description.querySelectorAll("a").forEach((a) => {
      a.target = env.mode === "desktop" ? "_self" : "_blank";
      a.rel = "noopener noreferrer";
    });
    content.insertBefore(description, bar);
    await loadDetailImages(tab, description, r.images || [], current);
  }
}

const detailTabs = new Map();
let selectedDetail = null;
function clearDetailTabs() {
  detailTabs.clear();
  selectedDetail = null;
  $("detail-pages").replaceChildren();
  renderDetailTabs();
}
function renderDetailTabs() {
  const host = $("detail-tabs");
  host.hidden = !detailTabs.size || env.standalone;
  host.replaceChildren();
  const tabs = element("div");
  tabs.setAttribute("role", "tablist");
  const addTab = (key, title, callback) => {
    const wrap = element("div", undefined, "detail-tab");
    const tab = button(title, callback, "quiet");
    tab.title = title;
    tab.setAttribute("role", "tab");
    tab.setAttribute(
      "aria-selected",
      String(key === (activePage === "details" ? selectedDetail : null)),
    );
    tab.tabIndex =
      key === (activePage === "details" ? selectedDetail : null) ? 0 : -1;
    tab.onkeydown = (e) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const keys = [null, ...detailTabs.keys()],
        index = keys.indexOf(key);
      const target =
        e.key === "Home"
          ? 0
          : e.key === "End"
            ? keys.length - 1
            : (index + (e.key === "ArrowLeft" ? -1 : 1) + keys.length) %
              keys.length;
      if (keys[target] === null) navigate("search");
      else selectDetail(keys[target]);
      host.querySelectorAll("[role=tab]")[target]?.focus();
    };
    wrap.append(tab);
    if (key !== null) {
      wrap.draggable = true;
      wrap.ondragstart = (e) => e.dataTransfer.setData("text/plain", key);
      wrap.ondragover = (e) => e.preventDefault();
      wrap.ondrop = (e) => {
        e.preventDefault();
        const source = e.dataTransfer.getData("text/plain");
        if (!detailTabs.has(source) || source === key) return;
        const entries = [...detailTabs].filter(([id]) => id !== source);
        entries.splice(
          entries.findIndex(([id]) => id === key),
          0,
          [source, detailTabs.get(source)],
        );
        detailTabs.clear();
        entries.forEach(([id, value]) => detailTabs.set(id, value));
        renderDetailTabs();
      };
      const close = button("×", () => closeDetail(key), "quiet");
      close.setAttribute("aria-label", say("Close tab", "Fermer l’onglet"));
      wrap.append(close);
      wrap.onauxclick = (e) => {
        if (e.button === 1) {
          e.preventDefault();
          closeDetail(key);
        }
      };
    }
    tabs.append(wrap);
  };
  addTab(null, say("Search", "Recherche"), () => navigate("search"));
  for (const [key, tab] of detailTabs)
    addTab(key, tab.row.title, () => selectDetail(key));
  const menu = element("details", undefined, "fdrop");
  menu.append(element("summary", say("Open tabs", "Onglets ouverts"), "chip"));
  const items = element("div", undefined, "fdrop-panel");
  for (const [key, tab] of detailTabs)
    items.append(
      button(
        tab.row.title,
        () => {
          menu.open = false;
          selectDetail(key);
        },
        "quiet",
      ),
    );
  items.append(
    button(say("Close other tabs", "Fermer les autres onglets"), () => {
      for (const key of [...detailTabs.keys()])
        if (key !== selectedDetail) closeDetail(key);
    }),
  );
  items.append(
    button(
      say("Close all torrent tabs", "Fermer tous les onglets torrent"),
      () => {
        clearDetailTabs();
        navigate("search");
      },
    ),
  );
  if (!env.readonly) {
    items.append(
      button(say("Queue all tabs", "Mettre tous les onglets en file"), () =>
        queueDetailTabs(false),
      ),
    );
    if ([...detailTabs.values()].every((tab) => tab.row.queueSource !== "feed"))
      items.append(
        button(say("Download all tabs", "Télécharger tous les onglets"), () =>
          queueDetailTabs(true),
        ),
      );
  }
  menu.append(items);
  host.append(tabs, menu);
}
function selectDetail(key) {
  if (!detailTabs.has(key)) return;
  selectedDetail = key;
  activePage = "details";
  $("results").hidden = $("queue").hidden = true;
  $("detail-pages").hidden = false;
  for (const [hash, tab] of detailTabs) tab.content.hidden = hash !== key;
  hideHover();
  renderDetailTabs();
}
function closeDetail(key) {
  const tab = detailTabs.get(key);
  if (!tab) return;
  tab.content.remove();
  detailTabs.delete(key);
  if (selectedDetail === key) {
    selectedDetail = [...detailTabs.keys()].at(-1) || null;
    if (selectedDetail) selectDetail(selectedDetail);
    else navigate("search");
  }
  renderDetailTabs();
}
async function openDetail(row) {
  if (detailTabs.has(row.hash)) {
    selectDetail(row.hash);
    return;
  }
  const tab = { row, content: element("article", undefined, "torrent-detail") };
  detailTabs.set(row.hash, tab);
  $("detail-pages").append(tab.content);
  selectDetail(row.hash);
  try {
    await loadDetail(tab);
  } catch (error) {
    if (detailTabs.get(row.hash) === tab)
      tab.content.append(element("p", error.message, "muted"));
  }
}
async function loadDetailImages(tab, description, urls, current) {
  const g = generation;
  for (const image of description.querySelectorAll("[data-preview-index]")) {
    const position = Number(image.dataset.previewIndex);
    const url = urls[position];
    if (!url) continue;
    const status = element("span", undefined, "detail-image-error");
    const link = element("a", say("Open image", "Ouvrir l’image"));
    link.href = url;
    link.target = env.mode === "desktop" ? "_self" : "_blank";
    link.rel = "noopener noreferrer";
    const label = element(
      "span",
      say("Loading image…", "Chargement de l’image…"),
    );
    const retry = button(say("Retry images", "Réessayer les images"), () =>
      load(),
    );
    retry.hidden = true;
    status.append(label, link, retry);
    image.after(status);
    image.hidden = true;
    let retryAt = 0;
    async function load() {
      if (retryAt > Date.now() || g !== generation || !current()) return;
      retry.disabled = true;
      try {
        const result = await request("detail-image", {
          hash: tab.row.hash,
          position,
        });
        if (g !== generation || !current()) return;
        if (result.src) {
          image.src = result.src;
          image.hidden = false;
          status.remove();
        } else {
          label.textContent = say("Image unavailable.", "Image indisponible.");
          retry.hidden = false;
          retryAt = Date.now() + Math.max(0, result.retry_after || 0) * 1000;
          if (retryAt > Date.now()) {
            const seconds = Math.ceil(result.retry_after);
            label.textContent = say(
              `Image host busy. Retry in ${seconds}s.`,
              `Hébergeur occupé. Réessayez dans ${seconds}s.`,
            );
            setTimeout(() => {
              retry.disabled = false;
            }, seconds * 1000);
          }
        }
      } catch (error) {
        label.textContent = error.message;
        retry.hidden = false;
      } finally {
        retry.disabled = retryAt > Date.now();
      }
    }
    await load();
  }
}
window.searchTabShortcut = (command) => {
  if (command === "close") {
    if (activePage === "details") closeDetail(selectedDetail);
    return;
  }
  const keys = [null, ...detailTabs.keys()],
    index = keys.indexOf(activePage === "details" ? selectedDetail : null);
  const key =
    keys[
      (index + (command === "previous" ? -1 : 1) + keys.length) % keys.length
    ];
  if (key === null) navigate("search");
  else selectDetail(key);
};

window.searchTransport.then(() => window.searchReady());

window.addEventListener("message", (event) => {
  if (
    event.source === parent &&
    event.origin === location.origin &&
    event.data?.type === "search-open-detail"
  )
    guard(() => openDetail(event.data.row));
});

async function queueDetailTabs(now) {
  const feeds = [...detailTabs]
    .filter(([, tab]) => tab.row.queueSource === "feed")
    .map(([hash]) => hash);
  const search = [...detailTabs.keys()].filter((hash) => !feeds.includes(hash));
  if (feeds.length) await request("feed-queue", { hashes: feeds });
  if (search.length) await searchEnqueue(search, now);
}
