# LAI Processing — Sentinel-2 / SL2P

Computes LAI maps (and FAPAR/FCOVER) from Sentinel-2 L2A images, using the
**SL2P** neural network (Weiss & Baret, 2020 — S2ToolBox / SNAP
Biophysical Processor algorithm), from the coefficients provided by Marie
Weiss (INRAE).

Reference: Weiss, M., & Baret, F. (2020). *ATBD for S2ToolBox Level 2
products: LAI, FAPAR, FCOVER.* Version 2.1. INRAE.
[step.esa.int/docs/extra/ATBD_S2ToolBox_L2B_V1.1.pdf](https://step.esa.int/docs/extra/ATBD_S2ToolBox_L2B_V1.1.pdf)
— this is the ATBD version describing the network weights used in this
implementation. See *References* at the end of this document for the
underlying radiative transfer models (PROSPECT, SAIL) the SL2P network was
trained against.

## Installation

```bash
pip install -r requirements.txt
```

Python 3.13 (tested). `teledetection` and `pystac-client` are only needed
for the Theia STAC source (see below); the other dependencies are enough
to process local `.SAFE` products.

## Docker

For sharing this work with someone else without them having to set up a
Python environment themselves. The image bundles the code and its Python
dependencies only — **not** the data (SL2P coefficients, Sentinel-2
products, SNAP outputs): those stay on the host and are mounted at
runtime, so the image stays small and nobody accidentally redistributes
data files they don't own the rights to.

> ⚠️ Built from this Dockerfile but not yet actually run end-to-end on a
> machine with Docker installed — validate it once (`docker build` +
> one `docker run`) before relying on it. Report back if something in
> here needs fixing.

**Build** (from inside `Traitement_LAI/`):
```powershell
cd "C:\Users\mguimont\Desktop\PHENOME-LAI 2\Traitement_LAI"
docker build -t lai-sl2p .
```

**Run** — the simplest way is to mount the whole parent folder (the one
containing both `Traitement_LAI/` and the sibling data folders
`A_Marie_Weiss_Modele/`, `Images_SAFE/`, `sorties_SNAP/`) to `/app`:

```powershell
docker run --rm -it `
  -v "C:\Users\mguimont\Desktop\PHENOME-LAI 2:/app" `
  lai-sl2p 01_calcul_LAI/compute_lai_map_theia.py --tile 31TEJ --date 2021-04-02 --var LAI
```

```powershell
docker run --rm -it `
  -v "C:\Users\mguimont\Desktop\PHENOME-LAI 2:/app" `
  lai-sl2p 01_calcul_LAI/compute_lai_map.py "Images_SAFE/S2A_MSIL2A_20210402T104021_N0500_R008_T31TEJ_20230510T222312.SAFE" --var LAI
```

Any script under `Traitement_LAI/` can be run this way — just change the
argument after the image name to the script's path (relative to
`Traitement_LAI/`) and its own arguments. Outputs land directly in the
corresponding host `outputs/` folder (the mount makes the container write
straight back to disk, nothing stays trapped inside the container).

On Linux/macOS, replace the backtick line continuations with `\` and the
Windows path with the equivalent host path (e.g. `"$(pwd)/..":/app` run
from inside `Traitement_LAI/`).

**Troubleshooting**: if `pip install` fails on `rasterio` for your
platform/architecture (no prebuilt wheel available), switch the base
image to one with GDAL preinstalled (e.g. `ghcr.io/osgeo/gdal:ubuntu-small-latest`)
or add `RUN apt-get update && apt-get install -y gdal-bin libgdal-dev`
before the `pip install` step.

## Structure

```
Traitement_LAI/
├── commun/                        shared modules
│   ├── sl2p_network.py              SL2P network (xlsx parsing, vectorized application)
│   ├── lai_pipeline.py              applies the network to a bands+angles cube (source-agnostic)
│   ├── s2_safe_reader.py            reads a local .SAFE product (ESA)
│   └── theia_stac_reader.py         reads a Theia/MUSCATE product in streaming mode (STAC)
│
├── 01_calcul_LAI/                  LAI map computation
│   ├── compute_lai_map.py           from a local .SAFE
│   ├── compute_lai_map_theia.py     from the Theia STAC catalog (streaming, no download)
│   ├── preview_png.py               quick PNG preview of a LAI map
│   └── outputs/
│
├── 02_diff_vs_SNAP/                comparison against a SNAP output (Biophysical Processor)
│   ├── compute_diff_map.py          difference map (algo - SNAP)
│   ├── histogram_residus.py         residual histogram + quantified deviations
│   ├── preview_diff_png.py          PNG preview of the difference map
│   └── outputs/
│
└── 03_ndvi_vs_lai/                 NDVI/LAI physical consistency check
    ├── scatter_ndvi_lai.py           NDVI vs LAI density plot (expected saturation)
    └── outputs/
