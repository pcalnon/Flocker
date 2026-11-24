"""Where Flocker's data lives.

Project: Flocker
File: src/flocker/paths.py
Purpose: resolve the data root (the primary checkout, which holds the gitignored media) from any checkout
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

Code may run from a worktree, but the media and datasets exist only in the primary checkout, because git
ignores them. data_root() therefore finds the primary through git's common directory, which every worktree
shares. Set FLOCKER_DATA_ROOT to use another tree laid out the same way.
"""

import os
import subprocess
from functools import cache
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]


@cache
def primary_root() -> Path:
    """The primary checkout of the repository this code belongs to (CODE_ROOT itself when git cannot tell)."""
    try:
        out = subprocess.run(["git", "-C", str(CODE_ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return CODE_ROOT
    common = Path(out)
    return common.parent if common.name == ".git" else CODE_ROOT


def data_root() -> Path:
    """FLOCKER_DATA_ROOT if set, else the primary checkout."""
    env = os.environ.get("FLOCKER_DATA_ROOT")
    return Path(env).expanduser().resolve() if env else primary_root()


def teamtrack_root() -> Path:
    """TeamTrack's top-view soccer subset, as fetched by util/ad-hoc/2026-11-20_fetch_teamtrack_soccer_top.py."""
    return data_root() / "videos" / "raw" / "teamtrack_soccer_top"
