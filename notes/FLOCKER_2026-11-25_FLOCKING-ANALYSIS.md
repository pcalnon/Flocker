# Do the teams flock? Collective motion of TeamTrack's players, in pitch metres

**Date**: 2026-11-25
**Scope**: the research question, first pass. Do the two teams of TeamTrack's top-view match move the way flocks do? The
measures are alignment, rotation, cohesion and neighbour structure. Each is set against null models, against the ball
and team against team, from the ground truth first and then from the tracks. Builds on
`notes/FLOCKER_2026-11-25_PITCH-HOMOGRAPHY.md` (positions in metres) and `notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md`
(the tracks and team labels).
**Code**: `src/flocker/flocking.py` (new), `src/flocker/cli.py` (the `flock` command), `tests/test_flocking.py` (new),
`util/ad-hoc/2026-11-25_flocking_study.py` (new), `util/ad-hoc/2026-11-25_flocking_mutations.py` (new)
**Outputs** (gitignored): the primary checkout's `tmp/2026-11-25_flocking/`.
- `study/`:
  - `audit/`, `xcorr/` and `run/` (per-frame tables and per-clip sums);
  - `summary/`, `tracks/` and `plots/` (the four figures named below);
  - `run_v0_within_clip_shift/`, the first run, with the null the review replaced.
- `gt_test*/` and `tracks_test/`: the `flock` command on the test split.

## Summary

- **The teams are polarised far beyond chance.** The outfield players' mean unit heading averages 0.70 (team 0) and
  0.71 (team 1) per frame.
  - **Unsynchronised:** the same players, each taken from a different moment of the match, give 0.29. That is the level
    of random headings (0.28): left to themselves, players add no common direction.
  - **How often:** the excess, +0.41 and +0.42, holds in all 54 clips. A quarter of all frames have a team at 0.9 or
    more; the null never reaches it.
- **The two teams move as one larger flock.**
  - **Velocity:** their mean velocities correlate at 0.90 along the pitch and 0.86 across it, with no lag.
  - **Polarisation:** all 20 outfield players reach 0.68. With team 1 taken whole from another moment, they reach 0.49
    (51 of 54 clips).
- **Both teams follow the ball, about 1 s behind.** A team's mean velocity correlates best with the ball's velocity
  1.0-1.1 s earlier along the pitch (r 0.56-0.57) and 1.4 s earlier across it (r 0.61-0.63). Moving players head toward
  the ball at every distance: the mean cosine is 0.41 within 5 m, and 0.23-0.29 from 5 m to 50 m.
- **No milling.** Rotation about a team's centroid is no stronger than when headings are shuffled among the team's
  players.
- **Cohesion with spacing, two of the classic flocking rules.**
  - **Compact:** a team covers half the area that its players, taken from different moments, would (hull 880-980 m²
    against 1,750 m²). It is 26 m shorter along the pitch, in all 54 clips.
  - **Evenly spread:** inside that block, the nearest teammate is further away, for the team's size, than in either
    null: the spacing ratio is 1.10 against 0.94. That is the separation rule.
  - **Marking:** the nearest opponent is at 6.5-6.8 m, against 11.2-11.4 m in the null.
- **Neighbours align beyond their team's polarisation, and the range is counted in neighbours, not metres.**
  - **Teammates:** the nearest teammates run more alike than any two players of the same team in the same frame, by
    +0.07 in cosine for the nearest and +0.06 and +0.04 for the next two. The excess is gone by the 4th-5th.
  - **The nearest opponent most of all:** +0.125, the marking pair.
  - **The null shows none of it:** every rank is within ±0.01.
  - **The same rank whatever the spacing:** the range stays at 4-5 neighbours whether the team is compact or spread
    out, while in metres it runs from about 16 m to about 26 m. That is the signature of a *topological* interaction,
    as Ballerini et al. (2008) found in starlings.
- **The pipeline reproduces all of this from video.** The identity note's tracks give the same measures frame by frame
  on val and test: polarisation within 0.015-0.022 (median), r 0.93-0.97; hull areas within 2.5-3.7 m²; distances
  within 5 cm.
  - The excess over the null is 0.36-0.52 from tracks, against 0.36-0.52 from ground truth. Tracks beat the null in
    all 54 clip-team cases.
