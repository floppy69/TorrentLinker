"""Fragment routing survives authentication and preserves browser history."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_fragment_navigation_and_subtabs():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    static = Path("src/torrentlinker/web/static")
    app = (static / "app.js").read_text()
    routing = app[app.index("async function settingsSection(") : app.index("async function job(")]
    enter = app[app.index("async function enter()") : app.index('$("library-check-all")')]
    library = (static / "library.js").read_text()
    library = library[
        library.index("async function libraryTab(") : library.index(
            "async function browseLibraryFolder("
        )
    ]
    zen = (static / "zen.js").read_text()
    zen = zen[zen.index("function zenTab(") : zen.index("for (const name of")]
    script = r"""
const assert = require('node:assert/strict');
const nodes = new Map();
const $ = id => {
  if (!nodes.has(id)) nodes.set(id, {hidden:false, classList:{toggle(){}}, setAttribute(){}});
  return nodes.get(id);
};
const document = {querySelectorAll:()=>[],
  querySelector:selector=>selector===".library-nav"?$("library-nav"):null,
  body:{classList:{contains:()=>false,toggle(){}}}};
const state = {view:'torrents', setup:{configured:true, indexer_configured:true}};
const media = {kind:'video', view:'recent'};
const loaded = []; const reseedUI = {tab:'reseed'};
function clearAgentToken() {}
function step() {}
async function refreshSetup() {}
async function loadAgents() { loaded.push('agents'); }
async function loadAssistantConnections() {}
async function loadZenProfile() {}
async function loadAssistant() { loaded.push('assistant'); }
async function loadMedia() { loaded.push('media'); }
function mediaViews() {
  rememberTab('media',media.kind,media.view===(media.kind==='music'?'albums':'recent')?undefined:media.view);
}
function mediaAutoScan() {}
async function loadGuides() { loaded.push('documentation'); }
async function loadTorrents() { loaded.push('torrents'); }
async function loadQueue() { loaded.push('queue'); }
async function loadFeeds() { loaded.push('feeds'); }
async function loadUploadQueue() { loaded.push('upload/local'); }
async function loadRemoteUploads() { loaded.push('upload/remote'); }
async function loadUploadSources() { loaded.push('upload/sources'); }
function showUploadView(tab) { rememberTab('upload', tab); }
async function loadLibrary() { loaded.push('library/items'); }
async function loadReseed() { loaded.push('library/'+reseedUI.tab); }
async function loadJobs() { loaded.push('jobs'); }
async function loadZenSeeding() {}
async function loadZenPlan() {}
function showCatalogue() {}
async function loadSearchPage() { loaded.push('search'); }
async function api() { return {}; }
async function job() {}
async function pollJobs() {}
const guard = fn => fn();
let listener;
const window = {addEventListener:(name,fn)=>{assert.equal(name,'hashchange');listener=fn;}};
// Model browser history, including asynchronous hashchange delivery.
let entries=['https://example.test/torrentlinker/?source=bookmark'], index=0;
const events=[];
const location = {
 get href(){return entries[index];},
 get hash(){return new URL(this.href).hash;},
 set hash(hash){
   const url=new URL(this.href); url.hash=hash;
   if(url.href===this.href)return;
   entries.splice(index+1);entries.push(url.href);index++;events.push(listener);
 }
};
const history = {
 replaceState(_a,_b,hash){const url=new URL(location.href);url.hash=hash;entries[index]=url.href;},
 back(){if(index){index--;events.push(listener);}},
 forward(){if(index<entries.length-1){index++;events.push(listener);}}
};
async function settle(){while(events.length)await events.shift()();}
eval(process.argv[1] + process.argv[2] + process.argv[3] + process.argv[4] + `
(async()=>{
  // Initial deep link stays untouched while signed out, including Back/Forward.
  $('workspace').hidden=true;
  location.hash='#/library/activity';await settle();
  assert.equal(loaded.length,0);
  await enter(); await settle();
  assert.equal(state.view,'library');assert.equal($('library-activity').hidden,false);
  assert.equal(location.hash,'#/library/activity');
  assert.match(location.href,/\\/torrentlinker\\/\\?source=bookmark#/);
  // Reload or proxy authentication both use enter(), without adding history entries.
  for(const mode of ['password','proxy']){
    state.setup.web_auth=mode;const count=entries.length;
    await enter();await settle();assert.equal(entries.length,count);
    assert.equal($('logout').hidden,mode==='proxy');
    assert.equal($('library-activity').hidden,false);
  }
  const count=entries.length;
  const queueLoads=loaded.filter(value=>value==='queue').length;
  await navigate('queue');await settle();assert.equal(entries.length,count+1);
  assert.equal(loaded.filter(value=>value==='queue').length,queueLoads+1);
  history.back();await settle();assert.equal(state.view,'library');
  history.forward();await settle();assert.equal(state.view,'queue');
  await navigate('library');await libraryTab('folders');await settle();
  history.back();await settle();assert.equal(reseedUI.tab,'activity');
  history.forward();await settle();assert.equal($('library-reseed').hidden,false);
  assert.equal(reseedUI.tab,'folders');
  // Every top-level location and supported tab can be reopened from the URL.
  for(const [view,tabs] of Object.entries(viewTabs)){
    for(const tab of tabs.length?tabs:[undefined]){
      const parts=[view,...(tab?[tab]:[])];
      location.hash=routeFragment(parts);await settle();
      await enter();await settle();
      assert.equal(state.view,view);assert.equal(location.hash,routeFragment(parts));
    }
  }
  for(const [kind,views] of Object.entries(mediaViewsByKind)){
    for(const view of views.filter(value=>value!=='adult')){
      await navigate('media',kind,view);await settle();
      const hash=location.hash;
      await enter();await settle();
      assert.equal(media.kind,kind);assert.equal(media.view,view);assert.equal(location.hash,hash);
    }
  }
  location.hash='#/media/video/adult';await settle();
  assert.equal(state.view,'torrents');
  await navigate('setup','agents','activity');await settle();
  assert.equal(location.hash,'#/setup/agents/activity');
  await enter();await settle();assert.equal(location.hash,'#/setup/agents/activity');
  history.back();await settle();history.forward();await settle();
  assert.equal(state.settingsSection,'agents');
  // Unknown, malformed and unavailable locations replace the bad entry with the default.
  for(const hash of ['', '#bad', '#/missing', '#/constructor', '#/torrents/extra',
      '#/library/invalid', '#/setup/agents/invalid', '#/zen/profile/extra/more', '#/%E0%A4%A']){
    location.hash=hash;await settle();
    assert.equal(state.view,'torrents');assert.equal(location.hash,'#/torrents');
    await enter();await settle();
    assert.equal(state.view,'torrents');assert.equal(location.hash,'#/torrents');
  }
  state.setup.configured=false;
  location.hash='';await settle();await enter();await settle();
  assert.equal(state.view,'setup');assert.equal(location.hash,'#/setup/connections');
  // Setup is the default, not a navigation gate. Users can configure an Assistant
  // or review saved Upload drafts before connecting a Torrent Client.
  for(const [view,tab,loader] of [
    ['assistant',undefined,'assistant'], ['upload','local','upload/local'],
    ['library','activity','library/activity'],
  ]){
    const count=loaded.filter(value=>value===loader).length;
    await navigate(view,tab);await settle();
    assert.equal(state.view,view);
    assert.equal(loaded.filter(value=>value===loader).length,count+1);
    const hash=location.hash;
    await enter();await settle();assert.equal(state.view,view);assert.equal(location.hash,hash);
  }
  // A stale setup response cannot overwrite a newer navigation.
  state.setup.configured=true;
  let finish;
  refreshSetup=()=>new Promise(resolve=>{finish=resolve;});
  const pending=navigate('setup','agents');
  await navigate('jobs');finish();await pending;await settle();
  assert.equal(state.view,'jobs');assert.equal(location.hash,'#/jobs');
})().catch(error=>{console.error(error);process.exitCode=1;});
`);
"""
    subprocess.run(
        [node, "-e", script, routing, enter, library, zen],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
