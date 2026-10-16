"""Shared loading, QAQC, and annotation-masking logic for RCA data pipelines."""
import ast
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import s3fs
import xarray as xr
from loguru import logger

RCA_S3_BUCKET = "ooi-data/"
RCA_ADVANCED_BUCKET = "rca-advanced-qaqc/"
START_YEAR = 2015

# Advanced pH QC (rca_data_tools.qaqc.advanced_qaqc.ph_advanced_flags): positional
# test string, '1' pass / '3' fail. Per science lead (2026-07-20), a point is
# masked if ANY test reads 3 (all six tests are disqualifying, not just the hard ones).
PARAMS_URL = "https://raw.githubusercontent.com/OOI-CabledArray/rca-data-tools/refs/heads/main/rca_data_tools/qaqc/params"

fs = s3fs.S3FileSystem(anon=True, config_kwargs={"read_timeout": 300, "connect_timeout": 60})

ACTIVE_DICT = (
    pd.read_csv(f"{PARAMS_URL}/sitesDictionary.csv")
    .set_index("refDes")
    .T.to_dict("series")
)

ARCHIVE_DICT = (
    pd.read_csv(f"{PARAMS_URL}/archiveDictionary.csv")
    .set_index("refDes")
    .T.to_dict("series")
)

VARIABLE_MAP = (
    pd.read_csv(f"{PARAMS_URL}/variableMap.csv")
    .set_index("parameter")
    .T.to_dict("series")
)

PRES_PARAMS: list[str] = VARIABLE_MAP["pressure"]["variableNames"].strip('"').split(",")

PARAM_TO_INSTRUMENT: dict[str, str | list[str]] = {
    "sea_water_temperature":         "ctd",
    "sea_water_practical_salinity":  "ctd",
    "corrected_dissolved_oxygen":    ["o2", "ctd"],  # deep: DOSTA, shallow/fixed: integrated
    "sea_water_density":             "ctd",
    "salinity_corrected_nitrate":    "nutrients",
    "nitrate_concentration":         "nutrients",
    "ph_seawater":                   "ph",
    "ph_total":                      "ph",  # PHSENH (self-calibrating) reports total scale
    "pco2_seawater":                 "pco2",
    "partial_pressure_co2_ssw":      "pco2",
    "xco2_atm":                      "pco2",
    "fluorometric_chlorophyll_a":    "fluoro",
    "fluorometric_cdom":             "fluoro",
    "optical_backscatter":           "fluoro",
    "par":                           "par",
    "beam_attenuation":              "optics",
    "optical_absorption":            "optics",
    "flcdr_x_mmp_cds_fluorometric_cdom":  "cdom",
}

# Annotation parameter aliases: the shelf PHSENH reports ph_total, but the
# pipeline always serves pH as ph_seawater (via the shelf stitch rename), so
# ph_total annotations must match the unified ph_seawater variable.
PARAM_ALIASES: dict[str, str] = {"ph_total": "ph_seawater"}

QARTOD_EXCLUDE: dict[str, set[int]] = {
    "basic":    {4, 9},
    "highest":  {4, 9},
}

QARTOD_LABELS = {1: "pass", 2: "not_evaluated", 3: "suspect", 4: "fail", 9: "missing"}


def load_data(stream_name: str) -> xr.Dataset:
    zarr_store = fs.get_mapper(RCA_S3_BUCKET + stream_name)
    return xr.open_zarr(zarr_store, consolidated=True)


def group_params_by_instrument(params: list[str], site_dict: dict[str, str]) -> dict[str, list[str]]:
    """Resolve each requested parameter to an instrument key available at this site."""
    instrument_params: dict[str, list[str]] = {}
    for param in params:
        instr_keys = PARAM_TO_INSTRUMENT.get(param)
        if instr_keys is None:
            logger.warning(f"no instrument mapping for '{param}', skipping")
            continue
        if isinstance(instr_keys, str):
            instr_keys = [instr_keys]
        resolved = next((k for k in instr_keys if k in site_dict), None)
        if resolved is None:
            logger.warning(f"no available instrument for '{param}' at this site, skipping")
            continue
        instrument_params.setdefault(resolved, []).append(param)
    return instrument_params


ANNOTATIONS_DIR = "annotations"
RAW_DIR = "raw"  # harvested annotations + manifest, under ANNOTATIONS_DIR
LEDGER_FILE = "ledger.csv"
HARVEST_MANIFEST = "harvest_manifest.csv"
HARVEST_MAX_AGE_DAYS = 30

