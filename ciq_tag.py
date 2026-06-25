import os
import sys
from enum import Enum
import logging
import more_itertools as mit
import re
import textwrap
from typing import List, Tuple, Optional, Dict

DEFAULT_LOGLEVEL = "INFO"

LOGLEVEL = os.environ.get("LOGS", DEFAULT_LOGLEVEL).upper()
logger = logging.getLogger(__name__)
logger.propagate = False
logger.setLevel(LOGLEVEL)
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(funcName)s: %(message)s"))
logger.addHandler(log_handler)


def basic_regex_seeker(regex):
    def seeker(string):
        logger.debug(f"Searched text: {repr(string)}")
        logger.debug(f"Regex: {repr(regex)}")
        m = re.search(regex, string)
        logger.debug(f"Result: {m}")
        return (m.start(), m.end()) if m else None

    return seeker


def keyword_regex_seeker(keyword_regex):
    def seeker(string):
        logger.debug(f"Searched text: {repr(string)}")
        logger.debug(f"Regex: {repr(keyword_regex)}")
        m = re.search(keyword_regex, string, re.MULTILINE)
        logger.debug(f"Result: {m}")
        return (m.start(), m.end(1), m.end()) if m else None

    return seeker


def tokens_list_regex(tokens: List[str]):
    """
    Match the keyword from the list and the subsequent whitespace separator.
    The token is in the group 1.
    """
    return "^(" + "|".join(re.escape(token) for token in tokens) + r"):?[ \t]+"


DEFAULT_KEYWORD_SEPARATOR = " "

DEAFAULT_MULTILINE_BOUNDARY_SEEKER = basic_regex_seeker(r"\n\s*\n")
DEAFAULT_MULTILINE_BOUNDARY = "\n\n"

DEAFAULT_SINGLELINE_BOUNDARY_SEEKER = basic_regex_seeker(r"\n")
DEAFAULT_SINGLELINE_BOUNDARY = "\n"


class CiqTag(Enum):
    # The order of entries here defines the default order in the commit message for newly inserted
    # properties

    # The order of the keywords designating the same property is not important except for the first
    # one - it will be used as the primary keyword when inserting new property, also as a the tag
    # identifier in the command line tool

    JIRA = ["jira"]
    SUBSYSTEM_SYNC = ["subsystem-sync"]
    SUBSYSTEM_UPDATE = ["subsystem-update"]
    CVE = ["cve"]
    CVE_BUGFIX = ["cve-bf", "cve-bugfix", "cve-update"]
    CVE_PREREQ = ["cve-pre", "cve-prereq", "cve-dep", "cve-preq"]
    REBUILD_HISTORY = ["Rebuild_History"]
    REBUILD_CHGLOG = ["Rebuild_CHGLOG"]
    REBUILD_FUZZ = ["Rebuild_FUZZ"]
    COMMIT_AUTHOR = ["commit-author"]
    COMMIT = ["commit"]
    EMPTY_COMMIT = (["Empty-Commit"], True)
    UPSTREAM_DIFF = (["upstream-diff"], True)

    def __init__(self, keywords: List[str], multiline: bool = False):
        if len(keywords) == 0:
            raise ValueError("Keywords lits must have at least one elemnt")
        self.arg_name = keywords[0]
        self.keywords = keywords
        self.default_keyword = keywords[0]
        self.multiline = multiline
        self.keyword_seeker = keyword_regex_seeker(tokens_list_regex(keywords))
        self.default_separator = DEFAULT_KEYWORD_SEPARATOR
        (self.boundary_seeker, self.default_value_boundary) = (
            (DEAFAULT_MULTILINE_BOUNDARY_SEEKER, DEAFAULT_MULTILINE_BOUNDARY)
            if multiline
            else (DEAFAULT_SINGLELINE_BOUNDARY_SEEKER, DEAFAULT_SINGLELINE_BOUNDARY)
        )

    @classmethod
    def get_by_arg_name(cls, arg_name: str):
        return mit.first_true(cls, pred=lambda elem: elem.arg_name == arg_name, default=None)

    def get_keywords_dict(self):
        return {k: self for k in self.keywords}

    def get_order_num(self):
        if not hasattr(self, "order_num_cache"):
            self.order_num_cache = list(type(self)).index(self)
        return self.order_num_cache


