"use strict";
const requestReview = {rows: [], selected: "", query: "", member: "", history: false, margin: {}};
function requestNode(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function requestBytes(value) { return value == null ? "?" : `${(value / 1024 ** 3).toFixed(1)} Go`; }
function requestState(value) {
  return ({complete: say("Complete", "Terminé"), pending: say("Pending", "En attente"), accepted: say("Sending", "Envoi"),
    sent: say("Sent", "Envoyée"), downloading: say("Downloading", "Téléchargement"),
    available: say("Available", "Disponible"), refused: say("Refused", "Refusée"),
    send_failed: say("Waiting to send", "En attente d’envoi"), cancelled: say("Cancelled", "Annulée"),
    expired: say("Expired", "Expirée")})[value] || value;
}
function requestMargin(chosen = 0, original = 0) {
  const {capacity, downloading, pending, stale} = requestReview.margin;
  const box = requestNode("section", undefined, "card request-margin");
  box.append(requestNode("h3", say("Download margin", "Marge de téléchargement")));
  if (capacity == null || downloading == null) {
    box.append(requestNode("p", say("Margin unavailable. Check the tracker and Torrent Client.", "Marge indisponible. Vérifiez le tracker et le client Torrent.")));
    return box;
  }
  const amounts = [downloading, chosen, Math.max(0, pending - original)];
  const bar = requestNode("div", undefined, "request-margin-bar");
  const total = Math.max(capacity, amounts.reduce((a, b) => a + b, 0), 1);
  amounts.forEach((amount, i) => {
    const span = requestNode("span", undefined, `margin-${i}`);
    span.style.width = `${100 * amount / total}%`; bar.append(span);
  });
  box.append(bar, requestNode("p", `${say("Capacity", "Capacité")} ${requestBytes(capacity)} · ${say("Downloading", "En cours")} ${requestBytes(downloading)} · ${say("Selected", "Sélection")} ${requestBytes(chosen)} · ${say("Other pending", "Autres demandes")} ${requestBytes(amounts[2])}`));
  if (chosen + downloading > capacity || stale) box.append(requestNode("p", stale
    ? say("Cached tracker figures may be out of date.", "Les chiffres du tracker peuvent être anciens.")
    : say("This release exceeds the available margin.", "Cette release dépasse la marge disponible."), "field-error"));
  return box;
}
async function loadRequests() {
  const result = await api("requests/review");
  requestReview.rows = result.requests; requestReview.margin = result.margin;
  renderRequests();
}
function renderRequests() {
  const root = $("view-requests"); root.replaceChildren();
  root.append(requestNode("h2", say("Requests", "Demandes")), requestMargin());
  const controls = requestNode("div", undefined, "toolbar");
  const search = requestNode("input"); search.type = "search"; search.placeholder = say("Find a title", "Rechercher un titre"); search.value = requestReview.query;
  search.setAttribute("aria-label", search.placeholder);
  search.onchange = () => { requestReview.query = search.value; renderRequests(); };
  const members = requestNode("select"); members.setAttribute("aria-label", say("Member", "Membre"));
  members.append(new Option(say("All members", "Tous les membres"), ""));
  const seen = new Set(); for (const row of requestReview.rows) if (!seen.has(row.account)) { members.append(new Option(row.requester, row.account)); seen.add(row.account); }
  members.value = requestReview.member; members.onchange = () => { requestReview.member = members.value; renderRequests(); };
  const history = requestNode("button", requestReview.history ? say("Pending", "En attente") : say("History", "Historique"));
  history.onclick = () => {requestReview.history = !requestReview.history; renderRequests();};
  const refresh = requestNode("button", say("Refresh", "Actualiser")); refresh.onclick = (event) => guard(loadRequests, event.currentTarget);
  controls.append(search, members, history, refresh); root.append(controls);
  const layout = requestNode("div", undefined, "request-review-layout"), list = requestNode("div", undefined, "request-list"), inspector = requestNode("section", undefined, "card request-inspector");
  const rows = requestReview.rows.filter(row => ["pending", "send_failed", "accepted"].includes(row.state) !== requestReview.history && (!requestReview.member || row.account === requestReview.member) && `${row.title} ${row.release}`.toLocaleLowerCase().includes(requestReview.query.toLocaleLowerCase()));
  if (!rows.some(r => r.id === requestReview.selected)) requestReview.selected = rows[0]?.id || "";
  for (const row of rows) {
    const button = requestNode("button", undefined, `card request-row${row.id === requestReview.selected ? " selected" : ""}`);
    button.append(requestNode("strong", `${row.title} ${row.year}`), requestNode("span", `${row.requester} · ${requestBytes(row.size)} · ReleaseScore ${row.score ?? "?"} · ${requestState(row.state)}`), requestNode("small", row.release || say("Wish: choose a release", "Vœu : choisir une release")));
    button.onclick = () => {requestReview.selected = row.id; renderRequests();}; list.append(button);
  }
  if (!rows.length) list.append(requestNode("p", say("No Requests here.", "Aucune demande ici.")));
  const row = rows.find(r => r.id === requestReview.selected);
  if (row) requestInspector(inspector, row);
  layout.append(list, inspector); root.append(layout);
}
function requestInspector(panel, row) {
  panel.append(requestNode("h3", `${row.title} ${row.year}`), requestNode("p", `${row.requester} · ${requestState(row.state)}`));
  if (row.note) panel.append(requestNode("p", row.note));
  if (row.infohash) {
    const cover = requestNode("img", undefined, "request-cover"); cover.alt = "";
    cover.src = `api/requests/artwork/${row.infohash}`; cover.onerror = () => cover.remove();
    panel.append(cover);
  }
  const choices = requestNode("select"); choices.setAttribute("aria-label", say("Release", "Release"));
  choices.append(new Option(row.release || say("Choose a release", "Choisir une release"), row.infohash));
  const query = requestNode("input"); query.value = row.title; query.setAttribute("aria-label", say("Find a release", "Chercher une release"));
  const find = requestNode("button", say("Find releases", "Chercher les releases"));
  const margin = requestNode("div"); margin.append(requestMargin(row.size || 0, row.size || 0));
  const capWarning = requestNode("p", "", "field-error");
  const warn = size => {
    const cap = row.approval_limits || {};
    capWarning.textContent = cap.count_left === 0 || cap.bytes_left != null && size > cap.bytes_left
      ? say("Accepting exceeds this Member's weekly quota. The override will be recorded.", "Cette acceptation dépasse le quota hebdomadaire du membre. Le dépassement sera consigné.") : "";
  };
  warn(row.size || 0); panel.append(capWarning);
  let releases = [];
  find.onclick = (event) => guard(async () => {
    releases = (await api(`requests/releases?q=${encodeURIComponent(query.value)}`)).releases;
    choices.replaceChildren(new Option(say("Choose a release", "Choisir une release"), ""));
    for (const release of releases) choices.append(new Option(`${release.name} · ${requestBytes(release.size)} · ReleaseScore ${release.score ?? "?"}`, release.hash));
    choices.value = row.infohash;
  }, event.currentTarget);
  choices.onchange = () => {const selected = releases.find(r => r.hash === choices.value); margin.replaceChildren(requestMargin(selected?.size || 0, row.size || 0)); warn(selected?.size || 0);};
  if (row.state === "pending") panel.append(query, find, choices);
  panel.append(margin);
  const quota = row.quota;
  panel.append(requestNode("p", `${say("Weekly quota remaining", "Quota hebdomadaire restant")} : ${quota.requests_left ?? "∞"} · ${quota.bytes_left == null ? "∞" : requestBytes(quota.bytes_left)}`));
  const timeline = requestNode("ol"); for (const event of row.events) timeline.append(requestNode("li", `${new Date(event.at * 1000).toLocaleString()} · ${requestState(event.state)}${event.note ? ` · ${event.note}` : ""}`)); panel.append(timeline);
  const note = requestNode("textarea"); note.maxLength = 500; note.placeholder = say("Note for the Member", "Note pour le membre"); note.setAttribute("aria-label", note.placeholder);
  const error = requestNode("p", "", "field-error"); error.setAttribute("role", "alert");
  const actions = requestNode("div", undefined, "toolbar");
  function action(label, path) {
    const button = requestNode("button", label);
    button.onclick = async () => {
      for (const control of actions.children) control.disabled = true;
      try { await api(`requests/${row.id}/${path}`, {infohash: path === "accept" ? choices.value : "", note: note.value}); await loadRequests(); }
      catch (failure) {error.textContent = failure.message; for (const control of actions.children) control.disabled = false;}
    }; actions.append(button);
  }
  if (row.state === "pending") { action(say("Accept", "Accepter"), "accept"); action(say("Refuse", "Refuser"), "refuse"); }
  if (row.state === "send_failed") action(say("Retry", "Réessayer"), "retry");
  panel.append(note, error, actions);
}
