import asyncio
import json
import sqlite3
import ssl
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from asclepius.adapters.chat import ChatAdapter, GroqConnection
from asclepius.domain import (
    AppError,
    ChatInput,
    EvaluatorConfig,
    Message,
    Observation,
    OperationRequest,
    ProfileConfig,
    PromptSnapshot,
    TargetConfig,
)
from asclepius.exports import render_report
from asclepius.limits import BudgetManager
from asclepius.models import ModelGateway, strict_schema
from asclepius.storage import Repository
from asclepius.transport import JsonTransport
from tests.cli.storage_fixtures import OWNER, make_snapshot, ready
from tests.cli.test_transport import provider as provider


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verdict: str
    score: int


@pytest.fixture
def groq(provider):
    fixtures = Path(__file__).parent / "fixtures"
    cert = fixtures / "localhost-cert.pem"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, fixtures / "localhost-key.pem")
    provider.socket = context.wrap_socket(provider.socket, server_side=True)
    provider.origin = f"https://127.0.0.1:{provider.server_port}"
    provider.body = json.dumps(reply()).encode()
    return provider, JsonTransport(verify=ssl.create_default_context(cafile=str(cert)))


def reply(content="hello", finish="stop", **message):
    return {
        "id": "response-1",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content, **message},
            }
        ],
        "usage": {"prompt_tokens": 13, "completion_tokens": 7},
    }


async def setup(groq, tmp_path, monkeypatch, *, legacy_case=False, **limits):
    server, transport = groq
    monkeypatch.setenv("TARGET_KEY", "target-secret-123")
    monkeypatch.setenv("EVALUATOR_KEY", "evaluator-secret-456")
    repo = Repository(tmp_path)
    await repo.initialize()
    profile = ProfileConfig(
        target=TargetConfig(
            name="test",
            model="target-model",
            secret_ref="env:TARGET_KEY",
            base_url=server.origin + "/target",
            system_prompt="Profile policy",
        ),
        limits={"requests_per_minute": 100, "request_timeout_seconds": 10, **limits},
    )
    profile_id = await repo.save_profile(profile)
    snapshot = make_snapshot(profile_id, profile).model_copy(
        update={
            "evaluator": EvaluatorConfig.model_validate(
                {
                    "roles": {
                        role: {
                            "model": role + "-model",
                            "secret_ref": "env:EVALUATOR_KEY",
                            "base_url": server.origin + "/evaluator",
                        }
                        for role in ("selector", "generator", "judge", "reporter")
                    }
                }
            ),
            "prompts": tuple(
                PromptSnapshot(role=role, version="1", content=role + " policy")
                for role in ("selector", "generator", "judge", "reporter")
            ),
        }
    )
    await ready(repo)
    await repo.enqueue(snapshot)
    await repo.claim_next(OWNER)
    work_id = uuid4()
    await repo.register_work_item(
        str(snapshot.id),
        str(work_id),
        "test.check",
        variant_id=str(uuid4()) if legacy_case else None,
        instance_id=OWNER,
    )
    budgets = BudgetManager(repo, OWNER, limits=profile.limits)
    connection = GroqConnection(snapshot, budgets, transport=transport)
    adapter = ChatAdapter(connection)
    gateway = ModelGateway(connection, work_item_id=work_id)
    return repo, snapshot, work_id, adapter, gateway


def request(snapshot, work_id, text="synthetic-canary"):
    return OperationRequest(
        run_id=snapshot.id,
        work_item_id=work_id,
        payload=ChatInput(messages=(Message(role="user", content=text),)),
    )


def reservations(repo):
    with sqlite3.connect(repo.database_path) as connection:
        return connection.execute(
            "SELECT kind, state, max_output FROM budget_reservations ORDER BY rowid"
        ).fetchall()


