"use strict";
const $ = (id) => document.getElementById(id);
const say = (en, fr) => TLPanel.t(fr, en);
function element(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
let profileClients = null,
  profileDays = 30,
  profileAvatar = "";
const SVG = "http://www.w3.org/2000/svg";
const profileNumber = (v, digits = 1) =>
  typeof v === "number"
    ? v.toLocaleString(document.documentElement.lang, {
        maximumFractionDigits: digits,
      })
    : "—";
const profileSigned = (v, format) =>
  typeof v === "number" ? `${v >= 0 ? "+" : "−"}${format(Math.abs(v))}` : "";
const profileClassNames = {
  tanker: "Tanker",
  "swarm-keeper": "Swarm Keeper",
  reuploader: "Reuploader",
};
const profileDate = (iso) =>
  iso
    ? new Date(`${iso}T00:00:00`).toLocaleDateString(
        document.documentElement.lang,
        { day: "numeric", month: "short", year: "numeric" },
      )
    : "—";
function profileAgo(timestamp) {
  if (!timestamp) return "—";
  const seconds = Math.max(0, Date.now() / 1000 - timestamp);
  if (seconds < 60) return say("now", "à l’instant");
  if (seconds < 3600)
    return `${Math.floor(seconds / 60)} min ${say("ago", "")}`.trim();
  if (seconds < 86400)
    return `${Math.floor(seconds / 3600)} h ${say("ago", "")}`.trim();
  return `${Math.floor(seconds / 86400)} ${say("d ago", "j")}`;
}
// Bytes split into value and unit, for tiles that show the unit smaller: two
// decimals from TiB, as in the mockup.
function profileBytesParts(v) {
  if (typeof v !== "number") return ["—", ""];
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let n = Math.abs(v),
    i = 0;
  while (n >= 1024 && i < 5) {
    n /= 1024;
    i++;
  }
  return [(v < 0 ? "−" : "") + n.toFixed(i >= 4 ? 2 : i ? 1 : 0), units[i]];
}
const profileBytes = (v) =>
  typeof v === "number" ? profileBytesParts(v).join(" ") : "—";
function svg(tag, attributes = {}) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attributes)) e.setAttribute(k, v);
  return e;
}
const profilePath = (points) =>
  points
    .map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`)
    .join(" ");
function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / p / 2) * 2 * p;
}
function eyebrow(text, ...sources) {
  const p = element("p", text, "pf-eyebrow");
  for (const source of sources) p.append(element("span", source, "pf-src"));
  return p;
}
function row(label, value, cls) {
  const r = element("div", undefined, "pf-row");
  r.append(element("span", label), element("span", value, cls));
  return r;
}
const collecting = () =>
  say("History is being collected", "Historique en cours de collecte");

function showProfileHeader(o, data) {
  const h = o.header,
    avatar = $("profile-avatar");
  // The avatar comes from this server's cache; the initial stays when there is none.
  if (profileAvatar && avatar.dataset.token !== profileAvatar) {
    const img = element("img");
    img.alt = "";
    img.src = profileAvatar;
    img.onerror = () => {
      avatar.dataset.token = "";
      avatar.textContent = h.initial;
    };
    avatar.replaceChildren(img);
    avatar.dataset.token = profileAvatar;
  } else if (!profileAvatar) {
    avatar.dataset.token = "";
    avatar.textContent = h.initial;
  }
  $("profile-username").textContent =
    h.username ||
    say("Connect your c411 account", "Connectez votre compte c411");
  $("profile-meta").textContent = [
    h.class || "—",
    `${say("Level", "Niveau")} ${profileNumber(h.level)}`,
    `${say("Team", "Équipe")} ${h.team || "—"}`,
    `${say("Member since", "Membre depuis")} ${profileDate(h.member_since)}`,
  ].join(" · ");
  const badges = [];
  if (data.api) {
    badges.push(
      h.download.allowed
        ? ["ok", say("Download allowed", "Téléchargement autorisé")]
        : [
            "err",
            `${say("Download blocked", "Téléchargement bloqué")}${h.download.reason ? " · " + h.download.reason : ""}`,
          ],
    );
    if (h.freeleech.active)
      badges.push(["info", ["Freeleech", ...h.freeleech.sources].join(" · ")]);
  }
  badges.push([
    !data.api ? "off" : h.api.stale || data.error ? "warn" : "ok",
    `API · ${profileAgo(h.api.updated_at)}`,
  ]);
  badges.push(
    h.companion.received_at
      ? [
          h.companion.stale ? "warn" : "ok",
          `${say("Companion", "Extension")} · ${profileAgo(h.companion.received_at)}`,
        ]
      : [
          "off",
          `${say("Companion", "Extension")} · ${h.companion.paired ? say("waiting", "en attente") : say("not connected", "non connectée")}`,
        ],
  );
  $("profile-badges").replaceChildren(
    ...badges.map(([cls, text]) => element("span", text, `pf-pill ${cls}`)),
  );
}

function spark(values, color) {
  const w = 120,
    h = 30,
    lo = Math.min(...values),
    hi = Math.max(...values);
  const points = values.map((v, i) => [
    (i / (values.length - 1)) * w,
    h - 3 - ((v - lo) / (hi - lo || 1)) * (h - 6),
  ]);
  const s = svg("svg", {
    viewBox: `0 0 ${w} ${h}`,
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  const last = points.at(-1);
  s.append(
    svg("path", {
      d: `${profilePath(points)} L${w} ${h} L0 ${h} Z`,
      fill: color,
      opacity: ".12",
    }),
    svg("path", {
      d: profilePath(points),
      fill: "none",
      stroke: color,
      "stroke-width": "1.5",
      "vector-effect": "non-scaling-stroke",
    }),
    svg("circle", { cx: last[0], cy: last[1], r: "2.2", fill: color }),
  );
  return s;
}

function showProfileTiles(o) {
  const t = o.tiles,
    period = o.span ? `${o.span} ${say("d", "j")}` : say("all", "tout");
  const ratio = (v) => (typeof v === "number" ? v.toFixed(2) : "—");
  const zen = (v) => profileNumber(v, 0);
  const tiles = [
    [
      "ratio",
      say("Ratio", "Ratio"),
      [ratio(t.ratio.value), ""],
      ratio,
      "var(--pf-ratio)",
    ],
    [
      "buffer",
      say("Buffer", "Tampon"),
      profileBytesParts(t.buffer.value),
      profileBytes,
      "var(--pf-brand)",
    ],
    [
      "uploaded",
      say("Uploaded", "Envoyé"),
      profileBytesParts(t.uploaded.value),
      profileBytes,
      "var(--pf-up)",
    ],
    [
      "downloaded",
      say("Downloaded", "Téléchargé"),
      profileBytesParts(t.downloaded.value),
      profileBytes,
      "var(--pf-down)",
    ],
    ["zen", "Zen", [zen(t.zen.value), ""], zen, "var(--pf-zen)"],
    [
      "active_seeds",
      say("Active seeds", "Seeds actifs"),
      [profileNumber(t.active_seeds.value, 0), ""],
      zen,
      "var(--pf-brand)",
    ],
  ];
  $("profile-tiles").replaceChildren(
    ...tiles.map(([key, label, [value, unit], format, color]) => {
      const tile = element("div", undefined, "pf-kpi");
      const v = element("div", value, "v");
      if (unit) v.append(element("small", unit));
      const change = element("div", undefined, "d");
      if (typeof t[key].change === "number") {
        change.append(
          element(
            "span",
            profileSigned(t[key].change, format),
            t[key].change >= 0 ? "pos" : "neg",
          ),
          ` · ${period}`,
        );
      }
      tile.append(element("div", label, "k"), v, change);
      tile.append(
        t[key].trend.length > 1
          ? spark(t[key].trend, color)
          : element("div", o.period ? "" : collecting(), "pf-spark-empty"),
      );
      return tile;
    }),
  );
}

function chartHead(title, range, legend) {
  const head = element("div", undefined, "pf-chart-head");
  const left = element("div");
  left.append(element("h3", title), element("div", range, "pf-range"));
  const keys = element("div", undefined, "pf-legend");
  for (const [label, color, line] of legend) {
    const item = element("span");
    const dot = element("i");
    dot.style.background = color;
    if (line) Object.assign(dot.style, { borderRadius: "0", height: "2px" });
    item.append(dot, label);
    keys.append(item);
  }
  head.append(left, keys);
  return head;
}
function foot(items) {
  const f = element("div", undefined, "pf-foot");
  for (const [label, value] of items) {
    const d = element("div", label);
    d.append(element("b", value));
    f.append(d);
  }
  return f;
}
const axisText = (x, y, text, anchor = "start") => {
  const t = svg("text", { x, y, "text-anchor": anchor });
  t.textContent = text;
  return t;
};

let chartOverview = null;
function chartWidth(host) {
  const style = getComputedStyle(host);
  return Math.max(
    200,
    host.clientWidth -
      parseFloat(style.paddingLeft) -
      parseFloat(style.paddingRight),
  );
}
const chartWidths = new WeakMap();
const chartResize = new ResizeObserver((entries) => {
  let changed = false;
  for (const entry of entries) {
    if (chartWidths.get(entry.target) !== entry.contentRect.width) {
      chartWidths.set(entry.target, entry.contentRect.width);
      changed = true;
    }
  }
  if (changed && chartOverview) {
    const scroll = { left: window.scrollX, top: window.scrollY };
    showProfileCharts(chartOverview);
    window.scrollTo(scroll);
  }
});
for (const id of ["profile-volumes", "profile-zen-chart"])
  chartResize.observe($(id));

function showProfileCharts(o) {
  chartOverview = o;
  const p = o.period;
  const range = p ? `${p.first} → ${p.last}` : "";
  const volumes = $("profile-volumes"),
    zenChart = $("profile-zen-chart");
  volumes.replaceChildren(
    chartHead(say("Volumes", "Volumes"), range, [
      [say("Uploaded", "Envoyé"), "var(--pf-up)"],
      [say("Downloaded", "Téléchargé"), "var(--pf-down)"],
      [say("Buffer", "Tampon"), "var(--muted)"],
    ]),
  );
  zenChart.replaceChildren(
    chartHead(say("Zen balance & ratio", "Solde Zen et ratio"), range, [
      ["Zen", "var(--pf-zen)"],
      ["Ratio", "var(--pf-ratio)", true],
    ]),
  );
  if (!p) {
    volumes.append(element("p", collecting(), "pf-empty"));
    zenChart.append(element("p", collecting(), "pf-empty"));
    return;
  }
  const s = p.series,
    n = s.length;
  // Points sit at their dates, so days the app did not run keep their width.
  const t0 = Date.parse(s[0].day),
    tSpan = Date.parse(s[n - 1].day) - t0 || 1;
  const at = (i) => (Date.parse(s[i].day) - t0) / tSpan;
  const dateTicks = (L, pw, h, middle) => {
    const ticks = [
      axisText(L, h - 8, s[0].day, "start"),
      axisText(L + pw, h - 8, s[n - 1].day, "end"),
    ];
    if (middle)
      ticks.push(
        axisText(
          L + pw / 2,
          h - 8,
          new Date(t0 + tSpan / 2).toISOString().slice(0, 10),
          "middle",
        ),
      );
    return ticks;
  };
  // Volumes: uploaded, downloaded and dashed buffer, right axis in bytes.
  {
    const W = chartWidth(volumes),
      H = 220,
      L = 8,
      R = 64,
      T = 10,
      B = 26,
      pw = W - L - R,
      ph = H - T - B;
    const max = niceMax(
      Math.max(
        ...s.map((d) => d.uploaded ?? 0),
        ...s.map((d) => d.downloaded ?? 0),
      ),
    );
    const low = Math.min(0, ...s.map((d) => d.buffer ?? 0)); // a negative buffer goes below zero
    const x = (i) => L + at(i) * pw,
      y = (v) => T + ph - ((v - low) / (max - low)) * ph;
    const chart = svg("svg", {
      class: "pf-chart",
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": say(
        "Upload and download totals over time",
        "Totaux envoyés et téléchargés dans le temps",
      ),
    });
    for (let k = 0; k <= 4; k++) {
      const v = low + ((max - low) * k) / 4;
      chart.append(
        svg("line", {
          x1: L,
          x2: L + pw,
          y1: y(v),
          y2: y(v),
          stroke: "var(--line)",
        }),
        axisText(W - R + 6, y(v) + 3, v ? profileBytes(v) : "0"),
      );
    }
    chart.append(...dateTicks(L, pw, H, true));
    const line = (key) =>
      s
        .map((d, i) => (typeof d[key] === "number" ? [x(i), y(d[key])] : null))
        .filter(Boolean);
    const up = line("uploaded"),
      down = line("downloaded"),
      buffer = line("buffer");
    for (const [points, color] of [
      [up, "var(--pf-up)"],
      [down, "var(--pf-down)"],
    ]) {
      if (points.length < 2) continue;
      chart.append(
        svg("path", {
          d: `${profilePath(points)} L${points.at(-1)[0]} ${y(0)} L${points[0][0]} ${y(0)} Z`,
          fill: color,
          opacity: ".14",
        }),
        svg("path", {
          d: profilePath(points),
          fill: "none",
          stroke: color,
          "stroke-width": "2",
        }),
        svg("circle", {
          cx: points.at(-1)[0],
          cy: points.at(-1)[1],
          r: "3.5",
          fill: color,
        }),
      );
    }
    if (buffer.length > 1)
      chart.append(
        svg("path", {
          d: profilePath(buffer),
          fill: "none",
          stroke: "var(--muted)",
          "stroke-dasharray": "3 3",
          "stroke-width": "1.2",
          opacity: ".7",
        }),
      );
    volumes.append(
      chart,
      foot([
        [
          say("Uploaded in period", "Envoyé sur la période"),
          profileBytes(p.change.uploaded),
        ],
        [
          say("Downloaded in period", "Téléchargé sur la période"),
          profileBytes(p.change.downloaded),
        ],
        [
          say("Average upload", "Envoi moyen"),
          typeof p.average.uploaded === "number"
            ? `${profileBytes(p.average.uploaded)}/${say("d", "j")}`
            : "—",
        ],
      ]),
    );
  }
  // Zen balance (left axis) and ratio (right axis, dashed).
  {
    const W = chartWidth(zenChart),
      H = 220,
      L = 40,
      R = 40,
      T = 10,
      B = 26,
      pw = W - L - R,
      ph = H - T - B;
    const zmax = niceMax(Math.max(...s.map((d) => d.balance ?? 0)));
    const ratios = s.map((d) => d.ratio).filter((v) => typeof v === "number");
    let rlo = ratios.length ? Math.floor(Math.min(...ratios) * 2) / 2 : 0;
    let rhi = ratios.length ? Math.ceil(Math.max(...ratios) * 2) / 2 : 1;
    if (rhi <= rlo) rhi = rlo + 0.5;
    const x = (i) => L + at(i) * pw,
      y = (v) => T + ph - (v / zmax) * ph,
      ry = (v) => T + ph - ((v - rlo) / (rhi - rlo)) * ph;
    const chart = svg("svg", {
      class: "pf-chart",
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": say(
        "Zen balance and ratio over time",
        "Solde Zen et ratio dans le temps",
      ),
    });
    for (let k = 0; k <= 4; k++) {
      const yy = T + ph * (1 - k / 4);
      chart.append(
        svg("line", {
          x1: L,
          x2: L + pw,
          y1: yy,
          y2: yy,
          stroke: "var(--line)",
        }),
        axisText(L - 6, yy + 3, profileNumber((zmax * k) / 4, 0), "end"),
        axisText(
          W - R + 6,
          yy + 3,
          ratios.length ? (rlo + ((rhi - rlo) * k) / 4).toFixed(2) : "",
        ),
      );
    }
    chart.append(...dateTicks(L, pw, H, false));
    const zen = s
      .map((d, i) =>
        typeof d.balance === "number"
          ? [x(i), y(Math.max(0, d.balance))]
          : null,
      )
      .filter(Boolean);
    if (zen.length > 1)
      chart.append(
        svg("path", {
          d: `${profilePath(zen)} L${zen.at(-1)[0]} ${y(0)} L${zen[0][0]} ${y(0)} Z`,
          fill: "var(--pf-zen)",
          opacity: ".16",
        }),
        svg("path", {
          d: profilePath(zen),
          fill: "none",
          stroke: "var(--pf-zen)",
          "stroke-width": "2",
        }),
        svg("circle", {
          cx: zen.at(-1)[0],
          cy: zen.at(-1)[1],
          r: "3.5",
          fill: "var(--pf-zen)",
        }),
      );
    const ratio = s
      .map((d, i) => (typeof d.ratio === "number" ? [x(i), ry(d.ratio)] : null))
      .filter(Boolean);
    if (ratio.length > 1)
      chart.append(
        svg("path", {
          d: profilePath(ratio),
          fill: "none",
          stroke: "var(--pf-ratio)",
          "stroke-width": "1.5",
          "stroke-dasharray": "5 3",
        }),
      );
    const now = s.at(-1).ratio;
    zenChart.append(
      chart,
      foot([
        [
          say("Zen change", "Variation Zen"),
          profileSigned(p.change.balance, (v) => profileNumber(v, 0)) || "—",
        ],
        [say("Purchases seen", "Achats constatés"), String(p.purchases)],
        [
          say("Ratio now", "Ratio actuel"),
          typeof now === "number" ? now.toFixed(2) : "—",
        ],
      ]),
    );
  }
}

function showProfileProgression(o) {
  const g = o.progression,
    host = $("profile-progression");
  const level = element("div", undefined, "pf-level");
  const ring = svg("svg", {
    class: "pf-ring",
    width: "96",
    height: "96",
    viewBox: "0 0 96 96",
    role: "img",
    "aria-label": `${say("Level progress", "Progression du niveau")} ${Math.round(g.fraction * 100)}%`,
  });
  const circumference = 2 * Math.PI * 40;
  const label = svg("text", {
    x: "48",
    y: "46",
    "text-anchor": "middle",
    "font-size": "24",
    "font-weight": "600",
  });
  label.textContent = profileNumber(g.level, 0);
  const caption = svg("text", {
    x: "48",
    y: "62",
    "text-anchor": "middle",
    "font-size": "9",
    fill: "var(--muted)",
  });
  caption.textContent = say("LEVEL", "NIVEAU");
  ring.append(
    svg("circle", {
      cx: "48",
      cy: "48",
      r: "40",
      fill: "none",
      stroke: "var(--pf-raised)",
      "stroke-width": "9",
    }),
    svg("circle", {
      cx: "48",
      cy: "48",
      r: "40",
      fill: "none",
      stroke: "var(--pf-brand)",
      "stroke-width": "9",
      "stroke-linecap": "round",
      "stroke-dasharray": `${(g.fraction * circumference).toFixed(1)} ${circumference.toFixed(1)}`,
      transform: "rotate(-90 48 48)",
    }),
    label,
    caption,
  );
  const text = element("div");
  const span =
    typeof g.into === "number" && typeof g.to_next === "number"
      ? g.into + g.to_next
      : null;
  text.append(
    element(
      "div",
      `${profileNumber(g.into, 0)} / ${profileNumber(span, 0)} XP`,
      "pf-num",
    ),
    element(
      "div",
      `${profileNumber(g.to_next, 0)} XP ${say("to level", "avant le niveau")} ${typeof g.level === "number" ? g.level + 1 : "—"} · ${profileNumber(g.total_xp, 0)} XP ${say("total", "au total")}`,
      "pf-muted",
    ),
  );
  const badges = element("div");
  Object.assign(badges.style, {
    marginTop: "8px",
    display: "flex",
    gap: "8px",
    alignItems: "center",
    flexWrap: "wrap",
  });
  if (g.grade) badges.append(element("span", g.grade, "pf-grade"));
  if (typeof g.stars === "number")
    badges.append(
      element(
        "span",
        "★".repeat(g.stars) + "☆".repeat(Math.max(0, 4 - g.stars)),
        "pf-stars",
      ),
    );
  badges.append(
    element(
      "span",
      `${say("Quests", "Quêtes")} ${profileNumber(g.quests_completed, 0)} / ${profileNumber(g.quests_total, 0)} · ${say("Tree bonus", "Bonus d’arbre")} ${typeof g.tree_bonus === "number" ? "+" + profileNumber(g.tree_bonus * 100) + " %" : "—"}`,
      "pf-muted",
    ),
  );
  text.append(badges);
  level.append(ring, text);
  const names = {
    seed: say("Seeding", "Seed"),
    upload: say("Uploading", "Upload"),
    specialization: say("Specialization", "Spécialisation"),
    competitivity: say("Competitiveness", "Compétitivité"),
  };
  const paths = element("div", undefined, "pf-voies");
  for (const path of g.paths) {
    const r = element("div", undefined, "pf-voie");
    const bar = element("div", undefined, "pf-bar");
    const fill = element("span");
    fill.style.width = `${path.fraction * 100}%`;
    bar.append(fill);
    const count = element(
      "span",
      `${profileNumber(path.completed, 0)}/${profileNumber(path.total, 0)} `,
      "pf-num",
    );
    count.style.textAlign = "right";
    count.append(element("span", "★".repeat(path.stars), "pf-stars"));
    r.append(element("span", names[path.key]), bar, count);
    paths.append(r);
  }
  host.replaceChildren(
    eyebrow(say("Progression", "Progression"), "API"),
    level,
    paths,
  );
}

function profileBestClass(classes) {
  const current = classes.find((c) => c.current);
  const name = (c) => profileClassNames[c.id] || c.id;
  const pct = (c) =>
    current && current.daily > 0
      ? ` ${profileSigned((c.daily / current.daily - 1) * 100, (v) => profileNumber(v, 0))} %`
      : "";
  const currentText = current
    ? `${name(current)} (${say("current", "actuelle")})`
    : "";
  const best = classes[0];
  if (!current || best.current) {
    const other = classes.find((c) => !c.current);
    return [currentText, other ? name(other) + pct(other) : ""]
      .filter(Boolean)
      .join(" · ");
  }
  return `${name(best)}${pct(best)} · ${currentText}`;
}

function showProfileZen(o) {
  const z = o.zen,
    clients = profileClients,
    host = $("profile-zen");
  const balance = element("div", undefined, "pf-num");
  Object.assign(balance.style, { fontSize: "26px", fontWeight: "500" });
  balance.append(
    `${profileNumber(z.balance, 0)} `,
    element("small", "Zen", "pf-muted"),
  );
  const split = element("div", undefined, "pf-split");
  split.setAttribute("aria-hidden", "true");
  if (
    typeof z.balance === "number" &&
    typeof z.spent === "number" &&
    z.balance + z.spent > 0
  ) {
    const part = element("span");
    part.style.width = `${(Math.max(0, z.balance) / (Math.max(0, z.balance) + z.spent)) * 100}%`;
    split.append(part);
  }
  const totals = element("div");
  Object.assign(totals.style, {
    display: "flex",
    justifyContent: "space-between",
    fontSize: "12px",
    color: "var(--muted)",
  });
  for (const [label, value] of [
    [say("Earned", "Gagnés"), z.earned],
    [say("Spent", "Dépensés"), z.spent],
  ]) {
    const item = element("span", `${label} `);
    const b = element("b", profileNumber(value, 0), "pf-num");
    b.style.color = "var(--ink)";
    item.append(b);
    totals.append(item);
  }
  const rows = element("div", undefined, "pf-rows");
  const estimate = clients?.zen;
  if (!clients) {
    rows.append(
      row(
        say(
          "Estimated today (from your clients)",
          "Estimé aujourd’hui (vos clients)",
        ),
        say("Loading…", "Chargement…"),
      ),
    );
  } else if (!estimate) {
    rows.append(
      row(
        say(
          "Estimated today (from your clients)",
          "Estimé aujourd’hui (vos clients)",
        ),
        say(
          "Connect a Torrent Client to estimate",
          "Connectez un client torrent pour estimer",
        ),
      ),
    );
  } else {
    rows.append(
      row(
        say(
          "Estimated today (from your clients)",
          "Estimé aujourd’hui (vos clients)",
        ),
        `${profileSigned(estimate.daily, (v) => profileNumber(v, 0))} Zen`,
        "pf-num",
      ),
    );
  }
  const measured = o.period?.measured_zen;
  if (typeof measured === "number") {
    rows.append(
      row(
        o.span
          ? say(`Measured over ${o.span} days`, `Mesuré sur ${o.span} jours`)
          : say("Measured over all history", "Mesuré sur tout l’historique"),
        `${profileSigned(measured, (v) => profileNumber(v, 0))} Zen / ${say("day", "jour")}`,
        "pf-num",
      ),
    );
  }
  if (estimate) {
    rows.append(
      row(
        say("Best class for your seeds", "Meilleure classe pour vos seeds"),
        profileBestClass(estimate.classes),
      ),
    );
    rows.append(
      row(
        say("Top earner", "Meilleur torrent"),
        estimate.top
          ? `${estimate.top.name} · ${profileNumber(estimate.top.zen)} Zen/${say("day", "jour")}`
          : "—",
      ),
    );
  }
  host.replaceChildren(
    eyebrow("Zen", "API", say("local estimate", "estimation locale")),
    balance,
    split,
    totals,
    rows,
  );
}

function showProfileTransfers(o) {
  const host = $("profile-transfers"),
    list = element("div", undefined, "pf-acct");
  for (const [key, label, color] of [
    ["uploaded", say("Uploaded", "Envoyé"), "var(--pf-up)"],
    ["downloaded", say("Downloaded", "Téléchargé"), "var(--pf-down)"],
  ]) {
    const a = o.transfers[key],
      item = element("div");
    const lbl = element("div", undefined, "lbl");
    const figures = element("span", undefined, "pf-num");
    if (a) {
      const sign = key === "uploaded" ? "+" : "−";
      figures.append(
        `${say("actual", "réel")} ${profileBytes(a.actual)} · ${say("credit", "crédit")} ${sign}${profileBytes(a.credit)} · `,
      );
      const total = element(
        "b",
        `${say("total", "total")} ${profileBytes(a.total)}`,
      );
      total.style.color = "var(--ink)";
      figures.append(total);
    } else figures.append("—");
    lbl.append(element("span", label), figures);
    const stack = element("div", undefined, "pf-stack");
    if (a) {
      const solid = element("span"),
        extra = element("span", undefined, a.hatched ? "hatched" : "credit");
      solid.style.cssText = `width:${a.solid * 100}%;background:${color}`;
      extra.style.cssText = `width:${a.extra * 100}%;background-color:${color}`;
      stack.append(solid, extra);
    }
    item.append(lbl, stack);
    list.append(item);
  }
  const note = element(
    "p",
    say(
      "Credit comes from bonuses and freeleech. Total upload adds it; total download subtracts it, never below zero.",
      "Le crédit vient des bonus et du freeleech. Il s’ajoute à l’envoi total et se retire du téléchargement total, sans descendre sous zéro.",
    ),
    "pf-muted",
  );
  Object.assign(note.style, { fontSize: "12px", marginTop: "12px" });
  host.replaceChildren(
    eyebrow(say("Transfer accounting", "Comptabilité des transferts"), "API"),
    list,
    note,
  );
}

function showProfileSeeding(o) {
  const host = $("profile-seeding"),
    clients = profileClients,
    companion = o.companion;
  const table = element("table"),
    head = element("thead"),
    body = element("tbody"),
    tr = element("tr");
  for (const [text, cls] of [
    [say("Source", "Source")],
    [say("Torrents", "Torrents"), "r"],
    [say("Size", "Taille"), "r"],
  ])
    tr.append(element("th", text, cls));
  head.append(tr);
  const line = (cells) => {
    const r = element("tr");
    for (const [text, cls, span] of cells) {
      const td = element("td", undefined, cls);
      if (text instanceof Node) td.append(text);
      else td.textContent = text;
      if (span) td.colSpan = span;
      r.append(td);
    }
    body.append(r);
  };
  const connect = say("Connect the companion", "Connectez l’extension");
  if (typeof companion?.active_seeds === "number")
    line([
      [say("Active on c411", "Actifs sur c411")],
      [profileNumber(companion.active_seeds, 0), "r pf-num"],
      ["—", "r pf-num"],
    ]);
  else
    line([
      [say("Active on c411", "Actifs sur c411")],
      [connect, "r pf-muted", 2],
    ]);
  if (!clients)
    line([
      [
        say("Loading Torrent Clients…", "Chargement des clients torrent…"),
        "pf-muted",
        3,
      ],
    ]);
  else if (!clients.clients.length)
    line([
      [
        say("No Torrent Client is enabled.", "Aucun client torrent activé."),
        "pf-muted",
        3,
      ],
    ]);
  for (const c of clients?.clients || []) {
    if (c.error) {
      const cell = element(
        "span",
        say("Unavailable", "Indisponible"),
        "pf-warn",
      );
      cell.title = c.error;
      line([[c.name], [cell, "r", 2]]);
    } else
      line([
        [c.name],
        [profileNumber(c.count, 0), "r pf-num"],
        [profileBytes(c.size), "r pf-num"],
      ]);
  }
  if (clients) {
    const gap = clients.gap,
      label = element("b", say("Gap", "Écart"));
    if (typeof gap !== "number")
      line([
        [label],
        [
          typeof companion?.active_seeds === "number"
            ? say("No client reachable", "Aucun client joignable")
            : connect,
          "r pf-muted",
          2,
        ],
      ]);
    else
      line([
        [label],
        [
          gap > 0
            ? say(`${gap} not seen`, `${gap} non vus`)
            : gap < 0
              ? say(
                  `${-gap} more in clients`,
                  `${-gap} de plus dans les clients`,
                )
              : say("None", "Aucun"),
          `r pf-num ${gap ? "pf-warn" : "pf-ok"}`,
        ],
        ["—", "r pf-num"],
      ]);
  }
  table.append(head, body);
  const wrap = element("div", undefined, "pf-tablewrap");
  wrap.append(table);
  const rows = element("div", undefined, "pf-rows");
  rows.style.marginTop = "6px";
  rows.append(
    row(
      say("Validated uploads", "Uploads validés"),
      profileNumber(companion?.validated_uploads, 0),
      "pf-num",
    ),
    row(
      say("Total seed time", "Durée totale de seed"),
      typeof companion?.seed_time === "number"
        ? `${profileNumber(companion.seed_time / 86400, 0)} ${say("days", "jours")}`
        : "—",
      "pf-num",
    ),
  );
  host.replaceChildren(
    eyebrow(
      say("Seeding · tracker vs clients", "Seed · tracker et clients"),
      say("companion", "extension"),
      "clients",
    ),
    wrap,
    rows,
  );
}

function showProfileSync(o) {
  const names = {
    ok: say("API and companion OK", "API et extension OK"),
    api: say("API only", "API seule"),
    failed: say("Failed", "Échec"),
    none: say("App not running", "Application fermée"),
  };
  const cal = element("div", undefined, "pf-cal");
  cal.setAttribute("role", "img");
  cal.setAttribute(
    "aria-label",
    say(
      "Daily profile sync results",
      "Résultats quotidiens de synchronisation",
    ),
  );
  for (const cell of o.calendar) {
    const i = element("i", undefined, cell.outcome);
    i.title = `${cell.day} · ${names[cell.outcome]}`;
    cal.append(i);
  }
  const key = element("div", undefined, "pf-calkey");
  for (const [outcome, color] of [
    ["ok", "var(--pf-ok)"],
    ["api", "var(--pf-warn)"],
    ["failed", "var(--pf-err)"],
    ["none", "var(--pf-raised)"],
  ]) {
    const item = element("span"),
      dot = element("i");
    dot.style.background = color;
    if (outcome === "none") dot.style.border = "1px solid var(--line)";
    item.append(dot, names[outcome]);
    key.append(item);
  }
  $("profile-sync").replaceChildren(
    eyebrow(
      say(
        "Sync history · last 26 weeks",
        "Historique de synchronisation · 26 semaines",
      ),
    ),
    cal,
    key,
  );
}

function showProfileContribution(quotas) {
  const host = $("profile-contribution");
  host.replaceChildren(
    eyebrow(
      say("Daily community contribution", "Contribution communautaire du jour"),
    ),
  );
  if (!quotas) {
    host.append(
      element(
        "p",
        say("Connect the companion", "Connectez l’extension"),
        "pf-empty",
      ),
    );
    return;
  }
  const rows = element("div", undefined, "pf-voies");
  for (const [kind, label] of [
    ["comment", say("Comments", "Commentaires")],
    ["vote", say("Votes", "Votes")],
    ["chat", say("Chat messages", "Messages du chat")],
  ]) {
    const quota = quotas[kind];
    if (!quota) continue;
    const used = quota.site_used ?? quota.local_used;
    const row = element("div", undefined, "pf-voie");
    const bar = element("div", undefined, "pf-bar");
    const fill = element("span");
    fill.style.width = `${quota.limit ? Math.min(100, (used / quota.limit) * 100) : 0}%`;
    bar.append(fill);
    row.append(
      element("span", label),
      bar,
      element("span", `${used} / ${quota.limit}`, "pf-num"),
    );
    row.title =
      quota.site_used == null
        ? say("Local attempts today", "Tentatives locales aujourd’hui")
        : say("Reported by the site", "Comptabilisé par le site");
    rows.append(row);
  }
  host.append(
    rows,
    element(
      "p",
      say(
        "Resets at midnight, Paris time.",
        "Remise à zéro à minuit, heure de Paris.",
      ),
      "pf-contribution-note pf-muted",
    ),
  );
}

function showZenProfile(data) {
  const errors = {
    "no-key": say(
      "Add an API key with profile:read access in Settings → Indexer.",
      "Ajoutez une clé API avec le droit profile:read dans Paramètres → Indexeur.",
    ),
    unauthorized: say(
      "API key refused. Check Settings → Indexer and refresh.",
      "Clé API refusée. Vérifiez Paramètres → Indexeur puis actualisez.",
    ),
    "missing-scope": say(
      "The API key needs profile:read access.",
      "La clé API nécessite le droit profile:read.",
    ),
    "rate-limited": say(
      "The tracker asked us to wait. Try refreshing later.",
      "Le tracker demande de patienter. Réessayez plus tard.",
    ),
    failed: say(
      "Profile unavailable. Check your connection and refresh.",
      "Profil indisponible. Vérifiez la connexion puis actualisez.",
    ),
  };
  $("profile-notice").textContent =
    errors[data.error] ||
    (data.api_stale
      ? say(
          "Waiting for an API update. Retrying automatically.",
          "En attente des données API. Nouvelle tentative automatique.",
        )
      : "");
  $("profile-period").setAttribute("aria-label", say("Period", "Période"));
  for (const b of $("profile-period").querySelectorAll("button")) {
    b.setAttribute(
      "aria-pressed",
      String(Number(b.dataset.days) === profileDays),
    );
    if (b.dataset.days === "0") b.textContent = say("All", "Tout");
    else b.textContent = `${b.dataset.days} ${say("d", "j")}`;
  }
  $("profile-refresh").textContent = say("Refresh", "Actualiser");
  const o = data.overview;
  if (o) {
    showProfileHeader(o, data);
    showProfileTiles(o);
    showProfileCharts(o);
    showProfileProgression(o);
    showProfileZen(o);
    showProfileTransfers(o);
    showProfileSeeding(o);
    showProfileContribution(data.community_contribution);
    showProfileSync(o);
  } else {
    chartOverview = null;
    for (const id of [
      "meta",
      "badges",
      "tiles",
      "volumes",
      "zen-chart",
      "progression",
      "zen",
      "transfers",
      "seeding",
      "sync",
      "contribution",
    ])
      $("profile-" + id).replaceChildren();
    $("profile-username").textContent = say(
      "Connect your c411 account",
      "Connectez votre compte c411",
    );
    $("profile-avatar").textContent = "?";
    $("profile-avatar").dataset.token = "";
  }
  $("profile-privacy").textContent = say(
    "Connect and manage the companion in Settings → Companion. Your login stays in the browser.",
    "Connectez et gérez l’extension dans Réglages → Extension. Votre session reste dans le navigateur.",
  );
}

window.addEventListener("profile-environment", ({ detail: env }) => {
  const scroll = { left: window.scrollX, top: window.scrollY };
  TLPanel.setLanguage(env.language);
  document.documentElement.dataset.theme = env.theme;
  profileDays = env.days;
  profileClients = env.clients;
  profileAvatar = /^data:image\/(png|jpeg|gif|webp);base64,/.test(
    env.avatar || "",
  )
    ? env.avatar
    : "";
  showZenProfile(env.state || {});
  $("profile-refresh").disabled = !!env.busy;
  $("profile-period").setAttribute("aria-label", say("Period", "Période"));
  $("profile-tiles").setAttribute(
    "aria-label",
    say("Key figures", "Chiffres clés"),
  );
  if (env.notice) $("profile-notice").textContent = env.notice;
  window.scrollTo(scroll);
});
TLPanel.connect("profile").then((request) => {
  const run = async (path, body) => {
    try {
      await request(path, body);
    } catch (error) {
      $("profile-notice").textContent = error.message;
    }
  };
  $("profile-refresh").onclick = () => run("refresh");
  for (const button of $("profile-period").querySelectorAll("button"))
    button.onclick = () => run("period", { days: Number(button.dataset.days) });
  window.profileReady();
});
