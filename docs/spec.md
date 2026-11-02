# RCA-CRESST Data Products: Product Specification

**Version 0.1 (draft), 2026-10-28.** Describes the products as built on 2026-10-23 and published to
`s3://rca-advanced-qaqc/cresst-one-easy-rca/`. Rules are numbered (R1, R2, …) so they can be
cited, and each is meant to become a test. Nothing in this version is guaranteed between
releases yet (see [Versioning](#10-versioning-and-release)).

## 1. Purpose and audience

Good-quality, easy-to-use time series and profiles of Essential Ocean Variables from the OOI
Regional Cabled Array (RCA), for scientists and modelers who don't want to work through OOI's
raw streams, QC flags and annotations. Every value in a product has passed the QC in section 6,
and nothing else: no flag variables, no data modes. Values that fail are NaN.

The full-detail tier is OOI's own zarr archive (`s3://ooi-data/`), which keeps every sample and
flag. These products are a curated, gridded layer on top of it.

## 2. Products

| Product | What it is | Files |
|---|---|---|
| Profiler profiles | Each profiler cast interpolated onto a fixed pressure grid | 6 sites |
| Profiler daily bins | Profiler profiles averaged into 24 h time bins | 6 sites |
| Fixed time series | Fixed-depth instruments averaged into 1 h time bins | 7 sites |

Each is published as both zarr and netCDF with the same content.

## 3. Sites and input streams

Instruments are identified by OOI reference designator (refdes). Each refdes maps to one OOI
stream via the `zarrFile` column of the rca-data-tools params
([`sitesDictionary.csv`](https://github.com/OOI-CabledArray/rca-data-tools/blob/main/rca_data_tools/qaqc/params/sitesDictionary.csv)
for active instruments, `archiveDictionary.csv` for retired ones), which is the source of truth.
Which instruments feed each product is set in [`config/sites.csv`](../config/sites.csv); loading
fails if a refdes there is missing from the rca-data-tools params.

### 3.1 Shallow profilers (science pod, ~9 casts/day, 5–200 m)

| Site key | CTD | pH | pCO₂ | Nitrate |
|---|---|---|---|---|
| `oregon_offshore` | CE04OSPS-SF01B-2A-CTDPFA107 | CE04OSPS-SF01B-2B-PHSENA108 | CE04OSPS-SF01B-4F-PCO2WA102 | CE04OSPS-SF01B-4A-NUTNRA102 |
| `slope_base` | RS01SBPS-SF01A-2A-CTDPFA102 | RS01SBPS-SF01A-2D-PHSENA101 | RS01SBPS-SF01A-4F-PCO2WA101 | RS01SBPS-SF01A-4A-NUTNRA101 |
| `axial_base` | RS03AXPS-SF03A-2A-CTDPFA302 | RS03AXPS-SF03A-2D-PHSENA301 | RS03AXPS-SF03A-4F-PCO2WA301 | RS03AXPS-SF03A-4A-NUTNRA301 |

### 3.2 Deep profilers (archived streams, through 2025)

| Site key | CTD | Oxygen | Fluorometer | CDOM |
|---|---|---|---|---|
| `oregon_offshore_deep` | CE04OSPD-DP01B-01-CTDPFL105 | CE04OSPD-DP01B-06-DOSTAD105 | CE04OSPD-DP01B-04-FLNTUA103 | CE04OSPD-DP01B-03-FLCDRA103 |
| `slope_base_deep` | RS01SBPD-DP01A-01-CTDPFL104 | RS01SBPD-DP01A-06-DOSTAD104 | RS01SBPD-DP01A-04-FLNTUA102 | RS01SBPD-DP01A-03-FLCDRA102 |
| `axial_base_deep` | RS03AXPD-DP03A-01-CTDPFL304 | RS03AXPD-DP03A-06-DOSTAD304 | RS03AXPD-DP03A-03-FLNTUA302 | RS03AXPD-DP03A-03-FLCDRA302 |

### 3.3 Fixed instruments

| Site key | Platform, depth | CTD | pH | pCO₂ | Fluorometer |
|---|---|---|---|---|---|
| `oregon_offshore` | 200 m platform | CE04OSPS-PC01B-4A-CTDPFA109 | CE04OSPS-PC01B-4B-PHSENA106 | CE04OSPS-PC01B-4D-PCO2WA105 | — |
| `slope_base` | 200 m platform | RS01SBPS-PC01A-4A-CTDPFA103 | RS01SBPS-PC01A-4B-PHSENA102 | — | RS01SBPS-PC01A-4C-FLORDD103 |
| `axial_base` | 200 m platform | RS03AXPS-PC03A-4A-CTDPFA303 | RS03AXPS-PC03A-4B-PHSENA302 | — | RS03AXPS-PC03A-4C-FLORDD303 |
| `oregon_offshore_seafloor` | seafloor, ~580 m | CE04OSBP-LJ01C-06-CTDBPO108 | CE04OSBP-LJ01C-10-PHSEND107 | excluded | — |
| `oregon_shelf_seafloor` | seafloor, ~80 m | CE02SHBP-LJ01D-06-CTDBPN106 | CE02SHBP-LJ01D-10-PHSEND103, then -PHSENH110 (R14) | excluded | — |
| `slope_base_seafloor` | seafloor, ~2900 m | RS01SLBS-LJ01A-12-CTDPFB101 | — | — | — |
| `axial_base_seafloor` | seafloor, ~2600 m | RS03AXBS-LJ03A-12-CTDPFB301 | — | — | — |

- **R1.** Seafloor pCO₂ (CE04OSBP-LJ01C-09-PCO2WB104, CE02SHBP-LJ01D-09-PCO2WB103) is excluded
  until it has been offset and reviewed by a subject-matter expert.
- **R2.** Data start on 2015-01-01. Earlier data, where they exist, are not included.

## 4. Variables

Names, units and `long_name` / `standard_name` attributes are OOI's, carried through unchanged.

| Variable | Units | Instrument | In |
|---|---|---|---|
| `sea_water_temperature` | degrees_Celsius | CTD | all |
| `sea_water_practical_salinity` | 1 (PSS-78) | CTD | all |
| `sea_water_density` | kg m-3 | CTD | all |
| `sea_water_pressure` | dbar | CTD | fixed (variable); profiler (grid coordinate) |
| `corrected_dissolved_oxygen` | umol kg-1 | CTD (integrated sensor) or DOSTA (deep profilers) | all |
| `ph_seawater` | 1 (total scale per OOI's `standard_name`) | PHSEN; PHSENH on the shelf after 2025-08-28 | shallow profilers, fixed |
| `pco2_seawater` | uatm | PCO2W | shallow profilers, `oregon_offshore` fixed |
| `salinity_corrected_nitrate` | umol L-1 | NUTNR | shallow profilers |
| `fluorometric_chlorophyll_a` | ug L-1 | FLORD | PC fixed (missing from deep profilers, section 9) |
| `fluorometric_cdom` | ppb | FLORD | PC fixed |
| `flcdr_x_mmp_cds_fluorometric_cdom` | ppb | FLCDR | deep profilers |
| `optical_backscatter` | m-1 | FLORD | PC fixed |

A site's file contains only the variables its instruments provide (section 3).
`docs/parameter_dependencies.md` explains how OOI computes each from the raw measurements.

## 5. Processing

### 5.1 Profiler profiles

- **R3.** Casts come from the OOI [profile index](https://github.com/OOI-CabledArray/profileIndices)
  (`start`, `peak`, `end` times per cast, UTC). `peak` is the shallowest point.
- **R4.** pH and pCO₂ are taken from the downcast (`peak` to `end`); every other variable from
  the upcast (`start` to `peak`). These sensors sample in that direction.
- **R5.** Within a cast, repeated pressure values are reduced to the first sample. A cast with
  fewer than 2 samples is dropped for that instrument.
- **R6.** Each cast is linearly interpolated in pressure onto the site grid. Grid points outside
  the cast's observed pressure range are NaN (no extrapolation).
- **R7.** Grids are uniform, 1 dbar spacing, start inclusive and stop exclusive:

  | Site | Grid (dbar) |
  |---|---|
  | shallow profilers | 0–199 |
  | `oregon_offshore_deep` | 175–589 |
  | `slope_base_deep` | 150–2899 |
  | `axial_base_deep` | 150–2599 |

- **R8.** Instruments are merged per cast; a cast is kept if at least one instrument has data.

### 5.2 Profiler daily bins

- **R9.** Profiles are grouped by `peak_time` into 24 h bins and averaged at each pressure level.
  `time` is the bin's start (00:00 UTC).

### 5.3 Fixed time series

- **R10.** QC (section 6) is applied at native resolution, then each instrument is averaged into
  1 h bins. `time` is the bin's start.
- **R11.** Instruments are merged on the union of their bins. Empty bins are NaN.
- **R12.** Pressure comes from the CTD only.

### 5.4 Adjustments to the raw data

Applied before QC, from [`config/adjustments.csv`](../config/adjustments.csv), one variable per row.
Each adjusted variable lists the rows applied in its `adjustments` attribute.

- **R13.** Dissolved oxygen splice: during the 2017–2021 optode firmware-noise windows, OOI's
  onboard-calculated `dissolved_oxygen` (and its QARTOD flags) replaces
  `corrected_dissolved_oxygen`, per OOI annotation guidance. One row per CTD with an
  integrated optode (7 rows).
- **R14.** Oregon Shelf pH stitch: the archived PHSEND103 record (`ph_seawater`) is followed by
  the active PHSENH110 record (`ph_total`) in one `ph_seawater` variable, without scale
  conversion. A small offset is possible at the 2025-08-28 seam. Documented in the variable's
  `source_note`. Where PHSENH has no QARTOD flags, its period is treated as flag 2 (not evaluated).

## 6. Quality control

Applied in this order, at native resolution, before gridding or binning. Each product records
the order in its `qc_steps` attribute.

1. Adjustments (section 5.4).
2. Advanced pH tests (seafloor products only, R17).
3. HITL annotation masks (R18–R21).
4. QARTOD (R15–R16).

- **R15.** QARTOD: each variable is set to NaN where its own QARTOD flag is fail (4) or
  missing (9). Suspect (3) and not evaluated (2) are kept.
- **R16.** QARTOD flag variables are not written to products.
- **R17.** Advanced pH (`_phadv` products): `ph_seawater` is NaN wherever any of the six
  rca-data-tools advanced pH tests fails, using flags from `s3://rca-advanced-qaqc/`. Streams
  without flags are unaffected. Expect heavy loss on sediment-embedded seafloor sensors (~63%).
- **R18.** HITL annotations: OOI's human-in-the-loop annotations are harvested from the OOI M2M
  API, and each gets one reviewed decision in `annotations/ledger.csv`: `mask`, `ignore` or
  `superseded`. Only approved `mask` rows apply, using the annotation's time window from the
  latest harvest. An annotation with no end date masks to the end of the data.
- **R19.** A mask applies to the named variables on every instrument at the annotation's node
  (OOI wildcards: a missing node applies to the whole site).
- **R20.** A masked CTD salinity also masks the variables OOI computes from it on the same node:
  density, dissolved oxygen, salinity-corrected nitrate, and SeapHOx pH (shelf, after
  2025-08-28). The list is read from the OOI preload database; PHSEN pH and backscatter are
  excluded as too weakly affected. Details: `docs/parameter_dependencies.md`.
- **R21.** Not masked, by rule: platform blowdowns (real ocean events); annotations saying
  calibrations were since corrected; offsets found by discrete samples or calibration casts
  (correctable, not bad).

## 7. Files

### 7.1 Naming

```
<site>_profiles_<start>_<end>_qf49_HITL[_phadv].<ext>                 profiler profiles
<site>_profiles_<start>_<end>_qf49_HITL[_phadv]_binned_24h.<ext>      profiler daily bins
<site>_fixed_<start>_<end>_1h_qf49_HITL[_phadv].<ext>                 fixed time series
```

- `<start>`, `<end>`: first and last date in the file, `YYYYMMDD`, UTC.
- `qf49`: QARTOD flags 4 and 9 removed. `HITL`: annotation masks applied. `phadv`: R17 applied.
- `<ext>`: `zarr` or `nc`.

Published set: profilers `_qf49_HITL`; PC-platform fixed `_qf49_HITL`; seafloor fixed
`_qf49_HITL_phadv`.

### 7.2 Dimensions and coordinates

| Product | Dimensions | Coordinates |
|---|---|---|
| Profiler profiles | `profile_number`, `sea_water_pressure` | `start_time`, `peak_time`, `end_time` per profile |
| Profiler daily bins | `time`, `sea_water_pressure` | |
| Fixed time series | `time` | |

- **R22.** All times are UTC.
- **R23.** Missing values are NaN. Data variables are float64.

### 7.3 Global attributes

| Attribute | Meaning |
|---|---|
| `qc_steps` | QC applied, in order |
| `hitl_annotations_harvested` | When the annotations used were harvested |
| `hitl_ledger_sha1` | Fingerprint of the ledger used |

Other global attributes (`title`, `sensor`, `stream`, `time_coverage_*`, …) are copied from one
of the OOI source streams and describe that stream, not the product. See section 9.

## 8. Access

| Location | Contents |
|---|---|
| `s3://rca-advanced-qaqc/cresst-one-easy-rca/` | This specification's products |
| `s3://rca-advanced-qaqc/cresst/` | Earlier build of the same products |

Both buckets are publicly readable without credentials.

## 9. Known limitations

- Deep profilers have no chlorophyll: their FLNTU stream names it
  `flntu_x_mmp_cds_fluorometric_chlorophyll_a`, which the build doesn't request.
- Global attributes describe a source stream, not the product (7.3).
- Profiles crossing midnight on 31 December are cut at the year boundary.
- Sparse variables (pH, pCO₂, nitrate) are interpolated across gaps of any size within a cast;
  Axial pH has ~13 samples per downcast, so many grid values are interpolated.
- Dense CTD data are interpolated from the two nearest samples, not averaged within each level.
- Bins built from very few samples look the same as full bins.
- Shelf pH: possible offset at the stitch seam (R14). OOI labels both sources total scale, so the
  scale caveat in `source_note` may be unnecessary.
- About 718 annotation decisions made by an LLM before the ledger have not been reviewed by a
  person.

## 10. Versioning and release

Not yet implemented; planned for version 1.0:

- The spec version recorded in every file's attributes.
- Monthly releases under a versioned path (`vYYYY.MM/`), with a build report of the percentage
  masked by variable, reason and year, compared with the previous release.
- A DOI for the spec and for the product series.
- Each numbered rule checked by a test.

Until then, products are replaced in place when rebuilt.
