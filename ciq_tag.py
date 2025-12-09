#!/usr/bin/env python3

import os
import sys
import argparse
from enum import Enum
import logging
import more_itertools as mit
import re
import textwrap
import bisect
from typing import List, Tuple, Optional, Iterable

DEFAULT_LOGLEVEL = "INFO"

LOGLEVEL = os.environ.get("LOGS", DEFAULT_LOGLEVEL).upper()
logger = logging.getLogger(__name__)
logger.propagate = False
logger.setLevel(LOGLEVEL)
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(funcName)s: %(message)s"))
logger.addHandler(log_handler)

####################################################################################################
#                                              Library                                             #
####################################################################################################


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

DEAFAULT_MULTILINE_BOUNDARY_SEEKER = basic_regex_seeker(r"(\n\s*\n|$)")
DEAFAULT_MULTILINE_BOUNDARY = "\n\n"

DEAFAULT_SINGLELINE_BOUNDARY_SEEKER = basic_regex_seeker(r"(\n|$)")
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
        assert len(keywords) > 0
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

    def get_order_num(self):
        if not hasattr(self, "order_num_cache"):
            self.order_num_cache = list(type(self)).index(self)
        return self.order_num_cache


class TagPosition:
    def __init__(self, tag, keyword_start, keyword_end, separator_end, boundary_start, boundary_end):
        assert keyword_start >= 0
        assert keyword_start <= keyword_end
        assert keyword_end <= separator_end
        assert separator_end <= boundary_start
        assert boundary_start < boundary_end
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


def get_first_tag_position(message: str, tag: CiqTag, empty_on_no_value: bool = False) -> Optional[CiqTag]:
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


def get_indexed_tag_position(
    message: str, tag: CiqTag, index: int = 0, empty_on_no_value: bool = False
) -> Optional[CiqTag]:
    assert index >= 0
    cursor = 0
    i = 0
    while position := get_first_tag_position(message[cursor:], tag, empty_on_no_value=empty_on_no_value):
        if i == index:
            return position.shift(cursor)
        cursor += position.boundary_end
        i += 1
    return None


def get_tag_positions(message: str, tag: CiqTag, empty_on_no_value: bool = False) -> List[CiqTag]:
    cursor = 0
    result = []
    while position := get_first_tag_position(message[cursor:], tag, empty_on_no_value=empty_on_no_value):
        result += [position.shift(cursor)]
        cursor += position.boundary_end
    return result


def get_all_tags_positions(message: str) -> List[CiqTag]:
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
    tag: CiqTag, keyword_and_separator: str, value: str, trim: bool, indent_arg: int, wrap: bool, wrap_width: int
) -> str:
    """Preserve _keyword_and_separator in the returned property"""
    trimmed_value = value.strip() if trim else value
    if tag.multiline:
        indent = indent_arg if indent_arg >= 0 else len(keyword_and_separator)
        if wrap:
            n = len(keyword_and_separator)
            wrapped_value = textwrap.fill(
                "x" * n + trimmed_value, width=wrap_width, initial_indent="", subsequent_indent=" " * indent
            )
            formatted_value = wrapped_value[n:]
        else:
            formatted_value = indent_tag_value(trimmed_value, indent)
    else:
        if indent_arg != 0:
            logger.warning(f"Non-zero indenting requested for a single line property '{tag.arg_name}'. " + "Ignoring")
        if wrap:
            logger.warning(f"Wrapping requested for a single line property '{tag.arg_name}'. " + "Ignoring")
        formatted_value = trimmed_value
    return keyword_and_separator + formatted_value


def omit_prefixing_empty_lines(string: str) -> str:
    # Match all the prefixing empty lines '([\s^\n]*\n)*', then everything else '(.*)'
    # The empty lines will be omitted.
    m = re.match(r"^(([\s^\n]*\n)*)(.*)$", string, re.DOTALL)
    assert m is not None
    return m[3]


def split_first_line(text: str) -> Tuple[str, str]:
    n = text.find("\n")
    return (text, "") if n == -1 else (text[:n], text[n:])


def unwrap_text(text: str) -> str:
    return textwrap.fill(text, width=sys.maxsize)