- **The null was corrected after an independent review.**
  - **The first null** moved each player in time within the clip, by its own offset. It left 44 % of player pairs
    within 5 s of each other, where real headings still correlate. It gave 0.42 instead of 0.29, and false neighbour
    alignment.
  - **Every conclusion held,** once spacing is measured for the team's size, and the excesses grew. The first
    numbers stay below as a sensitivity check.
- **The ground truth has glitches** that a velocity must not cross: 229 one-frame steps faster than 12 m/s, permanent
  jumps of up to 24 m, and three frames where many players jump at once. Most of them are in the first 7.5 minutes,
  where the boxes are a fixed 39 px. Tracks are cut there, which costs 0.02 % of rows.

## The data

- **54 clips of 30 s,** all from one continuous 30-minute stretch of one match, at 29.97 frames per second: all 60 of
  TeamTrack's top-view clips, minus the six train clips whose labels drift (`flocker.yolo_dataset.MISALIGNED_TRAIN`).
- **Positions** are box centres in pitch metres, through each frame's homography
  (`tmp/2026-11-25_homography/pitch/`). They carry the parallax the pitch note measured, about 1 % of the distance from
  the camera's nadir. The ball, when in the air, is displaced further.
- **The teams:** ids 0-10 and 11-21. **The goalkeepers, ids 0 and 13, are left out,** so each team has 10 outfield
  players.
  - **Checked here for all 60 clips:** team 0 defends the left goal and team 1 the right, throughout. Id 0 is team 0's
    deepest player in a median 100 % of frames, and at least 30 % in every used clip; id 13 is team 1's in at least 84 %
    (`study/audit/clips.csv`).
  - The low clips are a goalkeeper on his line with a teammate further back (`0930_0960`, `0960_0990`), or off his line.
  - **Two clips break the rule:** in `0570_0600` and `0600_0630`, ids 0 and 13 play in midfield and are never deepest.
    Both are among the six drifting clips, so the analysis never uses them. `tests/test_flocking.py` pins all of this.
- **An id keeps its role from clip to clip.** Each id's mean position in one clip correlates with the next clip's at r
  0.91 (along the pitch) and 0.93 (across), and still at 0.87 and 0.84 ten clips apart.
- **Coverage:** 8 of the 54 clips miss some player rows (at most 166 of 19,800). The ball is labelled in 593-900 of
  each clip's 900 frames.

### The ground truth's glitches (`study/audit/`)

A footballer's top speed is about 10-11 m/s, which is 0.33-0.37 m per frame. The pitch note's fastest smoothed
ground-truth speed was 10.0 m/s. Yet:

| One-frame steps, players | Count |
|---|---|
| Faster than 12 m/s (0.4 m per frame) | 229, in 31 of the 60 clips (224 in 27 of the 54 used) |
| Longer than 1 m | 15 |
| One-frame spikes (back within 0.3 m two frames on) | 41 |
| In the 15 clips whose boxes are a fixed 39 x 39 px (`0000_0030` to `0420_0450`) | 187 of the 229 |

- **The largest steps:**
  - permanent jumps: 24.0 m (`0660_0690`, id 18, frame 604) and 7.45 m (`0180_0210`, goalkeeper id 0, frame 301);
  - 18.7 m (`0360_0390`, id 17, frame 290), where an 18 x 10 px box became 40 x 36.
- **Impossible runs:** there are runs of 16-26 m/s lasting up to ten frames, for example `0060_0090`, id 8, frames
  96-105.
- **Whole frames:** three frames move many players at once.
  - `0540_0570`, frame 304: 17 players shift by about (−9, +6) px and come back.
  - `0180_0210`, frames 300-301: 4 players, then 10.
  - `1320_1350`, frame 517: 6 players, during a camera jerk.
  - The homography fits those frames at 0.39-0.52 px RMS, and the jumps are in the image coordinates. So they are in
    the annotation, not in the pitch tracking.
- **One ball glitch:** the ball moves 1.96 m in one frame (59 m/s), in `1170_1200`, frame 465.
- The early clips' fixed boxes show a change of annotation protocol about 7.5 minutes into the match. Most glitches are
  in those clips.

