"""Shared loading, QAQC, and annotation-masking logic for RCA data pipelines."""
import ast
import hashlib
import json
import subprocess
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import s3fs
import xarray as xr
from loguru import logger

RCA_S3_BUCKET = "ooi-data/"
RCA_ADVANCED_BUCKET = "rca-advanced-qaqc/"
START_YEAR = 2014  # cabled array data begin late 2014

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
    "flntu_x_mmp_cds_fluorometric_chlorophyll_a":  "fluoro",  # deep profiler FLNTU
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

# QC levels (science lead, 2026-11-04), cumulative: each applies every step of the levels before it.
#   ooi:                 OOI values as served, only gridded or resampled
#   qartod:              + QARTOD masks
#   hitl:                + config/adjustments.csv, HITL ledger masks, salinity inheritance
#   advanced:            + advanced flags (pH so far; fixed products only)
#   deploymentcorrected: + per-deployment discrete-sample corrections (calibrationPipeline), provisional
QC_LEVELS = ("ooi", "qartod", "hitl", "advanced", "deploymentcorrected")
QARTOD_EXCLUDE = {4, 9}  # fail, missing
SPEC_VERSION = "0.2"  # docs/spec.md

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


# repo-relative so the pipelines can run from data/ (see README)
REPO_ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS_DIR = str(REPO_ROOT / "annotations")
DATA_DIR = REPO_ROOT / "data"  # one subdirectory per S3 prefix, e.g. data/cresst -> rca-advanced-qaqc/cresst
OUTPUT_DIR = str(DATA_DIR / "cresst")
ADJUSTMENTS_FILE = REPO_ROOT / "config" / "adjustments.csv"
SITES_FILE = REPO_ROOT / "config" / "sites.csv"

# Discrete-sample calibrations (OOI-CabledArray/calibrationPipeline), pinned. Ready per Ada
# (2026-11-02): shallow-profiler salinity and oxygen. Nitrate and fixed instruments in progress.
CALIBRATION_COMMIT = "a02841bcfd6d87d16470f5e498c198ec7088cfb6"
CALIBRATION_URL = (
    "https://raw.githubusercontent.com/OOI-CabledArray/calibrationPipeline/"
    f"{CALIBRATION_COMMIT}/outputs/deployments.json"
)
CALIBRATION_VARIABLES = {"salinity": "sea_water_practical_salinity", "oxygen": "corrected_dissolved_oxygen"}
CALIBRATION_MAX_STATUS = 3  # provisional: worst status level (1 good to 4 not recommended) applied
RAW_DIR = "raw"  # harvested annotations + manifest, under ANNOTATIONS_DIR
LEDGER_FILE = "ledger.csv"
HARVEST_MANIFEST = "harvest_manifest.csv"
HARVEST_MAX_AGE_DAYS = 30

PRELOAD_PARAMS = "https://raw.githubusercontent.com/oceanobservatories/preload-database/master/csv/ParameterDefs.csv"
# computed from salinity per preload, but too weakly to inherit a salinity mask
# (sensitivities in docs/parameter_dependencies.md)
SALINITY_INSENSITIVE = {"ph_seawater", "optical_backscatter"}
# ph_total is masked through its ph_seawater alias, which also holds PHSEN pH (insensitive), so
# it inherits only where and when a PHSENH supplies the pH: the shelf, after it replaced PHSEND103
PHSENH_START = {"LJ01D": pd.Timestamp("2025-08-28", tz="UTC")}


def content_hash(row: pd.Series) -> str:
    """Fingerprint of the annotation fields a decision depends on (not its window)."""
    params = sorted(ast.literal_eval(row["parameters"])) if isinstance(row["parameters"], str) else []
    key = "|".join(str(row[c]) for c in ("subsite", "node", "sensor", "annotation", "qcFlag")) + f"|{params}"
    return hashlib.sha1(key.encode()).hexdigest()[:10]


@cache
def read_preload() -> pd.DataFrame:
    """Preload ParameterDefs.csv, indexed by parameter id (PD###)."""
    p = pd.read_csv(PRELOAD_PARAMS)
    return p[p["id"].astype(str).str.match(r"^PD\d+$")].set_index("id")


