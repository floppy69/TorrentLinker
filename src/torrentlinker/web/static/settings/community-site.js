"use strict";
async function communitySiteSettings(root, initial) {
  const call = (action, value = {}) => request("community-site", {action, value});
  const data = initial || await call("state");
  if (!root.isConnected) return;
  root.replaceChildren();
  const collection = async () => {const panel = element("section"); root.append(panel); await achievementSettings(panel);};
  root.append(element("p", say("Link this app to torrentlinker.fr to share and import community creations.", "Liez cette application à torrentlinker.fr pour partager et importer les créations de la communauté.")));
  const link = (label, url) => {
    const a = element("a", label); a.href = url; a.style.color = "var(--accent)"; a.target = "_blank"; a.rel = "noopener noreferrer";
    if (environment.mode === "desktop") a.onclick = event => {
      event.preventDefault(); guard(() => call("open", {page: new URL(url).pathname.endsWith("/link") ? "link" : "account"}));
    };
    return a;
  };
  if (data.linked) {
    root.append(element("h3", say("App linked", "Application liée")));
    if (data.account) root.append(element("p", `${data.account.name || ""} · ${data.account.forumAccess ? say("Forum access approved", "Accès au forum approuvé") : say("Forum approval pending", "Accès au forum en attente")}`));
    root.append(element("p", say("Expires: ", "Expire le : ") + new Date(data.expires * 1000).toLocaleDateString()));
    const accountLink = element("p");
    accountLink.style.margin = "20px 0";
    accountLink.append(link(say("Open my account on the site", "Ouvrir mon compte sur le site"), `${data.site}/${language === "fr" ? "fr" : "en"}/space/account`));
    root.append(accountLink);
    const actions = element("div", undefined, "settings-actions");
    actions.append(button(say("Check connection", "Vérifier la connexion"), async () => communitySiteSettings(root, await call("check"))), button(say("Revoke this app's access", "Révoquer l’accès de cette application"), async () => communitySiteSettings(root, await call("disconnect"))));
    root.append(actions); await collection(); return;
  }
  if (data.pending.userCode) {
    root.append(element("h3", say("Approve this code on the site", "Approuvez ce code sur le site")));
    const code = element("input"); code.value = data.pending.userCode; code.readOnly = true; code.setAttribute("aria-label", say("Community link code", "Code de liaison communautaire")); root.append(code);
    root.append(element("p", say("The site will verify your email, then ask you to approve this app. Forum access requires separate moderator approval.", "Le site vérifie votre e-mail, puis vous demande d’approuver cette application. L’accès au forum nécessite ensuite l’accord d’un modérateur.")));
    root.append(link(say("Open the approval page", "Ouvrir la page d’approbation"), data.pending.verificationUri));
    root.append(element("p", say("Code expires: ", "Le code expire à : ") + new Date(data.pending.expires * 1000).toLocaleTimeString()));
    root.append(button(say("Cancel linking", "Annuler la liaison"), async () => communitySiteSettings(root, await call("disconnect"))));
    setTimeout(() => {if (root.isConnected && section === "community_site") guard(async () => communitySiteSettings(root, await call("poll")));}, Math.max(5000, data.poll_after * 1000));
    await collection(); return;
  }
  root.append(element("p", say("Only a fingerprint of your signed-in profile is sent. Your tracker username, password and API key stay in the app. The app's access is revocable.", "Seule une empreinte de votre profil connecté est envoyée. Votre identifiant tracker, votre mot de passe et votre clé API restent dans l’application. L’accès de l’application est révocable.")));
  const values = {name: "TorrentLinker"};
  field(root, say("App name shown on the site", "Nom de l’application affiché sur le site"), values, "name");
  root.append(button(say("Get a link code", "Obtenir un code de liaison"), async () => communitySiteSettings(root, await call("start", values)), "primary"));
  await collection();
}
