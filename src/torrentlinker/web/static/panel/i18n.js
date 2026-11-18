"use strict";
window.TLPanel = (() => {
  let language = "fr";
  const english = {
    "Interrompu": "Interrupted",
    "Annulé": "Cancelled",
    "Échec": "Failed",
    "Partiel": "Partial",
    "Terminé": "Completed",
    "En cours": "Running",
    "En attente": "Queued",
    "Réparation": "Repair",
    "Actualisation de la réparation": "Repair update",
    "Préparation de la réparation": "Repair preparation",
    "Diagnostic de réparation": "Repair diagnosis",
    "Recherche de torrents compatibles": "Compatible torrent search",
    "Import de provenance": "Provenance import",
    "Éléments de preuve": "Provenance evidence",
    "Extraction et remise en seed": "Unpack and reseed",
    "Aperçu de l’extraction": "Unpacking preview",
    "Vérification du candidat": "Candidate verification",
    "Candidat écarté": "Candidate rejected",
    "Examen des candidats": "Candidate review",
    "Recherche de candidats": "Candidate search",
    "Analyse des dossiers": "Folder scan",
    "Analyse incomplète · éléments précédents conservés": "Scan incomplete · previous items kept",
    "Analyser pour vérifier l’accès aux fichiers": "Scan to check file access",
    "Adulte": "Adult",
    "Les prochaines transitions apparaîtront ici.": "Upcoming transitions will appear here.",
    "Chaque élément conserve ses propres étapes.": "Each item keeps its own steps.",
    "Analyser maintenant": "Scan now",
    "Les emplacements analysés par le parcours.": "Locations scanned by the workflow.",
    "Retirer de la bibliothèque": "Remove from library",
    "Il ne sera plus analysé par la bibliothèque. Tous les fichiers restent sur le disque.": "The Library will stop scanning this folder. All files stay on disk.",
    "Retirer ce dossier ?": "Remove this folder?",
    "L’analyse affinera ces résultats avec les torrents déjà en partage.": "Scanning will refine these results using already seeded torrents.",
    "Épisode inclus dans le pack": "Episode included in pack",
    "Chaque entrée à la profondeur choisie forme un élément local. Les fichiers rencontrés avant comptent aussi.": "Each entry at the chosen depth is one Local Item. Files encountered earlier also count.",
    "Les dossiers contenant une release restent entiers. Les dossiers de genres et de collections sont parcourus.": "Release folders stay whole. Genre and collection folders are opened.",
    "épisodes inclus": "included episodes",
    "éléments locaux": "Local Items",
    "Choisissez un dossier pour voir comment ses éléments seront regroupés.": "Choose a folder to preview its Local Items.",
    "Recherche des éléments locaux…": "Looking for Local Items\u2026",
    "Analyser après l’enregistrement": "Scan after saving",
    "Regroupement des éléments": "Item grouping",
    "APERÇU DES ÉLÉMENTS LOCAUX": "LOCAL ITEM PREVIEW",
    "DOSSIER DE BIBLIOTHÈQUE": "LIBRARY FOLDER",
    "Modifier le dossier": "Edit folder",
    "Retirer": "Remove",
    "Modifier": "Edit",
    "À retrouver": "Find torrents",
    Comparer: "Compare",
    "Préparer les noms": "Prepare names",
    Vérifier: "Verify",
    Compléter: "Complete",
    "En partage": "Seeding",
    " Go": " GB",
    " Mo": " MB",
    " Ko": " KB",
    "En pause": "Paused",
    "À examiner": "Needs review",
    " · en cours": " · in progress",
    "En attente · ": "Waiting · ",
    "Dossiers de bibliothèque": "Library folders",
    "Modifier les dossiers": "Edit folders",
    "+ Ajouter un dossier": "+ Add a folder",
    Automatique: "Automatic",
    "Profondeur ": "Depth ",
    "Liens prêts": "Links ready",
    "Contenu vérifié": "Content verified",
    "Vérification du client": "Client verification",
    "Chaque fichier avance à son rythme.":
      "Each item progresses at its own pace.",
    "Retrouvez, vérifiez et partagez. Intervenez seulement quand c’est nécessaire.":
      "Find, verify and share. Step in only when needed.",
    Réglages: "Settings",
    Disque: "Disk",
    " dossiers · ": " folders · ",
    "Les éléments avancent indépendamment. Les décisions attendues ne bloquent pas les autres.":
      "Items progress independently. Pending decisions do not block other items.",
    "Tous les éléments": "All items",
    "Vue d’ensemble": "Overview",
    " opérations simultanées · ": " concurrent operations · ",
    " décisions attendues": " pending decisions",
    "Vérification : 1 à la fois · Recherche : 2 maximum":
      "Verification: one at a time · Search: up to two",
    " éléments": " items",
    "Reprendre le parcours": "Resume workflow",
    "Suspendre le parcours": "Pause workflow",
    "Tout enchaîner": "Run all",
    "Client à configurer": "Client setup required",
    "Dossier de liens configuré": "Link folder configured",
    "Dossier de liens à choisir": "Choose a link folder",
    "Analyse en cours…": "Scanning…",
    "parcourir et analyser": "browse and scan",
    " en cours": " in progress",
    "Parcours suspendu": "Workflow paused",
    "Parcours actif": "Workflow running",
    "Prêt à commencer": "Ready to start",
    " sélectionnés": " selected",
    "Sélectionner la liste": "Select the list",
    "Enchaîner la sélection": "Run selected",
    Fermer: "Close",
    "L’ÉLÉMENT SÉLECTIONNÉ": "SELECTED ITEM",
    "La pause prend effet à la fin de l’opération en cours.":
      "Pausing takes effect when the current operation finishes.",
    "Examiner les fichiers et les réparations": "Review files and repairs",
    "Son parcours": "Its workflow",
    "Historique de cet élément": "Item history",
    "Un seul hash à la fois protège le disque. Les recherches continuent.":
      "One hash check at a time protects the disk. Searches continue.",
    "Les fichiers originaux conservent leurs noms.":
      "Original files keep their names.",
    "Reprendre cet élément": "Resume this item",
    "Suspendre cet élément": "Pause this item",
    "Continuer cet élément": "Continue this item",
    Manquant: "Missing",
    "Dossier de liens à conserver": "Link folder to keep",
    "01 · RÉGLAGES": "01 · SETTINGS",
    "Réglages du parcours": "Workflow settings",
    "Client cible : ": "Target client: ",
    "+ Ajouter un client": "+ Add a client",
    "Paramètres du client": "Client settings",
    "Parcourir…": "Browse…",
    "Hors bibliothèque, accessible au client. Les fichiers originaux gardent leurs noms.":
      "Outside the library, accessible to the client. Original files keep their names.",
    Enregistrer: "Save",
    "Continuer vers Disque →": "Continue to Disk →",
    "02 · DISQUE": "02 · DISK",
    "Parcourir mes dossiers": "Browse my folders",
    "Dossiers sur cet ordinateur": "Folders on this computer",
    "Dossiers accessibles au serveur TorrentLinker":
      "Folders accessible to the TorrentLinker server",
    "Parcourir mon disque maintenant": "Scan my disk now",
    "Ajouter à la bibliothèque": "Add to library",
    "Chemin accessible à TorrentLinker": "Path accessible to TorrentLinker",
    Contenu: "Content",
    Films: "Movies",
    Séries: "Series",
    Livres: "Books",
    "Jeux vidéo": "Video games",
    "Impression 3D": "3D printing",
    Autre: "Other",
    " Analyser après l’ajout": " Scan after adding",
    "Ajouter le dossier": "Add folder",
    "Sur cet ordinateur": "On this computer",
    "Sur le serveur TorrentLinker": "On the TorrentLinker server",
    "Connecter un client torrent": "Connect a torrent client",
    Nom: "Name",
    Adresse: "Address",
    Utilisateur: "Username",
    "Mot de passe": "Password",
    "Tester et ajouter": "Test and add",
    "Dossiers du serveur TorrentLinker": "TorrentLinker server folders",
    "Racines montées": "Mounted roots",
    " élément(s). Créer les liens, vérifier le contenu puis partager ? Les fichiers originaux restent inchangés.":
      " item(s). Create links, verify content and share? Original files stay unchanged.",
    "Choisissez au moins un dossier.": "Choose at least one folder.",
    "Aucun dossier configuré.": "No folders configured.",
    "Activité du parcours": "Workflow activity",
    Arrêter: "Stop",
    "Rechercher dans mes fichiers…": "Search my files…",
    Rechercher: "Search",
    "Sélectionner ": "Select ",
    "Aucun élément ici. Ajoutez un dossier ou changez le filtre.":
      "No items here. Add a folder or change the filter.",
    "Choisir ce candidat": "Choose this candidate",
    "Aucune opération enregistrée.": "No recorded operations.",
    "Choisir ce dossier": "Choose this folder",
    "Remise en seed": "Reseed",
    Dossiers: "Folders",
    Activité: "Activity",
    Bibliothèque: "Library",
    "Vérifier l’existant": "Check existing releases",
    Préparer: "Prepare",
    Présentation: "Presentation",
    Révision: "Revision",
    "Envoyer & suivre": "Send and track",
    "Aucun candidat trouvé": "No candidate found",
    "Candidats incompatibles": "Incompatible candidates",
    "Recherche incomplète": "Incomplete search",
    "Ajout manuel": "Manual addition",
    "+ Choisir un fichier": "+ Choose a file",
    "+ Choisir un dossier": "+ Choose a folder",
    " opérations en cours · ": " operations in progress · ",
    " brouillons locaux": " local drafts",
    "Envoi uniquement après votre confirmation":
      "Send only after your confirmation",
    "Un nouveau partage commence ici.": "A new share starts here.",
    "Chaque brouillon avance à son rythme.":
      "Each draft progresses at its own pace.",
    "Gardez le fil de vos partages.": "Keep track of your shares.",
    "Les recherches de votre bibliothèque suggèrent des fichiers à examiner.":
      "Library searches suggest files to review.",
    "Préparez, complétez et relisez. Vos autres brouillons continuent d’avancer.":
      "Prepare, complete and review. Your other drafts keep moving.",
    "Retrouvez les envois, les corrections attendues et leur historique.":
      "Find submissions, requested corrections and their history.",
    "Bibliothèque ou ajout manuel": "Library or manual addition",
    "Rechercher les équivalents": "Search for equivalents",
    "Fichiers et informations": "Files and information",
    "Description, NFO et images": "Description, NFO and images",
    "Relire la version enregistrée": "Review the saved version",
    "Brouillon c411 et publication": "c411 draft and publication",
    "Préparation en cours": "Preparing",
    "Vous gardez la main sur chaque envoi": "You control every submission",
    " élément(s) ·  Un candidat incompatible ne prouve pas l’absence du contenu sur c411.":
      " item(s) · An incompatible candidate does not prove the content is absent from c411.",
    "mes sources": "my sources",
    "mes brouillons": "my drafts",
    Tous: "All",
    "Sans candidat": "No candidate",
    "Candidats écartés": "Rejected candidates",
    "Ajouts manuels": "Manual additions",
    "À vérifier": "Needs checking",
    "Sources proposées": "Suggested sources",
    "Brouillons locaux": "Local drafts",
    "Origine de la suggestion": "Suggestion origin",
    "Étape actuelle": "Current stage",
    "Analyse en cours": "Analyzing",
    "Fermer l’inspecteur": "Close inspector",
    "FICHIERS D’ORIGINE": "ORIGINAL FILES",
    "Les fichiers restent à leur emplacement.":
      "Files stay in their original location.",
    "LE BROUILLON SÉLECTIONNÉ": "SELECTED DRAFT",
    "LA SOURCE SÉLECTIONNÉE": "SELECTED SOURCE",
    "Pourquoi cette suggestion ?": "Why this suggestion?",
    "Recherche encore nécessaire": "Search still needed",
    "Avant de préparer l’upload": "Before preparing the upload",
    "Les candidats examinés ne correspondent pas à vos fichiers. Vérifiez les autres éditions ou releases avant de créer le brouillon.":
      "Reviewed candidates do not match your files. Check other editions or releases before creating a draft.",
    "La recherche reste à effectuer ou à compléter. Cet élément n’est pas considéré comme absent du site.":
      "The search still needs to be done or completed. This item is not considered absent from the site.",
    "L’absence de résultat est une piste. Confirmez le contenu et vérifiez les éventuels doublons.":
      "No results is a lead. Confirm the content and check for duplicates.",
    "Voir le suivi": "View tracking",
    "Ouvrir le brouillon →": "Open draft →",
    "Révision ": "Revision ",
    "Pas encore de brouillon": "No draft yet",
    "Envois et publication": "Submissions and publication",
    "La préparation locale, le brouillon c411 et la publication sont des étapes distinctes.":
      "Local preparation, the c411 draft and publication are separate steps.",
    Actualiser: "Refresh",
    "Un problème d’envoi reste visible. Aucun nouvel envoi n’est tenté sans votre accord.":
      "Submission problems stay visible. No retry is attempted without your consent.",
    "Correction demandée": "Correction requested",
    "À compléter": "Incomplete",
    "Envoi lancé · vérifier sur c411": "Submission started · check on c411",
    "Brouillon c411": "c411 draft",
    "Envoi à vérifier": "Submission needs checking",
    "Le client cible a changé. Rouvrez Upload.":
      "The target client changed. Reopen Upload.",
    " · Révision ": " · Revision ",
    " enregistrée": " saved",
    "État : ": "State: ",
    "Vérifier ce qui existe déjà": "Check what already exists",
    "Une recherche sans résultat ne prouve pas l’absence du contenu sur le site. Examinez les éditions et formats.":
      "A search without results does not prove the content is absent from the site. Review editions and formats.",
    "Nom de la release": "Release name",
    Catégorie: "Category",
    "Sous-catégorie": "Subcategory",
    "Contenu sélectionné": "Selected content",
    "Informations techniques": "Technical information",
    "Outils de préparation": "Preparation tools",
    Choisir: "Choose",
    "Choisir…": "Choose…",
    "Description du partage · BBCode": "Share description · BBCode",
    "Insérer un modèle": "Insert a template",
    "Illustrations et captures": "Artwork and screenshots",
    "+ Ajouter une image": "+ Add an image",
    "Lien direct de l’image hébergée": "Direct link to the hosted image",
    "Postimages · le lien est inclus dans la présentation à l’enregistrement.":
      "Postimages · the link is included in the presentation when saved.",
    "Relire la révision ": "Review revision ",
    "Toute modification demande un nouvel enregistrement et une nouvelle relecture.":
      "Every change requires saving and reviewing again.",
    Fichiers: "Files",
    "Présentation enregistrée": "Saved presentation",
    "NFO enregistré": "Saved NFO",
    "La publication finale reste manuelle sur c411.":
      "Final publication remains manual on c411.",
    "Révision enregistrée": "Saved revision",
    Relecture: "Review",
    "Brouillon c411 créé": "c411 draft created",
    "Prêt pour l’envoi du brouillon ?": "Ready to send the draft?",
    Confirmée: "Confirmed",
    "À effectuer": "Pending",
    "Voir la liste": "View list",
    "← Précédente": "← Previous",
    "AJOUT MANUEL · ": "MANUAL ADDITION · ",
    "Choisir ": "Choose ",
    Chemin: "Path",
    "L’ajout prépare un brouillon local. Aucun envoi sur c411.":
      "Adding prepares a local draft. Nothing is sent to c411.",
    "Ajouter aux sources": "Add to sources",
    "CET ORDINATEUR": "THIS COMPUTER",
    "SERVEUR TORRENTLINKER": "TORRENTLINKER SERVER",
    "un fichier": "a file",
    "un dossier": "a folder",
    "Parcourez les fichiers accessibles au serveur.":
      "Browse files accessible to the server.",
    "Sélectionnez vos fichiers sur cet ordinateur.":
      "Select your files on this computer.",
    "Parcourir le serveur": "Browse server",
    "Emplacements accessibles": "Accessible locations",
    "Version enregistrée. Les nouvelles modifications restent à enregistrer.":
      "Version saved. New changes still need saving.",
    "Brouillon enregistré localement.": "Draft saved locally.",
    "Examinez les résultats puis confirmez cette source.":
      "Review the results, then confirm this source.",
    "Enregistrez les modifications avant de relire cette révision.":
      "Save changes before reviewing this revision.",
    "Relisez et confirmez cette révision.": "Review and confirm this revision.",
    "Enregistrez les nouvelles modifications avant de continuer.":
      "Save new changes before continuing.",
    "Créer ce brouillon sur c411 ?": "Create this draft on c411?",
    " · révision ": " · revision ",
    "La publication finale restera manuelle sur c411.":
      "Final publication will remain manual on c411.",
    "Confirmer l’envoi": "Confirm submission",
    "Relisez la révision enregistrée.": "Review the saved revision.",
    "Brouillons c411": "c411 drafts",
    "Choisissez une source puis examinez-la.": "Choose a source and review it.",
    "Enregistrez les nouvelles modifications avant la relecture.":
      "Save new changes before review.",
    "Vérifiez les brouillons sur c411 avant de permettre un nouvel essai.":
      "Check drafts on c411 before allowing a retry.",
    "Autorisez la fenêtre Postimages pour choisir votre image.":
      "Allow the Postimages window to choose your image.",
    "Choisissez une image dans Postimages. Son lien sera ajouté à la présentation.":
      "Choose an image in Postimages. Its link will be added to the presentation.",
    "Réponse image trop longue.": "Image response too long.",
    "Postimages n’a pas retourné de lien image valide.":
      "Postimages did not return a valid image link.",
    "Le brouillon a changé. Rouvrez le sélecteur d’image.":
      "The draft changed. Reopen the image picker.",
    "Image hébergée et ajoutée à la présentation. Enregistrez le brouillon.":
      "Image hosted and added to the presentation. Save the draft.",
    "Rechercher dans ": "Search in ",
    "Aucun élément pour ce filtre.": "No items match this filter.",
    "Examiner cette source →": "Review this source →",
    "Voir le détail →": "View details →",
    "Vos envois apparaîtront ici.": "Your submissions will appear here.",
    "Choisissez un brouillon.": "Choose a draft.",
    "Rechercher sur c411": "Search on c411",
    "Aucun résultat pour cette recherche.": "No results for this search.",
    "Recherche à effectuer.": "Search pending.",
    " J’ai examiné les résultats et retenu cette source.":
      " I reviewed the results and selected this source.",
    " J’ai relu cette version, les fichiers et les avertissements.":
      " I reviewed this version, its files and warnings.",
    "Enregistrer et continuer →": "Save and continue →",
    Brouillons: "Drafts",
    Suivi: "Tracking",
    "Créer le brouillon c411…": "Create c411 draft…",
    "↑ Remonter": "↑ Up",
    "J’ai vérifié c411, autoriser un nouvel essai":
      "I checked c411, allow a retry",
    "Parcours de l’élément sélectionné": "Selected item workflow",
    "Espaces Upload": "Upload views",
  };
  return {
    setLanguage(value) {
      language = value || language;
      document.documentElement.lang = language;
    },
    // Rerender translated dialog labels while preserving user input and focus.
    refreshForm(container, render) {
      const controls = [
        ...container.querySelectorAll("input,select,textarea,button"),
      ];
      const focused = controls.indexOf(document.activeElement);
      const values = controls.map((node) => ({
        value: node.value,
        checked: node.checked,
        selected: node.multiple
          ? [...node.selectedOptions].map((o) => o.value)
          : null,
        start: node.selectionStart,
        end: node.selectionEnd,
        click: node.onclick,
      }));
      render();
      [...container.querySelectorAll("input,select,textarea,button")].forEach(
        (node, index) => {
          const saved = values[index];
          if (!saved) return;
          if (node.matches("input,select,textarea") && node.type !== "file")
            node.value = saved.value;
          if (node.matches("input")) node.checked = saved.checked;
          if (saved.selected)
            [...node.options].forEach(
              (o) => (o.selected = saved.selected.includes(o.value)),
            );
          if (saved.click && !node.onclick) node.onclick = saved.click;
          if (index === focused) {
            node.focus({ preventScroll: true });
            if (saved.start != null)
              node.setSelectionRange(saved.start, saved.end);
          }
        },
      );
    },
    t(fr, en) {
      return language.startsWith("fr")
        ? fr
        : (en ?? (Object.hasOwn(english, fr) ? english[fr] : fr));
    },
  };
})();
