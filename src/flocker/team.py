"""Team labels from kit colour: which team each detected player belongs to.

Project: Flocker
File: src/flocker/team.py
Purpose: measure each detection's kit colour against the clip's empty pitch, and label detections and tracks by team
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

Colour: the camera above the pitch is static, so the per-pixel median of frames sampled across a clip is the empty
pitch (the players move, the pitch does not). Inside a detection box, the pixels that differ from that background by
more than FG_THRESHOLD in CIE Lab are the player; their mean Lab colour is the detection's kit colour. Pitch lines
are part of the background, so a player standing on a line is not mistaken for a white kit.

Teams: in one clip, the outfield players of the two teams form two large, compact colour clusters. Goalkeepers and
referees wear other colours, and assigning them to the nearer outfield cluster would often be wrong (on TeamTrack,
the red goalkeeper is nearer the blue team and the yellow one nearer the white team). fit_teams() therefore finds
the two outfield clusters, then marks every colour far from both as OTHER instead of forcing it into a team.

OpenCV's 8-bit Lab is used throughout: L, a and b each run 0-255, and neutral a and b are 128.
"""

from dataclasses import dataclass

import cv2
import numpy as np
import pandas as pd

from flocker.mot import PLAYER

FG_THRESHOLD = 25.0  # Lab distance from the background above which a pixel belongs to the player
MIN_FG_PIXELS = 5
OTHER = -1


