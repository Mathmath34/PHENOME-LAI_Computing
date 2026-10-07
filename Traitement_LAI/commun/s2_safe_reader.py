# -*- coding: utf-8 -*-
"""Lecture d'un produit Sentinel-2 L2A (.SAFE) : les 8 bandes de
reflectance requises par le reseau SL2P (a 20 m) et les angles de
visee/soleil (grilles MTD_TL.xml, reechantillonnees sur la grille 20 m).
"""
from __future__ import annotations

import glob
import os
import warnings
import xml.etree.ElementTree as ET

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from affine import Affine

BAND_TO_FILESUFFIX = {
    "B3": "B03_20m", "B4": "B04_20m", "B5": "B05_20m", "B6": "B06_20m",
    "B7": "B07_20m", "B8A": "B8A_20m", "B11": "B11_20m", "B12": "B12_20m",
}
# bandId Sentinel-2 (ordre S2 MTD, 0-indexe) pour les 8 bandes utilisees
BAND_TO_BANDID = {"B3": 2, "B4": 3, "B5": 4, "B6": 5, "B7": 6, "B8A": 8, "B11": 11, "B12": 12}


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1]


def find_granule_dir(safe_root: str) -> str:
    """Trouve le dossier GRANULE/<tuile>/ contenant MTD_TL.xml, meme si
    le .SAFE est imbrique dans un dossier du meme nom (cas frequent apres
    une decompression manuelle)."""
    matches = glob.glob(os.path.join(safe_root, "**", "MTD_TL.xml"), recursive=True)
    if not matches:
        raise FileNotFoundError(f"MTD_TL.xml introuvable sous {safe_root}")
    return os.path.dirname(matches[0])


def find_product_mtd(safe_root: str) -> str:
    matches = glob.glob(os.path.join(safe_root, "**", "MTD_MSIL2A.xml"), recursive=True)
    if not matches:
        raise FileNotFoundError(f"MTD_MSIL2A.xml introuvable sous {safe_root}")
    return matches[0]


def read_boa_offsets(mtd_product_path: str) -> tuple[dict, float]:
    """Retourne (offsets par bandId, valeur de quantification BOA).
    Necessaire depuis la baseline de traitement N0400 (avril 2022) qui
    ajoute un offset (-1000) aux reflectances stockees."""
    tree = ET.parse(mtd_product_path)
    root = tree.getroot()
    offsets = {}
    quant = 10000.0
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        if tag == "BOA_QUANTIFICATION_VALUE":
            quant = float(elem.text)
        elif tag == "BOA_ADD_OFFSET":
            offsets[int(elem.attrib["band_id"])] = float(elem.text)
    return offsets, quant


def read_processing_baseline(mtd_product_path: str) -> str:
    """Retourne la baseline de traitement S2 (ex. '05.12', soit N0512 dans
    le nom du produit) depuis MTD_MSIL2A.xml. A associer a toute production
    LAI pour pouvoir la ratracer si l'ESA met a jour sa chaine de traitement
    (Sen2Cor, calibration...) -- cf. balise PROCESSING_BASELINE."""
    tree = ET.parse(mtd_product_path)
    root = tree.getroot()
    for elem in root.iter():
        if _strip_ns(elem.tag) == "PROCESSING_BASELINE":
            return elem.text.strip()
    raise ValueError(f"Balise PROCESSING_BASELINE introuvable dans {mtd_product_path}")


def read_bands_20m(granule_dir: str) -> tuple[dict, dict]:
    """Lit les 8 bandes a 20 m, corrige l'offset BOA, renvoie les
    reflectances en float32 (NaN = pas de donnee) ainsi que le profil
    rasterio (crs, transform, taille) de la grille commune."""
    img_dir = os.path.join(granule_dir, "IMG_DATA", "R20m")
    mtd_product = find_product_mtd(_guess_safe_root(granule_dir))
    offsets, quant = read_boa_offsets(mtd_product)

    bands = {}
    profile = None
    for name, suffix in BAND_TO_FILESUFFIX.items():
        candidates = glob.glob(os.path.join(img_dir, f"*_{suffix}.jp2"))
        if not candidates:
            raise FileNotFoundError(f"Bande {name} ({suffix}) introuvable dans {img_dir}")
        with rasterio.open(candidates[0]) as ds:
            dn = ds.read(1).astype(np.float32)
            if profile is None:
                profile = ds.profile.copy()
        offset = offsets.get(BAND_TO_BANDID[name], 0.0)
        refl = (dn + offset) / quant
        refl[dn == 0] = np.nan  # 0 = no-data Sentinel-2
        bands[name] = refl
    return bands, profile


def _guess_safe_root(granule_dir: str) -> str:
    # granule_dir = .../GRANULE/<tile>  -> remonte jusqu'au dossier .SAFE
    d = granule_dir
    for _ in range(10):
        parent = os.path.dirname(d)
        if os.path.basename(parent) == "GRANULE":
            return os.path.dirname(parent)
        d = parent
    raise FileNotFoundError("Impossible de remonter jusqu'au dossier .SAFE depuis " + granule_dir)


