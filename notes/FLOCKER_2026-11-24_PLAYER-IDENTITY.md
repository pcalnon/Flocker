# Player identity: why tracks broke, and team labels from kit colour

**Date**: 2026-11-24
**Scope**: the first item of the identity work in
`prompts/thread-handoff_automated-prompts/HANDOFF_2026-11-24_teamtrack-evaluation-harness.md`: keep each player's
identity through a clip, and label each player's team. Builds on `notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md`
(the harness, the detector and the first tracking results).
**Code**: `src/flocker/track.py`, `src/flocker/team.py` (new), `src/flocker/evaluate.py`, `src/flocker/cli.py`,
`config/trackers/flocker_bytetrack.yaml` (new), `util/ad-hoc/2026-11-24_tracker_sweep.py`,
`util/ad-hoc/2026-11-24_team_colours.py`
**Outputs** (gitignored): the primary checkout's `tmp/2026-11-24_identity/` (val detections, colours, tracks, the
sweep tables `sweep_val.csv` and `sweep_test.csv`, logs) and `videos/edit/2026-11-24_identity-dots/`

## Summary

- **Most identity breaks were not hard cases.** With Ultralytics' ByteTrack defaults, 53 % of the identity switches
  on the test split were a track dying and a new one starting while the player was in plain view: the detector
  found the player in 99 % of the frames of each gap.
- **Two causes, which only matter together:**
  - **duplicate boxes:** the detection-time NMS (IoU 0.6) leaves a near-copy of the box on many players, at IoU
    0.54-0.60 with the original. These copies are as many as the true detections.
  - **an under-confident detector meeting score fusion:** true players score a median 0.40. ByteTrack's default
    cost, 1 − IoU × confidence below 0.8, then demands IoU > 0.6 from a player detected at 0.33.
- **The fix is settings, not a new tracker:** a second, stricter NMS at IoU 0.3, and ByteTrack without score fusion
  and with lower thresholds (`config/trackers/flocker_bytetrack.yaml`). It was chosen on the val split and scored
  once on test. On the test split, players, matching centres within 15 px:

  | Tracker | IDF1 | ID switches | Track ids (198 true) | MOTA | HOTA (IoU) | AssA (IoU) |
  |---|---|---|---|---|---|---|
  | ByteTrack, Ultralytics' defaults | 71.4 | 574 | 774 | 96.4 | 48.0 | 41.5 |
  | **Flocker's settings** | **97.3** | **36** | **235** | **99.1** | **58.3** | **59.5** |

- **Every Ultralytics tracker converges** once the detections are cleaned: ByteTrack, BoT-SORT, OC-SORT and Deep
  OC-SORT all score IDF1 98.3-98.8 on val. FastTrack scores 97.1 and TrackTrack 89.1.
- **Team labels from kit colour work:** the two kits are found in all 18 val and test clips, the goalkeepers are kept
  out of both teams, and 98.9 % (test) to 99.9 % (val) of matched outfield track rows carry the right team.
- **Gating association by team made identity worse** (val IDF1 95.4 against 98.8). A detection's colour is least
  reliable in a duel, exactly where gating would act, because its box takes in part of the opponent.

## Method

- **Tuned on val, scored on test once.** The harness note reported the default trackers on the test split, so
  tuning on test would flatter the result. Every setting here was chosen on the 9 val sequences. The test split was
  scored once, at the end, with the settings already fixed.
- **Detections were cached once per split** with the harness note's detector and settings:
  - **the detector:** `resources/models/flocker_yolo11n_teamtrack-tiles1280-e30_2026-11-24.pt`;
  - **the settings:** `imgsz` 3840, `conf` 0.05, NMS IoU 0.6, FP16.
  - Val took 8.4 min on the GPU. Test reuses the harness's cache.
  - Tracking replays a cache in about 5 s per sequence.
