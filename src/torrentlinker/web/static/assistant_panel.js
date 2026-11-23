"use strict";
// The full workspace and Media side panel share one renderer and owner API transport.
function assistantHostFrame(id) {
  const frame=document.createElement("iframe");
  frame.id=id;frame.title="Assistant";frame.src="static/assistant/view.html";
  frame.style.cssText="width:100%;height:100%;min-height:240px;border:0;display:block;flex:1";
  return frame;
}
const assistantFrame=assistantHostFrame("assistant-frame");
const mediaAssistantFrame=assistantHostFrame("media-assistant-frame");
let assistantRevision=0, mediaAssistantRevision=0, assistantSelectionRevision=0;
let mediaChatConversation="", assistantRequestedConversation="";
async function loadAssistant() {
  if(!assistantFrame.isConnected)$("view-assistant").replaceChildren(assistantFrame);
  assistantRevision++;assistantEnvironment();
}
async function mountMediaAssistant(container, conversationId) {
  if(!mediaAssistantFrame.isConnected)container.replaceChildren(mediaAssistantFrame);
  mediaChatConversation=conversationId;mediaAssistantRevision++;assistantEnvironment();
}
function restoreMediaAssistant(){assistantEnvironment()}
function assistantEnvironment() {
  for(const [frame,compact] of [[assistantFrame,false],[mediaAssistantFrame,true]]){
    const active=frame.isConnected&&!$("workspace").hidden&&(compact?state.view==="media"&&media.chat:state.view==="assistant");
    if(active&&!compact)frame.style.height=`${Math.max(240,innerHeight-frame.getBoundingClientRect().top-20)}px`;
    frame.contentWindow?.postMessage({type:"assistant-environment",value:{mode:"web",active,compact,revision:compact?mediaAssistantRevision:assistantRevision,conversation_id:compact?mediaChatConversation:assistantRequestedConversation,selection_revision:assistantSelectionRevision,language,theme:document.documentElement.dataset.theme||"dark"}},location.origin);
  }
}
window.addEventListener("message",async event=>{
  if(event.origin!==location.origin)return;
  const frame=[assistantFrame,mediaAssistantFrame].find(frame=>frame.contentWindow===event.source);
  if(!frame)return;
  const compact=frame===mediaAssistantFrame, message=event.data;
  if(message?.type==="assistant-ready"){assistantEnvironment();return}
  if(message?.type!=="assistant-request")return;
  try {
    if($("workspace").hidden)throw Error("Sign in first.");
    let value;
    if(message.path==="media-chat"&&compact){
      await mediaOpenChat(message.body.conversation_id||"",!!message.body.new);value=null;
    }else if(message.path==="media-chat-close"&&compact){mediaCloseChat();value=null;
    }else if(message.path==="media-heartbeat"&&compact){await mediaHeartbeat(true);value=null;
    }else if(message.path==="open-assistant"&&compact){
      assistantRequestedConversation=mediaChatConversation;assistantSelectionRevision++;
      await navigate("assistant");value=null;
    }else if(message.path==="connections"){
      await navigate("setup","assistant");value=null;
    }else if(message.path==="preferences"){
      if(message.body.sidebar_width)localStorage.setItem("tl-assistant-sidebar-width",String(Math.max(180,Math.min(420,message.body.sidebar_width))));
      value={sidebar_width:Number(localStorage.getItem("tl-assistant-sidebar-width"))||240};
    }else if(message.path.startsWith("assistant/image?")){
      const response=await fetch(new URL("api/"+message.path,document.baseURI),{credentials:"same-origin"});
      if(!response.ok)throw Error("Image unavailable");
      const blob=await response.blob();
      value={data_url:await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob)})};
    }else{
      if(!/^(community-site\/items-[a-z-]+$|setup(?:\/assistant(?:\/|$)|$)|assistant\/|agents\/proposals\/|jobs\/)/.test(message.path))throw Error("Unknown Assistant panel operation");
      value=await api(message.path,message.body.body,message.body.method);
    }
    frame.contentWindow?.postMessage({type:"assistant-response",id:message.id,value},location.origin);
  }catch(error){frame.contentWindow?.postMessage({type:"assistant-response",id:message.id,error:error.message},location.origin)}
});
window.addEventListener("resize",assistantEnvironment);
document.addEventListener("tl-language-changed",assistantEnvironment);
new MutationObserver(assistantEnvironment).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
new MutationObserver(assistantEnvironment).observe($("view-assistant"),{attributes:true,attributeFilter:["hidden"]});
window.addEventListener("media-host-changed",assistantEnvironment);
