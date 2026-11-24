"""Tests for flocker.yolo_dataset (tiling and labels).

Project: Flocker
File: tests/test_yolo_dataset.py
Purpose: tile placement over 4K frames and the visibility rule for labels cut by tile edges
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)
"""

import pandas as pd
import pytest

from flocker.mot import BALL, PLAYER
from flocker.yolo_dataset import tile_labels, tile_origins

pytestmark = pytest.mark.unit


def test_tile_origins_cover_4k_with_overlap():
    xs, ys = tile_origins(3840, 1280, 256), tile_origins(2160, 1280, 256)
    assert xs == [0, 853, 1707, 2560] and ys == [0, 880]
    for o in (xs, ys):
        assert all(b - a <= 1280 - 256 for a, b in zip(o, o[1:]))  # neighbours overlap by at least 256 px
    assert xs[-1] + 1280 == 3840 and ys[-1] + 1280 == 2160
    assert tile_origins(1000, 1280, 256) == [0]


def _box(x, y, w=30, h=30, cls=PLAYER):
    return pd.DataFrame({"x": [float(x)], "y": [float(y)], "w": [float(w)], "h": [float(h)], "cls": [cls]})


def test_label_inside_a_tile_is_normalised():
    (line,) = tile_labels(_box(1000, 960, cls=BALL), x0=853, y0=880, tile=1280)
    c, cx, cy, w, h = line.split()
    assert int(c) == BALL
    assert float(cx) == pytest.approx((1015 - 853) / 1280, abs=1e-6) and float(cy) == pytest.approx((975 - 880) / 1280, abs=1e-6)
    assert float(w) == pytest.approx(30 / 1280, abs=1e-6) and float(h) == pytest.approx(30 / 1280, abs=1e-6)


def test_visibility_rule_at_tile_edges():
    assert len(tile_labels(_box(1265, 100), 0, 0, 1280)) == 1  # 15 of 30 px inside: exactly half, kept
    assert tile_labels(_box(1268, 100), 0, 0, 1280) == []  # 12 of 30 px inside: dropped
    (line,) = tile_labels(_box(1265, 100), 0, 0, 1280)
    assert float(line.split()[3]) == pytest.approx(15 / 1280, abs=1e-6)  # the label is clipped to the tile
    assert tile_labels(_box(5000, 100), 0, 0, 1280) == []
