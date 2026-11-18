import subprocess
import sys


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "asclepius", *args], capture_output=True, text=True, timeout=10
    )


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
