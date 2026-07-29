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
    '"ssh_key": "~/ciq/id_ed25519_generic.pub",'
    '"user": "testuser"'
    "}"
)


def test_config_load_default_fallback(monkeypatch):
    # Remove the environment variable if it exists when running local tests
    monkeypatch.delenv("KTOOLS_CONFIG_FILE", raising=False)
    config = Config.load()
    assert config.base_path == DEFAULT_CONFIG["base_path"]


def test_config_load_from_filename_None():
    config = Config.from_filename(None)
    assert config.base_path == DEFAULT_CONFIG["base_path"]


@pytest.mark.filterwarnings("ignore", message=r"*using default config")
def test_config_load_from_filename_not_exists():
    config = Config.from_filename("test")
    assert config.base_path == DEFAULT_CONFIG["base_path"]


def test_config_load_from_filename_valid_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(CONFIG_STR)

    config = Config.from_filename(str(config_file))
    assert config.base_path == Path("~/ciq").expanduser()
    assert config.user == "testuser"


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

    with pytest.raises(SystemExit, match="config is missing"):
        Config.from_json(json_data)


def test_config_load_from_json_partial_config_missing_keys():
    json_data = '{"base_path": "~/workspace/kt_pro"}'

    with pytest.raises(SystemExit, match="kernels_dir"):
        Config.from_json(json_data)


def test_config_load_from_json_partial_config_lists_all_missing():
    json_data = '{"base_path": "~/workspace/kt_pro"}'

    with pytest.raises(SystemExit) as exc_info:
        Config.from_json(json_data)

    msg = str(exc_info.value)
    for key in ["images_dir", "images_source_dir", "kernels_dir", "ssh_key"]:
        assert key in msg


def test_config_load_from_json_user_defaults_from_env(monkeypatch):
    monkeypatch.setenv("USER", "testuser")
    json_data = (
        "{"
        '"base_path": "~/ciq",'
        '"kernels_dir": "~/ciq/kernels",'
        '"images_source_dir": "~/ciq/default_test_images",'
        '"images_dir": "~/ciq/tmp/virt-images",'
        '"ssh_key": "~/ciq/id_ed25519_generic.pub"'
        "}"
    )

    config = Config.from_json(json_data)
    assert config.user == "testuser"


def test_config_load_from_str_dict_relative_path_raises():
    data = {
        "base_path": "relative/path",
        "kernels_dir": "~/ciq/kernels",
        "images_source_dir": "~/ciq/default_test_images",
        "images_dir": "~/ciq/tmp/virt-images",
        "ssh_key": "~/ciq/id_ed25519_generic.pub",
        "user": "testuser",
    }

    with pytest.raises(ValueError, match="all paths should be absolute"):
        Config.from_str_dict(data)


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


def test_config_load_from_json_proper_user():
    config = Config.from_json(CONFIG_STR)
    assert config.user == "testuser"
