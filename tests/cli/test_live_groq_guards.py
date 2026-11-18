import os
from pathlib import Path

import pytest

from scripts.live_groq_fixture import run_workflow
from scripts.pipeline_fixture import KEY, provider
from tests.cli.live_groq_support import configurations

CERTIFICATES = Path(__file__).parent / "fixtures"


def test_distinct_paths_receive_preflights_and_exact_duplicates_collapse(tmp_path, monkeypatch):
    from scripts.live_groq_fixture import preflight, probes
    from scripts.pipeline_fixture import Handler

    paths = []
    original = Handler.do_POST

    def record_path(handler):
        paths.append(handler.path)
        return original(handler)

    monkeypatch.setattr(Handler, "do_POST", record_path)
    with provider(tmp_path / "store", CERTIFICATES) as server:
        spec = {"model": "same-model", "secret_ref": "env:PIPELINE_KEY"}
        target = {"target": dict(spec, base_url=server.origin + "/target")}
        evaluator = {
            "roles": {
                "selector": dict(spec, base_url=server.origin + "/first/v1"),
                "generator": dict(spec, base_url=server.origin + "/second/v1"),
                "judge": dict(spec, base_url=server.origin + "/first/v1/"),
            }
        }
        report = {"preflights": []}
        preflight(
            probes(target, evaluator),
            {"PIPELINE_KEY": KEY},
            report,
            lambda: None,
            ca_bundle=CERTIFICATES / "localhost-cert.pem",
        )
        assert paths == [
            "/target/chat/completions",
            "/first/v1/chat/completions",
            "/second/v1/chat/completions",
        ]
        assert len(report["preflights"]) == 3
        assert all(item["status"] == "succeeded" for item in report["preflights"])
        assert server.calls == []


@pytest.mark.parametrize("opt_in", ["", "true", "1"])
@pytest.mark.parametrize("configuration", ["missing", "malformed"])
def test_opt_in_precedes_configuration_read(tmp_path, monkeypatch, opt_in, configuration):
    from scripts import live_groq_fixture

    def forbidden(*args, **kwargs):
        pytest.fail("Guard dispatched CLI or HTTP")

    monkeypatch.setattr(live_groq_fixture, "isolated_python", forbidden)
    monkeypatch.setattr(live_groq_fixture.httpx, "Client", forbidden)
    target = tmp_path / "target.toml"
    if configuration == "malformed":
        target.write_text("[invalid")
    result = run_workflow(
        target,
        tmp_path / "missing-evaluator.toml",
        tmp_path / "evidence",
        environment={"ASCLEPIUS_LIVE_TESTS": opt_in},
    )
    assert result["status"] == ("failed" if opt_in == "1" else "not_run")
    assert result["reason"] == (
        "configuration_unreadable" if opt_in == "1" else "explicit_opt_in_missing"
    )
    assert result["commands"] == result["preflights"] == []


def test_pytest_live_guard_skips_before_missing_configuration(tmp_path, monkeypatch):
    import importlib.util

    path = Path(__file__).with_name("test_live_groq.py")
    spec = importlib.util.spec_from_file_location("guarded_live_scenario", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("ASCLEPIUS_LIVE_TESTS", "")
    monkeypatch.setenv("ASCLEPIUS_LIVE_TARGET", str(tmp_path / "missing.toml"))
    with pytest.raises(pytest.skip.Exception, match="explicit_opt_in_missing"):
        module.test_real_groq_two_full_broad_trials(tmp_path)


@pytest.mark.parametrize("port", ["", ":443", ":8443"])
def test_live_origin_port_boundary_without_remote_http(tmp_path, monkeypatch, port):
    from scripts import live_groq_fixture

    def forbidden(*args, **kwargs):
        raise live_groq_fixture.WorkflowFailure("preflight_intercepted_without_http")

    monkeypatch.setattr(live_groq_fixture, "preflight", forbidden)
    monkeypatch.setattr(live_groq_fixture.httpx, "Client", forbidden)
    target, evaluator = configurations(tmp_path, "https://api.groq.com" + port + "/openai/v1")
    target.write_text(target.read_text().split("[limits]")[0])
    result = run_workflow(
        target,
        evaluator,
        tmp_path / "evidence",
        environment=dict(os.environ, ASCLEPIUS_LIVE_TESTS="1", PIPELINE_KEY=KEY),
    )
    assert result["status"] == "failed"
    assert result["reason"] == (
        "live_groq_origin_required" if port == ":8443" else "preflight_intercepted_without_http"
    )
    assert result["preflights"] == result["run_ids"] == []


def test_caller_source_claim_does_not_verify_itself(tmp_path):
    claim = {"checkpoint": "nonexistent", "diff_sha256": "not-a-hash"}
    result = run_workflow(
        tmp_path / "missing",
        tmp_path / "missing",
        tmp_path / "evidence",
        environment={},
        source_identity=claim,
    )
    assert result["source_identity"] == {
        "verification": "unverified_caller_metadata",
        "claim": claim,
    }
    assert "source_checkpoint_and_diff_identity" in result["missing_proofs"]
    assert len(result["helper_sha256"]) == 64
