let assistantSidebarOpen = !matchMedia("(max-width: 1050px)").matches;
/* Same owner APIs as desktop; chat Markdown is rendered safely by the server. */
let assistantView = "chat", assistantConversation = "", assistantRun = "", assistantSnapshot = null;
let assistantRefreshBusy = false, assistantRenderKey = "", assistantLoadVersion = 0;
const assistantDrafts = new Map();
const assistantCollapsedFolders = new Set();
const at = (en, fr) => say(en, fr);
const assistantRoot = () => $("view-assistant");
const assistantVisible = () => state.view === "assistant";
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
      item.oncontextmenu = event => {
        event.preventDefault();
        aMenu(item, [
          [at("Rename…", "Renommer…"), () => aRename(chat)],
          [at("Move to folder…", "Déplacer vers un dossier…"), () => aMoveConversation(chat, conversations)],
          [at("Delete discussion", "Supprimer la discussion"), () => aDelete(chat)],
        ]);
      };
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
  footer.append(button(at("Save", "Enregistrer"), async () => { if (!form.reportValidity() || await save() === false) return; await loadAssistant(); if (state.view === "setup") await loadAssistantConnections(); dialog.close(); }, "primary"), button(at("Cancel", "Annuler"), () => dialog.close(), "quiet"));
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
  menu.onkeydown = event => { if(event.key === "Escape") { menu.remove(); anchor.focus(); } };
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
async function aOpenConnections() { await panelRequest("connections", {}); }
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
  assistantDrafts.delete(current.id);
  if (assistantConversation === current.id) { assistantConversation = ""; assistantRun = ""; }
  await loadAssistant();
}
// The owner service stores the acknowledgement once for desktop and Web.
async function aConfirmExecute() {
  if ((await api("setup/assistant")).execute_acknowledged) return true;
  if (!confirm(at("In this mode the assistant runs the actions allowed in this discussion's settings without asking, within its limits on clients, size and downloads per day. Removing queue entries or torrents and deleting files still need your approval.\n\nSwitch to Execute within limits? You will not be asked again.", "Dans ce mode, l’assistant exécute sans demander les actions autorisées dans les paramètres de la discussion, dans ses limites de clients, de volume et de téléchargements par jour. Retirer des entrées de la file ou des torrents, ou supprimer des fichiers, demande toujours votre accord.\n\nPasser en mode Exécuter dans les limites ? Cette question ne sera plus posée."))) return false;
  await api("setup/assistant/acknowledge-execute", {});
  return true;
}
const aModeLabel = mode => mode === "execute" ? at("Execute within limits", "Exécuter dans les limites") : at("Proposals only", "Propositions uniquement");
// In Media, the side panel header switches discussions through the host's Media session.
const aMediaChat = (conversationId = "", fresh = false) => panelRequest("media-chat", {conversation_id: conversationId, new: fresh});
function aMediaChatMenu(anchor, items) {
  const menu = $("media-chat-menu");
  if (!menu.hidden && menu.dataset.anchor === anchor.id) { menu.hidden = true; menu.replaceChildren(); return; }
  menu.replaceChildren(...items.map(([label, action, checked]) => {
    const item = button(label, () => { menu.hidden = true; menu.replaceChildren(); return action(); });
    item.setAttribute("role", checked === undefined ? "menuitem" : "menuitemradio");
    if (checked !== undefined) item.setAttribute("aria-checked", String(checked));
    return item;
  }));
  menu.dataset.anchor = anchor.id; menu.hidden = false;
  menu.querySelector("button")?.focus();
}
function aMediaChatHeader() {
  const wrap = element("div"), header = element("header", undefined, "media-chat-header"), menu = element("div", undefined, "media-chat-menu");
  menu.id = "media-chat-menu"; menu.setAttribute("role", "menu"); menu.hidden = true;
  const title = element("h2", at("Media discussion", "Discussion Médias")); title.id = "media-chat-title";
  const history = aIconButton("☰", at("Discussions", "Discussions"), async () => {
    const conversations = (await api("assistant/conversations")).filter(c => c.folder === "Media").slice(0, 20);
    aMediaChatMenu(history, [
      [at("New discussion", "Nouvelle discussion"), () => aMediaChat("", true)],
      ...conversations.map(c => [c.name, () => aMediaChat(c.id), c.id === assistantConversation]),
    ]);
  });
  history.id = "media-chat-history"; history.setAttribute("aria-haspopup", "menu");
  const more = aIconButton("⋯", at("More", "Plus"), () => aMediaChatMenu(more, [
    [at("Discussion settings", "Paramètres de la discussion"), () => $("assistant-chat-settings")?.click()],
    [at("Open in Assistant", "Ouvrir dans l’Assistant"), () => panelRequest("open-assistant", {})],
    [at("Delete discussion", "Supprimer la discussion"), async () => {
      if (!assistantConversation || !confirm(at("Delete this discussion and its history? Pending proposals will be rejected. Torrents and files will not be removed.", "Supprimer cette discussion et son historique ? Les propositions en attente seront refusées. Les torrents et fichiers ne seront pas supprimés."))) return;
      await api(`assistant/conversations/${assistantConversation}`, undefined, "DELETE");
      await aMediaChat("", true);
    }],
  ]));
  more.id = "media-chat-more"; more.setAttribute("aria-haspopup", "menu");
  const close = aIconButton("✕", at("Close chat", "Fermer la discussion"), () => panelRequest("media-chat-close", {}));
  close.id = "media-chat-close";
  header.append(title, history, more, close);
  wrap.append(header, menu);
  wrap.addEventListener("keydown", event => { if (event.key === "Escape" && !menu.hidden) { event.stopPropagation(); menu.hidden = true; menu.replaceChildren(); } });
  return wrap;
}
async function loadAssistant() {
  const version = ++assistantLoadVersion;
  const setup = await api("setup/assistant");
  if (version !== assistantLoadVersion) return;
  assistantSnapshot = setup;
  const root = assistantRoot(); root.replaceChildren(); assistantRenderKey = "";
  // In the Media Center side panel: one discussion, no tabs; folders and automations stay on the Assistant page.
  const compact = !!state.compact;
  if (compact) assistantView = "chat";
  root.classList.toggle("assistant-compact", compact);
  if (compact) root.append(aMediaChatHeader());
  const nav = element("div", undefined, "assistant-tabs"); nav.setAttribute("role", "tablist");
  for (const [id, label] of [["chat", at("Discussion", "Discussion")], ["tasks", at("Automations", "Automatisations")], ["history", at("History", "Historique")]]) {
    const tab = button(label, async () => { assistantView = id; await loadAssistant(); }, assistantView === id ? "active" : "");
    tab.setAttribute("role", "tab"); tab.setAttribute("aria-selected", String(assistantView === id));
    nav.append(tab);
  }
  if (!compact) root.append(nav);
  if (assistantView === "tasks") return aTasks(root, version);
  if (assistantView === "history") {
    const [history, conversations] = await Promise.all([api("assistant/jobs"), api("assistant/conversations")]);
    if (version !== assistantLoadVersion) return;
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
  // An empty list has nothing to resize: no stray handle.
  side.classList.toggle("assistant-empty", !conversations.length);
  layout.append(side, main); root.append(layout); rememberSidebar(side);
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
  const renderedConversation=assistantConversation;
  prompt.value = assistantDrafts.get(renderedConversation) || "";
  prompt.oninput = () => assistantDrafts.set(renderedConversation, prompt.value);
  prompt.placeholder = at("Give a task or ask a question…", "Donnez une tâche ou posez une question…"); prompt.setAttribute("aria-label", at("Message", "Message"));
  const send = element("button", "➤", "assistant-send"); send.type = "submit"; send.id = "assistant-send";
  field.append(prompt, send);
  const chips = element("div", undefined, "assistant-chips");
  const model = element("select", undefined, "assistant-chip"); model.id = "assistant-model";
  model.setAttribute("aria-label", at("Model connection", "Connexion au modèle"));
  for (const p of assistantSnapshot.providers) { const o = element("option", `${p.name} · ${p.model}`); o.value = p.id; model.append(o); }
  if ([...model.options].some(o => o.value === config.provider_id)) model.value = config.provider_id;
  const manage = element("option", at("Manage connections…", "Gérer les connexions…"));
  manage.value = "__connections__"; model.append(manage);
  let selectedModel = model.value;
  model.onchange = () => guard(async () => {
    if (model.value === "__connections__") {
      model.value = selectedModel;
      await aOpenConnections();
      return;
    }
    selectedModel = model.value;
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
    if (next === "execute" && !(await aConfirmExecute())) return;
    if (current) {
      const {id, ...body} = current;
      await api(`assistant/conversations/${id}`, {...body, policy: {...body.policy, mode: next}}, "PUT");
      current.policy.mode = next;
    } else assistantPendingMode = next;
    modeChip.textContent = aModeLabel(next);
  }, "quiet assistant-chip");
  modeChip.id = "assistant-mode"; modeChip.title = at("Switch the discussion mode", "Changer le mode de la discussion");
  chips.append(model, modeChip);
  chips.append(communityMenu(at("Community", "Communauté"), [
    [at("Share prompt", "Partager le prompt"), () => {
      if (!prompt.value.trim()) throw Error(at("Write a prompt before sharing it.", "Rédigez un prompt avant de le partager."));
      return communityShareDialog("prompt", {}, {prompt:prompt.value});
    }],
    [at("Community prompts", "Prompts communautaires"), () => communityBrowseDialog("prompt", async result => {
      prompt.value=result.data.prompt;assistantDrafts.set(renderedConversation,prompt.value);prompt.focus();
    })],
  ], "assistant-community-menu"));

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
    if (!prompt.value.trim() || send.disabled || root.inert || renderedConversation!==assistantConversation) return;
    send.disabled = true;
    const origin = renderedConversation, message = prompt.value;
    let identifier = origin;
    try {
      if (!identifier) {
        const body = {...defaults, provider_id: model.value, name: "Discussion"};
        if (assistantPendingMode) body.policy = {...body.policy, mode: assistantPendingMode};
        const chat = await api("assistant/conversations", body);
        identifier = chat.id; assistantPendingMode = "";
        assistantDrafts.set(identifier, message); assistantDrafts.delete("");
      }
      // The Media host reports its player and selection before the run reads them.
      if (state.compact) await panelRequest("media-heartbeat", {});
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
  }, false); }; // The send button runs its own busy/stop states: no automatic busy button.
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
    if (href.startsWith("/documentation/") && state.mode !== "desktop") link.href = new URL("../../" + href.slice(1), document.baseURI).href;
    link.rel = "noopener noreferrer";
    link.target = "_blank";
  }
  for (const image of content.querySelectorAll("img")) {
    loadPanelImage(image, image.getAttribute("src"));
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
async function aTasks(root, version) {
  const top = element("div", undefined, "assistant-tasks-top");
  top.append(element("p", at("Tasks run while TorrentLinker is running. On desktop, keep the app open; on Docker, closing this browser is fine. Missed intervals are combined into one run. Failed/interrupted runs wait for review and Run now.", "Les tâches s’exécutent lorsque TorrentLinker fonctionne. Sur PC, gardez l’application ouverte ; sur Docker, vous pouvez fermer le navigateur. Les échéances manquées sont regroupées en une exécution. Les exécutions échouées ou interrompues attendent votre vérification et Exécuter maintenant."), "muted"), button(at("Create task", "Créer une tâche"), () => aTaskEditor(true), "primary"));
  root.append(top);
  const tasks = await api("assistant/schedules");
  if (version !== assistantLoadVersion) return;
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
  for (const [input, minimum, maximum] of [
    [bytes, 0, 1000000], [torrents, 0, 1000], [reserve, 0, 1000000],
    [calls, scheduled ? 1 : 0, scheduled ? 40 : 200],
    [seconds, scheduled ? 10 : 0, 1800],
  ]) {
    input.min = minimum; input.max = maximum; input.step = input === bytes || input === reserve ? "any" : "1"; input.required = true;
  }
  const web = aField(form, at("Allow public Web research", "Autoriser la recherche sur le Web public"), existing?.web || false, "checkbox");
  let instruction, kind, frequency, interval, atTime, timezone, days, enabled;
  if (scheduled) {
    instruction = aField(form, at("Instructions", "Instructions"), existing?.instruction || "", "textarea");
    kind = aField(form, at("Task type", "Type de tâche"), existing?.kind || "model", "", [["model", at("Model task", "Tâche avec modèle")], ["refresh", at("Refresh torrents (no model)", "Actualiser les torrents (sans modèle)")], ["catalogue", at("Refresh Catalogue (no model)", "Actualiser le Catalogue (sans modèle)")]]);
    frequency = aField(form, at("Frequency", "Fréquence"), existing?.frequency || "daily", "", [["interval", at("Every X minutes", "Toutes les X minutes")], ["daily", at("Daily", "Quotidienne")], ["weekly", at("Weekly", "Hebdomadaire")]]);
    interval = aField(form, at("Interval, minutes", "Intervalle, minutes"), existing?.interval_minutes || 60, "number"); interval.min = 5; interval.max = 525600; interval.step = 1; interval.required = true;
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
  if (scheduled) form.append(button(at("Preview next run", "Voir la prochaine exécution"), async () => { if (!form.reportValidity()) return; const preview = await api("assistant/schedules/preview", body()); form.append(element("p", new Date(preview.next_at * 1000).toLocaleString())); }));
  aActions(dialog, form, async () => {
    if (mode.value === "execute" && !(await aConfirmExecute())) return false;
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

/* Persisted selection presentations. Opening details never starts a model turn. */
const assistantPresentationPages = new Map(), assistantPresentationOffsets = new Map();
const aCardKinds = {
  movie: ["Film", "Film"], series: ["Series", "Série"], ebook: ["Book", "Livre"],
  comic: ["Comic", "BD"], music: ["Music", "Musique"], game: ["Game", "Jeu"],
  software: ["Software", "Logiciel"], model3d: ["3D model", "Modèle 3D"], other: ["Content", "Contenu"]
};
function aSavedImage(value) {
  if (/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(value || "") && value.length <= 10666800) return value;
  return /^https?:\/\//i.test(value || "") ? "api/assistant/image?url=" + encodeURIComponent(value) : "";
}
function aCardArtwork(item, large = false) {
  const art = element("div", undefined, "selection-artwork" + (large ? " large" : ""));
  art.dataset.kind = item.kind;
  const label = at(...(aCardKinds[item.kind] || aCardKinds.other));
  art.append(element("span", label));
  if (aSavedImage(item.image_url)) {
    const img = element("img");
    img.alt = item.content_title || item.title;
    img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    loadPanelImage(img, aSavedImage(item.image_url));
    img.addEventListener("load", () => art.querySelector("span")?.remove(), {once: true});
    img.addEventListener("error", () => img.remove(), {once: true});
    art.append(img);
  }
  return art;
}
function aCardSize(item) {
  if (item.presentation_type === "media") {
    const value = item.facts?.Availability || item.availability;
    return ({available: at("Available", "Disponible"), unavailable: at("Unavailable", "Indisponible"), unfinished: at("Still downloading", "Téléchargement en cours")})[value] || value || "";
  }
  const size = item.size_bytes == null ? at("Unknown size", "Taille inconnue") : bytes(item.size_bytes);
  return item.presentation_type === "upload_drafts" ? size : size + " · " + (item.seeders ?? "—") + " sources";
}
function aUploadSummary(item) {
  const states = {queued: at("Awaiting review", "À relire"), sending: at("Send started; verify the result on c411", "Envoi lancé ; vérifiez le résultat sur c411"),
    sent: at("Sent to c411", "Envoyé à c411"), uncertain: at("Check c411 before retrying", "Vérifiez c411 avant de réessayer")};
  const status = states[(item.draft_changed ? item.saved_status : item.current_status) || item.saved_status] || at("Saved draft", "Brouillon enregistré");
  let text = `${at("Upload draft", "Brouillon Upload")} · ${at("revision", "révision")} ${item.draft_revision} · ${status}`;
  text += ` · ${item.review_summary?.refusals || 0} ${at("refusals", "refus")} · ${item.review_summary?.warnings || 0} ${at("warnings", "avertissements")}`;
  if (item.draft_deleted) text += " · " + at("Draft removed. Saved review snapshot.", "Brouillon supprimé. Copie de relecture enregistrée.");
  else if (item.draft_changed) text += " · " + at("Draft changed. Review the current revision before sending.", "Brouillon modifié. Relisez la révision actuelle avant l'envoi.");
  return element("span", text, "selection-upload-summary");
}
function aCardScores(item) {
  const value = (n, places) => typeof n === "number" && Number.isFinite(n) ? n.toFixed(places) : "—";
  const label = element("span",
    `Note ${value(item.torrent_note, 2)} · ≈ ${value(item.estimated_zen_per_day, 3)} ${at("Zen/day", "Zen/jour")}`,
    "selection-scores");
  label.title = item.zen_assumptions || "";
  return label;
}
async function aPresentationItem(identifier, itemId) {
  return aCardDetail(() => api(`assistant/presentations/${encodeURIComponent(identifier)}/items/${encodeURIComponent(itemId)}`));
}
async function aCardDetail(load) {
  const {dialog, form} = aDialog(at("Selection details", "Détails de la sélection"));
  dialog.classList.add("selection-detail");
  const body = element("div", at("Loading details…", "Chargement des détails…"));
  form.append(body, button(at("Close", "Fermer"), () => dialog.close(), "quiet"));
  try {
    const item = await load();
    if (!dialog.isConnected) return;
    if (item.presentation_type === "upload_drafts") form.querySelector("h2").textContent = at("Upload draft review", "Relecture du brouillon Upload");
    body.replaceChildren(element("h3", item.content_title || item.title));
    const header = element("div", undefined, "selection-detail-header"), info = element("div");
    if (item.presentation_type === "upload_drafts") header.classList.add("upload-review-header");
    info.append(element("p", item.title, "selection-release"), element("p", aCardSize(item), "muted"));
    if (item.presentation_type !== "media") info.append(item.presentation_type === "upload_drafts" ? aUploadSummary(item) : aCardScores(item));
    if (item.zen_assumptions) info.append(element("p", item.zen_assumptions, "muted"));
    const facts = element("dl", undefined, "selection-facts");
    const labels = {Category: at("Category", "Catégorie"), Subcategory: at("Subcategory", "Sous-catégorie"), Source: at("Source", "Source"), Files: at("Files", "Fichiers"), Status: at("Status", "État"), Availability: at("Availability", "Disponibilité"), Artist: at("Artist", "Artiste"), Metadata: at("Metadata", "Métadonnées")};
    for (const [name, value] of Object.entries(item.facts || {})) facts.append(element("dt", labels[name] || name), element("dd", String(value)));
    info.append(facts);
    if (item.note) info.append(element("p", item.note));
    header.append(aCardArtwork(item, true), info); body.append(header);
    const description = element("div", undefined, "selection-description");
    // Server returns sanitized Indexer HTML, never model-generated HTML. Keep only
    // description formatting here; artwork always uses the authenticated proxy.
    if (item.description_html) {
      const template = document.createElement("template");
      template.innerHTML = item.description_html;
      const allowed = new Set(["P", "DIV", "SPAN", "B", "STRONG", "I", "EM", "U", "S", "BR", "HR",
        "H1", "H2", "H3", "H4", "PRE", "CODE", "BLOCKQUOTE", "UL", "OL", "LI",
        "TABLE", "THEAD", "TBODY", "TR", "TD", "TH", "A", "IMG"]);
      for (const node of template.content.querySelectorAll("*")) {
        if (!allowed.has(node.tagName)) { node.remove(); continue; }
        const href = node.tagName === "A" ? node.getAttribute("href") : "";
        const imageIndex = /^preview-image:(\d+)$/.exec(node.getAttribute("src") || "");
        const align = node.getAttribute("align");
        const color = node.style.color, fontSize = node.style.fontSize;
        const width = node.getAttribute("width");
        for (const attr of [...node.attributes]) node.removeAttribute(attr.name);
        if (["left", "center", "right"].includes(align)) node.style.textAlign = align;
        if (/^(#[0-9a-f]{3,6}|[a-z]{1,20}|rgb\([\d, ]+\))$/i.test(color)) node.style.color = color;
        if (/^\d{1,2}px$/.test(fontSize)) node.style.fontSize = `${Math.min(36, Math.max(8, parseInt(fontSize)))}px`;
        if (node.tagName === "IMG") {
          const url = imageIndex ? item.description_images?.[Number(imageIndex[1])] : "";
          if (!aSavedImage(url)) { node.remove(); continue; }
          loadPanelImage(node, aSavedImage(url));
          node.alt = at("Presentation image", "Image de présentation");
          node.loading = "lazy"; node.referrerPolicy = "no-referrer";
          if (/^\d+$/.test(width || "")) node.width = Math.min(600, Math.max(1, Number(width)));
          node.addEventListener("error", () => node.replaceWith(element("span", at("Image unavailable", "Image indisponible"))), {once: true});
        }
        if (href && /^https?:\/\//i.test(href)) {
          node.href = href; node.target = "_blank"; node.rel = "noopener noreferrer";
        }
      }
      description.append(template.content);
    } else description.textContent = item.description || at("No description available.", "Aucune description disponible.");
    if (item.presentation_type === "upload_drafts") {
      body.append(element("p", at("Reviewing these cards does not approve or send the draft.", "Consulter ces fiches ne valide ni n'envoie le brouillon.")));
      const review = item.upload_review || {};
      const reviewContent = element("div");
      for (const [title, values] of [[at("Refusals", "Refus"), review.refusals || []], [at("Warnings", "Avertissements"), review.warnings || []]]) {
        reviewContent.append(element("h3", title), element("pre", values.length ? values.join("\n") : at("None", "Aucun")));
      }
      aReviewTabs(body, [
        [at("Presentation", "Présentation"), description],
        ["NFO", element("pre", item.nfo || at("No NFO available.", "Aucun NFO disponible."))],
        [at("Files", "Fichiers"), element("pre", (item.files || []).map(file => `${file.path} · ${bytes(file.size)}`).join("\n"))],
        [at("Category options", "Options de catégorie"), element("pre", JSON.stringify(item.upload_form?.options || {}, null, 2))],
        [at("Review", "Relecture"), reviewContent],
      ]);
    } else body.append(description);
    if (/^https?:\/\//i.test(item.source_url || "")) {
      const link = element("a", at("Open source", "Ouvrir la source"));
      link.href = item.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
      body.append(link);
    }
  } catch (error) {
    if (dialog.isConnected) { body.textContent = error.message; body.classList.add("error"); }
  }
}
function aSelectionCards(identifier) {
  const section = element("section", undefined, "selection-presentation");
  section.setAttribute("aria-label", at("Saved selection", "Sélection enregistrée"));
  const title = element("h3", at("Loading selection…", "Chargement de la sélection…"));
  const status = element("p", "", "muted"), grid = element("div", undefined, "selection-grid");
  const footer = element("div", undefined, "selection-pagination");
  let offset = assistantPresentationOffsets.get(identifier) || 0, nextOffset = null;
  const previous = button(at("Previous", "Précédent"), () => load(Math.max(0, offset - 12)));
  const next = button(at("Next", "Suivant"), () => load(nextOffset));
  footer.append(previous, next); section.append(title, status, grid, footer);
  async function load(position) {
    offset = position; assistantPresentationOffsets.set(identifier, offset);
    previous.disabled = next.disabled = true;
    status.textContent = at("Loading…", "Chargement…");
    const key = identifier + ":" + offset;
    try {
      if (!assistantPresentationPages.has(key)) {
        const promise = api(`assistant/presentations/${encodeURIComponent(identifier)}?offset=${offset}&limit=12`);
        assistantPresentationPages.set(key, promise);
        promise.catch(() => assistantPresentationPages.delete(key));
        if (assistantPresentationPages.size > 64) assistantPresentationPages.delete(assistantPresentationPages.keys().next().value);
      }
      const page = await assistantPresentationPages.get(key);
      if (!section.isConnected || offset !== position) return;
      title.textContent = page.title;
      if (page.presentation_type === "upload_drafts") assistantPresentationPages.delete(key);
      status.textContent = `${page.items.length ? offset + 1 : 0}–${offset + page.items.length} / ${page.count} · ${page.presentation_type === "upload_drafts" ? at("saved Upload drafts", "brouillons Upload enregistrés") : page.presentation_type === "media" ? at("saved media selection", "sélection de médias enregistrée") : at("saved revision", "révision enregistrée") + " " + (page.revision ?? "")}`;
      grid.replaceChildren();
      for (const item of page.items) {
        const card = button("", () => aPresentationItem(identifier, item.item_id), "selection-card");
        card.dataset.kind = item.kind;
        card.setAttribute("aria-label", item.content_title || item.title);
        card.append(aCardArtwork(item), element("strong", item.content_title || item.title));
        if (item.subtitle) card.append(element("span", item.subtitle, "muted"));
        card.append(element("span", aCardSize(item), "selection-size"));
        if (item.presentation_type !== "media") card.append(item.presentation_type === "upload_drafts" ? aUploadSummary(item) : aCardScores(item));
        if (item.note) card.append(element("span", item.note, "selection-note"));
        grid.append(card);
      }
      nextOffset = page.next_offset;
      previous.disabled = offset === 0; next.disabled = !page.has_more;
    } catch (error) {
      if (section.isConnected) { status.textContent = error.message; previous.disabled = offset === 0; }
    }
  }
  // Defer until aRunCard has attached the section to the document.
  queueMicrotask(() => load(offset));
  return section;
}

let reviewTabSequence = 0;
function aReviewTabs(host, sections) {
  const id = `upload-review-${++reviewTabSequence}`;
  const nav = element("div", undefined, "toolbar review-tabs");
  nav.setAttribute("role", "tablist");
  nav.setAttribute("aria-label", at("Upload draft review", "Relecture du brouillon Upload"));
  const panels = [], tabs = [];
  function select(index) {
    tabs.forEach((tab, i) => {
      tab.setAttribute("aria-selected", String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
    });
  }
  host.append(nav);
  sections.forEach(([label, content], index) => {
    const panel = element("section", undefined, "review-panel");
    panel.id = `${id}-panel-${index}`; panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", `${id}-tab-${index}`); panel.tabIndex = 0;
    panel.append(content); panels.push(panel); host.append(panel);
    const tab = button(label, () => select(index));
    tab.id = `${id}-tab-${index}`; tab.type = "button";
    tab.setAttribute("role", "tab"); tab.setAttribute("aria-controls", panel.id);
    tab.onkeydown = event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? sections.length - 1 : (index + (event.key === "ArrowRight" ? 1 : sections.length - 1)) % sections.length;
      select(next); tabs[next].focus();
    };
    tabs.push(tab); nav.append(tab);
  });
  select(0);
}

// Escape closes a menu first, a dialog next, and an empty Media composer last.
document.addEventListener("keydown", event => {
  if(event.key!=="Escape" || !state.compact || document.querySelector("dialog[open]"))return;
  const menu=$("media-chat-menu");
  if(menu&&!menu.hidden){event.preventDefault();menu.hidden=true;document.getElementById(menu.dataset.anchor)?.focus();return}
  if(!$("assistant-prompt")?.value.trim()){event.preventDefault();guard(()=>panelRequest("media-chat-close",{}))}
});
document.addEventListener("click",event=>{
  const menu=$("media-chat-menu");
  if(menu&&!menu.hidden&&!event.target.closest(".media-chat-header,.media-chat-menu"))menu.hidden=true;
});