# The shelf PHSENH (reports ph_total from its own CTD salinity) replaced PHSEND103 here;
# before this date the stitched pH is PHSEND, which is insensitive to salinity.
SHELF_PHSENH_START = pd.Timestamp("2025-08-28", tz="UTC")


def content_hash(row: pd.Series) -> str:
    """Fingerprint of the annotation fields a decision depends on (not its window)."""
    params = sorted(ast.literal_eval(row["parameters"])) if isinstance(row["parameters"], str) else []
    key = "|".join(str(row[c]) for c in ("subsite", "node", "sensor", "annotation", "qcFlag")) + f"|{params}"
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def inherit_params(params: set[str], node, end) -> set[str]:
    """Add products OOI computes from a CTD's practical salinity (see CLAUDE.md)."""
    params = set(params)
    if "sea_water_practical_salinity" in params:
        params.add("corrected_dissolved_oxygen")
        if str(node).startswith("SF"):
            params.add("salinity_corrected_nitrate")
        if node == "LJ01D" and (pd.isna(end) or end > SHELF_PHSENH_START):
            params.add("ph_total")
    return params


def read_raw_annotations(subsite: str, annotations_dir: str = ANNOTATIONS_DIR) -> pd.DataFrame:
    raw = pd.read_csv(Path(annotations_dir) / RAW_DIR / f"{subsite}.csv")
    raw["beginDT"] = pd.to_datetime(raw["beginDT"], format="ISO8601", utc=True)
    raw["endDT"] = pd.to_datetime(raw["endDT"], format="ISO8601", utc=True)
    return raw


def read_ledger(annotations_dir: str = ANNOTATIONS_DIR) -> pd.DataFrame:
    return pd.read_csv(Path(annotations_dir) / LEDGER_FILE, dtype={"reviewed_at": str, "content_hash": str})


def harvest_time(subsite: str, annotations_dir: str = ANNOTATIONS_DIR) -> pd.Timestamp | None:
    path = Path(annotations_dir) / RAW_DIR / HARVEST_MANIFEST
    if not path.exists():
        return None
    m = pd.read_csv(path).set_index("subsite")
    return pd.Timestamp(m.at[subsite, "harvested_at"]) if subsite in m.index else None


def load_annotations(subsite: str, nodes: set[str] | None = None, annotations_dir: str = ANNOTATIONS_DIR) -> pd.DataFrame:
    """Approved `mask` decisions from the ledger, with windows from the latest harvest.

    Annotation masking matches on parameter name, and instruments on different
    nodes of the same mooring share parameter names — so filter to the nodes
    actually being processed (node-null annotations are subsite-wide and kept).
    """
    raw = read_raw_annotations(subsite, annotations_dir)
    if nodes is not None:
        raw = raw[raw["node"].isin(nodes) | raw["node"].isna()]
    ledger = read_ledger(annotations_dir).set_index("id")

    harvested = harvest_time(subsite, annotations_dir)
    if harvested is None or (pd.Timestamp.now(tz="UTC") - harvested).days > HARVEST_MAX_AGE_DAYS:
        logger.warning(f"{subsite}: annotations harvested {harvested or 'at unknown time'}; run harvest-annotations")
    unreviewed = raw[~raw["id"].isin(ledger.index)]
    if len(unreviewed):
        logger.warning(f"{subsite}: {len(unreviewed)} annotations not in ledger, run curate-annotations: {sorted(unreviewed['id'])}")
    known = raw[raw["id"].isin(ledger.index)]
    changed = known[known.apply(content_hash, axis=1).values != ledger.loc[known["id"], "content_hash"].values]
    if len(changed):
        logger.warning(f"{subsite}: {len(changed)} annotations edited by OOI since review, run curate-annotations: {sorted(changed['id'])}")
    proposed = ledger.loc[known["id"]].query("status != 'approved'")
    if len(proposed):
        logger.warning(f"{subsite}: {len(proposed)} proposed decisions not applied until approved: {sorted(proposed.index)}")

    masks = ledger[(ledger["decision"] == "mask") & (ledger["status"] == "approved")]
    unknown = {p for s in masks["parameters_affected"] for p in ast.literal_eval(s)} - set(PARAM_TO_INSTRUMENT)
    if unknown:
        logger.warning(f"ledger names unknown parameters (typo?), they mask nothing: {sorted(unknown)}")
    annotations = raw[raw["id"].isin(masks.index)].copy()
    annotations["parameters_affected"] = [
        sorted(inherit_params(ast.literal_eval(masks.at[i, "parameters_affected"]), node, end))
        for i, node, end in zip(annotations["id"], annotations["node"], annotations["endDT"])
    ]
    logger.info(f"{subsite}: {len(annotations)} approved mask annotations (nodes={nodes}, harvested {harvested})")
    return annotations


