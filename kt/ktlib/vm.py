from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import wget
from git import Repo
from pathlib3x import Path
from ruamel.yaml import YAML

from urllib.parse import urlparse

from kt.ktlib.config import Config
from kt.ktlib.kernel_workspace import KernelWorkspace
from kt.ktlib.kernels import KernelsInfo
from kt.ktlib.local import LocalCommand
from kt.ktlib.ssh import SshCommand
from kt.ktlib.util import Constants
from kt.ktlib.virt import VirtHelper, VmCommand

# TODO move this to a separate repo
CLOUD_INIT_BASE_PATH = Path(__file__).parent.parent.joinpath("data/cloud_init.yaml")
CLOUD_INIT_CENTOS7_PATH = Path(__file__).parent.parent.joinpath("data/cloud_init_centos7.yaml")


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
    vm_image_url: str | None = None
    depot_channels: list[str] | None = None
    os_variant: str | None = None
    use_nfs: bool = False

    @classmethod
    def load(
        cls,
        config: Config,
        kernel_workspace: KernelWorkspace,
        vm_image_url: str | None = None,
        depot_channels: list[str] | None = None,
        os_variant: str | None = None,
        use_nfs: bool = False,
    ):
        kernel_workspace_str = kernel_workspace.folder.name
        kernel_name = cls._extract_kernel_name(kernel_workspace_str)
        vm_major_version = cls._extract_major(kernel_name)
        vm_major_minor_version = cls._extract_major_minor(kernel_name)

        # Image source paths construction — use pinned URL basename if set, else default
        if vm_image_url:
            source_image_name = Path(urlparse(vm_image_url).path).name
        else:
            source_image_name = cls._qcow2_name(vm_major_minor_version=vm_major_minor_version)

        qcow2_source_path = config.images_source_dir / Path(source_image_name)

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
            vm_image_url=vm_image_url,
            depot_channels=depot_channels,
            os_variant=os_variant,
            use_nfs=use_nfs,
        )

    @classmethod
    def _extract_kernel_name(cls, kernel_workspace):
        # <kernel>_<feature> --> <kernel> where kernel does not contain any '_'
        return kernel_workspace.split("_")[0]

    @classmethod
    def _extract_major(cls, full_version):
        # lts-9.2 --> return 9
        return full_version.split("-")[-1].split(".")[0]

    @classmethod
    def _extract_major_minor(cls, full_version):
        # lts-9.2 -> return 9.2
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

        vm_image_url = None
        depot_channels = None
        os_variant = None
        use_nfs = False
        kernel_name = cls._extract_kernel_name(kernel_workspace_name)
        kernels_info = KernelsInfo.from_yaml(config=config)
        kernel_info = kernels_info.kernels.get(kernel_name)
        if kernel_info:
            vm_image_url = kernel_info.vm_image_url
            depot_channels = kernel_info.depot_channels
            os_variant = kernel_info.os_variant
            use_nfs = kernel_info.use_nfs

        return cls.load(
            config=config,
            kernel_workspace=kernel_workspace,
            vm_image_url=vm_image_url,
            depot_channels=depot_channels,
            os_variant=os_variant,
            use_nfs=use_nfs,
        )

    @classmethod
    def setup_and_spinup(
        cls,
        kernel_workspace_name: str,
        override: bool = False,
        override_base: bool = False,
        vcpus: int = 12,
        memory: int = 32768,
        no_depot: bool = False,
    ):
        """
        Setup and spin up a VM from a kernel workspace name.

        Args:
            kernel_workspace_name: The name of the kernel workspace
            override: If True, destroy and recreate the VM
            override_base: If True, destroy and recreate the VM but override the base image as well
            vcpus: Number of virtual CPUs
            memory: Memory in MiB
            no_depot: If True, skip depot client installation and channel setup

        Returns:
            VmInstance: The running VM instance
        """
        vm = cls.load_from_workspace(kernel_workspace_name)
        config = Config.load()

        if override or override_base:
            vm.destroy()

        vm.setup(override_base=override_base)
        vm_instance = vm.spin_up(config=config, vcpus=vcpus, memory=memory, no_depot=no_depot)

        return vm_instance

    def _get_vm_url(self):
        if self.vm_image_url:
            return self.vm_image_url
        return f"{Constants.BASE_URL}/{self.vm_major_minor_version}/images/x86_64/{Constants.DEFAULT_VM_BASE}-{self.vm_major_version}-{Constants.QCOW2_TRAIL}"

    def _download_source_image(self, override_base: bool = False):
        if self.qcow2_source_path.exists() and not override_base:
            logging.info(f"Image {self.qcow2_source_path} already exists, nothing to do")
            return

        # Make sure the folder exists
        self.qcow2_source_path.parent.mkdir(parents=True, exist_ok=True)

        # Delete existing image if it exists
        self.qcow2_source_path.unlink(missing_ok=True)

        logging.info(f"Downloading image from {self._get_vm_url()}")
        wget.download(self._get_vm_url(), out=str(self.qcow2_source_path))

    def _is_centos7(self) -> bool:
        return bool(self.os_variant and self.os_variant.startswith("centos7"))

    def _setup_cloud_init(self, config: Config, no_depot: bool = False):
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.width = 4096
        yaml.default_flow_style = False
        yaml.best_sequence_indent = 2

        template_path = CLOUD_INIT_CENTOS7_PATH if self._is_centos7() else CLOUD_INIT_BASE_PATH
        with open(template_path) as f:
            data = yaml.load(f)

        # replace placeholders with user data
        data["users"][0]["name"] = config.user

        # password remains the default for now
        data["chpasswd"]["list"][0] = f"{config.user}:test"

        # ssh key
        with open(config.ssh_key) as f:
            ssh_key_content = f.read().strip()
            data["users"][0]["ssh_authorized_keys"][0] = ssh_key_content

        base_path_str = str(config.base_path.absolute())
        if self._is_centos7():
            nfs_source = f"{Constants.LIBVIRT_HOST_IP}:{base_path_str}"
            data["bootcmd"][0] = f"mkdir -p {base_path_str}"
            data["mounts"][0][0] = nfs_source
            data["mounts"][0][1] = base_path_str
            data["mounts"][1][0] = base_path_str
        else:
            data["mounts"][0][1] = base_path_str
            data["mounts"][1][0] = base_path_str

        # Go to the working directory of the kernel
        working_dir = config.kernels_dir / Path(self.name)
        data["write_files"][0]["content"] = f"cd {str(working_dir)}"

        # Because $HOME is the same as the host, during boot, cloud-init
        # sees the home dir already exists and root remains the owner
        # change it to {config.user}
        data["runcmd"][0][1] = f"{config.user}:{config.user}"
        data["runcmd"][0][2] = os.environ["HOME"]

        if not self._is_centos7():
            # Pin dnf to vault for kernels with a pinned VM image (Rocky only)
            if self.vm_image_url:
                data["runcmd"].append(f'echo "{self.vm_major_minor_version}" > /etc/dnf/vars/releasever')
                data["runcmd"].append('echo "vault/rocky" > /etc/dnf/vars/contentdir')
                data["runcmd"].append(
                    "cd /etc/yum.repos.d/ && for f in *.repo; do "
                    'sed -i -e "s/^mirrorlist=/#mirrorlist=/" -e "s/#baseurl=/baseurl=/" "$f"; done'
                )
                data["runcmd"].append("dnf clean all")

        pkg_mgr = "yum" if self._is_centos7() else "dnf"

        # Depot: install the client and login+enable if credentials are present
        if not no_depot:
            data["runcmd"].append(
                f"{pkg_mgr} install -y https://depot.ciq.com/public/files/depot-client/depot/depot.x86_64.rpm"
            )
            depot_user = os.environ.get("DEPOT_USER")
            depot_token = os.environ.get("DEPOT_TOKEN")
            if depot_user and depot_token and self.depot_channels:
                data["runcmd"].append(f"depot login -u {depot_user} -t {depot_token}")
                for channel in self.depot_channels:
                    data["runcmd"].append(f"depot enable {channel} -y")
            data["runcmd"].append(f"{pkg_mgr} clean all")
            data["runcmd"].append(f"{pkg_mgr} update -y")

        # kernel_install_dep.sh only supports Rocky 8/9/10
        if not self._is_centos7():
            data["runcmd"].append(
                [str(config.base_path / Path("kernel-src-tree-tools") / Path("kernel_install_dep.sh"))]
            )

        # Write this to image cloud_init
        with open(self.cloud_init_path, "w") as f:
            yaml.dump(data, f)

    def _create_image(self, config: Config, vcpus: int = 12, memory: int = 32768, no_depot: bool = False):
        # Make sure the dir exists
        self.qcow2_path.parent.mkdir(parents=True, exist_ok=True)

        self._setup_cloud_init(config=config, no_depot=no_depot)
        # Copy qcow2 image to work dir
        self.qcow2_source_path.copy(self.qcow2_path)

        # Resize the disk to 30GB
        self._resize_disk()

        self._virt_install(config=config, vcpus=vcpus, memory=memory)
        time.sleep(Constants.VM_STARTUP_WAIT_SECONDS)

    def _virt_install(self, config: Config, vcpus: int = 12, memory: int = 32768):
        os_variant = self.os_variant or f"rocky{self.vm_major_version}"
        return VmCommand.install(
            name=self.name,
            qcow2_path=self.qcow2_path,
            os_variant=os_variant,
            cloud_init_path=self.cloud_init_path,
            common_dir=config.base_path,
            vcpus=vcpus,
            memory=memory,
            use_nfs=self.use_nfs,
        )

    def _resize_disk(self):
        """Resize the qcow2 disk image to 30GB."""
        logging.info(f"Resizing disk {self.qcow2_path} to 30G")
        try:
            LocalCommand.run(command=["qemu-img", "resize", str(self.qcow2_path), "30G"])
        except RuntimeError as e:
            raise RuntimeError(f"Failed to resize disk image: {e}")

    def setup(self, override_base: bool = False):
        self._download_source_image(override_base=override_base)

    def _wait_for_running(self):
        attempted_start = False
        for attempt in range(Constants.VM_POLL_MAX_ATTEMPTS):
            if VirtHelper.is_running(vm_name=self.name):
                logging.info(f"VM {self.name} is running")
                return
            if not attempted_start and VirtHelper.exists(vm_name=self.name):
                logging.info(f"VM {self.name} is shut off, attempting start...")
                try:
                    VmCommand.start(vm_name=self.name)
                    attempted_start = True
                except RuntimeError as e:
                    logging.warning(f"Failed to start VM {self.name}: {e}")
            logging.info(
                f"Waiting for VM {self.name} to be running (attempt {attempt + 1}/{Constants.VM_POLL_MAX_ATTEMPTS})..."
            )
            time.sleep(Constants.VM_POLL_INTERVAL_SECONDS)
        raise RuntimeError(
            f"VM {self.name} did not become running after {Constants.VM_POLL_MAX_ATTEMPTS * Constants.VM_POLL_INTERVAL_SECONDS}s"
        )

    def spin_up(self, config: Config, vcpus: int = 12, memory: int = 32768, no_depot: bool = False) -> VmInstance:
        if not VirtHelper.exists(vm_name=self.name):
            logging.info(f"VM {self.name} does not exist, creating from scratch...")

            self._create_image(config=config, vcpus=vcpus, memory=memory, no_depot=no_depot)
            self._wait_for_running()
            return VmInstance(name=self.name, kernel_workspace=self.kernel_workspace, config=config)

        logging.info(f"Vm {self.name} already exists")

        if VirtHelper.is_running(vm_name=self.name):
            logging.info(f"Vm {self.name} is running, nothing to do")
            return VmInstance(name=self.name, kernel_workspace=self.kernel_workspace, config=config)

        logging.info(f"Vm {self.name} is not running, starting it")
        VmCommand.start(vm_name=self.name)
        self._wait_for_running()

        return VmInstance(name=self.name, kernel_workspace=self.kernel_workspace, config=config)

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

    def __init__(self, name: str, kernel_workspace: KernelWorkspace, config: Config):
        self.name = name
        ip_addr = VirtHelper.ip_addr(vm_name=self.name)
        self.domain = f"{config.user}@{ip_addr}"
        self.kernel_workspace = kernel_workspace
        ssh_pub = str(config.ssh_key)
        self.ssh_key = ssh_pub.removesuffix(".pub") if ssh_pub.endswith(".pub") else ssh_pub
        self._wait_for_ssh()

    def _wait_for_ssh(self):
        for attempt in range(Constants.VM_POLL_MAX_ATTEMPTS):
            try:
                SshCommand.run(domain=self.domain, command=["true"], ssh_key=self.ssh_key)
                logging.info(f"SSH connection to {self.domain} established")
                return
            except RuntimeError:
                logging.info(
                    f"Waiting for SSH on {self.domain} (attempt {attempt + 1}/{Constants.VM_POLL_MAX_ATTEMPTS})..."
                )
                time.sleep(Constants.VM_POLL_INTERVAL_SECONDS)
        raise RuntimeError(
            f"SSH to {self.domain} not available after "
            f"{Constants.VM_POLL_MAX_ATTEMPTS * Constants.VM_POLL_INTERVAL_SECONDS}s"
        )

    def wait_for_cloud_init(self):
        """ "Wait for cloud-init to finish on the VM. This method will block until cloud-init has completed its tasks."""
        try:
            SshCommand.run(
                domain=self.domain,
                command=["sudo cloud-init status --wait || true"],
                ssh_key=self.ssh_key,
            )
        except RuntimeError as e:
            if "closed by remote host" in str(e):
                logging.info("VM rebooted during cloud-init, waiting for it to come back...")
                self._wait_for_ssh()
            else:
                raise

    def reboot(self):
        logging.debug("Rebooting vm")

        command = ["sudo", "reboot"]
        try:
            SshCommand.run(domain=self.domain, command=command, ssh_key=self.ssh_key)
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

        SshCommand.run_with_output(output_file=output_file, domain=self.domain, command=[ssh_cmd], ssh_key=self.ssh_key)

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
            SshCommand.run_with_output(
                output_file=output_file, domain=self.domain, command=[kselftest_cmd], ssh_key=self.ssh_key
            )
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
        return SshCommand.running_kernel_version(domain=self.domain, ssh_key=self.ssh_key)

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

        SshCommand.run_with_output(output_file=output_file, domain=self.domain, command=[ssh_cmd], ssh_key=self.ssh_key)

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
