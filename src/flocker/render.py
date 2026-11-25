"""Render tracks as dots: the owner's edits 2 (replace players with dots), 4 (correct the camera angle) and 5 (speed up).

Project: Flocker
File: src/flocker/render.py
Purpose: draw each tracked object as a dot, over the original frames or the clip's empty pitch, as filmed or seen
    straight from above, at N x speed
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE); rendered clips derive from their sources and keep the sources' licences

Views:
- "image": the frame as filmed, scaled to ``width``.
- "pitch": straight down onto the pitch, through each frame's image-to-pitch homography (flocker.pitch.track_pitch):
  the camera angle is corrected and the drone's drift and yaw are removed, so the pitch stands still.

Backgrounds:
- "median": the per-pixel median of frames sampled across the clip, each taken through its own frame's view. The players
  move and the pitch does not, so this is the empty pitch; moving shadows vanish with the players.
- "frame": the original video.
- "pitch" (pitch view only): a drawn pitch, green with white markings.

Speed-up keeps every speed-th frame at the source frame rate, so an N x clip plays smoothly in any player. The
output is H.264 (yuv420p) written by the environment's ffmpeg, which has libx264.
"""

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from flocker.mot import BALL, centers

TEAM_COLOURS = {0: (60, 60, 230), 1: (230, 120, 40), -1: (255, 255, 255)}  # BGR: team 0 red, team 1 blue, unknown white
BALL_COLOUR = (0, 230, 255)
GRASS = (60, 120, 50)
PITCH_MARGIN = 4.0  # metres of surround in the pitch view


def ffmpeg_path() -> str:
    """The ffmpeg beside this interpreter (the Flocker environment's GPL build), else the first on PATH."""
    candidate = Path(sys.prefix) / "bin" / "ffmpeg"
    return str(candidate) if candidate.is_file() else "ffmpeg"


class View:
    """How a frame of the source video maps to the output canvas: transform(frame) is a 3 x 3 from image pixels to
    canvas pixels, and size the canvas (width, height)."""

    def __init__(self, src_size: tuple[int, int], width: int = 1920, pitch: tuple[pd.DataFrame, float, float] | None = None):
        self.pitch = pitch
        if pitch is None:
            s = width / src_size[0]
            self.size = (width, int(round(src_size[1] * s / 2)) * 2)
            self._fixed = np.diag([s, s, 1.0])
            self._h = None
        else:
            from flocker.pitch import homography_of, pitch_canvas

            table, length, pw = pitch
            self.canvas, self.size = pitch_canvas(length, pw, width / (length + 2 * PITCH_MARGIN), PITCH_MARGIN)
            self._h = homography_of(table)
            self._fixed = None
        self.max_frame = None if self._h is None else max(self._h)  # frames past the homographies cannot be viewed

    def transform(self, frame: int) -> np.ndarray:
        if self._h is None:
            return self._fixed
        return self.canvas @ self._h[frame]

    def warp(self, img: np.ndarray, frame: int) -> np.ndarray:
        if self._h is None:
            return cv2.resize(img, self.size, interpolation=cv2.INTER_AREA)
        from flocker.pitch import warp_area

        return warp_area(img, self.transform(frame), self.size)


def median_background(video: str | Path, size: tuple[int, int] | None = None, samples: int = 45, view: View | None = None, max_frames: int | None = None) -> np.ndarray:
    """Per-pixel median of ``samples`` frames spread over the clip, read in one sequential pass. Each frame goes through
    view.warp (or is resized to size = (width, height) when there is no view)."""
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    n = min(n, max_frames) if max_frames else n
    wanted = set(np.linspace(0, n - 1, samples).astype(int).tolist())
    frames = []
    for i in range(n):
        if not cap.grab():
            break
        if i in wanted:
            ok, img = cap.retrieve()
            if ok:
                frames.append(view.warp(img, i + 1) if view is not None else cv2.resize(img, size, interpolation=cv2.INTER_AREA))
    cap.release()
    if not frames:
        raise ValueError(f"could not read frames from {video}")
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def drawn_pitch(view: View, colour=(235, 235, 235)) -> np.ndarray:
    """A green canvas with the pitch's markings, for the pitch view."""
    from flocker.pitch import draw_markings, markings

    _, length, width = view.pitch
    canvas = np.full((view.size[1], view.size[0], 3), GRASS, np.uint8)
    return draw_markings(canvas, view.canvas, markings(length, width, corner_arcs=True), colour, 2)


