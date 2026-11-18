/* Upload workspace: the same saved-draft flow as the desktop. */
const uploadUI = {section: "details", view: "local", baseline: null, loading: false, busy: false, stale: false,
  generation: 0, rows: [], refusals: [], sourceOffset: 0, sourceGeneration: 0};
$("upload-nfo").addEventListener("input", () => { state.uploadNfoOrigin = "original"; });

// Category rule wording matches the desktop Upload translations. Stored codes stay stable.
const uploadRuleMessages = {
  "no-file": ["No file to upload", "Aucun fichier à uploader"],
  "archive": ["c411 refuses archives ({detail}), and this one cannot be read", "c411 refuse les archives ({detail}), et celle-ci est illisible"],
  "no-3d-file": ["No 3D file (STL, 3MF, OBJ, STEP, GCODE…)", "Aucun fichier 3D (STL, 3MF, OBJ, STEP, GCODE…)"],
  "no-ebook-format": ["No accepted format (PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG, MP3, M4A/M4B, FLAC)", "Aucun format accepté (PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG, MP3, M4A/M4B, FLAC)"],
  "option-missing": ["Choose a value for {detail}", "Choisissez une valeur pour {detail}"],
  "no-audio-file": ["No audio file (FLAC, MP3, M4A, WAV, OGG…)", "Aucun fichier audio (FLAC, MP3, M4A, WAV, OGG…)"],
  "audio-format": ["c411 does not accept these formats: {detail}", "c411 n'accepte pas ces formats : {detail}"],
  "low-bitrate": ["Bitrate too low: {detail}", "Débit trop faible : {detail}"],
  "needs-cue": ["A single-file album needs its .cue sheet", "Un album en un seul fichier a besoin de sa feuille .cue"],
  "mixed-audio": ["One format and bitrate per album, found: {detail}", "Un seul format et un seul débit par album, trouvés : {detail}"],
  "no-mediainfo": ["MediaInfo is not installed: install libmediainfo (for example the libmediainfo0v5 package) to upload videos", "MediaInfo n'est pas installé : installez libmediainfo (par exemple le paquet libmediainfo0v5) pour téléverser des vidéos"],
  "no-video-file": ["No video file (MKV, MP4, M4V, AVI, TS, M2TS)", "Aucun fichier vidéo (MKV, MP4, M4V, AVI, TS, M2TS)"],
  "bad-container": ["c411 does not accept these containers: {detail}", "c411 n'accepte pas ces conteneurs : {detail}"],
  "gpu-encoder": ["GPU encoders are forbidden ({detail})", "Les encodeurs GPU sont interdits ({detail})"],
  "low-video-bitrate": ["Video bitrate too low: {detail}", "Débit vidéo trop faible : {detail}"],
  "banned-team": ["Banned team or source: {detail}", "Team ou source bannie : {detail}"],
  "no-french": ["No French audio and no full French subtitles in {detail}", "Ni audio français ni sous-titres français complets dans {detail}"],
  "mixed-pack": ["The files of a pack must share their specs and their team; they differ in: {detail}", "Les fichiers d'un pack doivent avoir les mêmes caractéristiques et la même team ; ils diffèrent par : {detail}"],
  "downloader": ["Downloader executables are forbidden: {detail}", "Les exécutables de téléchargement sont interdits : {detail}"],
  "bin-no-cue": ["A .bin image needs its .cue sheet", "Une image .bin a besoin de sa feuille .cue"],
  "clonecd-incomplete": ["A CloneCD image is missing: {detail}", "Image CloneCD incomplète, manque : {detail}"],
  "password-archive": ["Password-protected archives: {detail}", "Archives protégées par mot de passe : {detail}"],
  "console-container": ["Files this console does not take (archives are fine, one per game): {detail}", "Fichiers que cette console n'accepte pas (les archives sont permises, une par jeu) : {detail}"],
  "forbidden-tool": ["Trainers, hack tools and hypervisor cracks are forbidden: {detail}", "Les trainers, outils de hack et cracks hyperviseur sont interdits : {detail}"],
  "iso-not-allowed": ["An .iso is only allowed for a crack, repack or scene release: extract it first", "Un .iso n'est permis que pour un crack, un repack ou une release scene : extrayez-le d'abord"],
  "metadata-consistency": ["Metadata consistency: {detail}", "Cohérence des métadonnées: {detail}"],
  "paid-creators": ["c411 forbids files from independent creators who live off them", "c411 interdit les fichiers de créateurs indépendants qui en vivent"],
  "pack-theme": ["A pack must have one coherent theme", "Un pack doit avoir un thème cohérent"],
  "french-only": ["c411 accepts eBooks in French only", "c411 n'accepte que des eBooks en français"],
  "no-duplicate": ["Duplicates are strictly forbidden (another format is not one)", "Les doublons sont strictement interdits (un autre format n'en est pas un)"],
  "few-formats": ["At most two or three formats of the same book", "Deux ou trois formats au plus pour un même livre"],
  "whole-volumes": ["A pack must hold whole volumes", "Un pack doit contenir des tomes entiers"],
  "every-volume": ["A BD pack must hold every volume", "Un pack de BD doit contenir tous les tomes"],
  "no-transcode": ["No transcodes (MP3 to FLAC, 128 to 320 kbps, stereo to 5.1)", "Pas de transcodage (MP3 vers FLAC, 128 vers 320 kbps, stéréo vers 5.1)"],
  "short-single": ["Singles are accepted from 20 minutes only", "Les singles ne sont acceptés qu'à partir de 20 minutes"],
  "discography": ["Discographies are accepted for inactive artists only", "Les discographies ne sont acceptées que pour les artistes inactifs"],
  "cd-rip-missing": ["A CD-Rip needs: {detail}", "Un CD-Rip demande : {detail}"],
  "cd-rip-links": ["A CD-Rip's description gives the catalogue number and a Discogs or MusicBrainz link", "La description d'un CD-Rip donne le numéro de catalogue et un lien Discogs ou MusicBrainz"],
  "french-title": ["The release title must be the French one: {detail}", "Le titre de la release doit être le titre français : {detail}", "The release title must be the French one (the original goes in the description)", "Le titre de la release doit être le titre français (l'original va dans la description)"],
  "forbidden-source": ["Forbidden sources: CAM, TS, upscales, Plex transcodes, films still in cinemas", "Sources interdites : CAM, TS, upscales, transcodes Plex, films encore en salles"],
  "incomplete-season": ["Incomplete season, missing: {detail}", "Saison incomplète, manque : {detail}"],
  "web-platform": ["A WEB release must name its VOD platform in the description", "Une release WEB doit nommer sa plateforme VOD dans la description"],
  "mickey-tag": ["The MICKEY tag is a known detag: check the original release", "Le tag MICKEY est un detag connu : vérifiez la release d'origine"],
  "slots": ["c411 keeps 28 slots per release: check the existing releases for a free one", "c411 garde 28 slots par release : regardez les releases existantes pour en trouver un libre"],
  "version-activation": ["State the version and how it is activated (NFO and description)", "Indiquez la version et le mode d'activation (NFO et description)"],
  "no-alpha": ["No alpha or early-access versions", "Pas de version alpha ni d'accès anticipé"],
  "retro-only": ["Only retro cartridge and floppy platforms, and arcade", "Uniquement les plateformes rétro à cartouche ou disquette, et l'arcade"],
  "no-mixed-machines": ["Do not mix machines in one pack (except MAME): {detail}", "Ne mélangez pas les machines dans un pack (sauf MAME) : {detail}"],
  "release-type": ["Release type decided from the files: {detail} (edit the name to change it)", "Type de release décidé d'après les fichiers : {detail} (modifiez le nom pour le changer)"],
  "install-note": ["An install note is mandatory unless the release is portable", "Une note d'installation est obligatoire sauf pour une release portable"],
  "no-iptv": ["No IPTV software", "Pas de logiciel IPTV"],
  "older-version": ["An older version of the same generation is removed when this one is accepted", "Une version plus ancienne de la même génération est retirée quand celle-ci est acceptée"],
  "one-per-release": ["One scene version, plus one repack with language or bonus options, one repacker release and one portable per scene release; a repack must be compressed and smaller than the scene release: this is {detail}", "Une version scene, plus un repack avec options de langue ou bonus, une release de repackeur et un portable par release scene ; un repack doit être compressé et plus petit que la release scene : ici {detail}"],
  "official-training": ["Official video trainings only (audio at 64 kbps or more)", "Formations vidéo officielles uniquement (audio à 64 kbps ou plus)"],
  "plugin-host": ["A plugin or extension needs its host software on the tracker, compatible with that version, with a link to it in the description", "Un plugin ou une extension exige son logiciel hôte sur le tracker, compatible avec cette version, avec un lien vers celui-ci dans la description"],
  "original-crack": ["Find the original crack and use the cracker's or repacker's own name", "Retrouvez le crack d'origine et utilisez le nom d'origine du crackeur ou du repackeur"],
  "update-only": ["An update holds only the update files (not a new full pack), states the crack used, and is one per game version", "Une mise à jour ne contient que les fichiers de mise à jour (pas un nouveau pack complet), indique le crack utilisé, et il n'y en a qu'une par version du jeu"],
  "one-gog": ["One GOG version per game", "Une seule version GOG par jeu"],
  "one-per-console": ["One version per console game", "Une seule version par jeu console"],
  "region": ["Region {detail}: PAL/EU, NTSC/US, NTSC-J/JP or HK, one release each", "Région {detail} : PAL/EU, NTSC/US, NTSC-J/JP ou HK, une release chacune", "State the region: PAL/EU, NTSC/US, NTSC-J/JP or HK", "Indiquez la région : PAL/EU, NTSC/US, NTSC-J/JP ou HK"],
};
// Exact BBCode field labels, matching upload_presentation.FIELDS.
const uploadPresentationFields = {
  "title": "Titre",
  "files": "Fichiers",
  "size": "Taille totale",
  "author": "Auteur",
  "format": "Format",
  "language": "Langue",
  "duration": "Durée",
  "video_codec": "Codec vidéo",
  "video_bitrate": "Débit vidéo",
  "video_resolution": "Résolution vidéo",
  "audio_codec": "Codecs audio",
  "audio_bitrate": "Débits audio",
  "audio_channels": "Canaux audio",
  "audio_languages": "Langues audio",
  "audio": "Audio",
  "subtitles": "Sous-titres",
  "subtitle_formats": "Formats des sous-titres",
  "subtitle_types": "Types des sous-titres",
  "subtitle_languages": "Langues des sous-titres",
  "source": "Source",
  "platform": "Plateforme VOD",
  "artist": "Artiste",
  "album": "Album",
  "year": "Année",
  "tracks": "Pistes",
  "tracklist": "Liste des pistes",
  "codec": "Codec",
  "bitrate": "Débit",
  "sample_rate": "Fréquence",
  "bit_depth": "Profondeur",
  "catalogue_number": "Numéro de catalogue",
  "release_link": "Discogs / MusicBrainz",
  "install_size": "Taille installée",
  "version": "Version",
  "os": "Système",
  "activation": "Activation",
  "requirements": "Configuration requise",
  "installation": "Installation",
  "region": "Région",
  "resolution": "Résolution des images",
  "contents": "Contenu",
  "narrator": "Narrateur"
};

