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

Settings (notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md): the detection-time NMS (IoU 0.6) leaves a near-copy of the box
on many players, at IoU 0.54-0.60 with the original, and the detector is under-confident (true players: median conf
0.40). With Ultralytics' ByteTrack defaults, score fusion then rejects many true matches while the copies start rival
tracks: 892 track ids for 198 players on the val split. suppress_duplicates() at DEDUP_IOU and FLOCKER_TRACKER (no
score fusion, lower thresholds) together bring that to 227, and IDF1 from 70.5 to 98.8 (centres within 15 px).

Teams: when the detections carry a ``team`` column (flocker.team), each player track gets its detections' majority
team. team_aware() can also forbid matches across teams, but on the val split it added identity switches: a
detection's colour is least reliable in a duel, where its box takes in part of the opponent.
"""

import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from flocker.mot import BALL, PLAYER, normalize_mot
from flocker.paths import CODE_ROOT

ID_OFFSET = 100_000
CLASS_NAMES_TO_FLOCKER = {"player": PLAYER, "person": PLAYER, "ball": BALL, "sports ball": BALL}
FLOCKER_TRACKER = CODE_ROOT / "config" / "trackers" / "flocker_bytetrack.yaml"  # ByteTrack tuned on TeamTrack's val split
DEDUP_IOU = 0.3  # the second NMS that goes with it (suppress_duplicates)


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
        # quantize 16 is FP16 and None FP32: what the deprecated half=True/False mean (ultralytics/cfg/__init__.py)
        results = yolo.predict([img for _, img in chunk], imgsz=imgsz, conf=conf, iou=iou, device=device, quantize=16 if half else None, classes=sorted(class_map), verbose=False, max_det=300)
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


def tracker_config(tracker: str = "flocker", **overrides):
    """An Ultralytics tracker configuration with overrides applied. ``tracker`` is "flocker" (FLOCKER_TRACKER, the
    settings tuned for TeamTrack), an Ultralytics built-in name such as "bytetrack", or a YAML path."""
    from ultralytics.utils import YAML, IterableSimpleNamespace
    from ultralytics.utils.checks import check_yaml

    if tracker == "flocker":
        tracker = str(FLOCKER_TRACKER)
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


def suppress_duplicates(dets: pd.DataFrame, iou: float) -> pd.DataFrame:
    """Greedy non-maximum suppression per frame and class: keep the highest-scoring box and drop every lower-scoring
    box that overlaps a kept one by IoU > iou (the rule Ultralytics' own NMS applies, at its --nms-iou).

    Run on cached detections, this is a second, stricter NMS: it removes the near-copies of a box that a looser
    detection-time NMS let through. Ties in score keep the earlier row."""
    d = normalize_mot(dets)
    keep = np.zeros(len(d), bool)
    xyxy_all = np.column_stack([d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"]])
    for idx in d.groupby(["frame", "cls"]).indices.values():
        order = idx[np.argsort(-d["conf"].to_numpy()[idx], kind="stable")]
        ious = _iou_matrix(xyxy_all[order], xyxy_all[order])
        alive = np.ones(len(order), bool)
        for i in range(len(order)):
            if alive[i]:
                keep[order[i]] = True
                alive[i + 1 :] &= ious[i, i + 1 :] <= iou
    return d[keep].reset_index(drop=True)


TEAM_UNKNOWN_CLS = 2  # a player detection's team travels through the tracker in its cls field: 0, 1, or this
TEAM_CLASH_COST = 10.0  # above every association threshold, so lapjv's cost_limit never accepts the pair


def team_aware(base: type) -> type:
    """``base`` (an Ultralytics tracker built on BYTETracker) changed so that it never matches a detection of one team
    to a track of the other.

    Detections carry their team in cls (0 or 1; TEAM_UNKNOWN_CLS when unknown). A track's team is the majority of the
    teams of the detections it has been matched to, once it holds at least ``team_min_votes`` votes and the majority
    is at least ``team_purity`` of them (tracker settings, default 5 and 0.8). Until then, and for a detection of
    unknown team, the base cost stands. Every association that goes through get_dists is gated: the first one and the
    one for unconfirmed tracks. ByteTrack's second association (low-score detections, plain IoU) is not.
    """

    class TeamAware(base):
        def __init__(self, args):
            super().__init__(args)
            self.team_votes: dict[int, np.ndarray] = {}
            self.team_min_votes = int(getattr(args, "team_min_votes", 5))
            self.team_purity = float(getattr(args, "team_purity", 0.8))

        def track_team(self, track) -> int:
            votes = self.team_votes.get(track.track_id)
            if votes is None or votes.sum() < self.team_min_votes:
                return -1
            k = int(votes.argmax())
            return k if votes[k] >= self.team_purity * votes.sum() else -1

        def get_dists(self, tracks, detections):
            dists = super().get_dists(tracks, detections)
            if len(tracks) and len(detections):
                tt = np.array([self.track_team(t) for t in tracks])
                dt = np.array([int(d.cls) if int(d.cls) in (0, 1) else -1 for d in detections])
                clash = (tt[:, None] >= 0) & (dt[None, :] >= 0) & (tt[:, None] != dt[None, :])
                dists = np.where(clash, TEAM_CLASH_COST, dists)
            return dists

        def update(self, results, img=None, feats=None, **kwargs):
            out = super().update(results, img, feats, **kwargs)
            for row in out:
                if int(row[6]) in (0, 1):
                    self.team_votes.setdefault(int(row[4]), np.zeros(2))[int(row[6])] += 1
            return out

    TeamAware.__name__ = f"TeamAware{base.__name__}"
    return TeamAware


def track_teams(det_team: pd.Series, ids: pd.Series, purity: float = 0.5) -> pd.Series:
    """Each row's track team: the majority of its track's detection teams (0/1; -1 unknown is not a vote), or -1 when
    the track has no votes or its majority is below ``purity``."""
    votes = pd.crosstab(ids, det_team.where(det_team.isin([0, 1]), -1)).reindex(columns=[0, 1], fill_value=0)
    n = votes.sum(axis=1)
    team = np.where(votes[1] > votes[0], 1, 0)
    team = np.where((n > 0) & (votes.max(axis=1) >= purity * n), team, -1)
    return ids.map(pd.Series(team, index=votes.index)).fillna(-1).astype(int)


def track_detections(dets: pd.DataFrame, tracker: str = "flocker", n_frames: int | None = None, orig_shape: tuple[int, int] = (2160, 3840), box_source: str = "track", team_gate: bool = False, **overrides) -> pd.DataFrame:
    """Tracks (MOT frame with ids) from cached detections; one tracker per class; ball ids offset by ID_OFFSET.

    When dets has a ``team`` column (0, 1, or -1 unknown; flocker.team), each player track gets a ``team`` column too:
    the majority team of the detections it was matched to (track_teams). team_gate also forbids matching a detection
    to a track of the other team (team_aware).
    """
    from ultralytics.engine.results import Boxes
    from ultralytics.trackers.track import TRACKER_MAP

    if box_source not in ("track", "detection"):
        raise ValueError(f"box_source must be 'track' or 'detection', not {box_source!r}")
    has_team = "team" in dets.columns
    if team_gate and not has_team:
        raise ValueError("team_gate needs a 'team' column in the detections")
    dets = normalize_mot(dets)
    n_frames = n_frames or (int(dets["frame"].max()) if len(dets) else 0)
    rows = []
    for cls in sorted(dets["cls"].unique()):
        cfg = tracker_config(tracker, **overrides)
        kind = TRACKER_MAP[cfg.tracker_type]
        trk = team_aware(kind)(args=cfg) if team_gate and cls != BALL else kind(args=cfg)
        if hasattr(trk, "reset_id"):  # ids start at 1 per instance; TRACKTRACK has no reset_id and needs none
            trk.reset_id()
        offset = ID_OFFSET if cls == BALL else 0
        sub = dets[dets["cls"] == cls]
        label = np.where(sub["team"].isin([0, 1]), sub["team"], TEAM_UNKNOWN_CLS) if has_team and cls != BALL else sub["cls"].to_numpy()
        sub = sub.assign(_label=label)
        by_frame = dict(iter(sub.groupby("frame")))
        for f in range(1, n_frames + 1):
            g = by_frame.get(f)
            xyxy = np.zeros((0, 4)) if g is None else np.column_stack([g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"]])
            data = np.zeros((0, 6), np.float32) if g is None else np.column_stack([xyxy, g["conf"], g["_label"]]).astype(np.float32)
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
                det_team = int(t[6]) if has_team and cls != BALL and int(t[6]) in (0, 1) else -1
                rows.append((f, int(t[4]) + offset, x1, y1, x2 - x1, y2 - y1, float(t[5]), int(cls), det_team))
    out = pd.DataFrame(rows, columns=["frame", "id", "x", "y", "w", "h", "conf", "cls", "det_team"])
    if has_team:
        out["team"] = np.where(out["cls"] == BALL, -1, track_teams(out["det_team"], out["id"]))
    return normalize_mot(out.drop(columns="det_team"))


def timed(fn, *args, **kwargs):
    """(result, seconds) of fn(*args, **kwargs)."""
    t = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - t