@cache
def read_sites() -> pd.DataFrame:
    """config/sites.csv: instruments feeding each product."""
    s = pd.read_csv(SITES_FILE, comment="#")
    missing = (set(s["refdes"]) | set(s["stitch_from"].dropna())) - set(ACTIVE_DICT) - set(ARCHIVE_DICT)
    assert not missing, f"not in rca-data-tools params: {missing}"
    return s


def product_sites(product: str) -> dict[str, dict[str, str]]:
    """site -> {instrument: refdes} for product 'profiler' or 'fixed'."""
    s = read_sites().query("product == @product")
    return {site: dict(zip(g["instrument"], g["refdes"])) for site, g in s.groupby("site", sort=False)}


def upstream_dpis(p: pd.DataFrame, pd_id: str, seen: set[str] | None = None) -> set[str]:
    """Data products (DPIs) a parameter is computed from, following its parameterfunctionmap."""
    seen = set() if seen is None else seen
    if pd_id in seen or pd.isna(p.at[pd_id, "parameterfunctionmap"]):
        return set()
    seen.add(pd_id)
    dpis = set()
    for value in json.loads(p.at[pd_id, "parameterfunctionmap"]).values():
        for x in value if isinstance(value, list) else [value]:
            if isinstance(x, str) and x.startswith("dpi_"):
                dpis.add(x.removeprefix("dpi_"))
            elif isinstance(x, str) and x in p.index:
                if pd.notna(p.at[x, "dataproductidentifier"]):
                    dpis.add(p.at[x, "dataproductidentifier"])
                dpis |= upstream_dpis(p, x, seen)
    return dpis


@cache
def salinity_dependents() -> frozenset[str]:
    """Variables OOI computes from practical salinity (PRACSAL_L2), less SALINITY_INSENSITIVE."""
    p = read_preload()
    rows = p[p["netcdf_name"].isin(PARAM_TO_INSTRUMENT)]
    deps = {r["netcdf_name"] for pd_id, r in rows.iterrows() if "PRACSAL_L2" in upstream_dpis(p, pd_id)}
    return frozenset(deps - SALINITY_INSENSITIVE - {"sea_water_practical_salinity"})


def inherit_params(params: set[str], node, end) -> set[str]:
    """Add products OOI computes from a masked CTD salinity (see docs/parameter_dependencies.md).

    Applies node-wide; a product absent from the node masks nothing.
    """
    params = set(params)
    if "sea_water_practical_salinity" in params:
        params |= salinity_dependents()
        start = PHSENH_START.get(node)
        if start is None or not (pd.isna(end) or end > start):
            params.discard("ph_total")
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
    annotations["parameters_direct"] = [sorted(ast.literal_eval(masks.at[i, "parameters_affected"])) for i in annotations["id"]]
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


def iso_utc(ts: pd.Timestamp) -> str | None:
    return None if pd.isna(ts) else ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def hitl_mask_entry(row: pd.Series, param: str, sensors: set[str]) -> dict:
    """R25 record of one annotation masking one variable, with the rule that carried it there."""
    rules = []
    if pd.isna(row["sensor"]) or row["sensor"] not in sensors:
        rules.append("R19")  # node- or site-wide wildcard, or another sensor at the node
    if param not in {PARAM_ALIASES.get(p, p) for p in row["parameters_direct"]}:
        rules.append("R20")  # added by salinity inheritance
    return {"annotation_id": int(row["id"]), "begin": iso_utc(row["beginDT"]), "end": iso_utc(row["endDT"]),
            "via": "+".join(rules) or "direct"}


def mask_annotation_windows(
    ds: xr.Dataset,
    params: list[str],
    annotations: pd.DataFrame,
    sensors: set[str] = frozenset(),
    applied: dict | None = None,
) -> xr.Dataset:
    """NaN out affected parameters in a raw time-series for each annotation window.
    Records each annotation that matched in `applied` (variable -> {annotation id: entry}, R25);
    `sensors` are the instrument's sensor codes (e.g. 2A-CTDPFA102)."""
    if ds.sizes["time"] == 0:
        return ds
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
            if applied is not None:
                applied.setdefault(param, {})[int(row["id"])] = hitl_mask_entry(row, param, sensors)

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
    rca-advanced-qaqc bucket (rca_data_tools.qaqc.advanced_qaqc.ph_advanced_flags: one
    character per test, 1 pass / 3 fail), aligns to ds by time, and masks any point whose
    flag string contains a 3: every test is disqualifying (science lead, 2026-07-20). Only 3
    masks: any other code is kept, as are points with no matching flag.
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


