import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import asclepius


def main() -> None:
    assert "site-packages" in str(asclepius.__file__), (
        "Install the wheel before running this probe."
    )
    config = Path(sys.argv[1]).resolve()
    name = tomllib.loads(config.read_text(encoding="utf-8"))["target"]["name"]
    with tempfile.TemporaryDirectory(prefix="asclepius-management-") as directory:

        def command(*arguments: str, expected: int = 0) -> dict:
            result = subprocess.run(
                [sys.executable, "-m", "asclepius", "--data-dir", directory, "--json", *arguments],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == expected, result.stdout + result.stderr
            assert result.stderr == "", result.stderr
            return json.loads(result.stdout)

        assert command("init")["data"]["initialized"] is True
        identity = command("targets", "add", name, "--config", str(config))["data"]["id"]
        duplicate = command("targets", "add", name, "--config", str(config), expected=2)
        assert duplicate["error"]["code"] == "conflict"
        records = command("targets", "list")["data"]
        assert [item["id"] for item in records["items"]] == [identity]
        assert records["next_cursor"] is None
        shown = command("targets", "show", identity)["data"]
        assert shown["config"]["target"]["name"] == name
        assert shown["revision"] == 1
        assert command("runs", "list")["data"]["items"] == []
        removed = command("targets", "remove", identity)["data"]
        assert removed == {"id": identity, "removed": True}
        assert command("targets", "show", identity, expected=3)["error"]["code"] == "not_found"
    print(
        "Installed wheel CLI management verified outside the source tree. "
        "No daemon or provider calls."
    )


if __name__ == "__main__":
    main()
