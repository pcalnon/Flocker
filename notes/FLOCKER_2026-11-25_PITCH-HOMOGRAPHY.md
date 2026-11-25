# The image-to-pitch homography: positions in metres, and the camera angle corrected (edit 4)

**Date**: 2026-11-25
**Scope**: the owner's edit 4, "correct the camera angle (a homography)", on TeamTrack's top view. Every frame gets a
map from image pixels to pitch metres, and positions, speeds and the 15 px matching threshold are put in metres. Builds
on `notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md` and `notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md`.
**Code**: `src/flocker/pitch.py` (new), `src/flocker/render.py`, `src/flocker/cli.py`, `src/flocker/teamtrack.py`,
`src/flocker/evaluate.py`, `tests/test_pitch.py` (new), `util/ad-hoc/2026-11-25_pitch_study.py` (new)
**Outputs** (gitignored): the primary checkout's `tmp/2026-11-25_homography/`. It holds `pitch/` (a homography per frame
for all 60 clips), `study/` (the tables and plots below) and `look/`. The renders are in `videos/edit/2026-11-25_pitch-view/`.

## Summary

- **The pitch is a regulation 105 x 68 m.** The fit was run on frame 1 of all 60 clips with the size left free. It gives
  105.018 ± 0.002 m by 67.955 ± 0.002 m, measured to the lines' outer edges.
  - Only the markings inside the field fix the scale: the penalty and goal areas, the arcs and the centre circle.
  - The touchlines and goal lines then land on the regulation size by themselves.
- **The fit is sub-pixel.**
  - **The lines:** the painted lines' centres sit 0.39 px RMS from the fitted markings, about 1.4 cm.
  - **The marks:** the fit never sees the centre mark or the penalty marks. They lie 0.4-1.2 px from where it puts
    them (1.4-4.1 cm, medians over 60 clips).
- **The scale is 27.9 px per metre** in the middle of the pitch, and 27.3-28.7 across it, because the camera is tilted
  about 2°.
  - The harness note's "about 37 px per metre" was wrong; the earlier handoff's 28 was right.
  - The 15 px matching threshold is 0.52-0.55 m. The detector's mean centre error of 4.3 px is 0.15 m.
- **The camera moves, and the pitch must be followed frame by frame.** The drone yaws by up to 4.9° within a 30 s clip
  (median 0.5°) and drifts.
  - **How far:** a pitch corner moves up to 80 px in the image (about 2.9 m); the median clip's worst is 17 px.
  - **The answer:** `track_pitch` refits every frame, from the previous frame's fit, at 12-16 frames per second.
  - **The result:** across all 54,000 frames, the lines stay 0.39 px RMS from the markings (clip medians), with no
    restarts and no failures.
  - **The alternative fails:** one homography per clip would misplace positions by up to 3.0 m. It would also add
    false velocities of up to 4.7 m/s.
  - The harness note's "at most about 12 px" came from phase correlation, which measures translation and cannot see a
    rotation.
- **Speeds in metres look like football.** Ground-truth outfield players reach 5.2 m/s (median top speed per 30 s clip;
  95th percentile 7.4, fastest 10.0). They cover 136 m per minute (median), a ball-in-play running rate.
- **Tracking scored in metres agrees with pixels:** at 0.54 m the test split scores MOTA 99.2 and IDF1 97.3, with 36
  identity switches, and a mean centre error of 0.15 m.
- **Positions are box centres on the ground plane, not feet.**
  - **The bias:** the camera is about 100 m up, so a box centre, about 1 m above the grass, lands about 1 % of its
    distance from the camera's nadir too far out. That is about 0.45 m at a goal line.
  - **Why it is not corrected:** within a frame it is a near-uniform 1 % scaling, which distances, speeds and
    alignments barely notice. The altitude is not known well enough (±15 %) to correct it.
- **Edit 4 renders:** `dots --view pitch` looks straight down onto the pitch, with the drone's motion removed. Players,
  tracks or ground truth are drawn there as dots.

## The pitch template (`flocker.pitch.markings`)

- **Coordinates:** metres, with the origin at the centre mark.
  - x runs along the touchlines toward the goal on the right of the video.
  - y runs across the pitch toward the bottom of the video. A top-down drawing with y downward therefore looks like the
    video.
  - Seen from above, this frame is left-handed: an angle measured from x toward y turns clockwise as seen in the video.
