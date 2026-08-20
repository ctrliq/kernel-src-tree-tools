from kt.ktlib.ciq_helpers import CIQ_cherry_pick_commit_standardization, read_spec_el_version

UPSTREAM_SHA = "1234567890abcdef1234567890abcdef12345678"
AUTHOR_TAG = "commit-author Upstream Author <author@example.com>"


def standardized_cherry_pick_msg():
    """Run standardization on commit message lines mimicking MERGE_MSG after `git cherry-pick -nsx`."""
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
    return CIQ_cherry_pick_commit_standardization(lines, UPSTREAM_SHA, tags=[AUTHOR_TAG], jira="VULN-123")


def test_cherry_pick_standardization_indents_upstream_trailers():
    lines = standardized_cherry_pick_msg()
    assert "\tSigned-off-by: Upstream Author <author@example.com>\n" in lines
    assert "\tReviewed-by: Upstream Reviewer <reviewer@example.com>\n" in lines


def test_cherry_pick_standardization_stops_indenting_at_marker():
    lines = standardized_cherry_pick_msg()
    assert lines[-2] == f"(cherry picked from commit {UPSTREAM_SHA})\n"
    assert lines[-1] == "Signed-off-by: Backporter <backporter@example.com>\n"


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
