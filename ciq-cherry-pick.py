import argparse
import logging
import os
import re
import subprocess

import git

from ciq_helpers import (
    CIQ_cherry_pick_commit_standardization,
    CIQ_commit_exists_in_current_branch,
    CIQ_find_fixes_in_mainline_current_branch,
    CIQ_fixes_references,
    CIQ_get_full_hash,
    CIQ_original_commit_author_to_tag_string,
)

MERGE_MSG = git.Repo(os.getcwd()).git_dir + "/MERGE_MSG"


def check_fixes(sha):
    """
    Checks if commit has "Fixes:" references and if so, it checks if the
    commit(s) that it tries to fix are part of the current branch
    """

    fixes = CIQ_fixes_references(repo_path=".", sha=sha)
    if len(fixes) == 0:
        logging.warning("The commit you try to cherry pick has no Fixes: reference; review it carefully")
        return

    for fix in fixes:
        if not CIQ_commit_exists_in_current_branch(".", fix):
            raise RuntimeError(f"The commit you want to cherry pick references a Fixes {fix}: but this is not here")


def cherry_pick(sha, ciq_tags, jira_ticket):
    # Expand the provided SHA1 to the full SHA1 in case it's either abbreviated or an expression
    full_sha = CIQ_get_full_hash(".", sha)

    check_fixes(full_sha)

    author = CIQ_original_commit_author_to_tag_string(repo_path=os.getcwd(), sha=full_sha)
    if author is None:  # TODO raise Exception maybe
        exit(1)

    git_res = subprocess.run(["git", "cherry-pick", "-nsx", full_sha])  # Move it into a separate method
    if git_res.returncode != 0:
        print(f"[FAILED] git cherry-pick -nsx {args.sha}")
        print("       Manually resolve conflict and include `upstream-diff` tag in commit message")
        print("Subprocess Call:")
        print(git_res)
        print("")

    print(os.getcwd())
    subprocess.run(["cp", MERGE_MSG, f"{MERGE_MSG}.bak"])

    tags.append(author)

    with open(MERGE_MSG, "r") as file:
        original_msg = file.readlines()

    new_msg = CIQ_cherry_pick_commit_standardization(original_msg, full_sha, jira=jira_ticket, tags=ciq_tags)

    print(f"Cherry Pick New Message for {args.sha}")
    print(f"\n Original Message located here: {MERGE_MSG}.bak")

    with open(MERGE_MSG, "w") as file:
        file.writelines(new_msg)

    if git_res.returncode == 0:
        subprocess.run(["git", "commit", "-F", MERGE_MSG])


def cherry_pick_fixes(sha, ciq_tags, jira_ticket, upstream_ref):
    fixes_in_mainline = CIQ_find_fixes_in_mainline_current_branch(".", upstream_ref, sha)

    # Replace cve with cve-bf
    # Leave cve-pre and cve-bf as they are
    ciq_tags = [re.sub(r"^cve ", "cve-bf ", s) for s in ciq_tags]
    for full_hash, display_str in fixes_in_mainline:
        print(f"Extra cherry picking {display_str}")
        full_cherry_pick(sha=full_hash, ciq_tags=ciq_tags, jira_ticket=jira_ticket, upstream_ref=upstream_ref)


def full_cherry_pick(sha, ciq_tags, jira_ticket, upstream_ref):
    # Cherry pick the commit
    cherry_pick(sha=sha, ciq_tags=ciq_tags, jira_ticket=jira_ticket)

    # Cherry pick the fixed-by dependencies
    cherry_pick_fixes(sha=sha, ciq_tags=ciq_tags, jira_ticket=jira_ticket, upstream_ref=upstream_ref)


if __name__ == "__main__":
    print("CIQ custom cherry picker")
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--sha", help="Target SHA1 to cherry-pick")
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

    args = parser.parse_args()

    tags = []
    if args.ciq_tag is not None:
        tags = args.ciq_tag.split(",")

    full_cherry_pick(sha=args.sha, ciq_tags=tags, jira_ticket=args.ticket, upstream_ref=args.upstream_ref)
