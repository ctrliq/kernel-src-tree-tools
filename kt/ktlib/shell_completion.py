from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelsInfo


class ShellCompletion:
    @classmethod
    def show_kernels(cls, ctx, param, incomplete):
        config = Config.load()
        kernels = KernelsInfo.from_yaml(config=config).kernels

        return [kernel for kernel in kernels if kernel.startswith(incomplete)]

    @classmethod
    def show_kernel_workspaces(cls, ctx, param, incomplete):
        config = Config.load()

        # Since the current tooling uses a bunch of relative paths, we may have other dirs in the kernels directory.
        # Therefore, an extra check is required to make sure the kernel workspaces are the one recommended
        kernels = KernelsInfo.from_yaml(config=config).kernels.keys()

        kernel_workspaces = [
            kernel_workspace.name
            for kernel_workspace in config.kernels_dir.iterdir()
            if kernel_workspace.is_dir() and kernel_workspace.name.split("_")[0] in kernels
        ]

        return [kernel_workspace for kernel_workspace in kernel_workspaces if kernel_workspace.startswith(incomplete)]
