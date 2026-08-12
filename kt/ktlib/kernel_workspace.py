import logging
from dataclasses import dataclass

from git import GitCommandError, Repo
from pathlib3x import Path

from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelInfo
from kt.ktlib.util import Constants


@dataclass
class RepoWorktree:
    source_root: Repo
    folder: Path
    remote: str
    remote_branch: str
    local_branch: str
    use_worktree: bool = True

    @classmethod
    def load_from_filepath(cls, folder: Path):
        if not folder.exists():
            raise RuntimeError(f"{folder} does not exist")

        # check if folder is a git repo
        repo = Repo(folder)

        source_root = Path(repo.git.rev_parse("--path-format=absolute", "--git-common-dir")).parent
        remote = repo.remotes.origin

        remote_branch = repo.active_branch.tracking_branch()

        local_branch = repo.active_branch.name

        return cls(
            source_root=source_root,
            folder=folder,
            remote=remote,
            remote_branch=remote_branch,
            local_branch=local_branch,
            use_worktree=(folder / ".git").is_file(),
        )

    @staticmethod
    def detect_repo_disk_mode(directory) -> bool | None:
        """
        Static method to work out if a .git exists in directory.
        If the .git is a file its a part of a worktree representation
        else a directory is a pure clone.
        Return
          True  - Git WorkTree
          False - Git Clone Repo
          None  - NOT a git repo
        """
        git_path = directory / ".git"
        if git_path.is_file():
            return True
        if git_path.is_dir():
            return False
        return None

    def setup(self):
        """
        First run: It will create the worktree / clone
        Second run: It will update the worktree / clone
        """

        if self.folder.exists():
            disk_mode = self.detect_repo_disk_mode(self.folder)
            if disk_mode is None or disk_mode != self.use_worktree:
                disk_label = "worktree" if disk_mode else "clone" if disk_mode is False else "unknown"
                requested_label = "worktree" if self.use_worktree else "clone"
                raise RuntimeError(
                    f"Mode mismatch for {self.folder}:\n"
                    f"  On disk: {disk_label}\n"
                    f"  Requested: {requested_label}\n"
                    "To switch modes, clean up first then re-checkout:\n"
                    f"  kt checkout <kernel> --cleanup\n"
                    f"  kt checkout <kernel> --{'worktree' if self.use_worktree else 'no-worktree'}"
                )
            self.update()
            return
        self._setup_worktree() if self.use_worktree else self._setup_clone()

    def _setup_worktree(self):
        try:
            remote_ref = f"{self.remote}/{self.remote_branch}"
            self.source_root.git.worktree(
                "add",
                "--track",
                "-b",
                self.local_branch,
                self.folder,
                remote_ref,
            )

        except GitCommandError as e:
            if "already exists" in e.stderr:
                self.update()
            else:
                # Make sure the worktree is properly cleaned up
                self.cleanup()
                raise e

    def _setup_clone(self):
        try:
            logging.info(f"Cloning Full Repo {self.source_root.remotes.origin.url} to {self.folder}")
            repo = Repo.clone_from(url=self.source_root.remotes.origin.url, to_path=self.folder, no_checkout=True)
            repo_ref = f"origin/{self.remote_branch}"
            logging.info(f"Checking out {self.local_branch} tracking to {repo_ref}")
            repo.git.checkout("-b", self.local_branch, "--track", repo_ref)

        except GitCommandError as e:
            self.cleanup()
            raise e

    def update(self):
        """
        It will make sure the worktree is up-to-date with remote.
        It assumes the worktree is already created and initialized.
        """
        logging.info("update")
        repo = Repo(self.folder)

        repo.remotes.origin.pull(rebase=True)

    def cleanup(self):
        disk_mode = self.detect_repo_disk_mode(self.folder)
        if disk_mode is True:
            self._cleanup_worktree()
            return

        logging.info(f"Removing Local Clone for {self.folder}")
        self.folder.rmtree(ignore_errors=True)

    def _cleanup_worktree(self):
        # remove worktree, only if it exists
        try:
            self.source_root.git.worktree("remove", self.folder, "-f")
        except GitCommandError as e:
            if f"'{self.folder}' is not a working tree" not in e.stderr:
                raise e

        # remove local branch, only if it exists
        try:
            self.source_root.delete_head(self.local_branch, force=True)
        except GitCommandError as e:
            if f"branch '{self.local_branch}' not found" not in e.stderr:
                raise e

    def push(self, force: bool = False):
        repo = Repo(self.folder)
        origin = repo.remote(name=self.remote)
        args = ["--set-upstream", origin.name, self.local_branch]
        if force:
            args.append("--force-with-lease")

        repo.git.push(*args)

    def check_git_config_value(self, section, option):
        """
        Get a git config value from repo or global config.

        Args:
            section: Config section (e.g., 'user')
            option: Config option (e.g., 'name')

        Returns:
            The config value, or None if not found
        """
        repo = Repo(self.folder)
        try:
            # Try repo-specific config first
            return repo.config_reader().get_value(section, option)
        except Exception:
            pass

        try:
            # Fall back to global config
            return repo.config_reader("global").get_value(section, option)
        except Exception:
            return None


