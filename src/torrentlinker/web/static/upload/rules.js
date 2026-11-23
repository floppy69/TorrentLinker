// Saved diagnostic wording shared by both Upload hosts.
const uploadRuleMessages = {
  "no-file": ["No file to upload", "Aucun fichier à uploader"],
  archive: [
    "c411 refuses archives ({detail}), and this one cannot be read",
    "c411 refuse les archives ({detail}), et celle-ci est illisible",
  ],
  "no-3d-file": [
    "No 3D file (STL, 3MF, OBJ, STEP, GCODE…)",
    "Aucun fichier 3D (STL, 3MF, OBJ, STEP, GCODE…)",
  ],
  "no-ebook-format": [
    "No accepted format (PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG, MP3, M4A/M4B, FLAC)",
    "Aucun format accepté (PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG, MP3, M4A/M4B, FLAC)",
  ],
  "option-missing": [
    "Choose a value for {detail}",
    "Choisissez une valeur pour {detail}",
  ],
  "no-audio-file": [
    "No audio file (FLAC, MP3, M4A, WAV, OGG…)",
    "Aucun fichier audio (FLAC, MP3, M4A, WAV, OGG…)",
  ],
  "audio-format": [
    "c411 does not accept these formats: {detail}",
    "c411 n'accepte pas ces formats : {detail}",
  ],
  "low-bitrate": ["Bitrate too low: {detail}", "Débit trop faible : {detail}"],
  "needs-cue": [
    "A single-file album needs its .cue sheet",
    "Un album en un seul fichier a besoin de sa feuille .cue",
  ],
  "mixed-audio": [
    "One format and bitrate per album, found: {detail}",
    "Un seul format et un seul débit par album, trouvés : {detail}",
  ],
  "no-mediainfo": [
    "MediaInfo is not installed: install libmediainfo (for example the libmediainfo0v5 package) to upload videos",
    "MediaInfo n'est pas installé : installez libmediainfo (par exemple le paquet libmediainfo0v5) pour téléverser des vidéos",
  ],
  "no-video-file": [
    "No video file (MKV, MP4, M4V, AVI, TS, M2TS)",
    "Aucun fichier vidéo (MKV, MP4, M4V, AVI, TS, M2TS)",
  ],
  "bad-container": [
    "c411 does not accept these containers: {detail}",
    "c411 n'accepte pas ces conteneurs : {detail}",
  ],
  "gpu-encoder": [
    "GPU encoders are forbidden ({detail})",
    "Les encodeurs GPU sont interdits ({detail})",
  ],
  "low-video-bitrate": [
    "Video bitrate too low: {detail}",
    "Débit vidéo trop faible : {detail}",
  ],
  "banned-team": [
    "Banned team or source: {detail}",
    "Team ou source bannie : {detail}",
  ],
  "no-french": [
    "No French audio and no full French subtitles in {detail}",
    "Ni audio français ni sous-titres français complets dans {detail}",
  ],
  "mixed-pack": [
    "The files of a pack must share their specs and their team; they differ in: {detail}",
    "Les fichiers d'un pack doivent avoir les mêmes caractéristiques et la même team ; ils diffèrent par : {detail}",
  ],
  downloader: [
    "Downloader executables are forbidden: {detail}",
    "Les exécutables de téléchargement sont interdits : {detail}",
  ],
  "bin-no-cue": [
    "A .bin image needs its .cue sheet",
    "Une image .bin a besoin de sa feuille .cue",
  ],
  "clonecd-incomplete": [
    "A CloneCD image is missing: {detail}",
    "Image CloneCD incomplète, manque : {detail}",
  ],
  "password-archive": [
    "Password-protected archives: {detail}",
    "Archives protégées par mot de passe : {detail}",
  ],
  "console-container": [
    "Files this console does not take (archives are fine, one per game): {detail}",
    "Fichiers que cette console n'accepte pas (les archives sont permises, une par jeu) : {detail}",
  ],
  "forbidden-tool": [
    "Trainers, hack tools and hypervisor cracks are forbidden: {detail}",
    "Les trainers, outils de hack et cracks hyperviseur sont interdits : {detail}",
  ],
  "iso-not-allowed": [
    "An .iso is only allowed for a crack, repack or scene release: extract it first",
    "Un .iso n'est permis que pour un crack, un repack ou une release scene : extrayez-le d'abord",
  ],
  "metadata-consistency": [
    "Metadata consistency: {detail}",
    "Cohérence des métadonnées: {detail}",
  ],
  "paid-creators": [
    "c411 forbids files from independent creators who live off them",
    "c411 interdit les fichiers de créateurs indépendants qui en vivent",
  ],
  "pack-theme": [
    "A pack must have one coherent theme",
    "Un pack doit avoir un thème cohérent",
  ],
  "french-only": [
    "c411 accepts eBooks in French only",
    "c411 n'accepte que des eBooks en français",
  ],
  "no-duplicate": [
    "Duplicates are strictly forbidden (another format is not one)",
    "Les doublons sont strictement interdits (un autre format n'en est pas un)",
  ],
  "few-formats": [
    "At most two or three formats of the same book",
    "Deux ou trois formats au plus pour un même livre",
  ],
  "whole-volumes": [
    "A pack must hold whole volumes",
    "Un pack doit contenir des tomes entiers",
  ],
  "every-volume": [
    "A BD pack must hold every volume",
    "Un pack de BD doit contenir tous les tomes",
  ],
  "no-transcode": [
    "No transcodes (MP3 to FLAC, 128 to 320 kbps, stereo to 5.1)",
    "Pas de transcodage (MP3 vers FLAC, 128 vers 320 kbps, stéréo vers 5.1)",
  ],
  "short-single": [
    "Singles are accepted from 20 minutes only",
    "Les singles ne sont acceptés qu'à partir de 20 minutes",
  ],
  discography: [
    "Discographies are accepted for inactive artists only",
    "Les discographies ne sont acceptées que pour les artistes inactifs",
  ],
  "cd-rip-missing": [
    "A CD-Rip needs: {detail}",
    "Un CD-Rip demande : {detail}",
  ],
  "cd-rip-links": [
    "A CD-Rip's description gives the catalogue number and a Discogs or MusicBrainz link",
    "La description d'un CD-Rip donne le numéro de catalogue et un lien Discogs ou MusicBrainz",
  ],
  "french-title": [
    "The release title must be the French one: {detail}",
    "Le titre de la release doit être le titre français : {detail}",
    "The release title must be the French one (the original goes in the description)",
    "Le titre de la release doit être le titre français (l'original va dans la description)",
  ],
  "forbidden-source": [
    "Forbidden sources: CAM, TS, upscales, Plex transcodes, films still in cinemas",
    "Sources interdites : CAM, TS, upscales, transcodes Plex, films encore en salles",
  ],
  "incomplete-season": [
    "Incomplete season, missing: {detail}",
    "Saison incomplète, manque : {detail}",
  ],
  "web-platform": [
    "A WEB release must name its VOD platform in the description",
    "Une release WEB doit nommer sa plateforme VOD dans la description",
  ],
  "mickey-tag": [
    "The MICKEY tag is a known detag: check the original release",
    "Le tag MICKEY est un detag connu : vérifiez la release d'origine",
  ],
  slots: [
    "c411 keeps 28 slots per release: check the existing releases for a free one",
    "c411 garde 28 slots par release : regardez les releases existantes pour en trouver un libre",
  ],
  "version-activation": [
    "State the version and how it is activated (NFO and description)",
    "Indiquez la version et le mode d'activation (NFO et description)",
  ],
  "no-alpha": [
    "No alpha or early-access versions",
    "Pas de version alpha ni d'accès anticipé",
  ],
  "retro-only": [
    "Only retro cartridge and floppy platforms, and arcade",
    "Uniquement les plateformes rétro à cartouche ou disquette, et l'arcade",
  ],
  "no-mixed-machines": [
    "Do not mix machines in one pack (except MAME): {detail}",
    "Ne mélangez pas les machines dans un pack (sauf MAME) : {detail}",
  ],
  "release-type": [
    "Release type decided from the files: {detail} (edit the name to change it)",
    "Type de release décidé d'après les fichiers : {detail} (modifiez le nom pour le changer)",
  ],
  "install-note": [
    "An install note is mandatory unless the release is portable",
    "Une note d'installation est obligatoire sauf pour une release portable",
  ],
  "no-iptv": ["No IPTV software", "Pas de logiciel IPTV"],
  "older-version": [
    "An older version of the same generation is removed when this one is accepted",
    "Une version plus ancienne de la même génération est retirée quand celle-ci est acceptée",
  ],
  "one-per-release": [
    "One scene version, plus one repack with language or bonus options, one repacker release and one portable per scene release; a repack must be compressed and smaller than the scene release: this is {detail}",
    "Une version scene, plus un repack avec options de langue ou bonus, une release de repackeur et un portable par release scene ; un repack doit être compressé et plus petit que la release scene : ici {detail}",
  ],
  "official-training": [
    "Official video trainings only (audio at 64 kbps or more)",
    "Formations vidéo officielles uniquement (audio à 64 kbps ou plus)",
  ],
  "plugin-host": [
    "A plugin or extension needs its host software on the tracker, compatible with that version, with a link to it in the description",
    "Un plugin ou une extension exige son logiciel hôte sur le tracker, compatible avec cette version, avec un lien vers celui-ci dans la description",
  ],
  "original-crack": [
    "Find the original crack and use the cracker's or repacker's own name",
    "Retrouvez le crack d'origine et utilisez le nom d'origine du crackeur ou du repackeur",
  ],
  "update-only": [
    "An update holds only the update files (not a new full pack), states the crack used, and is one per game version",
    "Une mise à jour ne contient que les fichiers de mise à jour (pas un nouveau pack complet), indique le crack utilisé, et il n'y en a qu'une par version du jeu",
  ],
  "one-gog": ["One GOG version per game", "Une seule version GOG par jeu"],
  "one-per-console": [
    "One version per console game",
    "Une seule version par jeu console",
  ],
  region: [
    "Region {detail}: PAL/EU, NTSC/US, NTSC-J/JP or HK, one release each",
    "Région {detail} : PAL/EU, NTSC/US, NTSC-J/JP ou HK, une release chacune",
    "State the region: PAL/EU, NTSC/US, NTSC-J/JP or HK",
    "Indiquez la région : PAL/EU, NTSC/US, NTSC-J/JP ou HK",
  ],
};
// Exact BBCode field labels, matching upload_presentation.FIELDS.
const uploadPresentationFields = {
  title: "Titre",
  files: "Fichiers",
  size: "Taille totale",
  author: "Auteur",
  format: "Format",
  language: "Langue",
  duration: "Durée",
  video_codec: "Codec vidéo",
  video_bitrate: "Débit vidéo",
  video_resolution: "Résolution vidéo",
  audio_codec: "Codecs audio",
  audio_bitrate: "Débits audio",
  audio_channels: "Canaux audio",
  audio_languages: "Langues audio",
  audio: "Audio",
  subtitles: "Sous-titres",
  subtitle_formats: "Formats des sous-titres",
  subtitle_types: "Types des sous-titres",
  subtitle_languages: "Langues des sous-titres",
  source: "Source",
  platform: "Plateforme VOD",
  artist: "Artiste",
  album: "Album",
  year: "Année",
  tracks: "Pistes",
  tracklist: "Liste des pistes",
  codec: "Codec",
  bitrate: "Débit",
  sample_rate: "Fréquence",
  bit_depth: "Profondeur",
  catalogue_number: "Numéro de catalogue",
  release_link: "Discogs / MusicBrainz",
  install_size: "Taille installée",
  version: "Version",
  os: "Système",
  activation: "Activation",
  requirements: "Configuration requise",
  installation: "Installation",
  region: "Région",
  resolution: "Résolution des images",
  contents: "Contenu",
  narrator: "Narrateur",
};