### Velocities (`flocker.flocking.kinematics`)

- **Each player's track is cut** after a missing frame and after any step longer than 0.4 m (12 m/s). The ball's limit
  is 1.5 m (45 m/s).
- **Each run of 15 frames or more** is smoothed with a 0.5 s Savitzky-Golay filter (quadratic) and differentiated. A
  shorter run gets no velocity.
- **The cost is negligible:** 179 of 971,391 outfield rows (0.02 %) lose their velocity. The clips have a median of 21
  runs for their 20 outfield players. The fastest smoothed speed is 12.1 m/s (median clip 7.5).
- **A heading needs 0.5 m/s.** Slower players count for positions and for the speed-weighted polarisation only. 97-98 %
  of team frames have at least 5 moving players.
- **The method was fixed before looking:** the smoothing, the 0.4 m limit, the 0.5 m/s threshold and every bin.
  Nothing was tuned, so val and test are used alike.

## The measures (`flocker.flocking`)

**Per team (10 outfield players) and frame**, and for both teams together (`frame_measures`, `bin/flocker.py flock`):

| Measure | Definition | Reference values |
|---|---|---|
| polarisation | the length of the mean unit heading of the moving players | 1 if all run one way; 0.28 for 10 random headings, 0.20 for 20 |
| polarisation_w | \|sum of velocities\| / sum of speeds, every player, no threshold | as above |
| milling | the mean of (unit vector from the centroid) x (unit heading); signed | +1 for a clockwise circle in the video, −1 anticlockwise |
| radius | RMS distance from the centroid, m | |
| hull_area | the convex hull, m² | |
| length, width | extent along x (goal to goal) and y (touchline to touchline), m | |
| nn_mean | mean distance to the nearest teammate, m | |
| nn_opponent | mean distance to the nearest opponent, m | |

- **The sign of milling:** the pitch frame is left-handed seen from above (y runs down the video), so positive milling
  is clockwise in the video. `tests/test_flocking.py` checks the sign on a synthetic mill.
- **The spacing ratio,** nn_mean / sqrt(hull_area / 10), is computed in the study: a team's nearest-teammate distance
  for its size.

### The null models

- **Players from different clips (`mix`, the main null):**
  - every outfield player's whole track, positions and velocities together, comes from a different clip;
  - the 20 source clips are drawn at random, never the clip itself (`flocker.flocking.mix_clips`, `draw_clips`).
  - **What it keeps:** every player's own speeds and directions, and where they play, since an id keeps its role.
  - **What it removes:** players from different clips are minutes apart, so nothing synchronises them.
  - Ten repetitions per clip.
- **Team 1 from another clip (`team_mix`):** team 0 stays; team 1 comes whole from one other clip. Each team keeps its
  own coordination, and only the link between the teams is lost.
- **Headings shuffled within the team (`shuffle`):** each frame's velocities are dealt at random among one team's
  players. The team keeps its shape and its set of headings; only who runs which way is lost.
- **Why players are not simply moved in time within their clip** (`study/xcorr/`):

  | Time between two teammates | 0 s | 2.5 s | 5 s | 7.5 s | 10 s | 12.5 s | 15 s | Different clips |
  |---|---|---|---|---|---|---|---|---|
  | Mean heading alignment u_a(t) . u_b(t + D) | +0.520 | +0.287 | +0.089 | +0.006 | −0.036 | −0.083 | −0.104 | −0.033 |

  - **The decay:** headings stay correlated for about 7 s and swing negative beyond, as play turns round.
  - **The limit:** within a 30 s clip, ten players can be at most 3 s apart from each other.
  - **The first null** (`shift_ids`, each player shifted by an independent random 5-25 s) left 43.7 % of pairs under
    5 s apart and 9.6 % under 1 s, for an expected pair alignment of +0.121. Players from different clips give −0.033.
  - An independent review of the code found this on 2026-11-25. The first null's results are kept as `shift` below.

### Statistics

- Frames within a clip are strongly correlated, so the unit is the clip.
- Each number below is the mean over the 54 clips of each clip's mean over its frames. Its 95 % interval comes from
  resampling clips 10,000 times.