- **The markings** follow IFAB Law 1:
  - the touchlines, goal lines and halfway line;
  - the centre circle (9.15 m);
  - the penalty areas (16.5 m deep, 40.32 m wide) and goal areas (5.5 m, 18.32 m);
  - the penalty arcs (9.15 m about the penalty marks, 11 m out);
  - the corner arcs (1 m), which are drawn but not fitted.
- **Lines belong to the areas they bound,** so every distance runs to a line's outer edge. The template holds each
  line's centreline, 6 cm inside: half the 12 cm maximum width. The painted lines measure 4-5 px, about 15 cm with
  blur.
- **The length and width are parameters.** A field may measure 90-120 m by 45-90 m, but the markings inside it are
  fixed. So the fit can measure the size.

## The fit (`flocker.pitch.fit_pitch`)

1. **A response image in which lines are bright.**
   - For a single image: a white top-hat of the lightness channel, with a 15 px disc.
   - For tracking: plain grey levels, which locate the lines to within 0.035 px of the top-hat, at 1/30 of its cost
     (8 ms for a 4K frame).
2. **Observations.**
   - The template is projected into the image with the current homography.
   - Along each marking, every 0.5 m, the response is read across the marking, within ±S px, at 0.5 px steps.
   - The profile's median is subtracted. A peak rising 12 or more above the median, at least 3 px inside the window, gives
     an observation: the response's centroid within 3 px of the peak.
   - Points within 1 m of another marking, or within 1.5 m of a goal mouth, are not searched. There the posts, nets and
     goalkeepers cover the line.
   - That leaves about 1,215 observations per frame.
3. **A robust fit.** Least squares adjusts the homography's eight parameters, and the length and width if asked. The
   loss is soft-L1 with a 5 cm scale, and it acts on each observation's signed distance from its marking, in metres,
   after mapping the observation to the pitch.
   - Players standing on lines are outliers that the loss ignores: masking the ground-truth boxes out changed the fit by
     0.03 px.
4. **Rounds:** search windows of 24, 12, 8, 6 and 6 px, from a start of four corners read by eye off one clip's median
   background (`flocker.teamtrack.PITCH_CORNERS_PX`).
   - The first round moves the fit about 3 px; the later ones move it under 0.1 px.
   - `tests/test_pitch.py` starts a synthetic pitch from corners 15-20 px off. It recovers a known homography to 0.25 px
     everywhere, and a pitch size of 104 x 67 m to 5 cm.
5. **Tracking (`flocker.pitch.track_pitch`):** each frame starts from the previous frame's fit, with one ±8 px search
   at the pitch size already measured. If a frame gives under 300 observations, or an RMS over 1.5 px, it is refitted
   from the clip's reference fit with 24, 12 and 8 px searches.

The first run on the median background of `D_20220220_1_1260_1290` gave 104.99 x 67.96 m at RMS 0.61 px. Its residuals
were larger and patterned on the left of the pitch, where some lines looked doubled. A median of 45 frames from a moving
camera blends two positions: in that clip the drone yawed 0.8° and back (below). Single frames fit better, at RMS 0.39
px, so every measurement below uses single frames.

## Size and accuracy: frame 1 of all 60 clips, size free (`study/size_frame1.csv`)

| Measure | Mean | Std | Min | Max |
|---|---|---|---|---|
| Length, m | 105.018 | 0.002 | 105.014 | 105.022 |
| Width, m | 67.955 | 0.002 | 67.949 | 67.958 |
| Line RMS, px | 0.389 | 0.007 | 0.378 | 0.407 |
| Observations | 1,214 | 1.1 | 1,211 | 1,216 |
| Scale at the centre mark, px/m | 27.93 | 0.04 | 27.85 | 28.01 |

- **The size is a regulation 105 x 68 m.** The 2-5 cm differences are within what the assumed line width and the lens
  allow (below).
  - Tracking uses 105.01 x 67.96 m (`flocker.teamtrack.PITCH_SIZE_M`), measured with the first version of the
    centroid. The final version moved the measurement by under 1 cm.
- **The first version of the fit** was reviewed independently, and six bugs were fixed. Only one changed fitted
  homographies: a centroid window that clipped wide lines, which moved them by at most 0.11 px. All the numbers here
  come from the final code.
