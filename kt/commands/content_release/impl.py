import logging
import os
import re

from git import GitCommandError, Repo

from kt.ktlib.config import Config
from kt.ktlib.kernel_workspace import KernelWorkspace
from kt.ktlib.local import LocalCommand
from kt.ktlib.mock import Mock
from kt.ktlib.ssh import SshCommand
from kt.ktlib.vm import Vm

# Source download configuration for kernels that don't work with getsrc.sh
SOURCE_DOWNLOAD_CONFIG = {
    "lts-8.6": {
        "base_url": "https://rocky-linux-sources-staging.a1.rockylinux.org",
        "files": [
            ("cd67969ef0be82516b144066d3897b071f59f2a2", "kernel-abi-stablelists-4.18.0-372.tar.bz2"),
            ("89ce72b86bacc9c2cd712784e9053d9c36f37c23", "kernel-kabi-dw-4.18.0-372.tar.bz2"),
            ("c48b00ba5e77fcf4bc9e2dd5e58f1791ae71e8c8", "linux-4.18.0-372.32.1.el8_6.tar.xz"),
        ],
    },
    "fipslegacy-8.6": {
        "base_url": "https://rocky-linux-sources-staging.a1.rockylinux.org",
        "files": [
            ("feac61524ad00b8b03f2985f8ac330c7939ba425", "kernel-abi-stablelists-4.18.0-425.tar.bz2"),
            ("f2fb49be6e6fe2782bc58e2914d8dcc7b2948764", "kernel-kabi-dw-4.18.0-425.tar.bz2"),
            ("57cc7ba600df4d74be3a1b8c2324ea69b92699e4", "linux-4.18.0-425.13.1.el8_7.tar.xz"),
        ],
    },
    "cbr-7.9": {
        "base_url": "https://git.centos.org/sources/kernel/c7",
        "files": [
            ("ba5599148e52ecd126ebcf873672e26d3288323e", "kernel-abi-whitelists-1160.tar.bz2"),
            ("5000b85c42ef87b6835dd8eef063e4623c2e0fa9", "kernel-kabi-dw-1160.tar.bz2"),
            ("83cf85ab62fc9dca6d34175c60cc17cb917d7e0d", "linux-3.10.0-1160.119.1.el7.tar.xz"),
        ],
    },
}


