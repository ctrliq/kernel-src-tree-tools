#!/usr/bin/env python3
"""Check for FIPS protected directory changes in a range of git commits.

Exits 0 if no FIPS changes found (or --fips-override is set).
Exits 1 if FIPS changes are found without override.
"""

import argparse
import subprocess
import sys

from kt.ktlib.ciq_helpers import FIPS_PROTECTED_DIRECTORIES, check_for_fips_protected_changes


def main():
    parser = argparse.ArgumentParser(description="Check for FIPS protected directory changes")
    parser.add_argument("--repo", help="Path to git repository", default=".")
    parser.add_argument("--base-ref", help="Base ref (exclusive start of range)", required=True)
    parser.add_argument("--target-ref", help="Target ref (inclusive end of range)", required=True)
    parser.add_argument("--fips-override", help="Override FIPS check abort", action="store_true")
    args = parser.parse_args()

    print(f"[fips-check] Checking for FIPS protected changes in {args.base_ref}..{args.target_ref}")
    print(f"[fips-check] Protected directories: {', '.join(d.decode() for d in FIPS_PROTECTED_DIRECTORIES)}")

    try:
        fips_commits = check_for_fips_protected_changes(args.repo, args.base_ref, args.target_ref)
    except RuntimeError as e:
        print(f"[fips-check] ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if not fips_commits:
        print("[fips-check] No FIPS protected changes found")
        sys.exit(0)

    print("\n[fips-check] ========================================")
    print("[fips-check] FIPS protected changes detected")
    print("[fips-check] ========================================")
    print(f"[fips-check] {len(fips_commits)} commit(s) touch FIPS protected directories:\n")

    for sha, dirs in fips_commits.items():
        result = subprocess.run(
            ["git", "show", "--stat", sha.decode()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=args.repo,
        )
        print(f"## Commit {sha.decode()}")
        if result.returncode == 0:
            print(result.stdout.decode("utf-8", "backslashreplace"))
        else:
            print("  (could not show commit details)")
        for d in sorted(dirs):
            print(f"  FIPS directory: {d.decode()}")
        print()

    if args.fips_override:
        print("[fips-check] --fips-override set, continuing despite FIPS protected changes")
        sys.exit(0)

    print("[fips-check] Please contact the CIQ FIPS / Security team for further instructions")
    print("[fips-check] Use --fips-override to bypass this check")
    sys.exit(1)


if __name__ == "__main__":
    main()