class TagPosition:
    def __init__(self, tag, keyword_start, keyword_end, separator_end, boundary_start, boundary_end):
        if not keyword_start >= 0:
            raise ValueError("keyword_start < 0")
        if not keyword_start <= keyword_end:
            raise ValueError("keyword_start > keyword_end")
        if not keyword_end <= separator_end:
            raise ValueError("keyword_end > separator_end")
        if not separator_end <= boundary_start:
            raise ValueError("separator_end > boundary_start")
        if not boundary_start < boundary_end:
            raise ValueError("boundary_start >= boundary_end")
        self.tag = tag
        self.keyword_start = keyword_start
        self.keyword_end = keyword_end
        self.separator_end = separator_end
        self.boundary_start = boundary_start
        self.boundary_end = boundary_end

    def shift(self, offset):
        return TagPosition(
            self.tag,
            offset + self.keyword_start,
            offset + self.keyword_end,
            offset + self.separator_end,
            offset + self.boundary_start,
            offset + self.boundary_end,
        )


# Low-level tag location funcs #####################################################################


def get_first_tag_position(message: str, tag: CiqTag, empty_on_no_value: bool = False) -> Optional[TagPosition]:
    logger.debug(f"Message: {repr(message)}")
    keyword = tag.keyword_seeker(message)
    if keyword:
        kw_start, kw_end, sep_end = keyword
        logger.debug(f"Found keyword: {repr(message[kw_start:kw_end])}")
        logger.debug(f"Found separator: {repr(message[kw_end:sep_end])}")
        rest_of_message = message[sep_end:]
        boundary = tag.boundary_seeker(rest_of_message)
        if boundary:
            boundary_start, boundary_end = boundary
            logger.debug(f"Found value: {repr(rest_of_message[:boundary_start])}")
            logger.debug(f"Found boundary: {repr(rest_of_message[boundary_start:boundary_end])}")
            return TagPosition(tag, kw_start, kw_end, sep_end, sep_end + boundary_start, sep_end + boundary_end)
        else:
            logger.error(
                f"No value found after the '{keyword[kw_start:kw_end]}' "
                + f"keyword while extracting '{tag.arg_name}' property"
            )
            if empty_on_no_value:
                return None
            else:
                return TagPosition(tag, kw_start, kw_end, sep_end, sep_end, sep_end)
    else:
        logger.debug(f"No keyword for the tag {tag} found")
        return None


def get_tag_positions(message: str, tag: CiqTag, empty_on_no_value: bool = False) -> List[TagPosition]:
    cursor = 0
    result = []
    while position := get_first_tag_position(message[cursor:], tag, empty_on_no_value=empty_on_no_value):
        result += [position.shift(cursor)]
        cursor += position.boundary_end
    return result


def get_all_tags_positions(message: str) -> List[TagPosition]:
    return sorted(
        (position for ct in CiqTag for position in get_tag_positions(message, ct)),
        key=lambda position: position.keyword_start,
    )


# Utils ############################################################################################


def indent_tag_value(value: str, indent: int) -> str:
    if indent > 0:
        lines = value.split("\n")
        return "\n".join([lines[0]] + [" " * indent + line for line in lines[1:]])
    else:
        return value


def format_tag(
    tag: CiqTag,
    keyword_and_separator: str,
    value: str,
    indent_arg: int,
    wrap: bool,
    wrap_width: int,
    suspend_ignore_warns: bool = False,
) -> str:
    """Preserve _keyword_and_separator in the returned property"""
    if tag.multiline:
        indent = indent_arg if indent_arg >= 0 else len(keyword_and_separator)
        if wrap:
            n = len(keyword_and_separator)
            wrapped_value = textwrap.fill(
                "x" * n + value, width=wrap_width, initial_indent="", subsequent_indent=" " * indent
            )
            formatted_value = wrapped_value[n:]
        else:
            formatted_value = indent_tag_value(value, indent)
    else:
        if not suspend_ignore_warns:
            if indent_arg != 0:
                logger.warning(
                    f"Non-zero indenting requested for a single line property '{tag.arg_name}'. " + "Ignoring"
                )
            if wrap:
                logger.warning(f"Wrapping requested for a single line property '{tag.arg_name}'. " + "Ignoring")
        formatted_value = value
    return formatted_value


