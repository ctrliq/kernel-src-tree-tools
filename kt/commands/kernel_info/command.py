import click

from kt.commands.kernel_info.impl import main
from kt.ktlib.shell_completion import ShellCompletion

epilog = """
Show information about a specific kernel.
It is basically a wrapper that shows what's in kt/data/kernels.yaml, except
for the nested values, like dist_git_root and src_tree_root.

Examples:

\b
$ kt kernel-info lts-9.4
{
  "name": "lts-9.4",
  "src_tree_branch": "ciqlts9_4",
  "dist_git_branch": "lts94-9",
  "mock_config": "rocky-lts94",
  "automated": true
}
"""


@click.command(epilog=epilog)
@click.argument("kernel", required=True, type=str, shell_complete=ShellCompletion.show_kernels)
def kernel_info(kernel):
    main(name=kernel)
