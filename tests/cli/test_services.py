import sqlite3
from uuid import uuid4

import pytest

from asclepius.domain import AppError, RunState
from asclepius.services import EvaluationService
from tests.cli.storage_fixtures import OWNER, prepare, prompts, run


def test_profiles_keep_stable_identity_revision_and_history(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        record = await repo.get_profile(str(snapshot.profile_id))
        assert record.revision == 1
        changed = record.config.model_copy(
            update={"target": record.config.target.model_copy(update={"name": "renamed"})}
        )
        assert await repo.save_profile(changed, profile_id=str(record.id)) == str(record.id)
        edited = await repo.get_profile("renamed")
        assert edited.id == record.id
        assert edited.revision == 2
        await repo.save_profile(changed, profile_id=str(record.id))
        assert (await repo.get_profile("renamed")).revision == 2
        await repo.remove_profile("renamed")
        with pytest.raises(AppError) as error:
            await repo.get_profile(str(record.id))
        assert error.value.exit_code == 3
        assert (await repo.read_run(str(snapshot.id))).snapshot.profile.target.name != "renamed"
        assert (await repo.list_profiles()).items == ()

    run(scenario())


def test_submit_pins_complete_configuration_and_requires_ready_daemon(tmp_path, monkeypatch):
    monkeypatch.setenv("KEY", "test-secret-never-stored")

    async def scenario():
        repo, source, _ = await prepare(tmp_path)
        service = EvaluationService(repo)
        identity = await service.submit(
            str(source.profile_id), source.evaluator, source.checks, prompts=prompts()
        )
        saved = await repo.read_run(identity)
        assert saved.state == RunState.QUEUED
        assert saved.snapshot.checks == source.checks
        assert saved.snapshot.prompts == prompts()
        assert "test-secret-never-stored" not in saved.model_dump_json()
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute("UPDATE daemon_control SET state='stopped'")
        with pytest.raises(AppError) as error:
            await service.submit(
                str(source.profile_id), source.evaluator, source.checks, prompts=prompts()
            )
        assert error.value.exit_code == 4
        assert len((await repo.list_runs()).items) == 2

    run(scenario())


def test_missing_credentials_and_unsupported_checks_create_no_run(tmp_path, monkeypatch):
    monkeypatch.delenv("KEY", raising=False)

    async def scenario():
        repo, source, _ = await prepare(tmp_path)
        service = EvaluationService(repo)
        with pytest.raises(AppError) as error:
            await service.submit(
                str(source.profile_id), source.evaluator, source.checks, prompts=prompts()
            )
        assert error.value.code == "credentials_missing"
        monkeypatch.setenv("KEY", "secret")
        check = source.checks[0].model_copy(update={"capabilities": ("retrieval.v1",)})
        with pytest.raises(AppError) as error:
            await service.submit(
                str(source.profile_id), source.evaluator, (check,), prompts=prompts()
            )
        assert error.value.code == "unsupported_check"
        assert len((await repo.list_runs()).items) == 1

    run(scenario())


@pytest.mark.parametrize("state", [RunState.FAILED, RunState.CANCELLED, RunState.INTERRUPTED])
def test_retry_links_new_identity_and_pins_source_despite_profile_edits(
    tmp_path, monkeypatch, state
):
    monkeypatch.setenv("KEY", "secret")

    async def scenario():
        repo, source, _ = await prepare(tmp_path)
        service = EvaluationService(repo)
        identity = await service.submit(
            str(source.profile_id), source.evaluator, source.checks, prompts=prompts()
        )
        source = await repo.claim_next(OWNER)
        assert str(source.id) == identity
        await repo.finalize(str(source.id), state, "test", instance_id=OWNER)
        before = await repo.read_run(str(source.id))
        changed = source.profile.model_copy(
            update={"target": source.profile.target.model_copy(update={"model": "edited"})}
        )
        await repo.save_profile(changed, profile_id=str(source.profile_id))
        identity = await EvaluationService(repo).retry(str(source.id))
        saved = await repo.read_run(identity)
        assert identity != str(source.id)
        assert saved.snapshot.source_run_id == source.id
        assert saved.snapshot.profile.target.model == "target"
        assert saved.snapshot.evaluator == source.evaluator
        assert saved.snapshot.checks == source.checks
        assert await repo.read_run(str(source.id)) == before

    run(scenario())


def test_cancellation_is_durable_without_daemon_and_terminal_rejection(tmp_path):
    async def scenario():
        repo, queued, _ = await prepare(tmp_path, claim=False)
        assert (await repo.request_cancel(str(queued.id))).state == RunState.CANCELLED
        with pytest.raises(AppError) as error:
            await repo.request_cancel(str(queued.id))
        assert error.value.code == "invalid_transition"
        _, active, _ = await prepare(tmp_path)
        view = await repo.request_cancel(str(active.id))
        assert view.state == RunState.RUNNING
        assert view.cancel_requested is True
        before = await repo.events(str(active.id))
        assert (await repo.request_cancel(str(active.id))).cancel_requested is True
        assert await repo.events(str(active.id)) == before

    run(scenario())


def test_removed_profile_revokes_new_submissions_and_retries_not_history(tmp_path, monkeypatch):
    monkeypatch.setenv("KEY", "secret")

    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=False)
        await repo.request_cancel(str(snapshot.id))
        await repo.remove_profile(str(snapshot.profile_id))
        with pytest.raises(AppError) as error:
            await EvaluationService(repo).retry(str(snapshot.id))
        assert error.value.exit_code == 3
        assert (await repo.read_run(str(snapshot.id))).state == RunState.CANCELLED

    run(scenario())


