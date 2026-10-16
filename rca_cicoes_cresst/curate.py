#!/usr/bin/env python3
"""Propose ledger decisions for new or OOI-edited HITL annotations.

Reads harvested annotations from annotations/raw/<SUBSITE>.csv and adds `proposed`
rows to annotations/ledger.csv for every annotation that is not yet in the
ledger or whose content (text, qcFlag, parameters, refdes) changed since its
decision. Approved rows are never overwritten. A reviewer approves proposals by
setting status=approved (and reviewed_at) in a PR.

- Annotations on instruments outside the products are ignored by rule (no LLM).
- Claude judges data-quality relevance for the rest. When OOI lists official
  parameters, those are used (mapped to zarr names via the preload netcdf_name);
  otherwise Claude chooses from the instrument's product parameters.

Usage:
    curate-annotations --all
    curate-annotations RS03AXPS CE02SHBP
"""
import ast
import os
from datetime import date
from pathlib import Path

import click
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

from rca_cicoes_cresst.common import (
    ANNOTATIONS_DIR,
    LEDGER_FILE,
    RAW_DIR,
    PARAM_TO_INSTRUMENT,
    content_hash,
    read_ledger,
)
from rca_cicoes_cresst.fixed_instruments import FIXED_SITES, PH_STITCH
from rca_cicoes_cresst.harvest_annotations import SITES
from rca_cicoes_cresst.regrid_profiler import PROFILER_SITES

load_dotenv()

MODEL = "claude-haiku-4-5"
PRELOAD_PARAMS = "https://raw.githubusercontent.com/oceanobservatories/preload-database/master/csv/ParameterDefs.csv"
LEDGER_COLUMNS = ["id", "subsite", "decision", "parameters_affected", "parameters_source", "rationale",
                  "decided_by", "status", "reviewed_at", "content_hash"]

# refdes (subsite-node-sensor) of every instrument feeding a product
PRODUCT_REFDES = {
    r for sites in (PROFILER_SITES, FIXED_SITES) for site in sites.values() for r in site.values()
} | set(PH_STITCH.values())

INSTRUMENT_TO_PARAMS: dict[str, list[str]] = {
    "ctd":       ["sea_water_temperature", "sea_water_practical_salinity",
                  "corrected_dissolved_oxygen", "sea_water_density"],
    "ph":        ["ph_seawater"],
    "pco2":      ["pco2_seawater", "partial_pressure_co2_ssw", "xco2_atm"],
    "nutrients": ["salinity_corrected_nitrate", "nitrate_concentration"],
    "o2":        ["corrected_dissolved_oxygen"],
    "fluoro":    ["fluorometric_chlorophyll_a", "fluorometric_cdom", "optical_backscatter"],
    "cdom":      ["flcdr_x_mmp_cds_fluorometric_cdom"],
}
SENSOR_CLASS_TO_INSTRUMENT = {
    "CTDPF": "ctd", "CTDBP": "ctd", "PHSEN": "ph", "PCO2W": "pco2", "NUTNR": "nutrients",
    "DOSTA": "o2", "DOFST": "o2", "FLORD": "fluoro", "FLNTU": "fluoro", "FLCDR": "cdom",
}
ALL_PRODUCT_PARAMS = sorted({p for ps in INSTRUMENT_TO_PARAMS.values() for p in ps})

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
- Calibration errors that produced incorrect derived data products, unless the annotation says
  the calibrations or coefficients have since been corrected (then the served data is good)
- Physical events that corrupted measurements (biofouling, debris)

