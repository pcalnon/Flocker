#!/usr/bin/env bash
# Smoke-test scripts/wake_the_claude.bash, scripts/claude_interactive.bash, util/flocker_repo_tmp.bash and the SessionStart hook in
# .claude/settings.json, with a stub claude.
#
# Project:    Flocker
# File:       util/ad-hoc/2026-11-24_launcher_smoke_test.bash
# Author:     Paul Calnon
# Date:       2026-11-24
# Status:     ad-hoc (single use, re-runnable)
# Provenance: Adapted from the articles repo's util/ad-hoc/2026-11-24_launcher_smoke_test.bash, less its --paper cases, 2026-11-24
#
# Usage (the file carries no executable bit, so run it with bash):
#   bash util/ad-hoc/2026-11-24_launcher_smoke_test.bash [--out DIR]                 # this checkout: dry runs and no-worktree runs only
#   bash util/ad-hoc/2026-11-24_launcher_smoke_test.bash [--out DIR] --fixture DIR   # also real worktree runs, in the throwaway repo DIR
#
# Against this checkout, no case creates a worktree or a branch: worktree cases are dry runs, and every stub launch runs without
# one. With --fixture, DIR is a disposable git repo, built here when it does not exist yet (it must be under this checkout's tmp/):
# copies of the launchers, the helper and .claude/settings.json, a .gitignore naming tmp/, worktrees/ and .claude/settings.local.json,
# a gitignored .claude/settings.local.json, branch main free and branch feature/x checked out. Real worktrees are made only there,
# with git's global and system configuration switched off (no hooks, no signing).
# A stub claude first on PATH prints its argv, working directory and temp environment, and exits: no Claude Code session starts.
# This script writes only under --out (default: <checkout>/tmp/launcher-smoke/) and in the fixture. It prints PASS/FAIL per check
# and exits 1 on any FAIL.

REPO="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/../.." && pwd -P)"
SMOKE="${REPO}/tmp/launcher-smoke"
FIXTURE=""
while (( $# > 0 )); do
    case "${1}" in
        --out) SMOKE="${2:?--out needs a directory}" && shift 2 ;;
        --fixture) FIXTURE="${2:?--fixture needs a directory}" && shift 2 ;;
        -h | --help) sed -n '2,23p' "${BASH_SOURCE[0]}" && exit 0 ;;
        *) echo "unknown argument: ${1}" >&2 && exit 2 ;;
    esac
done
mkdir -p "${SMOKE}" || exit 2
SMOKE="$(cd "${SMOKE}" && pwd -P)"
OUT="${SMOKE}/out"
STUB_BIN="${SMOKE}/bin"
# Anything this script starts that wants a temp file gets one here, never in the system temp dir
export TMPDIR="${SMOKE}" TMP="${SMOKE}" TEMP="${SMOKE}"

PASS=0
FAIL=0
declare -a FAILED=()
LAST_LOG=""
mkdir -p "${OUT}" "${STUB_BIN}" "${SMOKE}/sessions" "${SMOKE}/prompts" "${SMOKE}/handoffs" "${SMOKE}/logs" "${SMOKE}/elsewhere"

ok()  { PASS=$((PASS + 1)); echo "PASS  $*"; }
bad() { FAIL=$((FAIL + 1)); FAILED+=("$*"); echo "FAIL  $*"; }

# run NAME WANTED_STATUS DIR CMD...: run CMD in DIR with the stub first on PATH and stdin closed; output to out/NAME.log
run() {
    local name="$1" want="$2" dir="$3"
    shift 3
    LAST_LOG="${OUT}/${name}.log"
    (cd "${dir}" && PATH="${STUB_BIN}:${PATH}" WTC_DEBUG="${RUN_DEBUG:-1}" "$@") > "${LAST_LOG}" 2>&1 < /dev/null
    local got=$?
    if [[ "${got}" == "${want}" ]]; then ok "${name}: exit ${got}"; else bad "${name}: exit ${got}, wanted ${want} (see ${LAST_LOG})"; fi
}
expect() { if grep -q -E -- "$2" "${LAST_LOG}"; then ok "  $1"; else bad "  $1: no /$2/ in ${LAST_LOG##*/}"; fi; }
refute() { if grep -q -E -- "$2" "${LAST_LOG}"; then bad "  $1: found /$2/ in ${LAST_LOG##*/}"; else ok "  $1"; fi; }
count_is() { local n; n="$(grep -c -E -- "$2" "${LAST_LOG}")"; if [[ "${n}" == "$3" ]]; then ok "  $1"; else bad "  $1: /$2/ x${n}, wanted x$3"; fi; }
# expect_fixed NAME FILE LINE: FILE holds LINE, exactly
expect_fixed() { if grep -q -x -F -- "$3" "$2"; then ok "  $1"; else bad "  $1: no line [$3] in ${2##*/}"; fi; }

