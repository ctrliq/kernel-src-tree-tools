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
$ kt checkout lts-9.4
\b
$ kt checkout lts-9.4 --cleanup
\b
$ kt checkout lts-9.4 --cleanup -c
\b
$ kt checkout lts-9.4 --cleanup --change-dir
\b
$ kt checkout lts-9.4 -e CVE-2022-49909
Will create folder lts-9.4_CVE-2022-49909 instead of lts-9.4.
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
@click.argument("kernel", required=True, type=str, shell_complete=ShellCompletion.show_kernels)
def checkout(kernel, change_dir, override, cleanup, extra):
    main(
        name=kernel,
        change_dir=change_dir,
        override=override,
        cleanup=cleanup,
        extra=extra,
    )
