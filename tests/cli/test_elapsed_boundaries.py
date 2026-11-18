import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from asclepius import storage
from asclepius.domain import ProfileConfig, TargetConfig
from asclepius.maintenance import instance_lock, readiness_lock
from asclepius.process import daemon_status
from asclepius.storage import Repository
from tests.cli.storage_fixtures import make_snapshot


@pytest.mark.parametrize("jump", [-86400, 86400])
def test_utc_jump_does_not_change_status_admission_or_deadline(tmp_path, monkeypatch, jump):
    repo = Repository(tmp_path)
    asyncio.run(repo.initialize())
    owner = str(uuid4())
    with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
        asyncio.run(repo.set_ready(owner, execution_available=True))
        instant = datetime.now(UTC) + timedelta(seconds=jump)

        class JumpedUTC:
            @staticmethod
            def now(zone):
                return instant

            fromisoformat = datetime.fromisoformat

        monkeypatch.setattr(storage, "datetime", JumpedUTC)
        import asclepius.process as process

        monkeypatch.setattr(process, "datetime", JumpedUTC, raising=False)
        assert daemon_status(tmp_path).responsive

        async def scenario():
            profile = ProfileConfig(
                target=TargetConfig(name="clock", model="x", secret_ref="env:KEY")
            )
            identity = await repo.save_profile(profile)
            snapshot = make_snapshot(identity, profile)
            await repo.enqueue(snapshot)
            await repo.claim_next(owner)
            with sqlite3.connect(repo.database_path) as connection:
                connection.execute("UPDATE runs SET started_at='2000-01-01T00:00:00+00:00'")
            await Repository(tmp_path).execution_checkpoint(str(snapshot.id), owner)

        asyncio.run(scenario())


def test_released_owner_cannot_admit_queued_work(tmp_path):
    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
            await repo.set_ready(owner)
        from asclepius.domain import AppError

        with pytest.raises(AppError) as error:
            await repo.claim_next(owner)
        assert error.value.code == "daemon_unavailable"

    asyncio.run(scenario())


def test_new_store_has_elapsed_schema(tmp_path):
    repo = Repository(tmp_path)
    asyncio.run(repo.initialize())
    with sqlite3.connect(repo.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute(
            "SELECT heartbeat_clock,heartbeat_tick_ns FROM daemon_control"
        ).fetchone() == (None, None)


@pytest.mark.parametrize(
    ("age_ns", "source", "expected"),
    [
        (0, "current", True),
        (10_000_000_000, "current", True),
        (10_000_000_001, "current", False),
        (-1, "current", False),
        (0, "other", False),
        (None, "current", False),
    ],
)
def test_heartbeat_boundary_controls_status_enqueue_and_claim(
    tmp_path, monkeypatch, age_ns, source, expected
):
    from asclepius.domain import AppError
    from asclepius.elapsed_clock import Tick, elapsed_clock

    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
            await repo.set_ready(owner, execution_available=True)
            current = elapsed_clock.sample()
            other = (
                "windows-gettickcount64-v1"
                if current.source == "linux-boottime-v1"
                else "linux-boottime-v1"
            )
            with sqlite3.connect(repo.database_path) as connection:
                connection.execute(
                    "UPDATE daemon_control SET heartbeat_clock=?,heartbeat_tick_ns=?",
                    (
                        None if age_ns is None else other if source == "other" else current.source,
                        None if age_ns is None else current.ns - age_ns,
                    ),
                )
            monkeypatch.setattr(elapsed_clock, "sample", lambda: Tick(current.source, current.ns))
            status = await repo.daemon_status()
            assert status.responsive is expected
            assert status.execution_available is expected
            profile = ProfileConfig(
                target=TargetConfig(name="boundary", model="x", secret_ref="env:KEY")
            )
            identity = await repo.save_profile(profile)
            snapshot = make_snapshot(identity, profile)
            if expected:
                assert await repo.enqueue(snapshot) == str(snapshot.id)
                assert (await repo.claim_next(owner)).id == snapshot.id
            else:
                with pytest.raises(AppError) as error:
                    await repo.enqueue(snapshot)
                assert error.value.code == "daemon_unavailable"
                with pytest.raises(AppError) as error:
                    await repo.claim_next(owner)
                assert error.value.code == "daemon_unavailable"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("age_ns", "expected"), [(999_999_999, None), (1_000_000_000, "run_timeout")]
)
def test_effective_runtime_deadline_is_inclusive_after_repository_reopen(
    tmp_path, monkeypatch, age_ns, expected
):
    from asclepius.domain import AppError, Limits
    from asclepius.elapsed_clock import Tick, elapsed_clock

    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
            await repo.set_ready(owner)
            profile = ProfileConfig(
                target=TargetConfig(name="deadline", model="x", secret_ref="env:KEY")
            )
            identity = await repo.save_profile(profile)
            snapshot = make_snapshot(identity, profile)
            await repo.enqueue(snapshot)
            await repo.claim_next(owner)
            current = elapsed_clock.sample()
            with sqlite3.connect(repo.database_path) as connection:
                connection.execute(
                    "UPDATE runs SET started_tick_ns=? WHERE id=?",
                    (current.ns - age_ns, str(snapshot.id)),
                )
            monkeypatch.setattr(elapsed_clock, "sample", lambda: Tick(current.source, current.ns))
            reopened = Repository(tmp_path)
            if expected:
                with pytest.raises(AppError) as error:
                    await reopened.execution_checkpoint(
                        str(snapshot.id), owner, runtime_limits=Limits(run_timeout_seconds=1)
                    )
                assert error.value.code == expected
            else:
                await reopened.execution_checkpoint(
                    str(snapshot.id), owner, runtime_limits=Limits(run_timeout_seconds=1)
                )

    asyncio.run(scenario())


