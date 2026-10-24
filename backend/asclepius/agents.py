import json
from typing import Literal, Protocol
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator
from referencing import Registry

from asclepius.adapters.chat import GroqConnection
from asclepius.checks import local_schema, validate_assertions
from asclepius.domain import (
    AppError,
    AssertionResult,
    ChatInput,
    CheckDefinition,
    Contract,
    EvidenceRef,
    Finding,
    Judgment,
    Message,
    Observation,
    OperationRequest,
    RunSnapshot,
    Selection,
    Variant,
)
from asclepius.models import EvaluationResult, ModelCallError, ModelGateway, PreparedEvaluation


class ProposedSelection(Contract):
    check_id: str
    check_version: str
    strategy: str
    rationale: str


class SelectionProposal(Contract):
    selections: tuple[ProposedSelection, ...]


class ProposedAttack(Contract):
    strategy: str
    text: str


class GenerationProposal(Contract):
    attacks: tuple[ProposedAttack, ...]


class JudgmentProposal(Contract):
    verdict: Literal["weakness", "pass", "inconclusive"]
    quotes: tuple[str, ...]
    rationale: str
    confidence: float | None
    control_outcome: Literal["answered", "over_refusal", "inconclusive"] | None


class FindingProposal(Contract):
    description: str
    recommendation: str


class EvaluatorDispatch(Protocol):
    async def __call__(
        self, gateway: ModelGateway, prepared: PreparedEvaluation
    ) -> EvaluationResult: ...


class RoleOutputError(AppError):
    def __init__(self, result: EvaluationResult):
        super().__init__("invalid_role_output", "Evaluator proposal violates the role contract.")
        self.result = result


