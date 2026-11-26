"""The studies behind notes/FLOCKER_2026-11-25_FLOCKING-ANALYSIS.md: how far the two teams of TeamTrack's match move as
flocks, against null models, against the ball and against each other; from the ground truth, then from the tracks.

Project: Flocker
File: util/ad-hoc/2026-11-25_flocking_study.py
Purpose: single-use analyses for the flocking analysis; each subcommand writes CSV (and PNG) into --out
Author: Paul Calnon
Created: 2026-11-25
License: CC0 1.0 (see LICENSE)

Ran on 2026-11-25 with the Flocker environment, from a worktree (the code finds the media in the primary checkout):

    S=~/Development/python/Flocker/tmp/2026-11-25_homography
    F=~/Development/python/Flocker/tmp/2026-11-25_flocking
    I=~/Development/python/Flocker/tmp/2026-11-24_identity
    P="/opt/miniforge3/envs/Flocker/bin/python -I"
    export OMP_NUM_THREADS=1
    $P util/ad-hoc/2026-11-25_flocking_study.py audit --pitch-dir $S/pitch --out $F/study      # the ground truth's glitches
    $P util/ad-hoc/2026-11-25_flocking_study.py xcorr --pitch-dir $S/pitch --out $F/study      # why the null mixes clips
    $P util/ad-hoc/2026-11-25_flocking_study.py run --pitch-dir $S/pitch --out $F/study        # 54 clips, about 7 min
    $P util/ad-hoc/2026-11-25_flocking_study.py summary --out $F/study
    $P util/ad-hoc/2026-11-25_flocking_study.py tracks --pitch-dir $S/pitch --tracks $I/tracks --out $F/study
    $P util/ad-hoc/2026-11-25_flocking_study.py plots --out $F/study

The ground truth is used without the goalkeepers (ids 0 and 13) and without the six train clips whose labels drift
(flocker.yolo_dataset.MISALIGNED_TRAIN): 54 clips of 30 s from one 30-minute period, 10 outfield players a side.
Nothing is tuned: the smoothing (0.5 s), the glitch threshold (0.4 m per frame), the heading threshold (0.5 m/s) and
the bins are fixed in advance. The main null takes every player's track from a different clip (ids keep their roles
from clip to clip); the within-clip time shift is kept as a weaker comparison, since independent offsets leave many
pairs of players within seconds of each other (an independent review found this on 2026-11-25). Clips are the unit of resampling for confidence intervals (frames within a clip are
strongly correlated); they are 30 s pieces of a single match, so the intervals describe this match, not football.
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from flocker.flocking import BALL_MAX_STEP_M, MAX_STEP_M, draw_clips, frame_measures, kinematics, lagged_correlation, mix_clips, neighbour_pairs, players_from_gt, shift_ids, shuffle_within  # noqa: E402
from flocker.mot import BALL  # noqa: E402
from flocker.pitch import read_homographies, with_pitch_positions  # noqa: E402
from flocker.teamtrack import list_sequences, load_gt  # noqa: E402
from flocker.yolo_dataset import MISALIGNED_TRAIN  # noqa: E402

MIN_SHIFT_S = 5.0
LAGS = np.arange(-150, 151, 3)  # frames: +-5 s at 0.1 s
DIST_EDGES = np.r_[np.arange(0, 42, 2), 50, 60, 80, 120]
DENSITY_EDGES = (0, 8, 10, np.inf)  # a team's mean nearest-teammate distance, m
DENSITY_LABELS = ("<8 m", "8-10 m", ">=10 m")
BALL_DIST_EDGES = (0, 5, 10, 20, 30, 50, 150)
BALL_SPEED_EDGES = (0, 2, 5, 10, 15, 60)
MEANS = ["polarisation", "polarisation_w", "milling", "abs_milling", "radius", "hull_area", "length", "width", "nn_mean", "nn_opponent", "speed_mean", "n", "n_moving"]
BESIDE = np.sqrt(0.5)  # |cos| below this: more than 45 degrees off the line


def _sequences(splits=("train", "val", "test")):
    return [s for s in list_sequences(splits=splits) if s.name not in MISALIGNED_TRAIN]


def _load(seq, pitch_dir: Path):
    """(outfield players' kinematics with team, ball kinematics, fps, frames) of one clip, from the ground truth."""
    info = seq.seqinfo()
    gt = with_pitch_positions(load_gt(seq), read_homographies(pitch_dir / f"{seq.name}.csv"))
    kin = kinematics(players_from_gt(gt), fps=info["framerate"])
    ball = kinematics(gt[gt["cls"] == BALL], fps=info["framerate"], max_step=BALL_MAX_STEP_M)
    return kin, ball, info["framerate"], info["seqlength"]


# ---------------------------------------------------------------------------------------------------------------- audit


def _audit_one(task):
    seq, pitch_dir = task
    gt = with_pitch_positions(load_gt(seq), read_homographies(pitch_dir / f"{seq.name}.csv"))
    n_frames = seq.seqinfo()["seqlength"]
    pl = gt[gt["cls"] != BALL]
    jumps, steps = [], []
    for pid, g in gt.groupby("id"):
        g = g.sort_values("frame")
        f, x, y = g["frame"].to_numpy(), g["mx"].to_numpy(), g["my"].to_numpy()
        d, gap = np.hypot(np.diff(x), np.diff(y)), np.diff(f)
        limit = BALL_MAX_STEP_M if pid == 22 else MAX_STEP_M
        if pid != 22:
            steps.append(pd.DataFrame({"frame": f[1:][gap == 1], "step": d[gap == 1]}))
        for k in np.flatnonzero((d > limit) & (gap == 1)):  # a longer step after missing frames is a return, not a glitch
            back = float(np.hypot(x[k + 2] - x[k], y[k + 2] - y[k])) if k + 2 < len(x) else np.nan  # from the frame before to 2 frames on
            jumps.append({"sequence": seq.name, "id": int(pid), "frame": int(f[k + 1]), "step_m": float(d[k]), "speed_ms": float(d[k] * 29.97), "back_m": back})
    steps = pd.concat(steps)
    wide = steps[steps["step"] > 0.3]["frame"].value_counts()
    kin = kinematics(players_from_gt(gt))
    lo = pl[pl["team"] == 0].groupby("frame")["mx"].idxmin()
    hi = pl[pl["team"] == 1].groupby("frame")["mx"].idxmax()
    row = {
        "sequence": seq.name,
        "split": seq.split,
        "player_rows": int(len(pl)),
        "missing_player_rows": int(22 * n_frames - len(pl)),
        "ball_frames": int((gt["cls"] == BALL).sum()),
        "fixed_39px_boxes": float(((pl["w"] == 39) & (pl["h"] == 39)).mean()),
        "keeper0_deepest": float((pl.loc[lo, "id"] == 0).mean()),
        "keeper13_deepest": float((pl.loc[hi, "id"] == 13).mean()),
        "steps_over_0.4m": int((steps["step"] > MAX_STEP_M).sum()),
        "frame_wide_events": ";".join(f"{int(k)}:{v}" for k, v in wide[wide >= 4].items()),
        "outfield_rows": int(len(kin)),
        "outfield_rows_without_velocity": int(kin["vx"].isna().sum()),
        "outfield_runs": int(kin.groupby("id")["run"].nunique().sum()),
        "outfield_speed_max": float(kin["speed"].max()),
    }
    return row, jumps


def cmd_audit(args) -> None:
    seqs = list_sequences()
    with ProcessPoolExecutor(args.jobs) as ex:
        res = list(ex.map(_audit_one, [(s, args.pitch_dir) for s in seqs]))
    clips = pd.DataFrame([r for r, _ in res])
    jumps = pd.DataFrame([j for _, js in res for j in js])
    out = args.out / "audit"
    out.mkdir(parents=True, exist_ok=True)
    clips.to_csv(out / "clips.csv", index=False, float_format="%.4f")
    jumps.to_csv(out / "jumps.csv", index=False, float_format="%.3f")
    used = clips[~clips["sequence"].isin(MISALIGNED_TRAIN)]
    print(f"{len(clips)} clips; {len(used)} used. One-frame steps over the glitch thresholds: {len(jumps)} ({(jumps['id'] != 22).sum()} players, {(jumps['id'] == 22).sum()} ball) in {jumps['sequence'].nunique()} clips; {jumps['sequence'].isin(used['sequence']).sum()} of them in the clips used")
    print(jumps.sort_values("step_m", ascending=False).head(12).round(2).to_string(index=False))
    pj = jumps[jumps["id"] != 22]
    print(f"player steps over 0.4 m: {len(pj)}; over 1 m: {(pj['step_m'] > 1).sum()}; one-frame spikes (back within 0.3 m two frames on): {(pj['back_m'] < 0.3).sum()}")
    print(f"in clips with fixed 39 px boxes (> 50 % of rows): {pj['sequence'].isin(clips.loc[clips['fixed_39px_boxes'] > 0.5, 'sequence']).sum()} of {len(pj)}; such clips: {(clips['fixed_39px_boxes'] > 0.5).sum()}")
    print("frame-wide events (4+ players stepping over 0.3 m at once):", clips.loc[clips["frame_wide_events"] != "", ["sequence", "frame_wide_events"]].to_string(index=False))
    print(used[["missing_player_rows", "ball_frames", "keeper0_deepest", "keeper13_deepest", "outfield_rows_without_velocity", "outfield_runs", "outfield_speed_max"]].describe().round(3).to_string())
    print(f"used clips: outfield rows without a velocity {used['outfield_rows_without_velocity'].sum()} of {used['outfield_rows'].sum()} ({used['outfield_rows_without_velocity'].sum() / used['outfield_rows'].sum():.3%})")


# ------------------------------------------------------------------------------------------------------------------ run


def _clip_means(table: pd.DataFrame, variant: str, rep: int) -> pd.DataFrame:
    t = table.assign(abs_milling=table["milling"].abs())
    return t.groupby("group")[MEANS].mean().reset_index().assign(variant=variant, rep=rep)


def _baselined(pairs: pd.DataFrame, ftab: pd.DataFrame) -> pd.DataFrame:
    """Neighbour pairs with the alignment expected of a random pair from the same frames: for teammates, the mean of
    u_i . u_j over all pairs of the team's moving players, (m p^2 - 1) / (m - 1); for opponents, h_A . h_B, the dot
    product of the two teams' mean headings. ``excess`` is the alignment beyond it."""
    t = ftab[ftab["group"].isin(["0", "1"])].assign(team=lambda d: d["group"].astype(int))[["frame", "team", "n_moving", "polarisation", "hx", "hy", "nn_mean"]]
    p = pairs.merge(t, on=["frame", "team"], how="left").assign(oteam=lambda d: 1 - d["team"])
    p = p.merge(t.rename(columns={"team": "oteam", "hx": "ohx", "hy": "ohy"})[["frame", "oteam", "ohx", "ohy"]], on=["frame", "oteam"], how="left")
    m, pol = p["n_moving"].to_numpy(float), p["polarisation"].to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mate = (m * pol**2 - 1) / (m - 1)
    p["baseline"] = np.where(p["relation"] == "teammate", mate, p["hx"] * p["ohx"] + p["hy"] * p["ohy"])
    p["excess"] = p["align"] - p["baseline"]
    p["density"] = pd.cut(p["nn_mean"], DENSITY_EDGES, right=False, labels=DENSITY_LABELS)
    return p


def _sums(p: pd.DataFrame, keys) -> pd.DataFrame:
    a = p[np.isfinite(p["align"]) & np.isfinite(p["baseline"])]
    g = a.groupby(keys, observed=True)
    return pd.DataFrame({"n": g.size(), "sum_align": g["align"].sum(), "sum_baseline": g["baseline"].sum(), "sum_excess": g["excess"].sum(), "sum_distance": g["distance"].sum()}).reset_index()


def _anisotropy(pairs: pd.DataFrame, variant: str) -> pd.DataFrame:
    """The nearest teammate of each moving player: where it lies relative to the player's heading, and to the pitch."""
    a = pairs[(pairs["relation"] == "teammate") & (pairs["rank"] == 1)]
    ab = a["bearing"].abs()
    return pd.DataFrame([{"variant": variant, "n": len(a), "sum_abs_bearing": ab.sum(), "beside": int((ab < BESIDE).sum()), "sum_axis_x": a["axis_x"].sum(), "across": int((a["axis_x"] < BESIDE).sum())}])


_CLIPS: dict = {}  # name -> (players' kinematics, ball kinematics, fps, frames), filled by cmd_run before its workers fork


def _load_task(task):
    seq, pitch_dir = task
    return seq.name, _load(seq, pitch_dir)


def _plan_mix(name: str, kin: pd.DataFrame, rng) -> dict:
    """Every outfield id of clip ``name`` from a different other clip (ids keep their roles from clip to clip)."""
    ids = sorted(kin["id"].unique())
    return dict(zip(ids, draw_clips(list(_CLIPS), len(ids), rng, exclude=[name])))


def _plan_team_mix(name: str, kin: pd.DataFrame, rng) -> dict:
    """Team 0 from clip ``name`` itself, team 1 (all its ids together) from one other clip."""
    other = draw_clips(list(_CLIPS), 1, rng, exclude=[name])[0]
    return {int(i): (name if t == 0 else other) for i, t in kin.groupby("id")["team"].first().items()}


def _clip(task):
    name, reps, seed = task
    rng = np.random.default_rng([seed, int(name[13:17])])
    kin, ball, fps, n_frames = _CLIPS[name]
    kins = {k: v[0] for k, v in _CLIPS.items()}
    min_shift = round(MIN_SHIFT_S * fps)
    real = frame_measures(kin)
    out = {"frames_real": real.assign(sequence=name)}
    means = [_clip_means(real, "real", 0)]
    for r in range(reps):
        mixed = frame_measures(mix_clips(kins, _plan_mix(name, kin, rng)))
        if r == 0:
            out["frames_mix"] = mixed.assign(sequence=name)
        means += [_clip_means(mixed, "mix", r), _clip_means(frame_measures(mix_clips(kins, _plan_team_mix(name, kin, rng))), "team_mix", r)]
        means += [_clip_means(frame_measures(shuffle_within(kin, rng)), "shuffle", r), _clip_means(frame_measures(shift_ids(kin, rng, n_frames, min_shift)), "shift", r)]
    out["clip_means"] = pd.concat(means, ignore_index=True)
    # neighbours: real; headings shuffled (same frames table: each team's set of headings is unchanged); players from
    # different clips; and the weaker within-clip time shift
    mixed_kin, shifted = mix_clips(kins, _plan_mix(name, kin, rng)), shift_ids(kin, rng, n_frames, min_shift)
    variants = {"real": (kin, real), "shuffle": (shuffle_within(kin, rng), real), "mix": (mixed_kin, frame_measures(mixed_kin)), "shift": (shifted, frame_measures(shifted))}
    rank, dist, dens, aniso = [], [], [], []
    for vname, (k, ftab) in variants.items():
        p = _baselined(neighbour_pairs(k), ftab)
        p["dist_bin"] = pd.cut(p["distance"], DIST_EDGES, right=False)
        rank.append(_sums(p, ["relation", "rank"]).assign(variant=vname))
        dist.append(_sums(p, ["relation", "dist_bin"]).assign(variant=vname))
        dens.append(pd.concat([_sums(p, ["relation", "density", "rank"]).assign(kind="rank"), _sums(p, ["relation", "density", "dist_bin"]).assign(kind="distance")], ignore_index=True).assign(variant=vname))
        aniso.append(_anisotropy(p, vname))
    out["neighbours_rank"], out["neighbours_distance"], out["neighbours_density"], out["anisotropy"] = (pd.concat(x, ignore_index=True) for x in (rank, dist, dens, aniso))
    out["neighbours_distance"]["dist_lo"] = out["neighbours_distance"].pop("dist_bin").map(lambda b: b.left).astype(float)
    dd = out["neighbours_density"]
    dd["key"] = np.where(dd["kind"] == "rank", dd["rank"].astype(float), dd["dist_bin"].map(lambda b: b.left if isinstance(b, pd.Interval) else np.nan).astype(float))
    out["neighbours_density"] = dd.drop(columns=["rank", "dist_bin"])
    out.update(_coupling(kin, ball, real, _CLIPS[draw_clips(list(_CLIPS), 1, rng, exclude=[name])[0]][1], n_frames))
    for v in out.values():
        v["sequence"] = name
    return name, out


def _coupling(kin, ball, real, ball_other, n_frames) -> dict:
    """The teams against the ball and against each other. ball_other is another clip's ball, the null for approach."""
    team = {g: real[real["group"] == g].set_index("frame").reindex(np.arange(1, n_frames + 1)) for g in ("0", "1")}
    b = ball.set_index("frame").reindex(np.arange(1, n_frames + 1))
    lags = []
    for axis in ("x", "y"):
        for g in ("0", "1"):
            lags.append(pd.DataFrame({"pair": f"ball->team{g}", "axis": axis, "lag": LAGS, "r": lagged_correlation(b[f"v{axis}"], team[g][f"v{axis}"], LAGS)}))
        lags.append(pd.DataFrame({"pair": "team0->team1", "axis": axis, "lag": LAGS, "r": lagged_correlation(team["0"][f"v{axis}"], team["1"][f"v{axis}"], LAGS)}))
    out = {"lags": pd.concat(lags, ignore_index=True)}
    # do players run toward the ball? the cosine between each moving player's heading and the direction to the ball,
    # against the ball of another clip
    mv = kin[kin["speed"] >= 0.5]
    rows = []
    for vname, bt in (("real", ball), ("other_clip", ball_other)):
        m = mv.merge(bt[["frame", "mx", "my"]].rename(columns={"mx": "bx", "my": "by"}), on="frame")
        dx, dy = m["bx"] - m["mx"], m["by"] - m["my"]
        d = np.hypot(dx, dy)
        cos = (m["vx"] * dx + m["vy"] * dy) / (m["speed"] * d.where(d > 0))
        m = m.assign(approach=cos, ball_dist=d, bin=pd.cut(d, BALL_DIST_EDGES, right=False))
        g = m.groupby(["team", "bin"], observed=True)
        rows.append(pd.DataFrame({"n": g["approach"].count(), "sum_approach": g["approach"].sum()}).reset_index().assign(variant=vname))
    a = pd.concat(rows, ignore_index=True)
    a["bin_lo"] = a.pop("bin").map(lambda x: x.left).astype(float)
    out["approach"] = a
    # each team's polarisation and spread against the ball's speed, and its centroid's distance from the ball
    rows = []
    for g in ("0", "1"):
        t = team[g].join(b[["mx", "my", "speed"]].rename(columns={"mx": "bx", "my": "by", "speed": "ball_speed"}))
        t["ball_dist"] = np.hypot(t["cx"] - t["bx"], t["cy"] - t["by"])
        t["bin"] = pd.cut(t["ball_speed"], BALL_SPEED_EDGES, right=False)
        gg = t.groupby("bin", observed=True)
        rows.append(pd.DataFrame({"frames": gg.size(), "sum_polarisation": gg["polarisation"].sum(), "n_polarisation": gg["polarisation"].count(), "sum_hull_area": gg["hull_area"].sum(), "n_hull_area": gg["hull_area"].count(), "sum_ball_dist": gg["ball_dist"].sum(), "n_ball_dist": gg["ball_dist"].count()}).reset_index().assign(team=g))
    s_ = pd.concat(rows, ignore_index=True)
    s_["speed_lo"] = s_.pop("bin").map(lambda x: x.left).astype(float)
    out["ball_speed"] = s_
    return out


def cmd_run(args) -> None:
    import multiprocessing

    seqs = _sequences()
    with ProcessPoolExecutor(args.jobs) as ex:
        _CLIPS.update(dict(ex.map(_load_task, [(s, args.pitch_dir) for s in seqs])))
    parts: dict[str, list] = {}
    with ProcessPoolExecutor(args.jobs, mp_context=multiprocessing.get_context("fork")) as ex:  # the workers inherit _CLIPS
        for name, out in ex.map(_clip, [(s.name, args.reps, args.seed) for s in seqs]):
            for k, v in out.items():
                parts.setdefault(k, []).append(v)
            print(f"{name}: done", flush=True)
    d = args.out / "run"
    d.mkdir(parents=True, exist_ok=True)
    for k, v in parts.items():
        pd.concat(v, ignore_index=True).to_csv(d / f"{k}.csv", index=False, float_format="%.6g")
    print(f"wrote {', '.join(sorted(parts))} into {d} ({len(seqs)} clips, {args.reps} null repetitions, seed {args.seed})")


# -------------------------------------------------------------------------------------------------------------- summary


def _boot(per_clip: pd.DataFrame, value, n: int = 10000, seed: int = 0):
    """Mean over clips and its 95 % interval, resampling clips: per_clip has one row per clip; value is a column name,
    or a (numerator, denominator) pair of columns whose sums give a ratio."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(per_clip), (n, len(per_clip)))
    if isinstance(value, tuple):
        num, den = per_clip[value[0]].to_numpy(float), per_clip[value[1]].to_numpy(float)
        est, boots = num.sum() / den.sum(), num[idx].sum(1) / den[idx].sum(1)
    else:
        x = per_clip[value].to_numpy(float)
        est, boots = x.mean(), x[idx].mean(1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return est, lo, hi


def _fmt(t, digits=3):
    return f"{t[0]:.{digits}f} [{t[1]:.{digits}f}, {t[2]:.{digits}f}]"


def _random_polarisation(n: int, draws: int = 200000, seed: int = 0) -> float:
    a = np.random.default_rng(seed).uniform(0, 2 * np.pi, (draws, n))
    return float(np.hypot(np.cos(a).mean(1), np.sin(a).mean(1)).mean())


def cmd_summary(args) -> None:
    d = args.out / "run"
    cm = pd.read_csv(d / "clip_means.csv", dtype={"group": str})
    null = cm[cm["variant"] != "real"].groupby(["sequence", "group", "variant"])[MEANS].mean().reset_index()
    real = cm[cm["variant"] == "real"].drop(columns=["variant", "rep"])
    print(f"random headings: polarisation {_random_polarisation(10):.3f} for 10 players, {_random_polarisation(20):.3f} for 20")
    moves = {"mix": None, "shift": None, "team_mix": {"both"}, "shuffle": {"milling", "abs_milling"}}  # where each null can differ from real
    rows = []
    for g in ("0", "1", "both"):
        for measure in ["polarisation", "polarisation_w", "abs_milling", "milling", "radius", "hull_area", "length", "width", "nn_mean", "nn_opponent", "speed_mean"]:
            r = real[real["group"] == g].set_index("sequence")[measure]
            if r.isna().all():
                continue
            row = {"group": g, "measure": measure, "real": _fmt(_boot(r.to_frame("v"), "v"))}
            for variant, where in moves.items():
                if variant == "team_mix" and g not in where or variant == "shuffle" and measure not in where:
                    continue  # identical to real by construction: one team moved whole, or headings dealt within a team
                nv = null[(null["group"] == g) & (null["variant"] == variant)].set_index("sequence")[measure].reindex(r.index)
                row[variant] = _fmt(_boot(nv.to_frame("v"), "v"))
                row[f"real-{variant}"] = _fmt(_boot((r - nv).to_frame("v"), "v"))
                row[f"clips real>{variant}"] = int((r > nv).sum())
            rows.append(row)
    t = pd.DataFrame(rows)
    pd.set_option("display.width", 320, "display.max_colwidth", 40)
    print(f"{real['sequence'].nunique()} clips; mean over clips of each clip's mean over frames [95 % interval, clips resampled]")
    print("null: every player from a different clip (mix); and the weaker within-clip time shift (shift)")
    print(t[["group", "measure", "real", "mix", "real-mix", "clips real>mix", "shift", "real-shift", "clips real>shift"]].to_string(index=False))
    print("null: team 1 whole from another clip (team_mix), for both teams together; headings shuffled within each team (shuffle), for milling")
    print(t[t["group"] == "both"].dropna(subset=["team_mix"])[["group", "measure", "real", "team_mix", "real-team_mix", "clips real>team_mix"]].to_string(index=False))
    print(t.dropna(subset=["shuffle"])[["group", "measure", "real", "shuffle", "real-shuffle", "clips real>shuffle"]].to_string(index=False))
    out = args.out / "summary"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "measures.csv", index=False)
    # pooled frames: quantiles
    fr = pd.read_csv(d / "frames_real.csv", dtype={"group": str})
    fm = pd.read_csv(d / "frames_mix.csv", dtype={"group": str})
    q = [0.1, 0.25, 0.5, 0.75, 0.9]
    for name, f in (("real", fr), ("mix", fm)):
        print(f"{name}: polarisation quantiles {q} by group\n" + f.groupby("group")["polarisation"].quantile(q).unstack().round(3).to_string())
        print(f"{name}: share of team frames with polarisation >= 0.9: " + ", ".join(f"{g} {f.loc[f['group'] == g, 'polarisation'].ge(0.9).mean():.3f}" for g in ("0", "1", "both")))
        print(f"{name}: median hull area, team length, nearest opponent (teams 0 and 1 pooled): " + ", ".join(f"{f.loc[f['group'].isin(['0', '1']), c].median():.1f}" for c in ("hull_area", "length", "nn_opponent")))
    print("frames with at least 5 moving players per team: " + ", ".join(f"{g} {fr.loc[fr['group'] == g, 'n_moving'].ge(5).mean():.3f}" for g in ("0", "1")))
    # spacing for the team's size: the nearest-teammate distance over sqrt(hull area per player), a Clark-Evans-like
    # ratio (larger: more evenly spread). The hull of 10 players biases it, so only real against null is read.

    def spacing(f):
        t = f[f["group"].isin(["0", "1"])]
        return (t["nn_mean"] / np.sqrt(t["hull_area"] / t["n"])).groupby(t["sequence"]).mean()

    sr, sm = spacing(fr), spacing(fm)
    print(f"spacing ratio, nearest teammate / sqrt(hull area per player), teams 0 and 1: real {_fmt(_boot(sr.to_frame('v'), 'v'))}, every player from a different clip {_fmt(_boot(sm.to_frame('v'), 'v'))}, real - null {_fmt(_boot((sr - sm).to_frame('v'), 'v'))}, clips real > null {int((sr > sm).sum())} of {len(sr)}")
    _summary_neighbours(d, out)
    _summary_coupling(d, out)


def _summary_neighbours(d: Path, out: Path) -> None:
    nr = pd.read_csv(d / "neighbours_rank.csv")
    rows = []
    for (rel, k, variant), g in nr.groupby(["relation", "rank", "variant"]):
        if (rel == "teammate" and k > 9) or (rel == "opponent" and k > 6):
            continue
        rows.append({"relation": rel, "rank": k, "variant": variant, "pairs": int(g["n"].sum()), "distance": _boot(g, ("sum_distance", "n"))[0], "align": _fmt(_boot(g, ("sum_align", "n"))), "baseline": _boot(g, ("sum_baseline", "n"))[0], "excess": _fmt(_boot(g, ("sum_excess", "n")))})
    t = pd.DataFrame(rows)
    print("alignment with the k-th nearest teammate / opponent (both moving), and beyond what the frames' team headings alone give:")
    print(t[t["variant"] == "real"].round(3).to_string(index=False))
    print(t[t["variant"] != "real"].pivot_table(index=["relation", "rank"], columns="variant", values="excess", aggfunc="first").to_string())
    t.to_csv(out / "neighbours_rank.csv", index=False)
    nd = pd.read_csv(d / "neighbours_distance.csv")
    rows = []
    for (rel, lo, variant), g in nd.groupby(["relation", "dist_lo", "variant"]):
        if g["n"].sum() < 2000:
            continue
        rows.append({"relation": rel, "dist_lo": lo, "variant": variant, "pairs": int(g["n"].sum()), "excess": _boot(g, ("sum_excess", "n"))[0], "align": _boot(g, ("sum_align", "n"))[0]})
    t = pd.DataFrame(rows)
    print("excess alignment by distance (real):\n" + t[t["variant"] == "real"].pivot_table(index="dist_lo", columns="relation", values="excess").round(3).to_string())
    t.to_csv(out / "neighbours_distance.csv", index=False)
    dn = pd.read_csv(d / "neighbours_density.csv")
    dn = dn[dn["variant"] == "real"]
    rows = []
    for (rel, kind, dens, key), g in dn.groupby(["relation", "kind", "density", "key"]):
        if g["n"].sum() < 2000:
            continue
        rows.append({"relation": rel, "kind": kind, "density": dens, "key": key, "pairs": int(g["n"].sum()), "excess": _boot(g, ("sum_excess", "n"))[0], "distance": _boot(g, ("sum_distance", "n"))[0]})
    t = pd.DataFrame(rows)
    t.to_csv(out / "neighbours_density.csv", index=False)
    for kind in ("rank", "distance"):
        s = t[(t["kind"] == kind) & (t["relation"] == "teammate")]
        print(f"teammates' excess alignment by {kind}, in compact and spread-out frames (the team's mean nearest-teammate distance):\n" + s.pivot_table(index="key", columns="density", values="excess").round(3).to_string())
    print("mean distance of the k-th teammate by density:\n" + t[(t["kind"] == "rank") & (t["relation"] == "teammate")].pivot_table(index="key", columns="density", values="distance").round(1).to_string())
    an = pd.read_csv(d / "anisotropy.csv")
    rows = []
    for variant, g in an.groupby("variant"):
        rows.append({"variant": variant, "pairs": int(g["n"].sum()), "mean |cos| to heading": _fmt(_boot(g, ("sum_abs_bearing", "n"))), "share beside (>45 deg off heading)": _fmt(_boot(g, ("beside", "n"))), "mean |cos| to pitch x": _fmt(_boot(g, ("sum_axis_x", "n"))), "share across the pitch (>45 deg off x)": _fmt(_boot(g, ("across", "n")))})
    t = pd.DataFrame(rows)
    print(f"where the nearest teammate lies (isotropic: mean |cos| {2 / np.pi:.3f}, share beside 0.500):\n" + t.to_string(index=False))
    t.to_csv(out / "anisotropy.csv", index=False)


def _summary_coupling(d: Path, out: Path) -> None:
    lg = pd.read_csv(d / "lags.csv")
    rows = []
    rng = np.random.default_rng(0)
    for (pair, axis), g in lg.groupby(["pair", "axis"]):
        w = g.pivot_table(index="sequence", columns="lag", values="r")
        mean = w.mean()
        peak = mean.idxmax()
        idx = rng.integers(0, len(w), (2000, len(w)))
        boot_peaks = np.array([w.iloc[i].mean().idxmax() for i in idx]) / 29.97
        rows.append({"pair": pair, "axis": axis, "clips": len(w), "r at lag 0": _fmt(_boot(w[0].to_frame("v"), "v"), 2), "peak lag s": f"{peak / 29.97:.2f} [{np.percentile(boot_peaks, 2.5):.2f}, {np.percentile(boot_peaks, 97.5):.2f}]", "r at peak": f"{mean.max():.2f}"})
    t = pd.DataFrame(rows)
    print("velocity coupling: correlation of a(t) with b(t + lag), mean over clips; a positive peak lag means b follows a:\n" + t.to_string(index=False))
    t.to_csv(out / "lags.csv", index=False)
    ap = pd.read_csv(d / "approach.csv")
    rows = []
    for (lo, variant), g in ap.groupby(["bin_lo", "variant"]):
        c = g.groupby("sequence")[["sum_approach", "n"]].sum().reset_index()
        rows.append({"ball_dist_lo": lo, "variant": variant, "player_frames": int(c["n"].sum()), "approach": _fmt(_boot(c, ("sum_approach", "n")))})
    t = pd.DataFrame(rows).pivot_table(index="ball_dist_lo", columns="variant", values=["approach", "player_frames"], aggfunc="first")
    print("cosine between a moving player's heading and the direction to the ball (real ball, and another clip's ball):\n" + t.to_string())
    t.to_csv(out / "approach.csv")
    bs = pd.read_csv(d / "ball_speed.csv", dtype={"team": str})
    rows = []
    for lo, g in bs.groupby("speed_lo"):
        c = g.groupby("sequence")[["sum_polarisation", "n_polarisation", "sum_hull_area", "n_hull_area", "frames", "sum_ball_dist", "n_ball_dist"]].sum().reset_index()
        rows.append({"ball_speed_lo": lo, "team_frames": int(c["frames"].sum()), "polarisation": _fmt(_boot(c, ("sum_polarisation", "n_polarisation"))), "hull_area": _fmt(_boot(c, ("sum_hull_area", "n_hull_area")), 0), "centroid_to_ball_m": _fmt(_boot(c, ("sum_ball_dist", "n_ball_dist")), 1)})
    t = pd.DataFrame(rows)
    print("both teams, by the ball's speed (m/s):\n" + t.to_string(index=False))
    t.to_csv(out / "ball_speed.csv", index=False)


# --------------------------------------------------------------------------------------------------------------- tracks


def _tracks_one(task):
    """The measures from tracks (track --teams output) and from the ground truth, frame by frame, for one clip."""
    from flocker.flocking import players_from_tracks
    from flocker.mot import read_mot

    seq, pitch_dir, tracks_dir = task
    info = seq.seqinfo()
    tr = players_from_tracks(read_mot(tracks_dir / f"{seq.name}.txt"), pd.read_csv(tracks_dir / "teams" / f"{seq.name}.csv"))
    kin_t = kinematics(with_pitch_positions(tr, read_homographies(pitch_dir / f"{seq.name}.csv")), fps=info["framerate"])
    kin_g = _load(seq, pitch_dir)[0]
    ft, fg = frame_measures(kin_t), frame_measures(kin_g)
    means = [_clip_means(ft, "tracks", 0), _clip_means(fg, "gt", 0)]
    teams = ["0", "1"]
    c = ft[ft["group"].isin(teams)].merge(fg[fg["group"].isin(teams)], on=["frame", "group"], suffixes=("_t", "_g"))
    other = fg[fg["group"].isin(teams)].assign(group=lambda d: d["group"].map({"0": "1", "1": "0"}))[["frame", "group", "cx", "cy"]].rename(columns={"cx": "cx_o", "cy": "cy_o"})
    c = c.merge(other, on=["frame", "group"])
    same, opp = np.hypot(c["cx_t"] - c["cx_g"], c["cy_t"] - c["cy_g"]), np.hypot(c["cx_t"] - c["cx_o"], c["cy_t"] - c["cy_o"])
    labels = {"sequence": seq.name, "split": seq.split, "team_frames": len(c), "own_team_centroid_closer": float((same < opp).mean()), "centroid_error_m_median": float(same.median()), "centroid_error_m_p95": float(same.quantile(0.95)), "track_ids": int(kin_t["id"].nunique()), "track_rows_without_velocity": float(kin_t["vx"].isna().mean())}
    frames = ft.merge(fg, on=["frame", "group"], suffixes=("_t", "_g")).assign(sequence=seq.name, split=seq.split)
    return frames, pd.concat(means, ignore_index=True).assign(sequence=seq.name, split=seq.split), labels


def cmd_tracks(args) -> None:
    seqs = [s for s in _sequences(("val", "test"))]
    tasks = [(s, args.pitch_dir, args.tracks / s.split / args.run_name) for s in seqs]
    with ProcessPoolExecutor(args.jobs) as ex:
        res = list(ex.map(_tracks_one, tasks))
    frames = pd.concat([r[0] for r in res], ignore_index=True)
    means = pd.concat([r[1] for r in res], ignore_index=True)
    labels = pd.DataFrame([r[2] for r in res])
    out = args.out / "tracks"
    out.mkdir(parents=True, exist_ok=True)
    frames.to_csv(out / "frames.csv", index=False, float_format="%.6g")
    means.to_csv(out / "clip_means.csv", index=False, float_format="%.6g")
    labels.to_csv(out / "labels.csv", index=False, float_format="%.4f")
    pd.set_option("display.width", 320)
    print("team labels: is each track team's centroid nearer the same ground-truth team's than the other's?\n" + labels.groupby("split")[["team_frames", "own_team_centroid_closer", "centroid_error_m_median", "centroid_error_m_p95", "track_ids", "track_rows_without_velocity"]].agg({"team_frames": "sum", "own_team_centroid_closer": "min", "centroid_error_m_median": "median", "centroid_error_m_p95": "max", "track_ids": "median", "track_rows_without_velocity": "max"}).round(4).to_string())
    frames["abs_milling_t"], frames["abs_milling_g"] = frames["milling_t"].abs(), frames["milling_g"].abs()
    rows = []
    for (split, g), f in frames.groupby(["split", "group"]):
        for m in ["n", "polarisation", "polarisation_w", "abs_milling", "radius", "hull_area", "length", "width", "nn_mean", "nn_opponent", "speed_mean"]:
            a, b = f[f"{m}_t"], f[f"{m}_g"]
            ok = a.notna() & b.notna()
            if ok.sum() < 10:
                continue
            rows.append({"split": split, "group": g, "measure": m, "frames": int(ok.sum()), "gt_median": b[ok].median(), "tracks_median": a[ok].median(), "median_abs_diff": (a - b)[ok].abs().median(), "p90_abs_diff": (a - b)[ok].abs().quantile(0.9), "mean_diff": (a - b)[ok].mean(), "pearson_r": np.corrcoef(a[ok], b[ok])[0, 1] if a[ok].std() > 0 and b[ok].std() > 0 else np.nan})
    t = pd.DataFrame(rows)
    t.to_csv(out / "agreement.csv", index=False, float_format="%.4f")
    print("frame by frame, tracks against ground truth:\n" + t.round(3).to_string(index=False))
    # the null is the ground truth's (every player from a different clip, from run's output): it does not depend on the tracker
    cm = pd.read_csv(args.out / "run" / "clip_means.csv", dtype={"group": str})
    null = cm[cm["variant"] == "mix"].groupby(["sequence", "group"])[["polarisation", "hull_area"]].mean()
    m = means.groupby(["split", "sequence", "group", "variant"])[MEANS].mean().reset_index()
    rows = []
    for (split, g), f in m.groupby(["split", "group"]):
        w = f.pivot_table(index="sequence", columns="variant", values="polarisation")
        h = f.pivot_table(index="sequence", columns="variant", values="hull_area")
        nz = null.xs(g, level="group").reindex(w.index)
        row = {"split": split, "group": g, "clips": len(w), "polarisation gt": w["gt"].mean(), "tracks": w["tracks"].mean(), "null": nz["polarisation"].mean()}
        row.update({"excess gt": (w["gt"] - nz["polarisation"]).mean(), "excess tracks": (w["tracks"] - nz["polarisation"]).mean(), "clips tracks>null": int((w["tracks"] > nz["polarisation"]).sum())})
        rows.append({**row, "hull gt": h["gt"].mean(), "hull tracks": h["tracks"].mean(), "hull null": nz["hull_area"].mean()})
    t = pd.DataFrame(rows)
    t.to_csv(out / "excess.csv", index=False, float_format="%.4f")
    print("per clip, real against the null (every player from a different clip, ground truth), from tracks and from the ground truth:\n" + t.round(3).to_string(index=False))


# ---------------------------------------------------------------------------------------------------------------- xcorr


def _units_task(task):
    """Each outfield player's unit heading in every frame (NaN when slower than 0.5 m/s or unknown), and their team."""
    seq, pitch_dir = task
    kin, _, _, n_frames = _load(seq, pitch_dir)
    sp = kin["speed"].to_numpy()
    mv = np.nan_to_num(sp) >= 0.5
    kin = kin.assign(ux=np.where(mv, kin["vx"] / np.where(mv, sp, 1), np.nan), uy=np.where(mv, kin["vy"] / np.where(mv, sp, 1), np.nan))
    units = {int(i): g.set_index("frame")[["ux", "uy"]].reindex(np.arange(1, n_frames + 1)).to_numpy() for i, g in kin.groupby("id")}
    return seq.name, (units, kin.groupby("id")["team"].first().astype(int).to_dict())


def cmd_xcorr(args) -> None:
    """How long teammates' headings stay correlated, which decides how a null must break their synchrony: the mean of
    u_a(t) . u_b(t + D) over ordered pairs of teammates, against the offset D (circular within a clip); the same with b
    taken from the next clip (no shared moment); and what the within-clip time shift's independent offsets leave."""
    seqs = _sequences()
    with ProcessPoolExecutor(args.jobs) as ex:
        units = dict(ex.map(_units_task, [(s, args.pitch_dir) for s in seqs]))
    offsets = np.arange(0, 451, 15)
    acc, cnt = np.zeros(len(offsets)), np.zeros(len(offsets))
    for u, team in units.values():
        for t in (0, 1):
            ids = [i for i in u if team[i] == t]
            for a in ids:
                for b in ids:
                    if a == b:
                        continue
                    for k, off in enumerate(offsets):
                        v = (u[a] * np.roll(u[b], -off, axis=0)).sum(axis=1)
                        ok = np.isfinite(v)
                        acc[k] += v[ok].sum()
                        cnt[k] += ok.sum()
    names = list(units)
    cross_sum, cross_n = 0.0, 0
    for c1, c2 in zip(names, names[1:] + names[:1]):
        (u1, team1), (u2, _) = units[c1], units[c2]
        for t in (0, 1):
            ids = [i for i in u1 if team1[i] == t and i in u2]
            for a in ids:
                for b in ids:
                    if a != b:
                        v = (u1[a] * u2[b]).sum(axis=1)
                        cross_sum, cross_n = cross_sum + np.nansum(v), cross_n + int(np.isfinite(v).sum())
    curve = acc / cnt
    rng = np.random.default_rng(0)
    s1, s2 = rng.integers(150, 751, (2, 400000))  # the within-clip shift: independent offsets of 5-25 s in 900 frames
    rel = np.abs(s1 - s2) % 900
    rel = np.minimum(rel, 900 - rel)
    out = args.out / "xcorr"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"offset_s": offsets / 29.97, "alignment": curve, "pairs": cnt}).to_csv(out / "teammates.csv", index=False, float_format="%.4f")
    print("teammates' heading alignment u_a(t) . u_b(t + D), all 54 clips:\n" + "\n".join(f"  D = {o / 29.97:4.1f} s: {c:+.3f}" for o, c in zip(offsets, curve) if o % 75 == 0))
    print(f"teammates from different clips: {cross_sum / cross_n:+.3f} ({cross_n} pair-frames)")
    print(f"within-clip shift: {np.mean(rel < 150):.1%} of pairs end up under 5 s apart and {np.mean(rel < 30):.1%} under 1 s; expected pair alignment {np.interp(rel, offsets, curve).mean():+.3f}")


