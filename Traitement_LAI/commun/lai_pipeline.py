# -*- coding: utf-8 -*-
"""Logique partagee d'application du reseau SL2P a un cube de bandes +
angles, independamment de la source des donnees (.SAFE local ESA ou
catalogue STAC Theia en streaming)."""
from __future__ import annotations

import os
import numpy as np

from sl2p_network import SL2PNetwork, INPUT_BANDS

# Classes SCL (ESA) considerees non fiables pour une retrieval LAI (nuages,
# ombres, neige, eau, pixels satures/defectueux, pas de donnee).
SCL_BAD_CLASSES = {0, 1, 3, 6, 8, 9, 10, 11}


def apply_sl2p(bands: dict, angles: dict, profile: dict, variable: str,
                models_dir: str, cloud_mask=None):
    """Applique le reseau SL2P sur une tuile complete.

    bands : dict {"B3":arr(H,W), ..., "B12":arr(H,W)} en reflectance [0-1]
    angles : dict {"cos_view_zenith":arr(H,W), "cos_sun_zenith":..., "cos_rel_azimuth":...}
    profile : dict avec au moins "height"/"width"
    cloud_mask : array bool (H,W) optionnel, True = pixel a exclure (NaN)

    Retourne (value_2d float32, flag_2d uint8). flag : 0=OK,
    1=hors domaine de definition, 2=cas extreme, 255=pas de donnee.
    """
    h, w = profile["height"], profile["width"]
    inputs = {b: bands[b].ravel() for b in INPUT_BANDS}
    inputs.update({k: v.ravel() for k, v in angles.items()})

    if cloud_mask is not None:
        flat_mask = cloud_mask.ravel()
        for b in INPUT_BANDS:
            inputs[b] = np.where(flat_mask, np.nan, inputs[b])

    xlsx_path = os.path.join(models_dir, f"Algo_S2_V2.0_SL2T_{variable}.xlsx")
    net = SL2PNetwork(xlsx_path, variable)

    value, flag = net.apply(inputs)
    value_2d = value.reshape(h, w).astype(np.float32)
    flag_2d = flag.reshape(h, w).astype(np.uint8)
    return value_2d, flag_2d
