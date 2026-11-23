"use strict";
// Paramètres → Utilisateurs (layout A of docs/specs/members-settings): one card per Member,
// the editor under the one being changed. The server checks every change again.
const memberApi = (path, body) =>
  request("members", {
    path,
    body,
    method: body === undefined ? "GET" : "POST",
  });
const memberGroups = () => [
  [
    say("Media", "Médias"),
    [
      ["music", say("Music", "Musique")],
      ["media-center", say("Media Center mode", "Mode Media Center")],
      ["adult", say("Adult content (XXX)", "Contenu adulte (XXX)")],
    ],
  ],
  [
    say("Requests", "Demandes"),
    [
      [
        "request",
        say(
          "Request films (you accept before any download)",
          "Demander des films (vous acceptez avant tout téléchargement)",
        ),
      ],
      [
        "wish",
        say(
          "Make wishes for a title not found",
          "Faire des vœux pour un titre introuvable",
        ),
      ],
    ],
  ],
  [
    say("Tools", "Outils"),
    [
      [
        "search",
        say("c411 Search, read-only", "Recherche c411, en consultation"),
      ],
      [
        "assistant",
        say("Assistant (on your keys)", "Assistant (sur vos clés)"),
      ],
      [
        "queue",
        say("See the download queue", "Voir la file de téléchargement"),
      ],
      ["torrents", say("See the torrents", "Voir les torrents")],
    ],
  ],
  [
    say("Team", "Équipe"),
    [
      [
        "approve",
        say("Accept or refuse requests", "Accepter ou refuser les demandes"),
      ],
      [
        "manage-members",
        say(
          "Manage members (never you nor your settings)",
          "Gérer les membres (jamais vous ni vos réglages)",
        ),
      ],
      [
        "edit-ratings",
        say("Edit ratings and film details", "Modifier classements et fiches"),
      ],
    ],
  ],
];
const memberVideo = () => [
  ["films", say("Films", "Films")],
  ["series", say("Series", "Séries")],
  ["anime", say("Anime", "Animés")],
];
const memberOwnerOnly = () => [
  say("Settings and credentials", "Paramètres et identifiants"),
  say("Zen and the c411 profile", "Zen et profil c411"),
  "Upload",
  say("Agent access", "Accès agents"),
  say("The Assistant's providers", "Fournisseurs de l'Assistant"),
];
const memberAges = () => [
  ["", say("No limit", "Aucune limite")],
  ["18", say("Under 18", "-18 ans")],
  ["16", say("Under 16", "-16 ans")],
  ["12", say("Under 12", "-12 ans")],
  ["10", say("Under 10", "-10 ans")],
  ["TP", say("All audiences", "Tous publics")],
];
const WATCHING = ["films", "series", "anime", "music", "media-center"];
// Presets only pre-tick Permissions; nothing remembers which one was used.
const memberPresets = () => ({
  viewer: [say("Viewer", "Spectateur"), WATCHING, {}],
  family: [
    say("Family", "Famille"),
    [...WATCHING, "request", "wish", "search"],
    { requests_per_week: 5, bytes_per_week: 100e9, pending: 3 },
  ],
  child: [
    say("Child", "Enfant"),
    ["films", "anime", "media-center"],
    {},
    { age_limit: "10" },
  ],
  admin: [
    say("Administrator", "Administrateur"),
    [
      ...WATCHING,
      ...["request", "wish", "search", "queue", "torrents"],
      ...["approve", "manage-members", "edit-ratings"],
    ],
    {},
  ],
});
const memberCaps = () => [
  ["requests_per_week", say("requests per week", "demandes par semaine"), 1, 5],
  ["bytes_per_week", say("GB per week", "Go par semaine"), 1e9, 100],
  [
    "pending",
    say("requests pending at once", "demandes en attente à la fois"),
    1,
    3,
  ],
];
let memberState = { data: null, editing: "", draft: null };