def dedent_text(text: str) -> str:
    first, rest = split_first_line(text)
    return textwrap.dedent(first) + textwrap.dedent(rest)


def conditional_action(switch: bool, func, arg):
    return func(arg) if switch else arg


def process_value(value: str, unwrap: bool, dedent: bool) -> str:
    return conditional_action(unwrap, unwrap_text, conditional_action(True if unwrap else dedent, dedent_text, value))


# Elementary operations ############################################################################

DEFAULT_TRIM = False
DEFAULT_INDENT = 0
DEFAULT_WRAP = False
DEFAULT_WRAP_WIDTH = 72

#
# Getting a tag value
#


def get_tag_value(message: str, tag: CiqTag, index: int = 0) -> str:
    pos = get_indexed_tag_position(message, tag, index)
    if pos:
        return message[pos.separator_end : pos.boundary_start]
    else:
        return None


#
# Modifying existing tag's value
#


def modify_tag_value(
    message: str,
    tag: CiqTag,
    value: str,
    index: int = 0,
    *,
    trim: bool = DEFAULT_TRIM,
    indent: int = DEFAULT_INDENT,
    wrap: bool = DEFAULT_WRAP,
    wrap_width: int = DEFAULT_WRAP_WIDTH,
) -> Tuple[bool, str]:
    pos = get_indexed_tag_position(message, tag, index)
    if pos:
        return (
            True,
            (
                message[: pos.keyword_start]
                + format_tag(tag, message[pos.keyword_start : pos.separator_end], value, trim, indent, wrap, wrap_width)
                + message[pos.boundary_start :]
            ),
        )
    else:
        return (False, message)


#
# Adding a new tag
#


def get_tag_insert_position_and_boundary(message: str, inserted_tag: CiqTag) -> Tuple[int, str]:
    properties = get_all_tags_positions(message)
    # Find the first property which is 'greater' than inserted_tag in the sense that it appears
    # later in the CiqTag enum dictating the order in which properties are expected to occur
    # in a message. The inserted_tag will be inserted right before it, if it exists, or right after
    # the last existing property, if any exist, or at the begginging of the message body otherwise.
    first_greater = mit.first_true(
        properties, pred=lambda prop: (inserted_tag.get_order_num() < prop.tag.get_order_num()), default=None
    )
    if properties:
        if first_greater:
            pos = first_greater.keyword_start
            boundary = inserted_tag.default_value_boundary
        else:
            pos = properties[-1].boundary_end
            if properties[-1].tag.multiline:
                if inserted_tag.multiline:
                    boundary = inserted_tag.default_value_boundary
                else:
                    # Assumes that there is some text after the last property to separate from,
                    # which doesn't have to be true, but simplifies the algorithm a lot
                    boundary = inserted_tag.default_value_boundary + DEAFAULT_SINGLELINE_BOUNDARY
            else:
                if inserted_tag.multiline:
                    boundary = DEAFAULT_SINGLELINE_BOUNDARY
                else:
                    boundary = inserted_tag.default_value_boundary
    else:
        subject_and_body = split_first_line(message)
        assert subject_and_body, f"Can't split '{message}' into subject and body"
        pos = len(subject_and_body[0]) + 2
        if inserted_tag.multiline:
            boundary = inserted_tag.default_value_boundary
        else:
            boundary = inserted_tag.default_value_boundary + DEAFAULT_SINGLELINE_BOUNDARY
    return (pos, boundary)


def add_tag(
    message: str,
    tag: CiqTag,
    value: str,
    *,
    trim: bool = DEFAULT_TRIM,
    indent: int = DEFAULT_INDENT,
    wrap: bool = DEFAULT_WRAP,
    wrap_width: int = DEFAULT_WRAP_WIDTH,
) -> Tuple[bool, str]:
    pos, boundary = get_tag_insert_position_and_boundary(message, tag)
    return (
        True,
        (
            message[:pos]
            + format_tag(tag, tag.default_keyword + tag.default_separator, value, trim, indent, wrap, wrap_width)
            + boundary
            + message[pos:]
        ),
    )


