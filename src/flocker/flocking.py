"""Collective motion: how far each team moves as a flock, in pitch metres.

Project: Flocker
File: src/flocker/flocking.py
Purpose: players' velocities from pitch positions; per team and frame, the order parameters of collective motion
    (polarisation, milling), cohesion (spread, convex hull, length and width) and nearest-neighbour structure; null
    models that keep each player's own motion and break only the synchrony between players
Author: Paul Calnon
Created: 2026-11-25
License: CC0 1.0 (see LICENSE)

Positions are flocker.pitch metres (mx, my): the origin is the centre mark, x runs toward the goal on the right of the
video and y toward the touchline at the bottom. Seen from above, that frame is left-handed, so a positive cross product
(a turn from x toward y) is clockwise as seen in the video: positive milling is a clockwise rotation in the video.

Velocities (kinematics): each player's track is cut into runs of consecutive frames, and cut again wherever it steps
further than max_step in one frame. 0.4 m per frame at 29.97 frames per second is 12 m/s, faster than any footballer;
TeamTrack's ground truth has one-frame spikes, runs of impossible speed and permanent jumps of up to 24 m
(notes/FLOCKER_2026-11-25_FLOCKING-ANALYSIS.md). Each run at least ``window`` frames long is smoothed with a
Savitzky-Golay filter (0.5 s, quadratic) and differentiated; a shorter run gets no velocity. Box corners are whole
pixels, so raw positions jitter by about 1.2 cm per frame, and differences of raw positions would be noise.

The measures of a group (one team's outfield players, or both teams') in one frame (group_measures):
    hx, hy          the mean unit heading of the players moving at min_speed or faster
    polarisation    its length, |(hx, hy)|: 1 when all run the same way, about sqrt(pi / 4n) for n independent random
                    headings (0.28 for 10)
    polarisation_w  |sum of velocities| / sum of speeds: every player with a velocity, weighted by speed (at least two)
    milling         the mean, over moving players, of (unit vector from the group's centroid) x (unit heading): +1 for
                    a group circling its centroid clockwise in the video, -1 anticlockwise, 0 for no rotation
    radius          RMS distance from the centroid (the radius of gyration), m
    hull_area       area of the convex hull of the positions, m^2
    length, width   extent along x (goal to goal) and along y (touchline to touchline), m
    nn_mean         mean distance from each player to the nearest other player of the group, m
    nn_opponent     (one team) mean distance from each player to the nearest player of the other team, m
    vx, vy          the group's mean velocity (its centroid's velocity when no one is missing), m/s

Nulls (mix_clips, shuffle_within, shift_ids):
    mixed clips     each player's whole track (positions and velocities together) comes from a different clip, minutes
                    apart: every player keeps their own motion (speeds, preferred directions and, on TeamTrack, where
                    they play: an id keeps its role from clip to clip), but nothing synchronises the players any more
    shuffle         velocities swapped at random among a group's players within each frame: the group keeps its shape
                    and its set of velocities, but loses which player runs which way
    time shift      each player moved in time within the clip by their own random offset. A weaker null: the offsets
                    are independent, so many pairs of players stay within a few seconds of each other, where real
                    headings are still correlated (notes/FLOCKER_2026-11-25_FLOCKING-ANALYSIS.md)
"""

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter
from scipy.spatial import ConvexHull, QhullError

from flocker.mot import BALL

FPS = 29.97  # TeamTrack's frame rate (seqinfo.ini)
SMOOTH_FRAMES = 15  # 0.5 s Savitzky-Golay window
SMOOTH_ORDER = 2
MAX_STEP_M = 0.4  # metres in one frame: 12 m/s
BALL_MAX_STEP_M = 1.5  # 45 m/s, faster than any shot
MIN_SPEED = 0.5  # m/s; a slower player has no heading
GOALKEEPER_IDS = (0, 13)  # TeamTrack ground truth (tests/test_flocking.py checks it on real data)
GROUPS = (("0", (0,)), ("1", (1,)), ("both", (0, 1)))
MEASURES = ("n", "n_moving", "cx", "cy", "vx", "vy", "speed_mean", "hx", "hy", "polarisation", "polarisation_w", "milling", "radius", "hull_area", "length", "width", "nn_mean")


def run_ids(frames, x, y, max_step: float = MAX_STEP_M) -> np.ndarray:
    """The run number of each point of one track, sorted by frame: a new run starts after a missing frame, or after a
    step longer than max_step metres (or a step that is not a number)."""
    frames = np.asarray(frames)
    if len(frames) == 0:
        return np.zeros(0, int)
    step = np.hypot(np.diff(np.asarray(x, float)), np.diff(np.asarray(y, float)))
    cut = (np.diff(frames) != 1) | ~(step <= max_step)
    return np.concatenate([[0], np.cumsum(cut)])


