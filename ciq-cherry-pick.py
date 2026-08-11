import argparse
import logging
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime

import git

from kt.ktlib.ciq_helpers import (
    CIQ_cherry_pick_commit_standardization,
    CIQ_commit_exists_in_current_branch,
    CIQ_find_fixes_in_mainline_current_branch_unapplied,
    CIQ_find_matching_cve,
    CIQ_fixes_references,
    CIQ_get_full_hash,
    CIQ_original_commit_author_to_tag_string,
    CIQ_raise_or_warn,
    CIQ_reset_HEAD,
    CIQ_run_git,
    CIQ_setup_vulns_repo,
)
from kt.ktlib.jira import JiraInstance

MERGE_MSG = git.Repo(os.getcwd()).git_dir + "/MERGE_MSG"
MERGE_MSG_BAK = f"{MERGE_MSG}.bak"


class CherryPickException(Exception):
    pass


def extract_cve_from_tag(tag):
    """
    Extract CVE ID from matches like 'cve CVE-2026-1234' or 'cve-bf CVE-2026-1234'
    Return None if no match
    """
    match = re.search(r"(?<!\S)(cve|cve-bf)\s+(CVE-\d{4}-\d+)", tag, re.IGNORECASE)
    if match:
        return match.group(2).upper()
    return None


def find_lts_kernel(jira_instance, jira_ticket):
    # Could be multiple tickets separated by ',', use the first one
    ticket = jira_ticket.split(",")[0]
    issue = jira_instance.get_issue(issue_key=ticket)
    return issue.get_field("customfield_10381")


def check_cve_number(sha, ciq_tags, jira_ticket, jira_instance, vulns_repo):
    # If ciq_tags are None it means the cherry pick is not for a cve backport, so this check is not relevant
    if not ciq_tags:
        return ciq_tags, jira_ticket

    # Temporary check until I figure out if we really need multiple tags
    if len(ciq_tags) != 1:
        print(f"len(ciq tags) != 1, not sure what to do: {ciq_tags}")
        return ciq_tags, jira_ticket

    if "cve" not in ciq_tags[0]:
        # Not a cve, not interested
        return ciq_tags, jira_ticket

    matching_cve = CIQ_find_matching_cve(vulns_repo=vulns_repo, kernel_repo=os.getcwd(), hash_=sha)
    if not matching_cve:
        return ciq_tags, jira_ticket

    new_ciq_tags = [f"cve {matching_cve}"]
    new_jira = jira_ticket

    print(f"CVE {matching_cve} for hash {sha} and original tags {ciq_tags}")

    if not jira_instance or not jira_ticket:
        return new_ciq_tags, new_jira

    # Find the jira ticket corresponding to the CVE only if jira_instance
    kernel = find_lts_kernel(jira_instance=jira_instance, jira_ticket=jira_ticket)
    origin_cve = extract_cve_from_tag(ciq_tags[0])
    if matching_cve != origin_cve:
        jira_query = f'''"sRPM[Short text]" ~ "kernel" and "LTS Product[Dropdown]" = "{kernel}" and "CVE ID[Short text]" = "{matching_cve}"'''
        issues, _ = jira_instance.search_issues(jql=jira_query)
        if issues:
            new_jira = issues[0].key
        else:
            print(f"[WARNING] Could not find ticket for {matching_cve} for {kernel}, using old ticket {jira_ticket}")

    return new_ciq_tags, new_jira


def update_jira_success(jira_instance, ticket_key, jira_dry_run):
    if ticket_key is None:
        return

    if jira_dry_run:
        print(f"[DRY-RUN] Would assign {ticket_key}")
        print(f"[DRY-RUN] Would transition {ticket_key} to In Progress")
        print(f"[DRY-RUN] Would add a label: automated-patch-applied to {ticket_key}")
        print(
            f"[DRY-RUN] Would add worklog: 30m time spent with comment 'CVE automation: Applied upstream patch' to {ticket_key}"
        )

        return

    if jira_instance is None:
        return

    jira_instance.assign_ticket(issue_key=ticket_key)
    jira_instance.transition_issue(issue_key=ticket_key, transition_name="In Progress")
    jira_instance.update_labels(issue_key=ticket_key, labels=["automated-patch-applied"])
    jira_instance.add_worklog(
        issue_key=ticket_key,
        time_spent="30m",
        comment="CVE automation: Applied upstream patch",
        started=datetime.now(),
    )


