"""Tests for flocker.team (kit colours and team labels) and team-aware tracking.

Project: Flocker
File: tests/test_team.py
Purpose: foreground colour against the background, the two-team model's outlier handling, track majority votes,
    and team gating in the tracker; no GPU or video needed
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

The colours are TeamTrack's, measured on D_20220220_1_1260_1290 (OpenCV 8-bit Lab): white kits about (195, 122, 133),
blue kits about (140, 122, 122), the red goalkeeper (139, 139, 132) and the yellow one (178, 115, 162).
"""

import cv2
import numpy as np
import pandas as pd
import pytest

from flocker.evaluate import evaluate
from flocker.mot import PLAYER
from flocker.team import OTHER, box_colours, fit_teams
from flocker.track import track_detections, track_teams

pytestmark = pytest.mark.unit
WHITE, BLUE, RED_GK, YELLOW_GK = (195.0, 122.0, 133.0), (140.0, 122.0, 122.0), (139.0, 139.0, 132.0), (178.0, 115.0, 162.0)


def test_box_colours_measures_the_player_not_the_pitch():
    bg = np.full((100, 100, 3), (40, 140, 60), np.uint8)  # green pitch, BGR
    frame = bg.copy()
    frame[40:50, 40:50] = (255, 255, 255)  # a white player, 10 x 10, inside a 30 x 30 box
    bg_lab = cv2.cvtColor(bg, cv2.COLOR_BGR2LAB).astype(np.float32)
    out = box_colours(frame, bg_lab, np.array([[30, 30, 60, 60], [0, 0, 20, 20], [95, 95, 140, 140]]))
    assert out[0, 3] == 100 and out[0, :3] == pytest.approx([255, 128, 128], abs=1)  # only the 100 white pixels
    assert out[1, 3] == 0 and np.isnan(out[1, :3]).all()  # empty pitch: no colour
    assert out[2, 3] == 0  # a box running off the frame is clipped to it


def _kits(rng, n=400):
    """Two outfield kits with Lab noise, and both goalkeepers at a tenth of a team's count each."""
    noise = np.array([8.0, 1.5, 2.0])
    parts = [np.array(c) + rng.normal(0, 1, (m, 3)) * noise for c, m in ((WHITE, n), (BLUE, n), (RED_GK, n // 10), (YELLOW_GK, n // 10))]
    return np.vstack(parts), np.repeat([0, 1, 2, 3], [n, n, n // 10, n // 10])


def test_fit_teams_keeps_goalkeepers_out_of_the_teams():
    x, who = _kits(np.random.default_rng(0))
    model = fit_teams(np.vstack([x, [[np.nan] * 3]]))
    team = model.predict(x)
    assert np.mean(team[who == 0] == 0) > 0.97 and np.mean(team[who == 1] == 1) > 0.97  # team 0 is the brighter kit
    assert (team[who >= 2] == OTHER).all()
    nearest = np.argmin(np.linalg.norm(x[who == 2][:, None] - model.means[None], axis=2), axis=1)
    assert (nearest == 1).all()  # plain nearest-mean would put the red goalkeeper in the blue team
    assert model.predict(np.array([[np.nan] * 3]))[0] == OTHER


def test_track_teams_is_a_majority_with_unknowns_abstaining():
    ids = pd.Series([1, 1, 1, 1, 2, 2, 3, 3])
    det = pd.Series([0, 0, 1, -1, -1, -1, 1, 0])
    assert track_teams(det, ids).tolist() == [0, 0, 0, 0, -1, -1, 0, 0]  # a 1-1 tie goes to team 0 at purity 0.5
    assert track_teams(det, ids, purity=0.7).tolist() == [-1, -1, -1, -1, -1, -1, -1, -1]


def _trade_places():
    """Players 0 (team 0) and 1 (team 1), 30 x 30 boxes 14 px apart for 20 frames, then trading places in one frame
    and standing there for 20 more. Each track overlaps the box where it stood by IoU 1 and the other by 16 / 44 = 0.36,
    so IoU association swaps the identities. (At 10 px apart the IoU would be exactly 0.5, and scoring at IoU >= 0.5
    would keep the old matches and count no switch.)"""
    rows = []
    for f in range(1, 41):
        a, b = (100.0, 114.0) if f <= 20 else (114.0, 100.0)
        rows += [(f, 0, a, 0), (f, 1, b, 1)]
    gt = pd.DataFrame([{"frame": f, "id": i, "x": x, "y": 500.0, "w": 30.0, "h": 30.0} for f, i, x, _ in rows])
    dets = pd.DataFrame([{"frame": f, "id": -1, "x": x, "y": 500.0, "w": 30.0, "h": 30.0, "conf": 0.8, "cls": PLAYER, "team": t} for f, _, x, t in rows])
    return gt, dets


def test_team_gate_prevents_a_swap_that_iou_makes():
    gt, dets = _trade_places()
    plain = track_detections(dets, n_frames=40, fuse_score=False, match_thresh=0.9)
    gated = track_detections(dets, n_frames=40, team_gate=True, fuse_score=False, match_thresh=0.9)
    idsw = {k: evaluate({"s": gt}, {"s": t}, n_jobs=1).loc["s", "IDSW"] for k, t in (("plain", plain), ("gated", gated))}
    assert idsw == {"plain": 2, "gated": 0}
    assert sorted(gated.groupby("id")["team"].first().tolist()) == [0, 1]  # each track keeps its player's team
    assert set(plain["team"]) <= {-1, 0, 1}


def test_team_gate_needs_teams():
    _, dets = _trade_places()
    with pytest.raises(ValueError):
        track_detections(dets.drop(columns="team"), n_frames=40, team_gate=True)


def _broad_kits_compact_keepers(seed, n=1000, keeper_share=0.12):
    """Kits with broad shading noise, and goalkeepers (one player each) whose colours are far more compact: the
    situation in which 2-means seeding picked a goalkeeper as a 'team' on 3 of TeamTrack's 9 val clips."""
    rng = np.random.default_rng(seed)
    kit, keeper, m = np.array([14.0, 1.5, 3.0]), np.array([1.0, 0.7, 0.7]), int(keeper_share * n)
    return np.vstack([np.array(WHITE) + rng.normal(0, 1, (n, 3)) * kit, np.array(BLUE) + rng.normal(0, 1, (n, 3)) * kit, np.array(RED_GK) + rng.normal(0, 1, (m, 3)) * keeper, np.array(YELLOW_GK) + rng.normal(0, 1, (m, 3)) * keeper])


def test_fit_teams_seeding_survives_compact_goalkeepers():
    for seed in range(5):
        model = fit_teams(_broad_kits_compact_keepers(seed))
        assert model.means[:, 0] == pytest.approx([195, 140], abs=6) and model.means[:, 2] == pytest.approx([133, 122], abs=3)
    refused = 0
    for seed in range(5):  # two-cluster seeding (the first version) fails here, and the share check refuses it
        try:
            fit_teams(_broad_kits_compact_keepers(seed), k=2, seeds=1)
        except ValueError:
            refused += 1
    assert refused >= 3
