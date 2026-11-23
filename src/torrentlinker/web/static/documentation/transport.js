"use strict";
let documentationRequest;
let documentationEnvironment = {language:"en",theme:"dark",active:false};
window.addEventListener("documentation-environment", event=>{
  documentationEnvironment=event.detail;
  if(documentationRequest) documentationApplyEnvironment(event.detail);
});
window.addEventListener("DOMContentLoaded",async()=>{
  documentationInit();
  documentationRequest=await TLPanel.connect("documentation",{asynchronous:true});
  window.documentationReady();
});
