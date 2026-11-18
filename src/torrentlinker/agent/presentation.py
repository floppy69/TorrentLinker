"""Compact owner-facing descriptions of the concrete action awaiting approval."""

import json


def _operation(event: dict) -> dict:
    """Summarize object or JSON-encoded arguments without trusting rejected call shapes."""
    for source in (event.get("review"), event.get("arguments")):
        if isinstance(source, dict):
            operation = source.get("operation")
            if isinstance(operation, str):
                try:
                    operation = json.loads(operation)
                except ValueError:
                    continue
            if (
                isinstance(operation, dict)
                and operation
                and all(
                    isinstance(operation.get(key, ""), str)
                    for key in ("kind", "action", "queue_action", "path", "client_path", "draft_id")
                )
                and isinstance(operation.get("hashes", []), list)
            ):
                return operation
    return {}


def tool_error(event: dict) -> str:
    """Recognize failed receipts, including history saved before explicit failed status."""
    result = event.get("result")
    result = result if isinstance(result, dict) else {}
    job = result.get("job")
    job = job if isinstance(job, dict) else {}
    error = event.get("error") or result.get("error") or job.get("error")
    if error:
        return str(error)[:2000]
    if event.get("status") == "failed" or job.get("status") == "failed":
        return "Tool call failed."
    return ""


