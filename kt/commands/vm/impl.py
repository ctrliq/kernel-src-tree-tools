import logging

from kt.ktlib.config import Config
from kt.ktlib.ssh import SshCommand
from kt.ktlib.virt import VmCommand
from kt.ktlib.vm import Vm


def main(
    name: str,
    console: bool,
    destroy: bool,
    override: bool,
    override_base: bool,
    list_all: bool,
    test: bool = False,
    vcpus: int = 12,
    memory: int = 32768,
    no_depot: bool = False,
):
    if list_all:
        VmCommand.list_all()
        return

    # If neither test nor console is requested, we just spin up the VM and exit.
    # This is useful for starting a VM that you'll interact with manually (e.g., via SSH).
    # If this behavior is not desired, consider requiring at least one action flag.

    if destroy:
        vm = Vm.load_from_workspace(name)
        vm.destroy()
        return

    vm_instance = Vm.setup_and_spinup(
        kernel_workspace_name=name,
        override=override,
        override_base=override_base,
        vcpus=vcpus,
        memory=memory,
        no_depot=no_depot,
    )
    config = Config.load()

    if test:
        logging.info("Waiting for cloud-init to finish...")
        SshCommand.run(
            domain=vm_instance.domain,
            command=["sudo cloud-init status --wait || true"],
            ssh_key=vm_instance.ssh_key,
        )
        vm_instance.test(config=config)

    if console:
        vm_instance.console()