#
# Setting a tag (attempt to modify, then to add)
#


def set_tag(
    message: str,
    tag: CiqTag,
    value: str,
    index: int = 0,
    *,
    trim: bool = DEFAULT_TRIM,
    indent: int = DEFAULT_INDENT,
    wrap: bool = DEFAULT_WRAP,
    wrap_width: int = DEFAULT_WRAP_WIDTH,
) -> Tuple[bool, str]:
    modified, new_message = modify_tag_value(
        message, tag, value, index, trim=trim, indent=indent, wrap=wrap, wrap_width=wrap_width
    )
    if modified:
        return (modified, new_message)
    else:
        return add_tag(message, tag, value, trim=trim, indent=indent, wrap=wrap, wrap_width=wrap_width)


#
# Deleting a tag
#


def delete_tag(message: str, deleted_tag: CiqTag, index: int = 0):
    deleted_tag_pos = get_indexed_tag_position(message, deleted_tag, index)
    if deleted_tag_pos:
        # Inserting or deleting a property is nontrivial because of the many border cases associated
        # with empty lines before and after the property. Sometimes they should be preserved,
        # sometiems shrinked, sometimes added. This depends on context whether the neighboring text
        # is another property or not. Mapping all properties in the message may be expensive but
        # it's the simplest way to solve this issue. May be honed in the future if needed.
        tags = get_all_tags_positions(message)
        # Find the deleted property among the list of all properties
        ip = bisect.bisect_left(tags, deleted_tag_pos.keyword_start, key=lambda pos: pos.keyword_start)
        # Establish the relation to other properties
        right_after_another_tag = ip > 0 and tags[ip - 1].boundary_end == deleted_tag_pos.keyword_start
        right_before_another_tag = ip + 1 < len(tags) and deleted_tag_pos.boundary_end == tags[ip + 1].keyword_start
        if right_before_another_tag or (right_after_another_tag and not deleted_tag.multiline):
            # Remove the property along with the boundary. Assuming the message was properly
            # formatted before it will remain so
            return (True, (message[: deleted_tag_pos.keyword_start] + message[deleted_tag_pos.boundary_end :]))
        elif right_after_another_tag and deleted_tag.multiline:
            # Removing multi-line property along with the boundary could glue the follwing text to
            # the properties block. Reset the vertical space to a single empty line
            return (
                True,
                (
                    message[: deleted_tag_pos.keyword_start]
                    + "\n"
                    + omit_prefixing_empty_lines(message[deleted_tag_pos.boundary_end :])
                ),
            )
        else:
            # The lone property case. Make sure not to leave the gaping hole after it's removed.
            return (
                True,
                (
                    message[: deleted_tag_pos.keyword_start]
                    + omit_prefixing_empty_lines(message[deleted_tag_pos.boundary_end :])
                ),
            )
    else:
        return (False, message)


# Exported symbols #################################################################################

__all__ = [
    "CiqTag",
    "TagPosition",
    # Low-level functions, may be useful in some scenarios
    "get_first_tag_position",
    "get_indexed_tag_position",
    "get_tag_positions",
    "get_all_tags_positions",
    # Core high-level functionality
    "get_tag_value",
    "modify_tag_value",
    "add_tag",
    "set_tag",
    "delete_tag",
]

####################################################################################################
#                                         Command-line tool                                        #
####################################################################################################


def overrides(interface_class):
    def overrider(method):
        assert method.__name__ in dir(interface_class)
        return method

    return overrider


# Args handling toolkit ############################################################################


class CmdLineArg:
    def __init__(self, key_name, char_symbol, args):
        self._key_name = key_name
        self._char_symbol = char_symbol
        self._args = args

    def get_base_name(self):
        return self._key_name

    def get_char_symbol(self):
        return self._char_symbol

    def get_parser_names(self):
        raise Exception(f"need to implement 'get_parser_names(…)' for {type(self)}")

    def get_parser_named_args(self):
        return self._args


class CmdLineArgPos(CmdLineArg):
    @overrides(CmdLineArg)
    def get_parser_names(self):
        return (self.get_base_name(),)


