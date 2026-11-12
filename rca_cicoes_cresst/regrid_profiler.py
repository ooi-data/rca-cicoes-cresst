#!/usr/bin/env python3
import os

import numpy as np
import xarray as xr
import pandas as pd
import click
from datetime import datetime, timezone
from loguru import logger
from tqdm.auto import tqdm

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
    mask_qartod,
    product_sites,
    hitl_mask_attrs,
    product_attrs,
    qc_at,
    qc_suffix,
    stream_qc,
)

PROFILER_SITES = product_sites("profiler")

DOWNCAST_INSTRUMENTS: set[str] = {"ph", "pco2"}
# Under 1 sample per dbar, so interpolated onto the grid; the rest (4-22 per dbar) are bin-averaged
SPARSE_INSTRUMENTS: set[str] = {"ph", "pco2", "nutrients"}
# Advanced pH flags are not applied to profiler products (science lead, 2026-11-04): profiler pH
# is rough and the any-test rule would remove most of it. Fixed products apply them at advanced.
ADVANCED_PH = False

DEFAULT_PARAMS: dict[str, list[str]] = {
    "shallow": [
        "sea_water_temperature",
        "sea_water_practical_salinity",
        "corrected_dissolved_oxygen",
        "sea_water_density",
        "salinity_corrected_nitrate",
        "ph_seawater",
        "pco2_seawater",
    ],
    "deep": [
        "sea_water_temperature",
        "sea_water_practical_salinity",
        "corrected_dissolved_oxygen",
        "sea_water_density",
        "flntu_x_mmp_cds_fluorometric_chlorophyll_a",
        "flcdr_x_mmp_cds_fluorometric_cdom",
    ],
}


def load_regridding_inputs(
    site_dict: dict[str, str],
    params: list[str],
    sites_lookup: dict,
    qaqc_filter: str = "ooi",
) -> tuple[list[dict], pd.DataFrame]:
    site = site_dict["ctd"][:8]

    instrument_params = group_params_by_instrument(params, site_dict)

    instrument_datasets: list[dict] = []
    for instr_key, instr_params in instrument_params.items():
        refdes = site_dict[instr_key]
        stream_name = sites_lookup[refdes]["zarrFile"]
        logger.info(f"loading zarr: {instr_key} ({refdes})")
        ds = stream_qc(load_data(stream_name), refdes, stream_name, qaqc_filter, ADVANCED_PH)
        qartod_vars = [f"{p}_qartod_results" for p in instr_params if f"{p}_qartod_results" in ds]
        available = [v for v in PRES_PARAMS + instr_params + qartod_vars if v in ds]
        instrument_datasets.append({
            "instrument": instr_key,
            "ds": ds[available],
            "params": [p for p in instr_params if p in ds],
            "is_downcast": instr_key in DOWNCAST_INSTRUMENTS,
            "is_sparse": instr_key in SPARSE_INSTRUMENTS,
            "sensors": {refdes.split("-", 2)[2]},
            "hitl_masks": {},
        })

    logger.info("loading profile indices")
    last_year = max(int(d["ds"].time.max().dt.year) for d in instrument_datasets if d["ds"].sizes["time"])
    frames = []
    for year in range(START_YEAR, last_year + 1):
        try:
            frames.append(pd.read_csv(
                f"https://raw.githubusercontent.com/OOI-CabledArray/profileIndices/refs/heads/main/{site}_profiles_{year}.csv"
            ))
        except Exception:
            logger.warning(f"{site}: no profile index for {year}, skipping")
    all_indices = pd.concat(frames, axis=0, ignore_index=True)

    return instrument_datasets, all_indices


def interpolate_cast(ds_cast: xr.Dataset, pres_var: str, new_grid: np.ndarray) -> xr.Dataset:
    """Linear interpolation in pressure; a repeated pressure keeps its first sample."""
    _, first = np.unique(ds_cast[pres_var].values, return_index=True)
    ds_cast = ds_cast.isel(time=np.sort(first)).swap_dims({"time": pres_var}).drop_vars("time")
    return ds_cast.interp({pres_var: new_grid}).rename({pres_var: "sea_water_pressure"})


def bin_average_cast(ds_cast: xr.Dataset, pres_var: str, new_grid: np.ndarray) -> xr.Dataset | None:
    """Loop edit then bin average, as Sea-Bird processing and Argo do: drop samples deeper than the
    shallowest point already reached on the upcast, then average each bin centred on a grid level.
    None if no sample falls in the grid."""
    pres = ds_cast[pres_var].values
    level = np.floor((pres - new_grid[0]) / (new_grid[1] - new_grid[0]) + 0.5)  # index of the sample's bin
    keep = (pres <= np.fmin.accumulate(pres)) & (level >= 0) & (level < len(new_grid))
    if not keep.any():
        return None
    ds_cast = ds_cast.isel(time=keep).drop_vars(["time", pres_var])
    ds_cast["sea_water_pressure"] = ("time", new_grid[level[keep].astype(int)])
    # pandas groupby: ~50x faster per cast than xarray's without flox, over ~40k casts per site
    means = ds_cast.to_dataframe().groupby("sea_water_pressure").mean()
    binned = xr.Dataset.from_dataframe(means).reindex(sea_water_pressure=new_grid)
    for v in binned.data_vars:
        binned[v].attrs = ds_cast[v].attrs
    return binned


