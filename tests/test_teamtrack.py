"""Tests for flocker.teamtrack (sequence discovery and ground truth).

Project: Flocker
File: tests/test_teamtrack.py
Purpose: unit tests on a synthetic TeamTrack tree; integration tests that pin the facts the module relies on
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)
"""

import numpy as np
import pandas as pd
import pytest

from flocker.mot import BALL, PLAYER
from flocker.teamtrack import BALL_ID, find_sequence, list_sequences, load_gt, select_objects, team_of
from synthetic import make_tracks, write_teamtrack_sequence


@pytest.mark.unit
def test_team_of():
    assert team_of([0, 10, 11, 21, 22]).tolist() == [0, 0, 1, 1, -1]


@pytest.mark.unit
def test_list_and_load_synthetic(tmp_path):
    gt = make_tracks(n_objects=23, n_frames=12)
    write_teamtrack_sequence(tmp_path, "test", "B_seq", gt, seqlength=10)
    write_teamtrack_sequence(tmp_path, "test", "A_seq", gt, seqlength=12)
    write_teamtrack_sequence(tmp_path, "train", "C_seq", gt, seqlength=12)
    assert [s.name for s in list_sequences(tmp_path, "test")] == ["A_seq", "B_seq"]
    assert [s.split for s in list_sequences(tmp_path)] == ["train", "test", "test"]
    seq = find_sequence("B_seq", tmp_path)
    assert seq.seqinfo()["seqlength"] == 10
    df = load_gt(seq)
    assert df["frame"].max() == 10  # rows past seqlength are clipped
    assert load_gt(seq, clip=False)["frame"].max() == 12
    assert set(df.loc[df["id"] == BALL_ID, "cls"]) == {BALL}
    assert set(df.loc[df["id"] != BALL_ID, "cls"]) == {PLAYER}
    assert set(load_gt(seq, objects="ball")["id"]) == {BALL_ID}
    assert BALL_ID not in set(load_gt(seq, objects="players")["id"])


@pytest.mark.unit
def test_select_objects_rejects_unknown_kind():
    with pytest.raises(ValueError):
        select_objects(pd.DataFrame({"cls": [0]}), "referees")


@pytest.mark.unit
def test_unknown_split_is_refused(tmp_path):
    with pytest.raises(ValueError):
        list_sequences(tmp_path, "dev")


@pytest.mark.integration
def test_real_dataset_facts(real_teamtrack):
    seqs = list_sequences(real_teamtrack)
    assert [sum(s.split == k for s in seqs) for k in ("train", "val", "test")] == [42, 9, 9]
    overrun = []
    for s in seqs:
        assert s.video_path.is_file() and s.csv_path.is_file()
        info = s.seqinfo()
        assert (info["seqlength"], info["imwidth"], info["imheight"]) == (900, 3840, 2160)
        raw = load_gt(s, clip=False)
        assert sorted(raw["id"].unique()) == list(range(23))
        if raw["frame"].max() > 900:
            overrun.append(s.name)
        assert load_gt(s)["frame"].max() == 900
    assert overrun == ["D_20220220_1_0570_0600", "D_20220220_1_0600_0630", "D_20220220_1_0630_0660", "D_20220220_1_0660_0690", "D_20220220_1_0690_0720", "D_20220220_1_0720_0750"]


@pytest.mark.integration
def test_real_ids_match_csv_teams(real_teamtrack):
    """MOT ids 0-10, 11-21 and 22 are the CSV's TeamID 0, TeamID 1 and BALL columns (checked on frame 1)."""
    for s in list_sequences(real_teamtrack, "test"):
        gt = load_gt(s)
        csv = pd.read_csv(s.csv_path, header=[0, 1, 2], index_col=0)
        f1 = gt[gt["frame"] == 1]
        row = csv.loc[1]
        for r in f1.itertuples():
            hits = [team for (team, player, attr) in csv.columns if attr == "bb_left" and abs(row[(team, player, "bb_left")] - r.x) < 1 and abs(row[(team, player, "bb_top")] - r.y) < 1]
            assert len(hits) >= 1
            expected = "BALL" if r.id == BALL_ID else str(int(team_of([r.id])[0]))
            assert expected in hits, (s.name, r.id, hits)
        assert np.isfinite(f1[["x", "y", "w", "h"]].to_numpy()).all()
