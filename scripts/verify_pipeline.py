import argparse
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline_fixture import assert_complete, cli, configure, provider, wait_run

import asclepius


def proof(root, certificates):
    results = {}
    with provider(root / "store", certificates, delay=0.01) as server:
        directory, evaluator, targets, started = configure(
            root,
            server,
            certificates,
            aliases=("first", "second"),
            limits={"outbound_concurrency": 1},
        )
        second = root / "second-evaluator.toml"
        second.write_text(
            evaluator.read_text().replace('model = "fixture-', 'model = "second-'), encoding="utf-8"
        )
        target = targets["second"]
        target.write_text(
            target.read_text().replace("fixture-target", "second-target"), encoding="utf-8"
        )
        cli(directory, "targets", "edit", "second", "--config", target)
        try:

            def submit(item):
                alias, config = item
                return cli(
                    directory, "run", alias, "--pack", "broad-chat-v1", "--evaluator", config
                )["id"]

            with ThreadPoolExecutor(max_workers=2) as clients:
                identities = list(clients.map(submit, [("first", evaluator), ("second", second)]))
            views = [wait_run(directory, identity, timeout=150) for identity in identities]
            assert server.failures == [], server.failures
            for view in views:
                calls = [item for item in server.calls if item["run_id"] == view["snapshot"]["id"]]
                assert_complete(view, calls)
            assert server.running_max == 2
            assert server.max_active == 1
            sequence = [item["run_id"] for item in server.calls]
            switches = sum(a != b for a, b in zip(sequence, sequence[1:], strict=False))
            assert switches > 2
            results.update(
                {
                    "daemon_instance": started["instance_id"],
                    "runs": [
                        {
                            "id": view["snapshot"]["id"],
                            "state": view["state"],
                            "progress": view["progress"],
                            "observations": len(view["observations"]),
                        }
                        for view in views
                    ],
                    "maximum_running_rows": server.running_max,
                    "maximum_simultaneous_http": server.max_active,
                    "cross_run_switches": switches,
                    "received_requests": len(server.calls),
                    "prepared_intent_checks": len(server.calls),
                    "target_input_commit_checks": sum(
                        item["actor"] == "target" for item in server.calls
                    ),
                }
            )
        finally:
            assert cli(directory, "daemon", "stop")["owned"] is False
        assert all(
            cli(directory, "runs", "show", identity)["state"] == "completed"
            for identity in identities
        )
    for fault, reason in (("http", "provider_http_503"), ("invalid", "invalid_role_output")):
        fault_root = root / fault
        with provider(fault_root / "store", certificates, fault=fault) as server:
            directory, evaluator, _, _ = configure(fault_root, server, certificates)
            try:
                accepted = cli(
                    directory, "run", "fixture", "--pack", "broad-chat-v1", "--evaluator", evaluator
                )
                view = wait_run(directory, accepted["id"])
                assert view["state"] == "failed" and view["reason"] == reason
                assert len(view["observations"]) == len(server.calls)
                assert not any(item["state"] == "pending" for item in view["attempts"])
                assert len(view["findings"]) == (1 if fault == "http" else 0)
                assert server.failures == []
                results[fault] = {
                    "state": view["state"],
                    "reason": view["reason"],
                    "observations": len(view["observations"]),
                    "findings": len(view["findings"]),
                }
            finally:
                assert cli(directory, "daemon", "stop")["owned"] is False
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificates", type=Path, required=True)
    args = parser.parse_args()
    assert "site-packages" in Path(asclepius.__file__).parts, "Install the built wheel first."
    with tempfile.TemporaryDirectory(prefix="asclepius-pipeline-proof-") as directory:
        result = proof(Path(directory), args.certificates.resolve())
    print(
        json.dumps(
            {
                "import_location": str(asclepius.__file__),
                "python": sys.version,
                "proof": result,
                "scope": (
                    "Real CLI, detached daemon, verified loopback HTTPS, SQLite; "
                    "deterministic provider responses, no hosted models."
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
