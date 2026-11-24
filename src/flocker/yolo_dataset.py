"""Build an Ultralytics YOLO detection dataset from TeamTrack: full-resolution tiles of sampled frames.

Project: Flocker
File: src/flocker/yolo_dataset.py
Purpose: turn TeamTrack videos and ground truth into YOLO images and labels (classes: 0 player, 1 ball)
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE); the images derive from TeamTrack (MIT) and must not be committed

Players are about 30 px across in TeamTrack's 3840 x 2160 frames. Downscaling whole frames to a usual training size
would shrink them to a few pixels, so frames are cut into overlapping tiles at full resolution instead; a model
trained on tiles then runs on whole frames at the same scale (YOLO is fully convolutional). A box is labelled in a
tile when at least min_visible of its area lies inside the tile; overlaps are far wider than a player, so every
player is whole in at least one tile.

Excluded by default: the six train sequences whose ground truth overruns the video (frames 901-906). Checked on
2026-11-24: their boxes are aligned at frame 1 but lead the players by several frames at frame 900, as if 906
annotated frames were stretched over the 900-frame video.
"""

import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from flocker.mot import BALL, PLAYER
from flocker.teamtrack import Sequence, load_gt

YOLO_NAMES = {PLAYER: "player", BALL: "ball"}
MISALIGNED_TRAIN = ("D_20220220_1_0570_0600", "D_20220220_1_0600_0630", "D_20220220_1_0630_0660", "D_20220220_1_0660_0690", "D_20220220_1_0690_0720", "D_20220220_1_0720_0750")


def tile_origins(size: int, tile: int, min_overlap: int) -> list[int]:
    """Evenly spaced tile origins covering [0, size) with at least min_overlap pixels between neighbours."""
    if size <= tile:
        return [0]
    n = math.ceil((size - min_overlap) / (tile - min_overlap))
    return [round(i * (size - tile) / (n - 1)) for i in range(n)]


def tile_labels(boxes: pd.DataFrame, x0: int, y0: int, tile: int, min_visible: float = 0.5) -> list[str]:
    """YOLO label lines (class cx cy w h, normalised to the tile) for the boxes visible enough in one tile."""
    if boxes.empty:
        return []
    x1, y1 = boxes["x"].to_numpy(), boxes["y"].to_numpy()
    x2, y2 = x1 + boxes["w"].to_numpy(), y1 + boxes["h"].to_numpy()
    cx1, cy1 = np.clip(x1, x0, x0 + tile), np.clip(y1, y0, y0 + tile)
    cx2, cy2 = np.clip(x2, x0, x0 + tile), np.clip(y2, y0, y0 + tile)
    area = (x2 - x1) * (y2 - y1)
    visible = np.clip(cx2 - cx1, 0, None) * np.clip(cy2 - cy1, 0, None)
    keep = (area > 0) & (visible >= min_visible * area)
    lines = []
    for c, a, b, d, e in zip(boxes["cls"].to_numpy()[keep], cx1[keep], cy1[keep], cx2[keep], cy2[keep]):
        lines.append(f"{int(c)} {((a + d) / 2 - x0) / tile:.6f} {((b + e) / 2 - y0) / tile:.6f} {(d - a) / tile:.6f} {(e - b) / tile:.6f}")
    return lines


def _build_sequence(task) -> dict:
    seq, out_dir, subset, every, tile, min_overlap, min_visible, quality = task
    gt = load_gt(seq)
    by_frame = dict(iter(gt.groupby("frame")))
    info = seq.seqinfo()
    xs, ys = tile_origins(info["imwidth"], tile, min_overlap), tile_origins(info["imheight"], tile, min_overlap)
    img_dir, lbl_dir = out_dir / "images" / subset, out_dir / "labels" / subset
    cap = cv2.VideoCapture(str(seq.video_path))
    counts = {"sequence": seq.name, "subset": subset, "frames": 0, "tiles": 0, "empty_tiles": 0, "player_labels": 0, "ball_labels": 0}
    empty = gt.iloc[:0]
    try:
        for f in range(1, info["seqlength"] + 1):
            if (f - 1) % every:
                if not cap.grab():
                    break
                continue
            ok, img = cap.read()
            if not ok:
                break
            counts["frames"] += 1
            boxes = by_frame.get(f, empty)
            for y0 in ys:
                for x0 in xs:
                    stem = f"{seq.name}_f{f:04d}_x{x0:04d}_y{y0:04d}"
                    cv2.imwrite(str(img_dir / f"{stem}.jpg"), img[y0 : y0 + tile, x0 : x0 + tile], [cv2.IMWRITE_JPEG_QUALITY, quality])
                    lines = tile_labels(boxes, x0, y0, tile, min_visible)
                    (lbl_dir / f"{stem}.txt").write_text("".join(line + "\n" for line in lines))
                    counts["tiles"] += 1
                    counts["empty_tiles"] += not lines
                    counts["player_labels"] += sum(line.startswith(f"{PLAYER} ") for line in lines)
                    counts["ball_labels"] += sum(line.startswith(f"{BALL} ") for line in lines)
    finally:
        cap.release()
    return counts


def build_yolo_dataset(out_dir: str | Path, train: list[Sequence], val: list[Sequence], every: int = 30, every_val: int = 90, tile: int = 1280, min_overlap: int = 256, min_visible: float = 0.5, quality: int = 95, workers: int = 8) -> dict:
    """Write images/{train,val}, labels/{train,val}, data.yaml and manifest.json under out_dir; return the manifest."""
    out_dir = Path(out_dir).resolve()
    if (out_dir / "data.yaml").exists():
        raise FileExistsError(f"{out_dir} already holds a dataset; choose a new folder")
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    tasks = [(s, out_dir, "train", every, tile, min_overlap, min_visible, quality) for s in train] + [(s, out_dir, "val", every_val, tile, min_overlap, min_visible, quality) for s in val]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        per_seq = list(pool.map(_build_sequence, tasks))
    names = "\n".join(f"  {k}: {v}" for k, v in YOLO_NAMES.items())
    (out_dir / "data.yaml").write_text(f"# TeamTrack soccer_top tiles for YOLO (built by flocker.yolo_dataset)\npath: {out_dir}\ntrain: images/train\nval: images/val\nnames:\n{names}\n")
    manifest = {
        "source": "TeamTrack soccer_top (MIT); see videos/raw/SOURCES.md",
        "params": {"every": every, "every_val": every_val, "tile": tile, "min_overlap": min_overlap, "min_visible": min_visible, "jpeg_quality": quality},
        "train_sequences": [s.name for s in train],
        "val_sequences": [s.name for s in val],
        "totals": {sub: {k: int(sum(c[k] for c in per_seq if c["subset"] == sub)) for k in ("frames", "tiles", "empty_tiles", "player_labels", "ball_labels")} for sub in ("train", "val")},
        "per_sequence": per_seq,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest
