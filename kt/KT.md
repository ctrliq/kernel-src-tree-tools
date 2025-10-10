# ktools

Introduction of kt CLI.

This command is supposed to be the base of all commands used for kernel
development at CIQ.

To keep things clear, it is introduced as a separate module in
kernel-src-tree-tools and it does not interfere with the current tooling.
By keeping this under the same repo, it will be easier to refactor things.

Steps:
1. Install dependencies globally (you can also create a venv) :
```
$ python -m pip install -e ".[dev]"
```
2. The command above will install pre-commit. To run the pre-commit tool
before you commit something, run this:
```
$ pre-commit install
```