cat > "${STUB_BIN}/claude" <<'STUB'
#!/usr/bin/env bash
# Stub claude for the launcher smoke test: prints its argv, working directory and temp environment, and exits; starts no session
if [[ "${1:-}" == "--version" ]]; then
    echo "9.9.9 (Claude Code stub)"
    exit 0
fi
echo "STUB argc=$#"
i=0
for arg in "$@"; do
    printf 'STUB argv[%d]=%s\n' "${i}" "${arg//$'\n'/\\n}"
    i=$((i + 1))
done
echo "STUB cwd=${PWD}"
for name in TMPDIR TMP TEMP CLAUDE_CODE_TMPDIR GIT_CEILING_DIRECTORIES; do
    echo "STUB ${name}=${!name-<unset>}"
done
top="$(git rev-parse --show-toplevel 2>/dev/null)"
echo "STUB toplevel=${top}"
if [[ -f "${top}/.claude/settings.local.json" ]]; then echo "STUB settings.local.json=present"; else echo "STUB settings.local.json=absent"; fi
[[ "${STUB_CLAUDE_TOUCH:-}" == "1" ]] && echo "stub" > "${PWD}/stub-was-here.txt"
exit "${STUB_CLAUDE_EXIT:-0}"
STUB
chmod 755 "${STUB_BIN}/claude"

printf 'Summarize the outline.\n---\nfront: matter\n' > "${SMOKE}/prompts/prompt-file.md"
printf 'Continue the review from this handoff.\n' > "${SMOKE}/handoffs/HANDOFF_2026-11-24_smoke-test.md"

WAKE="${REPO}/scripts/wake_the_claude.bash"
INTERACTIVE="${REPO}/scripts/claude_interactive.bash"
HELPER="${REPO}/util/flocker_repo_tmp.bash"
UUID_RE='[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
SETTINGS_JSON_RE="\{\"env\":\{\"CLAUDE_CODE_TMPDIR\":\"${REPO}/tmp\"\}\}"
# The hook writes this text as it stands, for the env file to expand when it is sourced: it must not expand here
# shellcheck disable=SC2016
CEILING_TAIL='${GIT_CEILING_DIRECTORIES:+:$GIT_CEILING_DIRECTORIES}"'
export WTC_SESSIONS_DIR="${SMOKE}/sessions" WTC_LOGS_DIR="${SMOKE}/logs"
unset WTC_PROMPT_DIR_DEFAULT

# What this checkout holds before the run: no case may add a worktree or a branch (read from files, not through git)
list_worktrees() { find "${REPO}/worktrees" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | sort; }
list_branches() { (cd "${REPO}/.git/refs/heads" 2>/dev/null && find . -type f | sort); }
WORKTREES_BEFORE="$(list_worktrees)"
BRANCHES_BEFORE="$(list_branches)"
PRIMARY_BRANCH="$(sed -n 's#^ref: refs/heads/##p' "${REPO}/.git/HEAD" 2>/dev/null)"

echo "== the files carry no executable bit and are no symlinks"
for rel in scripts/wake_the_claude.bash scripts/claude_interactive.bash util/flocker_repo_tmp.bash util/open_signed_pr.py \
           util/ad-hoc/2026-11-24_launcher_smoke_test.bash .claude/settings.json .claude/settings.local.json; do
    if [[ -L "${REPO}/${rel}" ]]; then bad "${rel} is a symlink"
    elif [[ ! -f "${REPO}/${rel}" ]]; then bad "${rel} is missing"
    elif [[ -x "${REPO}/${rel}" ]]; then bad "${rel} is executable"
    else ok "${rel}: a plain, non-executable file"; fi
done

