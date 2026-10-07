# -*- coding: utf-8 -*-
r"""Calcule une carte LAI pour CHAQUE date disponible d'une tuile Sentinel-2
(catalogue Theia STAC) sur une periode donnee.

Critere de selection des images (clarifie par Marie Weiss, 2026-10) :
pas de seuil de couverture nuageuse globale pour decider quelles dates
garder. On traite TOUTES les dates disponibles ; c'est le masque qualite
PAR PIXEL (MG2+EDG, cf. commun/theia_stac_reader.py) qui produit du NODATA
la ou necessaire -- une scene a 80% de nuages peut quand meme apporter des
pixels valides exploitables sur les 20% restants.

Usage:
    python compute_lai_series.py --tile 31TEJ --start 2021-01-01 --end 2021-12-31 [--var LAI]

Idempotent : si la sortie d'une date existe deja dans outputs/, elle est
reutilisee ([SKIP]) -- permet de relancer apres une interruption sans tout
recalculer. Les erreurs sur une date (produit corrompu, timeout reseau...)
n'interrompent pas le traitement des autres dates.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TRAITEMENT_LAI_DIR = os.path.dirname(HERE)
OUTPUT_DIR = os.path.join(HERE, "outputs")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(TRAITEMENT_LAI_DIR, "commun"))
import theia_stac_reader as theia
from compute_lai_map_theia import compute_map_for_item, write_outputs


def process_series(tile: str, start: str, end: str, variable: str = "LAI", mask_clouds: bool = True):
    print(f"[i] Recherche de toutes les dates disponibles : tuile {tile}, {start} -> {end}...")
    items = theia.find_all_items(tile, start, end)
    if not items:
        print("[!] Aucune date disponible sur cette periode.")
        return []
    print(f"[i] {len(items)} date(s) trouvee(s) :")
    for it in items:
        print(f"    {it.datetime.strftime('%Y-%m-%d')}  {it.id}  "
              f"(nuages scene : {it.properties.get('eo:cloud_cover')}%)")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = []
    for i, item in enumerate(items, 1):
        out_path = os.path.join(OUTPUT_DIR, f"{item.id}_{variable}.tif")
        print(f"\n=== [{i}/{len(items)}] {item.id} "
              f"({item.datetime.strftime('%Y-%m-%d')}, nuages scene : {item.properties.get('eo:cloud_cover')}%) ===")

        if os.path.exists(out_path):
            print(f"[SKIP] sortie deja presente : {out_path}")
            results.append({"item_id": item.id, "date": item.datetime.strftime("%Y-%m-%d"), "status": "SKIP"})
            continue

        t0 = time.time()
        try:
            value_2d, flag_2d, profile, provenance = compute_map_for_item(
                item, variable=variable, mask_clouds=mask_clouds, tile=tile,
            )
            write_outputs(value_2d, flag_2d, profile, out_path, provenance)
            results.append({
                "item_id": item.id, "date": item.datetime.strftime("%Y-%m-%d"),
                "status": "OK", "seconds": time.time() - t0,
            })
        except Exception as e:
            print(f"[ERREUR] {item.id} : {e}")
            results.append({
                "item_id": item.id, "date": item.datetime.strftime("%Y-%m-%d"),
                "status": "ERREUR", "error": str(e),
            })

    print("\n=== Resume ===")
    for r in results:
        if r["status"] == "OK":
            print(f"  OK     {r['date']}  {r['item_id']}  ({r['seconds']:.1f}s)")
        elif r["status"] == "SKIP":
            print(f"  SKIP   {r['date']}  {r['item_id']}  (deja present)")
        else:
            print(f"  ERREUR {r['date']}  {r['item_id']}  : {r['error']}")
    n_ok = sum(1 for r in results if r["status"] == "OK")
    n_skip = sum(1 for r in results if r["status"] == "SKIP")
    n_err = sum(1 for r in results if r["status"] == "ERREUR")
    print(f"\n{n_ok} calculee(s), {n_skip} deja presente(s), {n_err} erreur(s), sur {len(results)} date(s).")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tile", required=True, help="Code tuile MGRS, ex: 31TEJ")
    parser.add_argument("--start", required=True, help="Date de debut AAAA-MM-JJ")
    parser.add_argument("--end", required=True, help="Date de fin AAAA-MM-JJ")
    parser.add_argument("--var", default="LAI", choices=["LAI", "FAPAR", "FCOVER"], help="Variable biophysique")
    parser.add_argument("--no-cloud-mask", action="store_true",
                         help="Desactive le masquage qualite MG2/EDG (deconseille)")
    args = parser.parse_args()

    process_series(args.tile, args.start, args.end, variable=args.var, mask_clouds=not args.no_cloud_mask)


if __name__ == "__main__":
    main()
