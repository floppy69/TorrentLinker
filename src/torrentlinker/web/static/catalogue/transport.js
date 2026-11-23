"use strict";
let catalogueRequest;
let catalogueEnvironment={language:"en",theme:"dark",catalogue:{cards:[]}};
window.addEventListener("catalogue-environment",event=>{
  catalogueEnvironment=event.detail;
  if(catalogueRequest)catalogueRender();
});
window.addEventListener("DOMContentLoaded",async()=>{
  catalogueInit();
  catalogueRequest=await TLPanel.connect("catalogue");
  window.catalogueReady();
});
