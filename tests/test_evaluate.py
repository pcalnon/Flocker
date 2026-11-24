"""Tests for flocker.evaluate (HOTA, CLEAR-MOT and IDF1).

Project: Flocker
File: tests/test_evaluate.py
Purpose: hand-computed cases, the id-relabelling fix, and the overall row against motmetrics' own combination
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

Boxes are 10 x 10 unless stated. Shifting a box 4 px sideways gives IoU 60 / 140 = 0.4286, which lies between the
HOTA thresholds 0.40 and 0.45, so exactly 8 of the 19 thresholds (0.05 ... 0.40) accept the match.
"""

import math

import motmetrics as mm
import numpy as np
import pandas as pd
import pytest

from flocker.evaluate import HOTA_ALPHAS, evaluate, to_motmetrics
from synthetic import make_tracks

pytestmark = pytest.mark.unit
IOU_SHIFT4 = 60.0 / 140.0


def boxes(rows) -> pd.DataFrame:
    """rows of (frame, id, x) or (frame, id, x, y): 10 x 10 boxes."""
    out = []
    for r in rows:
        f, i, x = r[:3]
        y = r[3] if len(r) > 3 else 0.0
        out.append({"frame": f, "id": i, "x": float(x), "y": float(y), "w": 10.0, "h": 10.0})
    return pd.DataFrame(out)


def one(gt, pred, **kw) -> pd.Series:
    return evaluate({"s": gt}, {"s": pred}, n_jobs=1, **kw).loc["s"]


def test_perfect_tracking_scores_one():
    gt = make_tracks()
    row = one(gt, gt)
    for k in ["HOTA", "DetA", "AssA", "MOTA", "MOTP", "IDF1", "IDP", "IDR", "Rcll", "Prcn"]:
        assert row[k] == pytest.approx(1.0), k
    assert (row["FP"], row["FN"], row["IDSW"], row["GT"], row["MT"], row["GT_IDs"]) == (0, 0, 0, 240, 6, 6)


def test_split_track():
    """One object over 4 frames, tracked as id 1 then id 2 with exact boxes.

    CLEAR: 4 TP, 1 IDSW -> MOTA 0.75. IDF1: the object can keep only one tracker id -> IDTP 2, IDFN 2, IDFP 2 -> 0.5.
    HOTA: DetA 1; each TP's association IoU is 2 / (4 + 2 - 2) = 0.5 -> AssA 0.5, HOTA sqrt(0.5).
    """
    gt = boxes([(f, 7, 0) for f in range(1, 5)])
    pred = boxes([(1, 1, 0), (2, 1, 0), (3, 2, 0), (4, 2, 0)])
    row = one(gt, pred)
    assert (row["TP"], row["IDSW"]) == (4, 1)
    assert row["MOTA"] == pytest.approx(0.75)
    assert row["IDF1"] == pytest.approx(0.5)
    assert row["DetA"] == pytest.approx(1.0)
    assert row["AssA"] == pytest.approx(0.5)
    assert row["HOTA"] == pytest.approx(math.sqrt(0.5))


def test_localisation_below_the_clear_threshold():
    """IoU 0.4286 in every frame: no CLEAR match at 0.5, but HOTA accepts it at 8 of 19 thresholds."""
    gt = boxes([(f, 0, 0) for f in range(1, 6)])
    pred = boxes([(f, 0, 4) for f in range(1, 6)])
    row = one(gt, pred)
    assert (row["TP"], row["FN"], row["FP"]) == (0, 5, 5)
    assert row["MOTA"] == pytest.approx(-1.0)
    assert np.isnan(row["MOTP"])
    assert row["HOTA"] == pytest.approx(8 / 19)
    assert row["DetA"] == pytest.approx(8 / 19)
    assert row["AssA"] == pytest.approx(8 / 19)
    lenient = one(gt, pred, iou_threshold=0.4)
    assert lenient["MOTA"] == pytest.approx(1.0)
    assert lenient["MOTP"] == pytest.approx(IOU_SHIFT4)


