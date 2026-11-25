"""Flocker's commands (run through bin/flocker.py).

Project: Flocker
File: src/flocker/cli.py
Purpose: argument parsing and dispatch for Flocker's commands
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

Commands:
    build-dataset   cut TeamTrack train/val frames into full-resolution YOLO tiles
    train           fine-tune a YOLO detector on those tiles
    track           detect (once, cached) and track players and the ball in TeamTrack videos; --teams labels teams
    eval            score tracker output (a folder of <sequence>.txt MOT files) against TeamTrack ground truth
"""

import argparse
import json
import sys
from pathlib import Path

from flocker.teamtrack import SPLITS


def _add_dataset_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--teamtrack-root", type=Path, default=None, help="TeamTrack soccer_top root (default: <primary checkout>/videos/raw/teamtrack_soccer_top)")
    p.add_argument("--split", choices=SPLITS, default="test", help="which split's sequences (default: %(default)s)")
    p.add_argument("--sequences", nargs="+", default=None, metavar="NAME", help="only these sequences")


def cmd_eval(args: argparse.Namespace) -> int:
    from flocker.evaluate import evaluate, format_table
    from flocker.mot import read_mot
    from flocker.teamtrack import list_sequences, load_gt, select_objects

    seqs = list_sequences(args.teamtrack_root, args.split)
    if args.sequences:
        seqs = [s for s in seqs if s.name in set(args.sequences)]
    if not seqs:
        print("eval: no sequences selected", file=sys.stderr)
        return 2
    run_path = args.pred_dir / "run.json"
    processed = {k: v.get("frames") for k, v in json.loads(run_path.read_text()).get("sequences", {}).items()} if run_path.is_file() else {}
    gts, preds, missing, clipped = {}, {}, [], []
    for s in seqs:
        gt = load_gt(s, objects=args.objects)
        if processed.get(s.name) and processed[s.name] < gt["frame"].max():
            gt = gt[gt["frame"] <= processed[s.name]]  # a --max-frames run: score only the frames it processed
            clipped.append(f"{s.name}:{processed[s.name]}")
        gts[s.name] = gt
        path = args.pred_dir / f"{s.name}.txt"
        if path.is_file():
            preds[s.name] = select_objects(read_mot(path), args.objects)
        else:
            missing.append(s.name)
    if missing and not args.allow_missing:
        print(f"eval: no prediction file for {len(missing)} sequence(s), e.g. {args.pred_dir / (missing[0] + '.txt')}; pass --allow-missing to score them as empty", file=sys.stderr)
        return 2
    table = evaluate(gts, preds, iou_threshold=args.iou, hota=not args.no_hota, n_jobs=args.jobs, max_center_dist=args.max_dist)
    match = f"centres <= {args.max_dist} px (no HOTA)" if args.max_dist is not None else f"IoU >= {args.iou}"
    print(f"# {args.pred_dir} | split {args.split} | objects {args.objects} | CLEAR/ID {match}" + (f" | {len(missing)} missing, scored as empty" if missing else "") + (f" | ground truth clipped to the frames run.json says were processed: {', '.join(clipped)}" if clipped else ""))
    print(format_table(table))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.out, float_format="%.6f")
        meta = {"pred_dir": str(args.pred_dir), "split": args.split, "objects": args.objects, "iou_threshold": args.iou, "max_center_dist": args.max_dist, "missing": missing, "hota_alpha": table.attrs.get("hota_alpha", {})}
        args.out.with_suffix(".json").write_text(json.dumps(meta, indent=1))
        print(f"wrote {args.out} and {args.out.with_suffix('.json')}")
    return 0


def cmd_build_dataset(args: argparse.Namespace) -> int:
    from flocker.teamtrack import list_sequences
    from flocker.yolo_dataset import MISALIGNED_TRAIN, build_yolo_dataset

    train = [s for s in list_sequences(args.teamtrack_root, "train") if args.keep_misaligned or s.name not in MISALIGNED_TRAIN]
    val = list_sequences(args.teamtrack_root, "val")
    manifest = build_yolo_dataset(args.out, train, val, every=args.every, every_val=args.every_val, tile=args.tile, min_overlap=args.min_overlap, min_visible=args.min_visible, quality=args.jpeg_quality, workers=args.workers)
    print(json.dumps(manifest["totals"], indent=1))
    print(f"wrote {Path(args.out).resolve() / 'data.yaml'} ({len(train)} train and {len(val)} val sequences)")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    from flocker.detector import train

    overrides = {k: v for k, v in {"epochs": args.epochs, "batch": args.batch, "imgsz": args.imgsz, "workers": args.workers}.items() if v is not None}
    best = train(args.data, args.project, args.name, args.model, device=args.device, **overrides)
    print(f"best weights: {best}")
    return 0