def read_adjustments() -> pd.DataFrame:
    adj = pd.read_csv(ADJUSTMENTS_FILE)
    adj["begin"] = pd.to_datetime(adj["begin"], utc=True)
    adj["end"] = pd.to_datetime(adj["end"], utc=True)
    return adj


def apply_adjustments(ds: xr.Dataset, refdes: str) -> xr.Dataset:
    """Apply config/adjustments.csv rows for this instrument: mask, substitute or offset
    one variable inside a time window. Runs on the raw stream, before any masking."""
    adj = read_adjustments()
    for row in adj[adj["refdes"] == refdes].itertuples():
        var = row.variable
        if var not in ds:
            continue
        end = ds.time.values[-1] if pd.isna(row.end) else row.end.tz_localize(None).to_datetime64()
        in_window = (ds.time >= row.begin.tz_localize(None).to_datetime64()) & (ds.time <= end)
        if row.action == "mask":
            ds[var] = ds[var].where(~in_window)
        elif row.action == "substitute":
            if row.source not in ds:
                logger.warning(f"{refdes} adjustment {row.id}: source {row.source} not in stream, skipped")
                continue
            ds[var] = ds[var].where(~in_window, ds[row.source])
            q, src_q = f"{var}_qartod_results", f"{row.source}_qartod_results"
            if q in ds and src_q in ds:
                ds[q] = ds[q].where(~in_window, ds[src_q])
        elif row.action == "offset":
            ds[var] = ds[var].where(~in_window, ds[var] + row.value)
        until = "open" if pd.isna(row.end) else f"{row.end:%Y-%m-%dT%H:%M}"
        note = f"adjustment {row.id}: {row.action} {row.begin:%Y-%m-%dT%H:%M} to {until} ({row.rationale})"
        ds[var].attrs["adjustments"] = "; ".join(filter(None, [ds[var].attrs.get("adjustments"), note]))
        logger.info(f"{refdes} {note}")
    return ds


@cache
def read_calibrations() -> pd.DataFrame:
    """Per-deployment discrete-sample corrections from calibrationPipeline: one row per product
    refdes, variable and deployment, with kind (offset: add, scale: multiply), value and status
    level (1 good to 4 not recommended)."""
    cal = requests.get(CALIBRATION_URL).json()
    # oxygen is calibrated on the DOFSTA refdes but served in the CTD stream on the same port
    ctd = {r.rsplit("-", 1)[0]: r for r in read_sites()["refdes"] if "-CTD" in r}
    rows = []
    for inst in cal["instruments"]:
        if inst["variable"] not in CALIBRATION_VARIABLES:
            continue
        for d in filter(lambda d: d["calibrated"], inst["deployments"]):
            gain = (d["function_offset"] or {}).get("gain")
            rows.append({
                "refdes": ctd.get(inst["refdes"].rsplit("-", 1)[0], inst["refdes"]),
                "variable": CALIBRATION_VARIABLES[inst["variable"]],
                "deployment": d["deployment"],
                "kind": "offset" if gain is None else "scale",
                "value": d["flat_offset"]["value"] if gain is None else gain,
                "status": d["status"]["level"],
                "record_id": d["record_id"],
            })
    return pd.DataFrame(rows)


def apply_calibrations(ds: xr.Dataset, refdes: str, max_status: int) -> xr.Dataset:
    """Apply read_calibrations rows for this instrument, matched on the stream's deployment number.
    Deployments rated above max_status stay uncorrected. Runs on the raw stream, after adjustments."""
    cal = read_calibrations()
    for row in cal[(cal["refdes"] == refdes) & (cal["status"] <= max_status)].itertuples():
        if row.variable not in ds:
            continue
        var = ds[row.variable]
        corrected = var + row.value if row.kind == "offset" else var * row.value
        ds[row.variable] = var.where(ds["deployment"] != row.deployment, corrected)
        note = f"deployment {row.deployment}: {row.kind} {row.value} (status {row.status}, {row.record_id})"
        ds[row.variable].attrs["calibrations"] = "; ".join(filter(None, [var.attrs.get("calibrations"), note]))
        logger.info(f"{refdes} {row.variable} calibration, {note}")
    if "sea_water_practical_salinity" in cal[cal["refdes"] == refdes]["variable"].values:
        logger.warning(f"{refdes}: sea_water_density not recomputed from calibrated salinity")  # TODO: gsw
    return ds


