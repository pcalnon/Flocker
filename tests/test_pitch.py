"""Tests for flocker.pitch: the pitch template, the image-to-pitch homography, its frame-by-frame tracking, and views.

Project: Flocker
File: tests/test_pitch.py
Purpose: the fit recovers a known homography and pitch size from a synthetic pitch image; tracking follows a known camera
    motion in a synthetic video; geometry helpers agree with each other; on TeamTrack (integration), the measured size,
    the accuracy at the centre and penalty marks, and the drone's yaw in D_20220220_1_1260_1290
Author: Paul Calnon
Created: 2026-11-25
License: CC0 1.0 (see LICENSE)
"""

import cv2
import numpy as np
import pandas as pd
import pytest

from flocker.pitch import H_COLUMNS, apply_h, draw_markings, fit_pitch, homography_from_corners, interpolate_homographies, markings, pitch_canvas, signed_residuals, spots, to_pitch_coords, track_pitch, with_pitch_positions

GRID = np.array([(x, y) for x in (-50.0, -25.0, 0.0, 25.0, 50.0) for y in (-30.0, 0.0, 30.0)])
GREEN = (70, 130, 60)


def _camera(scale=12.0, angle_deg=1.0, size=(1600, 1000), tilt=(4e-5, -2e-5), shift=(0.0, 0.0)) -> np.ndarray:
    """A pitch-to-image homography: rotation, scale and a mild perspective, centred in an image of ``size``."""
    a = np.radians(angle_deg)
    rs = scale * np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    m = np.array([[rs[0, 0], rs[0, 1], size[0] / 2 + shift[0]], [rs[1, 0], rs[1, 1], size[1] / 2 + shift[1]], [0, 0, 1.0]])
    return m @ np.array([[1, 0, 0], [0, 1, 0], [tilt[0], tilt[1], 1.0]])


