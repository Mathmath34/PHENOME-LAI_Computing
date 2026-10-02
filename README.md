# Traitement LAI — Sentinel-2 / SL2P

Calcul de cartes de LAI (et FAPAR/FCOVER) à partir d'images Sentinel-2 L2A,
avec le réseau de neurones **SL2P** (Weiss & Baret, 2020 — algorithme
S2ToolBox / SNAP Biophysical Processor), à partir des coefficients fournis
par Marie Weiss (INRAE).

Référence : Weiss, M., & Baret, F. (2020). *ATBD for S2ToolBox Level 2
products: LAI, FAPAR, FCOVER.* Version 2.1. INRAE.
https://step.esa.int/docs/extra/ATBD_S2ToolBox_L2B_V1.1.pdf

## Installation

```bash
pip install -r requirements.txt
```

Python 3.13 (testé). `teledetection` et `pystac-client` ne sont nécessaires
que pour la source Theia STAC (voir plus bas) ; les autres dépendances
suffisent pour traiter des produits `.SAFE` locaux.

## Structure

```
Traitement_LAI/
├── commun/                        modules partages
│   ├── sl2p_network.py              reseau SL2P (lecture xlsx, application vectorisee)
│   ├── lai_pipeline.py              application du reseau a un cube bandes+angles (source-agnostique)
│   ├── s2_safe_reader.py            lecture d'un produit .SAFE local (ESA)
│   └── theia_stac_reader.py         lecture d'un produit Theia/MUSCATE en streaming (STAC)
│
├── 01_calcul_LAI/                  calcul de la carte LAI
│   ├── compute_lai_map.py           depuis un .SAFE local
│   ├── compute_lai_map_theia.py     depuis le catalogue STAC Theia (streaming, sans telechargement)
│   ├── preview_png.py               apercu PNG rapide d'une carte LAI
│   └── outputs/
│
├── 02_diff_vs_SNAP/                comparaison avec une sortie SNAP (Biophysical Processor)
│   ├── compute_diff_map.py          carte de difference (algo - SNAP)
│   ├── histogram_residus.py         histogramme des residus + quantification des ecarts
│   ├── preview_diff_png.py          apercu PNG de la carte de difference
│   └── outputs/
│
└── 03_ndvi_vs_lai/                 verification physique NDVI/LAI
    ├── scatter_ndvi_lai.py           density plot NDVI vs LAI (saturation attendue)
    └── outputs/
```

Les coefficients du réseau (`Algo_S2_V2.0_SL2T_{LAI,FAPAR,FCOVER}.xlsx`,
fournis par Marie Weiss, valables pour Sentinel-2A) sont attendus dans
`../A_Marie_Weiss_Modele/` (un niveau au-dessus de `Traitement_LAI/`).

## Utilisation

**Calculer une carte LAI depuis un `.SAFE` local :**
```bash
cd 01_calcul_LAI
python compute_lai_map.py "chemin/vers/PRODUIT.SAFE" --var LAI
```

**Calculer une carte LAI depuis le catalogue Theia STAC (sans téléchargement) :**
```bash
python compute_lai_map_theia.py --tile 31TEJ --date 2021-04-02 --var LAI
```

**Comparer à une sortie SNAP :**
```bash
cd ../02_diff_vs_SNAP
python compute_diff_map.py
python histogram_residus.py
```

**Vérifier la relation NDVI/LAI :**
```bash
cd ../03_ndvi_vs_lai
python scatter_ndvi_lai.py
```

Chaque script écrit ses sorties dans son propre dossier `outputs/`.

## Sorties

Chaque carte LAI est un GeoTIFF 1 bande (`float32`, NaN = pas de donnée),
accompagné d'un GeoTIFF de flags qualité (`_QA.tif`, `uint8`) :

