from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import oyaml as yaml
import wget
from git import Repo
from pathlib3x import Path

from kt.ktlib.config import Config
from kt.ktlib.kernel_workspace import KernelWorkspace
from kt.ktlib.local import LocalCommand
from kt.ktlib.ssh import SshCommand
from kt.ktlib.util import Constants
from kt.ktlib.virt import VirtHelper, VmCommand

# TODO move this to a separate repo
CLOUD_INIT_BASE_PATH = Path(__file__).parent.parent.joinpath("data/cloud_init.yaml")


@dataclass
class Vm:
    """
    Class that represents a virtual machine.

    Attributes:
    name: name of the vm

    qcow2_source_path: qcow2 path to the vm image used as source
    vm_major_version: major vm version (9 for Rocky 9)
    vm_major_version: major.minor vm version (9.2 for Rocky 9.2)
    qcow2_path: the qcow2 path of the vm image copied from qcow2_source_path
    cloud_init_path: cloud_init.yaml config, adapted from data/cloud_init.yaml
    """

    qcow2_source_path: Path
    vm_major_version: str
    vm_major_minor_version: str
    qcow2_path: Path
    cloud_init_path: Path
    name: str
    kernel_workspace: KernelWorkspace

    @classmethod
    def load(cls, config: Config, kernel_workspace: KernelWorkspace):
        kernel_workspace_str = kernel_workspace.folder.name
        kernel_name = cls._extract_kernel_name(kernel_workspace_str)
        vm_major_version = cls._extract_major(kernel_name)
        vm_major_minor_version = cls._extract_major_minor(kernel_name)

        # Image source paths construction
        qcow2_source_path = config.images_source_dir / Path(
            cls._qcow2_name(vm_major_minor_version=vm_major_minor_version)
        )

        # Actual current image paths construction
        work_dir = config.images_dir / Path(kernel_workspace_str)
        qcow2_path = work_dir / Path(f"{kernel_workspace_str}.qcow2")
        cloud_init_path = work_dir / Path(Constants.CLOUD_INIT)

        return cls(
            qcow2_source_path=qcow2_source_path,
            vm_major_version=vm_major_version,
            vm_major_minor_version=vm_major_minor_version,
            qcow2_path=qcow2_path,
            cloud_init_path=cloud_init_path,
            name=kernel_workspace_str,
            kernel_workspace=kernel_workspace,
        )

    @classmethod
    def _extract_kernel_name(cls, kernel_workspace):
        # <kernel>_<feature> --> <kernel> where kernel does not contain any '_'
        return kernel_workspace.split("_")[0]

    @classmethod
    def _extract_major(cls, full_version):
        # lts-9.4 --> return 9
        return full_version.split("-")[-1].split(".")[0]

    @classmethod
    def _extract_major_minor(cls, full_version):
        # lts-9.4 -> return 9.4
        return full_version.split("-")[-1]

    @classmethod
    def _qcow2_name(cls, vm_major_minor_version: str):
        return f"{Constants.DEFAULT_VM_BASE}-{vm_major_minor_version}-{Constants.QCOW2_TRAIL}"

    @classmethod
    def load_from_workspace(cls, kernel_workspace_name: str):
        """
        Load VM from a kernel workspace name.

        Args:
            kernel_workspace_name: The name of the kernel workspace

        Returns:
            Vm: The VM object
        """
        config = Config.load()
        kernel_workpath = config.kernels_dir / kernel_workspace_name
        kernel_workspace = KernelWorkspace.load_from_filepath(folder=kernel_workpath)
        return cls.load(config=config, kernel_workspace=kernel_workspace)

    @classmethod
    def setup_and_spinup(cls, kernel_workspace_name: str, override: bool = False, vcpus: int = 12, memory: int = 32768):
        """
        Setup and spin up a VM from a kernel workspace name.

        Args:
            kernel_workspace_name: The name of the kernel workspace
            override: If True, destroy and recreate the VM
            vcpus: Number of virtual CPUs
            memory: Memory in MiB

        Returns:
            VmInstance: The running VM instance
        """
        vm = cls.load_from_workspace(kernel_workspace_name)
        config = Config.load()

        if override:
            vm.destroy()

        vm.setup(config=config)
        vm_instance = vm.spin_up(config=config, vcpus=vcpus, memory=memory)

        return vm_instance

    def _get_vm_url(self):
        return f"{Constants.BASE_URL}/{self.vm_major_minor_version}/images/x86_64/{Constants.DEFAULT_VM_BASE}-{self.vm_major_version}-{Constants.QCOW2_TRAIL}"

    def _download_source_image(self):
        if self.qcow2_source_path.exists():
            logging.info(f"Image {self.qcow2_source_path} already exists, nothing to do")
            return

        # Make sure the folder exists
        self.qcow2_source_path.parent.mkdir(parents=True, exist_ok=True)

        # Delete existing image if it exists
        self.qcow2_source_path.unlink(missing_ok=True)

        logging.info(f"Downloading image from {self._get_vm_url()}")
        wget.download(self._get_vm_url(), out=str(self.qcow2_source_path))

    def _setup_cloud_init(self, config: Config):
        data = None
        with open(CLOUD_INIT_BASE_PATH) as f:
            data = yaml.safe_load(f)

        # replace placeholders with user data
        data["users"][0]["name"] = config.user

        # password remains the default for now
        data["chpasswd"]["list"][0] = f"{config.user}:test"

        # ssh key
        with open(config.ssh_key) as f:
            ssh_key_content = f.read().strip()
            data["users"][0]["ssh_authorized_keys"][0] = ssh_key_content

        data["mounts"][0][1] = str(config.base_path.absolute())
        data["mounts"][1][0] = str(config.base_path.absolute())

        # Go to the working directory of the kernel
        working_dir = config.kernels_dir / Path(self.name)
        data["write_files"][0]["content"] = f"cd {str(working_dir)}"

        # Because $HOME is the same as the host, during boot, cloud-init
        # sees the home dir already exists and root remains the owner
        # change it to {config.user}
        data["runcmd"][0][1] = f"{config.user}:{config.user}"
        data["runcmd"][0][2] = os.environ["HOME"]

        # Install packages needed later
        data["runcmd"].append([str(config.base_path / Path("kernel-src-tree-tools") / Path("kernel_install_dep.sh"))])
        # Write this to image cloud_init
        with open(self.cloud_init_path, "w") as f:
            f.write("#cloud-config\n")
            yaml.dump(data, f)

    def _create_image(self, config: Config, vcpus: int = 12, memory: int = 32768):
        # Make sure the dir exists
        self.qcow2_path.parent.mkdir(parents=True, exist_ok=True)

        self._setup_cloud_init(config=config)
        # Copy qcow2 image to work dir
        self.qcow2_source_path.copy(self.qcow2_path)

        # Resize the disk to 30GB
        self._resize_disk()

        self._virt_install(config=config, vcpus=vcpus, memory=memory)
        time.sleep(Constants.VM_STARTUP_WAIT_SECONDS)

    def _virt_install(self, config: Config, vcpus: int = 12, memory: int = 32768):
        return VmCommand.install(
            name=self.name,
            qcow2_path=self.qcow2_path,
            vm_major_version=self.vm_major_version,
            cloud_init_path=self.cloud_init_path,
            common_dir=config.base_path,
            vcpus=vcpus,
            memory=memory,
        )

    def _resize_disk(self):
        """Resize the qcow2 disk image to 30GB."""
        logging.info(f"Resizing disk {self.qcow2_path} to 30G")
        try:
            LocalCommand.run(command=["qemu-img", "resize", str(self.qcow2_path), "30G"])
        except RuntimeError as e:
            raise RuntimeError(f"Failed to resize disk image: {e}")

    def setup(self, config: Config):
        self._download_source_image()

    def spin_up(self, config: Config, vcpus: int = 12, memory: int = 32768) -> VmInstance:
        if not VirtHelper.exists(vm_name=self.name):
            logging.info(f"VM {self.name} does not exist, creating from scratch...")

            self._create_image(config=config, vcpus=vcpus, memory=memory)
            return VmInstance(name=self.name, kernel_workspace=self.kernel_workspace)

        logging.info(f"Vm {self.name} already exists")

        if VirtHelper.is_running(vm_name=self.name):
            logging.info(f"Vm {self.name} is running, nothing to do")
            return VmInstance(name=self.name, kernel_workspace=self.kernel_workspace)

        logging.info(f"Vm {self.name} is not running, starting it")
        VmCommand.start(vm_name=self.name)
        time.sleep(Constants.VM_STARTUP_WAIT_SECONDS)

        return VmInstance(name=self.name, kernel_workspace=self.kernel_workspace)

    def destroy(self):
        if VirtHelper.is_running(vm_name=self.name):
            VmCommand.destroy(vm_name=self.name)

        if VirtHelper.exists(vm_name=self.name):
            VmCommand.undefine(vm_name=self.name)

        # remove its folder that contains the qcow2 image and cloud-init config
        self.qcow2_path.parent.rmtree(ignore_errors=True)


