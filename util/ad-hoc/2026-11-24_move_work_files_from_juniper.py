#!/usr/bin/env python3
"""Move the 2026-11-20 work arc's files out of Juniper directories and into Flocker.

Single-use script (2026-11-24). The first Flocker session (video search and toolchain setup) ran
from a juniper-ml worktree, so its working files landed in juniper-ml's temp tree. This moves
them into Flocker, where they belong:

    the video-search agent's 10 bash scripts  -> util/ad-hoc/2026-11-20_video-search/   (tracked)
    its downloaded data, frames and previews  -> tmp/2026-11-20_video-search/           (ignored)
    contact sheet and hash lists              -> tmp/2026-11-20_video-search/           (ignored)
    its browser logs (2026-11-21 UTC only)    -> tmp/2026-11-20_video-search/playwright-mcp/
    the reviewed roboflow/sports archive      -> tmp/2026-11-20_toolchain/downloads/    (ignored)
    the Kaggle metadata probe                 -> tmp/2026-11-20_toolchain/kaggle-meta/  (ignored)
    the YOLO11n test weights                  -> resources/models/yolo11n.pt            (ignored)
    the conda environment build log           -> logs/2026-11-20_conda-env-create.log   (ignored)

The browser-log folder also holds older files (May 2026, plus four PNGs) that a juniper-ml worktree
copied in when it was created; they are not this work's and are left where they are.

Usage:  python3 util/ad-hoc/2026-11-24_move_work_files_from_juniper.py [--dry-run]
Re-running is safe: a source that no longer exists is reported and skipped.
"""

import argparse
import pathlib
import shutil
import sys

FLOCKER = pathlib.Path(__file__).resolve().parents[2]
SCRATCH = pathlib.Path("/home/pcalnon/Development/python/Juniper/juniper-ml/tmp/claude-1000/-home-pcalnon-Development-python-Juniper-juniper-ml/180928ad-1ef0-4d16-a165-e7de10cb0669/scratchpad")
BROWSER_LOGS = pathlib.Path("/home/pcalnon/Development/python/Juniper/juniper-ml/.claude/worktrees/shiny-pondering-gray/.playwright-mcp")
BROWSER_LOG_PREFIXES = ("console-2026-11-21T0", "page-2026-11-21T0")

# (source, destination). A directory source moves whole; a file source moves to exactly the destination path.
MOVES = [
    (SCRATCH / "video-check" / "scripts", FLOCKER / "util" / "ad-hoc" / "2026-11-20_video-search"),
    (SCRATCH / "video-check" / "data", FLOCKER / "tmp" / "2026-11-20_video-search" / "data"),
    (SCRATCH / "video-check" / "frames", FLOCKER / "tmp" / "2026-11-20_video-search" / "frames"),
    (SCRATCH / "raw-clips-contact-sheet.jpg", FLOCKER / "tmp" / "2026-11-20_video-search" / "raw-clips-contact-sheet.jpg"),
    (SCRATCH / "actual-hashes.txt", FLOCKER / "tmp" / "2026-11-20_video-search" / "actual-hashes.txt"),
    (SCRATCH / "manifest-hashes.txt", FLOCKER / "tmp" / "2026-11-20_video-search" / "manifest-hashes.txt"),
    (SCRATCH / "downloads", FLOCKER / "tmp" / "2026-11-20_toolchain" / "downloads"),
    (SCRATCH / "kaggle-meta", FLOCKER / "tmp" / "2026-11-20_toolchain" / "kaggle-meta"),
    (SCRATCH / "models" / "yolo11n.pt", FLOCKER / "resources" / "models" / "yolo11n.pt"),
    (SCRATCH / "flocker-env-create.log", FLOCKER / "logs" / "2026-11-20_conda-env-create.log"),
]


def move(src, dst, dry_run):
    if not src.exists():
        print(f"skip (gone)      {src}")
        return 0
    if dst.exists():
        print(f"REFUSE (exists)  {dst}")
        return 1
    print(f"{'would move' if dry_run else 'moved':<16} {src} -> {dst.relative_to(FLOCKER)}")
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    problems = sum(move(src, dst, args.dry_run) for src, dst in MOVES)
    logs_dst = FLOCKER / "tmp" / "2026-11-20_video-search" / "playwright-mcp"
    if BROWSER_LOGS.is_dir():
        for f in sorted(BROWSER_LOGS.iterdir()):
            if f.is_file() and f.name.startswith(BROWSER_LOG_PREFIXES):
                problems += move(f, logs_dst / f.name, args.dry_run)

    # Remove scratch folders the moves emptied.
    if not args.dry_run:
        for d in (SCRATCH / "video-check", SCRATCH / "models"):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                print(f"removed empty    {d}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
