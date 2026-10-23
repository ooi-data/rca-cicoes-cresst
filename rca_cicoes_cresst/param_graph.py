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


def mermaid(edges: set[tuple[str, str]], products: dict[str, set[str]]) -> str:
    keep = lambda n: not any(x in n for x in SKIP)
    nodes = sorted({n for e in edges for n in e} | {n for n in products if keep(n)})  # unlinked products too
    lines = ["flowchart LR"]
    for n in nodes:
        names = "<br/>".join(f"<i>{v}</i>" for v in sorted(products.get(n, [])))
        lines.append(f'    {n.replace("-", "_")}["<b>{n}</b>{"<br/>" + names if names else ""}"]')
    ordered = sorted(edges)
    for a, b in ordered:
        lines.append(f'    {a.replace("-", "_")} --> {b.replace("-", "_")}')
    lines.append("    classDef product fill:#dbeafe,stroke:#1d4ed8")
    lines.append("    classDef salinity fill:#fde68a,stroke:#b45309,stroke-width:2px")
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
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(f"""# Parameter dependencies

How OOI computes the variables in our products, drawn from the
[preload database](https://github.com/oceanobservatories/preload-database) `ParameterDefs.csv`
(`master` as of {date.today()}). Each box is an OOI data product (DPI); arrows point from an
input to the product computed from it. Blue boxes feed our products (our variable names in
italics). Practical salinity (`PRACSAL_L2`, amber) is the main shared input: a bad salinity
also corrupts every product it points to, which is what `common.inherit_params` handles. An arrow
means "used in", not "strongly affected by": see the sensitivity table in `CLAUDE.md` (e.g. PHSEN
`ph_seawater` changes only ~0.002 pH per unit salinity). Unlinked boxes depend only on their own
sensor and calibration.
Calibration constants, raw L0 counts, and surface-mooring / OPTAA branches are omitted.

Regenerate: `python -m rca_cicoes_cresst.param_graph`

```mermaid
{mermaid(edges, products)}
```
""")
    print(f"wrote {OUT} ({len(edges)} edges)")


if __name__ == "__main__":
    main()
