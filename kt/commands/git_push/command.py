import click

from kt.commands.git_push.impl import main
from kt.ktlib.shell_completion import ShellCompletion

epilog = """
It pushes the branch to remote for the kernelworkspace selected.
Since for every kernel we have two repos, one for the kernel source
and one for dist-git, an extra param is needed to select the repo.
The kernel workspace is created beforehead with kt checkout command.
Therefore, for every kernel we would have the branch
{USER}_<official_kernel_branch>_<feature>, where feature is optional.
This command will push this branch to the origin.

Examples:

\b
$ kt git-push lts-9.4 -k
Will push the branch {USER}_ciqlts-9.4 from kernel-src-tree from lts-9.4 kernel
workspace.

\b
$ kt git-push lts-9.4 -k -f
Same as above but it will force push

\b
$ kt git-push lts-9.4 -d
Will push the branch {USER}_lts94-9 from kernel-dist-tree from lts-9.4 kernel
workspace.

"""


@click.command(epilog=epilog)
@click.option(
    "-k",
    "--kernel-source",
    is_flag=True,
    help="It selects the kernel source repo",
)
@click.option(
    "-d",
    "--dist-git",
    is_flag=True,
    help="It selects the dist-git repo",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="It force pushes the branch",
)
@click.argument("kernel_workspace", required=False, shell_complete=ShellCompletion.show_kernel_workspaces)
def git_push(kernel_workspace, kernel_source, dist_git, force):
    main(
        name=kernel_workspace,
        kernel_source=kernel_source,
        dist_git=dist_git,
        force=force,
    )
