import argparse
import copy
import logging
import os
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
    CIQ_original_commit_author,
    CIQ_raise_or_warn,
    CIQ_reset_HEAD,
    CIQ_run_git,
    CIQ_setup_vulns_repo,
)
from kt.ktlib.commit_header import CommitHeader
from kt.ktlib.jira import JiraInstance

MERGE_MSG = git.Repo(os.getcwd()).git_dir + "/MERGE_MSG"
MERGE_MSG_BAK = f"{MERGE_MSG}.bak"


class CherryPickException(Exception):
    pass


class CherryPickCommand:
    def __init__(self, args):
        self._vulns_dir = args.vulns_dir
        self._ignore_fixes_check = args.ignore_fixes_check
        self._jira_dry_run = args.jira_dry_run
        jira_url = args.jira_url or os.environ.get("JIRA_URL")
        jira_user = args.jira_user or os.environ.get("JIRA_API_USER")
        jira_key = args.jira_key or os.environ.get("JIRA_API_TOKEN")

        # TODO temporary, this will be different per commit
        self._upstream_ref = args.upstream_ref
        if not all([jira_url, jira_user, jira_key]):
            print("[NOTE]: JIRA credentials not provided. Set via --jira-* args or environment variables.")
            self._jira_instance = None
        else:
            self._jira_instance = JiraInstance(
                server_url=jira_url, api_user=jira_user, api_key=jira_key, project_key="VULN"
            )

        # If cherry picking a CVE, set up the vulns repo as well
        if args.ciq_tag is not None:
            CIQ_setup_vulns_repo(vulns_repo=args.vulns_dir)

    # Helpers
    def _find_lts_kernel(self, jira_ticket):
        # TODO this won't be necessary when we move to kt
        # Could be multiple tickets separated by ',', use the first one
        ticket = jira_ticket.split(",")[0]
        issue = self._jira_instance.get_issue(issue_key=ticket)
        return issue.get_field("customfield_10381")

    def _adapt_cve_number_with_jira(self, commit_header: CommitHeader) -> CommitHeader:
        if not commit_header.is_cve():
            return commit_header

        origin_cve_number = commit_header.cve_number()

        vuln_cve_number = CIQ_find_matching_cve(
            vulns_repo=self._vulns_dir, kernel_repo=os.getcwd(), hash_=commit_header.commit
        )
        if not vuln_cve_number:
            # Continue with the existing tag
            return commit_header

        commit_header.set_cve(cve_number=vuln_cve_number)
        if not self._jira_instance or not commit_header.jira:
            return commit_header

        # Find the jira ticket corresponding to the CVE if it does not matches the original
        if vuln_cve_number != origin_cve_number:
            kernel = self._find_lts_kernel(jira_ticket=commit_header.jira)
            jira_query = f'''"sRPM[Short text]" ~ "kernel" and "LTS Product[Dropdown]" = "{kernel}" and "CVE ID[Short text]" = "{vuln_cve_number}"'''
            issues, _ = self._jira_instance.search_issues(jql=jira_query)
            if issues:
                new_jira = issues[0].key
                commit_header.jira = new_jira
            else:
                print(
                    f"[WARNING] Could not find ticket for {vuln_cve_number} for {kernel}, using old ticket {commit_header.jira}"
                )

        return commit_header

    def _update_jira_success(self, ticket_key: str):
        if ticket_key is None:
            return

        if self._jira_dry_run:
            print(f"[DRY-RUN] Would assign {ticket_key}")
            print(f"[DRY-RUN] Would transition {ticket_key} to In Progress")
            print(f"[DRY-RUN] Would add a label: automated-patch-applied to {ticket_key}")
            print(
                f"[DRY-RUN] Would add worklog: 30m time spent with comment 'CVE automation: Applied upstream patch' to {ticket_key}"
            )

            return

        if self._jira_instance is None:
            return

        self._jira_instance.assign_ticket(issue_key=ticket_key)
        self._jira_instance.transition_issue(issue_key=ticket_key, transition_name="In Progress")
        self._jira_instance.update_labels(issue_key=ticket_key, labels=["automated-patch-applied"])
        self._jira_instance.add_worklog(
            issue_key=ticket_key,
            time_spent="30m",
            comment="CVE automation: Applied upstream patch",
            started=datetime.now(),
        )

    def _update_jira_failure(self, ticket_key: str):
        if ticket_key is None:
            return

        if self._jira_dry_run:
            print(f"[DRY-RUN] Would add a label: automated-patch-failed to {ticket_key}")
            return

        if self._jira_instance is None:
            return

        self._jira_instance.update_labels(issue_key=ticket_key, labels=["automated-patch-failed"])

    def _check_fixes(self, sha):
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
        CIQ_raise_or_warn(cond=not_present_fixes, error_msg=err, warn=self._ignore_fixes_check)

    def _manage_commit_message(self, commit_header: CommitHeader, commit_successful: bool):
        """
        Standardize the commit message by including the ciq_tags, original
        author and the original commit full sha.

        Original message location: MERGE_MSG
        Makes a copy of the original message in MERGE_MSG_BAK

        The new standardized commit message is written to MERGE_MSG
        """

        subprocess.run(["cp", MERGE_MSG, MERGE_MSG_BAK], check=True)

        # TODO maybe do it earlier, idk
        author = CIQ_original_commit_author(repo_path=os.getcwd(), sha=commit_header.commit)
        if author is None:
            raise RuntimeError(f"Could not find author of commit {commit_header.commit}")
        commit_header.commit_author = author

        try:
            with open(MERGE_MSG, "r") as file:
                original_msg = file.readlines()
        except IOError as e:
            raise RuntimeError(f"Failed to read commit message from {MERGE_MSG}: {e}") from e

        if not commit_successful:
            commit_header.upstream_diff = "|"

        new_msg = CIQ_cherry_pick_commit_standardization(lines=original_msg, commit_header=commit_header)

        print(f"Cherry Pick New Message for {commit_header.commit}")
        print(f"\n Original Message located here: {MERGE_MSG_BAK}")

        try:
            with open(MERGE_MSG, "w") as file:
                file.writelines(new_msg)
        except IOError as e:
            raise RuntimeError(f"Failed to write commit message to {MERGE_MSG}: {e}") from e

    def full_cherry_pick(self, commit_header: CommitHeader):
        """
        Cherry picks a commit from upstream-ref along with its Fixes: references.
        If cherry-pick or cherry_pick_fixes fail, the exception is propagated
        If one of the cherry picks fails, an exception is returned and the previous
        successful cherry picks are left as they are.
        """

        updated_commit_header = self._adapt_cve_number_with_jira(commit_header=commit_header)

        # Cherry pick the commit
        try:
            self._cherry_pick(commit_header=updated_commit_header)
        except (CherryPickException, RuntimeError) as e:
            self._update_jira_failure(ticket_key=updated_commit_header.jira)
            raise e

        # Cherry pick the fixed-by dependencies
        try:
            self._cherry_pick_fixes(original_commit_header=updated_commit_header)
        except (CherryPickException, RuntimeError) as e:
            # TODO would add some extra information to jira if the cve-bf deps are not applied
            raise e

        # Update jira only if its deps are applied as well
        self._update_jira_success(ticket_key=updated_commit_header.jira)

    def _cherry_pick(self, commit_header: CommitHeader):
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
            full_sha = CIQ_get_full_hash(repo=os.getcwd(), short_hash=commit_header.commit)
        except RuntimeError as e:
            raise RuntimeError(f"Invalid commit SHA {commit_header.commit}: {e}") from e

        commit_header.commit = full_sha
        self._check_fixes(sha=full_sha)

        # Commit message is in MERGE_MSG
        commit_successful = True
        try:
            CIQ_run_git(repo_path=os.getcwd(), args=["cherry-pick", "-nsx", full_sha])
        except RuntimeError:
            commit_successful = False

        try:
            self._manage_commit_message(commit_header=commit_header, commit_successful=commit_successful)
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

    def _cherry_pick_fixes(self, original_commit_header: CommitHeader):
        """
        Check upstream_ref for commits that have this reference:
        Fixes: <sha>. If any, these will also be cherry picked with the ciq
        tag = cve-bf. If the tag was cve-pre, it stays the same.
        """
        fixes_in_mainline = CIQ_find_fixes_in_mainline_current_branch_unapplied(
            repo=os.getcwd(), upstream_ref=self._upstream_ref, hash_=original_commit_header.commit
        )

        for full_hash, display_str in fixes_in_mainline:
            print(f"Extra cherry picking {full_hash}: {display_str}")
            bf_commit_header = copy.deepcopy(original_commit_header)
            bf_commit_header.make_it_cve_bf()
            bf_commit_header.commit = full_hash
            self.full_cherry_pick(commit_header=bf_commit_header)


