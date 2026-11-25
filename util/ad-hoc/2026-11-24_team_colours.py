#!/usr/bin/env python3
"""Measure kit colours of cached TeamTrack detections, and study how well they separate the teams.

Project: Flocker
File: util/ad-hoc/2026-11-24_team_colours.py
Purpose: the 2026-11-24 identity work arc's team-colour study (notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md)
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

    extract  colours/<sequence>.csv beside a detections/ folder: L, a, b, n_fg for every row of the detection
             file, in the same order (flocker.team.detection_colours); one process per sequence
    study    match the player detections to the ground truth (centres within 15 px) and print each ground-truth
             player's median colour, with its team, so the colour clusters can be seen

    conda run -n Flocker python util/ad-hoc/2026-11-24_team_colours.py extract --det-dir DIR --split val
    conda run -n Flocker python util/ad-hoc/2026-11-24_team_colours.py study --det-dir DIR --split val
"""

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from flocker.evaluate import match_centres  # noqa: E402
from flocker.mot import BALL, read_mot  # noqa: E402
from flocker.teamtrack import list_sequences, load_gt  # noqa: E402


def _extract(task):
    from flocker.team import detection_colours

    seq, det_dir = task
    t = time.perf_counter()
    dets = read_mot(det_dir / "detections" / f"{seq.name}.txt")
    out = det_dir / "colours" / f"{seq.name}.csv"
    detection_colours(seq.video_path, dets).to_csv(out, index=False, float_format="%.2f")
    return seq.name, len(dets), time.perf_counter() - t


def load(det_dir: Path, seq, conf: float = 0.3) -> pd.DataFrame:
    """Player detections of one sequence with their colours and matched ground-truth id and team."""
    dets = read_mot(det_dir / "detections" / f"{seq.name}.txt")
    col = pd.read_csv(det_dir / "colours" / f"{seq.name}.csv")
    dets = pd.concat([dets, col], axis=1)
    dets = dets[(dets["cls"] != BALL) & (dets["conf"] >= conf)]
    gt = load_gt(seq, objects="players")
    dets["gt_id"] = match_centres(gt, dets)
    dets["gt_team"] = np.where(dets["gt_id"] < 0, -2, np.where(dets["gt_id"] < 11, 0, 1))
    return dets


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["extract", "study"])
    ap.add_argument("--det-dir", type=Path, required=True)
    ap.add_argument("--split", default="val")
    ap.add_argument("--jobs", type=int, default=9)
    args = ap.parse_args()
    seqs = list_sequences(None, args.split)
    if args.action == "extract":
        (args.det_dir / "colours").mkdir(exist_ok=True)
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            for name, n, s in ex.map(_extract, [(s, args.det_dir) for s in seqs]):
                print(f"{name}: {n} detections, {s:.0f} s", flush=True)
        return 0
    from flocker.team import OTHER, fit_teams

    tally = []
    for s in seqs:
        d = load(args.det_dir, s, conf=0.1)
        model = fit_teams(d.loc[d["conf"] >= 0.3, ["L", "a", "b"]].to_numpy())
        d["team"] = model.predict(d[["L", "a", "b"]].to_numpy())
        m = d[d["gt_id"] >= 0]
        med = m.groupby("gt_id")[["L", "a", "b"]].median()
        player_label = pd.Series(model.predict(med.to_numpy()), index=med.index)  # a player's label from its median colour
        keepers = player_label[player_label == OTHER].index.tolist()
        flip = 0 if (m.loc[m["team"] == 0, "gt_team"] == 0).mean() >= 0.5 else 1  # model team -> ground-truth team
        m = m.assign(pred=np.where(m["team"] == OTHER, OTHER, m["team"] ^ flip))
        out = m[~m["gt_id"].isin(keepers)]
        tally.append(out.assign(seq=s.name[-9:]))
        print(f"{s.name}: means {np.round(model.means, 0).astype(int).tolist()}; players labelled OTHER by median colour: {keepers} "
              f"(ground-truth team {[0 if k < 11 else 1 for k in keepers]}); outfield detections: right {np.mean(out['pred'] == out['gt_team']):.4f}, "
              f"wrong team {np.mean((out['pred'] != out['gt_team']) & (out['pred'] != OTHER)):.4f}, OTHER {np.mean(out['pred'] == OTHER):.4f}; "
              f"unmatched detections labelled a team: {np.mean(d.loc[d['gt_id'] < 0, 'team'] != OTHER):.3f}", flush=True)
    t = pd.concat(tally)
    wrong = (t["pred"] != t["gt_team"]) & (t["pred"] != OTHER)
    print(f"ALL outfield detections (conf >= 0.1, matched): n={len(t)} right {np.mean(t['pred'] == t['gt_team']):.4f} wrong {wrong.mean():.4f} OTHER {np.mean(t['pred'] == OTHER):.4f}")
    by_conf = t.assign(cbin=pd.cut(t["conf"], [0.1, 0.2, 0.3, 0.5, 1.0])).groupby("cbin", observed=True)
    print("by confidence: wrong-team rate", by_conf.apply(lambda g: round(float(((g["pred"] != g["gt_team"]) & (g["pred"] != OTHER)).mean()), 4), include_groups=False).to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
