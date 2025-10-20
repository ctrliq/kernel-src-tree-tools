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

kt/ktlib/kernels.py is the python representation of the kernels.yaml
in kt/data folder. This should be the only source of truth for the kernels
we currently maintain. Ideally, this should be in its own repo, but to keep
things simple, it is part of the kt tool for the time being.


The information we store for each kernel is:
- the kernel source tree (at the moment is the same for all)
- the corresponding branch in the kernel source tree
- the rocky staging rpm repo ( it can be lts, fips or cbr)
- the corresponding branch in the rocky staging rpm repo as we support
multiple lts and fips kernels

For example
```
kernels:
  fips-9.2:
    src_tree_root: kernel-src-tree
    src_tree_branch: fips-9-compliant/5.14.0-284.30.1
    dist_git_root: dist-git-tree-fips
    dist_git_branch: el92-fips-compliant-9
```

src_tree_root and dist_git_root are references to:

```
common_repos:
    dist-git-tree-fips: git@gitlab.com:ctrl-iq-public/fips/src/kernel.git
    kernel-src-tree: https://github.com/ctrliq/kernel-src-tree.git
```

NOTE:
Lts kernel and cbr reference `dist-git-tree-lts` and `dist-git-tree-cbr` that
are taken from a local config file in `<config.base_dir>/.private_repos.yaml`

A python dataclass KernelInfo that matches every kernel configuration is
introduced in kt/ktlib/kernels.py. The dataclass contains the absolute
path to the local clone of the repos, to make future work easier. And we
keep track of all kernels in KernelsInfo.

For example, based on the default configuration, the KernelInfo object for the above kernel
will contain the following:
```
- name: fips-9.2
- src_tree_root: RepoInfo(~/ciq/kernel-src-tree, https://github.com/ctrliq/kernel-src-tree.git)
- src_tree_branch: fips-9-compliant/5.14.0-284.30.1
- dist_git_root: RepoInfo(~/ciq/dist-git-tree-fips, git@gitlab.com:ctrl-iq-public/fips/src/kernel.git)
- dist_git_branch: el92-fips-compliant-9
```
if the base_path is ~/ciq.

The KernelInfo dataclass will be used later when we set up each kernel working
environment.

## Commands

Make sure kt is reachable from anywhere by adding it's location to PATH.
Example
```
export PATH=$HOME/ciq/kernel-src-tree-tools/bin:$PATH
```
If you are unsure how to use kt, just run it with --help.
Example:
```
$ kt --help
```

Run --help for subcommands as well.

Autocompletion works relatively well. Make sure it's enabled for your shell.
Check the official doc for [click](https://click.palletsprojects.com/en/stable/shell-completion/#enabling-completion)
Example for zsh:
```
eval "$(_KT_COMPLETE=zsh_source kt)"
```

A command implementation is under ```kt/commands/<command>``` folder.
To keep things cleaner, the actual logic is done in impl.py,
while command.py is used for the click interface, like argument and helper logic.

### kt list-kernels
It shows the kernels we currently maintain. The data is taken from
KernelsInfo object which represents the kernels.yaml file in kt/data.

Example:

```
$ kt list-kernels
cbr-7.9
fips-8.10
fips-8.6
fips-9.2
fipslegacy-8.6
lts-8.6
lts-8.8
lts-9.2
lts-9.4
```

### kt setup

```
$ kt setup --help
```

It prepares the working directory for later commands:

It clones the common_repos from kernels.yaml file in the config.base_path
directory.
If config.base_path = ~/ciq, these will be created:

~/ciq/kernel-src-tree

~/ciq/dist-git-tree-fips

~/ciq/dist-git-tree-cbr

~/ciq/dit-git-tree-lts

~/ciq/kernel-src-tree-tools

~/ciq/kernel-tools

If there's a repo that needs to be cloned relevant for any future command,
this is when it should be cloned.

### kt checkout
Prepares the working directory for a kernel.
It uses the KernelInfo dataclass created based on the kernels.yaml file.

The working directory location is based on configuration:
`<config.kernels_dir>/<kernel>/`

2 git worktrees are created for a kernel:

- kernel-dist-git

- kernel-src-tree

They will point out to their root sources. Check kt setup for more info.
They should be located in <config.base_path>.
The worktrees reference the remote <branch> from kernels.yaml.
The local branch is `{<user>}/<branch>`.

If `--change-dir` or `-c` option is used, it will also go to the working
directory of the kernel.

If `--cleanup` option is used, it will delete the worktree and the local branch
before creating it from scratch again.

#### Example:
```
$ kt checkout lts9_4
```

For this configuration
```
{
    "base_path": "~/ciq",
    "kernels_dir": "~/ciq/kernels",
    "images_source_dir": "~/ciq/default_test_images",
    "images_dir": "~/ciq/tmp/virt-images",
    "ssh_key": "~/.ssh/id_ed25519_generic.pub",
}
```

This is the working directory for this kernel:
`~/ciq/kernels/lts9_4`.

2 git worktrees are created:

1. kernel-dist-git

    This representes branch `{<user>}/lts9_4:origin/lts9_4`.
    The source repo is ~/ciq/dist-git-tree-lts

2. kernel-src-tree

    This representes branch `{<user>}/ciqlts9_4:origin/ciqlts9_4`
    The source repo is ~/ciq/kernel-src-tree