def mask_qartod(ds: xr.Dataset, params: list[str], exclude_flags: set[int]) -> xr.Dataset:
    """NaN each parameter where its own QARTOD flag is in exclude_flags, then drop the flag variables."""
    flag_vars = [f"{p}_qartod_results" for p in params if f"{p}_qartod_results" in ds]
    for fv in flag_vars:
        param = fv.removesuffix("_qartod_results")
        bad = ds[fv].isin(list(exclude_flags))
        if exclude_flags and bool(bad.any()):
            counts = {QARTOD_LABELS[f]: int((ds[fv] == f).sum()) for f in sorted(exclude_flags)}
            logger.info(f"QARTOD {param}: masked {counts}")
        ds[param] = ds[param].where(~bad)
    return ds.drop_vars(flag_vars)


def qc_at(level: str, step_level: str) -> bool:
    """Whether a product at `level` includes the steps introduced at `step_level`."""
    return QC_LEVELS.index(level) >= QC_LEVELS.index(step_level)


def stream_qc(ds: xr.Dataset, refdes: str, stream_name: str, level: str, advanced_ph: bool = True) -> xr.Dataset:
    """QC steps that run on each raw stream before slicing: adjustments, deployment corrections,
    advanced pH. Value changes run before masks; the level only decides which steps run."""
    if qc_at(level, "hitl"):
        ds = apply_adjustments(ds, refdes)
    if qc_at(level, "deploymentcorrected"):
        ds = apply_calibrations(ds, refdes, CALIBRATION_MAX_STATUS)
    if qc_at(level, "advanced") and advanced_ph:
        ds = mask_ph_advanced(ds, stream_name)
    return ds


def qc_steps(level: str, advanced_ph: bool = True) -> str:
    """The QC steps both pipelines apply at this level, in order, for the product's attrs."""
    steps = []
    if qc_at(level, "hitl"):
        steps.append("adjustments: config/adjustments.csv (mask/substitute/offset windows)")
    if qc_at(level, "deploymentcorrected"):
        steps.append(f"deployment corrections: calibrationPipeline {CALIBRATION_COMMIT[:7]} per-deployment "
                     f"offsets and gains, status <= {CALIBRATION_MAX_STATUS}")
    if qc_at(level, "advanced"):
        steps.append("advanced pH: ph_seawater masked where any advanced test failed (3)" if advanced_ph
                     else "advanced pH: not applied to profiler products")
    if qc_at(level, "hitl"):
        steps.append("HITL: approved annotations/ledger.csv masks, plus CTD-salinity inheritance")
    if qc_at(level, "qartod"):
        steps.append(f"QARTOD: each variable masked where its flag is in {sorted(QARTOD_EXCLUDE)}")
    return " | ".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) or "none: OOI values as served"


def hitl_mask_attrs(ds: xr.Dataset, instrument_datasets: list[dict]) -> xr.Dataset:
    """Set every variable's hitl_masks attribute (R25) from the masks recorded while building."""
    applied: dict[str, dict] = {}
    for instr in instrument_datasets:
        for var, entries in instr["hitl_masks"].items():
            applied.setdefault(var, {}).update(entries)
    for var in ds.data_vars:
        entries = sorted(applied.get(var, {}).values(), key=lambda e: (e["begin"], e["annotation_id"]))
        ds[var].attrs["hitl_masks"] = json.dumps(entries)
    return ds


def git_commit() -> str:
    """HEAD of this repository, with -dirty if tracked files have uncommitted changes."""
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True).stdout.strip()
    return git("rev-parse", "HEAD") + ("-dirty" if git("status", "--porcelain", "--untracked-files=no") else "")


def product_attrs(level: str, advanced_ph: bool = True) -> dict[str, str]:
    """Global attrs every product gets at build time (R29; release is added by release-cresst)."""
    return {"qc_level": level, "qc_steps": qc_steps(level, advanced_ph), "spec_version": SPEC_VERSION,
            "git_commit": git_commit()}


def qc_suffix(level: str) -> str:
    """Filename suffix naming the QC level, e.g. '_hitl'."""
    return f"_{level}"
