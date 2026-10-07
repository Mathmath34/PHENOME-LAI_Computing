# -*- coding: utf-8 -*-
"""Genere un apercu PNG rapide (decimate) d'une carte LAI GeoTIFF."""
import sys
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def preview(tif_path, png_path, vmax=6, step=6):
    with rasterio.open(tif_path) as ds:
        arr = ds.read(1)[::step, ::step]
    fig, ax = plt.subplots(figsize=(8, 8))
    im = ax.imshow(arr, cmap="YlGn", vmin=0, vmax=vmax)
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, label="LAI (m2/m2)", shrink=0.8)
    fig.tight_layout()
    fig.savefig(png_path, dpi=130)
    plt.close(fig)
    print("saved", png_path)

if __name__ == "__main__":
    preview(sys.argv[1], sys.argv[2])
