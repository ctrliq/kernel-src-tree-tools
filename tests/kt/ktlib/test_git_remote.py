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