def kinematics(df: pd.DataFrame, fps: float = FPS, window: int = SMOOTH_FRAMES, order: int = SMOOTH_ORDER, max_step: float = MAX_STEP_M, x: str = "mx", y: str = "my") -> pd.DataFrame:
    """``df`` (rows of frame, id and a position x, y in metres) sorted by id and frame, with each row's run number
    (``run``), its smoothed position (sx, sy), its velocity (vx, vy, metres per second) and its speed. Rows on runs
    shorter than ``window`` frames get NaN for all five."""
    if window % 2 == 0 or window <= order:
        raise ValueError(f"window must be odd and longer than order, not {window} with order {order}")
    out = df.sort_values(["id", "frame"], kind="stable").reset_index(drop=True)
    n = len(out)
    run = np.zeros(n, int)
    res = {k: np.full(n, np.nan) for k in ("sx", "sy", "vx", "vy")}
    ids, frames = out["id"].to_numpy(), out["frame"].to_numpy()
    px, py = out[x].to_numpy(float), out[y].to_numpy(float)
    starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]]) if n else np.zeros(0, int)
    for a, b in zip(starts, np.r_[starts[1:], n]):
        r = run_ids(frames[a:b], px[a:b], py[a:b], max_step)
        run[a:b] = r
        cuts = np.flatnonzero(np.r_[True, r[1:] != r[:-1]]) + a
        for c, d in zip(cuts, np.r_[cuts[1:], b]):
            if d - c < window:
                continue
            for src, s, v in ((px, "sx", "vx"), (py, "sy", "vy")):
                res[s][c:d] = savgol_filter(src[c:d], window, order)
                res[v][c:d] = savgol_filter(src[c:d], window, order, deriv=1) * fps
    return out.assign(run=run, **res, speed=np.hypot(res["vx"], res["vy"]))


def group_measures(xy, v=None, min_speed: float = MIN_SPEED) -> dict:
    """The measures of one group in one frame (see the module docstring): xy is an n x 2 array of positions in metres,
    v an n x 2 array of velocities in metres per second (a row of NaN for a player without one). Polarisation and
    milling need at least two moving players, the hull three players not on one line (else 0); anything that cannot
    be measured is NaN."""
    xy = np.asarray(xy, float).reshape(-1, 2)
    out = dict.fromkeys(MEASURES, np.nan)
    out["n"], out["n_moving"] = len(xy), 0
    if len(xy) == 0:
        return out
    c = xy.mean(axis=0)
    r = xy - c
    d = np.hypot(r[:, 0], r[:, 1])
    out.update(cx=c[0], cy=c[1], radius=float(np.sqrt(np.mean(d**2))), length=float(np.ptp(xy[:, 0])), width=float(np.ptp(xy[:, 1])))
    if len(xy) >= 2:
        dist = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
        np.fill_diagonal(dist, np.inf)
        out["nn_mean"] = float(dist.min(axis=1).mean())
    if len(xy) >= 3:
        try:
            out["hull_area"] = float(ConvexHull(xy).volume)  # in 2-D, qhull's "volume" is the area
        except QhullError:  # all on one line (or one point)
            out["hull_area"] = 0.0
    if v is None:
        return out
    v = np.asarray(v, float).reshape(-1, 2)
    has = np.isfinite(v).all(axis=1)
    if not has.any():
        return out
    speed = np.hypot(v[:, 0], v[:, 1])
    out["vx"], out["vy"] = (float(m) for m in v[has].mean(axis=0))
    out["speed_mean"] = float(speed[has].mean())
    total = speed[has].sum()
    out["polarisation_w"] = float(np.hypot(*v[has].sum(axis=0)) / total) if total > 0 and has.sum() >= 2 else np.nan
    s = np.where(has, speed, 0.0)
    moving = has & (s >= min_speed) & (s > 0)
    out["n_moving"] = int(moving.sum())
    if moving.any():  # one mover has a heading (an opponent's baseline needs it), but no polarisation
        u = v[moving] / speed[moving, None]
        out["hx"], out["hy"] = (float(m) for m in u.mean(axis=0))
    if moving.sum() >= 2:
        out["polarisation"] = float(np.hypot(out["hx"], out["hy"]))
        away = d[moving] > 0
        if away.any():
            rhat = r[moving][away] / d[moving][away, None]
            out["milling"] = float(np.mean(rhat[:, 0] * u[away, 1] - rhat[:, 1] * u[away, 0]))
    return out


def _frame_slices(frames: np.ndarray):
    """(start, stop) of each frame's rows in an array sorted by frame."""
    starts = np.flatnonzero(np.r_[True, frames[1:] != frames[:-1]]) if len(frames) else np.zeros(0, int)
    return zip(starts, np.r_[starts[1:], len(frames)])


