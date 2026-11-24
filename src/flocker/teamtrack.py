"""TeamTrack's top-view soccer subset: sequences, videos and ground truth.

Project: Flocker
File: src/flocker/teamtrack.py
Purpose: find TeamTrack soccer_top sequences and load their MOT ground truth with team and ball labels
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE); TeamTrack itself is MIT-licensed (videos/raw/SOURCES.md)

Layout under the root (videos/raw/teamtrack_soccer_top):
    teamtrack/soccer_top/<split>/videos/<seq>.mp4          3840x2160, 29.97 fps, 900 frames
    teamtrack/soccer_top/<split>/annotations/<seq>.csv     per-player boxes, three header rows
    teamtrack-mot/soccer_top/<split>/<seq>/seqinfo.ini     seqlength, framerate, image size
    teamtrack-mot/soccer_top/<split>/<seq>/gt/gt.txt       MOT ground truth, 1-based frames

Facts checked on 2026-11-24 against all 60 sequences (notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md):
every sequence has the 23 ids 0..22; ids 0-10 are one team, 11-21 the other and 22 is the ball (matched to the
CSV's TeamID columns); referees and staff are not annotated. Six train sequences (0570_0600 to 0720_0750) carry
ground truth for frames 901-906, past their 900-frame videos, so load_gt() clips to seqlength by default.
"""

import configparser
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from flocker.mot import BALL, PLAYER, read_mot
from flocker.paths import teamtrack_root

SPLITS = ("train", "val", "test")
BALL_ID = 22
TEAM_SIZE = 11


def team_of(ids) -> np.ndarray:
    """Team (0 or 1) of each TeamTrack ground-truth id; -1 for the ball."""
    ids = np.asarray(ids)
    return np.where(ids == BALL_ID, -1, np.where(ids < TEAM_SIZE, 0, 1))


@dataclass(frozen=True)
class Sequence:
    """One 30-second TeamTrack clip."""

    root: Path
    split: str
    name: str

    @property
    def mot_dir(self) -> Path:
        return self.root / "teamtrack-mot" / "soccer_top" / self.split / self.name

    @property
    def gt_path(self) -> Path:
        return self.mot_dir / "gt" / "gt.txt"

    @property
    def seqinfo_path(self) -> Path:
        return self.mot_dir / "seqinfo.ini"

    @property
    def video_path(self) -> Path:
        return self.root / "teamtrack" / "soccer_top" / self.split / "videos" / f"{self.name}.mp4"

    @property
    def csv_path(self) -> Path:
        return self.root / "teamtrack" / "soccer_top" / self.split / "annotations" / f"{self.name}.csv"

    def seqinfo(self) -> dict:
        """seqinfo.ini's [Sequence] section, with numbers converted."""
        ini = configparser.ConfigParser()
        if not ini.read(self.seqinfo_path):
            raise FileNotFoundError(self.seqinfo_path)
        s = ini["Sequence"]
        return {"name": s.get("name", self.name), "framerate": s.getfloat("framerate"), "seqlength": s.getint("seqlength"), "imwidth": s.getint("imwidth"), "imheight": s.getint("imheight")}


def list_sequences(root: str | Path | None = None, splits=SPLITS) -> list[Sequence]:
    """Every sequence with a gt/gt.txt in the given splits, sorted by split order then name."""
    root = Path(root) if root is not None else teamtrack_root()
    if isinstance(splits, str):
        splits = (splits,)
    seqs = []
    for split in splits:
        if split not in SPLITS:
            raise ValueError(f"unknown split {split!r}; expected one of {SPLITS}")
        base = root / "teamtrack-mot" / "soccer_top" / split
        if base.is_dir():
            seqs += [Sequence(root, split, d.name) for d in sorted(base.iterdir()) if (d / "gt" / "gt.txt").is_file()]
    return seqs


def find_sequence(name: str, root: str | Path | None = None) -> Sequence:
    """The sequence called ``name``, in whichever split holds it."""
    for seq in list_sequences(root):
        if seq.name == name:
            return seq
    raise KeyError(f"no TeamTrack sequence named {name!r}")


def load_gt(seq: Sequence, clip: bool = True, objects: str = "all") -> pd.DataFrame:
    """Ground truth in flocker.mot's layout, plus ``team``; ``cls`` is set to PLAYER or BALL.

    clip drops rows past seqinfo's seqlength (frames the video does not have). objects is "all", "players" or "ball".
    """
    df = read_mot(seq.gt_path)
    if clip:
        df = df[df["frame"] <= seq.seqinfo()["seqlength"]]
    df = df.assign(cls=np.where(df["id"] == BALL_ID, BALL, PLAYER), team=team_of(df["id"]))
    return select_objects(df, objects).reset_index(drop=True)


def select_objects(df: pd.DataFrame, objects: str) -> pd.DataFrame:
    """Rows of one kind: "all", "players" (cls PLAYER, or UNKNOWN for class-less tracker output) or "ball"."""
    if objects == "all":
        return df
    if objects == "players":
        return df[df["cls"] != BALL]
    if objects == "ball":
        return df[df["cls"] == BALL]
    raise ValueError(f"objects must be 'all', 'players' or 'ball', not {objects!r}")