| Flag | Signification |
|---|---|
| 0 | OK |
| 1 | hors du domaine de définition (réflectance hors bornes d'entraînement) |
| 2 | cas extrême (sortie clampée ou rejetée selon la tolérance du réseau) |
| 254 (Theia uniquement) | masqué par MG2/EDG (nuage/ombre/eau/neige/relief caché) |
| 255 | pas de donnée (nodata image, ou masqué SCL côté ESA) |

Chaque GeoTIFF embarque aussi des **tags de traçabilité** (lisibles via
`rasterio.open(...).tags()`, QGIS ou `gdalinfo`) : produit source, baseline
de traitement S2 (ou version produit Theia), fichier de coefficients
utilisé, date de traitement. Voir *Traçabilité* plus bas.

## Notes méthodologiques importantes

- **Géométrie d'acquisition** : les angles (zénith solaire, zénith de visée,
  azimut relatif) sont lus sur la grille fine fournie dans les métadonnées
  (mailles de 5 km, `MTD_TL.xml` côté ESA / `MTD_ALL.xml` côté Theia) et
  **interpolés en bilinéaire à l'échelle du pixel** — pas une géométrie
  recalculée depuis l'orbite/l'attitude du satellite. L'angle de visée est
  moyenné sur les détecteurs puis sur les 8 bandes utilisées, car le réseau
  n'a qu'une seule géométrie de visée en entrée. Impact mesuré de cette
  approximation face à un angle unique moyenné sur toute la tuile :
  r=0.9997, RMSE=0.018 LAI (faible mais non nul).
- **Domaine de définition** : le contrôle fin fourni dans les fichiers
  Excel originaux (grille 8D de cellules valides) s'est révélé rejeter à
  tort des cas de test pourtant valides — bug déjà présent dans le script
  d'origine, reproduit à l'identique en le portant. Remplacé ici par un
  contrôle bounding-box (réflectance dans les bornes min/max d'entraînement
  par bande), qui valide correctement les 250 cas de test de référence.
- **Correction d'offset BOA** : les produits ESA baseline ≥ N0400
  (janvier 2022) appliquent un offset (`BOA_ADD_OFFSET`, typiquement
  -1000) aux réflectances stockées. Lu dynamiquement depuis les
  métadonnées de chaque produit, pas codé en dur.
- **Validation** : implémentation vérifiée contre les 250 cas de test
  fournis par Marie Weiss (r=0.994 sur LAI) et contre une sortie réelle du
  SNAP Biophysical Processor sur 2 tuiles/dates (r=0.997, RMSE
  0.04-0.06 LAI — voir `02_diff_vs_SNAP/`).

## Traçabilité et baseline de traitement S2

La baseline de traitement ESA (`PROCESSING_BASELINE`, ex. `05.00`) ou la
version produit Theia (`PRODUCT_VERSION`) est lue depuis les métadonnées de
chaque image et écrite dans les tags du GeoTIFF produit. Objectif : pouvoir
identifier, si l'ESA ou le CNES met à jour sa chaîne de traitement
(correction atmosphérique, calibration...), quelles cartes LAI déjà
produites ont été calculées avec quelle version — et donc lesquelles
mériteraient d'être recalculées.

## Sources de données supportées

| | `.SAFE` local (ESA) | Theia STAC (CNES, streaming) |
|---|---|---|
| Récupération | téléchargement manuel ou CDSE | `api.stac.teledetection.fr`, aucun téléchargement |
| Correction atmosphérique | Sen2Cor | MAJA |
| Métadonnées | `MTD_TL.xml` + `MTD_MSIL2A.xml` | `MTD_ALL.xml` |
| Masque qualité | SCL | MG2 (bitwise) + EDG |
| Module | `commun/s2_safe_reader.py` | `commun/theia_stac_reader.py` |

Les deux sources ont été comparées sur la même tuile/date (2021-04-02,
T31TEJ) : r=0.982, RMSE=0.16 LAI — écart attendu et légitime, dû aux deux
chaînes de correction atmosphérique différentes (pas une erreur de code).

## Limites connues / pistes d'amélioration

- Le réseau SL2P fourni est spécifique à Sentinel-2A. Les coefficients
  S2B/S2C existent (Marie Weiss) mais ne sont pas encore intégrés.
- Algorithme Ma et al. (2025) — ensemble de 12 réseaux + médiane — pas
  encore implémenté (nécessite les 12 jeux de coefficients).
- Traitement non parallélisé (une tuile = un processus, ~45-65 s/tuile).
  Pour un traitement à grande échelle, voir l'architecture par blocs et
  SLURM du dossier `PHENOME-LAI/batch_lai_masse/` (pipeline distinct, voir
  comparaison méthodologique dans l'historique du projet).