def update_jira_failure(jira_instance, ticket_key, jira_dry_run):
    if ticket_key is None:
        return

    if jira_dry_run:
        print(f"[DRY-RUN] Would add a label: automated-patch-failed to {ticket_key}")
        return

    if jira_instance is None:
        return

    jira_instance.update_labels(issue_key=ticket_key, labels=["automated-patch-failed"])


def check_fixes(sha, ignore_fixes_check):
    """
    Checks if commit has "Fixes:" references and if so, it checks if the
    commit(s) that it tries to fix are part of the current branch
    """

    fixes = CIQ_fixes_references(repo_path=os.getcwd(), sha=sha)
    if len(fixes) == 0:
        logging.warning("The commit you try to cherry pick has no Fixes: reference; review it carefully")
        return

    not_present_fixes = []
    for fix in fixes:
        if not CIQ_commit_exists_in_current_branch(os.getcwd(), fix):
            not_present_fixes.append(fix)

    err = f"The commit you want to cherry pick has the following Fixes: references that are not part of the tree {not_present_fixes}"
    CIQ_raise_or_warn(cond=not_present_fixes, error_msg=err, warn=ignore_fixes_check)


def manage_commit_message(full_sha, ciq_tags, jira_ticket, commit_successful):
    """
    Standardize the commit message by including the ciq_tags, original
    author and the original commit full sha.

    Original message location: MERGE_MSG
    Makes a copy of the original message in MERGE_MSG_BAK

    The new standardized commit message is written to MERGE_MSG
    """

    subprocess.run(["cp", MERGE_MSG, MERGE_MSG_BAK], check=True)

    # Make sure it's a deep copy because ciq_tags may be used for other cherry-picks
    new_tags = [tag for tag in ciq_tags]

    author = CIQ_original_commit_author_to_tag_string(repo_path=os.getcwd(), sha=full_sha)
    if author is None:
        raise RuntimeError(f"Could not find author of commit {full_sha}")

    new_tags.append(author)
    try:
        with open(MERGE_MSG, "r") as file:
            original_msg = file.readlines()
    except IOError as e:
        raise RuntimeError(f"Failed to read commit message from {MERGE_MSG}: {e}") from e

    # git appends a "# Conflicts:" comment block to MERGE_MSG on a conflicted
    # cherry-pick, and committing with -F doesn't strip comment lines. Drop the
    # block to keep it out of the final commit message.
    for i, line in enumerate(original_msg):
        if line.rstrip("\n") == "# Conflicts:":
            original_msg = original_msg[:i]
            break

    optional_msg = "" if commit_successful else "upstream-diff |"
    new_msg = CIQ_cherry_pick_commit_standardization(
        original_msg, full_sha, jira=jira_ticket, tags=new_tags, optional_msg=optional_msg
    )

    print(f"Cherry Pick New Message for {full_sha}")
    print(f"\n Original Message located here: {MERGE_MSG_BAK}")

    try:
        with open(MERGE_MSG, "w") as file:
            file.writelines(new_msg)
    except IOError as e:
        raise RuntimeError(f"Failed to write commit message to {MERGE_MSG}: {e}") from e


