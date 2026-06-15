from __future__ import annotations

import inspect
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

    @classmethod
    def from_dict(cls, env):
        return cls(**{k: v for k, v in env.items() if k in inspect.signature(cls).parameters})

    @classmethod
    def from_ciq_msg(cls, ciq_msg: CiqMsg) -> CommitHeader:
        # CiqMsg has multible values for tags and their values, that's overkill, we will always use one, the first one
        msg_dict = {}
        for tag, value in ciq_msg._tags_dict.items():
            # TODO a bug here around upstream-diff from CiqMsg, this is an workaround
            if type(tag.value) is tuple:
                name = tag.value[0][0]
            else:
                name = tag.value[0]

            tag_name = name.replace("-", "_")
            tag_value = value[0][1]._value
            msg_dict[tag_name] = tag_value

        return cls(**msg_dict)

    @classmethod
    def from_commit_body(cls, commit_body: str) -> CommitHeader:
        ciq_msg = CiqMsg(commit_body)
        return cls.from_ciq_msg(ciq_msg=ciq_msg)

    def to_str(self) -> str:
        commit_header_dict = asdict(self)
        result = [f"{key.replace('_', '-')} {value}" for key, value in commit_header_dict.items() if value]

        return result

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
        self.cve_bf = None
        self.cve_pre = None
        self.cve = cve_number
        print(f"CVE {cve_number} for hash {self.commit} and original tags {self.print_cve_tags()}")

    def print_cve_tags(self) -> str:
        if not self.is_cve():
            return ""

        # TODO add a priint with the original tag situation
        return ""

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
        """Return a list of cve numbers"""

        cves = []
        if self.cve:
            cves.append(self.cve)

        if self.cve_bf:
            cves.append(self.cve_bf)

        if self.cve_pre:
            cves.append(self.cve_pre)

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
