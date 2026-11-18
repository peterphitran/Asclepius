import asyncio
from datetime import UTC, datetime, timedelta

from asclepius.adapters import chat
from tests.cli.groq_support import prepare_target, setup
from tests.cli.storage_fixtures import OWNER


def test_verified_https_reply_survives_utc_reversal(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        call = prepare_target(connection, work)
        await repo.begin_operation(call.request, instance_id=OWNER)
        started = datetime.now(UTC)
        finished = started - timedelta(seconds=2)
        instants = iter((started, finished))

        class ReversedUTC:
            @staticmethod
            def now(_zone):
                return next(instants)

        monkeypatch.setattr(chat, "datetime", ReversedUTC)
        observation = await connection.execute(call)
        assert observation.status == "success"
        assert observation.payload.content == "hello"
        assert observation.payload.response_id == "response-1"
        assert observation.started_at == started
        assert observation.finished_at == finished
        assert len(groq[0].calls) == 1
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations == (observation,)

    asyncio.run(scenario())
