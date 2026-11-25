# Handoff: player identity and team labels

**Date**: 2026-11-24 (session in worktree `worktree/20261124-200945`)
**Repository**: `pcalnon/Flocker` (public), `~/Development/python/Flocker`
**State at handoff**:
- The work is on branch `feat/player-identity`, PR #9, opened through the API and **not merged**. The owner merges;
  no merge approval was given this session.
- `main` is still `73bce2b` (PR #8).

---

## Handoff goal

Continue the Flocker research pipeline on TeamTrack.
- **Done:** players are detected, keep their identities, and carry team labels.
- **Next, in order:**
  1. merge PR #9, if the owner has not;
  2. edit 4, the image-to-pitch homography;
  3. the flocking analysis.

### Completed so far

- **The diagnosis** (`notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md`): with Ultralytics' ByteTrack defaults, 53 % of
  test-split identity switches were "restarts". A track died while its player was being detected (in 99 % of the gap
  frames). Two causes, which matter only together:
  - **duplicate boxes:** the detection-time NMS at IoU 0.6 leaves a near-copy on many players, at IoU 0.54-0.60;
  - **score fusion:** with true players at a median confidence of 0.40, ByteTrack's cost demands IoU > 0.6.
- **The fix, chosen on val and scored once on test:**
  - **the settings:** a second NMS at IoU 0.3 (`flocker.track.suppress_duplicates`), then ByteTrack with
    `fuse_score` False, `track_high_thresh` 0.15 and `match_thresh` 0.9 (`config/trackers/flocker_bytetrack.yaml`);
  - **test, players, centres within 15 px:** IDF1 71.4 → 97.3, ID switches 574 → 36, track ids 774 → 235 (198 true),
    MOTA 96.4 → 99.1;
  - **test, by IoU:** HOTA 48.0 → 58.3, AssA 41.5 → 59.5;
  - **the other Ultralytics trackers** reach IDF1 98.3-98.8 on val with the same cleanup, so the tracker choice
    matters little now.
- **Team labels** (`src/flocker/team.py`):
  - **the method:** kit colour against the clip's median background, and two Gaussian team clusters seeded by 4-means,
    with goalkeepers and referees left as OTHER;
  - **detections:** 98.2 % (val) and 97.6 % (test) of outfield detections are labelled right;
  - **track rows:** 99.87 % (val) and 98.88 % (test) carry the right team;
  - **2-means seeding failed** on 3 of 9 val clips (a goalkeeper became a "team"); a test pins the fix.
- **Hard team gating** (`flocker.track.team_aware`) was tried and rejected: val IDF1 95.4 against 98.8. A box in a
  duel takes in the opponent's kit, so labels fail exactly where gating would act.
- **The command line:**
  - **`track`:** `--tracker` defaults to `flocker`; new `--dedup-iou`, default 0.3 (1 turns it off); new `--teams`,
    which writes `colours/<seq>.csv` and `teams/<seq>.csv`; `run.json` records the resolved settings;
  - **`dots`:** colours tracks by team from that sidecar;
  - **detection** passes `quantize=16` instead of the deprecated `half=True`. The 738 detections checked were
    identical.
- **`flocker.evaluate`:** `switch_events` classifies switches as restart, swap or other; `match_centres`.
- **A look at real frames:** `videos/edit/2026-11-24_identity-dots/flocker_teams_1530_1560_4x.mp4`. Dots sit on the
  players in team colours, the goalkeepers are white and the referee has none.
- **Tests:** 42 pass (36 unit). Every new check was seen to fail under a mutation (seven mutations).
- **Docs:** `AGENTS.md` (pipeline, `config/trackers/`, "tune on val, score test once"), `README.md`, and the harness
  note's Reproduce section, which now says to add `--tracker bytetrack --dedup-iou 1` to repeat its runs.

### Remaining work

1. **PR #9:** if it is still open, the owner reviews and squash-merges it. Then sync:
   - fast-forward the primary: `git -C ~/Development/python/Flocker merge --ff-only origin/main`;
   - `git reset --mixed origin/main` in this worktree, if it is reused.
2. **Edit 4, the homography.**
   - **Fit:** one image-to-pitch homography from the pitch lines of a median background (`flocker.team.clip_background`
     gives one in 18 s). The camera drifts at most about 12 px over the match.
   - **Scale:** pixels per metre is unsettled. The harness note uses about 37 px/m, the old handoff about 28. A pitch
     about 105 x 68 m; the frame shows the whole pitch.
   - **Then** express positions, speeds and the 15 px threshold in metres.
3. **The flocking analysis.** Team-wise polarisation, cohesion and nearest-neighbour structure. Start from the ground
   truth (ids 0-10 and 11-21 are the teams), then use the tracks with `--teams` labels. Exclude the goalkeepers (team
   -1 in the tracks; ids 0 and 13 in every TeamTrack clip).
4. **Identity, optional:**
   - colour from the box centre only, to cut wrong labels in crowds, then retry gating as a cost, not a veto;
   - offline tracklet linking for the 6 remaining restarts;
   - the 18 test swaps.
5. **Edit 3** (what "proportionally" means: ask the owner), **edit 1** (shadows, on the stock clips) and **the ball**.
6. **Owner items still open:**
   - the YubiKey modes-and-symlinks commit;
   - juniper-ml's `shiny-pondering-gray` triage;
   - Ultralytics' host-level `datasets_dir`;
   - the smoke test's primary-detection fix;
   - removing the old worktree `worktree/20261124-142932`. Its `tmp/` holds `2026-11-24_pr-harness`,
     `2026-11-24_pr-results`, `2026-11-24_smoke` and `2026-11-24_teamtrack-look`. All but `2026-11-24_smoke` are
     already in the primary's `tmp/`; check that one before removing it.

### Key context

- **Tune on val, score test once.**
  - Val detections and colours are cached in the primary's `tmp/2026-11-24_identity/tracks/val/bytetrack_default/`.
  - Test's are in `tracks/test/bytetrack_default/`, copied from the harness's cache.
  - A tracker run replays a cache in seconds: `--reuse-detections`, after copying `detections/` and `colours/` into a
    new `--out-dir`.
- **The sweep tool:** `util/ad-hoc/2026-11-24_tracker_sweep.py` records every configuration as a named stage, and
  appends to `sweep_val.csv` or `sweep_test.csv`.
- **CPU:** cap threads (`OMP_NUM_THREADS=1` or `2`) when running process pools. Two pools at once reached a load of 54
  on 16 cores.
- **`conda run` swallows a heredoc's stdin.** For quick snippets, use `/opt/miniforge3/envs/Flocker/bin/python -`.
- **Landing:** `util/ad-hoc/2026-11-24_land_signed_pr.py`. This session's lists and bodies are in the worktree's
  `tmp/2026-11-24_pr-identity/`, copied to the primary's `tmp/`.
- **On this host, `grep` is ugrep.** Use `command grep` for anything under `tmp/`.

## Verification for the next thread

```bash
cd ~/Development/python/Flocker
git fetch origin && git status --short --branch               # "## main...origin/main"
gh pr view 9 --repo pcalnon/Flocker --json state,mergedAt     # OPEN, or MERGED once the owner has merged it
conda run -n Flocker python -m pytest -q -m unit               # 36 passed (on main after the merge, or on the PR branch)
I=tmp/2026-11-24_identity
conda run -n Flocker python bin/flocker.py eval --pred-dir $I/tracks/test/flocker_teams --split test --max-dist 15 | tail -1
# OVERALL MOTA 99.1, IDF1 97.3, IDSW 36, IDs 235
```

**Git status at handoff:**
- **Primary:** clean on `main` at `73bce2b`.
- **Worktree `worktree/20261124-200945`:** holds this work, uncommitted locally, as uploaded to PR #9. After the merge,
  run `git reset --mixed origin/main` there.

## Documents referenced, created or modified in this arc

- **Created:**
  - `notes/FLOCKER_2026-11-24_PLAYER-IDENTITY.md`;
  - `src/flocker/team.py`;
  - `tests/test_team.py`;
  - `config/trackers/flocker_bytetrack.yaml`;
  - `util/ad-hoc/2026-11-24_tracker_sweep.py` and `util/ad-hoc/2026-11-24_team_colours.py`;
  - this file.
- **Modified:**
  - `src/flocker/track.py`, `src/flocker/evaluate.py` and `src/flocker/cli.py`;
  - `tests/test_evaluate.py` and `tests/test_track.py`;
  - `AGENTS.md` and `README.md`;
  - `notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md`.
- **Referenced:**
  - `prompts/thread-handoff_automated-prompts/HANDOFF_2026-11-24_teamtrack-evaluation-harness.md`;
  - `util/ad-hoc/2026-11-24_land_signed_pr.py` and `util/open_signed_pr.py`.
- **Ignored local outputs:** the primary's `tmp/2026-11-24_identity/` and
  `videos/edit/2026-11-24_identity-dots/`.
