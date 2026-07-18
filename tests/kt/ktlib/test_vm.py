import os
from io import StringIO
from unittest.mock import MagicMock, patch

import oyaml as yaml
from pathlib3x import Path

from kt.ktlib.util import Constants
from kt.ktlib.vm import Vm

_real_open = open


def _make_vm(vm_image_url=None, major="9", major_minor="9.2"):
    vm = Vm.__new__(Vm)
    vm.vm_major_version = major
    vm.vm_major_minor_version = major_minor
    vm.vm_image_url = vm_image_url
    return vm


def test_get_vm_url_default():
    vm = _make_vm()
    url = vm._get_vm_url()
    expected = f"{Constants.BASE_URL}/9.2/images/x86_64/{Constants.DEFAULT_VM_BASE}-9-{Constants.QCOW2_TRAIL}"
    assert url == expected


def test_get_vm_url_pinned():
    pin = (
        "https://dl.rockylinux.org/vault/rocky/9.2/images/x86_64/Rocky-9-GenericCloud-Base-9.2-20230513.0.x86_64.qcow2"
    )
    vm = _make_vm(vm_image_url=pin)
    assert vm._get_vm_url() == pin


def test_load_cache_filename_default():
    config = MagicMock()
    config.images_source_dir = Path("/tmp/images")
    config.images_dir = Path("/tmp/virt-images")

    workspace = MagicMock()
    workspace.folder.name = "lts-9.2"

    vm = Vm.load(config=config, kernel_workspace=workspace)
    assert vm.qcow2_source_path.name == "Rocky-9.2-GenericCloud.latest.x86_64.qcow2"


def test_load_cache_filename_pinned():
    config = MagicMock()
    config.images_source_dir = Path("/tmp/images")
    config.images_dir = Path("/tmp/virt-images")

    workspace = MagicMock()
    workspace.folder.name = "lts-9.2"

    pin = (
        "https://dl.rockylinux.org/vault/rocky/9.2/images/x86_64/Rocky-9-GenericCloud-Base-9.2-20230513.0.x86_64.qcow2"
    )
    vm = Vm.load(config=config, kernel_workspace=workspace, vm_image_url=pin)
    assert vm.qcow2_source_path.name == "Rocky-9-GenericCloud-Base-9.2-20230513.0.x86_64.qcow2"


def test_load_pinned_url_stored():
    config = MagicMock()
    config.images_source_dir = Path("/tmp/images")
    config.images_dir = Path("/tmp/virt-images")

    workspace = MagicMock()
    workspace.folder.name = "lts-9.6"

    pin = (
        "https://dl.rockylinux.org/vault/rocky/9.6/images/x86_64/Rocky-9-GenericCloud-Base-9.6-20250531.0.x86_64.qcow2"
    )
    vm = Vm.load(config=config, kernel_workspace=workspace, vm_image_url=pin)
    assert vm.vm_image_url == pin
    assert vm._get_vm_url() == pin


def _make_config():
    config = MagicMock()
    config.user = "testuser"
    config.ssh_key = "/tmp/fake_key.pub"
    base = MagicMock()
    base.__str__ = lambda self: "/home/testuser/ciq"
    base.__truediv__ = lambda self, other: Path("/home/testuser/ciq") / other
    base.absolute.return_value = Path("/home/testuser/ciq")
    config.base_path = base
    config.kernels_dir = Path("/home/testuser/ciq/kernels")
    return config


