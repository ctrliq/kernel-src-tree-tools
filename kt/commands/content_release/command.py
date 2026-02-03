import click

from kt.commands.content_release.impl import ContentRelease
from kt.ktlib.shell_completion import ShellCompletion

epilog = """
Manages the complete content release workflow for kernel packages.

This command automates the kernel content release process through three steps:

--prepare: Validates git config, runs mkdistgitdiff.py to create staging branch,
           and creates a new tagged release in the src_worktree.

--build:   Builds both source and binary RPMs using mock. Downloads sources via
           getsrc.sh and builds kernel packages in build_files directory.
           Requires DEPOT_USER and DEPOT_TOKEN environment variables.

--test:    Spins up a VM, installs the built kernel RPMs, reboots, and runs
           kselftests using /usr/libexec/kselftests/run_kselftest.sh.

When run without options, executes all three steps sequentially.

Examples:

\b
$ DEPOT_USER=user@example.com DEPOT_TOKEN=token kt content-release lts-9.2
\b
$ kt content-release lts-9.2 --prepare
\b
$ DEPOT_USER=user@example.com DEPOT_TOKEN=token kt content-release lts-9.2 --build
\b
$ kt content-release lts-9.2 --test
"""


@click.command(epilog=epilog)
@click.argument("kernel_workspace", required=True, shell_complete=ShellCompletion.show_kernel_workspaces)
@click.option(
    "--prepare",
    is_flag=True,
    help="Run only the prepare step",
)
@click.option(
    "--build",
    is_flag=True,
    help="Run only the build step",
)
@click.option(
    "--test",
    is_flag=True,
    help="Run only the test step",
)
def content_release(kernel_workspace, prepare, build, test):
    """Manage content release workflow (prepare, build, test)."""

    # Check if any specific step was requested
    any_step_specified = prepare or build or test

    # Determine which steps to run
    run_prepare_step = prepare or not any_step_specified
    run_build_step = build or not any_step_specified
    run_test_step = test or not any_step_specified

    if not any_step_specified:
        click.echo(f"Running all content-release steps for {kernel_workspace}: prepare, build, test")

    # Run the selected steps
    if run_prepare_step:
        ContentRelease.prepare(kernel_workspace=kernel_workspace)

    if run_build_step:
        ContentRelease.build(kernel_workspace=kernel_workspace)

    if run_test_step:
        ContentRelease.test(kernel_workspace=kernel_workspace)
