"use strict";
const $=id=>document.getElementById(id);
const say=(en,fr)=>catalogueEnvironment.language==="fr"?fr:en;
const number=n=>Number(n||0).toLocaleString(catalogueEnvironment.language||"en");
let pending=false,retryAction=null,gainSequence=-1,gainTimer;
const states={done:["Up to date","À jour"],never:["Not read yet","Pas encore lu"],waiting:["Waiting","En attente"],running:["Reading","Lecture"],year:["By year","Par année"],prune:["Checking","Vérification"],paused:["Paused","En pause"],cache:["Cache only","Cache uniquement"]};
function note(card){
  if(!card.fetchable)return say("From searches and the first import; c411’s listing does not show it.","Issu des recherches et du premier import ; absent de la liste c411.");
  if(card.state==="year")return say("Reading year by year","Lecture année par année");
  if(card.state==="prune")return say("Checking torrents c411 no longer lists","Vérification des torrents absents de la liste c411");
  if(card.state==="running")return say("Reading every page","Lecture de toutes les pages");
  if(card.site===null||card.site===undefined)return say("Not compared with c411 yet","Pas encore comparé avec c411");
  const gap=card.ours-card.site;
  return gap===0?say("At parity with c411","À parité avec c411"):gap>0?say(`${number(gap)} more than c411: fetch to remove deleted torrents`,`${number(gap)} de plus que c411 : récupérez pour retirer les torrents supprimés`):say(`${number(-gap)} missing from the Catalogue`,`${number(-gap)} manquants dans le Catalogue`);
}
function summary(value){
  const parts=[say(`${number(value.count)} torrents · Coverage is not guaranteed complete.`,`${number(value.count)} torrents · La couverture complète n’est pas garantie.`)];
  if(value.updated_at)parts.push(say("Updated ","Mis à jour ")+new Date(value.updated_at*1000).toLocaleString(catalogueEnvironment.language));
  if(value.limited_categories?.length)parts.push(say("Indexer paging limit reached.","Limite de pagination de l’indexeur atteinte."));
  if(value.paused)parts.push(say("Historical fetch paused.","Récupération de l’historique en pause."));
  if(value.snapshot_imported_at)parts.push(say("Includes Zen Lab baseline metadata; direct c411 data takes priority.","Inclut les métadonnées de base Zen Lab ; les données c411 sont prioritaires."));
  return parts.join(" · ");
}
function catalogueRender(){
  const env=catalogueEnvironment,data=env.catalogue||{},cards=data.cards||[];
  document.documentElement.lang=env.language||"en";document.documentElement.dataset.theme=env.theme||"dark";
  $("catalogue-intro").textContent=say("Fetch every category or update only the one you need. A fetch reads it again in full, then removes what c411 deleted.","Récupérez toutes les catégories ou seulement celle dont vous avez besoin. Une récupération relit tout, puis retire les torrents supprimés par c411.");
  $("catalogue-fetch").textContent=data.paused?say("Resume fetching all categories","Reprendre toutes les catégories"):say("Fetch all categories","Récupérer toutes les catégories");
  $("catalogue-fetch").disabled=Boolean(env.running)||pending;
  $("catalogue-pause").textContent=say("Pause fetching","Suspendre la récupération");
  $("catalogue-pause").hidden=!env.running;$("catalogue-pause").disabled=pending||Boolean(env.stopping);
  $("catalogue-plan-now").textContent=say("Stop fetching and plan now","Arrêter et créer le Plan");
  $("catalogue-plan-now").disabled=pending||Boolean(env.stopping);
  $("catalogue-progress").hidden=!env.running;
  $("catalogue-phase").textContent=env.phase||say("Fetching the Catalogue…","Récupération du Catalogue…");
  if(Number.isFinite(env.fraction))$("catalogue-fraction").value=env.fraction;else $("catalogue-fraction").removeAttribute("value");
  $("catalogue-status").textContent=env.status||(data.count!==undefined?summary(data):"");
  $("catalogue-empty").hidden=cards.length>0;$("catalogue-empty").textContent=say("No categories available yet.","Aucune catégorie disponible pour le moment.");
  const list=$("catalogue-cards"),keys=cards.map(c=>String(c.root));
  for(const tile of [...list.children])if(!keys.includes(tile.dataset.root))tile.remove();
  for(const card of cards){
    let tile=[...list.children].find(t=>t.dataset.root===String(card.root));
    if(!tile){tile=document.createElement("section");tile.className="panel category";tile.dataset.root=card.root;tile.innerHTML='<div class="card-header"><h2></h2><span class="chip"></span></div><div class="counts"><strong class="number"></strong><span class="site muted"></span><span class="gain"></span></div><progress max="1"></progress><p class="note muted"></p><small class="updated muted"></small><button></button>';tile.querySelector("button").onclick=e=>act("fetch",{root:card.root},e.currentTarget);list.append(tile)}
    tile.dataset.active=String(["running","year","prune"].includes(card.state));
    tile.querySelector("h2").textContent=card.name;tile.querySelector(".chip").textContent=say(...(states[card.state]||states.never));
    tile.querySelector(".number").textContent=number(card.ours);tile.querySelector(".site").textContent=card.site===null||card.site===undefined?"":say(`/ ${number(card.site)} on c411`,`/ ${number(card.site)} sur c411`);
    tile.querySelector("progress").value=card.site?Math.min(1,card.ours/card.site):0;
    tile.querySelector(".note").textContent=note(card);
    tile.querySelector(".updated").textContent=card.updated_at?say("Updated ","Mis à jour ")+new Date(card.updated_at*1000).toLocaleString(env.language):"";
    const button=tile.querySelector("button");button.textContent=say("Fetch only ","Récupérer seulement ")+card.name;button.hidden=!card.fetchable;button.disabled=Boolean(env.running)||pending;
  }
  if(env.gain?.sequence!==undefined&&env.gain.sequence!==gainSequence){
    gainSequence=env.gain.sequence;clearTimeout(gainTimer);
    for(const gain of list.querySelectorAll(".gain"))gain.textContent="";
    const tile=[...list.children].find(t=>t.dataset.root===String(env.gain.root));
    if(tile&&env.gain.added>0){tile.querySelector(".gain").textContent="+"+number(env.gain.added);gainTimer=setTimeout(()=>{tile.querySelector(".gain").textContent=""},1500)}
  }
  $("catalogue-retry").textContent=say("Retry","Réessayer");
  if(env.error){$("catalogue-error").textContent=TLToast.translate(env.error);$("catalogue-error").hidden=false}
}
async function act(action,body={},node){
  if(pending)return;pending=true;const release=TLToast.working(node);retryAction=node=>act(action,body,node);
  $("catalogue-error").hidden=true;$("catalogue-retry").hidden=true;catalogueRender();
  try{await catalogueRequest(action,body);const done={fetch:["Catalogue fetch started.","Récupération du Catalogue lancée."],pause:["Pause requested.","Pause demandée."],"plan-now":["Plan started.","Plan lancé."]}[action];if(done)TLToast.show(say(...done),"ok")}catch(error){TLToast.error(error);$("catalogue-retry").hidden=false}
  finally{release();pending=false;catalogueRender()}
}
function catalogueInit(){
  $("catalogue-fetch").onclick=e=>act("fetch",{},e.currentTarget);$("catalogue-pause").onclick=e=>act("pause",{},e.currentTarget);
  $("catalogue-plan-now").onclick=e=>act("plan-now",{},e.currentTarget);$("catalogue-retry").onclick=e=>retryAction?.(e.currentTarget);
}
