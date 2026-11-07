import copy
import html
import json
from pathlib import Path

import pytest

from asclepius.domain import EvaluatorConfig, ProfileConfig
from scripts.live_groq_fixture import WorkflowFailure, preflight, probes, run_workflow, save
from scripts.pipeline_fixture import KEY, provider
from tests.cli.test_live_groq_driver import configurations

CERTIFICATES = Path(__file__).parent / "fixtures"
GPT_OSS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")
STRICT_PROMPT = 'Asclepius access preflight. Reply with only {"ok":true}.'


def specs(origin, model, cap=None):
    spec = {"model": model, "secret_ref": "env:PIPELINE_KEY", "base_url": origin}
    if cap is not None:
        spec["max_completion_tokens"] = cap
    return {"target": {"name": "fixture", **spec}}, {
        "roles": {role: dict(spec) for role in ("selector", "generator", "judge", "reporter")}
    }


def invoke(server, tmp_path, model=GPT_OSS[0], cap=None):
    report = {"preflights": []}
    items = probes(*specs(server.origin, model, cap))
    preflight(
        items,
        {"PIPELINE_KEY": KEY},
        report,
        lambda: save(tmp_path / "preflight.json", report, (KEY,)),
        ca_bundle=CERTIFICATES / "localhost-cert.pem",
    )
    return report


@pytest.mark.parametrize("model", GPT_OSS + ("fixture-other", "openai/gpt-oss-20b-suffix"))
@pytest.mark.parametrize("cap", [None, 17, 2048])
def test_effective_policy_in_actual_https_request(tmp_path, model, cap):
    with provider(tmp_path / "store", CERTIFICATES) as server:
        report = invoke(server, tmp_path, model, cap)
        ceiling = 512 if model in GPT_OSS else 64
        assert len(server.preflights) == 2
        for request, receipt in zip(server.preflights, report["preflights"], strict=True):
            assert request["max_completion_tokens"] == min(ceiling, cap or ceiling)
            assert receipt["max_completion_tokens"] == request["max_completion_tokens"]
            if model in GPT_OSS:
                assert request["reasoning_effort"] == receipt["reasoning_effort"] == "low"
            else:
                assert "reasoning_effort" not in request
            assert receipt["status"] == "succeeded"
        assert server.preflights[1]["messages"] == [{"role": "user", "content": STRICT_PROMPT}]
        assert server.calls == []


def test_policy_matches_raw_materialized_profile_and_snapshot_without_mutation():
    target, evaluator = specs("https://127.0.0.1:443", GPT_OSS[0])
    before = copy.deepcopy((target, evaluator))
    profile = ProfileConfig.model_validate(target).model_dump(mode="json")
    roles = EvaluatorConfig.model_validate(evaluator).model_dump(mode="json")
    snapshot = json.loads(json.dumps({"profile": profile, "evaluator": roles}))
    assert probes(target, evaluator) == probes(profile, evaluator)
    assert probes(target, evaluator) == probes(snapshot["profile"], snapshot["evaluator"])
    assert [p.max_tokens for p in probes(target, evaluator)] == [512, 512]
    assert (target, evaluator) == before
    assert profile["target"]["max_completion_tokens"] == 512
    assert roles["roles"]["selector"]["max_completion_tokens"] == 2048


def test_deduplication_preserves_distinct_effective_caps_in_order():
    target, evaluator = specs("https://127.0.0.1:443", GPT_OSS[0])
    for role, cap in zip(evaluator["roles"].values(), (512, 17, 2048, 17), strict=True):
        role["max_completion_tokens"] = cap
    items = probes(target, evaluator)
    assert [(item.strict, item.max_tokens) for item in items] == [
        (False, 512),
        (True, 512),
        (True, 17),
    ]
    assert len({item.identity for item in items}) == 3


