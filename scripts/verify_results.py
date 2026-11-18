import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from pipeline_fixture import (
    assert_complete,
    cli,
    cli_result,
    configure,
    isolated_python,
    provider,
    wait_run,
)

import asclepius
from asclepius.checks import load_pack_plan

HOSTILE = '<script>alert("report")</script>\n\n[click](https://evil.invalid)\n```\n# injected\n\x1b]8;;https://evil.invalid\x07x\x1b]8;;\x07\u202e'

HOSTILE_FAMILY = (
    'Family\r<script>alert("CR")</script>\r\n<script>alert("CRLF")</script>'
    "\x1b]8;;x\x07x\x1b]8;;\x07\u202e"
)


def logical_state(directory):
    with closing(sqlite3.connect(directory / "asclepius.sqlite3")) as connection:
        return "\n".join(connection.iterdump())


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def export_all(directory, identities, label, artifacts):
    paths = {}
    for format in ("json", "markdown", "html"):
        destination = artifacts / f"{label}.{format}"
        receipt = cli(directory, "report", *identities, "--format", format, "--output", destination)
        assert receipt == {"path": str(destination.resolve()), "format": format, "written": True}
        first = destination.read_bytes()
        refused = cli_result(
            directory, "report", *identities, "--format", format, "--output", destination
        )
        assert refused.returncode == 2
        assert refused.payload["error"]["code"] == "export_exists"
        assert destination.read_bytes() == first
        cli(
            directory,
            "report",
            *identities,
            "--format",
            format,
            "--output",
            destination,
            "--overwrite",
        )
        second = destination.read_text(encoding="utf-8")
        assert len(second) > 100
        if format == "json":
            document = json.loads(second)
            assert document["report_schema_version"] == 1
            assert [item["snapshot"]["id"] for item in document["runs"]] == identities
        paths[format] = str(destination)
    return paths


def assert_full_summary(summary):
    assert summary["attacks"] == {
        "generated": 60,
        "judged": 60,
        "weakness": 1,
        "passed": 58,
        "inconclusive": 1,
        "verdict_unknown": 0,
        "missing_judgment": 0,
        "findings": 1,
        "delivery": {"success": 60, "transport_error": 0, "unknown": 0, "unobserved": 0},
    }
    assert summary["controls"]["generated"] == summary["controls"]["answered"] == 20
    assert summary["target_usage"]["observations"] == 80
    assert summary["evaluator_usage"]["observations"] == 102
    assert summary["target_usage"]["input_tokens"] == 400
    assert summary["target_usage"]["output_tokens"] == 240
    assert summary["evaluator_usage"]["input_tokens"] == 510
    assert summary["evaluator_usage"]["output_tokens"] == 306
    assert summary["target_usage"]["truncated"] == 1


def stopped_reports(directory, server, groups, artifacts):
    before = logical_state(directory)
    receipts = list(server.calls)
    save_json(artifacts / "provider-receipts.json", receipts)
    (artifacts / "database-before.sql").write_text(before, encoding="utf-8")
    paths = {}
    for label, identities in groups.items():
        if len(identities) > 1:
            comparison = cli(directory, "compare", *identities)
            assert [item["run_id"] for item in comparison["summaries"]] == identities
        page = cli(directory, "findings", "list", "--run", identities[0], "--limit", 1)
        if page["items"]:
            detail = cli(directory, "findings", "show", page["items"][0]["id"])
            assert detail["run_id"] == identities[0]
        paths[label] = export_all(directory, identities, label, artifacts)
    after = logical_state(directory)
    (artifacts / "database-after.sql").write_text(after, encoding="utf-8")
    assert after == before, "Inspection changed saved state"
    assert server.calls == receipts, "Inspection made provider requests"
    assert server.failures == [], server.failures
    assert cli(directory, "daemon", "status")["owned"] is False
    return {
        "artifacts": paths,
        "provider_receipts": len(receipts),
        "logical_state_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "provider_calls_unchanged": True,
        "logical_state_unchanged": True,
        "daemon_stopped": True,
    }