echo "== help, usage and versions"
run wake-help 0 "${REPO}" bash "${WAKE}" --help
expect "wake --help: the usage line says bash scripts/" '^usage: bash scripts/wake_the_claude\.bash$'
expect "wake --help documents --dry-run" '--dry-run:'
expect "wake --help names the worktree naming" 'A new worktree is named Flocker--<branch'
expect "wake --help names the worktrees dir" "worktrees: +${REPO}/worktrees\$"
expect "wake --help has a bash scripts/ example" 'bash scripts/wake_the_claude\.bash --worktree --id 0 --file HANDOFF_'
refute "wake --help has no paper feature" '[Pp]aper'
run wake-help-defaults 0 "${REPO}" env -u WTC_SESSIONS_DIR -u WTC_LOGS_DIR bash "${WAKE}" --help
expect "session-ID files default to the primary's tmp/sessions" "session-ID files: +${REPO}/tmp/sessions\$"
expect "the headless log defaults to the primary's logs/" "headless log: +${REPO}/logs/wake_the_claude\.nohup\.log\$"
expect "handoffs default to prompts/thread-handoff_automated-prompts" "handoff prompts: +${REPO}/prompts/thread-handoff_automated-prompts\$"
run wake-usage 1 "${REPO}" bash "${WAKE}" -u
run wake-no-args 1 "${REPO}" bash "${WAKE}"
run interactive-help 0 "${REPO}" bash "${INTERACTIVE}" --help
expect "claude_interactive --help: the usage line says bash scripts/" '^Usage: bash scripts/claude_interactive\.bash '
expect "claude_interactive --help documents --dry-run" '\[--dry-run\]'
expect "claude_interactive --help has a bash scripts/ example" 'bash scripts/claude_interactive\.bash --worktree --dry-run'
refute "claude_interactive --help has no paper feature" '[Pp]aper'
run wake-script-version 0 "${REPO}" bash "${WAKE}" --script-version
expect "wake script version" 'wake_the_claude\.bash 1\.2\.0'
run interactive-script-version 0 "${REPO}" bash "${INTERACTIVE}" --script-version
expect "claude_interactive script version" '^0\.3\.0$'
run interactive-claude-version 0 "${REPO}" bash "${INTERACTIVE}" --version
expect "claude_interactive --version asks claude, through wake_the_claude.bash run with bash" '9\.9\.9 \(Claude Code stub\)'

echo "== plain interactive"
run wake-plain 0 "${REPO}" bash "${WAKE}" --model opus
expect "runs at the checkout root" "^STUB cwd=${REPO}\$"
expect "model sent" '^STUB argv\[1\]=opus$'
expect "TMPDIR is the primary tmp/" "^STUB TMPDIR=${REPO}/tmp\$"
expect "TMP is the primary tmp/" "^STUB TMP=${REPO}/tmp\$"
expect "TEMP is the primary tmp/" "^STUB TEMP=${REPO}/tmp\$"
expect "CLAUDE_CODE_TMPDIR is the primary tmp/" "^STUB CLAUDE_CODE_TMPDIR=${REPO}/tmp\$"
expect "ceiling starts with the primary tmp/" "^STUB GIT_CEILING_DIRECTORIES=${REPO}/tmp(:|\$)"
expect "--settings pins CLAUDE_CODE_TMPDIR to this repo's tmp/" "^STUB argv\[3\]=${SETTINGS_JSON_RE}\$"
refute "no worktree flag reaches claude" '^STUB argv\[[0-9]+\]=--worktree$'
refute "no --add-dir reaches claude" '^STUB argv\[[0-9]+\]=--add-dir$'
refute "no path into another repository reaches claude" '^STUB (argv\[[0-9]+\]|cwd|TMPDIR|TMP|TEMP|CLAUDE_CODE_TMPDIR)=.*(/Juniper/|/Development/articles)'
run interactive-plain 0 "${REPO}" bash "${INTERACTIVE}" --no-worktree
expect "claude_interactive: runs at the checkout root" "^STUB cwd=${REPO}\$"
expect "claude_interactive: default model opus" '^STUB argv\[[0-9]+\]=opus$'
expect "claude_interactive: default effort max" '^STUB argv\[[0-9]+\]=max$'
expect "claude_interactive: bare --remote-control" '^STUB argv\[[0-9]+\]=--remote-control$'
expect "claude_interactive: DEBUG adds --dangerously-skip-permissions" '^STUB argv\[[0-9]+\]=--dangerously-skip-permissions$'
expect "claude_interactive: default prompt last, after --" '^STUB argv\[[0-9]+\]=Hello World, Claude!$'
expect "claude_interactive: CLAUDE_CODE_TMPDIR is the primary tmp/" "^STUB CLAUDE_CODE_TMPDIR=${REPO}/tmp\$"
refute "claude_interactive --no-worktree: no worktree" '^Worktree:'
refute "claude_interactive: no path into another repository reaches claude" '^STUB (argv\[[0-9]+\]|cwd|TMPDIR|TMP|TEMP|CLAUDE_CODE_TMPDIR)=.*(/Juniper/|/Development/articles)'
RUN_DEBUG=0 run wake-plain-debug 0 "${REPO}" bash "${WAKE}" --model opus
expect "debug output still launches" "^STUB cwd=${REPO}\$"
expect "debug output is written" 'wake_the_claude\.bash: .*Resolve the checkout and the worktree'

