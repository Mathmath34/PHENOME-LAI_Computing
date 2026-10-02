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
