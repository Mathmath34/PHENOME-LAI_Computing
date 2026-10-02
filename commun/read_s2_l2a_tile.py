# -*- coding: utf-8 -*-
"""
read_s2_l2a_tile.py

Lecture d'un produit Sentinel-2 L2A (.SAFE) pour alimenter Compute_LAI_image :
  - angles moyens de la tuile (Sun + Viewing) depuis MTD_TL.xml
  - facteurs d'echelle (BOA_ADD_OFFSET, QUANTIFICATION_VALUE) depuis MTD_MSIL2A.xml
  - lecture des 8 bandes de reflectance a 20m avec rasterio

⚠️ IMPORTANT : ce module a ete ecrit a partir de la documentation officielle
de la structure des produits S2 (ESA/Copernicus), mais n'a PAS pu etre teste
sur un vrai produit .SAFE (aucun fichier fourni). Avant de lancer un
traitement de masse, executez-le sur UN produit et comparez visuellement
la carte LAI obtenue avec un import du meme produit dans SNAP
(plugin Biophysical Processor) - voir la checklist en bas de fichier.

Simplification assumee : l'algorithme S2ToolBox attend un angle de visee,
un angle solaire et un azimut relatif PAR PIXEL. Ici, on utilise les
angles MOYENS de la tuile (une seule valeur par tuile/date, identique pour
tous les pixels), ce qui est une approximation standard en traitement
operationnel a grande echelle : la variation d'angle de visee au sein
d'une tuile Sentinel-2 reste limitee (< 10.3° d'ouverture), donc l'impact
sur le LAI final est generalement faible comparativement a la complexite
d'une reconstruction pixel par pixel (qui necessite de fusionner les
empreintes de chaque detecteur). A valider selon la precision recherchee.
"""

import os
import glob
import xml.etree.ElementTree as ET

import numpy as np
import rasterio
from rasterio.enums import Resampling

# Bandes necessaires pour LAI/FAPAR/FCOVER, dans l'ordre attendu par le NNT,
# et leur "bandId" (index 0-based) tel qu'utilise dans les metadonnees S2
BAND_NAMES = ["B03", "B04", "B05", "B06", "B07", "B8A", "B11", "B12"]
BAND_IDS   = [2,     3,     4,     5,     6,     8,     11,    12]

# Classes de la Scene Classification Layer (SCL, livree en 20m dans les
# produits L2A) a exclure du calcul. Codes officiels ESA :
#   0=No data  1=Saturated/defective  2=Dark area pixels  3=Cloud shadows
#   4=Vegetation  5=Not vegetated  6=Water  7=Unclassified
#   8=Cloud medium proba  9=Cloud high proba  10=Thin cirrus  11=Snow
# On garde 4 (vegetation), 5 (sol nu/bati - LAI ~0, legitime) et
# 7 (non classifie - ambigu mais pas franchement mauvais). On exclut le
# reste. A ajuster selon votre tolerance (ex: retirer 2 si vous voulez
# aussi exclure les zones sombres/ombres de relief).
SCL_BAD_CLASSES = {0, 1, 3, 6, 8, 9, 10, 11}


def _local(tag):
    """Enleve le namespace XML d'un tag (ex: '{...}Mean_Sun_Angle' -> 'Mean_Sun_Angle')."""
    return tag.split("}")[-1]


def _find_all(root, name):
    return [e for e in root.iter() if _local(e.tag) == name]


