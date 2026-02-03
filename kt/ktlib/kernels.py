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


@dataclass
class KernelsInfo:
    kernels: dict[str, KernelInfo]
    repos: dict[str, RepoInfo]

    @classmethod
    def _load_private_repos(cls, config: Config) -> dict[str, str]:
        """Load private repository URLs from local config"""
        private_repos_path = config.base_path / Constants.PRIVATE_REPOS_CONFIG_FILE

        if not private_repos_path.exists():
            logging.info(f"{private_repos_path} does not exist")
            return {}

        with open(private_repos_path) as f:
            data = yaml.safe_load(f)
            return data.get("private_repos", {})

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
    def _get_kernels_info(cls, data: dict, repos: dict[str, RepoInfo]):
        kernels_info = {}

        try:
            items = data[Constants.KERNELS].items()
        except KeyError as e:
            raise ValueError(f"Failed to process {data}: {e}")

        for kernel, info in items:
            k_info_dict = {"name": kernel, **info}

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

        private_data = cls._load_private_repos(config=config)

        return cls.from_dict(data=data, private_data=private_data, config=config)

    @classmethod
    def from_dict(cls, data: dict, private_data: dict, config: Config):
        repos = cls._get_repos(data=data, private_data=private_data, config=config)
        kernels_info = cls._get_kernels_info(data=data, repos=repos)

        return cls(kernels=kernels_info, repos=repos)
