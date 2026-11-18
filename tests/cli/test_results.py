import json
import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from asclepius.domain import (
    AppError,
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
from asclepius.results import assess_runs, compare_runs, finding_detail, summarize_run
from asclepius.storage import Repository
from tests.cli.storage_fixtures import make_snapshot, prepare, run
from tests.cli.test_cli_help import run_cli

HOSTILE = "<script>alert(1)</script>\n\n[click](https://evil.invalid)\n```\n# injected\n\x1b]8;;https://evil.invalid\x07x\x1b]8;;\x07\u202e"


def test_report_public_cli_writes_zero_generated_summary(tmp_path):
    store = tmp_path / "store"
    _, snapshot, _ = run(prepare(store, claim=False))
    destination = tmp_path / "report.json"
    result = run_cli(
        "--data-dir",
        str(store),
        "report",
        str(snapshot.id),
        "--format",
        "json",
        "--output",
        str(destination),
        "--json",
    )
    assert result.returncode == 0, result.stdout
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["report_schema_version"] == 1
    assert document["summaries"][0]["attacks"]["generated"] == 0
    assert document["summaries"][0]["planned_cases"] is None
    assert document["summaries"][0]["families"][0]["requested_checks"] == 1


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


def test_delivery_judgments_controls_and_unknown_usage_are_independent():
    summary = summarize_run(evidence_view())
    assert summary.attacks.model_dump() == {
        "generated": 6,
        "judged": 3,
        "weakness": 1,
        "passed": 1,
        "inconclusive": 1,
        "verdict_unknown": 0,
        "missing_judgment": 3,
        "findings": 0,
        "delivery": {"success": 3, "transport_error": 1, "unknown": 1, "unobserved": 1},
    }
    assert summary.controls.model_dump() == {
        "generated": 3,
        "judged": 3,
        "answered": 1,
        "over_refusal": 1,
        "inconclusive": 0,
        "outcome_unknown": 1,
        "missing_judgment": 0,
        "findings": 0,
        "delivery": {"success": 3, "transport_error": 0, "unknown": 0, "unobserved": 0},
    }
    assert summary.target_usage.model_dump() == {
        "observations": 8,
        "input_measured": 6,
        "output_measured": 0,
        "input_tokens": 30,
        "output_tokens": None,
        "truncated": 1,
        "redacted": 1,
        "raw_bytes_measured": 6,
        "raw_content_bytes": 600,
    }
    assert summary.evaluator_usage.observations == 1
    assert summary.evaluators[0].transport_error == 1
    assert summary.families[1].requested_checks == 1
    assert summary.families[1].attacks.generated == 0
    assert summary.generated_checks == 1
    assert summary.partial is True
    assert summary.stage_attempts[0].error_code == "provider_http_503"


def test_summary_without_reporter_finding_or_capture_time():
    summary = summarize_run(evidence_view())
    assert summary.attacks.weakness == 1
    assert summary.attacks.findings == 0
    assert summary.captured_at is None
    assert summary.planned_cases is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: {"variants": (*v.variants, v.variants[0])},
        lambda v: {"observations": (*v.observations, v.observations[0])},
        lambda v: {"judgments": (*v.judgments, v.judgments[0])},
        lambda v: {"variants": v.variants[1:]},
        lambda v: {"judgments": (v.judgments[0].model_copy(update={"check_version": "wrong"}),)},
        lambda v: {"observations": (v.observations[0].model_copy(update={"run_id": uuid4()}),)},
        lambda v: {
            "snapshot": v.snapshot.model_copy(update={"checks": (v.snapshot.checks[0],) * 2})
        },
    ],
)
def test_impossible_or_duplicate_lineage_is_an_actionable_error(mutation):
    view = evidence_view()
    with pytest.raises(AppError) as error:
        summarize_run(view.model_copy(update=mutation(view)))
    assert error.value.code == "results_corrupt"


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


def test_comparison_public_counts_and_conservative_relations():
    view = evidence_view()
    comparison = assess_runs((view, alternate(view, profile_id=uuid4())))
    assert comparison.assessment.relation == "same_pinned_settings"
    assert comparison.compatible is True
    assert comparison.summaries[0].attacks.generated == 6
    assert comparison.summaries[1].attacks.generated == 0
    assert comparison.assessment.remote_revision == "unknown"
    assert comparison.assessment.generated_input_matching == "not_established"
    changed = alternate(
        view,
        profile=view.snapshot.profile.model_copy(
            update={
                "target": view.snapshot.profile.target.model_copy(
                    update={"model": "other", "name": "renamed"}
                )
            }
        ),
    )
    assert assess_runs((view, changed)).assessment.relation == "cross_model"
    assert assess_runs((view, changed)).compatible is False
    reversed_checks = alternate(view, checks=tuple(reversed(view.snapshot.checks)))
    comparison = assess_runs((view, reversed_checks))
    assert comparison.assessment.checks_compatible is True
    assert comparison.assessment.relation == "incompatible"
    assert comparison.differences == (f"{reversed_checks.snapshot.id}: check_order",)
    with pytest.raises(ValidationError, match="order and identities"):
        type(comparison)(
            runs=comparison.runs,
            summaries=tuple(reversed(comparison.summaries)),
            assessment=comparison.assessment,
        )


