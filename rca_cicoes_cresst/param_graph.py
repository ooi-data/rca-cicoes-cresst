"""Draw how OOI computes our product variables, from the preload database.

Walks each product variable's `parameterfunctionmap` in preload ParameterDefs.csv
upstream and writes a Mermaid flowchart of data products (DPIs) to
docs/parameter_dependencies.md. Calibration constants, raw L0 counts, and
surface-mooring / OPTAA branches are left out for readability.

Usage:
    python -m rca_cicoes_cresst.param_graph
"""
import json
from datetime import date

import pandas as pd

from rca_cicoes_cresst.common import REPO_ROOT
from rca_cicoes_cresst.fixed_instruments import DEFAULT_PARAMS as FIXED_PARAMS
from rca_cicoes_cresst.regrid_profiler import DEFAULT_PARAMS as PROFILER_PARAMS

PRELOAD = "https://raw.githubusercontent.com/oceanobservatories/preload-database/master/csv/ParameterDefs.csv"
OUT = REPO_ROOT / "docs" / "parameter_dependencies.md"
SKIP = ("_L0", "SRF", "SALSURF", "OPT", "PRESTMP")  # raw counts, surface moorings, OPTAA
PRODUCT_VARS = set(FIXED_PARAMS) | {v for vs in PROFILER_PARAMS.values() for v in vs}
NAME_OVERRIDES = {  # preload names that vary by instrument or don't say which sensor
    "DOXYGEN_L2": "Dissolved Oxygen - Temp Pressure Sal Corrected",
    "ABSTHRM_L1": "pH Sensor Thermistor Temperature",
    "CO2THRM_L1": "pCO2 Sensor Thermistor Temperature",
}


def dpi_names(p: pd.DataFrame) -> dict[str, str]:
    """DPI -> its most common preload displayname."""
    names = p.dropna(subset=["dataproductidentifier", "displayname"]).groupby("dataproductidentifier")["displayname"]
    return names.agg(lambda s: s.mode().iloc[0]).to_dict() | NAME_OVERRIDES


def dpi_edges(p: pd.DataFrame) -> tuple[set[tuple[str, str]], dict[str, set[str]]]:
    """(input DPI, output DPI) edges upstream of our product variables, and DPI -> product names."""
    by_dpi = p[p["dataproductidentifier"].notna()].groupby("dataproductidentifier")
    products: dict[str, set[str]] = {}
    edges, seen = set(), set()

    def walk(pd_id: str, out_dpi: str | None) -> None:
        if pd_id in seen:
            return
        seen.add(pd_id)
        row = p.loc[pd_id]
        dpi = row["dataproductidentifier"] if pd.notna(row["dataproductidentifier"]) else out_dpi
        if pd.isna(row["parameterfunctionmap"]):
            return
        for value in json.loads(row["parameterfunctionmap"]).values():
            for x in value if isinstance(value, list) else [value]:
                if not isinstance(x, str):  # literal constants
                    continue
                if x.startswith("dpi_"):
                    src = x.removeprefix("dpi_")
                    if dpi and src != dpi:
                        edges.add((src, dpi))
                    for upstream in by_dpi.get_group(src).index if src in by_dpi.groups else []:
                        walk(upstream, src)
                elif x in p.index:  # another parameter: follow it, keeping the current DPI
                    up = p.loc[x, "dataproductidentifier"]
                    if pd.notna(up) and dpi and up != dpi:
                        edges.add((up, dpi))
                    walk(x, up if pd.notna(up) else dpi)

    for pd_id, row in p[p["netcdf_name"].isin(PRODUCT_VARS)].iterrows():
        dpi = row["dataproductidentifier"]
        if pd.notna(dpi):
            products.setdefault(dpi, set()).add(row["netcdf_name"])
        walk(pd_id, dpi if pd.notna(dpi) else None)
    keep = lambda n: not any(s in n for s in SKIP)
    return {e for e in edges if keep(e[0]) and keep(e[1])}, products


