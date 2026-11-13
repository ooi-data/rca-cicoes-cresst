# RCA-CRESST Data Products: Product Specification

**Version 0.2 (draft), 2026-11-13.** Describes the products published as versioned releases under
`s3://rca-advanced-qaqc/cresst-easy-one-rca/releases/` (section 10). Rules are numbered (R1, R2, …)
so they can be cited, and each is meant to become a test. Version 0.1 (2026-10-28) described the
2026-10-23 build, published as release `v2026.10`.

## 1. Purpose and audience

Good-quality, easy-to-use time series and profiles of Essential Ocean Variables from the OOI
Regional Cabled Array (RCA), for scientists and modelers who don't want to work through OOI's
raw streams, QC flags and annotations. Every value in a product has passed the QC in section 6,
and nothing else: no flag variables, no data modes. Values that fail are NaN.

The full-detail tier is OOI's own zarr archive (`s3://ooi-data/`), which keeps every sample and
flag. These products are a curated, gridded layer on top of it.

## 2. Products

| Product | Name | What it is | Sites |
|---|---|---|---|
| Profiler profiles | `<site>_profiles` | Each profiler cast bin-averaged or interpolated onto a fixed pressure grid | 6 |
| Profiler daily bins | `<site>_profiles_binned_24h` | Profiler profiles averaged into 24 h time bins | 6 |
| Fixed time series | `<site>_fixed_1h` | Fixed-depth instruments averaged into 1 h time bins | 7 |

Each product is built at one or more QC levels (section 6) and published as both zarr and netCDF
with the same content.

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
- **R2.** Data start on 2014-01-01, before the first cabled-array data. Profiler products have 2014
  data only where a 2014 profile index exists: `oregon_offshore`, `axial_base` and `axial_base_deep`.

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
| `fluorometric_chlorophyll_a` | ug L-1 | FLORD | PC fixed |
| `flntu_x_mmp_cds_fluorometric_chlorophyll_a` | ug L-1 | FLNTU | deep profilers |
| `fluorometric_cdom` | ppb | FLORD | PC fixed |
| `flcdr_x_mmp_cds_fluorometric_cdom` | ppb | FLCDR | deep profilers |
| `optical_backscatter` | m-1 | FLORD | PC fixed |

A site's file contains only the variables its instruments provide (section 3).
`docs/parameter_dependencies.md` explains how OOI computes each from the raw measurements.

## 5. Processing

### 5.1 Profiler profiles