def regrid_profiles(
    instrument_datasets: list[dict],
    indices: pd.DataFrame,
    new_grid: np.ndarray,
    qaqc_filter: str = "ooi",
    annotations: pd.DataFrame | None = None,
) -> xr.Dataset:
    pds = []

    subset = indices.sort_values("start").reset_index(drop=True)

    for year, year_indices in subset.groupby(pd.to_datetime(subset["start"]).dt.year):
        year_datasets = []
        for instr in instrument_datasets:
            # one day past the year so casts crossing midnight on 31 December are whole
            ds_year = instr["ds"].sel(time=slice(f"{year}-01-01", f"{year + 1}-01-01")).compute()
            if annotations is not None:
                ds_year = mask_annotation_windows(ds_year, instr["params"], annotations, instr["sensors"], instr["hitl_masks"])
            ds_year = mask_qartod(ds_year, instr["params"], QARTOD_EXCLUDE if qc_at(qaqc_filter, "qartod") else set())
            year_datasets.append({**instr, "ds_year": ds_year})
        skipped = 0

        for _, row in tqdm(year_indices.iterrows(), total=len(year_indices), desc=str(year)):
            profile_parts = []

            for instr in year_datasets:
                time_slice = (
                    slice(row["peak"], row["end"])
                    if instr["is_downcast"]
                    else slice(row["start"], row["peak"])
                )
                ds_cast = instr["ds_year"].sel(time=time_slice)

                if ds_cast.sizes["time"] < 2:
                    continue

                pres_var = next((v for v in PRES_PARAMS if v in ds_cast), None)
                if pres_var is None:
                    continue

                to_grid = interpolate_cast if instr["is_sparse"] else bin_average_cast
                ds_grid = to_grid(ds_cast, pres_var, new_grid)
                if ds_grid is not None:
                    profile_parts.append(ds_grid)

            if not profile_parts:
                skipped += 1
                continue

            ds_profile = xr.merge(profile_parts)
            ds_profile = ds_profile.assign_coords(
                profile_number=row["profile"],
                start_time=pd.Timestamp(row["start"]),
                peak_time=pd.Timestamp(row["peak"]),
                end_time=pd.Timestamp(row["end"]),
            )
            pds.append(ds_profile)

        if skipped:
            logger.warning(f"{year}: {skipped}/{len(year_indices)} profiles skipped")

    logger.info("concatenating")
    return xr.concat(pds, dim="profile_number")


def build_output_path(site: str, ds: xr.Dataset, qaqc_filter: str, ext: str) -> str:
    t_start = pd.Timestamp(ds.start_time.values.min()).strftime("%Y%m%d")
    t_end = pd.Timestamp(ds.end_time.values.max()).strftime("%Y%m%d")
    return f"{site}_profiles_{t_start}_{t_end}{qc_suffix(qaqc_filter)}.{ext}"


@click.command()
@click.argument("site", type=click.Choice(list(PROFILER_SITES.keys())))
@click.option(
    "--grid",
    nargs=3,
    type=float,
    required=True,
    metavar="START STOP STEP",
    help="Pressure grid bounds and step (dbar)",
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
    grid: tuple[float, float, float],
    fmt: str,
    qaqc_filter: str,
    annotations_dir: str,
    output_dir: str,
) -> None:
    """Grid RCA shallow and deep profiler casts onto a uniform pressure grid: dense sensors are
    bin-averaged, sparse ones (pH, pCO2, nitrate) interpolated.

    Output is saved to <output-dir>/<site>_profiles_<start>_<end>_<level>.<ext>.
    Example: oregon_offshore_profiles_20150101_20260508_hitl.zarr
    With --format both, saves zarr and nc versions with the same base name.
    """
    new_grid = np.arange(*grid)

    os.makedirs("logs", exist_ok=True)
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _log_id = logger.add(f"logs/{site}_{run_ts}.log")

    site_dict = PROFILER_SITES[site]
    profile_type = "deep" if site.endswith("_deep") else "shallow"
    sites_lookup = ARCHIVE_DICT if profile_type == "deep" else ACTIVE_DICT
    instrument_datasets, indices = load_regridding_inputs(
        site_dict, DEFAULT_PARAMS[profile_type], sites_lookup, qaqc_filter
    )

    nodes = {refdes.split("-")[1] for refdes in site_dict.values()}
    subsite = site_dict["ctd"][:8]
    annotations = load_annotations(subsite, nodes, annotations_dir) if qc_at(qaqc_filter, "hitl") else None
    ds_profiles = regrid_profiles(instrument_datasets, indices, new_grid, qaqc_filter, annotations)
    ds_profiles.attrs.update(product_attrs(qaqc_filter, ADVANCED_PH))
    if annotations is not None:
        ds_profiles = hitl_mask_attrs(ds_profiles, instrument_datasets)
        ds_profiles.attrs.update(annotation_provenance(subsite, annotations_dir))

    os.makedirs(output_dir, exist_ok=True)
    fmts = ["zarr", "nc"] if fmt == "both" else [fmt]
    for f in fmts:
        output_path = os.path.join(output_dir, build_output_path(site, ds_profiles, qaqc_filter, f))
        logger.info(f"saving to {output_path}")
        if f == "zarr":
            ds_profiles.to_zarr(output_path, mode="w")
        else:
            ds_profiles.to_netcdf(output_path)

    logger.info("done")
    logger.remove(_log_id)


if __name__ == "__main__":
    main()
