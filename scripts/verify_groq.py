import asyncio
import json
import os
import sqlite3
import ssl
import sys
import tempfile
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import localhost_tls
from pydantic import BaseModel, ConfigDict

import asclepius
from asclepius.adapters import chat
from asclepius.adapters.chat import GroqConnection
from asclepius.domain import (
    ROLES,
    ChatInput,
    CheckDefinition,
    EvaluatorConfig,
    Message,
    ProfileConfig,
    PromptSnapshot,
    RunSnapshot,
    TargetConfig,
)
from asclepius.exports import render_report
from asclepius.limits import BudgetManager
from asclepius.maintenance import instance_lock, readiness_lock
from asclepius.models import ModelGateway
from asclepius.storage import Repository
from asclepius.transport import JsonTransport


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verdict: str


class Provider(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append((self.path, self.headers["Authorization"], body))
        content = '{"verdict":"pass"}' if "response_format" in body else "synthetic-canary"
        response = json.dumps(
            {
                "id": "loopback-proof",
                "model": (
                    "evaluator-reported-proof"
                    if "response_format" in body
                    else "target-reported-proof"
                ),
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


async def prove(data_dir, server, transport):
    repo = Repository(data_dir)
    await repo.initialize()
    endpoint = f"https://127.0.0.1:{server.server_port}"
    profile = ProfileConfig(
        target=TargetConfig(
            name="installed-proof",
            model="target-proof",
            secret_ref="env:ASCL_PROBE_TARGET",
            base_url=endpoint + "/target",
        ),
    )
    profile_id = await repo.save_profile(profile)
    roles = ROLES
    snapshot = RunSnapshot(
        profile_id=profile_id,
        profile=profile,
        evaluator=EvaluatorConfig.model_validate(
            {
                "roles": {
                    role: {
                        "model": role + "-proof",
                        "secret_ref": "env:ASCL_PROBE_EVALUATOR",
                        "base_url": endpoint + "/evaluator",
                    }
                    for role in roles
                }
            }
        ),
        checks=(
            CheckDefinition(
                id="proof",
                version="1",
                family="proof",
                objective="Check installed provider boundary",
                system_prompt="Protect a canary",
                strategies=("probe",),
                benign_control="hello",
                rubric="Use observed evidence",
            ),
        ),
        prompts=tuple(
            PromptSnapshot(role=role, version="1", content=role + " policy") for role in roles
        ),
    )
    owner = str(uuid4())
    base = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    samples = iter(
        (
            base,
            base - timedelta(seconds=2),
            base + timedelta(minutes=1),
            base + timedelta(minutes=1, seconds=-2),
        )
    )

    class ReversedUTC:
        @staticmethod
        def now(_zone):
            return next(samples)

    with instance_lock(repo.data_dir), readiness_lock(repo.data_dir, owner):
        await repo.set_ready(owner)
        await repo.enqueue(snapshot)
        await repo.claim_next(owner)
        work = uuid4()
        await repo.register_work_item(str(snapshot.id), str(work), "proof", instance_id=owner)
        connection = GroqConnection(snapshot, BudgetManager(repo, owner), transport=transport)
        call = connection.prepare_target(
            work, ChatInput(messages=(Message(role="user", content="synthetic-canary"),))
        )
        assert (await repo.begin_operation(call.request, instance_id=owner)).created
        with patch.object(chat, "datetime", ReversedUTC):
            observation = await connection.execute(call)
        assert observation.status == "success"
        assert observation.payload.content == "synthetic-canary"
        await repo.save_observation(observation, instance_id=owner)
        gateway = ModelGateway(connection, work_item_id=work)
        evaluation = gateway.prepare("judge", {"observation": "synthetic-canary"}, Answer)
        assert (await repo.begin_operation(evaluation.call.request, instance_id=owner)).created
        with patch.object(chat, "datetime", ReversedUTC):
            result = await gateway.execute(evaluation)
        assert result.output == Answer(verdict="pass")
        await repo.save_observation(result.observation, instance_id=owner)
    view = await repo.read_run(str(snapshot.id))
    assert len(view.observations) == 2
    assert [(item.started_at, item.finished_at) for item in view.observations] == [
        (base, base - timedelta(seconds=2)),
        (base + timedelta(minutes=1), base + timedelta(minutes=1, seconds=-2)),
    ]
    identities = {item.actor: item.payload.provider_model for item in view.observations}
    assert identities == {"target": "target-reported-proof", "judge": "evaluator-reported-proof"}
    assert identities["target"] != snapshot.profile.target.model
    assert identities["judge"] != snapshot.evaluator.roles.judge.model
    for format in ("json", "markdown", "html"):
        artifact = render_report(view, format)
        for reported in identities.values():
            assert reported in artifact.content
        assert "provider_model" in artifact.content
        for item in view.observations:
            saved = item.model_dump(mode="json")
            assert saved["started_at"] in artifact.content
            assert saved["finished_at"] in artifact.content
    assert len(server.calls) == 2
    assert server.calls[0][0] == "/target/chat/completions"
    assert server.calls[1][0] == "/evaluator/chat/completions"
    assert server.calls[0][1] == "Bearer synthetic-target-key"
    assert server.calls[1][1] == "Bearer synthetic-evaluator-key"
    assert server.calls[0][2]["model"] == "target-proof"
    assert server.calls[1][2]["model"] == "judge-proof"
    with closing(sqlite3.connect(repo.database_path)) as database:
        assert database.execute("SELECT state FROM budget_reservations").fetchall() == [
            ("settled",),
            ("settled",),
        ]

    return identities, [
        (item.started_at.isoformat(), item.finished_at.isoformat()) for item in view.observations
    ]


def main():
    installed = Path(asclepius.__file__).resolve()
    assert "site-packages" in installed.parts, installed
    fixtures = localhost_tls.ensure(Path(sys.argv[1]).resolve())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server.calls = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(fixtures / "localhost-cert.pem", fixtures / "localhost-key.pem")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["ASCL_PROBE_TARGET"] = "synthetic-target-key"
    os.environ["ASCL_PROBE_EVALUATOR"] = "synthetic-evaluator-key"
    transport = JsonTransport(
        verify=ssl.create_default_context(cafile=str(fixtures / "localhost-cert.pem"))
    )
    try:
        with tempfile.TemporaryDirectory(prefix="asclepius-groq-proof-") as temporary:
            identities, reversed_samples = asyncio.run(prove(Path(temporary), server, transport))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    print(
        json.dumps(
            {
                "scope": "deterministic HTTPS components, storage and exports",
                "installed_import": str(installed),
                "provider_reported_models": identities,
                "verified_export_formats": ["json", "markdown", "html"],
                "loopback_https_requests": 2,
                "persisted_observations": 2,
                "validated_evaluator_output": True,
                "clock_reversal_verified": True,
                "clock_reversal_samples": reversed_samples,
                "live_groq": False,
            }
        )
    )


if __name__ == "__main__":
    main()