@pytest.mark.parametrize("change", ["rubric", "prompts", "evaluator", "limits", "endpoint"])
def test_comparison_checks_complete_execution_settings(change):
    view = evidence_view()
    snapshot = view.snapshot
    if change == "rubric":
        changed = alternate(
            view,
            checks=(
                snapshot.checks[0].model_copy(update={"rubric": "different"}),
                *snapshot.checks[1:],
            ),
        )
    elif change == "prompts":
        from asclepius.domain import PromptSnapshot

        changed = alternate(
            view, prompts=(PromptSnapshot(role="judge", version="1", content="changed"),)
        )
    elif change == "evaluator":
        roles = snapshot.evaluator.roles
        changed = alternate(
            view,
            evaluator=snapshot.evaluator.model_copy(
                update={
                    "roles": roles.model_copy(
                        update={"judge": roles.judge.model_copy(update={"temperature": 1.0})}
                    )
                }
            ),
        )
    elif change == "limits":
        changed = alternate(
            view,
            profile=snapshot.profile.model_copy(
                update={"limits": snapshot.profile.limits.model_copy(update={"target_calls": 3})}
            ),
        )
    else:
        changed = alternate(
            view,
            profile=snapshot.profile.model_copy(
                update={
                    "target": snapshot.profile.target.model_copy(
                        update={"base_url": "https://different.invalid"}
                    )
                }
            ),
        )
    comparison = assess_runs((view, changed))
    assert comparison.assessment.relation == "incompatible"
    assert comparison.assessment.checks_compatible == (change != "rubric")


def test_coherent_read_preserves_order_and_old_view_equality(tmp_path):
    async def scenario():
        repo, first, _ = await prepare(tmp_path, claim=False)
        second = first.model_copy(update={"id": uuid4()})
        await repo.enqueue(second)
        before = await repo.read_run(str(first.id))
        views = await repo.read_runs([str(second.id).upper(), str(first.id)])
        assert [view.snapshot.id for view in views] == [second.id, first.id]
        assert views[0].captured_at is not None
        assert views[0].captured_at == views[1].captured_at
        assert await repo.read_run(str(first.id)) == before
        for identities, code in (
            ([str(first.id), str(first.id).upper()], "arguments"),
            ([str(first.id), str(uuid4())], "not_found"),
            (["bad"], "arguments"),
        ):
            with pytest.raises(AppError) as error:
                await repo.read_runs(identities)
            assert error.value.code == code
        comparison = await compare_runs(repo, [str(first.id), str(second.id)])
        assert [s.attacks.generated for s in comparison.summaries] == [0, 0]

    run(scenario())


def test_multiread_retains_sqlite_snapshot_while_writer_commits(tmp_path):
    repo, first, _ = run(prepare(tmp_path, claim=False))
    second = first.model_copy(update={"id": uuid4()})
    run(repo.enqueue(second))
    entered = threading.Event()
    committed = threading.Event()
    failure = []

    class PausingReader(Repository):
        @staticmethod
        def _view(connection, row):
            view = Repository._view(connection, row)
            if view.snapshot.id == first.id:
                entered.set()
                assert committed.wait(5)
            return view

    def writer():
        try:
            assert entered.wait(5)
            run(repo.request_cancel(str(second.id)))
        except BaseException as error:
            failure.append(error)
        finally:
            committed.set()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        views = run(PausingReader(tmp_path).read_runs([str(first.id), str(second.id)]))
    finally:
        thread.join(5)
    assert not thread.is_alive()
    assert failure == []
    assert [view.state.value for view in views] == ["queued", "queued"]
    assert run(repo.read_run(str(second.id))).state.value == "cancelled"


def test_finding_detail_adds_lineage_without_moving_original_fields():
    view = evidence_view()
    finding = Finding(
        run_id=view.snapshot.id,
        variant_id=view.variants[0].id,
        judgment_id=view.judgments[0].id,
        severity="high",
        description="weakness",
        reproduction="reproduce",
        recommendation="fix",
        evidence=view.judgments[0].evidence,
    )
    view = view.model_copy(update={"findings": (finding,), "captured_at": datetime.now(UTC)})
    detail = finding_detail(view, finding.id)
    assert detail.model_dump(include=set(Finding.model_fields)) == finding.model_dump()
    assert detail.variant.id == finding.variant_id
    assert detail.observation.payload.content == "reply 0"
    assert detail.judgment.security_verdict == "weakness"
    assert detail.check.id == "test.check"
    assert summarize_run(view).attacks.findings == 1


