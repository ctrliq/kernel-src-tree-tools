import json
import os
import warnings
from dataclasses import dataclass
from typing import ClassVar, Optional

from pathlib3x import Path

CONFIG_FILE_ENV_VAR = "KTOOLS_CONFIG_FILE"


@dataclass
class Config:
    """
    Config dataclass that contains the basic paths for each kernel
    developer setup.

    base_path   The working directory for developers
    kernels_dir The directory where each kernel working dir will be created
    images_source_dir The directory where the default images will be
                        downloaded
    images_dir The directory where the vm images for each kernel will be
                        stored
    ssh_key: Path to the ssh key (public) shared between host and each vms

    All paths should be absolute, to avoid issues later.
    """

    base_path: Path
    kernels_dir: Path
    images_source_dir: Path
    images_dir: Path

    ssh_key: Path
    user: str

    DEFAULT: ClassVar = {
        "base_path": "~/ciq",
        "kernels_dir": "~/ciq/kernels",
        "images_source_dir": "~/ciq/default_test_images",
        "images_dir": "~/ciq/tmp/virt-images",
        "ssh_key": "~/.ssh/id_ed25519_generic.pub",
        "user": os.environ["USER"],
    }

    @classmethod
    def from_str_dict(cls, data: dict[str, str]):
        # Transform the str values to Path except for user
        non_path_keys = {"user"}
        new_data = {k: (Path(v).expanduser() if k not in non_path_keys else v) for k, v in data.items()}
        if not all(v.is_absolute() for k, v in new_data.items() if k not in non_path_keys):
            raise ValueError("all paths should be absolute; check your config")

        return cls(**new_data)

    @classmethod
    def load(cls):
        """Load the default configuration.

        The configuration is loaded in this order from:

        1. The filename provided in KTOOLS_CONFIG_FILE env var;
            filename type is a json file
        2. The default configuration

        """

        filename = os.getenv(CONFIG_FILE_ENV_VAR, None)
        return cls.from_filename(filename)

    @classmethod
    def from_filename(cls, filename: Optional[str]):
        """Load config from filename"""

        if filename is None:
            return cls.from_str_dict(cls.DEFAULT)

        if not os.path.exists(filename):
            warnings.warn(f"{filename} does not exist, using default config.")
            return cls.from_str_dict(cls.DEFAULT)

        with open(filename) as jfd:
            json_data = jfd.read()

        return cls.from_json(json_data)

    @classmethod
    def from_json(cls, json_data: Optional[str]):
        if json_data is None:
            return cls.from_str_dict(cls.DEFAULT)

        try:
            data = json.loads(json_data)
        except ValueError:
            warnings.warn("Invalid configuration, using default config.")
            data = dict(cls.DEFAULT)

        return cls.from_str_dict(data)
