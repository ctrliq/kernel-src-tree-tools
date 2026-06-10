#!/bin/env python3.11

import argparse
import os
import re
import subprocess
import sys

from jira import JIRA

from kt.ktlib.commit_header import CommitHeader
from release_config import jira_field_map, release_map

CVE_PATTERN = r"CVE-\d{4}-\d{4,7}"

# Reverse lookup: field name -> custom field ID
jira_field_reverse = {v: k for k, v in jira_field_map.items()}


def restore_git_branch(original_branch, kernel_src_tree):
    """Restore the original git branch in case of errors."""
    try:
        subprocess.run(
            ["git", "checkout", original_branch], cwd=kernel_src_tree, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to restore original branch {original_branch}: {e.stderr}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Validate PR Commits against JIRA VULN Tickets",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # This is a necessary requirement at the moment to allow multiple different JIRA creds from the same user
    parser.add_argument(
        "--jira-url",
        required=False,
        help="JIRA server URL.",
    )
    parser.add_argument(
        "--jira-user",
        required=False,
        help="JIRA user email",
    )
    parser.add_argument(
        "--jira-key",
        required=False,
        help="JIRA API Key (or set JIRA_API_TOKEN environment variable)",
    )
    # End JIRA creds section
    parser.add_argument(
        "--kernel-src-tree",
        required=True,
        help="Path to kernel source tree repository",
    )
    parser.add_argument(
        "--merge-target",
        required=True,
        help="Merge target branch",
    )
    parser.add_argument(
        "--pr-branch",
        required=True,
        help="PR branch to checkout",
    )

    args = parser.parse_args()

    # Verify kernel source tree path exists
    if not os.path.isdir(args.kernel_src_tree):
        print(f"ERROR: Kernel source tree path does not exist: {args.kernel_src_tree}")
        sys.exit(1)

    jira_url = args.jira_url or os.environ.get("JIRA_URL")
    jira_user = args.jira_user or os.environ.get("JIRA_API_USER")
    jira_key = args.jira_key or os.environ.get("JIRA_API_TOKEN")

    if not all([jira_url, jira_user, jira_key]):
        print("ERROR: JIRA credentials not provided. Set via --jira-* args or environment variables.")
        sys.exit(1)

    # Connect to JIRA
    try:
        jira = JIRA(server=jira_url, basic_auth=(jira_user, jira_key))
    except Exception as e:
        print(f"ERROR: Failed to connect to JIRA: {e}")
        sys.exit(1)

    original_branch = None
    try:
        # Get current branch to restore later
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=args.kernel_src_tree, check=True, capture_output=True, text=True
        )
        original_branch = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to get current git branch: {e.stderr}")
        sys.exit(1)

    # Checkout the merge target branch first to ensure it exists
    try:
        subprocess.run(
            ["git", "checkout", args.merge_target], cwd=args.kernel_src_tree, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to checkout merge target branch {args.merge_target}: {e.stderr}")
        # Restore original branch if needed
        restore_git_branch(original_branch, kernel_src_tree=args.kernel_src_tree)
        sys.exit(1)

    # Checkout the PR branch
    try:
        subprocess.run(
            ["git", "checkout", args.pr_branch], cwd=args.kernel_src_tree, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to checkout PR branch {args.pr_branch}: {e.stderr}")
        restore_git_branch(original_branch, kernel_src_tree=args.kernel_src_tree)
        sys.exit(1)

    # Get commits from merge_target to PR branch
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H", f"{args.merge_target}..{args.pr_branch}"],
            cwd=args.kernel_src_tree,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: failed to get commits: {e.stderr}")
        sys.exit(1)

    commit_shas = result.stdout.strip().split("\n") if result.stdout.strip() else []

    # Parse each commit and extract header
    commits_data = []
    for sha in commit_shas:
        if not sha:
            continue

        # Get full commit message
        try:
            result = subprocess.run(
                ["git", "show", "--format=%B", "--no-patch", sha],
                cwd=args.kernel_src_tree,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to get commits: {e.stderr}")
            sys.exit(1)

        commit_msg = result.stdout.strip()
        commit_header = CommitHeader.from_commit_body(commit_body=commit_msg)
        print(commit_header)
        lines = commit_msg.split("\n")

        # Extract summary line (first line)
        summary = lines[0] if lines else ""

        vuln_tickets = [commit_header.jira] if commit_header.jira else []
        commit_cves = commit_header.all_cves()

        # Check VULN tickets against merge target
        lts_match = None
        issues_list = []

        if vuln_tickets:
            for vuln_id in vuln_tickets:
                try:
                    issue = jira.issue(vuln_id)

                    # Get LTS product
                    lts_product_field = issue.get_field(jira_field_reverse["LTS Product"])
                    if hasattr(lts_product_field, "value"):
                        lts_product = lts_product_field.value
                    else:
                        lts_product = str(lts_product_field) if lts_product_field else None

                    # Get CVEs from JIRA ticket
                    ticket_cve_field = issue.get_field(jira_field_reverse["CVE"])
                    ticket_cves = set()

                    if ticket_cve_field:
                        # Handle different field types (string, list, or object)
                        if isinstance(ticket_cve_field, str):
                            # Split by common delimiters and extract CVE IDs
                            ticket_cves.update(re.findall(CVE_PATTERN, ticket_cve_field, re.IGNORECASE))
                        elif isinstance(ticket_cve_field, list):
                            for item in ticket_cve_field:
                                if isinstance(item, str):
                                    ticket_cves.update(re.findall(CVE_PATTERN, item, re.IGNORECASE))
                        else:
                            # Try to convert to string
                            ticket_cves.update(re.findall(CVE_PATTERN, str(ticket_cve_field), re.IGNORECASE))

                    # Normalize to uppercase
                    ticket_cves = {cve.upper() for cve in ticket_cves}

                    # Compare CVEs between commit and JIRA ticket
                    if commit_cves and ticket_cves:
                        commit_cves_set = set(commit_cves)
                        if not commit_cves_set.issubset(ticket_cves):
                            missing_in_ticket = commit_cves_set - ticket_cves
                            issues_list.append(
                                {
                                    "type": "error",
                                    "vuln_id": vuln_id,
                                    "message": f"CVE mismatch - Commit has {', '.join(sorted(missing_in_ticket))} but VULN ticket does not",
                                }
                            )
                        if not ticket_cves.issubset(commit_cves_set):
                            missing_in_commit = ticket_cves - commit_cves_set
                            issues_list.append(
                                {
                                    "type": "warning",
                                    "vuln_id": vuln_id,
                                    "message": f"VULN ticket has {', '.join(sorted(missing_in_commit))} but commit does not",
                                }
                            )
                    elif commit_cves and not ticket_cves:
                        issues_list.append(
                            {
                                "type": "warning",
                                "vuln_id": vuln_id,
                                "message": f"Commit has CVEs {', '.join(sorted(commit_cves))} but VULN ticket has no CVEs",
                            }
                        )
                    elif ticket_cves and not commit_cves:
                        issues_list.append(
                            {
                                "type": "warning",
                                "vuln_id": vuln_id,
                                "message": f"VULN ticket has CVEs {', '.join(sorted(ticket_cves))} but commit has no CVEs",
                            }
                        )

                    # Check ticket status
                    status = issue.fields.status.name
                    if status != "In Progress":
                        issues_list.append(
                            {
                                "type": "error",
                                "vuln_id": vuln_id,
                                "message": f"Status is '{status}', expected 'In Progress'",
                            }
                        )

                    # Check if time is logged
                    time_spent = issue.fields.timespent
                    if not time_spent or time_spent == 0:
                        issues_list.append(
                            {
                                "type": "warning",
                                "vuln_id": vuln_id,
                                "message": "No time logged - please log time manually",
                            }
                        )

                    # Check if LTS product matches merge target branch
                    if lts_product and lts_product in release_map:
                        expected_branch = release_map[lts_product]["src_git_branch"]
                        if expected_branch == args.merge_target:
                            lts_match = True
                        else:
                            lts_match = False
                            issues_list.append(
                                {
                                    "type": "error",
                                    "vuln_id": vuln_id,
                                    "message": f"LTS product '{lts_product}' expects branch '{expected_branch}', but merge target is '{args.merge_target}'",
                                }
                            )
                    else:
                        issues_list.append(
                            {
                                "type": "error",
                                "vuln_id": vuln_id,
                                "message": f"LTS product '{lts_product}' not found in release_map",
                            }
                        )

                except Exception as e:
                    issues_list.append(
                        {"type": "error", "vuln_id": vuln_id, "message": f"Failed to retrieve ticket: {e}"}
                    )

        commits_data.append(
            {
                "sha": sha,
                "summary": summary,
                "header": commit_header.to_str(),
                "full_message": commit_msg,
                "vuln_tickets": vuln_tickets,
                "lts_match": lts_match,
                "issues": issues_list,
            }
        )

    # Print formatted results
    print("\n## JIRA PR Check Results\n")

    commits_with_issues = [c for c in commits_data if c["issues"]]
    has_errors = False

    if commits_with_issues:
        print(f"**{len(commits_with_issues)} commit(s) with issues found:**\n")

        for commit in commits_with_issues:
            print(f"### Commit `{commit['sha'][:12]}`")
            print(f"**Summary:** {commit['summary']}\n")

            # Group issues by type
            errors = [i for i in commit["issues"] if i["type"] == "error"]
            warnings = [i for i in commit["issues"] if i["type"] == "warning"]

            if errors:
                has_errors = True
                print("**❌ Errors:**")
                for issue in errors:
                    print(f"- **{issue['vuln_id']}**: {issue['message']}")
                print()

            if warnings:
                print("**⚠️ Warnings:**")
                for issue in warnings:
                    print(f"- **{issue['vuln_id']}**: {issue['message']}")
                print()
    else:
        print("✅ **No issues found!**\n")

    print(f"\n---\n**Summary:** Checked {len(commits_data)} commit(s) total.")

    # Exit with error code if any errors were found
    if has_errors:
        restore_git_branch(original_branch, kernel_src_tree=args.kernel_src_tree)
        sys.exit(1)

    # Restore original branch
    restore_git_branch(original_branch, kernel_src_tree=args.kernel_src_tree)

    return jira, commits_data


if __name__ == "__main__":
    main()
