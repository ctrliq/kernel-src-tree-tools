#!/bin/bash
#
# check-upstream-commit.sh — Check if an upstream commit SHA is present
# (directly or as a backport reference) across CIQ maintained kernels.
#
# Usage:
#   ./scripts/check-upstream-commit.sh <sha> [sha2 ...]
#   ./scripts/check-upstream-commit.sh -f file_of_shas.txt
#   ./scripts/check-upstream-commit.sh --fetch <sha>
#
# Options:
#   -f, --file FILE      Read SHAs from FILE (one per line, # comments ok)
#   -F, --fetch          Run git fetch before checking
#   -r, --remote REMOTE  Remote name (default: origin)
#   -v, --verbose        Show matching commit subjects
#   -q, --quiet          Only show branches where the SHA was found
#   -j, --json           Output results as JSON
#   -h, --help           Show this help
#
# Environment:
#   KERNEL_REMOTE        Override default remote (same as --remote)
#   KERNEL_REPO_PATH     Path to kernel-src-tree checkout
#                        (default: auto-detect from script location)

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────

REMOTE="${KERNEL_REMOTE:-origin}"
FETCH=0
VERBOSE=0
QUIET=0
JSON=0
SHA_LIST=()
SHA_FILE=""

# ── Branch definitions ────────────────────────────────────────────────
# Static branches (always checked as-is)
STATIC_BRANCHES=(
    "ciqcbr7_9"
    "ciqlts8_6"
    "ciqlts8_8"
    "ciqlts9_2"
    "ciqlts9_4"
    "ciqlts9_6"
    "ciq-6.12.y"
    "ciq-6.18.y"
)

# RLC families — script auto-picks the most current branch per family
RLC_FAMILIES=(
    "rlc-8"
    "rlc-9"
    "rlc-10"
)

# ── Functions ─────────────────────────────────────────────────────────

usage() {
    sed -n '3,/^$/s/^# \?//p' "$0"
    exit 0
}

die() { echo "error: $*" >&2; exit 1; }

resolve_repo_path() {
    if [[ -n "${KERNEL_REPO_PATH:-}" ]]; then
        echo "$KERNEL_REPO_PATH"
        return
    fi
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local repo="${script_dir%/scripts}"
    if [[ -d "$repo/.git" || -f "$repo/.git" ]]; then
        echo "$repo"
        return
    fi
    if git rev-parse --git-dir >/dev/null 2>&1; then
        git rev-parse --show-toplevel
        return
    fi
    die "Cannot find kernel-src-tree repo. Set KERNEL_REPO_PATH or run from the repo."
}

latest_rlc_branch() {
    local family="$1"
    git branch -r --list "${REMOTE}/${family}/*" 2>/dev/null \
        | sed "s|^[[:space:]]*${REMOTE}/||" \
        | sort -t/ -k2 -V \
        | tail -1
}

