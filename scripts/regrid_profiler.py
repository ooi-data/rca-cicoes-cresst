#!/usr/bin/env python3
import numpy as np
import xarray as xr
import pandas as pd
import s3fs
import click
from datetime import datetime, timezone
from loguru import logger
from tqdm.auto import tqdm

RCA_S3_BUCKET = "ooi-data/"
START_YEAR = 2015

fs = s3fs.S3FileSystem(anon=True)

SITES_DICT = (
    pd.read_csv("https://raw.githubusercontent.com/OOI-CabledArray/rca-data-tools/refs/heads/main/rca_data_tools/qaqc/params/sitesDictionary.csv")
    .set_index("refDes")
    .T.to_dict("series")
)

VARIABLE_MAP = (
    pd.read_csv("https://raw.githubusercontent.com/OOI-CabledArray/rca-data-tools/refs/heads/main/rca_data_tools/qaqc/params/variableMap.csv")
    .set_index("parameter")
    .T.to_dict("series")
)

PROFILER_SITES: dict[str, dict[str, str]] = {
    "oregon_shelf": {
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
}

DOWNCAST_INSTRUMENTS: set[str] = {"ph", "pco2"}

PRES_PARAMS: list[str] = VARIABLE_MAP["pressure"]["variableNames"].strip('"').split(",")

PARAM_TO_INSTRUMENT: dict[str, str] = {
    "sea_water_temperature":         "ctd",
    "sea_water_practical_salinity":  "ctd",
    "corrected_dissolved_oxygen":    "ctd",
    "sea_water_density":             "ctd",
    "salinity_corrected_nitrate":    "nutrients",
    "nitrate_concentration":         "nutrients",
    "ph_seawater":                   "ph",
    "pco2_seawater":                 "pco2",
    "partial_pressure_co2_ssw":      "pco2",
    "xco2_atm":                      "pco2",
    "fluorometric_chlorophyll_a":    "fluoro",
    "optical_backscatter":           "fluoro",
    "par":                           "par",
    "beam_attenuation":              "optics",
    "optical_absorption":            "optics",
}

DEFAULT_PARAMS: list[str] = [
    "sea_water_temperature",
    "sea_water_practical_salinity",
    "corrected_dissolved_oxygen",
    "sea_water_density",
    "salinity_corrected_nitrate",
    "ph_seawater",
    "pco2_seawater",
]



QARTOD_EXCLUDE: dict[str, set[int]] = {
    "basic": {2, 4},
}



def load_data(stream_name: str) -> xr.Dataset:
    zarr_store = fs.get_mapper(RCA_S3_BUCKET + stream_name)
    return xr.open_zarr(zarr_store, consolidated=True)


def load_regridding_inputs(
    site_dict: dict[str, str],
    params: list[str],
) -> tuple[list[dict], pd.DataFrame]:
    now = datetime.now(timezone.utc)
    current_year = now.year
    years = list(range(START_YEAR, current_year + 1))

    site = site_dict["ctd"][:8]

    instrument_params: dict[str, list[str]] = {}
    for param in params:
        instr_key = PARAM_TO_INSTRUMENT.get(param)
        if instr_key is None:
            logger.warning(f"no instrument mapping for '{param}', skipping")
            continue
        instrument_params.setdefault(instr_key, []).append(param)

    instrument_datasets: list[dict] = []
    for instr_key, instr_params in instrument_params.items():
        refdes = site_dict[instr_key]
        stream_name = SITES_DICT[refdes]["zarrFile"]
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
    all_indices = pd.concat(
        [
            pd.read_csv(
                f"https://raw.githubusercontent.com/OOI-CabledArray/profileIndices/refs/heads/main/{site}_profiles_{year}.csv"
            )
            for year in years
        ],
        axis=0,
        ignore_index=True,
    )

    return instrument_datasets, all_indices


def regrid_profiles(
    instrument_datasets: list[dict],
    indices: pd.DataFrame,
    new_grid: np.ndarray,
    qaqc_filter: str = "none",
) -> xr.Dataset:
    pds = []

    subset = indices.sort_values("start").reset_index(drop=True)

    for year, year_indices in subset.groupby(pd.to_datetime(subset["start"]).dt.year):
        year_datasets = [
            {**instr, "ds_year": instr["ds"].sel(time=str(year)).compute()}
            for instr in instrument_datasets
        ]
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

                if qaqc_filter in QARTOD_EXCLUDE:
                    exclude_flags = QARTOD_EXCLUDE[qaqc_filter]
                    bad = np.zeros(ds_cast.sizes["time"], dtype=bool)
                    for fv in instr["qartod_vars"]:
                        if fv in ds_cast:
                            bad |= np.isin(ds_cast[fv].values, list(exclude_flags))
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

    logger.info("concatenating")
    return xr.concat(pds, dim="profile_number")


def build_output_path(site: str, ds: xr.Dataset, ext: str) -> str:
    t_start = pd.Timestamp(ds.start_time.values.min()).strftime("%Y%m%d")
    t_end = pd.Timestamp(ds.end_time.values.max()).strftime("%Y%m%d")
    return f"{site}_profiles_{t_start}_{t_end}.{ext}"


@click.command()
@click.argument("site", type=click.Choice(list(PROFILER_SITES.keys())))
@click.option(
    "--grid",
    nargs=3,
    type=float,
    default=(0.0, 220.0, 0.25),
    show_default=True,
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
    type=click.Choice(["none", "basic"]),
    default="none",
    show_default=True,
    help="QARTOD filter level. 'basic' excludes not-evaluated (2) and fail (4) flags.",
)
def main(
    site: str,
    grid: tuple[float, float, float],
    fmt: str,
    qaqc_filter: str,
) -> None:
    """Regrid RCA shallow profiler data to a uniform pressure grid.

    Output is saved to <site>_profiles_<start>_<end>.<ext> in the current directory.
    Example: oregon_shelf_profiles_20150101_20260508.zarr
    With --format both, saves zarr and nc versions with the same base name.
    """
    new_grid = np.arange(*grid)

    site_dict = PROFILER_SITES[site]
    instrument_datasets, indices = load_regridding_inputs(site_dict, DEFAULT_PARAMS)
    ds_profiles = regrid_profiles(instrument_datasets, indices, new_grid, qaqc_filter)

    fmts = ["zarr", "nc"] if fmt == "both" else [fmt]
    for f in fmts:
        output_path = build_output_path(site, ds_profiles, f)
        logger.info(f"saving to {output_path}")
        if f == "zarr":
            ds_profiles.to_zarr(output_path, mode="w")
        else:
            ds_profiles.to_netcdf(output_path)

    logger.info("done")


if __name__ == "__main__":
    main()