def annotation_provenance(subsite: str, annotations_dir: str = ANNOTATIONS_DIR) -> dict[str, str]:
    """Global attrs recording which harvest and ledger version masked a product."""
    ledger_sha = hashlib.sha1((Path(annotations_dir) / LEDGER_FILE).read_bytes()).hexdigest()[:10]
    return {"hitl_annotations_harvested": str(harvest_time(subsite, annotations_dir)), "hitl_ledger_sha1": ledger_sha}


def mask_annotation_windows(
    ds: xr.Dataset,
    params: list[str],
    annotations: pd.DataFrame,
) -> xr.Dataset:
    """NaN out affected parameters in a raw time-series for each annotation window."""
    combined_mask = xr.zeros_like(ds.time, dtype=bool)

    for _, row in annotations.iterrows():
        affected = [PARAM_ALIASES.get(p, p) for p in row["parameters_affected"]]

        overlap = [p for p in affected if p in params and p in ds]
        if not overlap:
            continue

        begin = row["beginDT"].to_datetime64()
        end = ds.time.values[-1] if pd.isna(row["endDT"]) else row["endDT"].to_datetime64()
        in_window = (ds.time >= begin) & (ds.time <= end)

        if not bool(in_window.any()):
            continue

        combined_mask = combined_mask | in_window

        for param in overlap:
            ds[param] = ds[param].where(~in_window)

        logger.info(
            f"annotation id={row['id']}: masked {int(in_window.sum())} time points "
            f"({row['beginDT'].date()} → {row['endDT'].date()}) params={overlap}"
        )

    if bool(combined_mask.any()):
        n_masked = int(combined_mask.sum())
        mean_dt = float(np.diff(ds.time.values).mean())  # nanoseconds
        total_duration = pd.Timedelta(int(n_masked * mean_dt))
        logger.info(f"params={params}: ~{total_duration} total masked ({n_masked} points)")

    return ds


def mask_ph_advanced(ds: xr.Dataset, ph_stream: str) -> xr.Dataset:
    """NaN out ph_seawater where any advanced pH QC test failed.

    Loads the precomputed advanced_qc_flags for this pH stream from the
    rca-advanced-qaqc bucket, aligns to ds by time, and masks any point whose
    flag string contains a 3 (failed test). Points with no matching flag are kept.
    """
    if "ph_seawater" not in ds:
        return ds
    if not fs.exists(RCA_ADVANCED_BUCKET + ph_stream):
        logger.warning(f"no advanced pH flags for {ph_stream}, skipping advanced masking")
        return ds
    store = fs.get_mapper(RCA_ADVANCED_BUCKET + ph_stream)
    flags = xr.open_zarr(store, consolidated=True)["advanced_qc_flags"]
    flags = flags.drop_duplicates("time")  # advanced store carries a few duplicate timestamps

    bad = flags.str.contains("3")  # any test failed (1 pass / 3 fail)
    bad = bad.reindex(time=ds.time, fill_value=False)
    ds["ph_seawater"] = ds["ph_seawater"].where(~bad)
    ds["ph_seawater"].attrs["advanced_qc"] = (
        f"masked where any advanced pH test failed ({flags.attrs['tests_executed']})"
    )
    logger.info(f"advanced pH: masked {int(bad.sum())}/{bad.sizes['time']} points ({ph_stream})")
    return ds


def qc_suffix(qaqc_filter: str, ph_advanced: bool = False) -> str:
    """Filename suffix encoding the QAQC level, e.g. '_qf49_HITL'."""
    suffix = ""
    if qaqc_filter in QARTOD_EXCLUDE:
        flags = "".join(str(f) for f in sorted(QARTOD_EXCLUDE[qaqc_filter]))
        suffix = f"_qf{flags}"
    if qaqc_filter == "highest":
        suffix += "_HITL"
    if ph_advanced:
        suffix += "_phadv"
    return suffix
