#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
import textwrap

from kt.ktlib.ciq_helpers import (
    CIQ_find_fixes_in_mainline,
    CIQ_find_matching_cve,
    CIQ_get_commit_body,
    CIQ_hash_exists_in_ref,
    CIQ_run_git,
    CIQ_setup_vulns_repo,
)


def ref_exists(repo, ref):
    """Return True if the given ref exists in the repository, False otherwise."""
    try:
        CIQ_run_git(repo, ["rev-parse", "--verify", "--quiet", ref])
        return True
    except RuntimeError:
        return False


def get_pr_commits(repo, pr_branch, base_branch):
    """Get a list of commit SHAs that are in the PR branch but not in the base branch."""
    output = CIQ_run_git(repo, ["rev-list", f"{base_branch}..{pr_branch}"])
    return output.strip().splitlines()


def get_short_hash_and_subject(repo, sha):
    """Get the abbreviated commit hash and subject for a given commit SHA."""
    output = CIQ_run_git(repo, ["log", "-n", "1", "--format=%h%x00%s", sha]).strip()
    short_hash, subject = output.split("\x00", 1)
    return short_hash, subject


def hash_exists_in_mainline(repo, upstream_ref, hash_):
    """
    Return True if hash_ is reachable from upstream_ref (i.e., is an ancestor of it).
    """

    return CIQ_hash_exists_in_ref(repo, upstream_ref, hash_)