def omit_prefixing_empty_lines(string: str) -> str:
    # Match all the prefixing empty lines '([\s^\n]*\n)*', then everything else '(.*)'
    # The empty lines will be omitted.
    m = re.match(r"^(([\s^\n]*\n)*)(.*)$", string, re.DOTALL)
    if m is None:
        raise ValueError("Input string does not match the expected format.")
    return m[3]


def split_subject_body(text: str):
    n = text.find("\n")
    if n == -1:
        raise Exception(f"Message '{text}' doesn't follow the format of a git commit message")
    m = re.match(r"^([\s^\n]*\n)(.*)$", text[n:], re.DOTALL)
    if m is None:
        raise Exception(f"Message '{text}' doesn't follow the format of a git commit message")
    return (text[:n], m[2])


def unwrap_text(text: str) -> str:
    return textwrap.fill(text, width=sys.maxsize)


def dedent_text(text: str) -> str:
    n = text.find("\n")
    first, rest = (text, "") if n == -1 else (text[:n], text[n:])
    return textwrap.dedent(first) + textwrap.dedent(rest)


# Elementary operations ############################################################################

DEFAULT_INDENT = 0
DEFAULT_WRAP = False
DEFAULT_WRAP_WIDTH = 72


def tag_value_boundary_check(tag, value):
    if m := tag.boundary_seeker(value):
        logger.warning(
            f"Value '{value}' for tag '{tag}' contains boundary "
            + f"'{value[m[0] : m[1]]}'. The tag won't parse properly"
        )


class TagInstance:
    def __init__(self, tag_type: CiqTag, keyword: str, separator: str, value: str, boundary: str):
        self._tag_type = tag_type
        self._keyword = keyword
        self._separator = separator
        self._boundary = boundary
        self.set_value(value)

    def get_keyword_and_sep(self):
        return self._keyword + self._separator

    def set_value(self, value: str):
        tag_value_boundary_check(self._tag_type, value)
        self._value = value

    def __str__(self):
        return self._keyword + self._separator + self._value + self._boundary


