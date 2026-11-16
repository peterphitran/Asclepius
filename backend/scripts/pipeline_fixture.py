import json
import os
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = "ASCLEPIUS_OFFLINE_FIXTURE_CREDENTIAL"
LIMITS = {
    "active_runs": 2,
    "requests_per_minute": 10000,
    "outbound_concurrency": 2,
    "target_concurrency": 2,
    "evaluator_concurrency": 2,
    "run_timeout_seconds": 180,
    "request_timeout_seconds": 10,
}


@dataclass(frozen=True)
class CliResult:
    returncode: int
    payload: dict


def isolated_python(*arguments, environment=None, interpreter=None, timeout=30):
    child_environment = dict(os.environ if environment is None else environment)
    child_environment.pop("PYTHONPATH", None)
    child_environment.pop("PYTHONHOME", None)
    return subprocess.run(
        [str(interpreter or sys.executable), "-I", *map(str, arguments)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=child_environment,
    )


def cli_result(directory, *arguments, environment=None):
    result = isolated_python(
        "-m",
        "asclepius",
        "--data-dir",
        directory,
        "--json",
        *arguments,
        environment=environment if environment is not None else dict(os.environ, PIPELINE_KEY=KEY),
    )
    assert KEY not in result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] == (result.returncode == 0), result.stdout + result.stderr
    return CliResult(result.returncode, payload)


def cli(directory, *arguments, environment=None):
    result = cli_result(directory, *arguments, environment=environment)
    assert result.returncode == 0, result.payload
    return result.payload["data"]


def wait_run(directory, identity, timeout=90):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = cli(directory, "runs", "show", identity)
        if result["state"] not in {"queued", "running"}:
            return result
        time.sleep(0.1)
    raise AssertionError("Run did not finish before fixture deadline")


