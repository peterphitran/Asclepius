import asyncio
import json
import sqlite3

import pytest

from asclepius.adapters.chat import GroqConnection
from asclepius.domain import (
    AppError,
    EvaluatorConfig,
    Observation,
)
from asclepius.models import ModelGateway
from tests.cli.groq_support import (
    Answer,
    execute_target,
    prepare_target,
    reply,
    reservations,
    setup,
)
from tests.cli.storage_fixtures import OWNER


def test_target_real_request_metadata_and_persistable_preparation(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        call = prepare_target(connection, work)
        assert json.loads(call.body_json)["messages"] == [
            {"role": "system", "content": "Profile policy"},
            {"role": "user", "content": "synthetic-canary"},
        ]
        intent = await repo.begin_operation(call.request, instance_id=OWNER)
        assert intent.created
        observation = await connection.execute(call)
        await repo.save_observation(observation, instance_id=OWNER)
        saved = (await repo.read_run(str(snapshot.id))).observations[0]
        assert saved == observation
        assert observation.payload.content == "hello"
        assert observation.payload.response_id == "response-1"
        assert observation.payload.finish_reason == "stop"
        assert observation.payload.usage.input_tokens == 13
        assert observation.payload.usage.output_tokens == 7
        assert observation.payload.raw_content_bytes == 5
        path, headers, body = groq[0].calls[0]
        assert path == "/target/chat/completions"
        assert headers["Authorization"] == "Bearer target-secret-123"
        assert body["model"] == "target-model"
        assert body["stream"] is False
        assert body["max_completion_tokens"] == 512
        assert not {"tools", "functions", "response_format"} & body.keys()
        assert body["messages"] == json.loads(call.body_json)["messages"]
        assert reservations(repo) == [("target", "settled", 512)]

    asyncio.run(scenario())


def test_evaluator_is_independent_and_strict_with_immutable_evidence(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, _, _, _, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply('{"verdict":"pass","score":2}')).encode()
        call = gateway.prepare("judge", {"evidence": "synthetic-canary"}, Answer)
        result = await gateway.execute(call)
        assert result.output == Answer(verdict="pass", score=2)
        assert result.error_code is None
        assert result.call == call.call
        assert result.observation.operation_id == call.call.request.id
        path, headers, body = groq[0].calls[0]
        assert path == "/evaluator/chat/completions"
        assert headers["Authorization"] == "Bearer evaluator-secret-456"
        assert body["model"] == "judge-model"
        assert body["messages"][0] == {"role": "system", "content": "judge policy"}
        schema = body["response_format"]["json_schema"]
        assert body["response_format"]["type"] == "json_schema"
        assert schema["strict"] is True
        assert schema["schema"]["required"] == ["verdict", "score"]
        assert schema["schema"]["additionalProperties"] is False
        assert json.loads(call.call.body_json) == body
        assert reservations(repo) == [("evaluator", "settled", 2048)]

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503, 307])
def test_provider_errors_cost_one_call_without_fallback(groq, tmp_path, monkeypatch, status):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        groq[0].status = status
        groq[0].body = b"target-secret-123"
        observation = await execute_target(connection, work)
        assert observation.status == "transport_error"
        assert observation.error_code == f"provider_http_{status}"
        assert observation.payload is None
        assert len(groq[0].calls) == 1
        assert reservations(repo) == [("target", "settled", 512)]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body,code",
    [
        ({}, "provider_response"),
        ({"choices": []}, "provider_response"),
        (reply(None), "provider_response"),
        (reply(""), "provider_response"),
        (reply("", refusal="blocked"), "provider_refusal"),
        (reply("text", tool_calls=[{"id": "call"}]), "provider_tools"),
        (reply("filtered", finish="content_filter"), "provider_refusal"),
    ],
)
def test_bad_or_unsupported_replies_are_not_success(groq, tmp_path, monkeypatch, body, code):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(body).encode()
        observation = await execute_target(connection, work)
        assert observation.error_code == code
        assert observation.status == "transport_error"
        assert observation.payload is None
        assert len(groq[0].calls) == 1
        assert reservations(repo)[0][1] == "settled"

    asyncio.run(scenario())