NOT DATA QUALITY RELEVANT (data_quality_relevant=false):
- Instrument offline / not operational / no data collected (power outage, instrument recovery)
- Network or infrastructure outages (fiber breaks, shore station power loss)
- Data gaps under investigation with no quality verdict
- Configuration or sampling mode changes
- Operational notes with no flag on measurement accuracy
- Scientific observations of natural ocean variability
- Shallow profiler platform blowdowns (currents pushing the platform deeper), even if described
  as anomalous or flagged suspect: the measurements are real, the platform was just deeper"""


def official_params(ids: str, netcdf_names: dict[int, str]) -> set[str]:
    """OOI official parameter IDs mapped to the product variable names they cover."""
    return {netcdf_names.get(i) for i in ast.literal_eval(ids)} & set(ALL_PRODUCT_PARAMS)


def classify_annotation(client, row: pd.Series, default_params: list[str], official: set[str]) -> dict:
    annotation_text = (
        f"Annotation ID: {row['id']}\n"
        f"Subsite: {row['subsite']} | Node: {row['node']} | Sensor: {row['sensor']}\n"
        f"Period: {row['beginDT']} → {row['endDT']}\n"
        f"qcFlag: {row['qcFlag']}\n"
        f"Text: {row['annotation']}\n"
        f"OOI official parameters: {sorted(official) or 'none listed (applies to the whole stream)'}\n"
        f"Available parameters for this instrument: {default_params}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[CURATION_TOOL],
        tool_choice={"type": "tool", "name": "classify_annotation"},
        messages=[{"role": "user", "content": annotation_text}],
    )
    return next(b for b in response.content if b.type == "tool_use").input


def propose(client, row: pd.Series, netcdf_names: dict[int, str]) -> dict:
    """One proposed ledger row for a harvested annotation."""
    base = {"id": row["id"], "subsite": row["subsite"], "content_hash": content_hash(row), "reviewed_at": ""}
    refdes = f"{row['subsite']}-{row['node']}-{row['sensor']}"
    if pd.notna(row["sensor"]) and refdes not in PRODUCT_REFDES:
        return {**base, "decision": "ignore", "parameters_affected": "", "parameters_source": "",
                "rationale": "Not a product instrument.", "decided_by": "rule", "status": "approved"}

    instrument = SENSOR_CLASS_TO_INSTRUMENT.get(str(row["sensor"]).split("-")[-1][:5])
    default_params = INSTRUMENT_TO_PARAMS.get(instrument, ALL_PRODUCT_PARAMS)
    official = official_params(row["parameters"], netcdf_names)
    result = classify_annotation(client, row, default_params, official)
    if not result["data_quality_relevant"]:
        params, source = [], ""
    elif official:
        params, source = sorted(official), "official"
    else:
        params, source = sorted(set(result["parameters_affected"]) & set(PARAM_TO_INSTRUMENT)), "llm"
    return {**base, "decision": "mask" if params else "ignore", "parameters_affected": str(params) if params else "",
            "parameters_source": source, "rationale": result["reasoning"], "decided_by": f"llm:{MODEL}",
            "status": "proposed"}


@click.command()
@click.argument("subsites", nargs=-1)
@click.option("--all", "curate_all", is_flag=True, help="Curate every harvested subsite.")
@click.option("--annotations-dir", default=ANNOTATIONS_DIR, show_default=True,
              help="Directory holding ledger.csv and raw/ harvested annotations.")
def main(subsites: tuple[str, ...], curate_all: bool, annotations_dir: str) -> None:
    """Add proposed ledger rows for new or edited annotations of SUBSITES."""
    subsites = list(SITES.values()) if curate_all else [SITES.get(s, s) for s in subsites]
    if not subsites:
        raise click.UsageError("Provide SUBSITES or use --all.")

    ledger = read_ledger(annotations_dir).set_index("id")
    raw = pd.concat([pd.read_csv(Path(annotations_dir) / RAW_DIR / f"{s}.csv") for s in subsites], ignore_index=True)
    needs_review = raw[~raw["id"].isin(ledger.index) |
                       (raw.apply(content_hash, axis=1) != raw["id"].map(ledger["content_hash"]))]
    logger.info(f"{len(needs_review)} of {len(raw)} annotations need a decision")
    if needs_review.empty:
        return

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    preload = pd.read_csv(PRELOAD_PARAMS, usecols=["id", "netcdf_name"])
    preload = preload[preload["id"].astype(str).str.match(r"^PD\d+$")]
    netcdf_names = dict(zip(preload["id"].str[2:].astype(int), preload["netcdf_name"]))

    rows = []
    for _, row in needs_review.iterrows():
        proposal = propose(client, row, netcdf_names)
        if row["id"] in ledger.index:
            proposal["rationale"] = (f"OOI edited annotation; previous decision {ledger.at[row['id'], 'decision']}. "
                                     + proposal["rationale"])
        logger.info(f"id={row['id']} {row['sensor']}: {proposal['decision']} ({proposal['decided_by']}) {proposal['parameters_affected']}")
        rows.append(proposal)

    updated = pd.concat([ledger.drop(index=[r["id"] for r in rows], errors="ignore").reset_index(),
                         pd.DataFrame(rows)], ignore_index=True)
    updated[LEDGER_COLUMNS].sort_values(["subsite", "id"]).to_csv(Path(annotations_dir) / LEDGER_FILE, index=False)
    n_proposed = sum(r["status"] == "proposed" for r in rows)
    logger.info(f"wrote {len(rows)} ledger rows ({n_proposed} proposed, {date.today()}); review and approve in a PR")


if __name__ == "__main__":
    main()
