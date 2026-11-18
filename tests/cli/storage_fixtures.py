import asyncio
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from asclepius.domain import (
    ROLES,
    ChatInput,
    ChatOutput,
    CheckDefinition,
    EvaluatorConfig,
    GenerationOutput,
    Message,
    Observation,
    OperationRequest,
    ProfileConfig,
    PromptSnapshot,
    RunSnapshot,
    TargetConfig,
    Variant,
)
from asclepius.maintenance import instance_lock, readiness_lock
from asclepius.storage import Repository

OWNER = "00000000-0000-4000-8000-000000000001"
REPLACEMENT = "00000000-0000-4000-8000-000000000002"
_leases: dict[Path, ExitStack] = {}


def release_leases():
    for lease in tuple(_leases.values()):
        lease.close()
    _leases.clear()


async def ready(repo, owner=OWNER, **kwargs):
    lease = _leases.pop(repo.data_dir, None)
    if lease is not None:
        lease.close()
    stack = ExitStack()
    try:
        stack.enter_context(instance_lock(repo.data_dir))
        stack.enter_context(readiness_lock(repo.data_dir, owner))
        _leases[repo.data_dir] = stack
        control = await repo.control()
        if str(control.instance_id) == owner:
            await repo.heartbeat(owner)
        else:
            await repo.set_ready(owner, **kwargs)
    except BaseException:
        stack.close()
        _leases.pop(repo.data_dir, None)
        raise


def make_snapshot(profile_id: str, profile: ProfileConfig) -> RunSnapshot:
    return RunSnapshot(
        profile_id=UUID(profile_id),
        profile=profile,
        evaluator=EvaluatorConfig.model_validate(
            {"roles": {role: {"model": "evaluator", "secret_ref": "env:KEY"} for role in ROLES}}
        ),
        checks=(
            CheckDefinition(
                id="test.check",
                version="1",
                family="test",
                objective="Protect a synthetic boundary",
                system_prompt="Protect it",
                strategies=("override", "role-play", "quoted-instructions"),
                benign_control="hello",
                rubric="Require observed evidence",
                evidence_criteria="Quote the reply",
                severity_rule="fixed_on_evidenced_weakness",
            ),
        ),
    )


async def prepare(data_dir: Path, claim: bool = True, **kwargs):
    repo = Repository(data_dir, **kwargs)
    lease = _leases.pop(repo.data_dir, None)
    if lease is not None:
        lease.close()
    await repo.initialize()
    profile = ProfileConfig(
        target=TargetConfig(name=f"test-{uuid4().hex[:8]}", model="target", secret_ref="env:KEY")
    )
    profile_id = await repo.save_profile(profile)
    snapshot = make_snapshot(profile_id, profile)
    await ready(repo)
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


async def observed_variant(repo, snapshot):
    variant = Variant(
        check_id="test.check",
        check_version="1",
        kind="attack",
        strategy="override",
        payload=ChatInput(messages=(Message(role="user", content="hello"),)),
    )
    variant_id = variant.id
    generator_work = str(uuid4())
    await repo.register_work_item(str(snapshot.id), generator_work, "test.check", instance_id=OWNER)
    await repo.commit_stage(
        str(snapshot.id),
        generator_work,
        "generator",
        GenerationOutput(variants=(variant,)),
        instance_id=OWNER,
    )
    request = OperationRequest(
        run_id=snapshot.id,
        work_item_id=variant_id,
        payload=ChatInput(messages=(Message(role="user", content="hello"),)),
    )
    intent = await repo.begin_operation(request, instance_id=OWNER)
    assert intent.operation_id == request.id
    assert intent.created is True
    observation = Observation(
        operation_id=request.id,
        run_id=snapshot.id,
        work_item_id=variant_id,
        status="success",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        payload=ChatOutput(content="synthetic reply"),
    )
    await repo.save_observation(observation, instance_id=OWNER)
    return request, observation


def prompts():
    return tuple(
        PromptSnapshot(role=role, version="test-v1", content=f"Test {role} contract")
        for role in ROLES
    )
