# Flocker

Research into unexpected instances of flocking behaviour and their potential real-world applications.

The first case study tracks soccer players in top-down drone video: detect and track every player, draw them as
dots on the pitch, and ask whether the teams move the way flocks do.

## Status

The video work is organised as five edits:
1. remove shadows;
2. replace players with dots;
3. scale movement;
4. correct the camera angle;
5. speed up playback.

- **The evaluation harness works.** It scores detection and tracking on TeamTrack's ground truth with HOTA,
  CLEAR-MOT and IDF1, and has been validated three ways: hand-computed cases, deliberate breakages it catches, and
  perturbed real data.
- **A YOLO11n player and ball detector** has been fine-tuned on full-resolution tiles of TeamTrack's top-view
  clips.
- **Players keep their identities through a clip.** On TeamTrack's test split, the identity score IDF1 is 97.3
  (centres within 15 px), up from 71.4 with Ultralytics' tracker defaults. That leaves 36 identity switches in
  99 player-minutes (9 clips of 30 s, 22 players).
- **Each player's team comes from kit colour,** with goalkeepers kept apart; 98.9 % of the test split's tracked
  outfield positions carry the right team.
- **Players can be redrawn as dots** on the clip's empty pitch (edit 2), at N x speed (edit 5), coloured by team.
- **Not done yet:**
  - edit 4, correcting the camera angle with a homography;
  - edit 3, scaling movement;
  - edit 1, removing shadows on the stock clips;
  - the flocking analysis itself.

Results and how they were obtained: `notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md` (the harness and the
detector) and `notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md` (identity and team labels).

## Quick start

The code runs in the `Flocker` conda environment (`config/environment.yml`, plus its post-create steps) and
needs no installation:

```bash
P="conda run -n Flocker python bin/flocker.py"
$P --help                                         # build-dataset, train, track, eval, dots
$P dots --sequence D_20220220_1_1530_1560 --out videos/edit/gt_dots_4x.mp4 --speed 4   # videos/edit/ is gitignored
$P track --model <weights> --split test --out-dir <folder> --teams   # tracks, plus each track's team
$P eval --pred-dir <folder of <sequence>.txt MOT files> --split test
conda run -n Flocker python -m pytest -q -m unit # fast tests; plain `pytest -q` adds the real-data ones
```

## Data

- **Not redistributed.** No video or dataset is in this repository. `videos/raw/SOURCES.md` records each clip's
  source, licence, attribution and checksum.
- **TeamTrack** (MIT) supplies the annotated top-view clips: A. Scott et al., "TeamTrack: A Dataset for
  Multi-Sport Multi-Object Tracking in Full-pitch Videos", CVPR Workshops (CVsports) 2024, arXiv:2404.13868.
- **Stock clips:** Pexels, Pixabay and Wikimedia Commons; publish links to them, never the files.

## Licence

`LICENSE` (CC0 1.0) covers this project's own work. Third-party clips and datasets keep their own licences.
Ultralytics YOLO, used for detection, is AGPL-3.0. That is fine for research, but distributing software built on
it brings AGPL obligations.

Contributors and AI agents: see `AGENTS.md`.
