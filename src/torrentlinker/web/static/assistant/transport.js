"use strict";
const $ = id => document.getElementById(id);
let state = {view: "assistant", language: "en", setup: {clients:[], client_id:""}};
const say = (en, fr) => state.language === "fr" ? fr : en;
let panelRequest;
function element(tag, text, cls) { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; }
function button(text, callback, cls) { const node=element("button",text,cls);node.type="button";node.onclick=()=>guard(callback,node);return node; }
const toast = text => TLToast.show(text, "ok");
// An action started by a button keeps that button busy until it ends.
async function guard(fn, node) { node ??= TLToast.trigger(); if(node)return TLToast.press(node,fn); try { return await fn(); } catch(error) { TLToast.error(error); } }
const api = (path, body, method) => panelRequest(path,{body, method:method || (body === undefined ? "GET" : "POST")});
const navigate = () => panelRequest("connections",{});
function bytes(value) {
  if(value == null)return "—";
  const units=["B","KiB","MiB","GiB","TiB","PiB"];
  let unit=0;
  while(value>=1024 && unit<units.length-1) { value/=1024;unit++; }
  return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}
let lastEnvironment="", pendingEnvironment="", lastSelection=-1, environmentVersion=0;
window.addEventListener("assistant-environment", async event => {
  const env=event.detail;
  state.mode=env.mode;state.view=env.active?"assistant":"";state.compact=!!env.compact;
  state.language=env.language||"en";
  document.documentElement.lang=state.language;
  document.documentElement.dataset.theme=env.theme||"dark";
  if(!panelRequest || !env.active)return;
  const root=$("view-assistant");
  if(env.error){
    const notice=element("p",env.error,"error");notice.setAttribute("role","alert");
    root.replaceChildren(notice);root.inert=false;lastEnvironment="";return;
  }
  const key=JSON.stringify([env.compact,env.language,env.theme,env.revision,env.conversation_id,env.selection_revision]);
  if(key===lastEnvironment || key===pendingEnvironment)return;
  const version=++environmentVersion;pendingEnvironment=key;root.inert=true;
  await guard(async()=>{
    try {
      const setup=await api("setup"), prefs=await panelRequest("preferences",{});
      if(version!==environmentVersion)return;
      state.setup=setup;
      document.documentElement.style.setProperty("--assistant-width",`${prefs.sidebar_width||240}px`);
      if(state.compact || env.selection_revision!==lastSelection && env.conversation_id){
        assistantView="chat";assistantConversation=env.conversation_id||"";assistantRun="";
      }
      lastSelection=env.selection_revision;
      await loadAssistant();
      if(version===environmentVersion){lastEnvironment=key;root.inert=false;if(state.compact && assistantVisible())$("assistant-prompt")?.focus()}
    }finally{
      if(version===environmentVersion){pendingEnvironment="";root.inert=false}
    }
  });
});
window.addEventListener("DOMContentLoaded",()=>{
  TLPanel.connect("assistant",{asynchronous:true}).then(request=>{panelRequest=request;window.assistantReady();});
});

async function loadPanelImage(image, source) {
  image.removeAttribute("src");
  try {
    if(source?.startsWith("data:image/")) { image.src=source;return; }
    if(!source?.startsWith("api/assistant/image?"))throw Error("Invalid image source");
    const result=await api(source.slice(4));
    image.src=result.data_url;
  } catch { image.dispatchEvent(new Event("error")); }
}

document.addEventListener("click",event=>{
  const link=event.target.closest("a");
  if(!link || state.mode!=="desktop")return;
  event.preventDefault();
  guard(()=>panelRequest("open-link",{url:link.getAttribute("href")}));
});
let sidebarObserver;
function rememberSidebar(side) {
  sidebarObserver?.disconnect();
  let timer;
  sidebarObserver=new ResizeObserver(()=>{
    if(innerWidth<=1050 || !side.isConnected || !side.getClientRects().length)return;
    const width=Math.round(side.getBoundingClientRect().width);
    document.documentElement.style.setProperty("--assistant-width",`${width}px`);
    clearTimeout(timer);
    timer=setTimeout(()=>guard(()=>panelRequest("preferences",{sidebar_width:width})),250);
  });
  sidebarObserver.observe(side);
}