- The neighbour and ball tables pool pairs or frames over the clips, and resample clips the same way.
- "Clips" counts the clips in which the real value beats the null.
- The clips are consecutive pieces of a single match, so the intervals describe this match. They say nothing yet of
  football in general.

## Alignment: the teams are polarised (`study/plots/real_vs_null.png`)

| Polarisation | Real | Players from different clips | Real − null [95 %] | Clips | First null (shift) |
|---|---|---|---|---|---|
| Team 0 | 0.697 [0.672, 0.722] | 0.289 | **+0.408** [0.383, 0.433] | 54 of 54 | 0.417 (+0.280) |
| Team 1 | 0.710 [0.684, 0.733] | 0.291 | **+0.419** [0.394, 0.442] | 54 of 54 | 0.420 (+0.289) |
| Both teams | 0.680 [0.653, 0.705] | 0.200 | **+0.481** [0.454, 0.505] | 54 of 54 | 0.366 (+0.314) |
| Speed-weighted, team 0 / 1 | 0.710 / 0.728 | 0.329 / 0.328 | +0.381 / +0.400 | 54 / 54 | 0.464 / 0.467 |

- **The per-frame distribution:**
  - **Real teams:** median 0.75-0.77 and 10th percentile 0.35-0.37. A team is at 0.9 or more in 23.5 % of frames.
  - **The null:** median 0.28, and 0.9 or more in no frame.
- **Players' own habits add nothing.** Players from different clips are as unaligned as random headings (0.29 against
  0.28), because each player runs both ways along the pitch.
- **The teams together:** with team 1 taken whole from another clip, all 20 players reach 0.492. The real 0.680 is
  +0.188 [0.163, 0.211] above it, in 51 of 54 clips, so the two teams align with each other.
- **Polarisation rises with the ball's speed** (both teams):

  | Ball speed, m/s | 0-2 | 2-5 | 5-10 | 10-15 | over 15 |
  |---|---|---|---|---|---|
  | Polarisation | 0.63 | 0.71 | 0.76 | 0.75 | 0.77 |
  | Team centroid to the ball, m | 23.2 | 19.4 | 19.3 | 18.4 | 17.6 |

  - A dead or slow ball (restarts, a dribble) leaves the teams less aligned and further from it.
  - A pass or a long ball turns them together. See the timeline `study/plots/timeline_D_20220220_1_1530_1560.png`.

## Milling: none

| \|milling\| | Real | From different clips | Headings shuffled within the team |
|---|---|---|---|
| Team 0 | 0.147 | 0.186 | 0.146 (real − null +0.000 [−0.008, 0.009]) |
| Team 1 | 0.149 | 0.185 | 0.142 (+0.008 [−0.001, 0.016]) |
| Both teams | 0.123 | 0.129 | 0.106 (+0.017 [0.009, 0.026]) |

- **The signed mean is 0.00** (team 0 +0.002, team 1 −0.004), so neither direction of rotation is preferred.
- **Real teams mill less than unsynchronised players,** because a polarised group cannot also circle. They mill no more
  than the same headings dealt at random to the team's players.
- **Both teams together show a slight excess** over shuffled headings (+0.017). That is small, and it is not
  interpreted here.

## Cohesion and spacing

| Team 0 / team 1 | Real | From different clips | Real − null [95 %] | Clips real > null |
|---|---|---|---|---|
| Hull area, m² | 984 / 881 | 1,760 / 1,748 | −777 [−858, −692] / −867 [−927, −807] | 0 / 0 of 54 |
| Length along the pitch, m | 31.8 / 33.4 | 58.0 / 59.8 | −26.2 / −26.5 | 0 / 0 |
| Width across the pitch, m | 41.5 / 38.6 | 51.5 / 50.1 | −10.0 / −11.4 | 9 / 5 |
| Radius of gyration, m | 17.3 / 16.5 | 23.9 / 24.0 | −6.6 / −7.5 | 0 / 0 |
| Nearest opponent, m | 6.8 / 6.5 | 11.2 / 11.4 | −4.5 [−4.8, −4.0] / −4.8 [−5.2, −4.4] | 1 / 1 |
| Nearest teammate, m | 10.7 / 10.1 | 12.2 / 12.3 | −1.6 / −2.2 | 14 / 2 |
| **Spacing ratio**, teams pooled | **1.095** [1.079, 1.110] | 0.935 | **+0.160** [0.141, 0.178] | 53 of 54 |

