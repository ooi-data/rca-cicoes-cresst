# Data Products

Curated data products from OOI Regional Cabled Array (RCA) profiler moorings and seafloor benthic packages.

## Contents

- [Setup](#setup)
- [Command overview](#command-overview)
- [Regridded Profiler Mooring Profiles](#regridded-profiler-mooring-profiles) (`regrid-profiler`)
- [Fixed Instrument Time Series](#fixed-instrument-time-series) (`fixed-instruments`)
- [QC Steps and Adjustments](#qc-steps-and-adjustments) (`config/adjustments.csv`)
- [HITL Annotations](#hitl-annotations) (`harvest-annotations`, `curate-annotations`)
- [Advanced pH QC](#advanced-ph-qc)
- [Binned Profiles](#binned-profiles-bin-dataset) (`bin-dataset`)
- [Syncing Products](#syncing-products-sync-cresst) (`sync-cresst`)

## Setup

```bash
pip install -e .
```

Python ≥3.10. Core dependencies (xarray, zarr, s3fs, numpy, pandas, click, loguru) install automatically; LLM curation additionally needs `anthropic` (`pip install -e ".[curate]"`). Reading OOI/RCA S3 data is anonymous — no credentials needed. Credentials are required only for: harvesting/curating annotations (`OOI_USERNAME`, `OOI_TOKEN`, and `ANTHROPIC_API_KEY` for LLM curation, in a local `.env`) and writing with `sync-cresst` (AWS credentials).

**Outputs & layout.** `regrid-profiler` and `fixed-instruments` write to the **current directory** and logs to `logs/`; `bin-dataset` writes to `data/binned/`. The convention is to keep finished products under `data/` — run the generators from `data/` (or move outputs there), since `sync-cresst` mirrors `data/` to S3.

## Command overview

| Command | Purpose |
|---------|---------|
| `regrid-profiler` | Regrid shallow/deep profiler data onto a uniform pressure grid |
| `fixed-instruments` | Resample fixed-instrument (PC platform + seafloor BEP) data to a common time grid |
| `bin-dataset` | Bin a regridded profiler dataset along the time axis |
| `harvest-annotations` | Fetch raw HITL annotations from the OOI M2M API |
| `curate-annotations` | Propose ledger decisions for new or OOI-edited annotations |
| `sync-cresst` | Push local products in `data/` to an S3 prefix (default `rca-advanced-qaqc/cresst`) |

> **Before building `--qaqc-filter highest` products,** run `harvest-annotations --all` and `curate-annotations --all`, then approve any proposals. OOI edits annotations after the fact, so stale or unreviewed annotations mask the wrong data. See [HITL Annotations](#hitl-annotations).

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

### Building the profiler product (`regrid-profiler`)

Run from `data/`; outputs land in the current directory and logs in `logs/`. For `--qaqc-filter highest`, run the [annotation steps](#before-every-product-build) first.

| Option | Effect | Filename suffix |
|--------|--------|-----------------|
| `--grid START STOP STEP` | Pressure grid in dbar (profiler only) | — |
| `--qaqc-filter none` | No QC masking (adjustments still apply) | — |
| `--qaqc-filter basic` | Mask QARTOD fail (4) and missing (9) | `_qf49` |
| `--qaqc-filter highest` | `basic` plus approved HITL ledger masks | `_qf49_HITL` |
| `--ph-advanced` | Also mask pH where any advanced pH test failed ([details](#advanced-ph-qc)) | `_phadv` |
| `--format zarr\|nc\|both` | Output format | extension |

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
<site>_profiles_<start>_<end>[_qf<flags>][_HITL][_phadv].<ext>
```

| Component | Description |
|-----------|-------------|
| `<site>` | Site key (e.g. `axial_base`) |
| `<start>` / `<end>` | Date range of profiles in the file (`YYYYMMDD`) |
| `_qf<flags>` | QARTOD flags removed (`49` = fail + missing); omitted when `--qaqc-filter none` |
| `_HITL` | Approved HITL ledger masks applied; present only with `--qaqc-filter highest` |
| `_phadv` | Advanced pH masking applied; present only with `--ph-advanced` |
| `<ext>` | `zarr` or `nc` |

Examples:

```
axial_base_profiles_20150107_20260604.zarr
axial_base_profiles_20150107_20260604_qf49.nc
axial_base_profiles_20150107_20260604_qf49_HITL.zarr
```

See `regrid-profiler --help` for full options.

## Fixed Instrument Time Series

Time-series datasets from fixed (non-profiling) instruments: the shallow profiler mooring 200 m platforms (PC nodes) and the seafloor Benthic Experiment Packages (BEP / LJ nodes). The same QAQC as the regridded profiler product (QARTOD flag masking + HITL ledger masking, plus optional advanced pH masking) is applied at native resolution, then each instrument is resampled to a common time grid (hourly means by default) and merged into one dataset per site.

### Sites and Instruments

| Key | Platform | Depth | CTD (T/S/ρ/DO) | pH | pCO₂ | Fluorometer |
|-----|----------|-------|-----|----|------|-------------|
| `oregon_offshore` | CE04OSPS-PC01B | 200 m | ✓ | ✓ | ✓ | — |
| `slope_base` | RS01SBPS-PC01A | 200 m | ✓ | ✓ | — | ✓ |
| `axial_base` | RS03AXPS-PC03A | 200 m | ✓ | ✓ | — | ✓ |
| `oregon_offshore_seafloor` | CE04OSBP-LJ01C | ~580 m | ✓ | ✓ | *excluded* | — |
| `oregon_shelf_seafloor` | CE02SHBP-LJ01D | ~80 m | ✓ | ✓ *(stitched)* | *excluded* | — |
| `slope_base_seafloor` | RS01SLBS-LJ01A | ~2900 m | ✓ | — | — | — |
| `axial_base_seafloor` | RS03AXBS-LJ03A | ~2600 m | ✓ | — | — | — |

All four `*_seafloor` sites are Benthic Experiment Packages (BEPs). The two Oregon Coastal Endurance BEPs carry CTD, pH and pCO₂, but pCO₂ is left out of this product until it can be offset and reviewed by an SME; the two deep cabled packages (Slope Base, Axial Base) carry only a CTD in this product — they also host OPTAA, ADCP, and HPIES, but no pH/pCO₂/fluorometer. The CTDs at all fixed sites report DO through the CTD stream (integrated optode), unlike the deep profilers which use a standalone DOSTA. OPTAA (spectral absorption/attenuation) is excluded from this product.

### Data Variables

CTD: `sea_water_temperature`, `sea_water_practical_salinity`, `corrected_dissolved_oxygen`, `sea_water_density`, `sea_water_pressure` · pH: `ph_seawater` (at Oregon Shelf, the archived PHSEND record followed by the active PHSENH `ph_total`, stitched without scale conversion; see the variable's `source_note`) · pCO₂: `pco2_seawater` · Fluorometer: `fluorometric_chlorophyll_a`, `fluorometric_cdom`, `optical_backscatter`. Only the instruments present at a site (see table) appear in its output. All variables share a single `time` dimension (bin left edges); empty bins are NaN.

**Dissolved oxygen splice:** during the optode DAC firmware-noise windows (~2017–2021; exact per-site windows are the `substitute` rows in `config/adjustments.csv`), the onboard-calculated `dissolved_oxygen` product and its QARTOD flags are substituted into `corrected_dissolved_oxygen` per OOI annotation guidance, keeping the DO record continuous. Documented on the variable's `adjustments` attribute. Applies to the PC platforms and the BEP/seafloor CTDs (every fixed site with the integrated optode).

### Building the fixed time series (`fixed-instruments`)

Same working directory, prerequisites and QC options as the [profiler build](#building-the-profiler-product-regrid-profiler); instead of `--grid`, use `--resample FREQ` (bin width, default `1h`) and `--start-year` / `--end-year`.

```bash
# PC platforms (200 m)
fixed-instruments slope_base --format both --qaqc-filter highest --ph-advanced
fixed-instruments oregon_offshore --format both --qaqc-filter highest --ph-advanced
fixed-instruments axial_base --format both --qaqc-filter highest --ph-advanced

# Oregon seafloor BEPs (CTD + pH; pCO₂ excluded pending offset review)
fixed-instruments oregon_offshore_seafloor --format both --qaqc-filter highest
fixed-instruments oregon_shelf_seafloor --format both --qaqc-filter highest

# deep cabled seafloor BEPs (CTD only)
fixed-instruments slope_base_seafloor --format both --qaqc-filter highest
fixed-instruments axial_base_seafloor --format both --qaqc-filter highest

# custom bin width or year range
fixed-instruments axial_base --resample 30min --start-year 2020 --end-year 2024
```

Output naming:

```
<site>_fixed_<start>_<end>_<freq>[_qf<flags>][_HITL][_phadv].<ext>
```

`<freq>` is the `--resample` bin width; the other components match the [profiler naming](#building-the-profiler-product-regrid-profiler). Example: `slope_base_fixed_20150101_20260630_1h_qf49_HITL_phadv.nc`

See `fixed-instruments --help` for full options.

## QC Steps and Adjustments

Both pipelines apply the same QC steps in the same order, at native resolution, before gridding or resampling. Each product records the order in its `qc_steps` attribute.

1. **Adjustments**: rows in `config/adjustments.csv` (below), applied to each raw stream.
2. **Advanced pH**: with `--ph-advanced` (see [Advanced pH QC](#advanced-ph-qc)).
3. **HITL ledger**: with `--qaqc-filter highest` (see [HITL Annotations](#hitl-annotations)).
4. **QARTOD**: with `basic` or `highest`, each variable is set to NaN where its own flag is fail (4) or missing (9). The flag variables are not written to products.

The shelf pH stitch combines the archived PHSEND and active PHSENH records after steps 1–2 have run on each source.

### `config/adjustments.csv`

One row per window-based fix that OOI's annotations don't handle: a substitution, an offset, or a mask OOI hasn't annotated. Each row changes one variable. When a new one-off problem turns up, add a row here instead of code, and review it in a PR like the ledger.

| Column | What it means | Values |
|--------|---------------|--------|
| `id` | Unique row number, quoted in the variable's `adjustments` attribute | integer; never reuse one |
| `refdes` | Instrument stream the row applies to | full reference designator, e.g. `CE02SHBP-LJ01D-10-PHSENH110` |
| `variable` | Variable to change, using the stream's own name | e.g. `ph_total` (before the shelf stitch renames it to `ph_seawater`) |
| `action` | What to do inside the window | `mask`: set to NaN<br>`substitute`: replace with `source` (and its QARTOD flags)<br>`offset`: add `value` |
| `source` | For `substitute`: the stream variable to use instead | e.g. `dissolved_oxygen`; empty otherwise |
| `value` | For `offset`: amount to add, in the variable's units | empty otherwise |
| `begin`, `end` | Window in UTC, inclusive | ISO 8601; empty `end` = to the end of the data |
| `annotation_id` | OOI annotation this row implements, if any | e.g. `4348`; empty if none |
| `rationale` | Why the row exists. The first thing a reviewer reads. | free text |

Edit it by hand or with an LLM; the decision rules are in `CLAUDE.md`. Changes take effect on the next build.

## HITL Annotations

OOI's human-in-the-loop (HITL) annotations flag time windows of bad or suspect data. Each annotation gets one reviewed decision in `annotations/ledger.csv`, which `--qaqc-filter highest` applies.

| File | Contents |
|------|----------|
| `annotations/ledger.csv` | One reviewed decision per annotation `id`: `mask`, `ignore`, or `superseded`. The only file people edit. |
| `annotations/raw/<SUBSITE>.csv` | Raw annotations from the OOI M2M API, overwritten on each harvest |
| `annotations/raw/harvest_manifest.csv` | When each subsite was last harvested, written by `harvest-annotations` |

The pipelines:

- apply only approved `mask` rows, with windows from the latest harvest (closed windows flow in automatically)
- add products OOI computes from a masked CTD salinity: DO; salinity-corrected nitrate on profiler nodes; shelf `ph_total` after 2025-08-28 (see `CLAUDE.md`, and [docs/parameter_dependencies.md](docs/parameter_dependencies.md) for OOI's dependency graph)
- write `hitl_annotations_harvested` and `hitl_ledger_sha1` to the output attrs
- warn when the harvest is over 30 days old, or when annotations are missing from the ledger, edited by OOI since review, or still `proposed`

### The ledger, column by column

Each row is one decision about one OOI annotation. To read the annotation itself (text, dates, instrument, OOI's qcFlag), look up the same `id` in `annotations/raw/<subsite>.csv`.

| Column | What it means | Values | Edit it? |
|--------|---------------|--------|----------|
| `id` | OOI's annotation id. Links the row to the harvested annotation; one row per id. | integer | Never |
| `subsite` | Mooring or seafloor site the annotation belongs to. | e.g. `RS03AXPS` | Never |
| `decision` | What the products do during the annotation's time window. | `mask`: set the listed variables to NaN<br>`ignore`: no effect (not data-affecting, non-product instrument, or a real ocean event like a blowdown)<br>`superseded`: handled another way (e.g. the DO splice in `config/adjustments.csv`), so not masked | Yes |
| `parameters_affected` | Variables to mask when `decision` is `mask`; empty otherwise. List only the directly affected variables: products OOI computes from a masked salinity (DO, nitrate, shelf pH) are added automatically. | Python-style list, e.g. `['sea_water_practical_salinity', 'sea_water_density']` (spreadsheets add the surrounding CSV quotes). Valid names below. | Yes |
| `parameters_source` | Where the parameter list came from. | `official`: OOI's own `parameters` field<br>`llm`: chosen from the annotation text<br>`human`: chosen by a reviewer<br>`+inherited` suffix: the list already includes salinity-derived products<br>empty for `ignore` / `superseded` | Yes, when you change the list |
| `rationale` | One sentence explaining the decision. The first thing a reviewer reads. | free text | Yes |
| `decided_by` | Who made the decision. | `human`, `rule` (instrument not in any product), `llm:<model>` (`curate-annotations`), `claude (in-session review)`, `llm (pre-ledger)` (made before 2026-10-16, never human-reviewed) | Yes, set to `human` when you decide |
| `status` | Whether the pipelines apply the row. | `proposed`: waiting for review, not applied<br>`approved`: applied | Yes, to approve |
| `reviewed_at` | Date the decision was last checked by a person or review session. | `YYYY-MM-DD`; empty if never reviewed | Yes, set to today |
| `content_hash` | Fingerprint of OOI's annotation (text, qcFlag, parameters, refdes) at the time of the decision. If OOI edits the annotation, the fingerprint stops matching and the row comes back for review. It fingerprints OOI's annotation, not your decision. | 10 hex characters | Never |

Valid `parameters_affected` names: `sea_water_temperature`, `sea_water_practical_salinity`, `sea_water_density`, `corrected_dissolved_oxygen`, `ph_seawater`, `ph_total`, `pco2_seawater`, `partial_pressure_co2_ssw`, `xco2_atm`, `salinity_corrected_nitrate`, `nitrate_concentration`, `fluorometric_chlorophyll_a`, `fluorometric_cdom`, `optical_backscatter`, `flcdr_x_mmp_cds_fluorometric_cdom` (full list: `PARAM_TO_INSTRUMENT` in `common.py`). The pipelines warn about any other name.

### Editing the ledger

By hand, in a spreadsheet or text editor:

1. Find the row by `id` and read the annotation in `annotations/raw/<subsite>.csv`.
2. Set `decision`, `parameters_affected`, `parameters_source` and `rationale`.
3. Set `decided_by` to `human`, `status` to `approved`, and `reviewed_at` to today.
4. Leave `id`, `subsite` and `content_hash` alone, and don't add rows by hand. `curate-annotations` creates rows for new annotations.
5. Check: `curate-annotations --all` reports 0 annotations needing a decision, and a `--qaqc-filter highest` run logs no ledger warnings.
6. Commit through a PR. The diff shows exactly which decisions changed.

With an LLM (e.g. Claude Code), point it at the rows and at `CLAUDE.md`, which holds the decision rules. For example: *"Review the `proposed` rows in annotations/ledger.csv. For each, read the annotation text, apply the rules in CLAUDE.md, and fill in `decision`, `parameters_affected`, `parameters_source` and `rationale`. Leave `status` as `proposed` for me to approve."* Keep approval with a person.

### Before every product build

```bash
harvest-annotations --all          # needs OOI_USERNAME / OOI_TOKEN in .env
curate-annotations --all           # proposes decisions for new or OOI-edited annotations; needs ANTHROPIC_API_KEY
git diff annotations/ledger.csv    # review the proposals
```

Approve a proposal by setting `status=approved` and `reviewed_at`, then commit through a PR. `curate-annotations` ignores annotations on non-product instruments by rule and asks Claude to judge the rest. OOI's official `parameters` (mapped through the preload `netcdf_name`) override Claude's parameter choice. Approved rows are never overwritten; an annotation OOI edits comes back as `proposed`.

Both commands also take single sites, e.g. `harvest-annotations oregon_offshore` or `curate-annotations CE04OSPS`. Decision rules (corrected calibrations, blowdowns, parameter inheritance) are in `CLAUDE.md`.

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

Flag products exist for the PC-platform and profiler PHSEN sensors and the archived Oregon Shelf
PHSEND (the pre-2025 part of the stitched shelf record). There are none for the Oregon Offshore
BEP or the active shelf PHSENH, so the option does nothing there. Works on both `fixed-instruments` and `regrid-profiler`; the
output filename gets a `_phadv` suffix.

## Binned Profiles (`bin-dataset`)

Bin a pressure-gridded profiler dataset along the time axis:

```
<input_stem>_binned_<N>h.<ext>
```

Example:

```
axial_base_profiles_20150107_20260604_qf49_HITL_binned_24h.zarr
```

```bash
bin-dataset data/axial_base_profiles_20150107_20260604_qf49_HITL.zarr --bin 24
bin-dataset data/axial_base_profiles_20150107_20260604_qf49_HITL.zarr --bin 24 --format both
```

Output is written to `data/binned/`. See `bin-dataset --help` for full options.

## Syncing Products (`sync-cresst`)

Push local products in `data/` up to an S3 prefix (default `rca-advanced-qaqc/cresst`, change with `--bucket`), matching by product identity (uploads when the local end date is newer or the same-range content changed). Dry-run by default; `--apply` writes (needs AWS credentials), `--delete-remote-only-data` also removes bucket files with no local counterpart.

```bash
sync-cresst                                   # preview the plan
sync-cresst --apply                           # upload + remove superseded same-identity copies
sync-cresst --apply --delete-remote-only-data # also delete bucket-only files
sync-cresst --bucket my-bucket/cresst-test     # preview against another bucket/prefix
```
