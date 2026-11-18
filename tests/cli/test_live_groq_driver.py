import json
import os
from pathlib import Path

import pytest

from scripts.live_groq_fixture import run_workflow
from scripts.pipeline_fixture import KEY, provider
from tests.cli.live_groq_support import configurations

CERTIFICATES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("snapshot_path_changed", [False, True])
def test_full_two_trial_public_workflow(tmp_path, monkeypatch, snapshot_path_changed):
    artifacts = tmp_path / "evidence"
    import sys

    if snapshot_path_changed:
        import json
        import subprocess

        from scripts import live_groq_fixture
        from scripts.pipeline_fixture import isolated_python

        def changed_snapshot(*args, **kwargs):
            result = isolated_python(*args, **kwargs)
            if args[-3:-1] == ("runs", "show") and result.returncode == 0:
                payload = json.loads(result.stdout)
                if payload["data"]["state"] == "completed":
                    role = payload["data"]["snapshot"]["evaluator"]["roles"]["judge"]
                    role["base_url"] += "/changed"
                    return subprocess.CompletedProcess(args, 0, json.dumps(payload), result.stderr)
            return result

        monkeypatch.setattr(live_groq_fixture, "isolated_python", changed_snapshot)

    shadow = tmp_path / "shadow"
    (shadow / "asclepius").mkdir(parents=True)
    (shadow / "asclepius" / "__init__.py").write_text("raise RuntimeError('shadow import')")
    monkeypatch.chdir(shadow)
    monkeypatch.setenv("PYTHONPATH", str(shadow))
    with provider(artifacts / "store", CERTIFICATES) as server:
        target, evaluator = configurations(tmp_path, server.origin)
        result = run_workflow(
            target,
            evaluator,
            artifacts,
            environment=dict(os.environ, PIPELINE_KEY=KEY),
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
            interpreter=sys.executable,
        )
        if snapshot_path_changed:
            assert result["status"] == "failed"
            assert result["reason"] == "snapshot_provider_settings_changed"
            assert len(result["run_ids"]) == 1
            assert result["cleanup"] == [{"daemon_stopped": True}]
            return
        assert result["status"] == "succeeded", result.get("reason")
        assert result["scope"] == "controlled_protocol"
        assert result["live_groq"] is False
        assert result["manual_semantic_review"] == "pending"
        assert len(set(result["run_ids"])) == 2
        assert len(server.preflights) == 5
        assert len(server.calls) == 362
        assert server.failures == []
        assert result["cleanup"][-1] == {"daemon_stopped": True}
        assert result["durable_inspection"]["unchanged"] is True
        for trial in result["trials"]:
            assert trial["call_counts"]["target"] == 80
            assert trial["call_counts"]["judge"] == 80
            assert len(trial["review_samples"]) == 10
            assert trial["limits"]["total_calls"] == 300
        assert len(result["exports"]) == 3
        assert result["python"]["executable"] == sys.executable
        assert "shadow" not in result["python"]["import"]
        assert all(receipt["argv"][0:2] == [sys.executable, "-I"] for receipt in result["commands"])
        assert KEY not in (artifacts / "evidence.json").read_text()


def test_evaluator_source_edit_after_preflight_cannot_change_trial_route(tmp_path, monkeypatch):
    import subprocess

    from scripts import live_groq_fixture
    from scripts.pipeline_fixture import isolated_python

    submitted = []
    original_preflight = live_groq_fixture.preflight

    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server:
        target, evaluator = configurations(tmp_path, server.origin)

        def edit_after_preflight(*args, **kwargs):
            original_preflight(*args, **kwargs)
            evaluator.write_text(
                evaluator.read_text(encoding="utf-8").replace(
                    server.origin + "/evaluator", server.origin + "/mutated"
                ),
                encoding="utf-8",
            )

        monkeypatch.setattr(live_groq_fixture, "preflight", edit_after_preflight)

        def intercept_submission(*args, **kwargs):
            if "run" in args:
                submitted.append(Path(args[args.index("--evaluator") + 1]))
                return subprocess.CompletedProcess(args, 1, '{"ok":false}', "")
            return isolated_python(*args, **kwargs)

        monkeypatch.setattr(live_groq_fixture, "isolated_python", intercept_submission)
        result = run_workflow(
            target,
            evaluator,
            artifacts,
            environment=dict(os.environ, PIPELINE_KEY=KEY),
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
        )
        assert result["status"] == "failed"
        assert result["reason"] == "cli_failed"
        assert len(submitted) == 1
        assert submitted[0] == artifacts / "captured-evaluator.toml"
        assert server.origin + "/mutated" not in submitted[0].read_text(encoding="utf-8")
        assert server.origin + "/evaluator" in submitted[0].read_text(encoding="utf-8")
        assert result["cleanup"] == [{"daemon_stopped": True}]