def clip_background(video, samples: int = 45, max_frames: int | None = None) -> np.ndarray:
    """Full-resolution per-pixel median of ``samples`` frames spread over the clip, read in one sequential pass
    (seeking in long-GOP H.264 decodes from the previous keyframe each time, which is several times slower)."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(video)
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
                frames.append(img)
    cap.release()
    if not frames:
        raise ValueError(f"could not read frames from {video}")
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def box_colours(frame: np.ndarray, bg_lab: np.ndarray, xyxy: np.ndarray, threshold: float = FG_THRESHOLD) -> np.ndarray:
    """For each box (N x 4, xyxy pixels) of a BGR frame, [L, a, b, n_fg]: the mean Lab colour of its foreground pixels
    (those further than ``threshold`` from the background, given in float Lab) and their count. Colour is NaN with
    under MIN_FG_PIXELS. Only the boxes are converted to Lab, not the whole frame (the same values, as cvtColor works
    pixel by pixel, at a fraction of the cost)."""
    h, w = frame.shape[:2]
    out = np.full((len(xyxy), 4), np.nan, np.float32)
    for i, (x0, y0, x1, y1) in enumerate(np.round(xyxy).astype(int)):
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            out[i, 3] = 0
            continue
        p = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2LAB).astype(np.float32).reshape(-1, 3)
        fg = np.linalg.norm(p - bg_lab[y0:y1, x0:x1].reshape(-1, 3), axis=1) > threshold
        out[i, 3] = fg.sum()
        if fg.sum() >= MIN_FG_PIXELS:
            out[i, :3] = p[fg].mean(axis=0)
    return out


def detection_colours(video, dets: pd.DataFrame, background: np.ndarray | None = None, samples: int = 45) -> pd.DataFrame:
    """Kit colour of every row of ``dets`` (a flocker.mot frame of one video): columns L, a, b, n_fg, indexed like
    dets. The background defaults to clip_background(video, samples)."""
    bg = clip_background(video, samples) if background is None else background
    bg_lab = cv2.cvtColor(bg, cv2.COLOR_BGR2LAB).astype(np.float32)
    out = np.full((len(dets), 4), np.nan, np.float32)
    by_frame = dets.groupby("frame").indices
    cap = cv2.VideoCapture(str(video))
    last = max(by_frame) if by_frame else 0
    f = 0
    while f < last:
        ok, img = cap.read()
        if not ok:
            break
        f += 1
        rows = by_frame.get(f)
        if rows is None:
            continue
        d = dets.iloc[rows]
        xyxy = np.column_stack([d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"]])
        out[rows] = box_colours(img, bg_lab, xyxy)
    cap.release()
    return pd.DataFrame(out, columns=["L", "a", "b", "n_fg"], index=dets.index)


@dataclass
class TeamModel:
    """Two outfield-team colour clusters (Gaussian, in Lab) and the squared Mahalanobis radius of membership."""

    means: np.ndarray  # 2 x 3
    covs: np.ndarray  # 2 x 3 x 3
    max_d2: float

    def d2(self, lab: np.ndarray) -> np.ndarray:
        """Squared Mahalanobis distance of each colour (N x 3) to each team (N x 2); NaN for a NaN colour."""
        lab = np.asarray(lab, float).reshape(-1, 3)
        out = np.empty((len(lab), 2))
        for k in range(2):
            diff = lab - self.means[k]
            out[:, k] = np.einsum("ni,ij,nj->n", diff, np.linalg.inv(self.covs[k]), diff)
        return out

    def predict(self, lab: np.ndarray) -> np.ndarray:
        """Team 0 or 1 for each colour, or OTHER when it is within max_d2 of neither team (or is NaN)."""
        d2 = self.d2(lab)
        near = np.nanmin(np.where(np.isfinite(d2), d2, np.inf), axis=1)
        return np.where(near <= self.max_d2, np.argmin(np.where(np.isfinite(d2), d2, np.inf), axis=1), OTHER)


def _seed_teams(x: np.ndarray, k: int, seeds: int) -> np.ndarray:
    """Labels 0 and 1 for the two most populous clusters of the best (lowest inertia) of ``seeds`` k-means runs on
    standardised colours, -1 for the rest."""
    from scipy.cluster.vq import kmeans2

    z = x / (x.std(axis=0) + 1e-6)
    best, best_inertia = None, np.inf
    for s in range(seeds):
        centres, label = kmeans2(z, k, seed=s, minit="++")
        inertia = float(((z - centres[label]) ** 2).sum())
        if inertia < best_inertia:
            best, best_inertia = label, inertia
    big = np.argsort(-np.bincount(best, minlength=k))[:2]
    return np.select([best == big[0], best == big[1]], [0, 1], -1)


def fit_teams(lab: np.ndarray, max_d2: float = 11.34, iters: int = 20, k: int = 4, seeds: int = 5, min_share: float = 0.2) -> TeamModel:
    """Fit the two outfield teams' colour clusters to kit colours (N x 3 Lab; NaN rows are ignored).

    Seeding: k-means with k clusters (default 4: two kits and two goalkeepers), and the two most populous clusters are
    the teams. Ten outfield players outnumber a goalkeeper ten to one, but a goalkeeper's colours are far more compact,
    so 2-means can lock onto one goalkeeper as a "team" and merge both kits into the other; on TeamTrack's val split it
    did so in 3 of 9 clips. Refinement: each colour joins the team it is nearer by Mahalanobis distance if within max_d2
    (11.34 is the 99th percentile of chi-squared with 3 degrees of freedom), and each team's mean and covariance are
    refitted to its members only, so goalkeepers and referees fall outside both. A fit in which either team holds
    under min_share of the colours is refused. Team 0 is the brighter kit (higher mean L), so labels are reproducible.
    """
    x = np.asarray(lab, float)
    x = x[np.isfinite(x).all(axis=1)]
    if len(x) < 20 * k:
        raise ValueError(f"too few colours to fit two teams ({len(x)})")
    label = _seed_teams(x, k, seeds)
    model = TeamModel(np.stack([x[label == j].mean(axis=0) for j in range(2)]), np.stack([np.cov(x[label == j].T) + np.eye(3) for j in range(2)]), max_d2)
    for _ in range(iters):
        team = model.predict(x)
        if min((team == j).sum() for j in range(2)) < 10:
            raise ValueError("a team cluster lost all its members; the colours do not show two teams")
        new = TeamModel(np.stack([x[team == j].mean(axis=0) for j in range(2)]), np.stack([np.cov(x[team == j].T) + 0.25 * np.eye(3) for j in range(2)]), max_d2)
        converged = np.allclose(new.means, model.means, atol=0.01)
        model = new
        if converged:
            break
    share = np.bincount(model.predict(x) + 1, minlength=3)[1:] / len(x)
    if share.min() < min_share:
        raise ValueError(f"the colours do not show two teams: the clusters hold {share.round(3).tolist()} of them")
    order = np.argsort(-model.means[:, 0])
    return TeamModel(model.means[order], model.covs[order], max_d2)


def label_teams(dets: pd.DataFrame, colours: pd.DataFrame, min_conf: float = 0.3, **fit_kwargs) -> tuple[pd.DataFrame, TeamModel]:
    """``dets`` (one clip) with a ``team`` column, and the team model fitted to it.

    colours is row-aligned with dets (detection_colours). The model is fitted to the player detections with
    conf >= min_conf, whose labels are the most reliable (on TeamTrack's val split, 0.26 % of them at 0.3-0.5 went to
    the wrong team, against 1-4 % below 0.3). Every player detection then gets team 0 or 1, or OTHER when its colour is
    neither team's (goalkeepers, referees, boxes too mixed to tell); the ball gets OTHER.
    """
    if len(colours) != len(dets):
        raise ValueError(f"{len(colours)} colours for {len(dets)} detections; they must be row-aligned")
    lab = colours[["L", "a", "b"]].to_numpy(float)
    player = (dets["cls"] == PLAYER).to_numpy()
    model = fit_teams(lab[player & (dets["conf"].to_numpy() >= min_conf)], **fit_kwargs)
    return dets.assign(team=np.where(player, model.predict(lab), OTHER)), model
