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
    QC_LEVELS,
    START_YEAR,
    group_params_by_instrument,
    load_annotations,
    load_data,
    mask_annotation_windows,
    mask_ph_advanced,
    mask_qartod,
    product_sites,
    hitl_mask_attrs,
    product_attrs,
    qc_at,
    read_sites,
    qc_suffix,
    stream_qc,
)

FIXED_SITES = product_sites("fixed")

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

# site -> archived pH sensor concatenated ahead of the active one (stitch_from in config/sites.csv)
PH_STITCH = read_sites().query("product == 'fixed'").dropna(subset=["stitch_from"]).set_index("site")["stitch_from"].to_dict()


def stitch_archived_ph(
    ds_active: xr.Dataset,
    archive_refdes: str,
    active_stream: str,
    qaqc_filter: str = "ooi",
) -> xr.Dataset:
    """Concatenate an archived pH sensor's record ahead of the active sensor's.

    See PH_STITCH: the active sensor reports ph_total (total scale) and the
    archived sensor ph_seawater (seawater scale). They are concatenated in time
    WITHOUT scale conversion into a single ph_seawater variable to keep the
    record continuous -- a small offset is possible at the swap seam.

    Advanced pH flags are keyed per stream, so at the advanced level each
    source is masked with its OWN stream before the concat (the archived PHSEND
    sensor carries advanced flags; the active PHSENH stream currently does not,
    so it no-ops).
    """
    archive_stream = ARCHIVE_DICT[archive_refdes]["zarrFile"]
    archive_ds = stream_qc(load_data(archive_stream), archive_refdes, archive_stream, qaqc_filter)
    logger.info(f"stitching archived pH {archive_refdes} ahead of the active sensor")

    # active reports ph_total; rename so both sources share the ph_seawater name
    rename = {"ph_total": "ph_seawater"}
    if "ph_total_qartod_results" in ds_active:
        rename["ph_total_qartod_results"] = "ph_seawater_qartod_results"
    active_ds = ds_active.rename(rename)

    if qc_at(qaqc_filter, "advanced"):  # active masked after the rename, with its own stream's flags
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
    qaqc_filter: str = "ooi",
) -> list[dict]:
    instrument_params = group_params_by_instrument(params, site_dict)

    instrument_datasets: list[dict] = []
    for instr_key, instr_params in instrument_params.items():
        refdes = site_dict[instr_key]
        stream_name = ACTIVE_DICT[refdes]["zarrFile"]
        logger.info(f"loading zarr: {instr_key} ({refdes})")
        ds = stream_qc(load_data(stream_name), refdes, stream_name, qaqc_filter)
        sources = [refdes]
        if instr_key == "ph" and ph_stitch:
            ds = stitch_archived_ph(ds, ph_stitch, stream_name, qaqc_filter)
            sources.append(ph_stitch)
            instr_params = ["ph_seawater"]  # unified stitched variable (see PH_STITCH)
        qartod_vars = [f"{p}_qartod_results" for p in instr_params if f"{p}_qartod_results" in ds]
        # only keep the platform pressure from the CTD; the other instruments
        # carry a duplicate int_ctd_pressure that would collide on merge
        pres_vars = [v for v in PRES_PARAMS if v in ds] if instr_key == "ctd" else []
        ds = ds[[v for v in pres_vars + instr_params + qartod_vars if v in ds]]
        instrument_datasets.append({
            "instrument": instr_key,
            "ds": ds,
            "params": [p for p in instr_params if p in ds],
            "sensors": {r.split("-", 2)[2] for r in sources},
            "hitl_masks": {},
        })
    return instrument_datasets


def resample_fixed(
    instrument_datasets: list[dict],
    resample: str,
    start_year: int,
    end_year: int,
    qaqc_filter: str = "ooi",
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
                ds_year = mask_annotation_windows(ds_year, instr["params"], annotations, instr["sensors"], instr["hitl_masks"])

            ds_year = mask_qartod(ds_year, instr["params"], QARTOD_EXCLUDE if qc_at(qaqc_filter, "qartod") else set())
            year_parts.append(ds_year.resample(time=resample).mean())
            logger.info(f"{instr['instrument']} {year}: {ds_year.sizes['time']:,} points → {year_parts[-1].sizes['time']:,} bins")


        if not year_parts:
            logger.warning(f"{instr['instrument']}: no data in {start_year}–{end_year}")
            continue

        resampled.append(xr.concat(year_parts, dim="time"))

    logger.info("merging instruments")
    return xr.merge(resampled, join="outer")  # union the instruments' hourly grids; empty bins NaN


def build_output_path(site: str, ds: xr.Dataset, resample: str, qaqc_filter: str, ext: str) -> str:
    t_start = pd.Timestamp(ds.time.values.min()).strftime("%Y%m%d")
    t_end = pd.Timestamp(ds.time.values.max()).strftime("%Y%m%d")
    return f"{site}_fixed_{t_start}_{t_end}_{resample}{qc_suffix(qaqc_filter)}.{ext}"


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
    type=click.Choice(QC_LEVELS),
    required=True,
    help=(
        "QC level; each includes the ones before it. 'ooi': OOI values as served. 'qartod': + QARTOD fail (4) "
        "and missing (9) masks. 'hitl': + config/adjustments.csv and approved HITL ledger masks. 'advanced': "
        "+ advanced pH flags (fixed products only). 'deploymentcorrected': + per-deployment discrete-sample "
        "corrections (provisional)."
    ),
)
@click.option(
    "--annotations-dir",
    default=ANNOTATIONS_DIR,
    show_default=True,
    help="Directory holding ledger.csv and raw/ harvested annotations (used at hitl and above).",
)
@click.option(
    "--output-dir",
    default=OUTPUT_DIR,
    show_default=True,
    help="Directory to write products to (one per S3 prefix under data/, e.g. data/cresst-easy-one-rca).",
)
def main(
    site: str,
    resample: str,
    start_year: int,
    end_year: int | None,
    fmt: str,
    qaqc_filter: str,
    annotations_dir: str,
    output_dir: str,
) -> None:
    """Resample fixed-instrument data (PC platforms and seafloor BEPs) to a common time grid.

    Output is saved to <output-dir>/<site>_fixed_<start>_<end>_<freq>_<level>.<ext>.  Example: slope_base_fixed_20150101_20260630_1h_hitl.zarr
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
        qaqc_filter=qaqc_filter,
    )
    nodes = {refdes.split("-")[1] for refdes in site_dict.values()}
    subsite = site_dict["ctd"][:8]
    annotations = load_annotations(subsite, nodes, annotations_dir) if qc_at(qaqc_filter, "hitl") else None
    ds_fixed = resample_fixed(instrument_datasets, resample, start_year, end_year, qaqc_filter, annotations)
    ds_fixed.attrs.update(product_attrs(qaqc_filter))
    if annotations is not None:
        ds_fixed = hitl_mask_attrs(ds_fixed, instrument_datasets)
        ds_fixed.attrs.update(annotation_provenance(subsite, annotations_dir))

    os.makedirs(output_dir, exist_ok=True)
    fmts = ["zarr", "nc"] if fmt == "both" else [fmt]
    for f in fmts:
        output_path = os.path.join(output_dir, build_output_path(site, ds_fixed, resample, qaqc_filter, f))
        logger.info(f"saving to {output_path}")
        if f == "zarr":
            ds_fixed.to_zarr(output_path, mode="w")
        else:
            ds_fixed.to_netcdf(output_path)

    logger.info("done")
    logger.remove(_log_id)


if __name__ == "__main__":
    main()
