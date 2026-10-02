# -*- coding: utf-8 -*-
"""Lecture d'une image Sentinel-2 L2A Theia/MUSCATE via le catalogue STAC
du CNES (api.stac.teledetection.fr), EN STREAMING -- pas de telechargement
de .SAFE local. C'est la source utilisee dans Phenome_LAI.ipynb.

Equivalent fonctionnel de s2_safe_reader.py, mais pour ce format :
  - metadonnees dans un seul MTD_ALL.xml (schema Muscate_Metadata_Document,
    noms de balises differents de ceux d'ESA MTD_TL.xml/MTD_MSIL2A.xml)
  - bandes accedees par URL signee (teledetection.sign_inplace), lues
    directement par rasterio via /vsicurl/ (pas de fichier local)
  - nodata = valeur constante (lue dans Special_Values_List, typiquement
    -10000), pas d'offset additif comme BOA_ADD_OFFSET cote ESA
  - pas de SCL : le masque qualite equivalent est construit a partir de
    MG2_R2 (masque geophysique bitwise) + EDG_R2 (bord d'image)
  - la grille d'angles fins (23x23, pas 5 km) existe bien dans MTD_ALL.xml
    (Angles_Grids_List), comme cote ESA -- on peut donc reconstruire les
    angles par pixel exactement comme pour les produits .SAFE, et pas
    seulement une moyenne par tuile.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pystac_client
import rasterio
import requests
import teledetection
from rasterio.enums import Resampling

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2_safe_reader import _strip_ns, _read_grid, _resample_grid  # reutilise les memes helpers generiques

STAC_API_URL = "https://api.stac.teledetection.fr"
COLLECTION = "sentinel2-l2a-theia"

# Bandes requises par le reseau SL2P (noms "Marie Weiss") -> cle d'asset STAC
BAND_TO_ASSET = {
    "B3": "B03", "B4": "B04", "B5": "B05", "B6": "B06",
    "B7": "B07", "B8A": "B8A", "B11": "B11", "B12": "B12",
}

# Bits du masque geophysique MG2 (doc MUSCATE PSC-NT-411-0362-CNES) :
# bit0=eau, bit1=nuages, bit2=neige, bit3=ombre de nuage, bit4=ombre
# topographique, bit5=zone cachee par le relief, bit6/7=geometrie extreme
MG2_BAD_BITS = [0, 1, 2, 3, 4, 5]


def find_item(tile: str, date: str, max_cloud: float | None = None):
    """Cherche un produit Theia pour la tuile MGRS `tile` (ex: '31TEJ', sans
    prefixe de zone/latitude superflu) sur la date `date` ('AAAA-MM-JJ', ou
    une plage 'AAAA-MM-JJ/AAAA-MM-JJ'). S'il y a plusieurs resultats, retient
    le moins nuageux. Retourne l'item STAC deja signe (URLs pretes a l'emploi)."""
    api = pystac_client.Client.open(STAC_API_URL)
    date_range = date if "/" in date else f"{date}T00:00:00Z/{date}T23:59:59Z"

    results = api.search(
        collections=[COLLECTION],
        query={"s2:mgrs_tile": {"eq": tile}},
        datetime=date_range,
    )
    items = list(results.items())
    if max_cloud is not None:
        items = [it for it in items if it.properties.get("eo:cloud_cover", 100) <= max_cloud]
    if not items:
        raise ValueError(f"Aucun produit Theia trouve pour la tuile {tile} sur {date}")

    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    item = items[0]
    teledetection.sign_inplace(item)
    return item


def fetch_mtd_root(item) -> ET.Element:
    """Telecharge et parse MTD_ALL.xml (une seule fois ; angles, facteurs
    d'echelle et version produit en sont tous extraits)."""
    r = requests.get(item.assets["MD"].href)
    r.raise_for_status()
    return ET.fromstring(r.content)


def get_scaling(root: ET.Element) -> tuple[float, float]:
    """Retourne (valeur de quantification, valeur nodata) depuis MTD_ALL.xml."""
    quant, nodata = 10000.0, -10000.0
    for e in root.iter():
        tag = _strip_ns(e.tag)
        if tag == "REFLECTANCE_QUANTIFICATION_VALUE":
            quant = float(e.text)
        elif tag == "SPECIAL_VALUE" and e.attrib.get("name") == "nodata":
            nodata = float(e.text)
    return quant, nodata


def get_product_version(root: ET.Element) -> str:
    """Equivalent de la baseline de traitement cote ESA : PRODUCT_VERSION
    (ex. '4.0'), aussi disponible via item.properties['processing:version']."""
    for e in root.iter():
        if _strip_ns(e.tag) == "PRODUCT_VERSION":
            return e.text.strip()
    raise ValueError("Balise PRODUCT_VERSION introuvable dans MTD_ALL.xml")


def read_bands_20m(item, quant: float, nodata: float) -> tuple[dict, dict]:
    """Lit les 8 bandes en streaming (B03/B04 natives 10m reechantillonnees
    en bilineaire, les 6 autres deja natives 20m), calees sur la grille B05.
    Retourne (bands, profile) comme s2_safe_reader.read_bands_20m."""
    with rasterio.open(item.assets["B05"].href) as ref:
        target_shape = (ref.height, ref.width)
        profile = {"height": ref.height, "width": ref.width, "transform": ref.transform, "crs": ref.crs}

    bands = {}
    for name, asset_key in BAND_TO_ASSET.items():
        with rasterio.open(item.assets[asset_key].href) as src:
            dn = src.read(1, out_shape=target_shape, resampling=Resampling.bilinear).astype(np.float32)
        refl = dn / quant
        refl[dn == nodata] = np.nan
        bands[name] = refl
    return bands, profile


def read_angles_20m(root: ET.Element, dst_profile: dict) -> dict:
    """Equivalent de s2_safe_reader.read_angles_20m, adapte au schema Theia
    (MTD_ALL.xml) : meme principe (grille 5 km interpolee au pixel, visee
    moyennee sur detecteurs puis sur les 8 bandes), balises differentes."""
    geo = next(
        e for e in root.iter()
        if _strip_ns(e.tag) == "Group_Geopositioning" and e.attrib.get("group_id") == "R2"
    )
    ulx = float(next(c for c in geo if _strip_ns(c.tag) == "ULX").text)
    uly = float(next(c for c in geo if _strip_ns(c.tag) == "ULY").text)

    angles_grids = next(e for e in root.iter() if _strip_ns(e.tag) == "Angles_Grids_List")

    sun_grids = next(c for c in angles_grids if _strip_ns(c.tag) == "Sun_Angles_Grids")
    sun_zen_elem = next(c for c in sun_grids if _strip_ns(c.tag) == "Zenith")
    sun_az_elem = next(c for c in sun_grids if _strip_ns(c.tag) == "Azimuth")
    step = float(next(c for c in sun_zen_elem if _strip_ns(c.tag) == "COL_STEP").text)
    sun_zen = _read_grid(next(c for c in sun_zen_elem if _strip_ns(c.tag) == "Values_List"))
    sun_az = _read_grid(next(c for c in sun_az_elem if _strip_ns(c.tag) == "Values_List"))

    wanted_bands = set(BAND_TO_ASSET.values())  # {'B03','B04','B05','B06','B07','B8A','B11','B12'}
    vig_list = next(c for c in angles_grids if _strip_ns(c.tag) == "Viewing_Incidence_Angles_Grids_List")

    per_band_zen, per_band_cos_az, per_band_sin_az = [], [], []
    for band_block in vig_list:
        if _strip_ns(band_block.tag) != "Band_Viewing_Incidence_Angles_Grids_List":
            continue
        if band_block.attrib.get("band_id") not in wanted_bands:
            continue
        zens, cos_azs, sin_azs = [], [], []
        for vig in band_block:
            if _strip_ns(vig.tag) != "Viewing_Incidence_Angles_Grids":
                continue
            zen_elem = next(c for c in vig if _strip_ns(c.tag) == "Zenith")
            az_elem = next(c for c in vig if _strip_ns(c.tag) == "Azimuth")
            zens.append(_read_grid(next(c for c in zen_elem if _strip_ns(c.tag) == "Values_List")))
            az = _read_grid(next(c for c in az_elem if _strip_ns(c.tag) == "Values_List"))
            cos_azs.append(np.cos(np.radians(az)))
            sin_azs.append(np.sin(np.radians(az)))
        per_band_zen.append(np.nanmean(np.stack(zens, axis=0), axis=0))
        per_band_cos_az.append(np.nanmean(np.stack(cos_azs, axis=0), axis=0))
        per_band_sin_az.append(np.nanmean(np.stack(sin_azs, axis=0), axis=0))

    view_zen = np.nanmean(np.stack(per_band_zen, axis=0), axis=0)
    cos_az = np.nanmean(np.stack(per_band_cos_az, axis=0), axis=0)
    sin_az = np.nanmean(np.stack(per_band_sin_az, axis=0), axis=0)
    view_az = np.degrees(np.arctan2(sin_az, cos_az)) % 360.0

    view_zen_20m = _resample_grid(view_zen, step, ulx, uly, dst_profile)
    view_az_20m = _resample_grid(view_az, step, ulx, uly, dst_profile)
    sun_zen_20m = _resample_grid(sun_zen, step, ulx, uly, dst_profile)
    sun_az_20m = _resample_grid(sun_az, step, ulx, uly, dst_profile)
    rel_az_20m = view_az_20m - sun_az_20m

    return {
        "cos_view_zenith": np.cos(np.radians(view_zen_20m)),
        "cos_sun_zenith": np.cos(np.radians(sun_zen_20m)),
        "cos_rel_azimuth": np.cos(np.radians(rel_az_20m)),
    }


def read_quality_mask_20m(item, dst_profile: dict) -> np.ndarray:
    """Masque nuages/ombres/eau/neige/relief cache (equivalent SCL), a
    partir de MG2_R2 (bitwise) + EDG_R2 (bord d'image)."""
    H, W = dst_profile["height"], dst_profile["width"]
    with rasterio.open(item.assets["MG2_R2"].href) as src:
        mg2 = src.read(1, out_shape=(H, W), resampling=Resampling.nearest).astype(np.uint8)
    with rasterio.open(item.assets["EDG_R2"].href) as src:
        edg = src.read(1, out_shape=(H, W), resampling=Resampling.nearest).astype(np.uint8)
    bad = edg != 0
    for bit in MG2_BAD_BITS:
        bad |= (mg2 & (1 << bit)) != 0
    return bad
