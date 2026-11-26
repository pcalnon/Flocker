"""The pitch, and the homography from image pixels to pitch metres: the owner's edit 4 (correct the camera angle).

Project: Flocker
File: src/flocker/pitch.py
Purpose: the pitch markings of the Laws of the Game as a template in metres; the image-to-pitch homography fitted to the
    painted lines of a clip's empty pitch, then followed frame by frame; conversions to metres; top-down views
Author: Paul Calnon
Created: 2026-11-25
License: CC0 1.0 (see LICENSE)

Pitch coordinates are metres, with the origin at the centre mark. x runs along the touchlines toward the goal on the
right of the video, and y across the pitch toward the touchline at the bottom of the video, so a top-down drawing with
y downward looks like the video. Seen from above, this frame is left-handed: an angle measured from x toward y turns
clockwise as seen in the video.

Markings (IFAB Law 1): lines are at most 12 cm wide and belong to the areas they bound, so every distance runs to a
line's outer edge. The template holds line centrelines, inset by half a line width (half_line). The length and the
width of a field vary from ground to ground (90-120 m by 45-90 m) while the markings inside it do not, so the fit
measures length and width as well: the penalty and goal areas, the arcs and the centre circle fix the scale, and the
touchlines and goal lines then fix the size.

The fit (fit_pitch):
1. The image is reduced to one channel in which lines are bright: line_response() (a white top-hat of the lightness)
   for a clip's median background, or plain grey levels, which locate lines in a frame just as well (each profile's
   median is subtracted, which removes the grass under it).
2. observe() projects the template into the image with the current homography. Along each marking, every ``step``
   metres, it searches the image along the marking's normal for the painted line's centre, to a fraction of a pixel
   (the centroid of the response around its peak). Points closer than ``clearance`` to another marking, or near a
   goal, are not searched, so no search sees two markings.
3. fit_observations() refines the homography (and the length and width) by robust least squares on the distance, in
   metres, from each observed centre, mapped to the pitch, to its marking. Players standing on a line give outliers,
   which the robust loss ignores: masking them out changes the fit by 0.03 px on TeamTrack.
4. Steps 2 and 3 repeat with a narrowing search.

The camera moves (track_pitch): TeamTrack's drone yaws by up to about 0.8 degrees within a clip (about 20 px at the
pitch corners), so one homography per clip is not enough. track_pitch() refits every frame, starting from the previous
frame's homography, and falls back to the clip's reference fit when a frame's fit is poor.

The homography maps points on the ground. A player's box centre is not on the ground: seen from a camera about 100 m up,
a point about 1 m up lands about 1 % of its distance from the camera's nadir too far out (about 0.45 m at a goal line).
notes/FLOCKER_2026-11-25_PITCH-HOMOGRAPHY.md measures that, and the fit's accuracy.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from scipy.ndimage import map_coordinates
from scipy.optimize import least_squares

# Law 1 dimensions, metres, to the outer edges of the lines
GOAL_WIDTH = 7.32
GOAL_AREA_DEPTH = 5.5
PENALTY_AREA_DEPTH = 16.5
PENALTY_MARK_DISTANCE = 11.0
CIRCLE_RADIUS = 9.15  # the centre circle and the penalty arcs
CORNER_ARC_RADIUS = 1.0
HALF_LINE = 0.06  # half of the 12 cm maximum line width
DEFAULT_LENGTH, DEFAULT_WIDTH = 105.0, 68.0

H_COLUMNS = [f"h{i}" for i in range(9)]  # a 3 x 3 homography, row by row, in a table


@dataclass(frozen=True)
class Marking:
    """One pitch marking's centreline, in pitch metres: a segment p0-p1, or an arc of ``radius`` about ``centre`` from
    angle a0 to a1 (radians, a0 < a1, measured from x toward y)."""

    name: str
    kind: str  # "line" or "arc"
    p0: tuple[float, float] = (0.0, 0.0)
    p1: tuple[float, float] = (0.0, 0.0)
    centre: tuple[float, float] = (0.0, 0.0)
    radius: float = 0.0
    a0: float = 0.0
    a1: float = 0.0

    def sample(self, step: float) -> tuple[np.ndarray, np.ndarray]:
        """Points every ``step`` metres along the marking (N x 2) and the unit normals there (N x 2)."""
        if self.kind == "line":
            p0, p1 = np.array(self.p0), np.array(self.p1)
            n = max(2, int(np.ceil(np.linalg.norm(p1 - p0) / step)) + 1)
            t = np.linspace(0.0, 1.0, n)[:, None]
            d = (p1 - p0) / np.linalg.norm(p1 - p0)
            return p0 + t * (p1 - p0), np.tile([-d[1], d[0]], (n, 1))
        full = self.a1 - self.a0 >= 2 * np.pi - 1e-9  # a whole circle: do not repeat the first point at the end
        n = max(2, int(np.ceil(self.radius * (self.a1 - self.a0) / step)) + (0 if full else 1))
        a = np.linspace(self.a0, self.a1, n, endpoint=not full)
        u = np.column_stack([np.cos(a), np.sin(a)])
        return np.array(self.centre) + self.radius * u, u

    def distance(self, pts: np.ndarray) -> np.ndarray:
        """Unsigned distance from each point (N x 2) to this finite marking."""
        pts = np.asarray(pts, float).reshape(-1, 2)
        if self.kind == "line":
            p0, p1 = np.array(self.p0), np.array(self.p1)
            d = p1 - p0
            t = np.clip(((pts - p0) @ d) / (d @ d), 0.0, 1.0)
            return np.linalg.norm(pts - (p0 + t[:, None] * d), axis=1)
        rel = pts - np.array(self.centre)
        ang = np.arctan2(rel[:, 1], rel[:, 0])
        mid, half = (self.a0 + self.a1) / 2, (self.a1 - self.a0) / 2
        inside = np.abs(np.angle(np.exp(1j * (ang - mid)))) <= half + 1e-9
        on_arc = np.abs(np.linalg.norm(rel, axis=1) - self.radius)
        ends = np.array([self.centre]) + self.radius * np.array([[np.cos(self.a0), np.sin(self.a0)], [np.cos(self.a1), np.sin(self.a1)]])
        to_ends = np.min(np.linalg.norm(pts[:, None] - ends[None], axis=2), axis=1)
        return np.where(inside, on_arc, to_ends)

    def residual(self, pts: np.ndarray) -> np.ndarray:
        """Signed distance from each point to the marking's infinite line (positive along the normal), or to its full
        circle (positive outside)."""
        pts = np.asarray(pts, float).reshape(-1, 2)
        if self.kind == "line":
            p0, p1 = np.array(self.p0), np.array(self.p1)
            d = (p1 - p0) / np.linalg.norm(p1 - p0)
            return (pts - p0) @ np.array([-d[1], d[0]])
        return np.linalg.norm(pts - np.array(self.centre), axis=1) - self.radius

    def foot(self, pts: np.ndarray) -> np.ndarray:
        """The nearest point of the marking's infinite line, or full circle, to each point."""
        pts = np.asarray(pts, float).reshape(-1, 2)
        if self.kind == "line":
            p0, p1 = np.array(self.p0), np.array(self.p1)
            d = (p1 - p0) / np.linalg.norm(p1 - p0)
            return p0 + ((pts - p0) @ d)[:, None] * d
        rel = pts - np.array(self.centre)
        return np.array(self.centre) + self.radius * rel / np.linalg.norm(rel, axis=1, keepdims=True)


