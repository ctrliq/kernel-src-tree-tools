import click

from kt.commands.list_kernels.impl import main

epilog = """
It list all the kernels we currently maintain.
If --automated or -a is used, it will list all the kernels we maintain
but are also part of KernelCI. Automated mode outputs bare kernel names
suitable for scripting and CI pipelines.

Example:

\b
$ kt list-kernels
cbr-7.9 (default)
fipslegacy-8.6 (default)
lts-8.6 (override)
lts-9.2 (override)
lts-9.6 (default)

\b
$ kt list-kernels --automated
cbr-7.9
lts-8.6
lts-9.2
lts-9.6

"""


@click.command(epilog=epilog)
@click.option("-a", "--automated", is_flag=True, help="It selects only automated kernels")
def list_kernels(automated):
    main(automated)
