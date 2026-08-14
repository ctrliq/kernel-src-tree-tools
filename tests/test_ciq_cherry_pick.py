"""Tests for ciq-cherry-pick.py

Imports the module via importlib (hyphenated filename, module-level
git.Repo(os.getcwd()) call) against temporary git repos. Test fixtures
use real commit data from ciqlts9_6 and rocky9_6 in ctrliq/kernel-src-tree.
"""

import importlib.util
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import git
import pytest

SCRIPT_PATH = str(Path(__file__).resolve().parent.parent / "ciq-cherry-pick.py")


@pytest.fixture
def cherry_pick_env(tmp_path, monkeypatch):
    """Create a git repo, chdir into it, and import ciq-cherry-pick.py.

    Returns (module, repo, tmp_path).
    """
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


# ---------------------------------------------------------------------------
# extract_cve_from_tag
# ---------------------------------------------------------------------------


class TestExtractCveFromTag:
    def test_cve_tag(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        assert mod.extract_cve_from_tag("cve CVE-2026-52976") == "CVE-2026-52976"

    def test_cve_bf_tag(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        assert mod.extract_cve_from_tag("cve-bf CVE-2025-38653") == "CVE-2025-38653"

    def test_cve_pre_not_matched(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        assert mod.extract_cve_from_tag("cve-pre CVE-2024-53216") is None

    def test_no_match(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        assert mod.extract_cve_from_tag("random text") is None

    def test_embedded_after_jira(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        assert mod.extract_cve_from_tag("jira VULN-123, cve CVE-2025-5678") == "CVE-2025-5678"


# ---------------------------------------------------------------------------
# manage_commit_message
# ---------------------------------------------------------------------------


class TestManageCommitMessage:
    """Modeled after ciqlts9_6 10d418025314 (drm/xe) and 0df72fa942dc (KVM)."""

    def _write_merge_msg(self, mod, lines):
        with open(mod.MERGE_MSG, "w") as f:
            f.writelines(lines)

    def _read_merge_msg(self, mod):
        with open(mod.MERGE_MSG) as f:
            return f.read()

    def test_standardizes_cve_commit(self, cherry_pick_env):
        """Verify full CIQ header: jira, cve, commit-author, commit."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(
                "drm/xe: Fix error cleanup in xe_exec_queue_create_ioctl()\n\n"
                "Two error handling issues exist.\n\n"
                'Fixes: 7970cb36966c ("drm/xe/hw_engine_group")\n'
                "Signed-off-by: Shuicheng Lin <shuicheng.lin@intel.com>\n"
            ),
            file_content="// fixed\nint qfq_init(void) { return 1; }\n",
            author_name="Shuicheng Lin",
            author_email="shuicheng.lin@intel.com",
        )
        sha = commit.hexsha

        self._write_merge_msg(
            mod,
            [
                "drm/xe: Fix error cleanup in xe_exec_queue_create_ioctl()\n",
                "\n",
                "Two error handling issues exist.\n",
                "\n",
                'Fixes: 7970cb36966c ("drm/xe/hw_engine_group")\n',
                "Signed-off-by: Shuicheng Lin <shuicheng.lin@intel.com>\n",
                f"(cherry picked from commit {sha})\n",
                "Signed-off-by: Backporter <backporter@ciq.com>\n",
            ],
        )

        mod.manage_commit_message(
            full_sha=sha,
            ciq_tags=["cve CVE-2026-52976"],
            jira_ticket="VULN-189406",
            commit_successful=True,
        )

        result = self._read_merge_msg(mod)
        assert "jira VULN-189406\n" in result
        assert "cve CVE-2026-52976\n" in result
        assert "commit-author Shuicheng Lin <shuicheng.lin@intel.com>\n" in result
        assert f"commit {sha}\n" in result
        assert "upstream-diff" not in result

    def test_conflict_adds_upstream_diff(self, cherry_pick_env):
        """commit_successful=False should insert upstream-diff marker."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="KVM: x86: Check for invalid root\n\nCheck for stale fault.\n\n"
            "Signed-off-by: Sean Christopherson <seanjc@google.com>\n",
            file_content="// kvm fix\n",
            author_name="Sean Christopherson",
            author_email="seanjc@google.com",
        )
        sha = commit.hexsha

        self._write_merge_msg(
            mod,
            [
                "KVM: x86: Check for invalid root\n",
                "\n",
                "Check for stale fault.\n",
                "\n",
                "Signed-off-by: Sean Christopherson <seanjc@google.com>\n",
                f"(cherry picked from commit {sha})\n",
                "Signed-off-by: Backporter <backporter@ciq.com>\n",
            ],
        )

        mod.manage_commit_message(
            full_sha=sha,
            ciq_tags=["cve CVE-2026-64561"],
            jira_ticket="VULN-195551",
            commit_successful=False,
        )

        result = self._read_merge_msg(mod)
        assert "upstream-diff |\n" in result
        assert "jira VULN-195551\n" in result

    def test_header_ordering(self, cherry_pick_env):
        """jira → cve → commit-author → commit, matching ciqlts9_6 format."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="nfsd: fix UAF\n\nFix UAF.\n\nSigned-off-by: Yang Erkun <yangerkun@huawei.com>\n",
            file_content="// nfsd fix\n",
            author_name="Yang Erkun",
            author_email="yangerkun@huawei.com",
        )
        sha = commit.hexsha

        self._write_merge_msg(
            mod,
            [
                "nfsd: fix UAF\n",
                "\n",
                "Fix UAF.\n",
                "\n",
                "Signed-off-by: Yang Erkun <yangerkun@huawei.com>\n",
                f"(cherry picked from commit {sha})\n",
                "Signed-off-by: Backporter <backporter@ciq.com>\n",
            ],
        )

        mod.manage_commit_message(
            full_sha=sha,
            ciq_tags=["cve CVE-2024-53216"],
            jira_ticket="VULN-167075",
            commit_successful=True,
        )

        result = self._read_merge_msg(mod)
        jira_pos = result.index("jira VULN-167075")
        cve_pos = result.index("cve CVE-2024-53216")
        author_pos = result.index("commit-author Yang Erkun")
        commit_pos = result.index(f"commit {sha}")
        assert jira_pos < cve_pos < author_pos < commit_pos

    def test_backup_created(self, cherry_pick_env):
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="fix something\n\nSigned-off-by: A <a@b.com>\n",
            file_content="// v2\n",
            author_name="A",
            author_email="a@b.com",
        )

        self._write_merge_msg(
            mod,
            [
                "fix something\n",
                "\n",
                "Signed-off-by: A <a@b.com>\n",
                f"(cherry picked from commit {commit.hexsha})\n",
                "Signed-off-by: Backporter <backporter@ciq.com>\n",
            ],
        )

        mod.manage_commit_message(commit.hexsha, [], None, True)
        assert os.path.exists(mod.MERGE_MSG_BAK)

    def test_multiple_jira_tickets(self, cherry_pick_env):
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="fix two things\n\nSigned-off-by: A <a@b.com>\n",
            file_content="// multi\n",
            author_name="A",
            author_email="a@b.com",
        )

        self._write_merge_msg(
            mod,
            [
                "fix two things\n",
                "\n",
                "Signed-off-by: A <a@b.com>\n",
                f"(cherry picked from commit {commit.hexsha})\n",
                "Signed-off-by: Backporter <backporter@ciq.com>\n",
            ],
        )

        mod.manage_commit_message(commit.hexsha, [], "VULN-100,VULN-200", True)

        result = self._read_merge_msg(mod)
        assert "jira VULN-100\n" in result
        assert "jira VULN-200\n" in result


# ---------------------------------------------------------------------------
# cherry_pick — full integration
# ---------------------------------------------------------------------------


class TestCherryPick:
    """Integration tests using real git cherry-pick operations.

    Modeled after ciqlts9_6 0df72fa942dc (KVM) and 42796dd9cd76 (net/sched).
    """

    def test_successful_cherry_pick(self, cherry_pick_env):
        """Clean cherry-pick produces CIQ-standardized commit on current branch."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(
                "KVM: x86: Check for invalid root after making MMU pages available\n\n"
                "Check for a stale page fault.\n\n"
                "Signed-off-by: Sean Christopherson <seanjc@google.com>\n"
                "Signed-off-by: Paolo Bonzini <pbonzini@redhat.com>\n"
            ),
            file_content=("// QFQ scheduler\nint qfq_init(void) { return 0; }\n// KVM fix applied\n"),
            author_name="Sean Christopherson",
            author_email="seanjc@google.com",
        )

        mod.cherry_pick(
            sha=commit.hexsha,
            ciq_tags=["cve CVE-2026-64561"],
            jira_ticket="VULN-195551",
            ignore_fixes_check=True,
        )

        msg = repo.head.commit.message
        assert "jira VULN-195551" in msg
        assert "cve CVE-2026-64561" in msg
        assert "commit-author Sean Christopherson <seanjc@google.com>" in msg
        assert f"commit {commit.hexsha}" in msg
        assert f"(cherry picked from commit {commit.hexsha})" in msg

    def test_cherry_pick_with_cve_bf(self, cherry_pick_env):
        """Cherry-pick with cve-bf tag, modeled after ciqlts9_6 64a032d7cc69."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(
                "proc: fix type confusion in pde_set_flags()\n\n"
                "Add !S_ISDIR test before calling pde_set_flags().\n\n"
                "Signed-off-by: wangzijie <wangzijie1@honor.com>\n"
            ),
            file_content="// proc fix\nint qfq_init(void) { return 0; }\n",
            author_name="wangzijie",
            author_email="wangzijie1@honor.com",
        )

        mod.cherry_pick(
            sha=commit.hexsha,
            ciq_tags=["cve-bf CVE-2025-38653"],
            jira_ticket="VULN-163195",
            ignore_fixes_check=True,
        )

        msg = repo.head.commit.message
        assert "cve-bf CVE-2025-38653" in msg
        assert "jira VULN-163195" in msg
        assert "commit-author wangzijie <wangzijie1@honor.com>" in msg

    def test_cherry_pick_conflict_raises(self, cherry_pick_env):
        """Conflicting cherry-pick raises CherryPickException, MERGE_MSG has CIQ header."""
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

        with pytest.raises(mod.CherryPickException):
            mod.cherry_pick(
                sha=commit.hexsha,
                ciq_tags=["cve CVE-2026-53264"],
                jira_ticket="VULN-189813",
                ignore_fixes_check=True,
            )

        with open(mod.MERGE_MSG) as f:
            merge_msg = f.read()

        assert "jira VULN-189813" in merge_msg
        assert "cve CVE-2026-53264" in merge_msg
        assert "upstream-diff |" in merge_msg

    def test_cherry_pick_no_tags(self, cherry_pick_env):
        """Cherry-pick without CIQ tags (non-CVE backport)."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(
                "SUNRPC: introduce cache_check_rcu\n\n"
                "Prepare patch for rcu context check.\n\n"
                "Signed-off-by: Yang Erkun <yangerkun@huawei.com>\n"
            ),
            file_content="// sunrpc\nint qfq_init(void) { return 0; }\n",
            author_name="Yang Erkun",
            author_email="yangerkun@huawei.com",
        )

        mod.cherry_pick(
            sha=commit.hexsha,
            ciq_tags=[],
            jira_ticket=None,
            ignore_fixes_check=True,
        )

        msg = repo.head.commit.message
        assert f"commit {commit.hexsha}" in msg
        assert "jira" not in msg
        assert "cve" not in msg


