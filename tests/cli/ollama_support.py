from uuid import uuid4

from asclepius.adapters.chat import GroqConnection
from asclepius.domain import (
    EvaluatorConfig,
    ProfileConfig,
    PromptSnapshot,
    TargetConfig,
)
from asclepius.limits import BudgetManager
from asclepius.storage import Repository
from asclepius.transport import JsonTransport
from tests.cli.storage_fixtures import OWNER, make_snapshot, ready


async def setup(server, tmp_path, monkeypatch, *, base_url=None, **limits):
    monkeypatch.setenv("EVALUATOR_KEY", "evaluator-secret-456")
    monkeypatch.delenv("TARGET_KEY", raising=False)
    repo = Repository(tmp_path)
    await repo.initialize()
    profile = ProfileConfig(
        target=TargetConfig(
            name="local",
            adapter="ollama-chat",
            model="llama3.2:1b",
            base_url=base_url or server.origin,
            system_prompt="Profile policy",
            temperature=0.2,
            max_completion_tokens=64,
        ),
        limits={"requests_per_minute": 100, "request_timeout_seconds": 10, **limits},
    )
    profile_id = await repo.save_profile(profile)
    snapshot = make_snapshot(profile_id, profile).model_copy(
        update={
            "evaluator": EvaluatorConfig.model_validate(
                {
                    "roles": {
                        role: {"model": role + "-model", "secret_ref": "env:EVALUATOR_KEY"}
                        for role in ("selector", "generator", "judge", "reporter")
                    }
                }
            ),
            "prompts": tuple(
                PromptSnapshot(role=role, version="1", content=role + " policy")
                for role in ("selector", "generator", "judge", "reporter")
            ),
        }
    )
    await ready(repo)
    await repo.enqueue(snapshot)
    await repo.claim_next(OWNER)
    work_id = uuid4()
    await repo.register_work_item(str(snapshot.id), str(work_id), "test.check", instance_id=OWNER)
    budgets = BudgetManager(repo, OWNER, limits=profile.limits)
    connection = GroqConnection(snapshot, budgets, transport=JsonTransport())
    return repo, snapshot, work_id, connection
