import logging
from dataclasses import dataclass

import git
from git import Repo
from pathlib3x import Path


class RepoInfoException(Exception):
    pass


@dataclass
class RepoInfo:
    """
    Dataclass that represents a local clone of a git repository.
    folder: absolute path to the local clone
    url: remote origin
    """

    folder: Path
    url: str

    def _clone_repo(self):
        """
        It clones the repo into destination folder
        """

        # TODO show progress
        logging.info(f"Cloning {self.url} to {self.folder}")
        git.Repo.clone_from(self.url, self.folder)

    def _update(self):
        repo = Repo(self.folder)
        repo.remotes.origin.pull(rebase=True)

    def setup_repo(self):
        """
        Set up a git repository at the destination.
        If destination already exists and override == True,
        nothing is done
        """

        if not self.folder.exists():
            try:
                self._clone_repo()
            except git.GitCommandError as e:
                raise RepoInfoException(f"{self.folder.name} could not be cloned") from e

            return

        logging.info(f"{self.folder} already exists, updating it")
        try:
            self._update()
        except git.GitCommandError as e:
            raise RepoInfoException(f"{self.folder.name} could not be updated") from e