def wrap_paragraph(text, width=80, initial_indent="", subsequent_indent=""):
    """Wrap a paragraph of text to the specified width and indentation."""
    wrapper = textwrap.TextWrapper(
        width=width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapper.fill(text)


def extract_cve_from_message(msg):
    """Extract CVE reference from commit message. Returns CVE ID or None.
    Only matches 'cve CVE-2025-12345', ignores 'cve-bf' and 'cve-pre' variants."""
    match = re.search(r"(?<!\S)cve\s+(CVE-\d{4}-\d+)", msg, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def main():
    parser = argparse.ArgumentParser(description="Check upstream references and Fixes: tags in PR branch commits.")
    parser.add_argument("--repo", help="Path to the git repo", required=True)
    parser.add_argument("--pr_branch", help="Name of the PR branch", required=True)
    parser.add_argument("--base_branch", help="Name of the base branch", required=True)
    parser.add_argument("--markdown", action="store_true", help="Output in Markdown, suitable for GitHub PR comments")
    parser.add_argument(
        "--upstream-ref",
        default="origin/kernel-mainline",
        help="Reference to upstream mainline branch (default: origin/kernel-mainline)",
    )
    parser.add_argument(
        "--check-cves",
        action="store_true",
        help="Check that CVE references in commit messages match upstream commit hashes",
    )
    parser.add_argument(
        "--vulns-dir", default="../vulns", help="Path to the kernel vulnerabilities repo (default: ../vulns)"
    )
    args = parser.parse_args()

    upstream_ref = args.upstream_ref

    # Set up vulns repo path if CVE checking is enabled
    vulns_repo = None
    if args.check_cves:
        vulns_repo = args.vulns_dir
        try:
            CIQ_setup_vulns_repo(vulns_repo=vulns_repo)
        except RuntimeError as e:
            print(e)
            sys.exit(1)

    # Validate that all required refs exist before continuing
    missing_refs = []
    for refname, refval in [
        ("upstream reference", upstream_ref),
        ("PR branch", args.pr_branch),
        ("base branch", args.base_branch),
    ]:
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
        msg = CIQ_get_commit_body(args.repo, sha)
        upstream_hashes = re.findall(r"^commit\s+([0-9a-fA-F]{40})", msg, re.MULTILINE)
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
                    header = (
                        f"{prefix}PR commit {pr_commit_desc} references upstream commit "
                        f"{short_uhash}, which does not exist in kernel-mainline."
                    )
                    out_lines.append(
                        wrap_paragraph(
                            header, width=80, initial_indent="", subsequent_indent=" " * len(prefix)
                        )  # spaces for '[NOTFOUND] '
                    )
                    out_lines.append("")  # blank line
                continue
            fixes = CIQ_find_fixes_in_mainline(args.repo, args.pr_branch, upstream_ref, uhash)
            if fixes:
                any_findings = True

                # Check CVEs for bugfix commits if enabled
                fix_cves = {}
                if args.check_cves:
                    for fix_hash, fix_display in fixes:
                        bugfix_cve = CIQ_find_matching_cve(vulns_repo=vulns_repo, kernel_repo=args.repo, hash_=fix_hash)
                        if bugfix_cve:
                            fix_cves[fix_hash] = bugfix_cve

                # Build the fixes display text with CVE info
                fixes_lines = []
                for fix_hash, display_str in fixes:
                    if fix_hash in fix_cves:
                        fixes_lines.append(f"{display_str} ({fix_cves[fix_hash]})")
                    else:
                        fixes_lines.append(display_str)
                fixes_text = "\n".join(fixes_lines)

                if args.markdown:
                    fixes_block = "    " + fixes_text.replace("\n", "\n    ")
                    out_lines.append(
                        f"- ⚠️ PR commit `{pr_commit_desc}` references upstream commit  \n"
                        f"  `{short_uhash}` which has been referenced by a `Fixes:` tag in the upstream  \n"
                        f"  Linux kernel:\n\n"
                        f"```text\n{fixes_block}\n```\n"
                    )
                else:
                    prefix = "[FIXES] "
                    header = (
                        f"{prefix}PR commit {pr_commit_desc} references upstream commit "
                        f"{short_uhash}, which has Fixes tags:"
                    )
                    out_lines.append(
                        wrap_paragraph(
                            header, width=80, initial_indent="", subsequent_indent=" " * len(prefix)
                        )  # spaces for '[FIXES] '
                    )
                    out_lines.append("")  # blank line after 'Fixes tags:'
                    for line in fixes_text.splitlines():
                        out_lines.append("    " + line)
                    out_lines.append("")  # blank line

            # Check CVE if enabled
            if args.check_cves:
                cve_id = extract_cve_from_message(msg)

                # Check if the upstream commit has a CVE associated with it
                try:
                    found_cve = CIQ_find_matching_cve(vulns_repo=vulns_repo, kernel_repo=args.repo, hash_=uhash)
                    if found_cve:
                        if cve_id:
                            # PR commit has a CVE reference - check if it matches
                            if found_cve != cve_id:
                                any_findings = True
                                if args.markdown:
                                    out_lines.append(
                                        f"- ❌ PR commit `{pr_commit_desc}` references `{cve_id}` but  \n"
                                        f"  upstream commit `{short_uhash}` is associated with `{found_cve}`\n"
                                    )
                                else:
                                    prefix = "[CVE-MISMATCH] "
                                    header = (
                                        f"{prefix}PR commit {pr_commit_desc} references {cve_id} but "
                                        f"upstream commit {short_uhash} is associated with {found_cve}"
                                    )
                                    out_lines.append(
                                        wrap_paragraph(
                                            header, width=80, initial_indent="", subsequent_indent=" " * len(prefix)
                                        )
                                    )
                                    out_lines.append("")  # blank line
                        else:
                            # PR commit doesn't reference a CVE, but upstream has one
                            any_findings = True
                            if args.markdown:
                                out_lines.append(
                                    f"- ⚠️ PR commit `{pr_commit_desc}` does not reference a CVE but  \n"
                                    f"  upstream commit `{short_uhash}` is associated with `{found_cve}`\n"
                                )
                            else:
                                prefix = "[CVE-MISSING] "
                                header = (
                                    f"{prefix}PR commit {pr_commit_desc} does not reference a CVE but "
                                    f"upstream commit {short_uhash} is associated with {found_cve}"
                                )
                                out_lines.append(
                                    wrap_paragraph(
                                        header, width=80, initial_indent="", subsequent_indent=" " * len(prefix)
                                    )
                                )
                                out_lines.append("")  # blank line
                    else:
                        # The upstream commit has no CVE assigned
                        if cve_id:
                            # PR commit claims a CVE but upstream has none
                            any_findings = True
                            if args.markdown:
                                out_lines.append(
                                    f"- ❌ PR commit `{pr_commit_desc}` references `{cve_id}` but  \n"
                                    f"  upstream commit `{short_uhash}` has no CVE assigned\n"
                                )
                            else:
                                prefix = "[CVE-NOTFOUND] "
                                header = (
                                    f"{prefix}PR commit {pr_commit_desc} references {cve_id} but "
                                    f"upstream commit {short_uhash} has no CVE assigned"
                                )
                                out_lines.append(
                                    wrap_paragraph(
                                        header, width=80, initial_indent="", subsequent_indent=" " * len(prefix)
                                    )
                                )
                                out_lines.append("")  # blank line
                except (subprocess.SubprocessError, OSError) as e:
                    # Error running cve_search
                    if cve_id:
                        any_findings = True
                        if args.markdown:
                            out_lines.append(
                                f"- ⚠️ PR commit `{pr_commit_desc}` references `{cve_id}` but  \n"
                                f"  failed to verify: {e}\n"
                            )
                        else:
                            prefix = "[CVE-ERROR] "
                            header = f"{prefix}PR commit {pr_commit_desc} references {cve_id} but failed to verify: {e}"
                            out_lines.append(
                                wrap_paragraph(header, width=80, initial_indent="", subsequent_indent=" " * len(prefix))
                            )
                            out_lines.append("")  # blank line

    if any_findings:
        if args.markdown:
            print("## :mag: Upstream Linux Kernel Commit Check\n")
            print("\n".join(out_lines))
            print("*This is an automated message from the kernel commit checker workflow.*")
        else:
            print("\n".join(out_lines))
    else:
        if args.markdown:
            print("> ✅ **All referenced commits exist upstream and have no Fixes: tags.**")
        else:
            print("All referenced commits exist upstream and have no Fixes: tags.")


if __name__ == "__main__":
    main()