def _read_grid(values_list_elem) -> np.ndarray:
    rows = values_list_elem.findall("VALUES")
    return np.array([[float(v) for v in r.text.split()] for r in rows], dtype=np.float64)


def _resample_grid(grid: np.ndarray, step_m: float, ulx: float, uly: float,
                    dst_profile: dict) -> np.ndarray:
    src_transform = Affine(step_m, 0.0, ulx, 0.0, -step_m, uly)
    dst = np.full((dst_profile["height"], dst_profile["width"]), np.nan, dtype=np.float64)
    reproject(
        source=grid,
        destination=dst,
        src_transform=src_transform,
        src_crs=dst_profile["crs"],
        dst_transform=dst_profile["transform"],
        dst_crs=dst_profile["crs"],
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return dst


def read_angles_20m(mtd_tl_path: str, dst_profile: dict) -> dict:
    """Reconstruit, sur la grille 20 m cible, les angles necessaires au
    reseau SL2P : cos(zenith visee), cos(zenith soleil), cos(azimut relatif).

    Le zenith/azimut de visee est moyenne sur les detecteurs (mosaique de
    detecteurs, zones disjointes) puis sur les 8 bandes utilisees (comme le
    fait le processeur biophysique SNAP, la geometrie de visee variant tres
    legerement d'une bande a l'autre selon le plan focal)."""
    tree = ET.parse(mtd_tl_path)
    root = tree.getroot()
    tile_angles = next(e for e in root.iter() if _strip_ns(e.tag) == "Tile_Angles")

    geo = next(
        e for e in root.iter()
        if _strip_ns(e.tag) == "Geoposition" and e.attrib.get("resolution") == "20"
    )
    ulx, uly = float(geo.find("ULX").text), float(geo.find("ULY").text)

    # --- Angles solaires : une seule grille pour toute la tuile ---
    sun = tile_angles.find("Sun_Angles_Grid")
    sun_zen_elem = sun.find("Zenith")
    sun_az_elem = sun.find("Azimuth")
    step = float(sun_zen_elem.find("COL_STEP").text)
    sun_zen = _read_grid(sun_zen_elem.find("Values_List"))
    sun_az = _read_grid(sun_az_elem.find("Values_List"))

    # --- Angles de visee : par bande x detecteur, a moyenner ---
    wanted_band_ids = set(BAND_TO_BANDID.values())
    per_band_zen = {b: [] for b in wanted_band_ids}
    per_band_cos_az = {b: [] for b in wanted_band_ids}
    per_band_sin_az = {b: [] for b in wanted_band_ids}

    for vig in tile_angles.findall("Viewing_Incidence_Angles_Grids"):
        band_id = int(vig.attrib["bandId"])
        if band_id not in wanted_band_ids:
            continue
        zen = _read_grid(vig.find("Zenith").find("Values_List"))
        az = _read_grid(vig.find("Azimuth").find("Values_List"))
        per_band_zen[band_id].append(zen)
        per_band_cos_az[band_id].append(np.cos(np.radians(az)))
        per_band_sin_az[band_id].append(np.sin(np.radians(az)))

    # Certaines cellules de la grille 5 km ne sont couvertes par AUCUN
    # detecteur (bord de fauchee, coins hors de l'empreinte du capteur) :
    # nanmean y moyenne un vecteur entierement NaN, ce qui est le
    # comportement voulu (-> NaN -> NODATA en sortie) mais declenche un
    # RuntimeWarning "Mean of empty slice" bruyant et attendu ici.
    band_zen_grids, band_cos_az_grids, band_sin_az_grids = [], [], []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        for band_id in wanted_band_ids:
            stacked_zen = np.stack(per_band_zen[band_id], axis=0)
            band_zen_grids.append(np.nanmean(stacked_zen, axis=0))
            band_cos_az_grids.append(np.nanmean(np.stack(per_band_cos_az[band_id], axis=0), axis=0))
            band_sin_az_grids.append(np.nanmean(np.stack(per_band_sin_az[band_id], axis=0), axis=0))

        view_zen = np.nanmean(np.stack(band_zen_grids, axis=0), axis=0)
        cos_az = np.nanmean(np.stack(band_cos_az_grids, axis=0), axis=0)
        sin_az = np.nanmean(np.stack(band_sin_az_grids, axis=0), axis=0)
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


def read_scl_20m(granule_dir: str, dst_profile: dict) -> np.ndarray:
    """Lit la Scene Classification Layer (deja a 20 m, meme grille)."""
    img_dir = os.path.join(granule_dir, "IMG_DATA", "R20m")
    candidates = glob.glob(os.path.join(img_dir, "*_SCL_20m.jp2"))
    if not candidates:
        raise FileNotFoundError(f"SCL introuvable dans {img_dir}")
    with rasterio.open(candidates[0]) as ds:
        return ds.read(1)