// Match complete diagnostics so a conflict on the same field stays visible.
function uploadPresentationMessages(value) {
  const messages = {
    "title: Add the release title.": ["Add the release title.", "Ajoutez le titre de la release."],
    "nfo: Add the NFO describing these exact files.": ["Add the NFO describing these exact files.", "Ajoutez le NFO décrivant ces fichiers précis."],
    "description.image: Add a public HTTP(S) cover/image inside the description: [img]URL[/img].": ["Add a public HTTP(S) cover/image inside the description: [img]URL[/img].", "Ajoutez une couverture ou une image publique HTTP(S) dans la description : [img]URL[/img]."],
    "description.synopsis: Fill the [h3]Présentation[/h3] section with a synopsis before [h3]Informations[/h3].": ["Fill the [h3]Présentation[/h3] section with a synopsis before [h3]Informations[/h3].", "Remplissez la section [h3]Présentation[/h3] avec un résumé avant [h3]Informations[/h3]."],
    "image: Set the hosted image URL before sending.": ["Set the hosted image URL before sending.", "Renseignez l'URL de l'image hébergée avant l'envoi."],
    "description.image: Public image hosting required before sending.": ["Public image hosting required before sending.", "Hébergez l'image sur une adresse publique avant l'envoi."],
    "category: Use upload IDs, not Catalogue IDs: 1 Video, 2 Ebook, 3 Audio, 4 Apps, 5 Games, 6 Emulation, 7 GPS, 10 3D. Call get_upload_requirements() to list them.": ["Choose a supported Upload Category in Details.", "Choisissez une catégorie Upload prise en charge dans Détails."],
    "category: Choose a subcategory belonging to this Upload Category.": ["Choose a subcategory belonging to this Upload Category.", "Choisissez une sous-catégorie appartenant à cette catégorie Upload."],
    "description.language: Ebooks require French content. Verify the file language; do not relabel foreign content.": ["Ebooks require French content. Verify the file language; do not relabel foreign content.", "Les ebooks doivent être en français. Vérifiez la langue du fichier ; ne modifiez pas sa langue déclarée pour masquer un contenu étranger."],
  };
  if (Object.hasOwn(messages, value)) return messages[value];
  const description = value.match(/^description\.[^:]+: (Fill '([^'\n]+)' in the description: \[b\]\2 :\[\/b\] value\.)$/);
  if (description) return [description[1], `Renseignez la rubrique '${description[2]}' dans la description : [b]${description[2]} :[/b] valeur.`];
  const nfo = value.match(/^nfo\.[^:]+: (NFO field missing: (.+)\. For a generated NFO use '\2 : value'\. Keep original release NFOs unaltered; obtain a complete original NFO\.)$/);
  if (nfo) return [nfo[1], `Rubrique NFO manquante : ${nfo[2]}. Pour un NFO généré, utilisez '${nfo[2]} : valeur'. Conservez les NFO d'origine sans les modifier ; obtenez un NFO d'origine complet.`];
  const separator = value.indexOf(": ");
  const field = value.slice(0, separator), detail = value.slice(separator + 2);
  const key = field.replace(/^(description|nfo)\./, "");
  const label = Object.hasOwn(uploadPresentationFields, key) ? uploadPresentationFields[key] : null;
  const fill = (templates, values) => templates.map(t => t.replace(/\{(\d+)\}/g, (_, i) => values[Number(i)]));
  let match;
  if (field === "description.language" && (match = detail.match(/^(.+): EPUB metadata declares (.+)\. French content is required\. Choose an eligible file, do not relabel it\.$/)))
    return fill(["{0}: EPUB metadata declares {1}. French content is required. Choose an eligible file, do not relabel it.", "{0} : les métadonnées EPUB indiquent {1}. Le contenu doit être en français. Choisissez un fichier admissible ; ne modifiez pas sa langue déclarée."], match.slice(1));
  if (field === "description.image.coverage" && (match = detail.match(/^Selected piece missing from attached render pages: (.+)\.$/)))
    return fill(["Selected piece missing from attached render pages: {0}.", "Pièce sélectionnée absente des planches de rendu jointes : {0}."], match.slice(1));
  if (field === "description.files" && (match = detail.match(/^Use the actual file count: (\d+)\.$/)))
    return fill(["Use the actual file count: {0}.", "Indiquez le nombre réel de fichiers : {0}."], match.slice(1));
  if (label && field.startsWith("nfo.") && (match = detail.match(/^NFO conflict: (.+); file facts\/presentation require (.+)\. Preserve the original NFO and obtain one for these exact files\.$/)))
    return fill(["NFO, {0}: declared {1}; file facts/presentation require {2}. Preserve the original NFO and obtain one for these exact files.", "NFO, {0} : valeur déclarée {1} ; les fichiers ou la présentation exigent {2}. Conservez le NFO d'origine et obtenez-en un correspondant à ces fichiers précis."], [label, ...match.slice(1)]);
  if (label && (match = detail.match(/^Conflicting facts: extracted (.+), declared (.+)\. Verify and correct the value or use the extracted fact\.$/)))
    return fill(["{0}: conflicting facts, extracted {1}, declared {2}. Verify and correct the value or use the extracted fact.", "{0} : informations contradictoires, valeur extraite {1}, valeur déclarée {2}. Vérifiez et corrigez la valeur ou utilisez celle extraite du fichier."], [label, ...match.slice(1)]);
  if ((match = field.match(/^(description|nfo)\.tracklist\[(\d+)\]\.duration$/)) && detail === "Add the duration of each track/chapter, for example 01. Title (03:42).")
    return fill(match[1] === "nfo" ? ["NFO, track/chapter {0}: add its duration, for example 03:42.", "NFO, piste ou chapitre {0} : ajoutez sa durée, par exemple 03:42."] : ["Description, track/chapter {0}: add its duration, for example 03:42.", "Description, piste ou chapitre {0} : ajoutez sa durée, par exemple 03:42."], [match[2]]);
  return null;
}

