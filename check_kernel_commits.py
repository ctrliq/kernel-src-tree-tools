#!/usr/bin/env python3

import argparse
import subprocess
import re
import sys
import textwrap

def run_git(repo, args):
    """Run a git command in the given repository and return its output as a string."""
    result = subprocess.run(['git', '-C', repo] + args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(args)}\n{result.stderr}")
    return result.stdout

def ref_exists(repo, ref):
    """Return True if the given ref exists in the repository, False otherwise."""
    try:
        run_git(repo, ['rev-parse', '--verify', '--quiet', ref])
        return True
    except RuntimeError:
        return False

def get_pr_commits(repo, pr_branch, base_branch):
    """Get a list of commit SHAs that are in the PR branch but not in the base branch."""
    output = run_git(repo, ['rev-list', f'{base_branch}..{pr_branch}'])
    return output.strip().splitlines()

def get_commit_message(repo, sha):
    """Get the commit message for a given commit SHA."""
    return run_git(repo, ['log', '-n', '1', '--format=%B', sha])

def get_short_hash_and_subject(repo, sha):
    """Get the abbreviated commit hash and subject for a given commit SHA."""
    output = run_git(repo, ['log', '-n', '1', '--format=%h%x00%s', sha]).strip()
    short_hash, subject = output.split('\x00', 1)
    return short_hash, subject

def hash_exists_in_mainline(repo, upstream_ref, hash_):
    """
    Return True if hash_ is reachable from upstream_ref (i.e., is an ancestor of it).
    """
    try:
        run_git(repo, ['merge-base', '--is-ancestor', hash_, upstream_ref])
        return True
    except RuntimeError:
        return False

def find_fixes_in_mainline(repo, upstream_ref, hash_):
    """
    Return unique commits in upstream_ref that have Fixes: <N chars of hash_> in their message, case-insensitive.
    Start from 12 chars and work down to 6, but do not include duplicates if already found at a longer length.
    """
    results = []
    # Get all commits with 'Fixes:' in the message
    output = run_git(repo, [
        'log', upstream_ref, '--grep', 'Fixes:', '-i', '--format=%H %h %s (%an)%x0a%B%x00'
    ]).strip()
    if not output:
        return ""
    # Each commit is separated by a NUL character and a newline
    commits = output.split('\x00\x0a')
    # Prepare hash prefixes from 12 down to 6
    hash_prefixes = [hash_[:l] for l in range(12, 5, -1)]
    for commit in commits:
        if not commit.strip():
            continue
        # The first line is the summary, the rest is the body
        lines = commit.splitlines()
        if not lines:
            continue
        header = lines[0]
        full_hash = header.split()[0]
        # Search for Fixes: lines in the commit message
        for line in lines[1:]:
            m = re.match(r'^\s*Fixes:\s*([0-9a-fA-F]{6,40})', line, re.IGNORECASE)
            if m:
                for prefix in hash_prefixes:
                    if m.group(1).lower().startswith(prefix.lower()):
                        results.append(' '.join(header.split()[1:]))
                        break
            else:
                continue
    return "\n".join(results)

def wrap_paragraph(text, width=80, initial_indent='', subsequent_indent=''):
    """Wrap a paragraph of text to the specified width and indentation."""
    wrapper = textwrap.TextWrapper(width=width,
                                   initial_indent=initial_indent,
                                   subsequent_indent=subsequent_indent,
                                   break_long_words=False,
                                   break_on_hyphens=False)
    return wrapper.fill(text)

