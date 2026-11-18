import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from pydantic import ValidationError

from asclepius.adapters.chat import GroqConnection
from asclepius.agents import AgentRunner
from asclepius.checks import load_pack_plan
from asclepius.domain import ChatOutput, Observation, ProfileConfig, TargetConfig
from asclepius.models import EvaluationResult
from tests.cli.storage_fixtures import make_snapshot


def harness(monkeypatch):
    monkeypatch.setenv("KEY", "synthetic-key-123")
    profile = ProfileConfig(target=TargetConfig(name="test", model="target", secret_ref="env:KEY"))
    plan = load_pack_plan("broad-chat-v1")
    snapshot = make_snapshot(str(uuid4()), profile).model_copy(
        update={"checks": plan.checks, "prompts": plan.prompts}
    )
    connection = GroqConnection(snapshot, SimpleNamespace(limits=profile.limits))
    calls, replies = [], []

    async def dispatch(gateway, prepared):
        calls.append(prepared)
        raw = json.dumps(replies.pop(0))
        try:
            output, code = prepared.output_type.model_validate(json.loads(raw)), None
        except ValidationError:
            output, code = None, "evaluator_invalid_output"
        obs = success_observation(prepared.call.request, raw)
        return EvaluationResult(prepared.call, obs, output, code)

    return snapshot, AgentRunner(connection, dispatch=dispatch), calls, replies


def success_observation(request, content):
    now = datetime.now(UTC)
    return Observation(
        operation_id=request.id,
        run_id=request.run_id,
        work_item_id=request.work_item_id,
        actor=request.actor,
        status="success",
        started_at=now,
        finished_at=now,
        payload=ChatOutput(content=content),
        request_payload=request.payload,
    )


def proposal(verdict="weakness", quotes=("ASCL_PRIORITY_BREACH",), control=None):
    return dict(
        verdict=verdict,
        quotes=list(quotes),
        rationale="Observed contract outcome",
        confidence=0.8,
        control_outcome=control,
    )


def target(snapshot, variant, content="ASCL_PRIORITY_BREACH", **updates):
    from asclepius.domain import ChatInput, Message

    now = datetime.now(UTC)
    profile = snapshot.profile.target.system_prompt
    payload = ChatInput(
        messages=((Message(role="system", content=profile),) if profile else ())
        + variant.payload.messages
    )
    obs = Observation(
        operation_id=uuid4(),
        run_id=snapshot.id,
        work_item_id=variant.id,
        status="success",
        started_at=now,
        finished_at=now,
        payload=ChatOutput(content=content),
        request_payload=payload,
    )
    return obs.model_copy(update=updates)
