import pytest
from pathlib3x import Path

from kt.ktlib.config import Config

DEFAULT_CONFIG = {"base_path": Path("~/ciq").expanduser()}
CONFIG_STR = (
    "{"
    '"base_path": "~/ciq",'
    '"kernels_dir": "~/ciq/kernels",'
    '"images_source_dir": "~/ciq/default_test_images",'
    '"images_dir": "~/ciq/tmp/virt-images",'
    '"ssh_key": "~/ciq/id_ed25519_generic.pub"'
    "}"
)


def test_config_load_default_fallback():
    config = Config.load()
    assert config.base_path == DEFAULT_CONFIG["base_path"]


def test_config_load_from_filename_None():
    config = Config.from_filename(None)
    assert config.base_path == DEFAULT_CONFIG["base_path"]


@pytest.mark.filterwarnings("ignore", message=r"*using default config")
def test_config_load_from_filename_not_exists():
    config = Config.from_filename("test")
    assert config.base_path == DEFAULT_CONFIG["base_path"]


def test_config_load_from_json_None():
    config = Config.from_json(None)
    assert config.base_path == DEFAULT_CONFIG["base_path"]


@pytest.mark.filterwarnings("ignore", message=r"*using default config")
def test_config_load_from_json_data_None():
    json_data = ""

    config = Config.from_json(json_data)
    assert config.base_path == DEFAULT_CONFIG["base_path"]


def test_config_load_from_json_data_empty():
    json_data = "{}"

    with pytest.raises(TypeError, match="missing 5 required positional arguments:"):
        config = Config.from_json(json_data)  # noqa F841


def test_config_load_from_json_proper_base_path():
    config = Config.from_json(CONFIG_STR)
    assert config.base_path == Path("~/ciq").expanduser()


def test_config_load_from_json_proper_kernels_dir():
    config = Config.from_json(CONFIG_STR)
    assert config.kernels_dir == Path("~/ciq/kernels").expanduser()


def test_config_load_from_json_proper_images_source_dir():
    config = Config.from_json(CONFIG_STR)
    assert config.images_source_dir == Path("~/ciq/default_test_images").expanduser()


def test_config_load_from_json_proper_images_dir():
    config = Config.from_json(CONFIG_STR)
    assert config.images_dir == Path("~/ciq/tmp/virt-images").expanduser()


def test_config_load_from_json_proper_ssh_key():
    config = Config.from_json(CONFIG_STR)
    assert config.ssh_key == Path("~/ciq/id_ed25519_generic.pub").expanduser()