@dataclass
class KernelWorkspace:
    folder: Path
    dist_worktree: RepoWorktree
    src_worktree: RepoWorktree

    @classmethod
    def load_from_filepath(cls, folder: Path):
        if not folder.exists():
            raise RuntimeError(f"{folder} does not exists")

        ## Get the dist-git-tree path
        dist_worktree_path = folder / Constants.DIST_TREE
        dist_worktree = RepoWorktree.load_from_filepath(folder=dist_worktree_path)

        src_worktree_path = folder / Constants.SRC_TREE
        src_worktree = RepoWorktree.load_from_filepath(folder=src_worktree_path)

        return cls(
            folder=folder,
            dist_worktree=dist_worktree,
            src_worktree=src_worktree,
        )

    @classmethod
    def load_from_name(cls, kernel_workspace_name: str):
        """
        Load a kernel workspace by name.

        Args:
            kernel_workspace_name: The name of the kernel workspace (e.g., 'lts-9.2')

        Returns:
            KernelWorkspace
        """
        config = Config.load()
        kernel_workpath = config.kernels_dir / kernel_workspace_name
        workspace = cls.load_from_filepath(folder=kernel_workpath)
        return workspace

    @classmethod
    def load(cls, name: str, config: Config, kernel_info: KernelInfo, use_worktree: bool, extra: str):
        if extra:
            name = name + "_" + extra

        folder = config.kernels_dir / Path(name)
        user = config.user
        default_remote = "origin"

        dist_folder = folder / Path(Constants.DIST_TREE)
        dist_local_branch = f"{{{user}}}_{kernel_info.dist_git_branch}"
        if extra:
            dist_local_branch += f"_{extra}"

        dist_worktree = RepoWorktree(
            source_root=Repo(kernel_info.dist_git_root.folder),
            folder=dist_folder,
            remote=default_remote,
            remote_branch=kernel_info.dist_git_branch,
            local_branch=dist_local_branch,
            use_worktree=use_worktree,
        )

        src_folder = folder / Path(Constants.SRC_TREE)
        src_local_branch = f"{{{user}}}_{kernel_info.src_tree_branch}"
        if extra:
            src_local_branch += f"_{extra}"

        src_worktree = RepoWorktree(
            source_root=Repo(kernel_info.src_tree_root.folder),
            folder=src_folder,
            remote=default_remote,
            remote_branch=kernel_info.src_tree_branch,
            local_branch=src_local_branch,
            use_worktree=use_worktree,
        )

        return cls(
            folder=folder,
            dist_worktree=dist_worktree,
            src_worktree=src_worktree,
        )

    def setup(self):
        # Make sure the folder is created
        self.folder.mkdir(parents=True, exist_ok=True)

        self.dist_worktree.setup()
        self.src_worktree.setup()

    def cleanup(self):
        self.dist_worktree.cleanup()
        self.src_worktree.cleanup()

        # Remove working directory that includes the above git worktrees
        self.folder.rmtree(ignore_errors=True)
