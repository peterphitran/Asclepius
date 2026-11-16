import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from asclepius.config import load_daemon
from asclepius.domain import AppError, DaemonStatus
from asclepius.paths import local_directory
from asclepius.storage import Repository

WSL_DAEMON_WARNING = (
    "Warning: on WSL the daemon stops when WSL shuts down, which happens shortly after the "
    "last WSL terminal or session closes. Keep a WSL terminal open while runs are active."
)


def running_under_wsl() -> bool:
    """WSL stops its Linux side, detached processes included, soon after its last session ends."""
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


def daemon_status(data_dir: Path) -> DaemonStatus:
    return asyncio.run(Repository(data_dir).daemon_status())


def _wait_existing(directory: Path, timeout: float) -> DaemonStatus:
    deadline = time.monotonic() + timeout
    while True:
        status = daemon_status(directory)
        if status.owned and status.responsive and status.state in {"ready", "draining"}:
            return status
        if not status.owned or time.monotonic() >= deadline:
            raise AppError(
                "daemon_unresponsive",
                "The owner is not ready. Inspect daemon status; do not remove its lock.",
                4,
            )
        time.sleep(0.05)


def start_daemon(
    data_dir: Path, *, timeout: float = 15, config: Path | None = None
) -> DaemonStatus:
    directory = local_directory(data_dir)
    status = daemon_status(directory)
    if status.owned:
        return _wait_existing(directory, timeout)
    policy = load_daemon(config.resolve() if config else None)
    instance = str(uuid4())
    log_dir = directory / "logs"
    child = None
    try:
        log_dir.mkdir(exist_ok=True)
        with (log_dir / f"daemon-{instance}.log").open("ab") as log:
            options = (
                {"start_new_session": True}
                if os.name != "nt"
                else {
                    "creationflags": subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                }
            )
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "asclepius.daemon",
                    "--data-dir",
                    str(directory),
                    "--instance-id",
                    instance,
                    "--policy-json",
                    policy.model_dump_json(),
                ],
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                **options,
            )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = daemon_status(directory)
            if (
                str(status.instance_id) == instance
                and status.owned
                and status.responsive
                and status.state == "ready"
            ):
                return status
            if child.poll() is not None:
                if status.owned:
                    return _wait_existing(directory, max(0, deadline - time.monotonic()))
                raise AppError(
                    "daemon_start_failed",
                    f"Daemon exited with code {child.returncode} before readiness. "
                    "Inspect the instance log under the data directory.",
                    4,
                )
            time.sleep(0.05)
        raise AppError(
            "daemon_start_timeout",
            "Daemon startup did not become ready before the deadline. "
            "Inspect status; it may still be starting.",
            4,
        )
    except OSError:
        raise AppError(
            "daemon_start_failed", "Cannot launch the daemon or open its log.", 4
        ) from None


def stop_daemon(data_dir: Path, *, timeout: float = 15) -> DaemonStatus:
    directory = local_directory(data_dir)
    status = daemon_status(directory)
    if not status.owned:
        return status
    if not status.responsive or status.state not in {"ready", "draining"}:
        raise AppError(
            "daemon_unresponsive", "The owner is unresponsive. No process was killed.", 4
        )
    instance = status.instance_id
    asyncio.run(Repository(directory).request_stop(str(instance)))
    deadline = time.monotonic() + timeout
    while True:
        status = daemon_status(directory)
        if not status.owned or status.instance_id != instance:
            return status
        if time.monotonic() >= deadline:
            raise AppError("daemon_draining", "Daemon is still draining. No process was killed.", 4)
        time.sleep(0.05)
