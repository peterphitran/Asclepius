import os
from uuid import uuid4

from pydantic import ValidationError

from asclepius.domain import (
    AppError,
    CheckDefinition,
    EvaluatorConfig,
    ProfileConfig,
    PromptSnapshot,
    RunSnapshot,
    RunState,
    RunView,
    SubmissionPlan,
)
from asclepius.storage import Repository


def validate_credentials(profile: ProfileConfig, evaluator: EvaluatorConfig) -> None:
    references = {profile.target.secret_ref}
    references.update(
        role.secret_ref
        for role in (
            evaluator.roles.selector,
            evaluator.roles.generator,
            evaluator.roles.judge,
            evaluator.roles.reporter,
        )
    )
    if any(reference and not os.environ.get(reference[4:], "").strip() for reference in references):
        raise AppError(
            "credentials_missing",
            "A required credential is missing. Set the configured environment references "
            "before submitting and starting the daemon.",
            2,
        )


def validate_checks(profile: ProfileConfig, checks: tuple[CheckDefinition, ...]) -> None:
    available = set(profile.target.capabilities)
    if not checks or any(not set(check.capabilities) <= available for check in checks):
        raise AppError("unsupported_check", "The target does not support every requested check.", 2)
    if len({check.id for check in checks}) != len(checks):
        raise AppError("invalid_plan", "Requested check identities must be unique.", 2)


def submission_plan(
    checks: tuple[CheckDefinition, ...], prompts: tuple[PromptSnapshot, ...]
) -> SubmissionPlan:
    try:
        return SubmissionPlan(checks=checks, prompts=prompts)
    except ValidationError:
        raise AppError("invalid_plan", "A complete valid evaluation plan is required.", 2) from None


class EvaluationService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    async def save_profile(self, config: ProfileConfig, *, profile_id: str | None = None) -> str:
        return await self.repo.save_profile(config, profile_id=profile_id)

    async def submit(
        self,
        profile: str,
        evaluator: EvaluatorConfig,
        checks: tuple[CheckDefinition, ...],
        *,
        prompts: tuple[PromptSnapshot, ...],
    ) -> str:
        record = await self.repo.get_profile(profile)
        validate_checks(record.config, checks)
        plan = submission_plan(checks, prompts)
        validate_credentials(record.config, evaluator)
        snapshot = RunSnapshot(
            profile_id=record.id,
            profile=record.config,
            evaluator=evaluator,
            checks=plan.checks,
            prompts=plan.prompts,
        )
        return await self.repo.enqueue(snapshot)

    async def cancel(self, run_id: str) -> RunView:
        return await self.repo.request_cancel(run_id)

    async def retry(self, run_id: str) -> str:
        source = await self.repo.read_run(run_id)
        if source.state not in {RunState.FAILED, RunState.CANCELLED, RunState.INTERRUPTED}:
            raise AppError(
                "invalid_transition", "Retry requires a failed, cancelled, or interrupted run.", 2
            )
        await self.repo.get_profile(source.snapshot.profile_id)
        validate_checks(source.snapshot.profile, source.snapshot.checks)
        submission_plan(source.snapshot.checks, source.snapshot.prompts)
        validate_credentials(source.snapshot.profile, source.snapshot.evaluator)
        content = source.snapshot.model_dump(
            mode="json", exclude={"id", "created_at", "source_run_id"}
        )
        snapshot = RunSnapshot.model_validate(
            {**content, "id": str(uuid4()), "source_run_id": run_id}
        )
        return await self.repo.enqueue(snapshot)
