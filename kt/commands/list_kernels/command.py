import click

from kt.commands.list_kernels.impl import main

epilog = """
It list all the kernels we currently maintain.
If --automated or -a is used, it will list all the kernels we maintain
but are also part of KernelCI.

Example:

\b
$ kt list-kernels
cbr-7.9
fipslegacy-8.6
lts-8.6
lts-9.2
lts-9.6

\b
$ kt list-kernels --automated
lts-8.6
lts-9.2
lts-9.6

"""


@click.command(epilog=epilog)
@click.option("-a", "--automated", is_flag=True, help="It selects only automated kernels")
def list_kernels(automated):
    main(automated)