def _parse_sets(pairs: list[str]) -> dict:
    """--set key=value pairs, with values typed as YAML (0.3 -> float, true -> bool, 60 -> int)."""
    import yaml

    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise SystemExit(f"--set needs key=value, not {pair!r}")
        out[key] = yaml.safe_load(value)
    return out


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cmd_track(args: argparse.Namespace) -> int:
    import pandas as pd

    from flocker.mot import read_mot, write_mot
    from flocker.teamtrack import list_sequences
    from flocker.track import detect_video, suppress_duplicates, timed, track_detections, tracker_config

    seqs = list_sequences(args.teamtrack_root, args.split)
    if args.sequences:
        seqs = [s for s in seqs if s.name in set(args.sequences)]
    if not seqs:
        print("track: no sequences selected", file=sys.stderr)
        return 2
    overrides = _parse_sets(args.set)
    out_dir, det_dir = args.out_dir.resolve(), args.out_dir.resolve() / "detections"
    det_dir.mkdir(parents=True, exist_ok=True)
    run_path = out_dir / "run.json"
    run = json.loads(run_path.read_text()) if run_path.is_file() else {"detection": None, "tracking": None, "sequences": {}}
    model = None
    for s in seqs:
        info = s.seqinfo()
        det_path = det_dir / f"{s.name}.txt"
        n_frames = min(info["seqlength"], args.max_frames) if args.max_frames else info["seqlength"]
        rec = run["sequences"].get(s.name, {})
        fresh = not (args.reuse_detections and det_path.is_file())
        if not fresh:
            dets = read_mot(det_path)
        else:
            if model is None:
                from ultralytics import YOLO

                model = YOLO(str(args.model))
                run["detection"] = {"model": str(args.model.resolve()), "model_sha256": _sha256(args.model), "imgsz": args.imgsz, "conf": args.conf, "iou": args.nms_iou, "half": not args.fp32, "batch": args.batch, "max_frames": args.max_frames}
            dets, seconds = timed(detect_video, s.video_path, model, imgsz=args.imgsz, conf=args.conf, iou=args.nms_iou, device=args.device, half=not args.fp32, batch=args.batch, max_frames=n_frames)
            write_mot(dets, det_path)
            rec["detect_seconds"], rec["detect_fps"] = round(seconds, 1), round(n_frames / seconds, 2)
        if args.teams:
            from flocker.team import detection_colours, label_teams

            col_path = out_dir / "colours" / f"{s.name}.csv"
            colours = None if fresh or not col_path.is_file() else pd.read_csv(col_path)
            if colours is None or len(colours) != len(dets):  # colours are row-aligned with the detection file
                colours, seconds = timed(detection_colours, s.video_path, dets)
                col_path.parent.mkdir(exist_ok=True)
                colours.to_csv(col_path, index=False, float_format="%.2f")
                rec["colour_seconds"] = round(seconds, 1)
            dets, team_model = label_teams(dets, colours)
            rec["team_means_lab"] = team_model.means.round(1).tolist()
        kept = dets if args.dedup_iou >= 1 else suppress_duplicates(dets, args.dedup_iou)
        tracks, seconds = timed(track_detections, kept, tracker=args.tracker, n_frames=n_frames, orig_shape=(info["imheight"], info["imwidth"]), box_source=args.box_source, **overrides)
        write_mot(tracks, out_dir / f"{s.name}.txt")
        if args.teams:  # each track's team (0, 1, or -1: none, e.g. a goalkeeper or the ball), beside the tracks
            (out_dir / "teams").mkdir(exist_ok=True)
            tracks.groupby("id")["team"].first().rename_axis("id").reset_index().to_csv(out_dir / "teams" / f"{s.name}.csv", index=False)
        rec.update({"frames": n_frames, "detections": int(len(dets)), "detections_kept": int(len(kept)), "track_rows": int(len(tracks)), "track_ids": int(tracks["id"].nunique()), "track_seconds": round(seconds, 2)})
        run["sequences"][s.name] = rec
        print(f"{s.name}: {len(dets)} detections ({len(kept)} after duplicate suppression), {len(tracks)} track boxes, {tracks['id'].nunique()} ids" + (f", detect {rec['detect_fps']} fps" if "detect_fps" in rec else ""), flush=True)
    run["tracking"] = {"tracker": args.tracker, "settings": {k: v for k, v in vars(tracker_config(args.tracker, **overrides)).items()}, "overrides": overrides, "dedup_iou": args.dedup_iou, "teams": args.teams, "box_source": args.box_source}
    run_path.write_text(json.dumps(run, indent=1))
    print(f"wrote {len(seqs)} track files and {run_path}")
    return 0


