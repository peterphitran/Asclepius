import asyncio
import multiprocessing
import sqlite3
import time
from pathlib import Path

import portalocker
import pytest

from asclepius.domain import AppError
from asclepius.storage import Repository
from tests.cli.storage_fixtures import OWNER, prepare, run


def claim_child(directory, gate, ready, output):
    repo = Repository(Path(directory))
    ready.put("ready")
    if not gate.wait(15):
        raise RuntimeError("Claim gate timed out")
    snapshot = asyncio.run(repo.claim_next(OWNER))
    output.put(str(snapshot.id) if snapshot else None)


def test_two_processes_cannot_claim_one_run_twice(tmp_path):
    repo, snapshot, _ = run(prepare(tmp_path, claim=False))
    context = multiprocessing.get_context("spawn")
    gate, ready, output = context.Event(), context.Queue(), context.Queue()
    children = [
        context.Process(target=claim_child, args=(str(tmp_path), gate, ready, output))
        for _ in range(2)
    ]
    try:
        for child in children:
            child.start()
        assert [ready.get(timeout=15) for _ in children] == ["ready", "ready"]
        gate.set()
        results = [output.get(timeout=15) for _ in children]
        assert sorted(results, key=str) == sorted([str(snapshot.id), None], key=str)
        for child in children:
            child.join(timeout=15)
            assert child.exitcode == 0
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        for queue in (ready, output):
            queue.close()
            queue.join_thread()
    events = run(repo.events(str(snapshot.id)))
    assert [event["kind"] for event in events] == ["run.queued", "run.started"]


def test_write_contention_has_a_bounded_actionable_error(tmp_path):
    repo, _, _ = run(prepare(tmp_path, claim=False, busy_timeout=0.1))
    with sqlite3.connect(repo.database_path, isolation_level=None) as connection:
        connection.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        try:
            with pytest.raises(AppError) as error:
                run(repo.claim_next(OWNER))
            assert error.value.code == "storage_busy"
            assert time.monotonic() - started < 3
        finally:
            connection.rollback()
    assert run(repo.claim_next(OWNER)) is not None


def test_wal_reads_do_not_acquire_a_writer_slot(tmp_path):
    repo, snapshot, _ = run(prepare(tmp_path, busy_timeout=0.1))
    with sqlite3.connect(repo.database_path, isolation_level=None) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            view = run(repo.read_run(str(snapshot.id)))
            assert view.snapshot.id == snapshot.id
            assert view.state.value == "running"
        finally:
            connection.rollback()


def test_maintenance_exclusion_is_shared_for_operations_and_exclusive_for_init(tmp_path):
    repo, snapshot, _ = run(prepare(tmp_path, busy_timeout=0.1))
    lock_path = tmp_path / "maintenance.lock"
    with portalocker.Lock(lock_path, mode="a", flags=portalocker.LOCK_SH | portalocker.LOCK_NB):
        assert run(repo.read_run(str(snapshot.id))).snapshot.id == snapshot.id
        with pytest.raises(AppError) as error:
            run(repo.initialize())
        assert error.value.code == "storage_busy"
    with portalocker.Lock(lock_path, mode="a", flags=portalocker.LOCK_EX | portalocker.LOCK_NB):
        with pytest.raises(AppError) as error:
            run(repo.read_run(str(snapshot.id)))
        assert error.value.code == "storage_busy"
    assert run(repo.read_run(str(snapshot.id))).state.value == "running"
