#!/usr/bin/env python3
"""Package built products into a versioned release (docs/spec.md sections 7 and 10).

Copies product files from a build directory into <data-dir>/releases/vYYYY.MM/<product>/<level>.<ext>,
stamps each with its release, and writes manifest.json, build_report.json, annotations.csv, the
ledger and adjustments snapshots and RELEASE_NOTES.md. Updates catalog.json, moves CHANGELOG.md's
Unreleased section under the version, and tags the build commit. Builds nothing; upload with
`sync-cresst --release vYYYY.MM --apply`.

Usage:
    release-cresst v2026.11 --from data/build
    release-cresst v2026.10 --legacy-from data/cresst-one-easy-rca   # migrate the 2026-10-23 flat build
"""
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import click
import pandas as pd
import xarray as xr
import zarr
from loguru import logger

from rca_cicoes_cresst.common import (
    ADJUSTMENTS_FILE,
    ANNOTATIONS_DIR,
    DATA_DIR,
    LEDGER_FILE,
    QC_LEVELS,
    RAW_DIR,
    REPO_ROOT,
    SPEC_VERSION,
    fs,
    git_commit,
    iso_utc,
    read_ledger,
    read_sites,
)

DEFAULT_DATA_DIR = DATA_DIR / "cresst-one-easy-rca"
BUCKET = "rca-advanced-qaqc/cresst-one-easy-rca"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
VERSION = re.compile(r"^v\d{4}\.(0[1-9]|1[0-2])$")
LEVEL = "|".join(QC_LEVELS)
PRODUCT_FILE = re.compile(
    rf"^(?P<site>.+?)_(?P<kind>profiles|fixed)_\d{{8}}_\d{{8}}(?:_(?P<freq>[^_]+))?_(?P<level>{LEVEL})"
    rf"(?P<binned>_binned_\d+h)?\.(?P<ext>zarr|nc)$"
)
# the 2026-10-23 flat build: _qf49_HITL is hitl, _qf49_HITL_phadv is hitl plus advanced pH
LEGACY_FILE = re.compile(
    r"^(?P<site>.+?)_(?P<kind>profiles|fixed)_\d{8}_\d{8}(?:_(?P<freq>[^_]+))?_qf49_HITL(?P<phadv>_phadv)?"
    r"(?P<binned>_binned_\d+h)?\.(?P<ext>zarr|nc)$"
)
CHANGELOG_TEMPLATE = "## [Unreleased]\n\n### Highlights\n\n"


def find_products(build_dir: Path, legacy: bool = False) -> dict[tuple[str, str], dict]:
    """(product, level) -> product record with its files by extension."""
    products: dict[tuple[str, str], dict] = {}
    for path in sorted(build_dir.iterdir()):
        m = (LEGACY_FILE if legacy else PRODUCT_FILE).match(path.name)
        if not m:
            continue
        g = m.groupdict()
        level = ("advanced" if g["phadv"] else "hitl") if legacy else g["level"]
        if g["kind"] == "fixed":
            product, kind = f"{g['site']}_fixed_{g['freq']}", "fixed"
        else:
            product = f"{g['site']}_profiles{g['binned'] or ''}"
            kind = "profiles_binned" if g["binned"] else "profiles"
        rec = products.setdefault((product, level), {"product": product, "site": g["site"], "type": kind,
                                                     "level": level, "sources": {}})
        if g["ext"] in rec["sources"]:
            raise click.ClickException(f"two builds of {product} {level} .{g['ext']}: {rec['sources'][g['ext']].name}, {path.name}")
        rec["sources"][g["ext"]] = path
    return products


def open_product(path: Path) -> xr.Dataset:
    return xr.open_zarr(path) if path.suffix == ".zarr" else xr.open_dataset(path)


