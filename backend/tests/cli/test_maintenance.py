import asyncio
import sqlite3
import threading
import time
from contextlib import closing
from importlib.resources import files

import pytest

from asclepius.domain import AppError
from asclepius.maintenance import migrate_storage
from asclepius.process import start_daemon, stop_daemon
from asclepius.storage import Repository
from tests.cli.storage_fixtures import run


def test_explicit_v1_migration_preserves_existing_records(tmp_path):
    from uuid import uuid4

    from asclepius.domain import ProfileConfig, TargetConfig
    from tests.cli.storage_fixtures import make_snapshot

    repo = Repository(tmp_path)
    profile_id = str(uuid4())
    profile = ProfileConfig(
        target=TargetConfig(name="kept", model="version-one-target", secret_ref="env:KEY")
    )
    snapshot = make_snapshot(profile_id, profile)
    with closing(sqlite3.connect(repo.database_path)) as connection:
        connection.executescript(
            files("asclepius").joinpath("migrations/001_initial.sql").read_text()
        )
        connection.execute(
            "INSERT INTO profiles VALUES(?,?,?,1,NULL)",
            (profile_id, "kept", profile.model_dump_json()),
        )
        connection.execute(
            "INSERT INTO runs(id,profile_id,snapshot_json,state,created_at) "
            "VALUES(?,?,?,'queued',?)",
            (
                str(snapshot.id),
                profile_id,
                snapshot.model_dump_json(),
                snapshot.created_at.isoformat(),
            ),
        )
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    with pytest.raises(AppError) as error:
        run(repo.list_runs())
    assert error.value.code == "schema_version"
    with pytest.raises(AppError) as error:
        run(repo.initialize())
    assert error.value.code == "schema_version"
    assert migrate_storage(tmp_path) == 2
    assert migrate_storage(tmp_path) == 2
    with closing(sqlite3.connect(repo.database_path)) as connection:
        assert connection.execute("SELECT id FROM profiles").fetchall() == [(profile_id,)]
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert "pid" in {row[1] for row in connection.execute("PRAGMA table_info(daemon_control)")}
    assert run(repo.read_run(str(snapshot.id))).snapshot == snapshot
    assert run(repo.get_profile("kept")).config.target.model == "version-one-target"


def test_migration_and_initialization_excluded_by_live_daemon(tmp_path):
    repo = Repository(tmp_path, busy_timeout=0.1)
    run(repo.initialize())
    start_daemon(tmp_path)
    try:
        with pytest.raises(AppError) as error:
            migrate_storage(tmp_path, timeout=0.1)
        assert error.value.code == "storage_busy"
        with pytest.raises(AppError):
            run(repo.initialize())
        assert run(repo.list_runs()).items == ()
    finally:
        stop_daemon(tmp_path, timeout=5)


def test_cancelled_repository_await_keeps_worker_tracked_until_it_finishes(tmp_path):
    repo = Repository(tmp_path)
    run(repo.initialize())
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def action(connection):
        entered.set()
        assert release.wait(5)
        connection.execute("UPDATE daemon_control SET state='stopped'")
        finished.set()

    async def scenario():
        task = asyncio.create_task(repo._run(action, write=True))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            drain = asyncio.create_task(repo.drain_operations())
            await asyncio.sleep(0.05)
            assert not drain.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            await drain
            assert finished.is_set()
        finally:
            release.set()

    run(scenario())


def test_repeated_cancellation_cannot_complete_drain_before_worker_exits(tmp_path):
    repo = Repository(tmp_path)
    run(repo.initialize())
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def action(connection):
        entered.set()
        assert release.wait(5)
        connection.execute("UPDATE daemon_control SET state='stopped'")
        finished.set()

    async def scenario():
        operation = asyncio.create_task(repo._run(action, write=True))
        assert await asyncio.to_thread(entered.wait, 2)
        drain = asyncio.create_task(repo.drain_operations())
        await asyncio.sleep(0)
        try:
            for _ in range(3):
                operation.cancel()
                drain.cancel()
                await asyncio.sleep(0.02)
            assert not operation.done()
            assert not drain.done()
        finally:
            release.set()
            for task in (operation, drain):
                with pytest.raises(asyncio.CancelledError):
                    await task
        assert finished.is_set()

    run(scenario())


def test_serve_keeps_instance_lock_through_repeated_cancellation_of_db_wait(tmp_path, monkeypatch):
    from uuid import uuid4

    import portalocker

    from asclepius.daemon import serve
    from asclepius.maintenance import instance_lock

    repo = Repository(tmp_path)
    run(repo.initialize())
    entered, release = threading.Event(), threading.Event()
    original = Repository.control
    calls = 0

    def blocked_read(connection):
        entered.set()
        assert release.wait(5)
        return connection.execute("SELECT state FROM daemon_control").fetchone()[0]

    async def control(self):
        nonlocal calls
        calls += 1
        if calls == 2:
            await self._run(blocked_read)
        return await original(self)

    monkeypatch.setattr(Repository, "control", control)

    async def scenario():
        owner = asyncio.create_task(serve(tmp_path, instance_id=str(uuid4())))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            for _ in range(3):
                owner.cancel()
                await asyncio.sleep(0.02)
            assert not owner.done()
            with pytest.raises(portalocker.LockException), instance_lock(tmp_path):
                pass
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await owner
        with instance_lock(tmp_path):
            assert (await original(repo)).state == "stopped"

    run(scenario())


@pytest.mark.parametrize("path", ["//server/share/asclepius", r"\\server\share\asclepius"])
def test_network_style_storage_is_rejected_without_creating_it(path):
    from pathlib import Path

    with pytest.raises(AppError) as error:
        Repository(Path(path))
    assert error.value.code == "storage_location"


def test_migration_writer_contention_respects_its_timeout(tmp_path):
    repo = Repository(tmp_path)
    with closing(sqlite3.connect(repo.database_path, isolation_level=None)) as connection:
        connection.executescript(
            files("asclepius").joinpath("migrations/001_initial.sql").read_text()
        )
        connection.execute("PRAGMA user_version=1")
        connection.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        try:
            with pytest.raises(AppError) as error:
                migrate_storage(tmp_path, timeout=0.1)
            assert error.value.code == "storage_busy"
            assert time.monotonic() - started < 1
        finally:
            connection.rollback()


def test_failed_upgrade_rolls_back_schema_and_preserves_version(tmp_path, monkeypatch):
    import asclepius.maintenance as maintenance

    repo = Repository(tmp_path)
    with closing(sqlite3.connect(repo.database_path)) as connection:
        connection.executescript(
            files("asclepius").joinpath("migrations/001_initial.sql").read_text()
        )
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    monkeypatch.setattr(
        maintenance,
        "_script",
        lambda _: "ALTER TABLE daemon_control ADD COLUMN pid INTEGER; INVALID SQL;",
    )
    with pytest.raises(AppError):
        migrate_storage(tmp_path)
    with closing(sqlite3.connect(repo.database_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "pid" not in {
            row[1] for row in connection.execute("PRAGMA table_info(daemon_control)")
        }


def test_wsl_symlink_to_windows_storage_is_rejected(tmp_path):
    import os
    from pathlib import Path

    if os.name == "nt" or not Path("/mnt/c").is_dir():
        pytest.skip("Requires an actual WSL Windows mount")
    alias = tmp_path / "windows-alias"
    alias.symlink_to("/mnt/c", target_is_directory=True)
    with pytest.raises(AppError) as error:
        Repository(alias / "asclepius-location-probe")
    assert error.value.code == "storage_location"