def get_mean_angles(mtd_tl_path):
    """
    Lit MTD_TL.xml et renvoie les angles moyens de la tuile, en degres :
        sun_zenith, sun_azimuth, view_zenith, view_azimuth
    view_zenith/azimuth = moyenne des angles moyens des 8 bandes utilisees
    par l'algorithme (B3,B4,B5,B6,B7,B8A,B11,B12).
    """
    tree = ET.parse(mtd_tl_path)
    root = tree.getroot()

    sun_node = _find_all(root, "Mean_Sun_Angle")
    if not sun_node:
        raise ValueError(f"Balise Mean_Sun_Angle introuvable dans {mtd_tl_path}")
    sun_zenith = float(_find_all(sun_node[0], "ZENITH_ANGLE")[0].text)
    sun_azimuth = float(_find_all(sun_node[0], "AZIMUTH_ANGLE")[0].text)

    view_list = _find_all(root, "Mean_Viewing_Incidence_Angle")
    view_by_band = {}
    for node in view_list:
        band_id = int(node.attrib["bandId"])
        z = float(_find_all(node, "ZENITH_ANGLE")[0].text)
        a = float(_find_all(node, "AZIMUTH_ANGLE")[0].text)
        view_by_band[band_id] = (z, a)

    missing = [b for b in BAND_IDS if b not in view_by_band]
    if missing:
        raise ValueError(f"Angles de visee manquants pour bandId(s) {missing} dans {mtd_tl_path}")

    zeniths  = [view_by_band[b][0] for b in BAND_IDS]
    azimuths = [view_by_band[b][1] for b in BAND_IDS]
    view_zenith = float(np.mean(zeniths))
    # Moyenne circulaire pour l'azimut (evite les artefacts pres de 0/360°)
    view_azimuth = float(np.degrees(np.arctan2(
        np.mean(np.sin(np.radians(azimuths))),
        np.mean(np.cos(np.radians(azimuths)))
    )) % 360)

    return sun_zenith, sun_azimuth, view_zenith, view_azimuth


def angles_to_nnt_inputs(sun_zenith, sun_azimuth, view_zenith, view_azimuth):
    """Convertit les 4 angles (deg) en 3 entrees attendues par le NNT :
    cos(view zenith), cos(sun zenith), cos(azimut relatif)."""
    rel_azimuth = abs(sun_azimuth - view_azimuth)
    if rel_azimuth > 180:
        rel_azimuth = 360 - rel_azimuth
    cos_vz = np.cos(np.radians(view_zenith))
    cos_sz = np.cos(np.radians(sun_zenith))
    cos_ra = np.cos(np.radians(rel_azimuth))
    return cos_vz, cos_sz, cos_ra


def get_boa_scaling(mtd_msil2a_path):
    """
    Lit MTD_MSIL2A.xml et renvoie, pour chaque bandId necessaire :
        offset[band_id] (0 si absent -> produits anterieurs a la
        Processing Baseline 04.00, janvier 2022)
        quantification_value (10000 par defaut)
    """
    tree = ET.parse(mtd_msil2a_path)
    root = tree.getroot()

    quant_nodes = _find_all(root, "BOA_QUANTIFICATION_VALUE")
    quant = float(quant_nodes[0].text) if quant_nodes else 10000.0

    offsets = {b: 0.0 for b in BAND_IDS}
    for node in _find_all(root, "BOA_ADD_OFFSET"):
        band_id = int(node.attrib.get("band_id", -1))
        if band_id in offsets:
            offsets[band_id] = float(node.text)

    return offsets, quant