@pytest.mark.parametrize("state", [RunState.QUEUED, RunState.RUNNING, RunState.COMPLETED])
def test_retry_rejects_non_retryable_states(tmp_path, state):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=state != RunState.QUEUED)
        if state == RunState.COMPLETED:
            await repo.finalize(str(snapshot.id), state, None, instance_id=OWNER)
        with pytest.raises(AppError) as error:
            await EvaluationService(repo).retry(str(snapshot.id))
        assert error.value.code == "invalid_transition"
        assert (await repo.read_run(str(snapshot.id))).state == state

    run(scenario())


def test_cancelled_run_records_the_same_terminal_reason_in_view_and_event(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path, claim=False)
        cancelled = await repo.request_cancel(str(snapshot.id))
        event = (await repo.events(str(snapshot.id)))[-1]
        assert cancelled.reason == "user_cancelled"
        assert event["data"]["reason"] == cancelled.reason

    run(scenario())


def test_retry_does_not_accept_a_source_with_missing_role_prompts(tmp_path, monkeypatch):
    monkeypatch.setenv("KEY", "secret")

    async def scenario():
        repo, source, _ = await prepare(tmp_path, claim=False)
        await repo.request_cancel(str(source.id))
        with pytest.raises(AppError) as error:
            await EvaluationService(repo).retry(str(source.id))
        assert error.value.code == "invalid_plan"
        assert len((await repo.list_runs()).items) == 1

    run(scenario())


def test_submission_checks_evaluator_credential_independently(tmp_path, monkeypatch):
    monkeypatch.setenv("KEY", "target-only-secret")
    monkeypatch.delenv("EVALUATOR_KEY", raising=False)

    async def scenario():
        repo, source, _ = await prepare(tmp_path)
        content = source.evaluator.model_dump(mode="json")
        content["roles"]["judge"]["secret_ref"] = "env:EVALUATOR_KEY"
        evaluator = type(source.evaluator).model_validate(content)
        with pytest.raises(AppError) as error:
            await EvaluationService(repo).submit(
                str(source.profile_id), evaluator, source.checks, prompts=prompts()
            )
        assert error.value.code == "credentials_missing"
        assert "target-only-secret" not in str(error.value)
        assert len((await repo.list_runs()).items) == 1

    run(scenario())


def test_name_matching_removed_uuid_cannot_restore_permission_for_its_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("KEY", "secret")

    async def scenario():
        repo, source, _ = await prepare(tmp_path)
        service = EvaluationService(repo)
        identity = await service.submit(
            str(source.profile_id), source.evaluator, source.checks, prompts=prompts()
        )
        saved = await repo.read_run(identity)
        await repo.request_cancel(identity)
        await repo.remove_profile(str(source.profile_id))
        impostor = source.profile.model_copy(
            update={
                "target": source.profile.target.model_copy(update={"name": str(source.profile_id)})
            }
        )
        other_id = await repo.save_profile(impostor)
        assert other_id != str(source.profile_id)
        with pytest.raises(AppError) as error:
            await service.retry(identity)
        assert error.value.exit_code == 3
        with pytest.raises(AppError) as error:
            await repo.enqueue(saved.snapshot.model_copy(update={"id": uuid4()}))
        assert error.value.exit_code == 3
        assert (await repo.get_profile(other_id)).config.target.name == str(source.profile_id)

    run(scenario())


def test_pagination_has_explicit_cursor_and_rejects_invalid_input(tmp_path):
    async def scenario():
        repo, first, _ = await prepare(tmp_path)
        await prepare(tmp_path)
        await prepare(tmp_path)
        page = await repo.list_profiles(limit=2)
        assert len(page.items) == 2
        assert page.next_cursor is not None
        tail = await repo.list_profiles(limit=2, cursor=page.next_cursor)
        assert len(tail.items) == 1
        assert tail.next_cursor is None
        assert len({record.id for record in (*page.items, *tail.items)}) == 3
        runs = await repo.list_runs(profile_id=str(first.profile_id))
        assert [item.id for item in runs.items] == [first.id]
        for arguments in ({"limit": 501}, {"limit": 0}, {"cursor": "invalid"}):
            with pytest.raises(AppError) as error:
                await repo.list_runs(**arguments)
            assert error.value.exit_code == 2
        with pytest.raises(AppError) as error:
            await repo.read_finding_view(str(uuid4()))
        assert error.value.exit_code == 3

    run(scenario())


@pytest.mark.parametrize("value", ["abc\n", "a b", "kéy"])
def test_credential_the_daemon_would_reject_creates_no_run(tmp_path, monkeypatch, value):
    monkeypatch.setenv("KEY", value)

    async def scenario():
        repo, source, _ = await prepare(tmp_path)
        before = len((await repo.list_runs()).items)
        with pytest.raises(AppError) as error:
            await EvaluationService(repo).submit(
                str(source.profile_id), source.evaluator, source.checks, prompts=prompts()
            )
        assert error.value.code == "secret_invalid"
        assert len((await repo.list_runs()).items) == before

    run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"strategies": ("override",)},
        {"strategies": ("a", "a", "b")},
        {"evidence_criteria": ""},
        {"severity_rule": None},
    ],
)
def test_plan_that_cannot_run_is_rejected_at_submit(tmp_path, monkeypatch, change):
    monkeypatch.setenv("KEY", "secret")

    async def scenario():
        repo, source, _ = await prepare(tmp_path)
        before = len((await repo.list_runs()).items)
        check = source.checks[0].model_copy(update=change)
        with pytest.raises(AppError) as error:
            await EvaluationService(repo).submit(
                str(source.profile_id), source.evaluator, (check,), prompts=prompts()
            )
        assert error.value.code == "plan_not_executable"
        assert len((await repo.list_runs()).items) == before

    run(scenario())