class CmdLineArgKey(CmdLineArg):
    def get_long_opt_name(self):
        return self.get_base_name().replace("_", "-")

    def get_short_opt_name(self):
        return self._char_symbol

    def get_long_option(self):
        return f"--{self.get_long_opt_name()}"

    def get_short_option(self):
        return f"-{self.get_short_opt_name()}"

    @overrides(CmdLineArg)
    def get_parser_names(self):
        return (
            (self.get_long_option(), self.get_short_option())
            if self.get_short_opt_name() is not None
            else (self.get_long_option(),)
        )


class ParameterBase:
    def __init__(self, args, help_msg="", default=None, short_name=None):
        self._args = {
            **args,
            **{"default": default, "help": help_msg + (f". Default: '{default}'" if default is not None else "")},
        }
        self._char_symbol = short_name if short_name != "-" else self.name[:1].lower()

    def get_key_name(self):
        """The name used as key to obtain the value of the parameter from
        the result of parser.parse_args()
        """
        return self.name.lower()

    def get_char_symbol(self):
        return self._char_symbol

    def get_val(self, cmd_line_args):
        d = vars(cmd_line_args)
        name = self.get_key_name()
        return d[name] if name in d else None

    def get_val_or_die(self, cmd_line_args):
        v = self.get_val(cmd_line_args)
        if v is not None:
            return v
        else:
            raise Exception(f"{self.name} parameter required")

    def get_pos_arg(self) -> CmdLineArgPos:
        return CmdLineArgPos(self.get_key_name(), self.get_char_symbol(), self._args)

    def get_key_arg(self) -> CmdLineArgKey:
        return CmdLineArgKey(self.get_key_name(), self.get_char_symbol(), self._args)

    def get_arg(self, positional: bool) -> CmdLineArg:
        return self.get_pos_arg() if positional else self.get_key_arg()


class CommandBase:
    def __init__(self, proc_func=None, descr=None, param_instances=None, sub_cmd_set=None):
        self._proc_func = proc_func
        self._descr = descr
        self.param_instances = param_instances
        # self.sub_args = sub_args
        self.sub_cmd_set = sub_cmd_set

    def process(self, args):
        if self._proc_func is not None:
            return self._proc_func(*(param.get_val_or_die(args) for param, _ in self.param_instances))
        else:
            return self.sub_cmd_set.get_by_cmd(vars(args)[self.sub_cmd_set.__name__]).process(args)

    def get_sub_args(self) -> Iterable[CmdLineArg]:
        return (param.get_arg(positional) for param, positional in self.param_instances)

    def get_cmd(self):
        return self.name.lower()

    def get_descr(self):
        return self._descr if isinstance(self._descr, str) else self._descr(self)

    @classmethod
    def get_by_cmd(cls, low_case_name: str):
        return cls[low_case_name.upper()]


# Command line arguments ###########################################################################


class Parameter(ParameterBase, Enum):
    OUTPUT = ({"type": str, "action": "store"}, "File path to write, or '-' for stdout", "-", "o")

    INPUT = ({"type": str, "action": "store"}, "File path to read, or '-' for stdin", "-", "i")

    TAG = (
        {"type": str, "action": "store", "choices": [c.arg_name for c in CiqTag]},
        "Commit meta-data tag, by its typical name",
    )

    VALUE = ({"type": str, "action": "store"}, "Value to set the tag to")

    INDEX = (
        {"type": int, "action": "store", "nargs": "?"},
        ("Which of the tags with the same keyword to operate on. " + "Starting from 0"),
        0,
        "n",
    )

    VAL_FROM_FILE = (
        {"action": "store_true"},
        (
            "Treat the VALUE argument as a path to a file from which "
            + "an actual value will be read (useful for multi-line formatted texts) "
        ),
        False,
        "f",
    )

    TRIM = (
        {"action": "store_true"},
        (
            "Trim the value from whitespaces at the beginning and end before "
            + "inserting to a commit message as a tag value."
            + " Useful when reading the tag value from a file, which can have trailing newlines"
        ),
        False,
        "t",
    )

    INDENT = (
        {"type": int, "action": "store"},
        (
            "When inserting multi-line values indent them by this many spaces."
            + " Special value -1 means value indenting equal to the width of the tag keyword."
        ),
        DEFAULT_INDENT,
        "s",
    )

    WRAP = ({"action": "store_true"}, ("Enable value wrapping"), False, "w")

    WRAP_WIDTH = (
        {"type": int, "action": "store"},
        "If WRAP flag is given wrap the value text to this many columns. ",
        DEFAULT_WRAP_WIDTH,
        "c",
    )

    UNWRAP = ({"action": "store_true"}, ("Unwrap multi-line values to a single line. Implies DEDENT."), False, "W")

    DEDENT = ({"action": "store_true"}, ("For the multi-line value remove the indent, if it has any"), False, "S")


