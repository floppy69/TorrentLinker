"use strict";
// Library navigation delegates to the shared Reseed panel.
const libraryUI={item:null,candidate:null,generation:0,client:null};
function resetLibraryReview(){
  if(libraryUI.client===state.clientId)return;
  libraryUI.client=state.clientId;libraryUI.item=null;libraryUI.candidate=null;libraryUI.generation++;
}
async function loadLibrary(){resetLibraryReview();await loadReseed();}
async function libraryTab(tab){
  resetLibraryReview();
  tab=["cross","folders","activity"].includes(tab)?tab:"reseed";
  rememberTab("library",tab);$("library-reseed").hidden=false;
  reseedUI.tab=tab;await loadReseed();
}