def markings(length: float = DEFAULT_LENGTH, width: float = DEFAULT_WIDTH, half_line: float = HALF_LINE, corner_arcs: bool = False) -> list[Marking]:
    """The centrelines of a pitch's markings (Law 1), for a field of ``length`` x ``width`` metres to the lines' outer
    edges, always in the same order. Corner arcs (1 m) are left out unless asked for: they are too small, and too close
    to the boundary lines, to help a fit."""
    hl, hw, h = length / 2, width / 2, half_line
    xo, yo = hl - h, hw - h  # boundary-line centrelines
    out = [Marking("touchline_top", "line", (-xo, -yo), (xo, -yo)), Marking("touchline_bottom", "line", (-xo, yo), (xo, yo)), Marking("halfway_line", "line", (0.0, -yo), (0.0, yo)), Marking("centre_circle", "arc", centre=(0.0, 0.0), radius=CIRCLE_RADIUS - h, a0=-np.pi, a1=np.pi)]
    pa_half, ga_half = GOAL_WIDTH / 2 + PENALTY_AREA_DEPTH - h, GOAL_WIDTH / 2 + GOAL_AREA_DEPTH - h
    arc_half = np.arccos((PENALTY_AREA_DEPTH - PENALTY_MARK_DISTANCE) / CIRCLE_RADIUS)  # where the arc meets the area's front line
    for side, s in (("left", -1.0), ("right", 1.0)):
        pa_x, ga_x, mark_x = s * (hl - PENALTY_AREA_DEPTH + h), s * (hl - GOAL_AREA_DEPTH + h), s * (hl - PENALTY_MARK_DISTANCE)
        out += [
            Marking(f"goal_line_{side}", "line", (s * xo, -yo), (s * xo, yo)),
            Marking(f"penalty_area_{side}_front", "line", (pa_x, -pa_half), (pa_x, pa_half)),
            Marking(f"penalty_area_{side}_top", "line", (s * xo, -pa_half), (pa_x, -pa_half)),
            Marking(f"penalty_area_{side}_bottom", "line", (s * xo, pa_half), (pa_x, pa_half)),
            Marking(f"goal_area_{side}_front", "line", (ga_x, -ga_half), (ga_x, ga_half)),
            Marking(f"goal_area_{side}_top", "line", (s * xo, -ga_half), (ga_x, -ga_half)),
            Marking(f"goal_area_{side}_bottom", "line", (s * xo, ga_half), (ga_x, ga_half)),
        ]
        a_mid = 0.0 if s < 0 else np.pi  # the arc bulges toward the halfway line
        out.append(Marking(f"penalty_arc_{side}", "arc", centre=(mark_x, 0.0), radius=CIRCLE_RADIUS - h, a0=a_mid - arc_half, a1=a_mid + arc_half))
    if corner_arcs:
        for name, (cx, cy), a0 in (("tl", (-hl, -hw), 0.0), ("tr", (hl, -hw), np.pi / 2), ("br", (hl, hw), np.pi), ("bl", (-hl, hw), -np.pi / 2)):
            out.append(Marking(f"corner_arc_{name}", "arc", centre=(cx, cy), radius=CORNER_ARC_RADIUS - h, a0=a0, a1=a0 + np.pi / 2))
    return out


