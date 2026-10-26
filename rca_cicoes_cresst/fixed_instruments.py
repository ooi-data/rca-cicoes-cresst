#!/usr/bin/env python3
"""Build resampled time-series datasets from fixed (non-profiling) instruments:
the shallow profiler mooring 200 m platforms (PC nodes) and the seafloor Benthic
Experiment Packages (BEP / LJ nodes).

Same QC steps, in the same order, as the regridded profiler product (see
common.qc_steps), but no profile slicing or pressure regridding: instruments are
masked at native resolution, resampled to a common time grid (default hourly
means), and merged into one dataset per site.
"""
import os

import xarray as xr
import pandas as pd
import click
from datetime import datetime, timezone
from loguru import logger

from rca_cicoes_cresst.common import (
    ACTIVE_DICT,
    ANNOTATIONS_DIR,
    OUTPUT_DIR,
    ARCHIVE_DICT,
    annotation_provenance,
    PRES_PARAMS,
    QARTOD_EXCLUDE,
    START_YEAR,
    apply_adjustments,
    group_params_by_instrument,
    load_annotations,
    load_data,
    mask_annotation_windows,
    mask_ph_advanced,
    mask_qartod,
    qc_steps,
    qc_suffix,
)

# PC = 200 m platform on the shallow profiler mooring; BEP = seafloor benthic
# experiment package. Both are fixed-depth. The deep RS seafloor BEPs carry
# only a CTD (with integrated optode); the CE BEPs add pH and pCO2.
FIXED_SITES: dict[str, dict[str, str]] = {
    "oregon_offshore": {
        "ctd":    "CE04OSPS-PC01B-4A-CTDPFA109",
        "ph":     "CE04OSPS-PC01B-4B-PHSENA106",
        "pco2":   "CE04OSPS-PC01B-4D-PCO2WA105",
    },
    "slope_base": {
        "ctd":    "RS01SBPS-PC01A-4A-CTDPFA103",
        "ph":     "RS01SBPS-PC01A-4B-PHSENA102",
        "fluoro": "RS01SBPS-PC01A-4C-FLORDD103",
    },
    "axial_base": {
        "ctd":    "RS03AXPS-PC03A-4A-CTDPFA303",
        "ph":     "RS03AXPS-PC03A-4B-PHSENA302",
        "fluoro": "RS03AXPS-PC03A-4C-FLORDD303",
    },
    "oregon_offshore_seafloor": {
        "ctd":    "CE04OSBP-LJ01C-06-CTDBPO108",
        "ph":     "CE04OSBP-LJ01C-10-PHSEND107",
        # pco2 CE04OSBP-LJ01C-09-PCO2WB104 excluded: pCO2 requires offsetting and
        # SME review prior to inclusion in this curated product (2026-08-03).
    },
    "oregon_shelf_seafloor": {
        "ctd":    "CE02SHBP-LJ01D-06-CTDBPN106",
        "ph":     "CE02SHBP-LJ01D-10-PHSENH110",  # reports ph_total, not ph_seawater
        # pco2 CE02SHBP-LJ01D-09-PCO2WB103 excluded: pCO2 requires offsetting and
        # SME review prior to inclusion in this curated product (2026-08-03).
    },
    "slope_base_seafloor": {  # deep BEP; CTD-only in this product (also has OPTAA/ADCP/HPIES)
        "ctd":    "RS01SLBS-LJ01A-12-CTDPFB101",
    },
    "axial_base_seafloor": {  # deep BEP; CTD-only in this product (also has OPTAA/ADCP/HPIES)
        "ctd":    "RS03AXBS-LJ03A-12-CTDPFB301",
    },
}

DEFAULT_PARAMS: list[str] = [
    "sea_water_temperature",
    "sea_water_practical_salinity",
    "corrected_dissolved_oxygen",
    "sea_water_density",
    "ph_seawater",
    "ph_total",
    "pco2_seawater",
    "fluorometric_chlorophyll_a",
    "fluorometric_cdom",
    "optical_backscatter",
]

# Sites whose current pH sensor superseded an older one at the same node, whose
# archived record is concatenated ahead of the active sensor to extend the pH
# series. Value is the OLD reference designator
# SCALE NOTE: the old PHSEND sensors report ph_seawater (seawater/free scale)
# and the current PHSENH reports ph_total (total scale). Per science lead
# (2026-08-03) the two are concatenated WITHOUT scale conversion
PH_STITCH: dict[str, str] = {
    "oregon_shelf_seafloor": "CE02SHBP-LJ01D-10-PHSEND103",
}