# Commands definition ##############################################################################

#
# Utils
#


def open_input(filename, **rest):
    return sys.stdin if filename == "-" else open(filename, "r", **rest)


def open_output(filename, **rest):
    return sys.stdout if filename == "-" else open(filename, "w", **rest)


def exit_0_if_modified(modificationPair: Tuple[bool, str]) -> Tuple[int, str]:
    return (0 if modificationPair[0] else 1, modificationPair[1])


def read_value(value_arg, val_from_file_arg, trim_arg):
    if val_from_file_arg:
        with open_input(value_arg) as inFile:
            value = "".join(inFile.readlines())
    else:
        value = value_arg
    return value.strip() if trim_arg else value


def process_in_out(p_input, p_output, p_tag, func):
    tag = CiqTag.get_by_arg_name(p_tag)
    with open_input(p_input) as in_file:
        input_str = "".join(in_file.readlines())
        with open_output(p_output) as out_file:
            ret, out = func(tag, input_str)
            if out:
                print(out, file=out_file)
            return ret


def process_in_out_val(p_input, p_output, p_tag, p_value, p_val_from_file, p_trim, func):
    value = read_value(p_value, p_val_from_file, p_trim)
    return process_in_out(p_input, p_output, p_tag, lambda tag, input_str: func(input_str, tag, value))


#
# Commands
#