def _render(h_img: np.ndarray, length: float, width: float, size=(1600, 1000), line_px: int = 3, seed: int = 0, blobs: int = 25) -> np.ndarray:
    """A grass-green image of a pitch's markings seen through h_img (pitch to image), drawn at twice the size and
    reduced (so lines are anti-aliased to sub-pixel accuracy), with grass noise and player-like blobs, some on lines."""
    rng = np.random.default_rng(seed)
    big = np.full((size[1] * 2, size[0] * 2, 3), GREEN, np.uint8)
    up = np.array([[2.0, 0, 0.5], [0, 2.0, 0.5], [0, 0, 1]])  # pixel centres: small pixel u covers big pixels 2u and 2u + 1
    draw_markings(big, up @ h_img, markings(length, width, corner_arcs=True), (235, 235, 235), 2 * line_px, step=0.05)
    for name, p in spots(length).items():
        c = apply_h(up @ h_img, [p])[0]
        cv2.circle(big, (int(round(c[0])), int(round(c[1]))), 2 * line_px, (235, 235, 235), -1, cv2.LINE_AA)
    img = cv2.resize(big, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    img += rng.normal(0, 4, img.shape)
    for p in rng.uniform([-length / 2, -width / 2], [length / 2, width / 2], (blobs, 2)):
        c = apply_h(h_img, [p])[0]
        cv2.circle(img, (int(c[0]), int(c[1])), 5, tuple(float(v) for v in rng.choice([20, 240], 3)), -1)
    return np.clip(img, 0, 255).astype(np.uint8)


@pytest.mark.unit
def test_markings_are_consistent_and_to_scale():
    marks = {m.name: m for m in markings(105.0, 68.0)}
    assert marks["touchline_top"].p0 == pytest.approx((-52.44, -33.94))  # centrelines: 6 cm inside the outer edges
    assert marks["penalty_area_left_front"].p0[0] == pytest.approx(-52.5 + 16.5 - 0.06)
    assert marks["penalty_area_right_front"].p0[0] == pytest.approx(52.5 - 16.5 + 0.06)
    assert abs(marks["penalty_area_left_front"].p0[1]) == pytest.approx(20.16 - 0.06)
    assert marks["centre_circle"].radius == pytest.approx(9.09)
    for side, sign in (("left", 1.0), ("right", -1.0)):  # each penalty arc bulges toward the halfway line, outside the area
        arc = marks[f"penalty_arc_{side}"]
        mid = np.array(arc.centre) + arc.radius * np.array([np.cos((arc.a0 + arc.a1) / 2), np.sin((arc.a0 + arc.a1) / 2)])
        assert sign * (mid[0] - arc.centre[0]) == pytest.approx(arc.radius)
        ends = np.array(arc.centre) + arc.radius * np.array([[np.cos(arc.a0), np.sin(arc.a0)], [np.cos(arc.a1), np.sin(arc.a1)]])
        assert np.abs(ends[:, 0] - marks[f"penalty_area_{side}_front"].p0[0]) == pytest.approx([0.0, 0.0], abs=0.05)
    rng = np.random.default_rng(0)
    pts = rng.uniform([-60, -40], [60, 40], (200, 2))
    names = list(marks)
    for i, name in enumerate(names):  # the vectorised residuals agree with each marking's own
        assert signed_residuals(pts, np.full(len(pts), i), 105.0, 68.0) == pytest.approx(marks[name].residual(pts))
    right_arc = marks["penalty_arc_right"]  # spans angle pi: a point on it is at distance 0, one across the circle is not
    on = np.array(right_arc.centre) + right_arc.radius * np.array([[np.cos(np.pi), np.sin(np.pi)], [np.cos(0.0), np.sin(0.0)]])
    assert right_arc.distance(on)[0] == pytest.approx(0.0, abs=1e-9) and right_arc.distance(on)[1] > 5.0


@pytest.mark.unit
def test_fit_recovers_a_known_homography_and_pitch_size():
    length, width = 104.0, 67.0  # not the starting size: the fit has to measure it
    truth = _camera()
    img = _render(truth, length, width)
    corners = apply_h(truth, [(-length / 2, -width / 2), (length / 2, -width / 2), (length / 2, width / 2), (-length / 2, width / 2)])
    start = corners + np.array([[15.0, -12.0], [-14.0, 10.0], [12.0, 15.0], [-15.0, -13.0]])  # each corner 15-20 px off
    fit, obs = fit_pitch(img, homography_from_corners(start, 105.0, 68.0), 105.0, 68.0, fit_size=True)
    assert fit.length == pytest.approx(length, abs=0.05) and fit.width == pytest.approx(width, abs=0.05)
    err = np.linalg.norm(fit.to_image(GRID) - apply_h(truth, GRID), axis=1)
    assert err.max() < 0.25, err.max()  # pixels, across the whole pitch
    assert fit.stats["rms_px"] < 0.35 and len(obs) > 600
    assert fit.scale([(0.0, 0.0)])[0] == pytest.approx(12.0, rel=0.01)


@pytest.mark.unit
def test_fit_holds_the_size_when_told_to():
    truth = _camera(angle_deg=-0.5)
    img = _render(truth, 105.0, 68.0, seed=1)
    fit, _ = fit_pitch(img, homography_from_corners(apply_h(truth, [(-52.5, -34), (52.5, -34), (52.5, 34), (-52.5, 34)]) + 6.0), 105.0, 68.0, fit_size=False)
    assert (fit.length, fit.width) == (105.0, 68.0)
    assert np.linalg.norm(fit.to_image(GRID) - apply_h(truth, GRID), axis=1).max() < 0.25


def _write_video(path, cams, length=105.0, width=68.0, size=(1600, 1000)):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, size)
    for i, h in enumerate(cams):
        writer.write(_render(h, length, width, size=size, seed=i, blobs=10))
    writer.release()