- **The marks were held out.** `find_spots` takes the centroid of the brightest small blob near where the fit puts each
  mark:

  | Mark | Median error, px | Median error, cm | Range over 60 clips, px |
  |---|---|---|---|
  | Penalty mark, left | 0.74 | 2.7 | 0.64-0.87 |
  | Penalty mark, right | 0.40 | 1.4 | 0.27-0.49 |
  | Centre mark, along the halfway line only | 1.15 | 4.1 | 0.85-6.9 |

  - Each mark's error is nearly the same in every clip, so it shows where the mark is painted, not noise.
  - The centre mark sits on the halfway line, which the fit uses. So it is measured along the line only, with the
    line removed from the response first. Otherwise the line's pixels pull its centroid back to the prediction:
    `tests/test_pitch.py` shows a 4 px error along the line that a plain centroid misses.
  - The centre mark's 6.9 px is a frame in which a player or the ball stands on it.
- **What is left is a small lens distortion.** In a single frame, the ends of all four boundary lines sit 1-1.7 px
  outward of the fitted lines, near the frame's corners. That is a mild pincushion distortion that a homography
  cannot model: at most about 6 cm, at the pitch corners. The centre circle sits about 0.8 px (3 cm) off-centre.
  Both are left uncorrected.
- **The camera is tilted about 2°.** The scale runs from 27.3 px/m near the bottom-left corner to 28.7 px/m near the
  top-right. Decomposing the homography gives a tilt of about 1.8°. For a camera this close to vertical, the
  decomposition cannot give a reliable focal length or altitude: its two constraints disagree, at 2,800-3,360 px
  against 1,160-1,400 px.

## Scale, and the 15 px threshold in metres

- **27.9 px per metre** in the middle: the harness note's "about 37" was wrong, and the earlier handoff's "about 28" was
  right.
- **15 px**, the centre-matching threshold, is **0.52-0.55 m** across the pitch (0.54 m in the middle).
- **The detector's mean centre error,** 4.3 px, is **0.15 m**.

## Parallax: what the homography does not correct

- **The homography maps the ground,** but a player's box centre is not on the ground. Seen from nearly straight above,
  a standing body projects away from the camera's nadir.
- **The ground-truth boxes show it.** Along x, the median box width grows from about 1.1 m in the middle to 1.45-1.6 m
  at the goal lines. Along y, the median box height grows from about 1.07 m to 1.2-1.3 m at the touchlines
  (`study/boxes.csv`, `study/boxes.png`).
- **The altitude is about 100 m, but only to ±15 %.**
  - For the DJI Mavic 3's lens at 4K (about 2,730 px focal length), 27.9 px/m means about 98 m.
  - The corner flags lean outward by 20-27 px, which gives 99-136 m depending on the flag.
  - The goal crossbars (2.44 m high) could pin the altitude, but that was not done.
- **The effect:** a box centre is about 0.9 m up, so it lands z/h, about 0.9 %, of its distance from the nadir too far
  out. That is about 0.45 m at a goal line and 0.2 m at 20 m from the middle. The nadir is within a few metres of the
  centre mark: the boxes are smallest there.
- **It is not corrected.**
  - Within a frame, the shift is a near-uniform 0.9 % scaling about the nadir. Distances between players, speeds and
    the alignment of headings change by under 1 %.
  - Absolute positions near the goals are off by up to about half a metre.
  - A correction needs the altitude, which is known only to ±15 %.

## The camera moves (`study/motion.csv`, `study/motion_match.png`)

The `pitch` command followed all 60 clips frame by frame: 54,000 frames, with no restarts and no failed frames.

| Per clip | Median | Max |
|---|---|---|
| Largest shift of a pitch corner from frame 1, px | 17 | 80 (`0000_0030`) |
| Largest shift of the centre mark from frame 1, px | 6.5 | 13.7 |
| Yaw range, degrees | 0.49 | 4.95 (`0000_0030`) |
| One homography per clip: worst position error, m | 0.47 | 3.0 |
| One homography per clip: 95th-percentile error, m | 0.31 | 2.4 |
| Line RMS, px (median frame) | 0.394 | 0.406 |
| Line RMS, px (worst frame) | 0.48 | 1.00 |
| Fewest observations in a frame | 1,209 | (min 521) |

- **The yaw is what matters.**
  - The centre of the image moves little, at most 14 px, but a rotation of a few degrees moves the pitch's corners by
    tens of pixels.
  - Phase correlation, which the harness note used, measures translation only, so it reported "at most about 12 px".
  - Across the match, frame 1 of each clip is up to 57 px from the match's first frame.
- **When it happens:**
  - the drone settles during the first two minutes;
  - its largest turns are at about 18 minutes (`1080_1110`, 3.6°) and at the start (`0000_0030`, 4.9°);
  - short jerks come at about 10, 12, 22 and 28 minutes.
  - Corrections can be fast: in `1260_1290`, a corner moves 15 px in frames 75-82.
