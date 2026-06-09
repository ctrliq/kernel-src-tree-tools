#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import tempfile

from kt.ktlib.commit_header import CommitHeader


def run_git(repo, args):
    """Run a git command in the given repository and return its output as a string."""
    result = subprocess.run(["git", "-C", repo] + args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(args)}\n{result.stderr}")
    return result.stdout


def ref_exists(repo, ref):
    """Return True if the given ref exists in the repository, False otherwise."""
    try:
        run_git(repo, ["rev-parse", "--verify", "--quiet", ref])
        return True
    except RuntimeError:
        return False


def get_pr_commits(repo, pr_branch, base_branch):
    """Get a list of commit SHAs that are in the PR branch but not in the base branch."""
    try:
        output = run_git(repo, ["rev-list", f"{base_branch}..{pr_branch}"])
        return output.strip().splitlines()
    except RuntimeError as e:
        raise RuntimeError(f"Failed to get commits from {base_branch}..{pr_branch}: {e}")


def get_commit_message(repo, sha):
    """Get the commit message for a given commit SHA."""
    try:
        return run_git(repo, ["log", "-n", "1", "--format=%B", sha])
    except RuntimeError as e:
        raise RuntimeError(f"Failed to get commit message for {sha}: {e}")


def get_short_hash_and_subject(repo, sha):
    """Get the abbreviated commit hash and subject for a given commit SHA."""
    try:
        output = run_git(repo, ["log", "-n", "1", "--format=%h%x00%s", sha]).strip()
        short_hash, subject = output.split("\x00", 1)
        return short_hash, subject
    except RuntimeError as e:
        raise RuntimeError(f"Failed to get short hash and subject for {sha}: {e}")


def run_interdiff(repo, backport_sha, upstream_sha, interdiff_path):
    """Run interdiff comparing the backport commit with the upstream commit.
    Returns (success, output) tuple."""
    # Generate format-patch for backport commit
    try:
        backport_patch = run_git(repo, ["format-patch", "-1", "--stdout", backport_sha])
    except RuntimeError as e:
        return False, f"Failed to generate patch for backport commit: {e}"

    # Generate format-patch for upstream commit
    try:
        upstream_patch = run_git(repo, ["format-patch", "-1", "--stdout", upstream_sha])
    except RuntimeError as e:
        return False, f"Failed to generate patch for upstream commit: {e}"

    # Write patches to temp files
    bp_path = None
    up_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as bp:
            bp.write(backport_patch)
            bp_path = bp.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as up:
            up.write(upstream_patch)
            up_path = up.name

        interdiff_result = subprocess.run(
            [interdiff_path, "--fuzzy", bp_path, up_path], text=True, capture_output=True, check=False
        )

        # Check for interdiff errors (non-zero return code other than 1)
        # Note: interdiff returns 0 if no differences, 1 if differences found
        if interdiff_result.returncode not in (0, 1):
            if interdiff_result.stderr:
                error_msg = interdiff_result.stderr.strip()
            else:
                error_msg = f"Exit code {interdiff_result.returncode}"
            return False, f"interdiff failed: {error_msg}"

        return True, interdiff_result.stdout.strip()
    except Exception as e:
        return False, f"Failed to run interdiff: {e}"
    finally:
        # Clean up temp files if they were created
        if bp_path and os.path.exists(bp_path):
            os.unlink(bp_path)
        if up_path and os.path.exists(up_path):
            os.unlink(up_path)