echo "== launched from elsewhere"
run wake-from-tmp 0 "${SMOKE}/elsewhere" bash "${WAKE}" --model opus
expect "from a scratch dir inside this checkout: the session runs at the checkout root" "^STUB cwd=${REPO}\$"
expect "  and TMPDIR is the primary tmp/" "^STUB TMPDIR=${REPO}/tmp\$"
run wake-from-outside 0 / bash "${WAKE}" --model opus
expect "from / (in no checkout): the session runs in this checkout" "^STUB cwd=${REPO}\$"
expect "  TMPDIR is this checkout's tmp/" "^STUB TMPDIR=${REPO}/tmp\$"
expect "  CLAUDE_CODE_TMPDIR is this checkout's tmp/" "^STUB CLAUDE_CODE_TMPDIR=${REPO}/tmp\$"
run interactive-dry-from-outside 0 / bash "${INTERACTIVE}" --no-worktree --dry-run
expect "claude_interactive from /: the plan names this checkout" "working directory: +${REPO}\$"
expect "  TMPDIR is this checkout's tmp/" "TMPDIR, TMP, TEMP: +${REPO}/tmp\$"
expect "  CLAUDE_CODE_TMPDIR is this checkout's tmp/" "CLAUDE_CODE_TMPDIR: +${REPO}/tmp\$"

echo "== resume and session ids"
run wake-resume-picker 0 "${REPO}" bash "${WAKE}" --resume 0
expect "--resume 0: Claude Code offers its list" '^STUB argv\[0\]=--resume$'
count_is "--resume 0: nothing after --resume but the --settings pair" '^STUB argv\[' 3
expect "--resume 0: the --settings pair follows" '^STUB argv\[1\]=--settings$'
run wake-resume-uuid 0 "${REPO}" bash "${WAKE}" --resume 7632f5ab-4bac-11e6-bcb7-0cc47a6c4dbd
expect "resume id passed" '^STUB argv\[1\]=7632f5ab-4bac-11e6-bcb7-0cc47a6c4dbd$'
run wake-id-new 0 "${REPO}" bash "${WAKE}" --id 0
expect "--id 0 sends a new session id" "^STUB argv\[1\]=${UUID_RE}\$"
NEW_ID="$(grep -o -E "^STUB argv\[1\]=${UUID_RE}" "${LAST_LOG}" | sed 's/^STUB argv\[1\]=//')"
if [[ ( "${NEW_ID}" != "" ) && ( -f "${SMOKE}/sessions/${NEW_ID}.txt" ) ]]; then ok "  session-ID file written under WTC_SESSIONS_DIR"; else bad "  no session-ID file for ${NEW_ID:-(no id)}"; fi
run wake-resume-file 0 "${REPO}" bash "${WAKE}" --resume "${NEW_ID}.txt"
expect "--resume <id>.txt resolves to the id" "^STUB argv\[1\]=${NEW_ID}\$"
run interactive-resume 0 "${REPO}" bash "${INTERACTIVE}" --resume --no-worktree
expect "claude_interactive --resume: Claude Code offers its list" '^STUB argv\[0\]=--resume$'
run wake-resume-invalid 1 "${REPO}" bash "${WAKE}" --resume not-a-session
refute "an invalid resume never starts claude" '^STUB '

echo "== prompt from a file"
run wake-file 0 "${REPO}" bash "${WAKE}" --file "${SMOKE}/prompts/prompt-file.md"
expect "the file's text is the last argument, after --" '^STUB argv\[3\]=Summarize the outline\.\\n---\\nfront: matter$'
expect "-- precedes it" '^STUB argv\[2\]=--$'
expect "the --settings pair comes first, before --" '^STUB argv\[0\]=--settings$'
run wake-path-and-file 0 "${REPO}" bash "${WAKE}" --path "${SMOKE}/prompts" --file prompt-file.md
expect "--path DIR --file NAME" '^STUB argv\[3\]=Summarize the outline'
run wake-file-default-dir 0 "${SMOKE}/elsewhere" env WTC_PROMPT_DIR_DEFAULT="${SMOKE}/handoffs" bash "${WAKE}" --file HANDOFF_2026-11-24_smoke-test.md
expect "a bare handoff name is read from the default prompt dir" '^STUB argv\[3\]=Continue the review from this handoff\.'
run interactive-file 0 "${REPO}" env WTC_PROMPT_DIR_DEFAULT="${SMOKE}/handoffs" bash "${INTERACTIVE}" --no-worktree --file HANDOFF_2026-11-24_smoke-test.md
expect "claude_interactive: the handoff replaces the default prompt" '^STUB argv\[[0-9]+\]=Continue the review from this handoff\.'
refute "claude_interactive: no default prompt alongside" 'Hello World, Claude!$'
run wake-file-missing 1 "${REPO}" bash "${WAKE}" --file HANDOFF_does-not-exist.md
expect "a missing prompt file is refused" 'no prompt file found'
refute "and claude did not start" '^STUB '

