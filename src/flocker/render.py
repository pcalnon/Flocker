"""Render tracks as dots: the owner's edits 2 (replace players with dots) and 5 (speed up playback).

Project: Flocker
File: src/flocker/render.py
Purpose: draw each tracked object as a dot, over the original frames or over the clip's empty pitch, at N x speed
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE); rendered clips derive from their sources and keep the sources' licences

Background "median": the camera above TeamTrack's pitch barely moves (about 12 px over the whole match), so the
per-pixel median of frames sampled across a clip shows the pitch with the players erased; moving shadows vanish
with them. Drawing the dots on that background replaces the players. Background "frame" keeps the original video.

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


def ffmpeg_path() -> str:
    """The ffmpeg beside this interpreter (the Flocker environment's GPL build), else the first on PATH."""
    candidate = Path(sys.prefix) / "bin" / "ffmpeg"
    return str(candidate) if candidate.is_file() else "ffmpeg"


def median_background(video: str | Path, size: tuple[int, int], samples: int = 45) -> np.ndarray:
    """Per-pixel median of ``samples`` frames spread over the clip, resized to size = (width, height)."""
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for f in np.linspace(0, n - 1, samples).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        ok, img = cap.read()
        if ok:
            frames.append(cv2.resize(img, size, interpolation=cv2.INTER_AREA))
    cap.release()
    if not frames:
        raise ValueError(f"could not read frames from {video}")
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def render_dots(video: str | Path, tracks: pd.DataFrame, out: str | Path, speed: int = 4, background: str = "median", width: int = 1920, radius: int = 7, trail: int = 0, label: str = "", max_frames: int | None = None, crf: int = 20) -> Path:
    """Write an H.264 clip of ``tracks`` drawn as dots; colour by ``team`` when present, the ball in yellow.

    trail draws each object's last ``trail`` output frames as a fading line. Returns the output path.
    """
    if background not in ("median", "frame"):
        raise ValueError("background must be 'median' or 'frame'")
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w, src_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = width / src_w
    size = (width, int(round(src_h * scale / 2)) * 2)
    bg = median_background(video, size) if background == "median" else None
    t = tracks.copy()
    t[["cx", "cy"]] = centers(t) * scale
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
        while max_frames is None or f < max_frames:
            ok, img = cap.read()
            if not ok:
                break
            f += 1
            g = by_frame.get(f)
            if g is not None:
                for r in g.itertuples():
                    history.setdefault(r.id, []).append((r.cx, r.cy))
            if (f - 1) % speed:
                continue
            canvas = bg.copy() if bg is not None else cv2.resize(img, size, interpolation=cv2.INTER_AREA)
            if g is not None:
                for r in g.itertuples():
                    colour = BALL_COLOUR if r.cls == BALL else TEAM_COLOURS.get(int(r.team), TEAM_COLOURS[-1])
                    if trail:
                        pts = np.array(history[r.id][-trail * speed :: speed], np.int32)
                        if len(pts) > 1:
                            cv2.polylines(canvas, [pts], False, colour, 1, cv2.LINE_AA)
                    rad = max(2, radius // 2) if r.cls == BALL else radius
                    cv2.circle(canvas, (int(r.cx), int(r.cy)), rad, colour, -1, cv2.LINE_AA)
                    cv2.circle(canvas, (int(r.cx), int(r.cy)), rad, (20, 20, 20), 1, cv2.LINE_AA)
            text = f"{label}  frame {f}  {speed}x" if label else f"frame {f}  {speed}x"
            cv2.putText(canvas, text, (16, size[1] - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
            proc.stdin.write(canvas.tobytes())
    finally:
        cap.release()
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {out}")
    return out
