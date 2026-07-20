# Data Products

Curated data products from OOI Regional Cabled Array (RCA) profiler moorings.

## Regridded Profiler Mooring Profiles

A multi-instrument, pressure-gridded dataset derived from RCA profiler mooring data. Time-series data from the OOI S3 zarr store is sliced into individual profiles using the [OOI profile index](https://github.com/OOI-CabledArray/profileIndices), deduplicated on pressure, and interpolated onto a uniform pressure grid.

### Sites

#### Shallow Profilers

Science pod winched through the upper water column. ~9 profiles/day.

| Key | Site | Depth Range | CTD Refdes |
|-----|------|-------------|------------|
| `oregon_offshore` | Coastal Endurance Oregon Offshore | 5–200 m | CE04OSPS-SF01B-2A-CTDPFA107 |
| `slope_base` | Oregon Slope Base | 5–200 m | RS01SBPS-SF01A-2A-CTDPFA102 |
| `axial_base` | Axial Base | 5–200 m | RS03AXPS-SF03A-2A-CTDPFA302 |

#### Deep Profilers

| Key | Site | Depth Range | Water Depth | CTD Refdes |
|-----|------|-------------|-------------|------------|
| `oregon_offshore_deep` | Coastal Endurance Oregon Offshore | 175–500 m | 576 m | CE04OSPD-DP01B-01-CTDPFL105 |
| `slope_base_deep` | Oregon Slope Base | 150–2,900 m | 2,900 m | RS01SBPD-DP01A-01-CTDPFL104 |
| `axial_base_deep` | Axial Base | 150–2,465 m | 2,604 m | RS03AXPD-DP03A-01-CTDPFL304 |

### Dimensions

| Dimension | Description |
|-----------|-------------|
| `profile_number` | Integer profile index from the OOI profile index CSV |
| `sea_water_pressure` | Uniform pressure grid (dbar), set via `--grid` |

### Coordinates

| Coordinate | Type | Description |
|------------|------|-------------|
| `profile_number` | `int` | Primary dimension |
| `start_time` | `datetime64` | Profiler upcast start (platform depth) |
| `peak_time` | `datetime64` | Profiler peak (shallowest point) |
| `end_time` | `datetime64` | Profiler downcast end (platform depth) |

Time coordinates are interchangeable with `profile_number` via `ds.swap_dims({"profile_number": "peak_time"})`.

### Data Variables

All variables are sampled on the upcast except `ph_seawater` and `pco2_seawater` (downcast).

| Variable | Shallow | Deep |
|----------|---------|------|
| `sea_water_temperature` | CTD (CTDPFA) | CTD (CTDPFL) |
| `sea_water_practical_salinity` | CTD (CTDPFA) | CTD (CTDPFL) |
| `corrected_dissolved_oxygen` | CTD (CTDPFA) | Oxygen (DOSTAD) |
| `sea_water_density` | CTD (CTDPFA) | CTD (CTDPFL) |
| `salinity_corrected_nitrate` | Nitrate (NUTNRA) | — |
| `ph_seawater` | pH (PHSENA) | — |
| `pco2_seawater` | pCO₂ (PCO2WA) | — |
| `fluorometric_chlorophyll_a` | — | Fluorometer (FLNTUA) |
| `flcdr_x_mmp_cds_fluorometric_cdom` | — | CDOM (FLCDRA) |

### Generating the Data Product

```bash
# shallow profilers (~0–200 m)
regrid-profiler oregon_offshore --grid 0 200 1 --format both --qaqc-filter highest
regrid-profiler axial_base --grid 0 200 1 --format both --qaqc-filter highest
regrid-profiler slope_base --grid 0 200 1 --format both --qaqc-filter highest

# deep profilers (site-dependent depth range)
regrid-profiler oregon_offshore_deep --grid 175 590 1 --format both --qaqc-filter highest
regrid-profiler slope_base_deep --grid 150 2900 1 --format both --qaqc-filter highest
regrid-profiler axial_base_deep --grid 150 2600 1 --format both --qaqc-filter highest
```

Output naming:

```
<site>_profiles_<start>_<end>[_qf<flags>][_HITL].<ext>
```

| Component | Description |
|-----------|-------------|
| `<site>` | Site key (e.g. `axial_base`) |
| `<start>` / `<end>` | Date range of profiles in the file (`YYYYMMDD`) |
| `_qf<flags>` | QARTOD flags removed (`49` = fail + missing); omitted when `--qaqc-filter none` |
| `_HITL` | Curated HITL annotation masking applied; present only with `--qaqc-filter highest` |
| `<ext>` | `zarr` or `nc` |

Examples:

```
axial_base_profiles_20150107_20260511.zarr
axial_base_profiles_20150107_20260511_qf49.nc
axial_base_profiles_20150107_20260511_qf49_HITL.zarr
```

See `regrid-profiler --help` for full options.

## Fixed Instrument Time Series

Time-series datasets from fixed (non-profiling) instruments: the shallow profiler mooring 200 m platforms (PC nodes) and the seafloor Benthic Experiment Packages (BEP / LJ nodes). The same QAQC as the regridded profiler product (QARTOD flag masking + curated HITL annotation masking, plus optional advanced pH masking) is applied at native resolution, then each instrument is resampled to a common time grid (hourly means by default) and merged into one dataset per site.

### Sites and Instruments

| Key | Platform | Depth | CTD (T/S/ρ/DO) | pH | pCO₂ | Fluorometer |
|-----|----------|-------|-----|----|------|-------------|
| `oregon_offshore` | CE04OSPS-PC01B | 200 m | ✓ | ✓ | ✓ | — |
| `slope_base` | RS01SBPS-PC01A | 200 m | ✓ | ✓ | — | ✓ |
| `axial_base` | RS03AXPS-PC03A | 200 m | ✓ | ✓ | — | ✓ |
| `oregon_offshore_bep` | CE04OSBP-LJ01C | ~580 m | ✓ | ✓ | ✓ | — |
| `oregon_shelf_bep` | CE02SHBP-LJ01D | ~80 m | ✓ | ✓ *(total)* | ✓ | — |
| `slope_base_ctd` | RS01SLBS-LJ01A | ~2900 m | ✓ | — | — | — |
| `axial_base_ctd` | RS03AXBS-LJ03A | ~2600 m | ✓ | — | — | — |

The two Oregon Coastal Endurance BEPs (`*_bep`) carry the full carbon suite (CTD, pH, pCO₂). The two deep cabled seafloor packages (`*_ctd`) carry only a CTD in this product — they also host OPTAA, ADCP, and HPIES, but no pH/pCO₂/fluorometer. The CTDs at all fixed sites report DO through the CTD stream (integrated optode), unlike the deep profilers which use a standalone DOSTA. OPTAA (spectral absorption/attenuation) is excluded from this product.

### Data Variables

CTD: `sea_water_temperature`, `sea_water_practical_salinity`, `corrected_dissolved_oxygen`, `sea_water_density`, `sea_water_pressure` · pH: `ph_seawater` (PHSEN) or `ph_total` (PHSENH at Oregon Shelf) · pCO₂: `pco2_seawater` · Fluorometer: `fluorometric_chlorophyll_a`, `fluorometric_cdom`, `optical_backscatter`. Only the instruments present at a site (see table) appear in its output. All variables share a single `time` dimension (bin left edges); empty bins are NaN.

**Dissolved oxygen splice:** during the optode DAC firmware-noise windows (~2017–2021; exact per-site windows hardcoded in `DO_SPLICE_WINDOWS` in `fixed_instruments.py`), the onboard-calculated `dissolved_oxygen` product and its QARTOD flags are substituted into `corrected_dissolved_oxygen` per OOI annotation guidance, keeping the DO record continuous. Documented on the variable's `source_note` attribute. Applies to the PC platforms only.

### Generating the Data Product

```bash
# PC platforms (200 m)
fixed-instruments slope_base --format both --qaqc-filter highest --ph-advanced
fixed-instruments oregon_offshore --format both --qaqc-filter highest --ph-advanced
fixed-instruments axial_base --format both --qaqc-filter highest --ph-advanced

# seafloor BEPs — Oregon carbon suite
fixed-instruments oregon_offshore_bep --format both --qaqc-filter highest
fixed-instruments oregon_shelf_bep --format both --qaqc-filter highest

# deep cabled seafloor CTDs
fixed-instruments slope_base_ctd --format both --qaqc-filter highest
fixed-instruments axial_base_ctd --format both --qaqc-filter highest

# custom bin width or year range
fixed-instruments axial_base --resample 30min --start-year 2020 --end-year 2024
```

Output naming:

```
<site>_fixed_<start>_<end>_<freq>[_qf<flags>][_HITL][_phadv].<ext>
```

Example: `slope_base_fixed_20150101_20260630_1h_qf49_HITL_phadv.nc`

See `fixed-instruments --help` for full options.

## HITL Annotations

Raw annotations are harvested from the OOI M2M API and saved to `annotations/<SUBSITE>.csv`.
Curated annotations (data-quality relevant only, with `parameters_affected`) live in `annotations/curated/<SUBSITE>_llm.csv`. Curation runs for different nodes merge into the same file (deduplicated by annotation id); the pipelines filter annotations to the nodes they process.

Requires `OOI_USERNAME` and `OOI_TOKEN` in `.env` (and `ANTHROPIC_API_KEY` for LLM curation).

```bash
# harvest one site (accepts site key or raw subsite code)
harvest-annotations oregon_offshore
harvest-annotations CE04OSPS

# harvest all profiler sites
harvest-annotations --all
```

Curate with qcFlag filtering:

```bash
curate-annotations CE04OSPS --qc-flag fail --qc-flag suspect
```

LLM curation (per node, mapping sensor codes to instrument keys):

```bash
# science pod (shallow profiler)
curate-annotations CE04OSPS --node SF01B \
    --sensor 2A-CTDPFA107:ctd --sensor 2B-PHSENA108:ph \
    --sensor 4F-PCO2WA102:pco2 --sensor 4A-NUTNRA102:nutrients

# fixed 200 m platform
curate-annotations CE04OSPS --node PC01B \
    --sensor 4A-CTDPFA109:ctd --sensor 4A-DOSTAD109:o2 \
    --sensor 4B-PHSENA106:ph --sensor 4D-PCO2WA105:pco2
```

## Advanced pH QC

An optional extra masking layer for pH, driven by the precomputed advanced pH flags
in the `rca-advanced-qaqc` S3 bucket (from `rca_data_tools.qaqc.advanced_qaqc.ph_advanced_flags`).
Each raw sample carries a positional flag string, one digit per test (`1` pass / `3` fail):

| Test | Meaning |
|------|---------|
| `low_indicator_signal` | indicator signal getting low (possible pump/flow issue) |
| `flat_indicator_signal` | flat indicator signal (pump starting to fail) |
| `erratic_reference` | erratic reference measurements |
| `failed_blank` | DI blank saturated or too low |
| `failed_intensity` | signal intensity saturated or too low |
| `flat_intensity` | flat signal intensity (pump not working / flow cell obstructed) |

Passing `--ph-advanced` NaNs `ph_seawater` wherever **any** test fails (the flag string
contains a `3`), per science-lead guidance. This is aggressive — the `low_indicator_signal`
test alone fires on a large fraction of samples — so expect substantial pH data loss; it is
opt-in for that reason.

Available for the PC-platform and profiler PHSEN sensors (where the flag products exist); the flag
is a no-op for the seafloor BEP pH. Works on both `fixed-instruments` and `regrid-profiler`; the
output filename gets a `_phadv` suffix.

## Binned Profiles (`bin-dataset`)

Bin a pressure-gridded profiler dataset along the time axis:

```
<input_stem>_binned_<N>h.<ext>
```

Example:

```
axial_base_profiles_20150107_20260511_binned_24h.zarr
```

```bash
bin-dataset axial_base_profiles_20150107_20260511.zarr --bin 24
bin-dataset axial_base_profiles_20150107_20260511.zarr --bin 24 --format both
```

Output is written to `data/binned/`. See `bin-dataset --help` for full options.