def request_summary(event: dict, language: str = "en") -> list[str]:
    def say(en: str, fr: str) -> str:
        return fr if language == "fr" else en

    review = event.get("review") or {}
    operation = _operation(event)
    kind = operation.get("kind", "")
    action = operation.get("action", "")
    selection = review.get("selection") or {}
    hashes = operation.get("hashes") or []
    count = review.get(
        "torrent_instance_count",
        selection.get("selected_count", len(hashes) or len(review.get("torrents", []))),
    )
    titles = {
        "enqueue": (
            f"Add {count} torrents to the download queue.",
            f"Ajouter {count} torrents à la file de téléchargement.",
        ),
        "send-queue": (
            f"Send {count} queued torrents to the Torrent Client."
            if count
            else "Send the download queue to the Torrent Client.",
            f"Envoyer {count} torrents de la file au client torrent."
            if count
            else "Envoyer la file de téléchargement au client torrent.",
        ),
        "configure-download-folder": (
            "Set the Download Folder.",
            "Définir le Dossier de téléchargement.",
        ),
        "upload-send": (
            "Send the saved Upload draft to c411.",
            "Envoyer le brouillon d’Upload enregistré à c411.",
        ),
        "upload-queue": (
            "Save the Upload to the local draft queue.",
            "Enregistrer l’Upload dans la file des brouillons locaux.",
        ),
        "upload-remove": (
            "Remove the local Upload draft.",
            "Supprimer le brouillon d’Upload local.",
        ),
        "upload-reset": (
            "Reset the Upload draft’s send status.",
            "Réinitialiser l’état d’envoi du brouillon d’Upload.",
        ),
        "upload-seed": (
            "Seed the Upload from its existing files.",
            "Mettre l’Upload en seed depuis ses fichiers existants.",
        ),
        "reseed": (
            "Reseed the selected Match from existing files.",
            "Remettre en seed la Correspondance sélectionnée depuis les fichiers existants.",
        ),
        "plan": (
            "Build a Zen Plan within the requested limits.",
            "Créer un Plan Zen selon les limites demandées.",
        ),
        "catalogue": ("Refresh the local Catalogue.", "Actualiser le Catalogue local."),
        "refresh": ("Refresh Torrent Client data.", "Actualiser les données du client torrent."),
    }
    management = {
        "pause": (f"Pause {count} torrents.", f"Mettre {count} torrents en pause."),
        "resume": (f"Resume {count} torrents.", f"Reprendre {count} torrents."),
        "recheck": (
            f"Verify the files of {count} torrents.",
            f"Vérifier les fichiers de {count} torrents.",
        ),
        "remove": (
            f"Remove {count} torrents. Their files will be kept.",
            f"Retirer {count} torrents. Leurs fichiers seront conservés.",
        ),
        "delete": (
            f"Delete {count} torrents AND their files. Other torrents may share these files.",
            f"Supprimer {count} torrents ET leurs fichiers. "
            "D’autres torrents peuvent partager ces fichiers.",
        ),
    }
    queue_edits = {
        "remove": (
            f"Remove {count} unsent entries from the download queue.",
            f"Retirer {count} entrées non envoyées de la file de téléchargement.",
        ),
        "retry": (
            f"Return {count} failed entries to the download queue.",
            f"Remettre {count} entrées en échec dans la file de téléchargement.",
        ),
        "priority": (
            f"Set priority {operation.get('priority', 0)} for {count} queued entries.",
            f"Définir la priorité {operation.get('priority', 0)} pour {count} entrées de la file.",
        ),
    }
    title = (
        management.get(action)
        if kind == "manage"
        else queue_edits.get(operation.get("queue_action", ""))
        if kind == "edit-queue-selection"
        else titles.get(kind)
    )
    lines = (
        [say(*title)]
        if title
        else [
            say("Review the requested action: ", "Vérifier l’action demandée : ")
            + (kind or event.get("tool", ""))
        ]
    )
    groups = review.get("groups") or []
    client = review.get("client") or operation.get("client") or operation.get("client_id")
    if client and not groups:
        lines.append(say("Torrent Client: ", "Client torrent : ") + str(client))
    for group in groups:
        size = group.get("metadata_size_bytes", 0)
        lines.append(
            f"{group.get('client', group.get('client_id'))} "
            f"({group.get('client_id')}): {group.get('torrent_instance_count', 0)} "
            + say("torrent instances", "instances de torrent")
            + f", {size:,} "
            + say("metadata bytes", "octets selon les métadonnées")
        )
        targets = group.get("targets") or []
        for target in targets[:20]:
            lines.append(
                f"  {target.get('name', '')} [{target.get('hash', '')}] {target.get('folder', '')}"
            )
        if len(targets) > 20:
            lines.append(
                f"  +{len(targets) - 20} "
                + say("more targets in the full review", "autres cibles dans la revue complète")
            )
    if groups:
        lines.append(
            say(
                "Metadata sizes may include shared files; they are not reclaimable disk space.",
                "Les tailles des métadonnées peuvent inclure des fichiers partagés ; "
                "ce n'est pas de l'espace récupérable.",
            )
        )
    if kind == "configure-download-folder":
        category = operation.get("category_name") or operation.get("category")
        if operation.get("category") is None:
            category = say(
                "Default for ALL categories without a configured Download Folder",
                "Dossier par défaut pour TOUTES les catégories "
                "sans Dossier de téléchargement configuré",
            )
        lines.append(say("Category: ", "Catégorie : ") + str(category))
        lines.append(say("Folder: ", "Dossier : ") + str(operation.get("path", "")))
        if operation.get("client_path"):
            lines.append(
                say("Folder on Torrent Client: ", "Dossier côté client torrent : ")
                + operation["client_path"]
            )
    if "total_size_bytes" in selection:
        size = selection["total_size_bytes"]
        if size is None:
            lines.append(say("Total size unknown.", "Taille totale inconnue."))
        else:
            lines.append(
                say("Total size: ", "Taille totale : ")
                + f"{size / 1024**3:.2f} GiB ({size:,} "
                + say("bytes)", "octets)")
            )
    categories = (selection.get("criteria") or {}).get("categories") or []
    if categories:
        lines.append(
            say("Catalogue categories: ", "Catégories du Catalogue : ")
            + ", ".join(review.get("category_names", {}).get(str(c), str(c)) for c in categories)
        )
    if kind == "edit-queue-selection":
        lines.append(
            say(
                "Queue records only. Keeps files and Torrent Client torrents. "
                "Downloads will not start.",
                "Uniquement la file locale. Conserve les fichiers et les torrents du client. "
                "Aucun téléchargement ne démarre.",
            )
        )
    if kind == "enqueue":
        lines.append(
            say("Downloads will not start yet.", "Les téléchargements ne démarrent pas encore.")
        )
    if operation.get("path") and kind != "configure-download-folder":
        lines.append(say("Path: ", "Chemin : ") + operation["path"])
    if operation.get("draft_id"):
        lines.append(
            say("Draft: ", "Brouillon : ")
            + operation["draft_id"]
            + f" · {operation.get('revision', 0)}"
        )
    if review.get("warning"):
        lines.append(review["warning"])
    if review.get("error"):
        lines.append(say("Review unavailable: ", "Vérification indisponible : ") + review["error"])
    return lines


