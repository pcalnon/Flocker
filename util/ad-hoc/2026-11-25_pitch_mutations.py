"""Mutation check for the pitch work (edit 4): break one thing at a time and confirm a unit test fails.

Project: Flocker
File: util/ad-hoc/2026-11-25_pitch_mutations.py
Purpose: each mutation is applied to a copy of src/ and tests/ under --work, never to the checkout, and the unit tests of
    tests/test_pitch.py and tests/test_render.py run against the copy; every mutation must make at least one test fail
Author: Paul Calnon
Created: 2026-11-25
License: CC0 1.0 (see LICENSE)

Ran on 2026-11-25 from the worktree, with the Flocker environment:

    /opt/miniforge3/envs/Flocker/bin/python -I util/ad-hoc/2026-11-25_pitch_mutations.py \\
        --work ~/Development/python/Flocker/tmp/2026-11-25_homography/mutations

Two weakenings are deliberately not listed, because the tests are not meant to catch them: they change speed or
precision, not correctness. One is tracking every frame from the reference fit instead of the previous frame, which the
restart path absorbs. The other is a narrower half-maximum run, which costs precision but not accuracy.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (name, file under src/flocker, old text, new text)
MUTATIONS = [
    ("penalty area front line not inset", "pitch.py", "pa_x, ga_x, mark_x = s * (hl - PENALTY_AREA_DEPTH + h)", "pa_x, ga_x, mark_x = s * (hl - PENALTY_AREA_DEPTH)"),
    ("penalty arcs bulge toward the goals", "pitch.py", "a_mid = 0.0 if s < 0 else np.pi", "a_mid = np.pi if s < 0 else 0.0"),
    ("line centre is the peak sample, no centroid", "pitch.py", "off = (w * t[None, :]).sum(1) / np.maximum(w.sum(1), 1e-9)", "off = t[j]"),
    ("arc residual sign flipped", "pitch.py", "arc_r = np.linalg.norm(q - cen[i], axis=1) - rad[i]", "arc_r = rad[i] - np.linalg.norm(q - cen[i], axis=1)"),
    ("pitch size never fitted", "pitch.py", "return signed_residuals(q, obs.marking, x[8], x[9], half_line) if fit_size", "return signed_residuals(q, obs.marking, length, width, half_line) if fit_size"),
    ("4-point solve sign error", "pitch.py", "a[2 * i] = (x, y, 1, 0, 0, 0, -u * x, -u * y)", "a[2 * i] = (x, y, 1, 0, 0, 0, u * x, -u * y)"),
    ("failed frames anchor the interpolation", "pitch.py", 'full = interpolate_homographies(table[~table["failed"]], np.arange(1, f + 1))', "full = interpolate_homographies(table, np.arange(1, f + 1))"),
    ("interpolation weight always 0", "pitch.py", "w = 0.0 if a == b else (f - known[a]) / (known[b] - known[a])", "w = 0.0"),
    ("per-frame conversion uses one frame", "pitch.py", "out[sel] = apply_h(hs[int(f)], pts[sel])", "out[sel] = apply_h(hs[int(frames[0])], pts[sel])"),
    ("yaw not taken relative to frame 1", "pitch.py", "yaw = np.degrees(np.angle(np.exp(1j * (ang - ang[0]))))", "yaw = np.degrees(ang)"),
    ("spot on a line measured with the line", "pitch.py", 'line = next((m for m in marks if m.kind == "line" and m.distance([p])[0] <= 0.3), None)', "line = None"),
    ("shrinking warp not area-averaged", "pitch.py", "k = max(1, int(np.ceil(local_scale(np.linalg.inv(t), [(w / 2, h / 2)])[0] - 1e-6)))", "k = 1"),
    ("pitch view ignores the homographies", "render.py", "return self.canvas @ self._h[frame]", "return self.canvas"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Mutation check for flocker.pitch and the pitch view.")
    ap.add_argument("--work", type=Path, required=True, help="scratch folder under the repository's tmp/ for the mutated copies")
    args = ap.parse_args()
    results = []
    for k, (name, fname, old, new) in enumerate(MUTATIONS, 1):
        work = args.work / f"m{k:02d}"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ROOT / "src", work / "src")
        shutil.copytree(ROOT / "tests", work / "tests")
        shutil.copy(ROOT / "pyproject.toml", work / "pyproject.toml")
        target = work / "src" / "flocker" / fname
        text = target.read_text()
        if text.count(old) != 1:
            print(f"m{k:02d} {name}: the text to mutate occurs {text.count(old)} times; fix the list", file=sys.stderr)
            return 2
        target.write_text(text.replace(old, new))
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "unit", "-p", "no:cacheprovider", "tests/test_pitch.py", "tests/test_render.py"], cwd=work, capture_output=True, text=True)
        failed = [line.split(" ")[1] for line in run.stdout.splitlines() if line.startswith("FAILED ")]
        caught = run.returncode != 0
        results.append((name, caught, failed))
        print(f"m{k:02d} {'CAUGHT' if caught else 'MISSED'}  {name}: {', '.join(f.split('::')[-1] for f in failed) or run.stdout.strip().splitlines()[-1]}", flush=True)
    missed = [n for n, c, _ in results if not c]
    print(f"{len(results) - len(missed)} of {len(results)} mutations caught" + (f"; missed: {missed}" if missed else ""))
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
