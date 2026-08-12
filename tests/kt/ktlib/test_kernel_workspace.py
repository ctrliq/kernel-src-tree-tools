import pytest
from git import Repo
from pathlib3x import Path

from kt.ktlib.kernel_workspace import KernelWorkspace, RepoWorktree
from kt.ktlib.util import Constants


@pytest.fixture
def git_topology(tmp_path):
    """
    Build the topology that mirrors production:
      bare_remote  — the "real" upstream (like github.com/ctrliq/kernel-src-tree)
      source_root  — a clone of bare_remote (what `kt setup` creates)
    The kernel branch exists in bare_remote but in source_root only as
    refs/remotes/origin/<branch>.
    """
    tmp_path = Path(str(tmp_path))
    bare_remote = tmp_path / "bare_remote.git"
    Repo.init(str(bare_remote), bare=True)
    bare_repo = Repo(str(bare_remote))

    source_root_path = tmp_path / "source_root"
    source_root_repo = Repo.clone_from(str(bare_remote), str(source_root_path))

    # Create an initial commit on main in source_root, push to bare
    readme = source_root_path / "README"
    readme.write_text("init")
    source_root_repo.index.add(["README"])
    source_root_repo.index.commit("initial commit")
    source_root_repo.remotes.origin.push("HEAD:refs/heads/main")

    # Create the kernel branch on the bare remote directly
    kernel_branch = "ciqcbr7_9"
    bare_repo.git.branch(kernel_branch, "main")

    # Fetch so source_root has origin/ciqcbr7_9
    source_root_repo.remotes.origin.fetch()

    kernels_dir = tmp_path / "kernels"
    kernels_dir.mkdir()

    return {
        "bare_remote": bare_remote,
        "source_root_path": source_root_path,
        "source_root_repo": source_root_repo,
        "kernels_dir": kernels_dir,
        "kernel_branch": kernel_branch,
        "tmp_path": tmp_path,
    }


def _make_repo_worktree(git_topology, folder_name, use_worktree):
    """Helper to create a RepoWorktree with the test topology."""
    folder = git_topology["kernels_dir"] / folder_name
    return RepoWorktree(
        source_root=git_topology["source_root_repo"],
        folder=folder,
        remote="origin",
        remote_branch=git_topology["kernel_branch"],
        local_branch=f"{{testuser}}_{git_topology['kernel_branch']}",
        use_worktree=use_worktree,
    )


# --- detect_repo_disk_mode ---


def test_detect_disk_mode_worktree(git_topology):
    rw = _make_repo_worktree(git_topology, "wt_detect", use_worktree=True)
    rw.setup()
    assert RepoWorktree.detect_repo_disk_mode(rw.folder) is True


def test_detect_disk_mode_clone(git_topology):
    rw = _make_repo_worktree(git_topology, "cl_detect", use_worktree=False)
    rw.setup()
    assert RepoWorktree.detect_repo_disk_mode(rw.folder) is False


def test_detect_disk_mode_nonexistent(tmp_path):
    assert RepoWorktree.detect_repo_disk_mode(Path(str(tmp_path)) / "nope") is None


# --- Clone setup ---


def test_clone_setup_git_dir_is_directory(git_topology):
    rw = _make_repo_worktree(git_topology, "clone_test", use_worktree=False)
    rw.setup()
    git_path = rw.folder / ".git"
    assert git_path.is_dir()


def test_clone_setup_local_branch_tracks_remote(git_topology):
    rw = _make_repo_worktree(git_topology, "clone_track", use_worktree=False)
    rw.setup()
    repo = Repo(str(rw.folder))
    assert repo.active_branch.name == f"{{testuser}}_{git_topology['kernel_branch']}"
    tracking = repo.active_branch.tracking_branch()
    assert tracking is not None
    assert git_topology["kernel_branch"] in str(tracking)


def test_clone_setup_origin_is_real_remote(git_topology):
    rw = _make_repo_worktree(git_topology, "clone_origin", use_worktree=False)
    rw.setup()
    repo = Repo(str(rw.folder))
    origin_url = repo.remotes.origin.url
    assert origin_url == str(git_topology["bare_remote"])