def mermaid(edges: set[tuple[str, str]], products: dict[str, set[str]], names: dict[str, str]) -> str:
    keep = lambda n: not any(x in n for x in SKIP)
    nodes = sorted({n for e in edges for n in e} | {n for n in products if keep(n)})  # unlinked products too
    lines = ["flowchart LR"]
    for n in nodes:
        vars_ = "<br/>".join(f"<i>{v}</i>" for v in sorted(products.get(n, [])))
        lines.append(f'    {n.replace("-", "_")}["<b>{names.get(n, n)}</b><br/>{n}{"<br/>" + vars_ if vars_ else ""}"]')
    ordered = sorted(edges)
    for a, b in ordered:
        lines.append(f'    {a.replace("-", "_")} --> {b.replace("-", "_")}')
    # explicit text colors so boxes stay legible in light and dark themes
    lines.append("    classDef default fill:#e5e7eb,stroke:#4b5563,color:#111827")
    lines.append("    classDef product fill:#bfdbfe,stroke:#1d4ed8,color:#0b1f4d")
    lines.append("    classDef salinity fill:#fcd34d,stroke:#b45309,stroke-width:2px,color:#451a03")
    prod = [n.replace("-", "_") for n in nodes if n in products and n != "PRACSAL_L2"]
    if prod:
        lines.append(f"    class {','.join(prod)} product")
    lines.append("    class PRACSAL_L2 salinity")
    sal = [str(i) for i, (a, _) in enumerate(ordered) if a == "PRACSAL_L2"]
    if sal:
        lines.append(f"    linkStyle {','.join(sal)} stroke:#b45309,stroke-width:2px")
    return "\n".join(lines)


def main() -> None:
    p = pd.read_csv(PRELOAD)
    p = p[p["id"].astype(str).str.match(r"^PD\d+$")].set_index("id")
    edges, products = dpi_edges(p)
    names = dpi_names(p)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(f"""# Parameter dependencies

How OOI computes the variables in our products, drawn from the
[preload database](https://github.com/oceanobservatories/preload-database) `ParameterDefs.csv`
(`master` as of {date.today()}). Each box is an OOI data product (DPI), labelled with OOI's
display name and DPI code; arrows point from an input to the product computed from it. Blue boxes
are our products (our variable names in italics); grey boxes are intermediate inputs; unlinked
boxes depend only on their own sensor and calibration. Calibration constants, raw L0 counts, and
surface-mooring / OPTAA branches are omitted.

Regenerate: `python -m rca_cicoes_cresst.param_graph`

```mermaid
{mermaid(edges, products, names)}
```

## Salinity inheritance

Practical salinity (`PRACSAL_L2`, amber) is the main shared input, so a CTD conductivity
clog or drift also affects the products it points to on the same node. An arrow means "used in",
not "strongly affected by":

| Mask | Error per unit salinity | Why |
|------|-------------------------|-----|
| `sea_water_practical_salinity`, `sea_water_density` | density -0.79 kg/m3 | computed directly |
| `corrected_dissolved_oxygen`, `dissolved_oxygen` | ~0.7% | Garcia & Gordon salinity correction, umol/L -> umol/kg |
| `ph_total` (PHSENH, ISFET) | ~0.015 pH | chloride / sulfate / ionic-strength terms |
| `salinity_corrected_nitrate` | large | sea-salt (bromide) absorbance subtraction |

Not masked: temperature (Sea-Bird: fouling doesn't affect the thermistor), PHSEN
`ph_seawater` (~0.002 pH per unit salinity, below sensor uncertainty), pCO2, chlorophyll,
CDOM, backscatter. Exception: on pumped profiling CTDs, a pump failure may also affect
temperature response.

Clogs are usually abrupt multi-unit steps (annotation 6394: -2.45 for 10 weeks), not slow
drift. BGC-Argo flags O2/NO3/pH as suspect (3) when salinity is bad; our products keep good
data only, so they mask. `common.inherit_params` adds these at load time, so ledger rows only
need the base parameters.
""")
    print(f"wrote {OUT} ({len(edges)} edges)")


if __name__ == "__main__":
    main()