def spots(length: float = DEFAULT_LENGTH) -> dict[str, tuple[float, float]]:
    """The centre mark and the two penalty marks, in pitch metres."""
    m = length / 2 - PENALTY_MARK_DISTANCE
    return {"centre_mark": (0.0, 0.0), "penalty_mark_left": (-m, 0.0), "penalty_mark_right": (m, 0.0)}


def goal_zones(length: float, reach: float = 1.5) -> list[tuple[float, float, float, float]]:
    """Boxes (x0, y0, x1, y1), metres, around each goal mouth: posts, nets and goalkeepers' wear cover the goal line there."""
    hl, g = length / 2, GOAL_WIDTH / 2 + 0.8
    return [(-hl - reach, -g, -hl + reach, g), (hl - reach, -g, hl + reach, g)]


def apply_h(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Points (N x 2) through the 3 x 3 projective transform h."""
    pts = np.asarray(pts, float).reshape(-1, 2)
    q = np.column_stack([pts, np.ones(len(pts))]) @ np.asarray(h, float).T
    return q[:, :2] / q[:, 2:3]


def homography_4pt(src, dst) -> np.ndarray:
    """The projective transform taking four points src (4 x 2) to dst, solved in float64 (OpenCV's
    getPerspectiveTransform works in float32, about 1e-5 px at image coordinates in the thousands)."""
    src, dst = np.asarray(src, float).reshape(4, 2), np.asarray(dst, float).reshape(4, 2)
    a = np.zeros((8, 8))
    b = dst.ravel()
    for i, ((x, y), (u, v)) in enumerate(zip(src, dst)):
        a[2 * i] = (x, y, 1, 0, 0, 0, -u * x, -u * y)
        a[2 * i + 1] = (0, 0, 0, x, y, 1, -v * x, -v * y)
    return np.append(np.linalg.solve(a, b), 1.0).reshape(3, 3)


def homography_from_corners(corners_px, length: float = DEFAULT_LENGTH, width: float = DEFAULT_WIDTH) -> np.ndarray:
    """The image-to-pitch homography that sends the four outer corners (top-left, top-right, bottom-right, bottom-left
    in the image) to the corners of a length x width pitch."""
    hl, hw = length / 2, width / 2
    return homography_4pt(corners_px, [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)])


def line_response(image: np.ndarray, kernel: int = 15, blur: float = 1.0) -> np.ndarray:
    """How much brighter than its surroundings each pixel is, for structures narrower than ``kernel`` pixels: the white
    top-hat of the lightness channel (OpenCV 8-bit Lab), lightly smoothed. Pitch lines are 4-5 px wide on TeamTrack."""
    light = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)[..., 0] if image.ndim == 3 else image
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    top = cv2.morphologyEx(light, cv2.MORPH_TOPHAT, k).astype(np.float32)
    return cv2.GaussianBlur(top, (0, 0), blur) if blur else top


def grey(image: np.ndarray) -> np.ndarray:
    """A frame's grey levels as float32: enough to find lines in, at 1/30 of line_response's cost."""
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) if image.ndim == 3 else image.astype(np.float32)


@dataclass(frozen=True)
class TemplateSamples:
    """Where to look for lines: template points (N x 2, metres), their unit normals, and each one's marking index."""

    pts: np.ndarray
    normals: np.ndarray
    marking: np.ndarray
    names: tuple[str, ...]


@lru_cache(maxsize=16)
def template_samples(length: float, width: float, half_line: float = HALF_LINE, step: float = 0.5, clearance: float = 1.0) -> TemplateSamples:
    """Template points every ``step`` metres along every marking, except within ``clearance`` metres of another marking
    or inside a goal zone (goal_zones)."""
    marks = markings(length, width, half_line)
    pts, nrm, idx = [], [], []
    for i, m in enumerate(marks):
        p, n = m.sample(step)
        near = np.min([o.distance(p) for j, o in enumerate(marks) if j != i], axis=0) < clearance
        for x0, y0, x1, y1 in goal_zones(length):
            near |= (p[:, 0] >= x0) & (p[:, 0] <= x1) & (p[:, 1] >= y0) & (p[:, 1] <= y1)
        pts.append(p[~near])
        nrm.append(n[~near])
        idx.append(np.full((~near).sum(), i))
    out = TemplateSamples(np.vstack(pts), np.vstack(nrm), np.concatenate(idx), tuple(m.name for m in marks))
    for a in (out.pts, out.normals, out.marking):
        a.setflags(write=False)  # cached and shared between calls
    return out


@dataclass
class Observations:
    """Observed line centres: image points (N x 2), the index of each one's marking, and its response peak."""

    pts: np.ndarray
    marking: np.ndarray
    peak: np.ndarray
    names: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.pts)


