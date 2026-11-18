import asyncio
import json
import socket
from uuid import uuid4

import pytest
from pydantic import ValidationError

from asclepius.adapters.chat import GroqConnection
from asclepius.domain import (
    AppError,
    EvaluatorConfig,
    ProfileConfig,
    PromptSnapshot,
    TargetConfig,
)
from asclepius.limits import BudgetManager
from asclepius.storage import Repository
from asclepius.transport import JsonTransport
from tests.cli.storage_fixtures import OWNER, make_snapshot, ready
from tests.cli.test_groq_contract import execute_target, prepare_target
from tests.cli.test_transport import provider as provider


def ollama_reply(content="local hello", done_reason="stop", **extra):
    return {
        "model": "llama3.2:1b",
        "created_at": "2026-11-16T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": 21,
        "eval_count": 9,
        **extra,
    }


async def setup(server, tmp_path, monkeypatch, *, base_url=None, **limits):
    monkeypatch.setenv("EVALUATOR_KEY", "evaluator-secret-456")
    monkeypatch.delenv("TARGET_KEY", raising=False)
    repo = Repository(tmp_path)
    await repo.initialize()
    profile = ProfileConfig(
        target=TargetConfig(
            name="local",
            adapter="ollama-chat",
            model="llama3.2:1b",
            base_url=base_url or server.origin,
            system_prompt="Profile policy",
            temperature=0.2,
            max_completion_tokens=64,
        ),
        limits={"requests_per_minute": 100, "request_timeout_seconds": 10, **limits},
    )
    profile_id = await repo.save_profile(profile)
    snapshot = make_snapshot(profile_id, profile).model_copy(
        update={
            "evaluator": EvaluatorConfig.model_validate(
                {
                    "roles": {
                        role: {"model": role + "-model", "secret_ref": "env:EVALUATOR_KEY"}
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
    await repo.register_work_item(str(snapshot.id), str(work_id), "test.check", instance_id=OWNER)
    budgets = BudgetManager(repo, OWNER, limits=profile.limits)
    connection = GroqConnection(snapshot, budgets, transport=JsonTransport())
    return repo, snapshot, work_id, connection


def test_ollama_config_needs_no_credential_and_refuses_one():
    target = TargetConfig(
        name="local", adapter="ollama-chat", model="m", base_url="http://127.0.0.1:11434"
    )
    assert target.secret_ref is None
    with pytest.raises(ValidationError):
        TargetConfig(
            name="local",
            adapter="ollama-chat",
            model="m",
            base_url="http://127.0.0.1:11434",
            secret_ref="env:TARGET_KEY",
        )
    with pytest.raises(ValidationError):
        TargetConfig(
            name="remote", adapter="ollama-chat", model="m", base_url="http://192.168.1.5:11434"
        )


def test_native_chat_request_reply_and_persistence(provider, tmp_path, monkeypatch):
    provider.body = json.dumps(ollama_reply()).encode()

    async def scenario():
        repo, snapshot, work, connection = await setup(provider, tmp_path, monkeypatch)
        connection.validate_credentials()
        call = prepare_target(connection, work)
        assert json.loads(call.body_json) == {
            "model": "llama3.2:1b",
            "messages": [
                {"role": "system", "content": "Profile policy"},
                {"role": "user", "content": "synthetic-canary"},
            ],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 64},
        }
        assert (await repo.begin_operation(call.request, instance_id=OWNER)).created
        observation = await connection.execute(call)
        await repo.save_observation(observation, instance_id=OWNER)
        assert (await repo.read_run(str(snapshot.id))).observations[0] == observation
        assert observation.status == "success" and observation.truncated is False
        payload = observation.payload
        assert payload.content == "local hello"
        assert payload.provider_model == "llama3.2:1b"
        assert payload.response_id is None
        assert payload.finish_reason == "stop"
        assert (payload.usage.input_tokens, payload.usage.output_tokens) == (21, 9)
        path, headers, _ = provider.calls[0]
        assert path == "/api/chat"
        assert "Authorization" not in headers

    asyncio.run(scenario())


def test_length_stop_is_a_truncated_reply(provider, tmp_path, monkeypatch):
    provider.body = json.dumps(ollama_reply("partial", done_reason="length")).encode()

    async def scenario():
        _, snapshot, work, connection = await setup(provider, tmp_path, monkeypatch)
        observation = await execute_target(connection, work)
        assert observation.truncated is True
        assert observation.payload.finish_reason == "length"

    asyncio.run(scenario())


def test_missing_local_model_is_a_named_error_without_a_pull(provider, tmp_path, monkeypatch):
    provider.status = 404
    missing = 'model "llama3.2:1b" not found, try pulling it first'
    provider.body = json.dumps({"error": missing}).encode()

    async def scenario():
        _, snapshot, work, connection = await setup(provider, tmp_path, monkeypatch)
        observation = await execute_target(connection, work)
        assert observation.status == "transport_error"
        assert observation.error_code == "local_model_missing"
        assert [path for path, _, _ in provider.calls] == ["/api/chat"]

    asyncio.run(scenario())


def test_no_server_is_a_connection_error_and_nothing_is_started(tmp_path, monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    async def scenario():
        _, snapshot, work, connection = await setup(
            None, tmp_path, monkeypatch, base_url=f"http://127.0.0.1:{closed_port}"
        )
        observation = await execute_target(connection, work)
        assert observation.status == "unknown"
        assert observation.error_code == "provider_connection"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body",
    [
        ollama_reply(done=False),
        ollama_reply(content=""),
        ollama_reply(done_reason="load"),
        {"model": "llama3.2:1b", "done": True},
        ollama_reply(message={"role": "assistant", "content": "x", "tool_calls": [{"f": 1}]}),
    ],
    ids=["not-done", "empty", "load", "no-message", "tool-call"],
)
def test_incomplete_or_unsupported_replies_are_rejected(provider, tmp_path, monkeypatch, body):
    provider.body = json.dumps(body).encode()

    async def scenario():
        _, snapshot, work, connection = await setup(provider, tmp_path, monkeypatch)
        observation = await execute_target(connection, work)
        assert observation.status == "transport_error"
        assert observation.error_code in {"provider_response", "provider_tools"}

    asyncio.run(scenario())


def test_same_limits_apply_to_the_local_target(provider, tmp_path, monkeypatch):
    provider.body = json.dumps(ollama_reply("x" * 4000)).encode()

    async def scenario():
        _, snapshot, work, connection = await setup(
            provider, tmp_path, monkeypatch, response_bytes=1024, target_input_bytes=200
        )
        with pytest.raises(AppError) as error:
            prepare_target(connection, work, "y" * 400)
        assert error.value.code == "input_too_large"
        observation = await execute_target(connection, work)
        assert observation.error_code == "response_too_large"
        assert observation.truncated is True

    asyncio.run(scenario())


def test_evaluator_roles_stay_on_groq_with_their_own_credential(provider, tmp_path, monkeypatch):
    async def scenario():
        _, snapshot, _, connection = await setup(provider, tmp_path, monkeypatch)
        monkeypatch.delenv("EVALUATOR_KEY")
        fresh = GroqConnection(snapshot, connection.budgets, transport=JsonTransport())
        with pytest.raises(AppError) as error:
            fresh.validate_credentials()
        assert error.value.code == "secret_missing"

    asyncio.run(scenario())


def test_full_pack_local_target_matches_hosted_run_history_and_exports(tmp_path):
    from pathlib import Path

    from scripts.pipeline_fixture import (
        LIMITS,
        cli,
        configure,
        ollama_provider,
        wait_run,
    )
    from scripts.pipeline_fixture import provider as hosted_provider

    certificates = Path(__file__).parent / "fixtures"
    hosted_context = hosted_provider(tmp_path / "store", certificates)
    with hosted_context as hosted, ollama_provider(hosted) as local:
        directory, evaluator, _, _ = configure(tmp_path, hosted, certificates)
        local_config = tmp_path / "local.toml"
        local_config.write_text(
            '[target]\nname = "local"\nadapter = "ollama-chat"\nmodel = "fixture-target"\n'
            f'base_url = "{local.origin}"\nsystem_prompt = "Frozen profile policy"\n[limits]\n'
            + "\n".join(f"{key} = {value}" for key, value in LIMITS.items()),
            encoding="utf-8",
        )
        cli(directory, "targets", "add", "local", "--config", local_config)
        try:
            views = {}
            for alias in ("fixture", "local"):
                accepted = cli(
                    directory, "run", alias, "--pack", "broad-chat-v1", "--evaluator", evaluator
                )
                views[alias] = wait_run(directory, accepted["id"])
            assert hosted.failures == []

            def summary(view):
                return {
                    "state": view["state"],
                    "variants": len(view["variants"]),
                    "verdicts": sorted(j["security_verdict"] for j in view["judgments"]),
                    "findings": len(view["findings"]),
                    "progress": view["progress"],
                }

            assert summary(views["local"]) == summary(views["fixture"])
            assert summary(views["local"])["state"] == "completed"
            local_targets = [o for o in views["local"]["observations"] if o["actor"] == "target"]
            assert len(local_targets) == 80
            assert {o["payload"]["provider_model"] for o in local_targets} == {
                "fixture-local-fixture-target"
            }
            assert {o["payload"]["response_id"] for o in local_targets} == {None}
            run_ids = [views[alias]["snapshot"]["id"] for alias in ("fixture", "local")]
            listed = {item["id"] for item in cli(directory, "runs", "list")["items"]}
            assert set(run_ids) <= listed
            assessment = cli(directory, "compare", *run_ids)["assessment"]
            assert assessment["checks_compatible"] is True
            assert assessment["differences"] == [f"{run_ids[1]}: target_config"]
            for fmt in ("json", "markdown", "html"):
                output = tmp_path / f"report.{fmt}"
                receipt = cli(directory, "report", *run_ids, "--format", fmt, "--output", output)
                assert receipt["written"] is True and output.stat().st_size > 0

            def keys(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        yield key.lower()
                        yield from keys(item)
                elif isinstance(value, list):
                    for item in value:
                        yield from keys(item)

            exported = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
            rag = {k for k in keys(exported) if any(w in k for w in ("corpus", "retriev", "rank"))}
            assert rag == set()
        finally:
            cli(directory, "daemon", "stop")
