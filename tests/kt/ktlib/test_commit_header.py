"""Tests for kt.ktlib.commit_header.CommitHeader."""

import re

import pytest

from kt.ktlib.commit_header import CommitHeader

MAINLINE_SHA = "2abd5287f08319fa35764566b15c6e22cb1068db"
SOURCE_SHA = "5db6ef9847717329f12c5ea8aba7e9f588a980c0"

# Real-world shaped body (JIRA KERNEL-516 example): source-only commit,
# mainline sha not known yet (commit -).
SOURCE_COMMIT_BODY = """
jira VULN-181881
cve-bf CVE-2026-31431
commit-author Yucheng Lu <kanolyc@gmail.com>
commit -
commit-source-sha 5db6ef9847717329f12c5ea8aba7e9f588a980c0
commit-source centos-stream-9

authencesn requires either a zero authsize or an authsize of at least
4 bytes because the ESN encrypt/decrypt paths always move 4 bytes of
high-order sequence number data at the end of the authenticated data.

    Signed-off-by: Yucheng Lu <kanolyc@gmail.com>
    Signed-off-by: Herbert Xu <herbert@gondor.apana.org.au>

"""

MAINLINE_COMMIT_BODY = f"""
jira VULN-195551
cve CVE-2026-64561
commit-author Sean Christopherson <seanjc@google.com>
commit {MAINLINE_SHA}

KVM: x86: Check for invalid/obsolete root after making MMU pages available

    Signed-off-by: Sean Christopherson <seanjc@google.com>

"""


# --- parsing ---


def test_from_commit_body_source_only():
    header = CommitHeader.from_commit_body(commit_body=SOURCE_COMMIT_BODY)

    assert header.jira == "VULN-181881"
    assert header.cve_bf == "CVE-2026-31431"
    assert header.commit_author == "Yucheng Lu <kanolyc@gmail.com>"
    assert header.commit == "-"
    assert header.commit_source == "centos-stream-9"
    assert header.commit_source_sha == SOURCE_SHA


def test_from_commit_body_mainline():
    header = CommitHeader.from_commit_body(commit_body=MAINLINE_COMMIT_BODY)

    assert header.jira == "VULN-195551"
    assert header.cve == "CVE-2026-64561"
    assert header.commit == MAINLINE_SHA
    assert header.commit_source is None
    assert header.commit_source_sha is None


def test_from_commit_body_ignores_body_lines():
    """Tag parsing must stop at the tags block; body text is not misread as tags."""
    header = CommitHeader.from_commit_body(commit_body=MAINLINE_COMMIT_BODY)

    # 'commit ' appearing in prose must not overwrite the parsed sha
    assert header.commit == MAINLINE_SHA


# --- to_str round trip ---


def test_to_str_returns_tag_lines():
    header = CommitHeader(
        jira="VULN-181881",
        cve_bf="CVE-2026-31431",
        commit="-",
        commit_source="centos-stream-9",
        commit_source_sha=SOURCE_SHA,
    )

    result = header.to_str()

    assert result == (
        "jira VULN-181881\n"
        "cve-bf CVE-2026-31431\n"
        "commit -\n"
        "commit-source centos-stream-9\n"
        "commit-source-sha 5db6ef9847717329f12c5ea8aba7e9f588a980c0"
    )


def test_to_str_round_trip_source_only():
    """from_commit_body -> to_str -> from_commit_body must be stable."""
    header = CommitHeader.from_commit_body(commit_body=SOURCE_COMMIT_BODY)

    rebuilt = CommitHeader.from_commit_body(commit_body="\n" + header.to_str() + "\n\n" + "body text\n")

    assert rebuilt == header


def test_to_str_omits_empty_fields():
    header = CommitHeader(commit=MAINLINE_SHA)

    assert header.to_str() == f"commit {MAINLINE_SHA}"


def test_to_str_no_fields_set():
    assert CommitHeader().to_str() == ""


# --- from_dict filtering ---


