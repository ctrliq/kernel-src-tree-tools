# ktools

Introduction of kt CLI.

This command is supposed to be the base of all commands used for kernel
development at CIQ.

To keep things clear, it is introduced as a separate module in
kernel-src-tree-tools and it does not interfere with the current tooling.
By keeping this under the same repo, it will be easier to refactor things.

## Setup:

1. Install dependencies globally (you can also create a venv) :
```
$ python -m pip install -e ".[dev]"
```
2. The command above will install pre-commit. To setup the pre-commit tool
before you commit something, run this:
```
$ pre-commit install
```

## Implementation details:

kt/ktlib is the place for common helpers that would be used for kt commands.

kt/ktlib.config.py is where a Config dataclass is implemented. This is crucial
for future commands and for doing the setup of the kernel developer. At the
moment it contains absolute paths to local directories:
- The working dir (the root directory for the setup)
- The directory parent for each kernel directory
- The parent directory where default images are downloaded
- The parent directory where running vm images for each kernel are stored.

Each developer has to  provide their own configuration in json file and keep
the path in KTOOLS_CONFIG_FILE. Otherwise a default one will be used.

Example content of the config file:
```
{
    "base_path": "~/ciq",
    "kernels_dir": "~/ciq/kernels",
    "images_source_dir": "~/ciq/default_test_images",
    "images_dir": "~/ciq/tmp/virt-images",
    "ssh_key": "~/.ssh/id_ed25519_generic.pub",
}
```