def test_misses_and_false_positives():
    gt = boxes([(f, 0, 0) for f in range(1, 5)])
    missed = one(gt, boxes([(f, 0, 0) for f in range(1, 4)]))
    assert (missed["FN"], missed["Rcll"], missed["Prcn"], missed["MOTA"]) == (1, 0.75, 1.0, 0.75)
    assert missed["HOTA"] == pytest.approx(0.75)  # DetA 3/4; association IoU 3 / (4 + 3 - 3) = 0.75
    extra = one(gt, pd.concat([gt, boxes([(f, 9, 500) for f in range(1, 5)])]))
    assert (extra["FP"], extra["Prcn"], extra["MOTA"]) == (4, 0.5, 0.0)
    assert extra["HOTA"] == pytest.approx(math.sqrt(0.5))  # DetA 4 / (4 + 4); AssA 1


def test_center_matching_ignores_box_size():
    """A 28 x 28 box centred in a 42 x 40 one (TeamTrack's 1770_1800 convention): IoU 784 / 1680 = 0.467."""
    gt = pd.DataFrame([{"frame": f, "id": 0, "x": 0.0, "y": 0.0, "w": 42.0, "h": 40.0} for f in range(1, 6)])
    pred = pd.DataFrame([{"frame": f, "id": 3, "x": 7.0, "y": 6.0, "w": 28.0, "h": 28.0} for f in range(1, 6)])
    assert one(gt, pred)["MOTA"] == pytest.approx(-1.0)  # by IoU every frame is a miss plus a false positive
    near = evaluate({"s": gt}, {"s": pred}, n_jobs=1, max_center_dist=5.0).loc["s"]
    assert (near["MOTA"], near["IDF1"], near["MOTP"]) == (1.0, 1.0, 0.0)  # MOTP: mean centre distance, px
    assert "HOTA" not in near.index
    far = evaluate({"s": gt}, {"s": pred.assign(x=pred["x"] + 6)}, n_jobs=1, max_center_dist=5.0).loc["s"]
    assert far["MOTA"] == pytest.approx(-1.0)  # centres 6 px apart: beyond 5 px


def test_missing_prediction_counts_as_empty():
    gt = make_tracks(n_objects=2, n_frames=5)
    table = evaluate({"a": gt, "b": gt}, {"a": gt}, n_jobs=1)
    assert (table.loc["b", "FN"], table.loc["b", "Rcll"]) == (10, 0.0)
    assert table.loc["OVERALL", "Rcll"] == pytest.approx(0.5)
    assert table.loc["b", "HOTA"] == 0.0


def _ambiguous_scene(gt_ids):
    """Two objects, apart for 10 frames, then 4 px apart in frame 11, where the two predictions swap places.

    Similarity alone prefers the swap (IoU 1 against 0.4286); the global alignment score built over frames 1-10
    keeps each object with its own prediction. Ground-truth ids are ``gt_ids`` = (a, b).
    """
    a, b = gt_ids
    gt = boxes([(f, a, 0) for f in range(1, 12)] + [(f, b, 100) for f in range(1, 11)] + [(11, b, 4)])
    pred = boxes([(f, 1, 0) for f in range(1, 11)] + [(11, 1, 4)] + [(f, 2, 100) for f in range(1, 11)] + [(11, 2, 0)])
    return gt, pred


def _raw_motmetrics_hota(gt, pred):
    """motmetrics' HOTA with the ids exactly as given (no relabelling)."""

    def layout(df):
        return df.rename(columns={"frame": "FrameId", "id": "Id", "x": "X", "y": "Y", "w": "Width", "h": "Height"}).set_index(["FrameId", "Id"])[["X", "Y", "Width", "Height"]]

    mh = mm.metrics.create()
    accs = mm.utils.compare_to_groundtruth_reweighting(layout(gt), layout(pred), "iou", distth=list(HOTA_ALPHAS))
    return float(np.mean([mh.compute(acc, metrics=["hota_alpha"], return_dataframe=False)["hota_alpha"] for acc in accs]))


def test_zero_based_ids_need_relabelling():
    """Ground-truth ids (0, 2) make motmetrics index rows -1 and 1 of a 2-row matrix: both land on row 1.

    If this assertion on raw motmetrics ever fails, upstream has fixed the indexing and the relabelling in
    flocker.evaluate.to_motmetrics is no longer needed (it stays harmless).
    """
    raw_zero_based = _raw_motmetrics_hota(*_ambiguous_scene((0, 2)))
    raw_one_based = _raw_motmetrics_hota(*_ambiguous_scene((1, 3)))
    assert raw_zero_based != pytest.approx(raw_one_based)
    ours_zero = one(*_ambiguous_scene((0, 2)))
    ours_one = one(*_ambiguous_scene((1, 3)))
    assert ours_zero["HOTA"] == pytest.approx(ours_one["HOTA"])
    assert ours_zero["HOTA"] == pytest.approx(raw_one_based)
    assert ours_zero.drop(["HOTA", "DetA", "AssA"]).equals(ours_one.drop(["HOTA", "DetA", "AssA"]))