- **Scoring:**
  - **CLEAR-MOT and IDF1 twice:** centres within 15 px (the primary score, blind to box-size conventions) and
    IoU ≥ 0.5;
  - **HOTA** for the shortlist.
  - `flocker.evaluate.switch_events` (new) classifies every identity switch:
    - **restart:** the old id had ended, and the new id was born after the player's last match;
    - **swap:** the new id had been following another player;
    - **other:** anything else.
  - `tests/test_evaluate.py` pins all three on constructed cases.

## Diagnosis (test split, ByteTrack defaults, centres within 15 px)

All numbers come from the harness's existing test tracks and detections.

1. **The switches, by kind:** 573 in all.
   - **303 restarts (53 %).** A median 6 frames passed without a match (95th percentile 29). The new id appeared a
     median 24 px from where the old one ended (95th percentile 121 px).
   - **238 other (42 %).** These have no gap and overlapping lifetimes, and ids flip back and forth: two tracks on one
     player.
   - **32 swaps (6 %).** Half of them are in `D_20220220_1_1710_1740`.
2. **Who was nearby:**
   - **Swaps happen in contact.** 94 % had another player within 30 px (about 1 m), and that player was an opponent in
     93 % of those cases.
   - **Restarts and "other" happen in the open.** Only 18-19 % had anyone within 30 px; the median nearest player
     was 73 px and 120 px away. Over all players and frames, 3.6 % have a neighbour within 30 px.
3. **The players were detected.**
   - In the frames of each restart gap, a detection lay within 15 px of the player 99 % of the time (median 100 %).
   - Those detections' mean confidence was 0.33.
   - The tracker discarded them.
4. **The detector is under-confident.** Detections matched to a player have a median confidence of 0.40; 25 % score
   below 0.23 and only 21 % above 0.5. A confidence floor of 0.25, ByteTrack's `track_high_thresh`, keeps 74.5 %
   of true players.
5. **Half the detections are duplicates.** Sampling every 10th frame, there were as many unmatched detections
   (17,744) as matched ones (17,795).
   - Of the unmatched ones scoring 0.25 or more, 99.7 % lie within 30 px of a player, a median 5.8 px from it.
   - Their IoU with the player's matched detection is a median 0.57 (quartiles 0.54 and 0.59), just under the
     detection-time NMS threshold of 0.6.
   - They are near-copies of the player's box, not referees or spectators.
6. **The mechanism:**
   - With `fuse_score` on, ByteTrack's cost is 1 − IoU × confidence, and `match_thresh` 0.8 accepts it below 0.8. A
     detection at confidence 0.33 therefore needs IoU > 0.6 with the predicted box, which a moving 28 px box often
     misses.
   - The unmatched detection then starts a new track (a restart).
   - Meanwhile, the duplicate boxes start rival tracks on the same player (the "other" flips).

## The fix, tuned on val (players, 9 sequences, 178,115 boxes)

`util/ad-hoc/2026-11-24_tracker_sweep.py` holds every configuration, in stages; `sweep_val.csv` holds every row.

**Stage 0: each cause alone, and both** (`dedup` is the second NMS, `flocker.track.suppress_duplicates`):

| ByteTrack | IDF1 @15 px | IDSW | Ids | FP | FN | IDF1 IoU | HOTA | AssA |
|---|---|---|---|---|---|---|---|---|
| Ultralytics' defaults | 70.5 | 678 | 892 | 2,141 | 5,299 | 58.9 | 46.3 | 39.0 |
| score fusion off | 71.5 | 879 | 896 | 7,823 | 823 | 59.7 | - | - |
| dedup 0.45 | 72.7 | 645 | 808 | 719 | 7,419 | 60.6 | - | - |
| both | 96.4 | 38 | 240 | 1,007 | 962 | 79.4 | - | - |

- **Each change alone fails, because each exposes the other's problem:**
  - **without score fusion:** the low-confidence players can be matched, but the duplicates become rival tracks
    (7,823 false positives);
  - **with dedup alone:** the duplicates go, but score fusion still refuses the low-confidence players (552 restarts).

**Stages 1-3:**

