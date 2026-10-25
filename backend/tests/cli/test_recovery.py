from pathlib import Path

import pytest

from scripts.recovery_fixture import crash_scenario

CERTIFICATES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("point", ["before_send", "target_received", "after_reporter"])
def test_killed_owner_manual_restart_and_linked_retry(tmp_path, point):
    crash_scenario(tmp_path, CERTIFICATES, point)


def test_stale_owner_cannot_append_new_run_or_overwrite_recovered_evidence(tmp_path):
    import asyncio
    from uuid import uuid4

    from asclepius.domain import AppError, ChatInput, Message, OperationRequest, RunState
    from tests.cli.storage_fixtures import OWNER, prepare

    async def scenario():
        repo, source, work = await prepare(tmp_path)
        request = OperationRequest(
            run_id=source.id,
            work_item_id=work,
            payload=ChatInput(messages=(Message(role="user", content="uncertain"),)),
        )
        await repo.begin_operation(request, instance_id=OWNER)
        replacement = "new-owner"
        await repo.set_ready(replacement)
        await repo.interrupt_orphans(replacement)
        source_before = await repo.read_run(str(source.id))
        new = source.model_copy(update={"id": uuid4(), "source_run_id": source.id})
        await repo.enqueue(new)
        assert (await repo.claim_next(replacement)).id == new.id
        new_work = str(uuid4())
        await repo.register_work_item(
            str(new.id), new_work, source.checks[0].id, instance_id=replacement
        )
        attempted = request.model_copy(
            update={"id": uuid4(), "run_id": new.id, "work_item_id": new_work}
        )
        for action in (
            repo.begin_operation(attempted, instance_id=OWNER),
            repo.finalize(str(new.id), RunState.FAILED, "stale", instance_id=OWNER),
            repo.finalize(str(source.id), RunState.COMPLETED, None, instance_id=OWNER),
            repo.save_observation(
                source_before.observations[0].model_copy(
                    update={"payload": None, "error_code": "changed"}
                ),
                instance_id=OWNER,
            ),
        ):
            with pytest.raises(AppError):
                await action
        replay = await repo.begin_operation(request, instance_id=OWNER)
        assert not replay.created and replay.status == "unknown"
        await repo.save_observation(source_before.observations[0], instance_id=OWNER)
        assert await repo.enqueue(source) == str(source.id)
        assert await repo.read_run(str(source.id)) == source_before
        assert (await repo.read_run(str(new.id))).state == RunState.RUNNING
        assert rows_for_run(repo.database_path, str(new.id)) == []

    def rows_for_run(database, run):
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(database)) as db:
            return db.execute("SELECT id FROM operations WHERE run_id=?", (run,)).fetchall()

    asyncio.run(scenario())
