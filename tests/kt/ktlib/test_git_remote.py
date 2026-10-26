"""Tests for kt.ktlib.git_remote (UpstreamRemotes / GitRemoteInfo)."""

import pytest
from git import Repo
from pathlib3x import Path

from kt.ktlib.git_remote import UpstreamRemotes

UPSTREAM_SOURCES = {
    "kernel-mainline": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git",
    "linux-stable": "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git",
}


@pytest.fixture
def bare_remote(tmp_path):
    """A bare remote with one branch, as a fetch source."""
    bare = tmp_path / "remote.git"
    Repo.init(str(bare), bare=True)

    seed = tmp_path / "seed"
    seed_repo = Repo.init(str(seed))
    with seed_repo.config_writer() as cw:
        cw.set_value("user", "name", "Tester")
        cw.set_value("user", "email", "t@t.com")
    (seed / "file.txt").write_text("content")
    seed_repo.index.add(["file.txt"])
    seed_repo.index.commit("initial commit")
    seed_repo.create_remote("origin", str(bare))
    seed_repo.remotes.origin.push("HEAD:refs/heads/main")

    return bare


@pytest.fixture
def local_repo(tmp_path):
    """A local repo the remote will be added to / fetched into."""
    repo = Repo.init(tmp_path / "local")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Tester")
        cw.set_value("user", "email", "t@t.com")
    (tmp_path / "local" / "readme").write_text("x")
    repo.index.add(["readme"])
    repo.index.commit("init")
    return repo


# --- UpstreamRemotes ---


def test_from_dict_builds_all_remotes():
    remotes = UpstreamRemotes.from_dict(data=UPSTREAM_SOURCES)

    assert set(remotes.remotes.keys()) == set(UPSTREAM_SOURCES.keys())
    for name, url in UPSTREAM_SOURCES.items():
        assert remotes.remotes[name].name == name
        assert remotes.remotes[name].url == url


def test_from_dict_empty():
    remotes = UpstreamRemotes.from_dict(data={})

    assert remotes.remotes == {}


def test_fetch_remote_unknown_name_raises():
    remotes = UpstreamRemotes.from_dict(data=UPSTREAM_SOURCES)

    with pytest.raises(KeyError):
        remotes.fetch_remote(remote_name="does-not-exist", repo_dir=Path("."))


# --- GitRemoteInfo.fetch ---


def test_fetch_creates_remote_and_fetches(local_repo, bare_remote):
    remotes = UpstreamRemotes.from_dict(data={"mainline": str(bare_remote)})

    remotes.fetch_remote(remote_name="mainline", repo_dir=Path(str(local_repo.working_dir)))

    assert "mainline" in [r.name for r in local_repo.remotes]
    assert local_repo.remotes["mainline"].url == str(bare_remote)
    # The fetched branch is visible as a remote ref
    refs = [str(r) for r in local_repo.remotes["mainline"].refs]
    assert any("main" in ref for ref in refs)


def test_fetch_is_idempotent_existing_remote(local_repo, bare_remote):
    """Fetching with the remote already present must not duplicate it."""
    local_repo.create_remote("mainline", str(bare_remote))
    remotes = UpstreamRemotes.from_dict(data={"mainline": str(bare_remote)})

    remotes.fetch_remote(remote_name="mainline", repo_dir=Path(str(local_repo.working_dir)))

    names = [r.name for r in local_repo.remotes]
    assert names.count("mainline") == 1


def test_fetch_warns_on_url_mismatch_existing_remote(local_repo, bare_remote, caplog):
    """If the remote exists pointing elsewhere, fetch proceeds from the
    existing url but logs a warning (never silently rewritten)."""
    import logging

    other = Path(str(bare_remote)).parent / "other.git"
    other_repo = Repo.init(str(other), bare=True)
    # give the other remote an object so fetch has something to do
    seed = Path(str(bare_remote)).parent / "seed_other"
    seed_repo = Repo.init(str(seed))
    (seed / "f.txt").write_text("x")
    seed_repo.index.add(["f.txt"])
    seed_repo.index.commit("c")
    seed_repo.create_remote("origin", str(other))
    seed_repo.remotes.origin.push("HEAD:refs/heads/main")
    del other_repo

    local_repo.create_remote("mainline", str(other))
    remotes = UpstreamRemotes.from_dict(data={"mainline": str(bare_remote)})

    with caplog.at_level(logging.WARNING):
        remotes.fetch_remote(remote_name="mainline", repo_dir=Path(str(local_repo.working_dir)))

    # Remote was NOT rewritten
    assert local_repo.remotes["mainline"].url == str(other)
    assert "different from configured" in caplog.text


# --- UpstreamRemotes.fetch_for_commit_source ---


