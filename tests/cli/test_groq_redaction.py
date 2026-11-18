import asyncio
import json
import sqlite3

import pytest

from asclepius.adapters.chat import GroqConnection
from asclepius.domain import (
    AppError,
)
from asclepius.exports import render_report
from asclepius.limits import BudgetManager
from asclepius.models import ModelGateway
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


def test_secrets_redacted_in_request_response_not_canary(groq, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        text = "target-secret-123 evaluator-secret-456 synthetic-canary"
        groq[0].body = json.dumps(reply(text)).encode()
        call = prepare_target(connection, work, text)
        observation = await connection.execute(call)
        for serialized in (call.model_dump_json(), observation.model_dump_json()):
            assert "target-secret-123" not in serialized
            assert "evaluator-secret-456" not in serialized
            assert "synthetic-canary" in serialized
        assert observation.payload.content == "[REDACTED] [REDACTED] synthetic-canary"
        assert observation.payload.content_redacted is True
        assert observation.payload.raw_content_bytes == len(text.encode())

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
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        groq[0].body = json.dumps(reply("\ud800")).encode()
        observation = await execute_target(connection, work)
        assert observation.error_code == "provider_response"
        assert observation.payload is None
        assert reservations(repo)[0][1] == "settled"

    asyncio.run(scenario())


def test_escaped_credential_in_json_reply_and_target_request_is_redacted(
    groq, tmp_path, monkeypatch
):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch)
        key = 'secret-with-"quote-and-\\slash'
        monkeypatch.setenv("TARGET_KEY", key)
        connection = GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        encoded = json.dumps({"evidence": key, "canary": "synthetic-canary"})
        groq[0].body = json.dumps(reply(encoded)).encode()
        call = prepare_target(connection, work, encoded)
        assert json.loads(call.request.payload.messages[-1].content) == {
            "evidence": "[REDACTED]",
            "canary": "synthetic-canary",
        }
        observation = await connection.execute(call)
        assert json.loads(observation.payload.content) == {
            "evidence": "[REDACTED]",
            "canary": "synthetic-canary",
        }
        assert observation.payload.content_redacted
        assert observation.payload.raw_content_bytes == len(encoded.encode())

    asyncio.run(scenario())


def test_nested_json_string_cannot_retain_an_escaped_credential(groq, tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch)
        key = 'secret-with-"quote-and-\\slash'
        monkeypatch.setenv("TARGET_KEY", key)
        connection = GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        text = json.dumps({"evidence": json.dumps({"secret": key, "canary": "synthetic-canary"})})
        groq[0].body = json.dumps(reply(text)).encode()
        observation = await execute_target(connection, work, text)
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
        _, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        content = '["x"]'
        for _ in range(70):
            content = "[" + content + "]"
        with pytest.raises(AppError) as caught:
            prepare_target(connection, work, content)
        assert caught.value.code == "redaction_limit"
        groq[0].body = json.dumps(reply(content)).encode()
        observation = await execute_target(connection, work)
        assert observation.error_code == "redaction_limit"
        assert observation.payload is None

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
        repo, snapshot, work, connection, _ = await setup(groq, tmp_path, monkeypatch)
        monkeypatch.setenv("RETRY_SECRET", secret)
        document = snapshot.model_dump(mode="json")
        if secret_actor == "target":
            document["profile"]["target"]["secret_ref"] = "env:RETRY_SECRET"
        else:
            document["evaluator"]["roles"][secret_actor]["secret_ref"] = "env:RETRY_SECRET"
        pinned = type(snapshot).model_validate(document)
        connection = GroqConnection(pinned, connection.budgets, transport=groq[1])
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


@pytest.mark.parametrize("encoded", [False, True])
def test_https_reported_models_redact_both_credentials_before_storage_and_exports(
    groq, tmp_path, monkeypatch, encoded
):
    async def scenario():
        repo, snapshot, work, _, _ = await setup(groq, tmp_path, monkeypatch, variant=True)
        secrets = ('target-"credential-\\value', 'evaluator-"credential-\\value')
        monkeypatch.setenv("TARGET_KEY", secrets[0])
        monkeypatch.setenv("EVALUATOR_KEY", secrets[1])
        connection = GroqConnection(snapshot, BudgetManager(repo, OWNER), transport=groq[1])
        gateway = ModelGateway(connection, work_item_id=work)
        expected_models = {}
        for actor in ("target", "judge"):
            model = {"actor": actor + "-reported", "credentials": list(secrets)}
            reported = json.dumps(model) if encoded else " ".join((actor + "-reported", *secrets))
            content = "hello" if actor == "target" else '{"verdict":"pass","score":2}'
            groq[0].body = json.dumps({**reply(content), "model": reported}).encode()
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
        repo, snapshot, work, connection, gateway = await setup(groq, tmp_path, monkeypatch)
        model = json.dumps({"name": "\ud800", "credential": "target-secret-123"})
        groq[0].body = json.dumps(
            {**reply('{"verdict":"pass","score":2}'), "model": model}
        ).encode()
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
            observation = result.observation
        assert observation.status == "transport_error"
        assert observation.error_code == "provider_response"
        assert observation.payload is None
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations == (observation,)
        assert len(groq[0].calls) == 1

    asyncio.run(scenario())
