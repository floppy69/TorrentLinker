let assistantSidebarOpen = !matchMedia("(max-width: 1050px)").matches;
/* Same owner APIs as desktop; chat Markdown is rendered safely by the server. */
let assistantView = "chat", assistantConversation = "", assistantRun = "", assistantSnapshot = null;
let assistantRefreshBusy = false, assistantRenderKey = "", assistantLoadVersion = 0;
const assistantDrafts = new Map();
const assistantCollapsedFolders = new Set();
const at = (en, fr) => say(en, fr);
const assistantRoot = () => $("view-assistant");
let mediaAssistantHome = null;
async function mountMediaAssistant(container, conversationId) {
  const root = assistantRoot();
  if (!mediaAssistantHome) { mediaAssistantHome = document.createComment("assistant home"); root.before(mediaAssistantHome); }
  container.append(root); root.hidden = false;
  assistantConversation = conversationId; assistantView = "chat"; assistantRun = "";
  await loadAssistant();
}
function restoreMediaAssistant() {
  const root = assistantRoot();
  if (mediaAssistantHome) { mediaAssistantHome.replaceWith(root); mediaAssistantHome = null; }
  root.hidden = state.view !== "assistant";
}
const assistantVisible = () => state.view === "assistant" || (typeof media !== "undefined" && media.chat);
function aFolderLabel(folder) {
  return ({"": at("General", "Général"), uploads: at("Uploads", "Uploads"), film_research: at("Film research", "Recherche de films"), series_research: at("Series research", "Recherche de séries"), troubleshooting: at("Troubleshooting", "Dépannage")})[folder] ?? folder;
}
function aConversationFolders(container, conversations) {
  const key = JSON.stringify([assistantConversation, conversations.map(c => [c.id, c.name, c.folder])]);
  if (container.dataset.snapshot === key) return;
  for (const group of container.querySelectorAll(":scope > .assistant-folder")) {
    group.open ? assistantCollapsedFolders.delete(group.dataset.folder) : assistantCollapsedFolders.add(group.dataset.folder);
  }
  container.dataset.snapshot = key;
  const groups = new Map();
  for (const chat of conversations) {
    const folder = chat.folder || "";
    if (!groups.has(folder)) groups.set(folder, []);
    groups.get(folder).push(chat);
  }
  container.replaceChildren();
  for (const [folder, chats] of groups) {
    const group = element("details", undefined, "assistant-folder");
    group.dataset.folder = folder;
    group.open = !assistantCollapsedFolders.has(folder);
    group.addEventListener("toggle", () => {
      if (group.isConnected) group.open ? assistantCollapsedFolders.delete(folder) : assistantCollapsedFolders.add(folder);
    });
    const title = element("summary", aFolderLabel(folder));
    const icon = element("span", "▱", "assistant-folder-icon"); icon.setAttribute("aria-hidden", "true"); title.prepend(icon);
    group.append(title);
    for (const chat of chats) {
      const item = button(chat.name, async () => { assistantConversation = chat.id; assistantRun = ""; await loadAssistant(); }, assistantConversation === chat.id ? "active" : "");
      item.title = chat.name;
      if (assistantConversation === chat.id) item.setAttribute("aria-current", "page");
      group.append(item);
    }
    container.append(group);
  }
}
function aMoveConversation(current, conversations) {
  const {dialog, form} = aDialog(at("Move to folder…", "Déplacer vers un dossier…"));
  const choices = [...new Set(["", "uploads", "film_research", "series_research", "troubleshooting", ...conversations.map(c => c.folder || "")])];
  let newValue = "__new__";
  while (choices.includes(newValue)) newValue += "_";
  const folder = aField(form, at("Folder", "Dossier"), current.folder || "", "", [...choices.map(f => [f, aFolderLabel(f)]), [newValue, at("New folder…", "Nouveau dossier…")]]);
  const name = aField(form, at("Folder name", "Nom du dossier")); name.maxLength = 80; name.parentElement.hidden = true;
  const automatic = aField(form, at("Let the assistant organize this conversation", "Laisser l’assistant classer cette conversation"), current.folder_source !== "manual", "checkbox");
  folder.onchange = () => { name.parentElement.hidden = folder.value !== newValue; automatic.checked = false; };
  aActions(dialog, form, async () => {
    const value = folder.value === newValue ? name.value.trim() : folder.value;
    if (folder.value === newValue && !value) { name.setCustomValidity(at("Enter a folder name", "Saisissez un nom de dossier")); name.reportValidity(); return false; }
    await api(`assistant/conversations/${current.id}/folder`, {folder: value, automatic: automatic.checked}, "PUT");
  });
  name.oninput = () => name.setCustomValidity("");
}
function aField(form, label, value = "", type = "text", options = null) {
  const wrapper = element("label", label), input = element(options ? "select" : type === "textarea" ? "textarea" : "input");
  input.setAttribute("aria-label", label);
  if (options) for (const [id, name] of options) { const o = element("option", name); o.value = id; input.append(o); }
  else if (type !== "textarea") input.type = type;
  if (type === "checkbox") input.checked = !!value; else input.value = value;
  wrapper.append(input); form.append(wrapper); return input;
}
function aDialog(title) {
  const dialog = element("dialog", undefined, "assistant-dialog"), form = element("form");
  form.append(element("h2", title)); dialog.append(form); document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal(); return {dialog, form};
}
function aActions(dialog, form, save) {
  const footer = element("div", undefined, "toolbar");
  footer.append(button(at("Save", "Enregistrer"), async () => { if (await save() === false) return; await loadAssistant(); if (state.view === "setup") await loadAssistantConnections(); dialog.close(); }, "primary"), button(at("Cancel", "Annuler"), () => dialog.close(), "quiet"));
  form.onsubmit = e => e.preventDefault(); form.append(footer);
}
// A small popup menu under an icon button: [[label, action], …]. Clicking elsewhere closes it.
function aMenu(anchor, items) {
  const open = anchor.parentElement.querySelector(".assistant-menu");
  document.querySelectorAll(".assistant-menu").forEach(m => m.remove());
  if (open) return;
  const menu = element("div", undefined, "assistant-menu"); menu.setAttribute("role", "menu");
  for (const [label, action, disabled] of items) {
    const item = button(label, async () => { menu.remove(); await action(); });
    item.setAttribute("role", "menuitem"); item.disabled = !!disabled; menu.append(item);
  }
  anchor.after(menu); menu.querySelector("button:not(:disabled)")?.focus();
  setTimeout(() => document.addEventListener("click", function close(e) {
    if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener("click", close); }
  }), 0);
}
function aIconButton(glyph, label, callback, cls = "") {
  const b = button(glyph, callback, `icon-button ${cls}`.trim());
  b.title = label; b.setAttribute("aria-label", label); return b;
}
const aExamples = () => [
  at("Find ten films I don't seed yet and show them before any action.", "Cherche dix films que je ne partage pas encore et montre-les-moi avant toute action."),
  at("Prepare a Plan within 200 GB with the best Zen gain.", "Prépare un Plan de 200 Go maximum avec le meilleur gain de Zen."),
  at("Review my local upload drafts and list what is missing.", "Relis mes brouillons d'upload locaux et liste ce qui manque."),
  at("Play a film with French subtitles.", "Lance un film avec des sous-titres français."),
];
let assistantPendingMode = "";
async function aOpenConnections() {
  await navigate("setup", "assistant");
  $("assistant-connections")?.scrollIntoView({block: "start"});
}
async function aRename(current) {
  const name = prompt(at("Rename discussion", "Renommer la discussion"), current.name)?.trim();
  if (!name) return;
  const {id, ...body} = current;
  await api(`assistant/conversations/${id}`, {...body, name: name.slice(0, 120)}, "PUT");
  await loadAssistant();
}
async function aDelete(current) {
  if (!confirm(at("Delete this discussion and its history? Pending proposals will be rejected. Torrents and files will not be removed.", "Supprimer cette discussion et son historique ? Les propositions en attente seront refusées. Les torrents et fichiers ne seront pas supprimés."))) return;
  await api(`assistant/conversations/${current.id}`, undefined, "DELETE");
  assistantDrafts.delete(current.id); assistantConversation = ""; assistantRun = "";
  await loadAssistant();
}
// The first switch to Execute within limits asks for confirmation; this browser remembers it.
function aConfirmExecute() {
  let confirmed = false;
  try { confirmed = localStorage.getItem("tl-execute-confirmed") === "1"; } catch { /* storage unavailable */ }
  if (confirmed) return true;
  if (!confirm(at("In this mode the assistant runs the actions allowed in this discussion's settings without asking, within its limits on clients, size and downloads per day. Removing queue entries or torrents and deleting files still need your approval.\n\nSwitch to Execute within limits? You will not be asked again.", "Dans ce mode, l’assistant exécute sans demander les actions autorisées dans les paramètres de la discussion, dans ses limites de clients, de volume et de téléchargements par jour. Retirer des entrées de la file ou des torrents, ou supprimer des fichiers, demande toujours votre accord.\n\nPasser en mode Exécuter dans les limites ? Cette question ne sera plus posée."))) return false;
  try { localStorage.setItem("tl-execute-confirmed", "1"); } catch { /* storage unavailable */ }
  return true;
}
const aModeLabel = mode => mode === "execute" ? at("Execute within limits", "Exécuter dans les limites") : at("Proposals only", "Propositions uniquement");
async function loadAssistant() {
  const version = ++assistantLoadVersion;
  const setup = await api("setup/assistant");
  if (version !== assistantLoadVersion) return;
  assistantSnapshot = setup;
  const root = assistantRoot(); root.replaceChildren(); assistantRenderKey = "";
  // In the Media Center side panel: one discussion, no tabs; folders and automations stay on the Assistant page.
  const compact = !!root.closest("#media-chat-content");
  if (compact) assistantView = "chat";
  root.classList.toggle("assistant-compact", compact);
  const nav = element("div", undefined, "assistant-tabs"); nav.setAttribute("role", "tablist");
  for (const [id, label] of [["chat", at("Discussion", "Discussion")], ["tasks", at("Automations", "Automatisations")], ["history", at("History", "Historique")]]) {
    const tab = button(label, async () => { assistantView = id; await loadAssistant(); }, assistantView === id ? "active" : "");
    tab.setAttribute("role", "tab"); tab.setAttribute("aria-selected", String(assistantView === id));
    nav.append(tab);
  }
  if (!compact) root.append(nav);
  if (assistantView === "tasks") return aTasks(root);
  if (assistantView === "history") {
    const [history, conversations] = await Promise.all([api("assistant/jobs"), api("assistant/conversations")]);
    const names = new Map(conversations.map(c => [c.id, c.name]));
    root.append(element("p", at("Runs and tool receipts are stored here. Interrupted actions are never replayed automatically.", "Les exécutions et leurs actions sont conservées ici. Une action interrompue n’est jamais rejouée automatiquement."), "muted"));
    const list = element("div", undefined, "assistant-history");
    for (const run of history) {
      const when = new Date((run.created || 0) * 1000).toLocaleString(state.language === "fr" ? "fr-FR" : undefined, {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
      list.append(element("p", [names.get(run.conversation_id) || at("Automation", "Automatisation"), when, aStatus(run.status)].join(" · "), "assistant-run-heading"), aRunCard(run));
    }
    root.append(list);
    return;
  }
  const layout = element("div", undefined, "assistant-layout"), side = element("aside", undefined, "assistant-conversations"), main = element("div", undefined, "assistant-main");
  side.id = "assistant-conversations";
  layout.classList.toggle("conversations-collapsed", !assistantSidebarOpen);
  const sideTop = element("div", undefined, "assistant-side-top");
  const search = element("input"); search.type = "search"; search.id = "assistant-search";
  search.placeholder = at("Search discussions", "Rechercher une discussion"); search.setAttribute("aria-label", search.placeholder);
  search.value = assistantSearch;
  search.oninput = () => { assistantSearch = search.value; aFilterConversations(); };
  sideTop.append(search, aIconButton("＋", at("New discussion", "Nouvelle discussion"), async () => {
    assistantConversation = ""; assistantRun = ""; assistantPendingMode = ""; assistantDrafts.delete("");
    await loadAssistant(); $("assistant-prompt")?.focus();
  }));
  side.append(sideTop);
  const conversations = await api("assistant/conversations");
  if (version !== assistantLoadVersion) return;
  const folders = element("div"); folders.id = "assistant-folders";
  aConversationFolders(folders, conversations); side.append(folders); aFilterConversations();
  layout.append(side, main); root.append(layout);
  const current = conversations.find(c => c.id === assistantConversation);
  if (assistantConversation && !current) { assistantConversation = ""; return loadAssistant(); }
  const defaults = await api("setup/assistant/chat"), config = current || defaults;
  if (version !== assistantLoadVersion) return;
  const mode = current ? current.policy.mode : assistantPendingMode || defaults.policy.mode;
  // Discussion header: the sidebar toggle, the title and the ⋯ menu (the panel has its own).
  const header = element("div", undefined, "assistant-header");
  const toggle = aIconButton("☰", at("Discussions", "Discussions"), () => {
    assistantSidebarOpen = !assistantSidebarOpen;
    layout.classList.toggle("conversations-collapsed", !assistantSidebarOpen);
    toggle.setAttribute("aria-expanded", String(assistantSidebarOpen));
  });
  toggle.setAttribute("aria-controls", side.id); toggle.setAttribute("aria-expanded", String(assistantSidebarOpen));
  const title = element("h2", current ? current.name : at("New discussion", "Nouvelle discussion"), "assistant-title");
  const settings = button(at("Discussion settings", "Paramètres de la discussion"), () => aTaskEditor(false, {...config, provider_id: model.value}, !current), "assistant-hidden-action");
  settings.id = "assistant-chat-settings"; settings.hidden = true;
  const more = aIconButton("⋯", at("More", "Plus"), () => aMenu(more, [
    [at("Discussion settings", "Paramètres de la discussion"), () => settings.click(), settings.disabled],
    [at("Rename…", "Renommer…"), () => aRename(current), !current],
    [at("Move to folder…", "Déplacer vers un dossier…"), async () => {
      const latest = await api("assistant/conversations");
      const selected = latest.find(c => c.id === assistantConversation);
      if (selected) aMoveConversation(selected, latest);
    }, !current],
    [at("Delete discussion", "Supprimer la discussion"), () => aDelete(current), !current],
  ]));
  more.id = "assistant-more"; more.setAttribute("aria-haspopup", "menu");
  const menuWrap = element("div", undefined, "assistant-menu-wrap"); menuWrap.append(more);
  header.append(toggle, title, settings, menuWrap);
  if (compact) { $("media-chat-title").textContent = title.textContent; main.append(settings); }
  else main.append(header);
  const transcript = element("div", undefined, "assistant-transcript"); transcript.id = "assistant-transcript";
  main.append(transcript);
  // The composer: one rounded field with Send/Stop inside, the model and mode chips under it.
  const form = element("form", undefined, "assistant-composer"), field = element("div", undefined, "assistant-field"), prompt = element("textarea");
  prompt.id = "assistant-prompt"; prompt.maxLength = 16000; prompt.rows = 2;
  prompt.value = assistantDrafts.get(assistantConversation) || "";
  prompt.oninput = () => assistantDrafts.set(assistantConversation, prompt.value);
  prompt.placeholder = at("Give a task or ask a question…", "Donnez une tâche ou posez une question…"); prompt.setAttribute("aria-label", at("Message", "Message"));
  const send = element("button", "➤", "assistant-send"); send.type = "submit"; send.id = "assistant-send";
  field.append(prompt, send);
  const chips = element("div", undefined, "assistant-chips");
  const model = element("select", undefined, "assistant-chip"); model.id = "assistant-model";
  model.setAttribute("aria-label", at("Model connection", "Connexion au modèle"));
  for (const p of assistantSnapshot.providers) { const o = element("option", `${p.name} · ${p.model}`); o.value = p.id; model.append(o); }
  if ([...model.options].some(o => o.value === config.provider_id)) model.value = config.provider_id;
  model.onchange = () => guard(async () => {
    if (current) {
      const {id, ...body} = current;
      model.disabled = true; settings.disabled = true;
      try { await api(`assistant/conversations/${id}`, {...body, provider_id: model.value}, "PUT"); current.provider_id = model.value; }
      catch (e) { model.value = current.provider_id; throw e; }
      finally { model.disabled = false; settings.disabled = false; aSetSend(false); }
    }
  });
  const modeChip = button(aModeLabel(mode), async () => {
    const next = (current ? current.policy.mode : assistantPendingMode || defaults.policy.mode) === "execute" ? "propose" : "execute";
    if (next === "execute" && !aConfirmExecute()) return;
    if (current) {
      const {id, ...body} = current;
      await api(`assistant/conversations/${id}`, {...body, policy: {...body.policy, mode: next}}, "PUT");
      current.policy.mode = next;
    } else assistantPendingMode = next;
    modeChip.textContent = aModeLabel(next);
  }, "quiet assistant-chip");
  modeChip.id = "assistant-mode"; modeChip.title = at("Switch the discussion mode", "Changer le mode de la discussion");
  chips.append(model, modeChip);
  form.append(field, chips);
  if (!current) {
    const welcome = element("div", undefined, "assistant-welcome");
    welcome.append(element("h2", at("What would you like to do?", "Que souhaitez-vous faire ?")), element("p", at("Find films, prepare an Upload or build your next Zen Plan.", "Trouvez des films, préparez un Upload ou votre prochain Plan Zen.")));
    const examples = element("div", undefined, "assistant-examples");
    for (const example of aExamples()) examples.append(button(example, () => { prompt.value = example; assistantDrafts.set(assistantConversation, example); prompt.focus(); }, "assistant-example"));
    welcome.append(examples); transcript.append(welcome);
  }
  if (!assistantSnapshot.providers.length) {
    form.hidden = true;
    main.append(button(at("Connect a model", "Connecter un modèle"), aOpenConnections, "primary assistant-connect"));
  }
  aSetSend(false);
  prompt.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!send.disabled) form.requestSubmit(); } };
  form.onsubmit = e => { e.preventDefault(); guard(async () => {
    if (send.dataset.running === "true") { if (assistantRun) await api(`assistant/jobs/${assistantRun}/cancel`, {}); return; }
    if (!prompt.value.trim() || send.disabled) return;
    send.disabled = true;
    const origin = assistantConversation, message = prompt.value;
    let identifier = origin;
    try {
      if (!identifier) {
        const body = {...defaults, provider_id: model.value, name: "Discussion"};
        if (assistantPendingMode) body.policy = {...body.policy, mode: assistantPendingMode};
        const chat = await api("assistant/conversations", body);
        identifier = chat.id; assistantPendingMode = "";
        assistantDrafts.set(identifier, message); assistantDrafts.delete("");
      }
      if (typeof media !== "undefined" && media.chat) await mediaHeartbeat();
      const run = await api("assistant/jobs", {conversation_id: identifier, message});
      assistantDrafts.delete(identifier);
      if (assistantConversation === origin) {
        assistantConversation = identifier; assistantRun = run.id;
        await loadAssistant(); $("assistant-prompt")?.focus();
      }
    } catch (e) {
      if (assistantConversation === origin && identifier) {
        assistantConversation = identifier; await loadAssistant();
      }
      throw e;
    } finally { if (send.isConnected) aSetSend(false); }
  }); };
  main.append(form); await aRefreshChat();
}
let assistantSearch = "";
function aFilterConversations() {
  const needle = assistantSearch.trim().toLocaleLowerCase();
  for (const group of document.querySelectorAll("#assistant-folders > .assistant-folder")) {
    let visible = 0;
    for (const item of group.querySelectorAll(":scope > button")) {
      const match = item.textContent.toLocaleLowerCase().includes(needle);
      item.hidden = !match; visible += match;
    }
    group.hidden = !visible;
    if (needle && visible) group.open = true;
  }
}
// One button sends while idle and stops the assistant while it works.
function aSetSend(running) {
  const send = $("assistant-send"), model = $("assistant-model");
  if (!send) return;
  const label = running ? at("Stop", "Arrêter") : at("Send", "Envoyer");
  send.textContent = running ? "■" : "➤"; send.title = label; send.setAttribute("aria-label", label);
  send.dataset.running = String(running);
  send.disabled = !running && !model?.value;
  if (model) model.disabled = running;
  if ($("assistant-chat-settings")) $("assistant-chat-settings").disabled = running;
}
async function aRefreshChat() {
  if (!assistantVisible() || assistantView !== "chat" || !assistantConversation || !$("assistant-transcript") || assistantRefreshBusy) return;
  assistantRefreshBusy = true;
  const identifier = assistantConversation, transcript = $("assistant-transcript");
  try {
    const [rows, conversations] = await Promise.all([api(`assistant/jobs?conversation_id=${encodeURIComponent(identifier)}`), api("assistant/conversations")]);
    if (assistantConversation !== identifier || $("assistant-transcript") !== transcript) return;
    if ($("assistant-folders")) { aConversationFolders($("assistant-folders"), conversations); aFilterConversations(); }
    const key = JSON.stringify(rows); if (key === assistantRenderKey) return;
    assistantRenderKey = key;
    const position = transcript.scrollTop, bottom = position >= transcript.scrollHeight - transcript.clientHeight - 20;
    transcript.replaceChildren(...[...rows].reverse().map(aRunCard));
    transcript.scrollTop = bottom ? transcript.scrollHeight : position;
    const active = rows.find(r => ["queued", "running", "awaiting_approval", "awaiting_user", "waiting_settings"].includes(r.status));
    assistantRun = active?.id || rows[0]?.id || "";
    aSetSend(!!active);
  } finally { assistantRefreshBusy = false; }
}
function aMarkdown(message) {
  const content = element("div", undefined, "assistant-markdown");
  // HTML comes only from the server's restricted Markdown renderer.
  if (message.html) content.innerHTML = message.html;
  else content.textContent = message.content;
  for (const link of content.querySelectorAll("a")) {
    const href = link.getAttribute("href") || "";
    // Tool citations are app-relative; retain the reverse proxy's mount path.
    if (href.startsWith("/documentation/")) link.href = new URL(href.slice(1), document.baseURI).href;
    link.rel = "noopener noreferrer";
    link.target = "_blank";
  }
  for (const image of content.querySelectorAll("img")) {
    image.addEventListener("error", () => {
      image.replaceWith(element("span", at("Image unavailable", "Image indisponible"), "assistant-image-error"));
    }, {once: true});
  }
  return content;
}
const assistantExpandedActivity = new Set();
const assistantExpandedCommands = new Set();
function aCommand(event, key) {
  const details = element("details", undefined, "assistant-command");
  details.open = assistantExpandedCommands.has(key);
  const summary = element("summary");
  const update = () => { summary.textContent = details.open ? at("Hide full command", "Masquer la commande complète") : at("Show full command", "Afficher la commande complète"); };
  update();
  details.addEventListener("toggle", () => {
    update();
    if (details.isConnected) details.open ? assistantExpandedCommands.add(key) : assistantExpandedCommands.delete(key);
  });
  const command = Object.fromEntries(["tool", "arguments", "review"].filter(k => k in event).map(k => [k, event[k]]));
  details.append(summary, aJson(command));
  return details;
}
function aJson(value) {
  const pre = element("pre", undefined, "assistant-json"), code = element("code");
  pre.setAttribute("tabindex", "0");
  pre.setAttribute("aria-label", at("Full command (JSON)", "Commande complète (JSON)"));
  const text = JSON.stringify(value, null, 2);
  const tokens = /"(?:\\.|[^"\\])*"\s*(?=:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
  let end = 0;
  for (const match of text.matchAll(tokens)) {
    code.append(document.createTextNode(text.slice(end, match.index)));
    const value = match[0], next = text.slice(match.index + value.length).trimStart();
    const kind = next.startsWith(":") ? "key" : value.startsWith('"') ? "string" : ["true", "false", "null"].includes(value) ? "literal" : "number";
    code.append(element("span", value, `json-${kind}`));
    end = match.index + value.length;
  }
  code.append(document.createTextNode(text.slice(end))); pre.append(code);
  return pre;
}