# --- Clone idempotency ---


def test_clone_idempotency_update(git_topology):
    rw = _make_repo_worktree(git_topology, "clone_idem", use_worktree=False)
    rw.setup()

    # Make a new commit on bare remote
    source = git_topology["source_root_repo"]
    readme = git_topology["source_root_path"] / "README"
    readme.write_text("updated")
    source.index.add(["README"])
    source.index.commit("second commit")
    source.remotes.origin.push(f"HEAD:refs/heads/{git_topology['kernel_branch']}")

    # Re-run setup — should update, not error
    rw.setup()
    assert "updated" in (rw.folder / "README").read_text()


# --- Clone cleanup ---


def test_clone_cleanup_removes_folder(git_topology):
    rw = _make_repo_worktree(git_topology, "clone_clean", use_worktree=False)
    rw.setup()
    assert rw.folder.exists()
    rw.cleanup()
    assert not rw.folder.exists()


# --- Clone failure path ---


def test_clone_failure_cleans_up_partial(git_topology):
    rw = _make_repo_worktree(git_topology, "clone_fail", use_worktree=False)
    # Break the remote branch so checkout fails
    rw.remote_branch = "nonexistent_branch"
    with pytest.raises(Exception):  # noqa: B017
        rw.setup()
    # Partial folder should be cleaned up
    assert not rw.folder.exists()


# --- Worktree failure path ---


def test_worktree_failure_cleans_up_partial(git_topology):
    rw = _make_repo_worktree(git_topology, "wt_fail", use_worktree=True)
    rw.remote_branch = "nonexistent_branch"
    with pytest.raises(Exception):  # noqa: B017
        rw.setup()
    assert not rw.folder.exists()


# --- Worktree setup ---


def test_worktree_setup_git_is_file(git_topology):
    rw = _make_repo_worktree(git_topology, "wt_test", use_worktree=True)
    rw.setup()
    git_path = rw.folder / ".git"
    assert git_path.is_file()


def test_worktree_setup_branch_in_source_root(git_topology):
    rw = _make_repo_worktree(git_topology, "wt_branch", use_worktree=True)
    rw.setup()
    branches = [h.name for h in git_topology["source_root_repo"].heads]
    assert rw.local_branch in branches


def test_worktree_cleanup_removes_both(git_topology):
    rw = _make_repo_worktree(git_topology, "wt_clean", use_worktree=True)
    rw.setup()
    assert rw.folder.exists()
    rw.cleanup()
    assert not rw.folder.exists()
    branches = [h.name for h in git_topology["source_root_repo"].heads]
    assert rw.local_branch not in branches


# --- Mode mismatch ---


def test_mode_mismatch_clone_then_worktree(git_topology):
    rw_clone = _make_repo_worktree(git_topology, "mismatch1", use_worktree=False)
    rw_clone.setup()
    rw_wt = _make_repo_worktree(git_topology, "mismatch1", use_worktree=True)
    with pytest.raises(RuntimeError, match="Mode mismatch"):
        rw_wt.setup()


def test_mode_mismatch_worktree_then_clone(git_topology):
    rw_wt = _make_repo_worktree(git_topology, "mismatch2", use_worktree=True)
    rw_wt.setup()
    rw_clone = _make_repo_worktree(git_topology, "mismatch2", use_worktree=False)
    with pytest.raises(RuntimeError, match="Mode mismatch"):
        rw_clone.setup()


# --- load_from_filepath detection ---


def test_load_from_filepath_clone(git_topology):
    rw = _make_repo_worktree(git_topology, "load_clone", use_worktree=False)
    rw.setup()
    loaded = RepoWorktree.load_from_filepath(rw.folder)
    assert loaded.use_worktree is False


def test_load_from_filepath_worktree(git_topology):
    rw = _make_repo_worktree(git_topology, "load_wt", use_worktree=True)
    rw.setup()
    loaded = RepoWorktree.load_from_filepath(rw.folder)
    assert loaded.use_worktree is True