echo "== --dry-run with worktree options (this checkout: nothing may be created)"
run dry-generated 0 "${REPO}" bash "${WAKE}" --worktree --dry-run
expect "a new worktree under the primary's worktrees/, named Flocker--<branch>--<stamp>--<sha8>" "worktree: +create ${REPO}/worktrees/Flocker--worktree--[0-9]{8}-[0-9]{6}--[0-9]{8}-[0-9]{4}--[0-9a-f]{8}\$"
expect "on a generated branch from HEAD" 'worktree branch: +worktree/[0-9]{8}-[0-9]{6}, a new generated branch from HEAD'
expect "working directory is the worktree" "working directory: +${REPO}/worktrees/Flocker--worktree--[^ ]*\$"
expect "TMPDIR stays the primary tmp/" "TMPDIR, TMP, TEMP: +${REPO}/tmp\$"
expect "CLAUDE_CODE_TMPDIR stays the primary tmp/" "CLAUDE_CODE_TMPDIR: +${REPO}/tmp\$"
expect "ceiling names the worktree's own tmp/ too" "GIT_CEILING_DIRECTORIES: +${REPO}/tmp:${REPO}/worktrees/Flocker--[^:]*/tmp"
expect "the argv is printed" '\[0\] .*/claude$'
expect "the argv carries the --settings JSON" "\[[0-9]+\] '${SETTINGS_JSON_RE}'\$"
expect "cleanup is described" 'worktree cleanup: +removed, with its branch'
refute "claude did not start" '^STUB '
run dry-named 0 "${REPO}" bash "${WAKE}" --worktree test/launcher-smoke --dry-run
expect "Flocker--, then the branch's / as --" "worktree: +create ${REPO}/worktrees/Flocker--test--launcher-smoke--[0-9]{8}-[0-9]{4}--[0-9a-f]{8}\$"
expect "a new named branch" 'test/launcher-smoke, a new branch from HEAD'
expect "a named worktree is kept" 'worktree cleanup: +kept'
if [[ "${PRIMARY_BRANCH}" != "" ]]; then
    run dry-checked-out 1 "${REPO}" bash "${WAKE}" --worktree "${PRIMARY_BRANCH}" --dry-run
    expect "the branch checked out in the primary (${PRIMARY_BRANCH}) is refused" "is checked out at ${REPO}"
else
    echo "SKIP  dry-checked-out: the primary's HEAD is not on a branch"
fi
run dry-bad-branch 1 "${REPO}" bash "${WAKE}" --worktree 'bad..name' --dry-run
expect "an invalid branch name is refused" 'nor a valid branch name'
run dry-worktree-off 0 "${REPO}" bash "${WAKE}" --worktree 1 --dry-run
expect "--worktree 1: no worktree" 'worktree: +\(none\)$'
run dry-id-headless 0 "${REPO}" env -u WTC_SESSIONS_DIR -u WTC_LOGS_DIR bash "${WAKE}" --dry-run --id 0 --headless --prompt 'hi there'
expect "the session-ID file is planned under the primary's tmp/sessions" "session-ID file: +${REPO}/tmp/sessions/${UUID_RE}\.txt\$"
PLANNED_ID_FILE="$(grep -o -E "${REPO}/tmp/sessions/${UUID_RE}\.txt" "${LAST_LOG}" | head -n 1)"
if [[ ( "${PLANNED_ID_FILE}" != "" ) && ( ! -e "${PLANNED_ID_FILE}" ) ]]; then ok "  the dry run wrote no session-ID file"; else bad "  the dry run wrote ${PLANNED_ID_FILE:-(nothing planned)}"; fi
expect "headless logs to the primary's logs/, else its tmp/" "mode: +headless: nohup, appending to ${REPO}/logs/wake_the_claude\.nohup\.log \(else ${REPO}/tmp/wake_the_claude\.nohup\.log\)"
run interactive-dry-default 0 "${REPO}" bash "${INTERACTIVE}" --dry-run
expect "claude_interactive's default worktree is planned" "worktree: +create ${REPO}/worktrees/Flocker--worktree--"
expect "claude_interactive's defaults reach the argv" "^    \[[0-9]+\] --dangerously-skip-permissions\$"
expect "the prompt is the last argv word" "^    \[[0-9]+\] 'Hello World, Claude!'\$"
RUN_DEBUG=0 run dry-debug-on 0 "${REPO}" bash "${WAKE}" --dry-run --worktree
expect "the dry run works with debug output on" 'Dry run: nothing is created'