def stitch_archived_ph(
    ds_active: xr.Dataset,
    archive_refdes: str,
    active_stream: str,
    ph_advanced: bool = False,
) -> xr.Dataset:
    """Concatenate an archived pH sensor's record ahead of the active sensor's.

    See PH_STITCH: the active sensor reports ph_total (total scale) and the
    archived sensor ph_seawater (seawater scale). They are concatenated in time
    WITHOUT scale conversion into a single ph_seawater variable to keep the
    record continuous -- a small offset is possible at the swap seam.

    Advanced pH flags are keyed per stream, so when ph_advanced is set each
    source is masked with its OWN stream before the concat (the archived PHSEND
    sensor carries advanced flags; the active PHSENH stream currently does not,
    so it no-ops).
    """
    archive_stream = ARCHIVE_DICT[archive_refdes]["zarrFile"]
    archive_ds = apply_adjustments(load_data(archive_stream), archive_refdes)
    logger.info(f"stitching archived pH {archive_refdes} ahead of the active sensor")

    # active reports ph_total; rename so both sources share the ph_seawater name
    rename = {"ph_total": "ph_seawater"}
    if "ph_total_qartod_results" in ds_active:
        rename["ph_total_qartod_results"] = "ph_seawater_qartod_results"
    active_ds = ds_active.rename(rename)

    if ph_advanced:  # mask each source with its own stream's flags (see docstring)
        archive_ds = mask_ph_advanced(archive_ds, archive_stream)
        active_ds = mask_ph_advanced(active_ds, active_stream)

    ph = xr.concat([archive_ds["ph_seawater"], active_ds["ph_seawater"]], dim="time").sortby("time").drop_duplicates("time")
    ph.attrs["source_note"] = (
        f"stitched without scale conversion: {archive_refdes} (ph_seawater, seawater scale) "
        f"then the active PHSENH sensor (ph_total, total scale); small offset possible at the seam"
    )
    out = ph.to_dataset()

    # keep whichever sensor has QARTOD; the PHSENH stream currently ships none,
    # so fill its period with flag 2 (not_evaluated) rather than drop the 11 yr
    # of real flags on the archived sensor.
    q = "ph_seawater_qartod_results"
    if q in archive_ds or q in active_ds:
        old_q = archive_ds[q] if q in archive_ds else xr.full_like(archive_ds["ph_seawater"], 2, dtype="int32")
        new_q = active_ds[q] if q in active_ds else xr.full_like(active_ds["ph_seawater"], 2, dtype="int32")
        out[q] = xr.concat([old_q.rename(q), new_q.rename(q)], dim="time").sortby("time").drop_duplicates("time")
        if q not in archive_ds or q not in active_ds:
            logger.info("stitched pH QARTOD: filled the un-flagged sensor's period with flag 2 (not_evaluated)")
    return out


def load_fixed_inputs(
    site_dict: dict[str, str],
    params: list[str],
    ph_stitch: str | None = None,
    ph_advanced: bool = False,
) -> list[dict]:
    instrument_params = group_params_by_instrument(params, site_dict)

    instrument_datasets: list[dict] = []
    for instr_key, instr_params in instrument_params.items():
        refdes = site_dict[instr_key]
        stream_name = ACTIVE_DICT[refdes]["zarrFile"]
        logger.info(f"loading zarr: {instr_key} ({refdes})")
        ds = apply_adjustments(load_data(stream_name), refdes)
        if instr_key == "ph" and ph_stitch:
            ds = stitch_archived_ph(ds, ph_stitch, stream_name, ph_advanced=ph_advanced)
            instr_params = ["ph_seawater"]  # unified stitched variable (see PH_STITCH)
        qartod_vars = [f"{p}_qartod_results" for p in instr_params if f"{p}_qartod_results" in ds]
        # only keep the platform pressure from the CTD; the other instruments
        # carry a duplicate int_ctd_pressure that would collide on merge
        pres_vars = [v for v in PRES_PARAMS if v in ds] if instr_key == "ctd" else []
        ds = ds[[v for v in pres_vars + instr_params + qartod_vars if v in ds]]
        # stitched pH masks per-source inside stitch_archived_ph (streams differ)
        if ph_advanced and instr_key == "ph" and not ph_stitch:
            ds = mask_ph_advanced(ds, stream_name)
        instrument_datasets.append({
            "instrument": instr_key,
            "ds": ds,
            "params": [p for p in instr_params if p in ds],
        })
    return instrument_datasets


def resample_fixed(
    instrument_datasets: list[dict],
    resample: str,
    start_year: int,
    end_year: int,
    qaqc_filter: str = "none",
    annotations: pd.DataFrame | None = None,
) -> xr.Dataset:
    resampled = []

    for instr in instrument_datasets:
        year_parts = []

        for year in range(start_year, end_year + 1):
            ds_year = instr["ds"].sel(time=slice(f"{year}-01-01", f"{year}-12-31")).compute()
            if ds_year.sizes["time"] == 0:
                continue

            if annotations is not None:
                ds_year = mask_annotation_windows(ds_year, instr["params"], annotations)

            ds_year = mask_qartod(ds_year, instr["params"], QARTOD_EXCLUDE.get(qaqc_filter, set()))
            year_parts.append(ds_year.resample(time=resample).mean())
            logger.info(f"{instr['instrument']} {year}: {ds_year.sizes['time']:,} points → {year_parts[-1].sizes['time']:,} bins")


        if not year_parts:
            logger.warning(f"{instr['instrument']}: no data in {start_year}–{end_year}")
            continue

        resampled.append(xr.concat(year_parts, dim="time"))

    logger.info("merging instruments")
    return xr.merge(resampled, join="outer")  # union the instruments' hourly grids; empty bins NaN