def observe(response: np.ndarray, h_img: np.ndarray, samples: TemplateSamples, search: float = 8.0, min_peak: float = 12.0) -> Observations:
    """Find the painted centreline of each template sample near where h_img (pitch to image) puts it.

    The response is read along the marking's image normal within +-``search`` px, every 0.5 px, and the profile's median
    is subtracted. A sample whose peak rises at least ``min_peak`` above it gives an observation at the centroid of the
    peak's half-maximum run: the contiguous samples around the peak at or above half its height, weighted by their
    height above that half. The run must end at least 1 px inside the window. Any line width works, flat-topped or
    not (a fixed window narrower than the line would have a fixed point anywhere on its plateau)."""
    p, n = samples.pts, samples.normals
    c = apply_h(h_img, p)
    d = apply_h(h_img, p + 0.05 * n) - apply_h(h_img, p - 0.05 * n)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    t = np.arange(-search, search + 1e-9, 0.5)
    xy = c[:, None, :] + t[None, :, None] * d[:, None, :]
    hgt, wid = response.shape
    inside = (xy[..., 0] >= 0).all(1) & (xy[..., 0] <= wid - 1).all(1) & (xy[..., 1] >= 0).all(1) & (xy[..., 1] <= hgt - 1).all(1)
    prof = map_coordinates(response, [xy[..., 1].ravel(), xy[..., 0].ravel()], order=1, mode="nearest").reshape(xy.shape[:2])
    prof = prof - np.median(prof, axis=1, keepdims=True)
    j = np.argmax(prof, axis=1)
    peak = prof[np.arange(len(prof)), j]
    half = 0.5 * peak[:, None]
    idx = np.arange(len(t))[None, :]
    below = prof < half
    lo = np.where(below & (idx < j[:, None]), idx, -1).max(axis=1) + 1  # first sample of the run
    hi = np.where(below & (idx > j[:, None]), idx, len(t)).min(axis=1) - 1  # last sample of the run
    w = np.where((idx >= lo[:, None]) & (idx <= hi[:, None]), prof - half, 0.0)
    off = (w * t[None, :]).sum(1) / np.maximum(w.sum(1), 1e-9)
    ok = inside & (peak >= min_peak) & (lo >= 2) & (hi <= len(t) - 3)  # the run ends 1 px or more inside the window
    obs = c + off[:, None] * d
    return Observations(obs[ok], samples.marking[ok], peak[ok], samples.names)


def _marking_arrays(length: float, width: float, half_line: float):
    """Per marking (markings() order): is it an arc; the line's unit normal and offset; the arc's centre and radius."""
    marks = markings(length, width, half_line)
    arc = np.array([m.kind == "arc" for m in marks])
    nrm, off, cen, rad = np.zeros((len(marks), 2)), np.zeros(len(marks)), np.zeros((len(marks), 2)), np.zeros(len(marks))
    for i, m in enumerate(marks):
        if m.kind == "line":
            d = np.subtract(m.p1, m.p0) / np.linalg.norm(np.subtract(m.p1, m.p0))
            nrm[i] = (-d[1], d[0])
            off[i] = nrm[i] @ np.array(m.p0)
        else:
            cen[i], rad[i] = m.centre, m.radius
    return arc, nrm, off, cen, rad


def signed_residuals(q: np.ndarray, marking: np.ndarray, length: float, width: float, half_line: float = HALF_LINE) -> np.ndarray:
    """Signed distance, metres, from each pitch point q (N x 2) to its marking (index into markings())."""
    arc, nrm, off, cen, rad = _marking_arrays(length, width, half_line)
    i = marking
    line_r = (q * nrm[i]).sum(1) - off[i]
    arc_r = np.linalg.norm(q - cen[i], axis=1) - rad[i]
    return np.where(arc[i], arc_r, line_r)


def _normaliser(size: tuple[int, int]) -> np.ndarray:
    """A similarity taking pixels of an image of size (width, height) to coordinates centred on it, about +-1 across."""
    w, h = size
    s = 2.0 / max(w, h)
    return np.array([[s, 0, -s * w / 2], [0, s, -s * h / 2], [0, 0, 1.0]])


def fit_observations(obs: Observations, h0: np.ndarray, size: tuple[int, int], length: float = DEFAULT_LENGTH, width: float = DEFAULT_WIDTH, fit_size: bool = True, half_line: float = HALF_LINE, loss_scale: float = 0.05):
    """Refine the image-to-pitch homography h0 (and the field's length and width, if fit_size) by robust least squares
    (soft L1, scale ``loss_scale`` metres) on each observation's signed distance from its marking. Returns
    (h, length, width, scipy result)."""
    norm = _normaliser(size)
    g = h0 @ np.linalg.inv(norm)
    g = g / g[2, 2]
    xn = apply_h(norm, obs.pts)
    x0 = np.concatenate([g.ravel()[:8], [length, width]]) if fit_size else g.ravel()[:8]

    def resid(x):
        q = apply_h(np.append(x[:8], 1.0).reshape(3, 3), xn)
        return signed_residuals(q, obs.marking, x[8], x[9], half_line) if fit_size else signed_residuals(q, obs.marking, length, width, half_line)

    res = least_squares(resid, x0, loss="soft_l1", f_scale=loss_scale, x_scale="jac", max_nfev=200)
    h = np.append(res.x[:8], 1.0).reshape(3, 3) @ norm
    return h / h[2, 2], (float(res.x[8]) if fit_size else length), (float(res.x[9]) if fit_size else width), res