def cherry_pick(sha, ciq_tags, jira_ticket, ignore_fixes_check):
    """
    Cherry picks a commit and it adds the ciq standardized format
    In case of error (cherry pick conflict):
        - MERGE_MSG.bak contains the original commit message
        - MERGE_MSG contains the standardized commit message
        - Conflict has to be solved manually
    In case of runtime errors that are not cherry pick conflicts, the cherry
    pick changes are reverted. (git reset --hard HEAD)

    In case of success:
        - the commit is cherry picked
        - MERGE_MSG.bak is deleted
        - You can still see MERGE_MSG for the original message
    """

    # Expand the provided SHA1 to the full SHA1 in case it's either abbreviated or an expression
    try:
        full_sha = CIQ_get_full_hash(repo=os.getcwd(), short_hash=sha)
    except RuntimeError as e:
        raise RuntimeError(f"Invalid commit SHA {sha}: {e}") from e

    check_fixes(sha=full_sha, ignore_fixes_check=ignore_fixes_check)

    # Commit message is in MERGE_MSG
    commit_successful = True
    try:
        CIQ_run_git(repo_path=os.getcwd(), args=["cherry-pick", "-nsx", full_sha])
    except RuntimeError:
        commit_successful = False

    try:
        manage_commit_message(
            full_sha=full_sha, ciq_tags=ciq_tags, jira_ticket=jira_ticket, commit_successful=commit_successful
        )
    except RuntimeError as e:
        CIQ_reset_HEAD(repo=os.getcwd())
        raise RuntimeError(f"Could not create proper commit message: {e}") from e

    if not commit_successful:
        error_str = (
            f"[FAILED] git cherry-pick -nsx {full_sha}\n"
            "Manually resolve conflict and add explanation under `upstream-diff` tag in commit message\n"
        )
        raise CherryPickException(error_str)

    CIQ_run_git(repo_path=os.getcwd(), args=["commit", "-F", MERGE_MSG])


def cherry_pick_fixes(
    sha, ciq_tags, jira_ticket, upstream_ref, ignore_fixes_check, jira_instance, vulns_repo, jira_dry_run
):
    """
    Check upstream_ref for commits that have this reference:
    Fixes: <sha>. If any, these will also be cherry picked with the ciq
    tag = cve-bf. If the tag was cve-pre, it stays the same.
    """
    fixes_in_mainline = CIQ_find_fixes_in_mainline_current_branch_unapplied(
        repo=os.getcwd(), upstream_ref=upstream_ref, hash_=sha
    )

    # Replace cve with cve-bf
    # Leave cve-pre and cve-bf as they are
    bf_ciq_tags = [re.sub(r"^cve ", "cve-bf ", tag.strip()) for tag in ciq_tags]
    for full_hash, display_str in fixes_in_mainline:
        print(f"Extra cherry picking {display_str}")
        full_cherry_pick(
            sha=full_hash,
            ciq_tags=bf_ciq_tags,
            jira_ticket=jira_ticket,
            upstream_ref=upstream_ref,
            ignore_fixes_check=ignore_fixes_check,
            jira_instance=jira_instance,
            vulns_repo=vulns_repo,
            jira_dry_run=jira_dry_run,
        )


def full_cherry_pick(
    sha, ciq_tags, jira_ticket, upstream_ref, ignore_fixes_check, jira_instance, vulns_repo, jira_dry_run
):
    """
    Cherry picks a commit from upstream-ref along with its Fixes: references.
    If cherry-pick or cherry_pick_fixes fail, the exception is propagated
    If one of the cherry picks fails, an exception is returned and the previous
    successful cherry picks are left as they are.
    """

    # Double check if cve number and jira matches the actual commit
    updated_ciq_tags, updated_jira_ticket = check_cve_number(
        sha=sha,
        ciq_tags=ciq_tags,
        jira_ticket=jira_ticket,
        jira_instance=jira_instance,
        vulns_repo=vulns_repo,
    )

    # Cherry pick the commit
    try:
        cherry_pick(
            sha=sha,
            ciq_tags=updated_ciq_tags,
            jira_ticket=updated_jira_ticket,
            ignore_fixes_check=ignore_fixes_check,
        )
    except (CherryPickException, RuntimeError) as e:
        update_jira_failure(jira_instance=jira_instance, ticket_key=updated_jira_ticket, jira_dry_run=jira_dry_run)
        raise e

    # Cherry pick the fixed-by dependencies
    try:
        cherry_pick_fixes(
            sha=sha,
            ciq_tags=updated_ciq_tags,
            jira_ticket=updated_jira_ticket,
            upstream_ref=upstream_ref,
            ignore_fixes_check=ignore_fixes_check,
            jira_instance=jira_instance,
            vulns_repo=vulns_repo,
            jira_dry_run=jira_dry_run,
        )
    except (CherryPickException, RuntimeError) as e:
        # TODO would add some extra information to jira if the cve-bf deps are not applied
        raise e

    # Update jira only if its deps are applied as well
    update_jira_success(jira_instance=jira_instance, ticket_key=updated_jira_ticket, jira_dry_run=jira_dry_run)


