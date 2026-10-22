import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from asclepius.domain import (
    CheckDefinition,
    EvaluatorConfig,
    ProfileConfig,
    RunSnapshot,
    TargetConfig,
)
from asclepius.storage import Repository

OWNER = "test-owner"


def make_snapshot(profile_id: str, profile: ProfileConfig) -> RunSnapshot:
    return RunSnapshot(
        profile_id=UUID(profile_id),
        profile=profile,
        evaluator=EvaluatorConfig.model_validate(
            {
                "roles": {
                    role: {"model": "evaluator", "secret_ref": "env:KEY"}
                    for role in ("selector", "generator", "judge", "reporter")
                }
            }
        ),
        checks=(
            CheckDefinition(
                id="test.check",
                version="1",
                family="test",
                objective="Protect a synthetic boundary",
                system_prompt="Protect it",
                strategies=("override",),
                benign_control="hello",
                rubric="Require observed evidence",
            ),
        ),
    )


async def prepare(data_dir: Path, claim: bool = True, **kwargs):
    repo = Repository(data_dir, **kwargs)
    await repo.initialize()
    profile = ProfileConfig(
        target=TargetConfig(name=f"test-{uuid4().hex[:8]}", model="target", secret_ref="env:KEY")
    )
    profile_id = await repo.save_profile(profile)
    snapshot = make_snapshot(profile_id, profile)
    await repo.set_ready(OWNER)
    assert await repo.enqueue(snapshot) == str(snapshot.id)
    if claim:
        claimed = await repo.claim_next(OWNER)
        assert claimed.id == snapshot.id
    work_id = str(uuid4())
    if claim:
        await repo.register_work_item(str(snapshot.id), work_id, "test.check", instance_id=OWNER)
    return repo, snapshot, work_id


def run(awaitable):
    return asyncio.run(awaitable)
