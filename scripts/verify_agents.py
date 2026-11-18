import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from asclepius.adapters.chat import GroqConnection
from asclepius.agents import AgentRunner
from asclepius.checks import load_pack_plan
from asclepius.domain import ROLES, ChatOutput, Observation
from asclepius.models import EvaluationResult
from asclepius.storage import Repository


def cli(directory: Path, *arguments: str):
    result = subprocess.run(
        [sys.executable, "-m", "asclepius", "--data-dir", str(directory), "--json", *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)["data"]


async def verify(root: Path):
    directory = root / "data"
    assert len(cli(directory, "checks", "list", "--pack", "broad-chat-v1")) == 20
    assert not directory.exists()
    cli(directory, "init")
    config = root / "target.toml"
    config.write_text('[target]\nname="proof"\nmodel="synthetic"\nsecret_ref="env:PROOF_KEY"\n')
    evaluator = root / "evaluator.toml"
    evaluator.write_text(
        "\n".join(
            f'[roles.{role}]\nmodel="synthetic"\nsecret_ref="env:PROOF_KEY"\n' for role in ROLES
        )
    )
    cli(directory, "targets", "add", "proof", "--config", str(config))
    repo = Repository(directory)
    await repo.set_ready("installed-proof")
    accepted = cli(
        directory, "run", "proof", "--pack", "broad-chat-v1", "--evaluator", str(evaluator)
    )
    view = await repo.read_run(accepted["id"])
    assert view.state == "queued"
    snapshot = view.snapshot
    plan = load_pack_plan("broad-chat-v1")
    assert snapshot.checks == plan.checks and snapshot.prompts == plan.prompts
    replies, calls = [], []

    async def dispatch(gateway, prepared):
        calls.append(prepared.call.request.actor)
        raw = json.dumps(replies.pop(0))
        request = prepared.call.request
        now = datetime.now(UTC)
        obs = Observation(
            operation_id=request.id,
            run_id=request.run_id,
            work_item_id=request.work_item_id,
            actor=request.actor,
            status="success",
            started_at=now,
            finished_at=now,
            request_payload=request.payload,
            payload=ChatOutput(content=raw),
        )
        return EvaluationResult(
            prepared.call, obs, prepared.output_type.model_validate_json(raw, strict=True)
        )

    runner = AgentRunner(
        GroqConnection(snapshot, SimpleNamespace(limits=snapshot.profile.limits)), dispatch=dispatch
    )
    replies.append(
        {
            "selections": [
                dict(
                    check_id=c.id,
                    check_version=c.version,
                    strategy_number=1,
                    rationale="Synthetic proof",
                )
                for c in snapshot.checks
            ]
        }
    )
    selections = await runner.select(snapshot)
    variants = []
    for selection, check in zip(selections, snapshot.checks, strict=True):
        replies.append(
            {"attacks": [dict(strategy=s, text="Synthetic attempt " + s) for s in check.strategies]}
        )
        variants.extend(await runner.generate(selection))
    assert len(variants) == 80
    check, variant = snapshot.checks[0], variants[0]
    now = datetime.now(UTC)
    target = Observation(
        operation_id=uuid4(),
        run_id=snapshot.id,
        work_item_id=variant.id,
        status="success",
        started_at=now,
        finished_at=now,
        request_payload=variant.payload,
        payload=ChatOutput(content="ASCL_PRIORITY_BREACH"),
    )
    replies.append(
        dict(
            verdict="weakness",
            quotes=["ASCL_PRIORITY_BREACH"],
            rationale="Recorded literal",
            confidence=1.0,
            control_outcome=None,
        )
    )
    judgment = await runner.judge(check, variant, target)
    finding = await runner.report(judgment, target)
    assert finding.evidence == judgment.evidence
    assert '"ASCL_PRIORITY_BREACH"' in finding.description
    assert calls == ["selector"] + ["generator"] * 20 + ["judge"]
    print("PASS: installed resources, public CLI listing and queued pack, 80 cases, four roles")


if __name__ == "__main__":
    os.environ["PROOF_KEY"] = "synthetic-installed-proof-key"
    with TemporaryDirectory() as directory:
        asyncio.run(verify(Path(directory)))
