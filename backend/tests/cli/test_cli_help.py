import json
import subprocess
import sys

import pytest


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "asclepius", *args], capture_output=True, text=True, timeout=10
    )


def test_module_help_does_not_need_api_database_or_credentials() -> None:
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "targets" in result.stdout
    assert "daemon" in result.stdout
    assert "report" in result.stdout


def test_unimplemented_command_does_not_claim_success() -> None:
    result = run_cli("daemon", "start", "--json")
    assert result.returncode == 5
    output = json.loads(result.stdout)
    assert output["schema_version"] == 1
    assert output["error"]["code"] == "not_implemented"


def test_bad_arguments_exit_two_without_traceback() -> None:
    result = run_cli("not-a-command")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("not-a-command",),
        ("config", "validate"),
        ("config", "validate", "unused.toml", "--kind", "invalid"),
    ],
)
def test_argument_errors_obey_json_contract(arguments: tuple[str, ...]) -> None:
    result = run_cli("--json", *arguments)
    assert result.returncode == 2
    assert result.stdout, "JSON mode must emit a structured error for invalid arguments"
    assert json.loads(result.stdout)["error"]["code"] == "arguments"
    assert result.stderr == ""