const assistantExpandedToolEvents = new Set();
const aToolDescription = event => at(event.description?.en, event.description?.fr) || event.tool.replaceAll("_", " ");
const aToolError = event => String(event.error || event.result?.error || event.result?.job?.error ||
  ((event.status === "failed" || event.result?.job?.status === "failed") ? at("Tool call failed.", "Échec de l’appel d’outil.") : "")).slice(0, 2000);
function aActivity(card, run, indexed, anchor) {
  const key = `${run.id}:${anchor}`;
  const activity = element("details", undefined, "assistant-activity");
  activity.open = assistantExpandedActivity.has(key);
  activity.addEventListener("toggle", () => { if (activity.isConnected) activity.open ? assistantExpandedActivity.add(key) : assistantExpandedActivity.delete(key); });
  const usage = `${at("Model calls", "Appels au modèle")}: ${run.calls} · ${at("Tool calls", "Appels d’outils")}: ${run.events.length} · Tokens: ${run.tokens}`;
  const failures = indexed.filter(([, event]) => aToolError(event));
  const label = indexed.length ? `${aToolDescription((failures.at(-1) || indexed.at(-1))[1])} · ${indexed.length}` : at("No tools called", "Aucun outil appelé");
  let groupStatus = indexed.length ? (indexed.find(([, event]) => ["running", "waiting", "failed"].includes(event.status))?.[1].status || "finished") : run.status;
  if (groupStatus === "waiting") groupStatus = run.status;
  if (failures.length) { if (groupStatus === "finished") groupStatus = "failed"; activity.classList.add("has-tool-error"); }
  const replyOnly = run.status === "completed" && !run.events.length;
  activity.append(element("summary", `${label} · ${replyOnly ? at("Reply only", "Réponse uniquement") : aStatus(groupStatus)}`));
  const entries = element("div", undefined, "assistant-tool-list");
  entries.append(element("p", usage, "assistant-usage"));
  if (run.compactions) entries.append(element("p", at("Context compacted; full history retained.", "Contexte compacté ; historique complet conservé."), "assistant-usage"));
  activity.append(entries); card.append(activity);
  if (replyOnly) card.append(element("p", at("No application action was performed in this reply.", "Cette réponse n’a exécuté aucune action dans l’application."), "assistant-execution-notice muted"));
  for (const [index, event] of indexed) {
    const detail = element("details", undefined, "assistant-tool"), result = event.result || {};
    const eventKey = `${run.id}:${index}`;
    const error = aToolError(event);
    if (error) detail.classList.add("has-tool-error");
    detail.append(element("summary", `${aToolDescription(event)} · ${aStatus(error ? "failed" : event.status === "waiting" ? run.status : event.status)}`));
    const content = element("div"); detail.append(content);
    const fill = () => {
      if (detail.open && !content.childElementCount) {
        if (error) content.append(element("p", error, "assistant-tool-error"));
        content.append(aJson(Object.fromEntries(["tool", "arguments", "result", "review", "error"].filter(k => k in event).map(k => [k, event[k]]))));
        if (result.job_id) content.append(button(at("Job progress", "Avancement de la tâche"), async () => {
          const job = await api(`jobs/${result.job_id}`); content.querySelector("pre").replaceWith(aJson(job));
        }));
      }
    };
    detail.open = assistantExpandedToolEvents.has(eventKey); fill();
    detail.addEventListener("toggle", () => {
      if (detail.isConnected) detail.open ? assistantExpandedToolEvents.add(eventKey) : assistantExpandedToolEvents.delete(eventKey);
      fill();
    });
    entries.append(detail);
    if (event.status === "waiting" && result.requires_owner_approval && result.id && !("decision" in event)) {
      const panel = element("section", undefined, "assistant-decision card");
      panel.append(element("h3", at("Action requires your approval", "Action à approuver")));
      const fields = element("div", undefined, "assistant-request-summary");
      for (const line of at(event.summary?.en, event.summary?.fr) || [event.tool]) fields.append(element("p", line));
      fields.append(aCommand(event, `${run.id}:${index}`));
      const decide = async approve => { await api(`assistant/jobs/${run.id}/decisions/${index}`, {approve}); await aRefreshChat(); };
      panel.append(fields, button(at("Approve once", "Approuver une fois"), () => decide(true), "primary"), button(at("Reject", "Refuser"), () => decide(false)));
      card.append(panel);
    }
    if (event.status === "waiting" && event.question && !("answer" in event)) {
      const panel = element("section", undefined, "assistant-question card"), choices = element("select"), custom = element("input"), submit = button(at("Submit answer", "Envoyer la réponse"), async () => {
        await api(`assistant/jobs/${run.id}/questions/${index}`, {answer: custom.value.trim() ? custom.value : choices.value}); await aRefreshChat();
      }, "primary");
      choices.append(new Option(at("Choose an answer…", "Choisir une réponse…"), ""));
      for (const option of event.question.options) choices.append(new Option(option, option));
      choices.setAttribute("aria-label", at("Suggested answers", "Réponses suggérées"));
      custom.placeholder = at("Or enter your own answer", "Ou saisir votre réponse"); custom.maxLength = 16000;
      submit.disabled = true;
      const changed = () => { submit.disabled = !custom.value.trim() && !choices.value; };
      choices.addEventListener("change", changed); custom.addEventListener("input", changed);
      panel.append(element("h3", event.question.question), choices, custom, submit); card.append(panel);
    }
  }
}
function aRunCard(run) {
  const card = element("article", undefined, "assistant-run"), groups = new Map();
  let fallback = run.messages.length - 1;
  if (run.messages.at(-1)?.role === "assistant") fallback--;
  run.events.forEach((event, index) => {
    const raw = Number.isInteger(event.after_message_index) ? event.after_message_index : fallback;
    const anchor = Math.max(-1, Math.min(raw, run.messages.length - 1));
    if (!groups.has(anchor)) groups.set(anchor, []);
    groups.get(anchor).push([index, event]);
  });
  if (groups.has(-1)) aActivity(card, run, groups.get(-1), -1);
  run.messages.forEach((message, index) => {
    const block = element("div", undefined, `assistant-message ${message.role}`);
    block.setAttribute("aria-label", message.role === "user" ? at("You", "Vous") : "Assistant");
    block.append(aMarkdown(message)); card.append(block);
    if (groups.has(index)) aActivity(card, run, groups.get(index), index);
  });
  // Keep activity chronological; place card presentations after the response summary.
  for (const event of run.events) {
    if (["present_selection", "present_upload_drafts", "present_media"].includes(event.tool) && event.result?.presentation_id) {
      card.append(aSelectionCards(event.result.presentation_id));
    }
  }
  if (!run.events.length) aActivity(card, run, [], run.messages.length);
  if (run.error) card.append(element("p", run.error, "error"));
  if (["queued", "running", "awaiting_approval", "awaiting_user", "waiting_settings"].includes(run.status)) card.append(element("p", at("Working…", "En cours…"), "assistant-working"), button(at("Stop", "Arrêter"), async () => { await api(`assistant/jobs/${run.id}/cancel`, {}); await aRefreshChat(); }));
  return card;
}