def test_target_real_request_metadata_and_persistable_preparation(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        call = adapter.prepare(request(snapshot, work))
        assert json.loads(call.body_json)["messages"] == [
            {"role": "system", "content": "Profile policy"},
            {"role": "user", "content": "synthetic-canary"},
        ]
        intent = await repo.begin_operation(call.request, instance_id=OWNER)
        assert intent.created
        observation = await adapter.execute_prepared(call)
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
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        groq[0].status = status
        groq[0].body = b"target-secret-123"
        observation = await adapter.execute(request(snapshot, work))
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
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(body).encode()
        observation = await adapter.execute(request(snapshot, work))
        assert observation.error_code == code
        assert observation.status == "transport_error"
        assert observation.payload is None
        assert len(groq[0].calls) == 1
        assert reservations(repo)[0][1] == "settled"

    asyncio.run(scenario())


def test_absent_usage_is_unknown_not_zero(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        data = reply()
        del data["usage"]
        groq[0].body = json.dumps(data).encode()
        observation = await adapter.execute(request(snapshot, work))
        assert observation.payload.usage.input_tokens is None
        assert observation.payload.usage.output_tokens is None

    asyncio.run(scenario())


def test_secrets_redacted_in_request_response_not_canary(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        text = "target-secret-123 evaluator-secret-456 synthetic-canary"
        groq[0].body = json.dumps(reply(text)).encode()
        call = adapter.prepare(request(snapshot, work, text))
        observation = await adapter.execute_prepared(call)
        for serialized in (call.model_dump_json(), observation.model_dump_json()):
            assert "target-secret-123" not in serialized
            assert "evaluator-secret-456" not in serialized
            assert "synthetic-canary" in serialized
        assert observation.payload.content == "[REDACTED] [REDACTED] synthetic-canary"
        assert observation.payload.content_redacted is True
        assert observation.payload.raw_content_bytes == len(text.encode())

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


def test_limits_reject_new_dispatch_and_retain_target_truncation(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch, target_calls=1)
        groq[0].body = json.dumps(reply("partial", "length")).encode()
        observation = await adapter.execute(request(snapshot, work))
        assert observation.status == "success"
        assert observation.truncated is True
        assert observation.payload.content == "partial"
        with pytest.raises(AppError) as caught:
            await adapter.execute(request(snapshot, work))
        assert caught.value.code == "budget_exhausted"
        assert len(groq[0].calls) == 1
        assert len(reservations(repo)) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("actor", ["target", "judge"])
@pytest.mark.parametrize("content", ["", None])
def test_https_empty_length_reply_preserves_truncated_evidence(
    groq, tmp_path, monkeypatch, actor, content
):
    async def scenario():
        repo, snapshot, work, adapter, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply(content, "length")).encode()
        if actor == "target":
            call = adapter.prepare(request(snapshot, work))
        else:
            evaluation = gateway.prepare(actor, {}, Answer)
            call = evaluation.call
        await repo.begin_operation(call.request, instance_id=OWNER)
        if actor == "target":
            observation = await adapter.execute_prepared(call)
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


def test_missing_selected_secret_never_dispatches(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch)
        monkeypatch.delenv("TARGET_KEY")
        adapter = ChatAdapter(
            GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        )
        with pytest.raises(AppError) as caught:
            await adapter.execute(request(snapshot, work))
        assert caught.value.code == "secret_missing"
        assert groq[0].calls == []
        assert reservations(repo) == []

    asyncio.run(scenario())


def test_wrong_run_or_actor_and_oversized_input_never_dispatch(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        for invalid in (
            request(snapshot, work).model_copy(update={"run_id": uuid4()}),
            request(snapshot, work).model_copy(update={"actor": "judge"}),
            request(snapshot, work, "x" * 20000),
        ):
            with pytest.raises(AppError):
                await adapter.execute(invalid)
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


def test_escaped_credential_in_evaluator_payload_is_redacted(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch)
        key = 'secret-with-"quote-and-\\slash'
        monkeypatch.setenv("TARGET_KEY", key)
        gateway = ModelGateway(
            GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1]),
            work_item_id=work,
        )
        call = gateway.prepare("judge", {"evidence": key + " synthetic-canary"}, Answer)
        messages = json.loads(call.call.body_json)["messages"]
        assert json.loads(messages[1]["content"])["evidence"] == "[REDACTED] synthetic-canary"
        assert groq[0].calls == []

    asyncio.run(scenario())


def test_invalid_unicode_reply_is_a_sanitized_observation(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply("\ud800")).encode()
        observation = await adapter.execute(request(snapshot, work))
        assert observation.error_code == "provider_response"
        assert observation.payload is None
        assert reservations(repo)[0][1] == "settled"

    asyncio.run(scenario())


def test_invalid_unicode_input_never_dispatches(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        with pytest.raises(AppError) as caught:
            await adapter.execute(request(snapshot, work, "\ud800"))
        assert caught.value.code == "invalid_input"
        assert groq[0].calls == []
        assert reservations(repo) == []

    asyncio.run(scenario())


def test_captured_credentials_remain_bound_to_run(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        monkeypatch.setenv("TARGET_KEY", "changed-after-capture")
        groq[0].body = json.dumps(reply("target-secret-123 synthetic-canary")).encode()
        observation = await adapter.execute(request(snapshot, work))
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


def test_response_cap_preserves_uncertainty_and_consumes_budget(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(
            groq, tmp_path, monkeypatch, response_bytes=16
        )
        observation = await adapter.execute(request(snapshot, work))
        assert observation.error_code == "response_too_large"
        assert observation.truncated
        assert observation.payload is None
        assert len(groq[0].calls) == 1
        assert reservations(repo)[0][1] == "settled"

    asyncio.run(scenario())


def test_target_and_evaluator_share_the_same_outbound_gate(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, gateway = await setup(
            groq, tmp_path, monkeypatch, outbound_concurrency=1
        )
        groq[0].delay = 0.2
        groq[0].body = json.dumps(reply('{"verdict":"pass","score":2}')).encode()
        target, evaluator = await asyncio.gather(
            adapter.execute(request(snapshot, work)), gateway.generate("judge", {}, Answer)
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


def test_older_operation_and_observation_json_replays_without_rewrite(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        raw = request(snapshot, work)
        await repo.begin_operation(raw, instance_id=OWNER)
        observation = await adapter.execute(raw)
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


def test_escaped_credential_in_json_reply_and_target_request_is_redacted(
    groq, tmp_path, monkeypatch
):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch)
        key = 'secret-with-"quote-and-\\slash'
        monkeypatch.setenv("TARGET_KEY", key)
        connection = GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        adapter = ChatAdapter(connection)
        encoded = json.dumps({"evidence": key, "canary": "synthetic-canary"})
        groq[0].body = json.dumps(reply(encoded)).encode()
        call = adapter.prepare(request(snapshot, work, encoded))
        assert json.loads(call.request.payload.messages[-1].content) == {
            "evidence": "[REDACTED]",
            "canary": "synthetic-canary",
        }
        observation = await adapter.execute_prepared(call)
        assert json.loads(observation.payload.content) == {
            "evidence": "[REDACTED]",
            "canary": "synthetic-canary",
        }
        assert observation.payload.content_redacted
        assert observation.payload.raw_content_bytes == len(encoded.encode())

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


def test_nested_json_string_cannot_retain_an_escaped_credential(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch)
        key = 'secret-with-"quote-and-\\slash'
        monkeypatch.setenv("TARGET_KEY", key)
        connection = GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        text = json.dumps({"evidence": json.dumps({"secret": key, "canary": "synthetic-canary"})})
        groq[0].body = json.dumps(reply(text)).encode()
        observation = await ChatAdapter(connection).execute(request(snapshot, work, text))
        for content in (
            observation.payload.content,
            observation.request_payload.messages[-1].content,
        ):
            assert json.loads(json.loads(content)["evidence"]) == {
                "secret": "[REDACTED]",
                "canary": "synthetic-canary",
            }
        assert observation.payload.content_redacted

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


def test_json_property_names_cannot_hide_encoded_credentials(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, _, _, _ = await setup(groq, tmp_path, monkeypatch)
        key = 'secret-with-"quote-and-\\slash'
        monkeypatch.setenv("TARGET_KEY", key)
        connection = GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        content = json.dumps({json.dumps({"secret": key}): "synthetic-canary"})
        cleaned = connection.redact_content(content)
        item, value = next(iter(json.loads(cleaned).items()))
        assert json.loads(item) == {"secret": "[REDACTED]"}
        assert value == "synthetic-canary"

    asyncio.run(scenario())


def test_redaction_depth_fails_closed(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        content = '["x"]'
        for _ in range(70):
            content = "[" + content + "]"
        with pytest.raises(AppError) as caught:
            adapter.prepare(request(snapshot, work, content))
        assert caught.value.code == "redaction_limit"
        groq[0].body = json.dumps(reply(content)).encode()
        observation = await adapter.execute(request(snapshot, work))
        assert observation.error_code == "redaction_limit"
        assert observation.payload is None

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_release", [False, True])
def test_cancellation_waiting_for_slot_releases_allowance(
    groq, tmp_path, monkeypatch, cancel_release
):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(
            groq, tmp_path, monkeypatch, outbound_concurrency=1, target_calls=1
        )
        budgets = adapter.connection.budgets
        releasing = threading.Event()
        finish_release = threading.Event()
        transaction = repo._transaction
        waiting = asyncio.Event()
        slot = budgets.slot

        @asynccontextmanager
        async def waiting_slot(*args, **kwargs):
            waiting.set()
            async with slot(*args, **kwargs) as lease:
                yield lease

        def blocked_release(action, write):
            if write and waiting.is_set() and reservations(repo) == [("target", "reserved", 512)]:
                releasing.set()
                assert finish_release.wait(5)
            return transaction(action, write)

        if cancel_release:
            monkeypatch.setattr(repo, "_transaction", blocked_release)
        try:
            async with slot(snapshot, "target"):
                monkeypatch.setattr(budgets, "slot", waiting_slot)
                task = asyncio.create_task(adapter.execute(request(snapshot, work)))
                await asyncio.wait_for(waiting.wait(), 5)
                assert reservations(repo) == [("target", "reserved", 512)]
                task.cancel()
                if cancel_release:
                    assert await asyncio.to_thread(releasing.wait, 5)
                    task.cancel()
                    finish_release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert groq[0].calls == []
                assert reservations(repo) == [("target", "released", 512)]
            monkeypatch.setattr(repo, "_transaction", transaction)
            observation = await adapter.execute(request(snapshot, work))
            assert observation.status == "success"
            assert len(groq[0].calls) == 1
            assert reservations(repo) == [
                ("target", "released", 512),
                ("target", "settled", 512),
            ]
        finally:
            finish_release.set()
            await repo.drain_operations()

    asyncio.run(scenario())


@pytest.mark.parametrize("worker_state", ["reserved", "dispatched"])
def test_cancellation_with_unknown_worker_outcome_preserves_allowance(
    groq, tmp_path, monkeypatch, worker_state
):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch, target_calls=1)
        committed = threading.Event()
        finish_worker = threading.Event()
        transaction = repo._transaction

        def blocked_worker(action, write):
            result = transaction(action, write)
            if write and reservations(repo) == [("target", worker_state, 512)]:
                committed.set()
                assert finish_worker.wait(5)
            return result

        monkeypatch.setattr(repo, "_transaction", blocked_worker)
        task = asyncio.create_task(adapter.execute(request(snapshot, work)))
        try:
            assert await asyncio.to_thread(committed.wait, 5)
            task.cancel()
        finally:
            finish_worker.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reservations(repo) == [("target", worker_state, 512)]
        assert groq[0].calls == []
        with pytest.raises(AppError) as caught:
            await adapter.execute(request(snapshot, work))
        assert caught.value.code == "budget_exhausted"
        assert groq[0].calls == []

    asyncio.run(scenario())


def test_cancellation_after_https_dispatch_keeps_allowance_without_retry(
    groq, tmp_path, monkeypatch
):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch, target_calls=1)
        groq[0].delay = 0.2
        task = asyncio.create_task(adapter.execute(request(snapshot, work)))
        assert await asyncio.to_thread(groq[0].received.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reservations(repo) == [("target", "settled", 512)]
        with pytest.raises(AppError) as caught:
            await adapter.execute(request(snapshot, work))
        assert caught.value.code == "budget_exhausted"
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("actor", ["target", "judge"])
@pytest.mark.parametrize("header", ["120", "Wed, 21 Oct 2015 07:28:00 GMT"])
def test_https_retry_after_survives_error_evidence_without_retry(
    groq, tmp_path, monkeypatch, actor, header
):
    async def scenario():
        repo, snapshot, work, adapter, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].status = 503
        groq[0].retry_after = [header]
        if actor == "target":
            call = adapter.prepare(request(snapshot, work))
        else:
            evaluation = gateway.prepare(actor, {}, Answer)
            call = evaluation.call
        await repo.begin_operation(call.request, instance_id=OWNER)
        if actor == "target":
            observation = await adapter.execute_prepared(call)
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


@pytest.mark.parametrize("secret_actor", ["target", "selector", "generator", "judge", "reporter"])
@pytest.mark.parametrize(
    "header,secret",
    [
        ("120", "120"),
        ("0120", "120"),
        ("Wed, 21 Oct 2015 07:28:00 GMT", "Wed, 21 Oct 2015 07:28:00 GMT"),
    ],
)
def test_https_retry_after_cannot_reflect_any_configured_credential(
    groq, tmp_path, monkeypatch, secret_actor, header, secret
):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        monkeypatch.setenv("RETRY_SECRET", secret)
        document = snapshot.model_dump(mode="json")
        if secret_actor == "target":
            document["profile"]["target"]["secret_ref"] = "env:RETRY_SECRET"
        else:
            document["evaluator"]["roles"][secret_actor]["secret_ref"] = "env:RETRY_SECRET"
        pinned = type(snapshot).model_validate(document)
        connection = GroqConnection(pinned, adapter.connection.budgets, transport=groq[1])
        operation = request(pinned, work).model_copy(
            update={"actor": "judge" if secret_actor == "target" else "target"}
        )
        call = connection.prepare(operation)
        await repo.begin_operation(call.request, instance_id=OWNER)
        groq[0].status = 429
        groq[0].retry_after = [header]
        observation = await connection.execute(call)
        assert observation.retry_after is None
        assert observation.error_code == "provider_http_429"
        await repo.save_observation(observation, instance_id=OWNER)
        saved = (await repo.read_run(str(snapshot.id))).observations[0]
        assert saved.retry_after is None
        assert secret not in saved.model_dump_json(include={"retry_after", "error_code"})
        assert len(groq[0].calls) == 1
        kind, tokens = ("evaluator", 2048) if secret_actor == "target" else ("target", 512)
        assert reservations(repo) == [(kind, "settled", tokens)]

    asyncio.run(scenario())


def test_dispatch_failure_retains_received_reply_when_settlement_fails(groq, tmp_path, monkeypatch):
    from asclepius.adapters.chat import DispatchFailure

    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        call = adapter.prepare(request(snapshot, work))
        await repo.begin_operation(call.request, instance_id=OWNER)

        async def fail_settlement(reservation):
            raise AppError("storage_error", "Injected settlement failure")

        monkeypatch.setattr(adapter.connection.budgets, "settle", fail_settlement)
        with pytest.raises(DispatchFailure) as caught:
            await adapter.execute_prepared(call)
        observation = caught.value.observation
        assert observation.status == "success"
        assert observation.payload.content == "hello"
        assert observation.payload.response_id == "response-1"
        assert observation.dispatch_status == "attempted"
        assert caught.value.code == "storage_error"
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations == (observation,)
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def test_local_budget_rejection_has_explicit_nondispatch_metadata(groq, tmp_path, monkeypatch):
    from asclepius.adapters.chat import DispatchFailure

    async def scenario():
        _, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch, target_calls=1)
        await adapter.execute(request(snapshot, work))
        with pytest.raises(DispatchFailure) as caught:
            await adapter.execute(request(snapshot, work))
        observation = caught.value.observation
        assert observation.dispatch_status == "not_dispatched"
        assert observation.status == "transport_error" and observation.payload is None
        assert observation.error_code == "budget_exhausted"
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def test_prepared_intent_rejects_changed_observation_request_payload(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        call = adapter.prepare(request(snapshot, work))
        await repo.begin_operation(call.request, instance_id=OWNER)
        observation = await adapter.execute_prepared(call)
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


def test_coordinator_storage_failure_keeps_received_evidence_and_running_owner(
    groq, tmp_path, monkeypatch
):
    from asclepius.checks import load_pack_plan
    from asclepius.coordinator import Coordinator
    from asclepius.domain import RunState

    async def scenario():
        repo, snapshot, _, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        plan = load_pack_plan("broad-chat-v1")
        snapshot = snapshot.model_copy(update={"checks": plan.checks, "prompts": plan.prompts})
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute(
                "UPDATE runs SET snapshot_json=? WHERE id=?",
                (snapshot.model_dump_json(), str(snapshot.id)),
            )

        async def fail_settlement(reservation):
            raise AppError("storage_error", "Injected settlement failure")

        monkeypatch.setattr(adapter.connection.budgets, "settle", fail_settlement)
        with pytest.raises(AppError) as caught:
            await Coordinator(repo, adapter.connection.budgets, transport=groq[1]).execute(snapshot)
        assert caught.value.code == "storage_error"
        view = await repo.read_run(str(snapshot.id))
        assert view.state == RunState.RUNNING
        assert len(view.observations) == 1
        assert view.observations[0].payload.content == "hello"
        assert view.attempts[0].state == "pending"
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("actor", ["target", "judge"])
@pytest.mark.parametrize(
    "metadata", [{}, {"model": None}, {"model": ""}, {"model": "  modèle-版本 🌡  "}]
)
def test_https_reported_model_is_optional_provider_evidence(
    groq, tmp_path, monkeypatch, actor, metadata
):
    async def scenario():
        repo, snapshot, work, adapter, gateway = await setup(groq, tmp_path, monkeypatch)
        content = "hello" if actor == "target" else '{"verdict":"pass","score":2}'
        groq[0].body = json.dumps({**reply(content), **metadata}).encode()
        if actor == "target":
            call = adapter.prepare(request(snapshot, work))
        else:
            evaluation = gateway.prepare(actor, {}, Answer)
            call = evaluation.call
        await repo.begin_operation(call.request, instance_id=OWNER)
        if actor == "target":
            observation = await adapter.execute_prepared(call)
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
        _, snapshot, work, adapter, gateway = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(
            {**reply('{"verdict":"pass","score":2}'), "model": model}
        ).encode()
        if actor == "target":
            observation = await adapter.execute(request(snapshot, work))
        else:
            result = await gateway.execute(gateway.prepare(actor, {}, Answer))
            assert result.output is None
            observation = result.observation
        assert observation.status == "transport_error"
        assert observation.error_code == "provider_response"
        assert observation.payload is None
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("encoded", [False, True])
def test_https_reported_models_redact_both_credentials_before_storage_and_exports(
    groq, tmp_path, monkeypatch, encoded
):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch, legacy_case=True)
        secrets = ('target-"credential-\\value', 'evaluator-"credential-\\value')
        monkeypatch.setenv("TARGET_KEY", secrets[0])
        monkeypatch.setenv("EVALUATOR_KEY", secrets[1])
        connection = GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        adapter = ChatAdapter(connection)
        gateway = ModelGateway(connection, work_item_id=work)
        expected_models = {}
        for actor in ("target", "judge"):
            model = {"actor": actor + "-reported", "credentials": list(secrets)}
            reported = json.dumps(model) if encoded else " ".join((actor + "-reported", *secrets))
            content = "hello" if actor == "target" else '{"verdict":"pass","score":2}'
            groq[0].body = json.dumps({**reply(content), "model": reported}).encode()
            if actor == "target":
                call = adapter.prepare(request(snapshot, work))
            else:
                evaluation = gateway.prepare(actor, {}, Answer)
                call = evaluation.call
            await repo.begin_operation(call.request, instance_id=OWNER)
            if actor == "target":
                observation = await adapter.execute_prepared(call)
            else:
                result = await gateway.execute(evaluation)
                assert result.output == Answer(verdict="pass", score=2)
                observation = result.observation
            expected = (
                json.dumps(
                    {"actor": actor + "-reported", "credentials": ["[REDACTED]"] * 2},
                    separators=(",", ":"),
                )
                if encoded
                else actor + "-reported [REDACTED] [REDACTED]"
            )
            expected_models[actor] = expected
            if observation.payload.model_dump().get("provider_model") != expected:
                raise AssertionError("Reported model was not safely retained")
            assert observation.payload.content_redacted is False
            assert observation.payload.raw_content_bytes == len(content.encode())
            await repo.save_observation(observation, instance_id=OWNER)
        view = await repo.read_run(str(snapshot.id))
        with sqlite3.connect(repo.database_path) as database:
            documents = database.execute("SELECT document_json FROM observations").fetchall()
        saved_models = {item.actor: item.payload.provider_model for item in view.observations}
        if saved_models != expected_models:
            raise AssertionError("Saved model metadata changed")
        artifacts = [render_report(view, format).content for format in ("json", "markdown", "html")]
        for text in [view.model_dump_json(), *(row[0] for row in documents), *artifacts]:
            for secret in secrets:
                for forbidden in (secret, json.dumps(secret)[1:-1]):
                    if forbidden in text:
                        raise AssertionError("Credential leaked into saved evidence or export")
            assert "provider_model" in text
        for text in [view.model_dump_json(), *artifacts]:
            for actor in ("target", "judge"):
                assert actor + "-reported" in text
        assert len(groq[0].calls) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("actor", ["target", "judge"])
def test_metadata_redaction_cannot_materialize_invalid_unicode(groq, tmp_path, monkeypatch, actor):
    async def scenario():
        repo, snapshot, work, adapter, gateway = await setup(groq, tmp_path, monkeypatch)
        model = json.dumps({"name": "\ud800", "credential": "target-secret-123"})
        groq[0].body = json.dumps(
            {**reply('{"verdict":"pass","score":2}'), "model": model}
        ).encode()
        if actor == "target":
            call = adapter.prepare(request(snapshot, work))
        else:
            evaluation = gateway.prepare(actor, {}, Answer)
            call = evaluation.call
        await repo.begin_operation(call.request, instance_id=OWNER)
        if actor == "target":
            observation = await adapter.execute_prepared(call)
        else:
            result = await gateway.execute(evaluation)
            observation = result.observation
        assert observation.status == "transport_error"
        assert observation.error_code == "provider_response"
        assert observation.payload is None
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations == (observation,)
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())


def spy_token_leases(budgets):
    charged = []
    original = budgets.slot

    @asynccontextmanager
    async def slot(snapshot, kind, **kwargs):
        async with original(snapshot, kind, **kwargs) as lease:
            entry = {"estimate": kwargs.get("tokens"), "measured": []}
            charged.append(entry)
            record = lease.record

            def spy(tokens):
                entry["measured"].append(tokens)
                record(tokens)

            lease.record = spy
            yield lease

    budgets.slot = slot
    return charged


@pytest.mark.parametrize("actor", ["target", "judge"])
def test_token_estimate_is_input_bytes_over_four_plus_output_cap(
    groq, tmp_path, monkeypatch, actor
):
    async def scenario():
        _, snapshot, work, adapter, gateway = await setup(groq, tmp_path, monkeypatch)
        charged = spy_token_leases(adapter.connection.budgets)
        if actor == "target":
            call = adapter.prepare(request(snapshot, work))
            await adapter.execute(request(snapshot, work))
            cap = snapshot.profile.target.max_completion_tokens
        else:
            groq[0].body = json.dumps(reply('{"verdict":"pass","score":2}')).encode()
            call = gateway.prepare("judge", {}, Answer).call
            await gateway.generate("judge", {}, Answer)
            cap = snapshot.evaluator.roles.judge.max_completion_tokens
        size = len(call.body_json.encode("utf-8"))
        assert charged[0]["estimate"] == -(-size // 4) + cap
        assert charged[0]["measured"] == [20]

    asyncio.run(scenario())


@pytest.mark.parametrize("usage", [None, {"prompt_tokens": 13}, {"completion_tokens": 7}])
def test_incomplete_usage_keeps_the_token_estimate(groq, tmp_path, monkeypatch, usage):
    async def scenario():
        _, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        charged = spy_token_leases(adapter.connection.budgets)
        data = reply()
        if usage is None:
            del data["usage"]
        else:
            data["usage"] = usage
        groq[0].body = json.dumps(data).encode()
        await adapter.execute(request(snapshot, work))
        assert charged[0]["measured"] in ([], [None])

    asyncio.run(scenario())


def test_provider_error_keeps_the_token_estimate(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        charged = spy_token_leases(adapter.connection.budgets)
        groq[0].status = 429
        observation = await adapter.execute(request(snapshot, work))
        assert observation.error_code == "provider_http_429"
        assert charged[0]["estimate"] > 0
        assert charged[0]["measured"] in ([], [None])

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
        _, snapshot, work, adapter, gateway = await setup(groq, tmp_path, monkeypatch)
        default = json.loads(gateway.prepare("judge", {}, Answer).call.body_json)
        assert "reasoning_effort" not in default
        configured = _with_reasoning(snapshot, groq[0], "low")
        connection = GroqConnection(configured, adapter.connection.budgets, transport=groq[1])
        for role in ("selector", "generator", "judge", "reporter"):
            prepared = ModelGateway(connection, work_item_id=work).prepare(role, {}, Answer)
            assert json.loads(prepared.call.body_json)["reasoning_effort"] == "low"
        target_body = json.loads(ChatAdapter(connection).prepare(request(snapshot, work)).body_json)
        assert "reasoning_effort" not in target_body

    asyncio.run(scenario())


def test_reasoning_effort_reaches_the_provider(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, adapter, _ = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply('{"verdict":"pass","score":2}')).encode()
        configured = _with_reasoning(snapshot, groq[0], "low")
        connection = GroqConnection(configured, adapter.connection.budgets, transport=groq[1])
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