def render_dots(video: str | Path, tracks: pd.DataFrame, out: str | Path, speed: int = 4, background: str = "median", width: int = 1920, radius: int = 7, trail: int = 0, label: str = "", max_frames: int | None = None, crf: int = 20, pitch: tuple[pd.DataFrame, float, float] | None = None, view: str = "image", lines: bool = False) -> Path:
    """Write an H.264 clip of ``tracks`` drawn as dots; colour by ``team`` when present, the ball in yellow.

    pitch is (homographies, length, width): a flocker.pitch.track_pitch table for this video and the pitch's size. It is
    needed for view "pitch" (straight down onto the pitch), for background "pitch", and for ``lines``, which draws the
    pitch's markings where the homographies put them (a check of the fit). trail draws each object's last ``trail``
    output frames as a fading line. Returns the output path.
    """
    if background not in ("median", "frame", "pitch"):
        raise ValueError("background must be 'median', 'frame' or 'pitch'")
    if view not in ("image", "pitch"):
        raise ValueError("view must be 'image' or 'pitch'")
    if pitch is None and (view == "pitch" or background == "pitch" or lines):
        raise ValueError("the pitch view, the drawn pitch and lines need homographies (pitch=...)")
    if background == "pitch" and view != "pitch":
        raise ValueError("background 'pitch' is drawn in the pitch view only")
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    v = View(src, width, pitch if view == "pitch" else None)
    hs = None
    if lines:
        from flocker.pitch import draw_markings, homography_of, markings

        hs = homography_of(pitch[0])
        marks = markings(pitch[1], pitch[2], corner_arcs=True)
    size = v.size
    bg = median_background(video, view=v, max_frames=v.max_frame) if background == "median" else drawn_pitch(v) if background == "pitch" else None
    t = tracks.copy()
    t[["cx", "cy"]] = centers(t)
    if "team" not in t.columns:
        t["team"] = -1
    by_frame = dict(iter(t.groupby("frame")))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_path(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{size[0]}x{size[1]}", "-r", f"{fps:.5f}", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    history: dict[int, list[tuple[float, float]]] = {}
    f = 0
    try:
        last = min(x for x in (max_frames, v.max_frame) if x is not None) if (max_frames or v.max_frame) else None
        while last is None or f < last:
            ok, img = cap.read()
            if not ok:
                break
            f += 1
            g = by_frame.get(f)
            if g is not None:
                pts = _apply(v.transform(f), g[["cx", "cy"]].to_numpy(float))
                for r, (px, py) in zip(g.itertuples(), pts):
                    history.setdefault(r.id, []).append((px, py))
            if (f - 1) % speed:
                continue
            canvas = bg.copy() if bg is not None else v.warp(img, f)
            if lines:
                h_draw = v.transform(f) @ np.linalg.inv(hs[f])
                draw_markings(canvas, h_draw, marks, (0, 0, 255), 1)
            if g is not None:
                for r, (px, py) in zip(g.itertuples(), pts):
                    colour = BALL_COLOUR if r.cls == BALL else TEAM_COLOURS.get(int(r.team), TEAM_COLOURS[-1])
                    if trail:
                        path = np.array(history[r.id][-trail * speed :: speed], np.int32)
                        if len(path) > 1:
                            cv2.polylines(canvas, [path], False, colour, 1, cv2.LINE_AA)
                    rad = max(2, radius // 2) if r.cls == BALL else radius
                    cv2.circle(canvas, (int(px), int(py)), rad, colour, -1, cv2.LINE_AA)
                    cv2.circle(canvas, (int(px), int(py)), rad, (20, 20, 20), 1, cv2.LINE_AA)
            text = f"{label}  frame {f}  {speed}x" if label else f"frame {f}  {speed}x"
            cv2.putText(canvas, text, (16, size[1] - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
            proc.stdin.write(canvas.tobytes())
    finally:
        cap.release()
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {out}")
    return out


def _apply(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    q = np.column_stack([pts, np.ones(len(pts))]) @ h.T
    return q[:, :2] / q[:, 2:3]