def find_tile_files(safe_path):
    """
    Localise, dans un produit .SAFE, le MTD_TL.xml, le MTD_MSIL2A.xml,
    et les 8 fichiers .jp2 necessaires (a 20m quand la bande existe
    nativement a 20m, sinon a 10m pour B03/B04 - reechantillonnees
    ensuite a la lecture).
    """
    # Recherche directe, puis recursive en fallback (gere le cas d'un .SAFE
    # imbrique en double suite a une extraction qui a recree un dossier
    # du meme nom a l'interieur - arrive selon l'outil d'extraction utilise)
    mtd_msil2a = (
        glob.glob(os.path.join(safe_path, "MTD_MSIL2A.xml"))
        or glob.glob(os.path.join(safe_path, "**", "MTD_MSIL2A.xml"), recursive=True)
    )
    if not mtd_msil2a:
        raise FileNotFoundError(f"MTD_MSIL2A.xml introuvable sous {safe_path} (meme en recherche recursive)")

    mtd_tl = (
        glob.glob(os.path.join(safe_path, "GRANULE", "*", "MTD_TL.xml"))
        or glob.glob(os.path.join(safe_path, "**", "GRANULE", "*", "MTD_TL.xml"), recursive=True)
    )
    if not mtd_tl:
        raise FileNotFoundError(f"MTD_TL.xml introuvable sous {safe_path} (meme en recherche recursive)")

    granule_dir = os.path.dirname(mtd_tl[0])
    img_data = os.path.join(granule_dir, "IMG_DATA")

    band_files = {}
    for name in BAND_NAMES:
        # B03/B04 existent en 10m ET 20m ; on prend directement la version 20m
        # quand elle existe (coherent avec les 6 autres bandes), sinon 10m.
        candidates = (
            glob.glob(os.path.join(img_data, "R20m", f"*_{name}_20m.jp2"))
            or glob.glob(os.path.join(img_data, "R10m", f"*_{name}_10m.jp2"))
            or glob.glob(os.path.join(img_data, "**", f"*_{name}_*.jp2"), recursive=True)
        )
        if not candidates:
            raise FileNotFoundError(f"Bande {name} introuvable sous {img_data}")
        band_files[name] = candidates[0]

    # SCL (Scene Classification Layer), native 20m - meme grille que B05
    scl_candidates = (
        glob.glob(os.path.join(img_data, "R20m", "*_SCL_20m.jp2"))
        or glob.glob(os.path.join(img_data, "**", "*_SCL_*.jp2"), recursive=True)
    )
    scl_file = scl_candidates[0] if scl_candidates else None
    if scl_file is None:
        print(f"⚠️ Bande SCL introuvable sous {img_data} - le masquage nuages/eau sera desactive pour ce produit")

    return mtd_msil2a[0], mtd_tl[0], band_files, scl_file


def read_bands_20m(band_files, offsets, quant, target_shape=None, target_transform=None, target_crs=None):
    """
    Lit les 8 bandes en reflectance BOA (0-1), reechantillonnees sur une
    grille commune a 20m (calee sur B05, deja a 20m, sauf si target_*
    est fourni explicitement).

    Retourne : bands_array (8, H, W) float32, profile rasterio (CRS,
    transform, dimensions) pour ecrire la sortie plus tard.
    """
    # Grille de reference = B05 (native 20m) si non fournie
    if target_shape is None:
        with rasterio.open(band_files["B05"]) as ref:
            target_shape = (ref.height, ref.width)
            target_transform = ref.transform
            target_crs = ref.crs

    H, W = target_shape
    out = np.empty((len(BAND_NAMES), H, W), dtype=np.float32)

    for i, (name, band_id) in enumerate(zip(BAND_NAMES, BAND_IDS)):
        with rasterio.open(band_files[name]) as src:
            dn = src.read(
                1,
                out_shape=(H, W),
                resampling=Resampling.bilinear,
            ).astype(np.float32)
        out[i] = (dn + offsets[band_id]) / quant

    profile = {"height": H, "width": W, "transform": target_transform, "crs": target_crs}
    return out, profile


# ---------------------------------------------------------------------------
# Auto-test de la logique de parsing (sur un exemple XML minimal, PAS un
# vrai produit) - permet de detecter des erreurs evidentes avant le terrain
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sz, sa, vz, va = get_mean_angles("_exemple_MTD_TL.xml")
    print(f"Sun zenith={sz}, Sun azimuth={sa}, View zenith={vz:.4f}, View azimuth={va:.4f}")
    cos_vz, cos_sz, cos_ra = angles_to_nnt_inputs(sz, sa, vz, va)
    print(f"cos(view_zenith)={cos_vz:.4f}, cos(sun_zenith)={cos_sz:.4f}, cos(rel_azimuth)={cos_ra:.4f}")
