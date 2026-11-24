#!/usr/bin/env python3
"""Download the top-view soccer subset of the TeamTrack dataset from Kaggle.

Single-use script (2026-11-20). Run it in the `Flocker` conda environment.

TeamTrack (Scott et al., CVPR Workshops 2024): https://www.kaggle.com/datasets/atomscott/teamtrack
Licence: MIT, as stated on the Kaggle page and returned by the Kaggle API (dataset metadata).
Its 60 top-view clips are the same files as SoccerTrack's `top_view/videos/`, which Kaggle lists
under LGPL-3.0; TeamTrack's MIT copy is used for that reason.

Files land in videos/raw/teamtrack_soccer_top/, keeping the dataset's train/val/test layout.
Re-running skips files already downloaded. Credentials come from the Kaggle CLI's usual sources
(KAGGLE_API_TOKEN or ~/.kaggle/kaggle.json).

Usage:
    python util/ad-hoc/2026-11-20_fetch_teamtrack_soccer_top.py --list-only
    python util/ad-hoc/2026-11-20_fetch_teamtrack_soccer_top.py
"""

import argparse
import hashlib
import json
import pathlib
import sys

from kaggle.api.kaggle_api_extended import KaggleApi

DATASET = "atomscott/teamtrack"
MARK = "soccer_top/"
DEST = pathlib.Path(__file__).resolve().parents[2] / "videos" / "raw" / "teamtrack_soccer_top"


def list_files(api):
    out, token = [], None
    while True:
        resp = api.dataset_list_files(DATASET, page_token=token, page_size=200)
        out.extend(getattr(resp, "dataset_files", None) or getattr(resp, "files", None) or [])
        token = getattr(resp, "next_page_token", None) or getattr(resp, "nextPageToken", None)
        if not token:
            return out


def name_of(f):
    return getattr(f, "name", None) or getattr(f, "path", None)


def size_of(f):
    return getattr(f, "total_bytes", None) or getattr(f, "totalBytes", None) or getattr(f, "size", None)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list-only", action="store_true", help="list the subset and exit")
    args = ap.parse_args()

    api = KaggleApi()
    api.authenticate()
    everything = list_files(api)
    subset = [f for f in everything if MARK in (name_of(f) or "")]
    total = sum(size_of(f) or 0 for f in subset)
    print(f"{DATASET}: {len(everything)} files in total; {len(subset)} under '{MARK}', {total / 1e9:.2f} GB")
    kinds = {}
    for f in subset:
        rel = name_of(f).split(MARK, 1)[1]
        key = (rel.split("/")[0], pathlib.Path(rel).suffix)
        kinds[key] = kinds.get(key, 0) + 1
    for (split, ext), n in sorted(kinds.items()):
        print(f"  {split:<6} {ext:<5} {n}")
    if args.list_only:
        print("examples:", [name_of(f) for f in subset[:3]])
        return 0

    DEST.mkdir(parents=True, exist_ok=True)
    staging = DEST / ".staging"
    problems = []
    for i, f in enumerate(subset, 1):
        name = name_of(f)
        # Keep the archive's two trees apart: "teamtrack/" (videos + CSV annotations) and
        # "teamtrack-mot/" (MOT-format gt.txt + seqinfo.ini). Drop only the duplicated top folder.
        rel = pathlib.Path(name.split("/", 1)[1])
        final = DEST / rel
        want = size_of(f)
        # dataset_download_file() writes to <path>/<full dataset-relative name>, not to
        # <path>/<file name>. So download into a staging folder and move the file into place.
        # The first run (2026-11-20) passed the final folder as <path>; move what it left there too.
        for landed in (DEST / rel.parent / name, staging / name):
            if landed.exists() and not final.exists():
                final.parent.mkdir(parents=True, exist_ok=True)
                landed.rename(final)
        if not final.exists():
            api.dataset_download_file(DATASET, name, path=str(staging), quiet=True, unzip=True)
            if (staging / name).exists():
                final.parent.mkdir(parents=True, exist_ok=True)
                (staging / name).rename(final)
        if not final.exists():
            problems.append(f"missing after download: {rel}")
        elif want and final.stat().st_size != want:
            problems.append(f"size mismatch: {rel} has {final.stat().st_size} bytes, Kaggle lists {want}")
        if i % 20 == 0 or i == len(subset):
            print(f"  {i}/{len(subset)} in place", flush=True)
    # Remove the folders the moves left empty (the staging tree and the first run's doubled paths).
    for d in sorted((p for p in DEST.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()

    files = sorted(p for p in DEST.rglob("*") if p.is_file() and p.name not in ("SHA256SUMS", "kaggle-dataset-metadata.json"))
    (DEST / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(DEST)}\n" for p in files))
    api.dataset_metadata(DATASET, str(DEST))
    meta = DEST / "dataset-metadata.json"
    if meta.exists():
        meta.rename(DEST / "kaggle-dataset-metadata.json")
    meta_json = json.loads((DEST / "kaggle-dataset-metadata.json").read_text())
    licences = meta_json.get("info", meta_json).get("licenses")
    print(f"wrote {len(files)} files, SHA256SUMS and kaggle-dataset-metadata.json (licenses: {licences}) to {DEST}")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