def request_command(event: dict) -> dict:
    """Keep original tool arguments and the resolved operation available together."""
    return {key: event[key] for key in ("tool", "arguments", "review") if key in event}


def tool_description(event: dict, language: str = "en") -> str:
    """Name the observable tool action; model commentary remains a separate message."""
    descriptions = {
        "search_indexer_options": (
            "Discover native Indexer filters",
            "Lire les filtres natifs de l’Indexeur",
        ),
        "present_upload_drafts": (
            "Show Upload draft cards",
            "Afficher les fiches des brouillons Upload",
        ),
        "present_selection": ("Show selection cards", "Afficher les fiches de la sélection"),
        "enrich_selection": ("Read selection metadata", "Lire les métadonnées de la sélection"),
        "read_selection_descriptions": (
            "Read descriptions for content review",
            "Lire les descriptions pour analyser le contenu",
        ),
        "review_selection": (
            "Save the selection after content review",
            "Enregistrer la sélection après analyse du contenu",
        ),
        "get_presentation": ("Read selection cards", "Lire les fiches de la sélection"),
        "get_presentation_item": ("Read card details", "Lire les détails de la fiche"),
        "search_indexer": ("Search the live Indexer", "Rechercher dans l’Indexeur en direct"),
        "create_torrent_list": ("Save a durable torrent list", "Enregistrer une liste de torrents"),
        "edit_torrent_list": ("Update the saved torrent list", "Modifier la liste enregistrée"),
        "get_torrent_list": ("Read the saved torrent list", "Lire la liste enregistrée"),
        "list_torrent_lists": ("Find saved torrent lists", "Retrouver les listes enregistrées"),
        "select_torrent_list": (
            "Prepare an exact saved-list selection",
            "Préparer une sélection de la liste",
        ),
        "compare_torrent_list_client": (
            "Compare the list with the torrent client",
            "Comparer la liste au client torrent",
        ),
        "classify_conversation": (
            "Organize this discussion in the sidebar.",
            "Classer cette discussion dans la barre latérale.",
        ),
        "overview": (
            "Inspect permissions and Torrent Clients.",
            "Consulter les droits et clients torrent.",
        ),
        "catalogue_categories": (
            "Read Catalogue categories and counts.",
            "Consulter les catégories et comptes du Catalogue.",
        ),
        "select_catalogue": (
            "Select Catalogue torrents and calculate exact totals.",
            "Sélectionner les torrents du Catalogue et calculer les totaux exacts.",
        ),
        "select_torrents": (
            "Select and rank Torrent Client torrents.",
            "Sélectionner et classer les torrents du client.",
        ),
        "compare_clients": (
            "Compare selected torrents across clients.",
            "Comparer les torrents sélectionnés entre clients.",
        ),
        "select_queue": (
            "Select entries from the download queue.",
            "Sélectionner les entrées de la file de téléchargement.",
        ),
        "preview_download": (
            "Check download blockers, budgets and space.",
            "Vérifier les blocages, budgets et espace disponible.",
        ),
        "prepare_download_batch": (
            "Prepare a bounded download batch.",
            "Préparer un lot de téléchargement limité.",
        ),
        "refine_selection": (
            "Keep or exclude items and save a new selection.",
            "Garder ou exclure des éléments et enregistrer une nouvelle sélection.",
        ),
        "deduplicate_selection": (
            "Keep one release per verified film.",
            "Garder une version par film identifié.",
        ),
        "compare_selections": (
            "Compare exact selections and category totals.",
            "Comparer les sélections et les totaux par catégorie.",
        ),
        "enqueue_selection": (
            "Save selected torrents to the download queue.",
            "Enregistrer la sélection dans la file de téléchargement.",
        ),
        "send_selection": (
            "Request sending the selected downloads.",
            "Demander l’envoi des téléchargements sélectionnés.",
        ),
        "edit_queue_selection": (
            "Edit the selected local queue entries.",
            "Modifier les entrées sélectionnées de la file locale.",
        ),
        "job_status": (
            "Read job progress and results.",
            "Consulter l’avancement et les résultats du travail.",
        ),
        "list_items": ("Read the saved items.", "Consulter les éléments enregistrés."),
        "search_documentation": (
            "Search the installed documentation.",
            "Rechercher dans la documentation installée.",
        ),
        "read_documentation": (
            "Read an installed guide section.",
            "Lire une section du guide installé.",
        ),
        "download_folder_options": (
            "Check verified Download Folder choices.",
            "Consulter les Dossiers de téléchargement vérifiés.",
        ),
        "ask_user": ("Ask for the missing information.", "Demander l’information manquante."),
        "search_web": ("Search for public sources.", "Rechercher des sources publiques."),
        "read_web_page": ("Read a public source.", "Lire une source publique."),
        "validate_image": ("Check a public image.", "Vérifier une image publique."),
        "lookup_metadata": (
            "Find public title metadata.",
            "Rechercher les métadonnées publiques du titre.",
        ),
        "manage_selection": (
            "Apply an action to selected Torrent Client torrents.",
            "Appliquer une action aux torrents sélectionnés du client.",
        ),
        "propose_download_folder": (
            "Propose the exact Download Folder for approval.",
            "Proposer le Dossier de téléchargement exact pour approbation.",
        ),
        "propose_action": (
            "Run the requested application action.",
            "Exécuter l’action demandée dans l’application.",
        ),
        "save_goal": (
            "Save the connection's seeding objective.",
            "Enregistrer l’objectif de seed de la connexion.",
        ),
        "goal_status": (
            "Check the saved seeding objective.",
            "Consulter l’objectif de seed enregistré.",
        ),
        "plan_goal": (
            "Prepare a Plan for the saved objective.",
            "Préparer un Plan pour l’objectif enregistré.",
        ),
        "read_assistant_history": (
            "Read earlier discussion context.",
            "Consulter le contexte des échanges précédents.",
        ),
        "cancel_job": (
            "Request stopping further job actions.",
            "Demander l’arrêt des prochaines actions du travail.",
        ),
    }
    tool = event.get("tool", "")
    arguments = event.get("arguments") or {}
    if _operation(event):
        return request_summary(event, language)[0]
    english, french = descriptions.get(tool, ("Run a tool.", "Exécuter un outil."))
    if tool == "edit_queue_selection":
        actions = {
            "remove": (
                "Remove selected unsent entries from the local queue.",
                "Retirer les entrées non envoyées de la file locale.",
            ),
            "retry": (
                "Return selected safe failures to the queue.",
                "Remettre les échecs sans envoi confirmé dans la file.",
            ),
            "priority": (
                "Change the selected entries' queue priority.",
                "Modifier la priorité des entrées sélectionnées dans la file.",
            ),
        }
        action = arguments.get("action", "")
        if isinstance(action, str):
            english, french = actions.get(action, (english, french))
    return french if language == "fr" else english
