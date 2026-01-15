import logging

from kt.ktlib.config import Config
from kt.ktlib.kernel_workspace import KernelWorkspace


def main(name: str, kernel_source: bool, dist_git: bool, force: bool):
    config = Config.load()
    kernel_workpath = config.kernels_dir / name
    kernel_workspace = KernelWorkspace.load_from_filepath(folder=kernel_workpath)

    if kernel_source:
        kernel_workspace.src_worktree.push(force=force)
    elif dist_git:
        kernel_workspace.dist_worktree.push(force)
    else:
        logging.error("You need to specify the repo you want to push")