class CiqMsg:
    def __init__(self, message: str):
        """
        message: Git commit's message as printed with the %B format
        """
        if message is None:
            raise ValueError("message cannot be None")
        self._message_subject, body = split_subject_body(message)
        groups_of_consecutive_tags = list(
            mit.split_when(get_all_tags_positions(body), lambda p, n: p.boundary_end < n.keyword_start)
        )
        tags_positions_group = (
            # Reject tags falling outside of the continuous tags block at the beginning of message's
            # body - they aren't actually tags (eg. see the message of
            # 081056dc00a27bccb55ccc3c6f230a3d5fd3f7e0)
            groups_of_consecutive_tags[0]
            if groups_of_consecutive_tags and groups_of_consecutive_tags[0][0].keyword_start == 0
            else []
        )
        self._tags = [
            TagInstance(
                p.tag,
                body[p.keyword_start : p.keyword_end],
                body[p.keyword_end : p.separator_end],
                body[p.separator_end : p.boundary_start],
                body[p.boundary_start : p.boundary_end],
            )
            for p in tags_positions_group
        ]
        self._tags_dict = self.tags_dict()
        self._message_body = omit_prefixing_empty_lines(
            body[tags_positions_group[-1].boundary_end :] if tags_positions_group else body
        )

    def get_message(self):
        return (
            self._message_subject
            + "\n\n"
            + "".join(str(t) for t in self._tags)
            + self.get_tags_block_sep()
            + self._message_body
        )

    def get_tags_block_sep(self):
        return "\n" if self._tags and not self._tags[-1]._tag_type.multiline else ""

    def tags_dict(self) -> Dict[CiqTag, List[Tuple[int, TagInstance]]]:
        buckets = mit.bucket(enumerate(self._tags), lambda index_tag: index_tag[1]._tag_type)
        return {tag: list(buckets[tag]) for tag in buckets}

    def get_indexed_tag_inst(self, tag: CiqTag, index: int = 0) -> Tuple[int, TagInstance]:
        return self._tags_dict[tag][index] if tag in self._tags_dict and index < len(self._tags_dict[tag]) else None

    def get_tag_value(self, tag: CiqTag, index: int = 0, unwrap: bool = False, dedent: bool = False) -> Optional[str]:
        index_tag_inst = self.get_indexed_tag_inst(tag, index)
        if index_tag_inst:
            value = index_tag_inst[1]._value
            if unwrap:
                return unwrap_text(dedent_text(value))
            elif dedent:
                return dedent_text(value)
            else:
                return value
        else:
            return None

    def modify_tag_value(
        self,
        modified_tag: CiqTag,
        value: str,
        index: int = 0,
        *,
        indent: int = DEFAULT_INDENT,
        wrap: bool = DEFAULT_WRAP,
        wrap_width: int = DEFAULT_WRAP_WIDTH,
        suspend_ignore_warns: bool = False,
    ) -> bool:
        indexed_tag_inst = self.get_indexed_tag_inst(modified_tag, index)
        if indexed_tag_inst:
            _, tag_inst = indexed_tag_inst
            tag_inst.set_value(
                format_tag(
                    modified_tag,
                    tag_inst.get_keyword_and_sep(),
                    value,
                    indent,
                    wrap,
                    wrap_width,
                    suspend_ignore_warns=suspend_ignore_warns,
                )
            )
            return True
        else:
            return False

    def add_tag(
        self,
        inserted_tag: CiqTag,
        value: str,
        *,
        indent: int = DEFAULT_INDENT,
        wrap: bool = DEFAULT_WRAP,
        wrap_width: int = DEFAULT_WRAP_WIDTH,
        suspend_ignore_warns: bool = False,
    ) -> bool:
        # Find the first property which is 'greater' than inserted_tag in the sense that it appears
        # later in the CiqTag enum dictating the order in which properties are expected to occur
        # in a message. The inserted_tag will be inserted right before it, if it exists, or right after
        # the last existing property, if any exists, or at the begginging of the message body otherwise.
        first_greater = mit.first_true(
            range(len(self._tags)),
            pred=lambda i: inserted_tag.get_order_num() < self._tags[i]._tag_type.get_order_num(),
            default=len(self._tags),
        )
        self._tags.insert(
            first_greater,
            TagInstance(
                inserted_tag,
                inserted_tag.default_keyword,
                inserted_tag.default_separator,
                format_tag(
                    inserted_tag,
                    inserted_tag.default_keyword + inserted_tag.default_separator,
                    value,
                    indent,
                    wrap,
                    wrap_width,
                    suspend_ignore_warns=suspend_ignore_warns,
                ),
                inserted_tag.default_value_boundary,
            ),
        )
        self._tags_dict = self.tags_dict()
        return True

    def set_tag(
        self,
        tag: CiqTag,
        value: str,
        index: int = 0,
        *,
        indent: int = DEFAULT_INDENT,
        wrap: bool = DEFAULT_WRAP,
        wrap_width: int = DEFAULT_WRAP_WIDTH,
        suspend_ignore_warns: bool = False,
    ) -> bool:
        return self.modify_tag_value(
            tag,
            value,
            index,
            indent=indent,
            wrap=wrap,
            wrap_width=wrap_width,
            suspend_ignore_warns=suspend_ignore_warns,
        ) or self.add_tag(
            tag, value, indent=indent, wrap=wrap, wrap_width=wrap_width, suspend_ignore_warns=suspend_ignore_warns
        )

    def delete_tag(self, deleted_tag: CiqTag, index: int = 0) -> bool:
        indexed_tag_inst = self.get_indexed_tag_inst(deleted_tag, index)
        if indexed_tag_inst:
            ip, tag_inst = indexed_tag_inst
            del self._tags[ip]
            self._tags_dict = self.tags_dict()
            return True
        else:
            return False


# Exported symbols #################################################################################

__all__ = [
    "CiqTag",
    "TagPosition",
    # Low-level functions, may be useful in some scenarios
    "get_first_tag_position",
    "get_tag_positions",
    "get_all_tags_positions",
    # Core high-level functionality
    "CiqMsg",
    "DEFAULT_INDENT",
    "DEFAULT_WRAP",
    "DEFAULT_WRAP_WIDTH",
]
