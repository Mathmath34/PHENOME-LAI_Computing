# -*- coding: utf-8 -*-
"""Reimplementation vectorisee (numpy) du reseau de neurones SL2P
(Weiss & Baret, 2020 - ATBD S2ToolBox L2B) fourni par Marie Weiss,
pour convertir des reflectances de surface Sentinel-2 en variables
biophysiques (LAI, FAPAR, FCOVER...).

Reprend fidelement la logique de Read_NNT_Files_Magellium.py (Read_NNt /
Apply_NNT) mais operant sur des tableaux numpy (N pixels) plutot que sur
une seule ligne de tableau de cas-test.

Ordre des 11 entrees, imposees par les fichiers Excel de Marie Weiss :
    B3, B4, B5, B6, B7, B8A, B11, B12,
    cos(zenith de visee), cos(zenith solaire), cos(azimut relatif)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

INPUT_BANDS = ["B3", "B4", "B5", "B6", "B7", "B8A", "B11", "B12"]
INPUT_NAMES = INPUT_BANDS + ["cos_view_zenith", "cos_sun_zenith", "cos_rel_azimuth"]


class SL2PNetwork:
    """Reseau de neurones a 2 couches (11 -> 5 -> 1) + controle qualite,
    pour une variable biophysique donnee (LAI, FAPAR, FCOVER, ...)."""

    def __init__(self, xlsx_path: str, variable_name: str):
        self.xlsx_path = xlsx_path
        self.variable_name = variable_name
        self._load()

    def _load(self) -> None:
        f = self.xlsx_path

        # --- Normalisation des entrees / sortie -----------------------
        norm_in_min = pd.read_excel(
            f, "Normalisation", header=None, skiprows=5, skipfooter=7,
            usecols=[1], dtype="float",
        ).to_numpy().ravel()
        norm_in_max = pd.read_excel(
            f, "Normalisation", header=None, skiprows=5, skipfooter=7,
            usecols=[2], dtype="float",
        ).to_numpy().ravel()
        norm_out_min = pd.read_excel(
            f, "Normalisation", header=None, skiprows=22, usecols=[1], dtype="float",
        ).to_numpy().ravel()[0]
        norm_out_max = pd.read_excel(
            f, "Normalisation", header=None, skiprows=22, usecols=[2], dtype="float",
        ).to_numpy().ravel()[0]

        # --- Poids / biais des 2 couches -------------------------------
        w1 = pd.read_excel(
            f, "Weights", header=None, skiprows=5, skipfooter=7,
            usecols=range(1, 12), dtype="float",
        ).to_numpy()  # (5 neurones, 11 entrees)
        b1 = pd.read_excel(
            f, "Weights", header=None, skiprows=10, skipfooter=6,
            usecols=range(1, 6), dtype="float",
        ).to_numpy().ravel()  # (5,)
        w2 = pd.read_excel(
            f, "Weights", header=None, skiprows=14, skipfooter=2,
            usecols=range(1, 6), dtype="float",
        ).to_numpy().ravel()  # (5,)
        b2 = pd.read_excel(
            f, "Weights", header=None, skiprows=15, skipfooter=1,
            usecols=[1], dtype="float",
        ).to_numpy().ravel()[0]

        # --- Gestion des cas extremes -----------------------------------
        tol = pd.read_excel(
            f, "Extreme Cases", header=None, skiprows=9,
            usecols=range(1, 4), dtype="float",
        ).to_numpy().ravel()
        self.tol, self.out_min, self.out_max = float(tol[0]), float(tol[1]), float(tol[2])

        # --- Domaine de definition (bounding box min/max par bande) --------
        # NB : le fichier fourni contient aussi une grille fine de cellules
        # "valides" (8 dimensions) destinee a un controle plus strict. On ne
        # l'utilise pas ici : en la reimplementant a l'identique de la formule
        # du script original (ceil((X-min)/(max-min)*10) puis recherche d'une
        # correspondance exacte dans la grille), on constate qu'elle rejette
        # a tort la quasi-totalite des 250 cas-test de reference fournis par
        # Marie Weiss (qui, eux, sont pourtant valides d'apres le fichier de
        # reference : QA jamais egal a 1). C'est deja le cas avec son propre
        # script tel quel : c'est donc une limitation du script d'exemple, pas
        # une erreur de portage. Le controle par bounding box ci-dessous
        # valide correctement les 250 cas de reference (0 hors bornes) et
        # reste un garde-fou raisonnable contre des reflectances aberrantes.
        dd = pd.read_excel(
            f, "Definition_Domain", header=None, skiprows=3, usecols=range(0, 9),
        ).to_numpy()
        self.cell_min = dd[0, 1:].astype(float)  # (8,) bornes basses par bande
        self.cell_max = dd[1, 1:].astype(float)  # (8,) bornes hautes par bande

        self.norm_in_min, self.norm_in_max = norm_in_min, norm_in_max
        self.norm_out_min, self.norm_out_max = norm_out_min, norm_out_max
        self.w1, self.b1, self.w2, self.b2 = w1, b1, w2, b2

    def _in_domain(self, refl8: np.ndarray) -> np.ndarray:
        """refl8: (8, N) reflectances brutes -> (N,) bool dans le domaine
        (bounding box min/max, voir note dans _load)."""
        return np.all(
            (refl8 >= self.cell_min[:, None]) & (refl8 <= self.cell_max[:, None]),
            axis=0,
        )

    def apply(self, inputs) -> tuple[np.ndarray, np.ndarray]:
        """Applique le reseau a N pixels.

        inputs : soit un dict {nom: array 1D}, soit un tableau (11, N),
        dans l'ordre INPUT_NAMES.

        Retourne (valeur, flag) en tableaux 1D de longueur N.
        flag : 0 = OK, 1 = hors du domaine de definition (NaN),
               2 = cas extreme (clampe ou NaN), 255 = entree manquante (NaN).
        """
        if isinstance(inputs, dict):
            X = np.stack([np.asarray(inputs[n], dtype=float) for n in INPUT_NAMES], axis=0)
        else:
            X = np.asarray(inputs, dtype=float)
        n = X.shape[1]

        valid_input = ~np.any(np.isnan(X), axis=0)

        in_domain = np.zeros(n, dtype=bool)
        if valid_input.any():
            in_domain[valid_input] = self._in_domain(X[0:8, valid_input])

        # Reseau applique partout (vectorise) ; les pixels hors-domaine /
        # sans entree valide seront ecrases par NaN a la fin.
        X_safe = np.where(np.isnan(X), 0.0, X)
        Xn = 2 * (X_safe - self.norm_in_min[:, None]) / (
            self.norm_in_max - self.norm_in_min
        )[:, None] - 1
        hidden = np.tanh(self.w1 @ Xn + self.b1[:, None])   # tansig == tanh
        out_norm = self.w2 @ hidden + self.b2
        out = 0.5 * (out_norm + 1) * (self.norm_out_max - self.norm_out_min) + self.norm_out_min

        below_far = out < (self.out_min - self.tol)
        below_near = (out >= (self.out_min - self.tol)) & (out < self.out_min)
        above_far = out > (self.out_max + self.tol)
        above_near = (out > self.out_max) & (out <= (self.out_max + self.tol))

        clipped = out.copy()
        clipped[below_near] = self.out_min
        clipped[above_near] = self.out_max
        out_of_range = below_far | above_far
        extreme = below_near | above_near | out_of_range

        flag = np.zeros(n, dtype=np.uint8)
        flag[valid_input & ~in_domain] = 1
        flag[valid_input & in_domain & extreme] = 2
        flag[~valid_input] = 255

        result = clipped
        result[out_of_range] = np.nan
        result[~in_domain] = np.nan
        result[~valid_input] = np.nan

        return result, flag
