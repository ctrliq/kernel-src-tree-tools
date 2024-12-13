#!/usr/bin/env python3
#

# CIQ Kernel Tools  function library

import git
import os
import re
import subprocess


def process_full_commit_message(commit):
    """Process the full git commit message specific to the CIQ Kernel Tools.
    NOTE: This has only been tested with byte strings and not unicode strings.

    Parameters:
    commit: <byte string array> The full commit message from a git commit.

    Return:
    upstream_commit: The upstream commit SHA1.
    cves: A list of CVEs.
    tickets: The ticket number.
    upstream_subject: The subject of the commit.
    repo_commit: The repo commit SHA1.
    """

    cves = []
    tickets = []
    upstream_commit = ""
    repo_commit = ""
    upstream_subject = ""

    repo_commit = commit[0].decode("utf-8").split()[1]
    upstream_subject = commit[4].decode("utf-8").strip()
    for line in commit[5:]:
        if re.match(b"^    jira", line, re.IGNORECASE):
            tickets.append(line.decode("utf-8").strip().split()[1:])
        elif re.match(b"^    cve", line, re.IGNORECASE):
            cves.append(line.decode("utf-8").strip().split()[1:])
        elif re.match(b"^    commit ", line, re.IGNORECASE):
            _commit = line.decode("utf-8").strip().split()
            if len(_commit) > 1:
                upstream_commit = _commit[1]
        if line.decode("utf-8").strip() == "" and upstream_commit:
            break

    return upstream_commit, cves, tickets, upstream_subject, repo_commit


def get_backport_commit_data(repo, branch, common_ancestor, allow_duplicates=False):
    """Get a dictionary of backport commits from a repo on a branch to the common ancestor.
    parameters
    repo: The git repo patch to the source
    branch: The branch we're building the backport data from
    common_ancestor: The Tag on Linus Mainline that is the common ancestor for the branch, this is where we stop
        looking for commits.  This is the tag that was used to create the branch.
    allow_duplicates: Allow duplicate commits in the backport data, this will overwrite the first one.
        Default is False.
        Note: This option is added because due to CentOS's cherry-pick process, we may have duplicate backprots in the
            backport data due to inconsistent changelog histories.

    Return: Dictoionary of backport commits
    "upstream_commmit": {
        "repo_commit": "SHA1",
        "upstream_subject": "Subject",
        "cves": ["tag1", "tag2"], (Optional)
        "tickets": ["JIRA-1234"], (Optional)
    }
    """
    upstream_commits = {}
    subprocess.run(
        ["git", "checkout", "-f", branch],
        cwd=repo,
        timeout=240,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    cmd = ["git", "log", "--no-abbrev-commit", common_ancestor + "~1.." + branch]
    res = subprocess.run(cmd, cwd=repo, timeout=240, check=True, stdout=subprocess.PIPE)
    lines = res.stdout.splitlines()

    commit = []

    for line in lines:
        if len(commit) > 0 and line.startswith(b"commit "):
            upstream_commit, cves, tickets, upstream_subject, repo_commit = (
                process_full_commit_message(commit)
            )
            if upstream_commit in upstream_commits:
                print(f"WARNING: {upstream_commit} already in upstream_commits")
                if not allow_duplicates:
                    return upstream_commits, False
            if upstream_commit != "":
                upstream_commits[upstream_commit] = {
                    "repo_commit": repo_commit,
                    "upstream_subject": upstream_subject,
                    "cves": cves,
                    "tickets": tickets,
                }
            commit = []
        commit.append(line)

    return upstream_commits, True


def CIQ_cherry_pick_commit_standardization(
    lines, commit, tags=None, jira="", optional_msg=""
):
    """Standardize CIQ the cherry-pick commit message.
    Parameters:
    lines: Original SHAS commit message.
    commit: The commit SHA1 that was cherry-picked.
    tags: A list of tags to add to the commit message.
    jira: The JIRA number to add to the commit message.
    optional_msg: An optional message to add to the commit message.  Traditionally used for `upstream-diff`.

    Return: The modified commit message passed in as lines.
    """

    # assemble in reverse by inserting lines below first blank line (line 2)
    lines.insert(2, "\n")
    if optional_msg != "":
        lines.insert(2, f"{optional_msg}\n")
    lines.insert(2, f"commit {commit}\n")
    if tags:
        for tag in tags[::-1]:
            lines.insert(2, f"{tag}\n")
    if jira:
        lines.insert(2, f"jira {jira}\n")

    # We Need to indent lines that have email addresss as some tooling in the community
    # will atttempt to read these lines and email everyone on the list.  We do not want
    # to annoy the community when doing our own work.
    for i in range(5, len(lines)):
        # The (cherry Picked from commit: <sha1>) line is the indicator we cherry-picked
        if lines[i].startswith("cherry picked from commit"):
            break
        if (
            lines[i].startswith("Signed-off-by")
            or lines[i].startswith("Reported-by")
            or lines[i].startswith("Cc:")
            or lines[i].startswith("Reviewed-by")
            or lines[i].startswith("Tested-by")
            or lines[i].startswith("Debugged-by")
            or lines[i].startswith("Acked-by")
            or lines[i].startswith("Suggested-by")
        ):
            lines[i] = f"\t{lines[i]}"
    return lines


def CIQ_original_commit_author_to_tag_string(repo_path, sha):
    """This will grab the original commit author and return the "tag" we use for the CIQ based header
    Parameters:
    repo_path: pwd to the repository with the kernel mainline remote
    sha: this is the full commit sha we're going to backport

    Return: String for Tag
    """
    git_auth_res = subprocess.run(['git', 'show', '--pretty="%aN <%aE>"', '--no-patch', sha], stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE, cwd=repo_path)
    if git_auth_res.returncode != 0:
        print(f"[FAILED] git show --pretty='%aN <%aE>' --no-patch {sha}")
        print(f"[FAILED][STDERR:{git_auth_res.returncode}] {git_auth_res.stderr.decode('utf-8')}")
        return None
    return "commit-author " + git_auth_res.stdout.decode('utf-8').replace('\"', '').strip()


def repo_init(repo):
    """Initialize a git repo object.

    Parameters:
    repo: The path to the git repo.

    Return: The git repo object.
    """
    if os.path.isdir(repo):
        return git.Repo.init(repo)
    return None


def last_git_tag(repo):
    """Returns the most recent tag for repo.

    Repo can either be a path to a repo or a git repo object.
    """
    if isinstance(repo, str) and os.path.isdir(repo):
        repo = git.Repo.init(repo)
    r = repo.git.describe("--tags", "--abbrev=0")
    if not r:
        raise Exception("Could not find last tag for", repo)
    return r
