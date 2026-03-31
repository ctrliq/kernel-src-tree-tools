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


def calculate_lt_rebase_versions(kernel_version, buildid):
    """Calculate version strings for LT rebase.

    Arguments:
    kernel_version: Kernel version string (e.g., '6.12.74')
    buildid: Build ID string (e.g., '.1')

    Returns:
    Tuple of (full_kernel_version, tag_version, kernel_major_minor, kernel_patch,
              buildid, new_tag, major_version)
    """
    # Parse kernel version into components
    version_parts = kernel_version.split(".")
    if len(version_parts) != 3:
        raise ValueError(f"Invalid kernel version format: {kernel_version}")

    kernel_major_minor = f"{version_parts[0]}.{version_parts[1]}"
    kernel_patch = version_parts[2]
    major_version = version_parts[0]

    tag_version = f"{kernel_version}-1"
    new_tag = f"ciq_kernel-{tag_version}"

    return kernel_version, tag_version, kernel_major_minor, kernel_patch, buildid, new_tag, major_version


def update_spec_file(
    spec_path,
    full_kernel_version,
    kernel_major_minor,
    kernel_patch,
    buildid,
    lt_tag_version,
    lt_new_tag,
    lt_major_version,
    upstream_tag,
    srcgit,
):
    """Update the spec file with new version information and changelog.

    Arguments:
    spec_path: Path to kernel.spec file
    full_kernel_version: Full kernel version (e.g., '6.12.77')
    kernel_major_minor: Major.minor version (e.g., '6.12')
    kernel_patch: Patch version (e.g., '77')
    buildid: Build ID (e.g., '.1')
    lt_tag_version: Tag version (e.g., '6.12.77-1')
    lt_new_tag: New tag name (e.g., 'ciq_kernel-6.12.77-1')
    lt_major_version: Major version number (e.g., '6')
    upstream_tag: Git tag name (e.g., 'v6.12.77')
    srcgit: Git repository object
    """
    import re

    # Read the spec file
    try:
        with open(spec_path, "r") as f:
            spec = f.read().splitlines()
    except IOError as e:
        print(f"ERROR: Failed to read spec file {spec_path}: {e}")
        sys.exit(1)

    # Extract el_version from spec file
    el_version = None
    for line in spec:
        if line.startswith("%define el_version"):
            match = re.search(r"%define el_version\s+(\d+)", line)
            if match:
                el_version = match.group(1)
                break

    if not el_version:
        print("ERROR: Could not find %define el_version in spec file")
        sys.exit(1)

    # Construct dist string from el_version for changelog
    dist = f".el{el_version}"

    # Get git user info, checking both repo-level and global config
    try:
        name, email = get_git_user(srcgit)
    except git.exc.GitCommandError as e:
        print("ERROR: Failed to read git config. Please ensure user.name and user.email are configured.")
        print('  Run: git config --global user.name "Your Name"')
        print('  Run: git config --global user.email "your.email@example.com"')
        print(f"  Error details: {e}")
        sys.exit(1)

    # Update version variables - updating base variables, not el_version
    updated_spec = []
    for line in spec:
        if line.startswith("%define kernel_major_minor"):
            line = f"%define kernel_major_minor {kernel_major_minor}"
        elif line.startswith("%define kernel_patch"):
            line = f"%define kernel_patch {kernel_patch}"
        elif line.startswith("%define buildid"):
            line = f"%define buildid {buildid}"
        updated_spec.append(line)

    # Build changelog entry lines
    changelog_date = time.strftime("%a %b %d %Y")
    changelog_lines = [
        f"* {changelog_date} {name} <{email}> - {lt_tag_version}{buildid}{dist}",
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
    parser.add_argument("--buildid", default=".1", help="Build ID (default: .1)")
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
    full_kernel_version, tag_version, kernel_major_minor, kernel_patch, buildid, new_tag, major_version = (
        calculate_lt_rebase_versions(kernel_version, args.buildid)
    )

    print("\nLT Rebase Version Information:")
    print(f"  Full Kernel Version: {full_kernel_version}")
    print(f"  Kernel Major.Minor: {kernel_major_minor}")
    print(f"  Kernel Patch: {kernel_patch}")
    print(f"  Build ID: {buildid}")
    print(f"  Tag Version: {tag_version}")
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
        kernel_major_minor,
        kernel_patch,
        buildid,
        tag_version,
        new_tag,
        major_version,
        upstream_tag,
        srcgit,
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