# ---------------------------------------------------------------------------
# check_fixes
# ---------------------------------------------------------------------------


class TestCheckFixes:
    def test_no_fixes_reference_warns(self, cherry_pick_env, caplog):
        """Commit without Fixes: reference logs a warning."""
        mod, repo, tmp_path = cherry_pick_env

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg="Simple feature\n\nAdd feature.\n\nSigned-off-by: Dev <d@e.com>\n",
            file_content="// feature\n",
            author_name="Dev",
            author_email="d@e.com",
        )

        with caplog.at_level(logging.WARNING):
            mod.check_fixes(sha=commit.hexsha, ignore_fixes_check=False)

        assert "no fixes" in caplog.text.lower()

    def test_fixes_present_in_branch_passes(self, cherry_pick_env):
        """Fixes: pointing to initial commit (on current branch) should not raise."""
        mod, repo, tmp_path = cherry_pick_env

        init_sha = repo.head.commit.hexsha
        short_sha = init_sha[:12]

        commit = _create_upstream_commit(
            repo,
            tmp_path,
            msg=(f'Fix a regression\n\nFixes: {short_sha} ("Initial QFQ scheduler")\nSigned-off-by: Dev <d@e.com>\n'),
            file_content="// regression fix\n",
            author_name="Dev",
            author_email="d@e.com",
        )

        # Should not raise — the referenced commit is on the current branch
        mod.check_fixes(sha=commit.hexsha, ignore_fixes_check=False)

    def test_fixes_missing_from_branch_raises(self, cherry_pick_env):
        """Fixes: pointing to upstream-only commit should raise RuntimeError."""
        mod, repo, tmp_path = cherry_pick_env
        original = repo.active_branch.name

        # Create first upstream commit (the one that will be referenced by Fixes:)
        repo.create_head("upstream-base").checkout()
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// upstream base change\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        base_commit = repo.index.commit(
            "upstream: introduce feature\n\nNew feature.\n\nSigned-off-by: A <a@b.com>\n",
            author=git.Actor("A", "a@b.com"),
        )
        base_short = base_commit.hexsha[:12]

        # Create second upstream commit that fixes the first
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// upstream fix for base\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        fix_commit = repo.index.commit(
            f"upstream: fix regression from feature\n\n"
            f'Fixes: {base_short} ("upstream: introduce feature")\n'
            f"Signed-off-by: B <b@c.com>\n",
            author=git.Actor("B", "b@c.com"),
        )

        repo.heads[original].checkout()

        with pytest.raises(RuntimeError, match="not part of the tree"):
            mod.check_fixes(sha=fix_commit.hexsha, ignore_fixes_check=False)

    def test_fixes_missing_ignored_when_flag_set(self, cherry_pick_env, caplog):
        """With ignore_fixes_check=True, missing Fixes: ref warns instead of raising."""
        mod, repo, tmp_path = cherry_pick_env
        original = repo.active_branch.name

        repo.create_head("upstream-ign").checkout()
        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// base\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        base = repo.index.commit("base\n\nSigned-off-by: A <a@b.com>\n", author=git.Actor("A", "a@b.com"))

        (tmp_path / "net" / "sched" / "sch_qfq.c").write_text("// fix\n")
        repo.index.add(["net/sched/sch_qfq.c"])
        fix = repo.index.commit(
            f'fix\n\nFixes: {base.hexsha[:12]} ("base")\nSigned-off-by: B <b@c.com>\n',
            author=git.Actor("B", "b@c.com"),
        )

        repo.heads[original].checkout()

        with caplog.at_level(logging.WARNING):
            mod.check_fixes(sha=fix.hexsha, ignore_fixes_check=True)
        # Should not raise