def main():
    parser = argparse.ArgumentParser(description="Check upstream references and Fixes: tags in PR branch commits.")
    parser.add_argument("--repo", help="Path to the git repo", required=True)
    parser.add_argument("--pr_branch", help="Name of the PR branch", required=True)
    parser.add_argument("--base_branch", help="Name of the base branch", required=True)
    parser.add_argument("--markdown", action='store_true', help="Output in Markdown, suitable for GitHub PR comments")
    parser.add_argument("--upstream-ref", default="origin/kernel-mainline", help="Reference to upstream mainline branch (default: origin/kernel-mainline)")
    args = parser.parse_args()

    upstream_ref = args.upstream_ref

    # Validate that all required refs exist before continuing
    missing_refs = []
    for refname, refval in [('upstream reference', upstream_ref),
                            ('PR branch', args.pr_branch),
                            ('base branch', args.base_branch)]:
        if not ref_exists(args.repo, refval):
            missing_refs.append((refname, refval))
    if missing_refs:
        for refname, refval in missing_refs:
            print(f"ERROR: The {refname} '{refval}' does not exist in the given repo.")
        print("Please fetch or create the required references before running this script.")
        sys.exit(1)

    pr_commits = get_pr_commits(args.repo, args.pr_branch, args.base_branch)
    if not pr_commits:
        if args.markdown:
            print("> ℹ️ **No commits found in PR branch that are not in base branch.**")
        else:
            print("No commits found in PR branch that are not in base branch.")
        sys.exit(0)

    any_findings = False
    out_lines = []

    for sha in reversed(pr_commits):  # oldest first
        short_hash, subject = get_short_hash_and_subject(args.repo, sha)
        pr_commit_desc = f"{short_hash} ({subject})"
        msg = get_commit_message(args.repo, sha)
        upstream_hashes = re.findall(r'^commit\s+([0-9a-fA-F]{12,40})', msg, re.MULTILINE)
        for uhash in upstream_hashes:
            short_uhash = uhash[:12]
            # Ensure the referenced commit in the PR actually exists in the upstream ref.
            exists = hash_exists_in_mainline(args.repo, upstream_ref, uhash)
            if not exists:
                any_findings = True
                if args.markdown:
                    out_lines.append(
                        f"- ❗ PR commit `{pr_commit_desc}` references upstream commit  \n"
                        f"  `{short_uhash}` which does **not** exist in the upstream Linux kernel.\n"
                    )
                else:
                    prefix = "[NOTFOUND] "
                    header = (f"{prefix}PR commit {pr_commit_desc} references upstream commit "
                              f"{short_uhash}, which does not exist in kernel-mainline.")
                    out_lines.append(
                        wrap_paragraph(header, width=80, initial_indent='',
                                       subsequent_indent=' ' * len(prefix))  # spaces for '[NOTFOUND] '
                    )
                    out_lines.append("")  # blank line
                continue
            fixes = find_fixes_in_mainline(args.repo, upstream_ref, uhash)
            if fixes:
                any_findings = True
                if args.markdown:
                    fixes_block = "    " + fixes.replace("\n", "\n    ")
                    out_lines.append(
                        f"- ⚠️ PR commit `{pr_commit_desc}` references upstream commit  \n"
                        f"  `{short_uhash}` which has been referenced by a `Fixes:` tag in the upstream  \n"
                        f"  Linux kernel:\n\n"
                        f"```text\n{fixes_block}\n```\n"
                    )
                else:
                    prefix = "[FIXES] "
                    header = (f"{prefix}PR commit {pr_commit_desc} references upstream commit "
                              f"{short_uhash}, which has Fixes tags:")
                    out_lines.append(
                        wrap_paragraph(header, width=80, initial_indent='',
                                       subsequent_indent=' ' * len(prefix))  # spaces for '[FIXES] '
                    )
                    out_lines.append("")  # blank line after 'Fixes tags:'
                    for line in fixes.splitlines():
                        out_lines.append('    ' + line)
                    out_lines.append("")  # blank line

    if any_findings:
        if args.markdown:
            print("## :mag: Upstream Linux Kernel Commit Check\n")
            print('\n'.join(out_lines))
            print("*This is an automated message from the kernel commit checker workflow.*")
        else:
            print('\n'.join(out_lines))
    else:
        if args.markdown:
            print("> ✅ **All referenced commits exist upstream and have no Fixes: tags.**")
        else:
            print("All referenced commits exist upstream and have no Fixes: tags.")

if __name__ == "__main__":
    main()
