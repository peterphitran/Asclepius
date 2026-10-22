import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from asclepius.domain import (
    AppError,
    ChatInput,
    ChatOutput,
    EvidenceRef,
    Finding,
    FindingOutput,
    GenerationOutput,
    Judgment,
    JudgmentOutput,
    Message,
    Observation,
    OperationRequest,
    RunState,
    Selection,
    SelectionOutput,
    Variant,
)
from asclepius.storage import Repository
from tests.cli.storage_fixtures import OWNER, make_snapshot, prepare, run


def selection(rationale="requested check"):
    return SelectionOutput(
        selections=(
            Selection(
                check_id="test.check", check_version="1", strategy="override", rationale=rationale
            ),
        )
    )


def test_initialization_is_repeatable_and_schema_version_is_checked(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        before = await repo.events(str(snapshot.id))
        await repo.initialize()
        assert await repo.events(str(snapshot.id)) == before
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute("PRAGMA user_version=99")
        with pytest.raises(AppError) as error:
            await repo.read_run(str(snapshot.id))
        assert error.value.code == "schema_version"
        with pytest.raises(AppError):
            await repo.initialize()
        with sqlite3.connect(repo.database_path) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 99

    run(scenario())


def test_unknown_database_is_not_reset(tmp_path):
    repo = Repository(tmp_path)
    with sqlite3.connect(repo.database_path) as connection:
        connection.execute("CREATE TABLE important(value TEXT)")
        connection.execute("INSERT INTO important VALUES ('keep me')")
    with pytest.raises(AppError):
        run(repo.initialize())
    with sqlite3.connect(repo.database_path) as connection:
        assert connection.execute("SELECT value FROM important").fetchall() == [("keep me",)]


def test_schema_foreign_keys_prevent_deleting_referenced_profile(tmp_path):
    repo, _, _ = run(prepare(tmp_path))
    with sqlite3.connect(repo.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM profiles")


def test_judgment_foreign_key_binds_run_work_item_and_variant_together(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        own, _ = await observed_variant(repo, snapshot)
        other, _ = await observed_variant(repo, snapshot)
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO judgments(id,run_id,work_item_id,variant_id,document_json) "
                    "VALUES(?,?,?,?,?)",
                    (
                        str(uuid4()),
                        str(snapshot.id),
                        str(own.work_item_id),
                        str(other.work_item_id),
                        "{}",
                    ),
                )
        assert (await repo.read_run(str(snapshot.id))).judgments == ()

    run(scenario())


def test_snapshot_is_immutable_after_profile_edit(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        edited = snapshot.profile.model_copy(
            update={"target": snapshot.profile.target.model_copy(update={"model": "new-model"})}
        )
        assert await repo.save_profile(edited, profile_id=str(snapshot.profile_id)) == str(
            snapshot.profile_id
        )
        restored = await repo.read_run(str(snapshot.id))
        assert restored.snapshot.profile.target.model == "target"
        assert restored.snapshot.checks[0].version == "1"

    run(scenario())


def test_duplicate_profile_creation_cannot_silently_edit_the_existing_profile(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        changed = snapshot.profile.model_copy(
            update={
                "target": snapshot.profile.target.model_copy(
                    update={"model": "unintended-replacement"}
                )
            }
        )
        with pytest.raises(AppError) as error:
            await repo.save_profile(changed)
        assert error.value.code == "conflict"
        with sqlite3.connect(repo.database_path) as connection:
            saved = connection.execute(
                "SELECT config_json FROM profiles WHERE id=?", (str(snapshot.profile_id),)
            ).fetchone()[0]
        assert '"model":"target"' in saved
        assert "unintended-replacement" not in saved

    run(scenario())


def test_duplicate_stage_is_idempotent_but_conflicting_content_fails(tmp_path):
    async def scenario():
        repo, snapshot, work_id = await prepare(tmp_path)
        output = selection()
        assert (
            await repo.commit_stage(
                str(snapshot.id), work_id, "selector", output, instance_id=OWNER
            )
            == output
        )
        count = len(await repo.events(str(snapshot.id)))
        assert (
            await repo.commit_stage(
                str(snapshot.id), work_id, "selector", output, instance_id=OWNER
            )
            == output
        )
        assert len(await repo.events(str(snapshot.id))) == count
        with pytest.raises(AppError) as error:
            await repo.commit_stage(
                str(snapshot.id), work_id, "selector", selection("changed"), instance_id=OWNER
            )
        assert error.value.code == "conflict"
        await repo.finalize(str(snapshot.id), RunState.COMPLETED, None, instance_id=OWNER)
        assert (
            await repo.commit_stage(
                str(snapshot.id), work_id, "selector", output, instance_id=OWNER
            )
            == output
        )

    run(scenario())


def test_stage_and_event_rollback_together(tmp_path):
    async def scenario():
        repo, snapshot, work_id = await prepare(tmp_path)
        before = await repo.events(str(snapshot.id))
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute("""CREATE TRIGGER reject_stage_event BEFORE INSERT ON events
                WHEN NEW.kind='stage.completed' BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
        with pytest.raises(AppError):
            await repo.commit_stage(
                str(snapshot.id), work_id, "selector", selection(), instance_id=OWNER
            )
        assert await repo.events(str(snapshot.id)) == before
        with sqlite3.connect(repo.database_path) as connection:
            assert connection.execute("SELECT count(*) FROM stages").fetchone()[0] == 0
            connection.execute("DROP TRIGGER reject_stage_event")
        await repo.commit_stage(
            str(snapshot.id), work_id, "selector", selection(), instance_id=OWNER
        )
        events = await repo.events(str(snapshot.id))
        assert len(events) == len(before) + 1
        assert [event["sequence"] for event in events] == sorted(
            {event["sequence"] for event in events}
        )

    run(scenario())


async def observed_variant(repo, snapshot):
    variant_id = uuid4()
    await repo.register_work_item(
        str(snapshot.id),
        str(variant_id),
        "test.check",
        variant_id=str(variant_id),
        instance_id=OWNER,
    )
    request = OperationRequest(
        run_id=snapshot.id,
        work_item_id=variant_id,
        payload=ChatInput(messages=(Message(role="user", content="hello"),)),
    )
    intent = await repo.begin_operation(request, instance_id=OWNER)
    assert intent.operation_id == request.id
    assert intent.created is True
    observation = Observation(
        operation_id=request.id,
        run_id=snapshot.id,
        work_item_id=variant_id,
        status="success",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        payload=ChatOutput(content="synthetic reply"),
    )
    await repo.save_observation(observation, instance_id=OWNER)
    return request, observation


def test_judgment_finding_and_repeated_writes_preserve_provenance(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        request, observation = await observed_variant(repo, snapshot)
        evidence = (EvidenceRef(observation_id=observation.id, quote="synthetic reply"),)
        judgment = Judgment(
            variant_id=request.work_item_id,
            rubric_version="1",
            security_verdict="weakness",
            evidence=evidence,
            rationale="controlled case",
        )
        await repo.commit_stage(
            str(snapshot.id),
            str(request.work_item_id),
            "judge",
            JudgmentOutput(judgment=judgment),
            instance_id=OWNER,
        )
        finding = Finding(
            run_id=snapshot.id,
            variant_id=request.work_item_id,
            judgment_id=judgment.id,
            severity="low",
            description="Controlled finding",
            reproduction="Replay input",
            recommendation="Keep the boundary",
            evidence=evidence,
        )
        output = FindingOutput(finding=finding)
        for _ in range(2):
            await repo.save_observation(observation, instance_id=OWNER)
            await repo.commit_stage(
                str(snapshot.id), str(request.work_item_id), "reporter", output, instance_id=OWNER
            )
        view = await Repository(tmp_path).read_run(str(snapshot.id))
        assert len(view.findings) == 1
        assert view.findings[0].description == "Controlled finding"
        assert view.judgments[0].evidence[0].observation_id == view.observations[0].id
        page = await repo.list_findings(str(snapshot.id))
        assert page.items == (finding,)
        assert page.next_cursor is None
        assert await repo.read_finding(str(finding.id)) == finding

    run(scenario())


def test_fabricated_evidence_is_rejected(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        request, observation = await observed_variant(repo, snapshot)
        for reference in (
            EvidenceRef(observation_id=uuid4(), quote="synthetic reply"),
            EvidenceRef(observation_id=observation.id, quote="not in the reply"),
        ):
            judgment = Judgment(
                variant_id=request.work_item_id,
                rubric_version="1",
                security_verdict="weakness",
                evidence=(reference,),
                rationale="invalid",
            )
            with pytest.raises(AppError):
                await repo.commit_stage(
                    str(snapshot.id),
                    str(request.work_item_id),
                    "judge",
                    JudgmentOutput(judgment=judgment),
                    instance_id=OWNER,
                )
        assert (await repo.read_run(str(snapshot.id))).judgments == ()

    run(scenario())


@pytest.mark.parametrize("other_run", [False, True])
def test_existing_foreign_variant_or_run_evidence_is_rejected(tmp_path, other_run):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        request, own_observation = await observed_variant(repo, snapshot)
        other_snapshot = (await prepare(tmp_path))[1] if other_run else snapshot
        _, foreign = await observed_variant(repo, other_snapshot)
        judgment = Judgment(
            variant_id=request.work_item_id,
            rubric_version="1",
            security_verdict="weakness",
            rationale="wrong provenance",
            evidence=(EvidenceRef(observation_id=foreign.id, quote="synthetic reply"),),
        )
        with pytest.raises(AppError) as error:
            await repo.commit_stage(
                str(snapshot.id),
                str(request.work_item_id),
                "judge",
                JudgmentOutput(judgment=judgment),
                instance_id=OWNER,
            )
        assert error.value.code == "invalid_evidence"
        view = await repo.read_run(str(snapshot.id))
        assert view.observations[0].id == own_observation.id
        assert view.judgments == ()

    run(scenario())


def test_generator_materialization_is_atomic_and_idempotent(tmp_path):
    async def scenario():
        repo, snapshot, work_id = await prepare(tmp_path)
        variant = Variant(
            check_id="test.check",
            kind="attack",
            payload=ChatInput(messages=(Message(role="user", content="test input"),)),
        )
        with pytest.raises(AppError):
            await repo.commit_stage(
                str(snapshot.id),
                work_id,
                "generator",
                GenerationOutput(variants=(variant, variant)),
                instance_id=OWNER,
            )
        with sqlite3.connect(repo.database_path) as connection:
            assert (
                connection.execute(
                    "SELECT count(*) FROM work_items WHERE variant_id IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
        output = GenerationOutput(variants=(variant,))
        await repo.commit_stage(str(snapshot.id), work_id, "generator", output, instance_id=OWNER)
        await repo.commit_stage(str(snapshot.id), work_id, "generator", output, instance_id=OWNER)
        with sqlite3.connect(repo.database_path) as connection:
            rows = connection.execute(
                "SELECT variant_id,variant_json FROM work_items WHERE variant_id IS NOT NULL"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == str(variant.id)
        assert Variant.model_validate_json(rows[0][1]).payload.messages[0].content == "test input"

    run(scenario())


def test_commit_without_stage_start_preserves_unknown_start_time(tmp_path):
    async def scenario():
        repo, snapshot, work_id = await prepare(tmp_path)
        await repo.commit_stage(
            str(snapshot.id), work_id, "selector", selection(), instance_id=OWNER
        )
        with sqlite3.connect(repo.database_path) as connection:
            row = connection.execute("SELECT started_at,finished_at FROM stage_attempts").fetchone()
        assert row[0] is None
        assert datetime.fromisoformat(row[1]).tzinfo is not None

    run(scenario())


def test_stale_owner_is_fenced_from_new_operations_observations_and_finalization(tmp_path):
    async def scenario():
        repo, snapshot, work_id = await prepare(tmp_path)
        request = OperationRequest(
            run_id=snapshot.id,
            work_item_id=work_id,
            payload=ChatInput(messages=(Message(role="user", content="pending"),)),
        )
        await repo.begin_operation(request, instance_id=OWNER)
        observation = Observation(
            operation_id=request.id,
            run_id=snapshot.id,
            work_item_id=work_id,
            status="transport_error",
            error_code="timeout",
            started_at=datetime.now(UTC),
        )
        await repo.set_ready("new-owner")
        actions = [
            repo.begin_operation(request.model_copy(update={"id": uuid4()}), instance_id=OWNER),
            repo.save_observation(observation, instance_id=OWNER),
            repo.finalize(str(snapshot.id), RunState.FAILED, "failure", instance_id=OWNER),
        ]
        for action in actions:
            with pytest.raises(AppError) as error:
                await action
            assert error.value.code == "ownership"
        assert (await repo.read_run(str(snapshot.id))).state == RunState.RUNNING
        assert await repo.interrupt_orphans("new-owner") == [str(snapshot.id)]

    run(scenario())


def test_recovery_rolls_back_observations_and_state_when_event_fails(tmp_path):
    async def scenario():
        repo, snapshot, work_id = await prepare(tmp_path)
        request = OperationRequest(
            run_id=snapshot.id,
            work_item_id=work_id,
            payload=ChatInput(messages=(Message(role="user", content="pending"),)),
        )
        await repo.begin_operation(request, instance_id=OWNER)
        await repo.set_ready("new-owner")
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute("""CREATE TRIGGER reject_recovery BEFORE INSERT ON events
                WHEN NEW.kind='run.finalized' BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
        with pytest.raises(AppError):
            await repo.interrupt_orphans("new-owner")
        view = await repo.read_run(str(snapshot.id))
        assert view.state == RunState.RUNNING
        assert view.observations == ()
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute("DROP TRIGGER reject_recovery")
        assert await repo.interrupt_orphans("new-owner") == [str(snapshot.id)]
        assert (await repo.read_run(str(snapshot.id))).observations[0].status == "unknown"

    run(scenario())


def test_stale_worker_cannot_write_and_crash_does_not_replay(tmp_path):
    async def scenario():
        repo, snapshot, work_id = await prepare(tmp_path)
        request, known = await observed_variant(repo, snapshot)
        pending = request.model_copy(update={"id": uuid4()})
        assert (await repo.begin_operation(pending, instance_id=OWNER)).created is True
        repeated = await repo.begin_operation(pending, instance_id=OWNER)
        assert repeated.operation_id == pending.id
        assert repeated.created is False
        with pytest.raises(AppError) as error:
            await repo.finalize(str(snapshot.id), RunState.COMPLETED, None, instance_id=OWNER)
        assert error.value.code == "inflight"
        await repo.set_ready("new-owner")
        with pytest.raises(AppError) as error:
            await repo.commit_stage(
                str(snapshot.id), work_id, "selector", selection(), instance_id=OWNER
            )
        assert error.value.code == "ownership"
        assert await repo.interrupt_orphans("new-owner") == [str(snapshot.id)]
        assert await repo.interrupt_orphans("new-owner") == []
        view = await repo.read_run(str(snapshot.id))
        assert view.state == RunState.INTERRUPTED
        assert {item.operation_id: item.status for item in view.observations} == {
            known.operation_id: "success",
            pending.id: "unknown",
        }
        assert view.observations[0].payload.content == "synthetic reply"
        repeated = await repo.begin_operation(pending, instance_id=OWNER)
        assert repeated.created is False
        assert repeated.status == "unknown"
        assert await repo.claim_next("new-owner") is None

    run(scenario())


def test_enqueue_requires_fresh_ready_control_and_preserves_accepted_identity(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=False)
        count = len(await repo.events(str(snapshot.id)))
        assert await repo.enqueue(snapshot) == str(snapshot.id)
        assert len(await repo.events(str(snapshot.id))) == count
        new_snapshot = make_snapshot(str(snapshot.profile_id), snapshot.profile)
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute("UPDATE daemon_control SET heartbeat_at='2000-01-01T00:00:00+00:00'")
        with pytest.raises(AppError) as error:
            await repo.enqueue(new_snapshot)
        assert error.value.exit_code == 4
        with pytest.raises(AppError) as error:
            await repo.read_run(str(new_snapshot.id))
        assert error.value.exit_code == 3

    run(scenario())
