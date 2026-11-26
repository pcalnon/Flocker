# Handoff: the image-to-pitch homography (edit 4) is done; the flocking analysis is next

**Date**: 2026-11-25 (session in worktree `worktree/20261125-135757`)
**Repository**: `pcalnon/Flocker` (public), `~/Development/python/Flocker`
**State at handoff**:
- PR #10 (edit 4) is squash-merged as `51483b0`, a verified commit.
- This handoff and an `AGENTS.md` fix follow as their own PR.
- **Merge approval:** the owner granted it for this work arc on 2026-11-25, including the ruleset bypass (`--admin`).
  It is per-session, so ask again.

---

## Handoff goal

Continue the Flocker research pipeline on TeamTrack. Players are detected and tracked, carry team labels, and now
have positions in metres in every frame.

**Next: the flocking analysis**, then the optional items below.

### Completed so far

- **PR #10, edit 4** (`notes/FLOCKER_2026-11-25_PITCH-HOMOGRAPHY.md` has the method, evidence and commands):
  - **`src/flocker/pitch.py` (new):**
    - the Law 1 markings in metres, with the origin at the centre mark, x toward the right goal and y down the image;
    - a sub-pixel line fit: each line's centre is the centroid of its half-maximum run, then robust least squares;
    - `track_pitch`, which refits every frame;
    - `with_pitch_positions`, which turns boxes into metres.
  - **The CLI:**
    - **`pitch`:** writes `<seq>.csv`, one homography per frame;
    - **`eval`:** `--pitch-dir` with `--max-dist-m`;
    - **`dots`:** `--pitch-dir` with `--view pitch`, plus `--lines` and `--background pitch`.
  - **The pitch:** a regulation 105 x 68 m (measured 105.018 x 67.955) at 27.9 px/m. 15 px is 0.52-0.55 m, and the
    harness note's 37 px/m was wrong.
  - **The fit:** the lines sit 0.39 px (1.4 cm) RMS from the markings. The marks, which the fit never sees, land
    0.4-1.2 px off.
  - **The camera turns** up to 4.9° within a clip (median 0.5°), and a corner moves up to 80 px.
    - One homography per clip would misplace positions by up to 3 m and invent common velocities of up to 4.7 m/s.
    - All 54,000 frames were tracked, with no restarts and no failures.
  - **Ground-truth speeds:** outfield players reach a median 5.2 m/s per 30 s clip (fastest 10.0) and cover 136 m/min.
  - **Test tracks in metres:** at 0.54 m, MOTA 99.2, IDF1 97.3 and 36 ID switches, the same as at 15 px.
  - **Parallax is not corrected.** A box centre about 0.9 m up lands about 0.9 % of its distance from the nadir too far
    out, up to 0.45 m at the goal lines. It is a near-uniform scale.
  - **Validation:**
    - 56 tests pass, 48 of them unit;
    - 13 of 13 mutations are caught (`util/ad-hoc/2026-11-25_pitch_mutations.py`);
    - an independent review found six bugs, all fixed;
    - real frames were checked.
- **Docs:** dated corrections in the harness and identity notes; `AGENTS.md` and `README.md` updated. This handoff's
  PR also records the `main` ruleset in `AGENTS.md`.

### Remaining work

1. **The flocking analysis** (the research question), in metres:
   - **Positions:** `flocker.pitch.with_pitch_positions(df, read_homographies(<pitch>/<seq>.csv))` adds `mx` and `my`.
     The tables for all 60 clips are in the primary's `tmp/2026-11-25_homography/pitch/`.
   - **Start from the ground truth:** ids 0-10 and 11-21 are the two teams. Leave out the goalkeepers (ids 0 and 13 in
     every clip; team -1 in the tracks) and the six drifting train clips (`flocker.yolo_dataset.MISALIGNED_TRAIN`).
   - **Then the tracks with team labels:** `tmp/2026-11-24_identity/tracks/test/flocker_teams/` holds the tracks and
     `teams/`.
   - **Measures, per team per frame:**
     - polarisation (the mean unit heading);
     - milling or angular momentum about the centroid;
     - cohesion (spread, convex-hull area);
     - nearest-neighbour distances, and the order of neighbours;
     - against a null model (shuffled headings or time-shifted teams), and against the ball where it is known.
   - **Velocities:**
     - Smooth before differencing: 0.5 s Savitzky-Golay, as in `util/ad-hoc/2026-11-25_pitch_study.py speeds`.
     - Use the per-frame homographies; frame 1's alone adds a spurious common turn.
     - The pitch frame is left-handed seen from above (y runs down the image), so positive angular momentum is
       clockwise in the video.
   - **One ground-truth glitch:** goalkeeper id 0 in `D_20220220_1_0180_0210` jumps 7 m at frame 301. Look for others
     before trusting speeds.
   - **Results** go in a new note, `notes/FLOCKER_<date>_<...>.md`, with the commands that produced them. Tune on val
     and score test once, if anything is tuned.
2. **Optional, edit 4:**
   - measure the altitude from the goal crossbars (2.44 m), then correct box centres toward the nadir;
   - a one-parameter radial lens term (1-1.7 px at the frame corners);
   - stabilise `flocker.team.clip_background` with the homographies.
3. **Edit 3** (ask the owner what "proportionally" means), **edit 1** (shadows, on the stock clips) and **the ball**.
   The stock clips would need a keypoint detector, or a hand start per clip, for a homography.
