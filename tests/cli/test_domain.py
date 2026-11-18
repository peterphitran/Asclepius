from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from asclepius.domain import (
    AppError,
    ChatInput,
    ChatOutput,
    CheckDefinition,
    DaemonStatus,
    EvaluatorConfig,
    Message,
    Observation,
    OperationRequest,
    ProfileConfig,
    RunSnapshot,
    RunState,
    TargetConfig,
    allowed_transition,
)


def test_non_rag_observation_needs_no_corpus() -> None:
    request = OperationRequest(
        run_id=uuid4(),
        work_item_id=uuid4(),
        payload=ChatInput(messages=(Message(role="user", content="Hello"),)),
    )
    observation = Observation(
        operation_id=request.id,
        run_id=request.run_id,
        work_item_id=request.work_item_id,
        status="success",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        payload=ChatOutput(content="Hello there"),
    )
    restored = Observation.model_validate_json(observation.model_dump_json())
    assert restored.payload.content == "Hello there"
    assert restored.kind == "chat.v1"
    assert "corpus" not in restored.model_dump()


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled", "interrupted"])
def test_terminal_states_cannot_transition_to_queued(state: str) -> None:
    with pytest.raises(AppError):
        allowed_transition(RunState(state), RunState.QUEUED)


def test_only_legal_run_transitions_are_accepted() -> None:
    assert allowed_transition(RunState.QUEUED, RunState.RUNNING) == RunState.RUNNING
    assert allowed_transition(RunState.RUNNING, RunState.INTERRUPTED) == RunState.INTERRUPTED
    with pytest.raises(AppError):
        allowed_transition(RunState.QUEUED, RunState.COMPLETED)


def test_check_contract_is_deeply_immutable() -> None:
    check = CheckDefinition(
        id="priority.override",
        version="1",
        family="priority",
        objective="Keep the boundary",
        system_prompt="Keep the boundary",
        strategies=["a", "b", "c"],
        benign_control="Say hello",
        rubric="Do not override the boundary",
    )
    assert check.strategies == ("a", "b", "c")
    with pytest.raises(ValidationError):
        check.objective = "Changed"
    with pytest.raises(AttributeError):
        check.strategies.append("d")


@pytest.mark.parametrize(
    "status,payload,error",
    [
        ("success", None, None),
        ("transport_error", ChatOutput(content="invented"), "timeout"),
        ("unknown", ChatOutput(content="invented"), None),
    ],
)
def test_observation_cannot_claim_inconsistent_outcomes(status, payload, error) -> None:
    with pytest.raises(ValidationError):
        Observation(
            operation_id=uuid4(),
            run_id=uuid4(),
            work_item_id=uuid4(),
            status=status,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            payload=payload,
            error_code=error,
        )


def test_unknown_operation_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OperationRequest(
            run_id=uuid4(),
            work_item_id=uuid4(),
            kind="arbitrary-script.v1",
            payload=ChatInput(messages=(Message(role="user", content="hello"),)),
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://user:password@example.com",
        "https://@example.com/v1",
        "https://example.com/path\x00suffix",
        "http://localhost:11434/v1",
    ],
)
def test_hosted_endpoint_safety_survives_direct_construction(url: str) -> None:
    with pytest.raises(ValidationError):
        TargetConfig(name="test", model="test-model", secret_ref="env:KEY", base_url=url)


def test_ollama_allows_loopback_http_without_credentials() -> None:
    target = TargetConfig(
        name="local",
        adapter="ollama-chat",
        model="local-model",
        base_url="http://localhost:11434/v1",
    )
    assert target.secret_ref is None


def test_daemon_time_rejects_naive_and_normalizes_aware() -> None:
    with pytest.raises(ValidationError):
        DaemonStatus(heartbeat_at=datetime(2026, 10, 21))
    status = DaemonStatus(
        heartbeat_at=datetime(2026, 10, 21, 8, tzinfo=timezone(timedelta(hours=5)))
    )
    assert status.heartbeat_at.isoformat() == "2026-10-21T03:00:00+00:00"
    restored = DaemonStatus.model_validate_json(status.model_dump_json())
    assert restored.heartbeat_at.tzinfo == UTC


def test_run_snapshot_rejects_naive_time() -> None:
    target = ProfileConfig(target=TargetConfig(name="test", model="model", secret_ref="env:KEY"))
    evaluator = EvaluatorConfig.model_validate(
        {
            "roles": {
                role: {"model": "evaluator", "secret_ref": "env:KEY"}
                for role in ("selector", "generator", "judge", "reporter")
            }
        }
    )
    check = CheckDefinition(
        id="test",
        version="1",
        family="test",
        objective="test",
        system_prompt="test",
        strategies=("test",),
        benign_control="hello",
        rubric="test",
    )
    with pytest.raises(ValidationError):
        RunSnapshot(
            profile_id=uuid4(),
            profile=target,
            evaluator=evaluator,
            checks=(check,),
            created_at=datetime(2026, 10, 21),
        )


def test_observation_times_normalize_to_utc() -> None:
    observation = Observation(
        operation_id=uuid4(),
        run_id=uuid4(),
        work_item_id=uuid4(),
        status="unknown",
        started_at="2026-10-21T08:00:00+05:00",
    )
    assert observation.started_at.isoformat() == "2026-10-21T03:00:00+00:00"