def test_stale_held_owner_recovers_by_heartbeat_and_draining_never_admits(tmp_path):
    from asclepius.domain import AppError
    from asclepius.elapsed_clock import elapsed_clock

    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
            await repo.set_ready(owner, execution_available=True)
            with sqlite3.connect(repo.database_path) as connection:
                connection.execute(
                    "UPDATE daemon_control SET heartbeat_tick_ns=?",
                    (elapsed_clock.sample().ns - 11_000_000_000,),
                )
            assert not (await repo.daemon_status()).responsive
            with pytest.raises(AppError) as error:
                await repo.claim_next(owner)
            assert error.value.code == "daemon_unavailable"
            await repo.heartbeat(owner)
            assert (await repo.daemon_status()).responsive
            await repo.request_stop(owner)
            assert (await repo.daemon_status()).responsive
            with pytest.raises(AppError) as error:
                await repo.claim_next(owner)
            assert error.value.code == "daemon_unavailable"

    asyncio.run(scenario())


def test_released_and_copied_store_cannot_reuse_elapsed_heartbeat(tmp_path):
    import shutil

    from asclepius.domain import AppError

    async def scenario():
        source = tmp_path / "source"
        repo = Repository(source)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(source), readiness_lock(source, owner):
            await repo.set_ready(owner, execution_available=True)
            assert (await repo.daemon_status()).responsive
            copy = tmp_path / "copy"
            shutil.copytree(source, copy)
            assert not (await Repository(copy).daemon_status()).responsive
        assert not (await repo.daemon_status()).responsive
        with pytest.raises(AppError) as error:
            await repo.claim_next(owner)
        assert error.value.code == "daemon_unavailable"

    asyncio.run(scenario())


def test_run_start_missing_or_wrong_source_fails_closed(tmp_path):
    from asclepius.domain import AppError
    from asclepius.elapsed_clock import elapsed_clock

    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
            await repo.set_ready(owner)
            profile = ProfileConfig(
                target=TargetConfig(name="start", model="x", secret_ref="env:KEY")
            )
            identity = await repo.save_profile(profile)
            snapshot = make_snapshot(identity, profile)
            await repo.enqueue(snapshot)
            await repo.claim_next(owner)
            current = elapsed_clock.sample()
            other = (
                "windows-gettickcount64-v1"
                if current.source == "linux-boottime-v1"
                else "linux-boottime-v1"
            )
            for clock, tick in (
                (None, None),
                (other, current.ns),
                (current.source, current.ns + 1_000_000_000),
            ):
                with sqlite3.connect(repo.database_path) as connection:
                    connection.execute(
                        "UPDATE runs SET started_clock=?,started_tick_ns=?", (clock, tick)
                    )
                with pytest.raises(AppError) as error:
                    await Repository(tmp_path).execution_checkpoint(str(snapshot.id), owner)
                assert error.value.code == "run_timeout"

    asyncio.run(scenario())


def test_daemon_renews_heartbeat_before_claim_after_pause(tmp_path, monkeypatch):
    from asclepius import daemon
    from asclepius.elapsed_clock import Tick, elapsed_clock
    from tests.cli.storage_fixtures import prepare, release_leases

    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=False)
        release_leases()
        base = elapsed_clock.sample()
        state = {"ns": base.ns, "claims": 0}
        monkeypatch.setattr(elapsed_clock, "sample", lambda: Tick(base.source, state["ns"]))
        monkeypatch.setattr(elapsed_clock, "ns", lambda: state["ns"])
        original_claim = Repository.claim_next
        original_sleep = asyncio.sleep

        async def delayed_claim(self, owner, **kwargs):
            state["claims"] += 1
            if state["claims"] == 1:
                return None
            claimed = await original_claim(self, owner, **kwargs)
            assert claimed.id == snapshot.id
            raise RuntimeError("claim reached after fresh heartbeat")

        async def pause(_seconds):
            state["ns"] += 11_000_000_000
            await original_sleep(0)

        monkeypatch.setattr(Repository, "claim_next", delayed_claim)
        monkeypatch.setattr(asyncio, "sleep", pause)
        with pytest.raises(RuntimeError, match="claim reached after fresh heartbeat"):
            await daemon.serve(tmp_path, instance_id=str(uuid4()))
        assert state["claims"] == 2

    asyncio.run(scenario())


