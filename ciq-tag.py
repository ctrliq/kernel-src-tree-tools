#!/usr/bin/env python3

import ciq_tag
import click
import os
from enum import Enum
import sys
import logging

DEFAULT_LOGLEVEL = "INFO"

LOGLEVEL = os.environ.get("LOGS", DEFAULT_LOGLEVEL).upper()
logger = logging.getLogger(__name__)
logger.propagate = False
logger.setLevel(LOGLEVEL)
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(funcName)s: %(message)s"))
logger.addHandler(log_handler)


CIQ_TAGS_LIST = ", ".join(c.arg_name for c in ciq_tag.CiqTag)


class CmdException(Exception):
    def __init__(self, exit_code, *rest):
        super().__init__(*rest)
        self._exit_code = exit_code


def open_input(filename, **rest):
    return sys.stdin if filename == "-" else open(filename, "r", **rest)


def open_output(filename, **rest):
    return sys.stdout if filename == "-" else open(filename, "w", **rest)


def process_in_out(input, output, result_to_output_map, ciq_msg_method, *method_args_pos, **method_args_key):
    with open_input(input) as in_file:
        input_str = "".join(in_file.readlines())
        with open_output(output) as out_file:
            msg = ciq_tag.CiqMsg(input_str)
            ret, out = result_to_output_map(msg, ciq_msg_method(msg, *method_args_pos, **method_args_key))
            if out:
                print(out, file=out_file, end="")
            if ret != 0:
                raise CmdException(ret)


def parse_tag(tag_name):
    tag = ciq_tag.CiqTag.get_by_arg_name(tag_name)
    if tag:
        return tag
    else:
        raise CmdException(1, f"Wrong TAG value. Must be one of: {CIQ_TAGS_LIST}")


def read_value(value_arg, val_from_file_arg, trim_arg):
    if val_from_file_arg:
        with open_input(value_arg) as inFile:
            value = "".join(inFile.readlines())
    else:
        value = value_arg
    return value.strip() if trim_arg else value


def getter_map(msg, result):
    return (0, result + "\n") if result else (1, "")


def setter_map(msg, modified):
    out = msg.get_message()
    return (0, out) if modified else (1, out)


def args(*positional, **keyword):
    return (positional, keyword)


class ClickDef(Enum):
    TAG = args("tag", type=str)

    VALUE = args("value", type=str)

    INDEX = args("index", type=int, required=False, default=0)

    VAL_FROM_FILE = args(
        "--val-from-file",
        "-f",
        flag_value=True,
        help="""
Treat the VALUE argument as a path to a file from which an actual value will be read (useful for
multi-line formatted texts)
""",
    )

    TRIM = args(
        "--trim",
        "-t",
        flag_value=(not ciq_tag.DEFAULT_TRIM),
        help="""
Trim the value from whitespaces at the beginning and end before inserting to a commit message as a
tag value. Useful when reading the tag value from a file, which can have trailing newlines
""",
    )

    INDENT = args(
        "--indent",
        "-t",
        type=int,
        default=ciq_tag.DEFAULT_INDENT,
        help="""
When inserting multi-line values indent them by this many spaces. Special value -1 means value
indenting equal to the width of the tag keyword.
""",
    )

    DEDENT = args("--dedent", "-T", flag_value=True, help="For the multi-line value remove the indent, if it has any.")

    WRAP = args("--wrap", "-w", flag_value=(not ciq_tag.DEFAULT_INDENT), help="Enable value wrapping")

    UNWRAP = args("--unwrap", "-W", flag_value=True, help="Unwrap multi-line values to a single line. Implies DEDENT.")

    WRAP_WIDTH = args(
        "--wrap-width",
        "-c",
        type=int,
        default=ciq_tag.DEFAULT_WRAP_WIDTH,
        help="If WRAP flag is given wrap the value text to this many columns.",
    )

    def __init__(self, positional, keyword):
        self.positional = positional
        self.keyword = keyword


OPTIONS = {}


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "--input", "-i", type=click.Path(), default="-", show_default=True, help="File path to read, or '-' for stdin"
)
@click.option(
    "--output", "-o", type=click.Path(), default="-", show_default=True, help="File path to write, or '-' for stdout"
)
def cli(input, output):
    OPTIONS["input"] = input
    OPTIONS["output"] = output


@cli.command(
    "get",
    help=f"""
Print to the output (--output) the value of the INDEXth TAG in the commit message given on
the input (--input). If INDEX is not given assume it's 0, which is the first occurence of
the TAG. Exit with nonzero if TAG not found. TAG can be one of: {CIQ_TAGS_LIST}
""",
)
@click.argument(*ClickDef.TAG.positional, **ClickDef.TAG.keyword)
@click.argument(*ClickDef.INDEX.positional, **ClickDef.INDEX.keyword)
@click.option(*ClickDef.UNWRAP.positional, **ClickDef.UNWRAP.keyword)
@click.option(*ClickDef.DEDENT.positional, **ClickDef.DEDENT.keyword)
def command_get(tag, index, unwrap, dedent):
    process_in_out(
        OPTIONS["input"],
        OPTIONS["output"],
        getter_map,
        ciq_tag.CiqMsg.get_tag_value,
        parse_tag(tag),
        index,
        unwrap=unwrap,
        dedent=dedent,
    )


