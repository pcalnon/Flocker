#!/usr/bin/env bash
#####################################################################################################################################################################################################################################
# Project:    Flocker
# Script:     claude_interactive
# File:       scripts/claude_interactive.bash
# Author:     Paul Calnon
# Date:       2026-11-24
# Version:    0.3.0
# Provenance: Adapted from juniper-ml scripts/claude_interactive.bash (version 0.2.0; juniper-ml main @ d7709ef7), by way of the articles
#             repo's adaptation of it (scripts/claude_interactive.bash, version 0.3.0), less that adaptation's --paper feature, 2026-11-24
#####################################################################################################################################################################################################################################
# Description:
#     Interactively launch a Claude Code session, through wake_the_claude.bash, by default in a new git worktree under the primary
#     checkout's worktrees/
#
# Usage (the file carries no executable bit: run it with bash, from any directory):
#    bash scripts/claude_interactive.bash [-m <model>] [-e <effort>] [-p <prompt> | -f <prompt file> | -l <prompt file> | -l <directory> -f <file name>] [--dry-run] [...]
#
# Example:
#    bash scripts/claude_interactive.bash -m fable -e auto
#    bash scripts/claude_interactive.bash --file prompts/thread-handoff_automated-prompts/HANDOFF_<...>.md
#
#####################################################################################################################################################################################################################################
# Notes:
#
#     This script is a wrapper for the wake_the_claude.bash script.
#     It is used to interactively launch a Claude Code session.
#
#     export USAGE_MESSAGE="Usage: ${WAKE_THE_CLAUDE_SCRIPT_NAME} [<model alias: ${MODEL_FABLE_ALIAS}|${MODEL_OPUS_ALIAS}|${MODEL_SONNET_ALIAS}|${MODEL_HAIKU_ALIAS}>] [<effort: ${AUTO}|${MAX}|${XHIGH}|${HIGH}|${MEDIUM}|${LOW}>] [<id: ${TRUE}|${FALSE}>] [<resume: ${TRUE}|${FALSE}>] [<worktree: ${TRUE}|${FALSE}>] [<remote-control: ${TRUE}|${FALSE}>] [<skip-permissions: ${TRUE}|${FALSE}>] [<prompt: 'your prompt here'>]"
#     CLAUDE_MODEL="${1}" && shift
#     CLAUDE_EFFORT="${1}" && shift || true
#     CLAUDE_ID="${1}" && shift || true
#     CLAUDE_WORKTREE="${1}" && shift || true
#     CLAUDE_RESUME="${1}" && shift || true
#     CLAUDE_REMOTE_CONTROL="${1}" && shift || true
#     CLAUDE_SKIP_PERMISSIONS="${1}" && shift || true
#     CLAUDE_PROMPT="${1}" && shift || true
#
########################################################################################################################################################################################################


########################################################################################################################################################################################################
# Define Script Global Constants
########################################################################################################################################################################################################
export TRUE="0"
export FALSE="1"

export DEBUG="${TRUE}"
# export DEBUG="${FALSE}"

export SCRIPT_VERSION="0.3.0"


########################################################################################################################################################################################################
# Define Script Environment Constants
########################################################################################################################################################################################################
SCRIPT_NAME="$(basename "$(realpath "${BASH_SOURCE[0]}")")"
export SCRIPT_NAME

SCRIPT_PATH="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
export SCRIPT_PATH


########################################################################################################################################################################################################
# Define Script Constants for Wake The Claude script
########################################################################################################################################################################################################
export WAKE_THE_CLAUDE_SCRIPT_NAME="wake_the_claude.bash"
export WAKE_THE_CLAUDE_SCRIPT="${SCRIPT_PATH}/${WAKE_THE_CLAUDE_SCRIPT_NAME}"


########################################################################################################################################################################################################
# Define Claude Code Command Line Flags for Interactive Session Arguments
########################################################################################################################################################################################################
export CLAUDE_SKIP_PERMISSIONS_FLAG="--dangerously-skip-permissions"
export CLAUDE_REMOTE_CONTROL_FLAG="--remote-control"
export CLAUDE_WORKTREE_FLAG="--worktree"
export CLAUDE_PROMPT_FLAG="--prompt"
export CLAUDE_PROMPT_FILE_FLAG="--file"
export CLAUDE_PROMPT_PATH_FLAG="--path"
export CLAUDE_VERSION_FLAG="--version"
export CLAUDE_RESUME_FLAG="--resume"
export CLAUDE_EFFORT_FLAG="--effort"
export CLAUDE_MODEL_FLAG="--model"
export CLAUDE_SEPERATOR_FLAG="--"
export CLAUDE_ID_FLAG="--id"
# wake_the_claude.bash's own flag, which it never sends to Claude Code
export CLAUDE_DRY_RUN_FLAG="--dry-run"


