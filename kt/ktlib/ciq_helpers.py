#!/usr/bin/env python3
#

# CIQ Kernel Tools  function library

import logging
import os
import re
import subprocess
import sys
from typing import Optional

import git


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
            upstream_commit, cves, tickets, upstream_subject, repo_commit = process_full_commit_message(commit)
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


def CIQ_cherry_pick_commit_standardization(lines, commit, tags=None, jira="", optional_msg=""):
    """Standardize CIQ the cherry-pick commit message.
    Parameters:
    lines: Original SHAS commit message.
    commit: The commit SHA1 that was cherry-picked.
    tags: A list of tags to add to the commit message.
    jira: The JIRA number to add to the commit message, this can be a comma separated list.
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
        for i in jira.split(","):
            lines.insert(2, f"jira {i.strip()}\n")

    # We Need to indent lines that have email addresss as some tooling in the community
    # will atttempt to read these lines and email everyone on the list.  We do not want
    # to annoy the community when doing our own work.
    for i in range(5, len(lines)):
        # The (cherry picked from commit <sha1>) line is the indicator we cherry-picked
        if lines[i].lstrip().startswith("(cherry picked from commit"):
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
    git_auth_res = subprocess.run(
        ["git", "show", '--pretty="%aN <%aE>"', "--no-patch", sha],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=repo_path,
    )
    if git_auth_res.returncode != 0:
        print(f"[FAILED] git show --pretty='%aN <%aE>' --no-patch {sha}")
        print(f"[FAILED][STDERR:{git_auth_res.returncode}] {git_auth_res.stderr.decode('utf-8')}")
        return None
    return "commit-author " + git_auth_res.stdout.decode("utf-8").replace('"', "").strip()


def CIQ_run_git(repo_path, args):
    """
    Run a git command in the given repository and return its output as a string.
    """
    result = subprocess.run(["git", "-C", repo_path] + args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(args)}\n{result.stderr}")

    return result.stdout


def CIQ_get_commit_body(repo_path, sha):
    return CIQ_run_git(repo_path, ["show", "-s", sha, "--format=%B"])


def CIQ_extract_fixes_references_from_commit_body_lines(lines):
    fixes = []
    for line in lines:
        m = re.match(r"^\s*Fixes:\s*([0-9a-fA-F]{6,40})", line, re.IGNORECASE)
        if not m:
            continue

        fixes.append(m.group(1))

    return fixes


def CIQ_fixes_references(repo_path, sha):
    """
    If commit message of sha contains lines like
    Fixes: <short_fixed>, this returns a list of <short_fixed>, otherwise an empty list
    """

    commit_body = CIQ_get_commit_body(repo_path, sha)
    return CIQ_extract_fixes_references_from_commit_body_lines(lines=commit_body.splitlines())


def CIQ_get_full_hash(repo, short_hash):
    return CIQ_run_git(repo, ["show", "-s", "--pretty=%H", short_hash]).strip()


def CIQ_get_current_branch(repo):
    return CIQ_run_git(repo, ["branch", "--show-current"]).strip()


def CIQ_hash_exists_in_ref(repo, pr_ref, hash_):
    """
    Return True if hash_ is reachable from pr_ref
    """

    try:
        CIQ_run_git(repo, ["merge-base", "--is-ancestor", hash_, pr_ref])
        return True
    except RuntimeError:
        return False


def CIQ_commit_exists_in_branch(repo, pr_branch, upstream_hash_, interval=None):
    """
    Return True if upstream_hash_ has been backported and it exists in the pr branch.
    If interval that consists of a pair of commit hashes is not None, we only
    check the interval[0]..interval[1], otherwise the whole history of the pr_branch will be used.
    """

    # First check if the commit has been backported by CIQ
    git_command = ["log", pr_branch, "--grep", "^commit " + upstream_hash_]
    if interval:
        oldest_commit, newest_commit = interval
        git_command.append(f"{oldest_commit}..{newest_commit}")

    output = CIQ_run_git(repo_path=repo, args=git_command)
    if output:
        return True

    # If we are searching in the interval <oldest_commit>..<newest_commit>,
    # we do not need to check way back if the commit came from upstream as it is
    if interval:
        return False

    # If it was not backported by CIQ, maybe it came from upstream as it is
    return CIQ_hash_exists_in_ref(repo=repo, pr_ref=pr_branch, hash_=upstream_hash_)


def CIQ_commit_exists_in_current_branch(repo, upstream_hash_, interval=None):
    """
    Return True if upstream_hash_ has been backported and it exists in the current branch
    """

    current_branch = CIQ_get_current_branch(repo)
    full_upstream_hash = CIQ_get_full_hash(repo, upstream_hash_)

    return CIQ_commit_exists_in_branch(
        repo=repo, pr_branch=current_branch, upstream_hash_=full_upstream_hash, interval=interval
    )


def CIQ_find_fixes_in_mainline(repo, upstream_ref, hash_):
    """
    Return unique commits in upstream_ref that have Fixes: <N chars of hash_> in their message, case-insensitive.
    Start from 12 chars and work down to 6, but do not include duplicates if already found at a longer length.
    Returns a list of tuples: (full_hash, display_string)
    """
    results = []

    # Prepare hash prefixes from 12 down to 6
    hash_prefixes = [hash_[:index] for index in range(12, 5, -1)]

    # Get all commits with 'Fixes:' in the message
    output = CIQ_run_git(
        repo,
        [
            "log",
            upstream_ref,
            "--grep",
            "Fixes:",
            "-i",
            "--format=%H %h %s (%an)%x0a%B%x00",
        ],
    ).strip()
    if not output:
        return []

    # Each commit is separated by a NUL character and a newline
    commits = output.split("\x00\x0a")
    for commit in commits:
        if not commit.strip():
            continue

        lines = commit.splitlines()
        # The first line is the summary, the rest is the body
        header = lines[0]
        full_hash, display_string = (lambda h: (h[0], " ".join(h[1:])))(header.split())
        fixes = CIQ_extract_fixes_references_from_commit_body_lines(lines=lines[1:])
        for fix in fixes:
            for prefix in hash_prefixes:
                if fix.lower().startswith(prefix.lower()):
                    results.append((full_hash, display_string))
                    break

    return results


def CIQ_filter_unapplied_commits(repo, pr_branch, commits, interval=None):
    """
    Receives a list of tuples: (full_hash, display_string)
    Returns filtered list with commits that were not applied in the pr_branch.
    If interval that consists of a pair of commit hashes is not None, we only
    check the interval[0]..interval[1], otherwise the whole history of the pr_branch will be used.

    Returns a list of tuples: (full_hash, display_string)
    """

    results = []
    for commit in commits:
        full_hash = commit[0]
        if not CIQ_commit_exists_in_branch(repo=repo, pr_branch=pr_branch, upstream_hash_=full_hash, interval=interval):
            results.append(commit)

    return results


def CIQ_find_fixes_in_mainline_unapplied(repo, pr_branch, upstream_ref, hash_, interval=None):
    """
    Return unique commits in upstream_ref that have Fixes: <N chars of hash_> in their message, case-insensitive,
    if they have not been committed in the pr_branch.
    If interval that consists of a pair of commit hashes is not None, we only
    check the interval[0]..interval[1], otherwise the whole history of the pr_branch will be used.
    Start from 12 chars and work down to 6, but do not include duplicates if already found at a longer length.
    Returns a list of tuples: (full_hash, display_string)
    """

    fixes = CIQ_find_fixes_in_mainline(repo=repo, upstream_ref=upstream_ref, hash_=hash_)
    return CIQ_filter_unapplied_commits(repo=repo, pr_branch=pr_branch, commits=fixes, interval=interval)


def CIQ_find_fixes_in_mainline_current_branch_unapplied(repo, upstream_ref, hash_, interval=None):
    current_branch = CIQ_get_current_branch(repo)

    return CIQ_find_fixes_in_mainline_unapplied(
        repo=repo, pr_branch=current_branch, upstream_ref=upstream_ref, hash_=hash_, interval=interval
    )


def CIQ_reset_HEAD(repo):
    return CIQ_run_git(repo_path=repo, args=["reset", "--hard", "HEAD"])


def CIQ_raise_or_warn(cond, error_msg, warn):
    if not cond:
        return

    if not warn:
        raise RuntimeError(error_msg)

    logging.warning(error_msg)


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


def get_git_user(repo):
    """Get the git user name and email from a repo's config.

    Returns a (name, email) tuple.
    Raises git.exc.GitCommandError if user.name or user.email are not configured.
    """
    name = repo.git.config("user.name")
    email = repo.git.config("user.email")
    return name, email


def parse_ciq_tag_release(tag):
    """Extract the release counter N from a CIQ tag like 'ciq_kernel-6.18.21-1'.

    Returns the integer N.
    Raises ValueError if the tag is not in ciq_kernel-X.Y.Z-N format.
    """
    m = re.match(r"^ciq_kernel-\d+\.\d+\.\d+-(\d+)$", tag)
    if not m:
        raise ValueError(
            f"Cannot parse CIQ release from tag: {tag!r} (expected 'ciq_kernel-X.Y.Z-N', e.g. 'ciq_kernel-6.18.21-1')"
        )
    return int(m.group(1))


def parse_kernel_tag(tag):
    """Validate and parse a kernel version tag.

    Accepts: 'v6.12.74', '6.12.74', or 'ciq_kernel-6.12.74-N'.

    Returns the version string (e.g., '6.12.74').
    Raises ValueError if the tag format is invalid.
    """
    m = re.match(r"^ciq_kernel-(\d+\.\d+\.\d+)-\d+$", tag)
    if m:
        return m.group(1)

    tag_without_v = tag.removeprefix("v")
    tag_parts = tag_without_v.split(".")
    if len(tag_parts) != 3:
        raise ValueError(f"Invalid kernel tag format: {tag} (expected vX.Y.Z, X.Y.Z, or ciq_kernel-X.Y.Z-N)")
    try:
        for part in tag_parts:
            int(part)
    except ValueError:
        raise ValueError(f"Invalid kernel tag format: {tag} (version parts must be numeric)")
    return tag_without_v


def replace_spec_changelog(spec_lines, new_changelog_lines):
    """Replace the %changelog section in spec_lines with new_changelog_lines.

    Preserves any trailing comment lines (starting with #) from the original changelog.
    Returns a new list of lines.
    Raises ValueError if %changelog is not found.
    """
    # Collect trailing comments from the original changelog section
    trailing_comments = []
    in_changelog = False
    for line in spec_lines:
        if line.startswith("%changelog"):
            in_changelog = True
            continue
        if in_changelog and (line.startswith("#")):
            trailing_comments.append(line)

    # Build new spec, replacing everything from %changelog onward
    new_spec = []
    found = False
    for line in spec_lines:
        if line.startswith("%changelog"):
            found = True
            new_spec.append(line)
            new_spec.extend(new_changelog_lines)
            new_spec.extend(trailing_comments)
            break
        new_spec.append(line)

    if not found:
        raise ValueError("Could not find %changelog section in spec file")

    return new_spec


def prepend_spec_changelog(spec_lines, new_entry_lines):
    """Prepend new_entry_lines at the top of the %changelog section.

    The existing changelog entries are preserved below the new entry.
    Returns a new list of lines.
    Raises ValueError if %changelog is not found.
    """
    new_spec = []
    found = False
    for i, line in enumerate(spec_lines):
        if line.startswith("%changelog"):
            found = True
            new_spec.append(line)
            new_spec.extend(new_entry_lines)
            new_spec.extend(spec_lines[i + 1 :])
            break
        new_spec.append(line)

    if not found:
        raise ValueError("Could not find %changelog section in spec file")

    return new_spec


def _read_spec_define(spec_lines, name, value_pattern):
    """Return the value of a %define directive from spec file lines.

    Builds a regex from name and value_pattern (a raw regex string matching the value),
    scans spec_lines for the first match, and returns the captured value string.
    Raises ValueError if the directive is not found.
    """
    pattern = re.compile(rf"^%define {re.escape(name)}\s+({value_pattern})")
    for line in spec_lines:
        m = pattern.match(line)
        if m:
            return m.group(1)
    raise ValueError(f"Could not find %define {name} in spec file")


def read_spec_el_version(spec_lines):
    """Read the EL version number from spec file lines.

    Returns the el_version string (e.g., '9'), or None if %define el_version
    is not present in the spec or its value does not match the expected
    numeric pattern.
    """
    try:
        return _read_spec_define(spec_lines, "el_version", r"\d+")
    except ValueError:
        return None


FIPS_PROTECTED_DIRECTORIES = [
    b"arch/x86/crypto/",
    b"crypto/asymmetric_keys/",
    b"crypto/",
    b"drivers/crypto/",
    b"drivers/char/random.c",
    b"include/crypto",
]


def check_for_fips_protected_changes(repo_path, start_ref, end_ref):
    """Check for changes to FIPS protected directories in a range of commits.

    Iterates over commits in start_ref..end_ref and checks whether any
    modified files fall under a FIPS protected directory.  Uses bytestrings
    throughout to avoid encoding issues with international contributor names
    in git output.

    Parameters:
        repo_path: Path to the git repository.
        start_ref: The starting ref (exclusive) for the commit range.
        end_ref: The ending ref (inclusive) for the commit range.

    Returns:
        dict mapping commit SHA (bytes) -> set of matched FIPS directory prefixes (bytes)
        for each commit that touches FIPS protected paths.  Empty dict if none found.
    """
    print("[fips-check] Checking for FIPS protected changes")
    print(f"[fips-check] Getting SHAS {start_ref}..{end_ref}")
    results = subprocess.run(
        ["git", "log", "--pretty=%H", f"{start_ref}..{end_ref}"],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=repo_path,
    )
    if results.returncode != 0:
        print(results.stderr)
        raise RuntimeError(f"git log failed for range {start_ref}..{end_ref}")

    num_commits = len(results.stdout.split(b"\n"))
    print("[fips-check] Number of commits to check: ", num_commits)
    shas_to_check = {}
    commits_checked = 0

    progress_interval = max(1, num_commits // 10)

    print("[fips-check] Checking modifications of shas")
    for sha in results.stdout.split(b"\n"):
        commits_checked += 1
        if commits_checked % progress_interval == 0:
            print(f"[fips-check] Checked {commits_checked} of {num_commits} commits")
        if sha == b"":
            continue
        res = subprocess.run(
            ["git", "show", "--name-only", "--pretty=%H %s", f"{sha.decode()}"],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=repo_path,
        )
        if res.returncode != 0:
            print(res)
            print(res.stderr)
            raise RuntimeError(f"git show failed for {sha}")

        sha_hash_and_subject = b""
        touched_fips_files = set()

        for line in res.stdout.split(b"\n"):
            if sha_hash_and_subject == b"":
                sha_hash_and_subject = line
                continue
            if line == b"":
                continue

            add_to_check = False

            for dir in FIPS_PROTECTED_DIRECTORIES:
                if line.startswith(dir):
                    add_to_check = True
                    if dir not in touched_fips_files:
                        touched_fips_files.add(dir)

            if add_to_check:
                shas_to_check[sha_hash_and_subject.split(b" ")[0]] = touched_fips_files

        if touched_fips_files:
            print(f"[fips-check] Checked commit {sha} touched {len(touched_fips_files)} FIPS protected files")
            for f in touched_fips_files:
                print(f"  - {f}")
        sha_hash_and_subject = b""

    print(f"[fips-check] {len(shas_to_check)} of {num_commits} commits have FIPS protected changes")

    return shas_to_check


def run_cve_search(vulns_repo, kernel_repo, query) -> tuple[bool, Optional[str]]:
    """
    Run the cve_search script from the vulns repo.
    Returns (success, output_message).
    """

    cve_search_path = os.path.join(vulns_repo, "scripts", "cve_search")
    if not os.path.exists(cve_search_path):
        raise RuntimeError(f"cve_search script not found at {cve_search_path}")

    env = os.environ.copy()
    env["CVEKERNELTREE"] = kernel_repo

    result = subprocess.run([cve_search_path, query], text=True, capture_output=True, check=False, env=env)

    # cve_search outputs results to stdout
    return result.returncode == 0, result.stdout.strip()


def CIQ_check_if_published_cve(vulns_repo, cve_id):
    if not cve_id:
        return False

    cve_id_year = cve_id.split("-")[1]
    published_path = f"{vulns_repo}/cve/published/{cve_id_year}/{cve_id}.sha1"
    if not os.path.isfile(published_path):
        print(f"[NOTE]: {cve_id} is not published, it has been rejected")
        return False

    return True


def CIQ_find_matching_cve(vulns_repo, kernel_repo, hash_) -> Optional[str]:
    """
    Returns the CVE (i.e CVE-2023-526) if there is a corresponding CVE to that commit hash
    and the CVE is published, not rejected.
    Otherwise it returns None
    """

    cve_id = None
    try:
        success, cve_output = run_cve_search(vulns_repo, kernel_repo, hash_)
        if success:
            # Parse the CVE from the result
            match = re.search(r"(CVE-\d{4}-\d+)\s+is assigned to git id", cve_output)
            if match:
                cve_id = match.group(1)
    except (RuntimeError, subprocess.SubprocessError) as e:
        # Log a warning instead of silently ignoring errors when checking bugfix CVEs
        print(f"Warning: Failed to check CVE for bugfix commit {hash_}: {e}", file=sys.stderr)

    if CIQ_check_if_published_cve(vulns_repo=vulns_repo, cve_id=cve_id):
        return cve_id

    return None


def CIQ_setup_vulns_repo(vulns_repo):
    """
    Setups the vuln repo, either by doing a pull update or cloning it from scratch
    if the repo does not exist.
    Raises RuntimeError exception for failures during a clone from scratch.
    If git pull fails, it is not considered an errros because we can still
    use the current version of the repo, even if it's older.
    """

    vulns_repo_url = "https://git.kernel.org/pub/scm/linux/security/vulns.git"
    if os.path.exists(vulns_repo):
        # Repository exists, update it with git pull
        try:
            CIQ_run_git(vulns_repo, ["pull"])
        except RuntimeError as e:
            print(f"WARNING: Failed to update vulns repo: {e}")
            print("Continuing with existing repository...")
    else:
        # Repository doesn't exist, clone it
        try:
            result = subprocess.run(
                ["git", "clone", vulns_repo_url, vulns_repo], text=True, capture_output=True, check=False
            )
            if result.returncode != 0:
                raise RuntimeError(f"ERROR: Failed to clone vulns repo: {result.stderr}")
        except Exception as e:
            raise RuntimeError(f"ERROR: Failed to clone vulns repo: {e}")