@cli.command(
    "modify",
    help="""
Set the value of TAG, in its current place, using the current keyword. Return nonzero if the TAG
wasn't defined already.
""",
)
@click.argument(*ClickDef.TAG.positional, **ClickDef.TAG.keyword)
@click.argument(*ClickDef.VALUE.positional, **ClickDef.VALUE.keyword)
@click.argument(*ClickDef.INDEX.positional, **ClickDef.INDEX.keyword)
@click.option(*ClickDef.VAL_FROM_FILE.positional, **ClickDef.VAL_FROM_FILE.keyword)
@click.option(*ClickDef.TRIM.positional, **ClickDef.TRIM.keyword)
@click.option(*ClickDef.INDENT.positional, **ClickDef.INDENT.keyword)
@click.option(*ClickDef.WRAP.positional, **ClickDef.WRAP.keyword)
@click.option(*ClickDef.WRAP_WIDTH.positional, **ClickDef.WRAP_WIDTH.keyword)
def command_modify(tag, value, index, val_from_file, trim, indent, wrap, wrap_width):
    process_in_out(
        OPTIONS["input"],
        OPTIONS["output"],
        setter_map,
        ciq_tag.CiqMsg.modify_tag_value,
        parse_tag(tag),
        read_value(value, val_from_file, trim),
        index,
        trim=trim,
        indent=indent,
        wrap=wrap,
        wrap_width=wrap_width,
    )


@cli.command(
    "add",
    help="""
Add a TAG with VALUE to the commit message. Attempt to locate the proper place to insert the tag then do it
using the default keyword and value formatting defined by the options.
""",
)
@click.argument(*ClickDef.TAG.positional, **ClickDef.TAG.keyword)
@click.argument(*ClickDef.VALUE.positional, **ClickDef.VALUE.keyword)
@click.option(*ClickDef.VAL_FROM_FILE.positional, **ClickDef.VAL_FROM_FILE.keyword)
@click.option(*ClickDef.TRIM.positional, **ClickDef.TRIM.keyword)
@click.option(*ClickDef.INDENT.positional, **ClickDef.INDENT.keyword)
@click.option(*ClickDef.WRAP.positional, **ClickDef.WRAP.keyword)
@click.option(*ClickDef.WRAP_WIDTH.positional, **ClickDef.WRAP_WIDTH.keyword)
def command_add(tag, value, val_from_file, trim, indent, wrap, wrap_width):
    process_in_out(
        OPTIONS["input"],
        OPTIONS["output"],
        setter_map,
        ciq_tag.CiqMsg.add_tag,
        parse_tag(tag),
        read_value(value, val_from_file, trim),
        trim=trim,
        indent=indent,
        wrap=wrap,
        wrap_width=wrap_width,
    )


@cli.command(
    "set",
    help="""
Attempt to set TAG to the VALUE in place as it would be done with the 'modify' action, using INDEX
(default 0). If that fails insert it as with the 'add' action.
""",
)
@click.argument(*ClickDef.TAG.positional, **ClickDef.TAG.keyword)
@click.argument(*ClickDef.VALUE.positional, **ClickDef.VALUE.keyword)
@click.argument(*ClickDef.INDEX.positional, **ClickDef.INDEX.keyword)
@click.option(*ClickDef.VAL_FROM_FILE.positional, **ClickDef.VAL_FROM_FILE.keyword)
@click.option(*ClickDef.TRIM.positional, **ClickDef.TRIM.keyword)
@click.option(*ClickDef.INDENT.positional, **ClickDef.INDENT.keyword)
@click.option(*ClickDef.WRAP.positional, **ClickDef.WRAP.keyword)
@click.option(*ClickDef.WRAP_WIDTH.positional, **ClickDef.WRAP_WIDTH.keyword)
def command_set(tag, value, index, val_from_file, trim, indent, wrap, wrap_width):
    process_in_out(
        OPTIONS["input"],
        OPTIONS["output"],
        setter_map,
        ciq_tag.CiqMsg.set_tag,
        parse_tag(tag),
        read_value(value, val_from_file, trim),
        index,
        trim=trim,
        indent=indent,
        wrap=wrap,
        wrap_width=wrap_width,
    )


@cli.command(
    "delete",
    help="""
Delete a tag from the commit message. Attempt to keep the message formatted nicely.
""",
)
@click.argument(*ClickDef.TAG.positional, **ClickDef.TAG.keyword)
@click.argument(*ClickDef.INDEX.positional, **ClickDef.INDEX.keyword)
def command_delete(tag, index):
    process_in_out(
        OPTIONS["input"],
        OPTIONS["output"],
        setter_map,
        ciq_tag.CiqMsg.delete_tag,
        ciq_tag.CiqTag.get_by_arg_name(tag),
        index,
    )


def main():
    try:
        cli()
        return 0
    except CmdException as exc:
        logger.error(str(exc))
        return exc._exit_code


if __name__ == "__main__":
    exit(main())