########################################################################################################################################################################################################
# Define Script Constants for Claude Code interaction
########################################################################################################################################################################################################
export MODEL_FABLE_NAME="claude-fable-5"
export MODEL_OPUS_NAME="claude-opus-5"
export MODEL_SONNET_NAME="claude-sonnet-4-6"
export MODEL_HAIKU_NAME="claude-haiku-4-5"

export MODEL_FABLE_ALIAS="fable"
export MODEL_OPUS_ALIAS="opus"
export MODEL_SONNET_ALIAS="sonnet"
export MODEL_HAIKU_ALIAS="haiku"

export AUTO="auto"
export MAX="max"
export XHIGH="xhigh"
export HIGH="high"
export MEDIUM="medium"
export LOW="low"


########################################################################################################################################################################################################
# Define Script Defaults
########################################################################################################################################################################################################
# export DEFAULT_MODEL="${MODEL_FABLE_ALIAS}"
export DEFAULT_MODEL="${MODEL_OPUS_ALIAS}"

# export DEFAULT_EFFORT="${AUTO}"
# export DEFAULT_EFFORT="${HIGH}"
export DEFAULT_EFFORT="${MAX}"

export DEFAULT_ID="${FALSE}"
export DEFAULT_RESUME="${FALSE}"
# Worktree and remote control are ON by default (Overtoad ruling, 2026-11-04): a bare --worktree, so wake_the_claude.bash makes a worktree
# under the primary checkout's worktrees/ on a generated branch (Claude Code's own --worktree would put it under .claude/worktrees/), and
# a bare --remote-control, which never takes a value. --no-worktree / --no-remote-control, or CLAUDE_WORKTREE / CLAUDE_REMOTE_CONTROL set
# to ${FALSE}, turn them off.
export DEFAULT_WORKTREE="${TRUE}"
export DEFAULT_REMOTE_CONTROL="${TRUE}"
export DEFAULT_SKIP_PERMISSIONS="${FALSE}"

export DEFAULT_PROMPT="Hello World, Claude!"


########################################################################################################################################################################################################
# Define Usage Message
########################################################################################################################################################################################################
export USAGE_MESSAGE_PREFIX="Usage: bash scripts/${SCRIPT_NAME}"

export USAGE_MESSAGE_MODEL="[--model-alias|--model|-m <${MODEL_FABLE_ALIAS}|${MODEL_OPUS_ALIAS}|${MODEL_SONNET_ALIAS}|${MODEL_HAIKU_ALIAS}>]"
export USAGE_MESSAGE_EFFORT="[--effort-level|--effort|-e <${AUTO}|${MAX}|${XHIGH}|${HIGH}|${MEDIUM}|${LOW}>]"
export USAGE_MESSAGE_ID="[--session-id|--session|--id|-s|-i <SESSION_ID|${FALSE}>]"
export USAGE_MESSAGE_WORKTREE="[--worktree-name|--worktree|-w [BRANCH|WORKTREE_DIR|${TRUE}|${FALSE}]] [--no-worktree]"
export USAGE_MESSAGE_DRY_RUN="[--dry-run]"
export USAGE_MESSAGE_RESUME="[--resume-session|--resume|-rs|-r]"
export USAGE_MESSAGE_REMOTE_CONTROL="[--remote-control-session|--remote-control|-rc] [--no-remote-control]"
export USAGE_MESSAGE_SKIP_PERMISSIONS="[--dangerously-skip-permissions|--skip-permissions|-sp]"
# A prompt, or a prompt file instead -- never both: --file names the file; --path names the file, or, with --file, the directory holding it
export USAGE_MESSAGE_PROMPT_FILE="[--file-name|--file|-f <PROMPT_FILE>] [--file-path|--path|-l <PROMPT_FILE, or with --file its DIRECTORY>]"
export USAGE_MESSAGE_PROMPT="[--initial-prompt|--prompt|-p <YOUR_INITIAL_PROMPT_HERE> | ${USAGE_MESSAGE_PROMPT_FILE}]"
export USAGE_MESSAGE_VERSION="[--version|--claude-version|-v|-V] [--script-version]"
export USAGE_MESSAGE_HELP="[--help|-h|-?]"

