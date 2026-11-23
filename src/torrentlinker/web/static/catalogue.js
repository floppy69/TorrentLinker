"use strict";
const catalogueFrame=document.createElement("iframe");
catalogueFrame.id="catalogue-frame";catalogueFrame.title="Catalogue";
catalogueFrame.src="static/catalogue/view.html";
catalogueFrame.style.cssText="width:100%;height:75vh;min-height:300px;border:0;display:block";
$("zen-catalogue-panel").append(catalogueFrame);
const catalogueUI={value:{cards:[]},job:null,progress:null,stopping:false,plan:false,error:"",refreshing:false,generation:0};
const catalogueFinished=new Set();
function showCatalogue(value){if(value){catalogueUI.value=value;catalogueEnvironment()}}
function catalogueEnvironment(){
  shellEnvironment();
  const active=state.view==="zen"&&!$("zen-catalogue-panel").hidden&&!$("workspace").hidden;
  if(active)catalogueFrame.style.height=`${Math.max(300,innerHeight-catalogueFrame.getBoundingClientRect().top-24)}px`;
  const p=catalogueUI.progress,root=p?.catalogue_root;
  const cards=(catalogueUI.value.cards||[]).map(card=>{
    if(!catalogueUI.job||!root||!card.fetchable)return card;
    const state=card.root===root?({"c411-capped":"year","c411-prune":"prune"}[p.source]||"running"):p.single_root===null&&card.root>root?"waiting":card.state;
    return {...card,state};
  });
  const position=p?.position;
  const phase=p?say(`Page ${p.pages||0} · ${p.added||0} added`,`Page ${p.pages||0} · ${p.added||0} ajoutés`):"";
  catalogueFrame.contentWindow?.postMessage({type:"catalogue-environment",value:{mode:"web",active,language,theme:document.documentElement.dataset.theme||"dark",catalogue:{...catalogueUI.value,cards},running:Boolean(catalogueUI.job),stopping:catalogueUI.stopping,error:catalogueUI.error,phase,status:catalogueUI.stopping?say("Pausing after the current page…","Suspension après la page en cours…"):"",fraction:position?(position.done-1)/Math.max(1,position.total):null}},location.origin);
}
async function refreshCatalogue(){
  const generation=++catalogueUI.generation;
  const value=await api("zen/catalogue");
  if(generation===catalogueUI.generation)showCatalogue(value);
}
async function loadCatalogue(){
  const generation=++catalogueUI.generation;
  const [value,jobs]=await Promise.all([api("zen/catalogue"),api("jobs")]);
  if(generation===catalogueUI.generation)showCatalogue(value);catalogueJobs(jobs);
}
function trackCatalogue(id,client){
  if(!state.jobs.has(id))state.jobs.set(id,{body:{client_id:client,kind:"catalogue"},done:()=>finishCatalogue(id),failed:error=>finishCatalogue(id,error)});
}
function catalogueJobs(rows){
  const candidates=rows.filter(row=>row.kind==="catalogue"&&!catalogueFinished.has(row.id));
  const current=candidates.find(row=>row.status==="running")||candidates.find(row=>row.status==="queued");
  // An older idle poll may not contain a job that was just submitted. Only its
  // terminal response can clear it; completed jobs cannot be revived by old polls.
  if(current){catalogueUI.job=current.id;catalogueUI.progress=current.progress;trackCatalogue(current.id,current.client_id)}
  if(current&&!catalogueUI.refreshing){
    catalogueUI.refreshing=true;
    refreshCatalogue().catch(error=>{catalogueUI.error=error.message}).finally(()=>{catalogueUI.refreshing=false;catalogueEnvironment()});
  }
  catalogueEnvironment();
}
async function finishCatalogue(id,error){
  catalogueFinished.add(id);
  if(catalogueUI.job!==id)return;
  catalogueUI.job=null;catalogueUI.progress=null;catalogueUI.stopping=false;
  catalogueUI.error=typeof error==="string"?error:"";
  await refreshCatalogue();
  if(catalogueUI.plan){const client=catalogueUI.plan;catalogueUI.plan=false;if(client===state.clientId){zenTab("plan");await startCachedPlan()}}
}
window.addEventListener("message",async event=>{
  if(event.source!==catalogueFrame.contentWindow||event.origin!==location.origin)return;
  const message=event.data;
  if(message?.type==="catalogue-ready"){catalogueEnvironment();return}
  if(message?.type!=="catalogue-request")return;
  try{
    if($("workspace").hidden)throw Error("Sign in first.");
    const body=message.body||{};
    catalogueUI.error="";
    if(message.path==="fetch"){
      if(catalogueUI.job)throw Error(say("A Catalogue fetch is already running.","Une récupération est déjà en cours."));
      if(state.clientId==="all")throw Error(say("Choose a target client first.","Choisissez un client cible."));
      const request={kind:"catalogue",client_id:state.clientId};
      if(body.root!==undefined){if(!Number.isInteger(body.root)||!catalogueUI.value.cards.some(c=>c.root===body.root&&c.fetchable))throw Error("Unknown category.");request.catalogue_root=body.root}
      const {id}=await api("jobs",request);
      catalogueUI.job=id;trackCatalogue(id,request.client_id);
      await pollJobs();
    }else if(["pause","plan-now"].includes(message.path)&&catalogueUI.job){
      const id=catalogueUI.job,client=state.clientId;
      catalogueUI.stopping=true;catalogueUI.plan=message.path==="plan-now"?client:false;
      catalogueEnvironment();
      try{await api(`jobs/${id}/cancel`,{})}catch(error){
        if(catalogueUI.job===id){catalogueUI.stopping=false;catalogueUI.plan=false;catalogueEnvironment()}
        throw error;
      }
    }else throw Error("Catalogue action is unavailable.");
    catalogueEnvironment();
    catalogueFrame.contentWindow?.postMessage({type:"catalogue-response",id:message.id,value:null},location.origin);
  }catch(error){catalogueFrame.contentWindow?.postMessage({type:"catalogue-response",id:message.id,error:error.message},location.origin)}
});
window.addEventListener("resize",catalogueEnvironment);
document.addEventListener("tl-language-changed",catalogueEnvironment);
new MutationObserver(catalogueEnvironment).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
for(const node of [$("zen-catalogue-panel"),$("view-zen"),$("workspace")])new MutationObserver(catalogueEnvironment).observe(node,{attributes:true,attributeFilter:["hidden"]});