- **The teams are compact,** above all along the pitch.
  - **Size:** each covers about half the area of its own players taken from different moments, and is 26 m shorter.
  - **Both teams together** span 37 m along the pitch. With team 1 taken from another moment they span 50 m, and with
    every player from a different clip 71 m: the two blocks stay close to each other.
  - This is the "block" that coaches ask for, and the cohesion rule of flocking models.
- **Inside the block, teammates keep their distance.**
  - **The raw distance misleads:** the nearest teammate is closer than in the null only because the whole team is
    smaller.
  - **For the team's size, it is further:** the spacing ratio is 1.10 against 0.94, in 53 of 54 clips. Against the
    first null, it is 0.97, again in 53 of 54.
  - The players spread out evenly instead of bunching. That is the separation rule.
- **The nearest neighbour is usually an opponent.** The nearest opponent is at 6.5-6.8 m and the nearest teammate at
  10.1-10.7 m; the null puts the nearest opponent at 11.2-11.4 m. That is marking.
- **The first null** was less extreme, because its players come from the same 30 s of play: hull −156 / −182 m²,
  length −7.2 / −7.0 m, nearest opponent −1.5 / −1.6 m.
- **The pooled frames** (`study/plots/real_vs_null.png`), real against the null:
  - hull area: median 874 m² against 1,715 m²;
  - team length: 32.2 m against 58.7 m;
  - nearest opponent: 6.4 m against 11.3 m.

## Neighbours: who aligns with whom (`study/plots/neighbours.png`)

- **What is measured:** for every moving player and frame, the cosine between their heading and that of their k-th
  nearest teammate or opponent (both moving). It is compared with the mean cosine over all pairs from the same frame.
  - **For teammates** that mean is (m p² − 1)/(m − 1), for m moving players at polarisation p.
  - **For opponents** it is the dot product of the two teams' mean headings.
- **The excess** is the alignment beyond what the team's polarisation alone gives.
  - Over all pairs of a frame it averages zero by construction. So a positive excess for near neighbours forces a
    negative one for far ones; only the near end and the crossing point carry information.
  - With headings shuffled within the team it is 0.000 ± 0.002 at every rank, as it must be.

| Rank | Teammate: distance | Excess [95 %] | Null: from different clips | Opponent: distance | Excess [95 %] | Null: from different clips |
|---|---|---|---|---|---|---|
| 1 | 10.5 m | **+0.069** [0.060, 0.078] | −0.010 [−0.023, 0.004] | 6.5 m | **+0.125** [0.110, 0.138] | +0.004 [−0.011, 0.019] |
| 2 | 13.9 m | +0.061 [0.055, 0.069] | +0.001 | 11.3 m | +0.046 [0.035, 0.057] | +0.012 |
| 3 | 16.9 m | +0.043 [0.035, 0.050] | +0.004 | 15.0 m | +0.022 [0.015, 0.029] | +0.002 |
| 4 | 20.0 m | +0.016 [0.009, 0.022] | +0.010 | 18.0 m | +0.012 [0.005, 0.019] | −0.002 |
| 5 | 23.0 m | −0.002 [−0.007, 0.003] | +0.001 | 21.0 m | −0.004 | +0.002 |
| 9 | 37.3 m | −0.073 [−0.084, −0.062] | +0.003 | | | |

- **Local alignment:** a player's nearest 3-4 teammates run more like them than the team does. Players from different
  clips show nothing of the kind (−0.010 to +0.010 at every rank), so the alignment is not a matter of where players
  stand.
  - The first null showed a weaker rank pattern of its own (+0.02-0.05 at ranks 1-3). Those were the pairs it left
    within seconds of each other.
- **Marking is the strongest alignment of all.** The nearest opponent, 6.5 m away, runs most like the player (+0.125,
  against +0.004 in the null).
  - By distance, the opponents' excess is +0.20 within 2 m and +0.14 at 2-4 m, and it fades by 20 m.
  - Teammates peak at +0.05 over 4-16 m. Very close teammates (under 4 m, +0.02) align less: crowds round the ball are
    tangles.

