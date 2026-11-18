# Communauté

Ouvrez **Zen → Communauté**, sur ordinateur ou dans la WebUI. Installez le
compagnon mis à jour depuis Réglages → Compagnon, associez-le et gardez un onglet
c411 connecté ouvert. L'application ou le serveur doit rester actif. Les uploads
ne font pas partie de cette fonction.

Les torrents en seed et les canaux général/de classe se chargent automatiquement
à l'ouverture de Communauté. La recherche parcourt les pages en arrière-plan.
Recherchez un titre dans **Torrents**, puis sélectionnez-le pour consulter vos
actions locales, écrire un commentaire ou préparer un vote. **Actualiser la
bibliothèque** relance la recherche ; sinon le cache est renouvelé après six
heures. Aucun disque ni liste de fichiers de torrent n'est parcouru. Le site vérifie l'éligibilité avant chaque envoi.

Choisissez un commentaire, votre vote de confiance ou un message de chat.
Rédigez le texte, choisissez le canal si nécessaire et réglez **Envoyer après**
à votre heure locale. **Brouillon** ne publie rien. **Programmer** ajoute l’action à la file.
L’icône des réglages permet d’activer les envois.
Vous pouvez modifier les modèles de commentaire/chat, la limite de chaque action
et l'intervalle minimum. Par défaut, chaque action est limitée à cinq par jour,
avec 60 secondes entre commentaires/votes et 600 secondes entre messages de chat.
Les envois sont initialement désactivés. Une limite de zéro désactive l'action.

Le sélecteur français propose 200 citations, blagues et petits poèmes modifiables.
Choisir une suggestion remplit l'éditeur et son aperçu. L'auteur reste dans le texte
des citations. Les canaux général et de classe partagent le même quota de chat.
Un message de chat doit contenir au moins cinq mots ; les répétitions sont refusées.
Vous choisissez vous-même votre vote. Aucun avis positif n'est créé automatiquement.

Vous pouvez suspendre la file entière ou un élément, le passer en premier,
l'annuler ou le modifier. **Modifier** le suspend immédiatement. Une fois
réenregistré, il redevient brouillon et doit être remis en file. Les éléments
déjà en cours d'envoi ou publiés ne sont pas modifiables ici. Une suspension
ne peut pas rappeler une requête déjà envoyée au site.

La file affiche délais, compteurs du site, usage local et résultats. L'heure
indiquée est la première heure possible : le compagnon vérifie environ toutes
les 30 secondes. Le site peut imposer un délai supplémentaire ou refuser le
message. Chaque action est plafonnée à cinq par jour, avec une limite utilisateur
plus basse possible. Les quotas du site et de l'application sont remis à zéro à minuit,
heure de Paris, y compris lors des changements d'heure. L'intervalle entre
deux publications reste applicable à cheval sur minuit. Les actions
faites ailleurs sur le site consomment également le quota disponible.

La file, les modèles et les reçus survivent aux redémarrages. Le journal suit
l'identifiant du compte c411 : changer de clé API ne remet pas les garde-fous
contre les doublons à zéro. Sans navigateur connecté, les éléments attendent.
Une limitation du site conserve le délai de reprise demandé.

Si une requête a pu réussir sans réponse, l'élément devient **Incertain** et
n'est jamais renvoyé automatiquement. Vérifiez c411 avant toute autre action.
Un commentaire publié indique **XP en attente, 24 h**, puis **XP non confirmée**.
La publication ne prouve pas l'attribution d'XP. Cette version ne rattache pas
les lignes du journal XP aux publications et ne promet pas de gain Zen fixe.

## Calendrier et historique

Dans **File d’attente**, le **Calendrier** affiche les opérations par semaine ou par mois et
leur détail quotidien. L'origine manuelle ou automatique est indiquée. Ouvrez
une opération pour lire son texte, la suspendre, l'annuler ou modifier sa date.
Le bouton **Liste** affiche les cartes de la file. Le même calendrier est disponible
sur ordinateur et dans la WebUI. Les horaires locaux tiennent compte des créneaux réservés et des
limites. Ils restent estimés.

L'**Historique** conserve les textes et les changements d'état de chaque opération.
Recherchez un titre ou un message, filtrez par action et choisissez aujourd'hui,
7 jours, 30 jours, tout l'historique ou une plage de dates incluse. Parcourez les
mois puis cliquez sur un jour pour retrouver les opérations anciennes. Chaque
entrée détaille ses modifications, tentatives et reçu. **Exporter** enregistre
les opérations filtrées au format JSON.

## Mode automatique

Ouvrez **Mode automatique** au-dessus des quatre onglets de Communauté, puis
activez **Planifier automatiquement** et choisissez les commentaires, votes
préparés et/ou messages du chat. La file doit aussi être active pour envoyer.
Réglez les plafonds, intervalles, heures de publication et fuseau IANA, par exemple
`Europe/Paris`. Le planning réserve jusqu'à sept jours à l'avance.

Les commentaires utilisent votre modèle ; `{titre}` ou `{title}` insère le titre
du torrent. Les votes conservent le choix et la date enregistrés. Si les votes
automatiques sont activés, enregistrer un vote le rend disponible pour la
planification automatique. L'application ne choisit pas un avis positif à votre
place. Le chat utilise vos messages sélectionnés, un par ligne, et les canaux
choisis. Ajoutez les suggestions une par une ou collez vos propres textes. Les
deux canaux partagent un seul quota.

Désactiver une action annule ses créneaux automatiques non envoyés et conserve
les opérations manuelles. Modifier les messages ou canaux retire les anciens
créneaux du chat ; changer le modèle actualise les commentaires automatiques non
envoyés. Une annulation explicite reste respectée. Le mode et les textes choisis
sont conservés après redémarrage.
