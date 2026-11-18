import asyncio
import sqlite3
from contextlib import ExitStack, closing
from uuid import uuid4

import pytest

from asclepius import daemon
from asclepius.config import DaemonConfig
from asclepius.domain import (
    AppError,
    ChatInput,
    Limits,
    Message,
    OperationRequest,
    ProfileConfig,
    RunState,
    TargetConfig,
)
from asclepius.elapsed_clock import Tick, elapsed_clock
from asclepius.maintenance import instance_lock, readiness_lock
from asclepius.storage import ReadyHeartbeatExpired, Repository
from tests.cli.storage_fixtures import OWNER, make_snapshot, prepare, ready, release_leases


def test_claim_survives_pause_after_heartbeat_commit(tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, _ = await prepare(tmp_path, claim=False)
        release_leases()
        initial = elapsed_clock.sample()
        state = {"ns": initial.ns, "paused": False}
        monkeypatch.setattr(elapsed_clock, "sample", lambda: Tick(initial.source, state["ns"]))
        original_heartbeat = Repository.heartbeat
        original_claim = Repository.claim_next

        async def heartbeat_then_pause(self, owner):
            await original_heartbeat(self, owner)
            if not state["paused"]:
                state["paused"] = True
                state["ns"] += 11_000_000_000

        async def claim(self, owner, **kwargs):
            claimed = await original_claim(self, owner, **kwargs)
            assert claimed.id == snapshot.id
            raise RuntimeError("queued work reached after pause")

        monkeypatch.setattr(Repository, "heartbeat", heartbeat_then_pause)
        monkeypatch.setattr(Repository, "claim_next", claim)
        with pytest.raises(RuntimeError, match="queued work reached after pause"):
            await daemon.serve(tmp_path, instance_id=str(uuid4()))
        assert state["paused"]

    asyncio.run(scenario())


@pytest.fixture
def tick(monkeypatch):
    source = elapsed_clock.sample().source
    value = {"ns": 100_000_000_000}
    monkeypatch.setattr(elapsed_clock, "sample", lambda: Tick(source, value["ns"]))
    return value


async def assert_queued(repo, snapshot):
    assert (await repo.read_run(str(snapshot.id))).state == RunState.QUEUED
    assert [event["kind"] for event in await repo.events(str(snapshot.id))] == ["run.queued"]


@pytest.mark.parametrize("pause_count", [1, 3])
def test_preclaim_pauses_refuse_clients_then_claim_once(tmp_path, monkeypatch, tick, pause_count):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=False)
        release_leases()
        original_claim = Repository.claim_next
        refusals = 0
        executions = []
        yielded = []
        original_sleep = asyncio.sleep

        async def observe_yield(delay):
            yielded.append(delay)
            await original_sleep(0)

        async def claim(self, owner, **kwargs):
            nonlocal refusals
            if refusals < pause_count:
                tick["ns"] += 11_000_000_000
                status = await self.daemon_status()
                assert status.owned and not status.responsive and not status.execution_available
                with pytest.raises(AppError) as error:
                    await self.enqueue(snapshot.model_copy(update={"id": uuid4()}))
                assert type(error.value) is AppError
                assert error.value.code == "daemon_unavailable"
                assert error.value.exit_code == 4
                try:
                    await original_claim(self, owner, **kwargs)
                except ReadyHeartbeatExpired:
                    refusals += 1
                    await assert_queued(self, snapshot)
                    raise
                pytest.fail("Expired claim was accepted")
            return await original_claim(self, owner, **kwargs)

        async def execute(self, claimed):
            executions.append(claimed.id)
            await self.repo.finalize(
                str(claimed.id),
                RunState.FAILED,
                "test_complete",
                instance_id=self.budgets.instance_id,
            )
            await self.repo.request_stop(self.budgets.instance_id)

        monkeypatch.setattr(Repository, "claim_next", claim)
        monkeypatch.setattr(daemon.Coordinator, "execute", execute)
        monkeypatch.setattr(asyncio, "sleep", observe_yield)
        await asyncio.wait_for(daemon.serve(tmp_path, instance_id=str(uuid4())), timeout=10)
        assert refusals == pause_count
        assert len(yielded) >= pause_count
        assert executions == [snapshot.id]
        events = await repo.events(str(snapshot.id))
        assert [event["kind"] for event in events].count("run.started") == 1
        assert (await repo.read_run(str(snapshot.id))).state == RunState.FAILED

    asyncio.run(scenario())


