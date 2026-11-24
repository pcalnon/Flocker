"""Multi-object tracking metrics: HOTA, CLEAR-MOT and identity (IDF1), computed with py-motmetrics.

Project: Flocker
File: src/flocker/evaluate.py
Purpose: score tracker output against ground truth, per sequence and overall, the way TrackEval and MOTChallenge do
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

py-motmetrics is installed from a reviewed GitHub commit (config/environment.yml, post-create step 2). This
module adds two things on top of it.

1. Every id is relabelled to 1..N before scoring. motmetrics' HOTA code sizes its global-alignment matrix by the
   largest id and indexes it with ``id - 1``, i.e. it assumes MOTChallenge's 1-based, contiguous ids. TeamTrack's
   ground truth starts at id 0, which would index -1, wrap onto the largest id and silently merge two objects'
   association statistics. The metrics depend on ids only through equality, so relabelling changes nothing else.
2. Sequences are scored in parallel processes and the overall row is combined from per-sequence counts with
   TrackEval's rules: counts are summed; per HOTA threshold alpha, DetA = TP / (TP + FN + FP), AssA is the
   TP-weighted mean of the sequences' AssA, and HOTA = sqrt(DetA * AssA); the reported HOTA, DetA and AssA are
   means over the 19 thresholds 0.05, 0.10, ..., 0.95. MOTA = 1 - (FN + FP + IDSW) / GT,
   IDF1 = 2 IDTP / (2 IDTP + IDFP + IDFN), and MOTP is the mean IoU of CLEAR matches (motmetrics reports 1 - IoU).

CLEAR-MOT and IDF1 match a prediction to a ground-truth box when IoU >= iou_threshold (0.5 by default), or, with
match="center", when the box centres are at most max_center_dist pixels apart. Centre matching measures what the
dots need (positions) and is blind to box-size conventions: TeamTrack's D_20220220_1_1770_1800 is annotated with
boxes about 42 x 40 px against 24-39 px elsewhere, so a perfectly centred 28 x 28 detection has IoU 0.47 there.
HOTA is defined on IoU and is skipped in centre mode; MOTP is then the mean matched centre distance in pixels.
"""

import os
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor

import motmetrics as mm
import numpy as np
import pandas as pd

from flocker.mot import normalize_mot

HOTA_ALPHAS = tuple(float(a) for a in np.arange(0.05, 0.99, 0.05))
_CLEAR_FIELDS = ["num_frames", "num_objects", "num_predictions", "num_unique_objects", "num_dt_ids", "num_detections", "num_switches", "num_false_positives", "num_misses", "num_fragmentations", "mostly_tracked", "partially_tracked", "mostly_lost", "motp", "idtp", "idfp", "idfn"]
_HOTA_FIELDS = ["num_detections", "num_misses", "num_false_positives", "assa_alpha", "deta_alpha", "hota_alpha"]
COLUMNS = ["HOTA", "DetA", "AssA", "MOTA", "MOTP", "IDF1", "IDP", "IDR", "Rcll", "Prcn", "TP", "FP", "FN", "IDSW", "Frag", "GT", "Dets", "GT_IDs", "IDs", "MT", "PT", "ML", "Frames"]


def to_motmetrics(df: pd.DataFrame) -> pd.DataFrame:
    """flocker.mot layout -> motmetrics' (FrameId, Id)-indexed layout, with ids relabelled to 1..N."""
    df = normalize_mot(df)
    codes, _ = pd.factorize(df["id"], sort=True)
    out = pd.DataFrame({"FrameId": df["frame"].to_numpy(), "Id": codes + 1, "X": df["x"].to_numpy(), "Y": df["y"].to_numpy(), "Width": df["w"].to_numpy(), "Height": df["h"].to_numpy(), "Confidence": df["conf"].to_numpy(), "ClassId": -1, "Visibility": -1.0})
    out["CX"], out["CY"] = out["X"] + out["Width"] / 2.0, out["Y"] + out["Height"] / 2.0
    return out.set_index(["FrameId", "Id"]).sort_index()


def _score_sequence(task) -> dict:
    """CLEAR/ID counts and per-alpha HOTA counts for one sequence (runs in a worker process)."""
    name, gt, pred, iou_threshold, hota, max_center_dist = task
    g, p = to_motmetrics(gt), to_motmetrics(pred)
    mh = mm.metrics.create()
    if max_center_dist is None:
        acc = mm.utils.compare_to_groundtruth(g, p, "iou", distth=1.0 - iou_threshold)
    else:
        acc = mm.utils.compare_to_groundtruth(g, p, "euclidean", distfields=["CX", "CY"], distth=float(max_center_dist))
    res = {"name": name, **mh.compute(acc, metrics=_CLEAR_FIELDS, return_dataframe=False)}
    if hota:
        accs = mm.utils.compare_to_groundtruth_reweighting(g, p, "iou", distth=list(HOTA_ALPHAS))
        per_alpha = [mh.compute(a, metrics=_HOTA_FIELDS, return_dataframe=False) for a in accs]
        res["hota_tp"] = np.array([r["num_detections"] for r in per_alpha], dtype=float)
        res["hota_fn"] = np.array([r["num_misses"] for r in per_alpha], dtype=float)
        res["hota_fp"] = np.array([r["num_false_positives"] for r in per_alpha], dtype=float)
        res["assa"] = np.array([r["assa_alpha"] for r in per_alpha], dtype=float)
        res["mm_deta"] = np.array([r["deta_alpha"] for r in per_alpha], dtype=float)
        res["mm_hota"] = np.array([r["hota_alpha"] for r in per_alpha], dtype=float)
    return res


