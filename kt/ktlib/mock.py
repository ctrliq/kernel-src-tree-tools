import logging
import os
from dataclasses import dataclass
from pathlib3x import Path

from kt.ktlib.config import Config
from kt.ktlib.kernel_workspace import KernelWorkspace
from kt.ktlib.kernels import KernelsInfo
from kt.ktlib.local import LocalCommand


@dataclass
class MockConfig:
    """
    Represents a mock configuration for building RPMs.

    Attributes:
        config_path: Path to the mock config file to use
        is_temporary: Whether this config is temporary and needs cleanup
        kernel_workspace: The kernel workspace name
    """

    config_path: Path
    is_temporary: bool
    kernel_workspace: str

    def cleanup(self):
        """Remove temporary mock config if it was created."""
        if self.is_temporary and self.config_path.exists():
            try:
                self.config_path.unlink()
                logging.info("Removed temporary mock config")
            except OSError as e:
                logging.warning(f"Failed to remove temporary mock config: {e}")


class Mock:
    """Mock build system operations."""

    @classmethod
    def verify_prerequisites(cls):
        """
        Verify mock is installed and user is in mock group.

        Raises:
            RuntimeError: If mock is not installed or user is not in mock group
        """
        # Verify mock command is available
        try:
            mock_path = LocalCommand.run(command=["which", "mock"]).strip()
            logging.info(f"mock command found at: {mock_path}")
        except RuntimeError:
            raise RuntimeError("mock command not found. Please install mock:\n  sudo dnf install mock")

        # Verify current user is in mock group
        try:
            groups_output = LocalCommand.run(command=["groups"])
            groups = groups_output.strip().split()
            if "mock" not in groups:
                raise RuntimeError(
                    "Current user is not in the mock group. Please add yourself to the mock group:\n"
                    "  sudo usermod -a -G mock $USER\n"
                    "Then log out and log back in for the group change to take effect."
                )
            logging.info("User is in mock group")
        except RuntimeError as e:
            raise RuntimeError(f"Failed to check user groups: {e}")

    @classmethod
    def verify_depot_credentials(cls):
        """
        Verify DEPOT_USER and DEPOT_TOKEN environment variables are set.

        Returns:
            Tuple of (depot_user, depot_token)

        Raises:
            RuntimeError: If either environment variable is not set
        """
        depot_user = os.environ.get("DEPOT_USER")
        depot_token = os.environ.get("DEPOT_TOKEN")

        if not depot_user:
            raise RuntimeError(
                "DEPOT_USER environment variable is not set. Please set it:\n  export DEPOT_USER=your_username"
            )
        if not depot_token:
            raise RuntimeError(
                "DEPOT_TOKEN environment variable is not set. Please set it:\n  export DEPOT_TOKEN=your_token"
            )
        logging.info("DEPOT_USER and DEPOT_TOKEN environment variables are set")

        return depot_user, depot_token

    @classmethod
    def prepare_config(cls, kernel_workspace: str, kernel_workspace_obj: KernelWorkspace, config: Config) -> MockConfig:
        """
        Prepare mock configuration for building.

        For CBR kernels, uses the config directly.
        For depot-based kernels, creates a temporary config with credentials replaced.

        Args:
            kernel_workspace: The name of the kernel workspace (e.g., 'lts-9.4')
            kernel_workspace_obj: The kernel workspace object
            config: The configuration object

        Returns:
            MockConfig object with the path to the config to use

        Raises:
            RuntimeError: If config not found or kernel workspace is unknown
        """
        # Get the mock config name from kernels.yaml
        kernels_info = KernelsInfo.from_yaml(config)
        if kernel_workspace not in kernels_info.kernels:
            raise RuntimeError(
                f"Unknown kernel workspace: {kernel_workspace}\n"
                f"Supported workspaces: {', '.join(sorted(kernels_info.kernels.keys()))}"
            )

        kernel_info = kernels_info.kernels[kernel_workspace]
        mock_config_base = kernel_info.mock_config

        # CBR is a special case - no depot config, no credential replacement needed
        is_cbr = kernel_workspace.startswith("cbr-")

        if is_cbr:
            mock_config_name = f"{mock_config_base}-x86_64.cfg"
        else:
            mock_config_name = f"{mock_config_base}-depot-x86_64.cfg"

        # Find the mock config file
        mock_configs_dir = config.base_path / "mock-configs"
        mock_config_source = mock_configs_dir / mock_config_name

        if not mock_config_source.exists():
            raise RuntimeError(
                f"Mock config not found: {mock_config_source}\nExpected to find {mock_config_name} in {mock_configs_dir}"
            )

        logging.info(f"Found mock config: {mock_config_source}")

        # For CBR, use the config directly. For others, create temp config with credentials
        if is_cbr:
            logging.info("Using CBR mock config directly (no depot credentials needed)")
            return MockConfig(config_path=mock_config_source, is_temporary=False, kernel_workspace=kernel_workspace)
        else:
            # Verify depot credentials are set
            depot_user, depot_token = cls.verify_depot_credentials()

            # Create a temporary mock config with DEPOT credentials replaced
            temp_mock_config = kernel_workspace_obj.folder / f"temp_{mock_config_name}"

            logging.info(f"Creating temporary mock config: {temp_mock_config}")

            with open(mock_config_source, "r") as src:
                config_content = src.read()

            # Replace DEPOT_USER and DEPOT_TOKEN
            config_content = config_content.replace("DEPOT_USER", depot_user)
            config_content = config_content.replace("DEPOT_TOKEN", depot_token)

            with open(temp_mock_config, "w") as dest:
                dest.write(config_content)

            logging.info("Temporary mock config created with credentials")
            return MockConfig(config_path=temp_mock_config, is_temporary=True, kernel_workspace=kernel_workspace)

    @classmethod
    def build_srpm(cls, mock_config: MockConfig, build_files_dir: Path, dist_git_path: Path, output_log: Path):
        """
        Build SRPM using mock.

        Args:
            mock_config: The mock configuration to use
            build_files_dir: Directory where build results will be placed
            dist_git_path: Path to dist-git repository (working directory)
            output_log: Path to write build output

        Raises:
            RuntimeError: If SRPM build fails
        """
        logging.info("Building SRPM with mock...")
        logging.info(f"Mock SRPM build output will be written to {output_log}")

        mock_cmd = [
            "mock",
            "-v",
            "-r",
            str(mock_config.config_path),
            f"--resultdir={build_files_dir}",
            "--buildsrpm",
            "--spec=SPECS/kernel.spec",
            "--sources=SOURCES",
        ]

        try:
            LocalCommand.run_with_output(command=mock_cmd, output_file=str(output_log), cwd=dist_git_path)
            logging.info("SRPM build completed successfully")
        except RuntimeError as e:
            logging.error(f"Mock SRPM build failed with exit code {e}")
            logging.error(f"Check {output_log} for details")
            raise RuntimeError(f"Mock SRPM build failed. See {output_log} for details")

    @classmethod
    def build_rpms(
        cls, mock_config: MockConfig, srpm_file: Path, build_files_dir: Path, dist_git_path: Path, output_log: Path
    ):
        """
        Build binary RPMs from SRPM using mock.

        Args:
            mock_config: The mock configuration to use
            srpm_file: Path to the source RPM file
            build_files_dir: Directory where build results will be placed
            dist_git_path: Path to dist-git repository (working directory)
            output_log: Path to write build output

        Raises:
            RuntimeError: If RPM build fails
        """
        logging.info("Building binary RPMs with mock...")
        logging.info(f"Mock binary RPM build output will be written to {output_log}")

        mock_build_cmd = [
            "mock",
            "-v",
            "-r",
            str(mock_config.config_path),
            f"--resultdir={build_files_dir}",
            str(srpm_file),
        ]

        try:
            LocalCommand.run_with_output(command=mock_build_cmd, output_file=str(output_log), cwd=dist_git_path)
            logging.info("Binary RPM build completed successfully")
        except RuntimeError as e:
            logging.error(f"Mock binary RPM build failed with exit code {e}")
            logging.error(f"Check {output_log} for details")
            raise RuntimeError(f"Mock binary RPM build failed. See {output_log} for details")
