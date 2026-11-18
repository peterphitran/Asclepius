import json
import sqlite3
import sys

import pytest

from asclepius import daemon
from asclepius.domain import AppError
from asclepius.storage import Repository


def run_main(monkeypatch, capsys, failure):
    async def serve(*args, **kwargs):
        raise failure

    monkeypatch.setattr(daemon, "serve", serve)
    monkeypatch.setattr(sys, "argv", ["daemon", "--data-dir", ".", "--instance-id", "test"])
    status = daemon.main()
    output = capsys.readouterr().out
    return status, json.loads(output), output


def test_real_sqlite_busy_is_logged_without_private_data(tmp_path, monkeypatch, capsys):
    repo = Repository(tmp_path, busy_timeout=0.01)
    repo._initialize()
    with sqlite3.connect(repo.database_path, isolation_level=None) as holder:
        holder.execute("BEGIN IMMEDIATE")
        try:
            repo._transaction(lambda connection: None, True)
        except AppError as failure:
            status, payload, output = run_main(monkeypatch, capsys, failure)
        finally:
            holder.rollback()
    assert status == 5
    assert payload["error"] == "storage_busy"
    nodes = payload["diagnostics"]["exceptions"]
    native = next(node for node in nodes if node["type"] == "OperationalError")
    assert native["sqlite_code"] == sqlite3.SQLITE_BUSY
    assert native["sqlite_name"] == "SQLITE_BUSY"
    assert any(
        frame["module"] == "asclepius.storage"
        and frame["function"] == "_transaction"
        and isinstance(frame["line"], int)
        for frame in native["frames"]
    )
    assert str(tmp_path) not in output
    assert "BEGIN IMMEDIATE" not in output
    assert "database is locked" not in output


def test_cleanup_context_and_cycles_are_bounded(monkeypatch, capsys):
    try:
        raise RuntimeError("private secret")
    except RuntimeError as original:
        try:
            sqlite3.connect(":memory:").execute("invalid secret sql")
        except sqlite3.Error as cleanup:
            cleanup.__cause__ = original
            original.__cause__ = cleanup
            status, payload, output = run_main(monkeypatch, capsys, cleanup)
    assert status == 5
    nodes = payload["diagnostics"]["exceptions"]
    assert [node["type"] for node in nodes] == ["OperationalError", "RuntimeError"]
    assert nodes[0]["cause"] == 1
    assert nodes[1]["cause"] == 0
    assert "private secret" not in output
    assert "invalid secret sql" not in output


def test_exception_graph_marks_truncation(monkeypatch, capsys):
    first = sqlite3.OperationalError("secret")
    current = first
    for _ in range(20):
        current.__cause__ = RuntimeError("secret")
        current = current.__cause__
    status, payload, _ = run_main(monkeypatch, capsys, first)
    assert status == 5
    assert len(payload["diagnostics"]["exceptions"]) == 16
    assert payload["diagnostics"]["truncated"] is True


@pytest.mark.parametrize(
    ("failure", "status", "payload"),
    [
        (AppError("ownership", "secret", 4), 4, {"error": "ownership"}),
        (RuntimeError("secret"), 5, {"error": "daemon_failed"}),
    ],
)
def test_unrelated_failures_keep_existing_payload(monkeypatch, capsys, failure, status, payload):
    actual_status, actual_payload, _ = run_main(monkeypatch, capsys, failure)
    assert (actual_status, actual_payload) == (status, payload)
