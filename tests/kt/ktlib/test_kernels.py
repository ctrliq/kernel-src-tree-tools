import pytest
from pathlib3x import Path

from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelsInfo

common_repos = {"dist-git-tree-cbr": "dist-url", "kernel-src-tree": "src-url"}

kernels = {
    "kernel1": {
        "src_tree_root": "kernel-src-tree",
        "src_tree_branch": "src-branch",
        "dist_git_root": "dist-git-tree-cbr",
        "dist_git_branch": "dist-branch",
    }
}


data = {"common_repos": common_repos, "kernels": kernels}


def test_kernels_from_empty_dict():
    data = {}
    config = Config.from_str_dict(Config.DEFAULT)

    with pytest.raises(ValueError, match="Failed to process"):
        kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)  # noqa F841


def test_kernels_no_kernels_key():
    data = {"common_repos": {}}
    config = Config.from_str_dict(Config.DEFAULT)

    with pytest.raises(ValueError, match="Failed to process"):
        kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)  # noqa F841


def test_kernels_invalid_kernel():
    data = {
        "common_repos": {},
        "kernels": {
            "kernel1": {
                "src_tree_root": "src-tree-url",
                "src_tree_branch": "src-branch",
                "dist_git_root": "dist-git-url",
                "dist_git_branch": "dist-branch",
            }
        },
    }
    config = Config.from_str_dict(Config.DEFAULT)

    with pytest.raises(ValueError, match="not valid; it must be a reference to"):
        kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)  # noqa F841


def test_kernels_from_dict_check_len():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    assert len(kernels_info.kernels) == 1


def test_kernels_from_dict_check_name():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    name = list(kernels_info.kernels.keys())[0]
    assert name == "kernel1"


def test_kernels_from_dict_check_dist_branch():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.dist_git_branch == "dist-branch"


def test_kernels_from_dict_check_src_branch():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.src_tree_branch == "src-branch"


def test_kernels_from_dict_check_dist_root():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.dist_git_root.folder == config.base_path / Path("dist-git-tree-cbr")


def test_kernels_from_dict_check_src_root():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.src_tree_root.folder == config.base_path / Path("kernel-src-tree")