def cmd_dots(args: argparse.Namespace) -> int:
    from flocker.mot import read_mot
    from flocker.render import render_dots
    from flocker.teamtrack import find_sequence, load_gt, team_of

    seq = find_sequence(args.sequence, args.teamtrack_root)
    if args.tracks:
        tracks, source = read_mot(args.tracks), f"tracks {Path(args.tracks).name}"
        teams = Path(args.tracks).parent / "teams" / (Path(args.tracks).stem + ".csv")
        if teams.is_file():  # written by track --teams
            import pandas as pd

            tracks["team"] = tracks["id"].map(pd.read_csv(teams).set_index("id")["team"]).fillna(-1).astype(int)
    else:
        tracks, source = load_gt(seq), "ground truth"
        tracks["team"] = team_of(tracks["id"])
    out = render_dots(seq.video_path, tracks, args.out, speed=args.speed, background=args.background, width=args.width, radius=args.radius, trail=args.trail, label=f"{seq.name} {source}", max_frames=args.max_frames)
    print(f"wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="flocker", description="Flocker: flocking behaviour in tracked video. Commands below; '<command> --help' for each.")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("eval", help="score tracker output against TeamTrack ground truth (HOTA, CLEAR-MOT, IDF1)")
    _add_dataset_args(p)
    p.add_argument("--pred-dir", type=Path, required=True, help="folder of <sequence>.txt MOT files")
    p.add_argument("--objects", choices=["players", "ball", "all"], default="players", help="which objects to score (default: %(default)s); predictions are filtered by their class column")
    p.add_argument("--iou", type=float, default=0.5, help="IoU needed for a CLEAR-MOT/IDF1 match (default: %(default)s)")
    p.add_argument("--no-hota", action="store_true", help="skip HOTA (about 15 s per sequence)")
    p.add_argument("--max-dist", type=float, default=None, metavar="PX", help="match box centres within PX pixels instead of IoU (CLEAR-MOT and IDF1; skips HOTA)")
    p.add_argument("--jobs", type=int, default=None, help="worker processes (default: half the CPUs, at most one per sequence)")
    p.add_argument("--allow-missing", action="store_true", help="score a sequence without a prediction file as empty instead of failing")
    p.add_argument("--out", type=Path, default=None, help="also write the table as CSV (and the settings and per-threshold HOTA as JSON beside it)")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("build-dataset", help="cut TeamTrack train/val frames into full-resolution YOLO tiles")
    p.add_argument("--teamtrack-root", type=Path, default=None, help="TeamTrack soccer_top root (default: <primary checkout>/videos/raw/teamtrack_soccer_top)")
    p.add_argument("--out", type=Path, required=True, help="new folder for images/, labels/, data.yaml and manifest.json")
    p.add_argument("--every", type=int, default=30, help="use every Nth train frame (default: %(default)s, i.e. about 1 per second)")
    p.add_argument("--every-val", type=int, default=90, help="use every Nth val frame (default: %(default)s)")
    p.add_argument("--tile", type=int, default=1280, help="tile size in pixels (default: %(default)s)")
    p.add_argument("--min-overlap", type=int, default=256, help="minimum overlap between neighbouring tiles (default: %(default)s)")
    p.add_argument("--min-visible", type=float, default=0.5, help="label a box in a tile when this fraction of it is inside (default: %(default)s)")
    p.add_argument("--jpeg-quality", type=int, default=95)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--keep-misaligned", action="store_true", help="also use the six train sequences whose labels drift (see flocker.yolo_dataset)")
    p.set_defaults(func=cmd_build_dataset)

    p = sub.add_parser("train", help="fine-tune a YOLO detector on a build-dataset folder")
    p.add_argument("--data", type=Path, required=True, help="the dataset's data.yaml")
    p.add_argument("--model", type=Path, required=True, help="local starting weights, e.g. resources/models/yolo11n.pt in the primary checkout")
    p.add_argument("--project", type=Path, required=True, help="folder for the run (Ultralytics writes <project>/<name>/)")
    p.add_argument("--name", required=True)
    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--batch", type=int, default=None)
    p.add_argument("--imgsz", type=int, default=None)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--device", default="0")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("track", help="detect (cached) and track players and the ball in TeamTrack videos, writing MOT files")
    _add_dataset_args(p)
    p.add_argument("--model", type=Path, help="detector weights (not needed with --reuse-detections when every cache exists)")
    p.add_argument("--out-dir", type=Path, required=True, help="writes <seq>.txt tracks, detections/<seq>.txt and run.json")
    p.add_argument("--imgsz", type=int, default=3840, help="inference size; 3840 keeps TeamTrack frames at native scale (default: %(default)s)")
    p.add_argument("--conf", type=float, default=0.05, help="detection confidence floor; the tracker applies its own thresholds above it (default: %(default)s)")
    p.add_argument("--nms-iou", type=float, default=0.6, help="NMS IoU (default: %(default)s)")
    p.add_argument("--batch", type=int, default=2, help="frames per inference batch (default: %(default)s)")
    p.add_argument("--fp32", action="store_true", help="infer in FP32 instead of FP16")
    p.add_argument("--device", default="0")
    p.add_argument("--max-frames", type=int, default=None, help="only the first N frames of each sequence")
    p.add_argument("--reuse-detections", action="store_true", help="track from detections/<seq>.txt when it exists")
    p.add_argument("--tracker", default="flocker", help="'flocker' (config/trackers/flocker_bytetrack.yaml: ByteTrack tuned on TeamTrack's val split), an Ultralytics tracker name such as bytetrack, or a YAML path (default: %(default)s)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a tracker setting, e.g. --set track_buffer=60 (repeatable)")
    p.add_argument("--dedup-iou", type=float, default=0.3, metavar="IOU", help="before tracking, drop a detection overlapping a higher-scoring one of its class by more than IOU (a second NMS; 1 turns it off; default: %(default)s)")
    p.add_argument("--teams", action="store_true", help="label each player track with its team from kit colours: writes colours/<seq>.csv (cached) and teams/<seq>.csv (id,team; -1: neither team)")
    p.add_argument("--box-source", choices=["track", "detection"], default="track", help="report Kalman-filtered track boxes or the matched raw detections (default: %(default)s)")
    p.set_defaults(func=cmd_track)

    p = sub.add_parser("dots", help="render a TeamTrack clip's players as dots (ground truth, or a tracks file), sped up")
    p.add_argument("--teamtrack-root", type=Path, default=None, help="TeamTrack soccer_top root (default: <primary checkout>/videos/raw/teamtrack_soccer_top)")
    p.add_argument("--sequence", required=True, help="sequence name, e.g. D_20220220_1_1530_1560")
    p.add_argument("--tracks", type=Path, default=None, help="a MOT tracks file; default: the sequence's ground truth, coloured by team. Tracks are coloured by team too when track --teams wrote teams/<seq>.csv beside them")
    p.add_argument("--out", type=Path, required=True, help="output .mp4 (H.264)")
    p.add_argument("--speed", type=int, default=4, help="keep every Nth frame at the source frame rate (default: %(default)s)")
    p.add_argument("--background", choices=["median", "frame"], default="median", help="the clip's empty pitch (players erased) or the original frames (default: %(default)s)")
    p.add_argument("--width", type=int, default=1920, help="output width in pixels (default: %(default)s)")
    p.add_argument("--radius", type=int, default=7, help="dot radius in output pixels (default: %(default)s)")
    p.add_argument("--trail", type=int, default=0, help="draw each dot's last N output positions as a line (default: off)")
    p.add_argument("--max-frames", type=int, default=None)
    p.set_defaults(func=cmd_dots)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
