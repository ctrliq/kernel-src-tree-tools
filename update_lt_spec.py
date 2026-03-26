#!/usr/bin/env python3
#
# coding: utf-8
#
# Update kernel.spec for LT (Long Term) kernel rebases.
# This script updates version variables and replaces the changelog
# to reflect the new upstream kernel version.

import argparse
import os
import sys
import time

try:
    import git
except ImportError:
    print("ERROR: GitPython is not installed. Install it with: pip install GitPython")
    sys.exit(1)

from ciq_helpers import get_git_user, last_git_tag, parse_kernel_tag, replace_spec_changelog


def calculate_lt_rebase_versions(kernel_version, distlocalversion, dist):
    """Calculate version strings for LT rebase.

    Arguments:
    kernel_version: Kernel version string (e.g., '6.12.74')
    distlocalversion: DISTLOCALVERSION string (e.g., '.1.0.0')
    dist: DIST string (e.g., '.el9_clk')

    Returns:
    Tuple of (full_kernel_version, tag_version, spectarfile_release, new_tag, major_version)
    """
    tag_version = f"{kernel_version}-1"
    spectarfile_release = f"{tag_version}{distlocalversion}{dist}"
    new_tag = f"ciq_kernel-{tag_version}"
    major_version = kernel_version.split(".")[0]

    return kernel_version, tag_version, spectarfile_release, new_tag, major_version


