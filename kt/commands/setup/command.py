import click

from kt.commands.setup.impl import main

epilog = """
Prepares the working directory for later commands:

It clones the common_repos from kernels.yaml file in the config.base_path
directory.
If the repos are cloned already, they will be updated.

If config.base_path = ~/ciq, these will be created:

~/ciq/kernel-src-tree

~/ciq/dist-git-tree-fips

~/ciq/dist-git-tree-cbr

~/ciq/dit-git-tree-lts

~/ciq/kernel-src-tree-tools

~/ciq/kernel-tools

Examples:

\b
$ kt setup
"""


@click.command(epilog=epilog)
def setup():
    main()