export USAGE_MESSAGE="${USAGE_MESSAGE_PREFIX} ${USAGE_MESSAGE_MODEL} ${USAGE_MESSAGE_EFFORT} ${USAGE_MESSAGE_ID} ${USAGE_MESSAGE_RESUME} ${USAGE_MESSAGE_WORKTREE} ${USAGE_MESSAGE_REMOTE_CONTROL} ${USAGE_MESSAGE_SKIP_PERMISSIONS} ${USAGE_MESSAGE_PROMPT} ${USAGE_MESSAGE_DRY_RUN} ${USAGE_MESSAGE_VERSION} ${USAGE_MESSAGE_HELP}"

# What the worktree and dry-run flags do, and examples; wake_the_claude.bash --help documents every flag in full
USAGE_DETAILS="$(cat <<USAGE_DETAILS_TEXT
  --worktree [BRANCH]   On by default. Start in a git worktree under <primary checkout>/worktrees/, named
                        Flocker--<branch, / as -->--<YYYYMMDD-HHMM>--<first 8 of its HEAD sha>. No BRANCH: a generated
                        branch, worktree/<YYYYMMDD-HHMMSS>, from the current checkout's HEAD; a worktree that session leaves
                        untouched is removed when it ends. BRANCH: that branch's worktree under worktrees/ when it has one,
                        else a new worktree on it (made from HEAD when the branch is new); a branch checked out anywhere
                        else is refused. A worktree directory name under worktrees/ starts in that worktree.
  --no-worktree         Run in the current checkout (the primary, or the worktree you are in).
  --dry-run             Print the plan -- checkout, working directory, worktree path and branch, TMPDIR, CLAUDE_CODE_TMPDIR,
                        GIT_CEILING_DIRECTORIES and the full claude argv -- and exit ${TRUE}, creating nothing.

  The session's temp files, Claude Code's own included, go to the primary checkout's tmp/, never to the system temp dir.

  Examples:
    bash scripts/claude_interactive.bash
    bash scripts/claude_interactive.bash --worktree --dry-run
    bash scripts/claude_interactive.bash --no-worktree --file HANDOFF_2026-11-24_<description>.md
                        (a --file name found nowhere else is read from prompts/thread-handoff_automated-prompts/)
USAGE_DETAILS_TEXT
)"
export USAGE_DETAILS


########################################################################################################################################################################################################
# Define Usage Message and Exit
########################################################################################################################################################################################################
function usage {
    local exit_code="${1:-1}"
    local message="${2}"

    [[ "${message}" != "" ]] && echo -ne "\n${message}\n\n" || true
    echo -ne "${USAGE_MESSAGE}\n\n" || true
    printf '%s\n\n' "${USAGE_DETAILS}" || true
    set -e
    exit "${exit_code}"
}

