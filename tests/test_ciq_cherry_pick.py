"""Tests for ciq-cherry-pick.py ({rnicolescu}_commit_source CherryPickCommand API).

Imports the module via importlib (hyphenated filename, module-level
git.Repo(os.getcwd()) call) against temporary git repos. Commit data in the
fixtures mirrors real backports (drm/xe, KVM, net/sched) from ctrliq/kernel-src-tree.
"""

import argparse
import importlib.util
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import git
import pytest

from kt.ktlib.commit_header import CommitHeader

SCRIPT_PATH = str(Path(__file__).resolve().parent.parent / "ciq-cherry-pick.py")

JIRA_ENV_VARS = ["JIRA_URL", "JIRA_API_USER", "JIRA_API_TOKEN", "KERNEL_JIRA_API_USER", "KERNEL_JIRA_API_KEY"]


def make_args(**overrides):
    """argparse.Namespace matching ciq-cherry-pick.py's parser."""
    defaults = dict(
        commit=None,
        jira=None,
        ciq_tag=None,
        upstream_ref="origin/kernel-mainline",
        commit_source=None,
        commit_source_sha=None,
        ignore_fixes_check=False,
        pick_fixes=False,
        jira_url=None,
        jira_user=None,
        jira_key=None,
        jira_dry_run=False,
        vulns_dir="../vulns",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def cherry_pick_env(tmp_path, monkeypatch):
    """Create a git repo, chdir into it, and import ciq-cherry-pick.py.

    Returns (module, repo, tmp_path).
    """
    # The ambient environment may carry real JIRA credentials; the command
    # would construct a live JiraInstance from them.
    for var in JIRA_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Backporter")
        cw.set_value("user", "email", "backporter@ciq.com")

    src = tmp_path / "net" / "sched"
    src.mkdir(parents=True)
    (src / "sch_qfq.c").write_text("// QFQ scheduler\nint qfq_init(void) { return 0; }\n")
    repo.index.add(["net/sched/sch_qfq.c"])
    repo.index.commit("Initial QFQ scheduler")

    monkeypatch.chdir(tmp_path)

    if "ciq_cherry_pick" in sys.modules:
        del sys.modules["ciq_cherry_pick"]
    spec = importlib.util.spec_from_file_location("ciq_cherry_pick", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    yield mod, repo, tmp_path

    if "ciq_cherry_pick" in sys.modules:
        del sys.modules["ciq_cherry_pick"]


@pytest.fixture
def command(cherry_pick_env):
    """A CherryPickCommand built from default args (no JIRA instance)."""
    mod, _, _ = cherry_pick_env
    return mod.CherryPickCommand(args=make_args())


def _create_upstream_commit(repo, tmp_path, msg, file_content, author_name, author_email):
    """Create a commit on a fresh branch from the current HEAD and return to the original branch."""
    original = repo.active_branch.name
    branch_name = f"upstream-{len(repo.heads)}"
    repo.create_head(branch_name).checkout()

    (tmp_path / "net" / "sched" / "sch_qfq.c").write_text(file_content)
    repo.index.add(["net/sched/sch_qfq.c"])
    commit = repo.index.commit(msg, author=git.Actor(author_name, author_email))

    repo.heads[original].checkout()
    return commit


def _write_merge_msg(mod, lines):
    with open(mod.MERGE_MSG, "w") as f:
        f.writelines(lines)


def _read_merge_msg(mod):
    with open(mod.MERGE_MSG) as f:
        return f.read()


def _merge_msg_lines(sha):
    """MERGE_MSG content mimicking `git cherry-pick -nsx <sha>`."""
    return [
        "KVM: x86: Check for invalid root\n",
        "\n",
        "Check for a stale page fault.\n",
        "\n",
        "Signed-off-by: Sean Christopherson <seanjc@google.com>\n",
        f"(cherry picked from commit {sha})\n",
        "Signed-off-by: Backporter <backporter@ciq.com>\n",
    ]


# ---------------------------------------------------------------------------
# CherryPickCommand._manage_commit_message
# ---------------------------------------------------------------------------


class TestManageCommitMessage:
    def _make_cmd(self, mod):
        return mod.CherryPickCommand(args=make_args())

    def test_standardizes_cve_commit(self, cherry_pick_env):
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(
                "drm/xe: Fix error cleanup in xe_exec_queue_create_ioctl()\n\n"
                "Two error handling issues exist.\n\n"
                "Signed-off-by: Shuicheng Lin <shuicheng.lin@intel.com>\n"
            ),
            file_content="// fixed\nint qfq_init(void) { return 1; }\n",
            author_name="Shuicheng Lin",
            author_email="shuicheng.lin@intel.com",
        )
        sha = commit.hexsha
        _write_merge_msg(mod, _merge_msg_lines(sha))

        cmd = self._make_cmd(mod)
        header = CommitHeader(jira="VULN-189406", cve="CVE-2026-52976", commit=sha)
        cmd._manage_commit_message(commit_header=header, commit_successful=True)

        result = _read_merge_msg(mod)
        assert "jira VULN-189406\n" in result
        assert "cve CVE-2026-52976\n" in result
        assert f"commit {sha}\n" in result
        assert "upstream-diff" not in result

    def test_conflict_sets_upstream_diff_marker(self, cherry_pick_env):
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="KVM: x86: Check for invalid root\n\nCheck for stale fault.\n\n",
            file_content="// kvm fix\n",
            author_name="Sean Christopherson",
            author_email="seanjc@google.com",
        )
        sha = commit.hexsha
        _write_merge_msg(mod, _merge_msg_lines(sha))

        cmd = self._make_cmd(mod)
        header = CommitHeader(jira="VULN-195551", cve="CVE-2026-64561", commit=sha)
        cmd._manage_commit_message(commit_header=header, commit_successful=False)

        result = _read_merge_msg(mod)
        assert "upstream-diff |\n" in result
        assert "jira VULN-195551\n" in result

    def test_header_ordering(self, cherry_pick_env):
        """jira -> cve -> commit-author -> commit, matching the CIQ format."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="nfsd: fix UAF\n\nFix UAF.\n\n",
            file_content="// nfsd fix\n",
            author_name="Yang Erkun",
            author_email="yangerkun@huawei.com",
        )
        sha = commit.hexsha
        _write_merge_msg(mod, _merge_msg_lines(sha))

        cmd = self._make_cmd(mod)
        header = CommitHeader(
            jira="VULN-167075",
            cve="CVE-2024-53216",
            commit_author="Yang Erkun <yangerkun@huawei.com>",
            commit=sha,
        )
        cmd._manage_commit_message(commit_header=header, commit_successful=True)

        result = _read_merge_msg(mod)
        jira_pos = result.index("jira VULN-167075")
        cve_pos = result.index("cve CVE-2024-53216")
        author_pos = result.index("commit-author Yang Erkun")
        commit_pos = result.index(f"commit {sha}")
        assert jira_pos < cve_pos < author_pos < commit_pos

    def test_commit_source_tags_emitted(self, cherry_pick_env):
        """KERNEL-516: source-only pick writes commit-source / commit-source-sha tags."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="authencesn: reject invalid authsize\n\nBody.\n\n",
            file_content="// fix\n",
            author_name="Yucheng Lu",
            author_email="kanolyc@gmail.com",
        )
        source_sha = commit.hexsha
        _write_merge_msg(mod, _merge_msg_lines(source_sha))

        cmd = self._make_cmd(mod)
        header = CommitHeader(
            jira="VULN-181881",
            cve_bf="CVE-2026-31431",
            commit="-",
            commit_source="centos-stream-9",
            commit_source_sha=source_sha,
        )
        cmd._manage_commit_message(commit_header=header, commit_successful=True)

        result = _read_merge_msg(mod)
        assert "commit -\n" in result
        assert "commit-source centos-stream-9\n" in result
        assert f"commit-source-sha {source_sha}\n" in result

    def test_conflicts_block_stripped(self, cherry_pick_env):
        """git appends a '# Conflicts:' comment block on conflicted picks; it must not
        survive into the final commit message."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="fix\n\nBody.\n\n",
            file_content="// fix\n",
            author_name="A",
            author_email="a@b.com",
        )
        sha = commit.hexsha
        lines = _merge_msg_lines(sha) + [
            "# Conflicts:\n",
            "#\tnet/sched/sch_qfq.c\n",
        ]
        _write_merge_msg(mod, lines)

        cmd = self._make_cmd(mod)
        header = CommitHeader(jira="VULN-1", commit=sha)
        cmd._manage_commit_message(commit_header=header, commit_successful=False)

        result = _read_merge_msg(mod)
        assert "# Conflicts:" not in result
        assert "sch_qfq.c\n" not in result

    def test_backup_created(self, cherry_pick_env):
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="fix something\n\n",
            file_content="// v2\n",
            author_name="A",
            author_email="a@b.com",
        )
        sha = commit.hexsha
        _write_merge_msg(mod, _merge_msg_lines(sha))

        cmd = self._make_cmd(mod)
        cmd._manage_commit_message(commit_header=CommitHeader(commit=sha), commit_successful=True)

        assert os.path.exists(mod.MERGE_MSG_BAK)


# ---------------------------------------------------------------------------
# CherryPickCommand._cherry_pick — full integration
# ---------------------------------------------------------------------------


class TestCherryPick:
    def _make_cmd(self, mod, **overrides):
        return mod.CherryPickCommand(args=make_args(**overrides))

    def test_successful_cherry_pick_mainline(self, cherry_pick_env):
        """Clean mainline cherry-pick produces the CIQ-standardized commit."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(
                "KVM: x86: Check for invalid root after making MMU pages available\n\n"
                "Check for a stale page fault.\n\n"
                "Signed-off-by: Sean Christopherson <seanjc@google.com>\n"
            ),
            file_content="// QFQ scheduler\nint qfq_init(void) { return 0; }\n// KVM fix applied\n",
            author_name="Sean Christopherson",
            author_email="seanjc@google.com",
        )

        cmd = self._make_cmd(mod)
        header = CommitHeader(jira="VULN-195551", cve="CVE-2026-64561", commit=commit.hexsha)
        cmd._cherry_pick(commit_header=header)

        msg = repo.head.commit.message
        assert "jira VULN-195551" in msg
        assert "cve CVE-2026-64561" in msg
        assert "commit-author Sean Christopherson <seanjc@google.com>" in msg
        assert f"commit {commit.hexsha}" in msg
        assert f"(cherry picked from commit {commit.hexsha})" in msg
        # author is resolved from the picked commit into the header
        assert header.commit_author == "Sean Christopherson <seanjc@google.com>"

    def test_cherry_pick_with_cve_bf(self, cherry_pick_env):
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="proc: fix type confusion in pde_set_flags()\n\nAdd !S_ISDIR test.\n\n",
            file_content="// proc fix\nint qfq_init(void) { return 0; }\n",
            author_name="wangzijie",
            author_email="wangzijie1@honor.com",
        )

        cmd = self._make_cmd(mod)
        header = CommitHeader(jira="VULN-163195", cve_bf="CVE-2025-38653", commit=commit.hexsha)
        cmd._cherry_pick(commit_header=header)

        msg = repo.head.commit.message
        assert "cve-bf CVE-2025-38653" in msg
        assert "jira VULN-163195" in msg
        assert "commit-author wangzijie <wangzijie1@honor.com>" in msg

    def test_cherry_pick_from_commit_source(self, cherry_pick_env):
        """KERNEL-516: with commit_source_sha set, the source sha is what gets
        cherry-picked (extract_upstream_name_and_sha routing)."""
        mod, repo, tmp_path = cherry_pick_env

        source_commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="authencesn: reject invalid authsize\n\nBody.\n\n",
            file_content="// centos variant\nint qfq_init(void) { return 0; }\n// fix applied\n",
            author_name="Yucheng Lu",
            author_email="kanolyc@gmail.com",
        )

        cmd = self._make_cmd(mod)
        header = CommitHeader(
            jira="VULN-181881",
            cve_bf="CVE-2026-31431",
            commit="-",
            commit_source="centos-stream-9",
            commit_source_sha=source_commit.hexsha,
        )
        cmd._cherry_pick(commit_header=header)

        msg = repo.head.commit.message
        assert f"(cherry picked from commit {source_commit.hexsha})" in msg
        assert "commit-source centos-stream-9" in msg
        assert "commit-author Yucheng Lu <kanolyc@gmail.com>" in msg

    def test_cherry_pick_conflict_raises(self, cherry_pick_env):
        """Conflicting cherry-pick raises CherryPickException; MERGE_MSG has the
        standardized header with upstream-diff marker."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(
                "net/sched: act_api: use RCU with deferred freeing\n\n"
                "Fix race condition.\n\n"
                "Signed-off-by: Jamal Hadi Salim <jhs@mojatatu.com>\n"
            ),
            file_content="// upstream RCU version\nint qfq_init(void) { return 42; }\n",
            author_name="Jamal Hadi Salim",
            author_email="jhs@mojatatu.com",
        )

        # Make a conflicting change on the current branch
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text(
            "// main branch version\nint qfq_init(void) { return -1; }\n"
        )
        repo.index.add(["net/sched/sch_qfq.c"])
        repo.index.commit("Conflicting change on main")

        cmd = self._make_cmd(mod)
        header = CommitHeader(jira="VULN-189813", cve="CVE-2026-53264", commit=commit.hexsha)

        with pytest.raises(mod.CherryPickException):
            cmd._cherry_pick(commit_header=header)

        merge_msg = _read_merge_msg(mod)
        assert "jira VULN-189813" in merge_msg
        assert "cve CVE-2026-53264" in merge_msg
        assert "upstream-diff |" in merge_msg

    def test_cherry_pick_no_tags(self, cherry_pick_env):
        """Cherry-pick without CIQ tags (non-CVE backport)."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="SUNRPC: introduce cache_check_rcu\n\nPrepare patch for rcu context check.\n\n",
            file_content="// sunrpc\nint qfq_init(void) { return 0; }\n",
            author_name="Yang Erkun",
            author_email="yangerkun@huawei.com",
        )

        cmd = self._make_cmd(mod)
        cmd._cherry_pick(commit_header=CommitHeader(commit=commit.hexsha))

        msg = repo.head.commit.message
        assert f"commit {commit.hexsha}" in msg
        assert "jira" not in msg
        assert "cve" not in msg