@pytest.mark.unit
def test_track_pitch_follows_the_camera(tmp_path):
    """A camera that yaws 0.15 degrees and drifts 1.5 px per frame: every frame's homography is recovered, from a
    reference fitted to frame 1 only; every=3 interpolates the frames in between."""
    cams = [_camera(angle_deg=0.15 * k, shift=(1.5 * k, -1.0 * k)) for k in range(8)]
    video = tmp_path / "pan.avi"
    _write_video(video, cams)
    first = cv2.VideoCapture(str(video)).read()[1]
    ref, _ = fit_pitch(first, homography_from_corners(apply_h(cams[0], [(-52.5, -34), (52.5, -34), (52.5, 34), (-52.5, 34)]) + 8.0), fit_size=False)
    table = track_pitch(video, ref)
    assert table["frame"].tolist() == list(range(1, 9)) and table["fitted"].all()
    for k, row in table.iterrows():
        h = row[H_COLUMNS].to_numpy(float).reshape(3, 3)
        assert np.linalg.norm(apply_h(np.linalg.inv(h), GRID) - apply_h(cams[k], GRID), axis=1).max() < 0.4
    sparse = track_pitch(video, ref, every=3)
    assert sparse["frame"].tolist() == list(range(1, 9))
    assert sparse["fitted"].tolist() == [True, False, False, True, False, False, True, True]  # frames 1, 4, 7 and the last
    for k, row in sparse.iterrows():
        h = row[H_COLUMNS].to_numpy(float).reshape(3, 3)
        assert np.linalg.norm(apply_h(np.linalg.inv(h), GRID) - apply_h(cams[k], GRID), axis=1).max() < 0.6


@pytest.mark.unit
def test_interpolation_and_per_frame_conversion():
    hs = {1: np.linalg.inv(_camera(angle_deg=0.0)), 5: np.linalg.inv(_camera(angle_deg=0.0, shift=(8.0, -4.0)))}
    table = pd.DataFrame([{"frame": f, **dict(zip(H_COLUMNS, (h / h[2, 2]).ravel())), "observations": 1, "rms_px": 0.1, "fitted": True, "restart": False} for f, h in hs.items()])
    full = interpolate_homographies(table, range(1, 7))
    assert full["frame"].tolist() == [1, 2, 3, 4, 5, 6] and full["fitted"].tolist() == [True, False, False, False, True, False]
    mid = full.loc[full["frame"] == 3, H_COLUMNS].to_numpy(float).reshape(3, 3)
    assert apply_h(np.linalg.inv(mid), [(0.0, 0.0)])[0] == pytest.approx([800 + 4.0, 500 - 2.0], abs=1e-6)  # half-way
    last = full.loc[full["frame"] == 6, H_COLUMNS].to_numpy(float).reshape(3, 3)
    assert last == pytest.approx(hs[5] / hs[5][2, 2])  # past the end: the nearest fitted frame
    pts = pd.DataFrame({"frame": [1, 5, 3], "cx": [800.0, 808.0, 804.0], "cy": [500.0, 496.0, 498.0]})
    assert to_pitch_coords(pts, full).ravel() == pytest.approx(np.zeros(6), abs=1e-6)  # the centre mark, each through its own frame
    boxes = pd.DataFrame({"frame": [1, 5, 3], "id": [7, 7, 7], "x": pts["cx"] - 10.0, "y": pts["cy"] - 20.0, "w": 20.0, "h": 40.0})
    m = with_pitch_positions(boxes, full)
    assert m[["mx", "my"]].to_numpy().ravel() == pytest.approx(np.zeros(6), abs=1e-6) and list(m["id"]) == [7, 7, 7]


@pytest.mark.unit
def test_pitch_canvas_puts_the_pitch_inside_its_margin():
    m, size = pitch_canvas(105.0, 68.0, px_per_m=10.0, margin=4.0)
    assert size == (1130, 760)
    assert apply_h(m, [(-52.5, -34.0), (52.5, 34.0)]).ravel() == pytest.approx([40.0, 40.0, 1090.0, 720.0])