def test_original_cutoff_retains_usage_and_stops_before_trials(tmp_path):
    artifacts = tmp_path / "evidence"
    with provider(artifacts / "store", CERTIFICATES) as server:
        original = server.respond

        def cutoff(body, **kwargs):
            status, reply = original(body, **kwargs)
            reply["id"] = "observed-cutoff"
            reply["model"] = GPT_OSS[0]
            reply["choices"][0].update(
                finish_reason="length", message={"content": "", "reasoning": "PRIVATE_REASONING"}
            )
            reply["usage"] = {
                "prompt_tokens": 82,
                "completion_tokens": 64,
                "total_tokens": 146,
                "completion_tokens_details": {"reasoning_tokens": 57},
            }
            return status, reply

        server.respond = cutoff
        target, evaluator = configurations(tmp_path, server.origin)
        target.write_text(
            target.read_text().replace(
                'model="fixture-target"', 'model="openai/gpt-oss-20b"\nmax_completion_tokens=64'
            )
        )
        report = run_workflow(
            target,
            evaluator,
            artifacts,
            environment={"PIPELINE_KEY": KEY},
            controlled_ca=CERTIFICATES / "localhost-cert.pem",
        )
        assert report["reason"] == "preflight_incomplete"
        assert report["trials"] == report["run_ids"] == []
        assert len(server.preflights) == 1
        assert server.calls == []
        entry = report["preflights"][0]
        assert entry["status"] == "failed"
        assert entry["finish_reason"] == "length"
        assert entry["response_id"] == "observed-cutoff"
        assert entry["reported_model"] == GPT_OSS[0]
        assert entry["usage"] == {
            "prompt_tokens": 82,
            "completion_tokens": 64,
            "total_tokens": 146,
            "completion_tokens_details": {"reasoning_tokens": 57},
        }
        saved = (artifacts / "evidence.json").read_text()
        assert json.loads(saved)["preflights"][0] == entry
        assert "PRIVATE_REASONING" not in saved


@pytest.mark.parametrize("fault", ["empty", "schema", "usage", "choices", "message", "root"])
def test_failure_projects_only_safe_metadata(tmp_path, monkeypatch, fault):
    from scripts import pipeline_fixture

    secret = 'synthetic-<credential>-"-\\'
    monkeypatch.setattr(pipeline_fixture, "KEY", secret)
    with provider(tmp_path / "store", CERTIFICATES) as server:
        original = server.respond

        def invalid(body, **kwargs):
            status, reply = original(body, **kwargs)
            reply["id"] = (
                secret
                + " "
                + html.escape(secret)
                + " "
                + "".join(f"\\u{ord(char):04x}" for char in secret)
            )
            reply["model"] = "nonsecret-provider-model"
            reply["usage"] = {
                "prompt_tokens": 82,
                "completion_tokens": False,
                "total_tokens": -1,
                "completion_tokens_details": [secret],
            }
            if fault != "usage":
                reply["usage"]["completion_tokens"] = 64
            if fault == "root":
                return status, [secret]
            if fault == "choices":
                reply["choices"] = {"secret": secret}
            elif fault == "message":
                reply["choices"][0]["message"] = [secret]
            elif fault == "empty":
                reply["choices"][0]["message"]["content"] = ""
            elif fault == "schema":
                reply["choices"][0]["message"]["content"] = '{"wrong":true}'
            return status, reply

        server.respond = invalid
        report = {"preflights": []}
        with pytest.raises(WorkflowFailure):
            preflight(
                probes(*specs(server.origin, GPT_OSS[0]))[1:],
                {"PIPELINE_KEY": secret},
                report,
                lambda: save(tmp_path / "failure.json", report, (secret,)),
                ca_bundle=CERTIFICATES / "localhost-cert.pem",
            )
        entry = json.loads((tmp_path / "failure.json").read_text())["preflights"][0]
        assert entry["status"] == "failed"
        assert len(server.preflights) == 1
        assert server.calls == []
        if fault != "root":
            assert entry["response_id"] == "[REDACTED] [REDACTED] [REDACTED]"
            assert entry["reported_model"] == "nonsecret-provider-model"
            assert entry["usage"] == (
                {"prompt_tokens": 82}
                if fault == "usage"
                else {"prompt_tokens": 82, "completion_tokens": 64}
            )


def test_false_boolean_remains_valid_strict_preflight(tmp_path):
    with provider(tmp_path / "store", CERTIFICATES) as server:
        original = server.respond

        def false_boolean(body, **kwargs):
            status, reply = original(body, **kwargs)
            reply["choices"][0]["message"]["content"] = '{"ok":false}'
            return status, reply

        server.respond = false_boolean
        assert all(e["status"] == "succeeded" for e in invoke(server, tmp_path)["preflights"])
