import asyncio
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import UUID, uuid4

import portalocker
from pydantic import BaseModel, TypeAdapter, ValidationError

from asclepius.domain import (
    AppError,
    BudgetReservation,
    DaemonStatus,
    Finding,
    FindingOutput,
    GenerationOutput,
    Judgment,
    JudgmentOutput,
    Observation,
    OperationIntent,
    OperationRequest,
    Page,
    ProfileConfig,
    ProfileRecord,
    RunSnapshot,
    RunState,
    RunSummary,
    RunView,
    SelectionOutput,
    StageOutput,
    allowed_transition,
)
from asclepius.maintenance import SCHEMA_VERSION, initialize_storage, maintenance_lock
from asclepius.paths import local_directory

T = TypeVar("T")
_STAGE = TypeAdapter(StageOutput)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: BaseModel) -> str:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class Repository:
    def __init__(self, data_dir: Path, *, busy_timeout: float = 5.0) -> None:
        if busy_timeout <= 0:
            raise ValueError("Storage timeout must be positive.")
        self.data_dir = local_directory(data_dir)
        self.database_path = self.data_dir / "asclepius.sqlite3"
        self.busy_timeout = busy_timeout
        self._operations: set[asyncio.Task] = set()

    def _lock(self, exclusive: bool = False):
        return maintenance_lock(self.data_dir, exclusive=exclusive, timeout=self.busy_timeout)

    def _connect(self, create: bool = False) -> sqlite3.Connection:
        uri = self.database_path.as_uri() + ("?mode=rwc" if create else "?mode=rw")
        connection = sqlite3.connect(uri, uri=True, timeout=self.busy_timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise AppError("schema_version", "Unsupported storage schema version.")

    def _transaction(self, action: Callable[[sqlite3.Connection], T], write: bool) -> T:
        if not self.database_path.exists():
            raise AppError("storage_missing", "Initialize this data directory first.", 3)
        try:
            with self._lock(), closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                try:
                    self._schema(connection)
                    result = action(connection)
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except (portalocker.LockException, sqlite3.OperationalError) as error:
            if isinstance(error, portalocker.LockException) or "locked" in str(error).lower():
                raise AppError("storage_busy", "Storage is busy. Retry the command.") from None
            raise AppError("storage_error", "Cannot access local storage.") from None
        except sqlite3.IntegrityError:
            raise AppError("conflict", "Storage identity or relationship conflicts.") from None
        except (sqlite3.DatabaseError, ValidationError, json.JSONDecodeError):
            raise AppError(
                "storage_corrupt", "Invalid stored data. Preserve the database for inspection."
            ) from None
        except OSError:
            raise AppError("storage_error", "Cannot access the data directory.") from None

    async def _run(self, action: Callable[[sqlite3.Connection], T], write: bool = False) -> T:
        task = asyncio.create_task(asyncio.to_thread(self._transaction, action, write))
        self._operations.add(task)
        task.add_done_callback(self._operations.discard)
        return await self._finish_worker(task)

    @staticmethod
    async def _finish_worker(task: asyncio.Future[T]) -> T:
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if cancelled:
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError
        return task.result()

    async def drain_operations(self) -> None:
        cancelled = False
        while self._operations:
            try:
                await self._finish_worker(
                    asyncio.gather(*tuple(self._operations), return_exceptions=True)
                )
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        initialize_storage(self.data_dir, timeout=self.busy_timeout)

    @staticmethod
    def _run_row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise AppError("not_found", "Run was not found.", 3)
        return row

    @staticmethod
    def _ready(connection: sqlite3.Connection, instance_id: str | None = None) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM daemon_control WHERE singleton=1").fetchone()
        fresh = False
        if row and row["heartbeat_at"]:
            heartbeat = datetime.fromisoformat(row["heartbeat_at"])
            if heartbeat.tzinfo is not None:
                fresh = 0 <= (datetime.now(UTC) - heartbeat).total_seconds() <= 10
        if (
            not row
            or row["state"] != "ready"
            or not fresh
            or (instance_id is not None and row["instance_id"] != instance_id)
        ):
            raise AppError("daemon_unavailable", "Start a ready daemon for this data directory.", 4)
        return row

    def _owned(self, connection: sqlite3.Connection, run_id: str, instance_id: str) -> sqlite3.Row:
        row = self._run_row(connection, run_id)
        control = connection.execute("SELECT * FROM daemon_control WHERE singleton=1").fetchone()
        if (
            row["state"] != "running"
            or row["owner_id"] != instance_id
            or (
                not control
                or control["instance_id"] != instance_id
                or control["state"] not in {"ready", "draining"}
            )
        ):
            raise AppError("ownership", "The current instance does not own this active run.")
        return row

    @staticmethod
    def _event(connection: sqlite3.Connection, run_id: str, kind: str, **data) -> None:
        connection.execute(
            "INSERT INTO events(run_id,kind,data_json,created_at) VALUES(?,?,?,?)",
            (run_id, kind, json.dumps(data, sort_keys=True), _now()),
        )

    @staticmethod
    def _same(saved: str, proposed: str) -> None:
        if saved != proposed:
            raise AppError("conflict", "Existing identity has different committed content.")

    async def save_profile(self, config: ProfileConfig, *, profile_id: str | None = None) -> str:
        def action(connection):
            named = connection.execute(
                "SELECT * FROM profiles WHERE name=?", (config.target.name,)
            ).fetchone()
            if named and named["id"] != profile_id:
                raise AppError("conflict", "This profile name is already reserved.", 2)
            if profile_id is not None:
                existing = connection.execute(
                    "SELECT * FROM profiles WHERE id=? AND deleted_at IS NULL", (profile_id,)
                ).fetchone()
                if existing is None:
                    raise AppError("not_found", "Profile not found.", 3)
                if existing["config_json"] != _json(config):
                    connection.execute(
                        "UPDATE profiles SET name=?,config_json=?,revision=revision+1 WHERE id=?",
                        (config.target.name, _json(config), profile_id),
                    )
                return profile_id
            identity = str(uuid4())
            connection.execute(
                "INSERT INTO profiles(id,name,config_json,revision) VALUES(?,?,?,1)",
                (identity, config.target.name, _json(config)),
            )
            return identity

        return await self._run(action, write=True)

    async def set_ready(self, instance_id: str, *, pid: int | None = None) -> None:
        def action(connection):
            connection.execute(
                "UPDATE daemon_control SET instance_id=?,state='ready',heartbeat_at=?,pid=? "
                "WHERE singleton=1",
                (instance_id, _now(), pid),
            )

        await self._run(action, write=True)

    async def control(self) -> DaemonStatus:
        def action(connection):
            row = connection.execute("SELECT * FROM daemon_control WHERE singleton=1").fetchone()
            return DaemonStatus(
                instance_id=row["instance_id"],
                state=row["state"],
                pid=row["pid"],
                heartbeat_at=row["heartbeat_at"],
            )

        return await self._run(action)

    async def heartbeat(self, instance_id: str) -> None:
        def action(connection):
            cursor = connection.execute(
                "UPDATE daemon_control SET heartbeat_at=? WHERE instance_id=? "
                "AND state IN ('ready','draining')",
                (_now(), instance_id),
            )
            if cursor.rowcount != 1:
                raise AppError("ownership", "Daemon ownership changed.")

        await self._run(action, write=True)

    async def request_stop(self, instance_id: str) -> None:
        def action(connection):
            cursor = connection.execute(
                "UPDATE daemon_control SET state='draining' WHERE instance_id=? "
                "AND state IN ('ready','draining')",
                (instance_id,),
            )
            if cursor.rowcount != 1:
                raise AppError("ownership", "Daemon ownership changed. Inspect status again.")

        await self._run(action, write=True)

    async def set_stopped(self, instance_id: str) -> None:
        await self._run(
            lambda connection: (
                connection.execute(
                    "UPDATE daemon_control SET state='stopped',pid=NULL,heartbeat_at=? "
                    "WHERE instance_id=?",
                    (_now(), instance_id),
                ).rowcount
            ),
            write=True,
        )

    async def active_count(self, instance_id: str) -> int:
        return await self._run(
            lambda connection: connection.execute(
                "SELECT count(*) FROM runs WHERE state='running' AND owner_id=?", (instance_id,)
            ).fetchone()[0]
        )

    def _execution(self, connection, run_id: str, instance_id: str) -> sqlite3.Row:
        row = self._owned(connection, run_id, instance_id)
        if row["cancel_requested"]:
            raise AppError("run_cancelled", "Run cancellation was requested.")
        if row["reason"] == "budget_exhausted":
            raise AppError("budget_exhausted", "Run execution budget is exhausted.")
        snapshot = RunSnapshot.model_validate_json(row["snapshot_json"])
        elapsed = (datetime.now(UTC) - datetime.fromisoformat(row["started_at"])).total_seconds()
        if elapsed >= snapshot.profile.limits.run_timeout_seconds:
            raise AppError("run_timeout", "Run execution deadline expired.")
        return row

    async def execution_checkpoint(self, run_id: str, instance_id: str) -> None:
        await self._run(lambda connection: self._execution(connection, run_id, instance_id)["id"])

    async def reserve_budget(self, reservation: BudgetReservation, instance_id: str) -> None:
        def action(connection):
            row = self._execution(connection, str(reservation.run_id), instance_id)
            limits = RunSnapshot.model_validate_json(row["snapshot_json"]).profile.limits
            if reservation.kind == "cleanup":
                raise AppError(
                    "unsupported_operation", "Cleanup requires a separate budget contract.", 2
                )
            counts = connection.execute(
                "SELECT count(*),COALESCE(sum(max_output),0),COALESCE(sum(kind=?),0) "
                "FROM budget_reservations WHERE run_id=? AND state<>'released'",
                (reservation.kind, str(reservation.run_id)),
            ).fetchone()
            cap = limits.target_calls if reservation.kind == "target" else limits.evaluator_calls
            if (
                counts[0] >= limits.total_calls
                or counts[2] >= cap
                or counts[1] + reservation.max_output > limits.completion_tokens
            ):
                connection.execute(
                    "UPDATE runs SET reason='budget_exhausted' WHERE id=?",
                    (str(reservation.run_id),),
                )
                self._event(connection, str(reservation.run_id), "run.budget_exhausted")
                return False
            connection.execute(
                "INSERT INTO budget_reservations VALUES(?,?,?,?,'reserved')",
                (
                    str(reservation.id),
                    str(reservation.run_id),
                    reservation.kind,
                    reservation.max_output,
                ),
            )
            return True

        accepted = await self._run(action, write=True)
        if not accepted:
            raise AppError("budget_exhausted", "Run execution budget is exhausted.")

    async def change_reservation(
        self, reservation: BudgetReservation, state: str, instance_id: str
    ) -> None:
        def action(connection):
            self._owned(connection, str(reservation.run_id), instance_id)
            row = connection.execute(
                "SELECT * FROM budget_reservations WHERE id=?", (str(reservation.id),)
            ).fetchone()
            if row is None or (row["run_id"], row["kind"], row["max_output"]) != (
                str(reservation.run_id),
                reservation.kind,
                reservation.max_output,
            ):
                raise AppError("conflict", "Budget reservation identity conflicts.")
            if row["state"] == state and state in {"settled", "released"}:
                return
            prior = {"dispatched": "reserved", "settled": "dispatched", "released": "reserved"}
            if state not in prior or row["state"] != prior[state]:
                raise AppError("conflict", "Budget reservation transition is not allowed.")
            if state == "dispatched":
                self._execution(connection, str(reservation.run_id), instance_id)
            connection.execute(
                "UPDATE budget_reservations SET state=? WHERE id=?", (state, str(reservation.id))
            )

        await self._run(action, write=True)

    async def enqueue(self, snapshot: RunSnapshot) -> str:
        def action(connection):
            identity = str(snapshot.id)
            existing = connection.execute(
                "SELECT snapshot_json FROM runs WHERE id=?", (identity,)
            ).fetchone()
            if existing:
                self._same(_json(RunSnapshot.model_validate_json(existing[0])), _json(snapshot))
                return identity
            self._ready(connection)
            self._profile_row(connection, snapshot.profile_id)
            connection.execute(
                "INSERT INTO runs(id,profile_id,snapshot_json,source_run_id,state,created_at) "
                "VALUES(?,?,?,?,'queued',?)",
                (
                    identity,
                    str(snapshot.profile_id),
                    _json(snapshot),
                    str(snapshot.source_run_id) if snapshot.source_run_id else None,
                    snapshot.created_at.isoformat(),
                ),
            )
            self._event(connection, identity, "run.queued")
            return identity

        return await self._run(action, write=True)

    async def claim_next(self, instance_id: str) -> RunSnapshot | None:
        def action(connection):
            self._ready(connection, instance_id)
            row = connection.execute(
                "SELECT * FROM runs WHERE state='queued' ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            changed = connection.execute(
                "UPDATE runs SET state='running',owner_id=?,started_at=? "
                "WHERE id=? AND state='queued'",
                (instance_id, _now(), row["id"]),
            )
            if changed.rowcount != 1:
                raise AppError("conflict", "Queued run changed before its claim.")
            self._event(connection, row["id"], "run.started", instance_id=instance_id)
            return RunSnapshot.model_validate_json(row["snapshot_json"])

        return await self._run(action, write=True)

    async def register_work_item(
        self,
        run_id: str,
        work_item_id: str,
        check_id: str,
        variant_id: str | None = None,
        *,
        instance_id: str,
    ) -> None:
        def action(connection):
            row = self._owned(connection, run_id, instance_id)
            snapshot = RunSnapshot.model_validate_json(row["snapshot_json"])
            if check_id not in {check.id for check in snapshot.checks}:
                raise AppError("invalid_output", "Work item does not belong to a requested check.")
            existing = connection.execute(
                "SELECT * FROM work_items WHERE run_id=? AND id=?", (run_id, work_item_id)
            ).fetchone()
            if existing:
                if existing["check_id"] != check_id or existing["variant_id"] != variant_id:
                    raise AppError("conflict", "Work item identity has different content.")
                return
            connection.execute(
                "INSERT INTO work_items(run_id,id,check_id,variant_id) VALUES(?,?,?,?)",
                (run_id, work_item_id, check_id, variant_id),
            )

        await self._run(action, write=True)

    def _evidence(self, connection, run_id, work_item_id, references) -> None:
        for reference in references:
            row = connection.execute(
                "SELECT document_json FROM observations WHERE id=? AND run_id=? AND work_item_id=?",
                (str(reference.observation_id), run_id, work_item_id),
            ).fetchone()
            observation = Observation.model_validate_json(row[0]) if row else None
            if (
                not observation
                or not observation.payload
                or reference.quote not in observation.payload.content
            ):
                raise AppError(
                    "invalid_evidence", "Evidence does not match this work item's observed reply."
                )

    async def commit_stage(
        self, run_id: str, work_item_id: str, stage: str, output: StageOutput, *, instance_id: str
    ) -> StageOutput:
        def action(connection):
            if output.stage != stage:
                raise AppError("invalid_output", "Stage and output type do not match.")
            existing = connection.execute(
                "SELECT output_json FROM stages WHERE run_id=? AND work_item_id=? AND stage=?",
                (run_id, work_item_id, stage),
            ).fetchone()
            if existing:
                self._same(_json(_STAGE.validate_json(existing[0])), _json(output))
                return _STAGE.validate_json(existing[0])
            run_row = self._owned(connection, run_id, instance_id)
            work = connection.execute(
                "SELECT * FROM work_items WHERE run_id=? AND id=?", (run_id, work_item_id)
            ).fetchone()
            if work is None:
                raise AppError("not_found", "Work item was not found.", 3)
            if isinstance(output, SelectionOutput):
                checks = {
                    check.id: check.version
                    for check in RunSnapshot.model_validate_json(run_row["snapshot_json"]).checks
                }
                if any(
                    checks.get(item.check_id) != item.check_version for item in output.selections
                ):
                    raise AppError(
                        "invalid_output", "Selection references an unrequested check version."
                    )
            elif isinstance(output, GenerationOutput):
                for variant in output.variants:
                    if variant.check_id != work["check_id"]:
                        raise AppError(
                            "invalid_output", "Variant does not match the work item check."
                        )
                    connection.execute(
                        "INSERT INTO work_items(run_id,id,check_id,variant_id,variant_json) "
                        "VALUES(?,?,?,?,?)",
                        (
                            run_id,
                            str(variant.id),
                            variant.check_id,
                            str(variant.id),
                            _json(variant),
                        ),
                    )
            elif isinstance(output, JudgmentOutput):
                judgment = output.judgment
                if str(judgment.variant_id) != work["variant_id"]:
                    raise AppError(
                        "invalid_output", "Judgment does not match the work item variant."
                    )
                self._evidence(connection, run_id, work_item_id, judgment.evidence)
                connection.execute(
                    "INSERT INTO judgments(id,run_id,work_item_id,variant_id,document_json) "
                    "VALUES(?,?,?,?,?)",
                    (
                        str(judgment.id),
                        run_id,
                        work_item_id,
                        str(judgment.variant_id),
                        _json(judgment),
                    ),
                )
            elif isinstance(output, FindingOutput):
                finding = output.finding
                if str(finding.run_id) != run_id or str(finding.variant_id) != work["variant_id"]:
                    raise AppError("invalid_output", "Finding does not match its run and variant.")
                judgment_row = connection.execute(
                    "SELECT document_json FROM judgments WHERE id=? AND run_id=? AND variant_id=?",
                    (str(finding.judgment_id), run_id, str(finding.variant_id)),
                ).fetchone()
                judgment = Judgment.model_validate_json(judgment_row[0]) if judgment_row else None
                if (
                    not judgment
                    or judgment.security_verdict != "weakness"
                    or not set(finding.evidence) <= set(judgment.evidence)
                ):
                    raise AppError(
                        "invalid_evidence", "Finding must cite its weakness judgment's evidence."
                    )
                self._evidence(connection, run_id, work_item_id, finding.evidence)
                connection.execute(
                    "INSERT INTO findings(id,run_id,variant_id,judgment_id,document_json) "
                    "VALUES(?,?,?,?,?)",
                    (
                        str(finding.id),
                        run_id,
                        str(finding.variant_id),
                        str(finding.judgment_id),
                        _json(finding),
                    ),
                )
            timestamp = _now()
            connection.execute(
                "INSERT INTO stages VALUES(?,?,?,?,?)",
                (run_id, work_item_id, stage, _json(output), timestamp),
            )
            connection.execute(
                "INSERT INTO stage_attempts VALUES(?,?,?,1,'completed',NULL,?,NULL)",
                (run_id, work_item_id, stage, timestamp),
            )
            self._event(
                connection, run_id, "stage.completed", work_item_id=work_item_id, stage=stage
            )
            return output

        return await self._run(action, write=True)

    async def begin_operation(
        self, request: OperationRequest, *, instance_id: str
    ) -> OperationIntent:
        def action(connection):
            existing = connection.execute(
                "SELECT request_json,status FROM operations WHERE id=?", (str(request.id),)
            ).fetchone()
            if existing:
                self._same(_json(OperationRequest.model_validate_json(existing[0])), _json(request))
                return OperationIntent(
                    operation_id=request.id, created=False, status=existing["status"]
                )
            self._owned(connection, str(request.run_id), instance_id)
            connection.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,'pending')",
                (
                    str(request.id),
                    str(request.run_id),
                    str(request.work_item_id),
                    _json(request),
                    _now(),
                ),
            )
            self._event(
                connection, str(request.run_id), "operation.started", operation_id=str(request.id)
            )
            return OperationIntent(operation_id=request.id, created=True, status="pending")

        return await self._run(action, write=True)

    def _save_observation(self, connection, observation: Observation) -> None:
        connection.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?)",
            (
                str(observation.id),
                str(observation.operation_id),
                str(observation.run_id),
                str(observation.work_item_id),
                _json(observation),
            ),
        )
        connection.execute(
            "UPDATE operations SET status=? WHERE id=?",
            (
                "unknown" if observation.status == "unknown" else "observed",
                str(observation.operation_id),
            ),
        )
        self._event(
            connection,
            str(observation.run_id),
            "operation.observed",
            operation_id=str(observation.operation_id),
            status=observation.status,
        )

    async def save_observation(self, observation: Observation, *, instance_id: str) -> None:
        def action(connection):
            existing = connection.execute(
                "SELECT document_json FROM observations WHERE operation_id=?",
                (str(observation.operation_id),),
            ).fetchone()
            if existing:
                self._same(_json(Observation.model_validate_json(existing[0])), _json(observation))
                return
            self._owned(connection, str(observation.run_id), instance_id)
            operation = connection.execute(
                "SELECT request_json FROM operations WHERE id=?", (str(observation.operation_id),)
            ).fetchone()
            request = OperationRequest.model_validate_json(operation[0]) if operation else None
            if (
                not request
                or request.run_id != observation.run_id
                or (
                    request.work_item_id != observation.work_item_id
                    or request.actor != observation.actor
                )
            ):
                raise AppError("invalid_output", "Observation does not match its operation.")
            self._save_observation(connection, observation)

        await self._run(action, write=True)

    async def events(self, run_id: str, after: int = 0) -> list[dict]:
        def action(connection):
            self._run_row(connection, run_id)
            rows = connection.execute(
                "SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence",
                (run_id, after),
            ).fetchall()
            return [
                {
                    "sequence": row["sequence"],
                    "kind": row["kind"],
                    "data": json.loads(row["data_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

        return await self._run(action)

    @staticmethod
    def _view(connection: sqlite3.Connection, row: sqlite3.Row) -> RunView:
        def documents(table, model):
            return tuple(
                model.model_validate_json(item[0])
                for item in connection.execute(
                    f"SELECT document_json FROM {table} WHERE run_id=? ORDER BY rowid",
                    (row["id"],),
                )
            )

        return RunView(
            snapshot=RunSnapshot.model_validate_json(row["snapshot_json"]),
            state=row["state"],
            cancel_requested=bool(row["cancel_requested"]),
            reason=row["reason"],
            observations=documents("observations", Observation),
            judgments=documents("judgments", Judgment),
            findings=documents("findings", Finding),
        )

    async def read_run(self, run_id: str) -> RunView:
        return await self._run(
            lambda connection: self._view(connection, self._run_row(connection, run_id))
        )

    @staticmethod
    def _profile_row(connection: sqlite3.Connection, identity: str | UUID) -> sqlite3.Row:
        if isinstance(identity, UUID):
            rows = connection.execute(
                "SELECT * FROM profiles WHERE id=? AND deleted_at IS NULL", (str(identity),)
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM profiles WHERE (id=? OR name=?) AND deleted_at IS NULL",
                (identity, identity),
            ).fetchall()
        if not rows:
            raise AppError("not_found", "Profile not found.", 3)
        if len(rows) != 1:
            raise AppError(
                "ambiguous_profile",
                "Profile selector is ambiguous. Rename the matching profile.",
                2,
            )
        return rows[0]

    @staticmethod
    def _profile(row: sqlite3.Row) -> ProfileRecord:
        return ProfileRecord(
            id=row["id"],
            revision=row["revision"],
            config=ProfileConfig.model_validate_json(row["config_json"]),
        )

    async def get_profile(self, identity: str | UUID) -> ProfileRecord:
        return await self._run(
            lambda connection: self._profile(self._profile_row(connection, identity))
        )

    @staticmethod
    def _page_input(limit: int, cursor: str | None) -> str:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise AppError("pagination", "Page size must be between 1 and 500.", 2)
        if cursor is None:
            return ""
        try:
            if str(UUID(cursor)) != cursor:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise AppError("pagination", "Invalid page cursor.", 2) from None
        return cursor

    async def list_profiles(
        self, *, limit: int = 50, cursor: str | None = None
    ) -> Page[ProfileRecord]:
        after = self._page_input(limit, cursor)

        def action(connection):
            rows = connection.execute(
                "SELECT * FROM profiles WHERE deleted_at IS NULL AND id>? ORDER BY id LIMIT ?",
                (after, limit + 1),
            ).fetchall()
            return Page[ProfileRecord](
                items=tuple(self._profile(row) for row in rows[:limit]),
                next_cursor=rows[limit - 1]["id"] if len(rows) > limit else None,
            )

        return await self._run(action)

    async def remove_profile(self, identity: str) -> str:
        def action(connection):
            row = self._profile_row(connection, identity)
            connection.execute("UPDATE profiles SET deleted_at=? WHERE id=?", (_now(), row["id"]))
            return row["id"]

        return await self._run(action, write=True)

    async def list_runs(
        self, *, profile_id: str | None = None, limit: int = 50, cursor: str | None = None
    ) -> Page[RunSummary]:
        after = self._page_input(limit, cursor)

        def action(connection):
            rows = connection.execute(
                "SELECT id,profile_id,state,cancel_requested,created_at,source_run_id,"
                "json_extract(snapshot_json,'$.profile.target.name') AS profile_name FROM runs "
                "WHERE id>? AND (? IS NULL OR profile_id=?) ORDER BY id LIMIT ?",
                (after, profile_id, profile_id, limit + 1),
            ).fetchall()
            return Page[RunSummary](
                items=tuple(RunSummary(**dict(row)) for row in rows[:limit]),
                next_cursor=rows[limit - 1]["id"] if len(rows) > limit else None,
            )

        return await self._run(action)

    async def list_findings(
        self, run_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> Page[Finding]:
        after = self._page_input(limit, cursor)

        def action(connection):
            self._run_row(connection, run_id)
            rows = connection.execute(
                "SELECT id,document_json FROM findings WHERE run_id=? AND id>? ORDER BY id LIMIT ?",
                (run_id, after, limit + 1),
            ).fetchall()
            return Page[Finding](
                items=tuple(
                    Finding.model_validate_json(row["document_json"]) for row in rows[:limit]
                ),
                next_cursor=rows[limit - 1]["id"] if len(rows) > limit else None,
            )

        return await self._run(action)

    async def read_finding(self, finding_id: str) -> Finding:
        def action(connection):
            row = connection.execute(
                "SELECT document_json FROM findings WHERE id=?", (finding_id,)
            ).fetchone()
            if row is None:
                raise AppError("not_found", "Finding not found.", 3)
            return Finding.model_validate_json(row[0])

        return await self._run(action)

    async def request_cancel(self, run_id: str) -> RunView:
        def action(connection):
            row = self._run_row(connection, run_id)
            if row["state"] not in {"queued", "running"}:
                raise AppError("invalid_transition", "A terminal run cannot be cancelled.", 2)
            if not row["cancel_requested"]:
                if row["state"] == "queued":
                    connection.execute(
                        "UPDATE runs SET state='cancelled',cancel_requested=1,"
                        "reason='user_cancelled',finished_at=? "
                        "WHERE id=?",
                        (_now(), run_id),
                    )
                    self._event(
                        connection,
                        run_id,
                        "run.finalized",
                        state="cancelled",
                        reason="user_cancelled",
                    )
                else:
                    connection.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
                    self._event(connection, run_id, "run.cancel_requested")
            return self._view(connection, self._run_row(connection, run_id))

        return await self._run(action, write=True)

    async def finalize(
        self, run_id: str, state: RunState, reason: str | None, *, instance_id: str
    ) -> None:
        def action(connection):
            row = self._run_row(connection, run_id)
            if (
                row["state"] == state
                and row["reason"] == reason
                and state not in {RunState.QUEUED, RunState.RUNNING}
            ):
                return
            row = self._owned(connection, run_id, instance_id)
            if state == RunState.COMPLETED and row["reason"] == "budget_exhausted":
                raise AppError("budget_exhausted", "An exhausted run cannot complete successfully.")
            if state in {RunState.QUEUED, RunState.RUNNING}:
                raise AppError("invalid_transition", "Finalization requires a terminal state.", 2)
            allowed_transition(RunState(row["state"]), state)
            if connection.execute(
                "SELECT 1 FROM operations WHERE run_id=? AND status='pending'", (run_id,)
            ).fetchone():
                raise AppError("inflight", "Settle pending operations before finalizing this run.")
            connection.execute(
                "UPDATE runs SET state=?,reason=?,owner_id=NULL,finished_at=? WHERE id=?",
                (state.value, reason, _now(), run_id),
            )
            self._event(connection, run_id, "run.finalized", state=state.value, reason=reason)

        await self._run(action, write=True)

    async def interrupt_orphans(self, instance_id: str) -> list[str]:
        def action(connection):
            self._ready(connection, instance_id)
            rows = connection.execute(
                "SELECT id FROM runs WHERE state='running' AND owner_id<>? ORDER BY created_at,id",
                (instance_id,),
            ).fetchall()
            identities = []
            for row in rows:
                identity = row["id"]
                operations = connection.execute(
                    "SELECT * FROM operations WHERE run_id=? AND status='pending'", (identity,)
                ).fetchall()
                for operation in operations:
                    request = OperationRequest.model_validate_json(operation["request_json"])
                    observation = Observation(
                        operation_id=request.id,
                        run_id=request.run_id,
                        work_item_id=request.work_item_id,
                        actor=request.actor,
                        status="unknown",
                        started_at=operation["started_at"],
                        error_code="owner_lost",
                    )
                    self._save_observation(connection, observation)
                connection.execute(
                    "UPDATE runs SET state='interrupted',owner_id=NULL,reason='owner_lost',"
                    "finished_at=? WHERE id=?",
                    (_now(), identity),
                )
                self._event(
                    connection, identity, "run.finalized", state="interrupted", reason="owner_lost"
                )
                identities.append(identity)
            return identities

        return await self._run(action, write=True)
