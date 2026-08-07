import logging
import re
import time
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
        os_variant: str,
        cloud_init_path: Path,
        common_dir: Path,
        vcpus: int = 12,
        memory: int = 32768,
        use_nfs: bool = False,
    ):
        command = [
            "--name",
            name,
            "--disk",
            f"{qcow2_path},device=disk,bus=virtio",
            f"--os-variant={os_variant}",
            "--virt-type",
            "kvm",
            "--vcpus",
            str(vcpus),
            "--memory",
            str(memory),
            "--vnc",
            "--cloud-init",
            f"user-data={cloud_init_path}",
        ]

        if not use_nfs:
            command += [
                "--filesystem",
                f"source={common_dir},target=mount_tag_mock_scratch,accessmode=passthrough,driver.type=virtiofs,driver.queue=1024,binary.path=/usr/libexec/virtiofsd,binary.xattr=on",
                "--memorybacking",
                "source.type=memfd,access.mode=shared",
            ]

        command.append("--noautoconsole")

        cls.run(command_type=VmCommandType.VIRT_INSTALL, command=command)

    @classmethod
    def start(cls, vm_name: str):
        try:
            cls.run(command_type=VmCommandType.VIRSH, command=["start", vm_name])
        except RuntimeError as e:
            if "Domain is already active" in str(e):
                pass
            else:
                raise e

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
    IP_PATTERN = re.compile(r"\d+\.\d+\.\d+\.\d+")
    IP_POLL_INTERVAL = 5
    IP_POLL_MAX_ATTEMPTS = 24

    @classmethod
    def ip_addr(cls, vm_name: str) -> str:
        for attempt in range(cls.IP_POLL_MAX_ATTEMPTS):
            output = VmCommand.domifaddr(vm_name=vm_name)
            for token in output:
                match = cls.IP_PATTERN.search(token)
                if match:
                    return match.group()
            logging.info(f"Waiting for IP address for {vm_name} (attempt {attempt + 1}/{cls.IP_POLL_MAX_ATTEMPTS})...")
            time.sleep(cls.IP_POLL_INTERVAL)
        raise RuntimeError(
            f"VM {vm_name} did not get an IP address after {cls.IP_POLL_MAX_ATTEMPTS * cls.IP_POLL_INTERVAL}s"
        )

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
