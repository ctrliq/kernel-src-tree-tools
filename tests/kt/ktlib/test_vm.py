from unittest.mock import MagicMock

from pathlib3x import Path

from kt.ktlib.util import Constants
from kt.ktlib.vm import Vm


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
