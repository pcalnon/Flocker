"""The studies behind notes/FLOCKER_2026-11-25_PITCH-HOMOGRAPHY.md: the pitch's size, the fit's accuracy, the camera's
motion, the parallax of player boxes, and speeds in metres.

Project: Flocker
File: util/ad-hoc/2026-11-25_pitch_study.py
Purpose: single-use analyses for the image-to-pitch homography (edit 4); each subcommand writes CSV/PNG into --out
Author: Paul Calnon
Created: 2026-11-25
License: CC0 1.0 (see LICENSE)

Ran on 2026-11-25 with the Flocker environment, from a worktree (the code finds the media in the primary checkout):

    S=~/Development/python/Flocker/tmp/2026-11-25_homography
    P="/opt/miniforge3/envs/Flocker/bin/python -I"
    $P util/ad-hoc/2026-11-25_pitch_study.py size --out $S/study          # frame 1 of all 60 clips, size free
    $P util/ad-hoc/2026-11-25_pitch_study.py motion --pitch-dir $S/pitch --out $S/study
    $P util/ad-hoc/2026-11-25_pitch_study.py boxes --pitch-dir $S/pitch --out $S/study
    $P util/ad-hoc/2026-11-25_pitch_study.py speeds --pitch-dir $S/pitch --out $S/study

`--pitch-dir` is the output of `bin/flocker.py pitch` for all three splits.
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from flocker.pitch import find_spots, fit_pitch, homography_from_corners, line_response  # noqa: E402
from flocker.teamtrack import PITCH_CORNERS_PX, list_sequences  # noqa: E402


def _frame(video, index: int = 0) -> np.ndarray:
    cap = cv2.VideoCapture(str(video))
    for _ in range(index):
        cap.grab()
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise ValueError(f"cannot read frame {index + 1} of {video}")
    return img


def _size_one(seq) -> dict:
    cv2.setNumThreads(2)
    img = _frame(seq.video_path)
    fit, obs = fit_pitch(img, homography_from_corners(PITCH_CORNERS_PX), response=line_response(img))
    found = find_spots(img, fit)
    corners = fit.to_image([(-fit.length / 2, -fit.width / 2), (fit.length / 2, -fit.width / 2), (fit.length / 2, fit.width / 2), (-fit.length / 2, fit.width / 2)])
    row = {"split": seq.split, "sequence": seq.name, "length_m": fit.length, "width_m": fit.width, "observations": len(obs), "rms_px": fit.stats["rms_px"], "px_per_m_centre": fit.stats["px_per_m_centre"], "first_move_px": fit.stats["rounds"][0]["moved_px"]}
    for k, (u, v) in zip(("tl", "tr", "br", "bl"), corners):
        row[f"{k}_u"], row[f"{k}_v"] = u, v
    for k, v in found.items():
        row[f"{k}_error_px"] = v["error_px"] if v else np.nan
        row[f"{k}_error_cm"] = v["error_cm"] if v else np.nan
    print(f"{seq.name}: {fit.length:.3f} x {fit.width:.3f} m, rms {fit.stats['rms_px']:.3f} px, {len(obs)} obs", flush=True)
    return row


def cmd_size(args) -> None:
    seqs = list_sequences()
    with ProcessPoolExecutor(args.jobs) as ex:
        rows = list(ex.map(_size_one, seqs))
    df = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out / "size_frame1.csv", index=False, float_format="%.4f")
    print(df[["length_m", "width_m", "rms_px", "px_per_m_centre", "observations"]].describe().round(4).to_string())
    spot_cols = [c for c in df.columns if c.endswith("_error_px")]
    print(df[spot_cols + [c.replace("_px", "_cm") for c in spot_cols]].describe().round(3).to_string())


def _tables(pitch_dir: Path):
    """(sequence, split, homography table, fit) for every clip with a pitch table, in match order."""
    from flocker.pitch import PitchFit, read_homographies

    for seq in sorted(list_sequences(), key=lambda s: s.name):
        csv = pitch_dir / f"{seq.name}.csv"
        if csv.is_file():
            yield seq, read_homographies(csv), PitchFit.load(pitch_dir / f"{seq.name}.json")


def _gt_metres(seq, table) -> pd.DataFrame:
    """Ground-truth players with box centres in pixels (cx, cy) and in pitch metres (mx, my), per-frame homographies."""
    from flocker.mot import centers
    from flocker.pitch import with_pitch_positions
    from flocker.teamtrack import load_gt

    gt = with_pitch_positions(load_gt(seq, objects="players"), table)
    c = centers(gt)
    gt["cx"], gt["cy"] = c[:, 0], c[:, 1]
    return gt


def cmd_motion(args) -> None:
    """Camera motion per clip and across the match, and what a single homography per clip would cost."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from flocker.pitch import H_COLUMNS, apply_h, camera_motion

    args.out.mkdir(parents=True, exist_ok=True)
    rows, traj = [], []
    first_corners = None
    for seq, table, fit in _tables(args.pitch_dir):
        hs = table[H_COLUMNS].to_numpy(float).reshape(-1, 3, 3)
        corners = np.array([(-fit.length / 2, -fit.width / 2), (fit.length / 2, -fit.width / 2), (fit.length / 2, fit.width / 2), (-fit.length / 2, fit.width / 2)])
        img = np.stack([apply_h(np.linalg.inv(h), corners) for h in hs])  # T x 4 x 2
        mean = img.mean(axis=0)
        # one homography per clip, the one through the clip's mean corner positions: its error at each corner and frame,
        # in pixels and in metres (each frame's own homography maps the corner where that homography puts it)
        from flocker.pitch import homography_4pt

        h_one = homography_4pt(mean, corners)
        err_m = np.stack([np.linalg.norm(apply_h(h_one, img[t]) - corners, axis=1) for t in range(len(img))])
        start = int(seq.name.split("_")[-2])
        if first_corners is None:
            first_corners = img[0]
        traj.append(pd.DataFrame({"t_s": start + (table["frame"].to_numpy() - 1) / 29.97, "tl_dx": img[:, 0, 0] - first_corners[0, 0], "tl_dy": img[:, 0, 1] - first_corners[0, 1], "br_dx": img[:, 2, 0] - first_corners[2, 0], "br_dy": img[:, 2, 1] - first_corners[2, 1]}))
        rows.append({"split": seq.split, "sequence": seq.name, **camera_motion(table, fit.length, fit.width), "one_h_error_m_max": float(err_m.max()), "one_h_error_m_p95": float(np.percentile(err_m, 95)), "frame1_corner_vs_match_start_px": float(np.linalg.norm(img[0] - first_corners, axis=1).max()), "rms_px_median": float(table["rms_px"].median()), "rms_px_max": float(table["rms_px"].max()), "restarts": int(table["restart"].sum()), "observations_min": int(table["observations"].min())})
    df = pd.DataFrame(rows)
    df["px_per_m_lo"] = df["px_per_m_centre_range"].str[0]
    df["px_per_m_hi"] = df["px_per_m_centre_range"].str[1]
    df.drop(columns="px_per_m_centre_range").to_csv(args.out / "motion.csv", index=False, float_format="%.4f")
    cols = ["corner_shift_px_max", "centre_shift_px_max", "yaw_deg_range", "one_h_error_m_max", "one_h_error_m_p95", "frame1_corner_vs_match_start_px", "rms_px_median", "rms_px_max", "restarts", "observations_min", "px_per_m_lo", "px_per_m_hi"]
    print(df[cols].describe().round(3).to_string())
    print(df.sort_values("corner_shift_px_max", ascending=False)[["sequence"] + cols[:5]].head(8).round(3).to_string(index=False))
    t = pd.concat(traj)
    fig, ax = plt.subplots(figsize=(14, 4))
    for col, lab in (("tl_dx", "top-left corner, x"), ("tl_dy", "top-left corner, y"), ("br_dx", "bottom-right corner, x"), ("br_dy", "bottom-right corner, y")):
        ax.plot(t["t_s"] / 60, t[col], lw=0.7, label=lab)
    ax.set_xlabel("match time, min (the 60 clips)")
    ax.set_ylabel("image position - match start, px")
    ax.grid(alpha=0.3)
    ax.legend(ncol=4, fontsize=8)
    ax.set_title("Where two pitch corners appear in the image, frame by frame (per-frame homographies)")
    fig.tight_layout()
    fig.savefig(args.out / "motion_match.png", dpi=90)


