# Bibliothèque et remise en seed

## Remise en seed guidée

Ouvrez **Bibliothèque → Remise en seed** sur bureau ou Web. La même liste et le panneau d’inspection montrent l’état de chaque élément. Les compteurs des étapes filtrent la liste. **Réglages** ouvre la configuration du client et **Disque** permet d’ajouter ou de parcourir des dossiers. Le bureau utilise le sélecteur natif ; le Web parcourt les racines de stockage du serveur.

**Tout enchaîner** ou **Enchaîner la sélection** fait avancer chaque élément indépendamment. Recherche et vérification peuvent travailler en parallèle dans leurs limites de ressources. Un candidat ambigu, une archive ou un fichier manquant attend votre examen sans bloquer les autres. Sélectionnez un élément pour consulter son parcours, le continuer ou ouvrir l’examen des fichiers et les réparations. La pause prend effet entre les opérations ; une vérification déjà lancée dans le client peut se terminer. Le parcours conservé peut être repris après un redémarrage.

Choisissez un **dossier de liens**, hors bibliothèque, dans les paramètres du client cible. Il doit être accessible au client ; les correspondances de chemins s’appliquent. Windows nécessite le mode développeur ou la permission de créer des liens symboliques. Les originaux conservent leurs noms et emplacements. Gardez les liens pendant le seed. Ce parcours ne télécharge pas automatiquement les fichiers manquants.

![Remise en seed guidée avec des données d’exemple](../images/web/reseed-workspace.png)


## Explorateur de dossiers et examen des candidats

La Bibliothèque propose **Remise en seed**, **Dossiers** et **Activité**. Sélectionnez un élément dans Remise en seed puis **Examiner les fichiers et les réparations** pour ouvrir la comparaison détaillée des candidats et les outils spécialisés.

Les onglets **Summary**, **Files**, **Description** et **NFO** permettent de consulter les détails. Files montre les fichiers correspondants, renommés ou absents. Une correspondance complète compare les noms et tailles ; le client torrent doit encore vérifier les hashes avant le seed. Le rejet d’un candidat est mémorisé pour cet élément local. Chercher, vérifier les fichiers ou rejeter un candidat ne lance pas de reseed.

**Folders** permet d’ajouter plusieurs dossiers et de modifier leur type de contenu et leur regroupement. Les nouveaux dossiers utilisent le mode **Automatique** : TorrentLinker trouve les sorties à toute profondeur, ouvre les dossiers de genre et de collection, garde un pack de saison entier et liste aussi chacun de ses épisodes : dépliez un pack dans la Bibliothèque pour les voir et les sélectionner. Les torrents déjà présents dans le client torrent et les tailles du Catalogue l’aident à reconnaître les dossiers de sortie. Choisissez une profondeur fixe seulement pour un dossier mal découpé : la profondeur 1 considère chaque enfant direct comme un élément local. Les dossiers existants gardent leur profondeur. Retirer un dossier de la bibliothèque conserve ses fichiers. Les paramètres donnent accès au même éditeur ; les destinations de téléchargement et les correspondances de chemins restent propres au client torrent.

Dans l’interface web, le navigateur de dossiers montre les fichiers du **serveur TorrentLinker**, dans les racines configurées, et non ceux de l’ordinateur du navigateur. Un dossier lisible peut être enregistré sans correspondance de chemins. Si le client torrent est indisponible, l’analyse indique un état de seed inconnu. Les dossiers inaccessibles conservent les éléments de leur dernière analyse.

L’interface web permet de chercher les éléments sélectionnés, revoir les candidats mémorisés, comparer les fichiers et rejeter un candidat. **Activity** permet d’annuler les tâches en cours. Les correspondances dans une archive proposent **Extraire et seeder…** dans les deux interfaces. Le WebUI affiche la destination sur le serveur TorrentLinker, la taille décompressée, le nombre de fichiers, l’espace libre et les fichiers manquants. Confirmez un candidat à la fois ; fermer ou annuler cet aperçu n’écrit rien. L’approbation expire après cinq minutes et l’archive ainsi que sa configuration sont revérifiées avant l’extraction. La boîte de dialogue et **Activity** affichent la progression et permettent l’annulation. L’annulation est disponible jusqu’au début de l’envoi au client torrent. Elle arrête l’outil et supprime sa sortie partielle ; les fichiers complets sont conservés si le reseed échoue ensuite. L’archive originale est conservée. L’approbation des renommages sur disque pour µTorrent nécessite encore l’application de bureau. Pour les archives RAR et 7z, installez 7-Zip sur le serveur TorrentLinker ou dans son conteneur.

