# -*- coding: utf-8 -*-
r"""Calcule une carte de LAI (ou FAPAR/FCOVER) a partir d'une image
Sentinel-2 L2A Theia/MUSCATE recuperee EN STREAMING depuis le catalogue
STAC du CNES (api.stac.teledetection.fr) -- pas de .SAFE local, comme dans
Phenome_LAI.ipynb.

Usage:
    python compute_lai_map_theia.py --tile 31TEJ --date 2021-04-02 [--var LAI]
                                     [--out sortie.tif] [--no-cloud-mask]

Equivalent de compute_lai_map.py (meme reseau SL2P, meme logique
d'application via commun/lai_pipeline.py), seule la source des donnees et
le format de metadonnees changent (commun/theia_stac_reader.py).

Difference notable avec compute_lai_map.py : le masque qualite est
construit a partir de MG2_R2 (masque geophysique bitwise) + EDG_R2 (bord
d'image) plutot que de la SCL, car les produits Theia n'ont pas de SCL.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

import numpy as np
import rasterio

HERE = os.path.dirname(os.path.abspath(__file__))       # .../work/commun
PROJECT_ROOT = os.path.dirname(HERE)                      # .../work
OUTPUT_DIR = os.path.join(HERE, "outputs")

sys.path.insert(0, HERE)
import theia_stac_reader as theia
from lai_pipeline import apply_sl2p

MODELS_DIR = os.path.join(PROJECT_ROOT, "A_Marie_Weiss_Modele")


def compute_map(tile: str, date: str, variable: str = "LAI", mask_clouds: bool = True,
                 max_cloud: float | None = None):
    print(f"[i] Recherche du produit Theia : tuile {tile}, date {date}...")
    item = theia.find_item(tile, date, max_cloud=max_cloud)
    print(f"[i] Produit retenu : {item.id} (nuages : {item.properties.get('eo:cloud_cover')}%)")

    print("[i] Lecture de MTD_ALL.xml...")
    mtd_root = theia.fetch_mtd_root(item)
    quant, nodata = theia.get_scaling(mtd_root)
    version = theia.get_product_version(mtd_root)
    print(f"[i] Version produit Theia : {version}  (quant={quant:g}, nodata={nodata:g})")

    print("[i] Lecture des 8 bandes de reflectance en streaming (20 m)...")
    bands, profile = theia.read_bands_20m(item, quant, nodata)

    print("[i] Lecture / reechantillonnage des angles soleil-visee (grille fine, par pixel)...")
    angles = theia.read_angles_20m(mtd_root, profile)

    if mask_clouds:
        print("[i] Lecture du masque qualite MG2+EDG (nuages/ombres/eau/neige/relief cache)...")
        cloud_mask = theia.read_quality_mask_20m(item, profile)
    else:
        cloud_mask = None

    h, w = profile["height"], profile["width"]
    print(f"[i] Application du reseau SL2P sur {h * w:,} pixels...".replace(",", " "))
    value_2d, flag_2d = apply_sl2p(bands, angles, profile, variable, MODELS_DIR, cloud_mask)

    n_valid = np.sum(~np.isnan(value_2d))
    print(f"[i] Pixels valides : {n_valid:,} / {h * w:,}".replace(",", " "))

    provenance = {
        "SOURCE": "Theia STAC (api.stac.teledetection.fr)",
        "SOURCE_THEIA_ITEM_ID": item.id,
        "THEIA_PRODUCT_VERSION": version,
        "S2_MGRS_TILE": tile,
        "SL2P_VARIABLE": variable,
        "SL2P_MODEL_FILE": f"Algo_S2_V2.0_SL2T_{variable}.xlsx",
        "CLOUD_MASK_APPLIED": str(mask_clouds),
        "PROCESSED_ON": datetime.datetime.now().strftime("%Y-%m-%d"),
    }
    return value_2d, flag_2d, profile, provenance


def write_outputs(value_2d, flag_2d, profile, out_path: str, provenance: dict):
    val_profile = {
        "driver": "GTiff", "height": profile["height"], "width": profile["width"],
        "count": 1, "dtype": "float32", "crs": profile["crs"], "transform": profile["transform"],
        "nodata": np.nan, "compress": "deflate",
    }
    with rasterio.open(out_path, "w", **val_profile) as dst:
        dst.write(value_2d, 1)
        dst.update_tags(**provenance)
    print(f"[OK] Carte ecrite : {out_path}")

    flag_path = os.path.splitext(out_path)[0] + "_QA.tif"
    flag_profile = val_profile.copy()
    flag_profile.update(dtype="uint8", nodata=255)
    with rasterio.open(flag_path, "w", **flag_profile) as dst:
        dst.write(flag_2d, 1)
        dst.update_tags(**provenance)
    print(f"[OK] Flags QA ecrits : {flag_path}")
    print("     (0=OK, 1=hors domaine de definition, 2=cas extreme, 255=pas de donnee/masque MG2-EDG)")
    print(f"[i] Tracabilite (tags GeoTIFF) : item Theia {provenance['SOURCE_THEIA_ITEM_ID']}, "
          f"version produit {provenance['THEIA_PRODUCT_VERSION']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tile", required=True, help="Code tuile MGRS, ex: 31TEJ")
    parser.add_argument("--date", required=True, help="AAAA-MM-JJ, ou plage AAAA-MM-JJ/AAAA-MM-JJ")
    parser.add_argument("--var", default="LAI", choices=["LAI", "FAPAR", "FCOVER"], help="Variable biophysique")
    parser.add_argument("--max-cloud", type=float, default=None, help="Filtre nuages max (%%) avant selection")
    parser.add_argument("--out", default=None, help="Fichier GeoTIFF de sortie (defaut: outputs/<item_id>_<var>.tif)")
    parser.add_argument("--no-cloud-mask", action="store_true", help="Desactive le masquage qualite MG2/EDG")
    args = parser.parse_args()

    value_2d, flag_2d, profile, provenance = compute_map(
        args.tile, args.date, variable=args.var,
        mask_clouds=not args.no_cloud_mask, max_cloud=args.max_cloud,
    )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = args.out or os.path.join(OUTPUT_DIR, f"{provenance['SOURCE_THEIA_ITEM_ID']}_{args.var}.tif")
    write_outputs(value_2d, flag_2d, profile, out_path, provenance)


if __name__ == "__main__":
    main()