class VmInstance:
    name: str
    ssh_domain: str
    kernel_workspace: KernelWorkspace

    def __init__(self, name: str, kernel_workspace: KernelWorkspace):
        self.name = name
        ip_addr = VirtHelper.ip_addr(vm_name=self.name)
        username = os.environ["USER"]
        self.domain = f"{username}@{ip_addr}"
        self.kernel_workspace = kernel_workspace

    def reboot(self):
        logging.debug("Rebooting vm")

        command = ["sudo", "reboot"]
        try:
            SshCommand.run(domain=self.domain, command=command)
        except RuntimeError as e:
            if "closed by remote host" in str(e):
                pass

        time.sleep(Constants.VM_REBOOT_WAIT_SECONDS)
        VmCommand.start(vm_name=self.name)
        time.sleep(Constants.VM_STARTUP_WAIT_SECONDS)

    def current_head_sha_long(self):
        repo = Repo(self.kernel_workspace.src_worktree.folder)
        return repo.head.commit.hexsha

    def current_head_sha_short(self):
        return self.current_head_sha_long()[:7]

    def kselftests(self, config):
        """Run kselftests from source tree."""
        logging.debug("Running kselftests")
        script = str(config.base_path / Path("kernel-src-tree-tools") / Path("kernel_kselftest.sh"))
        output_file = self.kernel_workspace.folder.absolute() / Path(f"kselftest-{self.current_head_sha_short()}.log")
        ssh_cmd = f"cd {self.kernel_workspace.src_worktree.folder.absolute()} &&  sudo {script}"

        SshCommand.run_with_output(output_file=output_file, domain=self.domain, command=[ssh_cmd])

    def kselftests_internal(self, output_file: Path):
        """
        Run installed kselftests from /usr/libexec/kselftests (for official releases).

        Args:
            output_file: Path to write kselftest output

        Raises:
            RuntimeError: If kselftests fail
        """
        logging.info("Running kernel selftests...")
        logging.info(f"Kselftest output will be written to {output_file}")

        kselftest_cmd = "sudo /usr/libexec/kselftests/run_kselftest.sh"

        try:
            SshCommand.run_with_output(output_file=output_file, domain=self.domain, command=[kselftest_cmd])
            logging.info("Kselftests completed successfully")
        except RuntimeError as e:
            logging.error(f"Kselftests failed: {e}")
            logging.error(f"Check {output_file} for details")
            raise RuntimeError(f"Kselftests failed. See {output_file} for details")

    @staticmethod
    def count_kselftest_passed(log_file: Path):
        """
        Count the number of passed tests in a kselftest log file.

        Args:
            log_file: Path to the kselftest log file

        Returns:
            int or None: Number of passed tests, or None if counting failed
        """
        try:
            with open(log_file, "r") as f:
                passed_tests = sum(1 for line in f if line.startswith("ok"))
            logging.info(f"Kselftests passed: {passed_tests} tests")
            return passed_tests
        except OSError as e:
            logging.warning(f"Could not count passed tests: {e}")
            return None

    def running_kernel_version(self):
        """
        Get the running kernel version from the VM.

        Returns:
            str: The kernel version string (e.g., "5.14.0-284.30.1+23.1.el9_2_ciq.x86_64")
        """
        return SshCommand.running_kernel_version(domain=self.domain)

    def expected_kernel_version(self):
        """
        Check if running kernel matches the current HEAD sha (for unofficial builds).

        Returns:
            bool: True if running kernel was built from current HEAD
        """
        kernel_version = self.running_kernel_version()
        subversions = kernel_version.split("-")
        if len(subversions) < 2:
            return False

        # TODO some proper matching versioning here
        install_hash = subversions[-1].split("+")[0]

        head_hash = self.current_head_sha_long()
        if not head_hash.startswith(install_hash):
            return False

        return True

    def build_kernel(self, config):
        logging.debug("Building kernel")
        build_script = str(config.base_path / Path("kernel-src-tree-tools") / Path("kernel_build.sh"))
        output_file = self.kernel_workspace.folder.absolute() / Path(
            f"kernel-build-{self.current_head_sha_short()}.log"
        )
        ssh_cmd = f"cd {self.kernel_workspace.src_worktree.folder.absolute()} &&  {build_script} -n"

        SshCommand.run_with_output(output_file=output_file, domain=self.domain, command=[ssh_cmd])

    def test(self, config):
        if self.expected_kernel_version():
            logging.info("Expected running kernel version, no need to build the kernel")
        else:
            self.build_kernel(config=config)
            self.reboot()

        if not self.expected_kernel_version():
            raise RuntimeError("Kernel version is not what we expect")

        self.kselftests(config=config)

    def console(self):
        VmCommand.console(vm_name=self.name)