class CommandRoot(CommandBase, Enum):
    GET = (
        (
            lambda p_input, p_output, p_tag, p_index, p_unwrap, p_dedent: process_in_out(
                p_input,
                p_output,
                p_tag,
                lambda tag, input_str: (
                    (0, process_value(tag_value, p_unwrap, p_dedent))
                    if (tag_value := get_tag_value(input_str, tag, p_index))
                    else (1, "")
                ),
            )
        ),
        "Get value of a given tag. Return nonzero if tag not found",
        [
            (Parameter.INPUT, False),
            (Parameter.OUTPUT, False),
            (Parameter.TAG, True),
            (Parameter.INDEX, True),
            (Parameter.UNWRAP, False),
            (Parameter.DEDENT, False),
        ],
    )

    MODIFY = (
        (
            lambda p_input,
            p_output,
            p_tag,
            p_value,
            p_index,
            p_val_from_file,
            p_trim,
            p_indent,
            p_wrap,
            p_wrap_width: process_in_out_val(
                p_input,
                p_output,
                p_tag,
                p_value,
                p_val_from_file,
                p_trim,
                lambda input_str, tag, value: exit_0_if_modified(
                    modify_tag_value(
                        input_str,
                        tag,
                        value,
                        p_index,
                        trim=p_trim,
                        indent=p_indent,
                        wrap=p_wrap,
                        wrap_width=p_wrap_width,
                    )
                ),
            )
        ),
        (
            "Set tag value, in its current place, using the current keyword. "
            + "Return nonzero if the tag wasn't defined already"
        ),
        [
            (Parameter.INPUT, False),
            (Parameter.OUTPUT, False),
            (Parameter.TAG, True),
            (Parameter.VALUE, True),
            (Parameter.INDEX, True),
            (Parameter.VAL_FROM_FILE, False),
            (Parameter.TRIM, False),
            (Parameter.INDENT, False),
            (Parameter.WRAP, False),
            (Parameter.WRAP_WIDTH, False),
        ],
    )

    ADD = (
        (
            lambda p_input,
            p_output,
            p_tag,
            p_value,
            p_val_from_file,
            p_trim,
            p_indent,
            p_wrap,
            p_wrap_width: process_in_out_val(
                p_input,
                p_output,
                p_tag,
                p_value,
                p_val_from_file,
                p_trim,
                lambda input_str, tag, value: exit_0_if_modified(
                    add_tag(input_str, tag, value, trim=p_trim, indent=p_indent, wrap=p_wrap, wrap_width=p_wrap_width)
                ),
            )
        ),
        (
            "Add a tag to the commit message. "
            + "Attempt to locate the proper place to insert the tag "
            + "then do it using the default keyword and value formatting defined by options"
        ),
        [
            (Parameter.INPUT, False),
            (Parameter.OUTPUT, False),
            (Parameter.TAG, True),
            (Parameter.VALUE, True),
            (Parameter.VAL_FROM_FILE, False),
            (Parameter.TRIM, False),
            (Parameter.INDENT, False),
            (Parameter.WRAP, False),
            (Parameter.WRAP_WIDTH, False),
        ],
    )

    SET = (
        (
            lambda p_input,
            p_output,
            p_tag,
            p_value,
            p_index,
            p_val_from_file,
            p_trim,
            p_indent,
            p_wrap,
            p_wrap_width: process_in_out_val(
                p_input,
                p_output,
                p_tag,
                p_value,
                p_val_from_file,
                p_trim,
                lambda input_str, tag, value: exit_0_if_modified(
                    set_tag(
                        input_str,
                        tag,
                        value,
                        p_index,
                        trim=p_trim,
                        indent=p_indent,
                        wrap=p_wrap,
                        wrap_width=p_wrap_width,
                    )
                ),
            )
        ),
        (
            "Attempt to set the tag value in place as it would be done with the 'modify' action. "
            + "If that fails insert it as with the 'add' action."
        ),
        [
            (Parameter.INPUT, False),
            (Parameter.OUTPUT, False),
            (Parameter.TAG, True),
            (Parameter.VALUE, True),
            (Parameter.INDEX, True),
            (Parameter.VAL_FROM_FILE, False),
            (Parameter.TRIM, False),
            (Parameter.INDENT, False),
            (Parameter.WRAP, False),
            (Parameter.WRAP_WIDTH, False),
        ],
    )

    DELETE = (
        (
            lambda p_input, p_output, p_tag, p_index: process_in_out(
                p_input, p_output, p_tag, lambda tag, input_str: exit_0_if_modified(delete_tag(input_str, tag, p_index))
            )
        ),
        ("Delete a tag from the commit message. " + "Attempt to keep the message formatted nicely."),
        [(Parameter.INPUT, False), (Parameter.OUTPUT, False), (Parameter.TAG, True), (Parameter.INDEX, True)],
    )


def define_parser(parser, commands_set):
    subparsers = parser.add_subparsers(dest=commands_set.__name__, required=True)
    for command in commands_set:
        # command: CommandBase
        subparser = subparsers.add_parser(command.get_cmd(), help=command.get_descr())
        if command.param_instances is not None:
            for c in command.get_sub_args():
                subparser.add_argument(*c.get_parser_names(), **c.get_parser_named_args())
        if command.sub_cmd_set is not None:
            define_parser(subparser, command.sub_cmd_set)
    return parser


def read_args():
    return define_parser(
        argparse.ArgumentParser(
            # formatter_class = argparse.RawDescriptionHelpFormatter,
            description=f"""
Provide CRUD operations for CIQ meta data tags on git commit messages.
Input is always assumed to be in the format produced by 'git log --pretty=%B'.
Control stderr logs with env variable LOGS = DEBUG | INFO | WARNING | ERROR | CRITICAL (default: {DEFAULT_LOGLEVEL}).
"""
        ),
        CommandRoot,
    ).parse_args()


def main():
    args = read_args()
    for c in Parameter:
        logger.debug(f"{c}: {c.get_val(args)}")
    return CommandRoot.get_by_cmd(args.CommandRoot).process(args)


if __name__ == "__main__":
    exit(main())
