import json
import os
import sqlite3
import subprocess
import sys

import pytest

from asclepius.storage import Repository
from tests.cli.storage_fixtures import OWNER, run
from tests.cli.test_services import prompts


def cli(directory, *arguments, env=None):
    return subprocess.run(
        [sys.executable, "-m", "asclepius", "--data-dir", str(directory), "--json", *arguments],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def target_file(tmp_path, name="target"):
    path = tmp_path / f"{name}.toml"
    path.write_text(
        f'[target]\nname = "{name}"\nmodel = "test-target"\nsecret_ref = "env:CLI_TEST_KEY"\n',
        encoding="utf-8",
    )
    return path


def evaluator_file(tmp_path):
    path = tmp_path / "evaluator.toml"
    path.write_text(
        "\n".join(
            f'[roles.{role}]\nmodel = "test-evaluator"\nsecret_ref = "env:CLI_TEST_KEY"\n'
            for role in ("selector", "generator", "judge", "reporter")
        ),
        encoding="utf-8",
    )
    return path


def plan_file(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {
                        "id": "custom.boundary",
                        "version": "1",
                        "family": "test",
                        "objective": "Protect synthetic marker",
                        "system_prompt": "Protect marker",
                        "strategies": ["override"],
                        "benign_control": "Hello",
                        "rubric": "Observed marker only",
                    }
                ],
                "prompts": [prompt.model_dump(mode="json") for prompt in prompts()],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_real_cli_initializes_and_persists_profiles_across_clients(tmp_path):
    directory = tmp_path / "data"
    created = cli(directory, "init")
    assert created.returncode == 0, created.stdout + created.stderr
    config = target_file(tmp_path)
    added = cli(directory, "targets", "add", "target", "--config", str(config))
    assert added.returncode == 0, added.stdout + added.stderr
    identity = json.loads(added.stdout)["data"]["id"]
    listed = cli(directory, "targets", "list")
    assert listed.returncode == 0
    item = json.loads(listed.stdout)["data"]["items"][0]
    assert item["id"] == identity
    assert item["config"]["target"]["model"] == "test-target"
    duplicate = cli(directory, "targets", "add", "target", "--config", str(config))
    assert duplicate.returncode == 2
    other = target_file(tmp_path, "renamed")
    edited = cli(directory, "targets", "edit", identity, "--config", str(other))
    assert json.loads(edited.stdout)["data"]["id"] == identity
    assert json.loads(cli(directory, "targets", "show", "renamed").stdout)["data"]["revision"] == 2
    assert cli(directory, "targets", "remove", "renamed").returncode == 0
    assert cli(directory, "targets", "show", identity).returncode == 3


def test_cli_submission_stopped_then_controlled_ready_then_cancel_and_retry(tmp_path):
    directory = tmp_path / "data"
    assert cli(directory, "init").returncode == 0
    config, evaluator, plan = target_file(tmp_path), evaluator_file(tmp_path), plan_file(tmp_path)
    assert cli(directory, "targets", "add", "target", "--config", str(config)).returncode == 0
    env = {**os.environ, "CLI_TEST_KEY": "SYNTHETIC-KEY-NOT-PERSISTED"}
    args = ("run", "target", "--plan", str(plan), "--evaluator", str(evaluator))
    stopped = cli(directory, *args, env=env)
    assert stopped.returncode == 4
    assert json.loads(stopped.stdout)["error"]["code"] == "daemon_unavailable"
    repo = Repository(directory)
    assert run(repo.list_runs()).items == ()
    run(repo.set_ready(OWNER))
    accepted = cli(directory, *args, env=env)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    identity = json.loads(accepted.stdout)["data"]["id"]
    shown = cli(directory, "runs", "show", identity)
    assert json.loads(shown.stdout)["data"]["state"] == "queued"
    assert "SYNTHETIC-KEY-NOT-PERSISTED" not in shown.stdout
    assert json.loads(cli(directory, "runs", "list").stdout)["data"]["items"][0]["id"] == identity
    assert cli(directory, "runs", "cancel", identity).returncode == 0
    terminal_watch = cli(directory, "runs", "watch", identity)
    assert terminal_watch.returncode == 0
    records = [json.loads(line) for line in terminal_watch.stdout.splitlines()]
    assert records[-1]["data"]["state"] == "cancelled"
    run(repo.set_ready(OWNER))
    retried = cli(directory, "runs", "retry", identity, env=env)
    assert retried.returncode == 0, retried.stdout + retried.stderr
    retry_id = json.loads(retried.stdout)["data"]["id"]
    assert retry_id != identity
    assert str(run(repo.read_run(retry_id)).snapshot.source_run_id) == identity
    with sqlite3.connect(repo.database_path) as connection:
        connection.execute("UPDATE daemon_control SET state='stopped'")
    assert cli(directory, "runs", "show", identity).returncode == 0
    assert (
        json.loads(cli(directory, "findings", "list", "--run", identity).stdout)["data"]["items"]
        == []
    )


def test_cli_plan_validation_and_missing_resources_are_structured(tmp_path):
    directory = tmp_path / "data"
    assert cli(directory, "init").returncode == 0
    assert cli(directory, "targets", "show", "unknown").returncode == 3
    assert cli(directory, "runs", "show", "unknown").returncode == 3
    bad = tmp_path / "invalid.json"
    bad.write_text('{"secret": "MUST-NOT-ECHO"}', encoding="utf-8")
    result = cli(
        directory,
        "run",
        "unknown",
        "--plan",
        str(bad),
        "--evaluator",
        str(evaluator_file(tmp_path)),
    )
    assert result.returncode == 2
    assert "MUST-NOT-ECHO" not in result.stdout + result.stderr
    assert result.stderr == ""
    pack = cli(
        directory,
        "run",
        "unknown",
        "--pack",
        "broad-chat-v1",
        "--evaluator",
        str(evaluator_file(tmp_path)),
    )
    assert pack.returncode == 2
    assert json.loads(pack.stdout)["error"]["code"] == "pack_unavailable"


def test_two_concurrent_cli_clients_keep_distinct_profile_ids(tmp_path):
    directory = tmp_path / "data"
    assert cli(directory, "init").returncode == 0
    configs = [target_file(tmp_path, name) for name in ("one", "two")]
    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "asclepius",
                "--data-dir",
                str(directory),
                "--json",
                "targets",
                "add",
                config.stem,
                "--config",
                str(config),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for config in configs
    ]
    try:
        outputs = [child.communicate(timeout=15) for child in children]
        assert [child.returncode for child in children] == [0, 0], outputs
        identities = {json.loads(output[0])["data"]["id"] for output in outputs}
        assert len(identities) == 2
        items = json.loads(cli(directory, "targets", "list").stdout)["data"]["items"]
        assert {item["id"] for item in items} == identities
        assert {item["config"]["target"]["name"] for item in items} == {"one", "two"}
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


