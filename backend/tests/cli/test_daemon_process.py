import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from asclepius.domain import AppError, RunState
from asclepius.process import daemon_status, start_daemon, stop_daemon
from asclepius.storage import Repository
from tests.cli.storage_fixtures import make_snapshot, run


def test_detached_start_duplicate_stop_and_stopped_reads(tmp_path):
    repo = Repository(tmp_path)
    run(repo.initialize())
    started = start_daemon(tmp_path)
    try:
        assert started.state == "ready"
        assert started.owned and started.responsive
        assert started.pid != os.getpid()
        assert started.execution_available is False
        repeated = start_daemon(tmp_path)
        assert repeated.instance_id == started.instance_id
        assert repeated.pid == started.pid
        assert run(repo.list_runs()).items == ()
    finally:
        stopped = stop_daemon(tmp_path, timeout=5)
    assert stopped.state == "stopped"
    assert stopped.owned is False
    assert run(repo.list_runs()).items == ()


def test_stale_ready_pid_cannot_impersonate_child_startup(tmp_path):
    repo = Repository(tmp_path)
    run(repo.initialize())
    old_id = str(uuid4())
    run(repo.set_ready(old_id, pid=os.getpid()))
    assert daemon_status(tmp_path).state == "stopped"
    started = start_daemon(tmp_path)
    try:
        assert str(started.instance_id) != old_id
        assert started.pid != os.getpid()
    finally:
        stop_daemon(tmp_path, timeout=5)


def test_daemon_accepts_queue_without_claiming_and_leaves_it_on_stop(tmp_path):
    from asclepius.domain import ProfileConfig, TargetConfig

    repo = Repository(tmp_path)
    run(repo.initialize())
    profile = ProfileConfig(target=TargetConfig(name="test", model="test", secret_ref="env:KEY"))
    profile_id = run(repo.save_profile(profile))
    started = start_daemon(tmp_path)
    snapshot = make_snapshot(profile_id, profile)
    try:
        assert run(repo.enqueue(snapshot)) == str(snapshot.id)
        time.sleep(0.6)
        assert run(repo.read_run(str(snapshot.id))).state == RunState.QUEUED
    finally:
        stop_daemon(tmp_path, timeout=5)
    assert run(repo.read_run(str(snapshot.id))).state == RunState.QUEUED
    assert str(started.instance_id)


def test_stop_timeout_reports_draining_without_killing_active_owner(tmp_path):
    from asclepius.domain import ProfileConfig, TargetConfig

    repo = Repository(tmp_path)
    run(repo.initialize())
    started = start_daemon(tmp_path)
    instance = str(started.instance_id)
    profile = ProfileConfig(target=TargetConfig(name="test", model="test", secret_ref="env:KEY"))
    profile_id = run(repo.save_profile(profile))
    snapshot = make_snapshot(profile_id, profile)
    try:
        run(repo.enqueue(snapshot))
        assert run(repo.claim_next(instance)).id == snapshot.id
        with pytest.raises(AppError) as error:
            stop_daemon(tmp_path, timeout=0.2)
        assert error.value.code == "daemon_draining"
        status = daemon_status(tmp_path)
        assert status.state == "draining" and status.owned and status.responsive
        with pytest.raises(AppError):
            run(repo.enqueue(snapshot.model_copy(update={"id": uuid4()})))
        run(repo.finalize(str(snapshot.id), RunState.CANCELLED, "test", instance_id=instance))
    finally:
        stop_daemon(tmp_path, timeout=5)


def test_cli_parent_exit_does_not_stop_the_detached_child(tmp_path):
    repo = Repository(tmp_path)
    run(repo.initialize())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "asclepius",
            "--data-dir",
            str(tmp_path),
            "--json",
            "daemon",
            "start",
        ],
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    child = json.loads(result.stdout)["data"]
    try:
        time.sleep(0.5)
        observed = daemon_status(tmp_path)
        assert str(observed.instance_id) == child["instance_id"]
        assert observed.owned and observed.responsive
        if os.name != "nt":
            assert os.getsid(observed.pid) == observed.pid
    finally:
        stop_daemon(tmp_path, timeout=5)


