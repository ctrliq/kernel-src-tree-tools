from kt.ktlib.command_runner import CommandRunner


class SshCommand(CommandRunner):
    COMMAND = "ssh"
    EXTRA = "-o StrictHostKeyChecking=no"

    @classmethod
    def _build_command(cls, domain: str, command: list[str]) -> list[str]:
        return [cls.COMMAND, cls.EXTRA, domain] + command

    @classmethod
    def running_kernel_version(cls, domain):
        return cls.run(domain=domain, command=["uname", "-r"])
