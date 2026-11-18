from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from asclepius.domain import (
    ActorResults,
    AppError,
    AttackCounts,
    Comparison,
    ComparisonAssessment,
    ControlCounts,
    DeliveryCounts,
    FamilyResults,
    Finding,
    FindingDetail,
    Judgment,
    Observation,
    RunResults,
    RunView,
    UsageCoverage,
    Variant,
)


@dataclass(frozen=True)
class _Case:
    variant: Variant
    observation: Observation | None
    judgment: Judgment | None
    finding: Finding | None


def _unique(items, key):
    result = {}
    for item in items:
        identity = key(item)
        if identity in result:
            raise AppError("results_corrupt", "Duplicate identity in saved run evidence.")
        result[identity] = item
    return result


def _cases(view: RunView) -> tuple[_Case, ...]:
    checks = _unique(view.snapshot.checks, lambda item: item.id)
    _unique(view.snapshot.prompts, lambda item: item.role)
    variants = _unique(view.variants, lambda item: item.id)
    observations = _unique(view.observations, lambda item: item.id)
    _unique(view.observations, lambda item: item.operation_id)
    targets = _unique(
        (item for item in view.observations if item.actor == "target"),
        lambda item: item.work_item_id,
    )
    judgments = _unique(view.judgments, lambda item: item.variant_id)
    _unique(view.judgments, lambda item: item.id)
    findings = _unique(view.findings, lambda item: item.variant_id)
    _unique(view.findings, lambda item: item.id)

    def require(condition):
        if not condition:
            raise AppError("results_corrupt", "Impossible lineage in saved run evidence.")

    for observation in view.observations:
        require(observation.run_id == view.snapshot.id)
    for identity in targets:
        require(identity in variants)
    for identity in judgments.keys() | findings.keys():
        require(identity in variants)
    cases = []
    for identity, variant in variants.items():
        require(variant.check_id in checks)
        check = checks[variant.check_id]
        require(variant.check_version == check.version)
        judgment = judgments.get(identity)
        observation = targets.get(identity)
        if judgment is not None:
            require(observation is not None)
            require(judgment.check_id == check.id)
            require(judgment.check_version == check.version)
            require(judgment.rubric_version == check.version)
            for ref in judgment.evidence:
                require(ref.observation_id in observations)
                require(ref.observation_id == observation.id)
        finding = findings.get(identity)
        if finding is not None:
            require(finding.run_id == view.snapshot.id and judgment is not None)
            require(finding.judgment_id == judgment.id)
            for ref in finding.evidence:
                require(observation is not None and ref.observation_id == observation.id)
        cases.append(_Case(variant, observation, judgment, finding))
    return tuple(cases)


def _counts(cases: tuple[_Case, ...], kind: str) -> AttackCounts | ControlCounts:
    selected = tuple(case for case in cases if case.variant.kind == kind)
    delivery = Counter(
        case.observation.status if case.observation else "unobserved" for case in selected
    )
    outcomes = Counter(
        (case.judgment.security_verdict if kind == "attack" else case.judgment.control_outcome)
        or "unknown"
        for case in selected
        if case.judgment is not None
    )
    common = dict(
        generated=len(selected),
        judged=sum(case.judgment is not None for case in selected),
        missing_judgment=sum(case.judgment is None for case in selected),
        inconclusive=outcomes["inconclusive"],
        findings=sum(case.finding is not None for case in selected),
        delivery=DeliveryCounts(**delivery),
    )
    if kind == "attack":
        return AttackCounts(
            **common,
            weakness=outcomes["weakness"],
            passed=outcomes["pass"],
            verdict_unknown=outcomes["unknown"],
        )
    return ControlCounts(
        **common,
        answered=outcomes["answered"],
        over_refusal=outcomes["over_refusal"],
        outcome_unknown=outcomes["unknown"],
    )


def _total(counts, model):
    return model(
        **{
            name: sum(getattr(item, name) for item in counts)
            for name in model.model_fields
            if name != "delivery"
        },
        delivery=DeliveryCounts(
            **{
                name: sum(getattr(item.delivery, name) for item in counts)
                for name in DeliveryCounts.model_fields
            }
        ),
    )