echo "== temp environment"
run env-inherited 0 "${REPO}" env TMPDIR=/home/elsewhere/tmp TMP=/home/elsewhere/tmp CLAUDE_CODE_TMPDIR=/home/elsewhere/tmp GIT_CEILING_DIRECTORIES="/home/elsewhere/tmp:${REPO}/tmp" bash "${WAKE}" --model opus
expect "an inherited TMPDIR is replaced" "^STUB TMPDIR=${REPO}/tmp\$"
expect "an inherited CLAUDE_CODE_TMPDIR is replaced" "^STUB CLAUDE_CODE_TMPDIR=${REPO}/tmp\$"
expect "an inherited ceiling is kept, after this repo's, without a duplicate" "^STUB GIT_CEILING_DIRECTORIES=${REPO}/tmp:/home/elsewhere/tmp\$"
run helper-run 0 "${SMOKE}/elsewhere" bash "${HELPER}"
expect "the helper names the primary tmp/ from inside tmp/" "^${REPO}/tmp\$"
run helper-help 0 "${REPO}" bash "${HELPER}" --help
run helper-usage 2 "${REPO}" bash "${HELPER}" one two
run helper-no-checkout 1 "${SMOKE}/elsewhere" env GIT_CEILING_DIRECTORIES="${SMOKE}" bash "${HELPER}"
expect "outside a checkout the helper refuses" 'is not in a git checkout'

echo "== the SessionStart hook (.claude/settings.json)"
HOOK_CMD="$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["hooks"]["SessionStart"][0]["hooks"][0]["command"])' "${REPO}/.claude/settings.json")"
if [[ "${HOOK_CMD}" == ": flocker-repo-tmpdir;"* ]]; then ok "the hook carries the marker flocker-repo-tmpdir"; else bad "the hook lacks the marker: ${HOOK_CMD:0:40}"; fi
for SHELL_NAME in sh bash; do
    : > "${SMOKE}/hook-${SHELL_NAME}.env"
    run "hook-${SHELL_NAME}-primary" 0 "${SMOKE}/elsewhere" env CLAUDE_ENV_FILE="${SMOKE}/hook-${SHELL_NAME}.env" CLAUDE_PROJECT_DIR="${REPO}" "${SHELL_NAME}" -c "${HOOK_CMD}"
    expect_fixed "the hook (${SHELL_NAME}) exports the primary's tmp/" "${SMOKE}/hook-${SHELL_NAME}.env" \
        "export TMPDIR=\"${REPO}/tmp\" TMP=\"${REPO}/tmp\" TEMP=\"${REPO}/tmp\" GIT_CEILING_DIRECTORIES=\"${REPO}/tmp${CEILING_TAIL}"
done
: > "${SMOKE}/hook-nogit.env"
run hook-no-checkout 0 / env CLAUDE_ENV_FILE="${SMOKE}/hook-nogit.env" CLAUDE_PROJECT_DIR=/ sh -c "${HOOK_CMD}"
if [[ ! -s "${SMOKE}/hook-nogit.env" ]]; then ok "  outside a checkout the hook writes nothing"; else bad "  the hook wrote outside a checkout"; fi
run hook-no-env-file 0 "${REPO}" env -u CLAUDE_ENV_FILE CLAUDE_PROJECT_DIR="${REPO}" sh -c "${HOOK_CMD}"

echo "== outside a git checkout (a copy under the output dir, with a ceiling hiding this repo)"
mkdir -p "${SMOKE}/nogit/scripts" "${SMOKE}/nogit/util"
cp "${WAKE}" "${SMOKE}/nogit/scripts/"
cp "${HELPER}" "${SMOKE}/nogit/util/"
run nogit-help 0 "${SMOKE}" env GIT_CEILING_DIRECTORIES="${SMOKE}" bash "${SMOKE}/nogit/scripts/wake_the_claude.bash" --help
run nogit-launch 1 "${SMOKE}" env GIT_CEILING_DIRECTORIES="${SMOKE}" bash "${SMOKE}/nogit/scripts/wake_the_claude.bash" --model opus
expect "no checkout: refuses to launch" 'is not in a git checkout'
refute "and claude did not start" '^STUB '

echo "== headless (a real nohup run of the stub)"
run headless 0 "${REPO}" bash "${WAKE}" --headless --prompt 'headless smoke'
expect "the nohup line is printed" "^nohup .* >> ${SMOKE}/logs/wake_the_claude\.nohup\.log 2>&1 &\$"
for _ in 1 2 3 4 5 6 7 8 9 10; do
    grep -q -E "^STUB cwd=${REPO}\$" "${SMOKE}/logs/wake_the_claude.nohup.log" 2>/dev/null && break
    sleep 0.5
done
if grep -q -E "^STUB cwd=${REPO}\$" "${SMOKE}/logs/wake_the_claude.nohup.log" 2>/dev/null; then ok "  the headless stub ran at the checkout root, logged to WTC_LOGS_DIR"; else bad "  the headless log lacks the stub's cwd"; fi

echo "== this checkout is unchanged"
if [[ "$(list_worktrees)" == "${WORKTREES_BEFORE}" ]]; then ok "no worktree was added under ${REPO}/worktrees"; else bad "the worktrees dir changed"; fi
if [[ "$(list_branches)" == "${BRANCHES_BEFORE}" ]]; then ok "no branch was added to this checkout"; else bad "the branch list changed"; fi