# ---------------------------------------------------------------------------
# CherryPickCommand._check_fixes
# ---------------------------------------------------------------------------


class TestCheckFixes:
    def test_no_fixes_reference_warns(self, cherry_pick_env, command, caplog):
        """Commit without Fixes: reference logs a warning."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="Simple feature\n\nAdd feature.\n\n",
            file_content="// feature\n",
            author_name="Dev",
            author_email="d@e.com",
        )

        with caplog.at_level(logging.WARNING):
            command._check_fixes(sha=commit.hexsha)

        assert "no fixes" in caplog.text.lower()

    def test_fixes_present_in_branch_passes(self, cherry_pick_env, command):
        """Fixes: pointing to initial commit (on current branch) should not raise."""
        mod, repo, tmp_path = cherry_pick_env

        init_sha = repo.head.commit.hexsha
        short_sha = init_sha[:12]

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(f'Fix a regression\n\nFixes: {short_sha} ("Initial QFQ scheduler")\n'),
            file_content="// regression fix\n",
            author_name="Dev",
            author_email="d@e.com",
        )

        command._check_fixes(sha=commit.hexsha)

    def test_fixes_missing_from_branch_raises(self, cherry_pick_env, command):
        """Fixes: pointing to an upstream-only commit should raise RuntimeError."""
        mod, repo, tmp_path = cherry_pick_env
        original = repo.active_branch.name

        repo.create_head("upstream-base").checkout()
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// upstream base change\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        base_commit = repo.index.commit(
            "upstream: introduce feature\n\nNew feature.\n\n",
            author=git.Actor("A", "a@b.com"),
        )
        base_short = base_commit.hexsha[:12]

        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// upstream fix for base\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        fix_commit = repo.index.commit(
            f'upstream: fix regression from feature\n\nFixes: {base_short} ("upstream: introduce feature")\n',
            author=git.Actor("B", "b@c.com"),
        )

        repo.heads[original].checkout()

        with pytest.raises(RuntimeError, match="not part of the tree"):
            command._check_fixes(sha=fix_commit.hexsha)

    def test_fixes_missing_ignored_when_flag_set(self, cherry_pick_env, caplog):
        """With ignore_fixes_check=True, missing Fixes: ref warns instead of raising."""
        mod, repo, tmp_path = cherry_pick_env
        original = repo.active_branch.name

        repo.create_head("upstream-ign").checkout()
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// base\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        base = repo.index.commit("base\n\n", author=git.Actor("A", "a@b.com"))

        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// fix\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        fix = repo.index.commit(f'fix\n\nFixes: {base.hexsha[:12]} ("base")\n', author=git.Actor("B", "b@c.com"))

        repo.heads[original].checkout()

        cmd = mod.CherryPickCommand(args=make_args(ignore_fixes_check=True))
        with caplog.at_level(logging.WARNING):
            cmd._check_fixes(sha=fix.hexsha)
        # Should not raise


# ---------------------------------------------------------------------------
# CherryPickCommand._cherry_pick_fixes
# ---------------------------------------------------------------------------


class TestCherryPickFixes:
    def test_skipped_without_mainline_sha(self, cherry_pick_env, command):
        """KERNEL-516: a source-only pick (commit='-') has no mainline sha to
        search Fixes: for — must skip cleanly, not crash."""
        mod, _, _ = cherry_pick_env

        header = CommitHeader(jira="VULN-181881", commit="-", commit_source="centos-stream-9")
        command.full_cherry_pick = MagicMock()

        command._cherry_pick_fixes(original_commit_header=header)

        command.full_cherry_pick.assert_not_called()

    def test_fixes_found_are_picked_as_cve_bf(self, cherry_pick_env, command):
        """A commit in upstream_ref with Fixes: <mainline sha> is re-picked with
        the cve tag swapped to cve-bf.

        Note: the branch name must not collide with the repo's default branch
        (init.defaultBranch may be 'mainline' on some systems).
        """
        mod, repo, tmp_path = cherry_pick_env
        original = repo.active_branch.name

        # The mainline CVE fix, on a dedicated branch used as upstream_ref
        repo.create_head("upstream-mainline").checkout()
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// mainline fix\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        mainline_fix = repo.index.commit(
            "net/sched: fix race\n\nFix the race.\n\n",
            author=git.Actor("Upstream Dev", "up@stream.com"),
        )

        # A follow-up commit on mainline referencing it via Fixes:
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// mainline fix + followup\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        followup = repo.index.commit(
            f'net/sched: fix regression from race fix\n\nFixes: {mainline_fix.hexsha[:12]} ("net/sched: fix race")\n',
            author=git.Actor("Upstream Dev", "up@stream.com"),
        )

        repo.heads[original].checkout()

        cmd = mod.CherryPickCommand(args=make_args(upstream_ref="upstream-mainline"))
        cmd.full_cherry_pick = MagicMock()

        header = CommitHeader(jira="VULN-1", cve="CVE-2026-1234", commit=mainline_fix.hexsha)
        cmd._cherry_pick_fixes(original_commit_header=header)

        assert cmd.full_cherry_pick.call_count == 1
        bf_header = cmd.full_cherry_pick.call_args.kwargs["commit_header"]
        assert bf_header.commit == followup.hexsha
        assert bf_header.cve is None
        assert bf_header.cve_bf == "CVE-2026-1234"

    def test_no_fixes_no_pick(self, cherry_pick_env, command):
        """No Fixes: commits in upstream_ref -> nothing re-picked."""
        mod, repo, tmp_path = cherry_pick_env

        repo.create_head("upstream-empty").checkout()
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// unrelated\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        unrelated = repo.index.commit("unrelated change\n\nNo fixes here.\n\n", author=git.Actor("A", "a@b.com"))

        # back to the original (non-upstream) branch
        original = [h for h in repo.heads if h.name != "upstream-empty"][0]
        original.checkout()

        cmd = mod.CherryPickCommand(args=make_args(upstream_ref="upstream-empty"))
        cmd.full_cherry_pick = MagicMock()

        header = CommitHeader(jira="VULN-1", cve="CVE-2026-1234", commit=unrelated.hexsha)
        cmd._cherry_pick_fixes(original_commit_header=header)

        cmd.full_cherry_pick.assert_not_called()


# ---------------------------------------------------------------------------
# CherryPickCommand JIRA updates
# ---------------------------------------------------------------------------


class TestUpdateJira:
    def test_success_dry_run_prints(self, cherry_pick_env, capsys):
        mod, _, _ = cherry_pick_env
        cmd = mod.CherryPickCommand(args=make_args(jira_dry_run=True))

        cmd._update_jira_success(ticket_key="VULN-189406")

        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "VULN-189406" in out

    def test_success_calls_jira_methods(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        cmd = mod.CherryPickCommand(args=make_args())
        jira = MagicMock()
        cmd._jira_instance = jira

        cmd._update_jira_success(ticket_key="VULN-189406")

        jira.assign_ticket.assert_called_once_with(issue_key="VULN-189406")
        jira.transition_issue.assert_called_once_with(issue_key="VULN-189406", transition_name="In Progress")
        jira.update_labels.assert_called_once_with(issue_key="VULN-189406", labels=["automated-patch-applied"])
        jira.add_worklog.assert_called_once()

    def test_success_none_ticket_is_noop(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        cmd = mod.CherryPickCommand(args=make_args())
        jira = MagicMock()
        cmd._jira_instance = jira

        cmd._update_jira_success(ticket_key=None)

        jira.assign_ticket.assert_not_called()

    def test_success_none_jira_is_noop(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        cmd = mod.CherryPickCommand(args=make_args())
        assert cmd._jira_instance is None

        cmd._update_jira_success(ticket_key="VULN-189406")  # should not raise

    def test_failure_dry_run_prints(self, cherry_pick_env, capsys):
        mod, _, _ = cherry_pick_env
        cmd = mod.CherryPickCommand(args=make_args(jira_dry_run=True))

        cmd._update_jira_failure(ticket_key="VULN-189406")

        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "automated-patch-failed" in out

    def test_failure_calls_update_labels(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        cmd = mod.CherryPickCommand(args=make_args())
        jira = MagicMock()
        cmd._jira_instance = jira

        cmd._update_jira_failure(ticket_key="VULN-189406")

        jira.update_labels.assert_called_once_with(issue_key="VULN-189406", labels=["automated-patch-failed"])

    def test_failure_none_ticket_is_noop(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        cmd = mod.CherryPickCommand(args=make_args())
        jira = MagicMock()
        cmd._jira_instance = jira

        cmd._update_jira_failure(ticket_key=None)

        jira.update_labels.assert_not_called()


# ---------------------------------------------------------------------------
# from_argsparse_to_commit_header
# ---------------------------------------------------------------------------


class TestFromArgsparseToCommitHeader:
    def test_ciq_tags_parsed_into_fields(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env

        args = make_args(commit=None, jira="VULN-1", ciq_tag="cve CVE-2026-52976")
        header = mod.from_argsparse_to_commit_header(args)

        assert header.cve == "CVE-2026-52976"
        assert header.jira == "VULN-1"

    def test_ciq_tags_with_comma_and_space(self, cherry_pick_env):
        """'cve CVE-1, cve-pre CVE-2' — the comma form must not crash on the
        leading space of the second tag."""
        mod, _, _ = cherry_pick_env

        args = make_args(ciq_tag="cve CVE-2026-52976, cve-pre CVE-2024-53216")
        header = mod.from_argsparse_to_commit_header(args)

        assert header.cve == "CVE-2026-52976"
        assert header.cve_pre == "CVE-2024-53216"

    def test_multi_word_tag_value(self, cherry_pick_env):
        """Tag values containing spaces must be kept whole, not crash the split."""
        mod, _, _ = cherry_pick_env

        args = make_args(ciq_tag="cve CVE-2026-52976 with suffix")
        header = mod.from_argsparse_to_commit_header(args)

        assert header.cve == "CVE-2026-52976 with suffix"

    def test_commit_short_sha_expanded(self, cherry_pick_env):
        mod, repo, _ = cherry_pick_env

        args = make_args(commit=repo.head.commit.hexsha[:12])
        header = mod.from_argsparse_to_commit_header(args)

        assert header.commit == repo.head.commit.hexsha

    def test_commit_source_sha_expanded_and_remote_fetched(self, cherry_pick_env, monkeypatch):
        mod, repo, _ = cherry_pick_env

        source_sha = repo.head.commit.hexsha

        class StubUpstreamRemotes:
            last_instance = None

            def __init__(self):
                self.fetch_mock = MagicMock()
                StubUpstreamRemotes.last_instance = self

            @classmethod
            def from_yaml(cls):
                return cls()

            def fetch_remote(self, remote_name, repo_dir):
                self.fetch_mock(remote_name=remote_name, repo_dir=repo_dir)

        monkeypatch.setattr(mod, "UpstreamRemotes", StubUpstreamRemotes)

        args = make_args(commit="-", commit_source="centos-stream-9", commit_source_sha=source_sha[:12])
        header = mod.from_argsparse_to_commit_header(args)

        assert StubUpstreamRemotes.last_instance.fetch_mock.call_count == 1
        assert StubUpstreamRemotes.last_instance.fetch_mock.call_args.kwargs["remote_name"] == "centos-stream-9"
        assert header.commit_source == "centos-stream-9"
        assert header.commit_source_sha == source_sha

    def test_no_fetch_without_both_source_args(self, cherry_pick_env, monkeypatch):
        """Only --commit-source (no sha) must not trigger a remote fetch."""
        mod, _, _ = cherry_pick_env

        class StubUpstreamRemotes:
            instances = []

            def __init__(self):
                self.fetch_mock = MagicMock()
                StubUpstreamRemotes.instances.append(self)

            @classmethod
            def from_yaml(cls):
                return cls()

            def fetch_remote(self, remote_name, repo_dir):
                self.fetch_mock(remote_name=remote_name, repo_dir=repo_dir)

        monkeypatch.setattr(mod, "UpstreamRemotes", StubUpstreamRemotes)

        args = make_args(commit_source="centos-stream-9")
        header = mod.from_argsparse_to_commit_header(args)

        assert StubUpstreamRemotes.instances[-1].fetch_mock.call_count == 0
        assert header.commit_source == "centos-stream-9"
        assert header.commit_source_sha is None
