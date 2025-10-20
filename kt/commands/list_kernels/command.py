import click

from kt.commands.list_kernels.impl import main

epilog = """
It list all the kernels we currently maintain.

Example:

\b
$ kt list-kernels

"""


@click.command(epilog=epilog)
def list_kernels():
    main()