def test_bad_schema_start_returns_diagnostics_without_reset(tmp_path):
    repo = Repository(tmp_path)
    run(repo.initialize())
    with sqlite3.connect(repo.database_path) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(AppError) as error:
        start_daemon(tmp_path, timeout=2)
    assert error.value.code in {"schema_version", "daemon_start_failed"}
    with sqlite3.connect(repo.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999


def test_stale_heartbeat_with_live_lock_does_not_spawn_a_replacement(tmp_path):
    from asclepius.maintenance import instance_lock

    repo = Repository(tmp_path)
    run(repo.initialize())
    with instance_lock(tmp_path):
        run(repo.set_ready(str(uuid4()), pid=os.getpid()))
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute("UPDATE daemon_control SET heartbeat_at='2000-01-01T00:00:00+00:00'")
        observed = daemon_status(tmp_path)
        assert observed.owned is True and observed.responsive is False
        with pytest.raises(AppError) as error:
            start_daemon(tmp_path, timeout=0.2)
        assert error.value.code == "daemon_unresponsive"


def test_concurrent_starts_converge_on_one_live_instance(tmp_path):
    repo = Repository(tmp_path)
    run(repo.initialize())
    try:
        with ThreadPoolExecutor(max_workers=2) as clients:
            results = list(clients.map(lambda _: start_daemon(tmp_path), range(2)))
        assert results[0].instance_id == results[1].instance_id
        assert results[0].pid == results[1].pid
        assert daemon_status(tmp_path).owned is True
    finally:
        stop_daemon(tmp_path, timeout=5)


def test_early_child_exit_returns_sanitized_start_failure(tmp_path, monkeypatch):
    import asclepius.process as process

    run(Repository(tmp_path).initialize())
    original = process.subprocess.Popen

    def exit_before_ready(arguments, **options):
        return original([sys.executable, "-c", "raise SystemExit(9)"], **options)

    monkeypatch.setattr(process.subprocess, "Popen", exit_before_ready)
    with pytest.raises(AppError) as error:
        start_daemon(tmp_path, timeout=2)
    assert error.value.code == "daemon_start_failed"
    assert daemon_status(tmp_path).owned is False
    assert len(list((tmp_path / "logs").glob("daemon-*.log"))) == 1


def test_restart_waiting_on_sqlite_does_not_make_old_ready_generation_live(tmp_path):
    import threading

    import portalocker

    from asclepius.maintenance import instance_lock

    repo = Repository(tmp_path)
    run(repo.initialize())
    old_id = str(uuid4())
    run(repo.set_ready(old_id, pid=os.getpid()))
    first_result = []
    first_error = []

    def start_first():
        try:
            first_result.append(start_daemon(tmp_path, timeout=4))
        except AppError as error:
            first_error.append(error)

    thread = threading.Thread(target=start_first)
    with sqlite3.connect(repo.database_path, isolation_level=None) as connection:
        connection.execute("BEGIN IMMEDIATE")
        thread.start()
        try:
            deadline = time.monotonic() + 2
            owned = False
            while time.monotonic() < deadline:
                try:
                    with instance_lock(tmp_path):
                        pass
                except portalocker.LockException:
                    owned = True
                    break
                time.sleep(0.02)
            assert owned
            with pytest.raises(AppError) as error:
                start_daemon(tmp_path, timeout=0.1)
            assert error.value.code == "daemon_unresponsive"
        finally:
            connection.rollback()
            thread.join(timeout=6)
    try:
        assert first_error == []
        assert len(first_result) == 1
        assert str(first_result[0].instance_id) != old_id
    finally:
        stop_daemon(tmp_path, timeout=5)
