import logging
import subprocess
import sys

import pexpect


class CommandRunner:
    """
    Base class for bash command execution
    """

    @classmethod
    def _build_command(cls, **kwargs) -> list[str]:
        """Build the full command. Override in subclasses to add prefixes/options."""
        raise NotImplementedError

    @classmethod
    def run(cls, cwd=None, **kwargs) -> str:
        full_command = cls._build_command(**kwargs)
        logging.info(f"Running command {full_command}")

        result = subprocess.run(
            full_command,
            text=True,
            capture_output=True,
            check=False,
            cwd=cwd,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        return result.stdout

    @classmethod
    def run_with_output(cls, output_file: str, cwd=None, **kwargs):
        full_command = cls._build_command(**kwargs)
        logging.info(f"Running command {full_command}")

        # Run the command and stream output
        process = subprocess.Popen(
            full_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            cwd=cwd,
        )

        # Read and display output line by line
        with open(output_file, "w") as f:
            for line in process.stdout:
                print(line, end="")
                f.write(line)  # Print to console
                sys.stdout.flush()  # Force immediate display

        # Wait for the process to complete
        return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(f"Command failed {return_code}")

    @classmethod
    def spawn(cls, **kwargs) -> pexpect.pty_spawn.spawn:
        full_command = cls._build_command(**kwargs)
        return pexpect.spawn(full_command[0], full_command[1:])
