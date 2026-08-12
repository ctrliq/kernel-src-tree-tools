import logging
import os
import shutil

from kt.ktlib.config import Config
from kt.ktlib.kernel_workspace import KernelWorkspace
from kt.ktlib.kernels import KernelsInfo


def main(name: str, change_dir: bool, cleanup: bool, override: bool, use_worktree: bool | None, extra: str):
    config = Config.load()
    kernels = KernelsInfo.from_yaml(config=config).kernels
    if name not in kernels:
        raise ValueError(f"Invalid param: {name} does not exist")

    kernel_info = kernels[name]
    resolved = kernel_info.should_use_worktree(config=config, cli_value=use_worktree)
    kernel_workspace = KernelWorkspace.load(
        name=name, config=config, kernel_info=kernel_info, use_worktree=resolved, extra=extra
    )
    if cleanup:
        kernel_workspace.cleanup()
        return

    if override:
        kernel_workspace.cleanup()

    kernel_workspace.setup()
    if change_dir:
        shell_exec = os.environ["SHELL"]
        if not shutil.which(shell_exec):
            raise Exception(f"No executable {shell_exec}; cannot start a new one")

        logging.info(f"Changing directory to {kernel_workspace.folder}")
        os.chdir(kernel_workspace.folder)
        os.execve(shell_exec, [shell_exec], os.environ)
