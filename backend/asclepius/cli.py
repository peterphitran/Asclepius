import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from asclepius import __version__
from asclepius.checks import load_pack, load_pack_plan
from asclepius.config import data_directory, load_evaluator, load_plan, load_target
from asclepius.domain import AppError, RunState
from asclepius.exports import render_report, safe_terminal, write_export
from asclepius.maintenance import migrate_storage
from asclepius.process import (
    WSL_DAEMON_WARNING,
    daemon_status,
    running_under_wsl,
    start_daemon,
    stop_daemon,
)
from asclepius.results import compare_runs
from asclepius.services import EvaluationService
from asclepius.storage import Repository


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
    commands.add_parser("init", help="Initialize a new local SQLite data directory.")
    targets = commands.add_parser("targets", help="Manage application profiles.")
    target_actions = targets.add_subparsers(dest="action", required=True)
    for name in ("add", "edit"):
        action = target_actions.add_parser(name)
        action.add_argument("profile")
        action.add_argument("--config", type=Path, required=True)
    target_list = target_actions.add_parser("list")
    pagination(target_list)
    for name in ("show", "remove"):
        target_actions.add_parser(name).add_argument("profile")
    submit = commands.add_parser("run", help="Queue a complete evaluation plan.")
    submit.add_argument("profile")
    source = submit.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path)
    source.add_argument("--pack")
    submit.add_argument("--evaluator", type=Path, required=True)
    runs = commands.add_parser("runs", help="Inspect and control persisted runs.")
    run_actions = runs.add_subparsers(dest="action", required=True)
    run_list = run_actions.add_parser("list")
    pagination(run_list)
    run_list.add_argument("--profile", help="Stable profile ID, including removed profiles.")
    for name in ("show", "cancel", "retry", "watch"):
        run_actions.add_parser(name).add_argument("run_id")
    findings = commands.add_parser("findings", help="Inspect saved findings.")
    finding_actions = findings.add_subparsers(dest="action", required=True)
    finding_list = finding_actions.add_parser("list")
    finding_list.add_argument("--run", required=True, dest="run_id")
    pagination(finding_list)
    finding_actions.add_parser("show").add_argument("finding_id")
    daemon = commands.add_parser("daemon", help="Manually control the detached queue daemon.")
    daemon_actions = daemon.add_subparsers(dest="action", required=True)
    for name in ("start", "stop"):
        action = daemon_actions.add_parser(name)
        action.add_argument("--timeout", type=float, default=15)
        if name == "start":
            action.add_argument("--config", type=Path)
    daemon_actions.add_parser("status")
    storage = commands.add_parser("storage", help="Explicit stopped-store maintenance.")
    storage.add_subparsers(dest="action", required=True).add_parser("migrate")
    checks = commands.add_parser("checks", help="List built-in checks.")
    listing = checks.add_subparsers(dest="action", required=True).add_parser("list")
    listing.add_argument("--pack", required=True)
    compare = commands.add_parser("compare", help="Compare saved run evidence.")
    compare.add_argument("run_ids", nargs="+")
    report = commands.add_parser("report", help="Export saved run evidence.")
    report.add_argument("run_ids", nargs="+")
    report.add_argument("--format", choices=("json", "markdown", "html"), required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--overwrite", action="store_true")
    return result


def pagination(command: argparse.ArgumentParser) -> None:
    command.add_argument("--limit", type=int, default=50)
    command.add_argument("--cursor")


def emit(data, json_output: bool) -> None:
    content = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    envelope = {"schema_version": 1, "ok": True, "data": content}
    print(
        json.dumps(envelope if json_output else content, indent=None if json_output else 2),
        flush=True,
    )


async def dispatch(options, json_output: bool) -> None:
    repo = Repository(data_directory(options.data_dir))
    service = EvaluationService(repo)
    command = options.command
    if command == "init":
        await repo.initialize()
        data = {"initialized": True}
    elif command == "storage":
        data = {"schema_version": await asyncio.to_thread(migrate_storage, repo.data_dir)}
    elif command == "daemon":
        if options.action == "status":
            data = await asyncio.to_thread(daemon_status, repo.data_dir)
        else:
            if not 0 < options.timeout <= 60:
                raise AppError(
                    "arguments", "Daemon wait timeout must be positive and at most 60 seconds.", 2
                )
            operation = start_daemon if options.action == "start" else stop_daemon
            data = await asyncio.to_thread(
                operation,
                repo.data_dir,
                timeout=options.timeout,
                **({"config": options.config} if options.action == "start" else {}),
            )
            if options.action == "start" and running_under_wsl():
                # Stderr keeps the JSON envelope on stdout unchanged.
                print(WSL_DAEMON_WARNING, file=sys.stderr, flush=True)
    elif command == "targets":
        if options.action == "add":
            config = load_target(options.config)
            if options.profile != config.target.name:
                raise AppError(
                    "profile_name", "Profile name must match the target configuration.", 2
                )
            data = {"id": await service.save_profile(config)}
        elif options.action == "edit":
            existing = await repo.get_profile(options.profile)
            data = {
                "id": await service.save_profile(
                    load_target(options.config), profile_id=str(existing.id)
                )
            }
        elif options.action == "remove":
            data = {"id": await repo.remove_profile(options.profile), "removed": True}
        elif options.action == "show":
            data = await repo.get_profile(options.profile)
        else:
            data = await repo.list_profiles(limit=options.limit, cursor=options.cursor)
    elif command == "run":
        plan = load_pack_plan(options.pack) if options.pack is not None else load_plan(options.plan)
        identity = await service.submit(
            options.profile, load_evaluator(options.evaluator), plan.checks, prompts=plan.prompts
        )
        data = {"id": identity, "state": "queued", "meaning": "Accepted for background execution."}
    elif command == "checks":
        data = [check.model_dump(mode="json") for check in load_pack(options.pack)]
    elif command == "runs":
        if options.action == "list":
            data = await repo.list_runs(
                profile_id=options.profile, limit=options.limit, cursor=options.cursor
            )
        elif options.action == "show":
            data = await repo.read_run(options.run_id)
        elif options.action == "cancel":
            data = await service.cancel(options.run_id)
        elif options.action == "retry":
            data = {"id": await service.retry(options.run_id), "state": "queued"}
        else:
            await watch(repo, options.run_id, json_output)
            return
    elif command == "findings":
        if options.action == "list":
            data = await repo.list_findings(
                options.run_id, limit=options.limit, cursor=options.cursor
            )
        else:
            data = await repo.read_finding_detail(options.finding_id)
    elif command == "compare":
        data = await compare_runs(repo, options.run_ids)
    elif command == "report":
        if len(options.run_ids) == 1:
            source = (await repo.read_runs(options.run_ids))[0]
        else:
            source = await compare_runs(repo, options.run_ids)
        artifact = render_report(source, options.format)
        destination = await asyncio.to_thread(
            write_export, artifact, options.output, options.overwrite
        )
        data = {"path": str(destination), "format": artifact.format, "written": True}
    emit(data, json_output)


async def watch(repo: Repository, run_id: str, json_output: bool) -> None:
    after = 0
    while True:
        for event in await repo.events(run_id, after=after):
            emit(event, json_output)
            after = event["sequence"]
        view = await repo.read_run(run_id)
        if view.state not in {RunState.QUEUED, RunState.RUNNING}:
            for event in await repo.events(run_id, after=after):
                emit(event, json_output)
            emit({"id": run_id, "state": view.state.value}, json_output)
            return
        await asyncio.sleep(0.25)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    json_output = "--json" in args
    try:
        options = parser().parse_args([argument for argument in args if argument != "--json"])
        if options.command != "config":
            asyncio.run(dispatch(options, json_output))
            return 0
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
            print(safe_terminal(str(error)), file=sys.stderr)
        return error.exit_code
    except KeyboardInterrupt:
        return 130
