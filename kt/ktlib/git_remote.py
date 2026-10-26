from dataclasses import dataclass
import logging

import yaml
from git import Repo
from git.exc import GitCommandError
from pathlib3x import Path

UPSTREAM_SOURCE_FILEPATH = Path(__file__).parent.parent.parent.joinpath("upstream_sources.yaml")


def _sha_in_local_repo(repo_dir: Path, sha: str) -> bool:
    """True if sha resolves to a commit object in the local repository."""
    try:
        result = Repo(repo_dir).git.rev_parse("--verify", "--quiet", f"{sha}^{{commit}}")
        return bool(result)
    except GitCommandError:
        return False


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
        if remote.url != self.url:
            # Fetch from the existing url; never silently rewrite remotes the
            # user already configured.
            logging.warning(
                f"remote '{self.name}' exists with url {remote.url}, "
                f"different from configured {self.url}; fetching from the existing url"
            )
        remote.fetch()


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

    def fetch_for_commit_source(self, commit_source: str, sha: str, repo_dir: Path):
        """Ensure the objects for commit_source/commit_source_sha are available locally.

        commit_source is a provenance label from a commit header's `commit-source`
        tag and can be either:
          - a remote name configured in upstream_sources.yaml (e.g. "centos-stream-9"),
          - or a branch name (e.g. "linux-6.12.y") carried by one of the configured
            remotes.

        Resolution order:
          1. sha already resolvable locally -> no-op (no network).
          2. commit_source is an upstream_sources.yaml key -> fetch that remote.
          3. commit_source is a branch -> ls-remote the configured remotes (ref
             query only, no objects) and fetch the first one carrying
             refs/heads/<branch>.
          4. Otherwise raise RuntimeError.

        Raises:
            RuntimeError: if commit_source cannot be resolved to a remote.
        """
        # 1. Fast path: objects are already local.
        if _sha_in_local_repo(repo_dir=repo_dir, sha=sha):
            return

        # 2. Remote-name provenance (upstream_sources.yaml key).
        if commit_source in self.remotes:
            self.fetch_remote(remote_name=commit_source, repo_dir=repo_dir)
            return

        # 3. Branch-style provenance: find a configured remote carrying the branch.
        for git_remote_info in self.remotes.values():
            ls = Repo(repo_dir).git.ls_remote(git_remote_info.url, f"refs/heads/{commit_source}")
            if ls.strip():
                logging.info(f"branch {commit_source} found on remote {git_remote_info.name}, fetching")
                git_remote_info.fetch(repo_dir=repo_dir)
                return

        raise RuntimeError(
            f"commit-source '{commit_source}' is neither an upstream source "
            f"({list(self.remotes.keys())}) nor a branch on any of them; "
            f"and sha {sha} is not available locally. "
            f"Fetch the branch manually and retry."
        )
