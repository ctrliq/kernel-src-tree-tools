import argparse
import os
import subprocess
from ciq_helpers import CIQ_cherry_pick_commit_standardization
from ciq_helpers import CIQ_original_commit_author_to_tag_string
# from ciq_helpers import *

MERGE_MSG = '.git/MERGE_MSG'

if __name__ == '__main__':
    print("CIQ custom cherry picker")
    parser = argparse.ArgumentParser()
    parser.add_argument('--sha', help='Taget SHA1 to cherry-pick')
    parser.add_argument('--ticket', help='Ticket associtated to cherry-pick work')
    parser.add_argument('--ciq-tag', help="Tags for commit message <feature><-optional modifier> <identifier>.\n"
                        "example: cve CVE-2022-45884 - A patch for a CVE Fix.\n"
                        "         cve-bf CVE-1974-0001 - A bug fix for a CVE currently being patched\n"
                        "         cve-pre CVE-1974-0001 - A pre-condition or depnedency needed for the CVE\n"
                        "Multiple tags are seperated with a comma. ex: cve CVE-1974-0001, cve CVE-1974-0002\n")
    args = parser.parse_args()

    tags = []
    if args.ciq_tag is not None:
        tags = args.ciq_tag.split(',')

    author = CIQ_original_commit_author_to_tag_string(repo_path=os.getcwd(), sha=args.sha)
    if author is None:
        exit(1)

    git_res = subprocess.run(['git', 'cherry-pick', '-nsx', args.sha])
    if git_res.returncode != 0:
        print(f"[FAILED] git cherry-pick -nsx {args.sha}")
        print("       Manually resolve conflict and include `upstream-diff` tag in commit message")
        print("Subprocess Call:")
        print(git_res)
        print("")

    print(os.getcwd())
    subprocess.run(['cp', MERGE_MSG, f'{MERGE_MSG}.bak'])

    tags.append(author)

    with open(MERGE_MSG, "r") as file:
        original_msg = file.readlines()

    new_msg = CIQ_cherry_pick_commit_standardization(original_msg, args.sha, jira=args.ticket, tags=tags)

    print(f"Cherry Pick New Message for {args.sha}")
    for line in new_msg:
        print(line.strip('\n'))
    print(f"\n Original Message located here: {MERGE_MSG}.bak")

    with open(MERGE_MSG, "w") as file:
        file.writelines(new_msg)