if __name__ == "__main__":
    print("CIQ custom cherry picker")

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--sha", help="Target SHA1 to cherry-pick", required=True)
    parser.add_argument("--ticket", help="Ticket associated to cherry-pick work, comma separated list is supported.")
    parser.add_argument(
        "--ciq-tag",
        help="Tags for commit message <feature><-optional modifier> <identifier>.\n"
        "example: cve CVE-2022-45884 - A patch for a CVE Fix.\n"
        "         cve-bf CVE-1974-0001 - A bug fix for a CVE currently being patched\n"
        "         cve-pre CVE-1974-0001 - A pre-condition or dependency needed for the CVE\n"
        "Multiple tags are separated with a comma. ex: cve CVE-1974-0001, cve CVE-1974-0002\n",
    )
    parser.add_argument(
        "--upstream-ref",
        default="origin/kernel-mainline",
        help="Reference to upstream mainline branch (default: origin/kernel-mainline)",
    )
    parser.add_argument(
        "--ignore-fixes-check",
        action="store_true",
        help="Continue even if the commit(s) referenced in Fixes: tags are not present in the current branch",
    )
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
        help="JIRA API Key",
    )
    parser.add_argument(
        "--jira-dry-run",
        help="Do not make any changes to JIRA, just print what would be done",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--vulns-dir", default="../vulns", help="Path to the kernel vulnerabilities repo (default: ../vulns)"
    )
    args = parser.parse_args()

    jira_url = args.jira_url or os.environ.get("JIRA_URL")
    jira_user = args.jira_user or os.environ.get("JIRA_API_USER")
    jira_key = args.jira_key or os.environ.get("JIRA_API_TOKEN")

    if not all([jira_url, jira_user, jira_key]):
        print("[NOTE]: JIRA credentials not provided. Set via --jira-* args or environment variables.")
        jira_instance = None
    else:
        jira_instance = JiraInstance(server_url=jira_url, api_user=jira_user, api_key=jira_key, project_key="VULN")

    if args.ciq_tag is not None:
        try:
            CIQ_setup_vulns_repo(vulns_repo=args.vulns_dir)
        except RuntimeError as e:
            print(e)
            sys.exit(1)

    # Expand the provided SHA1 to the full SHA1 in case it's either abbreviated or an expression
    git_sha_res = subprocess.run(["git", "show", "--pretty=%H", "-s", args.sha], stdout=subprocess.PIPE)
    if git_sha_res.returncode != 0:
        print(f"[FAILED] git show --pretty=%H -s {args.sha}")
        print("Subprocess Call:")
        print(git_sha_res)
        print("")
    else:
        args.sha = git_sha_res.stdout.decode("utf-8").strip()

    tags = []
    if args.ciq_tag is not None:
        tags = args.ciq_tag.split(",")

    try:
        full_cherry_pick(
            sha=args.sha,
            ciq_tags=tags,
            jira_ticket=args.ticket,
            upstream_ref=args.upstream_ref,
            ignore_fixes_check=args.ignore_fixes_check,
            jira_instance=jira_instance,
            vulns_repo=args.vulns_dir,
            jira_dry_run=args.jira_dry_run,
        )
    except CherryPickException as e:
        logging.error(e)
        sys.exit(1)
    except Exception as e:
        logging.error(f"full_cherry_pick failed {e}")
        traceback.print_exc()
        sys.exit(1)
