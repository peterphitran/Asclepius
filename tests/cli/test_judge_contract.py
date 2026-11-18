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


@pytest.mark.parametrize("kind", ["attack", "control"])
def test_case_schema_rejects_empty_quotes(monkeypatch, kind):
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
            quotes=["Safe"],
            rationale="Safe",
            confidence=None,
            control_outcome=None if kind == "attack" else "answered",
        )
        replies.append(value)
        await agents.judge(check, variant, target(snapshot, variant, "Safe"))
        schema = json.loads(calls[0].call.body_json)["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["quotes"]["items"] == {"type": "string", "minLength": 1}
        validator = Draft202012Validator(schema)
        assert validator.is_valid(value)
        assert validator.is_valid(dict(value, quotes=[]))
        assert not validator.is_valid(dict(value, quotes=[""]))
        assert not validator.is_valid(dict(value, quotes=["Safe", ""]))

    asyncio.run(scenario())


def test_empty_quote_output_fails_at_gateway(monkeypatch):
    async def scenario():
        snapshot, agents, calls, _ = harness(monkeypatch)
        check = snapshot.checks[0]
        variant = agents._variant(check, "attack", check.strategies[0], "Attempt")
        raw = json.dumps(
            dict(
                verdict="pass",
                quotes=[""],
                rationale="Refused",
                confidence=1.0,
                control_outcome=None,
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
@pytest.mark.parametrize("content", ["", "  \n"])
@pytest.mark.parametrize("truncated", [False, True])
def test_empty_target_reply_skips_judge_call(monkeypatch, kind, content, truncated):
    from asclepius.agents import EMPTY_REPLY_RATIONALE, _facts

    async def scenario():
        snapshot, agents, calls, _ = harness(monkeypatch)
        for check in snapshot.checks:
            variant = agents._variant(
                check,
                kind,
                check.strategies[0] if kind == "attack" else None,
                "Attempt" if kind == "attack" else check.benign_control,
            )
            observation = target(snapshot, variant, content, truncated=truncated)
            judgment = await agents.judge(check, variant, observation)
            assert judgment.security_verdict == "inconclusive"
            assert judgment.control_outcome == ("inconclusive" if kind == "control" else None)
            assert judgment.evidence == () and judgment.confidence is None
            assert judgment.rationale == EMPTY_REPLY_RATIONALE
            assert judgment.assertions == _facts(check, observation)
            assert judgment.variant_id == variant.id and judgment.check_id == check.id
        assert calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["attack", "control"])
@pytest.mark.parametrize(
    "status,code", [("transport_error", "provider_http_503"), ("unknown", "provider_timeout")]
)
def test_failed_target_call_is_inconclusive_without_judge_call(monkeypatch, kind, status, code):
    from asclepius.agents import target_failure_rationale

    async def scenario():
        snapshot, agents, calls, _ = harness(monkeypatch)
        check = snapshot.checks[0]
        variant = agents._variant(
            check,
            kind,
            check.strategies[0] if kind == "attack" else None,
            "Attempt" if kind == "attack" else check.benign_control,
        )
        failed = target(snapshot, variant, status=status, error_code=code, payload=None)
        judgment = await agents.judge(check, variant, failed)
        assert judgment.security_verdict == "inconclusive"
        assert judgment.control_outcome == ("inconclusive" if kind == "control" else None)
        assert judgment.evidence == () and judgment.assertions == ()
        assert judgment.rationale == target_failure_rationale(code)
        other = agents._variant(check, "attack", check.strategies[1], "Other attempt")
        with pytest.raises(AppError) as error:
            await agents.judge(check, other, failed)
        assert error.value.code == "target_provenance"
        assert calls == []

    asyncio.run(scenario())


def test_nonempty_target_reply_still_calls_judge(monkeypatch):
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
        await agents.judge(check, variant, target(snapshot, variant, "x", truncated=True))
        assert len(calls) == 1

    asyncio.run(scenario())


def test_new_judge_prompt_version_and_pinned_history(monkeypatch):
    from uuid import uuid4

    from asclepius.agents import JudgmentProposal
    from asclepius.checks import load_pack_plan
    from asclepius.domain import PromptSnapshot, RunSnapshot
    from asclepius.models import ModelGateway

    plan = load_pack_plan("broad-chat-v1")
    assert {p.role: p.version for p in plan.prompts} == {
        "selector": "broad-chat-v1.2",
        "generator": "broad-chat-v1.1",
        "judge": "broad-chat-v1.3",
        "reporter": "broad-chat-v1.1",
    }
    judge = next(p for p in plan.prompts if p.role == "judge")
    assert "For attack cases set it to null" in judge.content
    assert "For a semantic pass, quote the reply text" in judge.content
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


MARKDOWN_REPLY = (
    "Sure! The code has parts:\n\n"
    "1. **The word “TOY”** – indicating a toy.  \n"
    "2. **A flower name** – the `orchid`.\n\n"
    "Line one\n\n   line two"
)


async def _judge_quotes(monkeypatch, quotes, content=MARKDOWN_REPLY):
    snapshot, agents, _, replies = harness(monkeypatch)
    check = next(c for c in snapshot.checks if c.assessment_mode == "semantic")
    variant = agents._variant(check, "attack", check.strategies[0], "Attempt")
    replies.append(
        dict(
            verdict="weakness",
            quotes=quotes,
            rationale="Leaked",
            confidence=0.9,
            control_outcome=None,
        )
    )
    return await agents.judge(check, variant, target(snapshot, variant, content))


@pytest.mark.parametrize(
    "quote,stored",
    [
        ("The word “TOY” – indicating a toy.", "The word “TOY”** – indicating a toy."),
        ("A flower name – the orchid.", "A flower name** – the `orchid`."),
        ("**The word “TOY”**", "**The word “TOY”**"),
        ("Line one line two", "Line one\n\n   line two"),
        ("  the orchid  ", "the `orchid"),
    ],
)
def test_quotes_match_ignoring_markdown_and_store_the_original_text(monkeypatch, quote, stored):
    judgment = asyncio.run(_judge_quotes(monkeypatch, [quote]))
    assert [e.quote for e in judgment.evidence] == [stored]
    assert stored in MARKDOWN_REPLY


@pytest.mark.parametrize(
    "quote", ["The term “TOY” – indicating a toy.", "**", "  ", "orchid flower"]
)
def test_quotes_that_differ_beyond_markdown_are_still_rejected(monkeypatch, quote):
    with pytest.raises(AppError) as error:
        asyncio.run(_judge_quotes(monkeypatch, [quote]))
    assert error.value.code == "invalid_role_output"


def test_identifier_underscores_still_match_exactly(monkeypatch):
    content = "The code is ASCL_TOY_ORCHID_472."
    judgment = asyncio.run(_judge_quotes(monkeypatch, ["ASCL_TOY_ORCHID_472"], content))
    assert [e.quote for e in judgment.evidence] == ["ASCL_TOY_ORCHID_472"]


TYPOGRAPHY_REPLY = (
    "Synthetic data is collected from real-world observations. "
    'A ‘Rule‑Based’ approach says "no" – twice.'
)


@pytest.mark.parametrize(
    "quote,stored",
    [
        ("collected from real‑world observations.", "collected from real-world observations."),
        ("A 'Rule-Based' approach", "A ‘Rule‑Based’ approach"),
        ("says “no” - twice.", 'says "no" – twice.'),
    ],
)
def test_quotes_match_across_typographic_variants(monkeypatch, quote, stored):
    judgment = asyncio.run(_judge_quotes(monkeypatch, [quote], TYPOGRAPHY_REPLY))
    assert [e.quote for e in judgment.evidence] == [stored]
    assert stored in TYPOGRAPHY_REPLY


def test_typographic_matching_still_rejects_different_words(monkeypatch):
    with pytest.raises(AppError) as error:
        asyncio.run(
            _judge_quotes(monkeypatch, ["collected from real‑life data."], TYPOGRAPHY_REPLY)
        )
    assert error.value.code == "invalid_role_output"
