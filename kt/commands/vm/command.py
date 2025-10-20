import click

from kt.commands.vm.impl import main
from kt.ktlib.shell_completion import ShellCompletion

epilog = """
It spins up a virtual machine for the corresponding kernel.

If the virtual machine does not exist, it gets created.

First, the vm image base (source) is downloaded if it does not exist
in <config.images_source_dir>.

To spin up the machine, a copy of this qcow2 image is put in
<config.images_dir/<kernel>. Even if kernels may share the same image base,
they will have their own configuration and image.
cloud-init.yaml configuration is taken from kt/data and modified accordingly
for each user and then put in the same folder.

Examples:

\b
$ kt vm lts9_4
\b
$ kt vm lts9_4 --console
\b
$ kt vm lts9_4 -c
\b
$ kt vm lts9_4 --destroy
\b
$ kt vm lts9_4 -c --override

"""


@click.command(epilog=epilog)
@click.option(
    "-c",
    "--console",
    is_flag=True,
    help="It connects to the console of the vm",
)
@click.option(
    "-d",
    "--destroy",
    is_flag=True,
    help="It destroys the vm",
)
@click.option(
    "--override",
    is_flag=True,
    help="It destroys the vm if it exists and creates a new one",
)
@click.option(
    "--list-all",
    is_flag=True,
    help="Lists existings vms",
)
@click.option("--test", is_flag=True, help="Build the kernel and run kselftests")
@click.argument("kernel_workspace", required=False, shell_complete=ShellCompletion.show_kernel_workspaces)
def vm(kernel_workspace, console, destroy, override, list_all, test):
    main(name=kernel_workspace, console=console, destroy=destroy, override=override, list_all=list_all, test=test)
