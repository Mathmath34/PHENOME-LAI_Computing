# -*- coding: utf-8 -*-
"""Histogramme des residus (LAI algo maison - LAI SNAP), pour repondre a la
demande de Marie Weiss : quantifier combien de pixels s'ecartent reellement
(et de combien), au-dela de l'impression visuelle donnee par la carte de
difference coloree.

Usage:
    python histogram_residus.py
"""
from __future__ import annotations

import os
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(HERE, "outputs")

CASES = [
    {"label": "2021-04-02", "diff": os.path.join(OUTPUT_DIR, "diff_LAI_2021-04-02.tif")},
    {"label": "2026-08-06", "diff": os.path.join(OUTPUT_DIR, "diff_LAI_2026-08-06.tif")},
]

# Seuils (en LAI, m2/m2) pour quantifier "combien de points rouges" : au-dela
# de ces valeurs, l'ecart devient difficile a expliquer par du simple bruit
# numerique et merite d'etre regarde de plus pres.
THRESHOLDS = [0.1, 0.2, 0.5, 1.0]


def plot_case(ax, case):
    with rasterio.open(case["diff"]) as ds:
        arr = ds.read(1)
    d = arr[np.isfinite(arr)]
    n = d.size

    mean, std, median = d.mean(), d.std(), np.median(d)

    ax.hist(d, bins=300, color="#4c72b0", edgecolor="none")
    ax.set_yscale("log")
    ax.axvline(0, color="black", lw=1, ls="-")
    ax.axvline(mean, color="red", lw=1.5, ls="--", label=f"moyenne={mean:.4f}")
    ax.set_xlabel("LAI (algo maison - SNAP)")
    ax.set_ylabel("nombre de pixels (echelle log)")
    ax.set_title(case["label"])
    ax.legend(loc="upper right", fontsize=9)

    lines = [
        f"n = {n:,}".replace(",", " "),
        f"moyenne = {mean:.4f}   mediane = {median:.4f}   ecart-type = {std:.4f}",
    ]
    for t in THRESHOLDS:
        pct = 100 * np.mean(np.abs(d) > t)
        n_t = int(np.sum(np.abs(d) > t))
        lines.append(f"|diff| > {t:g} : {n_t:,} px ({pct:.3f}%)".replace(",", " "))
    text = "\n".join(lines)
    ax.text(0.02, 0.98, text, transform=ax.transAxes, va="top", ha="left",
            fontsize=8.5, family="monospace",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"))

    print(f"--- {case['label']} ---")
    print(text)
    print()


def main():
    fig, axes = plt.subplots(1, len(CASES), figsize=(7 * len(CASES), 5.5))
    if len(CASES) == 1:
        axes = [axes]
    for ax, case in zip(axes, CASES):
        plot_case(ax, case)
    fig.suptitle("Histogramme des residus LAI (algo maison - SNAP)", y=1.02)
    fig.tight_layout()
    out_png = os.path.join(OUTPUT_DIR, "histogramme_residus.png")
    fig.savefig(out_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Figure enregistree : {out_png}")


if __name__ == "__main__":
    main()