def test_watch_keyboard_interrupt_does_not_cancel_the_queued_run(tmp_path):
    from tests.cli.storage_fixtures import prepare

    repo, snapshot, _ = run(prepare(tmp_path, claim=False))
    script = (
        "import _thread, sys, threading; from asclepius.cli import main; "
        "timer=threading.Timer(0.5, _thread.interrupt_main); timer.start(); "
        "raise SystemExit(main(sys.argv[1:]))"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "--data-dir",
            str(tmp_path),
            "--json",
            "runs",
            "watch",
            str(snapshot.id),
        ],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 130, result.stdout + result.stderr
    view = run(repo.read_run(str(snapshot.id)))
    assert view.state.value == "queued"
    assert view.cancel_requested is False


def test_deeply_nested_plan_returns_structured_error_without_traceback(tmp_path):
    nested = tmp_path / "nested.json"
    nested.write_text("[" * 10000 + "0" + "]" * 10000, encoding="utf-8")
    result = cli(
        tmp_path / "data",
        "run",
        "any",
        "--plan",
        str(nested),
        "--evaluator",
        str(evaluator_file(tmp_path)),
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_plan"
    assert result.stderr == ""


def test_init_rejects_a_file_as_data_directory_with_structured_error(tmp_path):
    occupied = tmp_path / "occupied"
    occupied.write_text("preserve this file", encoding="utf-8")
    result = cli(occupied, "init")
    assert result.returncode == 5
    assert json.loads(result.stdout)["error"]["code"] == "storage_error"
    assert result.stderr == ""
    assert occupied.read_text(encoding="utf-8") == "preserve this file"


def test_remove_does_not_resolve_a_mutable_name_twice(tmp_path, monkeypatch, capsys):
    from asclepius.cli import main
    from asclepius.config import load_target
    from asclepius.domain import AppError

    repo = Repository(tmp_path / "data")
    run(repo.initialize())
    first = load_target(target_file(tmp_path, "first"))
    second = load_target(target_file(tmp_path, "second"))
    first_id, second_id = run(repo.save_profile(first)), run(repo.save_profile(second))
    original = Repository.get_profile

    async def concurrent_rename(self, identity):
        found = await original(self, identity)
        if identity == "first":
            renamed_first = first.model_copy(
                update={"target": first.target.model_copy(update={"name": "renamed"})}
            )
            renamed_second = second.model_copy(
                update={"target": second.target.model_copy(update={"name": "first"})}
            )
            await repo.save_profile(renamed_first, profile_id=first_id)
            await repo.save_profile(renamed_second, profile_id=second_id)
        return found

    monkeypatch.setattr(Repository, "get_profile", concurrent_rename)
    assert main(["--data-dir", str(repo.data_dir), "--json", "targets", "remove", "first"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["id"] == first_id
    with pytest.raises(AppError):
        run(original(repo, first_id))
    assert str(run(original(repo, second_id)).id) == second_id