function memberPreset(permissions) {
  const held = [...permissions].sort().join();
  const found = Object.values(memberPresets()).find(
    ([, granted]) => [...granted].sort().join() === held,
  );
  return found ? found[0] : say("Custom", "Sur mesure");
}
function memberCheck(parent, label, checked, disabled, change) {
  const node = element("label", undefined, "settings-check"),
    input = element("input");
  input.type = "checkbox";
  input.checked = checked;
  input.disabled = disabled;
  input.onchange = () => change(input.checked);
  node.append(input, document.createTextNode(` ${label}`));
  parent.append(node);
  return input;
}
function memberField(parent, label, value, change, type = "text") {
  const node = element("label", label, "settings-field"),
    input = element("input");
  input.type = type;
  input.value = value;
  input.oninput = () => change(input.value);
  node.append(input);
  parent.append(node);
  return input;
}
async function settingsMembers(root) {
  memberState.data = await memberApi("members");
  if (!root.isConnected) return;
  drawMembers(root);
}
function drawMembers(root) {
  const data = memberState.data;
  root.replaceChildren();
  const intro = element("section", undefined, "settings-card");
  intro.append(
    element("h3", say("Share TorrentLinker", "Partager TorrentLinker")),
    element(
      "p",
      say(
        "Each member sees and does only what you tick. They ask; you, or a member allowed to, accept.",
        "Chaque membre ne voit et ne fait que ce que vous cochez. Il demande ; vous, ou un membre qui en a le droit, acceptez.",
      ),
      "muted",
    ),
  );
  const actions = element("div", undefined, "settings-actions");
  if (!data.proxy)
    actions.append(
      button(
        say("Invite someone", "Inviter quelqu’un"),
        () => linkDialog(root),
        "primary",
      ),
    );
  actions.append(
    button(
      data.proxy
        ? say("Add a member", "Ajouter un membre")
        : say(
            "Create an account with a password",
            "Créer un compte avec mot de passe",
          ),
      () => createMember(root),
      data.proxy ? "primary" : "",
    ),
  );
  intro.append(actions);
  root.append(intro, ownerCard(root));
  for (const member of data.members) root.append(memberCard(root, member));
}
function ownerCard(root) {
  const data = memberState.data;
  const card = element("section", undefined, "client-card member-locked");
  const head = element("div", undefined, "member-head");
  const who = element("div");
  who.append(
    element(
      "h3",
      data.owner_proxy_user === undefined
        ? say("Owner", "Propriétaire")
        : say("You", "Vous"),
    ),
    element(
      "p",
      say(
        "Owner · every right, cannot be restricted",
        "Propriétaire · tous les droits, sans restriction possible",
      ),
      "muted",
    ),
  );
  head.append(
    who,
    element("span", say("Owner", "Propriétaire"), "member-tag on"),
  );
  card.append(
    head,
    element(
      "p",
      `${say("Always the owner's alone:", "Toujours réservés au propriétaire :")} ${memberOwnerOnly().join(", ")}.`,
      "muted",
    ),
  );
  if (data.proxy && data.owner_proxy_user !== undefined) {
    const value = { proxy_user: data.owner_proxy_user };
    const fields = element("div", undefined, "settings-fields");
    memberField(
      fields,
      say("Your name sent by the proxy", "Votre nom transmis par le proxy"),
      value.proxy_user,
      (text) => (value.proxy_user = text),
    );
    card.append(
      fields,
      element(
        "small",
        say(
          "If your proxy sends a name for you too, enter it before giving members one: an unknown name is refused.",
          "Si votre proxy transmet aussi votre nom, saisissez-le avant d’en donner un aux membres : un nom inconnu est refusé.",
        ),
        "muted",
      ),
      button(say("Save", "Enregistrer"), async () => {
        const saved = await memberApi("members/owner/proxy-user", value);
        memberState.data.owner_proxy_user = saved.proxy_user;
        toast(say("Saved", "Enregistré"));
      }),
    );
  }
  return card;
}
function memberCard(root, member) {
  const editing = memberState.editing === member.id;
  const card = element("section", undefined, "client-card");
  const head = element("div", undefined, "member-head");
  const who = element("div");
  who.append(
    element("h3", member.name),
    element(
      "p",
      `${memberStatus(member)} · ${memberPreset(member.permissions)}`,
      "muted",
    ),
  );
  const actions = element("div", undefined, "settings-actions");
  const mine = member.id === memberState.data.you;
  const open = member.link && !member.link.expired;
  if (member.invited) {
    actions.append(
      button(
        open
          ? say("Show the link", "Voir le lien")
          : say("New link", "Nouveau lien"),
        () => (open ? showLink(member) : linkDialog(root, member)),
      ),
      button(
        say("Cancel the invitation", "Annuler l’invitation"),
        async () => {
          if (
            !confirm(
              say(
                `Cancel ${member.name}'s invitation? The link will stop working.`,
                `Annuler l’invitation de ${member.name} ? Le lien ne fonctionnera plus.`,
              ),
            )
          )
            return;
          await memberApi(`members/${member.id}/cancel-link`, {});
          if (memberState.editing === member.id) memberState.editing = "";
          toast(say("Invitation cancelled", "Invitation annulée"));
          await settingsMembers(root);
        },
      ),
    );
  }
  if (!mine && !member.invited)
    actions.append(
      button(
        member.disabled
          ? say("Enable", "Réactiver")
          : say("Disable", "Désactiver"),
        async () => {
          if (
            !member.disabled &&
            !confirm(
              say(
                `Disable ${member.name}? Their sessions end at once; everything is kept.`,
                `Désactiver ${member.name} ? Ses sessions se terminent aussitôt ; tout est conservé.`,
              ),
            )
          )
            return;
          await memberApi(
            `members/${member.id}/${member.disabled ? "enable" : "disable"}`,
            {},
          );
          await settingsMembers(root);
        },
      ),
    );
  if (member.disabled && !mine)
    actions.append(
      button(
        say("Delete", "Supprimer"),
        async () => {
          if (
            !confirm(
              say(
                `Delete ${member.name}? Their account, progress and playlists are erased. This cannot be undone.`,
                `Supprimer ${member.name} ? Son compte, sa reprise de lecture et ses listes sont effacés. C’est définitif.`,
              ),
            )
          )
            return;
          await memberApi(`members/${member.id}/delete`, {});
          if (memberState.editing === member.id) memberState.editing = "";
          await settingsMembers(root);
        },
        "member-danger",
      ),
    );
  const edit = button(
    editing
      ? say("Editing", "En cours de modification")
      : say("Edit", "Modifier"),
    () => {
      memberState.editing = editing ? "" : member.id;
      memberState.draft = editing ? null : structuredClone(member);
      drawMembers(root);
    },
    editing ? "primary" : "",
  );
  edit.setAttribute("aria-pressed", String(editing));
  actions.append(edit);
  head.append(who, actions);
  const tags = element("div", undefined, "member-tags");
  const names = Object.fromEntries([
    ...memberVideo(),
    ...memberGroups().flatMap((g) => g[1]),
    // The card's summary keeps the short names.
    ["request", say("Requests", "Demandes")],
    ["wish", say("Wishes", "Vœux")],
    ["search", say("Search", "Recherche")],
    ["assistant", "Assistant"],
    ["manage-members", say("Manages members", "Gère les membres")],
  ]);
  for (const permission of member.permissions)
    tags.append(
      element("span", names[permission] || permission, "member-tag on"),
    );
  if (member.age_limit)
    tags.append(
      element(
        "span",
        `${say("Limit", "Limite")} ${memberAges().find(([r]) => r === member.age_limit)[1]}`,
        "member-tag",
      ),
    );
  if (member.folders)
    tags.append(
      element(
        "span",
        `${say("Folders", "Dossiers")} ${member.folders.length} / ${memberState.data.library_folders.length}`,
        "member-tag",
      ),
    );
  card.append(head, tags);
  if (editing) card.append(memberEditor(root, memberState.draft));
  return card;
}
function memberEditor(root, draft) {
  const data = memberState.data;
  const grantable = new Set(data.grantable);
  const mine = draft.id === data.you;
  const held = new Set(draft.permissions);
  const form = element("div", undefined, "settings-form member-editor");
  const redraw = () => drawMembers(root);
  const set = (permission, on) => {
    on ? held.add(permission) : held.delete(permission);
    draft.permissions = [...held].sort();
  };
  const fixed = (permission) => mine || !grantable.has(permission);

  const account = element("fieldset");
  account.append(element("legend", say("Account", "Compte")));
  const fields = element("div", undefined, "settings-fields");
  memberField(
    fields,
    say("Display name", "Nom affiché"),
    draft.name,
    (v) => (draft.name = v),
  );
  const login = memberField(
    fields,
    say("Sign-in name", "Identifiant de connexion"),
    draft.login,
    (v) => (draft.login = v),
  );
  if (draft.invited)
    login.placeholder = say(
      "chosen with the invitation",
      "choisi à l’invitation",
    );
  memberField(
    fields,
    say(
      "Name sent by the proxy (optional)",
      "Nom transmis par le proxy (facultatif)",
    ),
    draft.proxy_user,
    (v) => (draft.proxy_user = v),
  ).placeholder = say(
    "Remote-User, e.g. lea@family",
    "Remote-User, ex. lea@famille",
  );
  if (!data.proxy && !draft.invited)
    memberField(
      fields,
      say("New password (optional)", "Nouveau mot de passe (facultatif)"),
      "",
      (v) => (draft.password = v),
      "password",
    ).autocomplete = "new-password";
  const preset = element(
    "label",
    say("Start from a preset", "Partir d’un préréglage"),
    "settings-field",
  );
  const choice = element("select");
  choice.append(element("option", "—"));
  for (const [key, [label]] of Object.entries(memberPresets())) {
    const option = element("option", label);
    option.value = key;
    choice.append(option);
  }
  choice.disabled = mine;
  choice.onchange = () => {
    const [, granted, caps, limits = { age_limit: null }] =
      memberPresets()[choice.value];
    if (!mine) draft.age_limit = limits.age_limit;
    // A manager's preset keeps what they cannot grant as it was.
    draft.permissions = [
      ...granted.filter((p) => !fixed(p)),
      ...[...held].filter((p) => fixed(p)),
    ].sort();
    draft.caps = {
      ...draft.caps,
      requests_per_week: null,
      bytes_per_week: null,
      pending: null,
      ...caps,
    };
    redraw();
  };
  preset.append(choice);
  fields.append(preset);
  account.append(fields);
  if (!draft.invited && draft.id) {
    const links = element("div", undefined, "settings-actions");
    if (!data.proxy)
      links.append(
        button(say("Send a password link", "Envoyer un lien de mot de passe"), () =>
          linkDialog(root, draft),
        ),
      );
    // The people who watch under this account, and its Shared Screens (account.js).
    links.append(
      button(say("Profiles and Shared Screens", "Profils et écrans partagés"), () =>
        memberHousehold(draft),
      ),
    );
    account.append(links);
  }
  form.append(account);

  const [media, ...others] = memberGroups();
  const watch = element("fieldset");
  watch.append(element("legend", media[0]));
  const kinds = memberVideo();
  const video = memberCheck(
    watch,
    say("Video", "Vidéo"),
    kinds.some(([k]) => held.has(k)),
    kinds.every(([k]) => fixed(k)),
    (on) => {
      for (const [k] of kinds) if (!fixed(k)) set(k, on);
      redraw();
    },
  );
  const kindRow = element("div", undefined, "member-kinds");
  for (const [k, label] of kinds)
    memberCheck(
      kindRow,
      label,
      held.has(k),
      fixed(k) || !video.checked,
      (on) => {
        set(k, on);
        redraw();
      },
    );
  watch.append(kindRow);
  // Adult content goes with no age limit or −18 only; the server drops it under any other.
  const adultAllowed = [null, "18"].includes(draft.age_limit ?? null);
  for (const [k, label] of media[1])
    memberCheck(
      watch,
      label,
      held.has(k) && (k !== "adult" || adultAllowed),
      fixed(k) || (k === "adult" && !adultAllowed),
      (on) => set(k, on),
    );
  const limits = element("div", undefined, "settings-fields");
  const age = element("label", say("Age limit", "Limite d’âge"), "settings-field");
  const ages = element("select");
  for (const [rating, label] of memberAges()) {
    const option = element("option", label);
    option.value = rating;
    ages.append(option);
  }
  ages.value = draft.age_limit ?? "";
  ages.disabled = mine;
  ages.onchange = () => {
    draft.age_limit = ages.value || null;
    if (![null, "18"].includes(draft.age_limit)) set("adult", false);
    redraw();
  };
  age.append(
    ages,
    element(
      "small",
      say(
        "An unrated title is hidden under a limit; rate it from its details.",
        "Un titre sans classement est caché sous une limite ; ajoutez-lui un classement dans sa fiche.",
      ),
    ),
  );
  const folders = element("div", say("Visible folders", "Dossiers visibles"), "settings-field");
  const all = data.library_folders.map((f) => f.path);
  const shown = new Set(draft.folders ?? all);
  for (const folder of data.library_folders)
    memberCheck(folders, folder.name, shown.has(folder.path), mine, (on) => {
      on ? shown.add(folder.path) : shown.delete(folder.path);
      // Every folder ticked keeps the folders added later visible too.
      draft.folders = all.every((path) => shown.has(path)) ? null : [...shown].sort();
    });
  if (!data.library_folders.length)
    folders.append(element("small", say("No Library Folder yet.", "Aucun dossier de bibliothèque.")));
  limits.append(age, folders);
  watch.append(limits);
  form.append(watch);

  for (const [legend, items] of others) {
    const group = element("fieldset");
    group.append(element("legend", legend));
    for (const [k, label] of items)
      memberCheck(group, label, held.has(k), fixed(k), (on) => {
        set(k, on);
        if (k === "request") redraw();
      });
    if (items.some(([k]) => k === "request")) {
      group.append(
        element(
          "p",
          say("Caps, each optional", "Quotas, chacun facultatif"),
          "muted",
        ),
      );
      for (const [key, unit, factor, start] of memberCaps()) {
        const row = element("label", undefined, "settings-check member-cap"),
          on = element("input"),
          amount = element("input");
        on.type = "checkbox";
        amount.type = "number";
        amount.min = "1";
        const value = draft.caps[key];
        on.checked = value != null;
        on.disabled = mine || !held.has("request");
        amount.disabled = on.disabled || !on.checked;
        amount.value = value != null ? String(Math.round(value / factor)) : "";
        on.onchange = () => {
          draft.caps[key] = on.checked ? start * factor : null;
          redraw();
        };
        amount.oninput = () => {
          draft.caps[key] = amount.value ? Number(amount.value) * factor : null;
        };
        row.append(
          on,
          document.createTextNode(` ${say("At most", "Au plus")} `),
          amount,
          document.createTextNode(` ${unit}`),
        );
        group.append(row);
      }
    }
    form.append(group);
  }
  const assistantLimit = element("label", say("Assistant messages per day", "Messages Assistant par jour"), "settings-field");
  const daily = element("input"); daily.type = "number"; daily.min = "0"; daily.max = "10000";
  daily.value = String(draft.caps.assistant_per_day ?? 20); daily.disabled = mine;
  daily.oninput = () => { draft.caps.assistant_per_day = Number(daily.value); };
  assistantLimit.append(daily); form.append(assistantLimit);
  const locked = element("fieldset", undefined, "member-locked");
  locked.append(
    element("legend", say("The owner's alone", "Réservé au propriétaire")),
  );
  for (const label of memberOwnerOnly())
    memberCheck(locked, label, false, true, () => {});
  form.append(locked);

  const actions = element("div", undefined, "settings-actions");
  actions.append(
    button(
      say("Save", "Enregistrer"),
      async () => {
        const saved = await memberApi(`members/${draft.id}`, draft);
        memberState.data.members = memberState.data.members.map((m) =>
          m.id === saved.id ? saved : m,
        );
        memberState.draft = structuredClone(saved);
        toast(say("Member saved", "Membre enregistré"));
        redraw();
      },
      "primary",
    ),
    button(say("Discard changes", "Annuler les modifications"), () => {
      memberState.draft = structuredClone(
        data.members.find((m) => m.id === draft.id),
      );
      redraw();
    }),
  );
  form.append(actions);
  return form;
}
function createMember(root) {
  const data = memberState.data;
  const dialog = element("dialog", undefined, "assistant-dialog");
  const form = element("form");
  form.method = "dialog";
  const value = {
    name: "",
    login: "",
    password: "",
    proxy_user: "",
    preset: "viewer",
  };
  form.append(element("h2", say("Create an account", "Créer un compte")));
  memberField(
    form,
    say("Display name", "Nom affiché"),
    "",
    (v) => (value.name = v),
  ).required = true;
  const preset = element(
    "label",
    say("Preset", "Préréglage"),
    "settings-field",
  );
  const choice = element("select");
  for (const [key, [label, granted]] of Object.entries(memberPresets())) {
    if (granted.some((p) => !data.grantable.includes(p))) continue;
    const option = element("option", label);
    option.value = key;
    choice.append(option);
  }
  value.preset = choice.value;
  choice.onchange = () => (value.preset = choice.value);
  preset.append(choice);
  form.append(preset);
  memberField(
    form,
    say("Sign-in name", "Identifiant"),
    "",
    (v) => (value.login = v),
  ).required = true;
  if (data.proxy)
    memberField(
      form,
      say("Name sent by the proxy", "Nom transmis par le proxy"),
      "",
      (v) => (value.proxy_user = v),
    ).required = true;
  else {
    const password = memberField(
      form,
      say("Password", "Mot de passe"),
      "",
      (v) => (value.password = v),
      "password",
    );
    password.required = true;
    password.minLength = 12;
    password.autocomplete = "new-password";
  }
  const actions = element("div", undefined, "settings-actions");
  const create = element(
    "button",
    say("Create the account", "Créer le compte"),
    "primary",
  );
  create.type = "submit";
  const cancel = element("button", say("Cancel", "Annuler"));
  cancel.type = "button";
  cancel.onclick = () => dialog.close();
  actions.append(create, cancel);
  form.append(actions);
  form.onsubmit = (event) => {
    event.preventDefault();
    guard(async () => {
      const [, permissions, caps, limits = {}] = memberPresets()[value.preset] || [, [], {}];
      const created = await memberApi("members", {
        name: value.name,
        login: value.login,
        password: value.password,
        proxy_user: value.proxy_user,
        permissions,
        caps,
        ...limits,
      });
      dialog.close();
      memberState.editing = created.id;
      memberState.draft = structuredClone(created);
      toast(
        say(
          `${created.name} can now sign in`,
          `${created.name} peut maintenant se connecter`,
        ),
      );
      await settingsMembers(root);
    });
  };
  dialog.append(form);
  dialog.onclose = () => dialog.remove();
  document.body.append(dialog);
  dialog.showModal();
}