def stamp(src: Path, dst: Path, attrs: dict[str, str]) -> None:
    """Copy a product into the release and add the release attrs (zarr in place, netCDF rewritten)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".zarr":
        shutil.copytree(src, dst)
        zarr.open_group(dst, mode="r+").attrs.update(attrs)
    else:
        with xr.open_dataset(src) as ds:
            ds.attrs.update(attrs)
            ds.to_netcdf(dst)


def time_range(ds: xr.Dataset) -> tuple[str, str]:
    start, end = (ds["start_time"], ds["end_time"]) if "start_time" in ds.coords else (ds["time"], ds["time"])
    return (iso_utc(pd.Timestamp(start.min().values).tz_localize("UTC")),
            iso_utc(pd.Timestamp(end.max().values).tz_localize("UTC")))


def harvested_iso(value: str | None) -> str | None:
    return None if value in (None, "None") else iso_utc(pd.Timestamp(value).tz_convert("UTC"))


def manifest_entry(rec: dict, ds: xr.Dataset) -> dict:
    start, end = time_range(ds)
    return {
        "product": rec["product"], "site": rec["site"], "type": rec["type"], "level": rec["level"],
        "files": {ext: f"{rec['product']}/{rec['level']}.{ext}" for ext in sorted(rec["sources"])},
        "dims": {k: int(v) for k, v in ds.sizes.items()},
        "time_start": start, "time_end": end,
        "variables": list(ds.data_vars),
        "qc_steps": ds.attrs.get("qc_steps"),
        "hitl_ledger_sha1": ds.attrs.get("hitl_ledger_sha1"),
        "hitl_annotations_harvested": harvested_iso(ds.attrs.get("hitl_annotations_harvested")),
        "git_commit": ds.attrs.get("git_commit"),
        "spec_version": ds.attrs.get("spec_version"),
    }


def year_of(ds: xr.Dataset) -> xr.DataArray:
    return (ds["start_time"] if "start_time" in ds.coords else ds["time"]).dt.year.rename("year")


def build_report(products: dict[tuple[str, str], dict], previous: list[dict]) -> list[dict]:
    """R37: finite values per product, level, variable and year, and what each level removed from the
    next-lower level in the release, with the previous release's figures alongside."""
    prev = {(r["product"], r["level"], r["variable"], r["year"]): r for r in previous}
    rows = []
    for product in sorted({p for p, _ in products}):
        levels = sorted((lv for p, lv in products if p == product), key=QC_LEVELS.index)
        lower = None
        for level in levels:
            ds = open_product(products[(product, level)]["release_path"]).load()
            if lower is not None:
                ds, lower_ds = xr.align(ds, lower[1], join="inner")
            years = year_of(ds)
            for v in ds.data_vars:
                finite = ds[v].notnull()
                n = finite.groupby(years).sum(...)
                removed = ((lower_ds[v].notnull() & ~finite).groupby(years).sum(...)
                           if lower is not None and v in lower_ds else None)
                lower_n = lower_ds[v].notnull().groupby(years).sum(...) if removed is not None else None
                for year in n.year.values:
                    key = (product, level, v, int(year))
                    pct = (round(100 * float(removed.sel(year=year)) / float(lower_n.sel(year=year)), 2)
                           if removed is not None and float(lower_n.sel(year=year)) else None)
                    p = prev.get(key, {})
                    rows.append({"product": product, "level": level, "variable": v, "year": int(year),
                                 "n_values": int(n.sel(year=year)),
                                 "previous_level": lower[0] if removed is not None else None,
                                 "pct_removed": pct,
                                 "previous_release_n_values": p.get("n_values"),
                                 "previous_release_pct_removed": p.get("pct_removed")})
            lower = (level, ds)
    return rows


def annotations_table(subsites: list[str], ledger: pd.DataFrame, raw: dict[str, str]) -> pd.DataFrame:
    """R31: every harvested annotation for the release's subsites with its ledger decision."""
    cols = ["id", "subsite", "node", "sensor", "stream", "beginDT", "endDT", "qcFlag", "parameters", "annotation"]
    harvest = pd.concat([pd.read_csv(StringIO(raw[s]))[cols] for s in subsites if s in raw], ignore_index=True)
    for c in ["beginDT", "endDT"]:
        harvest[c] = pd.to_datetime(harvest[c], format="ISO8601", utc=True).map(iso_utc)
    decided = ledger[["id", "decision", "status", "parameters_affected", "parameters_source", "rationale",
                      "decided_by", "reviewed_at"]]
    return harvest.merge(decided, on="id", how="left").sort_values(["subsite", "beginDT", "id"])


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=True).stdout


def legacy_commit(ledger_sha1: str) -> str:
    """The commit whose ledger.csv has this fingerprint (products record the first 10 hex of its SHA-1)."""
    for h in git("log", "--format=%H", "--", f"annotations/{LEDGER_FILE}").split():
        if hashlib.sha1(git_bytes(h, f"annotations/{LEDGER_FILE}")).hexdigest()[:10] == ledger_sha1:
            return h
    raise click.ClickException(f"no commit has a ledger with sha1 {ledger_sha1}")


