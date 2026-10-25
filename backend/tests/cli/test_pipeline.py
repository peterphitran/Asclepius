import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from asclepius.domain import AppError, RunState, SelectionOutput
from tests.cli.storage_fixtures import OWNER, prepare


@pytest.mark.parametrize("committed", [True, False])
def test_provider_closes_evidence_connection(tmp_path, monkeypatch, committed):
    from scripts.pipeline_fixture import provider

    database = tmp_path / "asclepius.sqlite3"
    body = {"messages": [{"content": '{"requested_checks":[]}'}]}
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            "CREATE TABLE operations(id,run_id,work_item_id,request_json,status);"
            "CREATE TABLE work_items(run_id,id,variant_json);"
            "CREATE TABLE runs(state);"
        )
        if committed:
            connection.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?)",
                (
                    "operation",
                    "run",
                    "work",
                    json.dumps({"actor": "selector", "provider_body_json": json.dumps(body)}),
                    "pending",
                ),
            )
            connection.commit()

    connect = sqlite3.connect
    opened = []

    def capture_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", capture_connection)
    with provider(tmp_path, Path(__file__).parent / "fixtures") as server:
        if committed:
            assert server.respond(body)[0] == 200
        else:
            with pytest.raises(AssertionError, match="committed prepared intent"):
                server.respond(body)
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened[0].execute("SELECT 1")


def test_stage_attempt_started_completed_and_legacy_start_unknown(tmp_path):
    async def scenario():
        repo, snapshot, work = await prepare(tmp_path)
        attempt = await repo.begin_stage(str(snapshot.id), work, "selector", instance_id=OWNER)
        assert attempt.attempt == 1 and attempt.state == "pending"
        assert attempt.started_at is not None
        await repo.commit_stage(
            str(snapshot.id), work, "selector", SelectionOutput(selections=()), instance_id=OWNER
        )
        view = await repo.read_run(str(snapshot.id))
        assert view.attempts[0].state == "completed"
        assert view.attempts[0].started_at == attempt.started_at

    asyncio.run(scenario())


def test_pending_stage_blocks_finalization_and_failed_attempt_closes_it(tmp_path):
    async def scenario():
        repo, snapshot, work = await prepare(tmp_path)
        attempt = await repo.begin_stage(str(snapshot.id), work, "generator", instance_id=OWNER)
        with pytest.raises(AppError) as error:
            await repo.finalize(str(snapshot.id), RunState.COMPLETED, None, instance_id=OWNER)
        assert error.value.code == "pending_stage"
        await repo.fail_stage(attempt, "invalid_role_output", instance_id=OWNER)
        await repo.finalize(
            str(snapshot.id), RunState.FAILED, "invalid_role_output", instance_id=OWNER
        )
        view = await repo.read_run(str(snapshot.id))
        assert view.attempts[0].error_code == "invalid_role_output"
        with sqlite3.connect(repo.database_path) as connection:
            assert connection.execute("SELECT state FROM stage_attempts").fetchall() == [
                ("failed",)
            ]

    asyncio.run(scenario())


def test_legacy_plan_fails_before_credentials_or_provider(tmp_path):
    from asclepius.coordinator import Coordinator
    from asclepius.limits import BudgetManager

    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        await Coordinator(repo, BudgetManager(repo, OWNER)).execute(snapshot)
        view = await repo.read_run(str(snapshot.id))
        assert view.state == RunState.FAILED
        assert view.reason == "plan_not_executable"
        assert view.observations == ()

    asyncio.run(scenario())


def test_full_pack_real_cli_daemon_https_and_sqlite(tmp_path):
    from pathlib import Path

    from scripts.pipeline_fixture import assert_complete, cli, configure, provider, wait_run

    certificates = Path(__file__).parent / "fixtures"
    with provider(tmp_path / "store", certificates) as server:
        directory, evaluator, _, _ = configure(tmp_path, server, certificates)
        try:
            accepted = cli(
                directory, "run", "fixture", "--pack", "broad-chat-v1", "--evaluator", evaluator
            )
            view = wait_run(directory, accepted["id"])
            assert server.failures == []
            assert_complete(view, server.calls)
            with sqlite3.connect(directory / "asclepius.sqlite3") as connection:
                assert (
                    connection.execute(
                        "SELECT count(*) FROM operations WHERE status='pending'"
                    ).fetchone()[0]
                    == 0
                )
                assert connection.execute("SELECT count(*) FROM stages").fetchone()[0] == 102
        finally:
            cli(directory, "daemon", "stop")


@pytest.mark.parametrize(
    "fault,reason,targets,findings",
    [("http", "provider_http_503", 2, 1), ("invalid", "invalid_role_output", 0, 0)],
)
def test_real_provider_failure_retains_evidence_and_stops_dispatch(
    tmp_path, fault, reason, targets, findings
):
    from pathlib import Path

    from scripts.pipeline_fixture import cli, configure, provider, wait_run

    certificates = Path(__file__).parent / "fixtures"
    with provider(tmp_path / "store", certificates, fault=fault) as server:
        directory, evaluator, _, _ = configure(tmp_path, server, certificates)
        try:
            accepted = cli(
                directory, "run", "fixture", "--pack", "broad-chat-v1", "--evaluator", evaluator
            )
            view = wait_run(directory, accepted["id"])
            assert server.failures == []
            assert view["state"] == "failed" and view["reason"] == reason
            assert len(view["findings"]) == findings
            assert sum(item["actor"] == "target" for item in view["observations"]) == targets
            assert len(view["observations"]) == len(server.calls)
            assert all(item["state"] != "pending" for item in view["attempts"])
            if fault == "invalid":
                assert view["attempts"][-1]["state"] == "failed"
                assert view["observations"][-1]["status"] == "success"
                assert view["observations"][-1]["payload"]["content"] == '{"attacks":[]}'
            else:
                assert view["observations"][-1]["error_code"] == "provider_http_503"
            with sqlite3.connect(directory / "asclepius.sqlite3") as connection:
                assert (
                    connection.execute(
                        "SELECT count(*) FROM operations WHERE status='pending'"
                    ).fetchone()[0]
                    == 0
                )
        finally:
            cli(directory, "daemon", "stop")


