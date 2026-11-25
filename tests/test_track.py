"""Tests for flocker.track (tracking replayed from cached detections).

Project: Flocker
File: tests/test_track.py
Purpose: identities kept, classes tracked apart, box sources honoured; no GPU or video needed
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)
"""

import numpy as np
import pandas as pd
import pytest

from flocker.evaluate import evaluate
from flocker.mot import BALL, PLAYER
from flocker.track import ID_OFFSET, suppress_duplicates, track_detections
from synthetic import make_tracks

pytestmark = pytest.mark.unit


def _detections():
    """Three players on random walks, and a 12 px ball rolling at a steady 2 px per frame below them."""
    players = make_tracks(n_objects=3, n_frames=30, seed=1)
    frames = np.arange(1, 31)
    ball = pd.DataFrame({"frame": frames, "x": 300.0 + 2.0 * frames, "y": 1500.0 + 1.0 * frames, "w": 12.0, "h": 12.0})
    dets = pd.concat([players.assign(id=-1, conf=0.9, cls=PLAYER), ball.assign(id=-1, conf=0.8, cls=BALL)], ignore_index=True)
    return players, dets


@pytest.mark.parametrize("tracker", ["bytetrack", "botsort"])
def test_identities_kept_and_classes_apart(tracker):
    players, dets = _detections()
    tracks = track_detections(dets, tracker=tracker, n_frames=30)
    p, b = tracks[tracks["cls"] == PLAYER], tracks[tracks["cls"] == BALL]
    assert p["id"].nunique() == 3 and (p["id"] < ID_OFFSET).all()
    assert b["id"].nunique() == 1 and (b["id"] >= ID_OFFSET).all()
    t = evaluate({"s": players}, {"s": p}, n_jobs=1)
    assert t.loc["s", "IDSW"] == 0 and t.loc["s", "FP"] == 0
    assert t.loc["s", "Rcll"] > 0.95


def test_detection_box_source_reports_the_measurements():
    _, dets = _detections()
    tracks = track_detections(dets, n_frames=30, box_source="detection")
    pairs = tracks.reset_index().merge(dets, on=["frame", "cls"], suffixes=("", "_det"))
    same = np.isclose(pairs[["x", "y", "w", "h"]].to_numpy(), pairs[["x_det", "y_det", "w_det", "h_det"]].to_numpy(), atol=1e-6).all(axis=1)
    assert pairs[same]["index"].nunique() == len(tracks)  # every reported box is one of that frame's detections
    kalman = track_detections(dets, n_frames=30, box_source="track")
    assert not np.allclose(kalman.sort_values(["frame", "id"])["x"].to_numpy(), tracks.sort_values(["frame", "id"])["x"].to_numpy())


def test_empty_frames_age_tracks_out():
    still = pd.DataFrame({"frame": np.arange(1, 31), "id": -1, "x": 500.0, "y": 500.0, "w": 30.0, "h": 30.0, "conf": 0.9, "cls": PLAYER})
    gap = still[(still["frame"] <= 5) | (still["frame"] >= 26)]  # 20 empty frames: within ByteTrack's 30-frame buffer
    tracks = track_detections(gap, n_frames=30)
    assert tracks["id"].nunique() == 1
    short = track_detections(gap, n_frames=30, track_buffer=5)  # a 5-frame buffer forgets it
    assert short["id"].nunique() == 2


def test_suppress_duplicates_is_greedy_nms_per_frame_and_class():
    """Boxes 30 x 30. A (0.9) at x 0; B (0.8) at x 8: IoU(A, B) = 22 / 38 = 0.579; C (0.7) at x 16: IoU(B, C) 0.579 and
    IoU(A, C) = 14 / 46 = 0.304. At 0.5, A suppresses B, and B, being suppressed, cannot suppress C. At 0.6 all three
    stay. A ball box on top of A and a copy of B in another frame are untouched."""
    rows = [(1, 0.0, 0.9, PLAYER), (1, 8.0, 0.8, PLAYER), (1, 16.0, 0.7, PLAYER), (1, 2.0, 0.6, BALL), (2, 8.0, 0.8, PLAYER)]
    dets = pd.DataFrame([{"frame": f, "id": -1, "x": x, "y": 100.0, "w": 30.0, "h": 30.0, "conf": c, "cls": k} for f, x, c, k in rows])
    kept = suppress_duplicates(dets, 0.5)
    assert sorted(zip(kept["frame"], kept["x"], kept["cls"])) == [(1, 0.0, PLAYER), (1, 2.0, BALL), (1, 16.0, PLAYER), (2, 8.0, PLAYER)]
    assert len(suppress_duplicates(dets, 0.6)) == 5
    assert len(suppress_duplicates(dets, 0.25)) == 3  # A now also suppresses C; the ball and frame 2 remain