Les paramètres affichent les destinations de téléchargement par défaut et par catégorie du client sélectionné. La destination effective tient compte de l’héritage. Enregistrer une destination vérifie sa correspondance avec un fichier seedé et conserve les autres règles.

[Documentation](../../README.md) · [English](../en/library.md)

1. Cliquez sur **Ajouter un dossier…** et choisissez son type de contenu. Gardez **Automatique** sauf si l’aperçu montre de mauvais éléments.
2. Après l’analyse, sélectionnez un Orphelin et lancez sa recherche, ou recherchez tous les Orphelins.
3. Vérifiez les Candidats trouvés. Une correspondance par taille doit encore passer la vérification par hash du client.
4. Lancez la remise en seed des correspondances complètes. Le bilan distingue les nouveaux ajouts des torrents déjà présents.

Captures de l’interface française en thème sombre, avec des données d’exemple.

![Bibliothèque et actions de remise en seed](../images/bibliotheque.png)

![Gérer les dossiers de la Bibliothèque](../images/ajouter-dossier.png)

## Ajouter des dossiers et utiliser les actions par lot

La colonne **≈ Zen/jour** affiche l'estimation actuelle de Zen pour les torrents associés aux éléments en seed ou partiellement en seed. Pour les orphelins, elle indique l'estimation du meilleur candidat vérifié. Les torrents en pause comptent pour zéro ; les estimations indisponibles restent vides. Si un torrent couvre plusieurs éléments locaux, son estimation apparaît sur chacun : il ne faut donc pas additionner cette colonne pour calculer le total de la bibliothèque.

Dans la Bibliothèque, **Ajouter un dossier…** permet de choisir un dossier, son **Type de contenu** et son **Regroupement des éléments**, sans ouvrir les Paramètres. En mode Automatique, la fenêtre indique combien d’Éléments locaux et d’épisodes elle trouve. Une recherche groupée interroge c411 une seule fois par pack. Elle vérifie ensuite chaque épisode du pack dans le Catalogue et parmi les torrents déjà téléchargés, sans consommer de recherche : le torrent d’un épisode seul est donc trouvé aussi. Un épisode n’est en seed qu’avec son propre torrent : dans un pack en seed, il affiche **Orphelin · dans un pack en seed**. Dépliez le pack et sélectionnez des épisodes pour les chercher, puis remettez-les en seed comme épisodes seuls à côté du pack. Après enregistrement, la Bibliothèque est analysée et filtrée sur le nouveau dossier. Un dossier déjà enregistré n’est pas ajouté une seconde fois.

Le XXX reste masqué tant que vous ne cochez pas **Afficher le contenu XXX** dans **Paramètres → Général** (sur le web : dans les réglages de téléchargement de la Bibliothèque). **XXX** devient alors un type de contenu pour les dossiers de bibliothèque, et la catégorie XXX de c411 apparaît dans les recherches et les Plans. Les médias des dossiers XXX n’apparaissent que dans le panneau **XXX** de Médias, jamais parmi les Films et les Séries.

**Vérifier tous les Candidats** examine les Candidats encore non vérifiés, y compris ceux masqués par les filtres, sans relancer les recherches ni les vérifications réussies. **Remettre en seed toutes les correspondances complètes** ajoute les correspondances confirmées au client torrent, puis lance la vérification par hash avant le seed. Ces actions s’exécutent en arrière-plan, avec une progression et un bouton d’annulation. Les erreurs sont regroupées pour permettre au traitement de continuer. Les torrents déjà présents dans le client sont signalés et comptés séparément des nouvelles remises en seed.

Si des correspondances complètes se trouvent dans des archives, une fenêtre indique leur taille après décompression. Choisissez **Décompresser et remettre en seed la sélection…** pour vérifier la destination et l’espace disponible d’une archive, ou l’action de remise en seed des correspondances prêtes pour ne traiter que les fichiers déjà décompressés. Le traitement par lot ne décompresse jamais les archives automatiquement.

## Remettre des fichiers existants en seed

Analysez la Bibliothèque, puis recherchez les Orphelins : les Éléments locaux qu’aucun torrent c411 présent dans votre client ne couvre. Les fichiers partagés uniquement sur d’autres trackers restent des Orphelins et peuvent donc être proposés pour du cross-seed sur c411. Un torrent est reconnu comme appartenant à c411 par son tracker, son hash dans le Catalogue ou un tag TorrentLinker. Le hash aide notamment lorsqu’un torrent n’a pas encore annoncé et n’indique aucun tracker. Seules les listes de fichiers de ces torrents sont lues. Chaque recherche consulte d’abord le Catalogue local pour trouver les torrents de la taille exacte de l’élément, puis les torrents déjà téléchargés qui contiennent des fichiers aux tailles de l’élément, quelle que soit leur taille totale : par exemple un pack de saison dont il vous manque quelques épisodes. Aucune de ces étapes ne consomme le quota horaire de recherches de c411, et l’examen indique d’où vient chaque Candidat. c411 n’est interrogé que si elles ne donnent aucune correspondance complète, ou si vous saisissez votre propre texte de recherche.

