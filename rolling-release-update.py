import argparse
import json
import os
import re
import subprocess

import git

FIPS_PROTECTED_DIRECTORIES = [
    b"arch/x86/crypto/",
    b"crypto/asymmetric_keys/",
    b"crypto/",
    b"drivers/crypto/",
    b"drivers/char/random.c",
    b"include/crypto",
]

DEBUG = False


def find_common_tag(old_tags, new_tags):
    for tag in old_tags:
        if tag in new_tags:
            return tag
    return None


def get_branch_tag_sha_list(repo, branch, minor_version=False):
    print("[rolling release update] Checking out branch: ", branch)
    repo.git.checkout(branch)
    results = subprocess.run(
        ["git", "log", "--decorate", "--oneline"], stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=repo.working_dir
    )
    if results.returncode != 0:
        print(results.stderr)
        exit(1)

    print("[rolling release update] Gathering all the RESF kernel Tags")
    tags = []
    last_resf_tag = b""
    for line in results.stdout.split(b"\n"):
        if b"tag: resf_kernel" in line:
            if DEBUG:
                print(line)
            tags.append(line.split(b" ")[0])
            if last_resf_tag == b"":
                last_resf_tag = line.split(b" ")[0]
        if minor_version and b"tag: kernel-" in line:
            if DEBUG:
                print(line)
            tags.append(line.split(b" ")[0])

    # Print summary instead of all tags
    if len(tags) > 0:
        print(f"[rolling release update] Found {len(tags)} RESF kernel tags")
        if DEBUG:
            for line_tag in tags:
                print(f"  {line_tag.decode()}")

    return tags, last_resf_tag