@dataclass
class PitchFit:
    """An image-to-pitch homography with the field size it was fitted with, and how well it fits."""

    h: np.ndarray  # image pixels -> pitch metres
    length: float
    width: float
    image_size: tuple[int, int]  # (width, height) in pixels
    half_line: float = HALF_LINE
    stats: dict = field(default_factory=dict)

    @property
    def h_inv(self) -> np.ndarray:
        """Pitch metres -> image pixels."""
        return np.linalg.inv(self.h)

    def to_pitch(self, pts_px: np.ndarray) -> np.ndarray:
        return apply_h(self.h, pts_px)

    def to_image(self, pts_m: np.ndarray) -> np.ndarray:
        return apply_h(self.h_inv, pts_m)

    def markings(self, corner_arcs: bool = True) -> list[Marking]:
        return markings(self.length, self.width, self.half_line, corner_arcs=corner_arcs)

    def scale(self, pts_m: np.ndarray) -> np.ndarray:
        """Image pixels per pitch metre at each pitch point (the square root of the local area ratio)."""
        return local_scale(self.h_inv, pts_m)

    def to_json(self) -> dict:
        return {"h_image_to_pitch": self.h.tolist(), "length_m": self.length, "width_m": self.width, "image_size": list(self.image_size), "half_line_m": self.half_line, "stats": self.stats}

    @classmethod
    def from_json(cls, d: dict) -> "PitchFit":
        return cls(np.array(d["h_image_to_pitch"], float), float(d["length_m"]), float(d["width_m"]), tuple(d["image_size"]), float(d.get("half_line_m", HALF_LINE)), d.get("stats", {}))

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "PitchFit":
        return cls.from_json(json.loads(Path(path).read_text()))


def local_scale(h_img: np.ndarray, pts_m: np.ndarray) -> np.ndarray:
    """Image pixels per pitch metre at each pitch point, for h_img (pitch to image): the square root of the local area
    ratio."""
    pts_m = np.asarray(pts_m, float).reshape(-1, 2)
    e = 0.5
    dx = (apply_h(h_img, pts_m + [e, 0]) - apply_h(h_img, pts_m - [e, 0])) / (2 * e)
    dy = (apply_h(h_img, pts_m + [0, e]) - apply_h(h_img, pts_m - [0, e])) / (2 * e)
    return np.sqrt(np.abs(dx[:, 0] * dy[:, 1] - dx[:, 1] * dy[:, 0]))


def residual_table(fit: PitchFit, obs: Observations) -> dict:
    """Per marking: observations, and the RMS and largest distance from each observed centre to the fitted marking, in
    image pixels (the observed point against the projection of its foot on the marking) and in centimetres. The signed
    median is positive along the marking's normal (its p0-to-p1 direction turned toward +y for lines along x, toward -x
    for lines along y), or outward for an arc; mirrored markings can therefore show one bias with opposite signs."""
    marks = markings(fit.length, fit.width, fit.half_line)
    q = fit.to_pitch(obs.pts)
    out = {}
    for i in np.unique(obs.marking):
        sel = obs.marking == i
        r_m = marks[i].residual(q[sel])
        r_px = np.linalg.norm(fit.to_image(marks[i].foot(q[sel])) - obs.pts[sel], axis=1)
        out[obs.names[i]] = {"n": int(sel.sum()), "rms_px": float(np.sqrt(np.mean(r_px**2))), "max_px": float(r_px.max()), "rms_cm": float(100 * np.sqrt(np.mean(r_m**2))), "median_signed_cm": float(100 * np.median(r_m))}
    return out


def rms_px(h: np.ndarray, obs: Observations, length: float, width: float, half_line: float = HALF_LINE) -> float:
    """RMS distance, image pixels, of the observations from their markings (metres times the local scale)."""
    q = apply_h(h, obs.pts)
    r = signed_residuals(q, obs.marking, length, width, half_line) * local_scale(np.linalg.inv(h), q)
    return float(np.sqrt(np.mean(r**2)))


def refine(response: np.ndarray, h0: np.ndarray, length: float, width: float, searches=(8.0,), fit_size: bool = False, half_line: float = HALF_LINE, step: float = 0.5, clearance: float = 1.0, min_peak: float = 12.0, min_obs: int = 50):
    """Rounds of observe() and fit_observations() from h0 (image to pitch), one per search half-width (pixels).

    Returns (h, length, width, observations of the last round, history of the rounds)."""
    size = (response.shape[1], response.shape[0])
    h, lw, history = np.asarray(h0, float), (length, width), []
    for search in searches:
        samples = template_samples(round(lw[0], 6), round(lw[1], 6), half_line, step, clearance)
        obs = observe(response, np.linalg.inv(h), samples, search=search, min_peak=min_peak)
        if len(obs) < min_obs:
            raise ValueError(f"only {len(obs)} line observations within {search} px; is the starting homography near the pitch?")
        h_new, length_new, width_new, res = fit_observations(obs, h, size, *lw, fit_size=fit_size, half_line=half_line)
        grid = np.array([(x, y) for x in (-50, 0, 50) for y in (-32, 0, 32)], float)
        moved = float(np.max(np.linalg.norm(apply_h(np.linalg.inv(h_new), grid) - apply_h(np.linalg.inv(h), grid), axis=1)))
        h, lw = h_new, (length_new, width_new)
        history.append({"search_px": search, "observations": len(obs), "moved_px": round(moved, 3)})
    return h, lw[0], lw[1], obs, history


