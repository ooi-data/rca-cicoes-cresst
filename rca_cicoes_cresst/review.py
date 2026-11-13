#!/usr/bin/env python3
"""Streamlit app to review and approve decisions in annotations/ledger.csv.

Shows each decision next to its harvested annotation, flagged rows first. Approving or editing a row
marks it reviewed_by=human and clears its flag; decided_by keeps the initial assessor. Commit the
ledger through a PR as usual. Decision rules are in CLAUDE.md.

Usage:
    review-annotations
"""
import ast
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from rca_cicoes_cresst.common import ANNOTATIONS_DIR, LEDGER_FILE, PARAM_TO_INSTRUMENT, RAW_DIR, read_preload
from rca_cicoes_cresst.curate import LEDGER_COLUMNS, official_params
from rca_cicoes_cresst.harvest_annotations import SITES

LEDGER = Path(ANNOTATIONS_DIR) / LEDGER_FILE
DECISIONS = ["mask", "ignore", "superseded"]
EDITABLE = ["decision", "parameters_affected", "parameters_source", "rationale"]
SHOWN = ["approve", "id", "flag", "subsite", "sensor", "window", "qcFlag", "annotation", "ooi_parameters",
         *EDITABLE, "decided_by", "status", "reviewed_by", "reviewed_at"]
APPROVE_ALL_MAX = 100  # "Approve all shown" is for a filtered handful, not a bulk sign-off


@st.cache_data(show_spinner=False)
def load_raw(mtime: float) -> pd.DataFrame:
    """Harvested annotations with the fields a reviewer needs; mtime of the harvest manifest keys the cache."""
    raw = pd.concat([pd.read_csv(Path(ANNOTATIONS_DIR) / RAW_DIR / f"{s}.csv") for s in SITES.values()])
    preload = read_preload()
    netcdf_names = dict(zip(preload.index.str[2:].astype(int), preload["netcdf_name"]))
    return pd.DataFrame({
        "id": raw["id"].astype(str),
        "subsite": raw["subsite"],
        "sensor": (raw["node"].fillna("*") + "-" + raw["sensor"].fillna("*")).where(raw["node"].notna(), "*"),
        "window": raw["beginDT"].str[:16] + " → " + raw["endDT"].str[:16].fillna("open"),
        "qcFlag": raw["qcFlag"].fillna(""),
        "annotation": raw["annotation"],
        "ooi_parameters": raw["parameters"].map(lambda p: ", ".join(sorted(official_params(p, netcdf_names)))),
    })


def bad_params(value: str) -> str | None:
    """Why a parameters_affected cell is invalid, or None."""
    if not value:
        return None
    try:
        names = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return f"not a list: {value}"
    unknown = set(names) - set(PARAM_TO_INSTRUMENT)
    return f"unknown parameters: {sorted(unknown)}" if unknown else None


def save(ledger: pd.DataFrame, view: pd.DataFrame, edited: pd.DataFrame) -> str:
    """Write edited and approved rows: both become reviewed_by=human with today's reviewed_at and no flag;
    approved rows also get status=approved."""
    edited = edited.fillna("")
    changed = edited[EDITABLE].ne(view[EDITABLE]).any(axis=1)
    rows = edited[changed | edited["approve"]]
    for _, r in rows.iterrows():
        if problem := bad_params(r["parameters_affected"]):
            raise ValueError(f"id {r['id']}: {problem}")
        if r["decision"] == "mask" and not r["parameters_affected"]:
            raise ValueError(f"id {r['id']}: mask needs parameters_affected")
    ledger = ledger.set_index("id")
    ids = rows["id"]
    ledger.loc[ids, EDITABLE] = rows.set_index("id")[EDITABLE]
    ledger.loc[ids, ["reviewed_by", "reviewed_at", "flag"]] = ["human", date.today().isoformat(), ""]
    approved = rows.loc[rows["approve"], "id"]
    ledger.loc[approved, "status"] = "approved"
    ledger = ledger.reset_index()
    ledger = ledger.assign(_id=ledger["id"].astype(int)).sort_values(["subsite", "_id"])
    ledger[LEDGER_COLUMNS].to_csv(LEDGER, index=False)
    return f"Saved {len(rows)} rows ({len(approved)} approved, {int(changed.sum())} edited)."