function memberStatus(member) {
  if (member.disabled) return say("Disabled", "Désactivé");
  if (!member.invited) return say("Active", "Actif");
  if (!member.link || member.link.expired)
    return say("Invitation expired", "Invitation expirée");
  const days = Math.max(
    1,
    Math.round((member.link.expires * 1000 - Date.now()) / 86400e3),
  );
  return say(
    `Invitation sent, expires in ${days} d`,
    `Invitation envoyée, expire dans ${days} j`,
  );
}
// The address the Web UI is opened at: this panel lives under static/settings/.
const memberBase = () => new URL("../../", location.href).href;
function memberDialog() {
  const dialog = element("dialog", undefined, "assistant-dialog");
  dialog.onclose = () => dialog.remove();
  document.body.append(dialog);
  return dialog;
}
// "Inviter quelqu'un", a new invitation for `member`, or a password link for them.
function linkDialog(root, member) {
  const data = memberState.data;
  const dialog = memberDialog();
  const form = element("form");
  form.method = "dialog";
  const value = { name: "", note: "", preset: "viewer", days: "3" };
  const invite = !member;
  form.append(
    element(
      "h2",
      invite
        ? say("Invite someone", "Inviter quelqu’un")
        : member.invited
          ? say(`New invitation for ${member.name}`, `Nouvelle invitation pour ${member.name}`)
          : say(`Password link for ${member.name}`, `Lien de mot de passe pour ${member.name}`),
    ),
  );
  if (invite) {
    memberField(
      form,
      say("Display name", "Nom affiché"),
      "",
      (v) => (value.name = v),
    ).required = true;
    const preset = element(
      "label",
      say("Preset", "Préréglage"),
      "settings-field",
    );
    const choice = element("select");
    for (const [key, [label, granted]] of Object.entries(memberPresets())) {
      if (granted.some((p) => !data.grantable.includes(p))) continue;
      const option = element("option", label);
      option.value = key;
      choice.append(option);
    }
    value.preset = choice.value;
    choice.onchange = () => (value.preset = choice.value);
    preset.append(choice);
    form.append(preset);
    memberField(
      form,
      say("Message (optional)", "Message (facultatif)"),
      "",
      (v) => (value.note = v),
    ).maxLength = 500;
  }
  const validity = element(
    "label",
    say("Link valid for", "Validité du lien"),
    "settings-field",
  );
  const days = element("select");
  for (const [amount, label] of [
    ["3", say("3 days", "3 jours")],
    ["7", say("7 days", "7 jours")],
    ["1", say("24 hours", "24 heures")],
  ]) {
    const option = element("option", label);
    option.value = amount;
    days.append(option);
  }
  days.onchange = () => (value.days = days.value);
  validity.append(days);
  form.append(
    validity,
    element(
      "p",
      invite || member.invited
        ? say(
            "The link and its QR code show once created; the person chooses their password.",
            "Le lien et son QR code s’affichent après création ; la personne choisit son mot de passe.",
          )
        : say(
            "Their current password keeps working until the link is used; then their sessions end.",
            "Son mot de passe actuel reste valable jusqu’à l’utilisation du lien ; ses sessions se terminent alors.",
          ),
      "muted",
    ),
  );
  const actions = element("div", undefined, "settings-actions");
  const create = element(
    "button",
    say("Create the link", "Créer le lien"),
    "primary",
  );
  create.type = "submit";
  const cancel = element("button", say("Cancel", "Annuler"));
  cancel.type = "button";
  cancel.onclick = () => dialog.close();
  actions.append(create, cancel);
  form.append(actions);
  form.onsubmit = (event) => {
    event.preventDefault();
    guard(async () => {
      const base = memberBase();
      let answer;
      if (invite) {
        const [, permissions, caps, limits = {}] = memberPresets()[value.preset] || [, [], {}];
        answer = await memberApi("members/invite", {
          name: value.name,
          note: value.note,
          permissions,
          caps,
          ...limits,
          days: Number(value.days),
          base,
        });
      } else
        answer = await memberApi(`members/${member.id}/link`, {
          days: Number(value.days),
          base,
        });
      await settingsMembers(root);
      linkResult(dialog, answer.member, answer.link);
    });
  };
  dialog.append(form);
  dialog.showModal();
}
async function showLink(member) {
  const answer = await memberApi(`members/${member.id}/show-link`, {
    base: memberBase(),
  });
  const dialog = memberDialog();
  linkResult(dialog, member, answer.link);
  dialog.showModal();
}
// The QR code the server encoded, one row of modules per string, drawn as one SVG path.
function memberQr(rows) {
  const svg = "http://www.w3.org/2000/svg";
  const size = rows.length;
  const picture = document.createElementNS(svg, "svg");
  picture.setAttribute("viewBox", `-4 -4 ${size + 8} ${size + 8}`);
  picture.setAttribute("role", "img");
  picture.setAttribute("aria-label", say("QR code of the link", "QR code du lien"));
  picture.classList.add("member-qr");
  const path = document.createElementNS(svg, "path");
  path.setAttribute(
    "d",
    rows
      .flatMap((row, y) =>
        [...row].flatMap((on, x) => (on === "1" ? [`M${x} ${y}h1v1h-1z`] : [])),
      )
      .join(""),
  );
  picture.append(path);
  return picture;
}
function linkResult(dialog, member, link) {
  const invite = link.kind === "invite";
  const form = element("form");
  form.method = "dialog";
  form.append(
    element(
      "h2",
      invite
        ? say(`Invitation for ${member.name}`, `Invitation pour ${member.name}`)
        : say(`Password link for ${member.name}`, `Lien de mot de passe pour ${member.name}`),
    ),
    element(
      "p",
      invite
        ? say(
            `Send this link, or scan the QR code from a phone or a TV. It works once; ${member.name} chooses a sign-in name and password there.`,
            `Envoyez ce lien, ou faites scanner le QR code depuis un téléphone ou une télé. Il ne sert qu’une fois ; ${member.name} y choisit son identifiant et son mot de passe.`,
          )
        : say(
            `Send this link, or scan the QR code. It works once; ${member.name} chooses a new password there.`,
            `Envoyez ce lien, ou faites scanner le QR code. Il ne sert qu’une fois ; ${member.name} y choisit un nouveau mot de passe.`,
          ),
      "muted",
    ),
  );
  const row = element("div", undefined, "member-link");
  const side = element("div", undefined, "member-link-side");
  const label = element(
    "label",
    invite ? say("Invitation link", "Lien d’invitation") : say("Password link", "Lien de mot de passe"),
    "settings-field",
  );
  const url = element("input");
  url.readOnly = true;
  url.value = link.url;
  label.append(url);
  const copy = element("button", say("Copy the link", "Copier le lien"), "primary");
  copy.type = "button";
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(link.url);
    } catch {
      url.select();
      document.execCommand("copy");
    }
    copy.textContent = say("Copied", "Copié");
    toast(say("Link copied", "Lien copié"));
  };
  const copying = element("div", undefined, "settings-actions");
  copying.append(copy);
  const until = new Date(link.expires * 1000).toLocaleString(
    say("en-GB", "fr-FR"),
    { weekday: "long", day: "numeric", month: "long", hour: "numeric", minute: "2-digit" },
  );
  side.append(
    label,
    copying,
    element(
      "small",
      `${say("Valid until", "Valable jusqu’au")} ${until} · ${say("preset", "préréglage")} ${memberPreset(member.permissions)}`,
    ),
  );
  row.append(memberQr(link.qr), side);
  form.append(row);
  const mail = element("div", undefined, "file-access-note");
  const email = element(
    "label",
    say("Send by email", "Envoyer par e-mail"),
    "settings-field",
  );
  const address = element("input");
  address.type = "email";
  address.disabled = false;
  email.append(address);
  mail.append(
    email,
    element(
      "small",
      say(
        "Set up email sending first in Settings → Notifications (SMTP or OVHcloud MX Plan).",
        "Configurez d’abord l’envoi d’e-mails dans Paramètres → Notifications (SMTP ou MX Plan d’OVHcloud).",
      ),
    ),
  );
  mail.append(button(say("Send link", "Envoyer le lien"), async () => {
    if (!address.reportValidity() || !address.value) return;
    await memberApi(`members/${member.id}/email-link`, {email: address.value});
    toast(say("Email sent", "E-mail envoyé"));
  }));
  const actions = element("div", undefined, "settings-actions");
  const close = element("button", say("Close", "Fermer"));
  close.value = "close";
  actions.append(close);
  form.append(mail, actions);
  dialog.replaceChildren(form);
}