@pytest.mark.parametrize("placement", ["comment", "parsed_value"])
def test_captured_config_rejects_embedded_credential_before_cli(tmp_path, monkeypatch, placement):
    from scripts import live_groq_fixture

    secret = 'synthetic"\\credential'

    def forbidden(*args, **kwargs):
        pytest.fail("Credential-bearing config reached CLI or HTTP", pytrace=False)

    monkeypatch.setattr(live_groq_fixture, "isolated_python", forbidden)
    monkeypatch.setattr(live_groq_fixture.httpx, "Client", forbidden)
    target, evaluator = configurations(tmp_path, "https://127.0.0.1:1")
    if placement == "comment":
        evaluator.write_text(
            evaluator.read_text(encoding="utf-8") + "\n# " + json.dumps(secret)[1:-1] + "\n",
            encoding="utf-8",
        )
    else:
        evaluator.write_text(
            evaluator.read_text(encoding="utf-8") + "\nlabel = " + json.dumps(secret) + "\n",
            encoding="utf-8",
        )
    artifacts = tmp_path / "evidence"
    result = run_workflow(
        target,
        evaluator,
        artifacts,
        environment={"PIPELINE_KEY": secret},
        controlled_ca=CERTIFICATES / "localhost-cert.pem",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "configuration_contains_credential"
    assert result["commands"] == result["preflights"] == []
    assert not (artifacts / "captured-evaluator.toml").exists()
    assert secret not in (artifacts / "evidence.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("opt_in,credential", [("", KEY), ("true", KEY), ("1", "")])
def test_missing_guard_has_no_process_or_http(tmp_path, monkeypatch, opt_in, credential):
    from scripts import live_groq_fixture

    def forbidden(*args, **kwargs):
        pytest.fail("Guard dispatched a process")

    monkeypatch.setattr(live_groq_fixture, "isolated_python", forbidden)
    with provider(tmp_path / "evidence" / "store", CERTIFICATES) as server:
        target, evaluator = configurations(tmp_path, server.origin)
        result = run_workflow(
            target,
            evaluator,
            tmp_path / "evidence",
            environment={
                "ASCLEPIUS_LIVE_TESTS": opt_in,
                "PIPELINE_KEY": credential,
            },
        )
        assert result["status"] == "not_run"
        assert result["commands"] == []
        assert server.preflights == server.calls == []


def test_preflight_401_fails_before_attack_and_is_not_retried(tmp_path):
    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES, fault="preflight_401") as server:
        target, evaluator = configurations(tmp_path, server.origin)
        result = run_workflow(
            target,
            evaluator,
            artifacts,
            environment=dict(os.environ, PIPELINE_KEY=KEY),
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
        )
        assert result["status"] == "failed"
        assert result["reason"] == "preflight_http_failure"
        assert result["preflights"][0]["http_status"] == 401
        assert len(server.preflights) == 1
        assert server.calls == []
        assert result["run_ids"] == []


def test_controlled_scope_cannot_access_hosted_origin(tmp_path):
    target, evaluator = configurations(tmp_path, "https://api.groq.com/openai/v1")
    result = run_workflow(
        target,
        evaluator,
        tmp_path / "evidence",
        environment={"PIPELINE_KEY": KEY},
        controlled_ca=CERTIFICATES / "localhost-cert.pem",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "controlled_loopback_required"
    assert result["commands"] == []


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_interrupted_poll_preserves_partial_run_and_cleanup(tmp_path, monkeypatch, cleanup_failure):
    import subprocess
    import time
    from types import SimpleNamespace

    from scripts import live_groq_fixture
    from scripts.pipeline_fixture import cli, isolated_python

    def interrupt(_seconds):
        raise KeyboardInterrupt

    def fail_stop(*args, **kwargs):
        if "stop" in args:
            return subprocess.CompletedProcess(args, 2, '{"ok":false}', "private diagnostic")
        return isolated_python(*args, **kwargs)

    monkeypatch.setattr(
        live_groq_fixture, "time", SimpleNamespace(monotonic=time.monotonic, sleep=interrupt)
    )
    if cleanup_failure:
        monkeypatch.setattr(live_groq_fixture, "isolated_python", fail_stop)
    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server:
        target, evaluator = configurations(tmp_path, server.origin)
        try:
            result = run_workflow(
                target,
                evaluator,
                artifacts,
                environment=dict(os.environ, PIPELINE_KEY=KEY),
                controlled_ca=CERTIFICATES / "localhost-cert.pem",
            )
            assert result["status"] == "failed"
            assert len(result["run_ids"]) == 1
            assert result["cleanup"] == [{"daemon_stopped": not cleanup_failure}]
            assert result["reason"] == (
                "daemon_cleanup_failed" if cleanup_failure else "workflow_interrupted_or_failed"
            )
            assert (artifacts / (result["run_ids"][0] + ".json")).is_file()
        finally:
            stopped = cli(artifacts / "store", "daemon", "stop")
            assert stopped["owned"] is False


def test_transient_stale_heartbeat_does_not_label_owned_daemon_stopped(tmp_path, monkeypatch):
    import subprocess
    import time
    from types import SimpleNamespace

    from scripts import live_groq_fixture
    from scripts.pipeline_fixture import isolated_python

    stale_status_seen = False

    def stale_status(*args, **kwargs):
        nonlocal stale_status_seen
        result = isolated_python(*args, **kwargs)
        if args[-2:] == ("daemon", "status") and not stale_status_seen:
            payload = json.loads(result.stdout)
            status = payload["data"]
            if status["owned"] and status["state"] == "ready":
                status.update(responsive=False, execution_available=False)
                stale_status_seen = True
                return subprocess.CompletedProcess(
                    args, result.returncode, json.dumps(payload), result.stderr
                )
        return result

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(live_groq_fixture, "isolated_python", stale_status)
    monkeypatch.setattr(
        live_groq_fixture, "time", SimpleNamespace(monotonic=time.monotonic, sleep=interrupt)
    )
    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server:
        target, evaluator = configurations(tmp_path, server.origin)
        result = run_workflow(
            target,
            evaluator,
            artifacts,
            environment=dict(os.environ, PIPELINE_KEY=KEY),
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
        )
        assert stale_status_seen
        assert result["status"] == "failed"
        assert result["reason"] == "workflow_interrupted_or_failed"
        assert len(result["run_ids"]) == 1
        assert result["cleanup"] == [{"daemon_stopped": True}]


def test_reflected_quoted_credentials_never_cross_evidence_boundary(tmp_path, monkeypatch):
    import json

    from scripts import pipeline_fixture

    secret = 'synthetic-quote"-backslash\\-credential'
    monkeypatch.setattr(pipeline_fixture, "KEY", secret)
    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server:
        original = server.respond

        def reflect(body, **kwargs):
            status, reply = original(body, **kwargs)
            if len(server.preflights) == 1:
                reply["model"] = secret + " " + json.dumps(secret)
                reply["id"] = json.dumps(json.dumps(secret))
                return status, reply
            return 401, {"error": secret + json.dumps(secret)}

        server.respond = reflect
        target, evaluator = configurations(tmp_path, server.origin)
        result = run_workflow(
            target,
            evaluator,
            artifacts,
            environment=dict(os.environ, PIPELINE_KEY=secret),
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
        )
        assert result["status"] == "failed"
        assert result["reason"] == "preflight_http_failure"
        assert result["preflights"][0]["model_mismatch"] is True
        retained = (artifacts / "evidence.json").read_text() + json.dumps(result)
        forms = [secret, json.dumps(secret)[1:-1], json.dumps(json.dumps(secret))[1:-1]]
        if any(value in retained for value in forms):
            pytest.fail("Credential crossed the evidence boundary", pytrace=False)
        assert "[REDACTED]" in retained
        assert len(server.preflights) == 2
        assert server.calls == []


@pytest.mark.parametrize(
    "missing_config,opt_in,expected_status,reason,exit_code",
    [
        (False, "", "not_run", "explicit_opt_in_missing", 2),
        (True, "", "not_run", "explicit_opt_in_missing", 2),
        (True, "1", "failed", "configuration_unreadable", 1),
    ],
)
def test_driver_not_run_outside_checkout_with_selected_interpreter(
    tmp_path, missing_config, opt_in, expected_status, reason, exit_code
):
    import json
    import subprocess
    import sys

    target, evaluator = configurations(tmp_path, "https://127.0.0.1:1")
    if missing_config:
        target = tmp_path / "missing-target.toml"
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_live_groq.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--target",
            str(target),
            "--evaluator",
            str(evaluator),
            "--python",
            sys.executable,
            "--artifacts",
            str(tmp_path / "evidence"),
        ],
        cwd=tmp_path,
        env=dict(os.environ, ASCLEPIUS_LIVE_TESTS=opt_in),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == exit_code
    assert json.loads(result.stdout) == {
        "status": expected_status,
        "reason": reason,
        "manual_semantic_review": "pending",
    }


@pytest.mark.parametrize("fault", ["redirect", "truncated", "identity", "strict_schema"])
def test_preflight_invalid_reply_stops_without_retry(tmp_path, fault):
    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server:
        original = server.respond

        def invalid(body, **kwargs):
            status, reply = original(body, **kwargs)
            if fault == "redirect":
                return 307, reply
            if fault == "truncated":
                reply["choices"][0]["finish_reason"] = "length"
            if fault == "identity":
                reply["model"] = ""
            if fault == "strict_schema" and "response_format" in body:
                reply["choices"][0]["message"]["content"] = '{"wrong":true}'
            return status, reply

        server.respond = invalid
        target, evaluator = configurations(tmp_path, server.origin)
        result = run_workflow(
            target,
            evaluator,
            artifacts,
            environment=dict(os.environ, PIPELINE_KEY=KEY),
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
        )
        assert result["status"] == "failed"
        assert (
            result["reason"]
            == {
                "redirect": "preflight_http_failure",
                "truncated": "preflight_incomplete",
                "identity": "preflight_identity_missing",
                "strict_schema": "preflight_schema_invalid",
            }[fault]
        )
        assert len(server.preflights) == (2 if fault == "strict_schema" else 1)
        assert server.calls == []


@pytest.mark.parametrize("failure", ["malformed_stdout", "timeout"])
def test_subprocess_failure_diagnostics_are_private(tmp_path, monkeypatch, failure):
    import json
    import subprocess

    from scripts import live_groq_fixture

    secret = 'synthetic-process-secret"\\'

    def broken(*arguments, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(secret, 1, output=secret, stderr=json.dumps(secret))
        return subprocess.CompletedProcess(arguments, 1, secret, json.dumps(secret))

    monkeypatch.setattr(live_groq_fixture, "isolated_python", broken)
    target, evaluator = configurations(tmp_path, "https://127.0.0.1:1")
    result = run_workflow(
        target,
        evaluator,
        tmp_path / "evidence",
        environment={"PIPELINE_KEY": secret},
        controlled_ca=CERTIFICATES / "localhost-cert.pem",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "cli_response_or_process_failure"
    retained = (tmp_path / "evidence" / "evidence.json").read_text() + json.dumps(result)
    if secret in retained or json.dumps(secret)[1:-1] in retained:
        pytest.fail("Process diagnostic disclosed credential", pytrace=False)


def test_interrupt_cancels_gated_run_before_daemon_stop(tmp_path, monkeypatch):
    import json
    import time
    from types import SimpleNamespace

    from scripts import live_groq_fixture
    from scripts.pipeline_fixture import cli, isolated_python

    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server, server.gate("selector") as gate:

        def interrupt(_seconds):
            assert gate.received.wait(10)
            raise KeyboardInterrupt

        def process(*args, **kwargs):
            result = isolated_python(*args, **kwargs)
            if "cancel" in args:
                assert result.returncode == 0
                gate.release.set()
            return result

        monkeypatch.setattr(
            live_groq_fixture, "time", SimpleNamespace(monotonic=time.monotonic, sleep=interrupt)
        )
        monkeypatch.setattr(live_groq_fixture, "isolated_python", process)
        target, evaluator = configurations(tmp_path, server.origin)
        try:
            result = run_workflow(
                target,
                evaluator,
                artifacts,
                environment=dict(os.environ, PIPELINE_KEY=KEY),
                controlled_ca=CERTIFICATES / "localhost-cert.pem",
            )
            assert result["status"] == "failed"
            assert result["cancelled_run_ids"] == result["run_ids"]
            assert len(result["run_ids"]) == 1
            assert result["cleanup"] == [{"daemon_stopped": True}]
            partial = json.loads((artifacts / (result["run_ids"][0] + ".json")).read_text())
            assert partial["state"] == "cancelled"
            assert [call["actor"] for call in server.calls] == ["selector"]
            assert cli(artifacts / "store", "daemon", "status")["owned"] is False
            assert [call["actor"] for call in server.calls] == ["selector"]
        finally:
            gate.release.set()
            for identity in result.get("run_ids", []):
                if cli(artifacts / "store", "runs", "show", identity)["state"] in {
                    "queued",
                    "running",
                }:
                    cli(artifacts / "store", "runs", "cancel", identity)
            cli(artifacts / "store", "daemon", "stop")


@pytest.mark.skipif(os.name != "posix", reason="Owned daemon SIGKILL regression is POSIX only")
def test_stopped_daemon_with_running_snapshot_fails_promptly(tmp_path, monkeypatch):
    import json
    import signal

    from scripts import live_groq_fixture
    from scripts.pipeline_fixture import cli, isolated_python

    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server, server.gate("selector") as gate:
        terminated = False

        def process(*args, **kwargs):
            nonlocal terminated
            result = isolated_python(*args, **kwargs)
            if not terminated and args[-3:-1] == ("runs", "show"):
                assert gate.received.wait(10)
                status = cli(artifacts / "store", "daemon", "status")
                assert status["owned"] and status["pid"]
                os.kill(status["pid"], signal.SIGKILL)
                terminated = True
                gate.release.set()
            return result

        monkeypatch.setattr(live_groq_fixture, "isolated_python", process)
        target, evaluator = configurations(tmp_path, server.origin)
        result = run_workflow(
            target,
            evaluator,
            artifacts,
            environment=dict(os.environ, PIPELINE_KEY=KEY),
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
        )
        assert terminated
        assert result["status"] == "failed"
        assert result["reason"] == "daemon_stopped_during_trial"
        assert len(result["run_ids"]) == 1
        assert result["cleanup"] == [{"daemon_stopped": True}]
        assert result["last_daemon_status"]["owned"] is False
        partial = json.loads((artifacts / (result["run_ids"][0] + ".json")).read_text())
        assert partial["state"] in {"running", "cancelled"}
        assert cli(artifacts / "store", "daemon", "status")["owned"] is False


def test_failed_report_export_never_publishes_raw_evidence(tmp_path, monkeypatch):
    import subprocess
    import tomllib

    from scripts import live_groq_fixture

    secret = 'ab"cd'
    artifacts = tmp_path / "evidence"
    target, evaluator = configurations(tmp_path, "https://127.0.0.1:1")
    target_config = tomllib.loads(target.read_text())
    evaluator_config = tomllib.loads(evaluator.read_text())
    limits = {
        "requests_per_minute": 10000,
        "run_timeout_seconds": 180,
        "request_timeout_seconds": 10,
        "target_calls": 100,
        "evaluator_calls": 220,
        "total_calls": 300,
        "completion_tokens": 500000,
    }
    profile = {"target": target_config["target"], "limits": limits}
    view = {
        "state": "completed",
        "progress": {},
        "snapshot": {"id": "trial", "profile": profile, "evaluator": evaluator_config},
    }
    staged = []
    stopped = []

    def fake_cli(*args, **kwargs):
        if args[0] == "-c":
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "executable": "fixture",
                        "import": "fixture",
                        "version": "3",
                        "prefix": "fixture",
                    }
                ),
                "",
            )
        command = args[args.index("--json") + 1 :]
        if command[0] == "report":
            path = Path(command[command.index("--output") + 1])
            staged.append(path)
            path.write_text("credential: ab&quot;cd and " + json.dumps(secret), encoding="utf-8")
            return subprocess.CompletedProcess(args, 1, '{"ok":false}', "")
        if command[:2] == ("config", "validate") or command[0] == "init":
            data = {}
        elif command[:2] == ("targets", "add"):
            data = {}
        elif command[:2] == ("targets", "show"):
            data = {"config": profile}
        elif command[:2] == ("daemon", "start"):
            data = {"owned": True, "execution_available": True, "instance_id": "daemon"}
        elif command[:2] == ("daemon", "stop"):
            stopped.append(True)
            data = {"owned": False}
        elif command[0] == "run":
            data = {"id": f"trial-{len([c for c in calls if c[0] == 'run'])}"}
        elif command[:2] == ("runs", "show"):
            data = dict(view, snapshot=dict(view["snapshot"], id=command[2]))
        elif command[0] == "compare":
            data = {"summaries": [{"run_id": identity} for identity in command[1:]]}
        else:
            pytest.fail(f"unexpected CLI command: {command}")
        calls.append(command)
        return subprocess.CompletedProcess(args, 0, json.dumps({"ok": True, "data": data}), "")

    calls = []
    monkeypatch.setattr(live_groq_fixture, "isolated_python", fake_cli)
    monkeypatch.setattr(live_groq_fixture, "preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_groq_fixture, "verify_trial", lambda *args: {"review_samples": []})
    result = run_workflow(
        target,
        evaluator,
        artifacts,
        environment={"PIPELINE_KEY": secret},
        controlled_ca=CERTIFICATES / "localhost-cert.pem",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "cli_failed"
    assert len(staged) == 1
    assert artifacts not in staged[0].parents
    assert not staged[0].exists()
    assert not staged[0].parent.exists()
    assert not (artifacts / "report.json").exists()
    assert secret not in (artifacts / "evidence.json").read_text(encoding="utf-8")
    assert result["cleanup"] == [{"daemon_stopped": True}, {"daemon_stopped": True}]
    assert len(stopped) == 2


def test_unicode_escaped_credential_in_preflight_model_is_redacted(tmp_path):
    import json

    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server:
        original = server.respond

        def reflect(body, **kwargs):
            status, reply = original(body, **kwargs)
            if len(server.preflights) == 1:
                reply["model"] = '{"credential":"' + "".join(f"\\u{ord(c):04x}" for c in KEY) + '"}'
                return status, reply
            return 401, {}

        server.respond = reflect
        target, evaluator = configurations(tmp_path, server.origin)
        result = run_workflow(
            target,
            evaluator,
            artifacts,
            environment=dict(os.environ, PIPELINE_KEY=KEY),
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
        )
        assert result["status"] == "failed"
        model = json.loads(result["preflights"][0]["reported_model"])
        if model["credential"] != "[REDACTED]":
            pytest.fail("Encoded credential survived preflight sanitization", pytrace=False)
        saved = json.loads((artifacts / "evidence.json").read_text())
        assert json.loads(saved["preflights"][0]["reported_model"])["credential"] == "[REDACTED]"