# A flag that takes a value must be given one: "shift 2" fails on a missing value, and the parse loop below then never ends.
function require_value {
    (( $# >= 2 )) || usage 1 "Missing value for ${1}"
}

# A prompt file flag must name something: an empty value, such as -f "${HANDOFF}" with HANDOFF unset, would otherwise launch with the
# default prompt in place of the file.
function require_nonempty_value {
    require_value "${@}"
    [[ "${2}" != "" ]] || usage 1 "Missing value for ${1}"
}

# -v, -V, --version and --claude-version report Claude Code's version, as `claude -v` does, through wake_the_claude.bash; this script's
# own version is --script-version (Overtoad ruling, 2026-11-06). Until then -v and --version printed this script's version.
function claude_code_version {
    # Without wake_the_claude.bash's debug log, unless the caller asks for it: stdout is then the version line alone. Run with bash:
    # no file in this repo carries an executable bit.
    WTC_DEBUG="${WTC_DEBUG:-${FALSE}}" exec bash "${WAKE_THE_CLAUDE_SCRIPT}" "${CLAUDE_VERSION_FLAG}"
}


########################################################################################################################################################################################################
# Parse Command Line Input Parameters if provided
########################################################################################################################################################################################################
# Display Usage Message and Exit if --help, -h, or -? is provided
if [[ "${1}" == "--help" || "${1}" == "-h" || "${1}" == "-?" ]]; then
    usage 0
elif [[ "${1}" == "--version" || "${1}" == "--claude-version" || "${1}" == "-v" || "${1}" == "-V" ]]; then
    claude_code_version
elif [[ "${1}" == "--script-version" ]]; then
    echo "${SCRIPT_VERSION}"
    exit 0
fi

# The dry-run choice comes from the flag alone
CLAUDE_DRY_RUN="${FALSE}"

# Parse Optional Command Line Input Parameters if provided. Every word is parsed: an empty one once ended the loop, and the words after
# it -- a --file or --prompt among them -- reached wake_the_claude.bash unparsed, which stops at an empty word too, so they were dropped.
while (( $# > 0 )); do
    case "${1}" in
        "--help" | "-h" | "-?") usage 0 ;;
        "--version" | "--claude-version" | "-v" | "-V") claude_code_version ;;
        "--script-version") echo "${SCRIPT_VERSION}" && exit 0 ;;
        "--model-alias" | "--model" | "-m") require_value "${@}" && CLAUDE_MODEL="${2}" && shift 2 ;;
        "--effort-level" | "--effort" | "-e") require_value "${@}" && CLAUDE_EFFORT="${2}" && shift 2 ;;
        "--session-id" | "--session" | "--id" | "-s" | "-i") require_value "${@}" && CLAUDE_ID="${2}" && shift 2 ;;
        # The worktree name is optional: with none (the input ends, or a flag is next, such as --prompt) wake_the_claude.bash generates a branch
        "--worktree-name" | "--worktree" | "-w")
            if (( $# >= 2 )) && [[ "${2}" == "" ]]; then
                CLAUDE_WORKTREE="${TRUE}" && shift 2  # An empty name is no name
            elif [[ ( "${2:-""}" == "" ) || ( "${2:0:1}" == "-" ) ]]; then
                CLAUDE_WORKTREE="${TRUE}" && shift
            else
                CLAUDE_WORKTREE="${2}" && shift 2
            fi ;;
        "--no-worktree") CLAUDE_WORKTREE="${FALSE}" && shift ;;
        "--resume-session" | "--resume" | "-rs" | "-r") CLAUDE_RESUME="${TRUE}" && shift ;;
        # Remote control never takes a value (Overtoad ruling, 2026-11-04)
        "--remote-control-session" | "--remote-control" | "-rc") CLAUDE_REMOTE_CONTROL="${TRUE}" && shift ;;
        "--no-remote-control") CLAUDE_REMOTE_CONTROL="${FALSE}" && shift ;;
        "--dangerously-skip-permissions" | "--skip-permissions" | "-sp") CLAUDE_SKIP_PERMISSIONS="${TRUE}" && shift ;;
        "--initial-prompt" | "--prompt" | "-p") require_value "${@}" && CLAUDE_PROMPT="${2}" && shift 2 ;;
        # A prompt file, forwarded to wake_the_claude.bash, which reads it: --file names the file, --path the file or its directory
        "--file-name" | "--file" | "-f") require_nonempty_value "${@}" && CLAUDE_PROMPT_FILE="${2}" && shift 2 ;;
        "--file-path" | "--path" | "-l") require_nonempty_value "${@}" && CLAUDE_PROMPT_PATH="${2}" && shift 2 ;;
        "--dry-run") CLAUDE_DRY_RUN="${TRUE}" && shift ;;
        *) usage 1 "Unknown argument: ${1:-(an empty word)}";;
    esac
done


