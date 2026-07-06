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
    ARCHIVE_DICT,
    PRES_PARAMS,
    QARTOD_EXCLUDE,
    QARTOD_LABELS,
    START_YEAR,
    group_params_by_instrument,
    load_annotations,
    load_data,
    mask_annotation_windows,
    qc_suffix,
)

PROFILER_SITES: dict[str, dict[str, str]] = {
    "oregon_offshore": {
        "ctd":       "CE04OSPS-SF01B-2A-CTDPFA107",
        "ph":        "CE04OSPS-SF01B-2B-PHSENA108",
        "pco2":      "CE04OSPS-SF01B-4F-PCO2WA102",
        "nutrients": "CE04OSPS-SF01B-4A-NUTNRA102",
    },
    "slope_base": {
        "ctd":       "RS01SBPS-SF01A-2A-CTDPFA102",
        "ph":        "RS01SBPS-SF01A-2D-PHSENA101",
        "pco2":      "RS01SBPS-SF01A-4F-PCO2WA101",
        "nutrients": "RS01SBPS-SF01A-4A-NUTNRA101",
    },
    "axial_base": {
        "ctd":       "RS03AXPS-SF03A-2A-CTDPFA302",
        "ph":        "RS03AXPS-SF03A-2D-PHSENA301",
        "pco2":      "RS03AXPS-SF03A-4F-PCO2WA301",
        "nutrients": "RS03AXPS-SF03A-4A-NUTNRA301",
    },
    "oregon_offshore_deep": {
        "ctd":    "CE04OSPD-DP01B-01-CTDPFL105",
        "o2":     "CE04OSPD-DP01B-06-DOSTAD105",
        "fluoro": "CE04OSPD-DP01B-04-FLNTUA103",
        "cdom":   "CE04OSPD-DP01B-03-FLCDRA103",
    },
    "slope_base_deep": {
        "ctd":    "RS01SBPD-DP01A-01-CTDPFL104",
        "o2":     "RS01SBPD-DP01A-06-DOSTAD104",
        "fluoro": "RS01SBPD-DP01A-04-FLNTUA102",
        "cdom":   "RS01SBPD-DP01A-03-FLCDRA102",
    },
    "axial_base_deep": {
        "ctd":    "RS03AXPD-DP03A-01-CTDPFL304",
        "o2":     "RS03AXPD-DP03A-06-DOSTAD304",
        "fluoro": "RS03AXPD-DP03A-03-FLNTUA302",
        "cdom":   "RS03AXPD-DP03A-03-FLCDRA302",
    },
}

DOWNCAST_INSTRUMENTS: set[str] = {"ph", "pco2"}

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
        "fluorometric_chlorophyll_a",
        "flcdr_x_mmp_cds_fluorometric_cdom",
    ],
}


def load_regridding_inputs(
    site_dict: dict[str, str],
    params: list[str],
    sites_lookup: dict,
    end_year: int | None = None,
) -> tuple[list[dict], pd.DataFrame]:
    now = datetime.now(timezone.utc)
    current_year = now.year
    years = list(range(START_YEAR, (end_year or current_year) + 1))

    site = site_dict["ctd"][:8]

    instrument_params = group_params_by_instrument(params, site_dict)

    instrument_datasets: list[dict] = []
    for instr_key, instr_params in instrument_params.items():
        refdes = site_dict[instr_key]
        stream_name = sites_lookup[refdes]["zarrFile"]
        logger.info(f"loading zarr: {instr_key} ({refdes})")
        ds = load_data(stream_name)
        qartod_vars = [f"{p}_qartod_results" for p in instr_params if f"{p}_qartod_results" in ds]
        available = [v for v in PRES_PARAMS + instr_params + qartod_vars if v in ds]
        instrument_datasets.append({
            "instrument": instr_key,
            "ds": ds[available],
            "params": [p for p in instr_params if p in ds],
            "qartod_vars": qartod_vars,
            "is_downcast": instr_key in DOWNCAST_INSTRUMENTS,
        })

    logger.info("loading profile indices")
    frames = []
    for year in years:
        try:
            frames.append(pd.read_csv(
                f"https://raw.githubusercontent.com/OOI-CabledArray/profileIndices/refs/heads/main/{site}_profiles_{year}.csv"
            ))
        except Exception:
            logger.warning(f"{site}: no profile index for {year}, skipping")
    all_indices = pd.concat(frames, axis=0, ignore_index=True)

    return instrument_datasets, all_indices