branch_label() {
    local branch="$1"
    case "$branch" in
        ciqcbr7_9)    echo "CBR 7.9";;
        ciqlts8_6)    echo "LTS 8.6";;
        ciqlts8_8)    echo "LTS 8.8";;
        ciqlts9_2)    echo "LTS 9.2";;
        ciqlts9_4)    echo "LTS 9.4";;
        ciqlts9_6)    echo "LTS 9.6";;
        ciq-6.12.y)   echo "CLK 6.12";;
        ciq-6.18.y)   echo "CLK 6.18";;
        rlc-8/*)      echo "RLC 8 (${branch#rlc-8/})";;
        rlc-9/*)      echo "RLC 9 (${branch#rlc-9/})";;
        rlc-10/*)     echo "RLC 10 (${branch#rlc-10/})";;
        *)            echo "$branch";;
    esac
}

validate_sha() {
    local sha="$1"
    if [[ ! "$sha" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
        die "Invalid SHA: '$sha' (expected 7-40 hex characters)"
    fi
}

# ── Argument parsing ─────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)    usage;;
        -f|--file)    SHA_FILE="$2"; shift 2;;
        -F|--fetch)   FETCH=1; shift;;
        -r|--remote)  REMOTE="$2"; shift 2;;
        -v|--verbose) VERBOSE=1; shift;;
        -q|--quiet)   QUIET=1; shift;;
        -j|--json)    JSON=1; shift;;
        -*)           die "Unknown option: $1";;
        *)            SHA_LIST+=("$1"); shift;;
    esac
done

if [[ -n "$SHA_FILE" ]]; then
    [[ -f "$SHA_FILE" ]] || die "File not found: $SHA_FILE"
    while IFS= read -r line; do
        line="${line%%#*}"
        line="${line// /}"
        [[ -n "$line" ]] && SHA_LIST+=("$line")
    done < "$SHA_FILE"
fi

[[ ${#SHA_LIST[@]} -gt 0 ]] || die "No SHA(s) provided. Run with --help for usage."

for sha in "${SHA_LIST[@]}"; do
    validate_sha "$sha"
done

# ── Setup ─────────────────────────────────────────────────────────────

REPO_PATH="$(resolve_repo_path)"
cd "$REPO_PATH"

if [[ $FETCH -eq 1 ]]; then
    echo "Fetching ${REMOTE}..." >&2
    git fetch "$REMOTE" --prune --quiet
fi

# ── Build branch list ────────────────────────────────────────────────

BRANCHES=()
MISSING_BRANCHES=()

for b in "${STATIC_BRANCHES[@]}"; do
    if git rev-parse --verify "${REMOTE}/${b}" >/dev/null 2>&1; then
        BRANCHES+=("$b")
    else
        MISSING_BRANCHES+=("$b")
    fi
done

for family in "${RLC_FAMILIES[@]}"; do
    latest="$(latest_rlc_branch "$family")"
    if [[ -n "$latest" ]]; then
        BRANCHES+=("$latest")
    else
        MISSING_BRANCHES+=("$family/*")
    fi
done

if [[ ${#MISSING_BRANCHES[@]} -gt 0 && $QUIET -eq 0 && $JSON -eq 0 ]]; then
    echo "warning: branches not found on ${REMOTE}: ${MISSING_BRANCHES[*]}" >&2
fi

# ── Build ref list for batch operations ──────────────────────────────

REFS=()
for branch in "${BRANCHES[@]}"; do
    REFS+=("${REMOTE}/${branch}")
done

# ── Phase 1: batch grep — single git-log pass per SHA ────────────────
# Instead of running git-log per branch, we run ONE git-log --all --grep
# and then figure out which branches contain each matching commit.
# This is dramatically faster because git only walks the commit graph once.

declare -A GREP_HITS          # GREP_HITS["sha:branch"] = "commit_sha subject"
declare -A GREP_HIT_COUNTS   # GREP_HIT_COUNTS["sha:branch"] = count

for sha in "${SHA_LIST[@]}"; do
    sha_lower="$(echo "$sha" | tr '[:upper:]' '[:lower:]')"

    # Get all commits across all branches that mention this SHA in their message.
    # Use --format to get both the commit hash and subject for verbose mode.
    matching_commits=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && matching_commits+=("$line")
    done < <(git log --format="%H %s" --grep="$sha_lower" "${REFS[@]}" 2>/dev/null | sort -u)

    if [[ ${#matching_commits[@]} -eq 0 ]]; then
        continue
    fi

    # For each matching commit, determine which of our branches contain it
    for entry in "${matching_commits[@]}"; do
        commit_hash="${entry%% *}"
        for i in "${!BRANCHES[@]}"; do
            ref="${REFS[$i]}"
            branch="${BRANCHES[$i]}"
            if git merge-base --is-ancestor "$commit_hash" "$ref" 2>/dev/null; then
                key="${sha_lower}:${branch}"
                if [[ -z "${GREP_HITS[$key]:-}" ]]; then
                    GREP_HITS["$key"]="$entry"
                    GREP_HIT_COUNTS["$key"]=1
                else
                    GREP_HIT_COUNTS["$key"]=$(( ${GREP_HIT_COUNTS["$key"]} + 1 ))
                fi
            fi
        done
    done
done

# ── Phase 2: direct ancestry check (--contains) ─────────────────────
# For each SHA, check if the actual upstream commit object exists locally
# and is an ancestor of each branch. This is fast — no log walk needed.

declare -A CONTAINS_HITS  # CONTAINS_HITS["sha:branch"] = 1

for sha in "${SHA_LIST[@]}"; do
    sha_lower="$(echo "$sha" | tr '[:upper:]' '[:lower:]')"
    full_sha=""
    if git cat-file -t "$sha_lower" >/dev/null 2>&1; then
        full_sha="$(git rev-parse "$sha_lower" 2>/dev/null || true)"
    fi

    if [[ -z "$full_sha" ]]; then
        continue
    fi

    for i in "${!BRANCHES[@]}"; do
        ref="${REFS[$i]}"
        branch="${BRANCHES[$i]}"
        if git merge-base --is-ancestor "$full_sha" "$ref" 2>/dev/null; then
            CONTAINS_HITS["${sha_lower}:${branch}"]=1
        fi
    done
done

# ── Output ───────────────────────────────────────────────────────────

if [[ $JSON -eq 1 ]]; then
    json_results="["
    json_first_sha=1
fi

for sha in "${SHA_LIST[@]}"; do
    sha_lower="$(echo "$sha" | tr '[:upper:]' '[:lower:]')"

    full_sha=""
    if git cat-file -t "$sha_lower" >/dev/null 2>&1; then
        full_sha="$(git rev-parse "$sha_lower" 2>/dev/null || true)"
    fi

    if [[ $JSON -eq 0 ]]; then
        echo ""
        echo "━━━ Checking ${sha_lower} ━━━"
        if [[ -n "$full_sha" && "$full_sha" != "$sha_lower" ]]; then
            echo "    (resolved to ${full_sha})"
        fi
        echo ""
        printf "  %-35s  %-10s  %-10s  %s\n" "BRANCH" "CONTAINS" "BACKPORT" "DETAILS"
        printf "  %-35s  %-10s  %-10s  %s\n" "------" "--------" "--------" "-------"
    else
        if [[ $json_first_sha -eq 0 ]]; then json_results+=","; fi
        json_first_sha=0
        json_results+="{\"sha\":\"${sha_lower}\""
        [[ -n "$full_sha" ]] && json_results+=",\"full_sha\":\"${full_sha}\""
        json_results+=",\"branches\":["
        json_first_branch=1
    fi

    for branch in "${BRANCHES[@]}"; do
        label="$(branch_label "$branch")"
        key="${sha_lower}:${branch}"
        contains="no"
        backport="no"
        details=""

        if [[ -n "${CONTAINS_HITS[$key]:-}" ]]; then
            contains="YES"
        fi

        if [[ -n "${GREP_HITS[$key]:-}" ]]; then
            backport="YES"
            count="${GREP_HIT_COUNTS[$key]:-1}"
            if [[ $VERBOSE -eq 1 ]]; then
                entry="${GREP_HITS[$key]}"
                match_sha="${entry%% *}"
                match_subj="${entry#* }"
                details="${match_sha:0:12} ${match_subj}"
                if [[ $count -gt 1 ]]; then
                    details+=" (+$((count - 1)) more)"
                fi
            else
                if [[ $count -gt 1 ]]; then
                    details="${count} commits reference this SHA"
                fi
            fi
        fi

        if [[ $QUIET -eq 1 && "$contains" == "no" && "$backport" == "no" ]]; then
            continue
        fi

        if [[ $JSON -eq 0 ]]; then
            if [[ -t 1 ]]; then
                c_green="\033[32m"
                c_reset="\033[0m"
                c_dim="\033[2m"
                [[ "$contains" == "YES" ]] && c_cont="${c_green}YES${c_reset}" || c_cont="${c_dim}no${c_reset} "
                [[ "$backport" == "YES" ]] && c_back="${c_green}YES${c_reset}" || c_back="${c_dim}no${c_reset} "
                printf "  %-35s  ${c_cont}%-4s      ${c_back}%-4s      %s\n" "$label" "" "" "$details"
            else
                printf "  %-35s  %-10s  %-10s  %s\n" "$label" "$contains" "$backport" "$details"
            fi
        else
            if [[ $json_first_branch -eq 0 ]]; then json_results+=","; fi
            json_first_branch=0
            json_results+="{\"branch\":\"${branch}\",\"label\":\"${label}\""
            json_results+=",\"contains\":$([ "$contains" = "YES" ] && echo true || echo false)"
            json_results+=",\"backport\":$([ "$backport" = "YES" ] && echo true || echo false)"
            if [[ -n "$details" ]]; then
                details_escaped="${details//\\/\\\\}"
                details_escaped="${details_escaped//\"/\\\"}"
                json_results+=",\"details\":\"${details_escaped}\""
            fi
            json_results+="}"
        fi
    done

    if [[ $JSON -eq 1 ]]; then
        json_results+="]}"
    fi

    if [[ $JSON -eq 0 && $QUIET -eq 0 ]]; then
        echo ""
    fi
done

if [[ $JSON -eq 1 ]]; then
    json_results+="]"
    echo "$json_results"
fi
