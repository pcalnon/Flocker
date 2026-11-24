# TeamTrack evaluation harness and first detector

**Date**: 2026-11-24
**Scope**: the first step of the research pipeline. TeamTrack's ground truth is used to measure detection and
tracking, before any dots drawn from tracker output are trusted.
**Code**: `src/flocker/` (`teamtrack`, `mot`, `evaluate`, `yolo_dataset`, `detector`, `track`, `cli`),
`bin/flocker.py`, `tests/`
**Outputs** (gitignored; the primary checkout's `tmp/2026-11-24_teamtrack-eval/`): the tile dataset, training run,
detections, tracks and metric tables

## Summary

- **The metrics are validated.** The harness scores HOTA, CLEAR-MOT and IDF1 with py-motmetrics, using TrackEval's
  definitions. The checks:
  - hand-computed cases;
  - mutations of the code, which the tests catch;
  - real ground truth, perturbed in ways with exactly known effects.
- **A wrapper fixes a real problem with TeamTrack's ids.** py-motmetrics' HOTA assumes 1-based ids, and
  TeamTrack's start at 0. The wrapper relabels every id before scoring.
- **Off-the-shelf COCO YOLO is no baseline here.** Seen from directly above, players are not "persons" to it: it
  found 2 of 22 players on a test frame, at confidence 0.29 or below.
- **A YOLO11n detector is fine-tuned** on full-resolution tiles of 36 train sequences. On the 9 test sequences,
  with ByteTrack:
  - **positions are good:** centres within 15 px (about 0.5 m) give recall 97.8 % and precision 98.9 %, with a
    mean error of 4.3 px;
  - **IoU scores are lower:** HOTA 48.0 and MOTA 60.9, held down by box-size conventions;
  - **identity is the weak point:** 773 track ids for 198 players.
- **Six train sequences have labels that drift in time**, and are left out of training.
- **The camera barely moves**: at most about 12 px across the whole match. One homography could serve every clip.

## Tools added

All were checked with `util/validate_tool_sources.py` before installing. The output is kept in
`tmp/2026-11-24_toolchain/validate_tool_sources_2026-11-24_new-tools.txt`.

| Tool | Version | Source | Upstream (owner, stars, licence, last push) |
|---|---|---|---|
| pytest | 9.2.0 | conda-forge, built from PyPI's sdist | pytest-dev/pytest (org, 14,748, MIT, 2026-11-24) |
| black | 26.10.1 | conda-forge, built from PyPI's sdist | psf/black (org, 42,210, MIT, 2026-11-24) |
| isort | 9.0.2 | conda-forge, built from PyPI's sdist | PyCQA/isort (org, 6,965, MIT, 2026-11-16) |
| flake8 | 7.5.0 | conda-forge, built from the GitHub tag | PyCQA/flake8 (org, 3,837, MIT\*, 2026-11-04) |
| py-motmetrics | `develop` @ `e5ae766f` (reports 1.4.0) | GitHub archive, pip `--no-deps --no-build-isolation` | cheind/py-motmetrics (user, 1,484, MIT, 2026-07-17) |

\* GitHub's licence detection says NOASSERTION; the LICENSE file opens "Flake8 License (MIT)".

- **The dev tools:**
  - **The dry run** (`tmp/2026-11-24_toolchain/mamba-dryrun-devtools.txt`) only added packages: 15 `+` lines and
    no `-` lines.
  - **PyTorch is untouched**: it is still 2.13.0 on CUDA 12.9 afterwards.
  - **`pip check`** gives the same single known message, that `ultralytics-platform` is not installed.
- **Why py-motmetrics comes from GitHub:**
  - Conda-forge has only 1.2.0 (2020), and PyPI's newest release is 1.4.0 (2022). Both predate its HOTA fixes:
    "Hota bugs" (#203, 2025-06) and "fix hota overall aggregation" (#209, 2026-07).
  - Its CI now compares it with TrackEval (#212).
  - The commit is GitHub-verified.
- **The archive review:**
  - **sha256:** `824cee9062da4880343186c66ec023d9392f6d97aff617ddac559f46e1a8ebc8`. A copy is kept in
    `tmp/2026-11-24_toolchain/downloads/`.
  - **Packaging:** plain setuptools, depending on numpy, pandas and scipy only.
  - **No risky calls:** no network, shell, `eval`/`exec` or pickle use in the package code. The only `import imp`
    is in a Python 2 fallback branch that never runs on Python 3. Optional LAP solvers are found with `find_spec`.
  - **pip's dry run** would install `motmetrics-1.4.0` and nothing else.
- **Rejected alternatives:**
  - **PyPI's `trackeval`** is a third-party fork of the official TrackEval (1 star), and pulls in `opencv-python`,
    a second OpenCV.
  - **The official TrackEval** has had no commits since 2022-11-29.
- **`util/validate_tool_sources.py`** is the 2026-11-20 ad-hoc validator, promoted to `util/`. It gained options
  for checking a single candidate.
- **Ultralytics downloads a font when training.** It fetches `Arial.ttf` from its GitHub assets unless an Arial
  font is installed, and none is installed here. `flocker.detector.use_bundled_font()` points it at matplotlib's
  DejaVu Sans instead, so nothing is downloaded.

## TeamTrack facts the code relies on

These were checked against all 60 sequences. `tests/test_teamtrack.py` pins them (integration tests).

- **The clips:** 3840 x 2160 at 29.97 fps, 900 frames each, H.264. The splits are 42 train, 9 val and 9 test
  sequences.
- **The ids:** every sequence has the 23 ids 0..22. 0-10 are TeamID 0, 11-21 are TeamID 1 and 22 is the BALL.
  This was found by matching each frame-1 MOT box to the CSV's team columns.
  - Some frames hold only 21 or 22 objects, when a player or the ball is out of view.
- **Who is labelled:** referees, assistant referees and people off the pitch are not. A generic person detector is
  charged false positives for them, while a detector trained on TeamTrack learns to ignore them.
- **Box size:** a player's box is a median 32 x 32 px (min 14, max 60). The boxes are loose by a few pixels, which
  caps HOTA at the strictest IoU thresholds for any tracker.
- **Six train sequences have labels that drift in time:** `0570_0600`, `0600_0630`, `0630_0660`, `0660_0690`,
  `0690_0720` and `0720_0750`.
  - Their ground truth runs to frames 903-906, past their 900-frame videos (`seqinfo.ini` says 900).
  - Their boxes are aligned at frame 1 but lead the players by several frames at frame 900, as if 906 annotated
    frames were stretched over 900. This was seen on crops of the fastest players
    (`D_20220220_1_0630_0660`; `tmp/2026-11-24_teamtrack-look/align_*.png` in the worktree).
  - `load_gt()` clips frames past `seqlength`, and `build-dataset` leaves these six sequences out unless asked.
- **No shadows:** the day is overcast. Shadow handling has to be tested on the stock clips.
- **The camera barely moves.** Measured by phase correlation on frames downscaled to 960 x 540, and given in
  full-resolution pixels:
  - within a clip, frame 900 is at most about 9 px from frame 1;
  - across the match, each clip's frame 1 is within about 12 px of the first clip's.

  At about 37 px per metre, that is about 0.3 m, so one image-to-pitch homography could serve every clip.

## The evaluation harness (`src/flocker/evaluate.py`)

- **The metrics:**
  - **HOTA, DetA and AssA** are means over TrackEval's 19 thresholds, α = 0.05 ... 0.95.
  - **CLEAR-MOT** (MOTA, MOTP, FP, FN, IDSW, Frag, MT/PT/ML) and **IDF1** use IoU ≥ 0.5.
  - **MOTP** is reported as the mean IoU of matches; motmetrics itself reports 1 − IoU.
- **The overall row** is built from summed per-sequence counts, by TrackEval's rules:
  - per threshold, DetA = TP / (TP + FN + FP);
  - AssA is the TP-weighted mean of each sequence's AssA;
  - HOTA = √(DetA · AssA).

  Sequences are scored in parallel processes, so the 9 test sequences (178,155 player boxes) take about a minute
  with HOTA. Scoring the ground truth against itself gives 100 % on every metric for all nine.
- **py-motmetrics' HOTA assumes 1-based, contiguous ids.**
  - **What goes wrong:** its global-alignment matrix is sized by the largest id and indexed with `id − 1`.
    TeamTrack's id 0 indexes −1, which wraps onto the largest id, so two objects' alignment statistics merge.
    That changes which detection each object is matched to whenever similarity alone would choose wrongly.
  - **The workaround:** every id is relabelled to 1..N before scoring. The metrics depend on ids only through
    equality, so this changes nothing else.
  - **The proof:** `tests/test_evaluate.py::test_zero_based_ids_need_relabelling` builds such a scene. Raw
    motmetrics scores it differently with ids (0, 2) than with (1, 3); the wrapper scores both the same. If
    upstream ever fixes this, that assertion fails, and the relabelling can go.
- **How it was validated:**
  1. **Hand-computed cases:**
     - **Perfect tracking** scores 1.
     - **A track split into two ids** gives HOTA √0.5, MOTA 0.75 and IDF1 0.5.
     - **IoU 0.4286 in every frame** gives HOTA 8/19 (8 of the 19 thresholds accept it), and no CLEAR match at
       0.5.
     - **Misses and false positives** also have hand-computed expectations.
     - **The overall row** equals motmetrics' own `compute_many(generate_overall=True)`.
  2. **Mutations of the code are caught:**
     - **no id relabelling:** 4 tests fail;
     - **MOTA without IDSW:** 2 tests fail;
     - **AssA weighted per sequence instead of per TP:** 2 tests fail.
  3. **Perturbed real ground truth** (`tests/test_evaluate_teamtrack.py`, two test sequences, 39,555 player boxes):
     - **the truth itself** scores 1;
     - **dropping every 10th row** gives exactly FN = the number dropped, DetA = kept/GT and
       AssA = Σ m²/g ÷ Σ m;
     - **swapping two players' ids half-way** gives IDSW = 2 and IDF1 = 1 − 900/GT;
     - **shifting boxes 1 and 3 px** lowers MOTP and HOTA but not MOTA.

## Off-the-shelf detector: COCO YOLO11n

Tried on frame 1 of `D_20220220_1_1530_1560` (test split), counting the 22 ground-truth players matched at
IoU ≥ 0.5:
- **at `imgsz` 1920:** 1 person detection, at confidence 0.09, and 0 players matched;
- **at `imgsz` 3840:** 27 person detections, all at confidence 0.29 or below, and 2 players matched.

A COCO "person" is seen from the side, while these players are seen from above, at about 30 px. A detector has to
be trained on top-down data.

## Detector: YOLO11n fine-tuned on full-resolution tiles

- **Why tiles:** downscaling a 4K frame to a usual training size would shrink players to a few pixels. Instead,
  `build-dataset` cuts frames into 1280 px tiles at full resolution, overlapping by at least 256 px. That is
  4 × 2 tiles per frame.
  - A box is labelled in a tile when at least half of it is inside.
  - At inference, YOLO runs on whole frames at `imgsz` 3840, the same scale (it is fully convolutional).
- **The data:**
  - **train:** every 30th frame of the 36 aligned train sequences: 1,080 frames, 8,640 tiles (684 empty),
    49,204 player and 1,918 ball labels;
  - **val:** every 90th frame of the 9 val sequences: 720 tiles, 4,138 player and 162 ball labels;
  - built in 2 min 39 s, 3.8 GB.
  - Sample tiles were checked by eye: boxes sit on players, and the assistant referees and the people off the
    pitch are unlabelled.
- **The training:**
  - **start and length:** COCO YOLO11n (`resources/models/yolo11n.pt`, sha256 `0ebbc80d…`), 30 epochs,
    batch 8, `imgsz` 1280;
  - **optimiser:** AdamW, which Ultralytics chose automatically;
  - **augmentation:** `flipud` 0.5 (the view is top-down), `scale` 0.25 and no rotation.
  - It ran at about 3.5 min per epoch on the RTX 2080, using 4.8 GB.

## Tracking (`src/flocker/track.py`)

- **Detection runs once per video** and is cached as `detections/<seq>.txt`, so trackers can be tuned in seconds.
  A reader thread decodes frames while the GPU runs.
- **Classes are mapped from the model's names:** `player`/`person` → player and `ball`/`sports ball` → ball.
- **Each class gets its own Ultralytics tracker instance**, so the ball cannot take over a player's identity.
  Ball ids are offset by 100,000.
  - No images are passed to the trackers, so BoT-SORT runs without camera-motion compensation; the camera barely
    moves anyway.
- **`--box-source track`** reports the tracker's Kalman-filtered boxes, which is what Ultralytics' `model.track()`
  does. **`--box-source detection`** reports the raw detection behind each track instead.
  - Ultralytics' `idx` column cannot be used to find that detection: it counts within the high-score and
    low-score subsets, not the whole frame. So the box is matched by IoU instead.
- **`eval` reads `run.json`** and, for a `--max-frames` run, scores only the frames that were processed.

## Dots and speed-up (`src/flocker/render.py`): the owner's edits 2 and 5

- **What `dots` draws:** each tracked object as a dot.
  - **Colours:** for ground truth, by team (red for ids 0-10, blue for 11-21); the ball is yellow. Tracker
    output carries no team, so its dots are white.
  - **Trails** are optional.
- **What it draws on:**
  - **`--background median`:** the per-pixel median of 45 frames spread over the clip. The camera is static, so
    this is the pitch with the players erased; moving shadows would vanish the same way. The players are
    replaced, not covered.
  - **`--background frame`:** the original video.
- **Speed-up** keeps every Nth frame at the source frame rate, so an N x clip plays smoothly. The output is
  H.264, written by the environment's ffmpeg.
- **The first clip:** the ground truth of `D_20220220_1_1530_1560` at 4x, written to
  `videos/edit/2026-11-24_teamtrack-dots/` (ignored).
  - 1920 x 1080, 225 frames, 7.5 s, 0.9 MB, made in 113 s.
  - Checked by eye:
    - on the median background, the pitch is clean, apart from faint near-static people beyond the bottom line;
    - on a zoomed crop of frame 1 drawn over the video, each dot covers its player, with only limbs showing;
    - the unlabelled referee gets no dot.
- **Tests** (`tests/test_render.py`): the median erases a moving square; 4x keeps frames 1, 5, 9, ...; the dot
  lands on the object.

## Results (test split: 9 sequences, 8,100 frames, 178,155 player boxes)

**The detector.** Training took 85 min; epoch 28 was best on the 720 val tiles:

| Class | Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| player | 0.801 | 0.835 | 0.797 | 0.272 |
| ball | 0.861 | 0.846 | 0.849 | 0.365 |

The weights are archived as `resources/models/flocker_yolo11n_teamtrack-tiles1280-e30_2026-11-24.pt` (gitignored;
sha256 `84c9bce7…`). Detection ran at `imgsz` 3840, FP16, batch 2: 16-20 frames per second, so the whole test
split took 8.4 min, tracking included.

**Tracking, players:**

| Tracker, scoring | HOTA | DetA | AssA | MOTA | MOTP | IDF1 | Rcll | Prcn | IDSW | Track ids (198 true) |
|---|---|---|---|---|---|---|---|---|---|---|
| ByteTrack, Kalman boxes, IoU ≥ 0.5 | 48.0 | 56.0 | 41.6 | 60.9 | 67.0 % IoU | 59.3 | 80.0 | 81.0 | 592 | 773 |
| the same, without `1770_1800` | 49.6 | 58.6 | 42.2 | 73.3 | 67.5 % IoU | 64.3 | 86.2 | 87.3 | 529 | 683 |
| ByteTrack, raw detection boxes, IoU | 47.9 | 55.9 | 41.5 | 60.5 | 66.9 % IoU | 59.0 | 79.8 | 80.8 | 614 | 774 |
| BoT-SORT (no GMC or ReID), IoU | 48.9 | 56.2 | 42.9 | 61.2 | 66.9 % IoU | 60.6 | 80.3 | 81.0 | 496 | 682 |
| ByteTrack, centres ≤ 15 px (about 0.5 m) | - | - | - | **96.4** | 4.3 px | 71.6 | **97.8** | **98.9** | 573 | 773 |

1. **Positions are good, which is what the dots need.** Matching centres within 15 px:
   - recall is 97.8 % and precision 98.9 %;
   - the mean centre error is 4.3 px, about 0.15 m;
   - all 198 true tracks are mostly tracked;
   - false positives come to 0.23 a frame, so the detector learned to ignore the referees, as its labels do.
2. **IoU scores understate the detector**, because box size is an annotation convention.
   - `D_20220220_1_1770_1800`'s ground truth is drawn with boxes of median 42 x 40 px, against 24-39 px in every
     other val and test sequence, while the detector draws about 28 x 28 everywhere.
   - The positions agree: the median distance from a ground-truth centre to the nearest detection is 3-5 px at
     frames 1, 300, 600 and 900.
   - But a centred 28 x 28 box has IoU 0.47 inside a 42 x 40 one, so CLEAR counts each such detection as a miss
     plus a false positive. That sequence alone scores MOTA −38.6.
   - Across all sequences, MOTP is only 67 % IoU.
3. **Identity is the weak point.**
   - Tracks break and restart: 773 track ids for 198 players, about 570-600 identity switches, and IDF1 59-72.
   - BoT-SORT, still without camera-motion compensation or ReID, is slightly better: 496 switches, 682 ids,
     HOTA 48.9.
   - Kalman-filtered and raw boxes make no difference.
4. **The ball is not tracked usefully:** HOTA 10.7, recall 31 % by IoU and 41 % by centre, precision 44-57 %. A
   small, fast object needs more than IoU association.
5. **A look at the frames:** tracker output for `D_20220220_1_1530_1560` was drawn as dots over the video at 4x
   (`videos/edit/2026-11-24_teamtrack-dots/`). On a zoomed crop around frame 481:
   - the dots sit on the players;
   - the referee gets none;
   - one player on the halfway line is missed;
   - several trail-less dots are newly started tracks, the fragmentation counted above.

**Next:**
- **Identity:**
  - tune the trackers (`track_buffer`, thresholds);
  - run BoT-SORT with images, for camera-motion compensation and ReID;
  - try team-colour-aware association;
  - try a larger detector.
- **The ball:** a dedicated detector and tracker.
- **The camera angle (edit 4):** a homography, which would also put the 15 px threshold in metres.

## Reproduce

```bash
E=~/Development/python/Flocker/tmp/2026-11-24_teamtrack-eval
P="conda run -n Flocker python bin/flocker.py"
$P build-dataset --out $E/datasets/tiles1280_e30
$P train --data $E/datasets/tiles1280_e30/data.yaml --model ~/Development/python/Flocker/resources/models/yolo11n.pt \
    --project $E/runs --name yolo11n_tiles1280_e30 --epochs 30 --batch 8
$P track --model $E/runs/yolo11n_tiles1280_e30/weights/best.pt --split test --out-dir $E/tracks/yolo11n_e30_bytetrack
$P eval --pred-dir $E/tracks/yolo11n_e30_bytetrack --split test --out $E/tracks/yolo11n_e30_bytetrack/eval_players.csv
$P eval --pred-dir $E/tracks/yolo11n_e30_bytetrack --split test --max-dist 15          # centre matching
$P eval --pred-dir $E/tracks/yolo11n_e30_bytetrack --split test --objects ball
# variants from the cached detections (copy detections/ into the new folder first):
$P track --split test --out-dir $E/tracks/yolo11n_e30_botsort --reuse-detections --tracker botsort
$P dots --sequence D_20220220_1_1530_1560 --tracks $E/tracks/yolo11n_e30_bytetrack/D_20220220_1_1530_1560.txt \
    --out videos/edit/2026-11-24_teamtrack-dots/tracker_dots_4x.mp4 --background frame --trail 6
```
