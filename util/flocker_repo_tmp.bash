#!/usr/bin/env bash
# Print Flocker's temp root -- the PRIMARY checkout's gitignored tmp/ -- creating it.
#
# Project:     Flocker
# File:        util/flocker_repo_tmp.bash
# Author:      Paul Calnon
# Date:        2026-11-24
# Status:      permanent utility
# Provenance:  Adapted from juniper-ml util/juniper_repo_tmp.bash (juniper-ml main @ d7709ef7) and the articles repo's
#              util/articles_repo_tmp.bash, 2026-11-24
# Related:     scripts/wake_the_claude.bash (sources it); .claude/settings.json (the SessionStart hook gives the same answer)
#
# No file is ever written under the system temp directory. On the Linux host it is a tmpfs that
# systemd-tmpfiles-clean ages daily, deleting files a live process still uses, and a reboot empties
# it. This repo writes its temp files to its own gitignored tmp/ instead. This helper names that
# directory for a path, so a script can keep state another process must find (pid files, run dirs,
# session files) at a FIXED path derived from where the script lives -- never from TMPDIR.
#
# The PRIMARY checkout's tmp/, not a linked worktree's: a worktree is removed when its task ends,
# the primary is not. The primary is the directory holding the checkout's common .git, which
# `git rev-parse --git-common-dir` names from the primary and from every worktree alike. When the
# common git dir is not a .git directory (a submodule, a --separate-git-dir clone), the checkout's
# own top level stands in.
#
# Usage, run (the file carries no executable bit, so run it with bash):
#   bash util/flocker_repo_tmp.bash [DIR]   # prints the primary checkout's tmp/; DIR defaults to $PWD
# Usage, sourced (defines the two functions; sets no shell option):
#   source util/flocker_repo_tmp.bash
#   flocker_repo_primary [DIR]              # prints the primary checkout's root; creates nothing
#   flocker_repo_tmp [DIR]                  # prints the primary checkout's tmp/, creating it
#
# Exit codes (each function, and the run form):
#   0 -- the path was printed
#   1 -- DIR is in no git checkout (or git is missing), or tmp/ cannot be created; the reason goes
#        to stderr and nothing goes to stdout
#   2 -- the run form only: a usage error
#
# GIT_DIR, GIT_WORK_TREE and GIT_COMMON_DIR are ignored, because the answer is the checkout that
# holds DIR. Written for bash 3.2 too (macOS /bin/bash).

flocker_repo_primary() {
    local dir="${1:-$PWD}" common="" top=""
    common="$(unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR; git -C "$dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || common=""
    case "$common" in
        */.git)
            top="${common%/.git}"
            ;;
        *)
            top="$(unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR; git -C "$dir" rev-parse --show-toplevel 2>/dev/null)" || top=""
            ;;
    esac
    # A checkout at / would make its tmp/ the very directory this helper exists to avoid.
    if [ -z "$top" ] || [ "$top" = "/" ]; then
        echo "flocker_repo_tmp: ${dir} is not in a git checkout" >&2
        return 1
    fi
    printf '%s\n' "$top"
}

flocker_repo_tmp() {
    local primary=""
    primary="$(flocker_repo_primary "${1:-$PWD}")" || return 1
    if ! mkdir -p "${primary}/tmp" 2>/dev/null; then
        echo "flocker_repo_tmp: cannot create ${primary}/tmp" >&2
        return 1
    fi
    printf '%s/tmp\n' "$primary"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    set -euo pipefail
    case "${1:-}" in
        -h | --help)
            echo "usage: bash ${0##*/} [DIR]   # print the primary checkout's tmp/ for DIR (default: \$PWD), creating it"
            exit 0
            ;;
    esac
    if [ "$#" -gt 1 ]; then
        echo "usage: bash ${0##*/} [DIR]" >&2
        exit 2
    fi
    flocker_repo_tmp "${1:-$PWD}"
fi