def test_public_compare_reports_counts_and_rejects_missing_or_duplicate_ids(tmp_path):
    repo, first, _ = run(prepare(tmp_path, claim=False))
    second = first.model_copy(update={"id": uuid4()})
    run(repo.enqueue(second))
    result = run_cli(
        "--data-dir", str(tmp_path), "compare", str(second.id), str(first.id), "--json"
    )
    assert result.returncode == 0, result.stdout
    comparison = json.loads(result.stdout)["data"]
    assert [item["run_id"] for item in comparison["summaries"]] == [str(second.id), str(first.id)]
    assert comparison["summaries"][0]["attacks"]["generated"] == 0
    assert comparison["assessment"]["relation"] == "same_pinned_settings"
    for identities, expected in (
        ([str(first.id), str(first.id).upper()], "arguments"),
        ([str(first.id), str(uuid4())], "not_found"),
    ):
        failed = run_cli("--data-dir", str(tmp_path), "compare", *identities, "--json")
        assert json.loads(failed.stdout)["error"]["code"] == expected
        assert failed.returncode == (2 if expected == "arguments" else 3)


def test_coherent_finding_detail_and_uuid_cursor_pages(tmp_path):
    from asclepius.domain import FindingOutput, JudgmentOutput
    from tests.cli.storage_fixtures import OWNER
    from tests.cli.test_storage import observed_variant

    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        findings = []
        for index in range(3):
            request, observation = await observed_variant(repo, snapshot)
            evidence = (EvidenceRef(observation_id=observation.id, quote="synthetic reply"),)
            judgment = Judgment(
                variant_id=request.work_item_id,
                check_id="test.check",
                check_version="1",
                rubric_version="1",
                security_verdict="weakness",
                evidence=evidence,
                rationale="saved",
            )
            await repo.commit_stage(
                str(snapshot.id),
                str(request.work_item_id),
                "judge",
                JudgmentOutput(judgment=judgment),
                instance_id=OWNER,
            )
            finding = Finding(
                run_id=snapshot.id,
                variant_id=request.work_item_id,
                judgment_id=judgment.id,
                severity="low",
                description=f"finding {index}",
                reproduction="input",
                recommendation="boundary",
                evidence=evidence,
            )
            await repo.commit_stage(
                str(snapshot.id),
                str(request.work_item_id),
                "reporter",
                FindingOutput(finding=finding),
                instance_id=OWNER,
            )
            findings.append(finding)
        page = await repo.list_findings(str(snapshot.id), limit=2)
        tail = await repo.list_findings(str(snapshot.id), limit=2, cursor=page.next_cursor)
        assert [f.id for f in (*page.items, *tail.items)] == sorted(f.id for f in findings)
        assert tail.next_cursor is None
        detail = await repo.read_finding_detail(str(findings[0].id).upper())
        assert detail.description == "finding 0"
        assert detail.captured_at is not None
        assert detail.observation.id == detail.evidence[0].observation_id
        assert await repo.read_finding(str(findings[0].id)) == findings[0]
        return findings[0]

    finding = run(scenario())
    result = run_cli("--data-dir", str(tmp_path), "findings", "show", str(finding.id), "--json")
    assert result.returncode == 0, result.stdout
    detail = json.loads(result.stdout)["data"]
    assert detail["description"] == "finding 0"
    assert detail["variant"]["id"] == str(finding.variant_id)
    assert detail["variant"]["payload"]["messages"][0]["content"] == "hello"
    source = run(Repository(tmp_path).read_run(str(finding.run_id)))
    assert source.captured_at is None
    assert run(Repository(tmp_path).read_run(str(finding.run_id))) == source
    summary = summarize_run(source)
    assert summary.attacks.generated == 3
    assert summary.attacks.weakness == summary.attacks.findings == 3
    assert summary.controls.generated == 0
    destination = tmp_path / "saved.json"
    report = run_cli(
        "--data-dir",
        str(tmp_path),
        "report",
        str(finding.run_id),
        "--format",
        "json",
        "--output",
        str(destination),
        "--json",
    )
    assert report.returncode == 0, report.stdout
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["summaries"][0]["attacks"]["findings"] == 3
    assert len(document["runs"][0]["variants"]) == 3
    with pytest.raises(AppError) as error:
        summarize_run(source.model_copy(update={"variants": source.variants[1:]}))
    assert error.value.code == "results_corrupt"