def cmd_boxes(args) -> None:
    """Ground-truth box size against pitch position: bodies project away from the camera's nadir."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from flocker.pitch import local_scale

    parts = []
    for seq, table, fit in _tables(args.pitch_dir):
        if seq.split == "train" or seq.name == "D_20220220_1_1770_1800":  # val + test; 1770_1800 is boxed to another convention
            continue
        g = _gt_metres(seq, table)
        g = g[g["frame"] % 5 == 0]
        h0 = np.linalg.inv(table.loc[table["frame"] == 1, [f"h{i}" for i in range(9)]].to_numpy(float).reshape(3, 3))
        sc = local_scale(h0, g[["mx", "my"]].to_numpy())
        parts.append(g.assign(wm=g["w"] / sc, hm=g["h"] / sc))
    gt = pd.concat(parts)
    args.out.mkdir(parents=True, exist_ok=True)
    bx, by = np.arange(-54, 55, 6), np.arange(-36, 37, 6)
    wx = gt.groupby(pd.cut(gt["mx"], bx), observed=False)["wm"].agg(["median", "count"])
    hy = gt.groupby(pd.cut(gt["my"], by), observed=False)["hm"].agg(["median", "count"])
    print(f"{len(gt)} boxes (val and test except 1770_1800, every 5th frame)")
    print("box width (m) by pitch x:\n" + wx.round(3).to_string())
    print("box height (m) by pitch y:\n" + hy.round(3).to_string())
    pd.concat({"width_by_x": wx, "height_by_y": hy}).to_csv(args.out / "boxes.csv")
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    ax[0].plot((bx[:-1] + bx[1:]) / 2, wx["median"], "o-")
    ax[0].set_xlabel("pitch x, m")
    ax[0].set_ylabel("median box width, m")
    ax[1].plot((by[:-1] + by[1:]) / 2, hy["median"], "o-")
    ax[1].set_xlabel("pitch y, m")
    ax[1].set_ylabel("median box height, m")
    for a in ax:
        a.grid(alpha=0.3)
    fig.suptitle("Ground-truth player boxes grow away from the middle: bodies seen from about 100 m up lean outward")
    fig.tight_layout()
    fig.savefig(args.out / "boxes.png", dpi=90)


def cmd_speeds(args) -> None:
    """Players' speeds and distances in metres, from ground-truth positions through per-frame homographies; and the
    velocity error a single homography per clip would add."""
    from scipy.signal import savgol_filter

    from flocker.pitch import H_COLUMNS, apply_h

    fps, win = 29.97, 15  # a 0.5 s Savitzky-Golay window: box corners are whole pixels, so raw differences are noisy
    from flocker.yolo_dataset import MISALIGNED_TRAIN

    rows, per_clip = [], []
    for seq, table, fit in _tables(args.pitch_dir):
        if seq.name in MISALIGNED_TRAIN:  # labels that drift ahead of the video by up to 6 frames
            continue
        gt = _gt_metres(seq, table)
        h1 = table[H_COLUMNS].to_numpy(float)[0].reshape(3, 3)
        one = apply_h(h1, gt[["cx", "cy"]].to_numpy())  # frame 1's homography for every frame
        gt["ox"], gt["oy"] = one[:, 0], one[:, 1]
        for pid, g in gt.groupby("id"):
            g = g.sort_values("frame")
            if len(g) < 3 * win or (np.diff(g["frame"]) != 1).any():
                continue  # whole, gap-free tracks only
            v = np.column_stack([savgol_filter(g[c].to_numpy(), win, 2, deriv=1) * fps for c in ("mx", "my")])
            vo = np.column_stack([savgol_filter(g[c].to_numpy(), win, 2, deriv=1) * fps for c in ("ox", "oy")])
            speed = np.linalg.norm(v, axis=1)
            dist = np.linalg.norm(np.diff(np.column_stack([savgol_filter(g[c].to_numpy(), win, 2) for c in ("mx", "my")]), axis=0), axis=1).sum()
            minutes = (len(g) - 1) / fps / 60
            rows.append({"sequence": seq.name, "id": int(pid), "keeper": int(pid) in (0, 13), "top_speed_ms": float(speed.max()), "mean_speed_ms": float(speed.mean()), "metres_per_min": float(dist / minutes), "one_h_velocity_error_ms_max": float(np.linalg.norm(v - vo, axis=1).max())})
        per_clip.append(seq.name)
    df = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out / "speeds.csv", index=False, float_format="%.4f")
    out = df[~df["keeper"]]
    print(f"{len(df)} whole player tracks in {len(per_clip)} clips; outfield players:")
    print(out[["top_speed_ms", "mean_speed_ms", "metres_per_min", "one_h_velocity_error_ms_max"]].describe(percentiles=[0.05, 0.5, 0.95, 0.99]).round(3).to_string())
    print("goalkeepers:")
    print(df[df["keeper"]][["top_speed_ms", "mean_speed_ms", "metres_per_min"]].describe().round(3).to_string())
    print("fastest 5:\n" + out.sort_values("top_speed_ms", ascending=False).head(5).round(2).to_string(index=False))
    print("largest single-homography velocity errors:\n" + df.sort_values("one_h_velocity_error_ms_max", ascending=False).head(5).round(2).to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser(description="Studies behind notes/FLOCKER_2026-11-25_PITCH-HOMOGRAPHY.md (edit 4).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("size", help="fit frame 1 of every clip with the pitch size free")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--jobs", type=int, default=6)
    p.set_defaults(func=cmd_size)
    for name, func, text in (("motion", cmd_motion, "camera motion per clip and across the match"), ("boxes", cmd_boxes, "ground-truth box size against pitch position"), ("speeds", cmd_speeds, "players' speeds in metres per second")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--pitch-dir", type=Path, required=True, help="the pitch command's output")
        p.add_argument("--out", type=Path, required=True)
        p.set_defaults(func=func)
    args = ap.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