# ===================================================================
# Integration-style tests matching user's requested scenarios
# ===================================================================


def _make_full_workspace(git_topology, name, use_worktree):
    """Build a KernelWorkspace with both dist and src sub-repos."""
    folder = git_topology["kernels_dir"] / name
    branch = git_topology["kernel_branch"]
    source_root = git_topology["source_root_repo"]

    dist_worktree = RepoWorktree(
        source_root=source_root,
        folder=folder / Constants.DIST_TREE,
        remote="origin",
        remote_branch=branch,
        local_branch=f"{{testuser}}_{branch}_dist",
        use_worktree=use_worktree,
    )
    src_worktree = RepoWorktree(
        source_root=source_root,
        folder=folder / Constants.SRC_TREE,
        remote="origin",
        remote_branch=branch,
        local_branch=f"{{testuser}}_{branch}_src",
        use_worktree=use_worktree,
    )
    return KernelWorkspace(
        folder=folder,
        dist_worktree=dist_worktree,
        src_worktree=src_worktree,
    )


# --- cbr-7.9 default (use_worktree: false in yaml) ---


def test_cbr79_default_creates_clones(git_topology):
    ws = _make_full_workspace(git_topology, "cbr-7.9", use_worktree=False)
    ws.setup()

    for sub in [Constants.DIST_TREE, Constants.SRC_TREE]:
        sub_path = ws.folder / sub
        assert sub_path.exists()
        assert (sub_path / ".git").is_dir()

    ws.cleanup()
    assert not ws.folder.exists()


# --- cbr-7.9 --worktree (user explicitly overrides to worktree) ---


def test_cbr79_worktree_override_creates_worktrees(git_topology):
    ws = _make_full_workspace(git_topology, "cbr-7.9-wt", use_worktree=True)
    ws.setup()

    for sub in [Constants.DIST_TREE, Constants.SRC_TREE]:
        sub_path = ws.folder / sub
        assert sub_path.exists()
        assert (sub_path / ".git").is_file()

    ws.cleanup()
    assert not ws.folder.exists()


# --- lts-9.2 default (no use_worktree in yaml -> worktree mode) then checkout again ---


def test_lts92_default_worktree_then_update(git_topology):
    ws = _make_full_workspace(git_topology, "lts-9.2", use_worktree=True)
    ws.setup()

    for sub in [Constants.DIST_TREE, Constants.SRC_TREE]:
        sub_path = ws.folder / sub
        assert sub_path.exists()
        assert (sub_path / ".git").is_file()

    # Second checkout — should update without error
    ws.setup()

    for sub in [Constants.DIST_TREE, Constants.SRC_TREE]:
        sub_path = ws.folder / sub
        assert sub_path.exists()
        assert (sub_path / ".git").is_file()

    ws.cleanup()
    assert not ws.folder.exists()


# --- lts-9.2 --no-worktree then lts-9.2 --worktree (mode switch) ---


def test_lts92_no_worktree_then_worktree_mismatch(git_topology):
    # First checkout with --no-worktree
    ws_clone = _make_full_workspace(git_topology, "lts-9.2-switch", use_worktree=False)
    ws_clone.setup()

    for sub in [Constants.DIST_TREE, Constants.SRC_TREE]:
        sub_path = ws_clone.folder / sub
        assert (sub_path / ".git").is_dir()

    # Second checkout with --worktree — should error on mismatch
    ws_wt = _make_full_workspace(git_topology, "lts-9.2-switch", use_worktree=True)
    with pytest.raises(RuntimeError, match="Mode mismatch"):
        ws_wt.setup()

    # After cleanup + re-checkout, worktree mode works
    ws_clone.cleanup()
    ws_wt.setup()

    for sub in [Constants.DIST_TREE, Constants.SRC_TREE]:
        sub_path = ws_wt.folder / sub
        assert (sub_path / ".git").is_file()

    ws_wt.cleanup()
    assert not ws_wt.folder.exists()
