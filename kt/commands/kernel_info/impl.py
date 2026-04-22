import json
from dataclasses import asdict

from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelsInfo


def main(name: str):
    config = Config.load()
    kernels = KernelsInfo.from_yaml(config=config).kernels
    if name not in kernels:
        raise ValueError(f"Invalid param: {name} does not exist")

    kernel_info = kernels[name]
    data = asdict(kernel_info)
    filtered = {k: v for k, v in data.items() if not isinstance(v, dict)}
    print(json.dumps(filtered, indent=2))