- **The second NMS:** stricter is better, down to IoU 0.3.
  - **0.55:** IDF1 91.2;
  - **0.45:** 96.4;
  - **0.3:** 97.6;
  - **0.25:** 97.8;
  - **0.2:** 96.9, as real neighbours start being merged (FN 1,275 against 1,068 at 0.3).
  - **0.3 was kept:** at 0.25 the misses grow (FN 1,142) for a gain within noise.
- **The thresholds, one at a time, from dedup 0.3 with score fusion off (IDF1 97.6):**
  - **`track_high_thresh` 0.15:** IDF1 98.5;
  - **`match_thresh` 0.9:** IDF1 97.8;
  - **`new_track_thresh`:** 0.35 has fewer ids, while 0.45 delays real births (FN 4,065);
  - **`track_buffer`:** 60, 150 and 900 change nothing. After a gap, the predicted box no longer overlaps the
    player, so IoU fails whatever the buffer.
- **The chosen settings** are dedup 0.3, then ByteTrack with `fuse_score` False, `track_high_thresh` 0.15 and
  `match_thresh` 0.9: IDF1 98.8, 34 switches, 227 ids, HOTA 58.3, AssA 59.9.
  - Adding `new_track_thresh` 0.35 gives 27 switches and 218 ids at IDF1 98.6 and HOTA 58.1, which is within noise.
  - The settings are in `config/trackers/flocker_bytetrack.yaml`.
- **Other trackers, with dedup 0.3 and score fusion off:**
  - **BoT-SORT** (still without images, so no camera-motion compensation or ReID): 98.5;
  - **OC-SORT:** 98.3;
  - **Deep OC-SORT** (no ReID): 98.4;
  - **FastTrack:** 97.1;
  - **TrackTrack:** keeps almost nothing at its own defaults, because only about 10 % of true players score above
    its 0.6 threshold. Its best, with ByteTrack-like thresholds, is IDF1 89.1 with 95 restarts.
  - **`track_detections` no longer calls `reset_id()` on TrackTrack**, which has no such method and needs none.

## The fix on test (scored once, settings fixed)

Players, 9 sequences, 178,155 boxes (`sweep_test.csv`; the `final` stage):

| Tracker | IDF1 @15 px | MOTA @15 px | IDSW | Ids | FP | FN | IDF1 IoU | HOTA | DetA | AssA |
|---|---|---|---|---|---|---|---|---|---|---|
| ByteTrack, Ultralytics' defaults | 71.4 | 96.4 | 574 | 774 | 1,861 | 3,997 | 59.2 | 48.0 | 56.0 | 41.5 |
| Flocker's settings | **97.3** | **99.1** | **36** | **235** | 571 | 915 | **79.2** | **58.3** | 57.2 | **59.5** |

- **The baseline row reproduces the harness note** (HOTA 48.0, MOTA 96.4), apart from one switch and one id. The likely
  cause: the harness tracked its detections unrounded, in memory, while the cache stores boxes to 2 decimals.
- **The switches left** are 6 restarts, 18 swaps and 12 other.
- **The ball** improves slightly with the same settings, but stays unusable: MOTA −4.3 against −10.3 by IoU,
  recall 41 % against 31 %.
- **A look at the frames:**
  - **The render:** `videos/edit/2026-11-24_identity-dots/flocker_teams_1530_1560_4x.mp4` draws these tracks, team
    coloured, over `D_20220220_1_1530_1560` at 4x.
  - **What it shows:** each dot sits on a player with a continuous trail, and the two goalkeepers are drawn white
    (neither team). The referee, unlabelled in TeamTrack, gets no dot.

## Team labels from kit colour (`src/flocker/team.py`)

- **Colour:** the camera is static, so the per-pixel median of 45 frames spread over a clip is the empty pitch.
  - Inside each box, the pixels more than 25 Lab units from that background are the player.
  - Their mean Lab colour is the detection's kit colour.
  - Pitch lines belong to the background, so a player on a line does not look white.
