from __future__ import annotations

import inspect
import re
from dataclasses import asdict, dataclass
from typing import Optional

from kt.ktlib.ciq_tag import CiqMsg


@dataclass
class CommitHeader:
    """
    Name-field view of the CIQ tag block in a commit message.
    At the moment it represents only commits for cve fixes.
    """

    jira: Optional[str] = None
    # TODO maybe have a union of these cve_bf, cve_pre and cve) idk
    cve: Optional[str] = None
    cve_bf: Optional[str] = None
    cve_pre: Optional[str] = None
    commit_author: Optional[str] = None
    commit: Optional[str] = None
    commit_source: Optional[str] = None
    commit_source_sha: Optional[str] = None
    commit_source_author: Optional[str] = None
    upstream_diff: Optional[str] = None

    # There are a pile of other tags that have not been codified consistently keep them rather than silently
    # dropping them.  Provides the option of using them in the future if needed.
    extras: Optional[dict] = None

    def __post_init__(self):
        # Every value of every tag as parsed: not a dataclass field.  Ignored by asdict()/to_str().
        # populated by from_ciq_msg()
        self._raw_tags: dict = {}

    @classmethod
    def from_dict(cls, env):
        params = inspect.signature(cls).parameters
        known = {k: v for k, v in env.items() if k in params and k != "extras"}
        # CVE numbers are matched case-insensitively upstream and always stored
        # upper-cased (CVE-\d{4}-\d+); tag values with extra prose are kept as-is.
        for key in ("cve", "cve_bf", "cve_pre"):
            value = known.get(key)
            if value and re.fullmatch(r"(?i)cve-\d{4}-\d+", value.strip()):
                known[key] = value.strip().upper()
        extras = {k: v for k, v in env.items() if k not in params and v is not None}
        header = cls(**known)
        if extras:
            header.extras = extras
        return header

    @classmethod
    def from_ciq_msg(cls, ciq_msg: CiqMsg) -> CommitHeader:
        # CiqMsg has multible values for tags and their values. The scalar
        # fields keep the first value; every occurrence is collected in
        # _raw_tags so callers (jiras(), upstream_commits()) can see them all.
        msg_dict = {}
        raw: dict = {}
        for tag, value in ciq_msg._tags_dict.items():
            # TODO a bug here around upstream-diff from CiqMsg, this is an workaround
            if type(tag.value) is tuple:
                name = tag.value[0][0]
            else:
                name = tag.value[0]

            tag_name = name.replace("-", "_")
            for v in value:  # Collect all tags.
                raw.setdefault(tag_name, []).append(v[1]._value)
            msg_dict[tag_name] = raw[tag_name][0]  # use the first value for the tag

        header = cls.from_dict(msg_dict)
        header._raw_tags = raw

        return header

    @classmethod
    def from_commit_body(cls, commit_body: str) -> CommitHeader:
        if commit_body and not commit_body.endswith("\n"):
            commit_body += "\n"
        ciq_msg = CiqMsg(commit_body)
        return cls.from_ciq_msg(ciq_msg=ciq_msg)

    def to_str(self) -> str:
        lines = []
        for key, value in asdict(self).items():
            if key == "extras" or not value:
                continue
            if key == "jira" and "," in value:
                lines += [f"jira {t.strip()}" for t in value.split(",") if t.strip()]
            else:
                lines.append(f"{key.replace('_', '-')} {value}")

        if self.extras:
            lines += [f"{k.replace('_', '-')} {v}" for k, v in self.extras.items()]

        return "\n".join(lines)

    def jiras(self) -> list:
        # Return a list of individual jira tickets. Handles both repeated
        # `jira <ticket>` lines and comma-separated values on one line.
        tickets = []
        for value in self._raw_tags.get("jira", [self.jira]):
            if not value:
                continue
            tickets += [t.strip() for t in value.split(",") if t.strip()]
        return tickets

    def upstream_commits(self) -> list:
        # Return a list of upstream commits in a message, there should NOT be more than one but in the event there is
        # return them all
        if self._raw_tags and "commit" in self._raw_tags:
            return [c for c in self._raw_tags["commit"] if c and c != "-"]
        return [self.commit] if (self.commit and self.commit != "-") else []

    def is_cve(self) -> bool:
        return self.cve or self.cve_bf or self.cve_pre

    # A commit header may have multiple cve tags. But we are interested if it has the cve tag, since that
    # is the commit it represents
    # If not cve tag, check cve-bf or cve-pre
    # we may have situations where a commit has (cve, cve-pre) or (cve, cve-bf) because a deps may be a cve itself, because we do not enforce this, but our current tooling uses only tag
    def cve_number(self) -> str:
        if self.cve:
            return self.cve

        if self.cve_bf:
            return self.cve_bf

        if self.cve_pre:
            return self.cve_pre

    def set_cve(self, cve_number):
        # Make sure only one cve tag is used
        # Our current tooling uses only 1 tag at the moment, but this may change and result in a commit that has 2 cve tags (cve, cve-bf) or (cve, cve-pre) for commits that are deps but cve as well
        original_tags = ", ".join(
            f"{t} {v}" for t, v in (("cve", self.cve), ("cve-bf", self.cve_bf), ("cve-pre", self.cve_pre)) if v
        )
        self.cve_bf = None
        self.cve_pre = None
        self.cve = cve_number
        print(f"CVE {cve_number} for hash {self.commit} and original tags {original_tags}")

    def make_it_cve_bf(self):
        # Interchange cve with cve-bf
        if not self.is_cve():
            return

        # It already has a cve_bf val, it's fine
        if self.cve_bf:
            return

        self.cve_bf = self.cve
        self.cve = None

    def all_cves(self) -> list:
        """Return a list of cve numbers.

        A tag value may list several CVEs comma-separated (cve CVE-1, CVE-2);
        split those into individual numbers.
        """

        cves = []
        for value in (self.cve, self.cve_bf, self.cve_pre):
            if not value:
                continue
            cves += [c.strip() for c in value.split(",") if c.strip()]

        return cves

    def extract_upstream_name_and_sha(self):
        """Return a pair of (commit_source, commit_source_sha) if source is not mainline
        Otherwise returns (None, commit) if the source is mainline
        """

        if self.commit_source_sha:
            return (self.commit_source, self.commit_source_sha)

        if self.commit and self.commit != "-":
            return (None, self.commit)

        return (None, None)
