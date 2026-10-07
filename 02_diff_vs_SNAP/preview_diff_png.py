# -*- coding: utf-8 -*-
"""Apercu PNG d'une carte de difference LAI (colormap divergente centree sur
0, dont les bornes min/max correspondent exactement au min/max des donnees
de la carte -- pas une echelle fixe arbitraire)."""
import sys
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

def preview(tif_path, png_path, step=2):
    with rasterio.open(tif_path) as ds:
        full = ds.read(1)
        arr = full[::step, ::step]
    # bornes de l'echelle = min/max reels de la carte complete (pas de la
    # version sous-echantillonnee affichee, qui pourrait manquer un extremum)
    vmin = float(np.nanmin(full))
    vmax = float(np.nanmax(full))
    norm = TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax)

    fig, ax = plt.subplots(figsize=(8, 8))
    im = ax.imshow(arr, cmap="RdBu_r", norm=norm)
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, label="LAI (algo maison - SNAP)", shrink=0.8)
    ax.set_title(f"min={vmin:.3f}  max={vmax:.3f}", fontsize=10)
    fig.tight_layout()
    fig.savefig(png_path, dpi=130)
    plt.close(fig)
    print(f"saved {png_path}  (vmin={vmin:.3f}, vmax={vmax:.3f})")

if __name__ == "__main__":
    preview(sys.argv[1], sys.argv[2])