@pytest.mark.unit
def test_find_spots_sees_an_error_along_the_halfway_line():
    """A fit 4 px off along the halfway line: the centre mark, which sits on that line, must show the 4 px too (the
    line's own pixels would otherwise pull the centroid back to where the fit says). Across the line the centre mark
    is not measured (it is where the line is); the penalty marks are measured both ways."""
    from flocker.pitch import PitchFit, find_spots

    truth = _camera(angle_deg=0.3)
    img = _render(truth, 105.0, 68.0, seed=2, blobs=0)
    for shift in ((0.0, 4.0), (3.0, 0.0)):  # along the (near-vertical) halfway line, and across it
        t = np.array([[1, 0, shift[0]], [0, 1, shift[1]], [0, 0, 1.0]])
        off = PitchFit(np.linalg.inv(t @ truth), 105.0, 68.0, (1600, 1000))
        found = find_spots(img, off)
        assert found["centre_mark"]["measured"] == "along halfway_line" and found["penalty_mark_left"]["measured"] == "both axes"
        assert found["centre_mark"]["error_px"] == pytest.approx(abs(shift[1]), abs=0.3), found["centre_mark"]
        for name in ("penalty_mark_left", "penalty_mark_right"):
            assert found[name]["error_px"] == pytest.approx(np.hypot(*shift), abs=0.3), (shift, name, found[name])
    exact = find_spots(img, PitchFit(np.linalg.inv(truth), 105.0, 68.0, (1600, 1000)))
    assert max(v["error_px"] for v in exact.values()) < 0.4


@pytest.mark.unit
def test_observe_centres_wide_flat_lines():
    """A 7 px line with a flat top, at x = 100.3: argmax takes the plateau's first sample, so a centroid window that is
    not re-centred is clipped on one side and lands over a pixel off."""
    from flocker.pitch import TemplateSamples, observe

    xs = np.arange(200, dtype=float)
    profile = np.clip(4.0 - np.abs(xs - 100.3), 0, 1) * 80.0  # flat top 6 px wide, ramps of 1 px: about 7 px across
    response = np.tile(profile.astype(np.float32), (60, 1))
    samples = TemplateSamples(np.column_stack([np.full(21, 100.0), np.linspace(20, 40, 21)]), np.tile([1.0, 0.0], (21, 1)), np.zeros(21, int), ("line",))
    obs = observe(response, np.eye(3), samples, search=8.0)
    assert len(obs) == 21 and obs.pts[:, 0] == pytest.approx(np.full(21, 100.3), abs=0.05)


@pytest.mark.unit
def test_track_pitch_survives_a_frame_it_cannot_fit(tmp_path):
    """A black frame (the drone's video glitching, say) is flagged failed, takes a homography interpolated from its
    neighbours, and does not stop the clip or seed the next frame."""
    cams = [_camera(angle_deg=0.1 * k, shift=(1.0 * k, 0.0)) for k in range(6)]
    video = tmp_path / "glitch.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (1600, 1000))
    for k, h in enumerate(cams):
        writer.write(np.zeros((1000, 1600, 3), np.uint8) if k == 3 else _render(h, 105.0, 68.0, seed=k, blobs=0))
    writer.release()
    first = cv2.VideoCapture(str(video)).read()[1]
    ref, _ = fit_pitch(first, homography_from_corners(apply_h(cams[0], [(-52.5, -34), (52.5, -34), (52.5, 34), (-52.5, 34)]) + 5.0), fit_size=False)
    table = track_pitch(video, ref)
    assert table["frame"].tolist() == list(range(1, 7))
    assert table["failed"].tolist() == [False, False, False, True, False, False]
    for k, row in table.iterrows():
        h = row[H_COLUMNS].to_numpy(float).reshape(3, 3)
        tol = 0.6 if k == 3 else 0.4  # frame 4 is interpolated half-way between frames 3 and 5, as the camera moved
        assert np.linalg.norm(apply_h(np.linalg.inv(h), GRID) - apply_h(cams[k], GRID), axis=1).max() < tol


@pytest.mark.unit
def test_camera_motion_yaw_does_not_wrap():
    """The pitch's x axis pointing left in the image (a camera turned 180 degrees) while yawing 0.4 degrees: the yaw
    range is 0.4, not 359.6."""
    from flocker.pitch import camera_motion

    hs = [np.linalg.inv(_camera(angle_deg=180.0 + a)) for a in (-0.2, 0.0, 0.2)]
    table = pd.DataFrame([{"frame": f, **dict(zip(H_COLUMNS, (h / h[2, 2]).ravel()))} for f, h in enumerate(hs, 1)])
    assert camera_motion(table)["yaw_deg_range"] == pytest.approx(0.4, abs=1e-6)


