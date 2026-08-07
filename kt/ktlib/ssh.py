from kt.ktlib.command_runner import CommandRunner


class SshCommand(CommandRunner):
    COMMAND = "ssh"

    @classmethod
    def _build_command(cls, domain: str, command: list[str], ssh_key: str | None = None) -> list[str]:
        cmd = [cls.COMMAND, "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]
        if ssh_key:
            cmd += ["-i", ssh_key]
        return cmd + [domain] + command

    @classmethod
    def running_kernel_version(cls, domain, ssh_key: str | None = None):
        return cls.run(domain=domain, command=["uname", "-r"], ssh_key=ssh_key)
