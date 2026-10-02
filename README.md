# PHENOME-LAI

Calcul de cartes de LAI (Leaf Area Index — et accessoirement FAPAR/FCOVER) à partir
d'images Sentinel-2 L2A, par application directe du réseau de neurones **SL2P**
(S2ToolBox, Weiss & Baret — ATBD v2.1), le même algorithme que celui embarqué dans
le **Biophysical Processor** de SNAP/S2TBX.

> Le réseau est **pré-entraîné** (coefficients fournis par Marie Weiss, INRAE, sous
> forme de fichiers `.xlsx`). PROSAIL n'est **pas** inversé à l'exécution : on
> applique un perceptron à 2 couches (5 neurones cachés, activation `tansig`) déjà
> entraîné hors-ligne sur des simulations PROSAIL/SAIL.

---

## Sommaire

- [Principe](#principe)
- [Deux sources de données](#deux-sources-de-données)
- [Structure du dépôt](#structure-du-dépôt)
- [Installation](#installation)
- [Utilisation rapide](#utilisation-rapide)
- [Traitement de masse avec Dask / Onyxia](#traitement-de-masse-avec-dask--onyxia)
- [⚠️ Décision en attente](#️-décision-en-attente)
- [Validation vs SNAP](#validation-vs-snap)
- [Limites connues et points de vigilance](#limites-connues-et-points-de-vigilance)
- [Prochaines étapes](#prochaines-étapes)
- [Contacts](#contacts)

---

## Principe

Pour chaque pixel, le réseau SL2P prend en entrée **11 valeurs** :

- 8 bandes de réflectance Sentinel-2 à 20 m : B3, B4, B5, B6, B7, B8A, B11, B12
- 3 angles (cosinus) : zénith de visée, zénith solaire, azimut relatif

et renvoie la variable biophysique demandée (LAI, FAPAR ou FCOVER) + un code de
qualité indiquant si le pixel est dans le domaine de définition du réseau.

Les coefficients (poids, biais, bornes de normalisation en entrée/sortie) sont
lus depuis les fichiers `A_Marie_Weiss_Modele/Algo_S2_V2.0_SL2T_<VARIABLE>.xlsx`
(mêmes fichiers que ceux utilisés par SNAP). **Seuls les coefficients S2A sont
actuellement utilisés**, voir [Limites connues](#limites-connues-et-points-de-vigilance).

## Deux sources de données

Le projet peut lire les images Sentinel-2 L2A de deux façons :

1. **Produits ESA `.SAFE` locaux** (téléchargés depuis le Copernicus Data Space) :
   lecture de `MTD_MSIL2A.xml` (facteur d'échelle BOA) et `MTD_TL.xml` (angles
   moyens par tuile), masquage via la bande SCL.
2. **Streaming THEIA/MUSCATE via STAC** (`api.stac.teledetection.fr`, correction
   CNES/MAJA) : **aucun téléchargement local** — les bandes sont lues directement
   en flux (`rasterio` + GDAL `vsicurl`). Lecture de `MTD_ALL.xml`, masquage via
   MG2 (masque géophysique bitwise) + EDG (bord d'image), angles recalculés
   **par pixel** par interpolation de la grille fine d'angles plutôt qu'une
   valeur moyenne unique par tuile.

C'est le pipeline STAC/THEIA qui est utilisé pour le traitement de masse (pas de
gestion de stockage local de `.SAFE`).

## Structure du dépôt

## Installation

```bash
pip install rasterio numpy pandas openpyxl pystac-client dask distributed matplotlib
```

Variables d'environnement recommandées pour la lecture en streaming (évite les
blocages / lectures tronquées sur certains réseaux) :

```bash
export GDAL_HTTP_TIMEOUT=120
export GDAL_HTTP_CONNECTTIMEOUT=30
export GDAL_HTTP_MAX_RETRY=5
export GDAL_HTTP_RETRY_DELAY=3
```

## Utilisation rapide

### Depuis la ligne de commande

```bash
python commun/compute_lai_map_theia.py --tile 31TEJ --date 2021-04-02 --var LAI
```

Produit deux fichiers dans `commun/outputs/` :

- `<item_id>_LAI.tif` — carte de LAI (float32, NaN = nodata)
- `<item_id>_LAI_QA.tif` — carte de flags qualité :
  - `0` = OK
  - `1` = hors domaine de définition
  - `2` = cas extrême
  - `255` = pas de donnée / masqué (MG2 ou EDG)

### Depuis un notebook

```python
import sys
sys.path.insert(0, "commun")
from compute_lai_map_theia import compute_map, write_outputs

value_2d, flag_2d, profile, provenance = compute_map("31TEJ", "2021-04-02")
write_outputs(value_2d, flag_2d, profile, "commun/outputs/test_LAI.tif", provenance)
```

Chaque GeoTIFF produit embarque des **tags de traçabilité** (item STAC source,
version du produit THEIA, tuile, variable, fichier de coefficients utilisé,
masquage nuages appliqué ou non, date de traitement).

**Benchmark observé** : ~1358 s (≈ 22,6 min) pour une tuile complète à une date
donnée (31TEJ, ~30,1 millions de pixels à 20 m), essentiellement dominé par la
lecture réseau des 8 bandes en streaming — c'est ce chiffre qui sert de base au
dimensionnement Dask ci-dessous.

## Traitement de masse avec Dask / Onyxia

Objectif final : composites annuels sur la France métropolitaine + DROM-COM,
pour toutes les années disponibles depuis le lancement de Sentinel-2
(2015/2017 → aujourd'hui), en parallélisant sur un cluster Dask lancé depuis
Onyxia/SSPCloud.

### Lancer le cluster

Sur Onyxia, lancer un service **Dask** (distinct du service Jupyter-python),
récupérer l'adresse du scheduler (`tcp://<ip>:8786`), puis dans le notebook :

```python
from dask.distributed import Client
client = Client("tcp://10.233.113.9:8786")
print(client)
```

### ⚠️ Alignement des versions client/scheduler

Les workers du cluster Dask tournent avec des versions figées des paquets
(`dask`, `distributed`, `numpy`, `pandas`, `cloudpickle`, `msgpack`, `tornado`).
Une version client trop récente casse la connexion (`TypeError:
Scheduler.identity() got an unexpected keyword argument 'n_workers'`).

Fix appliqué : aligner le client sur les versions du scheduler, par exemple :

```bash
pip install distributed==2024.1.1 dask==2024.1.1
```

puis **redémarrer le kernel**. Un `VersionMismatchWarning` au moment de la
connexion liste précisément les paquets encore désalignés (dans notre cas :
`numpy`, `pandas`, `cloudpickle`, `msgpack`, `tornado`, `python`) — à vérifier
et aligner avant un run de masse, numpy/pandas étant les plus à risque pour la
cohérence des résultats numériques.

### Soumettre les tâches

```python
futures = client.map(
    lambda tile_date: compute_map(*tile_date),
    liste_de_couples_tuile_date,
)
results = client.gather(futures)
```

### Dimensionnement

Avec un run mono-tâche à ~22,6 min/tuile×date, le temps total dépend
directement du **nombre de tâches** à soumettre, qui dépend lui-même de la
granularité choisie (voir section suivante). Le nombre de workers à demander
sur Onyxia se dimensionne ensuite en fonction du temps total voulu et de la
limite de ressources du quota du projet.

## ⚠️ Décision en attente

**Granularité des tâches Dask : une tâche par date, ou une tâche par
tuile×année (composite) ?**

Cette question est actuellement posée à Marie Weiss / Jean-Baptiste Féret ;
réponse à venir. Elle conditionne :

- le nombre total de tâches à soumettre au cluster,
- donc le nombre de workers à dimensionner,
- et la stratégie de composite annuel (moyenne/médiane/max-NDVI des LAI
  valides sur l'année, à définir une fois la granularité tranchée).

**Ne pas lancer le traitement de masse complet avant d'avoir cette réponse.**

## Validation vs SNAP

Le pipeline Python est comparé pixel à pixel à la sortie officielle du
**Biophysical Processor** de SNAP (même algorithme SL2P), sur les mêmes
tuile/date, pour fiabiliser l'implémentation avant le passage à l'échelle.

### Export GeoTIFF depuis SNAP — piège à connaître

L'export direct depuis l'interface SNAP (Raster > Geometric > Reprojection
puis export GeoTIFF) peut produire un fichier **sans géoréférencement
exploitable** par `rasterio`/GDAL standard (CRS absent, transform identité,
0 GCP) : SNAP utilise en interne un export par grille de géolocalisation non
standard, que le driver `GTiff` classique ne sait pas relire correctement.

**Solution qui fonctionne** :

1. Exporter le produit reprojeté au format **BEAM-DIMAP** (pas GeoTIFF direct).
2. Convertir en ligne de commande avec `pconvert.exe` (pas `pconvert.bat`,
   absent de cette installation) :

```bash
   pconvert.exe -f tifp chemin\vers\produit.dim
```

Le `.tif` obtenu est alors correctement géoréférencé et lisible par `rasterio`.

> **Point non résolu** : sur un essai, le `.tif` converti faisait 1831×1831 px
> (résolution ≈ 60 m) au lieu des 5490×5490 px (20 m) attendus. Cause non
> identifiée — à surveiller lors de l'interprétation des cartes de différence
> (`diff_map.py` reprojette automatiquement B sur la grille de A, donc une
> incohérence de résolution ne lèvera pas d'erreur mais peut dégrader la
> comparaison).

### Carte de différence

`diff_map.py` calcule une carte de différence pixel à pixel entre deux
GeoTIFF, en reprojetant automatiquement le second sur la grille du premier si
CRS/transform/dimensions diffèrent (`rasterio.warp.reproject`,
`Resampling.nearest`). Validé sur données synthétiques avec un biais connu
(le biais injecté est retrouvé exactement).

## Limites connues et points de vigilance

- **Coefficients S2A uniquement** : le pipeline applique toujours les poids
  S2A, quel que soit le satellite réel ayant acquis l'image (S2A/S2B/S2C).
  Marie Weiss a indiqué disposer des coefficients S2B/S2C sur demande — à
  intégrer avec une sélection du modèle basée sur `item.properties["platform"]`.
- **Couverture DROM-COM STAC non confirmée** : le catalogue
  `api.stac.teledetection.fr` n'a renvoyé aucune tuile pour la Guadeloupe, la
  Martinique, la Guyane, La Réunion et Mayotte lors des tests. Une alternative
  à tester : `geodes-portal.cnes.fr/api/stac`.
- **Version d'algorithme** : un script de référence Sentinel Hub consulté en
  cours de projet correspond à une version de l'algorithme légèrement
  différente — à garder à l'esprit en cas d'écart avec d'autres
  implémentations externes (ce n'est pas comparable 1:1 à SNAP sans vérifier
  la version).
- **Interprétation saisonnière du LAI** : un LAI faible en été en zone
  méditerranéenne (dormance estivale) est un comportement écologique attendu,
  pas une anomalie du pipeline. Les comparaisons de validation privilégient un
  contraste printemps/forêt, plus discriminant.
- **Contrôle de domaine de définition désactivé** : la vérification explicite
  du domaine de définition du réseau (bornes multivariées d'entraînement, pas
  seulement un clipping par variable) s'est révélée peu fiable et a été
  retirée de `Compute_LAI.py` / `Compute_LAI_image.py`. Le flag `1` renvoyé
  actuellement reflète un simple dépassement des bornes de normalisation par
  variable, pas une vraie estimation de distance au domaine d'entraînement.
- **Alignement des versions Dask** : voir section dédiée ci-dessus — à
  reconfirmer avant tout run de masse.

## Prochaines étapes

- [ ] Réponse de Marie Weiss / Jean-Baptiste Féret sur la granularité des
      tâches Dask (par date vs par tuile×année)
- [ ] Récupérer les coefficients S2B/S2C auprès de Marie Weiss et brancher la
      sélection de modèle par satellite
- [ ] Résoudre la couverture DROM-COM (tester `geodes-portal.cnes.fr/api/stac`)
- [ ] Confirmer l'alignement numpy/pandas entre client et workers Dask
- [ ] Étendre la découverte de tuiles à la France entière + DROM-COM
- [ ] Lancer le traitement de masse complet une fois la granularité et le
      dimensionnement des workers décidés
- [ ] Clarifier la résolution anormale (1831×1831 au lieu de 5490×5490) sur
      les exports SNAP convertis via `pconvert`

## Contacts

- **Marie Weiss** (INRAE) — autrice du réseau SL2P / fichiers de coefficients,
  script original `Read_NNT_Files_Magellium.py`
- **Jean-Baptiste Féret** — co-créateur de PROSAIL, retours sur le calcul des
  angles par pixel
