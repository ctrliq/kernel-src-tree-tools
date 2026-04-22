#!/usr/bin/env python3

import logging

import click

from kt.commands.checkout.command import checkout
from kt.commands.content_release.command import content_release
from kt.commands.git_push.command import git_push
from kt.commands.kernel_info.command import kernel_info
from kt.commands.list_kernels.command import list_kernels
from kt.commands.setup.command import setup
from kt.commands.vm.command import vm

epilog = """
Base of all tooling used for kernel development.

All new tooling will be introduced as commands to kt.
"""


@click.group(epilog=epilog)
def cli():
    pass


def main():
    logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.INFO)

    cli.add_command(list_kernels)
    cli.add_command(setup)
    cli.add_command(checkout)
    cli.add_command(git_push)
    cli.add_command(vm)
    cli.add_command(content_release)
    cli.add_command(kernel_info)
    cli()


if __name__ == "__main__":
    main()