def test_failed_004_rolls_back_initialization(tmp_path, monkeypatch):
    from importlib.resources import files

    from asclepius import maintenance
    from asclepius.domain import AppError

    repo = Repository(tmp_path)
    monkeypatch.setattr(
        maintenance,
        "_script",
        lambda name: (
            "ALTER TABLE daemon_control ADD COLUMN heartbeat_clock TEXT; INVALID SQL;"
            if name == "004_elapsed.sql"
            else files("asclepius").joinpath("migrations", name).read_text()
        ),
    )
    with pytest.raises(AppError) as error:
        maintenance.initialize_storage(tmp_path)
    assert error.value.code == "storage_error"
    with sqlite3.connect(repo.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_elapsed_sample_occurs_after_write_transaction_acquisition(tmp_path, monkeypatch):
    import threading

    from asclepius.elapsed_clock import elapsed_clock

    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
            await repo.set_ready(owner)
            called = threading.Event()
            original = elapsed_clock.sample

            def sample():
                called.set()
                return original()

            monkeypatch.setattr(elapsed_clock, "sample", sample)
            with sqlite3.connect(repo.database_path, isolation_level=None) as connection:
                connection.execute("BEGIN IMMEDIATE")
                task = asyncio.create_task(repo.heartbeat(owner))
                await asyncio.sleep(0.1)
                assert not called.is_set()
                connection.rollback()
                await task
            assert called.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["checkpoint", "reserve", "dispatch"])
def test_exact_effective_deadline_fences_all_execution_paths(tmp_path, monkeypatch, boundary):
    from asclepius.domain import AppError, Limits
    from asclepius.elapsed_clock import Tick, elapsed_clock
    from asclepius.limits import BudgetManager

    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
            await repo.set_ready(owner)
            profile = ProfileConfig(
                target=TargetConfig(name="budget", model="x", secret_ref="env:KEY")
            )
            identity = await repo.save_profile(profile)
            snapshot = make_snapshot(identity, profile)
            await repo.enqueue(snapshot)
            await repo.claim_next(owner)
            now = elapsed_clock.sample()
            with sqlite3.connect(repo.database_path) as connection:
                connection.execute(
                    "UPDATE runs SET started_tick_ns=? WHERE id=?", (now.ns, str(snapshot.id))
                )
            point = {"ns": now.ns}
            monkeypatch.setattr(elapsed_clock, "sample", lambda: Tick(now.source, point["ns"]))
            limits = Limits(run_timeout_seconds=1)
            manager = BudgetManager(Repository(tmp_path), owner, limits=limits)
            reservation = None
            if boundary == "dispatch":
                reservation = await manager.reserve(str(snapshot.id), "target", 1)
            point["ns"] += 1_000_000_000
            with pytest.raises(AppError) as error:
                if boundary == "checkpoint":
                    await Repository(tmp_path).execution_checkpoint(
                        str(snapshot.id), owner, runtime_limits=limits
                    )
                elif boundary == "reserve":
                    await manager.reserve(str(snapshot.id), "target", 1)
                else:
                    await manager.dispatch(reservation)
            assert error.value.code == "run_timeout"
            if reservation is not None:
                await manager.release(reservation)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("condition", "code"), [("cancel", "run_cancelled"), ("budget", "budget_exhausted")]
)
def test_cancel_and_budget_exhaustion_precede_deadline(tmp_path, condition, code):
    from asclepius.domain import AppError

    async def scenario():
        repo = Repository(tmp_path)
        await repo.initialize()
        owner = str(uuid4())
        with instance_lock(tmp_path), readiness_lock(tmp_path, owner):
            await repo.set_ready(owner)
            profile = ProfileConfig(
                target=TargetConfig(name="priority", model="x", secret_ref="env:KEY")
            )
            identity = await repo.save_profile(profile)
            snapshot = make_snapshot(identity, profile)
            await repo.enqueue(snapshot)
            await repo.claim_next(owner)
            with sqlite3.connect(repo.database_path) as connection:
                connection.execute(
                    "UPDATE runs SET started_clock=NULL,started_tick_ns=NULL WHERE id=?",
                    (str(snapshot.id),),
                )
                if condition == "budget":
                    connection.execute(
                        "UPDATE runs SET reason='budget_exhausted' WHERE id=?", (str(snapshot.id),)
                    )
            if condition == "cancel":
                await repo.request_cancel(str(snapshot.id))
            with pytest.raises(AppError) as error:
                await Repository(tmp_path).execution_checkpoint(str(snapshot.id), owner)
            assert error.value.code == code

    asyncio.run(scenario())


def test_unsupported_elapsed_clock_has_no_wall_time_fallback(monkeypatch):
    from asclepius import elapsed_clock as module
    from asclepius.domain import AppError

    monkeypatch.setattr(module.sys, "platform", "unsupported")
    with pytest.raises(AppError) as error:
        module.ElapsedClock().sample()
    assert error.value.code == "clock_unavailable"