def test_missing_daemon_credential_preflight_ignores_client_credential(tmp_path):
    import os
    from pathlib import Path

    from scripts.pipeline_fixture import KEY, cli, configure, provider, wait_run

    certificates = Path(__file__).parent / "fixtures"
    with provider(tmp_path / "store", certificates) as server:
        directory, evaluator, _, _ = configure(tmp_path, server, certificates, daemon_key=False)
        try:
            environment = dict(os.environ, PIPELINE_KEY=KEY)
            accepted = cli(
                directory,
                "run",
                "fixture",
                "--pack",
                "broad-chat-v1",
                "--evaluator",
                evaluator,
                environment=environment,
            )
            view = wait_run(directory, accepted["id"])
            assert view["state"] == "failed" and view["reason"] == "secret_missing"
            assert view["observations"] == [] and view["attempts"] == []
            assert server.calls == []
        finally:
            cli(directory, "daemon", "stop")


def test_snapshot_survives_profile_and_local_plan_edits(tmp_path):
    import json
    from pathlib import Path

    from asclepius.checks import load_pack_plan
    from scripts.pipeline_fixture import cli, configure, provider, wait_run

    certificates = Path(__file__).parent / "fixtures"
    with provider(tmp_path / "store", certificates, fault="invalid") as server:
        directory, evaluator, targets, _ = configure(tmp_path, server, certificates)
        server.release.clear()
        try:
            plan = tmp_path / "plan.json"
            plan.write_text(load_pack_plan("broad-chat-v1").model_dump_json(), encoding="utf-8")
            accepted = cli(directory, "run", "fixture", "--plan", plan, "--evaluator", evaluator)
            assert server.received.wait(15)
            saved = cli(directory, "runs", "show", accepted["id"])["snapshot"]
            assert saved["checks"][0]["objective"]
            assert saved["profile"]["target"]["system_prompt"] == "Frozen profile policy"
            plan.write_text(json.dumps({"changed": True}), encoding="utf-8")
            target = targets["fixture"]
            target.write_text(
                target.read_text().replace("Frozen profile policy", "Changed after submit"),
                encoding="utf-8",
            )
            cli(directory, "targets", "edit", "fixture", "--config", target)
            server.release.set()
            view = wait_run(directory, accepted["id"])
            assert view["snapshot"] == saved
            assert server.failures == []
            assert (
                cli(directory, "targets", "show", "fixture")["config"]["target"]["system_prompt"]
                == "Changed after submit"
            )
        finally:
            server.release.set()
            cli(directory, "daemon", "stop")


def test_legacy_direct_commit_keeps_unknown_start_timestamp(tmp_path):
    async def scenario():
        repo, snapshot, work = await prepare(tmp_path)
        await repo.commit_stage(
            str(snapshot.id), work, "selector", SelectionOutput(selections=()), instance_id=OWNER
        )
        view = await repo.read_run(str(snapshot.id))
        assert view.attempts[0].state == "completed"
        assert view.attempts[0].started_at is None
        assert view.attempts[0].finished_at is not None

    asyncio.run(scenario())


def test_atomic_capacity_claim_waits_for_most_restrictive_active_snapshot(tmp_path):
    from uuid import uuid4

    from asclepius.domain import Limits

    async def scenario():
        repo, first, _ = await prepare(tmp_path)
        second = first.model_copy(
            update={
                "id": uuid4(),
                "profile": first.profile.model_copy(update={"limits": Limits(active_runs=2)}),
            }
        )
        await repo.enqueue(second)
        assert await repo.claim_next(OWNER, limits=Limits(active_runs=2)) is None
        assert (await repo.read_run(str(second.id))).state == RunState.QUEUED
        with sqlite3.connect(repo.database_path) as connection:
            assert (
                connection.execute(
                    "SELECT started_at FROM runs WHERE id=?", (str(second.id),)
                ).fetchone()[0]
                is None
            )
        await repo.finalize(str(first.id), RunState.FAILED, "fixture", instance_id=OWNER)
        assert (await repo.claim_next(OWNER, limits=Limits(active_runs=2))).id == second.id

    asyncio.run(scenario())


def test_orphan_interruption_closes_pending_attempt_without_claiming_completion(tmp_path):
    async def scenario():
        repo, snapshot, work = await prepare(tmp_path)
        await repo.begin_stage(str(snapshot.id), work, "selector", instance_id=OWNER)
        await repo.set_ready("replacement-owner")
        assert await repo.interrupt_orphans("replacement-owner") == [str(snapshot.id)]
        view = await repo.read_run(str(snapshot.id))
        assert view.state == RunState.INTERRUPTED
        assert view.attempts[0].state == "failed"
        assert view.attempts[0].error_code == "owner_lost"
        assert view.judgments == ()

    asyncio.run(scenario())