def regrid_profiles(
    instrument_datasets: list[dict],
    indices: pd.DataFrame,
    new_grid: np.ndarray,
    qaqc_filter: str = "none",
    annotations: pd.DataFrame | None = None,
) -> xr.Dataset:
    pds = []

    subset = indices.sort_values("start").reset_index(drop=True)

    for year, year_indices in subset.groupby(pd.to_datetime(subset["start"]).dt.year):
        year_datasets = []
        for instr in instrument_datasets:
            ds_year = instr["ds"].sel(time=slice(f"{year}-01-01", f"{year}-12-31")).compute()
            if annotations is not None:
                ds_year = mask_annotation_windows(ds_year, instr["params"], annotations)
            year_datasets.append({**instr, "ds_year": ds_year})
        skipped = 0
        flag_removed: dict[int, int] = {}

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

                if qaqc_filter in QARTOD_EXCLUDE:
                    exclude_flags = QARTOD_EXCLUDE[qaqc_filter]
                    bad = np.zeros(ds_cast.sizes["time"], dtype=bool)
                    for fv in instr["qartod_vars"]:
                        if fv in ds_cast:
                            flag_vals = ds_cast[fv].values
                            for flag in exclude_flags:
                                n = int(np.sum(flag_vals == flag))
                                if n:
                                    flag_removed[flag] = flag_removed.get(flag, 0) + n
                            bad |= np.isin(flag_vals, list(exclude_flags))
                    ds_cast = ds_cast.isel(time=~bad).drop_vars(instr["qartod_vars"], errors="ignore")
                    if ds_cast.sizes["time"] < 2:
                        continue

                pres_var = next((v for v in PRES_PARAMS if v in ds_cast), None)
                if pres_var is None:
                    continue

                _, uniq_idx = np.unique(ds_cast[pres_var].values, return_index=True)
                ds_cast = ds_cast.isel(time=np.sort(uniq_idx))
                ds_cast = ds_cast.swap_dims({"time": pres_var})
                ds_cast = ds_cast.drop_vars("time")
                ds_int = ds_cast.interp({pres_var: new_grid})

                if pres_var != "sea_water_pressure":
                    ds_int = ds_int.rename({pres_var: "sea_water_pressure"})

                profile_parts.append(ds_int)

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
        if flag_removed:
            for flag, count in sorted(flag_removed.items()):
                logger.info(f"{year}: removed {count:,} points with flag {flag} ({QARTOD_LABELS.get(flag, '?')})")

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
    type=click.Choice(["none", "basic", "highest"]),
    default="none",
    show_default=True,
    help=(
        "QARTOD filter level. 'basic' excludes fail (4) and missing (9) flags. "
        "'highest' applies 'basic' plus masks parameters flagged in curated HITL annotations."
    ),
)
@click.option(
    "--annotations-dir",
    default="annotations/curated",
    show_default=True,
    help="Directory containing curated annotation CSVs (used with --qaqc-filter highest).",
)
def main(
    site: str,
    grid: tuple[float, float, float],
    fmt: str,
    qaqc_filter: str,
    annotations_dir: str,
) -> None:
    """Regrid RCA shallow profiler data to a uniform pressure grid.

    Output is saved to <site>_profiles_<start>_<end>.<ext> in the current directory.
    Example: oregon_offshore_profiles_20150101_20260508.zarr
    With --format both, saves zarr and nc versions with the same base name.
    """
    new_grid = np.arange(*grid)

    os.makedirs("logs", exist_ok=True)
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _log_id = logger.add(f"logs/{site}_{run_ts}.log")

    site_dict = PROFILER_SITES[site]
    profile_type = "deep" if site.endswith("_deep") else "shallow"
    sites_lookup = ARCHIVE_DICT if profile_type == "deep" else ACTIVE_DICT
    end_year = 2025 if profile_type == "deep" else None
    instrument_datasets, indices = load_regridding_inputs(site_dict, DEFAULT_PARAMS[profile_type], sites_lookup, end_year=end_year)

    nodes = {refdes.split("-")[1] for refdes in site_dict.values()}
    annotations = load_annotations(site_dict["ctd"][:8], annotations_dir, nodes) if qaqc_filter == "highest" else None
    ds_profiles = regrid_profiles(instrument_datasets, indices, new_grid, qaqc_filter, annotations)

    fmts = ["zarr", "nc"] if fmt == "both" else [fmt]
    for f in fmts:
        output_path = build_output_path(site, ds_profiles, qaqc_filter, f)
        logger.info(f"saving to {output_path}")
        if f == "zarr":
            ds_profiles.to_zarr(output_path, mode="w")
        else:
            ds_profiles.to_netcdf(output_path)

    logger.info("done")
    logger.remove(_log_id)


if __name__ == "__main__":
    main()