class ContentRelease:
    """Manages the complete content release workflow for kernel packages."""

    @classmethod
    def prepare(cls, kernel_workspace: str):
        """
        Prepare step for content release.

        Ensures git user.name and user.email are configured in the kernel-dist-git repo
        or globally.

        Args:
            kernel_workspace: The name of the kernel workspace (e.g., 'lts-9.2')
        """
        logging.info(f"Running prepare step for kernel workspace: {kernel_workspace}")

        # Load the kernel workspace to get the dist-git repo path
        kernel_workspace_obj = KernelWorkspace.load_from_name(kernel_workspace)
        config = Config.load()

        # Get the kernel-dist-git repo
        dist_git_path = kernel_workspace_obj.dist_worktree.folder

        logging.info(f"Checking git config in {dist_git_path}")

        # Check user.name and user.email
        user_name = kernel_workspace_obj.dist_worktree.check_git_config_value("user", "name")
        user_email = kernel_workspace_obj.dist_worktree.check_git_config_value("user", "email")

        missing = []
        if not user_name:
            missing.append("user.name")
        if not user_email:
            missing.append("user.email")

        if missing:
            raise RuntimeError(
                f"Git config {' and '.join(missing)} not set in {dist_git_path} or globally. "
                f"Please configure them using:\n"
                f"  git config --global user.name 'Your Name'\n"
                f"  git config --global user.email 'your.email@example.com'\n"
                f"Or set them locally in the repository:\n"
                f"  cd {dist_git_path}\n"
                f"  git config user.name 'Your Name'\n"
                f"  git config user.email 'your.email@example.com'"
            )

        logging.info(f"Git config validated: user.name='{user_name}', user.email='{user_email}'")

        # Run mkdistgitdiff.py
        mkdistgitdiff_script = config.base_path / "kernel-tools" / "mkdistgitdiff.py"
        if not mkdistgitdiff_script.exists():
            raise RuntimeError(f"mkdistgitdiff.py not found at {mkdistgitdiff_script}")

        logging.info(f"Running mkdistgitdiff.py from {dist_git_path}")

        # Get just the branch name from remote_branch (strip "origin/" prefix)
        src_branch_name = str(kernel_workspace_obj.src_worktree.remote_branch).split("/")[-1]
        staging_branch = f"{{automation_tmp}}_{src_branch_name}"

        cmd = [
            str(mkdistgitdiff_script),
            "--srcgit",
            str(kernel_workspace_obj.src_worktree.folder.absolute()),
            "--srcgit-branch",
            kernel_workspace_obj.src_worktree.local_branch,
            "--distgit",
            ".",
            "--distgit-branch",
            kernel_workspace_obj.dist_worktree.local_branch,
            "--distgit-staging-branch",
            staging_branch,
            "--last-tag",
            "--bump",
        ]

        output_file = kernel_workspace_obj.folder.absolute() / "mkdistgitdiff.log"
        logging.info(f"Output will be written to {output_file}")

        try:
            LocalCommand.run_with_output(command=cmd, output_file=str(output_file), cwd=dist_git_path)
            logging.info("mkdistgitdiff.py completed successfully")
        except RuntimeError as e:
            logging.error(f"mkdistgitdiff.py failed with exit code {e}")
            logging.error(f"Check {output_file} for details")
            raise RuntimeError(f"mkdistgitdiff.py failed. See {output_file} for details")

        # Checkout the new staging branch created by mkdistgitdiff
        logging.info(f"Checking out staging branch: {staging_branch}")

        repo = Repo(dist_git_path)
        try:
            repo.git.checkout(staging_branch)
            logging.info(f"Successfully checked out {staging_branch}")
        except GitCommandError as e:
            logging.error(f"Failed to checkout {staging_branch}: {e}")
            raise RuntimeError(f"Failed to checkout staging branch {staging_branch}")

        # Verify and display the newly created tag from mkdistgitdiff output
        try:
            with open(output_file, "r") as f:
                log_content = f.read()
                # Look for the "Content Release" line which contains the new tag
                # Pattern matches version-like strings: kernel-X.Y.Z-A.B+C.D.elN_M_ciq
                tag_pattern = r"Content Release\s+(kernel-[\d\.]+-[\d\.]+\+[\d\.]+\.el\d+_\d+_ciq)"
                match = re.search(tag_pattern, log_content)
                if match:
                    tag_name = match.group(1)
                    logging.info(f"New tag created in src_worktree: {tag_name}")
                else:
                    # Fallback to old method if pattern doesn't match
                    for line in log_content.split("\n"):
                        if "Content Release" in line:
                            parts = line.split("Content Release")
                            if len(parts) > 1:
                                tag_name = parts[1].strip()
                                logging.info(f"New tag created in src_worktree: {tag_name}")
                                break
                    else:
                        logging.warning("Could not find new tag in mkdistgitdiff output")
        except OSError as e:
            logging.warning(f"Could not read tag from mkdistgitdiff output: {e}")

        logging.info("Prepare step completed")

    @classmethod
    def _download_sources(cls, kernel_workspace_obj: KernelWorkspace):
        """
        Download kernel sources using appropriate method.

        Args:
            kernel_workspace_obj: The kernel workspace object
        """
        kernel_workspace = kernel_workspace_obj.folder.name
        dist_git_path = kernel_workspace_obj.dist_worktree.folder
        sources_dir = dist_git_path / "SOURCES"

        download_config = SOURCE_DOWNLOAD_CONFIG.get(kernel_workspace)

        if download_config:
            # Direct download for special cases
            logging.info(f"Downloading {kernel_workspace} source files directly...")
            for hash_or_id, filename in download_config["files"]:
                url = f"{download_config['base_url']}/{hash_or_id}"
                try:
                    LocalCommand.run(command=["curl", url, "-o", str(sources_dir / filename)])
                except RuntimeError as e:
                    raise RuntimeError(f"Failed to download {filename}: {e}")
            logging.info(f"{kernel_workspace} source files downloaded successfully")
        else:
            # Use getsrc.sh for all other kernels
            logging.info("Downloading getsrc.sh script...")
            try:
                LocalCommand.run(
                    command=[
                        "curl",
                        "-O",
                        "https://raw.githubusercontent.com/rocky-linux/rocky-tools/main/getsrc/getsrc.sh",
                    ],
                    cwd=dist_git_path,
                )
                logging.info("getsrc.sh downloaded successfully")
            except RuntimeError as e:
                raise RuntimeError(f"Failed to download getsrc.sh: {e}")

            getsrc_script = dist_git_path / "getsrc.sh"
            try:
                LocalCommand.run(command=["chmod", "+x", str(getsrc_script)])
                logging.info("getsrc.sh made executable")
            except RuntimeError as e:
                raise RuntimeError(f"Failed to make getsrc.sh executable: {e}")

            try:
                LocalCommand.run(command=[str(getsrc_script)], cwd=dist_git_path)
                logging.info("getsrc.sh completed successfully")
            except RuntimeError as e:
                raise RuntimeError(f"getsrc.sh failed: {e}")

    @classmethod
    def build(cls, kernel_workspace: str):
        """
        Build step for content release.

        Verifies mock is available and user is in mock group, then builds the kernel RPMs.

        Args:
            kernel_workspace: The name of the kernel workspace (e.g., 'lts-9.2')
        """
        logging.info(f"Running build step for kernel workspace: {kernel_workspace}")

        # Verify mock prerequisites
        Mock.verify_prerequisites()

        # Load kernel workspace
        kernel_workspace_obj = KernelWorkspace.load_from_name(kernel_workspace)
        config = Config.load()

        # Prepare mock configuration
        mock_config = Mock.prepare_config(kernel_workspace, kernel_workspace_obj, config)

        # Create build_files directory
        build_files_dir = kernel_workspace_obj.folder / "build_files"
        build_files_dir.mkdir(exist_ok=True)
        if not build_files_dir.exists():
            raise RuntimeError(f"Failed to create build_files directory: {build_files_dir}")
        logging.info(f"Build files directory: {build_files_dir}")

        # Get dist_worktree path (where we'll run mock from)
        dist_git_path = kernel_workspace_obj.dist_worktree.folder
        logging.info(f"Running mock from: {dist_git_path}")

        # Download kernel sources
        cls._download_sources(kernel_workspace_obj)

        # Build SRPM using mock
        mock_srpm_log = kernel_workspace_obj.folder / "mock_buildsrpm.log"
        Mock.build_srpm(mock_config, build_files_dir, dist_git_path, mock_srpm_log)

        # Find the SRPM that was just built
        srpm_files = list(build_files_dir.glob("*.src.rpm"))
        if not srpm_files:
            raise RuntimeError(f"No SRPM found in {build_files_dir}")
        srpm_file = srpm_files[0]
        logging.info(f"Found SRPM: {srpm_file.name}")

        # Build binary RPMs from the SRPM
        mock_build_log = kernel_workspace_obj.folder / "mock_build.log"
        Mock.build_rpms(mock_config, srpm_file, build_files_dir, dist_git_path, mock_build_log)

        # List all RPMs created
        rpm_files = sorted(build_files_dir.glob("*.rpm"))
        if rpm_files:
            logging.info(f"Created {len(rpm_files)} RPM(s):")
            for rpm in rpm_files:
                logging.info(f"  {rpm.name}")
        else:
            logging.warning("No RPM files found in build directory")

        # Clean up temporary mock config if needed
        mock_config.cleanup()

        logging.info("Build step completed")

    @classmethod
    def test(cls, kernel_workspace: str):
        """
        Test step for content release.

        Spins up VM, installs built RPMs, reboots, and runs kselftests.

        Args:
            kernel_workspace: The name of the kernel workspace (e.g., 'lts-9.2')
        """
        if not kernel_workspace:
            logging.error("kernel_workspace is required for the test command")
            raise ValueError("kernel_workspace argument is required for test command")

        logging.info(f"Running test step for kernel workspace: {kernel_workspace}")

        # Load kernel workspace
        kernel_workspace_obj = KernelWorkspace.load_from_name(kernel_workspace)

        # Setup and spin up the VM (reuses common code from vm command)
        vm_instance = Vm.setup_and_spinup(kernel_workspace_name=kernel_workspace)

        # Wait for dependencies to be installed if VM was just created
        logging.info("Waiting for VM dependencies to be installed...")
        SshCommand.run(domain=vm_instance.domain, command=["sudo cloud-init status --wait || true"])

        # Install the built RPMs
        build_files_dir = kernel_workspace_obj.folder / "build_files"
        logging.info(f"Installing RPMs from {build_files_dir}...")

        # Special case for fipslegacy-8.6: enable depot to prevent issues with secure boot shim
        if kernel_workspace == "fipslegacy-8.6":
            logging.info("Enabling depot for fipslegacy-8.6...")
            depot_user = os.environ.get("DEPOT_USER")
            depot_token = os.environ.get("DEPOT_TOKEN")

            if not depot_user or not depot_token:
                raise RuntimeError(
                    "DEPOT_USER and DEPOT_TOKEN environment variables must be set for fipslegacy-8.6 testing"
                )

            try:
                # Install depot client
                SshCommand.run(
                    domain=vm_instance.domain,
                    command=[
                        'sudo dnf install -y "https://depot.ciq.com/public/files/depot-client/depot/depot.x86_64.rpm"'
                    ],
                )
                logging.info("Depot client installed")

                # Register depot with credentials
                SshCommand.run(
                    domain=vm_instance.domain, command=[f"sudo depot register -u {depot_user} -t {depot_token}"]
                )
                logging.info("Depot registered")

                # Enable fips-legacy-8
                SshCommand.run(domain=vm_instance.domain, command=["sudo depot enable fips-legacy-8"])
                logging.info("fips-legacy-8 enabled via depot")
            except RuntimeError as e:
                logging.error(f"Failed to enable depot for fipslegacy-8.6: {e}")
                raise RuntimeError(f"Failed to enable depot for fipslegacy-8.6: {e}")

        # Build the list of RPMs to install (exclude src, rt, and debug RPMs)
        all_rpms = list(build_files_dir.glob("*.rpm"))
        install_rpms = [
            rpm
            for rpm in all_rpms
            if not rpm.name.endswith(".src.rpm")
            and not rpm.name.startswith("kernel-rt")
            and not rpm.name.startswith("kernel-debug-")
        ]

        if not install_rpms:
            raise RuntimeError(f"No installable RPMs found in {build_files_dir}")

        rpm_paths = " ".join(str(rpm.absolute()) for rpm in install_rpms)
        # Remove libtraceevent first to avoid file conflicts with perf package
        install_cmd = (
            f"sudo dnf remove -y libtraceevent || true && sudo dnf install --skip-broken --allowerasing {rpm_paths} -y"
        )
        # install_cmd = f"sudo dnf clean all && sudo dnf install --skip-broken --allowerasing {rpm_paths} -y"

        install_log = kernel_workspace_obj.folder.absolute() / "install.log"
        logging.info(f"Installing {len(install_rpms)} RPM(s)")
        logging.info(f"RPM install output will be written to {install_log}")

        try:
            SshCommand.run_with_output(output_file=install_log, domain=vm_instance.domain, command=[install_cmd])
            logging.info("RPMs installed successfully")
        except RuntimeError as e:
            logging.error(f"RPM installation failed: {e}")
            logging.error(f"Check {install_log} for details")
            raise RuntimeError(f"RPM installation failed. See {install_log} for details")

        # Determine expected kernel version from the built RPMs
        kernel_rpms = list(build_files_dir.glob("kernel-[0-9]*.x86_64.rpm"))
        expected_version = None
        if kernel_rpms:
            # Extract version from RPM filename: kernel-5.14.0-284.30.1+23.1.el9_2_ciq.x86_64.rpm
            rpm_name = kernel_rpms[0].name
            # Use regex to extract version (more robust than string replacement)
            # Pattern: kernel-VERSION.ARCH.rpm where VERSION includes everything up to .x86_64
            version_match = re.match(r"kernel-(.*?)\.rpm$", rpm_name)
            if version_match:
                expected_version = version_match.group(1)
                logging.info(f"Expected kernel version: {expected_version}")
            else:
                # Fallback to old string replacement method
                expected_version = rpm_name.replace("kernel-", "").replace(".rpm", "")
                logging.info(f"Expected kernel version (fallback): {expected_version}")
        else:
            logging.warning("Could not determine expected kernel version from RPMs")

        # Ensure /boot/grub2/grubenv is a real file, not a symlink
        # grub can't follow symlinks, so if grubenv is a symlink we need to make it a real file
        logging.info("Ensuring /boot/grub2/grubenv is a real file...")
        grubenv_fix_cmd = (
            "sudo bash -c 'if [ -L /boot/grub2/grubenv ]; then "
            "cp --remove-destination $(readlink -f /boot/grub2/grubenv) /boot/grub2/grubenv; "
            "fi'"
        )
        try:
            SshCommand.run(domain=vm_instance.domain, command=[grubenv_fix_cmd])
            logging.info("grubenv symlink fixed if needed")
        except RuntimeError as e:
            logging.error(f"Failed to fix grubenv symlink: {e}")
            raise RuntimeError(f"Failed to fix grubenv symlink: {e}")

        # Set the newly installed kernel as the default boot kernel
        if expected_version:
            logging.info(f"Setting default boot kernel to {expected_version}")
            kernel_path = f"/boot/vmlinuz-{expected_version}"
            set_default_cmd = f"sudo grubby --set-default={kernel_path}"
            try:
                SshCommand.run(domain=vm_instance.domain, command=[set_default_cmd])
                logging.info("Default boot kernel set successfully")
            except RuntimeError as e:
                logging.error(f"Failed to set default boot kernel: {e}")
                raise RuntimeError(f"Failed to set default boot kernel: {e}")

        # Reboot the VM
        logging.info("Rebooting VM...")
        vm_instance.reboot()

        # Get the running kernel version from the VM
        kernel_version = vm_instance.running_kernel_version().strip()
        logging.info(f"Running kernel version: {kernel_version}")

        # Verify the kernel version matches what we installed
        if expected_version and kernel_version != expected_version:
            raise RuntimeError(f"Kernel version mismatch! Expected: {expected_version}, Running: {kernel_version}")
        logging.info("Verified VM is running the newly installed kernel")

        # Run kselftests using the installed kselftests
        kselftest_log = kernel_workspace_obj.folder.absolute() / f"selftest-{kernel_version}.log"
        vm_instance.kselftests_internal(kselftest_log)

        # Count passed tests
        vm_instance.count_kselftest_passed(kselftest_log)

        logging.info("Test step completed successfully")
