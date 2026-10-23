from kt.ktlib.ciq_helpers import CIQ_cherry_pick_commit_standardization, read_spec_el_version
from kt.ktlib.commit_header import CommitHeader

UPSTREAM_SHA = "1234567890abcdef1234567890abcdef12345678"


def standardized_cherry_pick_msg():
    """Run standardization on commit message lines mimicking MERGE_MSG after `git cherry-pick -nsx`."""
    commit_header = CommitHeader(jira="VULN-123", cve="CVE-2026-1234", commit=UPSTREAM_SHA)
    lines = [
        "gve: fix a bug in the driver\n",
        "\n",
        "Some body text describing the fix.\n",
        "\n",
        "Signed-off-by: Upstream Author <author@example.com>\n",
        "Reviewed-by: Upstream Reviewer <reviewer@example.com>\n",
        f"(cherry picked from commit {UPSTREAM_SHA})\n",
        "Signed-off-by: Backporter <backporter@example.com>\n",
    ]
    return CIQ_cherry_pick_commit_standardization(lines, commit_header)


def test_cherry_pick_standardization_indents_upstream_trailers():
    lines = standardized_cherry_pick_msg()
    assert "\tSigned-off-by: Upstream Author <author@example.com>\n" in lines
    assert "\tReviewed-by: Upstream Reviewer <reviewer@example.com>\n" in lines


def test_cherry_pick_standardization_stops_indenting_at_marker():
    lines = standardized_cherry_pick_msg()
    assert lines[-2] == f"(cherry picked from commit {UPSTREAM_SHA})\n"
    assert lines[-1] == "Signed-off-by: Backporter <backporter@example.com>\n"


def test_cherry_pick_standardization_emits_header_tags_as_lines():
    """The commit header must be inserted as real message lines, not a Python list repr."""
    lines = standardized_cherry_pick_msg()
    text = "".join(lines)

    assert "jira VULN-123\n" in text
    assert "cve CVE-2026-1234\n" in text
    assert f"commit {UPSTREAM_SHA}\n" in text
    assert "['" not in text  # regression: to_str() list repr leaking into the message


def test_cherry_pick_standardization_header_order():
    lines = standardized_cherry_pick_msg()
    text = "".join(lines)

    jira_pos = text.index("jira VULN-123")
    cve_pos = text.index("cve CVE-2026-1234")
    commit_pos = text.index(f"commit {UPSTREAM_SHA}")
    assert jira_pos < cve_pos < commit_pos


def test_cherry_pick_standardization_with_commit_source():
    """Source-only pick (KERNEL-516): commit-source tags are emitted."""
    commit_header = CommitHeader(
        jira="VULN-181881",
        cve_bf="CVE-2026-31431",
        commit="-",
        commit_source="centos-stream-9",
        commit_source_sha="5db6ef9847717329f12c5ea8aba7e9f588a980c0",
    )
    lines = [
        "authencesn: reject invalid authsize\n",
        "\n",
        "Body text.\n",
        "\n",
        "\tSigned-off-by: Yucheng Lu <kanolyc@gmail.com>\n",
    ]
    result = CIQ_cherry_pick_commit_standardization(lines, commit_header)
    text = "".join(result)

    assert "commit -\n" in text
    assert "commit-source centos-stream-9\n" in text
    assert "commit-source-sha 5db6ef9847717329f12c5ea8aba7e9f588a980c0\n" in text


# --- read_spec_el_version tests ---


def test_read_spec_el_version_returns_version():
    spec_lines = [
        "%define el_version 9\n",
        "Name: kernel\n",
    ]
    assert read_spec_el_version(spec_lines) == "9"


def test_read_spec_el_version_returns_two_digit_version():
    spec_lines = [
        "%define el_version 10\n",
        "Name: kernel\n",
    ]
    assert read_spec_el_version(spec_lines) == "10"


def test_read_spec_el_version_returns_none_when_missing():
    spec_lines = [
        "Name: kernel\n",
        "%define kversion 6\n",
    ]
    assert read_spec_el_version(spec_lines) is None


def test_read_spec_el_version_returns_none_for_non_numeric():
    spec_lines = [
        "%define el_version abc\n",
        "Name: kernel\n",
    ]
    assert read_spec_el_version(spec_lines) is None


def test_read_spec_el_version_empty_spec():
    assert read_spec_el_version([]) is None