function uploadRuleParagraph(value, cls) {
  const separator = value.indexOf(":");
  const code = separator < 0 ? value : value.slice(0, separator);
  const detail = separator < 0 ? "" : value.slice(separator + 1).trim();
  const rule = Object.hasOwn(uploadRuleMessages, code) ? uploadRuleMessages[code] : null;
  const messages = rule || uploadPresentationMessages(value);
  if (!messages) return element("p", value, cls);
  const offset = !detail && messages.length === 4 ? 2 : 0;
  const en = rule ? messages[offset].split("{detail}").join(detail) : messages[0];
  const fr = rule ? messages[offset + 1].split("{detail}").join(detail) : messages[1];
  const paragraph = element("p", say(en, fr), cls);
  paragraph.dataset.en = en;
  paragraph.dataset.fr = fr;
  return paragraph;
}

function uploadForm() {
  const options = {};
  $("upload-options")
    .querySelectorAll("select")
    .forEach((s) => {
      options[s.dataset.type] = [...s.selectedOptions]
        .map((o) => Number(o.value))
        .filter(Boolean);
    });
  return {
    ...state.uploadDraft?.form,
    category: Number($("upload-category").value) || null,
    subcategory: Number($("upload-subcategory").value) || null,
    source: $("upload-source").value,
    image: $("upload-image").value,
    title: $("upload-title").value,
    description: $("upload-description").value,
    nfo: $("upload-nfo").value,
    options,
    assets: state.uploadAssets || [],
    nfo_origin: state.uploadNfoOrigin || "",
    field_provenance: state.uploadDraft?.form.field_provenance || {},
    reviewed: $("upload-reviewed").checked,
  };
}
async function prepareUpload(row, saved = null) {
  if (uploadUI.busy) return;
  if (uploadDirty() && !confirm(say("Discard unsaved changes?", "Abandonner les modifications non enregistrées ?"))) return;
  const generation = ++uploadUI.generation;
  const client = state.clientId;
  state.uploadDraft = saved;
  state.uploadAssets = saved?.form.assets || [];
  state.uploadNfoOrigin = saved?.form.nfo_origin || "";
  state.uploadPath = row.path;
  $("upload-model-tools")?.remove();
  $("upload-save-local").disabled = false;
  await navigate("upload");
  $("upload-editor").hidden = false;
  showUploadView("local");
  $("upload-help").hidden = true;
  $("upload-editor-title").textContent = row.name;
  uploadUI.loading = true;
  uploadUI.stale = false;
  uploadUI.baseline = null;
  uploadUI.section = "details";
  const categories = await api("upload/categories");
  if (generation !== uploadUI.generation || client !== state.clientId) return;
  $("upload-category").replaceChildren(
    new Option("Auto", ""),
    ...categories.map((c) => new Option(c.name, c.id)),
  );
  [
    "upload-title",
    "upload-description",
    "upload-nfo",
    "upload-source",
    "upload-image",
  ].forEach((id) => ($(id).value = ""));
  $("upload-subcategory").replaceChildren();
  $("upload-options").replaceChildren();
  $("upload-reviewed").checked = false;
  $("upload-result").replaceChildren();

  if (saved) {
    for (const [field, id] of Object.entries({title: "upload-title", description: "upload-description",
      nfo: "upload-nfo", source: "upload-source", image: "upload-image", category: "upload-category"})) {
      $(id).value = saved.form[field] ?? "";
    }
    $("upload-subcategory").append(new Option(String(saved.form.subcategory), saved.form.subcategory));
    state.uploadSavedOptions = saved.form.options;
  }
  await previewUpload();
}
async function previewUpload() {
  const generation = uploadUI.generation, client = state.clientId;
  const form = uploadForm();
  if (state.uploadSavedOptions) { form.options = state.uploadSavedOptions; state.uploadSavedOptions = null; }
  await uploadOperation(
    { kind: "upload-preview", path: state.uploadPath, upload: form,
      draft_id: state.uploadDraft?.id || "", revision: state.uploadDraft?.revision || 0 },
    (r) => {
      if (generation !== uploadUI.generation || client !== state.clientId) return;
      state.uploadAssets = r.assets || [];
      state.uploadNfoOrigin = r.nfo_origin || "";
      $("upload-category").value = r.category;
      if (r.category === 10 && !$("upload-model-tools")) uploadModelTools();
      $("upload-title").value = r.title;
      $("upload-description").value = r.description;
      $("upload-nfo").value = r.nfo;
      $("upload-subcategory").replaceChildren(
        ...r.subcategories.map((s) => new Option(s.label || s.name, s.id)),
      );
      $("upload-subcategory").value = r.subcategory;
      $("upload-options").replaceChildren(
        ...r.options.map((o) => {
          const label = element("label", o.name + (o.required ? " *" : "")),
            select = element("select");
          select.dataset.type = o.id;
          select.multiple = o.multiple;
          select.append(
            new Option("—", ""),
            ...o.values.map(
              (v) =>
                new Option(
                  v.label,
                  v.id,
                  false,
                  (r.chosen[o.id] || []).includes(v.id),
                ),
            ),
          );
          label.append(select);
          return label;
        }),
      );
      let originals=$("upload-original-names");
      if(!originals){originals=element("div");originals.id="upload-original-names";$("upload-title").parentElement.append(originals);}
      originals.replaceChildren();
      for(const name of r.original_names || []) originals.append(button(say("Use verified original name: ","Utiliser le nom d’origine vérifié : ")+name,()=>{
        $("upload-title").value=name;$("upload-title").dispatchEvent(new Event("input",{bubbles:true}));
        guard(previewUpload);
      }));
      uploadUI.refusals = r.refusals;
      $("upload-rules").replaceChildren(
        ...r.refusals.map((v) => uploadRuleParagraph(v, "danger")),
        ...r.warnings.map((v) => uploadRuleParagraph(v)),
      );
      table(
        "upload-files",
        r.files,
        [
          { label: "Torrent file", render: (f) => f.torrent_path },
          { label: "Local file", render: (f) => f.local_path },
          { label: "Size", render: (f) => bytes(f.size) },
        ],
        null,
      );
      if (uploadUI.loading) {
        // The baseline describes what was loaded, while the send still checks the saved form.
        uploadUI.baseline = uploadCanonical(uploadForm());
        uploadUI.loading = false;
      }
      showUploadSection(uploadUI.section);
    },
  );
}
function uploadCameraControls(preset) {
  const details = element("details"), fields = new Map();
  details.append(element("summary", say("Advanced camera", "Caméra avancée")));
  const initial = {yaw: 45, pitch: 55, roll: 0, zoom: 1, center_x: 0, center_y: 0};
  const specs = [
    ["yaw", say("Yaw (degrees)", "Azimut (degrés)"), null, null, 1],
    ["pitch", say("Polar pitch (degrees)", "Angle polaire (degrés)"), null, null, 1],
    ["roll", say("Roll (degrees)", "Roulis (degrés)"), null, null, 1],
    ["zoom", say("Zoom (larger means closer)", "Zoom (plus grand signifie plus près)"), 0.1, 10, 0.1],
    ["center_x", say("Horizontal framing", "Cadrage horizontal"), -0.8, 0.8, 0.05],
    ["center_y", say("Vertical framing", "Cadrage vertical"), -0.8, 0.8, 0.05],
  ];
  for (const [field, text, min, max, step] of specs) {
    const label = element("label"), input = element("input");
    input.type = "number"; input.value = initial[field]; input.step = step;
    input.required = true; input.dataset.cameraField = field;
    if (min !== null) input.min = min;
    if (max !== null) input.max = max;
    if (["yaw", "pitch", "roll"].includes(field)) input.addEventListener("input", () => { preset.value = "custom"; });
    label.append(element("span", text), input); details.append(label); fields.set(field, input);
  }
  const presets = {isometric: [45, 55, 0], front: [0, 90, 0], back: [180, 90, 0],
    left: [-90, 90, 0], right: [90, 90, 0], top: [0, 0, 0], bottom: [0, 180, 0]};
  preset.addEventListener("change", () => {
    const angles = presets[preset.value];
    if (angles) ["yaw", "pitch", "roll"].forEach((field, index) => { fields.get(field).value = angles[index]; });
  });
  return {element: details, read: () => Object.fromEntries([...fields].map(([field, input]) => {
    if (!input.checkValidity() || input.value === "" || !Number.isFinite(Number(input.value)))
      throw Error(say("Invalid camera value: ", "Valeur de caméra incorrecte : ") + field);
    return [field, Number(input.value)];
  }))};
}
function uploadModelTools() {
  const box = element("div", undefined, "card"); box.id = "upload-model-tools";
  const path = state.uploadPath, client = state.clientId;
  const inventory = element("div"), output = element("div");
  const choices = [];
  const current = () => path === state.uploadPath && client === state.clientId;
  const show = result => {
    if (!current()) return;
    output.replaceChildren(element("p", `${result.covered.length}/${result.selected} ${say("pieces rendered", "pièces rendues")}`));
    for (const problem of result.unsupported) output.append(element("p", `${problem.file}: ${problem.reason}`, "danger"));
    for (const content of result.content || []) {
      const img = element("img"); img.src = `data:${content.mimeType};base64,${content.data}`;
      img.alt = say("Local 3D presentation image", "Image de présentation 3D locale");
      img.style.maxWidth = "100%"; output.append(img);
    }
    output.append(button(say("Use these private images", "Utiliser ces images privées"), () => {
      if (current()) state.uploadAssets = result.artifacts.map(asset => asset.asset_id);
      toast(say("Images selected. Save the Local Draft to keep them.", "Images sélectionnées. Enregistrez le brouillon local pour les conserver."));
    }));
  };
  box.append(button(say("Inspect 3D pieces", "Inspecter les pièces 3D"), () => job({kind: "model-inspect", path}, result => {
    if (!current()) return;
    inventory.replaceChildren(); choices.length = 0;
    inventory.append(element("p", say("Folder and assembled names are hints. Keep scale/support variants distinct.", "Les noms de dossiers et d’assemblage sont des indices. Distinguez les échelles et supports.")));
    for (const model of result.models) {
      const row = element("div"), check = element("input"); check.type = "checkbox"; check.checked = model.previewable;
      const preset = element("select");
      for (const name of ["isometric", "front", "back", "left", "right", "top", "bottom", "custom"]) preset.append(new Option(name, name));
      const camera = uploadCameraControls(preset);
      choices.push({file: model.file, check, camera});
      row.append(check, element("span", model.file), preset, camera.element, button(say("Preview", "Aperçu"), () => job({
        kind: "model-render", path, model_files: [model.file], model_cameras: {[model.file]: camera.read()}
      }, show)));
      inventory.append(row);
    }
  })), inventory, button(say("Render all selected pieces", "Rendre toutes les pièces sélectionnées"), () => {
    const selected = choices.filter(choice => choice.check.checked);
    if (!selected.length) throw Error(say("Select inspected pieces first.", "Sélectionnez d’abord les pièces inspectées."));
    return job({kind: "model-render", path, model_files: selected.map(choice => choice.file),
      model_cameras: Object.fromEntries(selected.map(choice => [choice.file, choice.camera.read()]))}, show);
  }), output);
  $("upload-artwork-tools").append(box);
}

