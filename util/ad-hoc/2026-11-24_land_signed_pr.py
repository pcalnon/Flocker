#!/usr/bin/env python3
"""Open one GitHub-signed PR on Flocker from a list of repo-relative paths.

Single-use helper for the 2026-11-24 repository-setup work arc. It builds the argument list for
open_signed_pr.py, which makes GitHub-signed commits through GraphQL createCommitOnBranch, from a
file of repo-relative paths. Long upload lists then never have to be typed on a command line.

Why the API: local `git commit` cannot sign in a headless session on this host, because the
signing key lives on a YubiKey that needs a touch. GitHub signs commits made through its API.
The API cannot record file modes or symlinks: every uploaded file lands as a regular 100644 file.

Usage:
    python3 util/ad-hoc/2026-11-24_land_signed_pr.py --branch BRANCH --paths-file LIST \\
        --message SUBJECT --commit-body-file FILE --title TITLE --body-file FILE \\
        [--delete-file LIST] [--tool PATH] [--base main] [--dry-run]

LIST holds one repo-relative path per line; blank lines and lines starting with # are skipped.
Each path is uploaded from this checkout to the same path in the repository. --tool defaults to
this repository's util/open_signed_pr.py.
"""

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_TOOL = ROOT / "util" / "open_signed_pr.py"


def read_list(path):
    lines = pathlib.Path(path).read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--branch", required=True)
    ap.add_argument("--paths-file", required=True, help="repo-relative paths to upload, one per line")
    ap.add_argument("--delete-file", help="repo-relative paths to delete, one per line")
    ap.add_argument("--message", required=True, help="commit subject")
    ap.add_argument("--commit-body-file", required=True)
    ap.add_argument("--title", required=True, help="PR title")
    ap.add_argument("--body-file", required=True, help="PR description (markdown)")
    ap.add_argument("--base", default="main")
    ap.add_argument("--tool", default=str(DEFAULT_TOOL), help="path to open_signed_pr.py")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    paths = read_list(args.paths_file)
    missing = [rel for rel in paths if not (ROOT / rel).is_file()]
    if missing:
        sys.exit(f"not a file in this checkout: {missing}")

    argv = [sys.executable, args.tool, "--owner", "pcalnon", "--repo", "Flocker", "--base", args.base,
            "--branch", args.branch, "--message", args.message, "--commit-body-file", args.commit_body_file,
            "--title", args.title, "--body-file", args.body_file]
    for rel in paths:
        argv += ["--add", f"{ROOT / rel}:{rel}"]
    for rel in read_list(args.delete_file) if args.delete_file else []:
        argv += ["--delete", rel]
    if args.dry_run:
        argv.append("--dry-run")

    print(f"{len(paths)} path(s) to upload -> branch {args.branch} on pcalnon/Flocker (base {args.base})", flush=True)
    return subprocess.call(argv)


if __name__ == "__main__":
    sys.exit(main())