- **R3.** Casts come from the OOI [profile index](https://github.com/OOI-CabledArray/profileIndices)
  (`start`, `peak`, `end` times per cast, UTC). `peak` is the shallowest point. Casts are
  processed by the year of `start`, reading data through the next 1 January, so a cast crossing
  midnight on 31 December is whole.
- **R4.** pH and pCO₂ are taken from the downcast (`peak` to `end`); every other variable from
  the upcast (`start` to `peak`). These sensors sample in that direction.
- **R5.** Dense sensors (4–22 samples per dbar: the CTD, and the deep profilers' oxygen, FLNTU and
  FLCDR) are loop-edited and bin-averaged, as in Sea-Bird processing and Argo. An upcast sample
  deeper than the shallowest pressure already reached on that cast is dropped. The rest are
  averaged in bins one grid step wide, centred on each grid level, lower edge inclusive. Values
  masked by QC are left out of the average; an empty bin is NaN.
- **R6.** Sparse sensors (under 1 sample per dbar: pH, pCO₂, nitrate) are linearly interpolated in
  pressure onto the grid; a repeated pressure keeps its first sample. Grid points outside the
  cast's observed pressure range are NaN (no extrapolation).
- **R7.** Grids are uniform, 1 dbar spacing, start inclusive and stop exclusive:

  | Site | Grid (dbar) |
  |---|---|
  | shallow profilers | 0–199 |
  | `oregon_offshore_deep` | 175–589 |
  | `slope_base_deep` | 150–2899 |
  | `axial_base_deep` | 150–2599 |

- **R8.** Instruments are merged per cast; an instrument with fewer than 2 samples in a cast is left
  out of it, and a cast is kept if at least one instrument has data.

### 5.2 Profiler daily bins

- **R9.** Profiles are grouped by `peak_time` into 24 h bins and averaged at each pressure level.
  `time` is the bin's start (00:00 UTC).

### 5.3 Fixed time series

- **R10.** QC (section 6) is applied at native resolution, then each instrument is averaged into
  1 h bins. `time` is the bin's start.
- **R11.** Instruments are merged on the union of their bins. Empty bins are NaN.
- **R12.** Pressure comes from the CTD only.

### 5.4 Adjustments to the raw data

Applied at the `hitl` level and above, before the other QC steps, from
[`config/adjustments.csv`](../config/adjustments.csv), one variable per row.
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

Products are built at one of five cumulative QC levels; each applies every step of the levels
before it. The level is in the filename and the `qc_level` attribute.

| Level | Adds |
|---|---|
| `ooi` | Nothing: OOI's values as served, only gridded or resampled |
| `qartod` | QARTOD (R15–R16) |
| `hitl` | Adjustments (section 5.4), HITL annotation masks (R18–R21) |
| `advanced` | Advanced pH tests (R17) |
| `deploymentcorrected` | Per-deployment discrete-sample corrections (R24, provisional) |

Steps run in this order, at native resolution, before gridding or binning: value changes first,
then masks. The level only decides which steps run. Each product records them in its `qc_steps`
attribute.

1. Adjustments (section 5.4).
2. Deployment corrections (R24).
3. Advanced pH tests (R17).
4. HITL annotation masks (R18–R21).
5. QARTOD (R15–R16).

- **R15.** QARTOD: each variable is set to NaN where its own QARTOD flag is fail (4) or
  missing (9). Suspect (3) and not evaluated (2) are kept.
- **R16.** QARTOD flag variables are not written to products.
- **R17.** Advanced pH (`advanced` level, fixed products only): `ph_seawater` is NaN wherever any
  of the six rca-data-tools advanced pH tests fails (code 3), using flags from
  `s3://rca-advanced-qaqc/`. Other codes are kept. Not applied to profiler products: their pH is
  rough and the rule would remove most of it (74% of Axial shallow-profiler samples). Streams
  without flags (Oregon Offshore BEP, active Oregon Shelf PHSENH) are unaffected. Expect heavy loss
  on sediment-embedded seafloor sensors (~63%).
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
- **R24.** Deployment corrections (`deploymentcorrected` level, provisional): per-deployment corrections from cruise
  discrete samples ([calibrationPipeline](https://github.com/OOI-CabledArray/calibrationPipeline),
  pinned commit), one per cruise. Shallow-profiler salinity and nitrate get an offset added and
  oxygen a gain multiplied, 2015–2025, matched on the stream's `deployment` number. A deployment
  spanning two cruises is interpolated linearly between their casts and held beyond them (OOI BGC
  Best Practices, Palevsky et al. 2023, 2.5.4 and 3.5.3). Deployments rated worse than status 3
  stay uncorrected. Each correction is listed in the variable's `calibrations` attribute. Where
  salinity is corrected, `sea_water_density` is shifted by the TEOS-10 change (`gsw.rho`, as OOI
  computes it), so uncorrected deployments keep OOI's values. Open: the status threshold, and some
  large oxygen gains, await review with the calibration team.
- **R25.** At `hitl` and above, every variable has a `hitl_masks` attribute: a JSON list with one
  entry per approved mask annotation that matched the variable's data, after R19 and R20 are
  applied. Each entry has `annotation_id` (integer), `begin` and `end` (ISO 8601 UTC; `end` is null
  for an open-ended annotation, which masks to the end of the data) and `via`:
  - `direct`: the annotation names this variable on this variable's instrument;
  - `R19`: it names the variable, but sits on another sensor at the node or is a node- or site-wide
    wildcard;
  - `R20`: the variable was added by salinity inheritance;
  - `R19+R20`: both.

  An empty list means no HITL masks apply. Every annotation and its ledger decision, including
  `ignore` and `superseded`, is in the release's `annotations.csv` (R31).

## 7. Files

### 7.1 Layout

```
s3://rca-advanced-qaqc/cresst-easy-one-rca/
  catalog.json                    releases, newest first (R33)
  CHANGELOG.md                    changes in every release
  releases/vYYYY.MM.N/
    manifest.json                 every product and level in the release (R32)
    RELEASE_NOTES.md              highlights and diffs against the previous release (R36)
    build_report.json             values kept and removed by variable, level and year (R37)
    annotations.csv               every harvested annotation with its ledger decision (R31)
    ledger.csv, adjustments.csv   the decision files the release was built with
    <product>/<level>.zarr
    <product>/<level>.nc
```

- **R26.** `<product>` names (section 2) carry no dates and stay the same across releases. Time
  coverage is in the manifest and the files' time coordinates.
- **R27.** `<level>` is the QC level (section 6). A release can hold any subset of levels for each
  product; the manifest lists which exist.
- **R28.** A published release is never changed: files are not replaced or deleted. Fixes go in a
  new release.

The 2026-10-23 build was published as flat files at the top of the prefix
(`_qf49_HITL` = `hitl`, `_qf49_HITL_phadv` = `advanced`) until 2026-11-04, and is now release
`v2026.10`. The prefix was named `cresst-one-easy-rca/` until 2026-11-12; `v2026.10` was copied
here unchanged except for `base_url` in its manifest. The top level holds only `catalog.json`, `CHANGELOG.md` and `releases/`.

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
| `release` | Release the file belongs to, e.g. `v2026.11.0` |
| `spec_version` | Version of this specification the build implements |
| `git_commit` | Commit of this repository the file was built from; `-dirty` if it had uncommitted changes |
| `qc_level` | QC level (section 6) |
| `qc_steps` | QC applied, in order |
| `hitl_annotations_harvested` | When the annotations used were harvested (`hitl` and above) |
| `hitl_ledger_sha1` | Fingerprint of the ledger used (`hitl` and above) |

Other global attributes (`title`, `sensor`, `stream`, `time_coverage_*`, …) are copied from one
of the OOI source streams and describe that stream, not the product. See section 9.

- **R29.** Every file in a release has the `release`, `spec_version` and `git_commit` attributes.
  Files in `v2026.10` predate `git_commit`, `qc_level` and `hitl_masks` (R25); their level is in the
  file path and the manifest.

### 7.4 Variable attributes

| Attribute | Meaning |
|---|---|
| `adjustments` | `config/adjustments.csv` rows applied (section 5.4) |
| `calibrations` | Deployment corrections applied (R24) |
| `hitl_masks` | HITL masks applied, as JSON (R25) |
| `source_note` | How a stitched variable was assembled (R14) |

### 7.5 Release files

- **R30.** Release files are UTF-8; times are ISO 8601 UTC with a `Z` suffix.
- **R31.** `annotations.csv` has one row per harvested annotation for the release's sites: OOI's
  fields (`id`, `subsite`, `node`, `sensor`, `stream`, `beginDT`, `endDT`, `qcFlag`, `parameters`,
  `annotation`) joined with the ledger's (`decision`, `status`, `parameters_affected`,
  `parameters_source`, `rationale`, `decided_by`, `reviewed_at`). Ledger fields are empty for an
  annotation with no decision yet.
- **R32.** `manifest.json` is the contract consumers read instead of listing the bucket:

  ```json
  {
    "release": "v2026.11.0",
    "date": "2026-11-30",
    "spec_version": "0.2",
    "git_commit": "<40 hex>",
    "base_url": "s3://rca-advanced-qaqc/cresst-easy-one-rca/releases/v2026.11.0/",
    "products": [
      {
        "product": "slope_base_profiles",
        "site": "slope_base",
        "type": "profiles",
        "level": "hitl",
        "files": {"zarr": "slope_base_profiles/hitl.zarr", "nc": "slope_base_profiles/hitl.nc"},
        "dims": {"profile_number": 24119, "sea_water_pressure": 200},
        "time_start": "2015-07-09T03:12:00Z",
        "time_end": "2026-08-16T21:40:00Z",
        "variables": ["sea_water_temperature", "sea_water_practical_salinity"],
        "qc_steps": "1. adjustments: … | 2. HITL: … | 3. QARTOD: …",
        "hitl_ledger_sha1": "<10 hex>",
        "hitl_annotations_harvested": "2026-11-28T18:34:30Z",
        "git_commit": "<40 hex>",
        "spec_version": "0.2"
      }
    ]
  }
  ```

  `type` is `profiles`, `profiles_binned` or `fixed`. `files` paths are relative to `base_url`.
  `hitl_*` are null below `hitl`. A field may be added in a later spec version; none is removed or
  renamed without a major version change.
- **R33.** `catalog.json` lists every release, newest first:
  `{"latest": "v2026.11.0", "releases": [{"id": "v2026.11.0", "date": "2026-11-30", "git_commit": "<40 hex>",
  "spec_version": "0.2"}]}`.

## 8. Access

| Location | Contents |
|---|---|
| `s3://rca-advanced-qaqc/cresst-easy-one-rca/catalog.json` | Index of releases; start here |
| `s3://rca-advanced-qaqc/cresst-easy-one-rca/releases/vYYYY.MM.N/` | One release (section 7) |
| `s3://rca-advanced-qaqc/cresst/` | July 2026 build, unversioned; not maintained |

All are publicly readable without credentials.

## 9. Known limitations

- Global attributes describe a source stream, not the product (7.3).
- Sparse variables (pH, pCO₂, nitrate) are interpolated across gaps of any size within a cast.
  pH and pCO₂ have 12–13 samples per downcast, at profiler stops about 10 dbar apart above
  ~110 dbar and 22 dbar apart below (largest gap per cast: pH 34 dbar, pCO₂ 22, median since
  2017); most 2014–2016 casts have 2 samples. So most of their grid values are interpolated. A gap
  limit (e.g. 40 dbar) or a distance-to-nearest-sample variable awaits the science lead.
- Bins built from very few samples look the same as full bins.
- Deep-profiler sensors are read on the upcast only (R4). In `v2026.10`, 25–41% of deep-profiler
  casts have 5 or fewer levels, for two reasons. At Axial (2017, 2018, 2021) and Slope Base (2015,
  2018, 2020) the profile index rows run top to bottom and the ascents fall between rows, so those
  years have almost no profiles (Axial 2018: 17.9 M CTD samples, 2 profiles). At Oregon Offshore,
  some casts logged descents only (spring 2022) or are short near-bottom cycles (2025, 522–578
  dbar). Fixing the index or finding casts from pressure is planned.
- Deep-profiler chlorophyll and CDOM are not despiked; a spike is averaged into its bin. They keep
  OOI's profiler-specific names (`flntu_x_mmp_cds_…`, `flcdr_x_mmp_cds_…`).
- Shelf pH: possible offset at the stitch seam (R14). OOI labels both sources total scale, so the
  scale caveat in `source_note` may be unnecessary.
- About 718 annotation decisions made by an LLM before the ledger have not been reviewed by a
  person.

## 10. Versioning and release

Products are built with `regrid-profiler`, `bin-dataset` and `fixed-instruments` at whichever QC
levels are wanted, then packaged and published as a release with `release-cresst` and
`sync-cresst`.

- **R34.** Releases are named `vYYYY.MM.N`, numbered from 0 within a month and compared as numbers
  (`v2026.10` predates the number). Each is tagged with its name in this
  repository on the commit its products were built from.
- **R35.** `CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). A
  release needs a non-empty `Unreleased` section with at least one entry under `Highlights`.
  Entries that change a method or rule cite its number (e.g. R14). Releasing moves `Unreleased`
  under the version.
- **R36.** `RELEASE_NOTES.md` has the highlights, the changelog section, and diffs against the
  previous release: ledger decisions added or changed (with rationale, and counts by
  `decided_by`), `adjustments.csv` rows added, removed or changed, products and levels added or
  removed, and changes in each product's time coverage.
- **R37.** `build_report.json` has one row per product, level, variable and year: the number of
  finite values, and the percentage of the next-lower level's values that this level removed (when
  that level is in the release). Each row also carries the previous release's figures for the same
  product, level, variable and year.

There is no `latest/` copy: `catalog.json` names the latest release. Not yet decided: how long old
releases keep every level.

Planned for version 1.0: a DOI for the spec and the product series, and each numbered rule checked
by a test.