def build_output_path(site: str, ds: xr.Dataset, resample: str, qaqc_filter: str, ph_advanced: bool, ext: str) -> str:
    t_start = pd.Timestamp(ds.time.values.min()).strftime("%Y%m%d")
    t_end = pd.Timestamp(ds.time.values.max()).strftime("%Y%m%d")
    return f"{site}_fixed_{t_start}_{t_end}_{resample}{qc_suffix(qaqc_filter, ph_advanced)}.{ext}"


@click.command()
@click.argument("site", type=click.Choice(list(FIXED_SITES.keys())))
@click.option(
    "--resample",
    default="1h",
    show_default=True,
    metavar="FREQ",
    help="Resampling frequency for bin means (pandas offset alias, e.g. 1h, 30min).",
)
@click.option(
    "--start-year",
    type=int,
    default=START_YEAR,
    show_default=True,
    help="First year to include.",
)
@click.option(
    "--end-year",
    type=int,
    default=None,
    help="Last year to include.  [default: current year]",
)
@click.option(
    "--format", "fmt",
    type=click.Choice(["zarr", "nc", "both"]),
    default="zarr",
    show_default=True,
    help="Output file format",
)
@click.option(
    "--qaqc-filter",
    type=click.Choice(["none", "basic", "highest"]),
    default="none",
    show_default=True,
    help=(
        "QARTOD filter level. 'basic' excludes fail (4) and missing (9) flags. "
        "'highest' applies 'basic' plus masks approved HITL annotations from the ledger."
    ),
)
@click.option(
    "--annotations-dir",
    default=ANNOTATIONS_DIR,
    show_default=True,
    help="Directory holding ledger.csv and raw/ harvested annotations (used with --qaqc-filter highest).",
)
@click.option(
    "--ph-advanced",
    is_flag=True,
    default=False,
    help=(
        "Also mask ph_seawater where any advanced pH QC test failed (flag string "
        "contains a 3). Advanced flags exist per-stream for some pH sensors (PC "
        "platforms and the archived shelf BEP); applied where present, skipped otherwise."
    ),
)
@click.option(
    "--output-dir",
    default=OUTPUT_DIR,
    show_default=True,
    help="Directory to write products to (one per S3 prefix under data/, e.g. data/cresst-one-easy-rca).",
)
def main(
    site: str,
    resample: str,
    start_year: int,
    end_year: int | None,
    fmt: str,
    qaqc_filter: str,
    annotations_dir: str,
    ph_advanced: bool,
    output_dir: str,
) -> None:
    """Resample fixed-instrument data (PC platforms and seafloor BEPs) to a common time grid.

    Output is saved to <output-dir>/<site>_fixed_<start>_<end>_<freq>.<ext>.  Example: slope_base_fixed_20150101_20260630_1h_qf49_HITL.zarr
    With --format both, saves zarr and nc versions with the same base name.
    """
    os.makedirs("logs", exist_ok=True)
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _log_id = logger.add(f"logs/{site}_fixed_{run_ts}.log")

    site_dict = FIXED_SITES[site]
    end_year = end_year or datetime.now(timezone.utc).year

    instrument_datasets = load_fixed_inputs(
        site_dict, DEFAULT_PARAMS,
        ph_stitch=PH_STITCH.get(site),
        ph_advanced=ph_advanced,
    )
    nodes = {refdes.split("-")[1] for refdes in site_dict.values()}
    subsite = site_dict["ctd"][:8]
    annotations = load_annotations(subsite, nodes, annotations_dir) if qaqc_filter == "highest" else None
    ds_fixed = resample_fixed(instrument_datasets, resample, start_year, end_year, qaqc_filter, annotations)
    ds_fixed.attrs["qc_steps"] = qc_steps(qaqc_filter, ph_advanced)
    if annotations is not None:
        ds_fixed.attrs.update(annotation_provenance(subsite, annotations_dir))

    os.makedirs(output_dir, exist_ok=True)
    fmts = ["zarr", "nc"] if fmt == "both" else [fmt]
    for f in fmts:
        output_path = os.path.join(output_dir, build_output_path(site, ds_fixed, resample, qaqc_filter, ph_advanced, f))
        logger.info(f"saving to {output_path}")
        if f == "zarr":
            ds_fixed.to_zarr(output_path, mode="w")
        else:
            ds_fixed.to_netcdf(output_path)

    logger.info("done")
    logger.remove(_log_id)


if __name__ == "__main__":
    main()
