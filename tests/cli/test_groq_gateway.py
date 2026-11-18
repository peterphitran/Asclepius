import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from asclepius.adapters.chat import GroqConnection
from asclepius.domain import (
    AppError,
    ChatInput,
    Message,
)
from asclepius.limits import BudgetManager
from asclepius.models import ModelGateway, strict_schema
from tests.cli.groq_support import (
    Answer,
    execute_target,
    prepare_target,
    reply,
    request,
    reservations,
    setup,
)
from tests.cli.storage_fixtures import OWNER


def test_missing_selected_secret_never_dispatches(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch)
        monkeypatch.delenv("TARGET_KEY")
        connection = GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        with pytest.raises(AppError) as caught:
            await execute_target(connection, work)
        assert caught.value.code == "secret_missing"
        assert groq[0].calls == []
        assert reservations(repo) == []

    asyncio.run(scenario())


def test_wrong_run_and_oversized_input_never_dispatch(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        for invalid in (
            request(snapshot, work).model_copy(update={"run_id": uuid4()}),
            request(snapshot, work, "x" * 20000),
        ):
            with pytest.raises(AppError):
                await connection.execute(connection.prepare(invalid))
        assert groq[0].calls == []
        assert reservations(repo) == []

    asyncio.run(scenario())


def test_schema_keeps_fields_named_default_and_requires_defaulted_properties():
    class Inner(BaseModel):
        model_config = ConfigDict(extra="forbid")
        default: str = "unchanged"

    class Outer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        nested: Inner
        optional: str | None = None

    schema = strict_schema(Outer)
    assert schema["$defs"]["Inner"]["properties"]["default"]["type"] == "string"
    assert schema["$defs"]["Inner"]["required"] == ["default"]
    assert schema["required"] == ["nested", "optional"]
    assert "default" not in schema["properties"]["optional"]
    assert schema["properties"]["optional"]["anyOf"] == [{"type": "string"}, {"type": "null"}]


def test_schema_rejects_models_that_silently_drop_extra_fields():
    class Loose(BaseModel):
        value: str

    with pytest.raises(AppError) as caught:
        strict_schema(Loose)
    assert caught.value.code == "unsupported_schema"


def test_gateway_rejects_another_work_item_before_dispatch(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, _, _, _, gateway = await setup(groq, tmp_path, monkeypatch)
        call = gateway.prepare("judge", {}, Answer)
        other = ModelGateway(gateway.connection, work_item_id=uuid4())
        with pytest.raises(AppError) as caught:
            await other.execute(call)
        assert caught.value.code == "operation_identity"
        assert groq[0].calls == []
        assert reservations(repo) == []

    asyncio.run(scenario())


def test_invalid_unicode_input_never_dispatches(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        with pytest.raises(AppError) as caught:
            await execute_target(connection, work, "\ud800")
        assert caught.value.code == "invalid_input"
        assert groq[0].calls == []
        assert reservations(repo) == []

    asyncio.run(scenario())


def test_captured_credentials_remain_bound_to_run(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        monkeypatch.setenv("TARGET_KEY", "changed-after-capture")
        groq[0].body = json.dumps(reply("target-secret-123 synthetic-canary")).encode()
        observation = await execute_target(connection, work)
        assert groq[0].calls[0][1]["Authorization"] == "Bearer target-secret-123"
        assert observation.payload.content == "[REDACTED] synthetic-canary"

    asyncio.run(scenario())


def test_evaluator_generate_failure_exposes_immutable_evidence(groq, tmp_path, monkeypatch):
    async def scenario():
        _, _, _, _, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply("invalid output")).encode()
        with pytest.raises(AppError) as caught:
            await gateway.generate("judge", {}, Answer)
        assert caught.value.code == "evaluator_invalid_output"
        assert caught.value.result.observation.payload.content == "invalid output"
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def test_schema_rejection_never_uses_fallback(groq, tmp_path, monkeypatch):
    class OpenMapping(BaseModel):
        model_config = ConfigDict(extra="forbid")
        values: dict[str, str]

    async def scenario():
        repo, _, _, _, gateway = await setup(groq, tmp_path, monkeypatch)
        with pytest.raises(AppError) as caught:
            await gateway.generate("judge", {}, OpenMapping)
        assert caught.value.code == "unsupported_schema"
        assert groq[0].calls == []
        assert reservations(repo) == []

    asyncio.run(scenario())


def test_target_and_evaluator_share_the_same_outbound_gate(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, gateway = await setup(
            groq, tmp_path, monkeypatch, outbound_concurrency=1
        )
        groq[0].delay = 0.2
        groq[0].body = json.dumps(reply('{"verdict":"pass","score":2}')).encode()
        target, evaluator = await asyncio.gather(
            execute_target(connection, work), gateway.generate("judge", {}, Answer)
        )
        assert target.status == "success"
        assert evaluator == Answer(verdict="pass", score=2)
        assert groq[0].peak == 1
        assert len(groq[0].calls) == 2
        assert sorted(reservations(repo)) == [
            ("evaluator", "settled", 2048),
            ("target", "settled", 512),
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize("content", ["{}", '{"score":NaN}'])
def test_wire_schema_cannot_be_satisfied_by_local_defaults(groq, tmp_path, monkeypatch, content):
    class Defaults(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)
        score: float = 1

    async def scenario():
        _, _, _, _, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply(content)).encode()
        result = await gateway.execute(gateway.prepare("judge", {}, Defaults))
        assert result.output is None
        assert result.error_code == "evaluator_invalid_output"
        assert result.observation.payload.content == content

    asyncio.run(scenario())


def test_conditional_schema_cannot_retrieve_a_remote_reference():
    class Conditional(BaseModel):
        model_config = ConfigDict(
            extra="forbid",
            json_schema_extra={"if": {"$ref": "https://example.invalid/remote-schema"}},
        )
        value: str

    with pytest.raises(AppError) as caught:
        strict_schema(Conditional)
    assert caught.value.code == "unsupported_schema"


def test_prepared_intent_rejects_changed_observation_request_payload(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        call = prepare_target(connection, work)
        await repo.begin_operation(call.request, instance_id=OWNER)
        observation = await connection.execute(call)
        changed = observation.model_copy(
            update={
                "request_payload": ChatInput(messages=(Message(role="user", content="changed"),))
            }
        )
        with pytest.raises(AppError) as caught:
            await repo.save_observation(changed, instance_id=OWNER)
        assert caught.value.code == "invalid_output"
        assert (await repo.read_run(str(snapshot.id))).observations == ()
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations == (observation,)

    asyncio.run(scenario())