async function aReview(id, completed = aRefreshChat) {
  const review = await api(`agents/proposals/${id}/review`), {dialog, form} = aDialog(at("Review action", "Vérifier l’action"));
  if (review.operation?.kind === "edit-queue-selection" && review.operation.queue_action === "remove") {
    const rows = review.operation.selection_rows || [];
    form.append(element("h3", at(`Remove ${rows.length} queue entries`, `Retirer ${rows.length} entrées de la file`)));
    form.append(element("p", `${at("Torrent Client", "Client torrent")} : ${review.client} (${review.operation.client_id})`));
    form.append(element("p", at("Queue entries only. Files and torrents in the client are kept. No download starts.", "Uniquement les entrées de la file. Les fichiers et les torrents du client sont conservés. Aucun téléchargement ne démarre.")));
    const targets = element("ul", undefined, "queue-removal-targets");
    targets.style.maxHeight = "20rem"; targets.style.overflowY = "auto";
    for (const row of rows) targets.append(element("li", `${row.title} [${row.hash || row.key}] · ${row.folder}`));
    form.append(targets);
    const details = element("details"); details.append(element("summary", at("Full review", "Revue complète")), element("pre", JSON.stringify(review, null, 2))); form.append(details);
  } else if (review.groups?.length) {
    form.append(element("p", `${review.action}: ${review.torrent_instance_count} ${at("torrent instances", "instances de torrent")}`));
    for (const group of review.groups) {
      form.append(element("h3", `${group.client} (${group.client_id})`));
      form.append(element("p", `${group.torrent_instance_count} ${at("torrent instances", "instances de torrent")} · ${group.metadata_size_bytes.toLocaleString()} ${at("metadata bytes", "octets selon les métadonnées")}`));
      const targets = element("details"), names = group.targets || [];
      targets.append(element("summary", `${at("Exact targets and folders", "Cibles et dossiers exacts")} (${names.length})`));
      const targetList = element("ul");
      for (const target of names) targetList.append(element("li", `${target.name} [${target.hash}] — ${target.folder || ""}`));
      targets.append(targetList); form.append(targets);
    }
    form.append(element("p", review.warning || "", "warning"));
    form.append(element("p", at("Metadata sizes are not reclaimable disk space.", "Les tailles des métadonnées ne sont pas de l’espace récupérable."), "muted"));
    const details = element("details"); details.append(element("summary", at("Full review", "Revue complète")), element("pre", JSON.stringify(review, null, 2))); form.append(details);
  } else form.append(element("pre", JSON.stringify(review, null, 2)));
  form.append(button(at("Approve this action", "Approuver cette action"), async () => { await api(`agents/proposals/${id}/approve`, {}); dialog.close(); await completed(); }, "primary"), button(at("Reject", "Refuser"), async () => { await api(`agents/proposals/${id}/reject`, {}); dialog.close(); await completed(); }), button(at("Close", "Fermer"), () => dialog.close(), "quiet"));
}
// Model connections live in Settings → Assistant; they are saved as soon as each dialog is.
async function loadAssistantConnections() {
  const root = $("assistant-connections-body");
  if (!root) return;
  assistantSnapshot = await api("setup/assistant");
  root.replaceChildren();
  await aConnections(root);
}
async function aConnections(root) {
  root.append(element("p", at("Credentials stay in TorrentLinker. Hosted providers receive your messages and tool results. Local connections never fall back to a hosted provider.", "Les clés restent dans TorrentLinker. Les fournisseurs distants reçoivent vos messages et les résultats des outils. Aucune bascule automatique du local vers une API distante."), "muted"));
  const actions = element("div", undefined, "toolbar");
  actions.append(button(at("Add connection", "Ajouter une connexion"), () => aProvider(), "primary"), button(at("Chat defaults", "Paramètres des nouvelles discussions"), async () => aTaskEditor(false, await api("setup/assistant/chat"), true), "quiet"));
  root.append(actions);
  for (const p of assistantSnapshot.providers) {
    const card = element("div", undefined, "card"); card.append(element("h3", p.name), element("p", `${p.kind} · ${p.model} · ${p.url}`));
    const assessment = element("div");
    const showAssessment = result => {
      assessment.replaceChildren();
      if (!result) { assessment.append(element("p", at("Capabilities untested", "Capacités non testées"))); return; }
      for (const [name, check] of Object.entries(result.checks || {})) {
        assessment.append(element("p", `${name}: ${check.status}. ${check.reason}`));
      }
      if (result.context) assessment.append(element("p", `${at("Reported context, not verified", "Contexte déclaré, non vérifié")}: ${result.context.context_window} (${result.context.source})`));
    };
    showAssessment(p.assessment);
    card.append(assessment, button(at("Edit", "Modifier"), () => aProvider(p)), button(at("Retest capabilities", "Retester les capacités"), async () => {
      showAssessment(await api(`setup/assistant/providers/${p.id}/test`, {}));
    })); root.append(card);
  }
  const research = await api("setup/assistant/research"), form = element("form", undefined, "card");
  form.append(element("h3", at("Web research", "Recherche Web")), element("p", at("Choose Brave Search or your SearXNG server. Page reading and book metadata work without a search key. Film metadata uses the TMDb key in Settings.", "Utilisez Brave Search ou votre serveur SearXNG. La lecture de pages et les métadonnées des livres fonctionnent sans clé de recherche. Les films utilisent la clé TMDb des paramètres.")));
  const url = aField(form, "SearXNG URL", research.searxng_url || "", "url"), key = aField(form, "Brave Search API key", "", "password");
  key.placeholder = research.has_brave_key ? at("Saved; leave blank to keep", "Enregistrée ; laisser vide pour conserver") : "";
  form.append(button(at("Save research settings", "Enregistrer la recherche"), async () => {
    await api("setup/assistant/research", {searxng_url: url.value, ...(key.value ? {brave_key: key.value} : {})}, "PUT"); key.value = "";
  })); form.onsubmit = e => e.preventDefault(); root.append(form);
}
function aProvider(existing = null) {
  const {dialog, form} = aDialog(at("Model connection", "Connexion au modèle"));
  const name = aField(form, at("Name", "Nom"), existing?.name || ""), kind = aField(form, at("Provider", "Fournisseur"), existing?.kind || "ollama", "", Object.keys(assistantSnapshot.presets).map(k => [k, k]));
  const url = aField(form, at("Base URL", "Adresse de base"), existing?.url || assistantSnapshot.presets.ollama, "url");
  const model = aField(form, at("Model ID", "Identifiant du modèle"), existing?.model || "");
  const contextAuto = aField(form, at("Detect context automatically", "Détecter automatiquement le contexte"), existing?.context_auto ?? true, "checkbox");
  const contextWindow = aField(form, at("Context window (tokens)", "Fenêtre de contexte (tokens)"), existing?.context_window ?? 32768, "number");
  contextWindow.min = 512; contextWindow.max = 2000000;
  const serverSampling = aField(form, at("Use server sampling defaults", "Utiliser les paramètres d’échantillonnage du serveur"), existing?.temperature == null, "checkbox");
  const temperature = aField(form, at("Temperature (0 = least variation)", "Température (0 = variation minimale)"), existing?.temperature ?? 0, "number");
  temperature.min = 0; temperature.max = 2; temperature.step = 0.1;
  const updateSampling = () => {
    const supported = ["ollama", "lmstudio", "compatible"].includes(kind.value);
    if (!supported) serverSampling.checked = true;
    serverSampling.disabled = !supported; temperature.disabled = !supported || serverSampling.checked;
  };
  serverSampling.addEventListener("change", updateSampling); kind.addEventListener("change", updateSampling); updateSampling();
  form.append(element("p", at("Sampling overrides are available for Ollama, LM Studio and compatible endpoints. Lower variation does not guarantee correct answers or actions.", "Les réglages d’échantillonnage sont disponibles pour Ollama, LM Studio et les connexions compatibles. Une variation réduite ne garantit pas des réponses ou des actions correctes."), "muted"));
  const key = aField(form, at("API key", "Clé API"), "", "password"); key.autocomplete = "new-password";
  key.placeholder = at("Leave blank to keep the saved key", "Laisser vide pour conserver la clé");
  form.append(element("p", at("Detection runs before each task. The configured value is a fallback when metadata is unavailable. Disable detection for a manual override.", "La détection s’effectue avant chaque tâche. La valeur configurée sert de repli si les métadonnées sont indisponibles. Désactivez la détection pour utiliser une valeur manuelle."), "muted"));
  const contextStatus = element("p", "", "muted");
  const contextBody = () => ({name: name.value || "Discovery", kind: kind.value, url: url.value, model: model.value, context_window: +contextWindow.value, context_auto: contextAuto.checked, temperature: temperature.disabled ? null : (temperature.value.trim() === "" ? "" : +temperature.value), ...(key.value ? {api_key: key.value} : {})});
  const checkContext = button(at("Check context", "Vérifier le contexte"), async () => {
    const snapshot = JSON.stringify(contextBody());
    checkContext.disabled = true;
    contextStatus.textContent = at("Checking server context…", "Vérification du contexte du serveur…");
    try {
      const result = await api(existing ? `setup/assistant/providers/${existing.id}/context` : "setup/assistant/context", contextBody());
      if (!dialog.isConnected || snapshot !== JSON.stringify(contextBody())) return;
      const source = {server: at("Server context", "Contexte du serveur"), provider: at("Provider context", "Contexte du fournisseur"), manual: at("Manual context", "Contexte manuel"), fallback: at("Not reported. Fallback", "Non communiqué. Valeur de repli")};
      contextStatus.textContent = `${source[result.source]}: ${result.context_window.toLocaleString()} tokens`;
      if (result.served_models) contextStatus.textContent += ` ${at("The server does not list this model. It serves", "Le serveur ne propose pas ce modèle. Il sert")}: ${result.served_models.join(", ")}`;
    } finally { checkContext.disabled = false; }
  });
  for (const input of [kind, url, model, key, contextWindow, contextAuto]) input.addEventListener("input", () => { contextStatus.textContent = ""; });
  form.append(checkContext, contextStatus);
  form.append(element("p", at("Use an address reachable by TorrentLinker. In Docker, localhost is the container, not your PC. Changing the endpoint clears the saved key unless you supply a new one.", "Utilisez une adresse accessible depuis TorrentLinker. Dans Docker, localhost désigne le conteneur, pas votre PC. Changer l’adresse efface la clé enregistrée, sauf si vous en fournissez une nouvelle."), "muted"));
  kind.onchange = () => { url.value = assistantSnapshot.presets[kind.value]; };
  form.append(button(at("List models", "Lister les modèles"), async () => {
    const unchanged = existing && url.value === existing.url && kind.value === existing.kind && !key.value;
    const models = unchanged ? await api(`setup/assistant/providers/${existing.id}/models`) : await api("setup/assistant/models", {name: name.value || "Discovery", kind: kind.value, url: url.value, model: model.value || "discovery", api_key: key.value});
    form.querySelector("datalist")?.remove();
    const list = element("datalist"); list.id = "assistant-models";
    for (const id of models) { const option = element("option"); option.value = id; list.append(option); }
    form.append(list); model.setAttribute("list", list.id); if (!model.value && models.length) model.value = models[0];
  }));
  aActions(dialog, form, async () => {
    const saved = await api("setup/assistant/providers" + (existing ? `/${existing.id}` : ""), {name: name.value, kind: kind.value, url: url.value, model: model.value, context_window: +contextWindow.value, context_auto: contextAuto.checked, temperature: temperature.disabled ? null : (temperature.value.trim() === "" ? "" : +temperature.value), ...(key.value ? {api_key: key.value} : {})}, existing ? "PUT" : "POST");
    if (!existing || existing.kind !== kind.value || existing.url !== url.value || existing.model !== model.value || (existing.temperature ?? null) !== saved.temperature) {
      await api(`setup/assistant/providers/${saved.id}/test`, {});
    }
  });
}
function aScheduleText(t) {
  if (t.frequency === "interval") return at(`Every ${t.interval_minutes} min`, `Toutes les ${t.interval_minutes} min`);
  if (t.frequency === "weekly") {
    const names = [at("Mon", "lun."), at("Tue", "mar."), at("Wed", "mer."), at("Thu", "jeu."), at("Fri", "ven."), at("Sat", "sam."), at("Sun", "dim.")];
    const days = [...(t.weekdays || [])].sort().map(d => names[d]).join(", ");
    return at(`Weekly, ${days} at ${t.at}`, `Chaque semaine, ${days} à ${t.at}`);
  }
  return at(`Daily at ${t.at}`, `Chaque jour à ${t.at}`);
}
function aTaskState(t) {
  if (!t.enabled) return at("Paused", "En pause");
  if (t.blocked) return at("Waiting for its actions or your review", "En attente de ses actions ou de votre validation");
  const when = new Date(t.next_at * 1000).toLocaleString(state.language === "fr" ? "fr-FR" : undefined, {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
  return at(`Next run ${when}`, `Prochaine exécution ${when}`);
}
async function aTasks(root) {
  const top = element("div", undefined, "assistant-tasks-top");
  top.append(element("p", at("Tasks run while TorrentLinker is running. On desktop, keep the app open; on Docker, closing this browser is fine. Missed intervals are combined into one run. Failed/interrupted runs wait for review and Run now.", "Les tâches s’exécutent lorsque TorrentLinker fonctionne. Sur PC, gardez l’application ouverte ; sur Docker, vous pouvez fermer le navigateur. Les échéances manquées sont regroupées en une exécution. Les exécutions échouées ou interrompues attendent votre vérification et Exécuter maintenant."), "muted"), button(at("Create task", "Créer une tâche"), () => aTaskEditor(true), "primary"));
  root.append(top);
  const tasks = await api("assistant/schedules");
  if (!tasks.length) root.append(element("p", at("No automations yet. Create one to run a task on a schedule.", "Aucune automatisation. Créez-en une pour exécuter une tâche à heure fixe."), "muted"));
  const toggle = async t => {
    const {id, next_at, last_error, blocked, ...body} = t; await api(`assistant/schedules/${id}`, {...body, enabled: !t.enabled}, "PUT"); await loadAssistant();
  };
  for (const t of tasks) {
    const card = element("article", undefined, "assistant-task"), text = element("div", undefined, "assistant-task-text");
    text.append(element("h3", t.name), element("p", `${aScheduleText(t)} · ${aTaskState(t)}`, "muted"));
    if (t.last_error) text.append(element("p", t.last_error, "error"));
    const main = t.enabled
      ? button(at("Run now", "Exécuter maintenant"), async () => { await api(`assistant/schedules/${t.id}/run`, {}); assistantView = "history"; await loadAssistant(); })
      : button(at("Enable", "Activer"), () => toggle(t));
    main.disabled = t.enabled && t.blocked;
    const more = aIconButton("⋯", at("More", "Plus"), () => aMenu(more, [
      [at("Edit", "Modifier"), () => aTaskEditor(true, t)],
      [t.enabled ? at("Pause", "Mettre en pause") : at("Enable", "Activer"), () => toggle(t)],
    ]));
    more.setAttribute("aria-haspopup", "menu");
    const wrap = element("div", undefined, "assistant-menu-wrap"); wrap.append(more);
    card.append(text, main, wrap); root.append(card);
  }
}
function aTaskEditor(scheduled, existing = null, defaults = false) {
  const {dialog, form} = aDialog(scheduled ? at("Scheduled task", "Tâche programmée") : defaults ? at("Chat defaults", "Paramètres des nouvelles discussions") : at("Discussion settings", "Paramètres de la discussion"));
  const name = aField(form, at("Name", "Nom"), existing?.name || "");
  if (defaults) name.parentElement.hidden = true;
  const provider = aField(form, at("Model connection", "Connexion au modèle"), existing?.provider_id || assistantSnapshot.providers[0]?.id || "", "", assistantSnapshot.providers.map(p => [p.id, `${p.name} · ${p.model}`]));
  const mode = aField(form, at("Action policy", "Politique d’action"), existing?.policy.mode || "propose", "", [["propose", at("Proposals only", "Propositions uniquement")], ["execute", at("Execute within limits", "Exécuter dans les limites")]]);
  const clients = element("fieldset"); clients.append(element("legend", at("Allowed Torrent Clients", "Clients torrent autorisés"))); form.append(clients);
  const clientInputs = state.setup.clients.filter(c => c.enabled).map(c => [c.id, aField(clients, c.name, existing ? existing.policy.clients.includes(c.id) : c.id === state.setup.client_id, "checkbox")]);
  const details = element("details"); details.append(element("summary", at("Permissions and limits", "Autorisations et limites"))); form.append(details);
  const permissions = ["queue", "downloads", "controls", "reseed", "uploads", "media"].map(p => [p, aField(details, ({queue: at("Prepare and edit download queue", "Préparer et modifier la file"), downloads: at("Start downloads", "Démarrer les téléchargements"), controls: at("Torrent controls", "Commandes des torrents"), reseed: at("Reseeds", "Remises en seed"), uploads: "Uploads", media: at("Media playback and playlists", "Lecture des médias et playlists")})[p], existing?.policy.permissions.includes(p) || false, "checkbox")]);
  const updateMode = () => { for (const [, el] of permissions) el.disabled = mode.value === "propose"; }; mode.onchange = updateMode; updateMode();
  const bytes = aField(details, at("Downloads per day, GiB", "Téléchargements par jour, Gio"), (existing?.policy.daily_bytes ?? 10 * 1024 ** 3) / 1024 ** 3, "number");
  const torrents = aField(details, at("Torrents per day", "Torrents par jour"), existing?.policy.daily_torrents ?? 20, "number");
  const reserve = aField(details, at("Keep free, GiB (0 = off)", "Conserver libres, Gio (0 = désactivé)"), (existing?.policy.reserve_bytes ?? 0) / 1024 ** 3, "number");
  const calls = aField(details, at("Maximum model calls per run", "Appels au modèle par exécution"), existing?.max_calls ?? (scheduled ? 12 : 0), "number");
  const seconds = aField(details, at("Maximum duration, seconds", "Durée maximale, secondes"), existing?.max_seconds ?? (scheduled ? 300 : 0), "number");
  if (!scheduled) details.append(element("p", at("Set calls or duration to 0 for no per-run limit. Stop remains available.", "Indiquez 0 pour ne pas limiter les appels ou la durée. Le bouton Arrêter reste disponible.")));
  const web = aField(form, at("Allow public Web research", "Autoriser la recherche sur le Web public"), existing?.web || false, "checkbox");
  let instruction, kind, frequency, interval, atTime, timezone, days, enabled;
  if (scheduled) {
    instruction = aField(form, at("Instructions", "Instructions"), existing?.instruction || "", "textarea");
    kind = aField(form, at("Task type", "Type de tâche"), existing?.kind || "model", "", [["model", at("Model task", "Tâche avec modèle")], ["refresh", at("Refresh torrents (no model)", "Actualiser les torrents (sans modèle)")], ["catalogue", at("Refresh Catalogue (no model)", "Actualiser le Catalogue (sans modèle)")]]);
    frequency = aField(form, at("Frequency", "Fréquence"), existing?.frequency || "daily", "", [["interval", at("Every X minutes", "Toutes les X minutes")], ["daily", at("Daily", "Quotidienne")], ["weekly", at("Weekly", "Hebdomadaire")]]);
    interval = aField(form, at("Interval, minutes", "Intervalle, minutes"), existing?.interval_minutes || 60, "number"); interval.min = 5;
    atTime = aField(form, at("Time", "Heure"), existing?.at || "09:00", "time");
    timezone = aField(form, at("Timezone", "Fuseau horaire"), existing?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone);
    days = element("fieldset"); days.append(element("legend", at("Days", "Jours"))); form.append(days);
    [at("Mon", "Lun"), at("Tue", "Mar"), at("Wed", "Mer"), at("Thu", "Jeu"), at("Fri", "Ven"), at("Sat", "Sam"), at("Sun", "Dim")].forEach((label, i) => { const check = aField(days, label, (existing?.weekdays || [0]).includes(i), "checkbox"); check.value = i; });
    enabled = aField(form, at("Enable schedule", "Activer la programmation"), existing?.enabled || false, "checkbox");
    frequency.onchange = () => { interval.parentElement.hidden = frequency.value !== "interval"; atTime.parentElement.hidden = frequency.value === "interval"; days.hidden = frequency.value !== "weekly"; timezone.parentElement.hidden = frequency.value === "interval"; }; frequency.onchange();
    kind.onchange = () => { provider.disabled = kind.value !== "model"; }; kind.onchange();
  }
  const body = () => ({name: name.value, provider_id: provider.value, policy: {name: name.value, clients: clientInputs.filter(([, e]) => e.checked).map(([id]) => id), mode: mode.value, permissions: permissions.filter(([, e]) => e.checked && !e.disabled).map(([id]) => id), daily_bytes: Math.round(+bytes.value * 1024 ** 3), daily_torrents: +torrents.value, reserve_bytes: Math.round(+reserve.value * 1024 ** 3)}, web: web.checked, max_output_tokens: existing?.max_output_tokens ?? 2048, max_calls: +calls.value, max_seconds: +seconds.value,
    ...(scheduled ? {instruction: instruction.value, kind: kind.value, frequency: frequency.value, interval_minutes: +interval.value, at: atTime.value, timezone: timezone.value, weekdays: [...days.querySelectorAll("input:checked")].map(e => +e.value), enabled: enabled.checked} : {})});
  if (scheduled) form.append(button(at("Preview next run", "Voir la prochaine exécution"), async () => { const preview = await api("assistant/schedules/preview", body()); form.append(element("p", new Date(preview.next_at * 1000).toLocaleString())); }));
  aActions(dialog, form, async () => {
    if (scheduled) {
      await api("assistant/schedules" + (existing ? `/${existing.id}` : ""), body(), existing ? "PUT" : "POST");
    } else {
      await api(defaults ? "setup/assistant/chat" : `assistant/conversations/${existing.id}`, body(), "PUT");
    }
  });
}
setInterval(() => { if (assistantVisible() && assistantView === "chat") guard(aRefreshChat); }, 1500);

function aStatus(value) {
  return ({queued: at("Queued", "En attente"), running: at("Running", "En cours"), completed: at("Completed", "Terminée"), failed: at("Failed", "Échec"), cancelled: at("Cancelled", "Annulée"), interrupted: at("Interrupted", "Interrompue"), awaiting_approval: at("Awaiting approval", "Validation requise"), awaiting_user: at("Awaiting your answer", "Réponse requise"), waiting_settings: at("Waiting for settings to finish updating", "Mise à jour des paramètres en cours"), finished: at("Finished", "Terminé")})[value] || value;
}