def fit_pitch(image: np.ndarray, h0: np.ndarray, length: float = DEFAULT_LENGTH, width: float = DEFAULT_WIDTH, fit_size: bool = True, searches=(24.0, 12.0, 8.0, 6.0, 6.0), half_line: float = HALF_LINE, response: np.ndarray | None = None, **kwargs) -> tuple[PitchFit, Observations]:
    """Fit the image-to-pitch homography to an image of the pitch (BGR), starting from h0 (image to pitch).

    The response defaults to line_response(image). Each round observes the line centres within the next search
    half-width (pixels) of where the current fit puts them, and refits. Returns the fit, with per-marking residuals in
    its stats, and the observations made with the final fit."""
    resp = line_response(image) if response is None else response
    size = (resp.shape[1], resp.shape[0])
    h, length, width, _, history = refine(resp, h0, length, width, searches, fit_size=fit_size, half_line=half_line, **kwargs)
    fit = PitchFit(h, length, width, size, half_line)
    obs = observe(resp, fit.h_inv, template_samples(round(length, 6), round(width, 6), half_line, kwargs.get("step", 0.5), kwargs.get("clearance", 1.0)), search=searches[-1], min_peak=kwargs.get("min_peak", 12.0))
    table = residual_table(fit, obs)
    fit.stats = {"rounds": history, "observations": len(obs), "rms_px": rms_px(h, obs, length, width, half_line), "markings": table, "px_per_m_centre": float(fit.scale([(0.0, 0.0)])[0])}
    return fit, obs


def track_pitch(video: str | Path, ref: PitchFit, search: float = 8.0, max_frames: int | None = None, min_obs: int = 300, max_rms: float = 1.5, every: int = 1, progress=None) -> pd.DataFrame:
    """The image-to-pitch homography of every frame of ``video``, with the field size of ``ref`` (the clip's reference fit).

    Every ``every``-th frame, and the last frame read, is fitted on its grey levels, starting from the previous good
    fit with one search of +-``search`` px. A fit with under ``min_obs`` observations or an RMS over ``max_rms`` px is
    redone from ``ref`` with searches of 24, 12 and 8 px (``restart``). If that fails too, the frame is ``failed``: it
    seeds nothing, and its homography is interpolated from the good fits around it, as are the frames between fitted
    ones. The video is read to its real end, whatever its header says. Returns one row per frame: frame (1-based),
    h0..h8 (image to pitch, row by row), observations, rms_px, fitted, restart, failed."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(video)
    n_hint = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def attempt(g, h0, searches):
        try:
            h, _, _, obs, _ = refine(g, h0, ref.length, ref.width, searches, half_line=ref.half_line)
        except ValueError:
            return None, 0, np.nan
        err = rms_px(h, obs, ref.length, ref.width, ref.half_line)
        return (h, len(obs), err) if len(obs) >= min_obs and err <= max_rms else (None, len(obs), err)

    rows, h_prev, pending, f = [], ref.h, None, 0
    while max_frames is None or f < max_frames:
        ok, img = cap.read()
        if not ok:
            break
        f += 1
        if (f - 1) % every:
            pending = (f, img)  # fitted only if it turns out to be the last frame
            continue
        pending = None
        h_prev = _fit_row(rows, f, grey(img), h_prev, ref.h, attempt, search)
        if progress is not None:
            progress(f, n_hint)
    if pending is not None:
        _fit_row(rows, pending[0], grey(pending[1]), h_prev, ref.h, attempt, search)
    cap.release()
    if not rows:
        raise ValueError(f"no frames read from {video}")
    table = pd.DataFrame(rows)
    if table["failed"].all():
        raise ValueError(f"no frame of {video} could be fitted")
    if every == 1 and not table["failed"].any():
        return table
    full = interpolate_homographies(table[~table["failed"]], np.arange(1, f + 1))
    full["failed"] = full["frame"].isin(table.loc[table["failed"], "frame"])
    full["restart"] = full["restart"].astype(bool)
    return full


def _fit_row(rows: list, f: int, g: np.ndarray, h_prev: np.ndarray, h_ref: np.ndarray, attempt, search: float) -> np.ndarray:
    """Fit frame f (grey levels g) for track_pitch, append its row, and return the homography the next frame starts
    from: this frame's, or h_prev if this frame failed."""
    h, n_obs, err = attempt(g, h_prev, (search,))
    restart = h is None
    if restart:
        h, n_obs, err = attempt(g, h_ref, (24.0, 12.0, 8.0))
    failed = h is None
    rows.append({"frame": f, **dict(zip(H_COLUMNS, (h_prev if failed else h).ravel())), "observations": n_obs, "rms_px": err, "fitted": not failed, "restart": restart, "failed": failed})
    return h_prev if failed else h