def _make_source_commit(target, msg="source commit"):
    """Create a commit with a distinct file and return its full sha.

    target may be a work repo (seeded directly) or a bare remote (seeded via
    a temp work repo and pushed), mirroring the bare_remote fixture pattern.
    """
    repo = Repo(str(target))
    if repo.bare:
        seed = Path(str(target)).parent / f"seed_{msg.replace(' ', '_')}"
        seed_repo = Repo.init(str(seed))
        with seed_repo.config_writer() as cw:
            cw.set_value("user", "name", "Tester")
            cw.set_value("user", "email", "t@t.com")
        (seed / "src.txt").write_text(msg)
        seed_repo.index.add(["src.txt"])
        commit = seed_repo.index.commit(msg)
        seed_repo.create_remote("origin", str(target))
        seed_repo.remotes.origin.push(f"HEAD:refs/heads/{msg.split()[0]}")
        return commit.hexsha

    (Path(str(target)) / "src.txt").write_text(msg)
    repo.index.add(["src.txt"])
    return repo.index.commit(msg).hexsha


class TestFetchForCommitSource:
    def test_sha_local_is_noop(self, local_repo):
        """Objects already local -> no fetch, no network."""
        remotes = UpstreamRemotes.from_dict(data={})
        sha = _make_source_commit(local_repo.working_dir)

        # No remotes configured: must still succeed because the sha is local
        remotes.fetch_for_commit_source(
            commit_source="linux-6.12.y", sha=sha, repo_dir=Path(str(local_repo.working_dir))
        )

    def test_remote_name_source_fetches_that_remote(self, local_repo, bare_remote):
        """commit_source matching an upstream_sources.yaml key -> that remote fetched."""
        sha = _make_source_commit(bare_remote, "seedcommit main")
        # sha not local yet: give local_repo a different history
        (Path(str(local_repo.working_dir)) / "other.txt").write_text("x")
        local_repo.index.add(["other.txt"])
        local_repo.index.commit("other")

        remotes = UpstreamRemotes.from_dict(data={"centos-stream-9": str(bare_remote)})
        remotes.fetch_for_commit_source(
            commit_source="centos-stream-9", sha=sha, repo_dir=Path(str(local_repo.working_dir))
        )

        refs = [str(r) for r in local_repo.remotes["centos-stream-9"].refs]
        assert any("main" in ref for ref in refs)
        # sha now resolvable
        local_repo.git.rev_parse("--verify", f"{sha}^{{commit}}")

    def test_branch_source_resolves_and_fetches(self, local_repo, bare_remote):
        """commit_source as a branch name -> ls-remote finds it, remote fetched."""
        sha = _make_source_commit(bare_remote, "linux-6.12.y main")
        remotes = UpstreamRemotes.from_dict(data={"linux-stable": str(bare_remote)})

        remotes.fetch_for_commit_source(
            commit_source="linux-6.12.y", sha=sha, repo_dir=Path(str(local_repo.working_dir))
        )

        assert "linux-stable" in [r.name for r in local_repo.remotes]
        # the branch was fetched and the sha is now resolvable
        refs = [str(r) for r in local_repo.remotes["linux-stable"].refs]
        assert any("linux-6.12.y" in ref for ref in refs)
        local_repo.git.rev_parse("--verify", f"{sha}^{{commit}}")

    def test_branch_source_unknown_branch_raises(self, local_repo, bare_remote):
        remotes = UpstreamRemotes.from_dict(data={"linux-stable": str(bare_remote)})

        with pytest.raises(RuntimeError, match="neither an upstream source"):
            remotes.fetch_for_commit_source(
                commit_source="linux-9.99.y", sha="1" * 40, repo_dir=Path(str(local_repo.working_dir))
            )

    def test_branch_source_no_remotes_configured_raises(self, local_repo):
        remotes = UpstreamRemotes.from_dict(data={})

        with pytest.raises(RuntimeError, match="neither an upstream source"):
            remotes.fetch_for_commit_source(
                commit_source="linux-6.12.y", sha="2" * 40, repo_dir=Path(str(local_repo.working_dir))
            )

    def test_remote_name_preferred_over_branch_resolution(self, local_repo, tmp_path):
        """If commit_source is a yaml key, fetch that remote even if a sha is unknown."""
        url = str(tmp_path / "c9.git")
        Repo.init(url, bare=True)
        remotes = UpstreamRemotes.from_dict(data={"centos-stream-9": url})

        # Unknown sha: the fetch happens (fetch of an empty remote succeeds and
        # the subsequent rev-parse would fail - but fetch_for_commit_source's
        # contract is "fetch the remote", not "guarantee the sha").
        remotes.fetch_for_commit_source(
            commit_source="centos-stream-9", sha="3" * 40, repo_dir=Path(str(local_repo.working_dir))
        )

        assert "centos-stream-9" in [r.name for r in local_repo.remotes]
