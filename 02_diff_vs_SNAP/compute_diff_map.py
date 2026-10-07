# -*- coding: utf-8 -*-
r"""Carte de difference LAI (algorithme SL2P maison) - (LAI exporte de SNAP).

Le produit SNAP (dossier sorties_SNAP\*_biophysical.tif, bande 1) est a
60 m/pixel, alors que notre sortie (01_calcul_LAI\outputs\*_LAI.tif) est a
20 m. Les deux partagent la meme origine/CRS (UTM31N, ULX=499980,
ULY=4900020), la grille SNAP est donc un sous-echantillonnage exact
(facteur 3) de la notre : on ramene notre carte 20 m sur la grille 60 m
par moyenne des blocs 3x3, puis on soustrait.

Usage:
    python compute_diff_map.py
"""
from __future__ import annotations

import os
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

HERE = os.path.dirname(os.path.abspath(__file__))
TRAITEMENT_LAI_DIR = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(TRAITEMENT_LAI_DIR)
SNAP_DIR = os.path.join(PROJECT_ROOT, "sorties_SNAP")
LAI_DIR = os.path.join(TRAITEMENT_LAI_DIR, "01_calcul_LAI", "outputs")
OUTPUT_DIR = os.path.join(HERE, "outputs")

PAIRS = [
    {
        "label": "2021-04-02",
        "mine": os.path.join(LAI_DIR, "S2A_MSIL2A_20210402T104021_N0500_R008_T31TEJ_20230510T222312_LAI.tif"),
        "snap": os.path.join(SNAP_DIR, "S2A_MSIL2A_20210402T104021_N0500_R008_T31TEJ_20230510T222312_biophysical.tif"),
        "out": os.path.join(OUTPUT_DIR, "diff_LAI_2021-04-02.tif"),
    },
    {
        "label": "2026-08-06",
        "mine": os.path.join(LAI_DIR, "S2A_MSIL2A_20260806T103701_N0512_R008_T31TEJ_20260806T190416_LAI.tif"),
        "snap": os.path.join(SNAP_DIR, "S2A_MSIL2A_20260806T103701_N0512_R008_T31TEJ_20260806T190416_biophysical.tif"),
        "out": os.path.join(OUTPUT_DIR, "diff_LAI_2026-08-06.tif"),
    },
]


def compute_diff(mine_path: str, snap_path: str, out_path: str, label: str):
    with rasterio.open(snap_path) as snap_ds:
        snap_lai = snap_ds.read(1)
        snap_profile = snap_ds.profile.copy()

    with rasterio.open(mine_path) as mine_ds:
        mine_lai = mine_ds.read(1)
        mine_profile = mine_ds.profile.copy()

    mine_on_snap_grid = np.full(snap_lai.shape, np.nan, dtype=np.float32)
    reproject(
        source=mine_lai,
        destination=mine_on_snap_grid,
        src_transform=mine_profile["transform"],
        src_crs=mine_profile["crs"],
        src_nodata=np.nan,
        dst_transform=snap_profile["transform"],
        dst_crs=snap_profile["crs"],
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )

    diff = mine_on_snap_grid - snap_lai

    out_profile = snap_profile.copy()
    out_profile.update(driver="GTiff", dtype="float32", count=1, nodata=np.nan, compress="deflate")
    with rasterio.open(out_path, "w", **out_profile) as dst:
        dst.write(diff.astype(np.float32), 1)

    valid = ~np.isnan(diff)
    n = valid.sum()
    print(f"[{label}] Carte de difference ecrite : {out_path}")
    print(f"[{label}] Pixels valides : {n:,} / {diff.size:,}".replace(",", " "))
    if n > 0:
        d = diff[valid]
        print(f"[{label}] diff mean={d.mean():.4f}  std={d.std():.4f}  "
              f"median={np.median(d):.4f}  min={d.min():.4f}  max={d.max():.4f}")
        rmse = np.sqrt(np.mean(d ** 2))
        r = np.corrcoef(mine_on_snap_grid[valid], snap_lai[valid])[0, 1]
        print(f"[{label}] RMSE={rmse:.4f}  correlation r={r:.4f}")
    return diff, out_profile


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for pair in PAIRS:
        if not os.path.exists(pair["mine"]):
            print(f"[!] Introuvable, on saute : {pair['mine']}")
            continue
        if not os.path.exists(pair["snap"]):
            print(f"[!] Introuvable, on saute : {pair['snap']}")
            continue
        compute_diff(pair["mine"], pair["snap"], pair["out"], pair["label"])
        print()


if __name__ == "__main__":
    main()
