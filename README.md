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
- **Marie Weiss** (INRAE) — autrice du réseau SL2P / fichiers de coefficients,
  script original `Read_NNT_Files_Magellium.py`
- **Jean-Baptiste Féret** — co-créateur de PROSAIL, retours sur le calcul des
  angles par pixel
