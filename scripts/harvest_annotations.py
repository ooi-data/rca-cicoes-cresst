#!/usr/bin/env python3
"""Harvest OOI HITL annotations for a subsite via the M2M API.

Saves raw annotations to annotations/<SUBSITE>.csv.

Usage:
    python scripts/harvest_annotations.py oregon_offshore
    python scripts/harvest_annotations.py CE04OSPS
    python scripts/harvest_annotations.py --all
"""
import os
import sys
from pathlib import Path

import click
import pandas as pd
import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

ANNOTATIONS_ENDPOINT = "https://ooinet.oceanobservatories.org/api/m2m/12580/anno/find"

PROFILER_SITES: dict[str, str] = {
    "oregon_offshore":      "CE04OSPS",
    "oregon_offshore_deep": "CE04OSPD",
    "slope_base":           "RS01SBPS",
    "slope_base_deep":      "RS01SBPD",
    "axial_base":           "RS03AXPS",
    "axial_base_deep":      "RS03AXPD",
}


def harvest(subsite: str, out_dir: Path) -> Path:
    """Fetch annotations for one subsite and write to CSV. Returns output path."""
    username = os.environ["OOI_USERNAME"]
    token = os.environ["OOI_TOKEN"]

    logger.info(f"fetching annotations for {subsite}")
    response = requests.get(
        ANNOTATIONS_ENDPOINT,
        params={"refdes": subsite},
        auth=(username, token),
    )
    response.raise_for_status()

    records = response.json()
    if not records:
        logger.warning(f"{subsite}: no annotations returned")
        return None

    df = pd.DataFrame(records)
    for col in ("beginDT", "endDT"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit="ms", utc=True)

    df = df.sort_values("beginDT").reset_index(drop=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{subsite}.csv"
    df.to_csv(out_path, index=False)
    logger.info(f"{subsite}: {len(df)} annotations saved to {out_path}")
    return out_path


@click.command()
@click.argument("site", required=False)
@click.option(
    "--all", "harvest_all",
    is_flag=True,
    help="Harvest all sites in PROFILER_SITES.",
)
@click.option(
    "--out-dir", default="annotations",
    show_default=True,
    help="Directory to write raw annotation CSVs.",
)
def main(site: str | None, harvest_all: bool, out_dir: str) -> None:
    """Harvest HITL annotations for SITE (site key or raw subsite code).

    SITE can be a key from PROFILER_SITES (e.g. 'oregon_offshore') or a raw
    OOI subsite code (e.g. 'CE04OSPS').  Use --all to harvest every site.
    """
    if not site and not harvest_all:
        raise click.UsageError("Provide a SITE argument or use --all.")

    out_path = Path(out_dir)

    if harvest_all:
        for key, subsite in PROFILER_SITES.items():
            try:
                harvest(subsite, out_path)
            except Exception as e:
                logger.error(f"{subsite}: {e}")
    else:
        subsite = PROFILER_SITES.get(site, site)
        harvest(subsite, out_path)


if __name__ == "__main__":
    main()
