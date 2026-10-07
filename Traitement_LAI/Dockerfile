# Minimal image: Python environment + the Traitement_LAI code baked in.
# Data (SL2P coefficients, Sentinel-2 .SAFE products, SNAP outputs) is NOT
# baked into the image -- it is mounted at runtime (see README "Docker"
# section). This keeps the image small and avoids redistributing data
# files (notably Marie Weiss's coefficient spreadsheets) inside a shared
# image.
#
# Build (from inside Traitement_LAI/):
#     docker build -t lai-sl2p .
#
# See README.md for full usage / volume-mount examples.

FROM python:3.13-slim

WORKDIR /app/Traitement_LAI

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python"]
CMD ["01_calcul_LAI/compute_lai_map_theia.py", "--help"]