@pytest.mark.parametrize("pause_count", [1, 3])
def test_startup_pause_recovers_orphan_once_without_replay(
    tmp_path, monkeypatch, tick, pause_count
):
    async def scenario():
        repo, orphan, work = await prepare(tmp_path)
        request = OperationRequest(
            run_id=orphan.id,
            work_item_id=work,
            payload=ChatInput(messages=(Message(role="user", content="uncertain"),)),
        )
        await repo.begin_operation(request, instance_id=OWNER)
        queued = orphan.model_copy(update={"id": uuid4()})
        await repo.enqueue(queued)
        release_leases()
        original_ready = Repository.set_ready
        original_interrupt = Repository.interrupt_orphans
        original_claim = Repository.claim_next
        refusals = 0
        recovered = []

        async def ready_then_pause(self, owner, **kwargs):
            await original_ready(self, owner, **kwargs)
            tick["ns"] += 11_000_000_000

        async def interrupt(self, owner):
            nonlocal refusals
            if 0 < refusals < pause_count:
                tick["ns"] += 11_000_000_000
            try:
                result = await original_interrupt(self, owner)
            except ReadyHeartbeatExpired:
                refusals += 1
                view = await self.read_run(str(orphan.id))
                assert view.state == RunState.RUNNING
                assert view.observations == ()
                raise
            recovered.extend(result)
            return result

        async def claim(self, owner, **kwargs):
            claimed = await original_claim(self, owner, **kwargs)
            assert claimed.id == queued.id
            raise RuntimeError("startup recovered")

        monkeypatch.setattr(Repository, "set_ready", ready_then_pause)
        monkeypatch.setattr(Repository, "interrupt_orphans", interrupt)
        monkeypatch.setattr(Repository, "claim_next", claim)
        with pytest.raises(RuntimeError, match="startup recovered"):
            await daemon.serve(tmp_path, instance_id=str(uuid4()))
        assert refusals == pause_count
        assert recovered == [str(orphan.id)]
        view = await repo.read_run(str(orphan.id))
        assert view.state == RunState.INTERRUPTED
        assert len(view.observations) == 1
        assert view.observations[0].operation_id == request.id
        assert view.observations[0].status == "unknown"
        kinds = [event["kind"] for event in await repo.events(str(orphan.id))]
        assert kinds.count("operation.started") == 1
        assert kinds.count("operation.observed") == 1
        assert kinds.count("run.finalized") == 1
        assert [event["kind"] for event in await repo.events(str(queued.id))].count(
            "run.started"
        ) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["claim_next", "interrupt_orphans"])
@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("exactly_ten", None),
        ("expired", ReadyHeartbeatExpired),
        ("wrong_generation", AppError),
        ("no_locks", AppError),
        ("instance_only", AppError),
        ("generation_only", AppError),
        ("draining", AppError),
        ("stopped", AppError),
        ("missing", AppError),
        ("future", AppError),
        ("source_mismatch", AppError),
        ("malformed", AppError),
        ("unsupported", AppError),
    ],
)
def test_ready_expiry_classification(tmp_path, monkeypatch, tick, condition, expected, method):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=False)
        owner = OWNER
        tick["ns"] += 10_000_000_000 if condition == "exactly_ten" else 10_000_000_001
        with ExitStack() as leases:
            if condition in {"no_locks", "instance_only", "generation_only"}:
                release_leases()
                if condition == "instance_only":
                    leases.enter_context(instance_lock(tmp_path))
                if condition == "generation_only":
                    leases.enter_context(readiness_lock(tmp_path, OWNER))
            elif condition == "wrong_generation":
                owner = str(uuid4())
            elif condition == "draining":
                await repo.request_stop(OWNER)
            elif condition == "stopped":
                await repo.set_stopped(OWNER)
            elif condition in {"missing", "future", "source_mismatch", "malformed"}:
                source = elapsed_clock.sample().source
                stamp = 100_000_000_000
                if condition == "missing":
                    source, stamp = None, None
                elif condition == "future":
                    stamp = tick["ns"] + 1
                elif condition == "source_mismatch":
                    source = (
                        "linux-boottime-v1"
                        if source == "windows-gettickcount64-v1"
                        else "windows-gettickcount64-v1"
                    )
                else:
                    stamp = -1
                with closing(sqlite3.connect(repo.database_path)) as connection:
                    connection.execute(
                        "UPDATE daemon_control SET heartbeat_clock=?,heartbeat_tick_ns=?",
                        (source, stamp),
                    )
                    connection.commit()
            elif condition == "unsupported":

                def unavailable():
                    raise AppError("clock_unavailable", "Unsupported elapsed clock.")

                monkeypatch.setattr(elapsed_clock, "sample", unavailable)
            action = getattr(repo, method)
            if expected is None:
                result = await action(owner)
                if method == "claim_next":
                    assert result.id == snapshot.id
                    assert (await repo.read_run(str(snapshot.id))).state == RunState.RUNNING
                else:
                    assert result == []
                    await assert_queued(repo, snapshot)
            else:
                with pytest.raises(AppError) as error:
                    await action(owner)
                assert type(error.value) is expected
                assert error.value.code == (
                    "storage_corrupt"
                    if condition == "malformed"
                    else "clock_unavailable"
                    if condition == "unsupported"
                    else "daemon_unavailable"
                )
                await assert_queued(repo, snapshot)

    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["claim", "startup"])