def update_spec_file(
    spec_path,
    full_kernel_version,
    spectarfile_release,
    lt_tag_version,
    lt_new_tag,
    lt_major_version,
    upstream_tag,
    srcgit,
    distlocalversion,
    dist,
):
    """Update the spec file with new version information and changelog.

    Arguments:
    spec_path: Path to kernel.spec file
    full_kernel_version: Full kernel version (e.g., '6.12.77')
    spectarfile_release: Value for tarfile_release variable
    lt_tag_version: Tag version (e.g., '6.12.77-1')
    lt_new_tag: New tag name (e.g., 'ciq_kernel-6.12.77-1')
    lt_major_version: Major version number (e.g., '6')
    upstream_tag: Git tag name (e.g., 'v6.12.77')
    srcgit: Git repository object
    distlocalversion: DISTLOCALVERSION string
    dist: DIST string
    """
    # Read the spec file
    try:
        with open(spec_path, "r") as f:
            spec = f.read().splitlines()
    except IOError as e:
        print(f"ERROR: Failed to read spec file {spec_path}: {e}")
        sys.exit(1)

    # Get git user info, checking both repo-level and global config
    try:
        name, email = get_git_user(srcgit)
    except git.exc.GitCommandError as e:
        print("ERROR: Failed to read git config. Please ensure user.name and user.email are configured.")
        print('  Run: git config --global user.name "Your Name"')
        print('  Run: git config --global user.email "your.email@example.com"')
        print(f"  Error details: {e}")
        sys.exit(1)

    # Update version variables
    updated_spec = []
    for line in spec:
        if line.startswith("%define specrpmversion"):
            line = f"%define specrpmversion {full_kernel_version}"
        elif line.startswith("%define specversion"):
            line = f"%define specversion {full_kernel_version}"
        elif line.startswith("%define tarfile_release"):
            line = f"%define tarfile_release {spectarfile_release}"
        updated_spec.append(line)

    # Build changelog entry lines
    changelog_date = time.strftime("%a %b %d %Y")
    changelog_lines = [
        f"* {changelog_date} {name} <{email}> - {lt_tag_version}{distlocalversion}{dist}",
        f"-- Rebased changes for Linux {full_kernel_version} (https://github.com/ctrliq/kernel-src-tree/releases/tag/{lt_new_tag})",
    ]

    try:
        commit_logs = srcgit.git.log("--no-merges", "--pretty=format:-- %s (%an)", f"{upstream_tag}..HEAD")
        for log_line in commit_logs.split("\n"):
            if log_line.strip():
                changelog_lines.append(log_line)
    except git.exc.GitCommandError as e:
        print(f"ERROR: Failed to get git log from {upstream_tag}..HEAD: {e}")
        sys.exit(1)

    changelog_lines += [
        f"-- Linux {full_kernel_version} (https://cdn.kernel.org/pub/linux/kernel/v{lt_major_version}.x/ChangeLog-{full_kernel_version})",
        "",
        "",
    ]

    new_spec = replace_spec_changelog(updated_spec, changelog_lines)

    # Write the updated spec file
    try:
        with open(spec_path, "w") as f:
            for line in new_spec:
                f.write(line + "\n")
    except IOError as e:
        print(f"ERROR: Failed to write spec file {spec_path}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update kernel.spec for LT kernel rebase")
    parser.add_argument("--srcgit", required=True, help="Location of srcgit repository")
    parser.add_argument("--spec-file", required=True, help="Path to kernel.spec file")
    parser.add_argument(
        "--distlocalversion", default=".1.0.0", help="DISTLOCALVERSION for tarfile_release (default: .1.0.0)"
    )
    parser.add_argument("--dist", default=".el9_clk", help="DIST for tarfile_release (default: .el9_clk)")
    parser.add_argument("--commit", action="store_true", help="Commit the spec file changes to git")
    args = parser.parse_args()

    # Initialize git repository
    srcgit_path = os.path.abspath(args.srcgit)
    try:
        srcgit = git.Repo(srcgit_path)
    except git.exc.InvalidGitRepositoryError:
        print(f"ERROR: {srcgit_path} is not a valid git repository")
        sys.exit(1)
    except git.exc.NoSuchPathError:
        print(f"ERROR: Path does not exist: {srcgit_path}")
        sys.exit(1)

    # Get the last git tag
    try:
        upstream_tag = last_git_tag(srcgit)
    except Exception as e:
        print(f"ERROR: Failed to get last git tag: {e}")
        sys.exit(1)

    print(f"Using last tag: {upstream_tag}")

    # Validate tag format (should be like 'v6.12.74' or '6.12.74')
    try:
        kernel_version = parse_kernel_tag(upstream_tag)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Calculate version strings
    full_kernel_version, tag_version, spectarfile_release, new_tag, major_version = calculate_lt_rebase_versions(
        kernel_version, args.distlocalversion, args.dist
    )

    print("\nLT Rebase Version Information:")
    print(f"  Full Kernel Version: {full_kernel_version}")
    print(f"  Tag Version: {tag_version}")
    print(f"  Spec tarfile_release: {spectarfile_release}")
    print(f"  New Tag: {new_tag}")
    print(f"  Major Version: {major_version}\n")

    # Verify spec file exists
    spec_path = os.path.abspath(args.spec_file)
    if not os.path.exists(spec_path):
        print(f"ERROR: Spec file not found: {spec_path}")
        sys.exit(1)

    # Update the spec file
    print(f"Updating spec file: {spec_path}")
    update_spec_file(
        spec_path,
        full_kernel_version,
        spectarfile_release,
        tag_version,
        new_tag,
        major_version,
        upstream_tag,
        srcgit,
        args.distlocalversion,
        args.dist,
    )

    print("Spec file updated successfully")

    # Optionally commit the changes
    if args.commit:
        print("Committing changes...")
        spec_path_rel = os.path.relpath(spec_path, srcgit.working_tree_dir)
        srcgit.git.add(spec_path_rel)

        # Check if there are changes to commit
        if srcgit.is_dirty(path=spec_path_rel):
            commit_message = f"[CIQ] {upstream_tag} - updated spec"
            try:
                srcgit.git.commit("-m", commit_message)
                print(f"Committed: {commit_message}")
            except git.exc.GitCommandError as e:
                print(f"ERROR: Failed to commit changes: {e}")
                sys.exit(1)
        else:
            print("No changes to commit")

    print("\nDone!")