def frame_measures(kin: pd.DataFrame, min_speed: float = MIN_SPEED, groups=GROUPS, x: str = "mx", y: str = "my") -> pd.DataFrame:
    """One row per frame and group (by default team 0, team 1 and both): group_measures of the group's players, from
    a kinematics() table with a ``team`` column (0 or 1). One-team groups also get nn_opponent."""
    k = kin.sort_values(["frame", "team", "id"], kind="stable")
    frames, teams = k["frame"].to_numpy(), k["team"].to_numpy()
    xy, v = k[[x, y]].to_numpy(float), k[["vx", "vy"]].to_numpy(float)
    rows = []
    for a, b in _frame_slices(frames):
        t, p, w = teams[a:b], xy[a:b], v[a:b]
        for name, members in groups:
            sel = np.isin(t, members)
            m = group_measures(p[sel], w[sel], min_speed)
            if len(members) == 1:
                other = ~sel & np.isin(t, (0, 1))
                m["nn_opponent"] = float(np.hypot(*(p[sel][:, None, :] - p[other][None, :, :]).transpose(2, 0, 1)).min(axis=1).mean()) if sel.any() and other.any() else np.nan
            rows.append({"frame": int(frames[a]), "group": name, **m})
    out = pd.DataFrame(rows, columns=["frame", "group", *MEASURES, "nn_opponent"])
    return out.astype({"frame": "int64", "n": "int64", "n_moving": "int64"})


def neighbour_pairs(kin: pd.DataFrame, k_max: int = 10, min_speed: float = MIN_SPEED, x: str = "mx", y: str = "my") -> pd.DataFrame:
    """Every moving player's k_max nearest teammates and k_max nearest opponents, in each frame of a kinematics()
    table with a ``team`` column: one row per (player, neighbour) with the neighbour's rank (1 = nearest, counted
    among all players of that relation present, moving or not), its distance (m), ``align``, the cosine between the
    two players' headings (NaN when the neighbour is not moving), ``bearing``, the cosine between the player's heading
    and the direction to the neighbour (1 straight ahead, -1 behind, 0 to the side), and ``axis_x``, the cosine between
    that direction and the pitch's x axis (its absolute value: 1 along the pitch, 0 across it)."""
    k = kin.sort_values(["frame", "team", "id"], kind="stable")
    frames, teams, ids = k["frame"].to_numpy(), k["team"].to_numpy(), k["id"].to_numpy()
    xy, v = k[[x, y]].to_numpy(float), k[["vx", "vy"]].to_numpy(float)
    speed = np.nan_to_num(np.hypot(v[:, 0], v[:, 1]))
    moving = (speed >= min_speed) & (speed > 0)
    u = np.where(moving[:, None], v / np.where(moving, speed, 1.0)[:, None], np.nan)
    cols = {c: [] for c in ("frame", "id", "team", "relation", "rank", "other", "distance", "align", "bearing", "axis_x")}
    for a, b in _frame_slices(frames):
        p, t, h, mv = xy[a:b], teams[a:b], u[a:b], moving[a:b]
        kk = min(k_max, len(p) - 1)
        if kk < 1:
            continue
        diff = p[None, :, :] - p[:, None, :]  # [i, j] = p_j - p_i
        dist = np.hypot(diff[..., 0], diff[..., 1])
        same = t[:, None] == t[None, :]
        np.fill_diagonal(same, False)
        for relation, mask in (("teammate", same), ("opponent", t[:, None] != t[None, :])):
            dm = np.where(mask, dist, np.inf)
            i = np.repeat(np.arange(len(p)), kk)
            j = np.argsort(dm, axis=1, kind="stable")[:, :kk].ravel()
            rank = np.tile(np.arange(1, kk + 1), len(p))
            dd = dm[i, j]
            keep = mv[i] & np.isfinite(dd)
            i, j, rank, dd = i[keep], j[keep], rank[keep], dd[keep]
            direction = diff[i, j] / np.where(dd > 0, dd, 1.0)[:, None]
            for c, val in (("frame", np.full(len(i), frames[a])), ("id", ids[a:b][i]), ("team", t[i]), ("relation", np.full(len(i), relation)), ("rank", rank), ("other", ids[a:b][j]), ("distance", dd), ("align", np.einsum("ij,ij->i", h[i], h[j])), ("bearing", np.einsum("ij,ij->i", h[i], direction)), ("axis_x", np.abs(direction[:, 0]))):
                cols[c].append(val)
    return pd.DataFrame({c: np.concatenate(parts) if parts else np.zeros(0) for c, parts in cols.items()})


