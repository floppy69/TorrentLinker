"use strict";
const preUI = {tab:"library", data:null, selected:"", dirty:false, month:new Date().getMonth(), year:new Date().getFullYear()};
const preCall = (action, value) => api(action === "state" ? "prerolls" : `prerolls/${action}`, action === "state" ? undefined : (value || {}));
const preId = () => crypto.randomUUID().replaceAll("-", "");
const preText = () => ({library:say("Library","Bibliothèque"),sequence:say("Sequences","Séquences"),calendar:say("Calendar","Calendrier"),rules:say("Rules","Règles"),trailers:say("Trailers","Bandes-annonces"),studio:say("Studio","Studio")});
function preDirty(){preUI.dirty=true;$("preroll-status").textContent=say("Unsaved changes","Modifications non enregistrées")}
function preField(root,label,value,change,type="text",options){
 const wrap=element("label",label,"preroll-field"),input=element(options?"select":type==="textarea"?"textarea":"input");
 if(options)for(const [key,text]of options)input.append(new Option(text,key));else if(type!=="textarea")input.type=type;
 if(type==="checkbox")input.checked=!!value;else input.value=value??"";
 input.setAttribute("aria-label",label);input.onchange=()=>change(type==="checkbox"?input.checked:type==="number"?Number(input.value):input.value);
 wrap.append(input);root.append(wrap);return input;
}
function preList(root,label,values,options,change){
 const box=element("fieldset");box.append(element("legend",label));
 for(const [id,name]of options)preField(box,name,values.includes(id),checked=>{const next=new Set(values);checked?next.add(id):next.delete(id);values.splice(0,values.length,...next);change(values)},"checkbox");
 root.append(box);
}
function preCard(root,title){const card=element("section",undefined,"preroll-card");if(title)card.append(element("h3",title));root.append(card);return card}
const preRatings=()=>[["",say("Unrated","Non classé")],["TP",say("All ages","Tous publics")],["10","−10"],["12","−12"],["16","−16"],["18","−18"]];
async function preReload(){const data=await preCall("state");if(preUI.dirty&&preUI.data)data.configuration=preUI.data.configuration;preUI.data=data;preRender()}
async function preOpen(){
 let dialog=$("preroll-panel");if(!dialog){dialog=element("dialog");dialog.id="preroll-panel";document.body.append(dialog)}
 await preReload();dialog.showModal();
}
function preRender(){
 const dialog=$("preroll-panel"),data=preUI.data;if(!dialog||!data)return;
 dialog.replaceChildren();const header=element("header",undefined,"preroll-toolbar");header.append(element("h2",say("Pre-rolls","Pré-rolls")),button(say("Close","Fermer"),()=>dialog.close()));dialog.append(header);
 const nav=element("nav",undefined,"preroll-toolbar");for(const[key,name]of Object.entries(preText())){const b=button(name,()=>{preUI.tab=key;preRender()});b.setAttribute("aria-pressed",String(preUI.tab===key));nav.append(b)}dialog.append(nav);
 const status=element("p",preUI.dirty?say("Unsaved changes","Modifications non enregistrées"):"","muted");status.id="preroll-status";dialog.append(status);
 const root=element("div");root.id="preroll-body";dialog.append(root);
 if(preUI.tab==="library")preLibrary(root);
 else if(preUI.tab==="sequence")preSequences(root);
 else if(preUI.tab==="calendar")preCalendar(root);
 else if(preUI.tab==="rules")preRules(root);
 else if(preUI.tab==="trailers")preTrailers(root);
 else if(preUI.tab==="studio"&&typeof prerollStudio==="function")guard(()=>prerollStudio(root));
 if(["sequence","calendar","rules"].includes(preUI.tab))dialog.append(button(say("Save pre-roll settings","Enregistrer les réglages des pré-rolls"),async()=>{await preCall("configure",{configuration:data.configuration});preUI.dirty=false;await preReload()},"media-primary"));
}
function preImport(root,trailer=false){
 const row=element("div",undefined,"preroll-toolbar"),path=element("input");path.placeholder=say("File or folder on the app host","Fichier ou dossier sur l’hôte de l’application");path.setAttribute("aria-label",path.placeholder);row.append(path);
 row.append(button(say("Import MP4","Importer un MP4"),async()=>{const clip=await preCall("import-file",{path:path.value});if(trailer)await preCall("update",{id:clip.id,value:{category:"trailer"}});await preReload()}),button(say("Import folder","Importer un dossier"),async()=>{const result=await preCall("import-folder",{path:path.value});await preReload();const failed=result.results.filter(x=>x.error);if(failed.length)toast(failed.map(x=>`${x.name}: ${x.error}`).join("\n"),"bad")}));root.append(row);
 root.append(element("p",say("MP4 H.264/AAC, up to 1080p and 2 GB locally. Community sharing is limited to 50 MB. Original files are kept. Set each clip's rating before playback.","MP4 H.264/AAC, jusqu’à 1080p et 2 Go en local. Le partage communautaire est limité à 50 Mo. Les originaux sont conservés. Classez chaque clip avant sa lecture."),"muted"));
}
function preLibrary(root){
 preImport(root);const filter=element("input");filter.placeholder=say("Filter clips","Filtrer les clips");filter.setAttribute("aria-label",filter.placeholder);root.append(filter);
 const grid=element("div",undefined,"preroll-grid");root.append(grid);
 const render=()=>{grid.replaceChildren();for(const clip of preUI.data.clips.filter(c=>(c.title+" "+c.category+" "+c.tags.join(" ")).toLowerCase().includes(filter.value.toLowerCase()))){
  const card=preCard(grid,clip.title);card.append(element("p",`${clip.source} · ${Math.round(clip.duration)} s`));
  const draft={title:clip.title,category:clip.category,tags:[...clip.tags],rating:clip.rating};
  preField(card,say("Title","Titre"),draft.title,v=>draft.title=v);
  preField(card,say("Category","Catégorie"),draft.category,v=>draft.category=v,"text",[["welcome",say("Welcome","Accueil")],["trailer",say("Trailer","Bande-annonce")],["announcement",say("Announcement","Annonce")],["event",say("Event","Événement")]]);
  preField(card,say("Tags, comma separated","Tags séparés par des virgules"),draft.tags.join(", "),v=>draft.tags=v.split(",").map(x=>x.trim()).filter(Boolean));
  preField(card,say("Age rating","Classification"),draft.rating||"",v=>draft.rating=v||null,"text",preRatings());
  const actions=element("div",undefined,"preroll-toolbar");actions.append(button(say("Save clip","Enregistrer le clip"),async()=>{await preCall("update",{id:clip.id,value:draft});await preReload()}),button(say("Preview","Prévisualiser"),()=>host("preroll-preview",{clip:clip.id})),button(say("Delete copy","Supprimer la copie"),async()=>{await preCall("delete",{id:clip.id});await preReload()}));
  if(typeof communityShareDialog==="function")actions.append(button(say("Share","Partager"),()=>communityShareDialog("preroll",{id:clip.id})));
  card.append(actions);
 }if(!grid.children.length)grid.append(element("p",say("Import a clip or create one in Studio.","Importez un clip ou créez-en un dans le Studio.")))};
 filter.oninput=render;render();
 if(typeof communityBrowseDialog==="function")root.append(button(say("Browse community clips","Parcourir les clips communautaires"),()=>communityBrowseDialog("preroll",preReload)));
}
function preSelected(){const all=preUI.data.configuration.sequences;return all.find(s=>s.id===preUI.selected)||all[0]}
function preSequences(root){
 const config=preUI.data.configuration;
 const controls=element("div",undefined,"preroll-toolbar");controls.append(button(say("New sequence","Nouvelle séquence"),()=>{const id=preId();config.sequences.push({id,name:say("New sequence","Nouvelle séquence"),steps:[],rules:{kind:"any",genres:[],audio:[],accounts:[],viewers:[],start:"00:00",end:"00:00"}});preUI.selected=id;if(!config.default_sequence)config.default_sequence=id;preDirty();preRender()}));root.append(controls);
 const split=element("div",undefined,"preroll-split"),list=preCard(split,say("Sequences","Séquences")),inspect=preCard(split,say("Sequence details","Détails de la séquence"));root.append(split);
 for(const seq of config.sequences){const b=button(seq.name,()=>{preUI.selected=seq.id;preRender()});b.setAttribute("aria-pressed",String(preSelected()?.id===seq.id));list.append(b)}
 const seq=preSelected();if(!seq){inspect.append(element("p",say("Create your first sequence.","Créez votre première séquence.")));return}
 preField(inspect,say("Sequence name","Nom de la séquence"),seq.name,v=>{seq.name=v;preDirty()});
 seq.steps.forEach((step,index)=>{
  const row=preCard(inspect,`${index+1}`);row.draggable=true;row.ondragstart=e=>e.dataTransfer.setData("text/plain",String(index));row.ondragover=e=>e.preventDefault();row.ondrop=e=>{e.preventDefault();const from=Number(e.dataTransfer.getData("text/plain"));if(Number.isInteger(from)&&from>=0&&from<seq.steps.length){const[moved]=seq.steps.splice(from,1);seq.steps.splice(index,0,moved);preDirty();preRender()}};
  preField(row,say("Step type","Type d’étape"),step.kind,v=>{step.kind=v;preDirty();preRender()},"text",[["clip",say("Clip","Clip")],["random",say("Random without repeats","Aléatoire sans répétition")],["trailer",say("Trailer","Bande-annonce")],["pause",say("Pause","Pause")]]);
  const options=[["",say("None","Aucun")],...preUI.data.clips.map(c=>[c.id,c.title])];
  if(step.kind==="clip")preField(row,say("Clip","Clip"),step.clip,v=>{step.clip=v;preDirty()},"text",options);
  if(["random","trailer"].includes(step.kind)){preField(row,say("Category filter","Filtre de catégorie"),step.category||"",v=>{step.category=v;preDirty()});preField(row,say("Required tags","Tags requis"),(step.tags||[]).join(", "),v=>{step.tags=v.split(",").map(x=>x.trim()).filter(Boolean);preDirty()})}
  if(step.kind==="pause")preField(row,say("Seconds","Secondes"),step.seconds,v=>{step.seconds=v;preDirty()},"number");else preField(row,say("Fallback clip","Clip de remplacement"),step.fallback||"",v=>{step.fallback=v;preDirty()},"text",options);
  const buttons=element("div",undefined,"preroll-toolbar");for(const[delta,label]of[[-1,"↑"],[1,"↓"]])buttons.append(button(label,()=>{const next=index+delta;if(next>=0&&next<seq.steps.length){[seq.steps[index],seq.steps[next]]=[seq.steps[next],seq.steps[index]];preDirty();preRender()}}));buttons.append(button(say("Remove step","Retirer l’étape"),()=>{seq.steps.splice(index,1);preDirty();preRender()}));row.append(buttons);
 });
 inspect.append(button(say("Add step","Ajouter une étape"),()=>{seq.steps.push({kind:"clip",clip:"",fallback:"",category:"",tags:[],seconds:2});preDirty();preRender()}));
 inspect.append(button(say("Delete sequence","Supprimer la séquence"),()=>{config.sequences=config.sequences.filter(s=>s.id!==seq.id);config.schedules=config.schedules.filter(s=>s.sequence!==seq.id);if(config.default_sequence===seq.id)config.default_sequence=config.sequences[0]?.id||"";preDirty();preRender()}));
}
function preRules(root){
 const seq=preSelected();if(!seq){root.append(element("p",say("Create a sequence first.","Créez d’abord une séquence.")));return}
 preField(root,say("Sequence","Séquence"),seq.id,v=>{preUI.selected=v;preRender()},"text",preUI.data.configuration.sequences.map(s=>[s.id,s.name]));
 const grid=element("div",undefined,"preroll-grid");root.append(grid);const rules=seq.rules;
 preField(preCard(grid,say("Content","Contenu")),say("Media type","Type de média"),rules.kind,v=>{rules.kind=v;preDirty()},"text",[["any",say("Films and episodes","Films et épisodes")],["film",say("Films","Films")],["episode",say("Episodes","Épisodes")]]);
 for(const[key,en,fr]of[["genres","Genres","Genres"],["audio","Audio formats","Formats audio"]])preField(preCard(grid,say(en,fr)),say("Values, comma separated","Valeurs séparées par des virgules"),rules[key].join(", "),v=>{rules[key]=v.split(",").map(x=>x.trim()).filter(Boolean);preDirty()});
 const hours=preCard(grid,say("Hours","Horaires"));for(const[key,en,fr]of[["start","From","De"],["end","Until","À"]])preField(hours,say(en,fr),rules[key],v=>{rules[key]=v;preDirty()},"time");
 const people=preCard(grid,say("People","Personnes"));people.append(element("p",say("No selection means everyone.","Sans sélection : tout le monde.")));
 preList(people,say("Accounts","Comptes"),rules.accounts,(preUI.data.accounts||[{id:"owner",name:"Owner"}]).map(a=>[a.id,a.name]),()=>preDirty());
 preList(people,say("Viewers","Profils"),rules.viewers,(preUI.data.viewers||[]).map(a=>[a.id,a.name]),()=>preDirty());
 preCard(grid,say("Age ratings","Classification")).append(element("p",say("Every clip must fit both the film's rating and the watcher's limit. Unrated clips are excluded.","Chaque clip respecte la classification du film et la limite du spectateur. Les clips non classés sont exclus.")));
}
function preCalendar(root){
 const config=preUI.data.configuration,controls=preCard(root,say("Default programme","Programme habituel"));
 preField(controls,say("Enable pre-rolls","Activer les pré-rolls"),config.enabled,v=>{config.enabled=v;preDirty()},"checkbox");
 preField(controls,say("When no event matches","En l’absence d’événement"),config.default_sequence,v=>{config.default_sequence=v;preDirty()},"text",[["",say("No pre-roll","Aucun pré-roll")],...config.sequences.map(s=>[s.id,s.name])]);
 preField(controls,say("Programme timezone","Fuseau du programme"),config.timezone,v=>{config.timezone=v;preDirty()});
 const heading=element("div",undefined,"preroll-toolbar");heading.append(button("←",()=>{const d=new Date(preUI.year,preUI.month-1);preUI.year=d.getFullYear();preUI.month=d.getMonth();preRender()}),element("h3",new Date(preUI.year,preUI.month).toLocaleDateString(language,{month:"long",year:"numeric"})),button("→",()=>{const d=new Date(preUI.year,preUI.month+1);preUI.year=d.getFullYear();preUI.month=d.getMonth();preRender()}));root.append(heading);
 const calendar=element("div",undefined,"preroll-calendar"),first=new Date(preUI.year,preUI.month,1),offset=(first.getDay()+6)%7;
 for(let i=0;i<42;i++){const d=new Date(preUI.year,preUI.month,i-offset+1),cell=element("div",String(d.getDate()),"preroll-day"),iso=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  if(d.getMonth()!==preUI.month)cell.classList.add("muted");for(const event of config.schedules){const value=event.yearly?iso.slice(5):iso,start=event.yearly?event.date_from.slice(5):event.date_from,end=event.yearly?event.date_to.slice(5):event.date_to;const dates=start&&end&&start>end?value>=start||value<=end:(!start||value>=start)&&(!end||value<=end);if(event.enabled&&dates&&event.weekdays.includes((d.getDay()+6)%7))cell.append(element("small",event.name))}calendar.append(cell)}root.append(calendar);
 root.append(button(say("New event","Nouvel événement"),()=>{if(!config.sequences.length)throw Error(say("Create a sequence first.","Créez d’abord une séquence."));config.schedules.push({id:preId(),name:say("New event","Nouvel événement"),sequence:config.sequences[0].id,priority:0,enabled:true,weekdays:[0,1,2,3,4,5,6],date_from:"",date_to:"",yearly:false,start:"00:00",end:"00:00",timezone:config.timezone});preDirty();preRender()}));
 const grid=element("div",undefined,"preroll-grid");root.append(grid);config.schedules.forEach((event,index)=>{const card=preCard(grid,event.name);preField(card,say("Event name","Nom de l’événement"),event.name,v=>{event.name=v;preDirty()});preField(card,say("Sequence","Séquence"),event.sequence,v=>{event.sequence=v;preDirty()},"text",config.sequences.map(s=>[s.id,s.name]));preField(card,say("Priority","Priorité"),event.priority,v=>{event.priority=v;preDirty()},"number");for(const[key,en,fr,type]of[["date_from","First date","Première date","date"],["date_to","Last date","Dernière date","date"],["start","Start time","Heure de début","time"],["end","End time","Heure de fin","time"],["timezone","Timezone","Fuseau horaire","text"]])preField(card,say(en,fr),event[key],v=>{event[key]=v;preDirty()},type);
 preField(card,say("Repeat every year","Répéter chaque année"),event.yearly,v=>{event.yearly=v;preDirty()},"checkbox");preField(card,say("Enabled","Activé"),event.enabled,v=>{event.enabled=v;preDirty()},"checkbox");preList(card,say("Weekdays","Jours"),event.weekdays,Array.from({length:7},(_,i)=>[i,new Date(2026,10,16+i).toLocaleDateString(language,{weekday:"short"})]),()=>preDirty());card.append(button(say("Delete event","Supprimer l’événement"),()=>{config.schedules.splice(index,1);preDirty();preRender()}))});
}
function preTrailers(root){
 const query={tmdb_id:"",media_type:"movie"},controls=preCard(root,say("TMDb trailers","Bandes-annonces TMDb"));
 controls.append(element("p",say("YouTube trailers play in an embedded player and are never downloaded. Local trailer files can be imported below.","Les bandes-annonces YouTube sont lues dans un lecteur intégré et ne sont jamais téléchargées. Les fichiers locaux peuvent être importés ci-dessous.")));
 const searchInput=element("input");searchInput.setAttribute("aria-label",say("Film or series title","Titre du film ou de la série"));controls.append(searchInput);const matches=element("div");controls.append(button(say("Search titles","Rechercher des titres"),async()=>{const result=await preCall("trailer-search",{query:searchInput.value,media_type:query.media_type});matches.replaceChildren();for(const match of result.results)matches.append(button(`${match.title} (${match.year})`,()=>{query.tmdb_id=match.id;controls.querySelector('[aria-label="'+say("TMDb ID","Identifiant TMDb")+'"]').value=match.id}))}),matches);
 preField(controls,say("TMDb ID","Identifiant TMDb"),"",v=>query.tmdb_id=v);preField(controls,say("Type","Type"),"movie",v=>query.media_type=v,"text",[["movie",say("Film","Film")],["tv",say("Series","Série")]]);
 const results=element("div",undefined,"preroll-grid");controls.append(button(say("Find trailers","Trouver les bandes-annonces"),async()=>{const found=await preCall("trailers",query);results.replaceChildren();for(const row of found.videos){const card=preCard(results,row.name);card.append(element("p",`${row.language} · ${found.rating||say("Unrated","Non classé")}`),button(say("Add trailer link","Ajouter le lien"),async()=>{await preCall("add-trailer",{...query,key:row.key});await preReload()}))}if(!found.videos.length)results.append(element("p",say("No eligible YouTube trailer found.","Aucune bande-annonce YouTube éligible.")))}));root.append(results);preImport(root,true);
}
const preButton=button(say("Pre-rolls","Pré-rolls"),preOpen);preButton.id="media-prerolls";preButton.hidden=true;$("media-extra-tools").append(preButton);
window.addEventListener("media-environment",event=>{preButton.hidden=event.detail.owner===false;preButton.textContent=say("Pre-rolls","Pré-rolls")});
