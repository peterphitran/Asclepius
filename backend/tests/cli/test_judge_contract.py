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
        replies.append(dict(verdict="pass", quotes=[], rationale="Refused", confidence=None,
                            control_outcome=None))
        await agents.judge(check, variant, target(snapshot, variant, "I cannot comply"))
        schema = json.loads(calls[0].call.body_json)["response_format"]["json_schema"]["schema"]
        value = dict(verdict="pass", quotes=[], rationale="Refused", confidence=None,
                     control_outcome="answered")
        assert not Draft202012Validator(schema).is_valid(value)

    asyncio.run(scenario())


def test_invalid_attack_output_fails_at_gateway_with_observation(monkeypatch):
    async def scenario():
        snapshot, agents, calls, _ = harness(monkeypatch)
        check = snapshot.checks[0]
        variant = agents._variant(check, "attack", check.strategies[0], "Attempt")
        raw = json.dumps(dict(verdict="pass", quotes=["I cannot comply"], rationale="Refused",
                              confidence=0.8, control_outcome="answered"))
        observations = []

        async def execute(call):
            request = call.request
            now = datetime.now(UTC)
            obs = Observation(operation_id=request.id, run_id=request.run_id,
                              work_item_id=request.work_item_id, actor=request.actor,
                              status="success", started_at=now, finished_at=now,
                              payload=ChatOutput(content=raw), request_payload=request.payload)
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
