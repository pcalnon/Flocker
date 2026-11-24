"""MOTChallenge text files: reading and writing tracks and detections.

Project: Flocker
File: src/flocker/mot.py
Purpose: one DataFrame layout for ground truth and tracker output, read from and written to MOTChallenge text
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

A MOTChallenge line is ``frame, id, left, top, width, height, conf, x, y, z`` with 1-based frames and boxes in
pixels. Flocker's own outputs put the object class in the eighth column (0 player, 1 ball, -1 unknown),
where 2D tracker results carry -1; the evaluation ignores that column.
"""

from pathlib import Path

import numpy as np
import pandas as pd

MOT_COLUMNS = ["frame", "id", "x", "y", "w", "h", "conf", "cls", "vis", "z"]
PLAYER, BALL, UNKNOWN = 0, 1, -1
CLASS_NAMES = {PLAYER: "player", BALL: "ball", UNKNOWN: "unknown"}


def empty_mot() -> pd.DataFrame:
    """An empty frame with MOT_COLUMNS and their dtypes."""
    return pd.DataFrame({c: pd.Series(dtype="int64" if c in ("frame", "id", "cls") else "float64") for c in MOT_COLUMNS})


def normalize_mot(df: pd.DataFrame) -> pd.DataFrame:
    """Give any frame with at least frame, id, x, y, w, h the full MOT_COLUMNS (defaults conf 1, cls/vis/z -1)."""
    missing = [c for c in ("frame", "id", "x", "y", "w", "h") if c not in df.columns]
    if missing:
        raise ValueError(f"MOT frame lacks columns {missing}")
    out = df.copy()
    defaults = {"conf": 1.0, "cls": UNKNOWN, "vis": -1.0, "z": -1.0}
    for c, v in defaults.items():
        if c not in out.columns:
            out[c] = v
    out = out[MOT_COLUMNS + [c for c in out.columns if c not in MOT_COLUMNS]]
    out = out.astype({"frame": "int64", "id": "int64", "cls": "int64", "x": "float64", "y": "float64", "w": "float64", "h": "float64", "conf": "float64", "vis": "float64", "z": "float64"})
    return out.sort_values(["frame", "id"], kind="stable").reset_index(drop=True)


def read_mot(path: str | Path) -> pd.DataFrame:
    """Read a MOTChallenge file with 6 to 10 comma-separated columns. An empty file gives an empty frame."""
    path = Path(path)
    if path.stat().st_size == 0:
        return empty_mot()
    raw = pd.read_csv(path, header=None, sep=",", skipinitialspace=True)
    if not 6 <= raw.shape[1] <= 10:
        raise ValueError(f"{path}: {raw.shape[1]} columns; a MOT file has 6 to 10")
    raw.columns = MOT_COLUMNS[: raw.shape[1]]
    return normalize_mot(raw)


def write_mot(df: pd.DataFrame, path: str | Path) -> Path:
    """Write ``frame,id,x,y,w,h,conf,cls,vis,z`` lines (boxes to 2 decimals), creating parent folders."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = normalize_mot(df)[MOT_COLUMNS]
    with path.open("w") as f:
        for r in out.itertuples(index=False):
            f.write(f"{r.frame},{r.id},{r.x:.2f},{r.y:.2f},{r.w:.2f},{r.h:.2f},{r.conf:.4f},{r.cls},{r.vis:g},{r.z:g}\n")
    return path


def centers(df: pd.DataFrame) -> np.ndarray:
    """Box centres, an N x 2 array of (cx, cy) in pixels."""
    return np.column_stack([df["x"].to_numpy() + df["w"].to_numpy() / 2.0, df["y"].to_numpy() + df["h"].to_numpy() / 2.0])