// Match complete diagnostics so a conflict on the same field stays visible.
function uploadPresentationMessages(value) {
  const messages = {
    "title: Add the release title.": [
      "Add the release title.",
      "Ajoutez le titre de la release.",
    ],
    "nfo: Add the NFO describing these exact files.": [
      "Add the NFO describing these exact files.",
      "Ajoutez le NFO décrivant ces fichiers précis.",
    ],
    "description.image: Add a public HTTP(S) cover/image inside the description: [img]URL[/img].":
      [
        "Add a public HTTP(S) cover/image inside the description: [img]URL[/img].",
        "Ajoutez une couverture ou une image publique HTTP(S) dans la description : [img]URL[/img].",
      ],
    "description.synopsis: Fill the [h3]Présentation[/h3] section with a synopsis before [h3]Informations[/h3].":
      [
        "Fill the [h3]Présentation[/h3] section with a synopsis before [h3]Informations[/h3].",
        "Remplissez la section [h3]Présentation[/h3] avec un résumé avant [h3]Informations[/h3].",
      ],
    "image: Set the hosted image URL before sending.": [
      "Set the hosted image URL before sending.",
      "Renseignez l'URL de l'image hébergée avant l'envoi.",
    ],
    "description.image: Public image hosting required before sending.": [
      "Public image hosting required before sending.",
      "Hébergez l'image sur une adresse publique avant l'envoi.",
    ],
    "category: Use upload IDs, not Catalogue IDs: 1 Video, 2 Ebook, 3 Audio, 4 Apps, 5 Games, 6 Emulation, 7 GPS, 10 3D. Call get_upload_requirements() to list them.":
      [
        "Choose a supported Upload Category in Details.",
        "Choisissez une catégorie Upload prise en charge dans Détails.",
      ],
    "category: Choose a subcategory belonging to this Upload Category.": [
      "Choose a subcategory belonging to this Upload Category.",
      "Choisissez une sous-catégorie appartenant à cette catégorie Upload.",
    ],
    "description.language: Ebooks require French content. Verify the file language; do not relabel foreign content.":
      [
        "Ebooks require French content. Verify the file language; do not relabel foreign content.",
        "Les ebooks doivent être en français. Vérifiez la langue du fichier ; ne modifiez pas sa langue déclarée pour masquer un contenu étranger.",
      ],
  };
  if (Object.hasOwn(messages, value)) return messages[value];
  const description = value.match(
    /^description\.[^:]+: (Fill '([^'\n]+)' in the description: \[b\]\2 :\[\/b\] value\.)$/,
  );
  if (description)
    return [
      description[1],
      `Renseignez la rubrique '${description[2]}' dans la description : [b]${description[2]} :[/b] valeur.`,
    ];
  const nfo = value.match(
    /^nfo\.[^:]+: (NFO field missing: (.+)\. For a generated NFO use '\2 : value'\. Keep original release NFOs unaltered; obtain a complete original NFO\.)$/,
  );
  if (nfo)
    return [
      nfo[1],
      `Rubrique NFO manquante : ${nfo[2]}. Pour un NFO généré, utilisez '${nfo[2]} : valeur'. Conservez les NFO d'origine sans les modifier ; obtenez un NFO d'origine complet.`,
    ];
  const separator = value.indexOf(": ");
  const field = value.slice(0, separator),
    detail = value.slice(separator + 2);
  const key = field.replace(/^(description|nfo)\./, "");
  const label = Object.hasOwn(uploadPresentationFields, key)
    ? uploadPresentationFields[key]
    : null;
  const fill = (templates, values) =>
    templates.map((t) => t.replace(/\{(\d+)\}/g, (_, i) => values[Number(i)]));
  let match;
  if (
    field === "description.language" &&
    (match = detail.match(
      /^(.+): EPUB metadata declares (.+)\. French content is required\. Choose an eligible file, do not relabel it\.$/,
    ))
  )
    return fill(
      [
        "{0}: EPUB metadata declares {1}. French content is required. Choose an eligible file, do not relabel it.",
        "{0} : les métadonnées EPUB indiquent {1}. Le contenu doit être en français. Choisissez un fichier admissible ; ne modifiez pas sa langue déclarée.",
      ],
      match.slice(1),
    );
  if (
    field === "description.image.coverage" &&
    (match = detail.match(
      /^Selected piece missing from attached render pages: (.+)\.$/,
    ))
  )
    return fill(
      [
        "Selected piece missing from attached render pages: {0}.",
        "Pièce sélectionnée absente des planches de rendu jointes : {0}.",
      ],
      match.slice(1),
    );
  if (
    field === "description.files" &&
    (match = detail.match(/^Use the actual file count: (\d+)\.$/))
  )
    return fill(
      [
        "Use the actual file count: {0}.",
        "Indiquez le nombre réel de fichiers : {0}.",
      ],
      match.slice(1),
    );
  if (
    label &&
    field.startsWith("nfo.") &&
    (match = detail.match(
      /^NFO conflict: (.+); file facts\/presentation require (.+)\. Preserve the original NFO and obtain one for these exact files\.$/,
    ))
  )
    return fill(
      [
        "NFO, {0}: declared {1}; file facts/presentation require {2}. Preserve the original NFO and obtain one for these exact files.",
        "NFO, {0} : valeur déclarée {1} ; les fichiers ou la présentation exigent {2}. Conservez le NFO d'origine et obtenez-en un correspondant à ces fichiers précis.",
      ],
      [label, ...match.slice(1)],
    );
  if (
    label &&
    (match = detail.match(
      /^Conflicting facts: extracted (.+), declared (.+)\. Verify and correct the value or use the extracted fact\.$/,
    ))
  )
    return fill(
      [
        "{0}: conflicting facts, extracted {1}, declared {2}. Verify and correct the value or use the extracted fact.",
        "{0} : informations contradictoires, valeur extraite {1}, valeur déclarée {2}. Vérifiez et corrigez la valeur ou utilisez celle extraite du fichier.",
      ],
      [label, ...match.slice(1)],
    );
  if (
    (match = field.match(
      /^(description|nfo)\.tracklist\[(\d+)\]\.duration$/,
    )) &&
    detail ===
      "Add the duration of each track/chapter, for example 01. Title (03:42)."
  )
    return fill(
      match[1] === "nfo"
        ? [
            "NFO, track/chapter {0}: add its duration, for example 03:42.",
            "NFO, piste ou chapitre {0} : ajoutez sa durée, par exemple 03:42.",
          ]
        : [
            "Description, track/chapter {0}: add its duration, for example 03:42.",
            "Description, piste ou chapitre {0} : ajoutez sa durée, par exemple 03:42.",
          ],
      [match[2]],
    );
  return null;
}

function uploadRuleText(value) {
  const separator = value.indexOf(":");
  const code = separator < 0 ? value : value.slice(0, separator);
  const detail = separator < 0 ? "" : value.slice(separator + 1).trim();
  const rule = Object.hasOwn(uploadRuleMessages, code)
    ? uploadRuleMessages[code]
    : null;
  const messages = rule || uploadPresentationMessages(value);
  if (!messages) return value;
  const offset = !detail && messages.length === 4 ? 2 : 0;
  const en = rule
    ? messages[offset].split("{detail}").join(detail)
    : messages[0];
  const fr = rule
    ? messages[offset + 1].split("{detail}").join(detail)
    : messages[1];
  return t(fr, en);
}
