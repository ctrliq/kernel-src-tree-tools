import pytest
from pathlib3x import Path

from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelsInfo

common_repos = {"dist-git-tree": "dist-url", "kernel-src-tree": "src-url"}

kernels = {
    "kernel1": {
        "src_tree_root": "kernel-src-tree",
        "src_tree_branch": "src-branch",
        "dist_git_root": "dist-git-tree",
        "dist_git_branch": "dist-branch",
        "mock_config": "test-mock-config",
        "automated": True,
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
    assert kernel_info.dist_git_root.folder == config.base_path / Path("dist-git-tree")


def test_kernels_from_dict_check_src_root():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.src_tree_root.folder == config.base_path / Path("kernel-src-tree")


def test_kernels_vm_image_url_default_none():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.vm_image_url is None


def test_kernels_override_dist_git_branch():
    config = Config.from_str_dict(Config.DEFAULT)
    overrides = {"kernel1": {"dist_git_branch": "overridden-branch"}}

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config, kernel_overrides=overrides)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.dist_git_branch == "overridden-branch"


def test_kernels_override_dist_git_root():
    private_repos = {"dist-git-tree-private": "private-url"}
    overrides = {"kernel1": {"dist_git_root": "dist-git-tree-private"}}
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(
        data=data, private_data=private_repos, config=config, kernel_overrides=overrides
    )
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.dist_git_root.folder == config.base_path / Path("dist-git-tree-private")


def test_kernels_override_nonexistent_kernel_ignored():
    config = Config.from_str_dict(Config.DEFAULT)
    overrides = {"nonexistent-kernel": {"dist_git_branch": "some-branch"}}

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config, kernel_overrides=overrides)
    assert len(kernels_info.kernels) == 1


def test_kernels_no_overrides_uses_defaults():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.dist_git_branch == "dist-branch"


def test_kernels_vm_image_url_present():
    pinned_url = (
        "https://dl.rockylinux.org/vault/rocky/9.2/images/x86_64/Rocky-9-GenericCloud-Base-9.2-20230513.0.x86_64.qcow2"
    )
    kernels_with_pin = {
        "kernel1": {
            **kernels["kernel1"],
            "vm_image_url": pinned_url,
        }
    }
    data_with_pin = {"common_repos": common_repos, "kernels": kernels_with_pin}
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data_with_pin, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.vm_image_url == pinned_url


# --- use_worktree field ---


def test_kernels_use_worktree_default_none():
    config = Config.from_str_dict(Config.DEFAULT)
    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.use_worktree is None


def test_kernels_use_worktree_parsed_from_dict():
    kernels_with_flag = {
        "kernel1": {
            **kernels["kernel1"],
            "use_worktree": False,
        }
    }
    data_with_flag = {"common_repos": common_repos, "kernels": kernels_with_flag}
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data_with_flag, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.use_worktree is False


def test_kernels_use_worktree_settable_via_overrides():
    config = Config.from_str_dict(Config.DEFAULT)
    overrides = {"kernel1": {"use_worktree": False}}

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config, kernel_overrides=overrides)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.use_worktree is False


# --- should_use_worktree precedence ---


def test_should_use_worktree_cli_wins():
    config = Config.from_str_dict({**Config.DEFAULT, "use_worktrees": True})
    kernels_with_flag = {"kernel1": {**kernels["kernel1"], "use_worktree": True}}
    data_with_flag = {"common_repos": common_repos, "kernels": kernels_with_flag}

    kernels_info = KernelsInfo.from_dict(data=data_with_flag, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.should_use_worktree(config=config, cli_value=False) is False


def test_should_use_worktree_per_kernel_over_global():
    config = Config.from_str_dict({**Config.DEFAULT, "use_worktrees": True})
    kernels_with_flag = {"kernel1": {**kernels["kernel1"], "use_worktree": False}}
    data_with_flag = {"common_repos": common_repos, "kernels": kernels_with_flag}

    kernels_info = KernelsInfo.from_dict(data=data_with_flag, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.should_use_worktree(config=config) is False


def test_should_use_worktree_global_fallback():
    config = Config.from_str_dict({**Config.DEFAULT, "use_worktrees": False})

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    # kernel1 has no use_worktree set, so falls through to global
    assert kernel_info.should_use_worktree(config=config) is False


def test_should_use_worktree_default_true():
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]
    assert kernel_info.should_use_worktree(config=config) is True


def test_should_use_worktree_centos7_warns(caplog):
    kernels_centos7 = {
        "kernel1": {
            **kernels["kernel1"],
            "os_variant": "centos7",
        }
    }
    data_centos7 = {"common_repos": common_repos, "kernels": kernels_centos7}
    config = Config.from_str_dict(Config.DEFAULT)

    kernels_info = KernelsInfo.from_dict(data=data_centos7, private_data={}, config=config)
    kernel_info = list(kernels_info.kernels.values())[0]

    import logging

    with caplog.at_level(logging.WARNING):
        result = kernel_info.should_use_worktree(config=config)
    assert result is True
    assert "CentOS 7" in caplog.text