def git_bytes(commit: str, path: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{commit}:{path}"], capture_output=True, check=True).stdout


def unreleased(text: str) -> str:
    """Body of the changelog's Unreleased section; R35 requires a Highlights entry."""
    m = re.search(r"^## \[Unreleased\]\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    body = m.group(1).strip() if m else ""
    highlights = re.search(r"^### Highlights\n(.*?)(?=^### |\Z)", body, re.M | re.S)
    if not highlights or not re.search(r"^- \S", highlights.group(1), re.M):
        raise click.ClickException("CHANGELOG.md needs an Unreleased section with at least one Highlights entry (R35)")
    return body


def release_changelog(text: str, version: str, date: str) -> str:
    entry = f"{CHANGELOG_TEMPLATE}## [{version}] - {date}\n\n{unreleased(text)}\n\n"
    return re.sub(r"^## \[Unreleased\]\n.*?(?=^## \[|\Z)", lambda _: entry, text, count=1, flags=re.M | re.S)


def section(body: str, name: str) -> str:
    m = re.search(rf"^### {name}\n(.*?)(?=^### |\Z)", body, re.M | re.S)
    return m.group(1).strip() if m else ""


def read_previous(data_dir: Path, release: str | None, name: str) -> str | None:
    """A file from a previous release: the local copy, else the bucket's."""
    if release is None:
        return None
    local = data_dir / "releases" / release / name
    if local.exists():
        return local.read_text()
    remote = f"{BUCKET}/releases/{release}/{name}"
    return fs.cat(remote).decode() if fs.exists(remote) else None


def md_cell(value) -> str:
    return "" if pd.isna(value) else str(value).replace("|", "/").replace("\n", " ")


def md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "None.\n"
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(md_cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines) + "\n"


def ledger_diff(prev: pd.DataFrame | None, cur: pd.DataFrame) -> str:
    if prev is None:
        return "No previous release to compare with.\n"
    keys = ["decision", "status", "parameters_affected", "rationale"]
    m = cur.merge(prev[["id"] + keys], on="id", how="left", suffixes=("", "_prev"), indicator=True)
    added = m[m["_merge"] == "left_only"]
    both = m[m["_merge"] == "both"]
    changed = both[(both[keys].fillna("").values != both[[f"{k}_prev" for k in keys]].fillna("").values).any(axis=1)]
    removed = prev[~prev["id"].isin(cur["id"])]
    counts = pd.DataFrame({"decided_by": sorted(set(added["decided_by"]) | set(changed["decided_by"]))})
    counts["added"] = [int((added["decided_by"] == d).sum()) for d in counts["decided_by"]]
    counts["changed"] = [int((changed["decided_by"] == d).sum()) for d in counts["decided_by"]]
    table = pd.concat([added.assign(change="added"), changed.assign(change="changed")])
    table = table.assign(previous=table["decision_prev"].fillna("") + " " + table["status_prev"].fillna(""))
    cols = ["id", "subsite", "change", "previous", "decision", "status", "parameters_affected", "decided_by", "rationale"]
    return (f"{len(added)} added, {len(changed)} changed, {len(removed)} removed.\n\n" + md_table(counts)
            + "\n" + md_table(table[cols].sort_values(["subsite", "id"])))


def adjustments_diff(prev: pd.DataFrame | None, cur: pd.DataFrame) -> str:
    if prev is None:
        return "No previous release to compare with.\n"
    m = cur.astype(str).merge(prev.astype(str), how="outer", indicator=True)
    out = m[m["_merge"] != "both"].assign(change=lambda d: d["_merge"].map({"left_only": "now", "right_only": "before"}))
    return md_table(out[["change"] + list(cur.columns)].sort_values(["id", "change"]))


def extents_diff(prev: dict | None, cur: dict) -> str:
    if prev is None:
        return "No previous release to compare with.\n"
    old = {(p["product"], p["level"]): p for p in prev["products"]}
    new = {(p["product"], p["level"]): p for p in cur["products"]}
    rows = []
    for key in sorted(old.keys() | new.keys()):
        o, n = old.get(key), new.get(key)
        if o is None or n is None:
            rows.append((*key, "added" if o is None else "removed", "", ""))
        elif (o["time_start"], o["time_end"]) != (n["time_start"], n["time_end"]):
            rows.append((*key, "time coverage", f"{o['time_start']} to {o['time_end']}", f"{n['time_start']} to {n['time_end']}"))
    return md_table(pd.DataFrame(rows, columns=["product", "level", "change", "before", "now"]))


def report_diff(rows: list[dict], threshold: float = 5.0) -> str:
    df = pd.DataFrame(rows)
    if df.empty or df["previous_release_pct_removed"].isna().all():
        return "No comparable figures in the previous release.\n"
    df["change_points"] = (df["pct_removed"] - df["previous_release_pct_removed"]).round(2)
    big = df[df["change_points"].abs() >= threshold].sort_values("change_points", key=abs, ascending=False)
    return (f"Product, level, variable and year where the share removed changed by {threshold:g} points or more.\n\n"
            + md_table(big[["product", "level", "variable", "year", "previous_level", "previous_release_pct_removed",
                            "pct_removed", "change_points"]]))


def release_notes(manifest: dict, previous: str | None, body: str, diffs: dict[str, str]) -> str:
    coverage = pd.DataFrame([(p["product"], p["level"], f"{p['time_start'][:10]} to {p['time_end'][:10]}")
                             for p in manifest["products"]], columns=["product", "level", "time coverage"])
    others = re.sub(r"^### Highlights\n.*?(?=^### |\Z)", "", body, flags=re.M | re.S).strip()
    return f"""# RCA-CRESST release {manifest['release']}

Released {manifest['date']}. Specification version {manifest['spec_version']}, built from commit
`{manifest['git_commit']}`. Previous release: {previous or 'none'}.

## Highlights

{section(body, 'Highlights') or 'None.'}

## Changes

{others or 'None.'}

## Products

{md_table(coverage)}
## Annotation decisions since {previous or 'the start'}

{diffs['ledger']}
## Adjustments since {previous or 'the start'}

{diffs['adjustments']}
## Products and time coverage since {previous or 'the start'}

{diffs['extents']}
## Masking since {previous or 'the start'}

{diffs['report']}"""


@click.command()
@click.argument("version")
@click.option("--from", "build_dir", type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Directory of products built with the current naming (<site>_..._<level>.<ext>).")
@click.option("--legacy-from", "legacy_dir", type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Migrate the 2026-10-23 flat build (_qf49_HITL, _qf49_HITL_phadv) instead.")
@click.option("--data-dir", default=DEFAULT_DATA_DIR, show_default=True, type=click.Path(path_type=Path),
              help="Local mirror of the bucket prefix; the release goes to <data-dir>/releases/<version>.")
@click.option("--changelog", default=CHANGELOG, show_default=True, type=click.Path(exists=True, path_type=Path))
@click.option("--allow-dirty", is_flag=True, help="Package products built from uncommitted code (no git tag).")
@click.option("--no-tag", is_flag=True, help="Don't create the git tag.")
def main(version: str, build_dir: Path | None, legacy_dir: Path | None, data_dir: Path, changelog: Path,
         allow_dirty: bool, no_tag: bool) -> None:
    """Package built products as release VERSION (vYYYY.MM)."""
    if not VERSION.match(version):
        raise click.UsageError("VERSION must be vYYYY.MM, e.g. v2026.11")
    if (build_dir is None) == (legacy_dir is None):
        raise click.UsageError("Give exactly one of --from or --legacy-from.")
    legacy = legacy_dir is not None
    release_dir = data_dir / "releases" / version
    catalog_path = data_dir / "catalog.json"
    catalog = (json.loads(catalog_path.read_text()) if catalog_path.exists()
               else json.loads(fs.cat(f"{BUCKET}/catalog.json")) if fs.exists(f"{BUCKET}/catalog.json")
               else {"latest": None, "releases": []})
    if release_dir.exists() or version in {r["id"] for r in catalog["releases"]} or fs.exists(f"{BUCKET}/releases/{version}"):
        raise click.ClickException(f"{version} already exists; releases are never changed (R28)")
    previous = max((r["id"] for r in catalog["releases"] if r["id"] < version), default=None)

    products = find_products(legacy_dir or build_dir, legacy)
    if not products:
        raise click.ClickException(f"no product files in {legacy_dir or build_dir}")
    opened = {key: open_product(rec["sources"].get("zarr") or rec["sources"]["nc"]) for key, rec in products.items()}
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if legacy:
        shas = {ds.attrs["hitl_ledger_sha1"] for ds in opened.values()}
        if len(shas) != 1:
            raise click.ClickException(f"legacy products used different ledgers: {shas}")
        commit, spec_version, changelog_text = legacy_commit(shas.pop()), "0.1", None
        date = git("show", "-s", "--format=%cs", commit).strip()  # the build ran from this commit that day
        ledger = pd.read_csv(StringIO(git_bytes(commit, f"annotations/{LEDGER_FILE}").decode()))
        adjustments_text = git_bytes(commit, "config/adjustments.csv").decode()
        raw = {}
        for s in read_sites()["refdes"].str[:8].unique():
            try:
                raw[s] = git_bytes(commit, f"annotations/{RAW_DIR}/{s}.csv").decode()
            except subprocess.CalledProcessError:
                pass
    else:
        commit, spec_version = git_commit(), SPEC_VERSION
        changelog_text = changelog.read_text()
        body = unreleased(changelog_text)
        built = {ds.attrs.get("git_commit") for ds in opened.values()}
        if not allow_dirty and (commit.endswith("-dirty") or built != {commit}):
            raise click.ClickException(f"products built from {sorted(map(str, built))}, HEAD is {commit}: commit and "
                                       "rebuild, or pass --allow-dirty")
        if not (no_tag or allow_dirty) and git("tag", "--list", version).strip():
            raise click.ClickException(f"git tag {version} already exists")
        for (product, level), ds in opened.items():
            if ds.attrs.get("qc_level") != level:
                raise click.ClickException(f"{product} {level}: file says qc_level={ds.attrs.get('qc_level')}")
        ledger = read_ledger()
        adjustments_text = ADJUSTMENTS_FILE.read_text()
        raw = {p.stem: p.read_text() for p in (Path(ANNOTATIONS_DIR) / RAW_DIR).glob("*.csv") if p.stem.isupper()}

    staging = release_dir.with_name(f"{version}.partial")
    if staging.exists():
        shutil.rmtree(staging)
    attrs = {"release": version, "spec_version": spec_version}
    for (product, level), rec in sorted(products.items()):
        for ext, src in sorted(rec["sources"].items()):
            dst = staging / product / f"{level}.{ext}"
            logger.info(f"{src.name} -> {dst.relative_to(data_dir)}")
            stamp(src, dst, attrs)
        rec["release_path"] = staging / product / f"{level}.{'zarr' if 'zarr' in rec['sources'] else 'nc'}"

    manifest = {"release": version, "date": date, "spec_version": spec_version, "git_commit": commit,
                "base_url": f"s3://{BUCKET}/releases/{version}/",
                "products": [manifest_entry(rec, opened[key]) for key, rec in sorted(products.items())]}
    for entry in manifest["products"]:
        entry["spec_version"] = entry["spec_version"] or spec_version
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    (staging / LEDGER_FILE).write_text(ledger.to_csv(index=False))
    (staging / "adjustments.csv").write_text(adjustments_text)
    sites = {rec["site"] for rec in products.values()}
    subsites = sorted(set(read_sites().query("site in @sites")["refdes"].str[:8]) & set(raw))
    annotations_table(subsites, ledger, raw).to_csv(staging / "annotations.csv", index=False)

    logger.info("computing build report")
    prev_report = read_previous(data_dir, previous, "build_report.json")
    rows = build_report(products, json.loads(prev_report)["rows"] if prev_report else [])
    (staging / "build_report.json").write_text(json.dumps({"release": version, "previous_release": previous,
                                                           "rows": rows}, indent=1) + "\n")

    prev_ledger = read_previous(data_dir, previous, LEDGER_FILE)
    prev_adj = read_previous(data_dir, previous, "adjustments.csv")
    prev_manifest = read_previous(data_dir, previous, "manifest.json")
    diffs = {
        "ledger": ledger_diff(pd.read_csv(StringIO(prev_ledger)) if prev_ledger else None, ledger),
        "adjustments": adjustments_diff(pd.read_csv(StringIO(prev_adj)) if prev_adj else None,
                                        pd.read_csv(StringIO(adjustments_text))),
        "extents": extents_diff(json.loads(prev_manifest) if prev_manifest else None, manifest),
        "report": report_diff(rows),
    }
    body = ("### Highlights\n\n- Migrated the 2026-10-23 build (spec 0.1) into the versioned layout.\n"
            if legacy else body)
    (staging / "RELEASE_NOTES.md").write_text(release_notes(manifest, previous, body, diffs))
    staging.rename(release_dir)

    catalog["releases"] = sorted([*catalog["releases"], {"id": version, "date": date, "git_commit": commit,
                                                         "spec_version": spec_version}],
                                 key=lambda r: r["id"], reverse=True)
    catalog["latest"] = catalog["releases"][0]["id"]
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    if changelog_text is not None:
        changelog.write_text(release_changelog(changelog_text, version, date))
    shutil.copy(changelog, data_dir / "CHANGELOG.md")

    if legacy or no_tag or allow_dirty:
        logger.info("no git tag created")
    else:
        git("tag", "-a", version, "-m", f"RCA-CRESST release {version}", commit)
        logger.info(f"tagged {commit[:12]} as {version}; push with: git push origin {version}")
    logger.info(f"{release_dir} ready: {len(products)} product levels. Commit CHANGELOG.md, then upload with "
                f"sync-cresst --bucket {BUCKET} --release {version} --apply")


if __name__ == "__main__":
    main()
