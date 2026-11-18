"use strict";
const libraryUI = {folder:"", selected:new Set(), item:null, candidates:[], chosen:new Map(), candidate:null, client:null, generation:0, loadGeneration:0, detailGeneration:0, tab:"summary"};
const libraryMatch = value => ({full:say("Full Match","Correspondance complète"),partial:say("Partial Match","Correspondance partielle"),none:say("No Match","Aucune correspondance"),unchecked:say("Not checked","Non vérifié")}[value] || value);

async function loadLibrary() {
  if (libraryUI.client !== state.clientId) {
    libraryUI.client = state.clientId;
    libraryUI.selected.clear(); libraryUI.chosen.clear(); libraryUI.item = null;
    libraryUI.candidate = null; libraryUI.generation++; libraryUI.detailGeneration++;
    $("candidates").hidden = true; $("library-results").hidden = false;
    $("library-items").classList.remove("library-expanded");
  }
  const generation = ++libraryUI.loadGeneration;
  const params = new URLSearchParams({q:$("library-query").value, offset:state.libraryOffset, folder:libraryUI.folder, state:$("library-state").value});
  const response = await api(`library?${params}`);
  if (generation !== libraryUI.loadGeneration) return;
  table("library-table", response.rows, [
    {label:say("Local Item","Élément local"), name:true, render:r=>button(r.within?`${r.within.split(/[\\/]/).pop()} › ${r.name}`:r.name,()=>reviewLibraryItem(r))},
    {label:say("State","État"),render:r=>({orphan:say("Orphan","Orphelin"),seeded:say("Seeded","Seedé"),"partially-seeded":say("Partially seeded","Partiellement seedé"),unknown:say("Seeding status unknown","État du seed inconnu")}[r.state] || r.state)},
    {label:say("Size","Taille"),render:r=>bytes(r.size)},
    {label:say("Folder","Dossier"),render:r=>{const path=element("span",r.folder,"library-folder-path");path.title=r.folder;return path;}},
    {label:"",render:r=>button(say("Find candidates","Chercher des candidats"),()=>check(r))},
    {label:"Upload",render:r=>button(say("Prepare","Préparer"),()=>prepareUpload(r))},
  ], libraryUI.selected, "path", updateLibrarySelection);
  $("library-count").textContent = `${response.total} · ${Math.floor(state.libraryOffset/100)+1}`;
  $("library-prev").disabled = !state.libraryOffset;
  $("library-next").disabled = state.libraryOffset+100 >= response.total;
  updateLibrarySelection();
  libraryUI.folderCounts=response.folder_counts; libraryUI.folderErrors=response.folder_errors;
  renderLibraryFolders();
}
function updateLibrarySelection() {
  $("library-selection-count").textContent = say(`${libraryUI.selected.size} selected`,`${libraryUI.selected.size} sélectionné(s)`);
  $("library-combine").disabled = libraryUI.selected.size < 2;
  $("library-search-selected").disabled = !libraryUI.selected.size;
}
function renderLibraryFolders() {
  const folders = state.setup?.folders || [];
  if (libraryUI.folder && !folders.some(f=>f.local===libraryUI.folder)) libraryUI.folder="";
  const rail = $("library-folders"); rail.replaceChildren();
  for (const f of [{local:"",label:say("All folders","Tous les dossiers")},...folders]) {
    const b = button(f.label || f.local.split(/[\\/]/).filter(Boolean).pop() || f.local, async()=>{
      libraryUI.folder=f.local; state.libraryOffset=0; await loadLibrary();
    });
    const count=f.local?libraryUI.folderCounts?.[f.local]:Object.values(libraryUI.folderCounts || {}).reduce((a,b)=>a+b,0);
    if(count !== undefined) b.textContent+=` · ${count}`;
    if((libraryUI.folderErrors || []).some(path=>path===f.local || path.startsWith(f.local+"/"))) b.textContent+=say(" · Incomplete scan"," · Analyse incomplète");
    b.title=f.local; b.setAttribute("aria-pressed",String(libraryUI.folder===f.local)); rail.append(b);
  }
}