def interpolate_homographies(table: pd.DataFrame, frames) -> pd.DataFrame:
    """Homographies for ``frames`` from a table of fitted ones (frame, h0..h8): between two fitted frames, the image
    positions of four pitch points move linearly. Frames outside the fitted range take the nearest fitted homography."""
    table = table.sort_values("frame")
    probe = np.array([(-40.0, -25.0), (40.0, -25.0), (40.0, 25.0), (-40.0, 25.0)])
    img = np.stack([apply_h(np.linalg.inv(r.reshape(3, 3)), probe) for r in table[H_COLUMNS].to_numpy()])  # T x 4 x 2
    known = table["frame"].to_numpy()
    frames = np.asarray(frames)
    rows = []
    for f in frames:
        k = np.searchsorted(known, f)
        if k < len(known) and known[k] == f:
            rows.append(table.iloc[k].to_dict())
            continue
        a, b = max(k - 1, 0), min(k, len(known) - 1)
        w = 0.0 if a == b else (f - known[a]) / (known[b] - known[a])
        h = homography_4pt((1 - w) * img[a] + w * img[b], probe)
        rows.append({"frame": int(f), **dict(zip(H_COLUMNS, (h / h[2, 2]).ravel())), "observations": 0, "rms_px": np.nan, "fitted": False, "restart": False})
    return pd.DataFrame(rows)


def camera_motion(table: pd.DataFrame, length: float = DEFAULT_LENGTH, width: float = DEFAULT_WIDTH) -> dict:
    """How far the view moved during a track_pitch table, relative to its first frame: the largest shift of a pitch
    corner and of the centre mark in the image (px), the range of the image direction of the pitch's x axis (yaw,
    degrees), and the range of the scale at the centre mark (px per metre)."""
    hs = [np.linalg.inv(r.reshape(3, 3)) for r in table[H_COLUMNS].to_numpy(float)]
    probe = np.array([(-length / 2, -width / 2), (length / 2, -width / 2), (length / 2, width / 2), (-length / 2, width / 2), (0.0, 0.0), (10.0, 0.0)])
    img = np.stack([apply_h(h, probe) for h in hs])  # T x 6 x 2
    shift = np.linalg.norm(img - img[0], axis=2)
    axis = img[:, 5] - img[:, 4]
    ang = np.arctan2(axis[:, 1], axis[:, 0])
    yaw = np.degrees(np.angle(np.exp(1j * (ang - ang[0]))))  # relative to frame 1, so no wrap at +-180 degrees
    scale = np.array([local_scale(h, [(0.0, 0.0)])[0] for h in hs])
    return {"corner_shift_px_max": float(shift[:, :4].max()), "centre_shift_px_max": float(shift[:, 4].max()), "yaw_deg_range": float(np.ptp(yaw)), "px_per_m_centre_range": [float(scale.min()), float(scale.max())]}


def read_homographies(path: str | Path) -> pd.DataFrame:
    """A table written by track_pitch (CSV)."""
    return pd.read_csv(path)


def homography_of(table: pd.DataFrame) -> dict[int, np.ndarray]:
    """frame -> 3 x 3 image-to-pitch homography, from a track_pitch table."""
    return {int(f): h.reshape(3, 3) for f, h in zip(table["frame"], table[H_COLUMNS].to_numpy())}


def to_pitch_coords(df: pd.DataFrame, table: pd.DataFrame, x: str = "cx", y: str = "cy") -> np.ndarray:
    """Pitch metres (N x 2) of image points df[x], df[y] (pixels), each through its own frame's homography from a
    track_pitch table. A frame missing from the table raises KeyError."""
    hs = homography_of(table)
    out = np.empty((len(df), 2))
    frames = df["frame"].to_numpy()
    pts = df[[x, y]].to_numpy(float)
    for f in np.unique(frames):
        sel = frames == f
        out[sel] = apply_h(hs[int(f)], pts[sel])
    return out


