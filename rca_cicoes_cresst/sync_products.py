#!/usr/bin/env python3
"""Resync local data products to the rca-advanced-qaqc/cresst S3 prefix.

Products are matched by *identity* — the filename with its <start>_<end> date
pair stripped — so a local file supersedes its bucket counterpart across date
ranges while keeping QAQC variants (_HITL, _phadv, _binned_Nh, ...) distinct.

Local supersedes the bucket when its end date is newer, or (same end date) its
size differs (a same-range re-QAQC). On upload, older-end-date copies of the
same identity are removed. Nothing else in the bucket is touched.

Dry-run by default; pass --apply to write. Writing needs AWS credentials.
"""
import re
from pathlib import Path

import click
import s3fs
from loguru import logger

from rca_cicoes_cresst.common import fs as anon_fs  # anonymous, read-only

BUCKET = "rca-advanced-qaqc/cresst"
DATE_PAIR = re.compile(r"\d{8}_\d{8}")


def identity(basename: str) -> tuple[str, str] | None:
    """(identity, end_date) for a product filename, or None if it has no date range."""
    m = DATE_PAIR.search(basename)
    if not m:
        return None
    return DATE_PAIR.sub("<DATES>", basename, count=1), m.group()[9:]


def local_products(data_dir: Path) -> dict[str, list[tuple[Path, str, int]]]:
    """identity -> [(path, end_date, size_bytes)], scanning data/ and data/binned/."""
    out: dict[str, list[tuple[Path, str, int]]] = {}
    for d in (data_dir, data_dir / "binned"):
        if not d.exists():
            continue
        for p in d.iterdir():
            if not (p.name.endswith(".zarr") or p.name.endswith(".nc")):
                continue
            ident = identity(p.name)
            if ident is None:
                logger.warning(f"no date range in {p.name}, skipping")
                continue
            size = (p.stat().st_size if p.is_file()
                    else sum(f.stat().st_size for f in p.rglob("*") if f.is_file()))
            out.setdefault(ident[0], []).append((p, ident[1], size))
    return out


def bucket_products() -> dict[str, list[tuple[str, str]]]:
    """identity -> [(bucket_path, end_date)] under the cresst prefix."""
    out: dict[str, list[tuple[str, str]]] = {}
    for path in anon_fs.ls(BUCKET):
        name = path.rsplit("/", 1)[-1]
        if not name:
            continue
        ident = identity(name)
        if ident is None:
            continue
        out.setdefault(ident[0], []).append((path, ident[1]))
    return out


@click.command()
@click.option("--data-dir", default="data", show_default=True, help="Local product directory.")
@click.option("--apply", "apply_", is_flag=True, help="Actually upload/delete (default is dry-run).")
@click.option("--delete-remote-only-data", "delete_remote_only", is_flag=True,
              help="Also delete bucket files that have no local counterpart.")
def main(data_dir: str, apply_: bool, delete_remote_only: bool) -> None:
    """Sync local data products up to rca-advanced-qaqc/cresst."""
    local = local_products(Path(data_dir))
    bucket = bucket_products()
    write_fs = s3fs.S3FileSystem() if apply_ else None

    uploads: list[tuple[Path, str]] = []   # (local_path, bucket_path)
    deletes: list[str] = []

    for ident, versions in sorted(local.items()):
        path, end, size = max(versions, key=lambda v: v[1])  # newest local of this identity
        bkt = bucket.get(ident, [])
        bkt_end = max((e for _, e in bkt), default=None)
        target = f"{BUCKET}/{path.name}"

        if bkt_end is None:
            uploads.append((path, target)); logger.info(f"UPLOAD  {path.name}  (new)")
        elif end > bkt_end:
            uploads.append((path, target)); logger.info(f"UPLOAD  {path.name}  (end {end} > bucket {bkt_end})")
        elif end < bkt_end:
            logger.warning(f"SKIP    {path.name}  (bucket end {bkt_end} is NEWER — not downgrading)")
        else:  # same end date — compare size
            bsize = anon_fs.du(f"{BUCKET}/{path.name}")
            if bsize != size:
                uploads.append((path, target)); logger.info(f"UPLOAD  {path.name}  (changed: {size:,}B vs bucket {bsize:,}B)")
            else:
                logger.info(f"SKIP    {path.name}  (in sync)")

        # remove older-end-date copies of this identity once local is going up
        if uploads and uploads[-1][0] is path:
            for bpath, bend in bkt:
                if bend < end:
                    deletes.append(bpath); logger.info(f"  SUPERSEDE-DELETE {bpath.rsplit('/',1)[-1]}  (end {bend})")

    for ident in sorted(set(bucket) - set(local)):
        for bpath, _ in bucket[ident]:
            name = bpath.rsplit("/", 1)[-1]
            if delete_remote_only:
                deletes.append(bpath); logger.info(f"DELETE-REMOTE-ONLY {name}  (no local counterpart)")
            else:
                logger.info(f"BUCKET-ONLY {name}  (no local counterpart — leaving)")

    logger.info(f"\nplan: {len(uploads)} upload(s), {len(deletes)} delete(s)")
    if not apply_:
        logger.info("dry-run; re-run with --apply to execute")
        return

    for path, target in uploads:
        if write_fs.exists(target):
            write_fs.rm(target, recursive=True)  # clean overwrite (esp. zarr chunks)
        logger.info(f"uploading {path.name}")
        write_fs.put(str(path), target, recursive=path.is_dir())
    for bpath in deletes:
        logger.info(f"deleting {bpath.rsplit('/',1)[-1]}")
        write_fs.rm(bpath, recursive=True)
    logger.info("done")


if __name__ == "__main__":
    main()