@pytest.mark.parametrize("race", ["stop", "generation"])
def test_change_after_expiry_does_not_claim(tmp_path, monkeypatch, tick, boundary, race):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=False)
        release_leases()
        owner = str(uuid4())
        replacement = str(uuid4())
        original = getattr(Repository, "claim_next" if boundary == "claim" else "interrupt_orphans")
        original_heartbeat = Repository.heartbeat
        refused = False
        renewed = []

        async def expire_then_change(self, identity, **kwargs):
            nonlocal refused
            tick["ns"] += 11_000_000_000
            try:
                await original(self, identity, **kwargs)
            except ReadyHeartbeatExpired:
                refused = True
                await assert_queued(self, snapshot)
                if race == "stop":
                    await self.request_stop(identity)
                else:
                    await self.set_ready(replacement)
                raise
            pytest.fail("Expired admission was accepted")

        async def heartbeat(self, identity):
            before = await self.control()
            await original_heartbeat(self, identity)
            if refused:
                renewed.append(before.state)

        monkeypatch.setattr(
            Repository,
            "claim_next" if boundary == "claim" else "interrupt_orphans",
            expire_then_change,
        )
        monkeypatch.setattr(Repository, "heartbeat", heartbeat)
        if race == "generation":
            with pytest.raises(AppError) as error:
                await daemon.serve(tmp_path, instance_id=owner)
            assert error.value.code == "ownership"
            assert str((await repo.control()).instance_id) == replacement
            assert renewed == []
        else:
            await asyncio.wait_for(daemon.serve(tmp_path, instance_id=owner), timeout=10)
            assert (await repo.control()).state == "stopped"
            assert renewed == ["draining"]
        assert refused
        await assert_queued(repo, snapshot)

    asyncio.run(scenario())


def test_recovery_rechecks_completed_task_failure_before_more_claims(tmp_path, monkeypatch, tick):
    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        profile = ProfileConfig(
            target=TargetConfig(name="pause", model="target", secret_ref="env:KEY"),
            limits=Limits(active_runs=2),
        )
        profile_id = await repo.save_profile(profile)
        first = make_snapshot(profile_id, profile)
        second = make_snapshot(profile_id, profile)
        await ready(repo)
        await repo.enqueue(first)
        await repo.enqueue(second)
        release_leases()
        original_claim = Repository.claim_next
        expire = asyncio.Event()
        attempts = 0
        accepted = []

        async def claim(self, owner, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                tick["ns"] += 11_000_000_000
                expire.set()
            result = await original_claim(self, owner, **kwargs)
            if result is not None:
                accepted.append(result.id)
            return result

        async def execute(self, snapshot):
            await expire.wait()
            raise RuntimeError("active task failed during pause")

        monkeypatch.setattr(Repository, "claim_next", claim)
        monkeypatch.setattr(daemon.Coordinator, "execute", execute)
        with pytest.raises(RuntimeError, match="active task failed during pause"):
            await asyncio.wait_for(
                daemon.serve(
                    tmp_path,
                    instance_id=str(uuid4()),
                    policy=DaemonConfig(limits=Limits(active_runs=2)),
                ),
                timeout=10,
            )
        assert attempts == 2
        assert accepted == [first.id]
        await assert_queued(repo, second)
        assert (await repo.control()).state == "stopped"

    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["claim_next", "interrupt_orphans"])
@pytest.mark.parametrize("condition", ["missing", "malformed", "unsupported"])
def test_daemon_does_not_renew_other_refusals(tmp_path, monkeypatch, tick, boundary, condition):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=False)
        release_leases()
        original = getattr(Repository, boundary)
        original_heartbeat = Repository.heartbeat
        invalidated = False
        renewals = []

        async def invalidate(self, owner, **kwargs):
            nonlocal invalidated
            invalidated = True
            if condition == "unsupported":

                def unavailable():
                    raise AppError("clock_unavailable", "Unsupported elapsed clock.")

                monkeypatch.setattr(elapsed_clock, "sample", unavailable)
            else:
                with closing(sqlite3.connect(self.database_path)) as connection:
                    if condition == "missing":
                        connection.execute(
                            "UPDATE daemon_control SET heartbeat_clock=NULL,heartbeat_tick_ns=NULL"
                        )
                    else:
                        connection.execute("UPDATE daemon_control SET heartbeat_tick_ns=-1")
                    connection.commit()
            return await original(self, owner, **kwargs)

        async def heartbeat(self, owner):
            if invalidated:
                renewals.append(owner)
            await original_heartbeat(self, owner)

        monkeypatch.setattr(Repository, boundary, invalidate)
        monkeypatch.setattr(Repository, "heartbeat", heartbeat)
        with pytest.raises(AppError) as error:
            await asyncio.wait_for(daemon.serve(tmp_path, instance_id=str(uuid4())), timeout=10)
        assert type(error.value) is AppError
        assert (
            error.value.code
            == {
                "missing": "daemon_unavailable",
                "malformed": "storage_corrupt",
                "unsupported": "clock_unavailable",
            }[condition]
        )
        assert invalidated
        assert renewals == []
        await assert_queued(repo, snapshot)

    asyncio.run(scenario())
