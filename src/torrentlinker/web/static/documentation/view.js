"use strict";
const $=id=>document.getElementById(id);
const say=(en,fr)=>documentationEnvironment.language==="fr"?fr:en;
let guideLanguage="", guides=[], entries=[], entryIndex=-1;
let pageVersion=0, indexVersion=0, navigationRevision=-1, initializing;
let retry=()=>{};
const current=()=>entries[entryIndex];
function labels(){
  document.documentElement.lang=documentationEnvironment.language||"en";
  document.documentElement.dataset.theme=documentationEnvironment.theme||"dark";
  $("guide-language-label").textContent=say("Guide language","Langue du guide");
  $("guide-language").setAttribute("aria-label",$("guide-language-label").textContent);
  for(const [id,en,fr] of [["guide-back","Back","Précédent"],["guide-forward","Forward","Suivant"]]){
    $(id).title=say(en,fr);$(id).setAttribute("aria-label",say(en,fr));
  }
  $("guide-filter").placeholder=say("Filter guides","Filtrer les guides");
  $("guide-filter").setAttribute("aria-label",$("guide-filter").placeholder);
  $("guide-online").textContent=say("Open online ↗","Ouvrir en ligne ↗");
  $("guide-retry").textContent=say("Retry","Réessayer");
  filterGuides();
}
function status(text,error=false){$("guide-status").textContent=text;$("guide-status").hidden=!text;$("guide-retry").hidden=!error}
function filterGuides(){
  const query=$("guide-filter").value.toLocaleLowerCase();let visible=0;
  for(const button of $("guide-list").children){button.hidden=!button.textContent.toLocaleLowerCase().includes(query);if(!button.hidden)visible++}
  $("guide-empty").textContent=say("No matching guide","Aucun guide correspondant");
  $("guide-empty").hidden=visible>0||!guides.length;
}
function renderIndex(){
  $("guide-list").replaceChildren(...guides.map(guide=>{
    const button=document.createElement("button");button.textContent=guide.title;
    button.dataset.guidePath=guide.path;button.onclick=()=>openGuide(guide.path);
    button.setAttribute("aria-current",guide.path===current()?.path?"page":"false");return button;
  }));
  $("guide-language").value=guideLanguage;filterGuides();
}
async function loadIndex(language,navigationVersion=null){
  const version=++indexVersion;
  const rows=await documentationRequest("index",{language});
  if(version!==indexVersion||(navigationVersion!==null&&navigationVersion!==pageVersion))return false;
  guideLanguage=language;guides=rows;renderIndex();return true;
}
async function documentationApplyEnvironment(env){
  labels();if(!env.active)return;
  try{
    if(!guideLanguage){
      initializing ||= loadIndex(env.language||"en").finally(()=>{initializing=null});
      await initializing;
    }
    if(env!==documentationEnvironment)return;
    if(env.guide && env.navigation_revision!==navigationRevision){
      navigationRevision=env.navigation_revision;
      await openGuide(env.guide,env.fragment||"");
    }else if(!current() && !pageVersion && guides.length)await openGuide(guides[0].path);
  }catch(error){retry=()=>documentationApplyEnvironment(documentationEnvironment);status(say("Guides unavailable. ","Guides indisponibles. ")+TLToast.translate(error.message),true)}
}
async function imageSource(image,version){
  try{
    const result=await documentationRequest("image",{path:image.dataset.guideImage});
    if(version!==pageVersion||!image.isConnected)return;
    image.src=result.src;
    await image.decode().catch(()=>{});
  }catch{image.alt=image.alt||say("Image unavailable","Image indisponible")}
}
async function openGuide(path,fragment="",targetIndex=null){
  const version=++pageVersion;
  if(current())current().scroll=window.scrollY;
  retry=()=>openGuide(path,fragment,targetIndex);
  status(say("Loading guide…","Chargement du guide…"));
  try{
    const result=await documentationRequest("page",{path});
    if(version!==pageVersion)return;
    const language=path.split("/")[1];
    if(["en","fr"].includes(language)&&language!==guideLanguage){
      if(!await loadIndex(language,version)||version!==pageVersion)return;
    }
    if(targetIndex===null){
      if(current()?.path!==path||current()?.fragment!==fragment){entries.splice(entryIndex+1);entries.push({path,fragment,scroll:0});entryIndex=entries.length-1}
    }else entryIndex=targetIndex;
    const template=document.createElement("template");template.innerHTML=result.html;
    for(const image of template.content.querySelectorAll("img"))image.removeAttribute("src");
    $("guide-content").replaceChildren(template.content);
    $("guide-content").dataset.path=path;
    $("guide-back").disabled=entryIndex<=0;$("guide-forward").disabled=entryIndex>=entries.length-1;
    $("guide-online").href="https://github.com/Vietnoirien/TorrentLinker/blob/main/docs/"+path.split("/").map(encodeURIComponent).join("/");
    renderIndex();status("");
    if(targetIndex===null&&!fragment)window.scrollTo(0,0);
    await Promise.all([...$("guide-content").querySelectorAll("img[data-guide-image]")].map(image=>imageSource(image,version)));
    if(version!==pageVersion)return;
    if(targetIndex!==null)window.scrollTo(0,current().scroll);
    else if(fragment){let anchor=fragment;try{anchor=decodeURIComponent(fragment)}catch{}document.getElementById(anchor)?.scrollIntoView()}
  }catch(error){if(version===pageVersion)status(say("Guide unavailable. ","Guide indisponible. ")+TLToast.translate(error.message),true)}
}
function documentationInit(){
  $("guide-filter").oninput=filterGuides;
  $("guide-retry").onclick=()=>retry();
  $("guide-back").onclick=()=>{const index=entryIndex-1;if(entries[index])openGuide(entries[index].path,entries[index].fragment,index)};
  $("guide-forward").onclick=()=>{const index=entryIndex+1;if(entries[index])openGuide(entries[index].path,entries[index].fragment,index)};
  $("guide-language").onchange=async()=>{
    const language=$("guide-language").value,index=Math.max(0,guides.findIndex(g=>g.path===current()?.path));
    const version=++pageVersion;
    try{if(await loadIndex(language,version)&&version===pageVersion)await openGuide(guides[index]?.path||guides[0].path)}
    catch(error){if(version===pageVersion){retry=()=>$("guide-language").onchange();status(TLToast.translate(error.message),true)}}
  };
  document.addEventListener("click",event=>{
    const link=event.target.closest("a");if(!link)return;
    if(link.dataset.guide){event.preventDefault();openGuide(link.dataset.guide,link.hash.slice(1))}
    else if(documentationEnvironment.mode==="desktop"){
      event.preventDefault();documentationRequest("open-link",{url:link.href}).catch(error=>TLToast.error(error));
    }
  });
  labels();
}
