import os
from uuid import uuid4

from pydantic import ValidationError

from asclepius.checks import require_executable
from asclepius.domain import (
    ROLES,
    AppError,
    CheckDefinition,
    EvaluatorConfig,
    ProfileConfig,
    PromptSnapshot,
    RunSnapshot,
    RunState,
    SubmissionPlan,
)
from asclepius.storage import Repository
from asclepius.transport import valid_secret


def validate_credentials(profile: ProfileConfig, evaluator: EvaluatorConfig) -> None:
    references = {profile.target.secret_ref}
    references.update(
        role.secret_ref for role in (getattr(evaluator.roles, name) for name in ROLES)
    )
    values = [os.environ.get(reference[4:], "") for reference in references if reference]
    if any(not value.strip() for value in values):
        raise AppError(
            "credentials_missing",
            "A required credential is missing. Set the configured environment references "
            "before submitting and starting the daemon.",
            2,
        )
    if not all(valid_secret(value) for value in values):
        raise AppError(
            "secret_invalid",
            "A configured credential has spaces, line breaks or non-ASCII characters.",
            2,
        )


def validate_checks(profile: ProfileConfig, checks: tuple[CheckDefinition, ...]) -> None:
    available = set(profile.target.capabilities)
    if not checks or any(not set(check.capabilities) <= available for check in checks):
        raise AppError("unsupported_check", "The target does not support every requested check.", 2)
    if len({check.id for check in checks}) != len(checks):
        raise AppError("invalid_plan", "Requested check identities must be unique.", 2)
    for check in checks:
        require_executable(check)


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