def app() -> None:
    st.set_page_config(page_title="Annotation review", page_icon=":material/fact_check:", layout="wide")
    ledger = pd.read_csv(LEDGER, dtype=str, keep_default_na=False)
    df = ledger.merge(load_raw((Path(ANNOTATIONS_DIR) / RAW_DIR / "harvest_manifest.csv").stat().st_mtime),
                      on=["id", "subsite"], how="left")

    with st.sidebar:
        unreviewed = st.toggle("Not yet reviewed by a person", value=True)
        flagged = st.toggle("Flagged only", help="Borderline judgements; they also sort to the top.")
        status = st.segmented_control("Status", ["proposed", "approved", "all"], default="all", required=True)
        subsites = st.multiselect("Subsite", sorted(df["subsite"].unique()))
        decisions = st.multiselect("Decision", DECISIONS)
        flags = st.multiselect("qcFlag", sorted(df["qcFlag"].dropna().unique()))
        deciders = st.multiselect("Decided by", sorted(df["decided_by"].unique()))
        search = st.text_input("Search annotation text")

    keep = pd.Series(True, index=df.index)
    if status != "all":
        keep &= df["status"] == status
    for col, chosen in (("subsite", subsites), ("decision", decisions), ("qcFlag", flags), ("decided_by", deciders)):
        if chosen:
            keep &= df[col].isin(chosen)
    if search:
        keep &= df["annotation"].str.contains(search, case=False, na=False)
    if unreviewed:
        keep &= df["reviewed_by"] != "human"
    if flagged:
        keep &= df["flag"] != ""
    view = df[keep]
    view = view.assign(approve=False, _unflagged=view["flag"] == "", _id=view["id"].astype(int))
    view = view.sort_values(["_unflagged", "subsite", "_id"])[SHOWN].reset_index(drop=True)

    st.title("Annotation review")
    st.caption(f"{(df['reviewed_by'] != 'human').sum()} of {len(df)} decisions in `annotations/ledger.csv` not yet "
               f"reviewed by a person, {(df['flag'] != '').sum()} flagged, {(df['status'] == 'proposed').sum()} proposed. "
               "Edit a decision or tick **approve**, then save; both mark the row `reviewed_by=human` and clear its flag. "
               "Commit the ledger through a PR. Decision rules are in `CLAUDE.md`.")
    if msg := st.session_state.pop("saved", None):
        st.success(msg, icon=":material/check_circle:")

    edited = st.data_editor(
        view, hide_index=True, width="stretch", height=560,
        disabled=[c for c in SHOWN if c not in EDITABLE + ["approve"]],
        column_config={
            "approve": st.column_config.CheckboxColumn("approve", pinned=True),
            "id": st.column_config.TextColumn("id", pinned=True),
            "annotation": st.column_config.TextColumn("annotation", width="large"),
            "ooi_parameters": st.column_config.TextColumn("OOI parameters", help="Official parameters; they take precedence"),
            "flag": st.column_config.TextColumn("flag", width="medium", help="Borderline judgement worth a person's look"),
            "decision": st.column_config.SelectboxColumn("decision", options=DECISIONS, required=True),
            "parameters_affected": st.column_config.TextColumn(
                "parameters_affected", help="Python list of product variables, e.g. ['ph_seawater']; base CTD parameters only"),
            "parameters_source": st.column_config.SelectboxColumn(
                "parameters_source", options=["", "official", "llm", "official+inherited", "llm+inherited"]),
            "rationale": st.column_config.TextColumn("rationale", width="medium"),
        },
    )

    with st.container(horizontal=True, vertical_alignment="center"):
        save_clicked = st.button("Save", type="primary", icon=":material/save:")
        all_clicked = st.button("Approve all shown", icon=":material/done_all:", disabled=len(view) > APPROVE_ALL_MAX,
                                help=f"Save edits and approve every row in the table (up to {APPROVE_ALL_MAX})")
        st.space("stretch")
        st.caption(f"{len(view)} rows shown")
    if save_clicked or all_clicked:
        try:
            st.session_state["saved"] = save(ledger, view, edited.assign(approve=True) if all_clicked else edited)
            st.rerun()
        except ValueError as e:
            st.error(str(e), icon=":material/error:")

    if len(view):
        pick = st.selectbox("Full annotation", view["id"], format_func=lambda i: f"{i}  ·  {view.set_index('id').at[i, 'sensor']}")
        row = view.set_index("id").loc[pick]
        with st.container(border=True):
            st.markdown(f"**{row['subsite']} {row['sensor']}**  ·  {row['window']}  ·  qcFlag `{row['qcFlag'] or 'null'}`  ·  "
                        f"OOI parameters: {row['ooi_parameters'] or 'none (whole stream)'}")
            st.write(row["annotation"])
            st.markdown(f"**{row['decision']}** {row['parameters_affected']}  ·  {row['rationale']}  ·  _{row['decided_by']}_")
            if row["flag"]:
                st.warning(row["flag"], icon=":material/flag:")


def main() -> None:
    """Launch the app with streamlit run."""
    from streamlit.web import cli
    sys.argv = ["streamlit", "run", __file__]
    sys.exit(cli.main())


if __name__ == "__main__":
    app()
