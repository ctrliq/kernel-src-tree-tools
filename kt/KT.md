# ktools

Introduction of kt CLI.

This command is supposed to be the base of all commands used for kernel
development at CIQ.

To keep things clear, it is introduced as a separate module in
kernel-src-tree-tools and it does not interfere with the current tooling.
By keeping this under the same repo, it will be easier to refactor things.

## Setup:

1. Install dependencies globally (you can also create a venv) in the repository
root directory:
```
[kernel-src-tree-tools]$ python -m pip install -e ".[dev]"
```
2. The command above will install pre-commit. To setup the pre-commit tool
before you commit something, run this:
```
[kernel-src-tree-tools]$ pre-commit install
```

3. Set up the configuration file for kt.
There is a default one in kt/data/config.json but you can create your own by
defining the KTOOLS_CONFIG_FILE environment variable to point to your own config
file.
```bash
$ echo $KTOOLS_CONFIG_FILE
/home/jmaple/.config/kt/test_config.json

(.venv) [jmaple@devbox kernel-src-tree-tools]$ cat $KTOOLS_CONFIG_FILE
{
  "base_path": "~/workspace/kt_test",
  "kernels_dir": "~/workspace/kt_test/kernels",
  "images_source_dir": "~/workspace/kt_test/images_source",
  "images_dir": "~/workspace/kt_test/images",
  "ssh_key": "~/.ssh/test.pub",
  "user": "USER"
}
```
user defaults to $USER, set this if you wish for your user on the VMs to be
different than the default.

4. Private Repos
By default, kt will use the public repos defined in kt/data/kernels.yaml. If
you have access to our private repos, you can create a .private_repos.yaml in
the base_path directory and define the private repos and branches should they
differ from the public ones. For example:
```yaml
private_repos:
    dist-git-tree-lts: <gitlab_private_repo_url>

kernel_overrides:
    lts-9.2:
        dist_git_branch: <private_branch>
        dist_git_root: dist-git-tree-lts
```

Optional is if you have an active depot account you can define the channels you
wish to use for each kernel. For example:
```yaml
kernel_overrides:
    lts-9.2:
        dist_git_branch: <private_branch>
        dist_git_root: dist-git-tree-lts
        depot_channels:
            - <channel_name>
```

5. Setup needs to be run first.
```bash
$ kt setup
```
### Disable Worktrees
By default, kt will use git worktrees to checkout the kernel source and
appropriate dist-git repo. If you don't want to use worktrees you have several
options.  Each option below will override the previous one, so if you turn off
worktrees at the kt config level you can turn them on for specific kernels later
by setting in the .private_repos.yaml or on the command line.

NOTE: By default CentOS7 worktree is turned off due to git inside the CentOS7
VM is too old to support worktrees.  You can enable it if you want, but note
that this is a limitation of the VM.

1. Set the global config variable.
```bash
{
  "base_path": "~/workspace/kt_test",
  "kernels_dir": "~/workspace/kt_test/kernels",
  "images_source_dir": "~/workspace/kt_test/images_source",
  "images_dir": "~/workspace/kt_test/images",
  "ssh_key": "~/.ssh/test.pub",
  "user": "USER",
  "use_worktrees": false
}
```

2. Set the per kernel config in the .private_repos.yaml file.
```yaml
kernel_overrides:
    lts-9.2:
        dist_git_branch: <private_branch>
        dist_git_root: dist-git-tree-lts
        use_worktree: false
```

3. CLI command line override. This will override the global and per kernel
config.  However you will need to use this option for every command that uses
every time for that kernel version.
```bash
$ kt checkout lts-9.2 --no-worktree
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

Kt is now installed when kernel-src-tree-tools is installed, no need
to do anything extra.

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
$ kt checkout lts-9.2
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
`~/ciq/kernels/lts-9.2`.

2 git worktrees are created:

1. kernel-dist-git

    This representes branch `{<user>}/lts9.2:origin/lts9.2`.
    The source repo is ~/ciq/dist-git-tree-lts

2. kernel-src-tree

    This representes branch `{<user>}/ciqlts9.2:origin/ciqlts9.2`
    The source repo is ~/ciq/kernel-src-tree

### kt vm

It spins up a virtual machine for the corresponding kernel.
If the virtual machine does not exist, it gets created.

First, the vm image base (source) is downloaded if it does not exist
in <config.images_source_dir>.
To spin up the machine, a copy of this qcow2 image is put in
<config.images_dir/<kernel>. Even if kernels may share the same image base,
they will have their own configuration and image.
cloud-init.yaml configuration is taken from kt/data and modified accordingly
for each user and then put in the same folder.

Make sure your user is part of the libvirt group, otherwise you would need
to type your root password multiple times when getting access to the vm:
```
$ sudo usermod -a -G libvirt $(whoami)
```

#### Example:
```
$ kt vm lts-9.2
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

Here is the qcow2 vm image used as source for other vms for 9.2 kernels as well:

```
~/ciq/default_test_images/Rocky-9.2-GenericCloud.latest.x86_64.qcow2
```

And here are the actual vm configuration and image files:
```
ciq/tmp/virt-images/lts-9.2/cloud-init.yaml
ciq/tmp/virt-images/lts-9.2/lts-9.2.qcow2
```

The cloud-init.yaml file is adapted from kt/data/cloud-init.yaml base file.

`virt-install` command is then used to create the vm.

If `--console` option is used, then `virsh --connect qemu://system console lts9.2`
is run (indirectly).


If `--test` option is used, then we connect to the vm via ssh and run

```
<config.base_path>/kernel-src-tree-tools/kernel-build.sh -n
```

reboot
and then

```
<config.base_path>/kernel-src-tree-tools/kernel-kselftest.sh
```

### kt content-release

Manages the complete content release workflow for kernel packages. This command
automates the process of preparing, building, and testing kernel releases.

The command has three steps that can be run individually or all together:

#### --prepare
Prepares the content release by:
- Validating git user.name and user.email are configured
- Running mkdistgitdiff.py to generate the staging branch and release files
- Checking out the staging branch {automation_tmp}_<src_branch>
- Creating and displaying the new release tag

#### --build
Builds kernel RPMs by:
- Verifying mock is installed and user is in mock group
- Checking DEPOT_USER and DEPOT_TOKEN environment variables are set
- Creating a temporary mock config with depot credentials
- Downloading sources using getsrc.sh
- Building SRPM with mock
- Building binary RPMs from the SRPM
- Listing all created RPMs

Requirements:
- mock must be installed
- User must be in the mock group
- DEPOT_USER and DEPOT_TOKEN environment variables must be set

#### --test
Tests the built kernel by:
- Spinning up a VM (creates if needed, boots if stopped)
- Installing the built kernel RPMs from build_files
- Rebooting the VM
- Running kselftests using /usr/libexec/kselftests/run_kselftest.sh
- Reporting number of tests passed

Output logs:
- install.log: RPM installation output
- selftest-<kernel_version>.log: Kselftest results

#### Example:

Run all steps:
```
$ DEPOT_USER=user@example.com DEPOT_TOKEN=token kt content-release lts-9.2
```

Run individual steps:
```
$ kt content-release lts-9.2 --prepare
$ DEPOT_USER=user@example.com DEPOT_TOKEN=token kt content-release lts-9.2 --build
$ kt content-release lts-9.2 --test
```