```

The network coefficients (`Algo_S2_V2.0_SL2T_{LAI,FAPAR,FCOVER}.xlsx`,
provided by Marie Weiss, valid for Sentinel-2A) are expected in
`../A_Marie_Weiss_Modele/` (one level above `Traitement_LAI/`).

## Usage

**Compute a LAI map from a local `.SAFE`:**
```bash
cd 01_calcul_LAI
python compute_lai_map.py "path/to/PRODUCT.SAFE" --var LAI
```

**Compute a LAI map from the Theia STAC catalog (no download):**
```bash
python compute_lai_map_theia.py --tile 31TEJ --date 2021-04-02 --var LAI
```

**Compare against a SNAP output:**
```bash
cd ../02_diff_vs_SNAP
python compute_diff_map.py
python histogram_residus.py
```

**Check the NDVI/LAI relationship:**
```bash
cd ../03_ndvi_vs_lai
python scatter_ndvi_lai.py
```

Each script writes its outputs to its own `outputs/` folder.

## Outputs

Each LAI map is a 1-band GeoTIFF (`float32`, NaN = no data), together with
a quality-flag GeoTIFF (`_QA.tif`, `uint8`):

| Flag | Meaning |
|---|---|
| 0 | OK |
| 1 | outside the definition domain (reflectance outside training bounds) |
| 2 | extreme case (output clamped or rejected per the network's tolerance) |
| 254 (Theia only) | masked by MG2/EDG (cloud/shadow/water/snow/hidden relief) |
| 255 | no data (image nodata, or SCL-masked on the ESA side) |

Each GeoTIFF also carries **provenance tags** (readable via
`rasterio.open(...).tags()`, QGIS, or `gdalinfo`): source product, S2
processing baseline (or Theia product version), coefficients file used,
processing date. See *Traceability* below.

## Important methodological notes

- **Acquisition geometry**: the angles (sun zenith, view zenith, relative
  azimuth) are read from the fine grid provided in the metadata (5 km
  cells, `MTD_TL.xml` on the ESA side / `MTD_ALL.xml` on the Theia side)
  and **bilinearly interpolated at pixel scale** — not a geometry
  recomputed from the satellite's orbit/attitude. The viewing angle is
  averaged over detectors and then over the 8 bands used, since the
  network only takes a single viewing geometry as input. Measured impact
  of this approximation versus a single tile-wide average angle: r=0.9997,
  RMSE=0.018 LAI (small but non-zero).
- **Definition domain**: the fine-grained check provided in the original
  Excel files (8D grid of valid cells) was found to wrongly reject
  otherwise valid test cases — a bug already present in the original
  script, reproduced identically when porting it. Replaced here with a
  bounding-box check (reflectance within the per-band training min/max),
  which correctly validates the 250 reference test cases.
- **BOA offset correction**: ESA products with baseline ≥ N0400 (January
  2022) apply an offset (`BOA_ADD_OFFSET`, typically -1000) to the stored
  reflectances. Read dynamically from each product's metadata, not
  hardcoded.
- **Validation**: implementation checked against the 250 test cases
  provided by Marie Weiss (r=0.994 on LAI) and against an actual SNAP
  Biophysical Processor output on 2 tiles/dates (r=0.997, RMSE
  0.04-0.06 LAI — see `02_diff_vs_SNAP/`).

## Traceability and S2 processing baseline

The ESA processing baseline (`PROCESSING_BASELINE`, e.g. `05.00`) or the
Theia product version (`PRODUCT_VERSION`) is read from each image's
metadata and written into the tags of the produced GeoTIFF. Goal: if ESA
or CNES updates their processing chain (atmospheric correction,
calibration...), be able to tell which already-produced LAI maps were
computed with which version — and therefore which ones might be worth
recomputing.

## Supported data sources

| | Local `.SAFE` (ESA) | Theia STAC (CNES, streaming) |
|---|---|---|
| Retrieval | manual download or CDSE | `api.stac.teledetection.fr`, no download |
| Atmospheric correction | Sen2Cor | MAJA |
| Metadata | `MTD_TL.xml` + `MTD_MSIL2A.xml` | `MTD_ALL.xml` |
| Quality mask | SCL | MG2 (bitwise) + EDG |
| Module | `commun/s2_safe_reader.py` | `commun/theia_stac_reader.py` |

Both sources were compared on the same tile/date (2021-04-02, T31TEJ):
r=0.982, RMSE=0.16 LAI — an expected and legitimate gap, due to the two
different atmospheric correction chains (not a code error).

## Known limitations / possible improvements

- The provided SL2P network is specific to Sentinel-2A. S2B/S2C
  coefficients exist (Marie Weiss) but are not yet integrated.
- Ma et al. (2025) algorithm — ensemble of 12 networks + median — not yet
  implemented (requires the 12 coefficient sets).
- Processing is not parallelized (one tile = one process, ~45-65 s/tile).
  For large-scale processing, see the block-based + SLURM architecture in
  `PHENOME-LAI/batch_lai_masse/` (a separate pipeline — see the
  methodological comparison earlier in the project's history).

## References

The SL2P network applied here was trained on simulations from the
PROSAIL radiative transfer model (PROSPECT leaf optics + SAIL canopy
reflectance), fit to the Sentinel-2 bands by Weiss & Baret. Foundational
and review references for that underlying model chain:

- Verhoef, W. (1984). Light scattering by leaf layers with application to
  canopy reflectance modeling: The SAIL model. *Remote Sensing of
  Environment*, 16(2), 125–141.
  [doi.org/10.1016/0034-4257(84)90057-9](https://doi.org/10.1016/0034-4257(84)90057-9)
- Jacquemoud, S., & Baret, F. (1990). PROSPECT: A model of leaf optical
  properties spectra. *Remote Sensing of Environment*, 34(2), 75–91.
  [doi.org/10.1016/0034-4257(90)90100-Z](https://doi.org/10.1016/0034-4257(90)90100-Z)
- Baret, F., Jacquemoud, S., Guyot, G., & Leprieur, C. (1992). Modeled
  analysis of the biophysical nature of spectral shifts and comparison
  with information content of broad bands. *Remote Sensing of
  Environment*, 41(2–3), 133–142. First publication combining PROSPECT
  and SAIL.
  [doi.org/10.1016/0034-4257(92)90073-S](https://doi.org/10.1016/0034-4257(92)90073-S)
- Jacquemoud, S., Verhoef, W., Baret, F., Bacour, C., Zarco-Tejada, P. J.,
  Asner, G. P., François, C., & Ustin, S. L. (2009). PROSPECT+SAIL
  models: A review of use for vegetation characterization. *Remote
  Sensing of Environment*, 113(Supplement 1), S56–S66. An older but
  thorough review, written by the model's principal developers.
  [doi.org/10.1016/j.rse.2008.01.026](https://doi.org/10.1016/j.rse.2008.01.026)

**SL2P / S2ToolBox algorithm:**
- Weiss, M., & Baret, F. (2020). *ATBD for S2ToolBox Level 2 products:
  LAI, FAPAR, FCOVER.* Version 2.1. INRAE. The ATBD describing the
  network weights used in this implementation.
  [step.esa.int/docs/extra/ATBD_S2ToolBox_L2B_V1.1.pdf](https://step.esa.int/docs/extra/ATBD_S2ToolBox_L2B_V1.1.pdf)

**PROSAIL R package** (a modern, maintained R implementation of the
PROSPECT+SAIL model chain referenced above):
- Package website:
  [jbferet.gitlab.io/prosail](https://jbferet.gitlab.io/prosail/index.html)
- "prosail: an R package to simulate canopy reflectance with the coupled
  model PROSAIL (PROSPECT + SAIL)." *Journal of Open Source Software*,
  11(125), 10451.
  [doi.org/10.21105/joss.10451](https://joss.theoj.org/papers/10.21105/joss.10451)
