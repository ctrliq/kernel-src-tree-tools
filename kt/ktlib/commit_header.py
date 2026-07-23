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
    cve: Optional[str] = None
    cve_bf: Optional[str] = None
    cve_pre: Optional[str] = None
    commit: Optional[str] = None
    commit_author: Optional[str] = None
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