# ---------------------------------------------------------------------------------------------------------------- plots

INK, INK2, GRID, NULL_GREY = "#191919", "#666666", "#e4e4e4", "#9a9a9a"
SERIES = ("#257de0", "#f47230", "#00b894")  # the reference palette's first three slots: blue, orange, aqua


def _axes_style(ax) -> None:
    ax.grid(color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK2)
    ax.tick_params(colors=INK2, labelcolor=INK2)
    ax.xaxis.label.set_color(INK)
    ax.yaxis.label.set_color(INK)
    ax.title.set_color(INK)


def cmd_plots(args) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    d, out = args.out / "run", args.out / "plots"
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.titlesize": 10, "legend.frameon": False, "legend.fontsize": 9, "lines.linewidth": 1.6})
    fr = pd.read_csv(d / "frames_real.csv", dtype={"group": str})
    fs = pd.read_csv(d / "frames_mix.csv", dtype={"group": str})
    teams = ["0", "1"]
    # 1. real against the time-shift null, team frames of both teams pooled
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    panels = [("polarisation", "polarisation of a team's moving players", np.linspace(0, 1, 51)), ("hull_area", "convex-hull area of a team, m²", np.linspace(0, 3500, 71)), ("length", "team length along the pitch (goal to goal), m", np.linspace(0, 100, 81)), ("nn_opponent", "mean distance to the nearest opponent, m", np.linspace(0, 20, 61))]
    for ax, (col, label, bins) in zip(axes.ravel(), panels):
        for frame, colour, name in ((fs, NULL_GREY, "players from different clips (null)"), (fr, SERIES[0], "real")):
            v = frame.loc[frame["group"].isin(teams), col].dropna()
            ax.hist(v, bins=bins, density=True, histtype="step", color=colour, lw=1.8, label=f"{name}: median {v.median():.2f}" if col == "polarisation" else f"{name}: median {v.median():.0f}" if col == "hull_area" else f"{name}: median {v.median():.1f}")
        if col == "polarisation":
            r10 = _random_polarisation(10)
            ax.axvline(r10, color=INK2, lw=1, ls=":", label=f"random headings, 10 players: mean {r10:.2f}")
        ax.set_ylim(0, ax.get_ylim()[1] * 1.4)  # headroom for the legend above the data
        ax.set_xlabel(label)
        ax.set_ylabel("share of team frames (density)")
        ax.legend(loc="upper left" if col == "polarisation" else "upper right")
        _axes_style(ax)
    fig.suptitle("Real teams against the same players, each taken from a different clip (null): 54 clips, both teams, ground truth", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "real_vs_null.png", dpi=110)
    plt.close(fig)
    # 2. neighbours: excess alignment by rank and by distance, with 95 % intervals over clips
    nr = pd.read_csv(d / "neighbours_rank.csv")
    nd = pd.read_csv(d / "neighbours_distance.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for (rel, kmax), colour in zip((("teammate", 9), ("opponent", 6)), SERIES):
        nulls = (("shuffle", "--", "headings shuffled within the team"), ("mix", ":", "players from different clips")) if rel == "teammate" else ()
        for variant, ls, what in (("real", "-", ""), *nulls):
            pts = [(k, *_boot(g, ("sum_excess", "n"))) for k, g in nr[(nr["relation"] == rel) & (nr["variant"] == variant)].groupby("rank") if k <= kmax]
            k, est, lo, hi = (np.array(x) for x in zip(*pts))
            axes[0].errorbar(k + (0.08 if rel == "opponent" else 0), est, yerr=[est - lo, hi - est], color=colour if variant == "real" else NULL_GREY, ls=ls, marker="o", ms=4, capsize=2, lw=1.4, label=f"{rel}s" + (f" ({what}: null)" if what else ""))
        for variant, ls, col in (("real", "-", colour),):
            g = nd[(nd["relation"] == rel) & (nd["variant"] == variant)]
            pts = [(lo_ + 1, _boot(x, ("sum_excess", "n"))[0], x["n"].sum()) for lo_, x in g.groupby("dist_lo") if x["n"].sum() >= 2000 and lo_ < 40]
            dx, est, _ = (np.array(x) for x in zip(*pts))
            axes[1].plot(dx, est, color=col, ls=ls, marker="o", ms=3.5, label=f"{rel}s")
    axes[0].axhline(0, color=INK2, lw=0.8)
    axes[1].axhline(0, color=INK2, lw=0.8)
    axes[0].set_xlabel("neighbour rank (1 = nearest)")
    axes[1].set_xlabel("distance to the neighbour, m (2 m bins)")
    for ax in axes:
        ax.set_ylabel("alignment beyond the frame's team headings")
        ax.legend()
        _axes_style(ax)
    fig.suptitle("Do neighbours run more alike than any two players of the same frames? (cosine of the headings, minus its expectation)", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "neighbours.png", dpi=110)
    plt.close(fig)
    # 3. couplings against lag
    lg = pd.read_csv(d / "lags.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, axis in zip(axes, ("x", "y")):
        for (pair, name), colour in zip((("ball->team0", "ball, then team 0"), ("ball->team1", "ball, then team 1"), ("team0->team1", "team 0, then team 1")), SERIES):
            w = lg[(lg["pair"] == pair) & (lg["axis"] == axis)].pivot_table(index="sequence", columns="lag", values="r")
            m = w.mean()
            ax.plot(m.index / 29.97, m.to_numpy(), color=colour, label=name)
            peak = m.idxmax()
            ax.plot([peak / 29.97], [m.max()], "o", color=colour, ms=5)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_xlabel("lag, s (positive: the second follows the first)")
        ax.set_title(f"velocity along {'x (goal to goal)' if axis == 'x' else 'y (touchline to touchline)'}")
        ax.legend(loc="upper right")
        _axes_style(ax)
    axes[0].set_ylabel("correlation, mean over 54 clips")
    fig.suptitle("Who follows whom: the correlation of the ball's velocity and each team's mean velocity, at a lag", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "lags.png", dpi=110)
    plt.close(fig)
    # 4. one clip, frame by frame
    seq = args.sequence
    f = fr[fr["sequence"] == seq]
    from flocker.teamtrack import find_sequence

    _, ball, fps, _ = _load(find_sequence(seq), args.pitch_dir) if args.pitch_dir else (None, None, 29.97, None)
    fig, axes = plt.subplots(3 if ball is not None else 2, 1, figsize=(11, 7.5), sharex=True)
    for g, colour in zip(teams, SERIES):
        t = f[f["group"] == g]
        axes[0].plot((t["frame"] - 1) / fps, t["polarisation"], color=colour, lw=1.2, label=f"team {g}")
        axes[1].plot((t["frame"] - 1) / fps, t["hull_area"], color=colour, lw=1.2, label=f"team {g}")
    axes[0].set_ylabel("polarisation")
    axes[1].set_ylabel("hull area, m²")
    if ball is not None:
        axes[2].plot((ball["frame"] - 1) / fps, ball["speed"], color=SERIES[2], lw=1.2, label="ball")
        axes[2].set_ylabel("ball speed, m/s")
    axes[-1].set_xlabel(f"time in {seq}, s")
    for ax, loc in zip(axes, ("lower left", "upper left", "upper right")):
        ax.legend(loc=loc, ncol=2)
        _axes_style(ax)
    fig.suptitle(f"{seq}: the two teams' polarisation and spread, and the ball's speed (ground truth)", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out / f"timeline_{seq}.png", dpi=110)
    plt.close(fig)
    print(f"wrote {', '.join(sorted(p.name for p in out.glob('*.png')))} into {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Studies behind notes/FLOCKER_2026-11-25_FLOCKING-ANALYSIS.md.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("audit", help="the ground truth's glitches, gaps and goalkeepers, all 60 clips")
    p.add_argument("--pitch-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--jobs", type=int, default=8)
    p.set_defaults(func=cmd_audit)
    p = sub.add_parser("run", help="measures, nulls, neighbours and couplings for the 54 clips used")
    p.add_argument("--pitch-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--reps", type=int, default=10, help="repetitions of each null per clip (default: %(default)s)")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--jobs", type=int, default=12)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("summary", help="tables with 95 %% intervals from run's output")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_summary)
    p = sub.add_parser("tracks", help="the measures from tracks against the ground truth, val and test")
    p.add_argument("--pitch-dir", type=Path, required=True)
    p.add_argument("--tracks", type=Path, required=True, help="a folder holding <split>/<run-name>/ (track --teams output)")
    p.add_argument("--run-name", default="flocker_teams")
    p.add_argument("--out", type=Path, required=True, help="the study folder; run's output must be in it (the null)")
    p.add_argument("--jobs", type=int, default=9)
    p.set_defaults(func=cmd_tracks)
    p = sub.add_parser("xcorr", help="how long teammates' headings stay correlated, and what each null leaves of it")
    p.add_argument("--pitch-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--jobs", type=int, default=8)
    p.set_defaults(func=cmd_xcorr)
    p = sub.add_parser("plots", help="figures from run's output")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--pitch-dir", type=Path, default=None, help="for the ball in the timeline")
    p.add_argument("--sequence", default="D_20220220_1_1530_1560", help="the clip for the timeline (default: %(default)s)")
    p.set_defaults(func=cmd_plots)
    args = ap.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
