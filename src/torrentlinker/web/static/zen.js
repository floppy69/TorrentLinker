"use strict";

const zenSeeding = { generation: 0, expanded: new Set(), client: null, groups: [] };
function zenTab(name) {
  rememberTab("zen", name);
  $("zen-overview").hidden = name !== "seeding";
  for (const key of ["profile", "seeding", "plan", "catalogue", "community"]) {
    const selected = key === name;
    $(`zen-${key}-panel`).hidden = !selected;
    $(`zen-${key}-tab`).setAttribute("aria-selected", String(selected));
    $(`zen-${key}-tab`).tabIndex = selected ? 0 : -1;
    $(`zen-${key}-tab`).classList.toggle("active", selected);
  }
}
for (const name of ["profile", "seeding", "plan", "catalogue", "community"]) {
  $(`zen-${name}-tab`).onclick = () => zenTab(name);
  $(`zen-${name}-tab`).onkeydown = (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const tabs = ["profile", "seeding", "plan", "catalogue", "community"];
      const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1] : tabs[(tabs.indexOf(name) + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      zenTab(next); $(`zen-${next}-tab`).focus();
    }
  };
}
zenTab("profile");
function seedingParams() {
  return new URLSearchParams({
    client_id: state.clientId,
    q: $("seeding-query").value,
    sort: $("seeding-sort").value,
    descending: String($("seeding-order").value === "desc"),
  });
}
function seedingGroupName(group) {
  return group.name || (group.category === null ? say("Unknown category", "Catégorie inconnue") : say("Category ", "Catégorie ") + group.category);
}
function seedingColumns() {
  return [say("Torrent", "Torrent"), say("Size", "Taille"), "Seeders", say("Seed age (days)", "Âge du seed (jours)"), say("≈ Zen/day", "≈ Zen/jour"), "≈ Note"];
}
function seedingGroup(group, all, generation, params) {
  const details = element("details", undefined, "seeding-group");
  details.dataset.group = group.id;
  const summary = element("summary");
  summary.append(element("strong", `${seedingGroupName(group)} (${group.count})`));
  summary.append(element("span", bytes(group.size)), element("span", `≈ ${num(group.zen)} Zen/${say("day", "jour")}`), element("span", `≈ Note ${num(group.note)}`));
  details.append(summary);
  for (const child of all.filter(g => g.parent === group.id)) details.append(seedingGroup(child, all, generation, params));
  const content = element("div", undefined, "seeding-rows");
  details.append(content);
  let loaded = false;
  let request = 0;
  async function page(offset = 0) {
    const currentRequest = ++request;
    content.replaceChildren(element("p", say("Loading…", "Chargement…")));
    const args = new URLSearchParams(params);
    args.set("group", group.id); args.set("offset", offset); args.set("limit", 100);
    try {
      const result = await api(`zen/seeding?${args}`);
      if (generation !== zenSeeding.generation || currentRequest !== request || !details.isConnected) return;
      const wrapper = element("div", undefined, "table-wrap");
      const table = element("table");
      const head = element("thead"), header = element("tr");
      for (const label of seedingColumns()) header.append(element("th", label));
      head.append(header); table.append(head);
      const body = element("tbody");
      for (const row of result.rows) {
        const line = element("tr");
        const title = element("td", row.name);
        title.title = row.name + (row.provisional_category ? say(" · Snapshot category, subcategory unconfirmed", " · Catégorie issue de l’instantané, sous-catégorie non confirmée") : "");
        line.append(title);
        const values = [bytes(row.size), row.seeders ?? "—", num(row.seed_days), row.zen === null ? "—" : `≈ ${num(row.zen)}`, row.note === null ? "—" : `≈ ${num(row.note)}`];
        for (const value of values) line.append(element("td", value));
        if (!row.seeding) line.title = say("Not seeding: earns no Zen", "Pas en partage : aucun gain Zen");
        body.append(line);
      }
      table.append(body); wrapper.append(table);
      const pager = element("div", undefined, "pager");
      const previous = button(say("Previous", "Précédent"), () => page(Math.max(0, offset - 100)));
      const next = button(say("Next", "Suivant"), () => page(offset + 100));
      previous.disabled = offset === 0; next.disabled = offset + 100 >= result.total;
      pager.append(previous, element("span", `${result.total ? offset + 1 : 0}–${Math.min(offset + result.rows.length, result.total)} / ${result.total}`), next);
      content.replaceChildren(wrapper, pager);
      loaded = true;
    } catch (error) {
      if (generation !== zenSeeding.generation || currentRequest !== request) return;
      content.replaceChildren(element("p", error.message, "error"), button(say("Retry", "Réessayer"), () => page(offset)));
    }
  }
  details.ontoggle = () => {
    if (details.open) {
      zenSeeding.expanded.add(group.id);
      if (!loaded && group.direct_count) guard(() => page());
    } else zenSeeding.expanded.delete(group.id);
  };
  details.open = zenSeeding.expanded.has(group.id) || Boolean(params.get("q"));
  return details;
}
async function loadZenSeeding() {
  const generation = ++zenSeeding.generation;
  if (zenSeeding.client !== state.clientId) {
    zenSeeding.expanded.clear(); zenSeeding.client = state.clientId;
  }
  const query = say("Filter torrents or categories…", "Filtrer les torrents ou catégories…");
  $("seeding-query").placeholder = query; $("seeding-query").setAttribute("aria-label", query);
  $("seeding-status").textContent = say("Loading…", "Chargement…");
  $("seeding-groups").replaceChildren();
  $("seeding-total").textContent = ""; $("seeding-classes").replaceChildren();
  $("zen-daily").textContent = "—"; $("zen-count").textContent = "—";
  const params = seedingParams();
  try {
    const result = await api(`zen/seeding?${params}`);
    if (generation !== zenSeeding.generation) return;
    $("zen-daily").textContent = num(result.summary.daily);
    $("zen-count").textContent = result.summary.count;
    const errors = result.client_errors.length ? result.client_errors.map(e => `${e.name}: ${e.message}`).join(" · ") + say(" · Last observed values; unavailable clients may be incomplete.", " · Dernières valeurs observées ; les clients indisponibles peuvent être incomplets.") : "";
    $("seeding-status").textContent = errors || (result.summary.total ? say(
      "Client-recorded seed age; c411 may count more. Estimates, not the c411 balance. All clients counts each hash once.",
      "Âge du seed mesuré par le client ; c411 peut compter davantage. Estimations, pas le solde c411. Tous les clients : chaque hash est compté une seule fois.",
    ) : say("Refresh to see your c411 torrents and Zen estimates.", "Actualisez pour voir vos torrents c411 et leurs estimations Zen."));
    zenSeeding.groups = result.groups;
    const ordered = [...result.groups].sort((a, b) => b.zen - a.zen || seedingGroupName(a).localeCompare(seedingGroupName(b)));
    $("seeding-groups").replaceChildren(...ordered.filter(g => !g.parent).map(g => seedingGroup(g, ordered, generation, params)));
    if (!result.matched && result.summary.total) $("seeding-groups").append(element("p", say("No matching torrents or categories.", "Aucun torrent ou catégorie ne correspond.")));
    $("seeding-total").textContent = `${result.summary.count} ${say("torrents seeding", "torrents en partage")} · ≈ ${num(result.summary.daily)} Zen/${say("day", "jour")} (${say("paid", "payés")} ≈ ${result.summary.paid}) · ${result.matched}/${result.summary.total} ${say("torrents shown", "torrents affichés")}`;
    const names = {tanker: "Tanker", "swarm-keeper": "Swarm Keeper", reuploader: "Reuploader"};
    for (const cls of result.classes) {
      const text = `${names[cls.id]} : ≈ ${num(cls.daily)} Zen/${say("day", "jour")}` + (cls.id === "reuploader" ? say(" (rough)", " (approximatif)") : "") + (cls.current ? say(" ← your Class", " ← votre Classe") : "");
      $("seeding-classes").append(element(cls.current ? "strong" : "span", text));
    }
    $("seeding-classes").append(element("span", `${say("Your uploads", "Vos uploads")} : ${result.uploads}`));
    if (document.activeElement !== $("seeding-uploads")) $("seeding-uploads").value = result.uploads;
  } catch (error) {
    if (generation === zenSeeding.generation) $("seeding-status").textContent = error.message;
  }
}
$("seeding-expand").onclick = () => $("seeding-groups").querySelectorAll("details").forEach(d => {d.open = true;});
$("seeding-collapse").onclick = () => $("seeding-groups").querySelectorAll("details").forEach(d => {d.open = false;});
$("seeding-refresh").onclick = () => guard(() => job({kind: "refresh"}, loadZenSeeding));
let seedingFilterTimer;
$("seeding-query").oninput = () => {
  clearTimeout(seedingFilterTimer);
  seedingFilterTimer = setTimeout(() => guard(loadZenSeeding), 200);
};
$("seeding-sort").onchange = () => guard(loadZenSeeding);
$("seeding-order").onchange = () => guard(loadZenSeeding);
