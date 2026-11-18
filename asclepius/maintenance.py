import sqlite3
from contextlib import closing
from importlib.resources import files
from pathlib import Path
from uuid import UUID

import portalocker

from asclepius.domain import AppError
from asclepius.paths import local_directory

MIGRATIONS = ("001_initial.sql", "002_daemon_pid.sql", "003_execution.sql", "004_elapsed.sql")
SCHEMA_VERSION = len(MIGRATIONS)


def instance_lock(data_dir: Path, *, timeout: float = 0):
    return portalocker.Lock(
        data_dir / "instance.lock",
        mode="a",
        timeout=timeout,
        flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
    )


def maintenance_lock(data_dir: Path, *, exclusive: bool = False, timeout: float = 5):
    mode = portalocker.LOCK_EX if exclusive else portalocker.LOCK_SH
    return portalocker.Lock(
        data_dir / "maintenance.lock", mode="a", timeout=timeout, flags=mode | portalocker.LOCK_NB
    )


def readiness_lock(data_dir: Path, instance_id: str):
    identity = str(UUID(instance_id))
    return portalocker.Lock(
        data_dir / f"ready-{identity}.lock",
        mode="a",
        timeout=0,
        flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
    )


def _script(name: str) -> str:
    return files("asclepius").joinpath(f"migrations/{name}").read_text(encoding="utf-8")


def initialize_storage(data_dir: Path, *, timeout: float = 5) -> None:
    _change_schema(data_dir, initialize=True, timeout=timeout)


def migrate_storage(data_dir: Path, *, timeout: float = 5) -> int:
    return _change_schema(data_dir, initialize=False, timeout=timeout)


def _change_schema(data_dir: Path, *, initialize: bool, timeout: float) -> int:
    directory = local_directory(data_dir)
    try:
        if initialize:
            directory.mkdir(parents=True, exist_ok=True)
        database = directory / "asclepius.sqlite3"
        if not initialize and not database.exists():
            raise AppError("storage_missing", "Initialize this data directory first.", 3)
        with (
            instance_lock(directory, timeout=timeout),
            maintenance_lock(directory, exclusive=True, timeout=timeout),
            closing(sqlite3.connect(database, isolation_level=None, timeout=timeout)) as connection,
        ):
            connection.execute("PRAGMA foreign_keys=ON")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == SCHEMA_VERSION:
                return version
            if initialize:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                if version != 0 or tables:
                    raise AppError("schema_version", "Unsupported storage schema version.")
                connection.execute("PRAGMA journal_mode=WAL")
                sql = "\n".join(_script(name) for name in MIGRATIONS)
            else:
                raise AppError("schema_version", "Unsupported storage schema version.")
            try:
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;"
                )
            except BaseException:
                connection.rollback()
                raise
            return SCHEMA_VERSION
    except portalocker.LockException:
        raise AppError("storage_busy", "Stop the daemon and wait for maintenance access.") from None
    except sqlite3.OperationalError as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise AppError(
                "storage_busy", "Storage is busy. Retry maintenance after other commands finish."
            ) from None
        raise AppError("storage_error", "Cannot initialize or migrate local storage.") from None
    except (OSError, sqlite3.DatabaseError):
        raise AppError("storage_error", "Cannot initialize or migrate local storage.") from None
