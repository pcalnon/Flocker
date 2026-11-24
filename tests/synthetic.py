"""Synthetic MOT data for Flocker's tests.

Project: Flocker
File: tests/synthetic.py
Purpose: build ground-truth-like tracks and TeamTrack-shaped sequence folders without any real data
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)
"""

from pathlib import Path

import numpy as np
import pandas as pd


def make_tracks(n_objects: int = 6, n_frames: int = 40, seed: int = 0, size: float = 30.0, first_id: int = 0) -> pd.DataFrame:
    """Objects on random walks, 200 px apart in x, one box per object per frame."""
    rng = np.random.default_rng(seed)
    rows = []
    pos = np.column_stack([np.arange(n_objects) * 200.0 + 100.0, rng.uniform(100, 900, n_objects)])
    for f in range(1, n_frames + 1):
        pos = pos + rng.normal(0, 3, pos.shape)
        for i in range(n_objects):
            rows.append((f, first_id + i, pos[i, 0], pos[i, 1], size, size))
    return pd.DataFrame(rows, columns=["frame", "id", "x", "y", "w", "h"])


def write_teamtrack_sequence(root: Path, split: str, name: str, gt: pd.DataFrame, seqlength: int) -> None:
    """A TeamTrack-shaped sequence folder: seqinfo.ini and gt/gt.txt (no video)."""
    d = root / "teamtrack-mot" / "soccer_top" / split / name
    (d / "gt").mkdir(parents=True)
    (d / "seqinfo.ini").write_text(f"[Sequence]\nname = {name}\nimdir = img1\nframerate = 29.97\nseqlength = {seqlength}\nimwidth = 3840\nimheight = 2160\nimext = .jpg\n\n")
    with (d / "gt" / "gt.txt").open("w") as f:
        for r in gt.itertuples(index=False):
            f.write(f"{int(r.frame)},{int(r.id)},{int(r.x)},{int(r.y)},{int(r.w)},{int(r.h)},1,-1,-1,-1\n")