def check_for_fips_protected_changes(repo, branch, common_tag):
    print("[rolling release update] Checking for FIPS protected changes")
    repo.git.checkout(branch)
    print(f"[rolling release update] Getting SHAS {common_tag.decode()}..HEAD")
    results = subprocess.run(
        ["git", "log", "--pretty=%H", f"{common_tag.decode()}..HEAD"],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=repo.working_dir,
    )
    if results.returncode != 0:
        print(results.stderr)
        exit(1)

    num_commits = len(results.stdout.split(b"\n"))
    print("[rolling release update] Number of commits to check: ", num_commits)
    shas_to_check = {}
    commits_checked = 0

    progress_interval = max(1, num_commits // 10)

    print("[rolling release update] Checking modifications of shas")
    if DEBUG:
        print(results.stdout.split(b"\n"))
    for sha in results.stdout.split(b"\n"):
        commits_checked += 1
        if commits_checked % progress_interval == 0:
            print(f"[rolling release update] Checked {commits_checked} of {num_commits} commits")
        if sha == b"":
            continue
        res = subprocess.run(
            ["git", "show", "--name-only", "--pretty=%H %s", f"{sha.decode()}"],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=repo.working_dir,
        )
        if res.returncode != 0:
            print(res)
            print(res.stderr)
            exit(1)

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
                    if DEBUG:
                        print(f"FIPS protected directory {dir} change found in commit {sha}")
                        print(sha_hash_and_subject)
                    add_to_check = True
                    if dir not in touched_fips_files:
                        touched_fips_files.add(dir)

            if add_to_check:
                shas_to_check[sha_hash_and_subject.split(b" ")[0]] = touched_fips_files

        if touched_fips_files:
            print(
                f"[rolling release update] Checked commit {sha} touched {len(touched_fips_files)} FIPS protected files"
            )
            for f in touched_fips_files:
                print(f"  - {f}")
        sha_hash_and_subject = b""

    print(f"[rolling release update] {len(shas_to_check)} of {num_commits} commits have FIPS protected changes")

    return shas_to_check


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rolling release update")
    parser.add_argument("--repo", help="Repository path", required=True)
    parser.add_argument("--new-base-branch", help="Branch name", required=True)
    parser.add_argument(
        "--old-rolling-branch",
        help="Branch name for old rolling release: ex: sig-cloud-8/4.18.0-553.33.1.el8_10",
        required=True,
    )
    parser.add_argument("--fips-override", help="Override FIPS check abort", action="store_true")
    parser.add_argument(
        "--verbose-git-show", help="When SHAs are detected for removal do the full git show <sha>", action="store_true"
    )
    parser.add_argument(
        "--new_minor_version",
        help="Do not stop at the RESF tags continue down the CENTOS / ROCKY MAIN branch."
        " This is used for the new minor version releases",
        action="store_true",
    )
    parser.add_argument(
        "--demo", help="DEMO mode, will make a new set of branches with demo_ prepended", action="store_true"
    )
    parser.add_argument("--debug", help="Enable debug output", action="store_true")
    parser.add_argument(
        "--interactive", help="Interactive mode - pause on merge conflicts for user resolution", action="store_true"
    )
    args = parser.parse_args()

    if args.demo:
        print("======================== DEMO MODE ENABLED ==========================")
        print("[rolling release update] DEMO mode enabled YOU SHOULD NOT COMMIT THIS")
        print("======================== DEMO MODE ENABLED ==========================")

    if args.debug:
        DEBUG = True
        print("======================== DEBUG MODE ENABLED ==========================")
        print("[rolling release update] Debug mode enabled")
        print("======================== DEBUG MODE ENABLED ==========================")

    repo = git.Repo(args.repo)

    rolling_product = args.old_rolling_branch.split("/")[0]
    print("[rolling release update] Rolling Product: ", rolling_product)

    if args.new_minor_version:
        print("[rolling release update] New Minor Version: ", args.new_minor_version)

    old_rolling_branch_tags, old_rolling_resf_tag_sha = get_branch_tag_sha_list(
        repo, args.old_rolling_branch, args.new_minor_version
    )
    if DEBUG:
        print("[rolling release update] Old Rolling Branch Tags: ", old_rolling_branch_tags)

    new_base_branch_tags, new_base_resf_tag_sha = get_branch_tag_sha_list(
        repo, args.new_base_branch, args.new_minor_version
    )
    if DEBUG:
        print("[rolling release update] New Base Branch Tags: ", new_base_branch_tags)

    common_sha = find_common_tag(old_rolling_branch_tags, new_base_branch_tags)
    print("[rolling release update] Common tag sha: ", common_sha)
    print(repo.git.show('--pretty="%H %s"', "-s", common_sha.decode()))

    if "fips" in rolling_product:
        print("[rolling release update] Checking for FIPS protected changes between the common tag and HEAD")
        shas_to_check = check_for_fips_protected_changes(repo, args.new_base_branch, common_sha)
        if shas_to_check and args.fips_override is False:
            for sha, dir in shas_to_check.items():
                print(f"## Commit {sha.decode()}")
                print("'''")
                dir_list = []
                for d in dir:
                    dir_list.append(d.decode())
                print(repo.git.show(sha.decode(), dir_list))
                print("'''")
            print("[rolling release update] FIPS protected changes found between the common tag and HEAD")
            print("[rolling release update] Please Contact the CIQ FIPS / Security team for further instructions")
            print("[rolling release update] Exiting")
            exit(1)

    print("[rolling release update] Checking out old rolling branch: ", args.old_rolling_branch)
    repo.git.checkout(args.old_rolling_branch)
    print(
        "[rolling release update] Finding the CIQ Kernel and Associated Upstream commits between the last resf tag and HEAD"
    )
    print(f"[rolling release update] Getting SHAS {old_rolling_resf_tag_sha.decode()}..HEAD")
    rolling_commit_map = {}
    rollint_commit_map_rev = {}
    rolling_commits = repo.git.log(f"{old_rolling_resf_tag_sha.decode()}..HEAD")
    for line in rolling_commits.split("\n"):
        if line.startswith("commit "):
            ciq_commit = line.split("commit ")[1]
            rolling_commit_map[ciq_commit] = ""
        if line.startswith("    commit "):
            upstream_commit = line.split("    commit ")[1]
            rolling_commit_map[ciq_commit] = upstream_commit
            rollint_commit_map_rev[upstream_commit] = ciq_commit

    print("[rolling release update] Last RESF tag sha: ", common_sha)

    print(f"[rolling release update] Total commits in old branch: {len(rolling_commit_map)}")
    if DEBUG:
        print('{ "CIQ COMMIT" : "UPSTREAM COMMIT" }')
        if len(rolling_commit_map) > 10:
            print("Printing first 5 and last 5 commits")
            print(json.dumps({k: rolling_commit_map[k] for k in list(rolling_commit_map)[:5]}, indent=2))
            print(json.dumps({k: rolling_commit_map[k] for k in list(rolling_commit_map)[-5:]}, indent=2))
        else:
            print(json.dumps(rolling_commit_map, indent=2))

    print("[rolling release update] Checking out new base branch: ", args.new_base_branch)
    repo.git.checkout(args.new_base_branch)

    results = subprocess.run(
        ["git", "log", "--decorate", "--oneline"], stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=repo.working_dir
    )

    print("[rolling release update] Finding the kernel version for the new rolling release")
    new_rolling_branch_kernel = ""
    for line in results.stdout.split(b"\n"):
        if b"tag: resf_kernel" in line:
            if DEBUG:
                print(line)
            r = re.match(b".*(?P<vendor>.*)_kernel-(?P<kernel_ver>[0-9.-]*el[0-9]{1,2}_[0-9]*)", line)
            if r:
                new_rolling_branch_kernel = r.group("kernel_ver")
                if DEBUG:
                    print(f"[rolling release update] Matched kernel version: {new_rolling_branch_kernel.decode()}")
            break

    if args.demo:
        new_rolling_branch_kernel = f"demo_{rolling_product}/{new_rolling_branch_kernel.decode()}"
    else:
        new_rolling_branch_kernel = f"{rolling_product}/{new_rolling_branch_kernel.decode()}"
    print(f"[rolling release update] New Branch to create: {new_rolling_branch_kernel}")

    if DEBUG:
        print(f"[rolling release update] Check if branch exists: {new_rolling_branch_kernel}")
    results = subprocess.run(
        ["git", "show-ref", "--quiet", f"refs/heads/{new_rolling_branch_kernel}"],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=args.repo,
    )
    if results.returncode == 0:
        print(f"[rolling release update] ERROR: Branch {new_rolling_branch_kernel} already exists")
        exit(1)
    else:
        print(f"[rolling release update] Creating new branch: {new_rolling_branch_kernel}")
        results = subprocess.run(
            ["git", "checkout", "-b", new_rolling_branch_kernel],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=args.repo,
        )
    if results.returncode != 0:
        print(results.stderr)
        exit(1)

    print("[rolling release update] Creating new branch for PR: ", f"{os.getlogin()}_{new_rolling_branch_kernel}")
    results = subprocess.run(
        ["git", "checkout", "-b", f"{os.getlogin()}_{new_rolling_branch_kernel}"],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=args.repo,
    )
    if results.returncode != 0:
        print(results.stderr)
        exit(1)

    print("[rolling release update] Creating Map of all new commits from last rolling release fork")
    new_base_commit_map = {}
    new_base_commit_map_rev = {}
    new_base_commits = repo.git.log(f"{common_sha.decode()}..HEAD")
    for line in new_base_commits.split("\n"):
        if line.startswith("commit "):
            ciq_commit = line.split("commit ")[1]
            new_base_commit_map[ciq_commit] = ""
        if line.startswith("    commit "):
            upstream_commit = line.split("    commit ")[1]
            new_base_commit_map[ciq_commit] = upstream_commit
            new_base_commit_map_rev[upstream_commit] = ciq_commit

    print(f"[rolling release update] Total commits in new branch: {len(new_base_commit_map)}")
    if DEBUG:
        print('{ "CIQ COMMIT" : "UPSTREAM COMMIT" }')
        if len(new_base_commit_map) > 10:
            print("Printing first 5 and last 5 commits")
            print(json.dumps({k: new_base_commit_map[k] for k in list(new_base_commit_map)[:5]}, indent=2))
            print(json.dumps({k: new_base_commit_map[k] for k in list(new_base_commit_map)[-5:]}, indent=2))
        else:
            print(json.dumps(new_base_commit_map, indent=2))

    print(
        "[rolling release update] Checking if any of the commits from the old rolling release are already present in the new base branch"
    )
    commits_to_remove = {}
    for ciq_commit, upstream_commit in rolling_commit_map.items():
        if upstream_commit in new_base_commit_map_rev:
            print(
                f"- Commit {ciq_commit} already present in new base branch: {repo.git.show('--pretty=oneline', '-s', ciq_commit)}"
            )
            commits_to_remove[ciq_commit] = upstream_commit
        if ciq_commit in new_base_commit_map:
            print(
                f"- CIQ Commit {ciq_commit} already present in new base branch: {repo.git.show('--pretty=oneline', '-s', ciq_commit)}"
            )
            commits_to_remove[ciq_commit] = upstream_commit

    print(f"[rolling release update] Found {len(commits_to_remove)} duplicate commits to remove")
    if commits_to_remove:
        print("[rolling release update] Removing duplicate commits:")
        for ciq_commit, upstream_commit in commits_to_remove.items():
            del rolling_commit_map[ciq_commit]
            if args.verbose_git_show:
                print(repo.git.show(ciq_commit))
            else:
                print(f"  - {repo.git.show('--pretty=oneline', '-s', ciq_commit)}")

    print(f"[rolling release update] Applying {len(rolling_commit_map)} remaining commits to the new branch")
    commits_applied = 0
    for ciq_commit, upstream_commit in reversed(rolling_commit_map.items()):
        commits_applied += 1
        commit_info = repo.git.show("--pretty=%h %s", "-s", ciq_commit)
        print(f"  [{commits_applied}/{len(rolling_commit_map)}] {commit_info}")
        result = subprocess.run(
            ["git", "cherry-pick", "-s", ciq_commit], stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=args.repo
        )
        if result.returncode != 0:
            print(f"[rolling release update] ERROR: Failed to cherry-pick commit {ciq_commit}")
            print(result.stderr.decode("utf-8"))

            if args.interactive:
                print("[rolling release update] ========================================")
                print("[rolling release update] INTERACTIVE MODE: Merge conflict detected")
                print("[rolling release update] ========================================")
                print("[rolling release update] Please resolve or skip the merge conflict manually.")
                print("[rolling release update] To resolve:")
                print("[rolling release update]   1. Fix merge conflicts in the working directory")
                print("[rolling release update]   2. Stage resolved files: git add <files>")
                print("[rolling release update]   3. Complete cherry-pick: git cherry-pick --continue")
                print("[rolling release update]      (or commit manually if needed)")
                print("[rolling release update] To skip:")
                print("[rolling release update]   1. To skip this commit: git cherry-pick --skip")
                print("[rolling release update] When done:")
                print("[rolling release update]   Return here and press Enter to continue")
                print("[rolling release update] ========================================")

                # Loop until conflict is resolved or user aborts
                while True:
                    user_input = input(
                        '[rolling release update] Press Enter when resolved (or type "stop"/"abort" to exit): '
                    ).strip().lower()

                    if user_input in ["stop", "abort"]:
                        print("[rolling release update] ========================================")
                        print("[rolling release update] User aborted. Remaining commits to forward port:")
                        print("[rolling release update] ========================================")

                        # Print remaining commits including the current failed one
                        remaining_commits = list(reversed(rolling_commit_map.items()))
                        start_idx = remaining_commits.index((ciq_commit, upstream_commit))

                        for remaining_commit, remaining_upstream in remaining_commits[start_idx:]:
                            short_sha = repo.git.rev_parse("--short", remaining_commit)
                            summary = repo.git.show("--pretty=%s", "-s", remaining_commit)
                            print(f"  {short_sha} {summary}")

                        print("[rolling release update] ========================================")
                        print(f"[rolling release update] Total remaining: {len(remaining_commits) - start_idx} commits")
                        exit(1)

                    # Verify the cherry-pick was completed successfully
                    # Check if CHERRY_PICK_HEAD still exists (indicates incomplete cherry-pick)
                    cherry_pick_head = os.path.join(args.repo, ".git", "CHERRY_PICK_HEAD")
                    if os.path.exists(cherry_pick_head):
                        print("[rolling release update] ERROR: Cherry-pick not completed (.git/CHERRY_PICK_HEAD still exists)")
                        print("[rolling release update] Please complete the cherry-pick with:")
                        print("[rolling release update]   git cherry-pick --continue")
                        print("[rolling release update] or abort with:")
                        print("[rolling release update]   git cherry-pick --abort")
                        print('[rolling release update] Type "stop" or "abort" to exit, or press Enter to check again')
                        continue

                    # Check for uncommitted changes
                    status_result = subprocess.run(
                        ["git", "status", "--porcelain"], stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=args.repo
                    )
                    if status_result.returncode != 0:
                        print("[rolling release update] ERROR: Could not check git status")
                        print('[rolling release update] Type "stop" or "abort" to exit, or press Enter to check again')
                        continue

                    if status_result.stdout.strip():
                        print("[rolling release update] ERROR: There are still uncommitted changes")
                        print("[rolling release update] Status:")
                        print(status_result.stdout.decode("utf-8"))
                        print("[rolling release update] Please commit or stash changes before continuing")
                        print('[rolling release update] Type "stop" or "abort" to exit, or press Enter to check again')
                        continue

                    # If we got here, everything is resolved
                    print("[rolling release update] Cherry-pick resolved successfully, continuing...")
                    break
            else:
                exit(1)

    print(f"[rolling release update] Successfully applied all {commits_applied} commits")
