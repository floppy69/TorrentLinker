"use strict";
const documentationFrame=document.createElement("iframe");
documentationFrame.id="documentation-frame";documentationFrame.title="Documentation";
documentationFrame.src="static/documentation/view.html";
documentationFrame.style.cssText="width:100%;height:75vh;min-height:300px;border:0;display:block";
$("view-documentation").append(documentationFrame);
function loadGuides(){documentationEnvironment()}
function documentationEnvironment(){
  const active=state.view==="documentation"&&!$("workspace").hidden;
  if(active)documentationFrame.style.height=`${Math.max(300,innerHeight-documentationFrame.getBoundingClientRect().top-24)}px`;
  documentationFrame.contentWindow?.postMessage({type:"documentation-environment",value:{mode:"web",active,language,theme:document.documentElement.dataset.theme||"dark"}},location.origin);
}
window.addEventListener("message",async event=>{
  if(event.source!==documentationFrame.contentWindow||event.origin!==location.origin)return;
  const message=event.data;
  if(message?.type==="documentation-ready"){documentationEnvironment();return}
  if(message?.type!=="documentation-request")return;
  try{
    if($("workspace").hidden)throw Error("Sign in first.");
    const body=message.body||{},path=String(body.path||"");let value;
    if(message.path==="index")value=await api(`documentation?language=${body.language==="fr"?"fr":"en"}`);
    else if(message.path==="page" && /^(README\.md|guide\/(en|fr)\/[a-z0-9-]+\.md)$/.test(path)){
      value=await api("documentation/page/"+path.split("/").map(encodeURIComponent).join("/"));
    }else if(message.path==="image" && /^guide\/images\/[\w./-]+\.(png|jpe?g)$/i.test(path) && !path.split("/").some(part=>part===".."||part===".")){
      value={src:new URL("api/documentation/file/"+path.split("/").map(encodeURIComponent).join("/"),document.baseURI).href};
    }else throw Error("Unknown Documentation operation.");
    documentationFrame.contentWindow?.postMessage({type:"documentation-response",id:message.id,value},location.origin);
  }catch(error){documentationFrame.contentWindow?.postMessage({type:"documentation-response",id:message.id,error:error.message},location.origin)}
});
window.addEventListener("resize",documentationEnvironment);
document.addEventListener("tl-language-changed",documentationEnvironment);
new MutationObserver(documentationEnvironment).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
for(const node of [$("view-documentation"),$("workspace")])new MutationObserver(documentationEnvironment).observe(node,{attributes:true,attributeFilter:["hidden"]});
