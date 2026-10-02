# -*- coding: utf-8 -*-
"""
download_s2_l2a.py

Recherche et telecharge en masse des produits Sentinel-2 L2A depuis le
Copernicus Data Space Ecosystem (CDSE), via l'API OData (methode
officielle recommandee pour le telechargement programmatique).

⚠️ Non teste en conditions reelles : l'environnement dans lequel ce
script a ete ecrit n'a pas d'acces reseau vers identity.dataspace.copernicus.eu
ni catalogue.dataspace.copernicus.eu. Le code suit exactement la
documentation officielle CDSE (endpoints, parametres), mais executez-le
d'abord sur UNE petite recherche/UN seul produit avant de lancer le
telechargement de plusieurs milliers d'images.

Pre-requis :
    - Un compte gratuit sur https://dataspace.copernicus.eu
    - pip install requests

Quotas a connaitre (compte gratuit, cf. documentation CDSE) :
    - 12 To de transfert par mois (fenetre glissante de 30 jours)
    - 4 connexions simultanees maximum, 20 Mo/s par connexion
    - Jeton d'acces valable 10 min, rafraichissable pendant 60 min
    - Pas de limite sur le nombre de produits telecharges avec un jeton
  -> Avec 4 connexions en parallele max, prevoir le temps necessaire
     pour plusieurs milliers de produits (~700 Mo-1 Go chacun).
     Lancez ce script en AMONT du job array SLURM de traitement (sur un
     noeud de transfert de donnees si votre cluster en a un dédié),
     pas depuis chaque tache du tableau.
"""

import os
import time
import zipfile
import shutil

import requests

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
MAX_CONCURRENT = 4  # respecte le quota CDSE (compte gratuit)


class CDSESession:
    """Gere le jeton d'acces et son rafraichissement automatique."""

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.token = None
        self.refresh_token = None
        self.expires_at = 0
        self._login()

    def _login(self):
        r = requests.post(TOKEN_URL, data={
            "client_id": "cdse-public",
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
        })
        r.raise_for_status()
        data = r.json()
        self.token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = time.time() + data["expires_in"] - 30  # marge de securite

    def _refresh(self):
        r = requests.post(TOKEN_URL, data={
            "client_id": "cdse-public",
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        })
        if r.status_code != 200:
            self._login()  # le refresh token a expire (>60 min) -> se reconnecter
            return
        data = r.json()
        self.token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = time.time() + data["expires_in"] - 30

    def get_headers(self):
        if time.time() > self.expires_at:
            self._refresh()
        return {"Authorization": f"Bearer {self.token}"}


def search_products(lon, lat, start_date, end_date, max_cloud=30,
                     collection="SENTINEL-2", product_type="S2MSI2A", top=100):
    """
    Recherche les produits couvrant un point (lon, lat) sur une periode
    donnee. Pour couvrir une zone entiere plutot qu'un point, remplacez
    le POINT WKT par un POLYGON WKT dans le filtre.

    Retourne une liste de dicts {"id":..., "name":...}.
    """
    aoi = f"POINT({lon} {lat})"
    filter_str = (
        f"Collection/Name eq '{collection}' "
        f"and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
        f"and att/OData.CSC.StringAttribute/Value eq '{product_type}') "
        f"and OData.CSC.Intersects(area=geography'SRID=4326;{aoi}') "
        f"and ContentDate/Start gt {start_date}T00:00:00.000Z "
        f"and ContentDate/Start lt {end_date}T00:00:00.000Z "
        f"and Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' "
        f"and att/OData.CSC.DoubleAttribute/Value le {max_cloud})"
    )
    params = {"$filter": filter_str, "$top": top, "$orderby": "ContentDate/Start asc"}
    r = requests.get(CATALOGUE_URL, params=params)
    r.raise_for_status()
    results = r.json().get("value", [])
    return [{"id": p["Id"], "name": p["Name"]} for p in results]


def download_product(session, product_id, product_name, output_dir):
    """
    Telecharge un produit (zip contenant le .SAFE) et le decompresse.
    Idempotent : ignore si le .SAFE existe deja dans output_dir.
    """
    safe_name = product_name if product_name.endswith(".SAFE") else product_name + ".SAFE"
    safe_path = os.path.join(output_dir, safe_name)
    if os.path.isdir(safe_path):
        print(f"[SKIP] {safe_name} deja present")
        return safe_path

    zip_path = os.path.join(output_dir, safe_name.replace(".SAFE", ".zip"))
    url = f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"

    os.makedirs(output_dir, exist_ok=True)
    with requests.get(url, headers=session.get_headers(), stream=True) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                f.write(chunk)

    with zipfile.ZipFile(zip_path) as z:
        z.extractall(output_dir)
    os.remove(zip_path)

    print(f"[OK] {safe_name} telecharge")
    return safe_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Telechargement en masse Sentinel-2 L2A (CDSE)")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--start", required=True, help="AAAA-MM-JJ")
    parser.add_argument("--end", required=True, help="AAAA-MM-JJ")
    parser.add_argument("--max-cloud", type=float, default=30)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    session = CDSESession(args.username, args.password)
    products = search_products(args.lon, args.lat, args.start, args.end, args.max_cloud)
    print(f"{len(products)} produits trouves")

    for p in products:
        download_product(session, p["id"], p["name"], args.output_dir)
