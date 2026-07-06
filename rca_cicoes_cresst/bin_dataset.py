#!/usr/bin/env python3
import os
import xarray as xr
import click
from pathlib import Path
from loguru import logger

OUTPUT_DIR = "data/binned"


def load_dataset(path: str) -> xr.Dataset:
    p = Path(path)
    if p.is_dir() or p.suffix == ".zarr":
        return xr.open_zarr(path)
    return xr.open_dataset(path)


def build_output_path(input_path: str, bin_hours: float, ext: str) -> str:
    stem = Path(input_path).stem
    label = f"{int(bin_hours)}h" if bin_hours == int(bin_hours) else f"{bin_hours}h"
    return os.path.join(OUTPUT_DIR, f"{stem}_binned_{label}.{ext}")


@click.command()
@click.argument("file", type=click.Path(exists=True))
@click.option(
    "--bin",
    "bin_hours",
    type=float,
    required=True,
    metavar="HOURS",
    help="Bin width in hours (e.g. 24 for daily, 168 for weekly)",
)
@click.option(
    "--format", "fmt",
    type=click.Choice(["zarr", "nc", "both"]),
    default="zarr",
    show_default=True,
    help="Output file format",
)
def main(file: str, bin_hours: float, fmt: str) -> None:
    """Bin a pressure-gridded profiler dataset along the time axis.

    Profiles are averaged into time bins of the specified width.
    Output dimensions: (peak_time, sea_water_pressure).

    Example:
        python scripts/bin_dataset.py axial_base_profiles.zarr --bin 24
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    logger.info(f"loading {file}")
    ds = load_dataset(file)

    logger.info(f"binning at {bin_hours}h intervals")
    ds_time = (
        ds
        .swap_dims({"profile_number": "peak_time"})
        .drop_vars(["profile_number", "start_time", "end_time"], errors="ignore")
    )
    ds_binned = ds_time.resample(peak_time=f"{bin_hours}h").mean().rename({"peak_time": "time"})

    fmts = ["zarr", "nc"] if fmt == "both" else [fmt]
    for f in fmts:
        out = build_output_path(file, bin_hours, f)
        logger.info(f"saving to {out}")
        if f == "zarr":
            ds_binned.to_zarr(out, mode="w")
        else:
            ds_binned.to_netcdf(out)

    logger.info("done")


if __name__ == "__main__":
    main()