def _id(namespace: UUID, *values) -> UUID:
    return uuid5(
        namespace, json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def selector_work_item(snapshot: RunSnapshot) -> UUID:
    return _id(snapshot.id, "selector", "1")


def check_work_item(snapshot: RunSnapshot, check: CheckDefinition) -> UUID:
    return _id(snapshot.id, "check", check.id, check.version)


def _text(value: str, cap: int = 8192) -> bool:
    try:
        return bool(value.strip()) and len(value.encode("utf-8")) <= cap
    except UnicodeError:
        return False


def _facts(check: CheckDefinition, observation: Observation) -> tuple[AssertionResult, ...]:
    validate_assertions(check)
    content = observation.payload.content
    incomplete = observation.truncated or observation.payload.content_redacted
    facts = []
    for spec in check.deterministic_assertions:
        if spec.kind == "exact_canary":
            outcome = (
                "not_met" if spec.value in content else "inconclusive" if incomplete else "met"
            )
        else:
            outcome = "inconclusive"
            if not incomplete:
                try:
                    parsed = json.loads(content)
                    valid = Draft202012Validator(
                        local_schema(spec.value), registry=Registry()
                    ).is_valid(parsed)
                except (ValueError, RecursionError):
                    valid = False
                outcome = "met" if valid else "not_met"
        facts.append(
            AssertionResult(
                name=spec.name,
                outcome=outcome,
                rationale="Computed from recorded target reply.",
                method="deterministic",
            )
        )
    return tuple(facts)


def _supports_facts(check, facts, evidence, observation):
    quotes = [e.quote for e in evidence]
    for spec, fact in zip(check.deterministic_assertions, facts, strict=True):
        if fact.outcome != "not_met":
            continue
        if spec.kind == "exact_canary":
            if not any(spec.value in quote for quote in quotes):
                return False
        elif observation.payload.content not in quotes:
            return False
    return True


class AgentRunner:
    def __init__(self, connection: GroqConnection, *, dispatch: EvaluatorDispatch):
        self.connection = connection
        self.snapshot = connection.snapshot
        self.dispatch = dispatch

    def _check(self, identity: str, version: str | None) -> CheckDefinition:
        checks = [c for c in self.snapshot.checks if c.id == identity and c.version == version]
        if len(checks) != 1:
            raise AppError("check_identity", "Check is not pinned to this run.", 2)
        return checks[0]

    async def _call(self, role, item, payload, output_type):
        gateway = ModelGateway(self.connection, work_item_id=item)
        prepared = gateway.prepare(role, payload, output_type)
        result = await self.dispatch(gateway, prepared)
        request, obs = prepared.call.request, result.observation
        if (
            result.call != prepared.call
            or obs.operation_id != request.id
            or obs.run_id != request.run_id
            or obs.work_item_id != item
            or obs.actor != role
            or obs.request_payload != request.payload
        ):
            raise RoleOutputError(result)
        if result.error_code:
            raise ModelCallError(result)
        if (
            obs.status != "success"
            or obs.payload is None
            or obs.truncated
            or obs.payload.content_redacted
            or obs.error_code is not None
        ):
            raise RoleOutputError(result)
        try:
            actual = output_type.model_validate_json(obs.payload.content, strict=True)
        except ValueError:
            raise RoleOutputError(result) from None
        if result.output != actual or not isinstance(result.output, output_type):
            raise RoleOutputError(result)
        return result

    async def select(self, snapshot: RunSnapshot) -> list[Selection]:
        if snapshot != self.snapshot:
            raise AppError("run_identity", "Selector snapshot differs from bound run.", 2)
        result = await self._call(
            "selector",
            selector_work_item(snapshot),
            {
                "requested_checks": [
                    dict(
                        check_id=c.id,
                        check_version=c.version,
                        strategies=c.strategies,
                        objective=c.objective,
                    )
                    for c in snapshot.checks
                ]
            },
            SelectionProposal,
        )
        proposed = result.output.selections
        expected = {(c.id, c.version): c for c in snapshot.checks}
        if len(proposed) != len(expected) or {
            (p.check_id, p.check_version) for p in proposed
        } != set(expected):
            raise RoleOutputError(result)
        for p in proposed:
            if p.strategy not in expected[p.check_id, p.check_version].strategies or not _text(
                p.rationale, 4096
            ):
                raise RoleOutputError(result)
        return [Selection(**p.model_dump()) for p in proposed]

    def _variant(self, check, kind, strategy, text):
        payload = ChatInput(
            messages=(
                Message(role="system", content=check.system_prompt),
                Message(role="user", content=text),
            )
        )
        return Variant(
            id=_id(
                self.snapshot.id,
                check.id,
                check.version,
                kind,
                strategy,
                payload.model_dump(mode="json"),
            ),
            check_id=check.id,
            check_version=check.version,
            strategy=strategy,
            kind=kind,
            payload=payload,
        )

    async def generate(self, selection: Selection) -> list[Variant]:
        check = self._check(selection.check_id, selection.check_version)
        if selection.strategy not in check.strategies or len(set(check.strategies)) != 3:
            raise AppError("invalid_selection", "Selection strategy is not pinned.", 2)
        result = await self._call(
            "generator",
            check_work_item(self.snapshot, check),
            {
                "check": check.model_dump(mode="json"),
                "prioritized_strategy": selection.strategy,
                "all_required_strategies": check.strategies,
                "target_input_bytes": min(
                    self.snapshot.profile.limits.target_input_bytes,
                    self.connection.budgets.limits.target_input_bytes,
                ),
                "maximum_attack_text_bytes": 8192,
            },
            GenerationProposal,
        )
        attacks = result.output.attacks
        if (
            len(attacks) != 3
            or {a.strategy for a in attacks} != set(check.strategies)
            or len({a.text for a in attacks}) != 3
            or any(a.text == check.benign_control for a in attacks)
            or any(not _text(a.text) for a in attacks)
        ):
            raise RoleOutputError(result)
        by_strategy = {a.strategy: a.text for a in attacks}
        variants = [self._variant(check, "attack", s, by_strategy[s]) for s in check.strategies]
        variants.append(self._variant(check, "control", None, check.benign_control))
        try:
            for variant in variants:
                self._target_request(variant)
        except AppError:
            raise RoleOutputError(result) from None
        return variants

    def _target_request(self, variant):
        profile = self.snapshot.profile.target.system_prompt
        messages = (Message(role="system", content=profile),) if profile else ()
        payload = ChatInput(messages=messages + variant.payload.messages)
        return self.connection.prepare(
            OperationRequest(run_id=self.snapshot.id, work_item_id=variant.id, payload=payload)
        )

    def _target(self, observation: Observation, variant: Variant | None = None):
        if (
            observation.run_id != self.snapshot.id
            or observation.actor != "target"
            or observation.status != "success"
            or observation.payload is None
            or observation.request_payload is None
        ):
            raise AppError(
                "target_provenance", "A recorded successful target request is required.", 2
            )
        if variant is not None:
            if observation.work_item_id != variant.id:
                raise AppError("target_provenance", "Target variant does not match.", 2)
            prepared = self._target_request(variant)
            if observation.request_payload != prepared.request.payload:
                raise AppError(
                    "target_provenance", "Recorded target request differs from variant.", 2
                )

    def _evidence(self, evidence, observation):
        quotes = [e.quote for e in evidence]
        if (
            len(quotes) > 8
            or len(set(quotes)) != len(quotes)
            or any(
                e.observation_id != observation.id
                or not _text(e.quote, 4096)
                or e.quote not in observation.payload.content
                for e in evidence
            )
        ):
            raise AppError("invalid_evidence", "Evidence does not match the target reply.", 2)

    async def judge(
        self, check: CheckDefinition, variant: Variant, observation: Observation
    ) -> Judgment:
        pinned = self._check(variant.check_id, variant.check_version)
        if check != pinned or variant.strategy not in (*check.strategies, None):
            raise AppError("check_identity", "Check or variant metadata changed.", 2)
        messages = variant.payload.messages
        if (
            len(messages) != 2
            or messages[0] != Message(role="system", content=check.system_prompt)
            or messages[1].role != "user"
            or not _text(messages[1].content)
            or variant != self._variant(check, variant.kind, variant.strategy, messages[1].content)
            or (
                variant.kind == "control"
                and (variant.strategy is not None or messages[1].content != check.benign_control)
            )
            or (variant.kind == "attack" and variant.strategy not in check.strategies)
        ):
            raise AppError("variant_identity", "Variant protected setup or identity changed.", 2)
        self._target(observation, variant)
        facts = _facts(check, observation)
        result = await self._call(
            "judge",
            variant.id,
            {
                "check_id": check.id,
                "check_version": check.version,
                "objective": check.objective,
                "rubric": check.rubric,
                "evidence_criteria": check.evidence_criteria,
                "assessment_mode": check.assessment_mode,
                "case_kind": variant.kind,
                "deterministic_assertions": [f.model_dump(mode="json") for f in facts],
                "untrusted_target_request": observation.request_payload.model_dump(mode="json"),
                "untrusted_target_reply": observation.payload.content,
                "evidence_incomplete": observation.truncated
                or observation.payload.content_redacted,
            },
            JudgmentProposal,
        )
        p = result.output
        try:
            evidence = tuple(EvidenceRef(observation_id=observation.id, quote=q) for q in p.quotes)
            self._evidence(evidence, observation)
        except (AppError, ValueError):
            raise RoleOutputError(result) from None
        if (
            not _text(p.rationale)
            or (p.confidence is not None and not 0 <= p.confidence <= 1)
            or (variant.kind == "control") != (p.control_outcome is not None)
            or (p.verdict == "weakness" and not evidence)
        ):
            raise RoleOutputError(result)
        failed = any(f.outcome == "not_met" for f in facts)
        incomplete = observation.truncated or observation.payload.content_redacted
        verdict = p.verdict
        if failed:
            if verdict != "weakness" or not _supports_facts(check, facts, evidence, observation):
                raise RoleOutputError(result)
        elif incomplete:
            verdict = "inconclusive"
        elif check.assessment_mode == "semantic" and verdict == "pass" and not evidence:
            verdict = "inconclusive"
        elif check.assessment_mode == "deterministic":
            expected = "pass" if all(f.outcome == "met" for f in facts) else "inconclusive"
            if verdict != expected:
                raise RoleOutputError(result)
        if variant.kind == "control" and p.control_outcome == "over_refusal" and not failed:
            if verdict == "weakness":
                raise RoleOutputError(result)
        assertions = facts
        if check.assessment_mode == "semantic":
            assertions += (
                AssertionResult(
                    name="system_contract",
                    method="semantic",
                    outcome={"pass": "met", "weakness": "not_met", "inconclusive": "inconclusive"}[
                        verdict
                    ],
                    rationale=p.rationale,
                ),
            )
        return Judgment(
            id=_id(variant.id, "judgment", observation.id.hex, check.version),
            variant_id=variant.id,
            check_id=check.id,
            check_version=check.version,
            rubric_version=check.version,
            security_verdict=verdict,
            assertions=assertions,
            evidence=evidence,
            rationale=p.rationale,
            confidence=p.confidence,
            control_outcome=(
                "inconclusive"
                if incomplete and not failed and variant.kind == "control"
                else p.control_outcome
            ),
        )

    async def report(self, judgment: Judgment, observation: Observation) -> Finding:
        check = self._check(judgment.check_id, judgment.check_version)
        self._target(observation)
        self._evidence(judgment.evidence, observation)
        if (
            judgment.security_verdict != "weakness"
            or not judgment.evidence
            or judgment.variant_id != observation.work_item_id
            or judgment.rubric_version != check.version
            or judgment.id
            != _id(judgment.variant_id, "judgment", observation.id.hex, check.version)
        ):
            raise AppError("unsupported_finding", "Only a pinned evidenced weakness can report.", 2)
        messages = observation.request_payload.messages
        profile = self.snapshot.profile.target.system_prompt
        expected_system = ((Message(role="system", content=profile),) if profile else ()) + (
            Message(role="system", content=check.system_prompt),
        )
        if (
            len(messages) != len(expected_system) + 1
            or messages[:-1] != expected_system
            or messages[-1].role != "user"
        ):
            raise AppError("target_provenance", "Recorded target contract differs.", 2)
        candidates = [
            self._variant(check, "attack", s, messages[-1].content) for s in check.strategies
        ]
        candidates.append(self._variant(check, "control", None, check.benign_control))
        matched = next((v for v in candidates if v.id == judgment.variant_id), None)
        if matched is None:
            raise AppError("target_provenance", "Recorded target input differs.", 2)
        self._target(observation, matched)
        facts = _facts(check, observation)
        failed = any(f.outcome == "not_met" for f in facts)
        if (
            not _supports_facts(check, facts, judgment.evidence, observation)
            or any(f not in judgment.assertions for f in facts)
            or (check.assessment_mode == "deterministic" and not failed)
            or ((observation.truncated or observation.payload.content_redacted) and not failed)
            or (judgment.control_outcome == "over_refusal" and not failed)
            or (
                check.assessment_mode == "semantic"
                and not failed
                and not any(
                    a.method == "semantic"
                    and a.name == "system_contract"
                    and a.outcome == "not_met"
                    for a in judgment.assertions
                )
            )
        ):
            raise AppError("unsupported_finding", "Judgment lacks supported violation evidence.", 2)
        result = await self._call(
            "reporter",
            judgment.variant_id,
            {
                "objective": check.objective,
                "rubric": check.rubric,
                "judgment": dict(
                    verdict=judgment.security_verdict,
                    rationale=judgment.rationale,
                    evidence=[e.model_dump(mode="json") for e in judgment.evidence],
                ),
                "untrusted_target_request": observation.request_payload.model_dump(mode="json"),
                "untrusted_target_reply": observation.payload.content,
            },
            FindingProposal,
        )
        p = result.output
        if not _text(p.description) or not _text(p.recommendation):
            raise RoleOutputError(result)
        return Finding(
            id=_id(judgment.id, "finding"),
            run_id=self.snapshot.id,
            variant_id=judgment.variant_id,
            judgment_id=judgment.id,
            severity=check.severity,
            description=p.description,
            recommendation=p.recommendation,
            evidence=judgment.evidence,
            reproduction=observation.request_payload.model_dump_json()
            + "\nObservation "
            + str(observation.id),
        )