**Rank or metres?**

- The question is the one Ballerini et al. (2008) asked of starlings: does a player align with a fixed number of
  neighbours, or with everyone within a fixed distance?
- Team frames were split by their spacing (the team's mean nearest-teammate distance). The teammates' excess is:

| Spacing class (share of team frames) | Rank 1 | 2 | 3 | 4 | 5 | Excess reaches 0 at rank | ... and at distance | 4th-5th teammate at |
|---|---|---|---|---|---|---|---|---|
| Compact, under 8 m (15 %) | +0.069 | +0.065 | +0.031 | +0.004 | +0.001 | 4-5 | about 16 m | 14-17 m |
| Middle, 8-10 m (29 %) | +0.076 | +0.064 | +0.036 | +0.013 | −0.012 | 4-5 | about 20 m | 18-21 m |
| Spread, 10 m or more (56 %) | +0.066 | +0.059 | +0.049 | +0.020 | +0.002 | 5 | about 26 m | 22-26 m |

- **By rank, the curves are the same** in all three classes. By distance, the range grows with the spacing, and in each
  class it is where the 4th-5th teammate stands.
- **So the interaction range is counted in neighbours (about 4-5), not in metres,** as for starlings (6-7 neighbours).
- **A caveat:** a team's spacing in football changes with the phase of play (attacking teams spread out). This is
  observational evidence, not a controlled test.

**Where the nearest teammate stands** (the nearest teammate of each moving player):

| | Real | From different clips | Headings shuffled | Isotropic |
|---|---|---|---|---|
| To the side of the player's heading (more than 45° off it) | 52.9 % [51.7, 54.1] | 50.2 % | 51.1 % | 50 % |
| Across the pitch (more than 45° off the x axis) | 58.2 % [56.8, 59.6] | 48.3 % | 58.4 % | 50 % |

- **The teams stand in lines across the pitch,** as in a back four or a midfield line: the nearest teammate is across the
  pitch in 58 % of cases, against 48 % for players from different clips.
- **A slight preference to the side:** the nearest teammate is beside the player's heading rather than ahead of or
  behind it, 52.9 % against 50 %. Starlings show the same anisotropy far more strongly.

## The ball (`study/plots/lags.png`)

- **What is measured:** the correlation of the ball's velocity at time t with a team's mean velocity at t + lag, over the
  frames where both are known. It is taken per clip and then averaged over the clips. The 95 % interval of the peak lag
  comes from resampling clips.

| | Along the pitch (x): r at lag 0 | Peak lag | r at peak | Across the pitch (y): r at lag 0 | Peak lag | r at peak |
|---|---|---|---|---|---|---|
| Ball, then team 0 | 0.42 [0.36, 0.48] | **+1.1 s** [1.0, 1.2] | 0.57 | 0.36 [0.32, 0.41] | **+1.4 s** [1.3, 1.6] | 0.61 |
| Ball, then team 1 | 0.43 [0.37, 0.48] | **+1.0 s** [0.9, 1.1] | 0.56 | 0.38 [0.34, 0.43] | **+1.4 s** [1.3, 1.5] | 0.63 |
| Team 0, then team 1 | **0.90** [0.84, 0.94] | −0.1 s [−0.1, 0.0] | 0.90 | **0.86** [0.82, 0.90] | 0.0 s [−0.1, 0.0] | 0.86 |

- **Both teams follow the ball** by about 1 s along the pitch and 1.4 s across it, with the same lag.
- **The teams follow each other without delay:** at 0.1 s resolution, neither leads.
- **Players run toward the ball.** The cosine between a moving player's heading and the direction to the ball:

  | Distance to the ball, m | 0-5 | 5-10 | 10-20 | 20-30 | 30-50 | 50 or more |
  |---|---|---|---|---|---|---|
  | Real ball | 0.41 [0.38, 0.45] | 0.29 | 0.27 | 0.26 | 0.23 | 0.34 |
  | Another clip's ball | −0.00 | −0.08 | −0.02 | +0.01 | +0.04 | +0.11 |

- **The ball is a common drive.** Some of the teams' alignment is a shared response to it, as in animals that turn
  together from one predator. Separating that from player-to-player alignment needs a model with both terms (see
  *Next*).
- **The neighbour excess** is measured against the same frames, so a drive common to a whole team does not produce it.
  A drive that depends on position can: players on one side of the ball who all run toward it run alike.

## From tracks instead of ground truth (`study/tracks/`)

- **The tracks:** the identity note's tracks (`tmp/2026-11-24_identity/tracks/{val,test}/flocker_teams/`), through the
  same homographies. Team-labelled tracks only: team −1, the goalkeepers and anyone unlabelled, is left out.
- **The team numbers match the ground truth's.** Track team 0 is the lighter kit, which is ground-truth team 0. Each
  track team's centroid lies nearer the same ground-truth team's centroid in 99.9 % (test) and 97.4 % (val) of team
  frames, 8-9 cm from it in the median.
- **Frame by frame:**

  | Test, team 0 / team 1 | Ground truth (median) | Tracks (median) | Median \|difference\| | Pearson r |
  |---|---|---|---|---|
  | Polarisation | 0.801 / 0.695 | 0.790 / 0.685 | 0.018 / 0.022 | 0.93 / 0.94 |
  | Speed-weighted polarisation | 0.809 / 0.724 | 0.800 / 0.719 | 0.016 / 0.018 | 0.97 / 0.97 |
  | Hull area, m² | 655 / 792 | 656 / 794 | 2.5 / 3.7 | 1.00 / 1.00 |
  | Nearest teammate, m | 8.92 / 9.29 | 9.08 / 9.25 | 0.045 / 0.049 | 0.99 / 0.98 |
  | Nearest opponent, m | 5.55 / 6.08 | 5.58 / 6.25 | 0.043 / 0.045 | 0.99 / 0.96 |
  | Mean speed, m/s | 2.04 / 2.14 | 2.05 / 2.16 | 0.07 / 0.08 | 0.99 / 0.99 |

  - **Val agrees as well:** polarisation within 0.015-0.017 (r 0.96-0.97).
  - **Players per team:** the tracks have 10 in the median frame. Their mean is 0.2 low for team 0 on test (missed or
    unlabelled players) and 0.16 high for team 1 (wrong-team labels).
- **The headline survives.** The null is the ground truth's (players from different clips), which does not depend on the
  tracker. Per clip, the excess polarisation over it is:
  - test: 0.440, 0.358 and 0.469 from tracks, against 0.443, 0.361 and 0.473 from ground truth (team 0, team 1, both);
  - val: 0.434, 0.440 and 0.519, against 0.436, 0.443 and 0.522.
  - Tracks beat the null in all 54 clip-team cases.

## What this shows, and what it does not

- **It shows** coordinated motion beyond what each player's own habits give:
  - alignment within each team and across the two teams;
  - cohesion with even spacing, and marking;
  - local, rank-limited alignment;
  - a ball that both teams follow about a second behind.
- **It does not separate interaction from common drive.** Both teams watch the same ball. The nulls keep each player's
  habits but remove the ball's influence along with the coordination. The neighbour excess is measured against the
  frame itself, but even that could come from players near each other answering the ball alike.
- **One match, 30 minutes:** 27 minutes of usable ground truth, ten outfield players a side. Whether other matches,
  levels or formations agree is open.
- **Box centres, not feet:** the parallax is a near-uniform 1 % scaling, which distances and alignments barely notice.
  The ball's height is not known, and a lofted ball's position is off by metres.
- **The ground truth's quality varies** across the match (fixed boxes early, glitches). The cuts remove the gross
  errors; finer annotation noise remains.

## Changes

- **`flocker.flocking` (new):**
  - **velocities:** `run_ids` and `kinematics`;
  - **measures:** `group_measures`, `frame_measures` and `neighbour_pairs`;
  - **nulls:** `draw_clips`, `mix_clips`, `shuffle_within` and `shift_ids`, whose docstring warns of its weakness;
  - **coupling:** `lagged_correlation`;
  - **inputs:** `players_from_gt` and `players_from_tracks`;
  - **constants:** `GOALKEEPER_IDS`, `MAX_STEP_M`, `MIN_SPEED` and the smoothing window.
- **`bin/flocker.py flock` (new):**
  - **output:** `frames.csv` (one row per sequence, frame and group: team 0, team 1, both) and `run.json`;
  - **source:** the ground truth by default, or tracks from `track --teams` with `--tracks-dir`;
  - **nulls:** `--null mix` (ground truth; it draws from all usable clips) or `--null shuffle`.
  - On the test clips its table equals the study's exactly.
- **Tests:** `tests/test_flocking.py`, 18 unit tests and 1 integration test.
  - **Known answers:** exact velocities on constant and accelerating motion; cuts at gaps, jumps and spikes; a square's
    geometry; milling's sign and centroid in the video's frame; neighbour ranks, alignments and bearings; what each
    null keeps; the lag's sign.
  - **The `flock` command** on a synthetic match: from ground truth and from tracks, with each null changing what it
    should.
  - **Pinned on TeamTrack:** the goalkeeper ids, and the 7 m jump being cut.
  - **Every check was seen to fail:** `util/ad-hoc/2026-11-25_flocking_mutations.py` breaks the code 30 ways, and the
    unit tests catch all 30.
- **Review:** an independent review found the weak null and seven smaller faults, and all were fixed:
  - three tests that could not fail as claimed;
  - summary rows that were identical to the real data by construction;
  - a speed-weighted polarisation from a single velocity;
  - an opponent baseline lost when a team has one mover;
  - a stale speed column after shuffling;
  - a hull-area denominator;
  - two CLI inputs that crashed instead of failing cleanly.

## Next

1. **Interaction or common drive:** fit a self-propelled-particle model with an alignment term over the k nearest
   neighbours, a cohesion term, and a ball term (attraction with a 1 s delay). Compare k and the weights between the
   teams, and against the null.
2. **Phases of play:** the ball's speed and position, and which team has it, change the measures. Possession is not
   labelled; it could be inferred from the ball's nearest player.
3. **Information flow:** is there a leader? Use lagged alignment between pairs of players (the ball-to-team lag of 1 s
   suggests it exists), and the order in which players turn after a long ball.
4. **More matches:** SoccerTrack's other views, or the stock clips once they have homographies (edit 4 there).
5. **The open edits:** edit 3 (ask what "proportionally" means), edit 1 (shadows) and the ball's detector.

## Reproduce

```bash
S=~/Development/python/Flocker/tmp/2026-11-25_homography
F=~/Development/python/Flocker/tmp/2026-11-25_flocking
I=~/Development/python/Flocker/tmp/2026-11-24_identity
P="/opt/miniforge3/envs/Flocker/bin/python -I"
export OMP_NUM_THREADS=1
$P bin/flocker.py flock --split test --pitch-dir $S/pitch --out-dir $F/gt_test               # per-frame measures, test
$P bin/flocker.py flock --split test --pitch-dir $S/pitch --out-dir $F/gt_test_mix --null mix --seed 1
$P bin/flocker.py flock --split test --pitch-dir $S/pitch --out-dir $F/tracks_test --tracks-dir $I/tracks/test/flocker_teams
$P util/ad-hoc/2026-11-25_flocking_study.py audit --pitch-dir $S/pitch --out $F/study        # the ground truth's glitches
$P util/ad-hoc/2026-11-25_flocking_study.py xcorr --pitch-dir $S/pitch --out $F/study        # why the null mixes clips
$P util/ad-hoc/2026-11-25_flocking_study.py run --pitch-dir $S/pitch --out $F/study          # 54 clips, about 7 min on 12 jobs
$P util/ad-hoc/2026-11-25_flocking_study.py summary --out $F/study                           # the tables above
$P util/ad-hoc/2026-11-25_flocking_study.py tracks --pitch-dir $S/pitch --tracks $I/tracks --out $F/study
$P util/ad-hoc/2026-11-25_flocking_study.py plots --out $F/study --pitch-dir $S/pitch
$P util/ad-hoc/2026-11-25_flocking_mutations.py --work $F/mutations                          # 30 of 30 caught
```

Reference: M. Ballerini et al., "Interaction ruling animal collective behavior depends on topological rather than
metric distance: evidence from a field study", PNAS 105(4), 1232-1237 (2008).
