# ReleaseScore

ReleaseScore compare les caractéristiques vidéo et audio d’une release avec votre profil. La petite pastille dans Recherche affiche une estimation issue de la liste. Un point d’interrogation indique des données insuffisantes, notamment pour les saisons sans durée totale fiable. Aucune requête indexeur supplémentaire n’est effectuée.

La couleur indique le respect du profil, indépendamment du nombre : vert si les critères sont respectés, jaune si un critère manque, gris si plusieurs manquent, rouge si le plafond de taille est dépassé. L’étoile désigne le meilleur résultat vert de la page. Ouvrez une fiche pour voir le calcul MediaInfo et son explication, quand le MediaInfo est disponible. Une note ne garantit ni la qualité subjective ni la compatibilité de lecture.

Le champ **Médias propose les releases à partir de** fixe le score exigé par les rangées du tracker dans Médias (90 par défaut). Dans Paramètres → ReleaseScore, choisissez le profil actif, modifiez ou réinitialisez un profil intégré, créez, dupliquez, renommez ou supprimez vos profils. Le questionnaire d’équipement propose un profil appliqué uniquement sur votre demande. Les capacités Dolby Vision, AVI, AV1 et DTS influencent tous les profils. Les résultats et fiches ouverts sont recalculés localement. La notation Poussée reste prévue pour plus tard.

## Crédits et licence

La formule Rapide suit [ReleaseScore](https://github.com/Pilaleur/releasescore) 0.3.0 de Pila33, commit `cb65746203871d29a04acdf5447c3f662ba072cb`. TorrentLinker porte le calcul en Python. Les estimations suivent les règles documentées par l’auteur et peuvent différer sensiblement des mesures.

```text
MIT License

Copyright (c) 2026 Pila33

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

```