async function libraryTab(tab) {
  tab = tab || "reseed";
  const shared = ["reseed", "folders", "activity"].includes(tab);
  document.querySelector(".library-nav").hidden = shared;
  rememberTab("library", tab);
  $("library-items").hidden = shared;
  $("library-reseed").hidden = !shared;
  if (shared) { reseedUI.tab = tab; await loadReseed(); }
  else await loadLibrary();
}

async function browseLibraryFolder(path="",target="library-folder-path") {
  const result=await api(`folders?path=${encodeURIComponent(path)}`);
  const host=$("dialog-content");host.replaceChildren(element("h2",say("Folders on the TorrentLinker server","Dossiers du serveur TorrentLinker")),element("p",result.path || say("Mounted roots","Racines montées")));
  if(result.path) {
    host.append(button(say("Use this folder","Utiliser ce dossier"),()=>{$(target).value=result.path;$("dialog").close();},"primary"));
    host.append(button("↑",()=>browseLibraryFolder(result.parent,target)));
  }
  for(const folder of result.folders) host.append(button(folder,()=>browseLibraryFolder(folder,target),"directory-button"));
  if(!result.path && !result.folders.length) host.append(element("p",say("No mounted roots. Set TL_STORAGE_ROOTS on the TorrentLinker server.","Aucune racine montée. Configurez TL_STORAGE_ROOTS sur le serveur.")));
  if(!$("dialog").open) $("dialog").showModal();
}
async function reviewLibraryItem(row, search=false) {
  $("evidence-report").replaceChildren();
  libraryUI.item=row; libraryUI.candidate=null; libraryUI.candidates=[];
  const generation=++libraryUI.generation;
  libraryUI.detailGeneration++;
  $("candidates").hidden=false; $("library-empty-review").hidden=true;
  $("candidate-title").textContent=`${row.name} · ${bytes(row.size)} · ${row.folder}`;
  $("candidate-table").replaceChildren(element("p",say("Loading Candidates…","Chargement des candidats…")));
  $("candidate-actions").replaceChildren();
  $("candidate-summary").replaceChildren(); $("candidate-files").replaceChildren();
  $("candidate-description").replaceChildren(); $("candidate-nfo").textContent="";
  await job({kind:search?"check":"library-review",path:row.path}, rows=>{
    if(generation!==libraryUI.generation) return;
    showLibraryCandidates(rows);
  });
}
async function check(row) { return reviewLibraryItem(row,true); }
function showLibraryCandidates(rows) {
  libraryUI.candidates=rows;
  const wanted=libraryUI.chosen.get(libraryUI.item.path);
  libraryUI.candidate=rows.find(c=>c.key===wanted) || rows[0] || null;
  renderCandidateChoices();
  showLibraryCandidate(libraryUI.candidate);
}
function renderCandidateChoices() {
  const host=$("candidate-table");host.replaceChildren();
  if(!libraryUI.candidates.length) host.append(element("p",say("No Candidates. Search this item to find matching torrents.","Aucun candidat. Lancez une recherche pour cet élément.")));
  for(const c of libraryUI.candidates) {
    const b=button(c.title,()=>{libraryUI.candidate=c;renderCandidateChoices();showLibraryCandidate(c);},"candidate-choice");
    b.append(element("small",`${libraryMatch(c.match)} · ${bytes(c.size)} · ${c.seeders} seeders${c.archive?" · Archive":""}`));
    b.setAttribute("aria-pressed",String(c===libraryUI.candidate));host.append(b);
  }
}
function showLibraryCandidate(candidate) {
  libraryUI.detailGeneration++;
  $("candidate-actions").replaceChildren(); $("candidate-files").replaceChildren();
  $("candidate-description").replaceChildren(); $("candidate-nfo").textContent="";
  $("candidate-summary").replaceChildren();
  if(!candidate) return;
  libraryUI.chosen.set(libraryUI.item.path,candidate.key);
  $("candidate-summary").append(element("h3",candidate.title),element("p",`${libraryMatch(candidate.match)} · ${bytes(candidate.size)} · ${candidate.seeders} seeders`),element("p",libraryUI.item.path),element("p",say("A Match compares file names and sizes. Your Torrent Client verifies the hashes before seeding.","La correspondance compare les noms et tailles. Le client torrent vérifie les hashes avant le seed."),"muted"));
  table("candidate-files",candidate.files,[{label:say("Torrent file","Fichier du torrent"),render:f=>f.torrent},{label:say("Local file","Fichier local"),render:f=>f.local || "—"},{label:say("Result","Résultat"),render:f=>f.status}],null);
  if(candidate.evidence?.discovery === "layout") $("candidate-summary").append(element("p",say("Found among the torrents already downloaded, by the sizes of your files, without spending a search.","Trouvé parmi les torrents déjà téléchargés, par la taille de vos fichiers, sans consommer de recherche.")));
  if(candidate.evidence?.discovery === "compatible") $("candidate-summary").append(element("p",say("Discovery scope: ","Périmètre de recherche : ") + candidate.evidence.scope + (candidate.evidence.limited === "true" ? say(" · Search limit reached; results are incomplete."," · Limite atteinte ; résultats incomplets.") : "")));
  const actions=$("candidate-actions");
  const checkButton=button(say("Check Candidate","Vérifier le candidat"),()=>candidateAction("check-candidate"));
  checkButton.disabled=candidate.match!=="unchecked";
  actions.append(checkButton,button(say("Reject Candidate","Rejeter le candidat"),()=>candidateAction("library-reject")));
  const reseed=button(candidate.archive?say("Unpack and reseed…","Extraire et seeder…"):say("Verify & reseed","Vérifier et seeder"),async()=>{
    if(candidate.archive) {await previewArchive(candidate);return;}
    const path=libraryUI.item.path, hash=candidate.hash;
    if(!confirm(say(`Verify and reseed ${candidate.title}? Missing files will not be downloaded. Check the Files tab for renamed paths.`,`Vérifier et remettre en seed ${candidate.title} ? Les fichiers manquants ne seront pas téléchargés.`))) return;
    await job({kind:"reseed",path,hashes:[hash]},()=>toast(say("Verification started.","Vérification lancée.")));
  },"primary");
  reseed.disabled=!(candidate.archive?candidate.key:candidate.hash) || !["full","partial"].includes(candidate.match);
  actions.append(reseed);
  actions.append(button(say("Diagnose repair…","Diagnostiquer une réparation…"),()=>guard(async()=>{
    const item=libraryUI.item,generation=libraryUI.generation;
    await job({kind:"diagnose-repair",path:item.path,candidate_key:candidate.key},r=>{
      if(generation===libraryUI.generation){candidateTab("evidence");renderEvidence({repairs:[r]});}
    });
  })));
  if(candidate.archive) $("candidate-summary").append(element("p",say("Review the extraction destination and available server space before unpacking and reseeding.","Examinez la destination et l’espace disponible sur le serveur avant d’extraire et de seeder.")));
  if(candidate.website) {const link=element("a",say("Open on website","Ouvrir sur le site"));link.href=candidate.website;link.target="_blank";link.rel="noopener noreferrer";actions.append(link);}
  candidateTab(libraryUI.tab);
}
async function candidateAction(kind) {
  const item=libraryUI.item, candidate=libraryUI.candidate, generation=libraryUI.generation;
  if(!item || !candidate) return;
  await job({kind,path:item.path,candidate_key:candidate.key},rows=>{if(generation===libraryUI.generation) showLibraryCandidates(rows);});
}
function candidateTab(tab) {
  libraryUI.tab=tab;
  document.querySelectorAll("[data-candidate-tab]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.candidateTab===tab)));
  for(const name of ["summary","files","description","nfo","evidence"]) $("candidate-"+name).hidden=name!==tab;
  if(["description","nfo"].includes(tab)) guard(loadLibraryDetails);
}
async function loadLibraryDetails() {
  const candidate=libraryUI.candidate, generation=libraryUI.detailGeneration;
  if(!candidate) return;
  if(!candidate.hash) {$("candidate-description").textContent=$("candidate-nfo").textContent=say("Open the Indexer website for these details.","Consultez ces détails sur le site de l’indexeur.");return;}
  if(candidate.details) {renderLibraryDetails(candidate.details);return;}
  if(candidate.loading) return;
  candidate.loading=true;
  $("candidate-description").textContent=$("candidate-nfo").textContent=say("Loading…","Chargement…");
  try {
    await job({kind:"details",hashes:[candidate.hash]},result=>{
      candidate.loading=false;candidate.details=result;
      if(generation===libraryUI.detailGeneration) renderLibraryDetails(result);
    }, error=>{candidate.loading=false;if(generation===libraryUI.detailGeneration) $("candidate-description").textContent=$("candidate-nfo").textContent=error;});
  } catch(error) {candidate.loading=false;throw error;}
}
function renderLibraryDetails(result) {
  // Same server-sanitized preview_html renderer used by Search.
  $("candidate-description").innerHTML=result.description || say("No description supplied.","Aucune description.");
  $("candidate-description").querySelectorAll("a").forEach(a=>{a.target="_blank";a.rel="noopener noreferrer";});
  $("candidate-nfo").textContent=result.nfo || say("No NFO supplied.","Aucun NFO.");
}
async function searchLibrary(selected) {
  const paths=selected?[...libraryUI.selected]:[];
  const generation=libraryUI.generation;
  await job({kind:"search-library",paths},result=>{
    toast(say(`Searched ${result.results.length} items. ${result.errors.length} errors.`,`${result.results.length} éléments cherchés. ${result.errors.length} erreurs.`));
    if(generation===libraryUI.generation && libraryUI.item) {
      const found=result.results.find(r=>r.path===libraryUI.item.path);if(found) showLibraryCandidates(found.rows);
    }
  });
}
for(const b of document.querySelectorAll("[data-library-tab]")) b.onclick=()=>guard(()=>libraryTab(b.dataset.libraryTab));
for(const b of document.querySelectorAll("[data-candidate-tab]")) b.onclick=()=>candidateTab(b.dataset.candidateTab);
$("library-manage-folders").onclick=()=>guard(()=>libraryTab("folders"));
$("library-state").onchange=()=>{state.libraryOffset=0;guard(loadLibrary);};
$("library-search-selected").onclick=()=>guard(()=>searchLibrary(true));
$("library-search-all").onclick=()=>guard(()=>searchLibrary(false));
$("candidate-search").onclick=()=>guard(()=>libraryUI.item && check(libraryUI.item));
$("candidate-expand").onclick=()=>{
  const expanded=!$("library-results").hidden;
  $("library-results").hidden=expanded;$("library-items").classList.toggle("library-expanded",expanded);
  $("candidate-expand").textContent=expanded?say("Back to Local Items","Retour aux éléments"):say("Expand review","Agrandir");
};

$("settings-library-folders").onclick=()=>guard(()=>navigate("library", "folders"));

function renderLibraryDownloads() {
  const folders=state.setup.download_folders || {default:"",by_category:{},effective:{}};
  const categories=state.setup.indexer_categories || {};
  const select=$("library-download-category"), current=select.value;
  select.replaceChildren(new Option(say("Default","Par défaut"),""));
  for(const row of categoryRows(categories)) select.add(new Option(row.path,row.id));
  select.value=current;
  select.parentElement.querySelector(".category-picker")?.remove();
  select.after(categoryPicker(select,categories));
  const sequential=$("library-sequential-video");sequential.checked=!!state.setup.sequential_video;
  sequential.onchange=()=>guard(async()=>{await api("setup/sequential-video",{enabled:sequential.checked});await refreshSetup();});
  const adult=$("library-adult-content");adult.checked=!!state.setup.adult_content;
  adult.onchange=()=>guard(async()=>{await api("setup/adult-content",{enabled:adult.checked});await refreshSetup();});
  const host=$("library-download-destinations");host.replaceChildren();
  for(const [id,path] of [["",folders.default],...Object.entries(folders.by_category)]) {
    const row=element("div",undefined,"library-folder-row");
    row.append(element("span",`${id?(categoryRows(categories).find(row=>row.id===id)?.path || id):say("Default","Par défaut")} · ${path || say("Not set","Non configuré")}`));
    row.append(button(say("Edit","Modifier"),()=>{select.value=id;select.dispatchEvent(new Event("change"));$("library-download-path").value=path;}));
    if(path) row.append(button(id?say("Use inherited destination","Utiliser la destination héritée"):say("Clear default","Retirer le dossier par défaut"),async()=>{
      await api("setup/remove-folder",{purpose:"download",local:path,category:id?Number(id):null});await refreshSetup();
    }));
    host.append(row);
  }
  select.onchange=()=>{
    $("library-download-path").value=select.value?folders.by_category[select.value] || "":folders.default;
    $("library-download-feedback").textContent=say("Effective destination: ","Destination effective : ")+(select.value?folders.effective[select.value]:folders.default || "—");
  };
}
$("library-download-form").onsubmit=e=>{e.preventDefault();guard(async()=>{
  const category=$("library-download-category").value;
  await job({kind:"configure-download-folder",path:$("library-download-path").value.trim(),category:category?Number(category):null},async()=>{
    await refreshSetup();$("library-download-feedback").textContent=say("Destination verified and saved.","Destination vérifiée et enregistrée.");
  });
});};

$("scan").onclick=()=>guard(()=>job({kind:"scan"},async result=>{
  libraryUI.generation++; libraryUI.detailGeneration++;libraryUI.item=null;libraryUI.candidate=null;
  $("candidates").hidden=true;$("library-empty-review").hidden=false;
  $("library-results").hidden=false;$("library-items").classList.remove("library-expanded");
  $("candidate-expand").textContent=say("Expand review","Agrandir");
  await loadLibrary();
  if(result.client_unavailable) toast(say("Files scanned. The Torrent Client is unavailable, so seeding status is unknown.","Fichiers analysés. Le client torrent est indisponible : état du seed inconnu."));
}));


async function previewArchive(candidate) {
  const body={path:libraryUI.item.path,candidate_key:candidate.key,client_id:state.clientId};
  const generation=libraryUI.generation;
  await job({kind:"preview-unpack",...body},preview=>{
    if(generation!==libraryUI.generation || libraryUI.candidate?.key!==candidate.key) return;
    const content=$("dialog-content"), dialog=$("dialog");
    content.replaceChildren(element("h2",say("Unpack and reseed","Extraire et seeder")),
      element("h3",preview.title),
      element("p",say("Extraction happens on the TorrentLinker server. The original archive is kept. Nothing is overwritten.","L’extraction a lieu sur le serveur TorrentLinker. L’archive originale est conservée. Aucun fichier n’est écrasé.")),
      element("p",say("Archive: ","Archive : ")+preview.archive,"archive-path"),
      element("p",say("Destination: ","Destination : ")+preview.destination,"archive-path"),
      element("p",say(`${preview.files} files · ${bytes(preview.size)} to unpack · ${bytes(preview.free)} available`,`${preview.files} fichiers · ${bytes(preview.size)} à extraire · ${bytes(preview.free)} disponibles`)),
      element("p",preview.match==="partial"?say(`Partial Match: ${preview.missing} missing files. Missing files will not be downloaded; after verification the torrent seeds the pieces you have, with every file skipped.`,`Correspondance partielle : ${preview.missing} fichiers manquants. Ils ne seront pas téléchargés ; après vérification, le torrent partage les pièces que vous avez, tous ses fichiers étant ignorés.`):say("The Torrent Client will verify the extracted files before seeding.","Le client torrent vérifiera les fichiers extraits avant le seed.")));
    const cancel=button(say("Cancel","Annuler"),()=>dialog.close(),"quiet");
    const approve=button(say("Unpack and reseed","Extraire et seeder"),async()=>{
      if(body.client_id!==state.clientId) {dialog.close();return;}
      approve.disabled=true;cancel.disabled=true;
      const status=element("p",say("Waiting to extract…","En attente d’extraction…"));
      status.setAttribute("role","status");
      const meter=element("progress");meter.max=preview.size;meter.value=0;
      content.append(status,meter);
      let identifier, canCancel=true;
      const showProgress=p=>{
        if(!p) return;
        meter.value=p.done;meter.max=p.total;
        canCancel=p.cancellable!==false;
        if(!canCancel) {cancel.disabled=true;status.textContent=say("Starting verification…","Démarrage de la vérification…");return;}
        status.textContent=say(`Extracting ${bytes(p.done)} / ${bytes(p.total)}`,`Extraction ${bytes(p.done)} / ${bytes(p.total)}`);
      };
      const finish=message=>{status.textContent=message;cancel.textContent=say("Close","Fermer");cancel.disabled=false;cancel.onclick=()=>dialog.close();};
      try {
        identifier=await job({kind:"unpack-reseed",...body,confirmation:preview.token},()=>{
          meter.value=preview.size;
          finish(say("Verification started. The original archive has been kept. Follow verification in Torrents.","Vérification lancée. L’archive originale est conservée. Suivez la vérification dans Torrents."));
          content.append(button(say("Open in Torrents","Ouvrir dans Torrents"),async()=>{dialog.close();await navigate("torrents");}));
          guard(()=>job({kind:"scan",client_id:body.client_id},loadLibrary));
        },error=>finish(error || say("Extraction cancelled. The original archive has been kept.","Extraction annulée. L’archive originale est conservée.")),showProgress);
        // A short extraction can complete during job()'s initial poll.
        if(state.jobs.has(identifier)) {
          cancel.disabled=!canCancel;cancel.textContent=say("Cancel extraction","Annuler l’extraction");
          cancel.onclick=()=>guard(async()=>{cancel.disabled=true;await api(`jobs/${identifier}/cancel`,{});status.textContent=say("Cancelling…","Annulation…");});
        }
      } catch(error) {finish(error.message);}
    },"primary");
    content.append(cancel,approve);dialog.showModal();cancel.focus();
  });
}

function renderEvidence(result) {
  const host=$("evidence-report");host.replaceChildren();
  if(result.observations?.length) {
    const grid=element("table"),head=element("tr");
    for(const label of [say("File / source","Fichier / source"),say("Claim","Déclaration"),say("Observed","Observé"),say("Confidence","Confiance")])head.append(element("th",label));
    grid.append(head);
    for(const row of result.observations){const tr=element("tr");for(const cell of [`${row.file} · ${evidenceLabel(row.source)} · ${evidenceLabel(row.field)}`,row.claim,row.observed,evidenceLabel(row.confidence)])tr.append(element("td",cell));grid.append(tr);}
    host.append(grid);
  }
  for(const file of result.unreadable || []) host.append(element("p",say("MediaInfo unavailable: ","MediaInfo indisponible : ")+file));
  for(const row of result.provenance || []) {
    host.append(element("h4",`${row.name} · ${evidenceLabel(row.status)}`),element("p",`${bytes(row.verified_bytes)} / ${bytes(row.target_bytes)}`));
    for(const f of row.files) host.append(element("p",`${f.original} → ${f.local || f.candidates.join(", ")}`));
  }
  for(const repair of result.repairs || []) renderRepair(host,repair);
  if(!host.childNodes.length) host.append(element("p",say("No inconsistencies reported. This does not certify the release origin.","Aucune incohérence signalée. Cela ne certifie pas l’origine de la release.")));
}
$("inspect-evidence").onclick=()=>guard(async()=>{
  const item=libraryUI.item,generation=libraryUI.generation;if(!item)return;
  await job({kind:"library-evidence",path:item.path},r=>{if(generation===libraryUI.generation)renderEvidence(r);});
});
$("import-provenance").onchange=()=>guard(async()=>{
  const input=$("import-provenance"),item=libraryUI.item,generation=libraryUI.generation;
  const files=Array.from(input.files);input.value="";if(!item)return;
  if(files.length>100)throw Error(say("Import at most 100 torrents at a time.","Importez au maximum 100 torrents à la fois."));
  const rows=[];
  for(const file of files){
    if(file.size>8*1024*1024)throw Error(say("Torrent exceeds 8 MiB.","Le torrent dépasse 8 Mio."));
    const data=new Uint8Array(await file.arrayBuffer());let binary="";
    for(let i=0;i<data.length;i+=32768)binary+=String.fromCharCode(...data.subarray(i,i+32768));
    await job({kind:"import-provenance",path:item.path,torrent_data:btoa(binary)},r=>{
      rows.push(r);if(generation===libraryUI.generation)renderEvidence({provenance:rows});
    });
  }
});

$("candidate-compatible").onclick=()=>guard(async()=>{
  const item=libraryUI.item,generation=libraryUI.generation;if(!item)return;
  await job({kind:"find-compatible",path:item.path},rows=>{if(generation===libraryUI.generation)showLibraryCandidates(rows);});
});

function renderRepair(host,row) {
  const card=element("section");host.append(card);
  card.append(element("h4",`${row.name} · ${evidenceLabel(row.status)}`),element("p",say("Original retained: ","Original conservé : ")+row.source),element("p",`${bytes(row.verified_bytes)} / ${bytes(row.target_bytes)} · ${say("Missing payload","Contenu manquant")} ${bytes(row.missing_bytes)}`),element("p",say("Experimental: single-file v1 torrents, 1% / 50 MiB size difference, at least 90% verified, at most 500 MiB missing and 2 advertised seeders. Source/team claims remain unverified.","Expérimental : torrents v1 d’un fichier, écart de 1 % / 50 Mio, au moins 90 % vérifiés, au plus 500 Mio manquants et 2 seeders annoncés. Les déclarations de source/team restent à vérifier.")));
  if(row.copy)card.append(element("p",row.copy));
  const update=r=>{card.remove();renderRepair(host,r);};
  if(row.eligible && row.status==="awaiting-confirmation"){
    const label=element("label",say("Server folder for the copy","Dossier du serveur pour la copie")),input=element("input");label.append(input);card.append(label);
    const optLabel=element("label"),opt=element("input");opt.type="checkbox";
    optLabel.append(opt,document.createTextNode(say("Enable experimental repair (real-library trials pending)","Activer la réparation expérimentale (essais sur des bibliothèques réelles en attente)")));card.append(optLabel);
    const prepare=button(say("Prepare independent copy","Préparer une copie indépendante"),()=>guard(async()=>{
      await job({kind:"prepare-repair",repair_id:row.id,client_path:input.value,experimental:opt.checked},update);
    }));prepare.disabled=true;opt.onchange=()=>{prepare.disabled=!opt.checked;};card.append(prepare);
  }
  if(row.copy)card.append(button(say("Refresh verification","Actualiser la vérification"),()=>guard(async()=>{
    await job({kind:"refresh-repair",repair_id:row.id},update);
  })));
  if(row.status==="ready")card.append(button(say("Confirm download into copy…","Confirmer le téléchargement dans la copie…"),()=>guard(async()=>{
    if(!confirm(say(`Download missing content into ${row.copy}? The original is retained. Network traffic may exceed the estimate.`,`Télécharger le contenu manquant dans ${row.copy} ? L’original est conservé. Le trafic réseau peut dépasser l’estimation.`)))return;
    await job({kind:"start-repair",repair_id:row.id,confirmation:row.id},update);
  })));
}

$("library-combine").onclick=()=>guard(async()=>{
  await job({kind:"combine-library",paths:Array.from(libraryUI.selected)},row=>{
    libraryUI.item=row;libraryUI.generation++;$("candidates").hidden=false;
    $("candidate-title").textContent=say("Selected Local Items · use Find compatible torrents","Éléments sélectionnés · utilisez Chercher des torrents compatibles");
    showLibraryCandidates([]);
  });
});

function evidenceLabel(value) {
  const labels={filename:["Filename","Nom du fichier"],"embedded-title":["Embedded title","Titre intégré"],"writing-application":["Writing application","Application d’écriture"],resolution:["Resolution","Résolution"],"video-codec":["Video codec","Codec vidéo"],"audio-codec":["Audio codec","Codec audio"],"audio-channels":["Audio channels","Canaux audio"],processing:["Processing clue","Indice de traitement"],measured:["Measured contradiction","Contradiction mesurée"],hint:["Clue only","Simple indice"],review:["Review needed","À examiner"],verified:["Hash verified","Hashes vérifiés"],unverified:["Unverified","Non vérifié"],ambiguous:["Ambiguous","Ambigu"],partial:["Partially verified","Partiellement vérifié"],stale:["File changed; verify again","Fichier modifié ; vérifier à nouveau"],"awaiting-confirmation":["Copy not prepared","Copie à préparer"],ineligible:["Outside repair limits","Hors des limites de réparation"],preparing:["Preparing copy","Préparation de la copie"],adding:["Addition pending; inspect client","Ajout en cours ; inspecter le client"],checking:["Client verification","Vérification par le client"],ready:["Ready for confirmation","Prêt pour confirmation"],"needs-review":["Inspect the client before retrying","Inspecter le client avant de réessayer"],starting:["Start uncertain; inspect client","Démarrage incertain ; inspecter le client"],downloading:["Downloading into copy","Téléchargement dans la copie"],completed:["Completed","Terminé"]};
  return labels[value]?say(...labels[value]):value;
}
