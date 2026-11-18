from datetime import UTC, datetime
from uuid import uuid4

from asclepius.domain import (
    ChatInput,
    ChatOutput,
    EvidenceRef,
    Finding,
    Judgment,
    Message,
    Observation,
    ProfileConfig,
    RunView,
    StageAttempt,
    TargetConfig,
    TokenUsage,
    Variant,
)
from tests.cli.storage_fixtures import make_snapshot

HOSTILE = "<script>alert(1)</script>\n\n[click](https://evil.invalid)\n```\n# injected\n\x1b]8;;https://evil.invalid\x07x\x1b]8;;\x07\u202e"


def evidence_view():
    profile = ProfileConfig(
        target=TargetConfig(name="fixture", model="model", secret_ref="env:KEY")
    )
    snapshot = make_snapshot(str(uuid4()), profile)
    extra = snapshot.checks[0].model_copy(update={"id": "unrun", "family": "unrun"})
    snapshot = snapshot.model_copy(update={"checks": (*snapshot.checks, extra)})
    variants = tuple(
        Variant(
            check_id="test.check",
            check_version="1",
            kind="control" if index >= 6 else "attack",
            payload=ChatInput(messages=(Message(role="user", content=f"case {index}"),)),
        )
        for index in range(9)
    )
    now = datetime.now(UTC)
    observations = []
    for index, variant in enumerate(variants):
        if index == 5:
            continue
        status = "transport_error" if index == 3 else "unknown" if index == 4 else "success"
        observations.append(
            Observation(
                operation_id=uuid4(),
                run_id=snapshot.id,
                work_item_id=variant.id,
                status=status,
                started_at=now,
                finished_at=now,
                error_code="provider_http_503" if index == 3 else None,
                truncated=index == 2,
                payload=ChatOutput(
                    content=f"reply {index}",
                    usage=TokenUsage(input_tokens=5),
                    raw_content_bytes=100,
                    content_redacted=index == 0,
                )
                if status == "success"
                else None,
            )
        )
    judgments = []
    for index in (0, 1, 2, 6, 7, 8):
        observation = next(item for item in observations if item.work_item_id == variants[index].id)
        judgments.append(
            Judgment(
                variant_id=variants[index].id,
                check_id="test.check",
                check_version="1",
                rubric_version="1",
                security_verdict=("weakness", "pass", "inconclusive")[index % 3],
                control_outcome=("answered", "over_refusal", None)[index % 3]
                if index >= 6
                else None,
                evidence=(
                    EvidenceRef(observation_id=observation.id, quote=observation.payload.content),
                ),
                rationale="Evidence",
            )
        )
    observations.append(
        Observation(
            operation_id=uuid4(),
            run_id=snapshot.id,
            work_item_id=uuid4(),
            actor="judge",
            status="transport_error",
            error_code="provider_http_503",
            started_at=now,
        )
    )
    return RunView(
        snapshot=snapshot,
        state="running",
        variants=variants,
        observations=tuple(observations),
        judgments=tuple(judgments),
        attempts=(
            StageAttempt(
                run_id=snapshot.id,
                work_item_id=variants[3].id,
                stage="judge",
                attempt=1,
                state="failed",
                error_code="provider_http_503",
            ),
        ),
    )


def alternate(view, **changes):
    return view.model_copy(
        update={
            "snapshot": view.snapshot.model_copy(update={"id": uuid4(), **changes}),
            "variants": (),
            "observations": (),
            "judgments": (),
            "attempts": (),
        }
    )


def hostile_view():
    view = evidence_view()
    check = view.snapshot.checks[0].model_copy(
        update={
            "family": HOSTILE,
            "objective": HOSTILE,
            "rubric": HOSTILE,
            "system_prompt": HOSTILE,
            "strategies": (HOSTILE,),
            "benign_control": HOSTILE,
        }
    )
    target = view.snapshot.profile.target.model_copy(
        update={"model": HOSTILE, "system_prompt": HOSTILE}
    )
    snapshot = view.snapshot.model_copy(
        update={
            "checks": (check, view.snapshot.checks[1]),
            "profile": view.snapshot.profile.model_copy(update={"target": target}),
        }
    )
    observation = view.observations[0]
    observation = observation.model_copy(
        update={"payload": observation.payload.model_copy(update={"content": HOSTILE})}
    )
    judgment = view.judgments[0].model_copy(
        update={
            "rationale": HOSTILE,
            "evidence": (view.judgments[0].evidence[0].model_copy(update={"quote": HOSTILE}),),
        }
    )
    finding = Finding(
        run_id=snapshot.id,
        variant_id=view.variants[0].id,
        judgment_id=judgment.id,
        severity="high",
        description=HOSTILE,
        reproduction=HOSTILE,
        recommendation=HOSTILE,
        evidence=judgment.evidence,
    )
    return view.model_copy(
        update={
            "snapshot": snapshot,
            "observations": (observation, *view.observations[1:]),
            "judgments": (judgment, *view.judgments[1:]),
            "findings": (finding,),
        }
    )