class Provider(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, directory, certificate_dir, *, fault=None, delay=0):
        super().__init__(("127.0.0.1", 0), Handler)
        self.directory = directory
        self.fault = fault
        self.delay = delay
        self.calls = []
        self.preflights = []
        self.failures = []
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.running_max = 0
        self.release = threading.Event()
        self.received = threading.Event()
        self.release.set()
        self.gates = []
        self.permitted_disconnects = set()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            certificate_dir / "localhost-cert.pem", certificate_dir / "localhost-key.pem"
        )
        self.socket = context.wrap_socket(self.socket, server_side=True)
        self.origin = f"https://127.0.0.1:{self.server_port}"

    @contextmanager
    def gate(self, actor, operation_id=None):
        gate = ResponseGate(actor, operation_id)
        with self.lock:
            self.gates.append(gate)
        try:
            yield gate
        finally:
            gate.release.set()
            with self.lock:
                self.gates.remove(gate)

    def respond(self, body, *, on_receipt=None):
        if body.get("messages") in (
            [{"role": "user", "content": "Asclepius access preflight. Reply OK."}],
            [
                {
                    "role": "user",
                    "content": 'Asclepius access preflight. Reply with only {"ok":true}.',
                }
            ],
        ):
            self.preflights.append(body)
            if self.fault == "preflight_401":
                return 401, {"error": "fixture access denied"}
            return 200, {
                "id": "fixture-preflight-" + str(len(self.preflights)),
                "model": "fixture-reported-" + body["model"],
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"ok":true}' if "response_format" in body else "OK",
                        },
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }
        with closing(sqlite3.connect(self.directory / "asclepius.sqlite3")) as connection:
            candidates = connection.execute(
                "SELECT id,run_id,work_item_id,request_json FROM operations WHERE status='pending'"
            ).fetchall()
            matching = [
                item
                for item in candidates
                if json.loads(json.loads(item[3])["provider_body_json"]) == body
            ]
            assert len(matching) == 1, (
                "Received request lacked exactly one committed prepared intent"
            )
            operation, run, work, raw = matching[0]
            request = json.loads(raw)
            actor = request["actor"]
            variant_row = connection.execute(
                "SELECT variant_json FROM work_items WHERE run_id=? AND id=?", (run, work)
            ).fetchone()
            variant = json.loads(variant_row[0]) if variant_row and variant_row[0] else None
            if actor == "target":
                assert variant is not None, "Target input was not committed before receipt"
                assert body["messages"][-2:] == variant["payload"]["messages"]
            if actor == "judge":
                assert connection.execute(
                    "SELECT 1 FROM observations o JOIN operations p ON o.operation_id=p.id "
                    "WHERE p.run_id=? AND p.work_item_id=? "
                    "AND json_extract(p.request_json,'$.actor')='target'",
                    (run, work),
                ).fetchone(), "Judge began before target evidence commit"
            running = connection.execute(
                "SELECT count(*) FROM runs WHERE state='running'"
            ).fetchone()[0]
        with self.lock:
            self.running_max = max(self.running_max, running)
            self.calls.append(
                {
                    "operation_id": operation,
                    "run_id": run,
                    "work_item_id": work,
                    "actor": actor,
                    "body": body,
                    "variant": variant,
                }
            )
        if on_receipt is not None:
            on_receipt(operation)
        self.received.set()
        with self.lock:
            gates = [
                g
                for g in self.gates
                if g.actor == actor and (g.operation_id is None or g.operation_id == operation)
            ]
        for gate in gates:
            gate.received.set()
            assert gate.release.wait(25), "Selective response gate deadline expired"
        assert self.release.wait(20)
        time.sleep(self.delay)
        if (
            self.fault == "http"
            and actor == "target"
            and variant["kind"] == "attack"
            and variant["strategy"]
            and variant["payload"]["messages"][-1]["content"].endswith("attack-1")
        ):
            return 503, {"error": "fixture unavailable"}
        content, finish = self.proposal(actor, body, variant)
        if self.fault == "invalid" and actor == "generator":
            content = '{"attacks":[]}'
        return 200, {
            "id": "fixture-" + operation,
            "model": "fixture-reported-" + body.get("model", "unspecified"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish,
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }

    @staticmethod
    def proposal(actor, body, variant):
        if actor == "target":
            if variant["check_id"] == "priority.override" and variant["kind"] == "attack":
                text = variant["payload"]["messages"][-1]["content"]
                if text.endswith("attack-0"):
                    return "ASCL_PRIORITY_BREACH", "stop"
                if text.endswith("attack-1"):
                    return "Incomplete reply", "length"
            return '{"answer":"Boundary maintained"}', "stop"
        payload = json.loads(body["messages"][-1]["content"])
        if actor == "selector":
            output = {
                "selections": [
                    {
                        "check_id": item["check_id"],
                        "check_version": item["check_version"],
                        "strategy_number": 1,
                        "rationale": "Exercise pinned cases",
                    }
                    for item in payload["requested_checks"]
                ]
            }
        elif actor == "generator":
            check = payload["check"]
            output = {
                "attacks": [
                    {"strategy": strategy, "text": check["id"] + "-attack-" + str(index)}
                    for index, strategy in enumerate(check["strategies"])
                ]
            }
        elif actor == "judge":
            reply = payload["untrusted_target_reply"]
            verdict = (
                "weakness"
                if reply == "ASCL_PRIORITY_BREACH"
                else "inconclusive"
                if payload["evidence_incomplete"]
                else "pass"
            )
            output = {
                "verdict": verdict,
                "quotes": [reply],
                "rationale": "Assess exact recorded reply",
                "confidence": 1.0,
                "control_outcome": "answered" if payload["case_kind"] == "control" else None,
            }
        else:
            output = {
                "description": "Target followed conflicting instruction",
                "recommendation": "Preserve the configured boundary",
            }
        return json.dumps(output), "stop"


@dataclass
class ResponseGate:
    actor: str
    operation_id: str | None = None

    def __post_init__(self):
        self.received = threading.Event()
        self.release = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def record_operation(self, operation_id):
        self.operation_id = operation_id

    def do_POST(self):
        self.operation_id = None
        with self.server.lock:
            self.server.active += 1
            self.server.max_active = max(self.server.max_active, self.server.active)
        try:
            try:
                assert self.headers.get("Authorization") == "Bearer " + KEY
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status, reply = self.server.respond(body, on_receipt=self.record_operation)
            except Exception as error:
                self.server.failures.append(str(error))
                status, reply = 500, {"error": "fixture invariant failed"}
            data = json.dumps(reply).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLEOFError) as error:
                with self.server.lock:
                    if self.operation_id not in self.server.permitted_disconnects:
                        self.server.failures.append(
                            f"Unexpected peer disconnect for {self.operation_id}: {error}"
                        )
        finally:
            with self.server.lock:
                self.server.active -= 1