def _build_vm_and_get_runcmd(vm_image_url=None, depot_channels=None, depot_env=None):
    """Build a Vm, call _setup_cloud_init, and capture the generated runcmd."""
    config = _make_config()

    vm = Vm.__new__(Vm)
    vm.vm_major_version = "8"
    vm.vm_major_minor_version = "8.6"
    vm.vm_image_url = vm_image_url
    vm.depot_channels = depot_channels
    vm.name = "lts-8.6"
    vm.cloud_init_path = Path("/tmp/test_cloud_init.yaml")

    env = {"HOME": "/home/testuser"}
    if depot_env:
        env["DEPOT_USER"] = depot_env[0]
        env["DEPOT_TOKEN"] = depot_env[1]
    else:
        env["DEPOT_USER"] = ""
        env["DEPOT_TOKEN"] = ""

    captured_yaml = {}

    def fake_open(path, mode="r"):
        path_str = str(path)
        if mode == "w":
            buf = StringIO()

            class WriteCapture:
                def __enter__(self_inner):
                    return buf

                def __exit__(self_inner, *args):
                    captured_yaml["content"] = buf.getvalue()

            return WriteCapture()
        if path_str == str(config.ssh_key):
            buf = StringIO("ssh-ed25519 TESTKEY")

            class ReadCtx:
                def __enter__(self_inner):
                    return buf

                def __exit__(self_inner, *args):
                    pass

            return ReadCtx()
        return _real_open(path, mode)

    with patch("builtins.open", side_effect=fake_open), patch.dict(os.environ, env):
        vm._setup_cloud_init(config=config)

    content = captured_yaml.get("content", "")
    if content.startswith("#cloud-config\n"):
        content = content[len("#cloud-config\n") :]
    data = yaml.safe_load(content)
    return data["runcmd"]


def test_cloud_init_vault_pin_present_when_image_pinned():
    pin = "https://dl.rockylinux.org/vault/rocky/8.6/images/Rocky-8-GenericCloud-8.6.20220702.0.x86_64.qcow2"
    runcmd = _build_vm_and_get_runcmd(vm_image_url=pin)

    runcmd_strs = [str(c) for c in runcmd]
    assert any("releasever" in s and "8.6" in s for s in runcmd_strs)
    assert any("vault/rocky" in s for s in runcmd_strs)
    assert any("mirrorlist" in s for s in runcmd_strs)


def test_cloud_init_no_vault_pin_when_no_image_url():
    runcmd = _build_vm_and_get_runcmd(vm_image_url=None)

    runcmd_strs = [str(c) for c in runcmd]
    assert not any("releasever" in s for s in runcmd_strs)
    assert not any("vault/rocky" in s for s in runcmd_strs)


def test_cloud_init_depot_install_always_present():
    runcmd = _build_vm_and_get_runcmd(vm_image_url=None)
    runcmd_strs = [str(c) for c in runcmd]
    assert any("depot.x86_64.rpm" in s for s in runcmd_strs)


def test_cloud_init_depot_login_when_creds_present():
    runcmd = _build_vm_and_get_runcmd(
        depot_channels=["lts-8.6"],
        depot_env=("myuser", "mytoken"),
    )
    runcmd_strs = [str(c) for c in runcmd]
    assert any("depot login -u myuser -t mytoken" in s for s in runcmd_strs)
    assert any("depot enable lts-8.6 -y" in s for s in runcmd_strs)


def test_cloud_init_no_depot_login_without_creds():
    runcmd = _build_vm_and_get_runcmd(depot_channels=["lts-8.6"])
    runcmd_strs = [str(c) for c in runcmd]
    assert not any("depot login" in s for s in runcmd_strs)
    assert not any("depot enable" in s for s in runcmd_strs)


def test_cloud_init_ordering():
    """Vault pin, then depot, then kernel_install_dep.sh — in that order."""
    pin = "https://dl.rockylinux.org/vault/rocky/8.6/images/Rocky-8-GenericCloud-8.6.20220702.0.x86_64.qcow2"
    runcmd = _build_vm_and_get_runcmd(
        vm_image_url=pin,
        depot_channels=["lts-8.6"],
        depot_env=("myuser", "mytoken"),
    )
    runcmd_strs = [str(c) for c in runcmd]

    vault_idx = next(i for i, s in enumerate(runcmd_strs) if "releasever" in s)
    depot_install_idx = next(i for i, s in enumerate(runcmd_strs) if "depot.x86_64.rpm" in s)
    depot_login_idx = next(i for i, s in enumerate(runcmd_strs) if "depot login" in s)
    dep_script_idx = next(i for i, s in enumerate(runcmd_strs) if "kernel_install_dep.sh" in s)

    assert vault_idx < depot_install_idx < depot_login_idx < dep_script_idx
