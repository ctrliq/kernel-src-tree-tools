from kt.ktlib.ciq_helpers import CIQ_cherry_pick_commit_standardization

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