- **The kits:** on `D_20220220_1_1260_1290`, frame 1, in OpenCV 8-bit Lab (neutral a and b are 128):

  | Who | L | a | b |
  |---|---|---|---|
  | team 0, outfield | 183-198 (white) | about 122 | 132.5-134 |
  | team 1, outfield | 123-157 (blue) | about 122 | 120-126 |
  | the red goalkeeper (id 0) | 139 | 139 | 132 |
  | the yellow goalkeeper (id 13) | 178 | 115 | 162 |

  The nearer outfield kit for the red goalkeeper is blue, and for the yellow one white. Forcing every colour into a
  team would put both goalkeepers in the wrong one.
- **The team model** (`fit_teams`): two Gaussian clusters, refitted on their own members. A colour joins a team only
  within a Mahalanobis radius of 11.34 (the 99th percentile of χ² with 3 degrees of freedom); anything else is
  OTHER.
  - **Seeding matters.** The first version seeded the clusters with 2-means, and on 3 of the 9 val clips it took a
    goalkeeper as a "team" and merged both kits into the other. A goalkeeper's colours are far more compact than a
    kit's, so the cluster held.
  - **The fix:** seed with 4-means, which gives two kits and two goalkeepers, and take the two most populous
    clusters, since ten outfield players outnumber a goalkeeper ten to one. A fit whose smaller team holds under 20 %
    of the colours is refused.
  - `tests/test_team.py` reproduces the failure on synthetic colours.
- **Labels:** the model is fitted per clip on player detections with confidence ≥ 0.3 (`label_teams`). Each track
  then takes its detections' majority team (`flocker.track.track_teams`).
- **Accuracy:** outfield players' detections at confidence ≥ 0.1, matched to the ground truth (the goalkeepers,
  ids 0 and 13 in every clip, come out OTHER in all 18 clips, as intended):

  | Split | Detections right | Wrong team | OTHER | Track rows right | Wrong team |
  |---|---|---|---|---|---|
  | val | 98.2 % | 0.55 % | 1.26 % | 99.87 % | 0.13 % |
  | test | 97.6 % | 0.95 % | 1.46 % | 98.88 % | 1.12 % |

  - **Wrong labels gather in crowds.** On val, the wrong-team rate is 0.04 % at confidence ≥ 0.5, but 3.7 % at
    0.2-0.3.
  - On test, `D_20220220_1_1710_1740`, the clip with half of the swaps, has 5.8 % wrong against 0.2-0.5 % in the
    other clips.
- **Speed:** about 36 s per clip, 18 s for the background read in one pass and 18 s for the colours.
  - Only the boxes are converted to Lab. Converting whole 4K frames gave the same numbers at about nine times the
    cost.
  - Seeking for background samples was also several times slower than one sequential pass: 74 s against 18 s.

**Gating association by team (`flocker.track.team_aware`) was tried and rejected.**
- **The rule:** a track that has gathered at least 5 team votes, at 80 % purity or more, may not take a detection of
  the other team. `tests/test_team.py` shows it preventing a swap that IoU alone makes.
- **On val it hurt:** IDF1 95.4 against 98.8, and 110 switches against 34.
  - Gating and voting only with detections at confidence ≥ 0.3 did no better: IDF1 95.5, 113 switches.
  - With every detection's team set to unknown, the gated tracker reproduces the ungated one exactly, so the wrapper
    is sound.
- **The cause is in the labels:**
  - **an example** (`D_20220220_1_1290_1320`, frame 131): the detection 3 px from a white-kit player, at confidence
    0.30, is labelled blue, because a blue opponent stands 19 px away inside the same box;
  - **the effect:** the gate blocks the player's own track, and the freed detection can join a wrong one.
- `team_aware` stays in the code, with this result in its docstring, for the next attempt.

## Changes

- **`flocker.track`:**
  - `suppress_duplicates` (greedy NMS per frame and class);
  - `FLOCKER_TRACKER` and `DEDUP_IOU`;
  - `tracker_config("flocker")`, now the default;
  - `team_aware` and `track_teams`, with a `team` column on tracks when the detections have one;
  - `quantize=16` in place of Ultralytics' deprecated `half=True`. It is the same FP16: 738 of 738 detections were
    identical on a 20-frame check, and the 3,119 deprecation warnings per run are gone.
