"use strict";
// Paramètres → Mon compte (#135): every account holder's own password, the profiles of the
// people who watch under their account (Viewers) with their PINs, and their Shared Screens.
// A manager edits another Member's from Utilisateurs with the same editor. The server checks
// every change again: a profile never sees more than its account.
const accountApi = (path, body) =>
  request(path.startsWith("members") ? "members" : "account", {
    path,
    body,
    method: body === undefined ? "GET" : "POST",
  });
const householdKinds = () => [...memberVideo(), ...memberGroups()[0][1]];
const householdRank = (age) => (age === null || age === "" ? 5 : ["TP", "10", "12", "16", "18"].indexOf(age));
async function settingsAccount(root) {
  const data = await accountApi("account");
  if (root.isConnected) drawAccount(root, data);
}
function drawAccount(root, data) {
  root.replaceChildren();
  const card = element("section", undefined, "settings-card");
  card.append(
    element("h3", data.owner ? say("Owner", "Propriétaire") : data.name),
    element(
      "p",
      data.owner
        ? say("Your password is the one chosen when starting the server.", "Votre mot de passe est celui choisi au démarrage du serveur.")
        : data.proxy
          ? say("Your reverse proxy signs you in.", "Votre proxy inverse vous connecte.")
          : `${say("Sign-in name", "Identifiant")} : ${data.login}`,
      "muted",
    ),
  );
  if (!data.owner && !data.proxy) {
    const value = { current: "", password: "" };
    const fields = element("div", undefined, "settings-fields");
    memberField(fields, say("Current password", "Mot de passe actuel"), "", (text) => (value.current = text), "password");
    memberField(fields, say("New password (12 characters or more)", "Nouveau mot de passe (12 caractères ou plus)"), "", (text) => (value.password = text), "password");
    card.append(
      fields,
      element(
        "small",
        say("Every other session and Shared Screen of your account ends.", "Toutes vos autres sessions et écrans partagés se terminent."),
        "muted",
      ),
      button(say("Change the password", "Changer le mot de passe"), async () => {
        await accountApi("account/password", value);
        toast(say("Password changed", "Mot de passe changé"));
        await settingsAccount(root);
      }),
    );
  }
  root.append(card);
  const household = element("div");
  root.append(household);
  householdEditor(household, { base: "account", account: data.id, name: data.owner ? say("you", "vous") : data.name, own: true, proxy: data.proxy, promote: data.promote, data });
}
// Profiles and Shared Screens of one account: `base` is "account" for one's own, or
// "members/<id>" for a manager.
function householdEditor(root, options) {
  const { data } = options;
  root.replaceChildren();
  const holder = data.profiles[0];
  const intro = element("section", undefined, "settings-card");
  intro.append(
    element("h3", say("Profiles", "Profils")),
    element(
      "p",
      say(
        `Profiles watch under ${options.name}'s account without signing in, on a Shared Screen: Media only, never broader than the account, and they never make requests. Each keeps its own progress and playlists.`,
        `Les profils regardent sous le compte de ${options.name} sans se connecter, sur un écran partagé : Médias seulement, jamais plus large que le compte, et ils ne font pas de demandes. Chacun garde sa reprise de lecture et ses listes.`,
      ),
      "muted",
    ),
  );
  root.append(intro);
  for (const profile of data.profiles) root.append(householdProfile(root, options, profile, holder));
  const add = element("div", undefined, "settings-actions");
  add.append(button(say("Add a profile", "Ajouter un profil"), () => householdForm(root, options, null, holder)));
  root.append(add);
  const screens = element("section", undefined, "settings-card");
  screens.append(
    element("h3", say("Shared Screens", "Écrans partagés")),
    element(
      "p",
      say(
        "Browsers marked as shared when signing in: they ask who watches, and stay signed in for 90 days of disuse.",
        "Navigateurs déclarés partagés en se connectant : on y demande qui regarde, et ils restent connectés 90 jours sans usage.",
      ),
      "muted",
    ),
  );
  if (!data.screens.length) screens.append(element("p", say("No Shared Screen.", "Aucun écran partagé."), "muted"));
  for (const screen of data.screens) {
    const row = element("div", undefined, "member-head file-access-note");
    const what = element("span");
    what.append(
      element("strong", screen.name),
      element("br"),
      element("small", `${say("Last used", "Dernier usage")} : ${new Date(screen.used * 1000).toLocaleString(language === "fr" ? "fr-FR" : "en-GB")}`),
    );
    row.append(
      what,
      button(say("Forget this screen", "Oublier cet écran"), async () => {
        if (!confirm(say(`Forget ${screen.name}? It is signed out at once.`, `Oublier ${screen.name} ? Il est déconnecté aussitôt.`))) return;
        options.data = await accountApi(`${options.base}/screens/${screen.id}/forget`, {});
        toast(say(`${screen.name} forgotten`, `${screen.name} oublié`));
        householdEditor(root, options);
      }),
    );
    screens.append(row);
  }
  root.append(screens);
}
function householdSummary(profile) {
  const kinds = householdKinds().filter(([key]) => profile.permissions.includes(key)).map(([, label]) => label);
  const age = memberAges().find(([value]) => value === (profile.age_limit || ""));
  return [kinds.join(", ") || say("Nothing to watch", "Rien à regarder"), profile.age_limit ? age?.[1] : ""].filter(Boolean).join(" · ");
}
function householdProfile(root, options, profile, holder) {
  const card = element("section", undefined, "client-card");
  const head = element("div", undefined, "member-head");
  const who = element("div");
  const pin = profile.pin
    ? say("PIN to open", "Code pour ouvrir")
    : profile.needs_pin
      ? say("PIN required: a more restricted profile exists", "Code obligatoire : un profil plus restreint existe")
      : say("No PIN", "Sans code");
  who.append(
    element("h3", profile.holder ? `${profile.name || say("Owner", "Propriétaire")} · ${say("account holder", "titulaire du compte")}` : profile.name),
    element("p", `${profile.holder ? say("Sees all the account allows", "Voit tout ce que le compte permet") : householdSummary(profile)} · ${pin}`, "muted"),
  );
  const actions = element("div", undefined, "settings-actions");
  if (options.own) actions.append(button(say("PIN", "Code"), () => householdPin(root, options, profile, card)));
  if (!profile.holder) {
    actions.append(button(say("Edit", "Modifier"), () => householdForm(root, options, profile, holder, card)));
    if (options.promote)
      actions.append(
        button(say("Invite as a member", "Inviter comme membre"), async () => {
          if (!confirm(say(`Invite ${profile.name} as a member? Their progress and playlists follow them.`, `Inviter ${profile.name} comme membre ? Sa reprise de lecture et ses listes la suivent.`))) return;
          const answer = await accountApi(`members/${options.account}/viewers/${profile.id}/promote`, { days: 3, base: memberBase() });
          const shown = memberDialog();
          linkResult(shown, answer.member, answer.link);
          shown.showModal();
          options.data = answer;
          householdEditor(root, options);
        }),
      );
    const remove = button(say("Remove", "Retirer"), async () => {
      if (!confirm(say(`Remove ${profile.name}? Their progress and playlists are erased.`, `Retirer ${profile.name} ? Sa reprise de lecture et ses listes sont effacées.`))) return;
      options.data = await accountApi(`${options.base}/viewers/${profile.id}/delete`, {});
      householdEditor(root, options);
    });
    remove.classList.add("member-danger");
    actions.append(remove);
  }
  head.append(who, actions);
  card.append(head);
  return card;
}
// A profile's name, Content Kinds and Age Rating limit, within the account holder's.
function householdForm(root, options, profile, holder, after) {
  document.querySelector(".household-form")?.remove();
  const value = profile
    ? { name: profile.name, permissions: [...profile.permissions], age_limit: profile.age_limit }
    : { name: "", permissions: holder.permissions.filter((p) => p !== "adult"), age_limit: holder.age_limit };
  const form = element("fieldset", undefined, "household-form");
  form.append(element("legend", profile ? say(`Edit ${profile.name}`, `Modifier ${profile.name}`) : say("New profile", "Nouveau profil")));
  const fields = element("div", undefined, "settings-fields");
  memberField(fields, say("Name", "Nom"), value.name, (text) => (value.name = text));
  const age = element("label", say("Age limit", "Limite d’âge"), "settings-field");
  const select = element("select");
  for (const [key, label] of memberAges())
    if (householdRank(key) <= householdRank(holder.age_limit)) select.append(new Option(label, key));
  select.value = value.age_limit || "";
  select.onchange = () => (value.age_limit = select.value || null);
  age.append(select);
  fields.append(age);
  form.append(fields);
  const kinds = element("div");
  for (const [key, label] of householdKinds())
    if (holder.permissions.includes(key))
      memberCheck(kinds, label, value.permissions.includes(key), false, (checked) => {
        value.permissions = checked ? [...value.permissions, key] : value.permissions.filter((p) => p !== key);
      });
  form.append(kinds);
  const actions = element("div", undefined, "settings-actions");
  actions.append(
    button(say("Save", "Enregistrer"), async () => {
      options.data = await accountApi(profile ? `${options.base}/viewers/${profile.id}` : `${options.base}/viewers/new`, value);
      toast(say("Profile saved", "Profil enregistré"));
      householdEditor(root, options);
    }, "primary"),
    button(say("Cancel", "Annuler"), () => form.remove()),
  );
  form.append(actions);
  (after || root.querySelector(".settings-actions:last-of-type") || root).after(form);
}
// Set, change or remove a PIN; a forgotten one is reset with the account's password.
function householdPin(root, options, profile, after) {
  document.querySelector(".household-form")?.remove();
  const value = { viewer: profile.id, pin: "", password: "" };
  const form = element("fieldset", undefined, "household-form");
  form.append(element("legend", say(`PIN of ${profile.name || say("the owner", "le propriétaire")}`, `Code de ${profile.name || say("the owner", "le propriétaire")}`)));
  const fields = element("div", undefined, "settings-fields");
  const pin = memberField(fields, say("New PIN, 4 to 8 digits (empty: none)", "Nouveau code, 4 à 8 chiffres (vide : aucun)"), "", (text) => (value.pin = text), "password");
  pin.inputMode = "numeric";
  pin.autocomplete = "off";
  pin.maxLength = 8;
  if (!options.proxy)
    memberField(fields, say("Your account's password", "Mot de passe de votre compte"), "", (text) => (value.password = text), "password");
  form.append(fields);
  const actions = element("div", undefined, "settings-actions");
  actions.append(
    button(say("Save the PIN", "Enregistrer le code"), async () => {
      options.data = await accountApi("account/pin", value);
      toast(value.pin ? say("PIN saved", "Code enregistré") : say("PIN removed", "Code retiré"));
      householdEditor(root, options);
    }, "primary"),
    button(say("Cancel", "Annuler"), () => form.remove()),
  );
  form.append(actions);
  after.after(form);
}
// Utilisateurs → a Member's "Profiles and Shared Screens", for a manager.
async function memberHousehold(member) {
  const data = await accountApi(`members/${member.id}/profiles`);
  const dialog = memberDialog();
  dialog.append(element("h2", say(`Profiles and Shared Screens of ${member.name}`, `Profils et écrans partagés de ${member.name}`)));
  const body = element("div");
  const close = element("button", say("Close", "Fermer"));
  close.type = "button";
  close.onclick = () => dialog.close();
  dialog.append(body, close);
  householdEditor(body, { base: `members/${member.id}`, account: member.id, name: member.name, own: false, proxy: memberState.data.proxy, promote: !memberState.data.proxy, data });
  dialog.showModal();
}