def _usage(observations: tuple[Observation, ...]) -> UsageCoverage:
    payloads = [item.payload for item in observations if item.payload is not None]
    inputs = [item.usage.input_tokens for item in payloads if item.usage.input_tokens is not None]
    outputs = [
        item.usage.output_tokens for item in payloads if item.usage.output_tokens is not None
    ]
    raw = [item.raw_content_bytes for item in payloads if item.raw_content_bytes is not None]
    return UsageCoverage(
        observations=len(observations),
        input_measured=len(inputs),
        output_measured=len(outputs),
        input_tokens=sum(inputs) if inputs else None,
        output_tokens=sum(outputs) if outputs else None,
        truncated=sum(item.truncated for item in observations),
        redacted=sum(item.content_redacted for item in payloads),
        raw_bytes_measured=len(raw),
        raw_content_bytes=sum(raw) if raw else None,
    )


def summarize_run(view: RunView) -> RunResults:
    cases = _cases(view)
    families = []
    for family in dict.fromkeys(check.family for check in view.snapshot.checks):
        checks = {check.id for check in view.snapshot.checks if check.family == family}
        family_cases = tuple(case for case in cases if case.variant.check_id in checks)
        families.append(
            FamilyResults(
                family=family,
                requested_checks=len(checks),
                generated_checks=len({case.variant.check_id for case in family_cases}),
                attacks=_counts(family_cases, "attack"),
                controls=_counts(family_cases, "control"),
            )
        )
    evaluators = tuple(item for item in view.observations if item.actor != "target")
    actors = []
    for actor in dict.fromkeys(item.actor for item in evaluators):
        items = tuple(item for item in evaluators if item.actor == actor)
        statuses = Counter(item.status for item in items)
        actors.append(
            ActorResults(
                actor=actor,
                success=statuses["success"],
                transport_error=statuses["transport_error"],
                unknown=statuses["unknown"],
                usage=_usage(items),
            )
        )
    return RunResults(
        run_id=view.snapshot.id,
        captured_at=view.captured_at,
        state=view.state,
        partial=view.state != "completed",
        requested_checks=len(view.snapshot.checks),
        generated_checks=sum(family.generated_checks for family in families),
        families=tuple(families),
        attacks=_total([f.attacks for f in families], AttackCounts),
        controls=_total([f.controls for f in families], ControlCounts),
        target_usage=_usage(tuple(item for item in view.observations if item.actor == "target")),
        evaluator_usage=_usage(evaluators),
        evaluators=tuple(actors),
        stage_attempts=view.attempts,
    )


def assess_runs(views: tuple[RunView, ...]) -> Comparison:
    summaries = tuple(summarize_run(view) for view in views)
    baseline = views[0].snapshot
    differences = []
    checks_compatible = True
    for view in views[1:]:
        snapshot = view.snapshot
        prefix = str(snapshot.id)
        if {c.id: c for c in baseline.checks} != {c.id: c for c in snapshot.checks}:
            checks_compatible = False
            differences.append(f"{prefix}: checks")
        if tuple(c.id for c in baseline.checks) != tuple(c.id for c in snapshot.checks):
            differences.append(f"{prefix}: check_order")
        if baseline.evaluator != snapshot.evaluator:
            differences.append(f"{prefix}: evaluator")
        if {p.role: p for p in baseline.prompts} != {p.role: p for p in snapshot.prompts}:
            differences.append(f"{prefix}: prompts")
        if baseline.profile.limits != snapshot.profile.limits:
            differences.append(f"{prefix}: limits")
        left = baseline.profile.target.model_dump(exclude={"name", "model"})
        right = snapshot.profile.target.model_dump(exclude={"name", "model"})
        if left != right:
            differences.append(f"{prefix}: target_config")
        if baseline.profile.target.model != snapshot.profile.target.model:
            differences.append(f"{prefix}: target_model")
    relation = "same_pinned_settings"
    if differences:
        relation = (
            "cross_model"
            if all(difference.endswith(": target_model") for difference in differences)
            else "incompatible"
        )
    return Comparison(
        runs=views,
        summaries=summaries,
        assessment=ComparisonAssessment(
            relation=relation,
            checks_compatible=checks_compatible,
            differences=tuple(differences),
        ),
    )


def finding_detail(view: RunView, finding_id: UUID) -> FindingDetail:
    cases = _cases(view)
    case = next((case for case in cases if case.finding and case.finding.id == finding_id), None)
    if case is None:
        raise AppError("results_corrupt", "Finding identity does not match saved run evidence.")
    return FindingDetail(
        **case.finding.model_dump(),
        captured_at=view.captured_at,
        snapshot=view.snapshot,
        state=view.state,
        variant=case.variant,
        observation=case.observation,
        judgment=case.judgment,
        check=next(check for check in view.snapshot.checks if check.id == case.variant.check_id),
        stage_attempts=tuple(
            item for item in view.attempts if item.work_item_id == case.variant.id
        ),
    )
