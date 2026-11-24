"""
Open a PR on Flocker (or another repo) whose commit is GitHub-signed (createCommitOnBranch).

Project: Flocker
Sub-Project: repository tooling
Author: Paul Calnon
Created: 2026-11-24
Status: permanent utility
Provenance: Flocker's copy of juniper-ml util/open_signed_pr.py (juniper-ml main @ d7709ef7, where the file
            last changed in e8a61490), 2026-11-24. The defaults now name pcalnon/Flocker; nothing else changed
            functionally. The original's hermetic tests (tests/test_open_signed_pr.py) stay in juniper-ml.

Why this exists
---------------
Commits here are signed, and the signing key lives on a YubiKey: a local ``git commit`` cannot
sign without someone touching the key, so a headless session cannot sign one. The portable way
to produce a signed commit without a key is the GraphQL ``createCommitOnBranch`` mutation:
GitHub signs commits authored through its API.

That also makes this the way to land a change without a working tree. It opens the branch, the
signed commit, and the PR in three API calls, so a session confined to one worktree, or one that
must not touch a checkout another session is committing in, can still land a change.

Usage
-----
    python3 util/open_signed_pr.py \\
        --branch docs/launcher-notes \\
        --add /local/path/notes.md:notes/FLOCKER_2026-11-24_LAUNCHER-NOTES.md \\
        --message "docs(notes): launcher notes" \\
        --title "docs(notes): launcher notes" \\
        --body-file /local/path/body.md \\
        [--delete path/to/remove] [--base main] [--owner pcalnon] [--repo Flocker] [--dry-run]

``--owner`` defaults to ``pcalnon`` and ``--repo`` to ``Flocker``. ``--add`` is repeatable
(LOCAL_PATH:REPO_PATH) and ``--delete`` is repeatable (REPO_PATH); together they express a file
move. At least one of the two is required. Exit 0 = PR opened (or --dry-run), 1 = refused (dup
PR / branch exists), 2 = hard error.

Safety contract
---------------
* Refuses when an open PR already exists for the branch (concurrent sessions are
  a real hazard) and when the branch already exists -- it never force-updates
  someone else's ref.
* ``expectedHeadOid`` is pinned to the resolved base sha, so a concurrent push
  makes the mutation fail loudly rather than clobber.
* ``--dry-run`` performs the read-only resolution and prints the plan; it creates
  no branch, no commit and no PR.

The GraphQL request body and the PR body pass through short-lived files from ``tempfile``,
which follows ``TMPDIR``: run this where TMPDIR names the repo's own tmp/, as a Flocker
session started by scripts/claude_interactive.bash, or under .claude/settings.json's
SessionStart hook, does.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile

CREATE_COMMIT_MUTATION = "mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) { commit { oid url } } }"


class GhError(RuntimeError):
    """A ``gh`` invocation failed or returned something unusable."""


def gh(args: list, check: bool = True) -> str:
    """Run ``gh`` and return stdout. Raises GhError on nonzero exit."""
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} -> exit {proc.returncode}\n{proc.stderr.strip()}")
    return proc.stdout


def resolve_base_sha(owner: str, repo: str, base: str) -> str:
    out = gh(["api", f"repos/{owner}/{repo}/git/ref/heads/{base}", "--jq", ".object.sha"])
    sha = out.strip()
    if not sha:
        raise GhError(f"could not resolve {owner}/{repo}@{base}")
    return sha


def branch_exists(owner: str, repo: str, branch: str) -> bool:
    proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/git/ref/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def create_branch(owner: str, repo: str, branch: str, sha: str) -> None:
    # Explicit ref= is mandatory: an omitted or empty ref must never be left
    # to the live API's default.
    gh(
        [
            "api",
            f"repos/{owner}/{repo}/git/refs",
            "-X",
            "POST",
            "-f",
            f"ref=refs/heads/{branch}",
            "-f",
            f"sha={sha}",
        ]
    )


def create_signed_commit(owner: str, repo: str, branch: str, message: str, additions: list, expected_head_oid: str, deletions: "list | None" = None, commit_body: "str | None" = None) -> str:
    """Land ``additions`` (and any ``deletions``) as ONE GitHub-signed commit on ``branch``.

    The whole CreateCommitOnBranchInput goes through as a single ``$input`` object
    via a JSON request body, because ``gh api graphql -f k=v`` can only pass scalars
    and ``fileChanges.additions`` is a list.

    ``deletions`` is omitted from the payload entirely when empty rather than sent
    as ``[]``, keeping the request byte-identical to the additions-only form.

    ``commit_body`` fills the message BODY. Without it this helper could only set a
    headline, so it could not carry a **commit trailer**. Since this script is the
    headless way to land a signed commit at all, "no body" would mean "no trailer".
    A trailer must live in a commit message rather than PR prose because it has to
    survive the squash-merge, and it must be in the FIRST commit because squash
    keeps only that message.
    """
    file_changes: dict = {"additions": [{"path": path, "contents": contents} for path, contents in additions]}
    if deletions:
        file_changes["deletions"] = [{"path": path} for path in deletions]
    body = {
        "query": CREATE_COMMIT_MUTATION,
        "variables": {
            "input": {
                "branch": {"repositoryNameWithOwner": f"{owner}/{repo}", "branchName": branch},
                "message": ({"headline": message, "body": commit_body} if commit_body else {"headline": message}),
                "expectedHeadOid": expected_head_oid,
                "fileChanges": file_changes,
            }
        },
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as fh:
        json.dump(body, fh)
        body_path = fh.name
    try:
        out = gh(["api", "graphql", "--input", body_path])
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            # Best-effort cleanup of our own tempfile; the commit either landed
            # or failed already and a stray temp file must not mask that.
            pass
    try:
        data = json.loads(out) if out else {}
    except ValueError as exc:
        raise GhError(f"createCommitOnBranch returned non-JSON for {repo}") from exc
    if data.get("errors"):
        raise GhError(f"createCommitOnBranch failed for {repo}: {data['errors']}")
    commit = (((data.get("data") or {}).get("createCommitOnBranch") or {}).get("commit") or {})
    if not commit.get("oid"):
        raise GhError(f"createCommitOnBranch returned no commit oid for {repo}")
    return commit["oid"]


def find_open_pr(owner: str, repo: str, branch: str) -> str:
    out = gh(
        ["pr", "list", "--repo", f"{owner}/{repo}", "--head", branch, "--state", "open", "--json", "url", "--jq", ".[0].url"],
        check=False,
    )
    return out.strip()


def parse_add(spec: str) -> tuple:
    local, sep, repo_path = spec.partition(":")
    if not sep or not local or not repo_path:
        raise argparse.ArgumentTypeError(f"--add expects LOCAL_PATH:REPO_PATH, got {spec!r}")
    return (local, repo_path)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", default="pcalnon", help="repository owner (default: %(default)s)")
    ap.add_argument("--repo", default="Flocker", help="repository name (default: %(default)s)")
    ap.add_argument("--base", default="main")
    ap.add_argument("--branch", required=True)
    ap.add_argument("--add", action="append", default=[], type=parse_add, metavar="LOCAL:REPOPATH")
    ap.add_argument("--delete", action="append", default=[], metavar="REPOPATH", help="repo path to delete in the same commit (repeatable)")
    ap.add_argument("--message", required=True, help="commit headline")
    ap.add_argument(
        "--commit-body",
        default=None,
        help="commit message BODY -- put commit trailers here, not in the PR "
        "description; a trailer must survive squash-merge",
    )
    ap.add_argument(
        "--commit-body-file",
        default=None,
        help="read the commit message body from a file (mutually exclusive with --commit-body)",
    )
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.add and not args.delete:
        print("ERROR: nothing to commit -- pass at least one --add or --delete.", file=sys.stderr)
        return 2

    additions = []
    for local, repo_path in args.add:
        try:
            with open(local, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"ERROR: cannot read {local}: {exc}", file=sys.stderr)
            return 2
        additions.append((repo_path, base64.b64encode(raw).decode("ascii")))

    if args.commit_body and args.commit_body_file:
        print("ERROR: --commit-body and --commit-body-file are mutually exclusive", file=sys.stderr)
        return 2
    commit_body = args.commit_body
    if args.commit_body_file:
        try:
            with open(args.commit_body_file, encoding="utf-8") as fh:
                commit_body = fh.read()
        except OSError as exc:
            print(f"ERROR: cannot read --commit-body-file {args.commit_body_file}: {exc}", file=sys.stderr)
            return 2

    try:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    except OSError as exc:
        print(f"ERROR: cannot read --body-file {args.body_file}: {exc}", file=sys.stderr)
        return 2

    slug = f"{args.owner}/{args.repo}"
    try:
        existing = find_open_pr(args.owner, args.repo, args.branch)
        if existing:
            print(f"DUP-GUARD: an open PR already exists for {slug}:{args.branch} -> {existing}")
            return 1

        base_sha = resolve_base_sha(args.owner, args.repo, args.base)

        if args.dry_run:
            print(f"DRY-RUN {slug}")
            print(f"  base   {args.base} @ {base_sha}")
            print(f"  branch {args.branch}")
            for repo_path, contents in additions:
                print(f"  add    {repo_path} ({len(base64.b64decode(contents))} bytes)")
            for repo_path in args.delete:
                print(f"  delete {repo_path}")
            print(f"  commit {args.message}")
            if commit_body:
                print("  commit body:")
                for line in commit_body.splitlines():
                    print(f"    {line}")
            print(f"  title  {args.title}")
            print("  (nothing written)")
            return 0

        if branch_exists(args.owner, args.repo, args.branch):
            print(f"REFUSED: branch {args.branch} already exists on {slug}; delete it or pick another name.")
            return 1
        create_branch(args.owner, args.repo, args.branch, base_sha)

        oid = create_signed_commit(
            args.owner, args.repo, args.branch, args.message, additions, base_sha, args.delete, commit_body
        )
        print(f"signed commit {oid[:12]} on {slug}:{args.branch}")

        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as fh:
            fh.write(body)
            body_path = fh.name
        try:
            url = gh(
                [
                    "pr", "create",
                    "--repo", slug,
                    "--base", args.base,
                    "--head", args.branch,
                    "--title", args.title,
                    "--body-file", body_path,
                ]
            ).strip()
        finally:
            try:
                os.unlink(body_path)
            except OSError as exc:
                print(f"WARNING: failed to remove temporary body file {body_path}: {exc}", file=sys.stderr)
        print(f"PR: {url}")
        return 0
    except GhError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
