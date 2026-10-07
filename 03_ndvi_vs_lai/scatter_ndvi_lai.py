# -*- coding: utf-8 -*-
r"""Density plot NDVI = (NIR-Red)/(NIR+Red) vs LAI (notre carte SL2P), pour
verifier la relation de saturation exponentielle bien documentee entre les
deux (Baret & Guyot, 1991) : NDVI sature quand le LAI augmente, alors que
le LAI retrouve par le reseau de neurones (qui utilise aussi le SWIR/red-edge)
continue de discriminer les forts LAI.

Suite a la remarque de Marie Weiss : la relation attendue etant non-lineaire
(saturation exponentielle), un R²/RMSE calcule sur un ajustement (lineaire ou
non) n'est pas la bonne facon de la "verifier" visuellement. Ce script trace
donc uniquement un density plot (hexbin, densite de pixels), avec en plus une
courbe de mediane par tranche de LAI -- une simple statistique descriptive,
sans hypothese de forme (pas un fit, pas de R²) -- pour aider a suivre la
tendance a l'oeil.

NIR = bande B8A (20 m, deja utilisee comme entree du reseau SL2P, donc sur
exactement la meme grille que notre carte de LAI -> pas de reechantillonnage
necessaire). Red = bande B4 (20 m).

Usage:
    python scatter_ndvi_lai.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
TRAITEMENT_LAI_DIR = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(TRAITEMENT_LAI_DIR)
SAFE_DIR = os.path.join(PROJECT_ROOT, "Images_SAFE")
LAI_DIR = os.path.join(TRAITEMENT_LAI_DIR, "01_calcul_LAI", "outputs")
OUTPUT_DIR = os.path.join(HERE, "outputs")

sys.path.insert(0, os.path.join(TRAITEMENT_LAI_DIR, "commun"))
import s2_safe_reader as s2

CASES = [
    {
        "label": "2021-04-02",
        "safe": os.path.join(SAFE_DIR, "S2A_MSIL2A_20210402T104021_N0500_R008_T31TEJ_20230510T222312.SAFE"),
        "lai": os.path.join(LAI_DIR, "S2A_MSIL2A_20210402T104021_N0500_R008_T31TEJ_20230510T222312_LAI.tif"),
    },
    {
        "label": "2026-08-06",
        "safe": os.path.join(SAFE_DIR, "S2A_MSIL2A_20260806T103701_N0512_R008_T31TEJ_20260806T190416.SAFE"),
        "lai": os.path.join(LAI_DIR, "S2A_MSIL2A_20260806T103701_N0512_R008_T31TEJ_20260806T190416_LAI.tif"),
    },
]


def binned_median(lai: np.ndarray, ndvi: np.ndarray, n_bins: int = 40, min_count: int = 30):
    """Mediane (+ P25/P75) de NDVI par tranche de LAI. Statistique purement
    descriptive (aucune hypothese de forme, pas un fit) : sert juste a
    donner un fil visuel a travers le nuage de points."""
    edges = np.linspace(0, lai.max(), n_bins + 1)
    centers, med, p25, p75 = [], [], [], []
    for i in range(n_bins):
        m = (lai >= edges[i]) & (lai < edges[i + 1])
        if m.sum() < min_count:
            continue
        centers.append(0.5 * (edges[i] + edges[i + 1]))
        med.append(np.median(ndvi[m]))
        p25.append(np.percentile(ndvi[m], 25))
        p75.append(np.percentile(ndvi[m], 75))
    return np.array(centers), np.array(med), np.array(p25), np.array(p75)


def load_case(case):
    granule_dir = s2.find_granule_dir(case["safe"])
    bands, _ = s2.read_bands_20m(granule_dir)
    nir, red = bands["B8A"], bands["B4"]
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = (nir - red) / (nir + red)

    with rasterio.open(case["lai"]) as ds:
        lai = ds.read(1)

    valid = np.isfinite(lai) & np.isfinite(ndvi)
    return lai[valid], ndvi[valid]


def main():
    fig, axes = plt.subplots(1, len(CASES), figsize=(6.5 * len(CASES), 5.5))
    if len(CASES) == 1:
        axes = [axes]

    for ax, case in zip(axes, CASES):
        print(f"[i] {case['label']} : lecture bandes + LAI...")
        lai, ndvi = load_case(case)
        print(f"[i] {case['label']} : {lai.size:,} pixels valides".replace(",", " "))

        hb = ax.hexbin(lai, ndvi, gridsize=70, bins="log", cmap="viridis", mincnt=1)

        centers, med, p25, p75 = binned_median(lai, ndvi)
        ax.fill_between(centers, p25, p75, color="red", alpha=0.15, label="P25-P75 par tranche de LAI")
        ax.plot(centers, med, color="red", lw=2, label="mediane par tranche de LAI")

        ax.set_xlabel("LAI (algo SL2P)")
        ax.set_ylabel("NDVI = (B8A-B4)/(B8A+B4)")
        ax.set_title(case["label"])
        ax.legend(loc="lower right", fontsize=9)
        fig.colorbar(hb, ax=ax, label="log10(nombre de pixels)")

    fig.tight_layout()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_png = os.path.join(OUTPUT_DIR, "scatter_ndvi_vs_lai.png")
    fig.savefig(out_png, dpi=130)
    plt.close(fig)
    print(f"[OK] Figure enregistree : {out_png}")


if __name__ == "__main__":
    main()
