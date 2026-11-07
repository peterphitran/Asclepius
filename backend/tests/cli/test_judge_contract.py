import asyncio
import json
from datetime import UTC, datetime

import pytest
from jsonschema import Draft202012Validator

from asclepius.domain import AppError, ChatOutput, Observation
from tests.cli.test_agents import harness, target


def test_attack_schema_rejects_control_outcomes(monkeypatch):
    async def scenario():
        snapshot, agents, calls, replies = harness(monkeypatch)
        check = snapshot.checks[0]
        variant = agents._variant(check, "attack", check.strategies[0], "Attempt")
        replies.append(
            dict(
                verdict="pass",
                quotes=[],
                rationale="Refused",
                confidence=None,
                control_outcome=None,
            )
        )
        await agents.judge(check, variant, target(snapshot, variant, "I cannot comply"))
        schema = json.loads(calls[0].call.body_json)["response_format"]["json_schema"]["schema"]
        value = dict(
            verdict="pass",
            quotes=[],
            rationale="Refused",
            confidence=None,
            control_outcome="answered",
        )
        assert not Draft202012Validator(schema).is_valid(value)

    asyncio.run(scenario())


def test_invalid_attack_output_fails_at_gateway_with_observation(monkeypatch):
    async def scenario():
        snapshot, agents, calls, _ = harness(monkeypatch)
        check = snapshot.checks[0]
        variant = agents._variant(check, "attack", check.strategies[0], "Attempt")
        raw = json.dumps(
            dict(
                verdict="pass",
                quotes=["I cannot comply"],
                rationale="Refused",
                confidence=0.8,
                control_outcome="answered",
            )
        )
        observations = []

        async def execute(call):
            request = call.request
            now = datetime.now(UTC)
            obs = Observation(
                operation_id=request.id,
                run_id=request.run_id,
                work_item_id=request.work_item_id,
                actor=request.actor,
                status="success",
                started_at=now,
                finished_at=now,
                payload=ChatOutput(content=raw),
                request_payload=request.payload,
            )
            observations.append(obs)
            return obs

        async def dispatch(gateway, prepared):
            calls.append(prepared)
            return await gateway.execute(prepared)

        monkeypatch.setattr(agents.connection, "execute", execute)
        agents.dispatch = dispatch
        with pytest.raises(AppError) as error:
            await agents.judge(check, variant, target(snapshot, variant, "I cannot comply"))
        assert error.value.code == "evaluator_invalid_output"
        assert error.value.result.observation == observations[0]
        assert len(calls) == len(observations) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["attack", "control"])
def test_case_schema_and_common_history(monkeypatch, kind):
    from asclepius.agents import JudgmentProposal

    async def scenario():
        snapshot, agents, calls, replies = harness(monkeypatch)
        check = snapshot.checks[0]
        variant = agents._variant(
            check,
            kind,
            check.strategies[0] if kind == "attack" else None,
            "Attempt" if kind == "attack" else check.benign_control,
        )
        value = dict(
            verdict="pass",
            quotes=[],
            rationale="Safe",
            confidence=None,
            control_outcome=None if kind == "attack" else "answered",
        )
        replies.append(value)
        await agents.judge(check, variant, target(snapshot, variant, "Safe"))
        body = json.loads(calls[0].call.body_json)
        spec = body["response_format"]["json_schema"]
        schema = spec["schema"]
        assert spec["strict"] is True and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert {item["type"] for item in schema["properties"]["confidence"]["anyOf"]} == {
            "number",
            "null",
        }
        field = schema["properties"]["control_outcome"]
        if kind == "attack":
            assert field["type"] == "null"
        else:
            assert field["type"] == "string"
            assert field["enum"] == ["answered", "over_refusal", "inconclusive"]
        validator = Draft202012Validator(schema)
        for outcome in (None, "answered", "over_refusal", "inconclusive", "invalid"):
            candidate = dict(value, control_outcome=outcome)
            assert validator.is_valid(candidate) == (
                outcome is None
                if kind == "attack"
                else outcome in ("answered", "over_refusal", "inconclusive")
            )
        assert not validator.is_valid({k: v for k, v in value.items() if k != "control_outcome"})
        assert not validator.is_valid(dict(value, extra=True))
        assert JudgmentProposal.model_validate_json(
            json.dumps(dict(value, control_outcome="answered"))
        )

    asyncio.run(scenario())


def test_new_judge_prompt_version_and_pinned_history(monkeypatch):
    from uuid import uuid4

    from asclepius.agents import JudgmentProposal
    from asclepius.checks import load_pack_plan
    from asclepius.domain import PromptSnapshot, RunSnapshot
    from asclepius.models import ModelGateway

    plan = load_pack_plan("broad-chat-v1")
    assert {p.role: p.version for p in plan.prompts} == {
        "selector": "broad-chat-v1.1",
        "generator": "broad-chat-v1.1",
        "judge": "broad-chat-v1.2",
        "reporter": "broad-chat-v1.1",
    }
    judge = next(p for p in plan.prompts if p.role == "judge")
    assert "For attack cases set it to null" in judge.content
    snapshot, agents, _, _ = harness(monkeypatch)
    old = PromptSnapshot(role="judge", version="broad-chat-v1.1", content="Old pinned judge")
    snapshot = snapshot.model_copy(
        update={"prompts": tuple(old if p.role == "judge" else p for p in snapshot.prompts)}
    )
    restored = RunSnapshot.model_validate_json(snapshot.model_dump_json())
    agents.connection.snapshot = restored
    prepared = ModelGateway(agents.connection, work_item_id=uuid4()).prepare(
        "judge", {}, JudgmentProposal
    )
    assert json.loads(prepared.call.body_json)["messages"][0]["content"] == old.content
    assert next(p for p in restored.prompts if p.role == "judge") == old
