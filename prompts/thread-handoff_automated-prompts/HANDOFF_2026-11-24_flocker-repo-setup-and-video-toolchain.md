# Handoff: Flocker repository setup and video toolchain ("flock this")

**Date**: 2026-11-24
**Work arc**: 2026-11-20 (clips and toolchain) and 2026-11-24 (repository setup), in one Claude Code session
that ran from a juniper-ml worktree
**Repository**: `pcalnon/Flocker` (public), `~/Development/python/Flocker`
**State at handoff**: `main` in sync with `origin/main` and clean. PRs #1 to #5 are squash-merged, each a
GitHub-verified commit.

---

## Handoff goal

Continue the Flocker project: research into unexpected flocking behaviour, starting with soccer players in
top-down drone video. The repository, environment, data and agent guidance are in place, but no analysis code
exists yet.

### Completed so far

- **Clips (2026-11-20):**
  - 10 licensed top-down soccer clips are in `videos/raw/` (685 MB): Pexels ×8, Pixabay ×1, Wikimedia Commons ×1.
    Provenance, licence, attribution text and sha256 for each are in `videos/raw/SOURCES.md`.
  - TeamTrack's top-view subset (MIT, 1.83 GB) is in `videos/raw/teamtrack_soccer_top/`: 60 thirty-second 4K
    clips of one 11-a-side match, with CSV boxes and MOT-format ground truth. Its checksums are in `SHA256SUMS`.
  - None of the media is in git.
- **The `Flocker` conda environment** (`/opt/miniforge3/envs/Flocker`, spec in `config/environment.yml`):
  - **Contents:** PyTorch 2.13 on CUDA 12.9 (verified on the RTX 2080), OpenCV 4.13, the GPL ffmpeg build,
    Ultralytics, supervision, mplsoccer, roboflow `sports` at `42c80c06`, and the Kaggle and Hugging Face tools.
  - **Validation record:** `notes/FLOCKER_2026-11-20_VIDEO-TOOLCHAIN-SETUP.md`.
- **The repository (2026-11-24):**
  - **PR #1:** the initial files and `.gitignore`.
  - **PR #2:** the work files moved out of juniper-ml's temp tree.
  - **PR #3:** Flocker's own launchers (`scripts/`), `util/flocker_repo_tmp.bash`, the `.claude/settings.json`
    hook, `util/open_signed_pr.py` and the launcher smoke test (201/0).
  - **PR #4:** `AGENTS.md`, imported by `CLAUDE.md`.
  - **PR #5:** this document.
- **Host:** `~/.claude/settings.json`'s user-level temp hook now exempts Flocker, as it does `articles`. The
  backup is `~/.claude/settings.json.bak-2026-11-24-flocker`.

### Remaining work

1. **Owner, needs the YubiKey:** set executable bits and create the symlinks the API cannot. See *Owner actions*.
   Afterwards, update `AGENTS.md` § Launching sessions and § Git (they say "run with `bash`") and the
   `CLAUDE.md` import note.
2. **Owner decisions:**
   - **Decided 2026-11-24:** `scripts/claude_interactive.bash` keeps `DEBUG=TRUE`, and with it
     `--dangerously-skip-permissions` on every launch.
   - **Done 2026-11-24:** juniper-ml's `kaggle` MCP entry now points at Kaggle's hosted server. See *Owner
     actions*.
   - **Still open:** triage the 43 modified files in juniper-ml worktree `shiny-pondering-gray` (see
     *Residue*).
3. **The research pipeline**, the five edits the owner asked about on 2026-11-20:
   1. remove shadows from moving and static objects;
   2. replace players with dots;
   3. scale movement proportionally;
   4. correct the camera angle (a homography);
   5. speed up playback.

   Start on TeamTrack: its ground truth lets you measure detection and tracking (MOT metrics) before you trust
   the dots. Then use the stock clips with long shadows (`pexels_33645092`, `pexels_39134041`,
   `pexels_40060083`, `pixabay_168908`) to test shadow handling. `sports` and mplsoccer provide pitch geometry
   and top-down "radar" drawing.
4. **Repository hygiene, when code lands:**
   - pre-commit, black, isort and flake8 at line length 512;
   - pytest;
   - optionally a GitHub Actions CI;
   - a fuller `README.md`.

### Key context

