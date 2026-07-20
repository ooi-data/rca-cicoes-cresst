"""Shared loading, QAQC, and annotation-masking logic for RCA data pipelines."""
import ast
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


def load_annotations(subsite: str, annotations_dir: str, nodes: set[str] | None = None) -> pd.DataFrame | None:
    """Load curated _llm annotations for a subsite. Returns None if file not found.

    Annotation masking matches on parameter name, and instruments on different
    nodes of the same mooring share parameter names — so filter to the nodes
    actually being processed (node-null annotations are subsite-wide and kept).
    """
    ann_path = Path(annotations_dir) / f"{subsite}_llm.csv"
    if not ann_path.exists():
        logger.warning(f"no annotation file at {ann_path}, skipping annotation masking")
        return None
    annotations = pd.read_csv(ann_path)
    annotations["beginDT"] = pd.to_datetime(annotations["beginDT"], format="ISO8601", utc=True)
    annotations["endDT"] = pd.to_datetime(annotations["endDT"], format="ISO8601", utc=True)
    if nodes is not None:
        annotations = annotations[annotations["node"].isin(nodes) | annotations["node"].isna()]
    logger.info(f"loaded {len(annotations)} curated annotations from {ann_path} (nodes={nodes})")
    return annotations


def mask_annotation_windows(
    ds: xr.Dataset,
    params: list[str],
    annotations: pd.DataFrame,
) -> xr.Dataset:
    """NaN out affected parameters in a raw time-series for each annotation window."""
    combined_mask = xr.zeros_like(ds.time, dtype=bool)

    for _, row in annotations.iterrows():
        affected = ast.literal_eval(row["parameters_affected"])

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
