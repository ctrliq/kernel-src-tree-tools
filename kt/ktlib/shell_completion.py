from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelsInfo


class ShellCompletion:
    @classmethod
    def show_kernels(cls, ctx, param, incomplete):
        config = Config.load()
        kernels = KernelsInfo.from_yaml(config=config).kernels

        return [kernel for kernel in kernels if kernel.startswith(incomplete)]
