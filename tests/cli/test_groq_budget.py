import asyncio
import json
import sqlite3
import threading
from contextlib import asynccontextmanager

import pytest

from asclepius.domain import (
    AppError,
)
from tests.cli.groq_support import (
    Answer,
    execute_target,
    prepare_target,
    reply,
    reservations,
    setup,
)
from tests.cli.storage_fixtures import OWNER


def test_limits_reject_new_dispatch_and_retain_target_truncation(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(
            groq, tmp_path, monkeypatch, target_calls=1
        )
        groq[0].body = json.dumps(reply("partial", "length")).encode()
        observation = await execute_target(connection, work)
        assert observation.status == "success"
        assert observation.truncated is True
        assert observation.payload.content == "partial"
        with pytest.raises(AppError) as caught:
            await execute_target(connection, work)
        assert caught.value.code == "budget_exhausted"
        assert len(groq[0].calls) == 1
        assert len(reservations(repo)) == 1

    asyncio.run(scenario())


def test_response_cap_preserves_uncertainty_and_consumes_budget(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(
            groq, tmp_path, monkeypatch, response_bytes=16
        )
        observation = await execute_target(connection, work)
        assert observation.error_code == "response_too_large"
        assert observation.truncated
        assert observation.payload is None
        assert len(groq[0].calls) == 1
        assert reservations(repo)[0][1] == "settled"

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_release", [False, True])
def test_cancellation_waiting_for_slot_releases_allowance(
    groq, tmp_path, monkeypatch, cancel_release
):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(
            groq, tmp_path, monkeypatch, outbound_concurrency=1, target_calls=1
        )
        budgets = connection.budgets
        releasing = threading.Event()
        finish_release = threading.Event()
        transaction = repo._transaction
        waiting = asyncio.Event()
        slot = budgets.slot

        @asynccontextmanager
        async def waiting_slot(*args, **kwargs):
            waiting.set()
            async with slot(*args, **kwargs) as lease:
                yield lease

        def blocked_release(action, write):
            if write and waiting.is_set() and reservations(repo) == [("target", "reserved", 512)]:
                releasing.set()
                assert finish_release.wait(5)
            return transaction(action, write)

        if cancel_release:
            monkeypatch.setattr(repo, "_transaction", blocked_release)
        try:
            async with slot(snapshot, "target"):
                monkeypatch.setattr(budgets, "slot", waiting_slot)
                task = asyncio.create_task(execute_target(connection, work))
                await asyncio.wait_for(waiting.wait(), 5)
                assert reservations(repo) == [("target", "reserved", 512)]
                task.cancel()
                if cancel_release:
                    assert await asyncio.to_thread(releasing.wait, 5)
                    task.cancel()
                    finish_release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert groq[0].calls == []
                assert reservations(repo) == [("target", "released", 512)]
            monkeypatch.setattr(repo, "_transaction", transaction)
            observation = await execute_target(connection, work)
            assert observation.status == "success"
            assert len(groq[0].calls) == 1
            assert reservations(repo) == [
                ("target", "released", 512),
                ("target", "settled", 512),
            ]
        finally:
            finish_release.set()
            await repo.drain_operations()

    asyncio.run(scenario())


@pytest.mark.parametrize("worker_state", ["reserved", "dispatched"])
def test_cancellation_with_unknown_worker_outcome_preserves_allowance(
    groq, tmp_path, monkeypatch, worker_state
):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(
            groq, tmp_path, monkeypatch, target_calls=1
        )
        committed = threading.Event()
        finish_worker = threading.Event()
        transaction = repo._transaction

        def blocked_worker(action, write):
            result = transaction(action, write)
            if write and reservations(repo) == [("target", worker_state, 512)]:
                committed.set()
                assert finish_worker.wait(5)
            return result

        monkeypatch.setattr(repo, "_transaction", blocked_worker)
        task = asyncio.create_task(execute_target(connection, work))
        try:
            assert await asyncio.to_thread(committed.wait, 5)
            task.cancel()
        finally:
            finish_worker.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reservations(repo) == [("target", worker_state, 512)]
        assert groq[0].calls == []
        with pytest.raises(AppError) as caught:
            await execute_target(connection, work)
        assert caught.value.code == "budget_exhausted"
        assert groq[0].calls == []

    asyncio.run(scenario())


def test_cancellation_after_https_dispatch_keeps_allowance_without_retry(
    groq, tmp_path, monkeypatch
):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(
            groq, tmp_path, monkeypatch, target_calls=1
        )
        groq[0].delay = 0.2
        task = asyncio.create_task(execute_target(connection, work))
        assert await asyncio.to_thread(groq[0].received.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reservations(repo) == [("target", "settled", 512)]
        with pytest.raises(AppError) as caught:
            await execute_target(connection, work)
        assert caught.value.code == "budget_exhausted"
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def test_dispatch_failure_retains_received_reply_when_settlement_fails(groq, tmp_path, monkeypatch):
    from asclepius.adapters.chat import DispatchFailure

    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        call = prepare_target(connection, work)
        await repo.begin_operation(call.request, instance_id=OWNER)

        async def fail_settlement(reservation):
            raise AppError("storage_error", "Injected settlement failure")

        monkeypatch.setattr(connection.budgets, "settle", fail_settlement)
        with pytest.raises(DispatchFailure) as caught:
            await connection.execute(call)
        observation = caught.value.observation
        assert observation.status == "success"
        assert observation.payload.content == "hello"
        assert observation.payload.response_id == "response-1"
        assert observation.dispatch_status == "attempted"
        assert caught.value.code == "storage_error"
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations == (observation,)
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def test_local_budget_rejection_has_explicit_nondispatch_metadata(groq, tmp_path, monkeypatch):
    from asclepius.adapters.chat import DispatchFailure

    async def scenario():
        _, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch, target_calls=1)
        await execute_target(connection, work)
        with pytest.raises(DispatchFailure) as caught:
            await execute_target(connection, work)
        observation = caught.value.observation
        assert observation.dispatch_status == "not_dispatched"
        assert observation.status == "transport_error" and observation.payload is None
        assert observation.error_code == "budget_exhausted"
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def test_coordinator_storage_failure_keeps_received_evidence_and_running_owner(
    groq, tmp_path, monkeypatch
):
    from asclepius.checks import load_pack_plan
    from asclepius.coordinator import Coordinator
    from asclepius.domain import RunState

    async def scenario():
        repo, snapshot, _, connection, _ = await setup(groq, tmp_path, monkeypatch)
        plan = load_pack_plan("broad-chat-v1")
        snapshot = snapshot.model_copy(update={"checks": plan.checks, "prompts": plan.prompts})
        with sqlite3.connect(repo.database_path) as db:
            db.execute(
                "UPDATE runs SET snapshot_json=? WHERE id=?",
                (snapshot.model_dump_json(), str(snapshot.id)),
            )

        async def fail_settlement(reservation):
            raise AppError("storage_error", "Injected settlement failure")

        monkeypatch.setattr(connection.budgets, "settle", fail_settlement)
        with pytest.raises(AppError) as caught:
            await Coordinator(repo, connection.budgets, transport=groq[1]).execute(snapshot)
        assert caught.value.code == "storage_error"
        view = await repo.read_run(str(snapshot.id))
        assert view.state == RunState.RUNNING
        assert len(view.observations) == 1
        assert view.observations[0].payload.content == "hello"
        assert view.attempts[0].state == "pending"
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def spy_token_leases(budgets):
    charged = []
    original = budgets.slot

    @asynccontextmanager
    async def slot(snapshot, kind, **kwargs):
        async with original(snapshot, kind, **kwargs) as lease:
            entry = {"estimate": kwargs.get("tokens"), "measured": []}
            charged.append(entry)
            record = lease.record

            def spy(tokens):
                entry["measured"].append(tokens)
                record(tokens)

            lease.record = spy
            yield lease

    budgets.slot = slot
    return charged


@pytest.mark.parametrize("actor", ["target", "judge"])
def test_token_estimate_is_input_bytes_over_four_plus_output_cap(
    groq, tmp_path, monkeypatch, actor
):
    async def scenario():
        _, snapshot, work, connection, gateway = await setup(groq, tmp_path, monkeypatch)
        charged = spy_token_leases(connection.budgets)
        if actor == "target":
            call = prepare_target(connection, work)
            await execute_target(connection, work)
            cap = snapshot.profile.target.max_completion_tokens
        else:
            groq[0].body = json.dumps(reply('{"verdict":"pass","score":2}')).encode()
            call = gateway.prepare("judge", {}, Answer).call
            await gateway.generate("judge", {}, Answer)
            cap = snapshot.evaluator.roles.judge.max_completion_tokens
        size = len(call.body_json.encode("utf-8"))
        assert charged[0]["estimate"] == -(-size // 4) + cap
        assert charged[0]["measured"] == [20]

    asyncio.run(scenario())


@pytest.mark.parametrize("usage", [None, {"prompt_tokens": 13}, {"completion_tokens": 7}])
def test_incomplete_usage_keeps_the_token_estimate(groq, tmp_path, monkeypatch, usage):
    async def scenario():
        _, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        charged = spy_token_leases(connection.budgets)
        data = reply()
        if usage is None:
            del data["usage"]
        else:
            data["usage"] = usage
        groq[0].body = json.dumps(data).encode()
        await execute_target(connection, work)
        assert charged[0]["measured"] in ([], [None])

    asyncio.run(scenario())


def test_provider_error_keeps_the_token_estimate(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        charged = spy_token_leases(connection.budgets)
        groq[0].status = 429
        observation = await execute_target(connection, work)
        assert observation.error_code == "provider_http_429"
        assert charged[0]["estimate"] > 0
        assert charged[0]["measured"] in ([], [None])

    asyncio.run(scenario())
