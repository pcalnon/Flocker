"""Integration tests: the evaluation on real TeamTrack ground truth, perturbed in ways with known effects.

Project: Flocker
File: tests/test_evaluate_teamtrack.py
Purpose: prove on real data that the metrics reward the truth and catch misses, identity swaps and offsets
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

Two test-split sequences (39,555 player boxes); about a minute and a half with HOTA.
"""

import numpy as np
import pytest

from flocker.evaluate import evaluate
from flocker.teamtrack import list_sequences, load_gt

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module")
def gts():
    from flocker.paths import teamtrack_root

    seqs = list_sequences(teamtrack_root(), "test")[:2]
    if not seqs:
        pytest.skip("TeamTrack test split not found")
    return {s.name: load_gt(s, objects="players") for s in seqs}


def test_truth_scores_one(gts):
    t = evaluate(gts, gts)
    for k in ["HOTA", "DetA", "AssA", "MOTA", "MOTP", "IDF1"]:
        assert t.loc["OVERALL", k] == pytest.approx(1.0), k
    assert t.loc["OVERALL", "GT_IDs"] == 44  # 22 players in each of the two sequences


def test_dropped_rows_are_misses(gts):
    preds = {k: v.drop(index=v.index[::10]) for k, v in gts.items()}
    t = evaluate(gts, preds)
    dropped = sum(len(v.index[::10]) for v in gts.values())
    gt_total = sum(len(v) for v in gts.values())
    assert t.loc["OVERALL", "FN"] == dropped
    assert (t.loc["OVERALL", "FP"], t.loc["OVERALL", "IDSW"]) == (0, 0)
    assert t.loc["OVERALL", "MOTA"] == pytest.approx(1 - dropped / gt_total)
    # Every kept box matches exactly (IoU 1), so all 19 thresholds agree. DetA = kept / GT. Each object keeps
    # m of its g frames under its own id, so each of its m matches has association IoU m / g, and
    # AssA = sum(m^2 / g) / sum(m): a little above 0.9, because the kept fraction varies between objects.
    kept = {k: (preds[k].groupby("id").size(), v.groupby("id").size()) for k, v in gts.items()}
    assa = sum(float((m**2 / g).sum()) for m, g in kept.values()) / sum(float(m.sum()) for m, _ in kept.values())
    deta = 1 - dropped / gt_total
    assert t.loc["OVERALL", "DetA"] == pytest.approx(deta)
    assert t.loc["OVERALL", "AssA"] == pytest.approx(assa)
    assert t.loc["OVERALL", "HOTA"] == pytest.approx(np.sqrt(deta * assa))


def test_identity_swap_is_two_switches(gts):
    name, gt = next(iter(gts.items()))
    frames = gt["frame"].nunique()
    full = [i for i, n in gt.groupby("id").size().items() if n == frames]
    a, b = full[0], full[-1]
    half = frames // 2
    pred = gt.copy()
    late = pred["frame"] > half
    pred.loc[late & (gt["id"] == a), "id"] = b
    pred.loc[late & (gt["id"] == b), "id"] = a
    t = evaluate({name: gt}, {name: pred}, n_jobs=1)
    assert t.loc[name, "IDSW"] == 2
    assert t.loc[name, "MOTA"] == pytest.approx(1 - 2 / len(gt))
    lost = 2 * (frames - half)  # each swapped object keeps one id for only half the clip
    assert t.loc[name, "IDF1"] == pytest.approx(1 - lost / len(gt))
    assert t.loc[name, "DetA"] == pytest.approx(1.0)
    assert t.loc[name, "AssA"] < 1.0


def test_offsets_lower_localisation_not_detection(gts):
    def shifted(px):
        return {k: v.assign(x=v["x"] + px) for k, v in gts.items()}

    small, large = evaluate(gts, shifted(1.0)), evaluate(gts, shifted(3.0))
    for t in (small, large):
        assert t.loc["OVERALL", "MOTA"] == pytest.approx(1.0)  # still IoU >= 0.5 for 30 px boxes
    assert large.loc["OVERALL", "MOTP"] < small.loc["OVERALL", "MOTP"] < 1.0
    assert large.loc["OVERALL", "HOTA"] < small.loc["OVERALL", "HOTA"] < 1.0
    curve = np.array(large.attrs["hota_alpha"]["OVERALL"])
    assert curve[0] == pytest.approx(1.0) and curve[-1] < 0.05  # every threshold up to 0.05 matches; 0.95 almost none
