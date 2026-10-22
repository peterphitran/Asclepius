import argparse
import json
import sys
from pathlib import Path

from asclepius import __version__
from asclepius.config import load_evaluator, load_target
from asclepius.domain import AppError


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AppError("arguments", "Invalid arguments. Use --help for usage.", 2)


def parser() -> argparse.ArgumentParser:
    result = ArgumentParser(prog="asclepius", description="Local LLM evaluation tool.")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--data-dir", type=Path)
    result.add_argument("--json", action="store_true", dest="json_output")
    commands = result.add_subparsers(dest="command", required=True)
    config = commands.add_parser("config", help="Validate configuration files.")
    config_commands = config.add_subparsers(dest="action", required=True)
    validate = config_commands.add_parser("validate")
    validate.add_argument("path", type=Path)
    validate.add_argument("--kind", choices=("target", "evaluator"), default="target")
    validate.add_argument(
        "--json", action="store_true", dest="json_output", default=argparse.SUPPRESS
    )
    for name in (
        "init",
        "storage",
        "targets",
        "daemon",
        "checks",
        "run",
        "runs",
        "findings",
        "compare",
        "report",
    ):
        command = commands.add_parser(name, help="Planned command; not implemented yet.")
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    json_output = "--json" in args
    try:
        options = parser().parse_args(args)
        if options.command != "config":
            raise AppError("not_implemented", "This command is not implemented yet.")
        loader = load_evaluator if options.kind == "evaluator" else load_target
        loader(options.path)
        if json_output:
            print(json.dumps({"schema_version": 1, "ok": True, "kind": options.kind}))
        else:
            print(f"Valid {options.kind} configuration.")
        return 0
    except AppError as error:
        if json_output:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ok": False,
                        "error": {"code": error.code, "message": str(error)},
                    }
                )
            )
        else:
            print(str(error), file=sys.stderr)
        return error.exit_code
