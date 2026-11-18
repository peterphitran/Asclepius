import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

import asclepius


def wait_for_windows_exit(pid: int) -> None:
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 3000) == 0, "Stopped child has not exited."
        finally:
            kernel.CloseHandle(handle)


def main() -> None:
    assert "site-packages" in str(asclepius.__file__), "Install the built wheel first."
    examples = Path(sys.argv[1]).resolve()
    target_path = examples / "groq-target.toml"
    evaluator_path = examples / "groq-evaluator.toml"
    target = tomllib.loads(target_path.read_text(encoding="utf-8"))["target"]
    roles = tomllib.loads(evaluator_path.read_text(encoding="utf-8"))["roles"]
    environment = dict(os.environ)
    refs = {target["secret_ref"], *(role["secret_ref"] for role in roles.values())}
    synthetic = "ASCLEPIUS_SYNTHETIC_PROBE_KEY_NOT_A_CREDENTIAL"
    for reference in refs:
        environment[reference[4:]] = synthetic
    with tempfile.TemporaryDirectory(prefix="asclepius-daemon-probe-") as directory:

        def command(*arguments: str) -> dict:
            result = subprocess.run(
                [sys.executable, "-m", "asclepius", "--data-dir", directory, "--json", *arguments],
                capture_output=True,
                text=True,
                timeout=25,
                env=environment,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stderr == "", result.stderr
            assert synthetic not in result.stdout
            return json.loads(result.stdout)["data"]

        command("init")
        command("targets", "add", target["name"], "--config", str(target_path))
        started = command("daemon", "start")
        try:
            assert started["owned"] and started["responsive"]
            assert started["execution_available"] is True
            assert command("daemon", "start")["instance_id"] == started["instance_id"]
            accepted = command(
                "run",
                target["name"],
                "--plan",
                str(examples / "submission-plan.json"),
                "--evaluator",
                str(evaluator_path),
            )
            assert accepted["state"] == "queued"
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                view = command("runs", "show", accepted["id"])
                if view["state"] not in {"queued", "running"}:
                    break
                time.sleep(0.1)
            assert view["state"] == "failed" and view["reason"] == "plan_not_executable"
            assert view["observations"] == []
        finally:
            assert command("daemon", "stop")["owned"] is False
            wait_for_windows_exit(started["pid"])
        assert command("runs", "show", accepted["id"])["state"] == "failed"
    print(
        "Installed daemon CLI probe passed: ownership, duplicate start, queued submission, "
        "legacy-plan preflight failure, stop, and stopped reads. No provider requests."
    )


if __name__ == "__main__":
    main()
