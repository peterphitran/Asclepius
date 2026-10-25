import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.pipeline_fixture import assert_complete, cli, configure, provider, wait_run


def test_two_cli_clients_share_daemon_global_and_account_bounds(tmp_path):
    certificates = Path(__file__).parent / "fixtures"
    with provider(tmp_path / "store", certificates, delay=0.01) as server:
        directory, evaluator, targets, _ = configure(
            tmp_path,
            server,
            certificates,
            aliases=("first", "second"),
            limits={"outbound_concurrency": 1},
        )
        second = tmp_path / "second-evaluator.toml"
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
            views = [wait_run(directory, identity, timeout=120) for identity in identities]
            assert server.failures == []
            for view in views:
                assert_complete(
                    view,
                    [item for item in server.calls if item["run_id"] == view["snapshot"]["id"]],
                )
            assert server.running_max == 2
            assert server.max_active == 1
            sequence = [item["run_id"] for item in server.calls]
            assert len([1 for a, b in zip(sequence, sequence[1:], strict=False) if a != b]) > 2
            with sqlite3.connect(directory / "asclepius.sqlite3") as connection:
                assert (
                    connection.execute(
                        "SELECT count(*) FROM budget_reservations WHERE state<>'settled'"
                    ).fetchone()[0]
                    == 0
                )
        finally:
            cli(directory, "daemon", "stop")