TorrentLinker compare l’arborescence de chaque Candidat aux fichiers locaux. Les correspondances complètes peuvent être remises en seed sans retélécharger leurs données. Les correspondances partielles ignorent les fichiers absents. Après vérification, elles partagent les pièces que vous avez, tous leurs fichiers étant ignorés : le client torrent ne télécharge jamais rien dans vos fichiers. S’il ne confirme pas que tous les fichiers sont ignorés, le torrent reste arrêté.

Les chemins sont renommés à l’intérieur du client torrent : les noms et le contenu de vos fichiers sur le disque restent intacts. Une vérification par hash doit réussir avant le démarrage du seed. En cas d’échec, le torrent est retiré du client sans supprimer les fichiers locaux. Deluge reprend un torrent arrêté pendant sa vérification ; TorrentLinker limite donc sa vitesse de téléchargement à 1 octet/s jusqu’à la fin de la vérification ou au démarrage de la remise en seed, pour protéger les fichiers. Voir [ADR-0009](../../adr/0009-deluge-through-its-web-ui-with-labels-and-a-speed-guard.md). Les recherches précédentes et les rejets sont conservés après redémarrage.

### Archives

Un Élément local au format `.zip`, `.rar` ou `.7z` est aussi comparé par son contenu, car les torrents partagent généralement les fichiers décompressés. Une correspondance affiche alors **Correspondance complète dans l’archive**. **Décompresser et repartager…** extrait les fichiers dans un nouveau dossier à côté de l’archive, après avoir indiqué la taille et l’espace libre, puis lance la remise en seed avec la vérification habituelle. Aucun fichier n’est écrasé. Une fois les fichiers vérifiés et le seed démarré, l’application de bureau propose de mettre l’archive à la corbeille ou de la conserver. Le WebUI conserve l’archive originale. Les Plans ne décompressent jamais d’archives.

