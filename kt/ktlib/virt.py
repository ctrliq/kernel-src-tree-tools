from enum import Enum

from pathlib3x import Path

from kt.ktlib.command_runner import CommandRunner


class VmCommandType(Enum):
    VIRSH = 1
    VIRT_INSTALL = 2


class VmCommand(CommandRunner):
    CONNECT = "--connect"
    DOMAIN = "qemu:///system"
    COMMAND_MAP = {
        VmCommandType.VIRSH: "virsh",
        VmCommandType.VIRT_INSTALL: "virt-install",
    }

    @classmethod
    def _build_command(cls, command_type: VmCommandType, command: list[str]) -> list[str]:
        return [
            cls.COMMAND_MAP[command_type],
            cls.CONNECT,
            cls.DOMAIN,
        ] + command

    @classmethod
    def dominfo(cls, vm_name: str) -> dict[str, str]:
        result = cls.run(command_type=VmCommandType.VIRSH, command=["dominfo", vm_name]).strip().split("\n")

        # TODO Security label has multiple : and it breaks the logic
        return dict([tuple("".join(x.split()).split(":")[:2]) for x in result])

    @classmethod
    def install(
        cls,
        name: str,
        qcow2_path: Path,
        vm_major_version: str,
        cloud_init_path: Path,
        common_dir: Path,
    ):
        command = [
            "--name",
            name,
            "--disk",
            f"{qcow2_path},device=disk,bus=virtio",
            f"--os-variant=rocky{vm_major_version}",
            "--virt-type",
            "kvm",
            "--vcpus",
            "12,vcpu.cpuset=0-11,vcpu.placement=static",
            "--memory",
            str(32768),
            "--vnc",
            "--cloud-init",
            f"user-data={cloud_init_path}",
            "--filesystem",
            f"source={common_dir},target=mount_tag_mock_scratch,accessmode=passthrough,driver.type=virtiofs,driver.queue=1024,binary.path=/usr/libexec/virtiofsd,binary.xattr=on",
            "--memorybacking",
            "source.type=memfd,access.mode=shared",
            "--noautoconsole",
        ]

        cls.run(command_type=VmCommandType.VIRT_INSTALL, command=command)

    @classmethod
    def start(cls, vm_name: str) -> str:
        cls.run(command_type=VmCommandType.VIRSH, command=["start", vm_name])

    @classmethod
    def console(cls, vm_name: str):
        child = cls.spawn(command_type=VmCommandType.VIRSH, command=["console", vm_name])
        child.interact()

    @classmethod
    def destroy(cls, vm_name: str):
        cls.run(command_type=VmCommandType.VIRSH, command=["destroy", vm_name])

    @classmethod
    def undefine(cls, vm_name: str):
        cls.run(command_type=VmCommandType.VIRSH, command=["undefine", vm_name])

    @classmethod
    def list_all(cls):
        print(cls.run(command_type=VmCommandType.VIRSH, command=["list", "--all"]))

    @classmethod
    def domifaddr(cls, vm_name: str) -> list[str]:
        return cls.run(command_type=VmCommandType.VIRSH, command=["domifaddr", vm_name]).strip().split("\n")[-1].split()


class VirtHelper:
    @classmethod
    def ip_addr(cls, vm_name: str) -> str:
        rc = VmCommand.domifaddr(vm_name=vm_name)

        return rc[-1].split("/")[0]

    @classmethod
    def is_running(cls, vm_name: str) -> bool:
        try:
            result = VmCommand.dominfo(vm_name=vm_name)
        except Exception:
            return False

        return result["State"] == "running"

    @classmethod
    def exists(cls, vm_name: str) -> bool:
        try:
            result = VmCommand.dominfo(vm_name=vm_name)
        except Exception:
            return False

        return result["Name"] == vm_name