function uploadCanonical(form) {
  const options = Object.entries(form.options || {}).filter(([,v]) => v.length)
    .sort(([a],[b]) => Number(a)-Number(b)).map(([k,v]) => [String(k), [...v].sort((a,b)=>a-b)]);
  return JSON.stringify([form.category || null, form.subcategory || null, form.source || "",
    form.image || "", form.title || "", form.description || "", form.nfo || "", options,
    [...(form.assets || [])].sort(), form.nfo_origin || ""]);
}
function uploadDirty() {
  return Boolean(uploadUI.baseline && state.uploadPath && uploadCanonical(uploadForm()) !== uploadUI.baseline);
}
function uploadStatus(value) {
  return {queued: say("Awaiting review", "À relire"), sending: say("Send started; verify the result on c411", "Envoi lancé ; vérifiez le résultat sur c411"),
    uncertain: say("Check c411 before retrying", "Vérifier c411 avant un nouvel essai"),
    sent: say("Sent to c411", "Envoyé à c411")}[value] || value;
}
function showUploadSection(section) {
  uploadUI.section = section;
  document.querySelectorAll('[data-upload-panel]').forEach(el => el.hidden = el.dataset.uploadPanel !== section);
  document.querySelectorAll('[data-upload-section]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.uploadSection === section)));
  uploadEditorState();
}
function showUploadView(view) {
  rememberTab("upload", view);
  uploadUI.view = view;
  $("upload-workspace").hidden = view !== "local";
  $("upload-remote").hidden = view !== "remote";
  $("upload-sources").hidden = view !== "sources";
  document.querySelectorAll('[data-upload-view]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.uploadView === (view === 'sources' ? 'local' : view))));
}
function uploadEditorState() {
  const saved = state.uploadDraft, dirty = uploadDirty();
  const editable = !uploadUI.loading && !uploadUI.busy && !uploadUI.stale && (!saved || saved.status === 'queued');
  const currentSaved = saved && uploadCanonical(uploadForm()) === uploadCanonical(saved.form);
  const review = uploadUI.section === 'review';
  if (dirty || !currentSaved) $("upload-reviewed").checked = false;
  $("upload-save-state").textContent = uploadUI.loading ? say("Loading draft…", "Chargement du brouillon…") :
    dirty || (saved && !currentSaved) ? say("Unsaved changes", "Modifications non enregistrées") :
    saved ? `${say("Saved locally", "Enregistré localement")} · ${say("Revision", "Version")} ${saved.revision} · ${uploadStatus(saved.status)}` :
    say("New preparation · Not saved", "Nouvelle préparation · Non enregistrée");
  $("upload-save-local").disabled = !editable;
  $("upload-save-local").classList.toggle('primary', !saved);
  $("upload-review").hidden = !saved || review;
  $("upload-send-local").hidden = !saved || !review;
  $("upload-reviewed").disabled = !editable || !currentSaved;
  const missing = !saved?.form.image || !saved?.form.description?.trim() || !saved?.form.nfo?.trim() || (saved?.review?.refusals || []).length;
  $("upload-send-local").disabled = !editable || !currentSaved || Boolean(missing) || !$("upload-reviewed").checked;
  $("upload-presentation-preview").disabled = !saved;
  $("upload-review-state").textContent = !saved ? say("Save a local draft first.", "Enregistrez d’abord un brouillon local.") :
    !currentSaved ? say("Save changes before reviewing this revision.", "Enregistrez les modifications avant de relire cette version.") :
    missing ? say("Resolve the missing fields and refusals before sending.", "Complétez les champs manquants et corrigez les refus avant l’envoi.") :
    say("Review the saved revision and confirm below.", "Relisez la version enregistrée et confirmez ci-dessous.");
  $("upload-form").querySelectorAll('input:not(#upload-reviewed),select,textarea').forEach(el => el.disabled = !editable);
  renderUploadActions();
}
function renderUploadQueue() {
  $("upload-draft-search").placeholder = say("Find a draft…", "Chercher un brouillon…");
  $("upload-draft-search").setAttribute('aria-label', $("upload-draft-search").placeholder);
  const host = $("upload-local-queue"), query = $("upload-draft-search").value.toLocaleLowerCase();
  host.replaceChildren();
  for (const row of uploadUI.rows.filter(r => r.form.title.toLocaleLowerCase().includes(query))) {
    const entry = button('', () => prepareUpload({path: row.path, name: row.form.title}, row));
    entry.className = 'upload-draft-row';
    entry.setAttribute('aria-pressed', String(row.id === state.uploadDraft?.id));
    entry.append(element('strong', row.form.title), element('small', `${row.files.length} ${say('files','fichiers')} · ${uploadStatus(row.status)}`));
    host.append(entry);
  }
  if (!host.childElementCount) host.append(element('p', say('No local drafts match. Choose New draft to prepare a Library item.', 'Aucun brouillon correspondant. Choisissez Nouveau brouillon pour préparer un élément de la Bibliothèque.'), 'muted'));
}
async function loadUploadQueue() {
  const client = state.clientId, rows = await api('upload/queue');
  if (client !== state.clientId) return;
  uploadUI.rows = rows;
  renderUploadQueue();
  const current = rows.find(r => r.id === state.uploadDraft?.id);
  if (state.uploadDraft && (!current || current.revision !== state.uploadDraft.revision || current.status !== state.uploadDraft.status)) {
    uploadUI.stale = true;
    $("upload-reviewed").checked = false;
  }
  uploadEditorState();
  if (uploadUI.stale) {
    $("upload-review-state").textContent = say('Draft changed elsewhere. Reopen it from the list before sending.', 'Le brouillon a changé ailleurs. Rouvrez-le dans la liste avant l’envoi.');
  }
}
function renderUploadActions() {
  const host = $("upload-draft-actions"), r = state.uploadDraft;
  host.replaceChildren();
  if (!r) return;
  host.append(button(say('Preview saved draft','Aperçu du brouillon enregistré'), previewSavedUpload));
  if (r.status !== 'sending') host.append(button(say('Remove locally','Retirer localement'), async () => {
    if (!confirm(say('Remove only this local record? Files and c411 drafts will be kept.', 'Retirer uniquement ce brouillon local ? Les fichiers et brouillons c411 seront conservés.'))) return;
    await job({kind:'upload-remove',draft_id:r.id,revision:r.revision}, async () => {
      if (state.uploadDraft?.id === r.id) { state.uploadDraft = null; uploadUI.baseline = null; $("upload-editor").hidden = true; $("upload-help").hidden = false; }
      await loadUploadQueue();
    });
  }));
  if (['sending','uncertain'].includes(r.status)) host.append(button(say('Allow retry…','Autoriser un nouvel essai…'), async () => {
    if (!confirm(say('Check c411 and wait for any running send. Confirm that no draft was created before allowing another attempt.', 'Vérifiez c411 et attendez la fin de tout envoi. Confirmez qu’aucun brouillon n’a été créé avant un nouvel essai.'))) return;
    await job({kind:'upload-reset',draft_id:r.id,revision:r.revision}, async () => { await loadUploadQueue(); const current=uploadUI.rows.find(x=>x.id===r.id); if(current) await prepareUpload({path:current.path,name:current.form.title},current); });
  }));
}
async function previewSavedUpload() {
  const r = state.uploadDraft;
  if (!r) return;
  return aCardDetail(() => api(`upload/queue/${encodeURIComponent(r.id)}/preview?revision=${r.revision}&client_id=${encodeURIComponent(state.clientId || '')}`));
}
async function loadRemoteUploads() {
  showUploadView('remote');
  const client=state.clientId;
  $("upload-remote-list").textContent=say('Loading c411 drafts…','Chargement des brouillons c411…');
  try {
    const rows=await api('upload/drafts');
    if(client!==state.clientId)return;
    table('upload-remote-list',rows,[{label:say('Draft','Brouillon'),render:r=>r.name||r.title||String(r.id)},
      {label:say('Category','Catégorie'),render:r=>r.subcategory?.name||r.category?.name||''},
      {label:say('Modified','Modifié'),render:r=>String(r.updatedAt||'').slice(0,16).replace('T',' ')}]);
    if(!rows.length)$("upload-remote-list").textContent=say('No drafts on c411.','Aucun brouillon sur c411.');
  } catch(error) { if(client===state.clientId)$("upload-remote-list").textContent=error.message; }
}
async function loadUploadSources(more=false) {
  if (!more) { uploadUI.sourceOffset=0; $("upload-source-list").replaceChildren(); }
  const generation=++uploadUI.sourceGeneration, client=state.clientId;
  const result=await api(`library?${new URLSearchParams({q:$("upload-source-search").value,offset:uploadUI.sourceOffset,limit:100})}`);
  if(generation!==uploadUI.sourceGeneration||client!==state.clientId)return;
  for(const r of result.rows.filter(r=>r.state==='orphan')) {
    const b=button('',()=>prepareUpload(r));b.className='upload-source-row';b.append(element('strong',r.name),element('small',`${r.kind} · ${bytes(r.size)}`));$("upload-source-list").append(b);
  }
  uploadUI.sourceOffset+=result.rows.length;
  $("upload-source-more").hidden=uploadUI.sourceOffset>=result.total;
  if(!$("upload-source-list").childElementCount)$("upload-source-list").append(element('p',say('No orphan items in this page. Scan your Library or load more items.', 'Aucun orphelin sur cette page. Analysez votre Bibliothèque ou affichez la suite.')));
}
$("upload-draft-search").oninput=renderUploadQueue;
$("upload-queue-refresh").onclick=()=>guard(loadUploadQueue);
$("upload-remote-refresh").onclick=()=>guard(loadRemoteUploads);
$("upload-new").onclick=()=>guard(async()=>{showUploadView('sources');await loadUploadSources();});
$("upload-source-refresh").onclick=()=>guard(()=>loadUploadSources());
$("upload-source-more").onclick=()=>guard(()=>loadUploadSources(true));
$("upload-source-search").onkeydown=e=>{if(e.key==='Enter')guard(()=>loadUploadSources());};
document.querySelectorAll('[data-upload-view]').forEach(b=>b.onclick=()=>guard(async()=>{if(b.dataset.uploadView==='remote')await loadRemoteUploads();else{showUploadView('local');await loadUploadQueue();}}));
document.querySelectorAll('[data-upload-section]').forEach(b=>b.onclick=()=>showUploadSection(b.dataset.uploadSection));
$("upload-review").onclick=()=>showUploadSection('review');
$("upload-reviewed").onchange=uploadEditorState;
$("upload-presentation-preview").onclick=()=>guard(previewSavedUpload);
$("upload-form").addEventListener('input',event=>{ if(event.target.id === 'upload-reviewed') return; $("upload-reviewed").checked=false;uploadEditorState(); });
$("upload-save-local").onclick=()=>guard(async()=>{
  const generation=uploadUI.generation,client=state.clientId;
  await uploadOperation({kind:'upload-queue',path:state.uploadPath,upload:uploadForm(),draft_id:state.uploadDraft?.id||'',revision:state.uploadDraft?.revision||0},async r=>{
    if(generation!==uploadUI.generation||client!==state.clientId)return;
    state.uploadDraft=r;
    $("upload-description").value=r.form.description;$("upload-nfo").value=r.form.nfo;
    state.uploadAssets=r.form.assets||[];state.uploadNfoOrigin=r.form.nfo_origin||'';
    uploadUI.baseline=uploadCanonical(uploadForm());$("upload-reviewed").checked=false;
    uploadUI.refusals=r.review?.refusals||[];
    $("upload-rules").replaceChildren(...uploadUI.refusals.map(x=>uploadRuleParagraph(x,'danger')),...(r.review?.warnings||[]).map(x=>uploadRuleParagraph(x)));
    toast(say('Saved locally. Nothing sent to c411.','Enregistré localement. Rien n’a été envoyé à c411.'));
    uploadEditorState();await loadUploadQueue();
  });
});
$("upload-send-local").onclick=()=>guard(async()=>{
  const saved=state.uploadDraft,generation=uploadUI.generation,client=state.clientId;
  if(!saved||!$("upload-reviewed").checked||uploadCanonical(uploadForm())!==uploadCanonical(saved.form))throw Error(say('Save and review this revision before sending.','Enregistrez et relisez cette version avant l’envoi.'));
  if(!confirm(say('Send this saved revision to c411 as a draft? It will not be published.','Envoyer cette version enregistrée à c411 comme brouillon ? Elle ne sera pas publiée.')))return;
  $("upload-send-local").disabled=true;
  await uploadOperation({kind:'upload-send',draft_id:saved.id,revision:saved.revision},async r=>{
    if(generation!==uploadUI.generation||client!==state.clientId)return;
    state.uploadDraft={...saved,status:'sent'};
    $("upload-result").replaceChildren(element('p',r.message),button(say('Start seeding','Démarrer le seed'),()=>job({kind:'upload-seed',hashes:[r.hash]},()=>toast(say('Verification started.','Vérification lancée.')))));
    uploadEditorState();await loadUploadQueue();
  });
});
$("upload-preview").onclick=()=>guard(previewUpload);
$("upload-category").onchange=()=>{$("upload-subcategory").replaceChildren();$("upload-title").value='';$("upload-reviewed").checked=false;guard(previewUpload);};
$("upload-subcategory").onchange=()=>{$("upload-reviewed").checked=false;guard(previewUpload);};
$("upload-form").onsubmit=e=>{e.preventDefault();$("upload-save-local").click();};

function resetUploadWorkspace() {
  uploadUI.generation++; uploadUI.sourceGeneration++;
  uploadUI.baseline=null; uploadUI.loading=false; uploadUI.busy=false; uploadUI.stale=false;
  state.uploadPath=''; state.uploadDraft=null;
  $("upload-help").hidden=false; $("upload-editor").hidden=true;
  $("upload-remote-list").replaceChildren(); $("upload-local-queue").replaceChildren();
  showUploadView('local');
}
async function uploadOperation(body, done) {
  const generation=uploadUI.generation;
  uploadUI.busy=true; uploadEditorState();
  const release=()=>{ if(generation===uploadUI.generation){uploadUI.busy=false;uploadUI.loading=false;uploadEditorState();} };
  try {
    return await job(body,async result=>{try{await done(result);}finally{release();}},async()=>{release();await loadUploadQueue();});
  } catch(error) { release(); throw error; }
}
