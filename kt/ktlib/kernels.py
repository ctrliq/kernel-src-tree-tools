import logging
from dataclasses import dataclass

import yaml
from pathlib3x import Path

from kt.ktlib.config import Config
from kt.ktlib.repo import RepoInfo
from kt.ktlib.util import Constants

# TODO move this to a separate repo
KERNEL_INFO_YAML_PATH = Path(__file__).parent.parent.joinpath("data/kernels.yaml")


@dataclass
class KernelInfo:
    """
    Dataclass that represents each kernel entry in the kernels.yaml file
    name: name of the kernel
    src_tree_root: kernel source tree
    src_tree_branch: the corresponding branch in the source tree
    dist_git_root: rocky staging rpm repo
    dist_git_branch: corresponding branch in the rocky staging rpm repo
    mock_config: mock configuration name for building RPMs

    The src_tree_root and dist_git_root contain absolute paths to the local
    clone of these repos and their corresponding remote url.
    """

    name: str

    src_tree_root: RepoInfo
    src_tree_branch: str

    dist_git_root: RepoInfo
    dist_git_branch: str

    mock_config: str

    automated: bool

    vm_image_url: str | None = None
    depot_channels: list[str] | None = None
    os_variant: str | None = None
    use_nfs: bool = False
    overridden: bool = False
    use_worktree: bool | None = None

    def should_use_worktree(self, config: Config, cli_value=None) -> bool:
        ret = True
        if cli_value is not None:
            ret = cli_value
        elif self.use_worktree is not None:
            ret = self.use_worktree
        else:
            ret = config.use_worktrees

        if self.os_variant == "centos7" and ret is True:
            logging.warning(
                "CentOS 7 does not support worktrees internally.\n"
                "Please check your configs:\n"
                f"- cli_value: {cli_value}\n"
                f"- local use_worktree: {self.use_worktree}\n"
                f"- config value: {config.use_worktrees}"
            )
        return ret


@dataclass
class KernelsInfo:
    kernels: dict[str, KernelInfo]
    repos: dict[str, RepoInfo]

    @classmethod
    def _load_private_config(cls, config: Config) -> tuple[dict[str, str], dict[str, dict]]:
        """Load private repository URLs and kernel overrides from local config"""
        private_repos_path = config.base_path / Constants.PRIVATE_REPOS_CONFIG_FILE

        if not private_repos_path.exists():
            logging.info(f"{private_repos_path} does not exist")
            return {}, {}

        with open(private_repos_path) as f:
            data = yaml.safe_load(f) or {}
            return data.get("private_repos", {}), data.get("kernel_overrides", {})

    @classmethod
    def _get_repos(cls, data: dict, private_data: dict, config: Config):
        repos = {}

        try:
            items = data[Constants.COMMON_REPOS].items()
        except KeyError as e:
            raise ValueError(f"Error: {e}; Failed to process {data}")

        for name, url in items:
            name_path = config.base_path / Path(name)
            repo = RepoInfo(folder=name_path, url=url)
            repos[name] = repo

        for name, url in private_data.items():
            name_path = config.base_path / Path(name)
            repo = RepoInfo(folder=name_path, url=url)
            repos[name] = repo

        return repos

    @classmethod
    def _get_kernels_info(cls, data: dict, repos: dict[str, RepoInfo], kernel_overrides: dict[str, dict] = None):
        kernels_info = {}
        kernel_overrides = kernel_overrides or {}

        try:
            items = data[Constants.KERNELS].items()
        except KeyError as e:
            raise ValueError(f"Failed to process {data}: {e}")

        for kernel, info in items:
            k_info_dict = {"name": kernel, **info}

            if kernel in kernel_overrides:
                k_info_dict.update(kernel_overrides[kernel])
                k_info_dict["overridden"] = True

            # Make the src_tree_root and dist_git_root absolute paths to the
            # local clone of these repos (transformation from src to Path)
            # repos dictionary contains the proper absolute paths
            if k_info_dict[Constants.DIST_GIT_ROOT] not in repos:
                raise ValueError(
                    (
                        f"{k_info_dict[Constants.DIST_GIT_ROOT]} not valid; "
                        f"it must be a reference to one of {list(repos.keys())}"
                    )
                )

            k_info_dict[Constants.DIST_GIT_ROOT] = repos[k_info_dict[Constants.DIST_GIT_ROOT]]

            if k_info_dict[Constants.SRC_TREE_ROOT] not in repos:
                raise ValueError(
                    (
                        f"{k_info_dict[Constants.SRC_TREE_ROOT]} not valid; "
                        f"it must be a reference to one of {list(repos.keys())}"
                    )
                )

            k_info_dict[Constants.SRC_TREE_ROOT] = repos[k_info_dict[Constants.SRC_TREE_ROOT]]

            kernel_info = KernelInfo(**k_info_dict)
            kernels_info[kernel] = kernel_info

        return kernels_info

    @classmethod
    def from_yaml(cls, config: Config):
        data = None

        with open(KERNEL_INFO_YAML_PATH) as f:
            data = yaml.safe_load(f)

        private_data, kernel_overrides = cls._load_private_config(config=config)

        return cls.from_dict(data=data, private_data=private_data, config=config, kernel_overrides=kernel_overrides)

    @classmethod
    def from_dict(cls, data: dict, private_data: dict, config: Config, kernel_overrides: dict[str, dict] = None):
        repos = cls._get_repos(data=data, private_data=private_data, config=config)
        kernels_info = cls._get_kernels_info(data=data, repos=repos, kernel_overrides=kernel_overrides)

        return cls(kernels=kernels_info, repos=repos)
