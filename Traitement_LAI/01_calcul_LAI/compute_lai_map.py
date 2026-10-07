# -*- coding: utf-8 -*-
r"""Calcule une carte de LAI (ou FAPAR/FCOVER) a partir d'un produit
Sentinel-2 L2A (.SAFE), avec le reseau de neurones SL2P de Marie Weiss
(algorithme S2ToolBox / SNAP Biophysical Processor, Weiss & Baret 2020).

Usage:
    python compute_lai_map.py "<dossier>.SAFE" [--var LAI] [--out sortie.tif]
                               [--no-cloud-mask]

Exemple:
    python compute_lai_map.py ^
        "..\..\Images_SAFE\S2A_MSIL2A_20210402T104021_N0500_R008_T31TEJ_20230510T222312.SAFE"

Structure du dossier :
    Traitement_LAI/
        commun/                 modules partages (reseau SL2P, lecture .SAFE)
        01_calcul_LAI/          ce script + outputs/ (cartes LAI + QA)
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

import numpy as np
import rasterio

HERE = os.path.dirname(os.path.abspath(__file__))
TRAITEMENT_LAI_DIR = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(TRAITEMENT_LAI_DIR)
OUTPUT_DIR = os.path.join(HERE, "outputs")

sys.path.insert(0, os.path.join(TRAITEMENT_LAI_DIR, "commun"))
import s2_safe_reader as s2
from lai_pipeline import apply_sl2p, SCL_BAD_CLASSES

MODELS_DIR = os.path.join(PROJECT_ROOT, "A_Marie_Weiss_Modele")


def compute_map(safe_root: str, variable: str = "LAI", mask_clouds: bool = True):
    granule_dir = s2.find_granule_dir(safe_root)
    mtd_tl_path = os.path.join(granule_dir, "MTD_TL.xml")
    print(f"[i] Granule : {granule_dir}")

    mtd_product = s2.find_product_mtd(safe_root)
    baseline = s2.read_processing_baseline(mtd_product)
    print(f"[i] Baseline de traitement S2 : {baseline}")

    print("[i] Lecture des 8 bandes de reflectance (20 m)...")
    bands, profile = s2.read_bands_20m(granule_dir)

    print("[i] Lecture / reechantillonnage des angles soleil-visee...")
    angles = s2.read_angles_20m(mtd_tl_path, profile)

    if mask_clouds:
        print("[i] Lecture de la SCL pour le masque nuages/ombres/eau...")
        scl = s2.read_scl_20m(granule_dir, profile)
        cloud_mask = np.isin(scl, list(SCL_BAD_CLASSES))
    else:
        cloud_mask = None

    h, w = profile["height"], profile["width"]
    print(f"[i] Application du reseau SL2P sur {h * w:,} pixels...".replace(",", " "))
    value_2d, flag_2d = apply_sl2p(bands, angles, profile, variable, MODELS_DIR, cloud_mask)

    n_valid = np.sum(~np.isnan(value_2d))
    print(f"[i] Pixels valides : {n_valid:,} / {h * w:,}".replace(",", " "))

    provenance = {
        "SOURCE_SAFE_PRODUCT": os.path.basename(safe_root.rstrip("\\/")),
        "S2_PROCESSING_BASELINE": baseline,
        "SL2P_VARIABLE": variable,
        "SL2P_MODEL_FILE": f"Algo_S2_V2.0_SL2T_{variable}.xlsx",
        "CLOUD_MASK_APPLIED": str(mask_clouds),
        "PROCESSED_ON": datetime.datetime.now().strftime("%Y-%m-%d"),
    }

    return value_2d, flag_2d, profile, provenance


def write_outputs(value_2d, flag_2d, profile, out_path: str, provenance: dict):
    val_profile = profile.copy()
    val_profile.update(driver="GTiff", dtype="float32", count=1, nodata=np.nan, compress="deflate")
    with rasterio.open(out_path, "w", **val_profile) as dst:
        dst.write(value_2d, 1)
        dst.update_tags(**provenance)
    print(f"[OK] Carte ecrite : {out_path}")

    flag_path = os.path.splitext(out_path)[0] + "_QA.tif"
    flag_profile = profile.copy()
    flag_profile.update(driver="GTiff", dtype="uint8", count=1, nodata=255, compress="deflate")
    with rasterio.open(flag_path, "w", **flag_profile) as dst:
        dst.write(flag_2d, 1)
        dst.update_tags(**provenance)
    print(f"[OK] Flags QA ecrits : {flag_path}")
    print("     (0=OK, 1=hors domaine de definition, 2=cas extreme, 255=pas de donnee)")
    print(f"[i] Tracabilite (tags GeoTIFF) : baseline S2 {provenance['S2_PROCESSING_BASELINE']}, "
          f"produit source {provenance['SOURCE_SAFE_PRODUCT']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("safe_dir", help="Chemin du produit Sentinel-2 L2A .SAFE")
    parser.add_argument("--var", default="LAI", choices=["LAI", "FAPAR", "FCOVER"], help="Variable biophysique")
    parser.add_argument("--out", default=None, help="Fichier GeoTIFF de sortie (defaut: outputs/<nom_produit>_<var>.tif)")
    parser.add_argument("--no-cloud-mask", action="store_true", help="Desactive le masquage nuages/ombres/eau via la SCL")
    args = parser.parse_args()

    safe_root = os.path.abspath(args.safe_dir)
    product_name = os.path.basename(safe_root.rstrip("\\/")).replace(".SAFE", "")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = args.out or os.path.join(OUTPUT_DIR, f"{product_name}_{args.var}.tif")

    value_2d, flag_2d, profile, provenance = compute_map(
        safe_root, variable=args.var, mask_clouds=not args.no_cloud_mask
    )
    write_outputs(value_2d, flag_2d, profile, out_path, provenance)


if __name__ == "__main__":
    main()