def with_pitch_positions(df: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """``df`` (a flocker.mot frame of one clip) with each box centre on the pitch: columns mx and my, in metres, each row
    through its own frame's homography (a track_pitch table). The centre is not the player's feet: see the module
    docstring on parallax."""
    from flocker.mot import centers

    c = centers(df)
    m = to_pitch_coords(pd.DataFrame({"frame": df["frame"].to_numpy(), "cx": c[:, 0], "cy": c[:, 1]}), table)
    return df.assign(mx=m[:, 0], my=m[:, 1])


def _line_kernel(length: int, angle: float) -> np.ndarray:
    """A length x length structuring element holding a one-pixel line through its centre at ``angle`` (radians)."""
    k = np.zeros((length, length), np.uint8)
    c = (length - 1) / 2
    dx, dy = c * np.cos(angle), c * np.sin(angle)
    cv2.line(k, (int(round(c - dx)), int(round(c - dy))), (int(round(c + dx)), int(round(c + dy))), 1, 1)
    return k


def find_spots(image: np.ndarray, fit: PitchFit, radius_px: float = 12.0, kernel: int = 9) -> dict:
    """Locate the centre and penalty marks near where the fit puts them: the centroid of the brightest small blob within
    radius_px. Returns name -> {predicted_px, found_px, error_px, error_cm, measured}, or None where no blob stands out.

    A mark painted on a line (the centre mark, on the halfway line) is measured along that line only ("measured":
    "along <line>"). Across it, the mark is where the line is, and the fit has used the line already. Along it, the
    line's own pixels would pull a plain centroid back to the predicted position, so the line is removed first by
    subtracting an opening with a line along it, which keeps the line but not the spot. What remains is the spot's two
    sides, whose centroid along the line is the mark's."""
    resp = line_response(image, kernel=kernel, blur=1.0)
    marks = fit.markings(corner_arcs=False)
    r, pad = int(np.ceil(radius_px)), int(np.ceil(radius_px)) + 14
    out = {}
    for name, p in spots(fit.length).items():
        u, v = fit.to_image([p])[0]
        cx, cy = int(round(u)), int(round(v))
        if cx - pad < 0 or cy - pad < 0 or cx + pad >= resp.shape[1] or cy + pad >= resp.shape[0]:
            out[name] = None
            continue
        win = resp[cy - pad : cy + pad + 1, cx - pad : cx + pad + 1].copy()
        line = next((m for m in marks if m.kind == "line" and m.distance([p])[0] <= 0.3), None)
        yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
        if line is None:
            core = win[pad - r : pad + r + 1, pad - r : pad + r + 1]
            if core.max() < 10:
                out[name] = None
                continue
            w = np.clip(core - 0.5 * core.max(), 0, None)
            found, measured = np.array([cx + (w * xx).sum() / w.sum(), cy + (w * yy).sum() / w.sum()]), "both axes"
        else:
            tang = (np.array(line.p1) - np.array(line.p0)) / np.linalg.norm(np.subtract(line.p1, line.p0))
            d = (fit.to_image([np.array(p) + tang]) - fit.to_image([np.array(p) - tang]))[0]
            d /= np.linalg.norm(d)
            win = np.clip(win - cv2.morphologyEx(win, cv2.MORPH_OPEN, _line_kernel(2 * pad - 1, float(np.arctan2(d[1], d[0])))), 0, None)
            core = win[pad - r : pad + r + 1, pad - r : pad + r + 1]
            if core.max() < 10:
                out[name] = None
                continue
            w = np.clip(core - 0.25 * core.max(), 0, None)  # both sides of the spot, however unequal
            along = ((xx * d[0] + yy * d[1]) * w).sum() / w.sum() - ((u - cx) * d[0] + (v - cy) * d[1])
            found, measured = np.array([u, v]) + along * d, f"along {line.name}"
        out[name] = {"predicted_px": [float(u), float(v)], "found_px": found.tolist(), "error_px": float(np.linalg.norm(found - [u, v])), "error_cm": float(100 * np.linalg.norm(fit.to_pitch([found])[0] - p)), "measured": measured}
    return out


def draw_markings(canvas: np.ndarray, h_draw: np.ndarray, marks: list[Marking], colour=(0, 0, 255), thickness: int = 1, step: float = 0.1) -> np.ndarray:
    """Draw markings (pitch metres) onto canvas through h_draw (pitch to canvas pixels), in place; returns canvas."""
    for m in marks:
        p, _ = m.sample(step)
        q = apply_h(h_draw, p)
        closed = m.kind == "arc" and m.a1 - m.a0 >= 2 * np.pi - 1e-6
        cv2.polylines(canvas, [np.round(q * 16).astype(np.int32)], closed, colour, thickness, cv2.LINE_AA, shift=4)
    return canvas


def pitch_canvas(length: float, width: float, px_per_m: float = 10.0, margin: float = 4.0) -> tuple[np.ndarray, tuple[int, int]]:
    """The transform from pitch metres to the pixels of a top-down canvas showing the pitch plus ``margin`` metres
    around it, at px_per_m, and the canvas size (width, height), rounded up to even numbers for video."""
    s = px_per_m
    m = np.array([[s, 0, s * (length / 2 + margin)], [0, s, s * (width / 2 + margin)], [0, 0, 1.0]])
    size = (int(np.ceil(s * (length + 2 * margin) / 2) * 2), int(np.ceil(s * (width + 2 * margin) / 2) * 2))
    return m, size


def warp_area(image: np.ndarray, t: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """warpPerspective(image, t, size) without aliasing where t shrinks the image (warpPerspective treats INTER_AREA
    as INTER_LINEAR): the warp is made k times larger, k being the source pixels per output pixel at the canvas centre
    rounded up, then reduced by area averaging. Output pixel u covers large pixels k u ... k u + k - 1, whose centre is
    k u + (k - 1) / 2."""
    w, h = size
    k = max(1, int(np.ceil(local_scale(np.linalg.inv(t), [(w / 2, h / 2)])[0] - 1e-6)))
    if k == 1:
        return cv2.warpPerspective(image, t, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    up = np.array([[k, 0, (k - 1) / 2], [0, k, (k - 1) / 2], [0, 0, 1.0]])
    big = cv2.warpPerspective(image, up @ t, (w * k, h * k), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return cv2.resize(big, size, interpolation=cv2.INTER_AREA)


def rectify(image: np.ndarray, h: np.ndarray, length: float, width: float, px_per_m: float = 10.0, margin: float = 4.0) -> np.ndarray:
    """The image warped by h (image to pitch) to a top-down view of the pitch in pitch_canvas's layout: the camera
    angle corrected."""
    m, size = pitch_canvas(length, width, px_per_m, margin)
    return warp_area(image, m @ h, size)
