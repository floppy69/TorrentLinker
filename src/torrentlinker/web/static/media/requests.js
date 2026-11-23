"use strict";
/* Requests and Wishes, the Member's side (layout B of docs/specs/members-media): "Ask the
   owner" instead of Download on a tracker film, "Make a wish", and a bell in the Media menu
   whose drawer lists each Request and Wish with its state and the approver's note.
   The server checks the Permissions and caps again; hiding is only presentation. */
const requests = {rows: [], quota: null, unread: 0, loaded: false, timer: 0, sequence: 0};
const requestPermission = name => state.setup?.owner === false && (state.setup.permissions || []).includes(name);
const requestsShown = () => requestPermission("request") || requestPermission("wish");
const requestStates = () => ({
  pending: [say("Pending", "En attente"), "wait"], accepted: [say("Accepted", "Acceptée"), ""], sent: [say("Accepted", "Acceptée"), ""],
  send_failed: [say("Waiting to be sent", "En attente d’envoi"), "wait"], downloading: [say("Downloading", "En téléchargement"), ""],
  available: [say("In Media", "Dans Médias"), ""], refused: [say("Refused", "Refusée"), "no"],
  cancelled: [say("Cancelled", "Annulée"), "no"], expired: [say("Expired", "Expirée"), "no"],
});
function requestState(row) {
  if (row.kind === "wish" && row.state === "pending") return [say("Wish · pending", "Vœu · en attente"), "wait"];
  return requestStates()[row.state] || [row.state, ""];
}
const requestSize = bytes => `${Math.max(0, Math.floor(bytes / 1e9))} ${say("GB", "Go")}`;
const requestDay = seconds => new Date(seconds * 1000).toLocaleDateString(language === "fr" ? "fr-FR" : "en-GB", {weekday: "long", day: "numeric", month: "long"});
// The request still open for a tracker release, if any.
const requestFor = infohash => requests.rows.find(row => row.infohash === infohash && !["refused", "cancelled", "expired"].includes(row.state));
// Why a new Request would be refused, or "" while the caps allow one of this size.
function requestBlocked(size = 0) {
  const quota = requests.quota;
  if (!quota) return "";
  if (quota.pending_left === 0) return say("Too many Requests are waiting for an answer: wait until one is answered.", "Trop de demandes attendent une réponse : attendez qu’une soit traitée.");
  if (quota.requests_left === 0) return say(`Weekly quota reached. Next Request possible on ${requestDay(quota.reset)}.`, `Quota atteint cette semaine. Prochaine demande possible ${requestDay(quota.reset)}.`);
  if (quota.bytes_left !== null && size > quota.bytes_left) return say(`Only ${requestSize(quota.bytes_left)} left this week. More on ${requestDay(quota.reset)}.`, `Il ne reste que ${requestSize(quota.bytes_left)} cette semaine. Davantage ${requestDay(quota.reset)}.`);
  return "";
}
function requestQuotaLine(size = 0) {
  const blocked = requestBlocked(size), quota = requests.quota || {};
  if (blocked) return element("p", blocked, "media-quota full");
  const parts = [];
  if (quota.requests_left !== null && quota.requests_left !== undefined) parts.push(say(`${quota.requests_left} Request${quota.requests_left > 1 ? "s" : ""}`, `${quota.requests_left} demande${quota.requests_left > 1 ? "s" : ""}`));
  if (quota.bytes_left !== null && quota.bytes_left !== undefined) parts.push(requestSize(quota.bytes_left));
  if (!parts.length) return element("p", say("No weekly limit on your Requests.", "Pas de limite hebdomadaire à vos demandes."), "media-quota");
  return element("p", say(`You have ${parts.join(" and ")} left this week.`, `Il vous reste ${parts.join(" et ")} cette semaine.`), "media-quota");
}
async function requestsLoad(result) {
  if (!requestsShown()) return;
  const sequence = ++requests.sequence;
  const found = result || await api("requests");
  if (sequence !== requests.sequence) return; // a later answer is on its way
  const before = new Map(requests.rows.map(row => [row.id, row.state]));
  const fresh = found.requests.filter(row => row.unread && requests.loaded && before.get(row.id) !== row.state);
  Object.assign(requests, {rows: found.requests, quota: found.quota, unread: found.unread, loaded: true});
  // A new answer shows a short notice, then waits in the drawer until it is seen.
  for (const row of fresh) toast(`${row.title} · ${requestState(row)[0]}${row.answer ? ` · « ${row.answer} »` : ""}`);
  requestsBell();
  if (!$("media-requests").hidden) requestsDrawer();
  if (fresh.length) { mediaRenderFeature(); mediaRenderHome(); }
}
function requestsBell() {
  const bell = $("media-requests-bell");
  bell.hidden = !requestsShown();
  const label = say("My Requests and notices", "Mes demandes et notifications");
  bell.setAttribute("aria-label", requests.unread ? `${label} (${requests.unread})` : label); bell.title = label;
  const badge = bell.querySelector("b"); badge.textContent = String(requests.unread); badge.hidden = !requests.unread;
  if (!requestsShown()) $("media-requests").hidden = true;
  clearInterval(requests.timer);
  // Answers come from the approvers; look for them while Médias is open.
  if (requestsShown()) requests.timer = setInterval(() => { if (state.view === "media") guard(() => requestsLoad()); }, 60000);
}
function requestsDrawer() {
  const root = $("media-requests"), header = element("div", undefined, "media-home-row-header");
  header.append(element("h2", say("My Requests", "Mes demandes")), button(say("Close", "Fermer"), () => { root.hidden = true; }, "quiet"));
  root.replaceChildren(header);
  if (requestPermission("request")) root.append(requestQuotaLine());
  if (!requests.rows.length) root.append(element("p", say("Your Requests and Wishes will appear here.", "Vos demandes et vœux apparaîtront ici."), "media-row-note"));
  for (const row of requests.rows) {
    const item = element("div", undefined, `media-request${row.unread ? " unread" : ""}`), copy = element("div");
    const [label] = requestState(row);
    copy.append(element("strong", [row.title, row.year].filter(Boolean).join(" · ")), element("small", `${label} · ${mediaAge(row.updated)}`));
    if (row.answer) copy.append(element("p", `${row.answered_by || say("The owner", "Le propriétaire")} : « ${row.answer} »`, "media-request-note"));
    if (row.state === "pending") copy.append(button(say("Cancel the Request", "Annuler la demande"), () => requestCancel(row), "quiet"));
    item.append(mediaArt({title: row.title}), copy); root.append(item);
  }
  if (requestPermission("wish")) {
    const actions = element("div", undefined, "media-feature-actions");
    actions.append(button(say("Make a wish", "Faire un vœu"), requestWishDialog, "media-secondary")); root.append(actions);
  }
}
async function requestsOpen() {
  const root = $("media-requests");
  if (!root.hidden) { root.hidden = true; return; }
  root.hidden = false; requestsDrawer();
  // Opening the drawer shows the new answers: they are seen.
  if (requests.unread) await requestsLoad(await api("requests/seen", {}));
  root.querySelector("button")?.focus();
}
async function requestCancel(row) {
  await api(`requests/${encodeURIComponent(row.id)}/cancel`, {});
  toast(say("Request cancelled", "Demande annulée"));
  await requestsLoad(); mediaRenderFeature(); mediaRenderHome();
}
// The tracker film's panel for a Member: "Ask the owner", or the state of their Request.
function mediaRequestActions(row, copy, actions) {
  const asked = requestFor(row.tracker.hash);
  // The latest answer stays on the panel, a refusal's note included; asking again is allowed.
  const latest = asked || requests.rows.find(item => item.infohash === row.tracker.hash && item.state !== "cancelled");
  if (latest) {
    const [label, tone] = requestState(latest), line = element("div", undefined, "media-request-state");
    const said = latest.answer ? `${latest.answered_by || say("The owner", "Le propriétaire")} : « ${latest.answer} »` : "";
    line.append(element("span", label, `media-poster-badge ${tone}`), element("span", latest.state === "pending" ? say(`Asked ${mediaAge(latest.created)}.`, `Demandé ${mediaAge(latest.created)}.`) : said));
    copy.append(line);
  }
  if (asked) {
    if (asked.state === "pending") actions.append(button(say("Cancel the Request", "Annuler la demande"), () => requestCancel(asked), "media-secondary"));
  } else {
    if (requestPermission("request")) {
      const blocked = requestBlocked(row.tracker.size);
      copy.append(requestQuotaLine(row.tracker.size));
      const ask = button(say("Ask the owner", "Demander au propriétaire"), async () => {
        ask.disabled = true;
        try {
          await api("requests", {infohash: row.tracker.hash});
          toast(say(`Request sent for ${row.title}`, `Demande envoyée pour ${row.title}`));
        } finally { await requestsLoad(); mediaRenderFeature(); mediaRenderHome(); }
      }, "media-primary");
      ask.disabled = !!blocked; if (blocked) ask.title = blocked;
      actions.append(ask);
    }
    if (requestPermission("wish")) actions.append(button(say("Make a wish", "Faire un vœu"), () => requestWishDialog(), "media-secondary"));
  }
  copy.append(actions);
}
// The poster badge of a tracker film the Member asked for.
function mediaRequestBadge(item, art) {
  const asked = item.tracker && requestsShown() && requestFor(item.tracker.hash);
  if (!asked) return;
  const [label, tone] = requestState(asked);
  art.append(element("span", label, `media-poster-badge ${tone}`));
}
function requestWishDialog() {
  const dialog = $("media-wish"), form = element("form"), fields = {};
  form.method = "dialog";
  form.append(element("h2", say("Make a wish", "Faire un vœu")), element("p", say("A film you cannot find? The owner will look for the right release.", "Un film introuvable ? Le propriétaire cherchera la bonne release."), "media-row-note"));
  for (const [key, en, fr, tag] of [["title", "Title", "Titre", "input"], ["year", "Year (optional)", "Année (facultatif)", "input"], ["note", "A word for the owner", "Un mot pour le propriétaire", "textarea"]]) {
    const label = element("label", undefined, "media-wish-field"), input = document.createElement(tag);
    label.append(element("span", say(en, fr)), input); fields[key] = input; form.append(label);
  }
  fields.title.required = true; fields.title.maxLength = 200;
  fields.year.inputMode = "numeric"; fields.year.maxLength = 4; fields.year.pattern = "[0-9]{4}";
  fields.note.rows = 3; fields.note.maxLength = 500;
  const actions = element("div", undefined, "media-feature-actions"), send = element("button", say("Send the wish", "Envoyer le vœu"), "media-primary");
  send.type = "submit";
  actions.append(send, button(say("Cancel", "Annuler"), () => dialog.close(), "media-secondary"));
  form.append(actions);
  form.onsubmit = event => {
    event.preventDefault();
    guard(async () => {
      await api("wishes", {title: fields.title.value, year: fields.year.value, note: fields.note.value});
      dialog.close(); toast(say("Wish sent", "Vœu envoyé")); await requestsLoad();
    });
  };
  dialog.replaceChildren(form); dialog.showModal(); fields.title.focus();
}
$("media-requests-bell").onclick = () => guard(requestsOpen);