def proof(root, certificates, artifacts):
    artifacts.mkdir(parents=True, exist_ok=False)
    normal_artifacts = artifacts / "normal"
    normal_artifacts.mkdir()
    with provider(root / "store", certificates) as server:
        directory, evaluator, targets, _ = configure(root, server, certificates)
        identities = {}
        try:
            target = targets["fixture"]
            target.write_text(
                target.read_text(encoding="utf-8").replace(
                    'system_prompt = "Frozen profile policy"',
                    "system_prompt = " + json.dumps(HOSTILE),
                ),
                encoding="utf-8",
            )
            cli(directory, "targets", "edit", "fixture", "--config", target)
            identities["completed"] = cli(
                directory, "run", "fixture", "--pack", "broad-chat-v1", "--evaluator", evaluator
            )["id"]
            complete = wait_run(directory, identities["completed"], timeout=150)
            assert_complete(
                complete,
                [call for call in server.calls if call["run_id"] == identities["completed"]],
            )
            with server.gate("selector") as gate:
                identities["empty"] = cli(
                    directory, "run", "fixture", "--pack", "broad-chat-v1", "--evaluator", evaluator
                )["id"]
                assert gate.received.wait(10)
                cli(directory, "runs", "cancel", identities["empty"])
            empty = wait_run(directory, identities["empty"])
            assert empty["state"] == "cancelled" and empty["variants"] == []
            plan = load_pack_plan("broad-chat-v1")
            plan = plan.model_copy(
                update={
                    "checks": (
                        plan.checks[0].model_copy(
                            update={"objective": HOSTILE, "family": HOSTILE_FAMILY}
                        ),
                    )
                }
            )
            plan_path = root / "one-check.json"
            plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
            identities["baseline"] = cli(
                directory, "run", "fixture", "--plan", plan_path, "--evaluator", evaluator
            )["id"]
            assert wait_run(directory, identities["baseline"])["state"] == "completed"
            target.write_text(
                target.read_text(encoding="utf-8").replace(
                    'model = "fixture-target"', 'model = "other-target"'
                ),
                encoding="utf-8",
            )
            cli(directory, "targets", "edit", "fixture", "--config", target)
            identities["model"] = cli(
                directory, "run", "fixture", "--plan", plan_path, "--evaluator", evaluator
            )["id"]
            assert wait_run(directory, identities["model"])["state"] == "completed"
            other_evaluator = root / "other-evaluator.toml"
            other_evaluator.write_text(
                evaluator.read_text(encoding="utf-8").replace("fixture-judge", "other-judge"),
                encoding="utf-8",
            )
            identities["evaluator"] = cli(
                directory, "run", "fixture", "--plan", plan_path, "--evaluator", other_evaluator
            )["id"]
            assert wait_run(directory, identities["evaluator"])["state"] == "completed"
            changed_plan = plan.model_copy(
                update={
                    "checks": (
                        plan.checks[0].model_copy(update={"rubric": "Changed pinned rubric"}),
                    )
                }
            )
            changed_path = root / "changed-check.json"
            changed_path.write_text(changed_plan.model_dump_json(), encoding="utf-8")
            identities["checks"] = cli(
                directory, "run", "fixture", "--plan", changed_path, "--evaluator", evaluator
            )["id"]
            assert wait_run(directory, identities["checks"])["state"] == "completed"
        finally:
            assert cli(directory, "daemon", "stop")["owned"] is False
        same = cli(directory, "compare", identities["completed"], identities["empty"])
        assert same["assessment"]["relation"] == "same_pinned_settings"
        assert_full_summary(same["summaries"][0])
        assert same["summaries"][1]["attacks"]["generated"] == 0
        assert same["summaries"][1]["requested_checks"] == 20
        cross = cli(directory, "compare", identities["baseline"], identities["model"])
        assert cross["assessment"]["relation"] == "cross_model"
        incompatible = cli(
            directory, "compare", identities["model"], identities["evaluator"], identities["checks"]
        )
        assert incompatible["assessment"]["relation"] == "incompatible"
        assert incompatible["assessment"]["checks_compatible"] is False
        findings = cli(
            directory, "findings", "list", "--run", identities["completed"], "--limit", 1
        )
        assert len(findings["items"]) == 1 and findings["next_cursor"] is None
        finding = cli(directory, "findings", "show", findings["items"][0]["id"])
        assert finding["judgment"]["id"] == finding["judgment_id"]
        assert finding["variant"]["id"] == finding["variant_id"]
        assert finding["observation"]["work_item_id"] == finding["variant_id"]
        assert finding["snapshot"]["id"] == identities["completed"]
        tail = cli(
            directory,
            "findings",
            "list",
            "--run",
            identities["completed"],
            "--cursor",
            finding["id"],
        )
        assert tail == {"items": [], "next_cursor": None}
        assert cli(directory, "findings", "list", "--run", identities["empty"])["items"] == []
        save_json(normal_artifacts / "comparison.json", same)
        save_json(normal_artifacts / "finding.json", finding)
        normal = stopped_reports(
            directory,
            server,
            {
                "completed": [identities["completed"]],
                "empty": [identities["empty"]],
                "same-settings": [identities["completed"], identities["empty"]],
                "cross-model": [identities["baseline"], identities["model"]],
                "incompatible": [
                    identities["model"],
                    identities["evaluator"],
                    identities["checks"],
                ],
            },
            normal_artifacts,
        )
        normal["run_ids"] = identities
        normal["full_summary"] = same["summaries"][0]
    fault_root = root / "partial"
    partial_artifacts = artifacts / "partial"
    partial_artifacts.mkdir()
    with provider(fault_root / "store", certificates, fault="http") as server:
        directory, evaluator, _, _ = configure(fault_root, server, certificates)
        try:
            identity = cli(
                directory, "run", "fixture", "--pack", "broad-chat-v1", "--evaluator", evaluator
            )["id"]
            partial_view = wait_run(directory, identity)
            assert partial_view["state"] == "failed"
            assert partial_view["reason"] == "provider_http_503"
            assert len(partial_view["observations"]) == len(server.calls)
        finally:
            assert cli(directory, "daemon", "stop")["owned"] is False
        partial = stopped_reports(directory, server, {"partial": [identity]}, partial_artifacts)
        partial["run_id"] = identity
        document = json.loads(
            Path(partial["artifacts"]["partial"]["json"]).read_text(encoding="utf-8")
        )
        summary = document["summaries"][0]
        assert summary["partial"] is True
        assert summary["attacks"]["delivery"]["transport_error"] == 1
        assert summary["attacks"]["missing_judgment"] >= 1
        partial["summary"] = summary
    return {
        "normal": normal,
        "partial": partial,
        "owned_daemons_stopped": True,
        "provider_servers_closed": True,
        "sqlite_connections_closed": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificates", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    location = Path(asclepius.__file__).resolve()
    assert "site-packages" in location.parts, "Install the built wheel first."
    assert location.is_relative_to(Path(sys.prefix).resolve()), (
        "Import must belong to this environment."
    )
    child = isolated_python("-c", "import asclepius; print(asclepius.__file__)")
    assert child.returncode == 0, child.stderr
    child_location = Path(child.stdout.strip()).resolve()
    assert child_location == location, "CLI child must use the checked installed package."
    with tempfile.TemporaryDirectory(prefix="asclepius-results-proof-") as directory:
        result = proof(Path(directory), args.certificates.resolve(), args.artifacts.resolve())
    payload = {
        "import_location": str(location),
        "child_import_location": str(child_location),
        "python": sys.version,
        "prefix": sys.prefix,
        "proof": result,
        "temporary_stores_removed": True,
        "scope": "Public CLI, daemon, verified loopback HTTPS and SQLite. No hosted models.",
    }
    if args.output:
        save_json(args.output, payload)
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
