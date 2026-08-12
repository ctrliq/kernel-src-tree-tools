import click

from kt.commands.checkout.impl import main
from kt.ktlib.shell_completion import ShellCompletion

epilog = """
Prepares the working directory for a kernel.
It uses the KernelInfo dataclass created based on the kernels.yaml file.

The working directory location is based on configuration:
<config.kernels_dir>/<kernel>/

2 git worktrees are created for a kernel:

- dist-git-tree

- kernel-src-tree

They will point out to their root sources. Check kt setup for more info.
They should be located in <config.base_path>.

The worktrees reference the remote <branch> from kernels.yaml.
The local branch is {<user>}/<branch>.

Examples:

\b
$ kt checkout lts-9.2
\b
$ kt checkout lts-9.2 --cleanup
\b
$ kt checkout lts-9.2 --cleanup -c
\b
$ kt checkout lts-9.2 --cleanup --change-dir
\b
$ kt checkout lts-9.2 -e CVE-2022-49909
Will create folder lts-9.2_CVE-2022-49909 instead of lts-9.2.
\b
$ kt checkout cbr-7.9 --no-worktree
Will not create worktrees for CentOS7 bridge.
Note: This is recommended because the git version in the CentOS7 VM is too old to support worktrees.
"""


@click.command(epilog=epilog)
@click.option(
    "-c",
    "--change-dir",
    is_flag=True,
    help="Change directory to the kernel directory",
)
@click.option(
    "--override",
    is_flag=True,
    help="Delete existing worktree for the kernel and start again",
)
@click.option(
    "--cleanup",
    is_flag=True,
    help="Delete existing worktree for the kernel",
)
@click.option(
    "-e",
    "--extra",
    type=str,
    help="Feature you'll be working on",
)
@click.option(
    "--worktree/--no-worktree",
    "use_worktree",
    default=None,
    help="Manually override config worktree configuration for kernel.",
)
@click.argument("kernel", required=True, type=str, shell_complete=ShellCompletion.show_kernels)
def checkout(kernel, change_dir, override, cleanup, extra, use_worktree):
    main(
        name=kernel,
        change_dir=change_dir,
        override=override,
        cleanup=cleanup,
        use_worktree=use_worktree,
        extra=extra,
    )
