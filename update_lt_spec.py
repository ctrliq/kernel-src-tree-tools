#!/usr/bin/env python3
#
# coding: utf-8
#
# Update kernel.spec for LT (Long Term) kernel rebases.
# This script updates version variables and replaces the changelog
# to reflect the new upstream kernel version.

import argparse
import os
import re
import sys
import time

try:
    import git
except ImportError:
    print("ERROR: GitPython is not installed. Install it with: pip install GitPython")
    sys.exit(1)

from kt.ktlib.ciq_helpers import (
    get_git_user,
    last_git_tag,
    parse_ciq_tag_release,
    parse_kernel_tag,
    prepend_spec_changelog,
    read_spec_el_version,
    replace_spec_changelog,
)


def _read_spec_file(spec_path):
    try:
        with open(spec_path, "r") as f:
            return f.read().splitlines()
    except IOError as e:
        print(f"ERROR: Failed to read spec file {spec_path}: {e}")
        sys.exit(1)


def _write_spec_file(spec_path, lines):
    try:
        with open(spec_path, "w") as f:
            for line in lines:
                f.write(line + "\n")
    except IOError as e:
        print(f"ERROR: Failed to write spec file {spec_path}: {e}")
        sys.exit(1)


def _set_spec_pkgrelease(line, n):
    """If line is a %define pkgrelease directive, set its numeric base to n.

    Returns the updated line, or the original line unchanged.
    """
    if re.match(r"^%define\s+pkgrelease\s+\d+", line):
        return re.sub(r"^(%define\s+pkgrelease\s+)\d+", rf"\g<1>{n}", line)
    return line


