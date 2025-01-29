import argparse
import json
import os
import subprocess
import re
import git

def find_common_tag(old_tags, new_tags):
    for tag in old_tags:
        if tag in new_tags:
            return tag
    return None

def get_branch_tag_sha_list(repo, branch):
    print('[rolling release update] Checking out branch: ', branch)
    repo.git.checkout(branch)
    results = subprocess.run(['git', 'log', '--decorate', '--oneline'], stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                            cwd=repo.working_dir)
    if results.returncode != 0:
        print(results.stderr)
        exit(1)

    print('[rolling release update] Gathering all the RESF kernel Tags')
    tags = []
    for line in results.stdout.split(b'\n'):
        if b'tag: resf_kernel' in line:
            print(line)
            tags.append(line.split(b' ')[0])
    return tags

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Rolling release update')
    parser.add_argument('--repo', help='Repository path', required=True)
    parser.add_argument('--new-base-branch', help='Branch name', required=True)
    parser.add_argument('--old-rolling-branch', help='Branch name for old rolling release: ex: sig-cloud-8/4.18.0-553.33.1.el8_10', required=True)
    args = parser.parse_args()

    repo = git.Repo(args.repo)

    rolling_product = args.old_rolling_branch.split('/')[0]
    print('[rolling release update] Rolling Product: ', rolling_product)

    old_rolling_branch_tags = get_branch_tag_sha_list(repo, args.old_rolling_branch)
    print('[rolling release update] Old Rolling Branch Tags: ', old_rolling_branch_tags)

    new_base_branch_tags = get_branch_tag_sha_list(repo, args.new_base_branch)
    print('[rolling release update] New Base Branch Tags: ', new_base_branch_tags)

    latest_resf_sha = find_common_tag(old_rolling_branch_tags, new_base_branch_tags)
    print('[rolling release update] Latest RESF tag sha: ', latest_resf_sha)
    print(repo.git.show('--pretty="%H %s"', '-s', latest_resf_sha.decode()))


    print('[rolling release update] Checking out old rolling branch: ', args.old_rolling_branch)
    repo.git.checkout(args.old_rolling_branch)
    print('[rolling release update] Finding the CIQ Kernel and Associated Upstream commits between the last resf tag and HEAD')
    rolling_commit_map = {}
    rollint_commit_map_rev = {}
    rolling_commits = repo.git.log(f'{latest_resf_sha.decode()}..HEAD')
    for line in rolling_commits.split('\n'):
        if line.startswith('commit '):
            ciq_commit = line.split('commit ')[1]
            rolling_commit_map[ciq_commit] = ''
        if line.startswith('    commit '):
            upstream_commit = line.split('    commit ')[1]
            rolling_commit_map[ciq_commit] = upstream_commit
            rollint_commit_map_rev[upstream_commit] = ciq_commit

    print('[rolling release update] Last RESF tag sha: ', latest_resf_sha)

    print('{ "CIQ COMMMIT" : "UPSTREAM COMMMIT" }')
    print(json.dumps(rolling_commit_map, indent=2))

    print('[rolling release update] Checking out new base branch: ', args.new_base_branch)
    repo.git.checkout(args.new_base_branch)

    results = subprocess.run(['git', 'log', '--decorate', '--oneline'], stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                            cwd=repo.working_dir)

    print('[rolling release update] Finding the kernel version for the new rolling release')
    new_rolling_branch_kernel = ''
    for line in results.stdout.split(b'\n'):
        if b'tag: resf_kernel' in line:
            print(line)
            r = re.match(b'.*(?P<vendor>.*)_kernel-(?P<kernel_ver>[0-9.-]*el[89]_[0-9]*)', line)
            print(r)
            if r:
                new_rolling_branch_kernel = r.group('kernel_ver')
            break
    new_rolling_branch_kernel = f'{rolling_product}/{new_rolling_branch_kernel.decode()}'
    print('[rolling release update} New Branch to create ', new_rolling_branch_kernel)
    
    print('[rolling release update] Check if branch Exists: ', new_rolling_branch_kernel)
    results = subprocess.run(['git', 'show-ref', '--quiet', f'refs/heads/{new_rolling_branch_kernel}'],
                            stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=args.repo)
    if results.returncode == 0:
        print(f'Branch {new_rolling_branch_kernel} already exists')
        exit(1)
    else:
        print(f'Branch {new_rolling_branch_kernel} does not exists creating')

    results = subprocess.run(['git', 'checkout', '-b', new_rolling_branch_kernel], stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE, cwd=args.repo)
    if results.returncode != 0:
        print(results.stderr)
        exit(1)
    
    print('[rolling release update] Crating Map of all new commits from last rolling release fork')
    new_base_commit_map = {}
    new_base_commit_map_rev = {}
    new_base_commits = repo.git.log(f'{latest_resf_sha.decode()}..HEAD')
    for line in new_base_commits.split('\n'):
        if line.startswith('commit '):
            ciq_commit = line.split('commit ')[1]
            new_base_commit_map[ciq_commit] = ''
        if line.startswith('    commit '):
            upstream_commit = line.split('    commit ')[1]
            new_base_commit_map[ciq_commit] = upstream_commit
            new_base_commit_map_rev[upstream_commit] = ciq_commit

    print('{ "CIQ COMMMIT" : "UPSTREAM COMMMIT" }')
    print(json.dumps(new_base_commit_map, indent=2))

    print('[rolling release update] Checking if any of the commits from the old rolling release are already present in the new base branch')
    commits_to_remove = {}
    for ciq_commit, upstream_commit in rolling_commit_map.items():
        if upstream_commit in new_base_commit_map_rev:
            print(f"Commit {ciq_commit} already present in new base branch")
            print(repo.git.show(ciq_commit))
            commits_to_remove[ciq_commit] = upstream_commit

    print('[rolling release update] Removing commits from the new branch')
    for ciq_commit, upstream_commit in commits_to_remove.items():
        del rolling_commit_map[ciq_commit]
        print("Removing commit: ", ciq_commit)
        repo.git.show(ciq_commit)

    print('[rolling release update] Applying the remaining commits to the new branch')
    for ciq_commit, upstream_commit in reversed(rolling_commit_map.items()):
        print('Applying commit ', repo.git.show('--pretty="%H %s"', '-s', ciq_commit))
        result = subprocess.run(['git', 'cherry-pick', '-s', ciq_commit], stderr=subprocess.PIPE,
                                stdout=subprocess.PIPE, cwd=args.repo)
        if result.returncode != 0:
            print(result.stderr.split(b'\n'))
            exit(1)