########################################################################################################################################################################################################
# Define Script Constants for Claude Code interaction
########################################################################################################################################################################################################
CLAUDE_SKIP_PERMISSIONS_PARAM="${CLAUDE_SKIP_PERMISSIONS:-${DEFAULT_SKIP_PERMISSIONS}}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_SKIP_PERMISSIONS_PARAM: ${CLAUDE_SKIP_PERMISSIONS_PARAM}" || true
CLAUDE_REMOTE_CONTROL_PARAM="${CLAUDE_REMOTE_CONTROL:-${DEFAULT_REMOTE_CONTROL}}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_REMOTE_CONTROL_PARAM: ${CLAUDE_REMOTE_CONTROL_PARAM}" || true
CLAUDE_WORKTREE_PARAM="${CLAUDE_WORKTREE:-${DEFAULT_WORKTREE}}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_WORKTREE_PARAM: ${CLAUDE_WORKTREE_PARAM}" || true
CLAUDE_PROMPT_FILE_PARAM="${CLAUDE_PROMPT_FILE:-}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_PROMPT_FILE_PARAM: ${CLAUDE_PROMPT_FILE_PARAM}" || true
CLAUDE_PROMPT_PATH_PARAM="${CLAUDE_PROMPT_PATH:-}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_PROMPT_PATH_PARAM: ${CLAUDE_PROMPT_PATH_PARAM}" || true
# An exported empty name is not "no file". ${var:-} above collapses it the way an unset variable collapses, and the
# branch below would then send the default prompt. That is the environment form of -f "${HANDOFF}" with HANDOFF unset,
# which require_nonempty_value already refuses for the flag. ${var+x} is set (even to empty) and unset otherwise.
if [[ "${CLAUDE_PROMPT_FILE+x}" == "x" && "${CLAUDE_PROMPT_FILE}" == "" ]]; then
    usage 1 "Missing value for ${CLAUDE_PROMPT_FILE_FLAG}"
fi
if [[ "${CLAUDE_PROMPT_PATH+x}" == "x" && "${CLAUDE_PROMPT_PATH}" == "" ]]; then
    usage 1 "Missing value for ${CLAUDE_PROMPT_PATH_FLAG}"
fi
# A prompt file replaces the default prompt (Overtoad ruling, 2026-11-06). wake_the_claude.bash prefers --prompt to a prompt file, so the
# default prompt sent alongside the file would silently discard it -- and so would an explicit prompt, which is refused instead.
if [[ ( "${CLAUDE_PROMPT_FILE_PARAM}" != "" ) || ( "${CLAUDE_PROMPT_PATH_PARAM}" != "" ) ]]; then
    [[ ( "${CLAUDE_PROMPT:-}" == "" ) || ( "${CLAUDE_PROMPT:-}" == "${FALSE}" ) ]] || usage 1 "A prompt and a prompt file are exclusive: give --prompt (or CLAUDE_PROMPT), or --file / --path (or CLAUDE_PROMPT_FILE / CLAUDE_PROMPT_PATH), not both"
    CLAUDE_PROMPT_PARAM=""
else
    CLAUDE_PROMPT_PARAM="${CLAUDE_PROMPT:-${DEFAULT_PROMPT}}"
fi
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_PROMPT_PARAM: ${CLAUDE_PROMPT_PARAM}" || true
CLAUDE_EFFORT_PARAM="${CLAUDE_EFFORT:-${DEFAULT_EFFORT}}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_EFFORT_PARAM: ${CLAUDE_EFFORT_PARAM}" || true
CLAUDE_RESUME_PARAM="${CLAUDE_RESUME:-${DEFAULT_RESUME}}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_RESUME_PARAM: ${CLAUDE_RESUME_PARAM}" || true
CLAUDE_MODEL_PARAM="${CLAUDE_MODEL:-${DEFAULT_MODEL}}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_MODEL_PARAM: ${CLAUDE_MODEL_PARAM}" || true
CLAUDE_ID_PARAM="${CLAUDE_ID:-${DEFAULT_ID}}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_ID_PARAM: ${CLAUDE_ID_PARAM}" || true
CLAUDE_DRY_RUN_PARAM="${CLAUDE_DRY_RUN}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "CLAUDE_DRY_RUN_PARAM: ${CLAUDE_DRY_RUN_PARAM}" || true


########################################################################################################################################################################################################
# Define the full parameter list for the Claude Code interactive session
########################################################################################################################################################################################################
# Built as an array and passed to wake_the_claude.bash as-is (no eval): every value stays exactly one argument, so a
# multi-word prompt arrives as one prompt with no literal quote characters, and no value is re-parsed by the shell.
CLAUDE_ARGS=()