def test_absent_usage_is_unknown_not_zero(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        data = reply()
        del data["usage"]
        groq[0].body = json.dumps(data).encode()
        observation = await execute_target(connection, work)
        assert observation.payload.usage.input_tokens is None
        assert observation.payload.usage.output_tokens is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "content,finish,code",
    [
        ('{"verdict":"pass","score":2}', "length", "evaluator_truncated"),
        ("not json", "stop", "evaluator_invalid_output"),
        ('{"verdict":"pass","score":"2"}', "stop", "evaluator_invalid_output"),
        ('{"verdict":"pass","score":2,"extra":1}', "stop", "evaluator_invalid_output"),
    ],
)
def test_invalid_evaluator_output_keeps_observation(
    groq, tmp_path, monkeypatch, content, finish, code
):
    async def scenario():
        _, _, _, _, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply(content, finish)).encode()
        call = gateway.prepare("judge", {}, Answer)
        result = await gateway.execute(call)
        assert result.output is None
        assert result.error_code == code
        assert result.observation.payload.content == content
        assert result.observation.truncated == (finish == "length")
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("actor", ["target", "judge"])
@pytest.mark.parametrize("content", ["", None])
def test_https_empty_length_reply_preserves_truncated_evidence(
    groq, tmp_path, monkeypatch, actor, content
):
    async def scenario():
        repo, snapshot, work, connection, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply(content, "length")).encode()
        if actor == "target":
            call = prepare_target(connection, work)
        else:
            evaluation = gateway.prepare(actor, {}, Answer)
            call = evaluation.call
        await repo.begin_operation(call.request, instance_id=OWNER)
        if actor == "target":
            observation = await connection.execute(call)
        else:
            result = await gateway.execute(evaluation)
            assert result.output is None
            assert result.error_code == "evaluator_truncated"
            observation = result.observation
        assert observation.status == "success"
        assert observation.error_code is None
        assert observation.truncated is True
        assert observation.payload.content == ""
        assert observation.payload.response_id == "response-1"
        assert observation.payload.finish_reason == "length"
        assert observation.payload.usage.input_tokens == 13
        assert observation.payload.usage.output_tokens == 7
        assert observation.payload.raw_content_bytes == 0
        assert observation.payload.content_redacted is False
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations == (observation,)
        assert len(groq[0].calls) == 1
        kind, tokens = ("target", 512) if actor == "target" else ("evaluator", 2048)
        assert reservations(repo) == [(kind, "settled", tokens)]

    asyncio.run(scenario())


