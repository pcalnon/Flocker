# Video toolchain: setup and source validation

**Date**: 2026-11-20
**Environment**: conda env `Flocker` at `/opt/miniforge3/envs/Flocker` (rebuild with `config/environment.yml`)
**Validation script**: `util/validate_tool_sources.py` (read-only; re-run it to refresh the evidence). It ran on
2026-11-20 as `util/ad-hoc/2026-11-20_validate_tool_sources.py` and was promoted on 2026-11-24.
**Later additions**: py-motmetrics, pytest, black, isort and flake8, recorded in
`notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md`.
**Local copies** (git ignores both; moved here from another repository's scratch folder on 2026-11-24):
- the reviewed `roboflow/sports` archive, in `tmp/2026-11-20_toolchain/downloads/`
- the YOLO11n weights used in the end-to-end test, at `resources/models/yolo11n.pt`

The toolchain covers the planned edits: detecting and tracking players, separating them from shadows,
correcting the camera angle with a homography, drawing players as dots on a top-down pitch, scaling
movement, and re-encoding at a different speed.

## Install order used

The requested priority was MCP servers, then conda/mamba, pip, direct package downloads, GitHub, apt.

1. **MCP servers**: three remote servers configured in `.mcp.json` (below).
2. **conda/mamba**: everything else except one package came from conda-forge.
3. **pip**: used only to install the GitHub package below, with `--no-deps`.
4. **Direct package downloads**: none needed.
5. **GitHub**: `roboflow/sports`, pinned to a reviewed commit.
6. **apt**: none needed.

## Source validation

conda-forge builds each package from a recipe in a public "feedstock" repository. For each package
I checked that the feedstock exists and is maintained, and that its recipe downloads the official
upstream source. conda then verifies every package's checksum on download.

| Tool | Version | Recipe source | Upstream repository (owner, stars, licence, last push) |
|---|---|---|---|
| PyTorch | 2.13.0, CUDA 12.9 | download.pytorch.org | pytorch/pytorch (org, 105,755, BSD-style, 2026-11-21) |
| torchvision | 0.28.0, CUDA 12.9 | github.com/pytorch/vision tags | pytorch/vision (org, 18,024, BSD-3-Clause, 2026-11-20) |
| OpenCV | 4.13.0, Qt6 GUI | github.com/opencv/opencv | opencv/opencv (org, 91,660, Apache-2.0, 2026-11-20) |
| FFmpeg | 9.0.2, GPL build | ffmpeg.org/releases | FFmpeg/FFmpeg (org mirror, 67,736, LGPL/GPL, 2026-11-21) |
| Ultralytics (YOLO, trackers) | 8.4.216 | PyPI source archive | ultralytics/ultralytics (org, 63,631, AGPL-3.0, 2026-11-20) |
| supervision | 0.32.0 | PyPI source archive | roboflow/supervision (org, 51,678, MIT, 2026-11-20) |
| mplsoccer | 1.8.1 | PyPI source archive | andrewRowlinson/mplsoccer (user, 555, MIT, 2026-10-27) |
| yt-dlp | 2026.10.26 | PyPI source archive | yt-dlp/yt-dlp (org, 209,425, Unlicense, 2026-11-21) |
| kaggle CLI | 2.2.5 | PyPI source archive | Kaggle/kaggle-cli (org, 7,683, Apache-2.0, 2026-11-18) |
| huggingface_hub | 2.4.0 | PyPI source archive | huggingface/huggingface_hub (org, 4,059, Apache-2.0, 2026-11-20) |
| gdown | 6.5.2 | PyPI source archive | wkentaro/gdown (user, 5,496, MIT, 2026-11-19) |
| lap | 0.5.14 | PyPI source archive | gatagat/lap (user, 254, BSD-2-Clause, 2026-11-04) |
| sports | 0.1.0 | GitHub archive of commit `42c80c06` | roboflow/sports (org, 5,508, MIT; commit 2025-05-27 by a Roboflow maintainer) |

No feedstock is archived; all were updated between 2026-10-02 and 2026-11-20.

- **sports**: I read `setup.py` (plain setuptools) and scanned the package code. It has no network
  calls, shell commands, `eval`/`exec` or pickle loading. Archive sha256:
  `169c88540f601514e9bbbb78ab31727cab42569f76fe6f6ff36e2494c413b26d`.
- **Not traced individually**: the general-purpose conda-forge packages (numpy, scipy, pandas,
  scikit-image, scikit-learn, matplotlib, tqdm, transformers, umap-learn, sentencepiece, protobuf, six,
  ipykernel). They are covered only by conda-forge's own review and checksums.

## MCP servers

Configured in `.mcp.json`. Tokens come from environment variables, so the file holds no secrets.
Claude Code asks you to approve project servers the first time a session opens in this repository.

| Server | Endpoint | Run by | Probe result (2026-11-20) |
|---|---|---|---|
| `kaggle` | `https://www.kaggle.com/mcp`, token from `KAGGLE_API_TOKEN` | Kaggle | 76 tools, including `search_datasets`, `list_dataset_files`, `download_dataset` |
| `hf-mcp-server` | `https://huggingface.co/mcp`, token from `HF_TOKEN` | Hugging Face | 4 tools (Hub search, repo details, file access) |
| `context7` | `https://mcp.context7.com/mcp` | Upstash | 2 tools (library documentation lookup) |

`deepwiki` and `chrome-devtools` are already configured for every project.

- **ffmpeg MCP servers: not configured.** The candidates (`mcp-video`, `mcp-ffmpeg`,
  `ffmpeg-mcp-server`, `vfx-mcp`) are community projects, not from the FFmpeg project or a major
  vendor; three of the four are published under individual developers' accounts. At least one
  (`ffmpeg-mcp-server`) exposes raw ffmpeg command execution. They add nothing over calling ffmpeg and OpenCV directly.
- **juniper-ml's local `kaggle-mcp` is broken and was not changed.** Its virtual environment links to
  `JuniperCascor1`'s Python. That interpreter moved from 3.13 to 3.14, and the server's packages are
  still in the 3.13 tree, so it cannot import `kaggle`.

## Verification

- **GPU**: `torch.cuda.is_available()` is true, and the build includes `sm_75` (the RTX 2080's architecture).
  A matrix multiply and a cuDNN 9.10.2 convolution ran on the GPU.
- **End to end**: YOLO11n detected 5 objects on `cuda:0` (6.5 ms inference). The model came from
  `github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt`, sha256
  `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`.
- **OpenCV**: background subtraction with shadow detection (MOG2), `findHomography`, `inpaint`, and a Qt6 GUI.
- **FFmpeg**: encoders `libx264`, `libx265`, `libsvtav1`, `libvpx-vp9`, `h264_nvenc` and `hevc_nvenc`.
- **`conda doctor`**: environment consistent, no missing files.
- **`pip check`**: one message, `ultralytics-platform` not installed. It was left out deliberately (see below).
- **`pip-audit`**: three advisories, all in `setuptools` 81.0.0 (see Known issues).

## Not installed, and why

- **`ultralytics-platform`**: Ultralytics' cloud-service client (AGPL-3.0, `ultralytics/sdk`, released
  almost daily since 2026-08). Ultralytics imports it only when its cloud client is used; local
  detection and tracking work without it. It is not on conda-forge.
- **`filterpy`**: version 2.0.0 appeared on 2026-10-26, eight years after 1.4.5. It is not needed: the
  trackers include their own Kalman filters, and SciPy covers smoothing.
- **SportsLabKit**: no commits since 2023-12-19.
- **roboflow/sports' example models and videos**: hosted on Google Drive. The models are pickle files
  trained on broadcast footage, and the videos are broadcast views, not top-down.
- **A video player**: VLC and Totem are already installed.
- **apt packages**: none needed. The system `/usr/bin/ffmpeg` (8.0.1) has vid.stab stabilization,
  which the conda build lacks, and GIMP is installed.

## Known issues

- **setuptools 81.0.0 carries three advisories.**
  - CVE-2026-59890 / PYSEC-2026-3447 matters only when building source distributions.
  - GHSA-xmj3-9gf7-h52w is a path escape on Windows.

  Neither applies here. Fixing them needs setuptools 84.1, but PyTorch 2.13.0's CUDA 12.9 build
  requires setuptools below 82.
- **An install once replaced the CUDA build silently.** Installing `setuptools>=84` swapped PyTorch for
  a CPU-only build. It was rolled back and verified, and `conda-meta/pinned` now holds
  `pytorch`, `libtorch` and `torchvision` to CUDA builds and `cuda-version` to 12.9.
- **Some packages are outside the scans.** `pip-audit` cannot check OpenCV (conda's 4.13.0 has no
  matching PyPI release) or `sports` (not on PyPI). Non-Python conda libraries such as FFmpeg and CUDA
  are not covered by any scan here.
- **Ultralytics is AGPL-3.0.** That is fine for research. Distributing software built on it brings
  AGPL obligations.
- **Ultralytics analytics are off.** Its anonymous usage analytics are on by default and were turned
  off with `yolo settings sync=False`. The setting lives in `~/.config/Ultralytics/settings.json` and
  applies to every Ultralytics install for this user.