def from_argsparse_to_commit_header(args: argparse.Namespace) -> CommitHeader:
    args_dict = vars(args)
    tags = []
    if args.ciq_tag is not None:
        tags = args.ciq_tag.split(",")  # TODO make it smarter maybe idk

        for tag in tags:
            name, value = tag.split(" ")
            args_dict[name] = value
    print(args)

    return CommitHeader.from_dict(args_dict)


if __name__ == "__main__":
    print("CIQ custom cherry picker")

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--commit", help="Target SHA1 to cherry-pick", required=True)
    parser.add_argument("--jira", help="Ticket associated to cherry-pick work, comma separated list is supported.")
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

    # TODO move this to CommitHEADEr maybe
    # Expand the provided SHA1 to the full SHA1 in case it's either abbreviated or an expression
    git_sha_res = subprocess.run(["git", "show", "--pretty=%H", "-s", args.commit], stdout=subprocess.PIPE)
    if git_sha_res.returncode != 0:
        print(f"[FAILED] git show --pretty=%H -s {args.sha}")
        print("Subprocess Call:")
        print(git_sha_res)
        print("")
    else:
        args.commit = git_sha_res.stdout.decode("utf-8").strip()

    try:
        cherry_pick_command = CherryPickCommand(args=args)
    except Exception as e:
        print(f"Setting chery pick command went wrong {e}")

    commit_header = from_argsparse_to_commit_header(args)
    print(commit_header)

    try:
        cherry_pick_command.full_cherry_pick(commit_header=commit_header)
    except CherryPickException as e:
        logging.error(e)
        sys.exit(1)
    except Exception as e:
        logging.error(f"full_cherry_pick failed {e}")
        traceback.print_exc()
        sys.exit(1)
