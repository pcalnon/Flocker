"""Mutation check for the flocking analysis: break one thing at a time and confirm a unit test fails.

Project: Flocker
File: util/ad-hoc/2026-11-25_flocking_mutations.py
Purpose: each mutation is applied to a copy of src/ and tests/ under --work, never to the checkout, and the unit tests of
    tests/test_flocking.py run against the copy; every mutation must make at least one test fail
Author: Paul Calnon
Created: 2026-11-25
License: CC0 1.0 (see LICENSE)

Ran on 2026-11-25 from the worktree, with the Flocker environment:

    /opt/miniforge3/envs/Flocker/bin/python -I util/ad-hoc/2026-11-25_flocking_mutations.py \\
        --work ~/Development/python/Flocker/tmp/2026-11-25_flocking/mutations
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (name, file under src/flocker, old text, new text)
MUTATIONS = [
    ("velocity per frame, not per second", "flocking.py", "res[v][c:d] = savgol_filter(src[c:d], window, order, deriv=1) * fps", "res[v][c:d] = savgol_filter(src[c:d], window, order, deriv=1)"),
    ("no cut at long steps", "flocking.py", "cut = (np.diff(frames) != 1) | ~(step <= max_step)", "cut = np.diff(frames) != 1"),
    ("no cut at missing frames", "flocking.py", "cut = (np.diff(frames) != 1) | ~(step <= max_step)", "cut = ~(step <= max_step)"),
    ("a NaN step does not cut", "flocking.py", "cut = (np.diff(frames) != 1) | ~(step <= max_step)", "cut = (np.diff(frames) != 1) | (step > max_step)"),
    ("milling sign flipped", "flocking.py", 'out["milling"] = float(np.mean(rhat[:, 0] * u[away, 1] - rhat[:, 1] * u[away, 0]))', 'out["milling"] = float(np.mean(rhat[:, 1] * u[away, 0] - rhat[:, 0] * u[away, 1]))'),
    ("no speed threshold for headings", "flocking.py", "moving = has & (s >= min_speed) & (s > 0)", "moving = has & (s > 0)"),
    ("weighted polarisation not divided by the speeds", "flocking.py", 'out["polarisation_w"] = float(np.hypot(*v[has].sum(axis=0)) / total) if total > 0 and has.sum() >= 2 else np.nan', 'out["polarisation_w"] = float(np.hypot(*v[has].mean(axis=0))) if total > 0 and has.sum() >= 2 else np.nan'),
    ("radius is the mean distance, not the RMS", "flocking.py", "radius=float(np.sqrt(np.mean(d**2)))", "radius=float(np.mean(d))"),
    ("nearest neighbour may be oneself", "flocking.py", "        np.fill_diagonal(dist, np.inf)\n        out[\"nn_mean\"]", "        out[\"nn_mean\"]"),
    ("collinear hull is NaN", "flocking.py", 'out["hull_area"] = 0.0', 'out["hull_area"] = np.nan'),
    ("opponents include teammates", "flocking.py", "other = ~sel & np.isin(t, (0, 1))", "other = np.isin(t, (0, 1))"),
    ("neighbours ranked among moving players only", "flocking.py", "dm = np.where(mask, dist, np.inf)", "dm = np.where(mask & mv[None, :], dist, np.inf)"),
    ("direction to a neighbour reversed", "flocking.py", "diff = p[None, :, :] - p[:, None, :]  # [i, j] = p_j - p_i", "diff = p[:, None, :] - p[None, :, :]"),
    ("time shift not circular", "flocking.py", 'out["frame"] = (out["frame"].to_numpy() - 1 + s) % n_frames + 1', 'out["frame"] = out["frame"].to_numpy() + s'),
    ("one time shift for every id", "flocking.py", "rng.integers(min_shift, n_frames - min_shift + 1, len(chosen))", "np.full(len(chosen), rng.integers(min_shift, n_frames - min_shift + 1))"),
    ("shuffle mixes frames and teams", "flocking.py", "group = out.iloc[rows].groupby(list(by), sort=False).ngroup().to_numpy()", "group = np.zeros(len(rows), int)"),
    ("lag sign flipped", "flocking.py", "p, q = (a[: n - lag], b[lag:]) if lag >= 0 else (a[-lag:], b[: n + lag])", "p, q = (a[lag:], b[: n - lag]) if lag >= 0 else (a[: n + lag], b[-lag:])"),
    ("goalkeepers kept", "flocking.py", 'return gt[(gt["cls"] != BALL) & ~gt["id"].isin(keepers)].reset_index(drop=True)', 'return gt[gt["cls"] != BALL].reset_index(drop=True)'),
    ("team -1 tracks kept", "flocking.py", 'keep = (tracks["cls"] != BALL).to_numpy() & team.isin((0, 1)).to_numpy()', 'keep = (tracks["cls"] != BALL).to_numpy()'),
    ("flock ignores --tracks-dir", "cli.py", "    if args.tracks_dir:\n        players = players_from_tracks", "    if False:\n        players = players_from_tracks"),
    # added after the independent review of 2026-11-25
    ("runs cut by row number, not frame", "flocking.py", "r = run_ids(frames[a:b], px[a:b], py[a:b], max_step)", "r = run_ids(np.arange(a, b), px[a:b], py[a:b], max_step)"),
    ("milling about the movers' centroid", "flocking.py", "        away = d[moving] > 0\n        if away.any():\n            rhat = r[moving][away] / d[moving][away, None]", "        rm = xy[moving] - xy[moving].mean(axis=0)\n        dm = np.hypot(rm[:, 0], rm[:, 1])\n        away = dm > 0\n        if away.any():\n            rhat = rm[away] / dm[away, None]"),
    ("weighted polarisation from one velocity", "flocking.py", "if total > 0 and has.sum() >= 2 else np.nan", "if total > 0 else np.nan"),
    ("no heading for a single mover", "flocking.py", "    if moving.any():  # one mover", "    if moving.sum() >= 2:  # one mover"),
    ("shuffle leaves speed stale", "flocking.py", 'if {"vx", "vy", "speed"} <= set(out.columns):', "if False:"),
    ("clips drawn with replacement", "flocking.py", "rng.choice(len(pool), n, replace=False)", "rng.choice(len(pool), n, replace=True)"),
    ("draw_clips ignores exclude", "flocking.py", "pool = [x for x in names if x not in set(exclude)]", "pool = list(names)"),
    ("mix takes every id from one clip", "flocking.py", 'for i, name in plan.items()], ignore_index=True)', 'for i, name in ((i, next(iter(plan.values()))) for i in plan)], ignore_index=True)'),
    ("flock ignores --null mix", "cli.py", '        if args.null == "mix":\n            ids = sorted(', '        if False:\n            ids = sorted('),
    ("flock ignores --null shuffle", "cli.py", '        elif args.null == "shuffle":\n            kin = shuffle_within(kin, rng)', '        elif False:\n            kin = shuffle_within(kin, rng)'),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Mutation check for flocker.flocking and the flock command.")
    ap.add_argument("--work", type=Path, required=True, help="scratch folder under the repository's tmp/ for the mutated copies")
    args = ap.parse_args()
    results = []
    for k, (name, fname, old, new) in enumerate(MUTATIONS, 1):
        work = args.work / f"m{k:02d}"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ROOT / "src", work / "src")
        shutil.copytree(ROOT / "tests", work / "tests")
        shutil.copy(ROOT / "pyproject.toml", work / "pyproject.toml")
        target = work / "src" / "flocker" / fname
        text = target.read_text()
        if text.count(old) != 1:
            print(f"m{k:02d} {name}: the text to mutate occurs {text.count(old)} times; fix the list", file=sys.stderr)
            return 2
        target.write_text(text.replace(old, new))
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "unit", "-p", "no:cacheprovider", "tests/test_flocking.py"], cwd=work, capture_output=True, text=True)
        failed = [line.split(" ")[1] for line in run.stdout.splitlines() if line.startswith("FAILED ")]
        caught = run.returncode != 0
        results.append((name, caught, failed))
        print(f"m{k:02d} {'CAUGHT' if caught else 'MISSED'}  {name}: {', '.join(f.split('::')[-1] for f in failed) or run.stdout.strip().splitlines()[-1]}", flush=True)
    missed = [n for n, c, _ in results if not c]
    print(f"{len(results) - len(missed)} of {len(results)} mutations caught" + (f"; missed: {missed}" if missed else ""))
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
