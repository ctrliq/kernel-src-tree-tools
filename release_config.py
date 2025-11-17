#!/usr/bin/env python3
"""
Product to branch mapping from content_release.sh and JIRA field mappings
"""

# JIRA custom field mapping
jira_field_map = {
    "summary": "summary",
    "description": "description",
    "customfield_10380": "CVE",
    "customfield_10404": "Ingested CVSS Vector",
    "customfield_10410": "CVE Ingested Fix",
    "customfield_10382": "sRPM",
    "customfield_10409": "CVE Ingestion Source",
    "customfield_10384": "Ingested CVSS Score",
    "customfield_10386": "Ingested Exploit Status",
    "customfield_10383": "Ingested CVE Impact",
    "customfield_10408": "Package in Priority List",
    "customfield_10411": "CVE Priority",
    "customfield_10390": "CIQ CVE Impact",
    "customfield_10387": "CIQ CVE Score",
    "customfield_10405": "CIQ Score Justification",
    "customfield_10381": "LTS Product",
}

# Product to branch mapping
release_map = {
    "lts-9.4": {"src_git_branch": "ciqlts9_4", "dist_git_branch": "lts94-9", "mock_config": "rocky-lts94"},
    "lts-9.2": {"src_git_branch": "ciqlts9_2", "dist_git_branch": "lts92-9", "mock_config": "rocky-lts92"},
    "lts-8.8": {"src_git_branch": "ciqlts8_8", "dist_git_branch": "lts88-8", "mock_config": "rocky-lts88"},
    "lts-8.6": {"src_git_branch": "ciqlts8_6", "dist_git_branch": "lts86-8", "mock_config": "rocky-lts86"},
    "cbr-7.9": {"src_git_branch": "ciqcbr7_9", "dist_git_branch": "cbr79-7", "mock_config": "centos-cbr79"},
    "fips-9.2": {
        "src_git_branch": "fips-9-compliant/5.14.0-284.30.1",
        "dist_git_branch": "el92-fips-compliant-9",
        "mock_config": "rocky-fips92",
    },
    "fips-8.10": {
        "src_git_branch": "fips-8-compliant/4.18.0-553.16.1",
        "dist_git_branch": "el810-fips-compliant-8",
        "mock_config": "rocky-fips810-553-depot",
    },
    "fips-8.6": {
        "src_git_branch": "fips-8-compliant/4.18.0-553.16.1",
        "dist_git_branch": "el86-fips-compliant-8",
        "mock_config": "rocky-fips86-553-depot",
    },
    "fipslegacy-8.6": {
        "src_git_branch": "fips-legacy-8-compliant/4.18.0-425.13.1",
        "dist_git_branch": "fips-compliant8",
        "mock_config": "rocky-lts86-fips",
    },
}