def calculate_lt_rebase_versions(kernel_version, buildid, tag_prefix="ciq"):
    """Calculate version strings for LT rebase.

    Arguments:
    kernel_version: Kernel version string (e.g., '6.12.74')
    buildid: Build ID string (e.g., '.1')
    tag_prefix: Tag prefix (e.g., 'ciq' or 'clkstable')

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
    new_tag = f"{tag_prefix}_kernel-{tag_version}"

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
    spec = _read_spec_file(spec_path)

    # Construct dist string from el_version for changelog (omit if not defined)
    el_version = read_spec_el_version(spec)
    dist = f".el{el_version}" if el_version else ""

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
        else:
            line = _set_spec_pkgrelease(line, 1)
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

    try:
        new_spec = replace_spec_changelog(updated_spec, changelog_lines)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    _write_spec_file(spec_path, new_spec)


def bump_spec_file(
    spec_path,
    kernel_version,
    upstream_tag,
    srcgit,
):
    """Update the spec file for a non-rebase build: bump pkgrelease and prepend changelog.

    Parses the release counter N from upstream_tag (ciq_kernel-X.Y.Z-N), increments it
    to N+1, updates %define pkgrelease in the spec, and prepends a new changelog entry.
    Uses upstream_tag..HEAD as the commit range.

    Arguments:
    spec_path: Path to kernel.spec file
    kernel_version: Kernel version string (e.g., '6.12.77')
    upstream_tag: CIQ git tag (e.g., 'ciq_kernel-6.12.77-1'), used as range start
    srcgit: Git repository object

    Returns the new pkgrelease base as an integer (e.g., 2).
    """
    # Parse the release counter from the CIQ tag
    try:
        current_n = parse_ciq_tag_release(upstream_tag)
    except ValueError as e:
        print(f"ERROR: {e}")
        print("  Bump mode requires a ciq_kernel-X.Y.Z-N tag. Run rebase mode first.")
        sys.exit(1)

    new_n = current_n + 1
    lt_tag_version = f"{kernel_version}-{new_n}"
    print(f"Bumping pkgrelease base: {current_n} -> {new_n}")

    spec = _read_spec_file(spec_path)

    # Construct dist string from el_version for changelog (omit if not defined)
    el_version = read_spec_el_version(spec)
    dist = f".el{el_version}" if el_version else ""

    # Get git user info
    try:
        name, email = get_git_user(srcgit)
    except git.exc.GitCommandError as e:
        print("ERROR: Failed to read git config. Please ensure user.name and user.email are configured.")
        print('  Run: git config --global user.name "Your Name"')
        print('  Run: git config --global user.email "your.email@example.com"')
        print(f"  Error details: {e}")
        sys.exit(1)

    # Get commits since the last tag
    try:
        commit_logs = srcgit.git.log("--no-merges", "--pretty=format:-- %s (%an)", f"{upstream_tag}..HEAD")
    except git.exc.GitCommandError as e:
        print(f"ERROR: Failed to get git log from {upstream_tag}..HEAD: {e}")
        sys.exit(1)

    if not commit_logs.strip():
        print(f"WARNING: No commits found since {upstream_tag}; changelog entry will have no commit lines")

    # Build new changelog entry
    changelog_date = time.strftime("%a %b %d %Y")
    changelog_lines = [
        f"* {changelog_date} {name} <{email}> - {lt_tag_version}.1{dist}",
    ]
    for log_line in commit_logs.split("\n"):
        if log_line.strip():
            changelog_lines.append(log_line)
    changelog_lines += [""]

    # Update spec: bump pkgrelease base and reset buildid to .1
    updated_spec = []
    for line in spec:
        line = _set_spec_pkgrelease(line, new_n)
        if line.startswith("%define buildid"):
            line = "%define buildid .1"
        updated_spec.append(line)

    # Prepend new entry above the existing changelog
    try:
        new_spec = prepend_spec_changelog(updated_spec, changelog_lines)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    _write_spec_file(spec_path, new_spec)

    return new_n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update kernel.spec for LT kernel rebases or bump the package release without changing the kernel version"
    )
    parser.add_argument("--srcgit", required=True, help="Location of srcgit repository")
    parser.add_argument("--spec-file", required=True, help="Path to kernel.spec file")
    parser.add_argument("--buildid", default=".1", help="Build ID for rebase mode (default: .1)")
    parser.add_argument("--commit", action="store_true", help="Commit the spec file changes to git")
    parser.add_argument(
        "--bump",
        action="store_true",
        help="Bump mode: increment pkgrelease, reset buildid to .1, and prepend changelog (no kernel version change)",
    )
    parser.add_argument(
        "--tag",
        action="store_true",
        help="Create a new git tag after updating the spec (bump mode only); tag format: <prefix>_kernel-X.Y.Z-(N+1)",
    )
    parser.add_argument(
        "--tag-prefix",
        default="ciq",
        help="Tag prefix for new tags (default: 'ciq', producing 'ciq_kernel-X.Y.Z-N'; use 'clkstable' for ciq-stable branch)",
    )
    args = parser.parse_args()

    if args.tag and not args.bump:
        print("WARNING: --tag is only valid with --bump, ignoring")
    elif args.tag and not args.commit:
        print("ERROR: --tag requires --commit (the spec must be committed before tagging)")
        sys.exit(1)

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

    # Validate tag format (e.g., 'v6.12.74', '6.12.74', or 'ciq_kernel-6.12.74-N')
    try:
        kernel_version = parse_kernel_tag(upstream_tag)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Verify spec file exists
    spec_path = os.path.abspath(args.spec_file)
    if not os.path.exists(spec_path):
        print(f"ERROR: Spec file not found: {spec_path}")
        sys.exit(1)

    new_ciq_tag = None

    if args.bump:
        print("\nBump mode: bumping pkgrelease and prepending changelog")
        print(f"  Kernel Version: {kernel_version}\n")

        print(f"Updating spec file: {spec_path}")
        new_n = bump_spec_file(
            spec_path,
            kernel_version,
            upstream_tag,
            srcgit,
        )
        print("Spec file updated successfully")

        new_ciq_tag = f"{args.tag_prefix}_kernel-{kernel_version}-{new_n}"
        commit_message = f"[CIQ] {new_ciq_tag} - updated spec"
    else:
        full_kernel_version, tag_version, kernel_major_minor, kernel_patch, buildid, new_tag, major_version = (
            calculate_lt_rebase_versions(kernel_version, args.buildid, args.tag_prefix)
        )

        print("\nLT Rebase Version Information:")
        print(f"  Full Kernel Version: {full_kernel_version}")
        print(f"  Kernel Major.Minor: {kernel_major_minor}")
        print(f"  Kernel Patch: {kernel_patch}")
        print(f"  Build ID: {buildid}")
        print(f"  Tag Version: {tag_version}")
        print(f"  New Tag: {new_tag}")
        print(f"  Major Version: {major_version}\n")

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

        commit_message = f"[CIQ] {upstream_tag} - updated spec"

    # Optionally commit the changes
    committed = False
    if args.commit:
        print("Committing changes...")
        spec_path_rel = os.path.relpath(spec_path, srcgit.working_tree_dir)
        srcgit.git.add(spec_path_rel)

        # Check if there are changes to commit
        if srcgit.is_dirty(path=spec_path_rel):
            try:
                srcgit.git.commit("-m", commit_message)
                print(f"Committed: {commit_message}")
                committed = True
            except git.exc.GitCommandError as e:
                print(f"ERROR: Failed to commit changes: {e}")
                sys.exit(1)
        else:
            print("No changes to commit")

    # Optionally create a git tag (bump mode only)
    if args.bump and args.tag:
        if not committed:
            print(f"WARNING: Skipping tag {new_ciq_tag} — no commit was made")
        else:
            print(f"Creating tag {new_ciq_tag}...")
            try:
                srcgit.create_tag(new_ciq_tag)
                print(f"Created tag: {new_ciq_tag}")
            except git.exc.GitCommandError as e:
                print(f"ERROR: Failed to create tag {new_ciq_tag}: {e}")
                sys.exit(1)

    print("\nDone!")