@pytest.mark.unit
def test_warp_area_is_an_area_reduction():
    """Shrinking by exactly 3 equals OpenCV's area resize (warpPerspective alone would sample, and alias)."""
    from flocker.pitch import warp_area

    rng = np.random.default_rng(3)
    img = rng.integers(0, 256, (90, 120, 3), dtype=np.uint8)
    third = np.array([[1 / 3, 0, -1 / 3], [0, 1 / 3, -1 / 3], [0, 0, 1.0]])  # output pixel u covers source pixels 3u..3u+2
    out = warp_area(img, third, (40, 30))
    ref = cv2.resize(img, (40, 30), interpolation=cv2.INTER_AREA)
    assert np.abs(out.astype(int) - ref.astype(int)).max() <= 1


# --- TeamTrack (real data) -------------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
def test_teamtrack_pitch_size_and_marks(real_teamtrack):
    """Frame 1 of a val clip: the size comes out as measured on all 60 clips (notes/FLOCKER_2026-11-25_PITCH-HOMOGRAPHY.md),
    the line fit is sub-pixel, and the centre and penalty marks, which the fit does not use, sit where it puts them."""
    from flocker.pitch import find_spots, line_response
    from flocker.teamtrack import PITCH_CORNERS_PX, PITCH_SIZE_M, find_sequence

    seq = find_sequence("D_20220220_1_1290_1320", real_teamtrack)
    img = cv2.VideoCapture(str(seq.video_path)).read()[1]
    fit, obs = fit_pitch(img, homography_from_corners(PITCH_CORNERS_PX), response=line_response(img))
    assert fit.length == pytest.approx(PITCH_SIZE_M[0], abs=0.03) and fit.width == pytest.approx(PITCH_SIZE_M[1], abs=0.03)
    assert fit.stats["rms_px"] < 0.5 and len(obs) > 1100
    assert fit.stats["px_per_m_centre"] == pytest.approx(27.9, abs=0.2)
    found = find_spots(img, fit)
    assert found["penalty_mark_left"]["error_px"] < 1.2 and found["penalty_mark_right"]["error_px"] < 1.2


@pytest.mark.integration
@pytest.mark.slow
def test_teamtrack_drone_yaw_is_followed(real_teamtrack):
    """In D_20220220_1_1260_1290 the drone yaws back by about 0.8 degrees between frames 75 and 82; a corner of the pitch
    moves about 15 px, and the per-frame fit follows it with the lines still within half a pixel."""
    from flocker.pitch import PitchFit, line_response
    from flocker.teamtrack import PITCH_CORNERS_PX, PITCH_SIZE_M, find_sequence

    seq = find_sequence("D_20220220_1_1260_1290", real_teamtrack)
    img = cv2.VideoCapture(str(seq.video_path)).read()[1]
    ref, _ = fit_pitch(img, homography_from_corners(PITCH_CORNERS_PX, *PITCH_SIZE_M), *PITCH_SIZE_M, fit_size=False, response=line_response(img))
    assert isinstance(ref, PitchFit)
    table = track_pitch(seq.video_path, ref, max_frames=100)
    assert table["rms_px"].max() < 0.6 and table["restart"].sum() == 0
    corner = [(-PITCH_SIZE_M[0] / 2, -PITCH_SIZE_M[1] / 2)]
    tl = {f: apply_h(np.linalg.inv(table.loc[table["frame"] == f, H_COLUMNS].to_numpy(float).reshape(3, 3)), corner)[0] for f in (1, 70, 90, 100)}
    assert np.linalg.norm(tl[70] - tl[1]) < 7.0 and np.linalg.norm(tl[90] - tl[70]) > 12.0 and np.linalg.norm(tl[100] - tl[90]) < 3.0
