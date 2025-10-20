from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelsInfo


def main():
    config = Config.load()
    kernels = KernelsInfo.from_yaml(config=config).kernels
    for k in sorted(kernels):
        print(k)
