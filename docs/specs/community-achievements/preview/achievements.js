"use strict";
async function achievementSettings(root) {
  const expanded = new Set([...root.querySelectorAll("details[open] > summary")].map(e => e.textContent));
  const call = (action, value = {}) => request("community-site", {action: `achievements-${action}`, value});
  const state = await call("state");
  if (!root.isConnected) return;
  root.replaceChildren(); root.style.marginTop = "24px";
  const names = {
    "already-seeding": ["Already seeding", "Déjà en partage"], "reseed-1": ["First reseed", "Première remise en partage"],
    "reseed-10": ["10 reseeds", "10 remises en partage"], "reseed-100": ["100 reseeds", "100 remises en partage"],
    "playlist-first": ["First playlist", "Première playlist"], "studio-first": ["First render", "Premier rendu"],
    "rss-first": ["First tested rule", "Première règle testée"], "community-import-first": ["First community import", "Premier import communautaire"]
  };
  const notify = message => { status.textContent = message; };
  const refresh = async (action, values) => {
    await call(action, values); await achievementSettings(root);
    root.querySelector('[role="status"]').textContent = say("Saved", "Enregistré");
  };
  const actions = () => element("div", undefined, "settings-actions");
  root.append(element("h3", say("App achievements", "Succès de l’application")));
  const status = element("p", state.status || ""); status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
  root.append(status);
  const info = element("details"), summary = element("summary", "ⓘ"); summary.setAttribute("aria-label", say("About achievements", "À propos des succès"));
  info.append(summary, element("p", say("Local evidence, no lifetime estimates. Only badge IDs are shared with the site. Pairing exchanges private ledgers directly between your installations. No automatic router port forwarding.", "Preuves locales, sans estimation de votre activité passée. Seuls les identifiants des succès sont partagés avec le site. L’appairage échange les registres privés entre vos installations. Aucun port n’est ouvert automatiquement sur le routeur.")));
  root.append(info);
  const grid = element("div", undefined, "achievement-grid"); grid.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:16px 0";
  for (const [code, labels] of Object.entries(names)) {
    const earned = state.achievements.some(a => a.code === code), card = element("div");
    card.style.cssText = `padding:14px;border:1px solid ${earned ? "var(--accent)" : "var(--line)"};border-radius:10px`;
    card.append(element("strong", `${earned ? "✓ " : ""}${say(...labels)}`), element("div", earned ? say("Earned", "Obtenu") : say("Not yet earned", "À obtenir")));
    grid.append(card);
  }
  root.append(grid, element("p", `${say("Verified reseeds", "Remises en partage vérifiées")} : ${state.reseeds} · ${say("Tracking since", "Suivi depuis le")} ${new Date(state.trackingStarted * 1000).toLocaleDateString()}`));
  const controls = actions();
  controls.append(button(say("Check retained history", "Vérifier l’historique conservé"), async () => {
    notify(say("Checking…", "Vérification…"));
    const result = await call("recover"); await achievementSettings(root);
    root.querySelector('[role="status"]').textContent = `${say("Playlists recovered", "Playlists retrouvées")} : ${result.recovery.playlistsRecovered} · ${say("Seeding observed", "Partages observés")} : ${result.recovery.seedingObserved} · ${say("Unavailable clients", "Clients indisponibles")} : ${result.recovery.unavailableClients}`;
  }));
  root.append(controls);
  const sharing = element("section"); sharing.append(element("h4", say("Community sharing", "Partage communautaire")));
  const account = element("a", say("Consent and badge visibility", "Consentement et visibilité des succès")); account.href = `https://torrentlinker.fr/${language === "fr" ? "fr" : "en"}/space/achievements`; account.target = "_blank"; account.rel = "noopener noreferrer"; account.style.color = "var(--link,var(--accent))";
  if (environment.mode === "desktop") account.onclick = e => {e.preventDefault(); guard(() => request("community-site", {action:"open",value:{page:"achievements"}}));};
  const accountRow = element("p"); accountRow.style.margin = "20px 0"; accountRow.append(account); sharing.append(accountRow);
  const toggles = actions();
  toggles.append(button(state.sharing ? say("Pause on this installation", "Suspendre sur cette installation") : say("Share future achievements", "Partager les prochains succès"), async () => {
    await refresh(state.sharing ? "disable" : "enable");
    if (state.sharing) root.querySelector('[role="status"]').textContent = say("Paused on this installation. Other installations are unchanged. Open the site controls to stop account-wide sharing and keep or hide existing badges.", "Partage suspendu sur cette installation. Les autres restent inchangées. Sur le site, arrêtez le partage du compte et choisissez de conserver ou masquer les succès publiés.");
  }));
  if (state.sharing) {
    toggles.append(button(say("Share earned achievements too", "Partager aussi les succès obtenus"), async () => refresh("share-existing")));
    toggles.append(button(say("Sync now", "Synchroniser"), async () => refresh("sync")));
  }
  sharing.append(toggles, element("p", `${say("Pending badges", "Succès en attente")} : ${state.pending}`)); root.append(sharing);
  const pairing = element("details"); pairing.append(element("summary", say("My installations", "Mes installations")));
  pairing.append(element("p", say("Approve pairing in your site account, then exchange invitations on both installations. Invitations expire after five minutes.", "Autorisez l’appairage dans votre compte sur le site, puis échangez les invitations sur les deux installations. Elles expirent après cinq minutes.")));
  pairing.append(button(state.pairing ? say("Disable pairing", "Désactiver l’appairage") : say("Enable pairing", "Activer l’appairage"), async () => refresh(state.pairing ? "pair-disable" : "pair-enable")));
  for (const peer of state.peers) {
    const row = element("div"); row.append(element("p", `${peer.installationId} · ${peer.endpoint} · ${peer.status}`), button(say("Remove pairing", "Retirer l’appairage"), async () => refresh("pair-remove", {fingerprint:peer.fingerprint}))); pairing.append(row);
  }
  if (state.pairing) {
    const address = element("input"); address.type="url"; address.placeholder="https://192.168.1.20:3198"; address.setAttribute("aria-label", say("This installation’s local HTTPS address", "Adresse HTTPS locale de cette installation"));
    const outgoing = element("textarea"); outgoing.readOnly=true; outgoing.rows=4; outgoing.setAttribute("aria-label", say("Invitation to copy to the other installation", "Invitation à copier sur l’autre installation"));
    pairing.append(address, button(say("Create invitation", "Créer une invitation"), async () => {outgoing.value=JSON.stringify(await call("invitation", {endpoint:address.value})); notify(say("Invitation ready", "Invitation prête"));}), outgoing);
    const incoming = element("textarea"); incoming.rows=4; incoming.setAttribute("aria-label", say("Invitation from the other installation", "Invitation de l’autre installation"));
    const review = element("div");
    pairing.append(incoming, button(say("Review invitation", "Examiner l’invitation"), async () => {
      const invitation = JSON.parse(incoming.value), identity = await call("pair-inspect", {invitation}); review.replaceChildren();
      review.append(element("p", `${identity.installationId} · ${identity.endpoint}`), Object.assign(element("code", identity.fingerprint), {style:"overflow-wrap:anywhere"}), button(say("Confirm this installation", "Confirmer cette installation"), async () => refresh("pair-add", {invitation,confirmed:true})));
    }), review);
  }
  root.append(pairing);
  const recovery = element("details"); recovery.append(element("summary", say("Backup and reset", "Sauvegarde et remise à zéro")));
  recovery.append(element("p", say("Private evidence only, without keys or consent. Restoring stops sharing and removes pairings. Published badges are unchanged.", "Preuves privées uniquement, sans clés ni consentement. Restaurer arrête le partage et retire les appairages. Les succès publiés sont conservés.")));
  recovery.append(button(say("Save ledger", "Sauvegarder le registre"), async () => {
    const document = await call("backup");
    if (environment.mode === "desktop") await request("community-site", {action:"save-ledger",value:{document}});
    else {const a=element("a"); a.href=URL.createObjectURL(new Blob([JSON.stringify(document)],{type:"application/json"})); a.download="torrentlinker-ledger.json"; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
    notify(say("Backup ready", "Sauvegarde prête"));
  }));
  const file=element("input");file.type="file";file.accept=".json";file.setAttribute("aria-label",say("Choose a ledger backup", "Choisir une sauvegarde du registre"));
  const reviewBackup=element("div"); file.onchange=()=>guard(async()=>{
    if(!file.files[0] || file.files[0].size>20000000) throw new Error(say("Backup exceeds 20 MB", "Sauvegarde supérieure à 20 Mo"));
    const document=JSON.parse(await file.files[0].text()); reviewBackup.replaceChildren();
    reviewBackup.append(element("p", `${say("Account", "Compte")} : ${document.accountId} · ${say("Pages", "Pages")} : ${document.pages?.length ?? "?"}`),button(say("Merge this backup", "Fusionner cette sauvegarde"), async()=>refresh("restore",{document,confirmed:true})));
  }); recovery.append(file,reviewBackup);
  const reset=element("details");reset.append(element("summary",say("Reset local progress", "Effacer la progression locale")),element("p",say("This removes local progress and pairings and stops sharing. Save a backup first.","Cette action efface la progression locale et les appairages, et arrête le partage. Sauvegardez d’abord.")),button(say("Confirm reset", "Confirmer l’effacement"),async()=>refresh("reset",{confirmed:true})));recovery.append(reset);root.append(recovery);
  for (const detail of root.querySelectorAll("details")) if (expanded.has(detail.querySelector("summary")?.textContent)) detail.open = true;
}
