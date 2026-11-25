"""Tests for flocker.render (dots, empty-pitch background, speed-up).

Project: Flocker
File: tests/test_render.py
Purpose: on a tiny synthetic video: the median erases a moving object, speed-up keeps every Nth frame, dots land
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)
"""

import cv2
import numpy as np
import pandas as pd
import pytest

from flocker.mot import PLAYER
from flocker.render import median_background, render_dots

pytestmark = pytest.mark.unit
W, H, N = 160, 96, 24


@pytest.fixture
def moving_square(tmp_path):
    """A grey field with a white 10 px square crossing it left to right, one step per frame (MJPG .avi)."""
    path = tmp_path / "square.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (W, H))
    rows = []
    for f in range(1, N + 1):
        img = np.full((H, W, 3), 100, np.uint8)
        x = 5 * f
        img[40:50, x : x + 10] = 255
        writer.write(img)
        rows.append({"frame": f, "id": 1, "x": float(x), "y": 40.0, "w": 10.0, "h": 10.0, "cls": PLAYER, "team": 0})
    writer.release()
    return path, pd.DataFrame(rows)


def test_median_erases_the_moving_object(moving_square):
    path, _ = moving_square
    bg = median_background(path, (W, H), samples=N)
    assert abs(int(bg[45, 12].mean()) - 100) <= 3  # where the square was at frame 1: back to the grey field
    first = cv2.VideoCapture(str(path)).read()[1]
    assert int(first[45, 12].mean()) > 200  # ...and the square really was there


def test_speed_up_keeps_every_nth_frame_and_draws_dots(moving_square, tmp_path):
    path, tracks = moving_square
    out = render_dots(path, tracks, tmp_path / "dots.mp4", speed=4, background="median", width=W, radius=4)
    cap = cv2.VideoCapture(str(out))
    frames = []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        frames.append(img)
    assert len(frames) == N // 4  # frames 1, 5, 9, ...
    cx = int(tracks.loc[0, "x"] + 5)  # frame 1's square centre, where the first output frame's dot sits
    b, g, r = (int(v) for v in frames[0][45, cx])
    assert r > 150 and b < 120  # team 0's red dot, not the grey field


def test_pitch_view_puts_dots_at_their_pitch_positions(moving_square, tmp_path):
    """A 'pitch' 16 x 9.6 m filling the 160 x 96 px video at 10 px per metre: in the pitch view (4 m margins, 240 px wide,
    so 10 px per metre again) frame 1's square, centred at pixel (10, 45), is at pitch (-7, -0.3) m and canvas (50, 85)."""
    from flocker.pitch import H_COLUMNS

    path, tracks = moving_square
    h = np.array([[0.1, 0, -8.0], [0, 0.1, -4.8], [0, 0, 1.0]])  # image pixels -> pitch metres
    table = pd.DataFrame([{"frame": f, **dict(zip(H_COLUMNS, h.ravel()))} for f in range(1, N + 1)])
    for background in ("pitch", "frame"):
        out = render_dots(path, tracks, tmp_path / f"pitch_{background}.mp4", speed=4, background=background, width=240, radius=4, pitch=(table, 16.0, 9.6), view="pitch", lines=True)
        first = cv2.VideoCapture(str(out)).read()[1]
        assert first.shape[:2] == (176, 240)
        b, g, r = (int(v) for v in first[85, 50])
        assert r > 150 and b < 120  # team 0's red dot
    with pytest.raises(ValueError):
        render_dots(path, tracks, tmp_path / "x.mp4", view="pitch")  # the pitch view needs homographies
