from kt.ktlib.command_runner import CommandRunner


class LocalCommand(CommandRunner):
    """
    Command runner for local commands.
    """

    @classmethod
    def _build_command(cls, command: list[str]) -> list[str]:
        """Return the command as-is for local execution."""
        return command
