"""Detect and track players and the ball in video.

Project: Flocker
File: src/flocker/track.py
Purpose: one detection pass per video (cached as a MOT file with id -1), then one tracker per class on the cache
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE); Ultralytics is AGPL-3.0

Detection runs YOLO on whole frames at native resolution (imgsz 3840 for TeamTrack's 3840 x 2160 frames), the
scale flocker.yolo_dataset's tiles were trained at. A reader thread decodes frames while the GPU works.

Tracking replays the cached detections through Ultralytics' trackers, so a tracker can be tuned in seconds without
re-running the detector. Each class gets its own tracker instance, so the ball cannot take over a player's
identity; ball track ids are offset by ID_OFFSET. No images are passed to the trackers, so BoT-SORT runs without
camera-motion compensation or ReID.

Box source: "track" reports the tracker's Kalman-filtered box (what Ultralytics' model.track() reports); "detection"
replaces it with the same-class detection of that frame it overlaps most (IoU >= 0.3), i.e. the raw measurement.
"""

import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from flocker.mot import BALL, PLAYER, normalize_mot

ID_OFFSET = 100_000
CLASS_NAMES_TO_FLOCKER = {"player": PLAYER, "person": PLAYER, "ball": BALL, "sports ball": BALL}


def class_map_for(names: dict) -> dict:
    """Model class -> flocker class, from the model's class names (flocker.detector's 'player'/'ball', or COCO's
    'person'/'sports ball'); classes with other names are not detected."""
    mapping = {int(k): CLASS_NAMES_TO_FLOCKER[v] for k, v in names.items() if v in CLASS_NAMES_TO_FLOCKER}
    if not mapping:
        raise ValueError(f"the model has none of the classes {sorted(CLASS_NAMES_TO_FLOCKER)}")
    return mapping


def _frames(video: str | Path, max_frames: int | None, prefetch: int = 8):
    """Yield (1-based frame number, BGR image), decoding in a background thread."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(video)
    q: queue.Queue = queue.Queue(maxsize=prefetch)

    def reader():
        n = 0
        try:
            while max_frames is None or n < max_frames:
                ok, img = cap.read()
                if not ok:
                    break
                n += 1
                q.put((n, img))
        finally:
            cap.release()
            q.put(None)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    while (item := q.get()) is not None:
        yield item
    t.join()


def detect_video(video: str | Path, model, imgsz: int = 3840, conf: float = 0.05, iou: float = 0.6, device=0, half: bool = True, class_map: dict | None = None, batch: int = 2, max_frames: int | None = None) -> pd.DataFrame:
    """Detections for every frame: a MOT frame with id -1 and cls mapped through class_map (default: from the
    model's class names, see class_map_for); other classes are not detected."""
    from ultralytics import YOLO

    yolo = YOLO(str(model)) if isinstance(model, (str, Path)) else model
    class_map = class_map_for(yolo.names) if class_map is None else class_map
    rows: list[tuple] = []

    def run(chunk):
        results = yolo.predict([img for _, img in chunk], imgsz=imgsz, conf=conf, iou=iou, device=device, half=half, classes=sorted(class_map), verbose=False, max_det=300)
        for (f, _), r in zip(chunk, results):
            b = r.boxes.cpu().numpy()
            for (x1, y1, x2, y2), c, k in zip(b.xyxy, b.conf, b.cls):
                rows.append((f, -1, float(x1), float(y1), float(x2 - x1), float(y2 - y1), float(c), class_map[int(k)]))

    chunk = []
    for item in _frames(video, max_frames):
        chunk.append(item)
        if len(chunk) == batch:
            run(chunk)
            chunk = []
    if chunk:
        run(chunk)
    return normalize_mot(pd.DataFrame(rows, columns=["frame", "id", "x", "y", "w", "h", "conf", "cls"]))


def tracker_config(tracker: str = "bytetrack", **overrides):
    """An Ultralytics tracker configuration (built-in name or YAML path) with overrides applied."""
    from ultralytics.utils import YAML, IterableSimpleNamespace
    from ultralytics.utils.checks import check_yaml

    cfg = dict(YAML.load(check_yaml(tracker if tracker.endswith((".yaml", ".yml")) else f"{tracker}.yaml")))
    cfg.update(overrides)
    if "gmc_method" in cfg:
        cfg["gmc_method"] = None  # no images are passed to the tracker
    if "with_reid" in cfg:
        cfg["with_reid"] = False
    return IterableSimpleNamespace(**cfg)


def _iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between xyxy boxes a (N x 4) and b (M x 4)."""
    ix = np.clip(np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    iy = np.clip(np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    inter = ix * iy
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


def track_detections(dets: pd.DataFrame, tracker: str = "bytetrack", n_frames: int | None = None, orig_shape: tuple[int, int] = (2160, 3840), box_source: str = "track", **overrides) -> pd.DataFrame:
    """Tracks (MOT frame with ids) from cached detections; one tracker per class; ball ids offset by ID_OFFSET."""
    from ultralytics.engine.results import Boxes
    from ultralytics.trackers.track import TRACKER_MAP

    if box_source not in ("track", "detection"):
        raise ValueError(f"box_source must be 'track' or 'detection', not {box_source!r}")
    dets = normalize_mot(dets)
    n_frames = n_frames or (int(dets["frame"].max()) if len(dets) else 0)
    rows = []
    for cls in sorted(dets["cls"].unique()):
        cfg = tracker_config(tracker, **overrides)
        trk = TRACKER_MAP[cfg.tracker_type](args=cfg)
        trk.reset_id()
        offset = ID_OFFSET if cls == BALL else 0
        by_frame = dict(iter(dets[dets["cls"] == cls].groupby("frame")))
        for f in range(1, n_frames + 1):
            g = by_frame.get(f)
            xyxy = np.zeros((0, 4)) if g is None else np.column_stack([g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"]])
            data = np.zeros((0, 6), np.float32) if g is None else np.column_stack([xyxy, g["conf"], g["cls"]]).astype(np.float32)
            tracks = trk.update(Boxes(data, orig_shape), None)
            if len(tracks) == 0:
                continue
            boxes = tracks[:, :4].astype(np.float64)
            if box_source == "detection" and len(xyxy):
                ious = _iou_matrix(boxes, xyxy)
                best = ious.argmax(axis=1)
                snap = ious[np.arange(len(boxes)), best] >= 0.3
                boxes[snap] = xyxy[best[snap]]
            for (x1, y1, x2, y2), t in zip(boxes, tracks):
                rows.append((f, int(t[4]) + offset, x1, y1, x2 - x1, y2 - y1, float(t[5]), int(cls)))
    return normalize_mot(pd.DataFrame(rows, columns=["frame", "id", "x", "y", "w", "h", "conf", "cls"]))


def timed(fn, *args, **kwargs):
    """(result, seconds) of fn(*args, **kwargs)."""
    t = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - t