# make_fixture DIR: a throwaway git repo under this checkout's tmp/, with git's global and system configuration off
make_fixture() {
    local f="$1"
    case "${f}" in
        "${REPO}/tmp/"*) ;;
        *) echo "refusing to build a fixture outside ${REPO}/tmp/: ${f}" >&2 && return 1 ;;
    esac
    mkdir -p "${f}/scripts" "${f}/util" "${f}/.claude" || return 1
    cp "${WAKE}" "${INTERACTIVE}" "${f}/scripts/" && cp "${HELPER}" "${f}/util/" && cp "${REPO}/.claude/settings.json" "${f}/.claude/" || return 1
    printf 'tmp/\nworktrees/\n.claude/settings.local.json\n' > "${f}/.gitignore"
    printf '{\n  "env": {\n    "CLAUDE_CODE_TMPDIR": "%s/tmp"\n  }\n}\n' "${f}" > "${f}/.claude/settings.local.json"
    printf '# Launcher smoke-test fixture: a throwaway repository\n' > "${f}/README.md"
    (
        export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
        git init -q --initial-branch=main "${f}" &&
            git -C "${f}" add -A &&
            git -C "${f}" -c user.name="Launcher Smoke" -c user.email="launcher-smoke@example.invalid" -c commit.gpgsign=false commit -q -m "launcher smoke-test fixture" &&
            git -C "${f}" checkout -q -b feature/x
    )
}

