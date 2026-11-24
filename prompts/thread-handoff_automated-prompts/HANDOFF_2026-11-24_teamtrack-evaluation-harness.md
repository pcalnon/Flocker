# Handoff: TeamTrack evaluation harness, first detector and dots

**Date**: 2026-11-24 (session in worktree `worktree/20261124-142932`)
**Repository**: `pcalnon/Flocker` (public), `~/Development/python/Flocker`
**State at handoff**:
- **PR #7** (the harness) was squash-merged as `cc697e2`.
- **PR #8** (results, dots, centre matching, README, this file) was opened and merged in the same session, under
  the owner's merge approval for the session.
- `main` is the merge of PR #8. The primary checkout was fast-forwarded to it.

---

## Handoff goal

Continue the Flocker research pipeline on TeamTrack. Players are now detected and their positions are accurate.
The next work, in order:
1. keep player identities through a clip;
2. map the image to pitch coordinates (edit 4);
3. then the flocking analysis.

### Completed so far

- **The evaluation harness** (`src/flocker/evaluate.py`, PR #7):
  - **Metrics:** HOTA, CLEAR-MOT and IDF1 through py-motmetrics, with ids relabelled to 1..N; its HOTA mishandles
    TeamTrack's 0-based ids.
  - **Centre matching (PR #8):** `eval --max-dist PX` matches box centres instead of IoU.
  - **Validation:** hand-computed cases, code mutations the tests catch, and perturbed real ground truth.
- **Commands** (`bin/flocker.py`): `build-dataset`, `train`, `track` (detections cached, one tracker per class),
  `eval` and `dots`.
- **The detector:** YOLO11n fine-tuned on 1280 px full-resolution tiles of 36 train sequences, in 85 min.
  - The weights are archived at `resources/models/flocker_yolo11n_teamtrack-tiles1280-e30_2026-11-24.pt`
    (sha256 `84c9bce7…`).
  - The run is at `tmp/2026-11-24_teamtrack-eval/runs/yolo11n_tiles1280_e30/`.
- **Test-split results, players** (see the note):
  - **positions:** with centres within 15 px, recall 97.8 %, precision 98.9 %, mean error 4.3 px;
  - **by IoU:** HOTA 48.0, MOTA 60.9, IDF1 59.3;
  - **identity:** 773 track ids for 198 players;
  - **BoT-SORT** (no GMC or ReID) is slightly better: HOTA 48.9, 496 identity switches;
  - **the ball:** HOTA 10.7, unusable.
- **TeamTrack facts:**
  - ids 0-10 and 11-21 are the teams and 22 is the ball; referees are unlabelled;
  - six train sequences have labels that drift in time, and are excluded from training;
  - `1770_1800` is annotated with oversized boxes (median 42 x 40 px), which wrecks its IoU scores but not its
    centre scores;
  - the camera drifts at most about 12 px over the match.
- **Dots** (edits 2 and 5): `dots` draws dots over the original frames, or over the clip's median "empty pitch",
  at N x speed.
  - **Clips:** `videos/edit/2026-11-24_teamtrack-dots/`, holding the ground truth and the tracker output for
    `1530_1560` at 4x.
  - **Checked by eye:** the dots sit on the players, and the referee gets none.
- **Environment:** pytest, black, isort and flake8 (conda-forge), and py-motmetrics `develop@e5ae766f` (pip,
  sha256-pinned). All dry runs were clean, and PyTorch is still on CUDA.
- **Repository:**
  - `pyproject.toml`, `.flake8`, `.gitignore` rules for generated outputs;
  - `util/validate_tool_sources.py` (promoted);
  - `AGENTS.md` updates, including an *Analysis pipeline* section and smoke-test caveats;
  - a fuller `README.md`.

### Remaining work

1. **Identity.**
   - Tune `track_buffer` and the thresholds with `--reuse-detections --set key=value`; each run takes seconds.
   - Try BoT-SORT with images: camera-motion compensation and ReID would need `track_detections` to accept
     frames.
   - Try team-colour-aware association.
   - Try YOLO11s (download it and record its sha256, as for YOLO11n).
   - Score both IoU and `--max-dist 15`.
2. **Edit 4, the homography.**
   - Fit one image-to-pitch homography from the pitch lines on a median background. Pitch about 105 x 68 m and
     roughly 28 px/m at 4K; to be checked.
   - Then express positions and the error thresholds in metres.
3. **Edit 3, scaling movement:** clarify with the owner what "proportionally" means.
4. **Edit 1, shadows,** on the stock clips with long shadows: `pexels_33645092`, `pexels_39134041`,
   `pexels_40060083` and `pixabay_168908`. The median background removes moving shadows, but static shadows need
   another method.
5. **The ball:** a dedicated approach.
6. **Flocking:** team-wise polarisation, cohesion and nearest-neighbour structure. Start from the ground truth,
   then use the tracks.
7. **Owner items still open:**
   - the YubiKey modes-and-symlinks commit;
   - juniper-ml's `shiny-pondering-gray` triage;
   - Ultralytics' host-level `datasets_dir` points into that juniper-ml worktree (Flocker passes explicit paths).
   - **Possible fix:** `util/ad-hoc/2026-11-24_launcher_smoke_test.bash` could find the primary through git's
     common directory and clear the ceiling for its helper case.

### Key context

- **Land work through the API:** `util/ad-hoc/2026-11-24_land_signed_pr.py` with path lists. This session's lists
  and bodies are in the worktree's `tmp/2026-11-24_pr-harness/` and `tmp/2026-11-24_pr-results/`.
- **Syncing after a merge:**
  - fast-forward the **primary** (`git -C <primary> merge --ff-only origin/main`), because its files were not
    written there;
  - `git reset --mixed origin/main` only in the checkout that wrote the files.
- **GPU budget:**
  - detection at 3840 takes about 50 ms a frame, so the 9 test sequences take 8.4 min;
  - training takes 4.8 GB, so never detect while it runs;
  - `eval` takes about 1 min with HOTA.
- **Ultralytics:** pass explicit output paths, and local weights only. `detector.use_bundled_font()` stops
  training from downloading `Arial.ttf`.
- **On this host, `grep` is ugrep.** Use `command grep` for anything under `tmp/`.

## Verification for the next thread

```bash
cd ~/Development/python/Flocker
git fetch origin && git status --short --branch               # "## main...origin/main", nothing else
gh pr list --repo pcalnon/Flocker --state merged --limit 3     # #8 and #7 merged
conda run -n Flocker python -m pytest -q -m unit               # 28 passed
conda run -n Flocker python -m pytest -q                       # 34 passed, about 2 min 15 s (reads the dataset)
sha256sum resources/models/flocker_yolo11n_teamtrack-tiles1280-e30_2026-11-24.pt   # 84c9bce7...
conda run -n Flocker python bin/flocker.py eval --pred-dir tmp/2026-11-24_teamtrack-eval/tracks/yolo11n_e30_bytetrack --max-dist 15 | tail -1   # OVERALL MOTA 96.4
```

**Git status at handoff:**
- **Primary:** clean on `main`, up to date with `origin/main`.
- **Worktree `worktree/20261124-142932`:** reset to `main`.
  - Its `tmp/` holds scratch: `2026-11-24_teamtrack-look/` (crops cited in the note), `2026-11-24_smoke/` and the
    PR bodies.
  - Move `2026-11-24_teamtrack-look/` to the primary's `tmp/` before removing the worktree.
- **Ignored local state in the primary:**
  - `tmp/2026-11-24_teamtrack-eval/` (dataset 3.8 GB, runs, tracks, logs);
  - `tmp/2026-11-24_toolchain/` (archive, validation output, install logs);
  - `tmp/2026-11-24_smoke-from-worktree-session/`;
  - `resources/models/`;
  - `videos/edit/2026-11-24_teamtrack-dots/`.

## Documents referenced, created or modified in this arc

- **Created:**
  - `notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md`;
  - `src/flocker/` (`__init__`, `cli`, `detector`, `evaluate`, `mot`, `paths`, `render`, `teamtrack`, `track`,
    `yolo_dataset`);
  - `tests/` (`conftest`, `synthetic`, `test_evaluate`, `test_evaluate_teamtrack`, `test_mot`, `test_render`,
    `test_teamtrack`, `test_track`, `test_yolo_dataset`);
  - `bin/flocker.py`, `pyproject.toml`, `.flake8`, `util/validate_tool_sources.py`;
  - this file.
- **Modified:** `AGENTS.md`, `README.md`, `.gitignore`, `config/environment.yml`,
  `notes/FLOCKER_2026-11-20_VIDEO-TOOLCHAIN-SETUP.md`.
- **Deleted:** `util/ad-hoc/2026-11-20_validate_tool_sources.py` (moved to `util/`), `src/.gitkeep`,
  `bin/.gitkeep`.
- **Referenced:**
  - `prompts/thread-handoff_automated-prompts/HANDOFF_2026-11-24_flocker-repo-setup-and-video-toolchain.md`;
  - `videos/raw/SOURCES.md`;
  - `util/ad-hoc/2026-11-24_launcher_smoke_test.bash`, `util/ad-hoc/2026-11-24_land_signed_pr.py`,
    `util/open_signed_pr.py`, `util/flocker_repo_tmp.bash`.
- **Outside the repository:** the `Flocker` conda environment (the five packages above).