4. **Identity, optional:** colour from the box centre, then team gating as a cost; tracklet linking; the 18 test swaps.
5. **Owner items still open:**
   - the YubiKey modes-and-symlinks commit;
   - juniper-ml's `shiny-pondering-gray` triage;
   - Ultralytics' host-level `datasets_dir`;
   - the smoke test's primary-detection fix;
   - removing the old worktrees `worktree/20261124-142932` and `worktree/20261124-200945`:
     - check `tmp/` first: 142932's `2026-11-24_smoke` is not in the primary's `tmp/`;
     - 200945 is level with `origin/main` only after a `git reset --mixed origin/main`;
     - this session's worktree (`worktree/20261125-135757`) can go too: its `tmp/2026-11-25_pr-pitch/` is copied to
       the primary's `tmp/`.

### Key context

- **Landing:**
  - Use `util/ad-hoc/2026-11-24_land_signed_pr.py` (GitHub-signed API commits).
  - **The ruleset "Flock-This"** (created 2026-11-24 21:26, all branches):
    - signed commits are required; deletion and force-pushes are blocked; only bypass actors may create or update
      branches;
    - a plain `gh pr merge` into `main` is refused; merging needs `--admin`;
    - the owner approved `--admin` for PR #10 under this arc's merge approval;
    - the API's branch creation goes through, because this account can bypass.
- **Studies and caches:** the primary's `tmp/2026-11-25_homography/`:
  - `pitch/`, the final run; `pitch_v0/` is an earlier partial run made before the review fixes; do not use it;
  - `study/`: `size_frame1.csv`, `motion.csv`, `motion_match.png`, `boxes.csv`, `speeds.csv`, and the eval CSVs;
  - `look/`: exploration images;
  - `mutations/`: the mutated copies.
  - The renders are in `videos/edit/2026-11-25_pitch-view/`.
- **Speed:** `pitch` takes about 55 s per clip. Five jobs on 16 cores took about 25 min for 60 clips, at a load of
  25-30, because FFmpeg starts its own decode threads. `track_pitch` fits about 12-16 frames per second.
- **Lessons:**
  1. **`pkill -f PATTERN` from the Bash tool matches the tool's own `bash -c` line** and kills it. Anchor the pattern,
     e.g. `pgrep -f '^/opt/miniforge3/envs/Flocker/bin/python -I bin/flocker.py'`.
  2. **When drawing at k times the size and reducing by area,** small pixel u maps to k u + (k - 1) / 2, not k u. A
     test renderer that skipped this showed a uniform 0.354 px "error" (√2 / 4).
  3. **Measure rotation, not just translation.** Phase correlation missed a 4.9° yaw.
  4. **Median backgrounds blend the camera's positions,** so fit single frames when the camera moves.
  5. **`conda run` swallows a heredoc's stdin.** Use `/opt/miniforge3/envs/Flocker/bin/python -I -`. On this host,
     `grep` is ugrep; use `command grep` or `/usr/bin/grep`.

## Verification for the next thread

```bash
cd ~/Development/python/Flocker
git fetch origin && git status --short --branch                       # ## main...origin/main
gh pr view 10 --repo pcalnon/Flocker --json state,mergeCommit --jq '.state + " " + .mergeCommit.oid'   # MERGED 51483b0...
conda run -n Flocker python -m pytest -q -m unit                       # 48 passed
ls tmp/2026-11-25_homography/pitch/*.csv | wc -l                       # 60
conda run -n Flocker python bin/flocker.py eval --pred-dir tmp/2026-11-24_identity/tracks/test/flocker_teams \
    --split test --pitch-dir tmp/2026-11-25_homography/pitch --max-dist-m 0.54 | tail -1   # OVERALL 99.2 0.15m 97.3 ... 36
```

**Git status at handoff:**
- **Primary:** clean on `main` at `51483b0`; after the handoff PR merges, at its squash commit.
- **This worktree** (`worktree/20261125-135757`): reset to `origin/main` and clean, apart from this handoff and the
  `AGENTS.md` fix (uploaded as their own PR). Its ignored `tmp/2026-11-25_pr-pitch/` holds the PR #10 lists and bodies.

## Documents referenced, created or modified in this arc

- **Created:**
  - `src/flocker/pitch.py` and `tests/test_pitch.py`;
  - `util/ad-hoc/2026-11-25_pitch_study.py` and `util/ad-hoc/2026-11-25_pitch_mutations.py`;
  - `notes/FLOCKER_2026-11-25_PITCH-HOMOGRAPHY.md`;
  - this file.
- **Modified:**
  - `src/flocker/render.py`, `src/flocker/cli.py`, `src/flocker/teamtrack.py` and `src/flocker/evaluate.py`;
  - `tests/test_render.py`;
  - `notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md` and `notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md`
    (dated corrections);
  - `AGENTS.md`, twice: the pipeline and pitch facts in PR #10, and the ruleset in the handoff PR;
  - `README.md`.
- **Referenced:**
  - `prompts/thread-handoff_automated-prompts/HANDOFF_2026-11-24_player-identity.md` (the predecessor);
  - `prompts/thread-handoff_automated-prompts/HANDOFF_2026-11-24_flocker-repo-setup-and-video-toolchain.md` (the owner's
    five edits);
  - `util/ad-hoc/2026-11-24_land_signed_pr.py` and `util/open_signed_pr.py`.
- **Ignored local outputs:** the primary's `tmp/2026-11-25_homography/` and `videos/edit/2026-11-25_pitch-view/`.