- **Hard frames:** the clips with the largest turns have a few frames with fewer observations, where part of the pitch
  leaves the frame or the lines blur. `0000_0030` has 17 frames under 1,150, the fewest being 521; their RMS stays at
  1.0 px or below.
- **The cost of ignoring it:** for a ground-truth player track, one homography per clip (frame 1's) would add a false
  velocity of up to 0.28 m/s (median track), 1.7 m/s (95th percentile) and 4.7 m/s (worst).
  - That is a uniform rotation of the whole pitch, so it would add a spurious common turn to every player. That is
    exactly what a flocking measure of alignment would pick up.

## Speeds in metres (`study/speeds.csv`)

- **The tracks:** ground-truth players, through each frame's homography, in 54 clips. The six train clips whose labels
  drift in time are excluded.
- **The smoothing:** whole, gap-free tracks only, smoothed with a 0.5 s Savitzky-Golay filter (15 frames, quadratic),
  because box corners are whole pixels.

| Outfield players, per 30 s track (1,074 tracks) | Median | 95th percentile | Max |
|---|---|---|---|
| Top speed, m/s | 5.2 | 7.4 | 10.0 |
| Mean speed, m/s | 2.2 | 3.3 | 4.2 |
| Distance per minute, m | 136 | 199 | 251 |

- **The scale is right.**
  - Top speeds of 7-10 m/s are sprints.
  - 136 m per minute is high for a whole match (typically 100-120), but those figures include stoppages; running rates
    while the ball is in play are of this size.
- **The distance is not noise.**
  - The raw positions jitter by about 1.2 cm per frame.
  - On four clips, the distance per minute was 145, 143, 142 and 141 m with 5-, 15-, 31- and 61-frame windows.
- **The ground truth has at least one jump.** Goalkeeper id 0 of `D_20220220_1_0180_0210` jumps 7 m between frames 300
  and 301, from behind the goal line to the goal line, and stays there. Its "top speed" of 22 m/s is that jump.

## Tracking scored in metres

`eval --pitch-dir ... --max-dist-m M` maps both box centres to the pitch with each frame's homography and matches them
within M metres. It was run on the test split, players, with the identity note's tracks (`tmp/2026-11-24_identity/tracks/test/flocker_teams`):

| Matching | MOTA | MOTP | IDF1 | IDSW | FP | FN |
|---|---|---|---|---|---|---|
| Centres within 15 px (identity note) | 99.1 | 4.3 px | 97.3 | 36 | 571 | 915 |
| Centres within 0.54 m on the pitch | 99.2 | 0.15 m | 97.3 | 36 | 541 | 885 |
| Centres within 0.50 m on the pitch | 98.7 | 0.15 m | 97.1 | 36 | 925 | 1,269 |

15 px is 0.52-0.55 m across the pitch, so 0.54 m reproduces it.

## Edit 4: the camera angle corrected (`videos/edit/2026-11-25_pitch-view/`)

`dots --pitch-dir DIR --view pitch` draws straight down onto the pitch through each frame's homography. The camera's
tilt is corrected, and its drift and yaw are removed, so the pitch stands still. Backgrounds: `median` is the median of
the warped frames, an empty and steady pitch; `frame` is the warped video; `pitch` is a drawn pitch. `--lines` draws
the fitted markings.

- `yaw_1260_1290_image_lines_1x.mp4` and `yaw_1260_1290_pitch_lines_1x.mp4`: frames 1-150 of the clip whose drone turns
  back by 0.8°, as filmed and from above, with the markings.
  - **Checked on frames 1 and 100:** the markings sit on the painted lines in both.
  - As filmed, the corner moves about 16 px; from above, it stays put.
- `flocker_teams_1530_1560_pitch_4x.mp4`: the identity note's tracks in team colours on the steady empty pitch, at 4x.
  The goalkeepers are white (neither team).
- `gt_1530_1560_drawn_pitch_4x.mp4`: the ground truth on a drawn pitch, at 4x.
  - **Checked on frame 241:** the dots match the tracks' positions.
- A shrinking warp is made at k times the size and reduced by area averaging (`flocker.pitch.warp_area`), because
  OpenCV's `warpPerspective` silently treats `INTER_AREA` as bilinear and would alias the lines.

## Changes

- **`flocker.pitch` (new):**
  - **the template:** `markings` and `spots`;
  - **the fit:** `line_response`, `grey`, `observe` and `fit_observations`, wrapped by `fit_pitch`;
  - **frame by frame:** `track_pitch`, `interpolate_homographies` and `camera_motion`;
  - **conversions:** `to_pitch_coords` and `with_pitch_positions` (box centres in metres);
  - **checks:** `find_spots` and `residual_table`;
  - **views:** `draw_markings`, `pitch_canvas`, `warp_area` and `rectify`.
- **`flocker.teamtrack`:** `PITCH_SIZE_M` and `PITCH_CORNERS_PX`.
- **`bin/flocker.py`:**
  - **new `pitch` command:** it writes `<seq>.csv` (a homography per frame), `<seq>.json` (frame 1's fit, its
    residuals by marking, the marks and a motion summary) and `overlays/<seq>.jpg`;
  - **`eval`:** `--pitch-dir` and `--max-dist-m`;
  - **`dots`:** `--pitch-dir`, `--view pitch`, `--background pitch` and `--lines`.
- **`flocker.render`:**
  - **a `View` class:** the image or the pitch, each with a transform per frame;
  - **`median_background`:** reads sequentially and through the view.
- **`flocker.evaluate`:** `format_table` takes a unit for MOTP (pixels or metres).
- **Tests:** 56 pass, 48 of them unit; there were 42, 36 unit.
  - **New:** `tests/test_pitch.py`, and a pitch-view test in `tests/test_render.py`.
  - **Every new check was seen to fail:** `util/ad-hoc/2026-11-25_pitch_mutations.py` breaks the code 13 ways, in a
    copy under `tmp/`, and the unit tests catch all 13.

## Next

1. **The flocking analysis,** now in metres: team-wise polarisation, cohesion and nearest-neighbour structure, from the
   ground truth first, then the tracks. Use `flocker.pitch.with_pitch_positions` with each clip's `<seq>.csv`.
2. **Parallax, if absolute positions matter:** measure the altitude from the goals' crossbars (2.44 m), then move box
   centres toward the nadir by z/h.
3. **The lens:** a one-parameter radial distortion would remove the 1-1.7 px at the frame's corners.
4. **Team colours:** `flocker.team.clip_background` assumes a static camera. Its median blurs at the pitch's edges,
   where the camera turns most. A background warped through the homographies would be sharper.
5. **The stock clips** (edit 4 there, and edit 1): they move and see only part of a pitch, so they would need a
   keypoint detector or a hand start per clip.

## Reproduce

```bash
S=~/Development/python/Flocker/tmp/2026-11-25_homography
I=~/Development/python/Flocker/tmp/2026-11-24_identity
P="/opt/miniforge3/envs/Flocker/bin/python -I"
export OMP_NUM_THREADS=1
$P bin/flocker.py pitch --split train val test --out-dir $S/pitch --jobs 5         # about 25 min on 16 cores
$P util/ad-hoc/2026-11-25_pitch_study.py size --out $S/study
$P util/ad-hoc/2026-11-25_pitch_study.py motion --pitch-dir $S/pitch --out $S/study
$P util/ad-hoc/2026-11-25_pitch_study.py boxes --pitch-dir $S/pitch --out $S/study
$P util/ad-hoc/2026-11-25_pitch_study.py speeds --pitch-dir $S/pitch --out $S/study
$P bin/flocker.py eval --pred-dir $I/tracks/test/flocker_teams --split test --pitch-dir $S/pitch --max-dist-m 0.54
$P util/ad-hoc/2026-11-25_pitch_mutations.py --work $S/mutations                    # 13 of 13 caught
V=videos/edit/2026-11-25_pitch-view
$P bin/flocker.py dots --sequence D_20220220_1_1260_1290 --pitch-dir $S/pitch --view pitch --background frame --lines \
    --speed 1 --max-frames 150 --out $V/yaw_1260_1290_pitch_lines_1x.mp4                # and --view image
$P bin/flocker.py dots --sequence D_20220220_1_1530_1560 --tracks $I/tracks/test/flocker_teams/D_20220220_1_1530_1560.txt \
    --pitch-dir $S/pitch --view pitch --background median --trail 6 --speed 4 --out $V/flocker_teams_1530_1560_pitch_4x.mp4
$P bin/flocker.py dots --sequence D_20220220_1_1530_1560 --pitch-dir $S/pitch --view pitch --background pitch --trail 6 \
    --speed 4 --out $V/gt_1530_1560_drawn_pitch_4x.mp4
```
