"""The CLI must work with every legacy web-API dependency unavailable."""

import json
import subprocess
import sys
from pathlib import Path

LEGACY = (
    "fastapi",
    "uvicorn",
    "pydantic_settings",
    "sqlalchemy",
    "asyncpg",
    "alembic",
    "jwt",
    "bcrypt",
    "multipart",
    "redis",
    "app",
)

# Runs the CLI in a child interpreter whose import system refuses every legacy package.
BLOCKED_CLI = """
import importlib.abc, sys
blocked = set(sys.argv[1].split(","))
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in blocked:
            raise ImportError("legacy dependency blocked: " + name)
sys.meta_path.insert(0, Block())
import asclepius.coordinator, asclepius.daemon, asclepius.exports  # noqa: E401
from asclepius.cli import main
sys.exit(main(sys.argv[2:]))
"""


def blocked_cli(*arguments):
    return subprocess.run(
        [sys.executable, "-I", "-c", BLOCKED_CLI, ",".join(LEGACY), *map(str, arguments)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_help_profiles_and_history_need_no_legacy_dependency(tmp_path):
    example = Path(__file__).parents[2] / "examples" / "ollama-target.toml"
    data = tmp_path / "store"
    help_result = blocked_cli("--help")
    assert help_result.returncode == 0, help_result.stderr
    assert "usage" in help_result.stdout.lower()
    for arguments in (
        ("init",),
        ("targets", "add", "ollama-target", "--config", example),
        ("targets", "list"),
        ("runs", "list"),
    ):
        result = blocked_cli("--data-dir", data, "--json", *arguments)
        assert result.returncode == 0, (arguments, result.stdout, result.stderr)
        assert json.loads(result.stdout)["ok"] is True


def test_blocker_really_refuses_legacy_imports():
    probe = BLOCKED_CLI.split("import asclepius.coordinator")[0] + "import sqlalchemy\n"
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, ",".join(LEGACY)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "legacy dependency blocked: sqlalchemy" in result.stderr