[[ "${CLAUDE_MODEL_PARAM}" != "${FALSE}" ]] && CLAUDE_ARGS+=("${CLAUDE_MODEL_FLAG}" "${CLAUDE_MODEL_PARAM}")                                            # Add the model alias parameter if provided
[[ "${CLAUDE_EFFORT_PARAM}" != "${FALSE}" ]] && CLAUDE_ARGS+=("${CLAUDE_EFFORT_FLAG}" "${CLAUDE_EFFORT_PARAM}")                                         # Add the effort parameter if provided
[[ "${CLAUDE_ID_PARAM}" != "${FALSE}" ]] && CLAUDE_ARGS+=("${CLAUDE_ID_FLAG}" "${CLAUDE_ID_PARAM}")                                                     # Add the id parameter if provided
[[ "${CLAUDE_WORKTREE_PARAM}" != "${FALSE}" ]] && CLAUDE_ARGS+=("${CLAUDE_WORKTREE_FLAG}" "${CLAUDE_WORKTREE_PARAM}")                                   # Add the worktree: a branch or worktree name, or ${TRUE} for a generated branch

(( ${#CLAUDE_ARGS[@]} > 0 )) && CLAUDE_ARGS+=("${CLAUDE_SEPERATOR_FLAG}")                                                                              # Add the seperator flag if any "[--flag <parameter>]" arguments have been added

[[ "${CLAUDE_REMOTE_CONTROL_PARAM}" == "${TRUE}" ]] && CLAUDE_ARGS+=("${CLAUDE_REMOTE_CONTROL_FLAG}")                                                  # Add a bare --remote-control: on by default, and it never takes a value
[[ "${CLAUDE_RESUME_PARAM}" == "${TRUE}" ]] && CLAUDE_ARGS+=("${CLAUDE_RESUME_FLAG}" "${TRUE}")                                                        # Opt in to --resume when requested (wake_the_claude.bash needs a session id or a boolean after --resume)
[[ "${DEBUG}" == "${TRUE}" || "${CLAUDE_SKIP_PERMISSIONS_PARAM}" == "${TRUE}" ]] && CLAUDE_ARGS+=("${CLAUDE_SKIP_PERMISSIONS_FLAG}")                   # Opt in to --dangerously-skip-permissions only when explicitly requested or in debug mode
[[ "${CLAUDE_PROMPT_PARAM}" != "" && "${CLAUDE_PROMPT_PARAM}" != "${FALSE}" ]] && CLAUDE_ARGS+=("${CLAUDE_PROMPT_FLAG}" "${CLAUDE_PROMPT_PARAM}")      # Add the initial prompt if provided
[[ "${CLAUDE_PROMPT_FILE_PARAM}" != "" ]] && CLAUDE_ARGS+=("${CLAUDE_PROMPT_FILE_FLAG}" "${CLAUDE_PROMPT_FILE_PARAM}")                                 # Add the prompt file, which wake_the_claude.bash reads
[[ "${CLAUDE_PROMPT_PATH_PARAM}" != "" ]] && CLAUDE_ARGS+=("${CLAUDE_PROMPT_PATH_FLAG}" "${CLAUDE_PROMPT_PATH_PARAM}")                                 # Add the prompt file's path: the file itself, or the directory holding --file
[[ "${CLAUDE_DRY_RUN_PARAM}" == "${TRUE}" ]] && CLAUDE_ARGS+=("${CLAUDE_DRY_RUN_FLAG}")                                                                # Add --dry-run: wake_the_claude.bash prints its plan and starts nothing


########################################################################################################################################################################################################
# Pass through any additional arguments from the caller
if (( $# > 0 )); then
    CLAUDE_ARGS+=("${@}")
    [[ "${DEBUG}" == "${TRUE}" ]] && echo "${CLAUDE_ARGS[@]}" || true
fi


########################################################################################################################################################################################################
# Call Wake The Claude script with params
SESSION_WORDS="Default Interactive session with Claude Code"
[[ "${CLAUDE_DRY_RUN_PARAM}" == "${TRUE}" ]] && SESSION_WORDS="dry run of the ${SESSION_WORDS}"
echo "Launching ${SESSION_WORDS}"
[[ "${DEBUG}" == "${TRUE}" ]] && echo "bash ${WAKE_THE_CLAUDE_SCRIPT} ${CLAUDE_ARGS[*]}" || true

# Run with bash: no file in this repo carries an executable bit
bash "${WAKE_THE_CLAUDE_SCRIPT}" "${CLAUDE_ARGS[@]}"
# wake_the_claude.bash's status is this launcher's: a prompt file it refused once ended in "Closed ..." and exit 0
EXIT_CODE=$?

echo "Closed ${SESSION_WORDS}"

exit "${EXIT_CODE}"