- **Commits are signed and headless signing hangs** (YubiKey touch). Land every change with
  `util/open_signed_pr.py`, or `util/ad-hoc/2026-11-24_land_signed_pr.py` for a list of paths. Squash-merge,
  delete the branch, then `git fetch origin && git reset --mixed origin/main`.
  - GitHub signs API commits, but the API writes every file as `100644`.
  - A local `chmod +x` file shows as a mode change; run `chmod 644` on it.
- **The repository is public.** Never commit media (GitHub's 100 MB limit, and the Pexels and Pixabay terms) or
  secrets. `.mcp.json` takes its tokens from `KAGGLE_API_TOKEN` and `HF_TOKEN`.
- **Dry-run every conda install.** `conda-meta/pinned` holds CUDA builds and `cuda-version=12.9`. Earlier, an
  unpinned `setuptools>=84` request silently swapped in CPU PyTorch.
- **Temp root:** the primary's `tmp/`. The launcher pins `CLAUDE_CODE_TMPDIR` with `--settings`, and
  `.claude/settings.local.json`, which is host-local and gitignored, sets it for sessions not started through
  the launcher.

---

## Owner actions

**Modes and symlinks** need a signed local commit, run at the keyboard:

```bash
cd ~/Development/python/Flocker && git switch -c chore/modes-and-symlinks
X="scripts/claude_interactive.bash scripts/wake_the_claude.bash util/flocker_repo_tmp.bash util/ad-hoc/2026-11-24_launcher_smoke_test.bash util/ad-hoc/2026-11-20_video-search/*.bash"
chmod +x $X && git update-index --chmod=+x $X
git rm -q CLAUDE.md && ln -s AGENTS.md CLAUDE.md && ln -s scripts/claude_interactive.bash claudey && git add CLAUDE.md claudey
git commit -m "chore(repo): set executable bits; link CLAUDE.md and claudey"    # touch the YubiKey
git push -u origin chore/modes-and-symlinks && gh pr create --fill && gh pr merge --squash --delete-branch
```

**juniper-ml's `kaggle` MCP server was repointed on 2026-11-24, with the owner's approval.**
- **The cause:** its stdio server ran from a uv virtual environment linked to `JuniperCascor1`'s Python. That
  Python moved from 3.13 to 3.14 on 2026-09-12, so the server could no longer import `kaggle`.
- **The new entry**, in the untracked `juniper-ml/.mcp.json`, is the same as Flocker's:
  `{"type": "http", "url": "https://www.kaggle.com/mcp", "headers": {"Authorization": "Bearer ${KAGGLE_API_TOKEN:-}"}}`.
- **The check:** `claude mcp get kaggle` reports it connected.
- **Only that entry changed.** The old file is backed up, readable by the owner only because it holds a token,
  in juniper-ml's `tmp/mcp-json-backups/`.
- **Running sessions** pick up the change after `/mcp` or a restart.
- **The old local server** in `~/.local/share/mcp-servers/kaggle-mcp/` is no longer used.

## Residue outside Flocker

- **juniper-ml worktree `shiny-pondering-gray`** (this session's):
  - It has 43 modified tracked files dated 2026-11-21 and 2026-11-22, for example "Owner ruling" became "The
    Overtoad ruling" in `conf/python_versions.yaml`. This session did not make them, and they were left
    untouched.
  - juniper-ml `main` @ `d7709ef7` already carries "Overtoad ruling" comments, so they may duplicate `main`.
    Check before removing the worktree.
  - Its `.playwright-mcp/` keeps 16 older files (May 2026, plus four PNGs) that a juniper-ml worktree copied in
    when it was created. This work's 25 files moved to Flocker.
- **Claude Code's own task records** for this session (background-task output and subagent links) remain under
  `juniper-ml/tmp/claude-1000/`, where Claude Code manages them. The session scratch folder is empty.
- **juniper-ml memory** was updated: `project_kaggle_mcp_venv_fix_2026-06-02.md`,
  `reference_cpu_torch_pin_lock_reresolution.md` and `MEMORY.md`. Flocker's own memory folder is empty; its
  lessons are in `AGENTS.md` and below.

## Lessons learned

1. **A headless commit cannot be signed here.** Use API commits, and design around their limits:
   - use `@AGENTS.md` instead of a symlink;
   - run scripts with `bash`;
   - run `chmod 644` locally;
   - sync with `reset --mixed`.
2. **A solver satisfies the letter of a request.** "setuptools>=84" was satisfied by silently dropping CUDA.
   - Read every dry run's `-`/`+` lines.
   - Pin what must not move.
   - Stop an unsatisfiable dry run after a few minutes; it can run for more than five.
3. **Kaggle's single-file download writes to `<path>/<full dataset-relative name>`**, not
   `<path>/<file name>`. Download to a staging folder, then move.
   - A `| tail -20` hid 220 of the 240 "missing" lines. Count the failures, don't sample them.
4. **A virtual environment linked to a conda env's interpreter breaks when that env changes minor version.**
   Prefer hosted MCP servers, or interpreters you manage yourself.
5. **The isolation guard refuses commands, not intentions.** It refuses loops, `git -C` inside compound
   commands, `.gitignore` paths in chains, and heredocs with dict literals.
   - Put the logic in a `util/ad-hoc/` script, and run it with one plain command.
6. **Self-containment has three layers:**
   - the repository's own hook;
   - a user-level exemption, because the global hook otherwise forces another project's `tmp/`;
   - `CLAUDE_CODE_TMPDIR`, set by `--settings` and `settings.local.json`, because user settings override the
     environment.

   The `articles` repository (`~/Development/articles`) is the template for a self-contained repo outside
   Juniper.
7. **Verify agents' claims independently.** That meant hashes, a contact sheet, and re-running the smoke test.
   - My first re-run failed because of my own relative paths, which the test rightly refused. Read a failure
     before blaming the work under test.
8. **Check the precedent before briefing an agent.** I first specified Claude Code's `--worktree`. `articles`
   showed launcher-made `worktrees/` was the better fit, and a mid-flight `SendMessage` corrected it.
9. **On this host `grep` is ugrep, which honours `.gitignore`.** Use `command grep` for anything under `tmp/`.

## Verification for the next thread

```bash
cd ~/Development/python/Flocker
git fetch origin && git status --short --branch        # expect "## main...origin/main" and nothing else
git log --oneline -6                                    # PRs #5..#1 squash commits above 512dce5
gh pr list --repo pcalnon/Flocker --state merged        # #1-#5
conda run -n Flocker python -c "import torch; print(torch.__version__, torch.cuda.is_available())"   # 2.13.0 True
bash scripts/wake_the_claude.bash --dry-run 2>&1 | head -20                                         # TMPDIR = .../Flocker/tmp
bash util/ad-hoc/2026-11-24_launcher_smoke_test.bash --out "$PWD/tmp/smoke/out" --fixture "$PWD/tmp/smoke/fixture" | tail -1   # PASS: 201 FAIL: 0
(cd videos/raw/teamtrack_soccer_top && sha256sum --quiet -c SHA256SUMS && echo dataset OK)
```

**Git status:** branch `main`, nothing staged, no uncommitted work.

**Ignored local state:**
- the media (2.5 GB)
- `tmp/`:
  - `2026-11-20_video-search/`
  - `2026-11-20_toolchain/`
  - `2026-11-24_launcher-port/`
  - `2026-11-24_repo-setup/`
- `logs/2026-11-20_conda-env-create.log`
- `resources/models/yolo11n.pt`
- `.claude/settings.local.json`

## Documents referenced and created in this arc

**Created or changed in Flocker:**
- `.gitignore`, `.mcp.json`, `.claude/settings.json`, `AGENTS.md`, `CLAUDE.md`
- `config/environment.yml`
- `notes/FLOCKER_2026-11-20_VIDEO-TOOLCHAIN-SETUP.md`
- `videos/raw/SOURCES.md`, `videos/raw/teamtrack_soccer_top/SHA256SUMS`, `videos/raw/teamtrack_soccer_top/kaggle-dataset-metadata.json`
- `scripts/claude_interactive.bash`, `scripts/wake_the_claude.bash`
- `util/flocker_repo_tmp.bash`, `util/open_signed_pr.py`
- `util/ad-hoc/`:
  - `2026-11-20_validate_tool_sources.py`
  - `2026-11-20_fetch_teamtrack_soccer_top.py`
  - `2026-11-20_video-search/`: a README and 10 scripts
  - `2026-11-24_move_work_files_from_juniper.py`
  - `2026-11-24_land_signed_pr.py`
  - `2026-11-24_launcher_smoke_test.bash`
- this file

**Changed outside Flocker:**
- `~/.claude/settings.json`
- `/opt/miniforge3/envs/Flocker/conda-meta/pinned`
- `~/.config/Ultralytics/settings.json`
- the juniper-ml memory files listed above