def _row(c: dict, hota: bool, center: bool = False) -> dict:
    """Final metrics from summed counts (one sequence's, or all sequences' for the overall row)."""
    tp, fp, fn, idsw = c["num_detections"], c["num_false_positives"], c["num_misses"], c["num_switches"]
    gt, idtp, idfp, idfn = c["num_objects"], c["idtp"], c["idfp"], c["idfn"]
    mean_dist = c["motp_dist_sum"] / tp if tp else np.nan
    row = {
        "MOTA": 1.0 - (fn + fp + idsw) / gt if gt else np.nan,
        "MOTP": mean_dist if center else 1.0 - mean_dist,
        "IDF1": 2 * idtp / (2 * idtp + idfp + idfn) if (idtp + idfp + idfn) else np.nan,
        "IDP": idtp / (idtp + idfp) if (idtp + idfp) else np.nan,
        "IDR": idtp / (idtp + idfn) if (idtp + idfn) else np.nan,
        "Rcll": tp / gt if gt else np.nan,
        "Prcn": tp / (tp + fp) if (tp + fp) else np.nan,
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "IDSW": idsw,
        "Frag": c["num_fragmentations"],
        "GT": gt,
        "Dets": c["num_predictions"],
        "GT_IDs": c["num_unique_objects"],
        "IDs": c["num_dt_ids"],
        "MT": c["mostly_tracked"],
        "PT": c["partially_tracked"],
        "ML": c["mostly_lost"],
        "Frames": c["num_frames"],
    }
    if hota:
        deta = c["hota_tp"] / np.maximum(1.0, c["hota_tp"] + c["hota_fn"] + c["hota_fp"])
        assa = c["assa_weighted"] / np.maximum(1e-10, c["hota_tp"])
        row.update({"HOTA": float(np.mean(np.sqrt(deta * assa))), "DetA": float(np.mean(deta)), "AssA": float(np.mean(assa)), "_hota_alpha": np.sqrt(deta * assa)})
    return row


def evaluate(gts: Mapping[str, pd.DataFrame], preds: Mapping[str, pd.DataFrame], iou_threshold: float = 0.5, hota: bool = True, n_jobs: int | None = None, max_center_dist: float | None = None) -> pd.DataFrame:
    """Score each sequence in ``gts`` against ``preds`` (a missing prediction counts as empty).

    Returns one row per sequence plus "OVERALL", with COLUMNS (HOTA, DetA and AssA only when hota is true).
    ``attrs["hota_alpha"]`` holds each row's HOTA at every threshold in HOTA_ALPHAS. With max_center_dist (pixels),
    CLEAR-MOT and IDF1 match box centres instead of IoU, HOTA is skipped and MOTP is the mean centre distance.
    """
    names = list(gts)
    if not names:
        raise ValueError("no ground-truth sequences to evaluate")
    center = max_center_dist is not None
    hota = hota and not center
    empty = pd.DataFrame(columns=["frame", "id", "x", "y", "w", "h"])
    tasks = [(n, gts[n], preds.get(n, empty), iou_threshold, hota, max_center_dist) for n in names]
    n_jobs = n_jobs or min(len(tasks), max(1, (os.cpu_count() or 2) // 2))
    if n_jobs == 1 or len(tasks) == 1:
        results = [_score_sequence(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=n_jobs) as pool:
            results = list(pool.map(_score_sequence, tasks))

    summed_keys = ["num_frames", "num_objects", "num_predictions", "num_unique_objects", "num_dt_ids", "num_detections", "num_switches", "num_false_positives", "num_misses", "num_fragmentations", "mostly_tracked", "partially_tracked", "mostly_lost", "idtp", "idfp", "idfn", "motp_dist_sum"]
    rows, total = {}, None
    for r in results:
        r["motp_dist_sum"] = (r["motp"] if np.isfinite(r["motp"]) else 0.0) * r["num_detections"]
        if hota:
            r["assa_weighted"] = np.nan_to_num(r["assa"]) * r["hota_tp"]
        rows[r["name"]] = _row(r, hota, center)
        keys = summed_keys + (["hota_tp", "hota_fn", "hota_fp", "assa_weighted"] if hota else [])
        total = {k: r[k] for k in keys} if total is None else {k: total[k] + r[k] for k in keys}
    rows["OVERALL"] = _row(total, hota, center)

    alpha = {k: v.pop("_hota_alpha").tolist() for k, v in rows.items()} if hota else {}
    table = pd.DataFrame.from_dict(rows, orient="index")
    table = table[[c for c in COLUMNS if c in table.columns]]
    table.attrs["hota_alpha"] = alpha
    table.attrs["iou_threshold"] = iou_threshold
    table.attrs["max_center_dist"] = max_center_dist
    return table


def format_table(table: pd.DataFrame) -> str:
    """The table with rates as percentages (one decimal) and counts as integers; a centre-mode MOTP in pixels."""
    center = table.attrs.get("max_center_dist") is not None
    rates = ["HOTA", "DetA", "AssA", "MOTA", "MOTP", "IDF1", "IDP", "IDR", "Rcll", "Prcn"]
    if center:
        rates.remove("MOTP")
    out = table.copy()
    if center:
        out["MOTP"] = out["MOTP"].map(lambda v: f"{v:.1f}px" if pd.notna(v) else "-")
    for c in [c for c in out.columns if not (center and c == "MOTP")]:
        out[c] = out[c].map(lambda v: f"{100 * v:.1f}" if pd.notna(v) else "-") if c in rates else out[c].map(lambda v: f"{int(v)}" if pd.notna(v) else "-")
    return out.to_string()
