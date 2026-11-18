import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from asclepius import __version__
from asclepius.checks import load_pack, load_pack_plan
from asclepius.config import data_directory, load_evaluator, load_plan, load_target
from asclepius.domain import AppError, Comparison, RunState
from asclepius.exports import render_report, safe_terminal, write_export
from asclepius.maintenance import migrate_storage
from asclepius.process import (
    WSL_DAEMON_WARNING,
    daemon_status,
    running_under_wsl,
    start_daemon,
    stop_daemon,
)
from asclepius.results import assess_runs, finding_detail
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
    validate.set_defaults(handler=_config_validate)
    commands.add_parser("init", help="Initialize a new local SQLite data directory.").set_defaults(
        handler=_init
    )
    targets = commands.add_parser("targets", help="Manage application profiles.")
    target_actions = targets.add_subparsers(dest="action", required=True)
    for name, handler in (("add", _targets_add), ("edit", _targets_edit)):
        action = target_actions.add_parser(name)
        action.add_argument("profile")
        action.add_argument("--config", type=Path, required=True)
        action.set_defaults(handler=handler)
    target_list = target_actions.add_parser("list")
    pagination(target_list)
    target_list.set_defaults(handler=_targets_list)
    for name, handler in (("show", _targets_show), ("remove", _targets_remove)):
        action = target_actions.add_parser(name)
        action.add_argument("profile")
        action.set_defaults(handler=handler)
    submit = commands.add_parser("run", help="Queue a complete evaluation plan.")
    submit.add_argument("profile")
    source = submit.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path)
    source.add_argument("--pack")
    submit.add_argument("--evaluator", type=Path, required=True)
    submit.set_defaults(handler=_run_submit)
    runs = commands.add_parser("runs", help="Inspect and control persisted runs.")
    run_actions = runs.add_subparsers(dest="action", required=True)
    run_list = run_actions.add_parser("list")
    pagination(run_list)
    run_list.add_argument("--profile", help="Stable profile ID, including removed profiles.")
    run_list.set_defaults(handler=_runs_list)
    for name, handler in (
        ("show", _runs_show),
        ("cancel", _runs_cancel),
        ("retry", _runs_retry),
        ("watch", _runs_watch),
    ):
        action = run_actions.add_parser(name)
        action.add_argument("run_id")
        action.set_defaults(handler=handler)
    findings = commands.add_parser("findings", help="Inspect saved findings.")
    finding_actions = findings.add_subparsers(dest="action", required=True)
    finding_list = finding_actions.add_parser("list")
    finding_list.add_argument("--run", required=True, dest="run_id")
    pagination(finding_list)
    finding_list.set_defaults(handler=_findings_list)
    finding_show = finding_actions.add_parser("show")
    finding_show.add_argument("finding_id")
    finding_show.set_defaults(handler=_findings_show)
    daemon = commands.add_parser("daemon", help="Manually control the detached queue daemon.")
    daemon_actions = daemon.add_subparsers(dest="action", required=True)
    for name, handler in (("start", _daemon_start), ("stop", _daemon_stop)):
        action = daemon_actions.add_parser(name)
        action.add_argument("--timeout", type=float, default=15)
        if name == "start":
            action.add_argument("--config", type=Path)
        action.set_defaults(handler=handler)
    daemon_actions.add_parser("status").set_defaults(handler=_daemon_status)
    storage = commands.add_parser("storage", help="Explicit stopped-store maintenance.")
    storage.add_subparsers(dest="action", required=True).add_parser("migrate").set_defaults(
        handler=_storage_migrate
    )
    checks = commands.add_parser("checks", help="List built-in checks.")
    listing = checks.add_subparsers(dest="action", required=True).add_parser("list")
    listing.add_argument("--pack", required=True)
    listing.set_defaults(handler=_checks_list)
    compare = commands.add_parser("compare", help="Compare saved run evidence.")
    compare.add_argument("run_ids", nargs="+")
    compare.set_defaults(handler=_compare_command)
    report = commands.add_parser("report", help="Export saved run evidence.")
    report.add_argument("run_ids", nargs="+")
    report.add_argument("--format", choices=("json", "markdown", "html"), required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--overwrite", action="store_true")
    report.set_defaults(handler=_report)
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


def _repo(options) -> Repository:
    return Repository(data_directory(options.data_dir))


async def _config_validate(options, json_output: bool) -> None:
    loader = load_evaluator if options.kind == "evaluator" else load_target
    loader(options.path)
    if json_output:
        print(json.dumps({"schema_version": 1, "ok": True, "kind": options.kind}))
    else:
        print(f"Valid {options.kind} configuration.")


async def _init(options, json_output: bool):
    await _repo(options).initialize()
    return {"initialized": True}


async def _storage_migrate(options, json_output: bool):
    return {"schema_version": await asyncio.to_thread(migrate_storage, _repo(options).data_dir)}


async def _daemon_status(options, json_output: bool):
    return await asyncio.to_thread(daemon_status, _repo(options).data_dir)


async def _daemon_start(options, json_output: bool):
    repo = _repo(options)
    _require_wait_timeout(options.timeout)
    data = await asyncio.to_thread(
        start_daemon, repo.data_dir, timeout=options.timeout, config=options.config
    )
    if running_under_wsl():
        print(WSL_DAEMON_WARNING, file=sys.stderr, flush=True)
    return data


async def _daemon_stop(options, json_output: bool):
    repo = _repo(options)
    _require_wait_timeout(options.timeout)
    return await asyncio.to_thread(stop_daemon, repo.data_dir, timeout=options.timeout)


def _require_wait_timeout(timeout: float) -> None:
    if not 0 < timeout <= 60:
        raise AppError(
            "arguments", "Daemon wait timeout must be positive and at most 60 seconds.", 2
        )


async def _targets_add(options, json_output: bool):
    repo = _repo(options)
    config = load_target(options.config)
    if options.profile != config.target.name:
        raise AppError("profile_name", "Profile name must match the target configuration.", 2)
    return {"id": await repo.save_profile(config)}


async def _targets_edit(options, json_output: bool):
    repo = _repo(options)
    existing = await repo.get_profile(options.profile)
    config = load_target(options.config)
    return {"id": await repo.save_profile(config, profile_id=str(existing.id))}


async def _targets_remove(options, json_output: bool):
    return {"id": await _repo(options).remove_profile(options.profile), "removed": True}


async def _targets_show(options, json_output: bool):
    return await _repo(options).get_profile(options.profile)


async def _targets_list(options, json_output: bool):
    return await _repo(options).list_profiles(limit=options.limit, cursor=options.cursor)


async def _run_submit(options, json_output: bool):
    service = EvaluationService(_repo(options))
    plan = load_pack_plan(options.pack) if options.pack is not None else load_plan(options.plan)
    identity = await service.submit(
        options.profile, load_evaluator(options.evaluator), plan.checks, prompts=plan.prompts
    )
    return {"id": identity, "state": "queued", "meaning": "Accepted for background execution."}


async def _checks_list(options, json_output: bool):
    _repo(options)
    return [check.model_dump(mode="json") for check in load_pack(options.pack)]


async def _runs_list(options, json_output: bool):
    return await _repo(options).list_runs(
        profile_id=options.profile, limit=options.limit, cursor=options.cursor
    )


async def _runs_show(options, json_output: bool):
    return await _repo(options).read_run(options.run_id)


async def _runs_cancel(options, json_output: bool):
    return await _repo(options).request_cancel(options.run_id)


async def _runs_retry(options, json_output: bool):
    service = EvaluationService(_repo(options))
    return {"id": await service.retry(options.run_id), "state": "queued"}


async def _runs_watch(options, json_output: bool) -> None:
    await watch(_repo(options), options.run_id, json_output)


async def _findings_list(options, json_output: bool):
    return await _repo(options).list_findings(
        options.run_id, limit=options.limit, cursor=options.cursor
    )


async def _findings_show(options, json_output: bool):
    view = await _repo(options).read_finding_view(options.finding_id)
    return finding_detail(view, UUID(options.finding_id))


async def _compare(repo: Repository, run_ids: list[str]) -> Comparison:
    if len(run_ids) < 2:
        raise AppError("arguments", "Comparison requires at least two distinct runs.", 2)
    return assess_runs(await repo.read_runs(run_ids))


async def _compare_command(options, json_output: bool):
    return await _compare(_repo(options), options.run_ids)


async def _report(options, json_output: bool):
    repo = _repo(options)
    if len(options.run_ids) == 1:
        source = (await repo.read_runs(options.run_ids))[0]
    else:
        source = await _compare(repo, options.run_ids)
    artifact = render_report(source, options.format)
    destination = await asyncio.to_thread(write_export, artifact, options.output, options.overwrite)
    return {"path": str(destination), "format": artifact.format, "written": True}


async def dispatch(options, json_output: bool) -> None:
    data = await options.handler(options, json_output)
    if data is not None:
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
        asyncio.run(dispatch(options, json_output))
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
