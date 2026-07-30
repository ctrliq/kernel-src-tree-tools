from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelsInfo


def main(automated: bool = False):
    config = Config.load()
    kernels = KernelsInfo.from_yaml(config=config).kernels

    for k in sorted(kernels.values(), key=lambda k: k.name):
        if not automated or k.automated:
            label = f"{k.name} (override)" if k.overridden else f"{k.name} (default)"
            print(label)
