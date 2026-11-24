"""Tests for flocker.mot (MOTChallenge text I/O).

Project: Flocker
File: tests/test_mot.py
Purpose: round-trips, column defaults, empty and malformed files
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)
"""

import numpy as np
import pandas as pd
import pytest

from flocker.mot import MOT_COLUMNS, UNKNOWN, centers, read_mot, write_mot

pytestmark = pytest.mark.unit


def test_round_trip_keeps_values(tmp_path):
    df = pd.DataFrame({"frame": [2, 1, 1], "id": [5, 7, 5], "x": [10.123, 20.0, 30.5], "y": [1.0, 2.0, 3.0], "w": [30.0, 31.0, 32.0], "h": [28.0, 29.0, 30.0], "conf": [0.9, 0.8, 0.7], "cls": [0, 1, 0]})
    back = read_mot(write_mot(df, tmp_path / "sub" / "t.txt"))
    assert list(back.columns) == MOT_COLUMNS
    assert back[["frame", "id"]].values.tolist() == [[1, 5], [1, 7], [2, 5]]  # sorted by frame, then id
    assert back["x"].tolist() == [30.5, 20.0, 10.12]  # boxes are written to 2 decimals
    assert back["cls"].tolist() == [0, 1, 0]


def test_six_column_file_gets_defaults(tmp_path):
    p = tmp_path / "six.txt"
    p.write_text("1,3,10,20,30,40\n2,3,11,21,30,40\n")
    df = read_mot(p)
    assert df["conf"].tolist() == [1.0, 1.0]
    assert df["cls"].tolist() == [UNKNOWN, UNKNOWN]


def test_empty_file_gives_empty_frame(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("")
    df = read_mot(p)
    assert df.empty and list(df.columns) == MOT_COLUMNS


def test_wrong_column_count_is_refused(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("1,2,3,4,5\n")
    with pytest.raises(ValueError, match="5 columns"):
        read_mot(p)


def test_centers():
    df = pd.DataFrame({"x": [0.0, 10.0], "y": [0.0, 20.0], "w": [4.0, 6.0], "h": [2.0, 8.0]})
    assert np.allclose(centers(df), [[2.0, 1.0], [13.0, 24.0]])
