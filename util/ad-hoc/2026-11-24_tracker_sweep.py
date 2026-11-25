#!/usr/bin/env python3
"""Sweep tracker settings on cached TeamTrack detections, scoring each configuration for player identity.

Project: Flocker
File: util/ad-hoc/2026-11-24_tracker_sweep.py
Purpose: the 2026-11-24 identity work arc's tracker sweep (notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md)
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

Each configuration is a tracker name, Ultralytics tracker overrides, and optional Flocker-side steps (a second,
stricter NMS on the cached detections). Players only: the ball is tracked separately and scored apart. Every
configuration is scored with CLEAR-MOT and IDF1 twice, matching centres within 15 px and IoU >= 0.5; --hota adds
HOTA (IoU, about a minute per configuration) and --breakdown classifies every switch (flocker.evaluate.switch_events).

The stages below are the record of what was run, in order; later stages start from the best settings found by the
earlier ones on the val split. Run a stage with:

    conda run -n Flocker python util/ad-hoc/2026-11-24_tracker_sweep.py --det-dir DIR --split val --stage NAME --out CSV

DIR holds detections/<sequence>.txt as written by `bin/flocker.py track`. Results append to CSV (one row per
configuration), so stages accumulate in one table.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from flocker.evaluate import evaluate, match_centres, switch_events  # noqa: E402
from flocker.mot import BALL, read_mot  # noqa: E402
from flocker.team import OTHER, fit_teams  # noqa: E402
from flocker.teamtrack import list_sequences, load_gt  # noqa: E402
from flocker.track import suppress_duplicates, track_detections  # noqa: E402


def cfg(name, tracker="bytetrack", dedup_iou=None, teams=None, team_min_conf=None, **overrides):
    """teams: None (no colours), "label" (team labels on tracks only) or "gate" (also gate association by team).
    team_min_conf: detections below this confidence get no team (neither gate nor vote)."""
    return {"name": name, "tracker": tracker, "dedup_iou": dedup_iou, "teams": teams, "team_min_conf": team_min_conf, "set": overrides}


STAGES = {
    # Stage 0: Ultralytics' defaults, and each of the two causes the diagnosis found, alone and together.
    "baseline": [
        cfg("bytetrack default"),
        cfg("bytetrack fuse_score off", fuse_score=False),
        cfg("bytetrack dedup 0.45", dedup_iou=0.45),
        cfg("bytetrack dedup 0.45 + fuse off", dedup_iou=0.45, fuse_score=False),
    ],
    # Stage 1 (after baseline: only both changes together help): the second NMS's threshold, score fusion off.
    "dedup": [cfg(f"bytetrack dedup {t} + fuse off", dedup_iou=t, fuse_score=False) for t in (0.3, 0.35, 0.4, 0.5, 0.55)],
    # Stage 2 (after dedup: stricter is better down to 0.3): two stricter points, then each tracker threshold in turn
    # around dedup 0.3 + fuse off (Ultralytics' defaults: high 0.25, low 0.1, new 0.25, match 0.8, buffer 30).
    "thresholds": [cfg(f"bytetrack dedup {t} + fuse off", dedup_iou=t, fuse_score=False) for t in (0.2, 0.25)]
    + [cfg(f"d0.3 nf {k}={v}", dedup_iou=0.3, fuse_score=False, **{k: v}) for k, vals in {"new_track_thresh": (0.15, 0.35, 0.45), "track_high_thresh": (0.15, 0.35), "track_low_thresh": (0.05,), "match_thresh": (0.7, 0.9), "track_buffer": (60, 150, 900)}.items() for v in vals],
    # Stage 3 (after thresholds: high 0.15 and match 0.9 help, buffer does nothing): the helpful changes combined, and
    # every Ultralytics tracker with dedup 0.3 + fuse off, at its own defaults and with high 0.15 + match 0.9.
    # TrackTrack has its own cost and thresholds (high 0.6, new 0.7, match 0.7), so only its defaults are tried.
    "trackers": [
        cfg("bytetrack d0.3 nf high0.15 match0.9", dedup_iou=0.3, fuse_score=False, track_high_thresh=0.15, match_thresh=0.9),
        cfg("bytetrack d0.3 nf high0.15 match0.9 new0.35", dedup_iou=0.3, fuse_score=False, track_high_thresh=0.15, match_thresh=0.9, new_track_thresh=0.35),
        cfg("bytetrack d0.25 nf high0.15 match0.9", dedup_iou=0.25, fuse_score=False, track_high_thresh=0.15, match_thresh=0.9),
    ]
    + [c for t in ("botsort", "ocsort", "deepocsort", "fasttrack") for c in (cfg(f"{t} d0.3 nf", t, dedup_iou=0.3, fuse_score=False), cfg(f"{t} d0.3 nf high0.15 match0.9", t, dedup_iou=0.3, fuse_score=False, track_high_thresh=0.15, match_thresh=0.9))]
    + [cfg("tracktrack d0.3", "tracktrack", dedup_iou=0.3)],
    # Stage 3b (TrackTrack at its defaults keeps almost nothing: few true players score above its 0.6 / 0.7): its
    # thresholds scaled to this detector's confidences, as found for ByteTrack.
    # Stage 4: HOTA (--hota) for the default and the best configurations of stages 2-3.
    "shortlist": [
        cfg("bytetrack default"),
        cfg("bytetrack d0.3 nf high0.15 match0.9", dedup_iou=0.3, fuse_score=False, track_high_thresh=0.15, match_thresh=0.9),
        cfg("bytetrack d0.3 nf high0.15 match0.9 new0.35", dedup_iou=0.3, fuse_score=False, track_high_thresh=0.15, match_thresh=0.9, new_track_thresh=0.35),
        cfg("botsort d0.3 nf high0.15 match0.9", "botsort", dedup_iou=0.3, fuse_score=False, track_high_thresh=0.15, match_thresh=0.9),
    ],
    # Stage 5: team colours (flocker.team) on the best configuration: labels only, and gating association by team.
    "teams": [
        cfg("best + team labels", dedup_iou=0.3, teams="label", fuse_score=False, track_high_thresh=0.15, match_thresh=0.9),
        cfg("best + team gate", dedup_iou=0.3, teams="gate", fuse_score=False, track_high_thresh=0.15, match_thresh=0.9),
        cfg("best new0.35 + team gate", dedup_iou=0.3, teams="gate", fuse_score=False, track_high_thresh=0.15, match_thresh=0.9, new_track_thresh=0.35),
    ],
    # Stage 5b (after teams: gating on every label hurts; labels below conf 0.3 are wrong 1-4 % of the time): gate and
    # vote only with detections of confidence >= 0.3, whose labels are wrong 0.26 % of the time or less.
    "teams_confident": [cfg("best + team gate conf>=0.3", dedup_iou=0.3, teams="gate", team_min_conf=0.3, fuse_score=False, track_high_thresh=0.15, match_thresh=0.9)],
    # Stage 6, on the TEST split, once, after every choice was made on val: Ultralytics' default (the 2026-11-24 harness
    # note's row), the chosen settings (config/trackers/flocker_bytetrack.yaml with dedup 0.3), and the same with team
    # labels. Run with --split test --hota --breakdown.
    "final": [
        cfg("bytetrack default"),
        cfg("flocker (dedup 0.3)", "flocker", dedup_iou=0.3),
        cfg("flocker (dedup 0.3) + team labels", "flocker", dedup_iou=0.3, teams="label"),
    ],
    "tracktrack": [cfg("tracktrack d0.3 high0.15 low0.1 new0.25", "tracktrack", dedup_iou=0.3, track_high_thresh=0.15, track_low_thresh=0.1, new_track_thresh=0.25), cfg("tracktrack d0.3 high0.3 low0.1 new0.35", "tracktrack", dedup_iou=0.3, track_high_thresh=0.3, track_low_thresh=0.1, new_track_thresh=0.35)],
}


def _track_one(task):
    name, dets, n_frames, c = task
    if c["teams"] is None:
        dets = dets.drop(columns=["team"], errors="ignore")
    elif c["team_min_conf"] is not None:
        dets = dets.assign(team=dets["team"].where(dets["conf"] >= c["team_min_conf"], OTHER))
    if c["dedup_iou"] is not None:
        dets = suppress_duplicates(dets, c["dedup_iou"])
    t = track_detections(dets, tracker=c["tracker"], n_frames=n_frames, team_gate=c["teams"] == "gate", **c["set"])
    return name, t


def score(c, seqs, dets, gts, n_frames, hota, breakdown, jobs, pool, keepers):
    t0 = time.perf_counter()
    tracks = dict(pool.map(_track_one, [(s, dets[s], n_frames[s], c) for s in seqs]))
    t_track = time.perf_counter() - t0
    c15 = evaluate(gts, tracks, max_center_dist=15, n_jobs=jobs).loc["OVERALL"]
    iou = evaluate(gts, tracks, hota=hota, n_jobs=jobs).loc["OVERALL"]
    row = {"config": c["name"], "tracker": c["tracker"], "dedup_iou": c["dedup_iou"], "set": json.dumps(c["set"], sort_keys=True)}
    for k in ("IDF1", "MOTA", "IDSW", "IDs", "Frag", "Rcll", "Prcn", "FP", "FN", "MOTP"):
        row[f"c15_{k}"] = c15[k]
    for k in ("IDF1", "MOTA", "IDSW", "Rcll", "Prcn") + (("HOTA", "DetA", "AssA") if hota else ()):
        row[f"iou_{k}"] = iou[k]
    if c["teams"] is not None:  # track-team accuracy over track rows matched to a player (centres within 15 px)
        right = wrong = unknown = keeper_rows = 0
        for s in seqs:
            gid = match_centres(gts[s], tracks[s])
            m = tracks[s][gid >= 0].assign(gt_id=gid[gid >= 0])
            keeper = m["gt_id"].isin(keepers[s])
            keeper_rows += int(keeper.sum())
            m = m[~keeper]
            truth = np.where(m["gt_id"] < 11, 0, 1)
            right += int((m["team"] == truth).sum())
            wrong += int(((m["team"] != truth) & (m["team"] >= 0)).sum())
            unknown += int((m["team"] < 0).sum())
        n = max(1, right + wrong + unknown)
        row.update({"team_right": right / n, "team_wrong": wrong / n, "team_unknown": unknown / n, "keeper_rows": keeper_rows})
    if breakdown:
        ev = pd.concat([switch_events(gts[s], tracks[s], max_center_dist=15) for s in seqs])
        for k in ("restart", "swap", "other"):
            row[f"c15_sw_{k}"] = int((ev["kind"] == k).sum())
    row["track_s"] = round(t_track, 1)
    return row


def summary(r: dict) -> str:
    """One line per configuration: centre-15 px identity and accuracy, then IoU scores."""
    out = f"{r['config']:40s} IDF1 {100 * r['c15_IDF1']:.1f} MOTA {100 * r['c15_MOTA']:.1f} IDSW {int(r['c15_IDSW']):4d} IDs {int(r['c15_IDs']):4d} FP {int(r['c15_FP']):5d} FN {int(r['c15_FN']):5d} | IoU IDF1 {100 * r['iou_IDF1']:.1f} MOTA {100 * r['iou_MOTA']:.1f}"
    if "iou_HOTA" in r:
        out += f" HOTA {100 * r['iou_HOTA']:.1f} AssA {100 * r['iou_AssA']:.1f}"
    if "team_right" in r:
        out += f" | team right/wrong/unknown {100 * r['team_right']:.2f}/{100 * r['team_wrong']:.2f}/{100 * r['team_unknown']:.2f}"
    if "c15_sw_restart" in r:
        out += f" | switches restart/swap/other {r['c15_sw_restart']}/{r['c15_sw_swap']}/{r['c15_sw_other']}"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--det-dir", type=Path, required=True, help="folder holding detections/<sequence>.txt")
    ap.add_argument("--split", default="val")
    ap.add_argument("--stage", required=True, choices=sorted(STAGES))
    ap.add_argument("--only", nargs="+", default=None, help="only the configurations with these names")
    ap.add_argument("--out", type=Path, required=True, help="CSV to append results to")
    ap.add_argument("--hota", action="store_true")
    ap.add_argument("--breakdown", action="store_true")
    ap.add_argument("--jobs", type=int, default=9)
    args = ap.parse_args()

    seqs = list_sequences(None, args.split)
    names = [s.name for s in seqs]
    gts = {s.name: load_gt(s, objects="players") for s in seqs}
    n_frames = {s.name: s.seqinfo()["seqlength"] for s in seqs}
    dets, keepers = {}, {}
    colours = args.det_dir / "colours"
    for n in names:
        d = read_mot(args.det_dir / "detections" / f"{n}.txt")
        if (colours / f"{n}.csv").is_file():  # kit colours, row-aligned with the detection file (2026-11-24_team_colours.py)
            d = pd.concat([d, pd.read_csv(colours / f"{n}.csv")], axis=1)
        d = d[d["cls"] != BALL].reset_index(drop=True)
        if "L" in d.columns:
            lab = d[["L", "a", "b"]].to_numpy()
            model = fit_teams(lab[d["conf"].to_numpy() >= 0.3])
            d["team"] = model.predict(lab)
            med = d.assign(gt_id=match_centres(gts[n], d)).query("gt_id >= 0").groupby("gt_id")[["L", "a", "b"]].median()
            keepers[n] = med.index[model.predict(med.to_numpy()) == OTHER].tolist()  # players whose kit is neither team's
            d = d.drop(columns=["L", "a", "b", "n_fg"])
        dets[n] = d
    configs = [c for c in STAGES[args.stage] if args.only is None or c["name"] in args.only]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for c in configs:
            row = score(c, names, dets, gts, n_frames, args.hota, args.breakdown, args.jobs, pool, keepers)
            row.update({"stage": args.stage, "split": args.split})
            pd.DataFrame([row]).to_csv(args.out, mode="a", header=not args.out.is_file(), index=False, float_format="%.4f")
            print(summary(row), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