@contextmanager
def provider(directory, certificate_dir, **options):
    server = Provider(directory, certificate_dir, **options)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.release.set()
        for gate in server.gates:
            gate.release.set()
        server.shutdown()
        server.server_close()
        thread.join(5)


def configure(root, server, certificate_dir, *, aliases=("fixture",), daemon_key=True, limits=None):
    root.mkdir(parents=True, exist_ok=True)
    directory = root / "store"
    cli(directory, "init")
    policy = dict(LIMITS, **(limits or {}))
    config = root / "daemon.toml"
    config.write_text(
        "ca_bundle = "
        + json.dumps(str((certificate_dir / "localhost-cert.pem").resolve()))
        + "\n[limits]\n"
        + "\n".join(f"{key} = {value}" for key, value in policy.items()),
        encoding="utf-8",
    )
    paths = {}
    for alias in aliases:
        target = root / f"{alias}.toml"
        target.write_text(
            f'[target]\nname = "{alias}"\nmodel = "fixture-target"\n'
            'secret_ref = "env:PIPELINE_KEY"\n'
            f'base_url = "{server.origin}/target"\n'
            'system_prompt = "Frozen profile policy"\n[limits]\n'
            + "\n".join(f"{key} = {value}" for key, value in policy.items()),
            encoding="utf-8",
        )
        cli(directory, "targets", "add", alias, "--config", target)
        paths[alias] = target
    evaluator = root / "evaluator.toml"
    evaluator.write_text(
        "\n".join(
            f'[roles.{role}]\nmodel = "fixture-{role}"\nsecret_ref = "env:PIPELINE_KEY"\n'
            f'base_url = "{server.origin}/evaluator"\n'
            for role in ("selector", "generator", "judge", "reporter")
        ),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment.pop("PIPELINE_KEY", None)
    if daemon_key:
        environment["PIPELINE_KEY"] = KEY
    started = cli(directory, "daemon", "start", "--config", config, environment=environment)
    assert started["execution_available"] is True
    return directory, evaluator, paths, started


def assert_complete(view, calls):
    assert view["state"] == "completed", (view["reason"], view["progress"])
    assert len(view["variants"]) == 80
    assert len({item["id"] for item in view["variants"]}) == 80
    assert {item["check_id"] for item in view["variants"]} == {
        item["id"] for item in view["snapshot"]["checks"]
    }
    assert {item["check_version"] for item in view["variants"]} == {"1"}
    assert sum(item["kind"] == "control" for item in view["variants"]) == 20
    assert len(view["judgments"]) == 80
    assert {
        verdict: sum(item["security_verdict"] == verdict for item in view["judgments"])
        for verdict in ("weakness", "pass", "inconclusive")
    } == {"weakness": 1, "pass": 78, "inconclusive": 1}
    assert len(view["findings"]) == 1
    assert {
        role: sum(item["actor"] == role for item in calls)
        for role in ("target", "selector", "generator", "judge", "reporter")
    } == {"target": 80, "selector": 1, "generator": 20, "judge": 80, "reporter": 0}
    assert len(view["observations"]) == len(calls) == 181
    assert len({item["operation_id"] for item in calls}) == 181
    assert all(
        item["payload"]["response_id"] == "fixture-" + item["operation_id"]
        for item in view["observations"]
    )
    assert len(view["attempts"]) == 102
    assert all(
        item["state"] == "completed" and item["started_at"] is not None for item in view["attempts"]
    )
    assert view["progress"] == {
        "phase": "finished",
        "requested_checks": 20,
        "generated_checks": 20,
        "generated_cases": 80,
        "observed_targets": 80,
        "judgments": 80,
        "findings": 1,
        "generation_complete": True,
    }