def shift_ids(df: pd.DataFrame, rng: np.random.Generator, n_frames: int, min_shift: int, ids=None, same: bool = False) -> pd.DataFrame:
    """``df`` with the rows of each id in ``ids`` (default: every id) moved in time, circularly within frames
    1..n_frames: frame f becomes (f - 1 + s) mod n_frames + 1. Each id gets its own offset s, drawn uniformly from
    min_shift..n_frames - min_shift, or all of them one offset when ``same``. Everything else in a row stays with it.

    The offsets are independent, so two ids can land close in time to each other (with 900 frames and min_shift 150,
    44 % of pairs end up within 150 frames): as a null for the synchrony between ids, mix_clips is cleaner."""
    if not 0 < min_shift <= n_frames - min_shift:
        raise ValueError(f"min_shift {min_shift} does not fit in {n_frames} frames")
    out = df.copy()
    chosen = np.unique(out["id"]) if ids is None else np.unique(np.asarray(ids))
    offsets = np.full(len(chosen), rng.integers(min_shift, n_frames - min_shift + 1)) if same else rng.integers(min_shift, n_frames - min_shift + 1, len(chosen))
    s = out["id"].map(dict(zip(chosen.tolist(), offsets.tolist()))).fillna(0).astype(int).to_numpy()
    out["frame"] = (out["frame"].to_numpy() - 1 + s) % n_frames + 1
    return out.sort_values(["id", "frame"], kind="stable").reset_index(drop=True)


def shuffle_within(df: pd.DataFrame, rng: np.random.Generator, by=("frame", "team"), cols=("vx", "vy")) -> pd.DataFrame:
    """``df`` with the values of ``cols`` (kept together, row by row) permuted at random among the rows of each group
    (``by``) where they are all finite. Rows where any is NaN keep their NaN."""
    out = df.copy()
    vals = out[list(cols)].to_numpy(float)
    rows = np.flatnonzero(np.isfinite(vals).all(axis=1))
    group = out.iloc[rows].groupby(list(by), sort=False).ngroup().to_numpy()
    in_order = rows[np.argsort(group, kind="stable")]
    shuffled = rows[np.lexsort((rng.random(len(rows)), group))]
    new = vals.copy()
    new[in_order] = vals[shuffled]
    out[list(cols)] = new
    if {"vx", "vy", "speed"} <= set(out.columns):
        out["speed"] = np.hypot(out["vx"], out["vy"])
    return out


def draw_clips(names, n: int, rng: np.random.Generator, exclude=()) -> list:
    """``n`` different clip names drawn at random from ``names``, none of them in ``exclude``."""
    pool = [x for x in names if x not in set(exclude)]
    if n > len(pool):
        raise ValueError(f"cannot draw {n} different clips from {len(pool)}")
    return [pool[k] for k in rng.choice(len(pool), n, replace=False)]


def mix_clips(clips: dict, plan: dict) -> pd.DataFrame:
    """A clip assembled from others: the rows of each id from the clip that ``plan[id]`` names (``clips`` maps a name
    to a table with frame and id). Ids taken from different clips share no moment of play, so nothing synchronises
    them, while each keeps its whole track. draw_clips makes a plan with every id from a different clip."""
    return pd.concat([clips[name][clips[name]["id"] == i] for i, name in plan.items()], ignore_index=True)


def lagged_correlation(a, b, lags) -> np.ndarray:
    """Pearson's correlation of a(t) with b(t + lag), for each lag (in samples), over the times where both are finite;
    NaN with fewer than three such times. A peak at a positive lag means that b follows a."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = len(a)
    out = np.full(len(lags), np.nan)
    for k, lag in enumerate(lags):
        lag = int(lag)
        if abs(lag) >= n:
            continue
        p, q = (a[: n - lag], b[lag:]) if lag >= 0 else (a[-lag:], b[: n + lag])
        ok = np.isfinite(p) & np.isfinite(q)
        if ok.sum() >= 3 and np.std(p[ok]) > 0 and np.std(q[ok]) > 0:
            out[k] = float(np.corrcoef(p[ok], q[ok])[0, 1])
    return out


def players_from_gt(gt: pd.DataFrame, keepers=GOALKEEPER_IDS) -> pd.DataFrame:
    """The outfield players of a ground-truth frame (flocker.teamtrack.load_gt): no ball, and no goalkeepers."""
    return gt[(gt["cls"] != BALL) & ~gt["id"].isin(keepers)].reset_index(drop=True)


def players_from_tracks(tracks: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
    """The player tracks (class PLAYER, or UNKNOWN for class-less tracker output, as flocker.teamtrack.select_objects
    takes them) whose track carries team 0 or 1 in ``teams`` (id, team: track --teams' teams/<seq>.csv), with a
    ``team`` column. Team -1 (the goalkeepers, and anyone unlabelled) and the ball are left out."""
    team = tracks["id"].map(teams.set_index("id")["team"]).fillna(-1).astype(int)
    keep = (tracks["cls"] != BALL).to_numpy() & team.isin((0, 1)).to_numpy()
    return tracks[keep].assign(team=team[keep]).reset_index(drop=True)