def find_interdiff():
    """Find interdiff in system PATH. Returns path if found, None otherwise."""
    result = subprocess.run(["which", "interdiff"], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def main():
    parser = argparse.ArgumentParser(description="Run interdiff on backported kernel commits to compare with upstream.")
    parser.add_argument("--repo", help="Path to the Linux kernel git repo", required=True)
    parser.add_argument("--pr_branch", help="Git reference to the feature branch", required=True)
    parser.add_argument("--base_branch", help="Branch the feature branch is based off of", required=True)
    parser.add_argument("--markdown", action="store_true", help="Format output with markdown")
    parser.add_argument("--interdiff", help="Path to interdiff executable (default: system interdiff)", default=None)
    args = parser.parse_args()

    # Determine interdiff path
    if args.interdiff:
        # User specified a path
        interdiff_path = args.interdiff
        if not os.path.exists(interdiff_path):
            print(f"ERROR: interdiff not found at specified path: {interdiff_path}")
            sys.exit(1)
        if not os.access(interdiff_path, os.X_OK):
            print(f"ERROR: interdiff at {interdiff_path} is not executable")
            sys.exit(1)
    else:
        # Try to find system interdiff
        interdiff_path = find_interdiff()
        if not interdiff_path:
            print("ERROR: interdiff not found in system PATH")
            print("Please install patchutils or specify path with --interdiff")
            sys.exit(1)

    # Validate that all required refs exist
    missing_refs = []
    for refname, refval in [("PR branch", args.pr_branch), ("base branch", args.base_branch)]:
        if not ref_exists(args.repo, refval):
            missing_refs.append((refname, refval))

    if missing_refs:
        for refname, refval in missing_refs:
            print(f"ERROR: The {refname} '{refval}' does not exist in the given repo.")
        print("Please fetch or create the required references before running this script.")
        sys.exit(1)

    # Get all PR commits
    pr_commits = get_pr_commits(args.repo, args.pr_branch, args.base_branch)
    if not pr_commits:
        if args.markdown:
            print("> ℹ️ **No commits found in PR branch that are not in base branch.**")
        else:
            print("No commits found in PR branch that are not in base branch.")
        sys.exit(0)

    any_differences = False
    out_lines = []

    # Process commits in chronological order (oldest first)
    for sha in reversed(pr_commits):
        try:
            short_hash, subject = get_short_hash_and_subject(args.repo, sha)
            pr_commit_desc = f"{short_hash} ({subject})"

            msg = get_commit_message(args.repo, sha)
            commit_header = CommitHeader.from_commit_body(commit_body=msg)
            upstream_hash = commit_header.commit
        except RuntimeError as e:
            # Handle errors getting commit information
            any_differences = True
            if args.markdown:
                out_lines.append(f"- ❌ PR commit `{sha[:12]}` → Error getting commit info")
                out_lines.append(f"  **Error:** {e}\n")
            else:
                out_lines.append(f"[ERROR] PR commit {sha[:12]} → Error getting commit info")
                out_lines.append(f"  {e}")
                out_lines.append("")
            continue

        # Only process commits that have an upstream reference
        if not upstream_hash:
            continue

        # Run interdiff
        success, output = run_interdiff(args.repo, sha, upstream_hash, interdiff_path)

        if not success:
            # Error running interdiff
            any_differences = True
            if args.markdown:
                out_lines.append(f"- ❌ PR commit `{pr_commit_desc}` → `{upstream_hash[:12]}`")
                out_lines.append(f"  **Error:** {output}\n")
            else:
                out_lines.append(f"[ERROR] PR commit {pr_commit_desc} → {upstream_hash[:12]}")
                out_lines.append(f"  {output}")
                out_lines.append("")
        elif output:
            # There are differences
            any_differences = True
            if args.markdown:
                out_lines.append(f"- ⚠️ PR commit `{pr_commit_desc}` → upstream `{upstream_hash[:12]}`")
                out_lines.append("  **Differences found:**\n")
                out_lines.append("```diff")
                out_lines.append(output)
                out_lines.append("```\n")
            else:
                out_lines.append(f"[DIFF] PR commit {pr_commit_desc} → upstream {upstream_hash[:12]}")
                out_lines.append("Differences found:")
                out_lines.append("")
                for line in output.splitlines():
                    out_lines.append("  " + line)
                out_lines.append("")

    # Print results
    if any_differences:
        if args.markdown:
            print("## :mag: Interdiff Analysis\n")
            print("\n".join(out_lines))
            print("*This is an automated interdiff check for backported commits.*")
        else:
            print("\n".join(out_lines))
    else:
        if args.markdown:
            print("> ✅ **All backported commits match their upstream counterparts.**")
        else:
            print("All backported commits match their upstream counterparts.")


if __name__ == "__main__":
    main()
