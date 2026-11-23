"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const e = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  let language = "fr",
    active = false,
    data = null,
    messages = [],
    busy = false,
    signature = "",
    account = "";
  let tab = "torrents",
    selected = "",
    action = "comment",
    query = "",
    filter = "all",
    sort = "recent",
    limit = 60;
  let queueDisplay = "calendar",
    calendarScale = "week",
    calendarAnchor = new Date(),
    calendarSelected = dateKey(new Date()),
    calendarKind = "";
  let historyPeriod = "all",
    historyQuery = "",
    historyKind = "",
    historyFrom = "",
    historyTo = "",
    historyMonth = new Date();
  let generation = 0,
    libraryObserver = null;
  let drafts = {},
    chatDraft = {},
    editing = null,
    restoreFocus = null;
  const kinds = ["comment", "vote", "chat"],
    editable = ["draft", "queued", "paused", "refused", "cancelled"];
  const t = (fr, en) => window.TLPanel.t(fr, en);
  const kindName = (k) =>
    ({
      comment: t("Commentaire", "Comment"),
      vote: t("Vote", "Vote"),
      chat: t("Chat", "Chat"),
    })[k];
  const stateName = (s) =>
    ({
      none: t("Non renseigné", "Not recorded"),
      draft: t("Brouillon", "Draft"),
      queued: t("Programmé", "Queued"),
      paused: t("Suspendu", "Paused"),
      sending: t("Envoi", "Sending"),
      posted: t("Publié", "Posted"),
      uncertain: t("À vérifier", "Check on c411"),
      refused: t("Refusé", "Refused"),
      cancelled: t("Annulé", "Cancelled"),
    })[s] || s;
  const icons = {
    search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    settings:
      '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    sync: '<path d="M4 10a8 8 0 0 1 13-4l3 3M20 14a8 8 0 0 1-13 4l-3-3M20 4v5h-5M4 20v-5h5"/>',
    arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    play: '<path d="m8 4 12 8-12 8Z"/>',
    zen: '<path d="m12 3 2 6 6 3-6 2-2 7-2-7-7-2 7-3Z"/>',
  };
  const icon = (name) =>
    `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${icons[name] || ""}</svg>`;
  const btn = (label, cmd, cls = "", attr = "") =>
    `<button type="button" class="${cls}" data-command="${cmd}" ${attr}>${label}</button>`;
  const options = (rows, selectedValue) =>
    rows
      .map(
        ([value, label]) =>
          `<option value="${e(value)}" ${value === selectedValue ? "selected" : ""}>${e(label)}</option>`,
      )
      .join("");
  const field = (label, control) =>
    `<label class="form-field">${label}${control}</label>`;
  const input = (id, type, value, attrs = "") =>
    `<input id="${id}" type="${type}" value="${e(value)}" ${attrs}>`;
  const toggle = (id, label, checked) =>
    `<label class="toggle"><span>${label}</span><input id="${id}" type="checkbox" role="switch" ${checked ? "checked" : ""}></label>`;
  function dateKey(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  const date = (stamp) => new Date(stamp * 1000);
  const at = (item) => item.next_at || item.due;
  const time = (stamp) =>
    date(stamp).toLocaleTimeString(language, {
      hour: "2-digit",
      minute: "2-digit",
    });
  const fullDate = (key) =>
    new Date(key + "T12:00:00").toLocaleDateString(language, {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  const localInput = (stamp) =>
    `${dateKey(date(stamp))}T${String(date(stamp).getHours()).padStart(2, "0")}:${String(date(stamp).getMinutes()).padStart(2, "0")}`;
  function badge(state, vote = "") {
    return `<span class="pill ${state === "posted" ? "green" : state === "queued" ? "blue" : ["uncertain", "refused"].includes(state) ? "amber" : ""}">${state === "posted" ? icon("check") : ""}${e(state === "posted" && vote ? (vote === "approve" ? t("Approuvé", "Approved") : t("Désapprouvé", "Disapproved")) : stateName(state))}</span>`;
  }
  function cover(c) {
    return `<div class="cover" style="--c:${["#946344", "#557b8d", "#817b3f", "#657d72", "#967e51", "#765c85"][parseInt(c.hash.slice(-4), 16) % 6]}"><span>${e(c.title)}</span></div>`;
  }
  function notify(message, kind = "ok") {
    TLToast.show(message, kind);
  }
  async function request(path, body) {
    return (await window.communityTransport)(path, body);
  }
  async function change(operation, body) {
    const current = generation;
    const result = await request(`community/${operation}`, body);
    if (current !== generation)
      throw new Error(t("Le compte a changé.", "The account changed."));
    accept(result);
    return result;
  }
  function capture() {
    if (!data) return;
    if ($("community-content"))
      drafts[selected + ":" + action] = {
        content: $("community-content").value,
        vote: $("community-vote")?.value || "",
        due: $("community-due").value,
        mode: $("community-due-choice").value,
      };
    if ($("chat-content"))
      chatDraft = {
        content: $("chat-content").value,
        channel: chatDraft.channel,
        due: $("chat-due").value,
        mode: $("chat-due-choice").value,
      };
  }
  function accept(next) {
    if (account !== next.account_id) {
      clear();
      account = next.account_id;
    }
    capture();
    data = next;
    const nextSignature = JSON.stringify([
      next.items.map(({ next_at, ...item }) => ({
        ...item,
        estimatedMinute: Math.floor((next_at || item.due) / 60),
      })),
      next.candidates,
      next.channels,
      next.settings,
      next.quotas,
      next.refresh_pending,
      next.paired,
    ]);
    if (signature !== nextSignature) {
      signature = nextSignature;
      render();
    } else renderStatus();
  }
  function clear() {
    generation += 1;
    data = null;
    signature = "";
    account = "";
    selected = "";
    drafts = {};
    chatDraft = {};
    editing = null;
    closeDrawer();
    $("community-app").innerHTML = "";
  }
  function renderStatus() {
    if (!data || !$("sync")) return;
    $("sync").innerHTML =
      `${icon(data.refresh_pending ? "sync" : data.paired ? "check" : "clock")} <span>${data.refresh_pending ? t("Synchronisation automatique…", "Synchronizing automatically…") : !data.paired ? t("Liste enregistrée · en attente du navigateur", "Saved library · waiting for browser") : t("À jour · compagnon connecté", "Up to date · companion connected")}</span>${btn(icon("sync"), "refresh", "small ghost", `aria-label="${t("Actualiser la bibliothèque", "Refresh library")}"`)}`;
    $("sync")
      .querySelector("svg")
      ?.classList.toggle("spin", Boolean(data.refresh_pending));
  }
  function render() {
    if (!data) return;
    const focused = document.activeElement,
      focusId = focused?.id,
      selection = focused?.selectionStart,
      selectionEnd = focused?.selectionEnd,
      selectionDirection = focused?.selectionDirection;
    const scroll = window.scrollY;
    const count = data.items.filter(
      (i) => !["posted", "cancelled"].includes(i.state),
    ).length;
    $("community-app").innerHTML =
      `<div class="community-controls"><span class="sync">${!data.paired ? t("Connectez le compagnon dans les paramètres pour publier.", "Connect the companion in Settings to publish.") : ""}</span>${btn(icon("zen") + " " + (!data.settings.automation.enabled ? t("Mode automatique", "Automatic mode") : data.settings.enabled ? t("Auto · actif", "Auto · active") : t("Auto · en pause", "Auto · paused")), "automation", "small")}${btn(icon("settings"), "settings", "ghost small", `aria-label="${t("Réglages de la communauté", "Community settings")}"`)}</div><section class="row between heading"><div><h2 class="content-heading">${t("Chaque contribution compte.", "Every contribution counts.")}</h2><p class="muted">${t("Retrouvez vos torrents, participez et gardez le fil.", "Find your torrents, take part and keep track.")}</p></div><div class="metrics">${kinds
        .map((k) => {
          const q = data.quotas[k],
            used = q.site_used ?? q.local_used;
          return `<div class="metric" title="${e(t("Tentatives locales sur 24 h", "Local attempts in 24 h"))}: ${q.local_used}"><small>${e(k === "comment" ? t("Commentaires aujourd’hui", "Comments today") : k === "vote" ? t("Votes aujourd’hui", "Votes today") : t("Chat aujourd’hui", "Chat today"))}</small><strong>${used}<span class="muted" style="font-size:12px"> / ${q.limit}</span></strong><div class="track"><i style="width:${q.limit ? Math.min(100, (used / q.limit) * 100) : 0}%"></i></div></div>`;
        })
        .join(
          "",
        )}</div></section><div class="row between workbar"><nav class="tabs" aria-label="${t("Vues communauté", "Community views")}">${[
        ["torrents", "Torrents", data.candidates.length],
        ["chat", "Chat", ""],
        ["queue", t("File d’attente", "Waitlist"), count],
        ["history", t("Historique", "History"), ""],
      ]
        .map(([key, label, n]) =>
          btn(
            label + (n !== "" ? `<span class="count">${n}</span>` : ""),
            "tab",
            tab === key ? "selected" : "",
            `data-tab="${key}" aria-current="${tab === key ? "page" : "false"}"`,
          ),
        )
        .join(
          "",
        )}</nav><div class="sync" id="sync" role="status"></div></div><div id="content">${tab === "torrents" ? libraryHTML() : tab === "chat" ? chatHTML() : tab === "queue" ? queueHTML() : historyHTML()}</div>`;
    renderStatus();
    bindInputs();
    if (focusId && $(focusId)) {
      $(focusId).focus({ preventScroll: true });
      if (
        selection != null &&
        (["text", "search"].includes($(focusId).type) ||
          $(focusId).tagName === "TEXTAREA")
      )
        $(focusId).setSelectionRange(
          selection,
          selectionEnd,
          selectionDirection,
        );
    }
    window.scrollTo(0, scroll);
  }
  function activity(hash, k) {
    return data.items.filter((i) => i.subject === hash && (!k || i.kind === k));
  }
  function latest(hash, k) {
    const rows = activity(hash, k);
    return (
      rows.find((i) => i.state === "posted") ||
      rows.find((i) => i.state !== "cancelled") ||
      null
    );
  }
  function libraryRows() {
    const rows = data.candidates.filter((c) => {
      if (
        !(c.title + " " + c.hash)
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase())
      )
        return false;
      const items = activity(c.hash);
      return (
        filter === "all" ||
        (filter === "comment" && !latest(c.hash, "comment")) ||
        (filter === "vote" && !latest(c.hash, "vote")) ||
        (filter === "queued" &&
          items.some((i) =>
            ["queued", "paused", "sending"].includes(i.state),
          )) ||
        (filter === "attention" &&
          items.some((i) => ["uncertain", "refused"].includes(i.state)))
      );
    });
    return rows.sort(
      sort === "title"
        ? (a, b) => a.title.localeCompare(b.title)
        : (a, b) => b.seen - a.seen,
    );
  }
  function libraryHTML() {
    const rows = libraryRows();
    if (!data.candidates.some((c) => c.hash === selected))
      selected = rows[0]?.hash || "";
    return `<div class="workspace"><section class="panel library"><div class="tools"><div class="row"><label class="search">${icon("search")}<input id="community-library-search" type="search" aria-label="${t("Rechercher un torrent", "Search torrents")}" placeholder="${t("Rechercher dans mes torrents…", "Search my torrents…")}" value="${e(query)}"></label><select id="library-sort" aria-label="${t("Trier les torrents", "Sort torrents")}">${options(
      [
        ["recent", t("Récents", "Recent")],
        ["title", t("Titre A → Z", "Title A → Z")],
      ],
      sort,
    )}</select></div><div class="filters">${[
      ["all", t("Tous", "All")],
      ["comment", t("Sans commentaire", "No comment")],
      ["vote", t("Sans vote", "No vote")],
      ["queued", t("Programmés", "Scheduled")],
      ["attention", t("À vérifier", "Needs attention")],
    ]
      .map(([key, label]) =>
        btn(
          label,
          "filter",
          filter === key ? "selected" : "",
          `data-filter="${key}"`,
        ),
      )
      .join(
        "",
      )}</div></div><div id="community-library"><div class="table-head"><span>Torrent</span><span>${t("Commentaire", "Comment")}</span><span class="vote-cell">Vote</span></div>${
      rows
        .slice(0, limit)
        .map(
          (c) =>
            `<button type="button" class="torrent ${c.hash === selected ? "chosen" : ""}" data-command="select" data-hash="${e(c.hash)}" aria-label="${e(t("Ouvrir ", "Open ") + c.title)}"><span class="identity">${cover(c)}<span class="grow"><strong>${e(c.title)}</strong><span class="meta">${t("En seed · bibliothèque synchronisée", "Seeding · synchronized library")}</span></span></span><span>${badge(latest(c.hash, "comment")?.state || "none")}</span><span class="vote-cell">${badge(latest(c.hash, "vote")?.state || "none", latest(c.hash, "vote")?.vote)}</span></button>`,
        )
        .join("") ||
      `<div class="empty">${data.refresh_pending ? t("Recherche de vos torrents en seed…", "Discovering your seeded torrents…") : t("Aucun torrent correspondant.", "No matching torrents.")}</div>`
    }</div><div class="library-more" id="library-more" ${rows.length <= limit ? "hidden" : ""}></div><div class="library-foot"><span>${rows.length} ${t("torrents en seed", "seeded torrents")}</span><span>${t("États connus de TorrentLinker", "States recorded in TorrentLinker")}</span></div></section>${innerWidth >= 950 ? `<aside class="panel inspector" id="community-detail">${detailHTML()}</aside>` : ""}</div>`;
  }
  function detailHTML() {
    const c = data.candidates.find((c) => c.hash === selected);
    if (!c)
      return `<p class="help">${t("Choisissez un torrent pour préparer une contribution.", "Choose a torrent to prepare a contribution.")}</p>`;
    const items = activity(c.hash),
      current = latest(c.hash, action),
      draft =
        drafts[selected + ":" + action] ||
        (current?.state === "draft"
          ? {
              content: current.content,
              vote: current.vote,
              due: localInput(current.due),
            }
          : {});
    return `<div class="row between"><span class="eyebrow">${t("Le torrent sélectionné", "Selected torrent")}</span><span class="pill dot green">${t("En seed", "Seeding")}</span></div><div class="hero">${cover(c)}<div><h2>${e(c.title)}</h2><span class="tiny muted">${t("Torrent de votre bibliothèque", "Torrent from your library")}</span></div></div><div class="segment">${[
      ["comment", t("Commenter", "Comment")],
      ["vote", t("Voter", "Vote")],
    ]
      .map(([k, label]) =>
        btn(
          label,
          "action",
          action === k ? "selected" : "",
          `data-kind="${k}"`,
        ),
      )
      .join("")}</div>${
      current &&
      ["posted", "queued", "paused", "sending", "uncertain"].includes(
        current.state,
      )
        ? `<div class="chat-preview">${badge(current.state, current.vote)}<p class="help">${t("Cette action figure dans votre suivi. Retrouvez son contenu et son état avant de continuer.", "This action is recorded. Review its content and status before continuing.")}</p>${btn(t("Examiner l’opération", "Inspect operation"), "inspect", "small", `data-id="${e(current.id)}"`)}</div>`
        : `${
            action === "vote"
              ? field(
                  t(
                    "Votre avis sur cette release",
                    "Your opinion of this release",
                  ),
                  `<select id="community-vote">${options(
                    [
                      ["", t("Choisir un vote…", "Choose your vote…")],
                      ["approve", t("Approuver", "Approve")],
                      ["disapprove", t("Désapprouver", "Disapprove")],
                    ],
                    draft.vote || "",
                  )}</select>`,
                )
              : ""
          }<label class="label" for="community-content">${action === "comment" ? t("Votre commentaire", "Your comment") : t("Précision / raison", "Details / reason")}</label><textarea id="community-content" maxlength="500" placeholder="${t("Un retour sur la qualité, les pistes audio, les sous-titres…", "Feedback on quality, audio tracks, subtitles…")}">${e(draft.content || "")}</textarea><div class="row between tiny muted" style="margin:7px 0 14px">${btn(t("Insérer mon modèle", "Insert my template"), "template", "small ghost")}<span id="characters">${(draft.content || "").length}/500</span></div>${dueField("community-due", draft.due, draft.mode)}<p class="help">${t("Créneau estimé selon vos limites et celles du site.", "Estimated slot based on your limits and the site limits.")}</p><div class="detail-actions">${btn(t("Brouillon", "Save draft"), "save-draft")}${btn(icon("clock") + t("Programmer", "Schedule"), "schedule", "primary")}</div>`
    }<div class="line"></div><div class="row between"><h3>${t("Sur ce torrent", "On this torrent")}</h3><span class="tiny muted">${items.length} ${t("actions", "actions")}</span></div>${items.length ? `<div class="timeline">${items.map((i) => `<div class="event"><small>${date(i.updated || i.created).toLocaleString(language)}</small><b>${kindName(i.kind)} · ${stateName(i.state)}</b><p>${e(i.content)}</p>${btn(t("Détails", "Details"), "inspect", "small ghost", `data-id="${e(i.id)}"`)}</div>`).join("")}</div>` : `<p class="help">${t("Aucune action enregistrée dans TorrentLinker. L’accès sera vérifié sur c411 avant l’envoi.", "No action recorded in TorrentLinker. Eligibility is checked on c411 before sending.")}</p>`}<a class="site-link" href="https://c411.org/torrents/${e(c.hash)}" ${location.protocol === "file:" ? "" : 'target="_blank" rel="noopener noreferrer"'}>${t("Ouvrir sur c411 ↗", "Open on c411 ↗")}</a>`;
  }
  async function saveLibrary(queue) {
    capture();
    const c = data.candidates.find((c) => c.hash === selected),
      draft = drafts[selected + ":" + action];
    const existing = activity(selected, action).find(
      (i) => i.state === "draft",
    );
    const payload = {
      kind: action,
      subject: selected,
      title: c.title,
      content: draft.content,
      vote: draft.vote,
      due: new Date(draft.due).getTime() / 1000,
    };
    const key = selected + ":" + action;
    const savedContent = draft.content;
    await saveOperation(payload, existing, queue);
    if (drafts[key]?.content === savedContent) delete drafts[key];
    if ($("drawer").dataset.inspector) closeDrawer();
    render();
  }
  async function saveOperation(payload, existing, queue) {
    if (!Number.isFinite(payload.due))
      throw new Error(t("Choisissez une date valide.", "Choose a valid date."));
    if (existing)
      Object.assign(payload, { id: existing.id, revision: existing.revision });
    payload.content = payload.content.trim();
    const previousIds = new Set(data.items.map((item) => item.id));
    const next = await change("save", payload);
    const item = existing
      ? next.items.find((i) => i.id === existing.id)
      : next.items.find(
          (i) =>
            i.kind === payload.kind &&
            i.subject === payload.subject &&
            i.content === payload.content &&
            !previousIds.has(i.id),
        );
    if (!item)
      throw new Error(
        t(
          "Le brouillon n’a pas pu être retrouvé. Consultez la file avant de réessayer.",
          "The saved draft could not be found. Check the waitlist before trying again.",
        ),
      );
    if (queue && item.state !== "queued")
      await change("control", {
        id: item.id,
        revision: item.revision,
        action: "queue",
      });
    notify(
      queue
        ? t(
            "Action programmée dans la file d’attente.",
            "Action scheduled in the waitlist.",
          )
        : t("Brouillon enregistré.", "Draft saved."),
    );
  }
  function dueField(id, value, mode) {
    const chosen = mode || (value ? "custom" : "asap");
    return field(
      t("Quand l’envoyer ?", "When to send?"),
      `<select id="${id}-choice" data-due-target="${id}">${options(
        [
          ["asap", t("Dès que possible", "As soon as possible")],
          ["tomorrow", t("Demain matin, 09:00", "Tomorrow morning, 09:00")],
          ["hour", t("Dans une heure", "In an hour")],
          ["custom", t("Date et heure…", "Date and time…")],
        ],
        chosen,
      )}</select>${input(id, "datetime-local", value || localInput(Date.now() / 1000), chosen === "custom" ? "" : "hidden")}`,
    );
  }
  function chatHTML() {
    const selectedChannel =
      data.channels.find((c) => String(c.id) === String(chatDraft.channel)) ||
      data.channels[0];
    if (!chatDraft.channel && selectedChannel)
      chatDraft.channel = String(selectedChannel.id);
    const last = data.items
      .filter((i) => i.kind === "chat" && i.state === "posted")
      .sort((a, b) => b.posted - a.posted)[0];
    const q = data.quotas.chat;
    return `<div class="chat-grid"><section class="panel"><div class="row between" style="margin-bottom:22px"><h2>${t("Une pensée à partager ?", "A thought to share?")}</h2><span class="pill">${Math.max(0, q.limit - (q.site_used ?? q.local_used))} ${t("messages disponibles", "messages available")}</span></div><label class="label">${t("Destination", "Destination")}</label><div class="segment">${data.channels.map((c) => btn("# " + e(c.name), "channel", String(c.id) === String(chatDraft.channel) ? "selected" : "", `data-channel="${e(c.id)}"`)).join("") || `<span class="help">${t("Les canaux se chargeront via le compagnon.", "Channels will load through the companion.")}</span>`}</div><label class="label" for="chat-content">${t("Votre message", "Your message")}</label><textarea id="chat-content" maxlength="500" placeholder="${t("Écrivez un message ou choisissez une suggestion à adapter…", "Write a message or choose a suggestion to edit…")}">${e(chatDraft.content || "")}</textarea><p class="help">${t("Au moins 5 mots. Les suggestions restent modifiables avant programmation.", "At least 5 words. Suggestions remain editable before scheduling.")}</p><div class="chat-preview"><span class="eyebrow">${t("Aperçu", "Preview")} · ${e(selectedChannel?.name || "")}</span><div class="row" style="margin-top:14px"><div class="avatar">${t("Moi", "Me")}</div><b class="tiny">${t("Votre compte", "Your account")}</b><span class="tiny muted">${t("À l’instant", "Just now")}</span></div><div class="bubble" id="chat-bubble">${e(chatDraft.content || t("Votre message apparaîtra ici.", "Your message will appear here."))}</div></div>${dueField("chat-due", chatDraft.due, chatDraft.mode)}<div class="detail-actions">${btn(t("Brouillon", "Save draft"), "chat-draft")}${btn(icon("clock") + t("Programmer", "Schedule"), "chat-schedule", "primary")}</div><div class="line"></div><h3>${t("Dernier message envoyé", "Last message sent")}</h3>${last ? `<p class="help">${date(last.posted).toLocaleString(language)} · ${e(last.title)}</p><p class="tiny muted">${e(last.content)}</p>` : `<p class="help">${t("Aucun message envoyé depuis TorrentLinker.", "No messages sent through TorrentLinker yet.")}</p>`}${btn(t("Retrouver dans l’historique", "Find in history") + icon("arrow"), "tab", "small ghost", 'data-tab="history"')}</section><aside class="panel"><div class="eyebrow">${t("Un peu d’inspiration", "Some inspiration")}</div><h2 style="margin-top:10px">${t("À faire vôtre.", "Make it your own.")}</h2><p class="help">${t("Sélectionnez un texte pour le reprendre dans votre message.", "Choose a text to use in your message.")}</p>${messages
      .slice(0, 3)
      .map((m) =>
        btn(e(m.text), "suggestion", "suggestion", `data-message="${e(m.id)}"`),
      )
      .join(
        "",
      )}${field(t("Toute la bibliothèque en français", "Full French library"), `<select id="community-suggestion">${options([["", t("Choisir une suggestion…", "Choose a suggestion…")], ...messages.map((m) => [m.id, m.text])], "")}</select>`)}</aside></div>`;
  }
  async function saveChat(queue) {
    capture();
    const savedContent = chatDraft.content;
    const channel = data.channels.find(
      (c) => String(c.id) === String(chatDraft.channel),
    );
    await saveOperation(
      {
        kind: "chat",
        subject: chatDraft.channel,
        title: channel?.name || chatDraft.channel,
        content: chatDraft.content,
        vote: "",
        due: new Date(chatDraft.due).getTime() / 1000,
      },
      null,
      queue,
    );
    if (chatDraft.content === savedContent) chatDraft = {};
    render();
  }
  function planned() {
    return data.items
      .filter(
        (i) =>
          ["queued", "paused", "sending"].includes(i.state) &&
          (!calendarKind || i.kind === calendarKind),
      )
      .sort((a, b) => at(a) - at(b));
  }
  function weekStart(d) {
    const start = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    return start;
  }
  function queueHTML() {
    const plannedItems = planned(),
      auto = plannedItems.filter((i) => i.source === "automatic").length,
      s = data.settings;
    return `<div class="planning-toolbar"><div><h2>${t("Vos prochaines contributions.", "Your upcoming contributions.")}</h2><p class="help" style="margin:5px 0 0">${plannedItems.length} ${t("opérations programmées", "scheduled operations")} · ${auto} ${t("en mode automatique", "automatic")}</p></div><div class="row"><div class="segment">${[
      ["calendar", t("Calendrier", "Calendar")],
      ["list", t("Liste", "List")],
    ]
      .map(([k, label]) =>
        btn(
          label,
          "queue-display",
          queueDisplay === k ? "selected" : "",
          `data-display="${k}"`,
        ),
      )
      .join(
        "",
      )}</div>${btn(icon(s.enabled ? "pause" : "play") + t(s.enabled ? "Tout suspendre" : "Reprendre", s.enabled ? "Pause all" : "Resume"), "pause")}</div></div><div class="planning-status"><div><b>${!s.enabled ? t("Tous les envois sont en pause", "All sending is paused") : s.automation.enabled ? t("Le mode automatique prépare la suite", "Automatic mode plans what comes next") : t("Vous choisissez le rythme", "You choose the pace")}</b><p class="tiny muted" style="margin-top:4px">${
      !data.paired
        ? t(
            "Compagnon hors ligne. Les opérations restent en attente.",
            "Companion offline. Operations remain queued.",
          )
        : s.automation.enabled
          ? kinds
              .filter((k) => s.automation.kinds[k])
              .map((k) => `${kindName(k)} · ${s.limits[k]}/${t("jour", "day")}`)
              .join(" · ") +
            ` · ${e(s.automation.start)}–${e(s.automation.end)}`
          : t(
              "Activez les actions souhaitées et retrouvez leurs prochains créneaux ici.",
              "Enable the actions you want and find their upcoming slots here.",
            )
    }</p></div>${btn(icon("settings") + t("Configurer le mode auto", "Configure automatic mode"), "automation", "small")}</div>${queueDisplay === "calendar" ? calendarHTML() : queueListHTML()}${queueDisplay === "calendar" ? `<div class="row between wrap" style="margin-top:16px"><span class="muted tiny">${data.items.filter((i) => i.state === "draft").length} ${t("brouillon(s)", "draft(s)")} · ${data.items.filter((i) => i.state === "uncertain").length} ${t("à vérifier", "to check")}</span>${btn(t("Voir dans la liste", "View in list"), "queue-display", "small ghost", 'data-display="list"')}</div>` : ""}`;
  }
  function calendarHTML() {
    const start = weekStart(
      calendarScale === "week"
        ? calendarAnchor
        : new Date(calendarAnchor.getFullYear(), calendarAnchor.getMonth(), 1),
    );
    const count =
      calendarScale === "week"
        ? 7
        : Math.ceil(
            (((new Date(
              calendarAnchor.getFullYear(),
              calendarAnchor.getMonth(),
              1,
            ).getDay() +
              6) %
              7) +
              new Date(
                calendarAnchor.getFullYear(),
                calendarAnchor.getMonth() + 1,
                0,
              ).getDate()) /
              7,
          ) * 7;
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    const title =
      calendarScale === "month"
        ? calendarAnchor.toLocaleDateString(language, {
            month: "long",
            year: "numeric",
          })
        : `${start.toLocaleDateString(language, { day: "numeric", month: "short" })} → ${end.toLocaleDateString(language, { day: "numeric", month: "short", year: "numeric" })}`;
    const items = planned(),
      agenda = items.filter((i) => dateKey(date(at(i))) === calendarSelected);
    return `<section class="panel calendar-panel" id="community-calendar"><div class="calendar-heading"><div class="row">${btn("←", "calendar-prev", "small ghost", `aria-label="${t("Période précédente", "Previous period")}"`)}<h3>${e(title)}</h3>${btn("→", "calendar-next", "small ghost", `aria-label="${t("Période suivante", "Next period")}"`)}${btn(t("Aujourd’hui", "Today"), "calendar-today", "small ghost")}</div><div class="row"><select id="community-calendar-filter" aria-label="${t("Actions du calendrier", "Calendar actions")}">${options([["", t("Toutes les actions", "All actions")], ...kinds.map((k) => [k, kindName(k)])], calendarKind)}</select><div class="segment">${[
      ["week", t("Semaine", "Week")],
      ["month", t("Mois", "Month")],
    ]
      .map(([k, label]) =>
        btn(
          label,
          "scale",
          calendarScale === k ? "selected" : "",
          `data-scale="${k}"`,
        ),
      )
      .join(
        "",
      )}</div></div></div><div class="calendar-scroll"><div class="calendar-grid ${calendarScale === "week" ? "calendar-week" : ""}">${Array.from(
      { length: 7 },
      (_, i) => {
        const d = new Date(2026, 0, 5 + i);
        return `<div class="calendar-weekday">${d.toLocaleDateString(language, { weekday: "short" })}</div>`;
      },
    ).join("")}${Array.from({ length: count }, (_, i) => {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      const key = dateKey(d),
        rows = items.filter((item) => dateKey(date(at(item))) === key),
        max = calendarScale === "week" ? 5 : 3;
      return `<div class="calendar-cell ${d.getMonth() !== calendarAnchor.getMonth() ? "other-month" : ""} ${key === dateKey(new Date()) ? "today" : ""} ${key === calendarSelected ? "selected" : ""}">${btn(`<b>${d.getDate()}</b><span>${rows.length || ""}</span>`, "agenda", "calendar-day", `data-date="${key}" aria-label="${e(fullDate(key))}"`)}${rows
        .slice(0, max)
        .map((item) =>
          btn(
            `<span class="event-time">${time(at(item))}<span class="auto-mark">${item.source === "automatic" ? "Auto" : t("Manuel", "Manual")}</span></span><strong>${e(item.title)}</strong>`,
            "inspect",
            `calendar-event ${item.kind} ${!data.settings.enabled || item.state === "paused" ? "paused" : ""}`,
            `data-id="${e(item.id)}"`,
          ),
        )
        .join(
          "",
        )}${rows.length > max ? btn(`+ ${rows.length - max} ${t("autres", "more")}`, "agenda", "small ghost", `data-date="${key}"`) : ""}</div>`;
    }).join(
      "",
    )}</div></div><div class="calendar-legend">${kinds.map((k) => `<span><i class="legend-dot ${k}"></i>${kindName(k)}</span>`).join("")}<span>${t("Créneaux estimés · heure locale", "Estimated slots · local time")}</span></div></section><section class="panel day-agenda"><div class="row between"><h3>${fullDate(calendarSelected)}</h3><span class="muted tiny">${agenda.length} ${t("opérations", "operations")}</span></div>${agenda.map((i) => `<div class="agenda-item"><time>${time(at(i))}</time><div class="grow"><div class="row wrap"><b>${e(i.title)}</b><span class="pill">${kindName(i.kind)}</span>${i.source === "automatic" ? `<span class="auto-source">${t("Automatique", "Automatic")}</span>` : ""}</div><p>${e(i.content)}</p></div>${btn(t("Examiner", "Inspect"), "inspect", "small", `data-id="${e(i.id)}"`)}</div>`).join("") || `<p class="calendar-empty">${t("Aucune opération programmée ce jour-là.", "No operations scheduled for this day.")}</p>`}</section>`;
  }
  function queueListHTML() {
    return `<div class="queue-grid">${[
      ["ready", t("Prochainement", "Coming up")],
      ["later", t("Plus tard & brouillons", "Later & drafts")],
      ["attention", t("À vérifier", "Needs attention")],
    ]
      .map(([group, label]) => {
        const rows = data.items.filter((i) =>
          group === "attention"
            ? ["uncertain", "refused"].includes(i.state)
            : group === "ready"
              ? ["queued", "paused", "sending"].includes(i.state) &&
                dateKey(date(at(i))) <= dateKey(new Date())
              : i.state === "draft" ||
                (["queued", "paused"].includes(i.state) &&
                  dateKey(date(at(i))) > dateKey(new Date())),
        );
        return `<section class="queue-col"><h3>${label}<span class="count">${rows.length}</span></h3>${rows.map((i) => `<article class="queue-card ${i.state === "sending" ? "sending" : ""}" data-id="${e(i.id)}"><div class="row between"><span class="eyebrow">${kindName(i.kind)}</span>${badge(i.state)}</div><h3>${e(i.title)}</h3><p>${e(i.content)}</p><time data-timer="${e(i.id)}">${date(at(i)).toLocaleString(language)}</time><div class="row wrap">${btn(t("Examiner", "Inspect"), "inspect", "small", `data-id="${e(i.id)}"`)}${i.state === "draft" ? btn(t("Mettre en file", "Queue"), "control", "small ghost", `data-id="${e(i.id)}" data-action="queue"`) : ""}</div></article>`).join("") || `<p class="muted tiny">${t("Aucune action ici pour le moment.", "No actions here yet.")}</p>`}</section>`;
      })
      .join("")}</div>`;
  }
  function historyBase() {
    return data.items.filter(
      (i) =>
        (!historyKind || i.kind === historyKind) &&
        (i.title + " " + i.content + " " + i.note)
          .toLocaleLowerCase()
          .includes(historyQuery.toLocaleLowerCase()),
    );
  }
  function bounds() {
    const today = new Date();
    if (historyPeriod === "all") return ["0000-01-01", "9999-12-31"];
    if (historyPeriod === "custom")
      return [historyFrom || "0000-01-01", historyTo || "9999-12-31"];
    const start = new Date(today);
    start.setDate(start.getDate() - Number(historyPeriod) + 1);
    return [dateKey(start), dateKey(today)];
  }
  async function exportHistory() {
    const [from, to] = bounds();
    const rows = historyBase().filter(
      (i) =>
        dateKey(date(i.updated || i.created)) >= from &&
        dateKey(date(i.updated || i.created)) <= to,
    );
    const text = JSON.stringify(rows, null, 2);
    if (location.protocol === "file:") {
      await request("community/export", { text });
      return;
    }
    const url = URL.createObjectURL(
      new Blob([text], { type: "application/json;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "torrentlinker-community-history.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function historyHTML() {
    const base = historyBase(),
      [from, to] = bounds(),
      stamp = (i) => i.updated || i.created;
    const rows = base
      .filter(
        (i) => dateKey(date(stamp(i))) >= from && dateKey(date(stamp(i))) <= to,
      )
      .sort((a, b) => stamp(b) - stamp(a));
    const year = historyMonth.getFullYear(),
      month = historyMonth.getMonth(),
      days = new Date(year, month + 1, 0).getDate();
    const counts = Array.from(
        { length: days },
        (_, i) =>
          base.filter(
            (item) =>
              dateKey(date(stamp(item))) ===
              dateKey(new Date(year, month, i + 1)),
          ).length,
      ),
      peak = Math.max(1, ...counts);
    let previous = "";
    return `<section class="panel library"><div class="tools"><div class="history-tools"><label class="search">${icon("search")}<input type="search" id="community-history-search" aria-label="${t("Rechercher dans l’historique", "Search history")}" placeholder="${t("Retrouver un torrent, un message…", "Find a torrent, a message…")}" value="${e(historyQuery)}"></label><select id="community-history-kind" aria-label="${t("Type d’action", "Action type")}">${options([["", t("Toutes les actions", "All actions")], ...kinds.map((k) => [k, kindName(k)])], historyKind)}</select></div><div class="history-periods">${[
      ["1", t("Aujourd’hui", "Today")],
      ["7", t("7 jours", "7 days")],
      ["30", t("30 jours", "30 days")],
      ["all", t("Tout l’historique", "All time")],
      ["custom", t("Dates personnalisées", "Custom dates")],
    ]
      .map(([k, label]) =>
        btn(
          label,
          "period",
          historyPeriod === k ? "selected" : "",
          `data-period="${k}"`,
        ),
      )
      .join(
        "",
      )}</div>${historyPeriod === "custom" ? `<div class="date-range">${field(t("Depuis le", "From date"), input("community-history-from", "date", historyFrom))}${field(t("Jusqu’au", "Through date"), input("community-history-to", "date", historyTo))}</div>` : ""}</div><section class="history-timeline" id="community-history-timeline"><div class="row between wrap"><div><h3>${t("Explorer dans le temps", "Explore over time")}</h3><span class="tiny muted">${t("Cliquez sur un jour pour retrouver ses actions.", "Choose a day to find its actions.")}</span></div><div class="month-nav">${btn("←", "history-prev", "small ghost", `aria-label="${t("Mois précédent", "Previous month")}"`)}<strong>${historyMonth.toLocaleDateString(language, { month: "long", year: "numeric" })}</strong>${btn("→", "history-next", "small ghost", `aria-label="${t("Mois suivant", "Next month")}"`)}</div></div><div class="activity-bars" style="--days:${days}">${counts
      .map((n, i) => {
        const key = dateKey(new Date(year, month, i + 1));
        return btn(
          `<span class="bar-area"><span class="bar" style="height:${n ? Math.max(12, (n / peak) * 100) : 3}%"></span></span><span>${i + 1}</span>`,
          "history-day",
          `activity-day ${key < from || key > to ? "outside" : ""}`,
          `data-date="${key}" aria-label="${key}: ${n}" title="${e(fullDate(key))} · ${n}"`,
        );
      })
      .join(
        "",
      )}</div><div class="timeline-note"><span>${counts.reduce((a, b) => a + b, 0)} ${t("actions dans ce mois · filtres appliqués", "actions this month · filters applied")}</span><span>${t("Hauteur = nombre d’actions", "Height = action count")}</span></div></section><div class="history-summary"><b>${rows.length} ${t("opérations", "operations")}</b><span class="tiny muted">${t("Les plus récentes d’abord", "Newest first")}</span>${btn(t("Exporter", "Export"), "export", "small")}</div><div id="community-history-results">${
      rows
        .map((i) => {
          const key = dateKey(date(stamp(i))),
            group =
              previous !== key
                ? `<div class="day-group"><strong>${fullDate(key)}</strong></div>`
                : "";
          previous = key;
          return (
            group +
            btn(
              `<span class="muted">${time(stamp(i))}</span><span><b>${e(i.title)}</b><small>${e(i.content.slice(0, 65))}${i.content.length > 65 ? "…" : ""}</small></span><span>${badge(i.state)}</span><span class="history-extra muted">${kindName(i.kind)}</span><span class="history-extra">${icon("arrow")}</span>`,
              "inspect",
              "history-row",
              `data-id="${e(i.id)}"`,
            )
          );
        })
        .join("") ||
      `<div class="empty">${t("Aucune action sur cette période. Changez de dates ou élargissez votre recherche.", "No actions in this period. Change the dates or broaden your search.")}</div>`
    }</div></section>`;
  }
  function openDrawer(html) {
    const drawer = $("drawer");
    restoreFocus = document.activeElement;
    drawer.innerHTML =
      btn("✕", "close", "close", `aria-label="${t("Fermer", "Close")}"`) +
      `<div id="drawer-body">${html}</div><p id="drawer-error" class="error" role="alert"></p>`;
    if (!drawer.open) drawer.showModal();
    drawer.querySelector("button").focus();
  }
  function closeDrawer() {
    const drawer = $("drawer");
    if (drawer.open) drawer.close();
    delete drawer.dataset.inspector;
    drawer.replaceChildren();
    editing = null;
    if (restoreFocus?.isConnected) restoreFocus.focus({ preventScroll: true });
    restoreFocus = null;
  }
  function inspect(id) {
    const item = data.items.find((i) => i.id === id);
    if (!item) return;
    const voteText =
      item.kind === "vote"
        ? `<p>${item.vote === "approve" ? t("Approuver", "Approve") : t("Désapprouver", "Disapprove")}</p>`
        : "";
    openDrawer(
      `<div class="eyebrow">${t("Détail de l’opération", "Operation details")} · ${item.source === "automatic" ? t("Automatique", "Automatic") : t("Manuelle", "Manual")}</div><h2>${e(item.title)}</h2><div class="row">${badge(item.state)}<span class="tiny muted">${kindName(item.kind)}</span></div><div class="line"></div><h3>${fullDate(dateKey(date(at(item))))} · ${time(at(item))}</h3><p class="help">${t("Créneau estimé. Les limites du site et la disponibilité du navigateur peuvent retarder l’envoi.", "Estimated slot. Site limits and browser availability may delay sending.")}</p>${!data.settings.enabled && ["queued", "paused"].includes(item.state) ? `<div class="panel paused-notice"><span class="pill amber">${icon("pause")} ${t("Envois en pause", "Sending paused")}</span><p class="help">${t("Rien n’est publié tant que les actions programmées sont en pause.", "Nothing is published while scheduled actions are paused.")}</p>${btn(icon("play") + t("Reprendre les envois", "Resume sending"), "pause", "small")}</div>` : ""}<div class="chat-preview" style="white-space:pre-wrap">${e(item.content)}${voteText}</div>${item.note ? `<p class="help">${e(item.note)}</p>` : ""}${
        editable.includes(item.state)
          ? `<div class="row wrap">${btn(t("Modifier / reprogrammer", "Edit / reschedule"), "edit", "primary", `data-id="${e(item.id)}"`)}${[
              ["queue", t("Mettre en file", "Queue")],
              ["pause", t("Suspendre", "Pause")],
              ["first", t("En premier", "Move first")],
              ["cancel", t("Annuler", "Cancel")],
            ]
              .map(([a, label]) =>
                btn(
                  label,
                  "control",
                  "small",
                  `data-id="${e(item.id)}" data-action="${a}"`,
                ),
              )
              .join("")}</div>`
          : ""
      }<div class="line"></div><h3>${t("Déroulement", "Operation timeline")}</h3><div class="timeline">${(item.events || []).map((ev) => `<div class="event"><small>${date(ev.time).toLocaleString(language)}</small><b>${stateName(ev.state)}</b><p>${e(ev.content)}</p>${ev.vote ? `<p>${ev.vote === "approve" ? t("Approuver", "Approve") : t("Désapprouver", "Disapprove")}</p>` : ""}<p>${e(ev.note)}</p></div>`).join("")}</div>${item.state === "posted" ? `<div class="panel"><span class="pill amber">${item.reward === "pending_24h" && Date.now() / 1000 < item.reward_due ? t("XP en attente, 24 h", "XP pending, 24 h") : t("XP non confirmée", "XP unconfirmed")}</span></div>` : ""}`,
    );
  }
  async function editItem(id) {
    let item = data.items.find((i) => i.id === id);
    await change("control", {
      id: item.id,
      revision: item.revision,
      action: "pause",
    });
    item = data.items.find((i) => i.id === id);
    openDrawer(
      `<div class="eyebrow">${t("Modifier une opération", "Edit an operation")}</div><h2>${e(item.title)}</h2>${
        item.kind === "vote"
          ? field(
              t("Votre vote", "Your vote"),
              `<select id="edit-vote">${options(
                [
                  ["approve", t("Approuver", "Approve")],
                  ["disapprove", t("Désapprouver", "Disapprove")],
                ],
                item.vote,
              )}</select>`,
            )
          : ""
      }${field(t("Texte / raison", "Text / reason"), `<textarea id="edit-content" maxlength="500">${e(item.content)}</textarea>`)}${field(t("Envoyer après", "Send after"), input("edit-due", "datetime-local", localInput(item.due)))}<p class="help">${t("L’opération est suspendue pendant l’édition. Enregistrer conserve un brouillon ; Programmer remet l’opération en file.", "The operation is paused while editing. Save keeps a draft; Schedule queues it again.")}</p><div class="detail-actions">${btn(t("Enregistrer", "Save"), "edit-save")}${btn(t("Programmer", "Schedule"), "edit-schedule", "primary")}</div>`,
    );
    editing = { ...item };
  }
  async function saveEdit(queue) {
    const item = editing;
    await saveOperation(
      {
        kind: item.kind,
        subject: item.subject,
        title: item.title,
        content: $("edit-content").value,
        vote: $("edit-vote")?.value || item.vote,
        due: new Date($("edit-due").value).getTime() / 1000,
      },
      item,
      queue,
    );
    closeDrawer();
  }
  function settingsHTML(automatic) {
    const s = data.settings,
      a = s.automation;
    if (!automatic)
      return `<div class="settings-drawer" id="community-settings"><div class="eyebrow">${t("Communauté", "Community")}</div><h2>${t("Réglages & modèles", "Settings & templates")}</h2><p class="help">${t("Un rythme qui vous convient, dans les limites du site.", "Your own pace, within the site limits.")}</p>${toggle("community-enabled", t("Exécuter les actions programmées", "Run scheduled actions"), s.enabled)}<h3>${t("Rythme des publications", "Publication pace")}</h3><div class="settings-row tiny muted"><span>Action</span><span>${t("Par jour", "Per day")}</span><span>${t("Intervalle (s)", "Interval (s)")}</span></div>${kinds.map((k) => `<div class="settings-row"><label for="community-${k}-limit">${kindName(k)}</label>${input(`community-${k}-limit`, "number", s.limits[k], `min="0" max="5" step="1" aria-label="${kindName(k)} ${t("par jour", "per day")}"`)}${input(`community-${k}-interval`, "number", s.intervals[k], `min="30" max="86400" step="1" aria-label="${t("Intervalle", "Interval")} ${kindName(k)}"`)}</div>`).join("")}<p class="help">${t("Général et classe partagent la limite Chat. 0 désactive l’action. Les quotas sont remis à zéro à minuit, heure de Paris.", "General and class share the Chat limit. 0 disables the action. Daily quotas reset at midnight, Europe/Paris time.")}</p>${["comment", "chat"].map((k) => `<h3>${t("Votre modèle", "Your template")} · ${kindName(k)}</h3><textarea id="template-${k}" maxlength="500">${e(s.templates[k])}</textarea>`).join("")}<h3>${t("Synchronisation", "Synchronization")}</h3><p class="help">${t("La liste enregistrée apparaît immédiatement, puis se complète automatiquement via le compagnon.", "Your saved library appears immediately, then refreshes automatically through the companion.")}</p>${btn(t("Enregistrer les réglages", "Save settings"), "settings-save", "primary full")}</div>`;
    return `<div class="auto-drawer"><div class="eyebrow">${t("Votre rythme de participation", "Your participation pace")}</div><h2>${t("Mode automatique", "Automatic mode")}</h2>${toggle("community-auto-enabled", `<b>${t("Planifier automatiquement", "Plan automatically")}</b><small class="muted" style="display:block">${t("Préparer les prochains créneaux", "Prepare the next slots")}</small>`, a.enabled)}<div class="line"></div><h3>${t("Quelles actions ?", "Which actions?")}</h3>${kinds
      .map(
        (k) =>
          `<section class="auto-kind">${toggle(`community-auto-${k}`, `<b>${k === "vote" ? t("Votes préparés", "Prepared votes") : kindName(k)}</b>`, a.kinds[k])}<p class="tiny muted" style="margin-top:7px">${k === "comment" ? t("Votre modèle sur les torrents éligibles sans commentaire connu.", "Your template for eligible torrents with no known comment.") : k === "vote" ? t("Publier uniquement les avis que vous avez déjà choisis.", "Publish only the votes you have already chosen.") : t("Utiliser votre sélection de messages, sans répétition.", "Use your selected messages without repetition.")}</p><div class="kind-options"><label class="tiny" for="auto-limit-${k}">${t("Maximum par jour", "Maximum per day")}</label>${input(`auto-limit-${k}`, "number", s.limits[k], 'min="0" max="5" step="1"')}</div>${
            k === "chat"
              ? `<div class="row wrap" style="margin-top:12px">${[
                  ["general", t("Général", "General")],
                  ["class", t("Classe", "Class")],
                ]
                  .map(
                    ([key, label]) =>
                      `<label class="check"><input type="checkbox" id="community-auto-channel-${key}" ${a.channels.includes(key) ? "checked" : ""}>${label}</label>`,
                  )
                  .join(
                    "",
                  )}</div>${field(t("Messages sélectionnés, un par ligne", "Selected messages, one per line"), `<textarea id="community-auto-messages">${e(a.messages.join("\n"))}</textarea>`)}${field(t("Ajouter une suggestion", "Add a suggestion"), `<select id="auto-suggestion">${options([["", t("Choisir…", "Choose…")], ...messages.map((m) => [m.id, m.text])], "")}</select>`)}<p class="help">${t("Une limite commune aux deux canaux.", "One shared limit for both channels.")}</p>`
              : ""
          }</section>`,
      )
      .join(
        "",
      )}<h3 style="margin:20px 0 10px">${t("Plage de publication", "Publication window")}</h3><div class="auto-hours">${field(t("À partir de", "From"), input("community-auto-start", "time", a.start))}${field(t("Jusqu’à", "Until"), input("community-auto-end", "time", a.end))}</div>${field(t("Fuseau horaire", "Timezone"), input("community-auto-timezone", "text", a.timezone))}<h3 style="margin:20px 0 10px">${t("Modèle des commentaires", "Comment template")}</h3><textarea id="auto-template" maxlength="500">${e(s.templates.comment)}</textarea><p class="help">${t("{titre} sera remplacé par le titre du torrent.", "{title} will be replaced by the torrent title.")}</p><div class="automation-summary">${t("Planification des 7 prochains jours, selon les créneaux et limites disponibles.", "Plans the next 7 days, subject to available slots and limits.")}</div><p class="help">${t("Désactiver une action retire ses créneaux automatiques non envoyés. Les opérations manuelles restent en place. La file doit être active pour publier.", "Disabling an action removes its unsent automatic slots. Manual operations stay in place. The queue must be active to publish.")}</p>${btn(t("Appliquer au calendrier", "Apply to calendar"), "automation-save", "primary full")}</div>`;
  }
  async function saveSettings(automatic) {
    const s = structuredClone(data.settings);
    if (automatic) {
      const a = s.automation;
      a.enabled = $("community-auto-enabled").checked;
      for (const k of kinds) {
        a.kinds[k] = $("community-auto-" + k).checked;
        s.limits[k] = Number($("auto-limit-" + k).value);
      }
      a.channels = ["general", "class"].filter(
        (k) => $("community-auto-channel-" + k).checked,
      );
      a.messages = $("community-auto-messages")
        .value.split("\n")
        .map((v) => v.trim())
        .filter(Boolean);
      a.start = $("community-auto-start").value;
      a.end = $("community-auto-end").value;
      a.timezone = $("community-auto-timezone").value.trim();
      s.templates.comment = $("auto-template").value;
    } else {
      s.enabled = $("community-enabled").checked;
      for (const k of kinds) {
        s.limits[k] = Number($("community-" + k + "-limit").value);
        s.intervals[k] = Number($("community-" + k + "-interval").value);
      }
      for (const k of ["comment", "chat"])
        s.templates[k] = $("template-" + k).value;
    }
    await change("settings", s);
    closeDrawer();
    if (automatic) {
      tab = "queue";
      queueDisplay = "calendar";
    }
    render();
    notify(t("Réglages enregistrés.", "Settings saved."));
  }
  function bindInputs() {
    const on = (id, event, callback) => {
      if ($(id)) $(id)["on" + event] = callback;
    };
    on("community-library-search", "input", (ev) => {
      query = ev.target.value;
      limit = 60;
      render();
    });
    on("library-sort", "change", (ev) => {
      sort = ev.target.value;
      render();
    });
    on("community-content", "input", () => {
      capture();
      $("characters").textContent =
        $("community-content").value.length + "/500";
    });
    on("community-vote", "change", capture);
    on("community-due", "change", capture);
    on("chat-content", "input", () => {
      capture();
      $("chat-bubble").textContent =
        chatDraft.content ||
        t("Votre message apparaîtra ici.", "Your message will appear here.");
    });
    on("community-channel", "change", capture);
    on("chat-due", "change", capture);
    on("community-suggestion", "change", (ev) => suggest(ev.target.value));
    on("community-calendar-filter", "change", (ev) => {
      calendarKind = ev.target.value;
      render();
    });
    on("community-history-search", "input", (ev) => {
      historyQuery = ev.target.value;
      render();
    });
    on("community-history-kind", "change", (ev) => {
      historyKind = ev.target.value;
      render();
    });
    on("community-history-from", "change", (ev) => {
      historyFrom = ev.target.value;
      render();
    });
    on("community-history-to", "change", (ev) => {
      historyTo = ev.target.value;
      render();
    });
    libraryObserver?.disconnect();
    if ($("library-more") && !$("library-more").hidden) {
      const observer = (libraryObserver = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            observer.disconnect();
            limit += 60;
            render();
          }
        },
        { rootMargin: "200px" },
      ));
      observer.observe($("library-more"));
    }
  }
  function suggest(id) {
    const message = messages.find((m) => m.id === id);
    if (message && $("chat-content")) {
      $("chat-content").value = message.text;
      capture();
      $("chat-bubble").textContent = message.text;
    }
  }
  document.addEventListener("change", (event) => {
    if (event.target.dataset.dueTarget) {
      const target = $(event.target.dataset.dueTarget),
        mode = event.target.value,
        next = new Date();
      target.hidden = mode !== "custom";
      if (mode === "tomorrow") {
        next.setDate(next.getDate() + 1);
        next.setHours(9, 0, 0, 0);
      }
      if (mode === "hour") next.setHours(next.getHours() + 1);
      if (mode !== "custom") target.value = localInput(next.getTime() / 1000);
      capture();
    }
    if (event.target.id === "auto-suggestion") {
      const m = messages.find((m) => m.id === event.target.value);
      if (m)
        $("community-auto-messages").value +=
          ($("community-auto-messages").value ? "\n" : "") +
          m.text.replace(/\s+/g, " ");
    }
  });
  document.addEventListener(
    "wheel",
    (event) => {
      if (event.target.type === "number") event.preventDefault();
    },
    { passive: false },
  );
  $("drawer").addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDrawer();
  });
  $("drawer").addEventListener("click", (event) => {
    if (
      event.target === $("drawer") &&
      event.clientX < $("drawer").getBoundingClientRect().left
    )
      closeDrawer();
  });
  document.addEventListener("click", async (event) => {
    const b = event.target.closest("[data-command]");
    if (!b || b.disabled) return;
    const cmd = b.dataset.command;
    capture();
    b.disabled = true;
    const quick = ["tab", "select", "filter", "action", "template", "suggestion", "channel", "queue-display", "scale", "agenda", "calendar-today", "calendar-prev", "calendar-next", "period", "history-day", "history-prev", "history-next", "inspect", "settings", "automation", "close"];
    const release = quick.includes(cmd) ? () => {} : TLToast.working(b);
    try {
      if (cmd === "tab") {
        tab = b.dataset.tab;
        render();
        window.scrollTo(0, 0);
      } else if (cmd === "refresh") await change("refresh", { page: 1 });
      else if (cmd === "select") {
        selected = b.dataset.hash;
        render();
        if (innerWidth < 950) {
          openDrawer(detailHTML());
          $("drawer").dataset.inspector = "true";
          bindInputs();
        }
      } else if (cmd === "filter") {
        filter = b.dataset.filter;
        limit = 60;
        render();
      } else if (cmd === "action") {
        action = b.dataset.kind;
        render();
        if ($("drawer").dataset.inspector) {
          $("drawer-body").innerHTML = detailHTML();
          bindInputs();
        }
      } else if (cmd === "template") {
        $("community-content").value = data.settings.templates.comment
          .replaceAll(
            "{titre}",
            data.candidates.find((c) => c.hash === selected).title,
          )
          .replaceAll(
            "{title}",
            data.candidates.find((c) => c.hash === selected).title,
          );
        capture();
      } else if (cmd === "save-draft" || cmd === "schedule")
        await saveLibrary(cmd === "schedule");
      else if (cmd === "chat-draft" || cmd === "chat-schedule")
        await saveChat(cmd === "chat-schedule");
      else if (cmd === "suggestion") suggest(b.dataset.message);
      else if (cmd === "channel") {
        chatDraft.channel = b.dataset.channel;
        render();
      } else if (cmd === "export") await exportHistory();
      else if (cmd === "queue-display") {
        queueDisplay = b.dataset.display;
        render();
      } else if (cmd === "scale") {
        calendarScale = b.dataset.scale;
        render();
      } else if (cmd === "agenda") {
        calendarSelected = b.dataset.date;
        render();
      } else if (cmd === "calendar-today") {
        calendarAnchor = new Date();
        calendarSelected = dateKey(calendarAnchor);
        render();
      } else if (cmd === "calendar-prev" || cmd === "calendar-next") {
        const step = cmd.endsWith("next") ? 1 : -1;
        calendarAnchor =
          calendarScale === "month"
            ? new Date(
                calendarAnchor.getFullYear(),
                calendarAnchor.getMonth() + step,
                1,
              )
            : new Date(
                calendarAnchor.getFullYear(),
                calendarAnchor.getMonth(),
                calendarAnchor.getDate() + step * 7,
              );
        render();
      } else if (cmd === "pause") {
        await change("settings", {
          ...data.settings,
          enabled: !data.settings.enabled,
        });
        if (b.closest(".paused-notice")) closeDrawer();
      } else if (cmd === "period") {
        historyPeriod = b.dataset.period;
        render();
      } else if (cmd === "history-day") {
        historyPeriod = "custom";
        historyFrom = historyTo = b.dataset.date;
        render();
      } else if (cmd === "history-prev" || cmd === "history-next") {
        historyMonth = new Date(
          historyMonth.getFullYear(),
          historyMonth.getMonth() + (cmd.endsWith("next") ? 1 : -1),
          1,
        );
        render();
      } else if (cmd === "inspect") inspect(b.dataset.id);
      else if (cmd === "edit") await editItem(b.dataset.id);
      else if (cmd === "edit-save" || cmd === "edit-schedule")
        await saveEdit(cmd === "edit-schedule");
      else if (cmd === "control") {
        const item = data.items.find((i) => i.id === b.dataset.id);
        await change("control", {
          id: item.id,
          revision: item.revision,
          action: b.dataset.action,
        });
        closeDrawer();
      } else if (cmd === "settings" || cmd === "automation")
        openDrawer(settingsHTML(cmd === "automation"));
      else if (cmd === "settings-save" || cmd === "automation-save")
        await saveSettings(cmd === "automation-save");
      else if (cmd === "close") closeDrawer();
    } catch (error) {
      if ($("drawer").open) $("drawer-error").textContent = TLToast.translate(error.message);
      else notify(error.message, "bad");
    } finally {
      release();
      b.disabled = false;
    }
  });
  async function refresh() {
    if (busy || !active) return;
    busy = true;
    const current = generation;
    try {
      const next = await request("community");
      if (current !== generation) return;
      accept(next);
      if (!messages.length) {
        messages = (await request("community/messages")).entries;
        render();
      }
    } catch (error) {
      if (error.message === "Refresh the c411 profile first.") {
        clear();
        $("community-app").innerHTML =
          `<p class="loading" role="status">${t("Actualisez d’abord votre profil c411.", "Refresh your c411 profile first.")}</p>`;
      } else if (!data) {
        $("community-app").innerHTML =
          `<p class="loading" role="alert">${e(TLToast.translate(error.message))}</p>`;
      } else notify(error.message, "bad");
    } finally {
      busy = false;
    }
  }
  window.addEventListener("community-environment", (event) => {
    const env = event.detail;
    active = env.active !== false;
    language = env.language || language;
    window.TLPanel.setLanguage(language);
    document.documentElement.dataset.theme = env.theme || "dark";
    capture();
    if (env.clear) {
      clear();
      return;
    }
    if (data) render();
    if (active) refresh();
  });
  setInterval(refresh, 3000);
  setInterval(() => {
    if (!active || !data) return;
    for (const node of document.querySelectorAll("[data-timer]")) {
      const item = data.items.find((i) => i.id === node.dataset.timer);
      if (!item) continue;
      const seconds = Math.max(0, Math.ceil(at(item) - Date.now() / 1000));
      node.textContent =
        item.state === "queued"
          ? item.wait_reason ||
            `${t("Dans", "In")} ${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m ${seconds % 60}s`
          : stateName(item.state);
    }
  }, 1000);
  window.communityTransport.then(() => window.communityReady());
})();
