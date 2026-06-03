#!/usr/bin/env python3
"""Curate OOI HITL annotations for a given subsite.

Reads a raw annotations CSV from annotations/<SUBSITE>.csv and writes curated
output to annotations/curated/<SUBSITE>.csv.

Two curation modes:
  --qc-flag   Rule-based: keep annotations whose qcFlag matches (fast, no API).
  (default)   LLM-based: Claude classifies each annotation for data-quality relevance.

Usage:
    # rule-based — keep fail and suspect flags only
    python scripts/curate.py CE04OSPS --qc-flag fail --qc-flag suspect

    # LLM-based
    python scripts/curate.py CE04OSPS \
        --sensor 2A-CTDPFA107:ctd \
        --sensor 2B-PHSENA108:ph \
        --sensor 4F-PCO2WA102:pco2 \
        --sensor 4A-NUTNRA102:nutrients
"""
import os
from pathlib import Path

import click
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

INSTRUMENT_TO_PARAMS: dict[str, list[str]] = {
    "ctd":       ["sea_water_temperature", "sea_water_practical_salinity",
                  "corrected_dissolved_oxygen", "sea_water_density"],
    "ph":        ["ph_seawater"],
    "pco2":      ["pco2_seawater", "partial_pressure_co2_ssw", "xco2_atm"],
    "nutrients": ["salinity_corrected_nitrate", "nitrate_concentration"],
    "o2":        ["corrected_dissolved_oxygen"],
    "fluoro":    ["fluorometric_chlorophyll_a", "optical_backscatter"],
    "cdom":      ["flcdr_x_mmp_cds_fluorometric_cdom"],
}

CURATION_TOOL = {
    "name": "classify_annotation",
    "description": "Classify an OOI annotation for data-quality relevance.",
    "input_schema": {
        "type": "object",
        "properties": {
            "data_quality_relevant": {
                "type": "boolean",
                "description": (
                    "True if this annotation identifies a period where measured data "
                    "values are inaccurate, suspect, or should be excluded from analysis. "
                    "False for operational notes, data gaps, network outages, instrument "
                    "restarts, or configuration changes that do not indicate bad measurement values."
                ),
            },
            "parameters_affected": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of OOI parameter names affected, drawn from the available parameters "
                    "for this instrument. Use the full default instrument parameter list unless "
                    "the annotation explicitly names a subset."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "One sentence explaining the classification decision.",
            },
        },
        "required": ["data_quality_relevant", "parameters_affected", "reasoning"],
    },
}

SYSTEM_PROMPT = """You are a physical oceanography data quality specialist reviewing OOI (Ocean Observatories Initiative) instrument annotations.

Your job is to classify each annotation as either data-quality relevant or not, and identify which measured parameters are affected.

DATA QUALITY RELEVANT (data_quality_relevant=true):
- Measurements are inaccurate, suspect, or should not be used in analysis
- Instrument malfunction affecting measurement values (pump failure, clogged conductivity cell, sensor drift)
- HITL or automated QC flagged data as fail or suspect
- Calibration errors that produced incorrect derived data products
- Physical events that corrupted measurements (biofouling, debris)

NOT DATA QUALITY RELEVANT (data_quality_relevant=false):
- Instrument offline / not operational / no data collected (power outage, instrument recovery)
- Network or infrastructure outages (fiber breaks, shore station power loss)
- Data gaps under investigation with no quality verdict
- Configuration or sampling mode changes
- Operational notes with no flag on measurement accuracy
- Scientific observations of natural ocean variability"""


def classify_annotation(
    client,
    row: pd.Series,
    default_params: list[str],
) -> dict:
    annotation_text = (
        f"Annotation ID: {row['id']}\n"
        f"Subsite: {row['subsite']} | Node: {row.get('node', '')} | Sensor: {row.get('sensor', '')}\n"
        f"Period: {row['beginDT']} → {row['endDT']}\n"
        f"qcFlag: {row.get('qcFlag', '')}\n"
        f"Text: {row['annotation']}\n"
        f"Available parameters for this instrument: {default_params}"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[CURATION_TOOL],
        tool_choice={"type": "tool", "name": "classify_annotation"},
        messages=[{"role": "user", "content": annotation_text}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input


@click.command()
@click.argument("subsite")
@click.option(
    "--sensor", "sensors",
    multiple=True,
    metavar="SENSOR:INSTRUMENT",
    help="e.g. 2A-CTDPFA107:ctd  (repeatable, LLM mode only)",
)
@click.option(
    "--node", default=None,
    help="Restrict to a specific node (e.g. SF01B). If omitted, all nodes are considered.",
)
@click.option(
    "--qc-flag", "qc_flags",
    multiple=True,
    metavar="FLAG",
    help=(
        "Keep annotations with this qcFlag value (repeatable). "
        "If provided, skips LLM classification entirely. "
        "Valid values: fail, suspect, not_operational, not_available."
    ),
)
@click.option(
    "--annotations-dir", default="annotations",
    show_default=True,
    help="Directory containing raw annotation CSVs.",
)
def main(
    subsite: str,
    sensors: tuple[str, ...],
    node: str | None,
    qc_flags: tuple[str, ...],
    annotations_dir: str,
) -> None:
    """Curate OOI annotations for SUBSITE.

    Rule-based mode (--qc-flag): filters by qcFlag value, no API call required.\n
    LLM mode (default): uses Claude to classify each annotation for data-quality relevance.
    """
    raw_path = Path(annotations_dir) / f"{subsite}.csv"
    if not raw_path.exists():
        raise click.ClickException(f"Raw annotations not found: {raw_path}")

    df = pd.read_csv(raw_path)

    if node:
        df = df[df["node"] == node]

    out_dir = Path(annotations_dir) / "curated"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{subsite}.csv"

    if qc_flags:
        curated = df[df["qcFlag"].isin(qc_flags)].copy()
        logger.info(
            f"{subsite}: {len(curated)}/{len(df)} annotations match qcFlag in {list(qc_flags)}"
        )
        if curated.empty:
            logger.warning("No annotations matched the requested qcFlag values.")
            return
        out_path = out_dir / f"{subsite}_qcflag.csv"
        curated.to_csv(out_path, index=False)
        logger.info(f"Saved {len(curated)} curated annotations to {out_path}")
        return

    # LLM mode
    sensor_map: dict[str, str] = {}
    for s in sensors:
        sensor_code, instr_key = s.split(":", 1)
        sensor_map[sensor_code] = instr_key

    if sensor_map:
        df = df[df["sensor"].isin(sensor_map)]

    logger.info(f"{len(df)} annotations to classify for {subsite}")

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    results = []
    for _, row in df.iterrows():
        sensor = row.get("sensor", "")
        instr_key = sensor_map.get(sensor, "")
        default_params = INSTRUMENT_TO_PARAMS.get(instr_key, [])

        try:
            result = classify_annotation(client, row, default_params)
        except Exception as e:
            logger.warning(f"id={row['id']}: classification failed ({e}), skipping")
            continue

        logger.info(
            f"id={row['id']} sensor={sensor} relevant={result['data_quality_relevant']} — {result['reasoning']}"
        )
        results.append({**row.to_dict(), **result})

    curated = pd.DataFrame([r for r in results if r["data_quality_relevant"]])
    if curated.empty:
        logger.warning("No data-quality-relevant annotations found.")
        return

    out_path = out_dir / f"{subsite}_llm.csv"
    curated.to_csv(out_path, index=False)
    logger.info(f"Saved {len(curated)}/{len(results)} curated annotations to {out_path}")


if __name__ == "__main__":
    main()
