import sqlite3
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from asclepius.adapters.chat import GroqConnection
from asclepius.domain import (
    ROLES,
    ChatInput,
    EvaluatorConfig,
    GenerationOutput,
    Message,
    OperationRequest,
    ProfileConfig,
    PromptSnapshot,
    TargetConfig,
    Variant,
)
from asclepius.limits import BudgetManager
from asclepius.models import ModelGateway
from asclepius.storage import Repository
from tests.cli.storage_fixtures import OWNER, make_snapshot, ready


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verdict: str
    score: int


def reply(content="hello", finish="stop", **message):
    return {
        "id": "response-1",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content, **message},
            }
        ],
        "usage": {"prompt_tokens": 13, "completion_tokens": 7},
    }


async def setup(groq, tmp_path, monkeypatch, *, variant=False, **limits):
    server, transport = groq
    monkeypatch.setenv("TARGET_KEY", "target-secret-123")
    monkeypatch.setenv("EVALUATOR_KEY", "evaluator-secret-456")
    repo = Repository(tmp_path)
    await repo.initialize()
    profile = ProfileConfig(
        target=TargetConfig(
            name="test",
            model="target-model",
            secret_ref="env:TARGET_KEY",
            base_url=server.origin + "/target",
            system_prompt="Profile policy",
        ),
        limits={"requests_per_minute": 100, "request_timeout_seconds": 10, **limits},
    )
    profile_id = await repo.save_profile(profile)
    snapshot = make_snapshot(profile_id, profile).model_copy(
        update={
            "evaluator": EvaluatorConfig.model_validate(
                {
                    "roles": {
                        role: {
                            "model": role + "-model",
                            "secret_ref": "env:EVALUATOR_KEY",
                            "base_url": server.origin + "/evaluator",
                        }
                        for role in ROLES
                    }
                }
            ),
            "prompts": tuple(
                PromptSnapshot(role=role, version="1", content=role + " policy") for role in ROLES
            ),
        }
    )
    await ready(repo)
    await repo.enqueue(snapshot)
    await repo.claim_next(OWNER)
    work_id = uuid4()
    if variant:
        generator_work = str(uuid4())
        await repo.register_work_item(
            str(snapshot.id), generator_work, "test.check", instance_id=OWNER
        )
        await repo.commit_stage(
            str(snapshot.id),
            generator_work,
            "generator",
            GenerationOutput(
                variants=(
                    Variant(
                        id=work_id,
                        check_id="test.check",
                        check_version="1",
                        kind="attack",
                        strategy="override",
                        payload=ChatInput(messages=(Message(role="user", content="hello"),)),
                    ),
                )
            ),
            instance_id=OWNER,
        )
    else:
        await repo.register_work_item(
            str(snapshot.id), str(work_id), "test.check", instance_id=OWNER
        )
    budgets = BudgetManager(repo, OWNER, limits=profile.limits)
    connection = GroqConnection(snapshot, budgets, transport=transport)
    gateway = ModelGateway(connection, work_item_id=work_id)
    return repo, snapshot, work_id, connection, gateway


def request(snapshot, work_id, text="synthetic-canary"):
    return OperationRequest(
        run_id=snapshot.id,
        work_item_id=work_id,
        payload=ChatInput(messages=(Message(role="user", content=text),)),
    )


def prepare_target(connection, work_id, text="synthetic-canary"):
    payload = ChatInput(messages=(Message(role="user", content=text),))
    return connection.prepare_target(work_id, payload)


async def execute_target(connection, work_id, text="synthetic-canary"):
    return await connection.execute(prepare_target(connection, work_id, text))


def reservations(repo):
    with sqlite3.connect(repo.database_path) as connection:
        return connection.execute(
            "SELECT kind, state, max_output FROM budget_reservations ORDER BY rowid"
        ).fetchall()