def test_from_dict_ignores_unknown_keys():
    header = CommitHeader.from_dict({"jira": "VULN-1", "commit": MAINLINE_SHA, "not_a_field": "x"})

    assert header.jira == "VULN-1"
    assert header.commit == MAINLINE_SHA
    assert not hasattr(header, "not_a_field")


# --- cve helpers ---


def test_is_cve_true_for_each_variant():
    assert CommitHeader(cve="CVE-1").is_cve()
    assert CommitHeader(cve_bf="CVE-1").is_cve()
    assert CommitHeader(cve_pre="CVE-1").is_cve()


def test_is_cve_false():
    assert not CommitHeader(commit=MAINLINE_SHA).is_cve()


def test_cve_number_prefers_cve():
    assert CommitHeader(cve="CVE-1", cve_bf="CVE-2").cve_number() == "CVE-1"


def test_cve_number_falls_back_to_bf_then_pre():
    assert CommitHeader(cve_bf="CVE-2").cve_number() == "CVE-2"
    assert CommitHeader(cve_pre="CVE-3").cve_number() == "CVE-3"
    assert CommitHeader().cve_number() is None


def test_set_cve_clears_other_cve_tags():
    header = CommitHeader(cve_bf="CVE-2", cve_pre="CVE-3")

    header.set_cve("CVE-9")

    assert header.cve == "CVE-9"
    assert header.cve_bf is None
    assert header.cve_pre is None


def test_make_it_cve_bf_swaps_cve():
    header = CommitHeader(cve="CVE-1")

    header.make_it_cve_bf()

    assert header.cve is None
    assert header.cve_bf == "CVE-1"


def test_make_it_cve_bf_keeps_existing_bf():
    header = CommitHeader(cve="CVE-1", cve_bf="CVE-2")

    header.make_it_cve_bf()

    # Already has a cve_bf value - leave it alone
    assert header.cve == "CVE-1"
    assert header.cve_bf == "CVE-2"


def test_make_it_cve_bf_noop_without_cve():
    header = CommitHeader(commit=MAINLINE_SHA)

    header.make_it_cve_bf()

    assert not header.is_cve()


def test_all_cves():
    assert CommitHeader(cve="CVE-1", cve_bf="CVE-2", cve_pre="CVE-3").all_cves() == ["CVE-1", "CVE-2", "CVE-3"]
    assert CommitHeader(commit=MAINLINE_SHA).all_cves() == []


# --- extract_upstream_name_and_sha ---


def test_extract_upstream_mainline():
    header = CommitHeader(commit=MAINLINE_SHA)

    assert header.extract_upstream_name_and_sha() == (None, MAINLINE_SHA)


def test_extract_upstream_source():
    header = CommitHeader(commit="-", commit_source="centos-stream-9", commit_source_sha=SOURCE_SHA)

    assert header.extract_upstream_name_and_sha() == ("centos-stream-9", SOURCE_SHA)


def test_extract_upstream_source_with_mainline_known():
    """Both shas present: the source sha is what gets cherry-picked."""
    header = CommitHeader(commit=MAINLINE_SHA, commit_source="linux-stable", commit_source_sha=SOURCE_SHA)

    assert header.extract_upstream_name_and_sha() == ("linux-stable", SOURCE_SHA)


def test_extract_upstream_nothing_known():
    assert CommitHeader().extract_upstream_name_and_sha() == (None, None)
    assert CommitHeader(commit="-").extract_upstream_name_and_sha() == (None, None)


# --- regression: provenance tags must never look like a mainline anchor line ---


@pytest.mark.parametrize(
    "field,tag_name",
    [("commit_source", "commit-source"), ("commit_source_sha", "commit-source-sha")],
)
def test_source_tags_do_not_match_commit_anchor(field, tag_name):
    """check_kernel_commits.py anchors on ^commit <40hex>; the provenance tags
    commit-source / commit-source-sha must stay visually and semantically distinct."""
    header = CommitHeader(**{field: SOURCE_SHA})
    line = header.to_str()

    assert not re.match(r"^commit\s+[0-9a-fA-F]{40}$", line)
    assert line.startswith(tag_name)
