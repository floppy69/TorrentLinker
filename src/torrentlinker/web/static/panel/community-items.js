"use strict";
function communityCall(action,body={}){
 if(location.pathname.includes("/settings/"))return request("community-site",{action:`items-${action}`,value:body});
 if(location.pathname.includes("/media/"))return preCall(`community-${action}`,body);
 if(location.pathname.includes("/feeds/"))return api(`community-items/${action}`,body);
 return api(`community-site/items-${action}`,body);
}
function communityMenu(label, actions, className = "") {
 const menu = element("details", undefined, `community-menu ${className}`);
 const summary = element("summary", label);
 const items = element("div", undefined, "community-menu-actions");
 for (const [name, action] of actions) items.append(button(name, () => {
   menu.open = false;
   return action();
 }));
 menu.append(summary, items);
 menu.addEventListener("keydown", event => {
   if (event.key === "Escape") { menu.open = false; summary.focus(); }
 });
 return menu;
}
let communityDialogSequence = 0;
function communityDialog(title) {
 const dialog = element("dialog", undefined, "community-review");
 const header = element("header", undefined, "community-dialog-heading");
 const heading = element("h2", title);
 heading.id = `community-title-${++communityDialogSequence}`;
 dialog.setAttribute("aria-labelledby", heading.id);
 header.append(heading, button(say("Close", "Fermer"), () => dialog.close(), "community-close"));
 dialog.append(header);
 document.body.append(dialog);
 dialog.onclose = () => dialog.remove();
 dialog.showModal();
 return dialog;
}
function communityField(root,label,value="",multiline=false){const wrap=element("label",label),input=element(multiline?"textarea":"input");input.value=value;input.setAttribute("aria-label",label);wrap.append(input);root.append(wrap);return input}
function communityJSON(root,value){const pre=element("pre",JSON.stringify(value,null,2));root.append(pre)}
async function communityShareDialog(kind,source={},data){
 const dialog=communityDialog(say("Share a creation","Partager une création"));dialog.append(element("p",say("Review the sanitized content before publishing. Known credentials, URLs, paths and account names are removed from preset text. Check remaining text and every media file yourself.","Vérifiez le contenu nettoyé avant publication. Les identifiants connus, URL, chemins et noms de compte sont retirés du texte. Vérifiez le texte restant et chaque fichier média.")));
 const title=communityField(dialog,say("Public title","Titre public")),description=communityField(dialog,say("Description","Description"),"",true),category=communityField(dialog,say("Category","Catégorie"),kind),tags=communityField(dialog,say("Tags, comma separated","Tags séparés par des virgules")),licence=element("select");licence.setAttribute("aria-label",say("Licence","Licence"));for(const name of["CC-BY-4.0","CC-BY-SA-4.0","CC0-1.0","MIT","own-work"])licence.append(new Option(name,name));dialog.append(licence);
 const existing=communityField(dialog,say("Existing item ID for a new version, optional","ID d’une création existante pour une nouvelle version, facultatif"));
 const review=element("div");dialog.append(review);let stage="";dialog.addEventListener("close",()=>{if(stage)communityCall("cancel",{review:stage}).catch(()=>{})});
 dialog.append(button(say("Prepare sanitized preview","Préparer l’aperçu nettoyé"),async()=>{if(stage)await communityCall("cancel",{review:stage});const metadata={title:title.value,description:description.value,category:category.value,tags:tags.value.split(",").map(x=>x.trim()).filter(Boolean),license:licence.value};if(existing.value.trim())metadata.itemId=existing.value.trim();const result=await communityCall("prepare",{kind,source,data,metadata});stage=result.review;review.replaceChildren();communityJSON(review,{metadata:result.metadata,content:result.content,bytes:result.bytes,sha256:result.sha256});const label=element("label"),rights=element("input");rights.type="checkbox";label.append(rights,document.createTextNode(say("I reviewed this exact preview and every selected media file, and can redistribute them under this licence.","J’ai vérifié cet aperçu et chaque média sélectionné, et je peux les redistribuer sous cette licence.")));review.append(label,button(say("Publish this reviewed version","Publier cette version vérifiée"),async()=>{if(!rights.checked)throw Error(say("Confirm your review and rights first.","Confirmez d’abord votre vérification et les droits."));const published=await communityCall("publish",{review:stage,confirmed:true});stage="";review.replaceChildren(element("p",`${published.status} · v${published.version}`));communityJSON(review,published)}))}));
}
async function communityBrowseDialog(kind, onImport = async () => {}) {
 const names = {rss:say("Community rules","Règles communautaires"), "release-score":say("Community profiles","Profils communautaires"), prompt:say("Community prompts","Prompts communautaires"), studio:say("Community projects","Projets communautaires"), preroll:say("Community clips","Clips communautaires")};
 const dialog = communityDialog(names[kind] || say("Community creations","Créations communautaires"));
 dialog.append(element("p", say("Browse shared creations, then review a local copy before importing.", "Parcourez les créations partagées, puis vérifiez la copie locale avant de l’importer."), "muted"));
 const search = element("form", undefined, "community-search");
 const query = communityField(search, say("Search", "Rechercher"));
 const submit = button(say("Search", "Rechercher"), () => {offset=0; updates=false; return browse();});
 search.append(submit);
 const tools = element("div", undefined, "community-browse-tools");
 const status = element("p", "", "community-status");
 status.setAttribute("role", "status");
 const list = element("div", undefined, "community-results");
 const pagination = element("div", undefined, "community-pagination");
 let offset=0, updates=false, generation=0;
 const previous = button(say("Previous", "Précédent"), () => {offset=Math.max(0,offset-30);return browse();});
 const next = button(say("Next", "Suivant"), () => {offset+=30;return browse();});
 pagination.append(previous,next);
 const browse = async () => {
   const current = ++generation;
   status.textContent=say("Loading creations…", "Chargement des créations…");
   list.replaceChildren(); previous.disabled=next.disabled=true;
   try {
     const found=await communityCall(updates?"updates":"browse",{kind,q:query.value,offset});
     if(current!==generation || !dialog.isConnected)return;
     status.textContent=updates?say("Available updates", "Mises à jour disponibles"):"";
     for(const item of found.items) {
       const card=element("section",undefined,"community-result");
       card.append(element("h3",item.title),element("p",item.description),element("small",`v${item.version} · ${item.license} · ${(item.bytes/1000000).toFixed(2)} MB`));
       card.append(button(say("Review import", "Vérifier l’import"),async()=>{
         const result=await communityCall("download",{id:item.id,version:item.version_id});
         const preview=communityDialog(say("Review local copy","Vérifier la copie locale"));
         let stage=result.review;
         preview.addEventListener("close",()=>{if(stage)communityCall("cancel",{review:stage}).catch(()=>{})});
         preview.append(element("p",say("Creates a separate local copy and preserves existing edits. Prompts are never sent automatically. Imported RSS rules remain paused.","Crée une copie locale indépendante et conserve les modifications existantes. Les prompts ne sont jamais envoyés automatiquement. Les règles RSS importées restent en pause.")));
         communityJSON(preview,result);
         preview.append(button(say("Import this version","Importer cette version"),async()=>{
           const imported=await communityCall("apply",{review:stage,confirmed:true});
           stage="";await onImport(imported);preview.close();
         }));
       }));
       list.append(card);
     }
     if(!found.items.length)list.append(element("p",updates?say("Your imported creations are up to date.","Vos créations importées sont à jour."):say("No creations found. Try another search.","Aucune création trouvée. Essayez une autre recherche."),"community-empty"));
     previous.disabled=offset===0;next.disabled=found.items.length<30;
   } catch(error) {
     if(current!==generation || !dialog.isConnected)return;
     status.textContent=say("Community is unavailable", "La communauté est indisponible");
     const message = error.message === "Link this app to the community first."
       ? say("Link this app to the community first.", "Cette application n’est pas encore associée à un compte communautaire.")
       : error.message || String(error);
     list.replaceChildren(element("p",message,"community-error"),element("p",say("Check the account link in Settings → Join the community, then try again.","Vérifiez l’association du compte dans Paramètres → Rejoindre la communauté, puis réessayez."),"muted"));
   }
 };
 search.onsubmit=event=>{event.preventDefault();offset=0;updates=false;void browse();};
 tools.append(button(say("Check updates","Vérifier les mises à jour"),()=>{offset=0;updates=true;return browse();}),button(say("Imported versions","Versions importées"),async()=>{generation++;status.textContent=say("Import history","Historique des imports");list.replaceChildren();previous.disabled=next.disabled=true;try{communityJSON(list,await communityCall("history"));}catch(error){status.textContent=error.message||String(error);}}));
 dialog.append(search,tools,status,list,pagination);
 await browse();
}