Les archives ZIP ne demandent aucun outil supplémentaire. Les archives RAR et 7z nécessitent [7-Zip](https://www.7-zip.org/), ou unrar pour RAR ; sans cet outil, elles sont comparées comme de simples fichiers.

[Documentation](../../README.md) · [English](../en/library.md)

## Éléments de preuve et noms d’origine

Dans l’inspecteur d’un élément local, ouvrez **Éléments de preuve**, puis **Inspecter les métadonnées**. TorrentLinker compare le nom du fichier, son titre intégré et le NFO adjacent de même nom avec MediaInfo. Chaque avertissement indique sa source et son niveau de confiance. Les dimensions recadrées et les pistes audio multiples sont prises en compte. HandBrake est un simple indice de traitement ; ces contrôles ne certifient ni la source ni la team.

**Importer d’anciens torrents…** accepte jusqu’à 100 fichiers `.torrent` par lot, de 8 Mio maximum chacun. L’import est hors ligne : aucune annonce au tracker, aucun ajout au client et aucun renommage des médias. La taille exacte suggère une association ; les hashes du torrent vérifient les octets. Les associations ambiguës restent non résolues. Une modification du fichier invalide sa vérification enregistrée. Les torrents v2 et hybrides ne sont pas encore pris en charge par ce parcours.

La préparation d’upload propose **Utiliser un nom d’origine vérifié…** après vérification d’un ancien torrent. Cette action change uniquement le nom de release proposé. Examinez la liste des fichiers avant d’enregistrer le brouillon ; les noms internes d’un pack ne sont pas restaurés automatiquement. Les règles actuelles du tracker et la revue de l’uploader restent nécessaires.

## Trouver d’autres torrents pour les mêmes fichiers

**Chercher des torrents compatibles** fonctionne aussi pour les éléments déjà en seed. La recherche couvre les séries, saisons et épisodes selon les capacités de l’indexeur. Un épisode peut correspondre à un sous-ensemble d’une intégrale plus volumineuse. La recherche est limitée à 30 requêtes et 100 candidats ; un avertissement indique si cette limite rend les résultats incomplets. Les résultats ne garantissent pas une couverture exhaustive du tracker.

Sélectionnez plusieurs éléments locaux de la même série et du même type de contenu, puis **Combiner les éléments locaux sélectionnés** pour chercher un pack. Cette opération construit une liste virtuelle, sans copier les médias ni créer de liens. Elle nécessite actuellement qBittorrent et une correspondance de chemins cohérente depuis le dossier parent commun. Tous les fichiers du torrent cible doivent être présents, y compris les fichiers annexes. La vérification habituelle du client doit réussir avant le seed. Après un redémarrage, sélectionnez à nouveau les éléments pour recréer la sélection combinée.

## Réparation expérimentale sur une copie indépendante

Sélectionnez un candidat pour un fichier local unique, puis **Diagnostiquer une réparation…**. Le diagnostic lit les hashes sans modifier l’original ni contacter de pairs. Les limites initiales sont un écart de taille inférieur ou égal à 1 % et 50 Mio, au moins 90 % des octets cibles vérifiés, au plus 500 Mio manquants et au moins deux seeders annoncés. Ces valeurs prudentes sont fixes dans cette version. Les seeders annoncés et les déclarations de source/team ne garantissent ni disponibilité ni authenticité.

Pour un résultat admissible, choisissez la destination d’une copie indépendante. Dans le WebUI, ce dossier doit être monté sous une racine de stockage autorisée du serveur. TorrentLinker crée un nouveau dossier et conserve l’original intact. Il ajoute le torrent arrêté dans qBittorrent et demande une vérification. Utilisez **Actualiser la vérification**, puis **Confirmer le téléchargement dans la copie…** uniquement quand le résultat est prêt. Les autres clients et les torrents multifichiers/v2 ne sont pas encore pris en charge par la réparation.

L’estimation concerne le contenu utile manquant, pas le trafic réseau total. L’historique persiste après redémarrage ; aucune réparation en attente ne démarre automatiquement. Les opérations échouées ou incertaines nécessitent une inspection du client torrent. Les copies incomplètes sont conservées ; retirer un torrent seul ne les supprime pas. L’original reste disponible. Les tests utilisent des données synthétiques ; le taux de réussite sur des vidéothèques réelles reste à mesurer.

Avant de préparer une copie, activez explicitement la réparation expérimentale. Les essais sur des bibliothèques réelles restent à mener ; le diagnostic reste disponible sans activer les téléchargements.

## Cross-seed et indexeurs

Un cross-seed ajoute à un autre indexeur un torrent que vous avez déjà, avec les mêmes fichiers et sans téléchargement. TorrentLinker le trouve, le vérifie et l’ajoute pour vous. Cette fonction est réservée au propriétaire.

**Indexeurs.** Ouvrez **Paramètres → Indexeurs**. c411 est intégré. Ajoutez-en d’autres avec **Ajouter un indexeur Torznab** (nom, URL, clé d’API ; **Tester** lit aussi ce qu’il sait chercher), ou importez-les depuis Prowlarr ou Jackett (adresse et clé d’API, cochez ceux voulus, **Importer la sélection** ; **Resynchroniser** reprend les changements). Chaque carte montre son état, les recherches prises en charge et son rythme. TorrentLinker respecte les limites de chaque indexeur. Retirer un indexeur laisse ses cross-seeds dans votre client.

**Cross-seed automatique.** Chaque torrent terminé de votre client et chaque élément de la bibliothèque est cherché sur les autres indexeurs, par identifiant IMDb ou TMDb quand l’indexeur le permet, par nom sinon. Une correspondance complète, ou partielle couvrant au moins 95 % (seuil réglable), est ajoutée sans revue. Elle entre arrêtée, est vérifiée à 100 % par le client, puis démarrée. Les fichiers manquants sont ignorés, jamais téléchargés. Le torrent garde la catégorie et le dossier de l’original, avec les étiquettes `cross-seed` et le nom de l’indexeur. **Suspendre le cross-seed** dans les paramètres le met en pause.

**Onglet Cross-seed.** Dans **Bibliothèque → Remise en seed**, l’onglet **Cross-seed** liste ce qui a été trouvé. Filtrez par À vérifier, Ajoutés, En attente, Échecs ou Données disparues. Une correspondance partielle sous le seuil, ou dans une archive, attend votre décision : ajouter sans les fichiers manquants, décompresser et remettre en seed, ou écarter. Après un échec de vérification, **Réessayer** est possible. Si les données d’un cross-seed disparaissent, il est signalé comme orphelin ; **Retirer du client (garder les données)** le retire. Les notifications signalent les cross-seeds ajoutés, en attente et en échec.

## Captures des nouveaux outils

![Éléments de preuve dans l’examen des candidats](../images/library-evidence.png)

![Confirmation de l’extraction dans le WebUI](../images/web/web-archive-confirmation-fr.png)