- **`flocker.team` (new):** the background, box colours, `fit_teams` and `label_teams`.
- **`flocker.evaluate`:** `switch_events` and `match_centres`.
- **`bin/flocker.py track`:**
  - `--tracker` now defaults to `flocker` (was `bytetrack`);
  - new `--dedup-iou`, default 0.3 (1 turns it off);
  - new `--teams`, which writes `colours/<seq>.csv` (cached) and `teams/<seq>.csv`;
  - `run.json` now records the resolved tracker settings.
- **`bin/flocker.py dots`:** colours tracks by team when `teams/<seq>.csv` sits beside them.
- **To repeat the harness note's tracking runs** under the new defaults, pass `--tracker bytetrack --dedup-iou 1`.
- **Tests:** 36 unit tests, up from 28. Each new check was seen to fail under a mutation of the code it guards (seven
  mutations, all caught):
  - **`suppress_duplicates`:** suppressed boxes also suppress; the class is ignored;
  - **`switch_events`:** every switch is a restart; a restart is counted while the old id lives on;
  - **the team model:** no outlier radius;
  - **the team gate:** it never blocks; tracks never collect votes.

## Next

1. **Colour from the middle of the box,** or excluding pixels nearer another detection. That should cut wrong labels
   in crowds; then try team gating again, perhaps as a cost rather than a veto.
2. **What is left of identity:** 36 switches and 37 extra ids on test.
   - **Restarts:** offline linking of tracklets could join them.
   - **Swaps:** they need appearance beyond kit colour, or motion over longer spans.
3. **Edit 4, the homography,** as planned. The pixels-per-metre figure needs measuring: the harness note uses about
   37 px/m, the handoff about 28.
4. **The flocking analysis** can now use team labels.
5. **The ball,** still unusable: it needs a dedicated approach.

## Reproduce

```bash
I=~/Development/python/Flocker/tmp/2026-11-24_identity
P="conda run -n Flocker python"
M=~/Development/python/Flocker/resources/models/flocker_yolo11n_teamtrack-tiles1280-e30_2026-11-24.pt
# val detections (ran with the defaults of the time: Ultralytics' ByteTrack, no dedup)
$P bin/flocker.py track --model $M --split val --out-dir $I/tracks/val/bytetrack_default --tracker bytetrack --dedup-iou 1
# test: the harness's cached detections, copied to $I/tracks/test/bytetrack_default/detections/
$P util/ad-hoc/2026-11-24_team_colours.py extract --det-dir $I/tracks/val/bytetrack_default --split val   # and test
$P util/ad-hoc/2026-11-24_team_colours.py study --det-dir $I/tracks/val/bytetrack_default --split val
for s in baseline dedup thresholds trackers tracktrack teams teams_confident; do
  $P util/ad-hoc/2026-11-24_tracker_sweep.py --det-dir $I/tracks/val/bytetrack_default --split val --stage $s --out $I/sweep_val.csv --breakdown
done
$P util/ad-hoc/2026-11-24_tracker_sweep.py --det-dir $I/tracks/val/bytetrack_default --split val --stage shortlist --out $I/sweep_val.csv --hota
$P util/ad-hoc/2026-11-24_tracker_sweep.py --det-dir $I/tracks/test/bytetrack_default --split test --stage final --out $I/sweep_test.csv --hota --breakdown
# the command itself (defaults: --tracker flocker --dedup-iou 0.3), with team labels, and its scores
$P bin/flocker.py track --split test --out-dir $I/tracks/test/flocker_teams --reuse-detections --teams  # detections/ and colours/ copied in
$P bin/flocker.py eval --pred-dir $I/tracks/test/flocker_teams --split test --max-dist 15
$P bin/flocker.py dots --sequence D_20220220_1_1530_1560 --tracks $I/tracks/test/flocker_teams/D_20220220_1_1530_1560.txt \
    --out videos/edit/2026-11-24_identity-dots/flocker_teams_1530_1560_4x.mp4 --background frame --trail 6
```