if [[ "${FIXTURE}" != "" ]]; then
    FRESH=0
    if [[ ! -e "${FIXTURE}" ]]; then
        if make_fixture "${FIXTURE}"; then FRESH=1; else bad "could not build the fixture ${FIXTURE}"; fi
    fi
    F="$(cd "${FIXTURE}" && pwd -P)"
    FW="${F}/scripts/wake_the_claude.bash"
    FI="${F}/scripts/claude_interactive.bash"
    FENV=(env GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1)
    echo "== fixture ${F}: another repository, then real worktrees"

    run fx-foreign 0 "${F}" bash "${WAKE}" --model opus
    expect "launched from another repository: the session runs in this checkout" "^STUB cwd=${REPO}\$"
    expect "  with this checkout's tmp/" "^STUB TMPDIR=${REPO}/tmp\$"
    expect "  and no ceiling for the other repository" "^STUB GIT_CEILING_DIRECTORIES=${REPO}/tmp(:|\$)"
    if [[ "${FRESH}" == "1" ]]; then
        if [[ -e "${F}/tmp" ]]; then bad "  the other repository got a tmp/"; else ok "  the other repository got no tmp/"; fi
    fi

    run fx-generated-untouched 0 "${F}" "${FENV[@]}" bash "${FW}" --worktree
    expect "made under the fixture's worktrees/" "^Worktree: ${F}/worktrees/Flocker--worktree--[0-9]{8}-[0-9]{6}--[0-9]{8}-[0-9]{4}--[0-9a-f]{8} "
    expect "claude ran in the worktree" "^STUB cwd=${F}/worktrees/Flocker--worktree--[^/]*\$"
    expect "the gitignored settings were copied in" '^STUB settings.local.json=present$'
    expect "ceiling: primary tmp/, then the worktree's" "^STUB GIT_CEILING_DIRECTORIES=${F}/tmp:${F}/worktrees/Flocker--[^:]*/tmp(:|\$)"
    expect "TMPDIR is the fixture primary's tmp/" "^STUB TMPDIR=${F}/tmp\$"
    expect "CLAUDE_CODE_TMPDIR is the fixture primary's tmp/" "^STUB CLAUDE_CODE_TMPDIR=${F}/tmp\$"
    expect "--settings names the fixture primary's tmp/" "^STUB argv\[[0-9]+\]=\{\"env\":\{\"CLAUDE_CODE_TMPDIR\":\"${F}/tmp\"\}\}\$"
    expect "the untouched worktree was removed" '^Removed the untouched worktree '
    expect "and its branch deleted" '^Deleted its branch worktree/[0-9]{8}-[0-9]{6}'
    MADE="$(sed -n 's/^Worktree: \([^ ]*\) .*/\1/p' "${LAST_LOG}" | head -n 1)"
    if [[ ( "${MADE}" != "" ) && ( ! -e "${MADE}" ) ]]; then ok "  no worktree dir left behind"; else bad "  a worktree dir is left behind: ${MADE:-(none made)}"; fi

    STUB_CLAUDE_TOUCH=1 run fx-generated-touched 0 "${F}" "${FENV[@]}" STUB_CLAUDE_TOUCH=1 bash "${FW}" --worktree
    expect "a touched worktree is kept" "^Worktree kept: ${F}/worktrees/Flocker--worktree--"
    expect "with how to start in it again" 'Start in it again: --worktree worktree/[0-9]{8}-[0-9]{6}'
    KEPT_BRANCH="$(grep -o -E 'branch worktree/[0-9]{8}-[0-9]{6}(-[0-9]+)?' "${LAST_LOG}" | head -n 1 | sed 's/^branch //')"
    KEPT_DIR="$(grep -o -E '^Worktree kept: [^ ]+' "${LAST_LOG}" | sed 's/^Worktree kept: //')"
    if [[ ( "${KEPT_DIR}" != "" ) && ( -d "${KEPT_DIR}" ) ]]; then ok "  the kept worktree exists"; else bad "  kept worktree missing: ${KEPT_DIR}"; fi

    run fx-reuse-branch 0 "${F}" "${FENV[@]}" bash "${FW}" --worktree "${KEPT_BRANCH}"
    expect "--worktree <its branch> reuses it" "^STUB cwd=${KEPT_DIR}\$"
    expect "and keeps it" '^Worktree kept: '
    run fx-reuse-dir 0 "${F}" "${FENV[@]}" bash "${FW}" --worktree "$(basename "${KEPT_DIR}")"
    expect "--worktree <its directory name> reuses it" "^STUB cwd=${KEPT_DIR}\$"
    run fx-from-inside 0 "${KEPT_DIR}/scripts" "${FENV[@]}" bash "${FW}" --model opus
    expect "launched inside a worktree with no --worktree: that worktree is the checkout" "^STUB cwd=${KEPT_DIR}\$"
    expect "  its tmp/ joins the ceiling" "^STUB GIT_CEILING_DIRECTORIES=${F}/tmp:${KEPT_DIR}/tmp(:|\$)"
    expect "  TMPDIR is still the primary's tmp/" "^STUB TMPDIR=${F}/tmp\$"
    run fx-from-inside-new 0 "${KEPT_DIR}" "${FENV[@]}" bash "${FW}" --worktree --dry-run
    expect "a new worktree from inside one still goes under the primary's worktrees/" "worktree: +create ${F}/worktrees/Flocker--worktree--"
    run fx-helper-in-worktree 0 "${KEPT_DIR}" bash "${F}/util/flocker_repo_tmp.bash"
    expect "the helper names the primary's tmp/ from a worktree" "^${F}/tmp\$"
    : > "${SMOKE}/hook-worktree.env"
    run fx-hook-worktree 0 "${KEPT_DIR}" env CLAUDE_ENV_FILE="${SMOKE}/hook-worktree.env" CLAUDE_PROJECT_DIR="${KEPT_DIR}" sh -c "${HOOK_CMD}"
    expect_fixed "the hook in a worktree exports the primary's tmp/ and adds the worktree's tmp/ to the ceiling" "${SMOKE}/hook-worktree.env" \
        "export TMPDIR=\"${F}/tmp\" TMP=\"${F}/tmp\" TEMP=\"${F}/tmp\" GIT_CEILING_DIRECTORIES=\"${F}/tmp:${KEPT_DIR}/tmp${CEILING_TAIL}"

    run fx-named 0 "${F}" "${FENV[@]}" bash "${FW}" --worktree test/launcher-smoke
    expect "a named new branch gets its worktree" "^Worktree: ${F}/worktrees/Flocker--test--launcher-smoke--[0-9]{8}-[0-9]{4}--[0-9a-f]{8} "
    expect "a named worktree is kept" '^Worktree kept: '
    run fx-existing 0 "${F}" "${FENV[@]}" bash "${FW}" --worktree main
    expect "an existing free branch is checked out in a new worktree" "^STUB cwd=${F}/worktrees/Flocker--main--[0-9]{8}-[0-9]{4}--[0-9a-f]{8}\$"
    run fx-checked-out 1 "${F}" "${FENV[@]}" bash "${FW}" --worktree feature/x
    expect "the primary's branch is refused" "is checked out at ${F}"
    run fx-interactive-default 0 "${F}" "${FENV[@]}" bash "${FI}"
    expect "claude_interactive makes a worktree by default" "^Worktree: ${F}/worktrees/Flocker--worktree--"
    expect "  and removes it, left untouched" '^Removed the untouched worktree '

    mkdir -p "${SMOKE}/read-only-logs" && chmod 555 "${SMOKE}/read-only-logs"
    run fx-headless-fallback 0 "${F}" "${FENV[@]}" WTC_LOGS_DIR="${SMOKE}/read-only-logs" bash "${FW}" --headless --prompt 'fallback smoke'
    chmod 755 "${SMOKE}/read-only-logs"
    expect "a logs dir that cannot be written falls back to the primary's tmp/" "^nohup .* >> ${F}/tmp/wake_the_claude\.nohup\.log 2>&1 &\$"
fi

echo
echo "PASS: ${PASS}   FAIL: ${FAIL}"
if (( FAIL > 0 )); then
    printf '  failed: %s\n' "${FAILED[@]}"
    exit 1
fi
exit 0