def test_older_operation_and_observation_json_replays_without_rewrite(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        call = prepare_target(connection, work)
        raw = call.request.model_copy(update={"provider_body_json": None})
        await repo.begin_operation(raw, instance_id=OWNER)
        observation = await connection.execute(call)
        await repo.save_observation(observation, instance_id=OWNER)
        old_request = raw.model_dump(mode="json")
        old_request.pop("provider_body_json")
        old_observation = observation.model_dump(mode="json")
        old_observation.pop("request_payload")
        old_observation.pop("retry_after")
        old_observation["payload"].pop("raw_content_bytes")
        old_observation["payload"].pop("content_redacted")
        old_observation["payload"].pop("provider_model", None)
        request_json = json.dumps(old_request, sort_keys=True, separators=(",", ":"))
        observation_json = json.dumps(old_observation, sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute(
                "UPDATE operations SET request_json=? WHERE id=?", (request_json, str(raw.id))
            )
            connection.execute(
                "UPDATE observations SET document_json=? WHERE id=?",
                (observation_json, str(observation.id)),
            )
        intent = await repo.begin_operation(raw, instance_id=OWNER)
        assert intent.created is False
        restored = Observation.model_validate_json(observation_json)
        assert restored.retry_after is None
        assert restored.payload.provider_model is None
        assert (await repo.read_run(str(snapshot.id))).observations[
            0
        ].payload.provider_model is None
        await repo.save_observation(restored, instance_id=OWNER)
        with sqlite3.connect(repo.database_path) as connection:
            assert (
                connection.execute("SELECT request_json FROM operations").fetchone()[0]
                == request_json
            )
            assert (
                connection.execute("SELECT document_json FROM observations").fetchone()[0]
                == observation_json
            )
        with pytest.raises(AppError) as caught:
            await repo.begin_operation(raw.model_copy(update={"actor": "judge"}), instance_id=OWNER)
        assert caught.value.code == "conflict"
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("actor", ["target", "judge"])
@pytest.mark.parametrize("header", ["120", "Wed, 21 Oct 2015 07:28:00 GMT"])
def test_https_retry_after_survives_error_evidence_without_retry(
    groq, tmp_path, monkeypatch, actor, header
):
    async def scenario():
        repo, snapshot, work, connection, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].status = 503
        groq[0].retry_after = [header]
        if actor == "target":
            call = prepare_target(connection, work)
        else:
            evaluation = gateway.prepare(actor, {}, Answer)
            call = evaluation.call
        await repo.begin_operation(call.request, instance_id=OWNER)
        if actor == "target":
            observation = await connection.execute(call)
        else:
            result = await gateway.execute(evaluation)
            assert result.output is None
            assert result.error_code == "provider_http_503"
            observation = result.observation
        assert observation.retry_after == header
        assert observation.error_code == "provider_http_503"
        assert observation.status == "transport_error"
        assert observation.payload is None
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations == (observation,)
        assert len(groq[0].calls) == 1
        kind, tokens = ("target", 512) if actor == "target" else ("evaluator", 2048)
        assert reservations(repo) == [(kind, "settled", tokens)]

    asyncio.run(scenario())


@pytest.mark.parametrize("actor", ["target", "judge"])
@pytest.mark.parametrize(
    "metadata", [{}, {"model": None}, {"model": ""}, {"model": "  modèle-版本 🌡  "}]
)
def test_https_reported_model_is_optional_provider_evidence(
    groq, tmp_path, monkeypatch, actor, metadata
):
    async def scenario():
        repo, snapshot, work, connection, gateway = await setup(groq, tmp_path, monkeypatch)
        content = "hello" if actor == "target" else '{"verdict":"pass","score":2}'
        groq[0].body = json.dumps({**reply(content), **metadata}).encode()
        if actor == "target":
            call = prepare_target(connection, work)
        else:
            evaluation = gateway.prepare(actor, {}, Answer)
            call = evaluation.call
        await repo.begin_operation(call.request, instance_id=OWNER)
        if actor == "target":
            observation = await connection.execute(call)
        else:
            result = await gateway.execute(evaluation)
            assert result.output == Answer(verdict="pass", score=2)
            observation = result.observation
        assert observation.status == "success"
        expected = metadata.get("model") or None
        assert observation.payload.model_dump().get("provider_model") == expected
        assert groq[0].calls[0][2]["model"] == actor + "-model"
        assert observation.payload.content_redacted is False
        assert observation.payload.raw_content_bytes == len(content.encode("utf-8"))
        await repo.save_observation(observation, instance_id=OWNER)
        restored = (await repo.read_run(str(snapshot.id))).observations[0]
        assert restored == observation
        await repo.save_observation(restored, instance_id=OWNER)
        assert not (await repo.begin_operation(call.request, instance_id=OWNER)).created
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("actor", ["target", "judge"])
@pytest.mark.parametrize("model", [17, False, [], {}, "\ud800"])
def test_https_invalid_reported_model_fails_safely(groq, tmp_path, monkeypatch, actor, model):
    async def scenario():
        _, snapshot, work, connection, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(
            {**reply('{"verdict":"pass","score":2}'), "model": model}
        ).encode()
        if actor == "target":
            observation = await execute_target(connection, work)
        else:
            result = await gateway.execute(gateway.prepare(actor, {}, Answer))
            assert result.output is None
            observation = result.observation
        assert observation.status == "transport_error"
        assert observation.error_code == "provider_response"
        assert observation.payload is None
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def _with_reasoning(snapshot, server, effort):
    return snapshot.model_copy(
        update={
            "evaluator": EvaluatorConfig.model_validate(
                {
                    "roles": {
                        role: {
                            "model": role + "-model",
                            "secret_ref": "env:EVALUATOR_KEY",
                            "base_url": server.origin + "/evaluator",
                            "reasoning_effort": effort,
                        }
                        for role in ("selector", "generator", "judge", "reporter")
                    }
                }
            )
        }
    )


def test_evaluator_reasoning_effort_is_sent_only_when_configured(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, connection, gateway = await setup(groq, tmp_path, monkeypatch)
        default = json.loads(gateway.prepare("judge", {}, Answer).call.body_json)
        assert "reasoning_effort" not in default
        configured = _with_reasoning(snapshot, groq[0], "low")
        connection = GroqConnection(configured, connection.budgets, transport=groq[1])
        for role in ("selector", "generator", "judge", "reporter"):
            prepared = ModelGateway(connection, work_item_id=work).prepare(role, {}, Answer)
            assert json.loads(prepared.call.body_json)["reasoning_effort"] == "low"
        target_body = json.loads(prepare_target(connection, work).body_json)
        assert "reasoning_effort" not in target_body

    asyncio.run(scenario())


def test_reasoning_effort_reaches_the_provider(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply('{"verdict":"pass","score":2}')).encode()
        configured = _with_reasoning(snapshot, groq[0], "low")
        connection = GroqConnection(configured, connection.budgets, transport=groq[1])
        await ModelGateway(connection, work_item_id=work).generate("judge", {}, Answer)
        assert groq[0].calls[-1][2]["reasoning_effort"] == "low"

    asyncio.run(scenario())


@pytest.mark.parametrize("effort", ["extreme", "", "LOW"])
def test_reasoning_effort_rejects_unknown_values(effort):
    from pydantic import ValidationError

    from asclepius.domain import RoleConfig

    with pytest.raises(ValidationError):
        RoleConfig.model_validate(
            {"model": "m", "secret_ref": "env:KEY", "reasoning_effort": effort}
        )
