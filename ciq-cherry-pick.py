import argparse
import logging
import os
import re
import subprocess
import traceback

import git

from ciq_helpers import (
    CIQ_cherry_pick_commit_standardization,
    CIQ_commit_exists_in_current_branch,
    CIQ_find_fixes_in_mainline_current_branch,
    CIQ_fixes_references,
    CIQ_get_full_hash,
    CIQ_original_commit_author_to_tag_string,
    CIQ_raise_or_warn,
    CIQ_reset_HEAD,
    CIQ_run_git,
)

MERGE_MSG = git.Repo(os.getcwd()).git_dir + "/MERGE_MSG"
MERGE_MSG_BAK = f"{MERGE_MSG}.bak"


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
    CIQ_raise_or_warn(cond=not not_present_fixes, error_msg=err, warn=ignore_fixes_check)


def manage_commit_message(full_sha, ciq_tags, jira_ticket, commit_successful):
    """
    It standardize the commit message by including the ciq_tags, original
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
    In case runtime errors that are not cherry pick conflicts, the cherry
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
        raise RuntimeError(error_str)

    CIQ_run_git(repo_path=os.getcwd(), args=["commit", "-F", MERGE_MSG])


def cherry_pick_fixes(sha, ciq_tags, jira_ticket, upstream_ref, ignore_fixes_check):
    """
    It checks upstream_ref for commits that have this reference:
    Fixes: <sha>. If any, these will also be cherry picked with the ciq
    tag = cve-bf. If the tag was cve-pre, it stays the same.
    """
    fixes_in_mainline = CIQ_find_fixes_in_mainline_current_branch(os.getcwd(), upstream_ref, sha)

    # Replace cve with cve-bf
    # Leave cve-pre and cve-bf as they are
    bf_ciq_tags = [re.sub(r"^cve ", "cve-bf ", s) for s in ciq_tags]
    for full_hash, display_str in fixes_in_mainline:
        print(f"Extra cherry picking {display_str}")
        full_cherry_pick(
            sha=full_hash,
            ciq_tags=bf_ciq_tags,
            jira_ticket=jira_ticket,
            upstream_ref=upstream_ref,
            ignore_fixes_check=ignore_fixes_check,
        )


def full_cherry_pick(sha, ciq_tags, jira_ticket, upstream_ref, ignore_fixes_check):
    """
    It cherry picks a commit from upstream-ref along with its Fixes: references.
    If cherry-pick or cherry_pick_fixes fail, the exception is propagated
    If one of the cherry picks fails, an exception is returned and the previous
    successful cherry picks are left as they are.
    """
    # Cherry pick the commit
    cherry_pick(sha=sha, ciq_tags=ciq_tags, jira_ticket=jira_ticket, ignore_fixes_check=ignore_fixes_check)

    # Cherry pick the fixed-by dependencies
    cherry_pick_fixes(
        sha=sha,
        ciq_tags=ciq_tags,
        jira_ticket=jira_ticket,
        upstream_ref=upstream_ref,
        ignore_fixes_check=ignore_fixes_check,
    )


if __name__ == "__main__":
    print("CIQ custom cherry picker")
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
        help="If the commit(s) this commit is trying to fix are not part of the tree, do not exit",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

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
        )
    except Exception as e:
        print(f"full_cherry_pick failed {e}")
        traceback.print_exc()
        exit(1)
