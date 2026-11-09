# Changelog

Changes to the RCA-CRESST data products, newest first, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format. A release needs at least one `Highlights` entry under `Unreleased`; entries that change a method or rule
cite its number in [docs/spec.md](docs/spec.md) (e.g. R14). `release-cresst` moves `Unreleased` under the version.

## [Unreleased]

### Highlights

- Products are published as versioned releases under `cresst-one-easy-rca/releases/`, each with a manifest,
  release notes and a build report (R26–R37).
- QC levels replace the `_qf49_HITL` and `_phadv` suffixes: `ooi`, `qartod`, `hitl`, `advanced`,
  `deploymentcorrected` (section 6). A release can carry any subset of levels.
- Profiler CTD data are loop-edited and averaged in 1 dbar bins, as Argo and Sea-Bird processing do,
  instead of interpolated between the nearest samples (R5). So are the deep profilers' oxygen,
  chlorophyll and CDOM. pH, pCO₂ and nitrate are still interpolated (R6).

### Added

- `hitl_masks` attribute on every variable at `hitl` and above, listing the annotations that masked it (R25).
- `annotations.csv`, `ledger.csv` and `adjustments.csv` in each release (R31).
- `release`, `spec_version` and `git_commit` attributes on every file (R29).
- `deploymentcorrected` level: per-deployment corrections from cruise samples (R24). Provisional; not published.
  Covers salinity, oxygen and nitrate, 2015–2025; a deployment spanning two cruises is interpolated between them.
- Deep-profiler chlorophyll, `flntu_x_mmp_cds_fluorometric_chlorophyll_a` (section 4). Ledger decision 5882 now
  names it, masking Axial deep chlorophyll from 2024-08-30 to 2025-08-07 (negative values).
- 2014 data (R2): fixed series from August–October 2014, and profiles where a 2014 profile index exists
  (`axial_base_deep` 134 casts, `axial_base` 47, `oregon_offshore` 1).

### Changed

- Advanced pH flags are the `advanced` level, applied to every fixed product whose pH stream has flags, and not to
  profiler products (R17).
- `qartod` (formerly `basic`) no longer applies `config/adjustments.csv`; adjustments start at `hitl` (section 6).
- The salinity inheritance list is read from the OOI preload database (R20); the masks it produces are unchanged.
- Sites and instruments are read from `config/sites.csv` (section 3).
- Casts crossing midnight on 31 December are whole, not cut at the year boundary (R3).

## [v2026.10] - 2026-10-23

### Highlights

- The 2026-10-23 build, migrated into the versioned layout: `_qf49_HITL` files are `hitl`, `_qf49_HITL_phadv`
  files are `advanced`. Specification 0.1.