# ---------------------------------------------------------------------------
# update_jira_success / update_jira_failure
# ---------------------------------------------------------------------------


class TestUpdateJira:
    def test_success_dry_run_prints(self, cherry_pick_env, capsys):
        mod, _, _ = cherry_pick_env
        mod.update_jira_success(
            jira_instance=MagicMock(),
            ticket_key="VULN-189406",
            jira_dry_run=True,
        )
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "VULN-189406" in out

    def test_success_calls_jira_methods(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        jira = MagicMock()
        mod.update_jira_success(jira_instance=jira, ticket_key="VULN-189406", jira_dry_run=False)

        jira.assign_ticket.assert_called_once_with(issue_key="VULN-189406")
        jira.transition_issue.assert_called_once_with(
            issue_key="VULN-189406",
            transition_name="In Progress",
        )
        jira.update_labels.assert_called_once_with(
            issue_key="VULN-189406",
            labels=["automated-patch-applied"],
        )
        jira.add_worklog.assert_called_once()

    def test_success_none_ticket_is_noop(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        jira = MagicMock()
        mod.update_jira_success(jira_instance=jira, ticket_key=None, jira_dry_run=False)
        jira.assign_ticket.assert_not_called()

    def test_success_none_jira_is_noop(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        mod.update_jira_success(jira_instance=None, ticket_key="VULN-189406", jira_dry_run=False)
        # Should not raise

    def test_failure_dry_run_prints(self, cherry_pick_env, capsys):
        mod, _, _ = cherry_pick_env
        mod.update_jira_failure(
            jira_instance=MagicMock(),
            ticket_key="VULN-189406",
            jira_dry_run=True,
        )
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "automated-patch-failed" in out

    def test_failure_calls_update_labels(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        jira = MagicMock()
        mod.update_jira_failure(jira_instance=jira, ticket_key="VULN-189406", jira_dry_run=False)
        jira.update_labels.assert_called_once_with(
            issue_key="VULN-189406",
            labels=["automated-patch-failed"],
        )

    def test_failure_none_ticket_is_noop(self, cherry_pick_env):
        mod, _, _ = cherry_pick_env
        jira = MagicMock()
        mod.update_jira_failure(jira_instance=jira, ticket_key=None, jira_dry_run=False)
        jira.update_labels.assert_not_called()