def test_relabelling_is_contiguous_and_one_based():
    df = boxes([(1, 0, 0), (1, 22, 50), (2, 22, 50), (2, 5, 90)])
    assert sorted(to_motmetrics(df).index.get_level_values("Id").unique()) == [1, 2, 3]


def _noisy(gt: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Jittered boxes, 10 % misses, one id switch half-way and 15 false positives."""
    rng = np.random.default_rng(seed)
    pred = gt.copy()
    pred[["x", "y"]] += rng.normal(0, 2.5, (len(pred), 2))
    pred = pred[rng.random(len(pred)) > 0.1].copy()
    first = pred["id"].min()
    pred.loc[(pred["id"] == first) & (pred["frame"] > gt["frame"].max() // 2), "id"] = 100
    n = 15
    fp = pd.DataFrame({"frame": rng.integers(1, gt["frame"].max() + 1, n), "id": 200 + np.arange(n), "x": rng.uniform(0, 1500, n), "y": rng.uniform(0, 1000, n), "w": 30.0, "h": 30.0})
    return pd.concat([pred, fp], ignore_index=True)


def test_overall_row_matches_motmetrics_combination():
    """The overall row, built from summed counts, equals motmetrics' compute_many(generate_overall=True)."""
    gts = {f"s{k}": make_tracks(n_objects=5, n_frames=30, seed=k) for k in range(3)}
    preds = {k: _noisy(v, seed=10 + i) for i, (k, v) in enumerate(gts.items())}
    ours = evaluate(gts, preds, n_jobs=1)

    mh = mm.metrics.create()
    names = list(gts)
    g = {k: to_motmetrics(v) for k, v in gts.items()}
    p = {k: to_motmetrics(v) for k, v in preds.items()}
    accs = [mm.utils.compare_to_groundtruth(g[k], p[k], "iou", distth=0.5) for k in names]
    ref = mh.compute_many(accs, names=names, metrics=["mota", "motp", "idf1", "recall", "precision", "num_switches", "num_false_positives", "num_misses"], generate_overall=True)
    for name in names + ["OVERALL"]:
        assert ours.loc[name, "MOTA"] == pytest.approx(ref.loc[name, "mota"])
        assert ours.loc[name, "MOTP"] == pytest.approx(1 - ref.loc[name, "motp"])
        assert ours.loc[name, "IDF1"] == pytest.approx(ref.loc[name, "idf1"])
        assert (ours.loc[name, "IDSW"], ours.loc[name, "FP"], ours.loc[name, "FN"]) == (ref.loc[name, "num_switches"], ref.loc[name, "num_false_positives"], ref.loc[name, "num_misses"])

    per_alpha = []
    hota_accs = {k: mm.utils.compare_to_groundtruth_reweighting(g[k], p[k], "iou", distth=list(HOTA_ALPHAS)) for k in names}
    for a in range(len(HOTA_ALPHAS)):
        per_alpha.append(mh.compute_many([hota_accs[k][a] for k in names], names=names, metrics=["hota_alpha", "deta_alpha", "assa_alpha"], generate_overall=True))
    for name in names + ["OVERALL"]:
        assert ours.loc[name, "HOTA"] == pytest.approx(np.mean([s.loc[name, "hota_alpha"] for s in per_alpha]))
        assert ours.loc[name, "DetA"] == pytest.approx(np.mean([s.loc[name, "deta_alpha"] for s in per_alpha]))
        assert ours.loc[name, "AssA"] == pytest.approx(np.mean([s.loc[name, "assa_alpha"] for s in per_alpha]))
    assert 0.3 < ours.loc["OVERALL", "HOTA"] < 0.95  # the noise must actually cost something


def test_parallel_equals_serial():
    gts = {f"s{k}": make_tracks(n_objects=4, n_frames=20, seed=k) for k in range(3)}
    preds = {k: _noisy(v, seed=20 + i) for i, (k, v) in enumerate(gts.items())}
    assert evaluate(gts, preds, n_jobs=1).equals(evaluate(gts, preds, n_jobs=3))
