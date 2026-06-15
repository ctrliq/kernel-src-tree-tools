from dataclasses import dataclass

import yaml
from git import Repo
from pathlib3x import Path

UPSTREAM_SOURCE_FILEPATH = Path(__file__).parent.parent.parent.joinpath("upstream_sources.yaml")


@dataclass
class GitRemoteInfo:
    """
    Dataclass that a git remote
    name: name of remote
    url: url from where we can fetch the remote
    """

    name: str
    url: str

    def _add_remote(self, repo_dir: Path = "."):
        """Adds remote in repo_dir"""
        repo = Repo(repo_dir)
        repo.create_remote(name=self.name, url=self.url)

    def fetch(self, repo_dir: Path = "."):
        """
        Fetch remote repo_dir.
        """
        repo = Repo(repo_dir)
        if self.name not in repo.remotes:
            self._add_remote(repo_dir=repo_dir)

        remote = repo.remotes[self.name]
        remote.fetch()

    # TODO fetch that is not full, depth=1 or sth else??


@dataclass
class UpstreamRemotes:
    remotes: dict[str, GitRemoteInfo]

    @classmethod
    def from_yaml(cls):
        data = None

        with open(UPSTREAM_SOURCE_FILEPATH) as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data=data)

    @classmethod
    def from_dict(cls, data: dict):
        remotes_dict = {}
        for name, url in data.items():
            git_remote_info = GitRemoteInfo(name=name, url=url)
            remotes_dict[name] = git_remote_info

        return cls(remotes=remotes_dict)

    def fetch_remote(self, remote_name: str, repo_dir: Path):
        git_remote_info = self.remotes[remote_name]
        git_remote_info.fetch(repo_dir=repo_dir)
